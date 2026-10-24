"""Per-form roles (DESIGN 7): who can open a form, and as what.

``GET /forms/{id}/permissions`` lists explicit grants plus the organisation admins (implicit
owners); any role on the form may read it. ``PUT`` replaces the explicit grants (owners only).
Only existing members of the form's organisation can be granted a role, and a form always
keeps at least one explicit owner.

Someone outside the organisation can be invited and given the form role in one step
(``POST .../permissions/invite``): only organisation admins may invite, because it brings
the person into the whole organisation (docs/ux/PEOPLE-SCREENS.md 6). Their pending access is
listed under ``pending`` until they accept.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import EmailStr, Field
from sqlalchemy import delete, select

from app.api.v1.common import ApiModel
from app.api.v1.people import limit_invites, send_invitation
from app.auth.deps import DbDep, RedisDep, SettingsDep
from app.models import (
    FormPermission,
    FormRole,
    InvitationStatus,
    Organization,
    OrgInvitation,
    OrgMembership,
    OrgRole,
    User,
)
from app.net import client_ip
from app.permissions import FormAccess, FormOwner, FormViewer, org_role
from app.queue import QueueDep
from app.services import invitations
from app.services.users import audit, normalize_email

router = APIRouter(tags=["access"])


class AccessEntry(ApiModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: FormRole
    # Org admins act as owners on every form and cannot be edited here.
    org_admin: bool = False


class PendingEntry(ApiModel):
    """Someone invited to the organisation who gets ``role`` on this form when they accept."""

    invitation_id: uuid.UUID
    email: str
    role: FormRole
    expired: bool


class AccessList(ApiModel):
    entries: list[AccessEntry]
    pending: list[PendingEntry] = Field(default_factory=list)
    can_manage: bool
    # Owners who are also organisation admins can invite people from outside.
    can_invite: bool = False
    org_name: str = ""


class InviteGrant(ApiModel):
    email: EmailStr
    role: FormRole


class Grant(ApiModel):
    email: EmailStr
    role: FormRole


class AccessPut(ApiModel):
    grants: Annotated[list[Grant], Field(max_length=500)]


async def _list(db: DbDep, form_id: uuid.UUID, org_id: uuid.UUID) -> list[AccessEntry]:
    admins = (
        (
            await db.execute(
                select(User)
                .join(OrgMembership, OrgMembership.user_id == User.id)
                .where(OrgMembership.org_id == org_id, OrgMembership.role == OrgRole.ADMIN)
                .order_by(User.email)
            )
        )
        .scalars()
        .all()
    )
    admin_ids = {u.id for u in admins}
    grants = (
        await db.execute(
            select(User, FormPermission.role)
            .join(FormPermission, FormPermission.user_id == User.id)
            .where(FormPermission.form_id == form_id)
            .order_by(User.email)
        )
    ).all()
    out = [
        AccessEntry(
            user_id=u.id,
            email=u.email,
            display_name=u.display_name,
            role=FormRole.OWNER,
            org_admin=True,
        )
        for u in admins
    ]
    out += [
        AccessEntry(user_id=u.id, email=u.email, display_name=u.display_name, role=role)
        for u, role in grants
        if u.id not in admin_ids
    ]
    return out


async def _pending(db: DbDep, form_id: uuid.UUID, org_id: uuid.UUID) -> list[PendingEntry]:
    rows = await db.scalars(
        select(OrgInvitation)
        .where(
            OrgInvitation.org_id == org_id,
            OrgInvitation.status == InvitationStatus.PENDING,
            OrgInvitation.form_grants.contains([{"formId": str(form_id)}]),
        )
        .order_by(OrgInvitation.email)
    )
    out = []
    for inv in rows:
        grant = next(g for g in inv.form_grants if g.get("formId") == str(form_id))
        out.append(
            PendingEntry(
                invitation_id=inv.id,
                email=inv.email,
                role=FormRole(grant["role"]),
                expired=not invitations.is_open(inv),
            )
        )
    return out


async def access_list(db: DbDep, access: FormAccess) -> AccessList:
    form = access.form
    org = await db.get(Organization, form.org_id)
    owner = access.role == FormRole.OWNER
    return AccessList(
        entries=await _list(db, form.id, form.org_id),
        pending=await _pending(db, form.id, form.org_id),
        can_manage=owner,
        can_invite=owner and await org_role(db, access.user, form.org_id) == OrgRole.ADMIN,
        org_name=org.name if org else "",
    )


@router.get("/forms/{form_id}/permissions", response_model=AccessList)
async def get_access(db: DbDep, access: FormViewer) -> AccessList:
    return await access_list(db, access)


@router.put("/forms/{form_id}/permissions", response_model=AccessList)
async def put_access(body: AccessPut, db: DbDep, access: FormOwner) -> AccessList:
    form = access.form
    wanted: dict[uuid.UUID, FormRole] = {}
    for g in body.grants:
        email = normalize_email(str(g.email))
        user = await db.scalar(
            select(User)
            .join(OrgMembership, OrgMembership.user_id == User.id)
            .where(User.email == email, OrgMembership.org_id == form.org_id)
        )
        if user is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "not_a_member", "email": email},
            )
        wanted[user.id] = g.role
    admins = set(
        (
            await db.scalars(
                select(OrgMembership.user_id).where(
                    OrgMembership.org_id == form.org_id, OrgMembership.role == OrgRole.ADMIN
                )
            )
        ).all()
    )
    current = (
        await db.scalars(select(FormPermission).where(FormPermission.form_id == form.id))
    ).all()
    before = {p.user_id: p.role for p in current}
    # Org admins are listed as implicit owners and not edited here; keep their own grants.
    for p in current:
        if p.user_id in admins and p.user_id not in wanted:
            wanted[p.user_id] = p.role
    if FormRole.OWNER not in wanted.values() and not admins:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, {"code": "owner_required"})
    await db.execute(delete(FormPermission).where(FormPermission.form_id == form.id))
    for user_id, role in wanted.items():
        db.add(FormPermission(form_id=form.id, user_id=user_id, role=role))
    await audit(
        db,
        "form.permissions",
        org_id=form.org_id,
        actor_id=access.user.id,
        target_type="form",
        target_id=form.id,
        meta={
            "before": {str(k): v.value for k, v in before.items()},
            "after": {str(k): v.value for k, v in wanted.items()},
        },
    )
    await db.commit()
    return await access_list(db, access)


@router.post("/forms/{form_id}/permissions/invite", response_model=AccessList)
async def invite_and_share(
    body: InviteGrant,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    queue: QueueDep,
    access: FormOwner,
) -> AccessList:
    """Invite someone from outside the organisation as a member, with ``role`` on this form
    once they accept (added to their pending invitation if they already have one)."""
    form = access.form
    if await org_role(db, access.user, form.org_id) != OrgRole.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invite_requires_admin")
    org = await db.get(Organization, form.org_id)
    assert org is not None
    await limit_invites(redis, settings, access.user, org.id, 1)
    result = await invitations.invite(
        db,
        settings,
        org,
        access.user,
        str(body.email),
        OrgRole.MEMBER,
        form_grant=(form.id, body.role),
        ip=client_ip(request, settings),
    )
    if result.invitation is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_member")
    await db.commit()
    await send_invitation(queue, result.invitation)
    return await access_list(db, access)


@router.delete(
    "/forms/{form_id}/permissions/invitations/{invitation_id}", response_model=AccessList
)
async def remove_pending(invitation_id: uuid.UUID, db: DbDep, access: FormOwner) -> AccessList:
    """Take this form out of a pending invitation (the invitation itself stays)."""
    inv = await db.get(OrgInvitation, invitation_id)
    if (
        inv is None
        or inv.org_id != access.form.org_id
        or inv.status != InvitationStatus.PENDING
        or not invitations.drop_grant(inv, access.form.id)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invitation_not_found")
    await audit(
        db,
        "form.permissions_invite_remove",
        org_id=access.form.org_id,
        actor_id=access.user.id,
        target_type="form",
        target_id=access.form.id,
        meta={"invitation_id": str(inv.id), "email": inv.email},
    )
    await db.commit()
    return await access_list(db, access)
