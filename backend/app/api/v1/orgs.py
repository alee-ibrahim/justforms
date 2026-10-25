"""Organisations and memberships (DESIGN sections 7 and 17).

An organisation always keeps at least one admin: the last one can't be demoted or removed
(``409 last_admin``). Removing someone also removes their roles on the organisation's forms.

``GET /orgs/{id}/members/search`` suggests members as someone types a name or email
(docs/ux/PEOPLE-SCREENS.md 6.2): for org admins, and for a form's owners with ``form_id`` (then
each match says what access they already have on that form). Only this organisation's members
are ever returned.
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import EmailStr, Field, StringConstraints
from sqlalchemy import String, case, cast, func, select

from app.api.v1.common import ApiModel
from app.auth.deps import CurrentUser, DbDep, RedisDep, SettingsDep
from app.models import (
    FormPermission,
    FormRecord,
    FormRole,
    Organization,
    OrgMembership,
    OrgRole,
    User,
)
from app.permissions import OrgAdmin, OrgMember, effective_form_role, org_role
from app.ratelimit import enforce
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


class MemberMatch(ApiModel):
    """A member suggested while typing (``/members/search``)."""

    user_id: uuid.UUID
    email: str
    display_name: str
    role: OrgRole
    initials: str
    # With ``form_id``: the role they already have on that form (organisation admins are owners).
    form_role: FormRole | None = None


# Accent folding without the unaccent extension: common Latin letters with diacritics.
_FOLD_PAIRS = (
    ("àáâãäåāăą", "a"),
    ("çćč", "c"),
    ("ďđ", "d"),
    ("èéêëēėęě", "e"),
    ("ìíîïīįı", "i"),
    ("ł", "l"),
    ("ñńň", "n"),
    ("òóôõöøōő", "o"),
    ("ř", "r"),
    ("śšş", "s"),
    ("ť", "t"),
    ("ùúûüūůűų", "u"),
    ("ýÿ", "y"),
    ("žźż", "z"),
)
_FROM = "".join(chars for chars, _ in _FOLD_PAIRS)
_TO = "".join(plain * len(chars) for chars, plain in _FOLD_PAIRS)
_FOLD = str.maketrans(_FROM, _TO)


def fold(text: str) -> str:
    """Lower case, common accents removed (the same folding the search query applies)."""
    return text.lower().translate(_FOLD)


def _folded(column: Any) -> Any:
    return func.translate(func.lower(cast(column, String)), _FROM, _TO)


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def initials(display_name: str, email: str) -> str:
    parts = [p for p in re.split(r"[\s@._-]+", display_name.strip() or email) if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


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


@router.get("/orgs/{org_id}/members/search", response_model=list[MemberMatch])
async def search_members(
    org_id: uuid.UUID,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    user: CurrentUser,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
    form_id: uuid.UUID | None = None,
) -> list[MemberMatch]:
    """Members whose name or email matches ``q`` (case and common accents ignored): exact
    matches first, then names or emails starting with it, then words starting with it, then
    anywhere. Org admins may search; a form's owners may too, for that form (``form_id``)."""
    role = await org_role(db, user, org_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "org_not_found")
    if form_id is not None:
        form = await db.get(FormRecord, form_id)
        form_role = (
            await effective_form_role(db, user, form)
            if form is not None and form.deleted_at is None and form.org_id == org_id
            else None
        )
        if form_role is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "form_not_found")
        if form_role != FormRole.OWNER:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_form_role")
    elif role != OrgRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_org_role")
    await enforce(redis, settings, "member_search", str(user.id))

    term = fold(q.strip())
    if len(term) < 2:
        return []
    like = _like(term)
    name, email = _folded(User.display_name), _folded(User.email)
    rank = case(
        ((name == term) | (email == term), 0),
        (name.like(f"{like}%", escape="\\") | email.like(f"{like}%", escape="\\"), 1),
        (name.like(f"% {like}%", escape="\\"), 2),
        else_=3,
    )
    # Without a form the join matches nothing (form ids are never null): form_role stays None.
    query = (
        select(User, OrgMembership.role, FormPermission.role)
        .join(OrgMembership, OrgMembership.user_id == User.id)
        .outerjoin(
            FormPermission,
            (FormPermission.user_id == User.id) & (FormPermission.form_id == form_id),
        )
        .where(
            OrgMembership.org_id == org_id,
            name.like(f"%{like}%", escape="\\") | email.like(f"%{like}%", escape="\\"),
        )
        .order_by(rank, func.lower(User.display_name), User.email)
        .limit(limit)
    )
    out = []
    for u, member_role, granted in (await db.execute(query)).all():
        out.append(
            MemberMatch(
                user_id=u.id,
                email=u.email,
                display_name=u.display_name,
                role=member_role,
                initials=initials(u.display_name, u.email),
                form_role=FormRole.OWNER if form_id and member_role == OrgRole.ADMIN else granted,
            )
        )
    return out


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
