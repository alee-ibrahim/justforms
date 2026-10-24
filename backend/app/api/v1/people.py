"""People in an organisation and invitations to join it (docs/ux/PEOPLE-SCREENS.md, DESIGN 7).

Org admins (and superadmins, in any organisation) list members and pending invitations,
invite by email, change roles, resend or cancel invitations. Member role changes and removal
live in ``orgs.py`` (``/orgs/{id}/members/{user_id}``). The invitation link page and accepting
an invitation while signed in are at the bottom.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import EmailStr, Field
from sqlalchemy import select

from app.api.v1.auth import Me, build_me
from app.api.v1.common import ApiModel
from app.auth.deps import CurrentUser, DbDep, RedisDep, SettingsDep
from app.models import (
    InvitationStatus,
    InviteEmailStatus,
    Organization,
    OrgInvitation,
    OrgMembership,
    OrgRole,
    User,
)
from app.net import client_ip
from app.permissions import OrgAdmin
from app.queue import JobQueue, QueueDep
from app.ratelimit import enforce, per_ip, take, too_many
from app.services import invitations as svc
from app.services.users import audit

router = APIRouter(tags=["people"])
public = APIRouter(prefix="/public", tags=["people"])

PersonStatus = Literal["active", "never_signed_in"]
InviteState = Literal["invited", "expired", "email_failed"]


class PersonOut(ApiModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: OrgRole
    status: PersonStatus
    last_login_at: datetime | None
    # Forms (not deleted) in this organisation the person has a role on.
    form_count: int
    # The role comes from OIDC sign-in groups and is set again at each sign-in.
    managed_by_groups: bool
    is_superadmin: bool


class InvitationOut(ApiModel):
    id: uuid.UUID
    email: str
    role: OrgRole
    state: InviteState
    expires_at: datetime
    created_at: datetime
    sent_at: datetime | None
    email_error: str | None
    invited_by_name: str | None
    form_count: int


class PeopleOut(ApiModel):
    org_id: uuid.UUID
    org_name: str
    members: list[PersonOut]
    invitations: list[InvitationOut]
    admin_count: int
    invite_days: int


class InviteIn(ApiModel):
    emails: Annotated[list[EmailStr], Field(min_length=1, max_length=svc.MAX_PER_REQUEST)]
    role: OrgRole = OrgRole.MEMBER


class InviteResultOut(ApiModel):
    email: str
    outcome: svc.Outcome


class InviteOut(ApiModel):
    results: list[InviteResultOut]


class InvitationPatch(ApiModel):
    role: OrgRole


def invite_state(inv: OrgInvitation) -> InviteState:
    if inv.email_status == InviteEmailStatus.FAILED:
        return "email_failed"
    return "invited" if svc.is_open(inv) else "expired"


def invitation_out(inv: OrgInvitation, inviter: User | None) -> InvitationOut:
    return InvitationOut(
        id=inv.id,
        email=inv.email,
        role=inv.role,
        state=invite_state(inv),
        expires_at=inv.expires_at,
        created_at=inv.created_at,
        sent_at=inv.sent_at,
        email_error=inv.email_error,
        invited_by_name=(inviter.display_name or inviter.email) if inviter else None,
        form_count=len(inv.form_grants),
    )


async def people(db: DbDep, settings: SettingsDep, org: Organization) -> PeopleOut:
    counts = await svc.grant_counts(db, org.id)
    groups = settings.oidc_group_mapping and org.slug == settings.default_org_slug
    rows = await db.execute(
        select(User, OrgMembership)
        .join(OrgMembership, OrgMembership.user_id == User.id)
        .where(OrgMembership.org_id == org.id)
        .order_by(User.display_name, User.email)
    )
    members = [
        PersonOut(
            user_id=u.id,
            email=u.email,
            display_name=u.display_name,
            role=m.role,
            status="active" if u.last_login_at else "never_signed_in",
            last_login_at=u.last_login_at,
            form_count=counts.get(u.id, 0),
            managed_by_groups=groups and m.idp_managed,
            is_superadmin=u.is_superadmin,
        )
        for u, m in rows.all()
    ]
    invs = (
        await db.execute(
            select(OrgInvitation, User)
            .outerjoin(User, User.id == OrgInvitation.invited_by)
            .where(
                OrgInvitation.org_id == org.id,
                OrgInvitation.status == InvitationStatus.PENDING,
            )
            .order_by(OrgInvitation.created_at.desc())
        )
    ).all()
    return PeopleOut(
        org_id=org.id,
        org_name=org.name,
        members=members,
        invitations=[invitation_out(inv, inviter) for inv, inviter in invs],
        admin_count=sum(1 for m in members if m.role == OrgRole.ADMIN),
        invite_days=settings.invite_days,
    )


async def _org(db: DbDep, org_id: uuid.UUID) -> Organization:
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "org_not_found")
    return org


async def _invitation(db: DbDep, org_id: uuid.UUID, invitation_id: uuid.UUID) -> OrgInvitation:
    inv = await db.get(OrgInvitation, invitation_id)
    if inv is None or inv.org_id != org_id or inv.status != InvitationStatus.PENDING:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invitation_not_found")
    return inv


async def limit_invites(
    redis: RedisDep, settings: SettingsDep, user: User, org_id: uuid.UUID, n: int
) -> None:
    """``n`` addresses at once: per admin, then per organisation (all or nothing)."""
    wait = await take(redis, settings, "invite_user", str(user.id), n)
    if wait is None:
        wait = await take(redis, settings, "invite_org", str(org_id), n)
    if wait is not None:
        raise too_many(wait)


async def send_invitation(queue: JobQueue, inv: OrgInvitation) -> None:
    await queue.enqueue("send_invitation_email", invitation_id=str(inv.id))


@router.get("/orgs/{org_id}/people", response_model=PeopleOut)
async def list_people(
    org_id: uuid.UUID, db: DbDep, settings: SettingsDep, _: OrgAdmin
) -> PeopleOut:
    return await people(db, settings, await _org(db, org_id))


@router.post("/orgs/{org_id}/invitations", response_model=InviteOut)
async def create_invitations(
    org_id: uuid.UUID,
    body: InviteIn,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    queue: QueueDep,
    user: CurrentUser,
    _: OrgAdmin,
) -> InviteOut:
    org = await _org(db, org_id)
    emails = list(dict.fromkeys(str(e).strip().lower() for e in body.emails))
    await limit_invites(redis, settings, user, org.id, len(emails))
    ip = client_ip(request, settings)
    results = [await svc.invite(db, settings, org, user, e, body.role, ip=ip) for e in emails]
    await db.commit()
    for r in results:
        if r.invitation is not None:
            await send_invitation(queue, r.invitation)
    return InviteOut(results=[InviteResultOut(email=r.email, outcome=r.outcome) for r in results])


@router.patch("/orgs/{org_id}/invitations/{invitation_id}", response_model=InvitationOut)
async def patch_invitation(
    org_id: uuid.UUID,
    invitation_id: uuid.UUID,
    body: InvitationPatch,
    db: DbDep,
    user: CurrentUser,
    _: OrgAdmin,
) -> InvitationOut:
    inv = await _invitation(db, org_id, invitation_id)
    before = inv.role
    inv.role = body.role
    await audit(
        db,
        "org.invite_role",
        org_id=org_id,
        actor_id=user.id,
        target_type="invitation",
        target_id=inv.id,
        meta={"email": inv.email, "before": before.value, "role": body.role.value},
    )
    await db.commit()
    inviter = await db.get(User, inv.invited_by) if inv.invited_by else None
    return invitation_out(inv, inviter)


@router.post("/orgs/{org_id}/invitations/{invitation_id}/resend", response_model=InvitationOut)
async def resend_invitation(
    org_id: uuid.UUID,
    invitation_id: uuid.UUID,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    queue: QueueDep,
    user: CurrentUser,
    _: OrgAdmin,
) -> InvitationOut:
    inv = await _invitation(db, org_id, invitation_id)
    await enforce(redis, settings, "invite_resend", str(inv.id))
    await limit_invites(redis, settings, user, org_id, 1)
    svc.restart(settings, inv)
    await audit(
        db,
        "org.invite_resend",
        org_id=org_id,
        actor_id=user.id,
        target_type="invitation",
        target_id=inv.id,
        ip=client_ip(request, settings),
        meta={"email": inv.email},
    )
    await db.commit()
    await send_invitation(queue, inv)
    inviter = await db.get(User, inv.invited_by) if inv.invited_by else None
    return invitation_out(inv, inviter)


@router.delete("/orgs/{org_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_invitation(
    org_id: uuid.UUID,
    invitation_id: uuid.UUID,
    db: DbDep,
    user: CurrentUser,
    _: OrgAdmin,
) -> Response:
    inv = await _invitation(db, org_id, invitation_id)
    inv.status = InvitationStatus.CANCELLED
    inv.token_hash = None  # the emailed link stops working
    await audit(
        db,
        "org.invite_cancel",
        org_id=org_id,
        actor_id=user.id,
        target_type="invitation",
        target_id=inv.id,
        meta={"email": inv.email},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- the invitation link ------------------------------------------------------------------------

LinkStatus = Literal["pending", "expired", "accepted", "invalid"]


class InvitationLink(ApiModel):
    status: LinkStatus
    org_name: str | None = None
    org_slug: str | None = None
    email: str | None = None
    role: OrgRole | None = None
    invited_by_name: str | None = None
    expires_at: datetime | None = None


@public.get(
    "/invitations/{invite_token}",
    response_model=InvitationLink,
    dependencies=[per_ip("invite_link")],
)
async def invitation_link(invite_token: str, db: DbDep, settings: SettingsDep) -> InvitationLink:
    """What the invitation page shows. Unknown, cancelled and replaced links are "invalid"."""
    inv = await svc.by_token(db, invite_token)
    if inv is None or inv.status == InvitationStatus.CANCELLED:
        return InvitationLink(status="invalid")
    from app.branding.service import resolve

    org = await db.get(Organization, inv.org_id)
    inviter = await db.get(User, inv.invited_by) if inv.invited_by else None
    state: LinkStatus = (
        "accepted"
        if inv.status == InvitationStatus.ACCEPTED
        else "pending"
        if svc.is_open(inv)
        else "expired"
    )
    return InvitationLink(
        status=state,
        org_name=resolve(settings, org).name,
        org_slug=org.slug if org else None,
        email=inv.email,
        role=inv.role,
        invited_by_name=(inviter.display_name or inviter.email) if inviter else None,
        expires_at=inv.expires_at,
    )


class AcceptOut(ApiModel):
    org_id: uuid.UUID
    org_name: str
    me: Me


@router.post(
    "/invitations/{invite_token}/accept", response_model=AcceptOut, dependencies=[per_ip("auth")]
)
async def accept_invitation(
    invite_token: str, request: Request, db: DbDep, settings: SettingsDep, user: CurrentUser
) -> AcceptOut:
    """Accept while signed in as the invited address (sign-in accepts it on its own too)."""
    inv = await svc.by_token(db, invite_token)
    if inv is None or inv.status == InvitationStatus.CANCELLED:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invitation_not_found")
    if inv.email.lower() != user.email.lower():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "wrong_account")
    if inv.status == InvitationStatus.PENDING:
        if not svc.is_open(inv):
            raise HTTPException(status.HTTP_410_GONE, "invitation_expired")
        await svc.accept_all(db, user, ip=client_ip(request, settings))
        await db.commit()
    from app.branding.service import resolve

    org = await db.get(Organization, inv.org_id)
    return AcceptOut(
        org_id=inv.org_id, org_name=resolve(settings, org).name, me=await build_me(db, user)
    )
