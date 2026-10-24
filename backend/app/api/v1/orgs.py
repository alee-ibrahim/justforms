"""Organisations and memberships (DESIGN sections 7 and 17).

An organisation always keeps at least one admin: the last one can't be demoted or removed
(``409 last_admin``). Removing someone also removes their roles on the organisation's forms.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import EmailStr, Field, StringConstraints
from sqlalchemy import select

from app.api.v1.common import ApiModel
from app.auth.deps import CurrentUser, DbDep
from app.models import Organization, OrgMembership, OrgRole, User
from app.permissions import OrgAdmin, OrgMember
from app.services.invitations import admin_count, revoke_form_grants
from app.services.users import audit, get_user_by_email, normalize_email, set_membership

router = APIRouter(tags=["orgs"])

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")]


class OrgOut(ApiModel):
    id: uuid.UUID
    name: str
    slug: str


class OrgCreate(ApiModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)]
    slug: Slug


class OrgPatch(ApiModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)]


class MemberOut(ApiModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: OrgRole


class MemberAdd(ApiModel):
    email: EmailStr
    display_name: Annotated[str, Field(max_length=200)] = ""
    role: OrgRole = OrgRole.MEMBER


class MemberPatch(ApiModel):
    role: OrgRole


@router.get("/orgs", response_model=list[OrgOut])
async def list_orgs(db: DbDep, user: CurrentUser) -> list[Organization]:
    query = select(Organization).order_by(Organization.name)
    if not user.is_superadmin:
        query = query.join(OrgMembership, OrgMembership.org_id == Organization.id).where(
            OrgMembership.user_id == user.id
        )
    return list((await db.execute(query)).scalars())


@router.post("/orgs", response_model=OrgOut, status_code=status.HTTP_201_CREATED)
async def create_org(body: OrgCreate, db: DbDep, user: CurrentUser) -> Organization:
    if not user.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "superadmin_required")
    if await db.scalar(select(Organization).where(Organization.slug == body.slug)):
        raise HTTPException(status.HTTP_409_CONFLICT, "slug_taken")
    org = Organization(name=body.name, slug=body.slug)
    db.add(org)
    await db.flush()
    await set_membership(db, org, user, OrgRole.ADMIN)
    await audit(
        db, "org.create", org_id=org.id, actor_id=user.id, target_type="org", target_id=org.id
    )
    await db.commit()
    return org


@router.get("/orgs/{org_id}", response_model=OrgOut)
async def get_org(org_id: uuid.UUID, db: DbDep, _: OrgMember) -> Organization:
    org = await db.get(Organization, org_id)
    assert org is not None
    return org


@router.patch("/orgs/{org_id}", response_model=OrgOut)
async def patch_org(
    org_id: uuid.UUID, body: OrgPatch, db: DbDep, user: CurrentUser, _: OrgAdmin
) -> Organization:
    org = await db.get(Organization, org_id)
    assert org is not None
    org.name = body.name
    await audit(
        db, "org.update", org_id=org.id, actor_id=user.id, target_type="org", target_id=org.id
    )
    await db.commit()
    return org


@router.get("/orgs/{org_id}/members", response_model=list[MemberOut])
async def list_members(org_id: uuid.UUID, db: DbDep, _: OrgAdmin) -> list[MemberOut]:
    rows = await db.execute(
        select(User, OrgMembership.role)
        .join(OrgMembership, OrgMembership.user_id == User.id)
        .where(OrgMembership.org_id == org_id)
        .order_by(User.email)
    )
    return [
        MemberOut(user_id=u.id, email=u.email, display_name=u.display_name, role=r)
        for u, r in rows.all()
    ]


@router.post(
    "/orgs/{org_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED
)
async def add_member(
    org_id: uuid.UUID, body: MemberAdd, db: DbDep, user: CurrentUser, _: OrgAdmin
) -> MemberOut:
    org = await db.get(Organization, org_id)
    assert org is not None
    member = await get_user_by_email(db, body.email)
    if member is None:
        member = User(email=normalize_email(body.email), display_name=body.display_name)
        db.add(member)
        await db.flush()
    await set_membership(db, org, member, body.role)
    await audit(
        db,
        "org.member_add",
        org_id=org.id,
        actor_id=user.id,
        target_type="user",
        target_id=member.id,
        meta={"role": body.role.value},
    )
    await db.commit()
    return MemberOut(
        user_id=member.id, email=member.email, display_name=member.display_name, role=body.role
    )


@router.patch("/orgs/{org_id}/members/{user_id}", response_model=MemberOut)
async def patch_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberPatch,
    db: DbDep,
    user: CurrentUser,
    _: OrgAdmin,
) -> MemberOut:
    membership = await db.get(OrgMembership, (org_id, user_id), with_for_update=True)
    member = await db.get(User, user_id)
    if membership is None or member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "member_not_found")
    before = membership.role
    if (
        before == OrgRole.ADMIN
        and body.role != OrgRole.ADMIN
        and await admin_count(db, org_id) <= 1
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "last_admin")
    membership.role = body.role
    await audit(
        db,
        "org.member_role",
        org_id=org_id,
        actor_id=user.id,
        target_type="user",
        target_id=user_id,
        meta={"before": before.value, "role": body.role.value},
    )
    await db.commit()
    return MemberOut(
        user_id=member.id, email=member.email, display_name=member.display_name, role=body.role
    )


@router.delete("/orgs/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    org_id: uuid.UUID, user_id: uuid.UUID, db: DbDep, user: CurrentUser, _: OrgAdmin
) -> Response:
    membership = await db.get(OrgMembership, (org_id, user_id), with_for_update=True)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "member_not_found")
    if membership.role == OrgRole.ADMIN and await admin_count(db, org_id) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "last_admin")
    await db.delete(membership)
    # Leaving the organisation also ends access to its forms (DESIGN 7).
    revoked = await revoke_form_grants(db, org_id, user_id)
    await audit(
        db,
        "org.member_remove",
        org_id=org_id,
        actor_id=user.id,
        target_type="user",
        target_id=user_id,
        meta={"role": membership.role.value, "forms_revoked": revoked},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
