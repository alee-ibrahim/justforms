"""Organisation invitations and membership changes (docs/ux/PEOPLE-SCREENS.md, DESIGN 7).

An invitation is accepted when someone signs in with its address (an emailed code proves the
address; OIDC needs a matching email that the IdP doesn't mark unverified) while it is pending
and not expired. The emailed link only leads to a prefilled sign-in page. Its token is stored as
a SHA-256 hash and minted by the worker right before the email goes out (after committing it,
as for approval links), so a resend replaces the link.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    FormPermission,
    FormRecord,
    FormRole,
    InvitationStatus,
    InviteEmailStatus,
    Organization,
    OrgInvitation,
    OrgMembership,
    OrgRole,
    User,
)
from app.notifications import emails
from app.permissions import higher_form_role, higher_org_role
from app.services.users import audit, get_user_by_email, normalize_email

MAX_PER_REQUEST = 20


def now() -> datetime:
    return datetime.now(UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def invite_url(settings: Settings, token: str) -> str:
    return f"{settings.public_origin}/login/invite/{token}"


def is_open(inv: OrgInvitation) -> bool:
    return inv.status == InvitationStatus.PENDING and inv.expires_at > now()


def mint_link(settings: Settings, inv: OrgInvitation) -> str:
    """A new link token for ``inv`` (stored as a hash; the previous link stops working)."""
    token = secrets.token_urlsafe(24)
    inv.token_hash = hash_token(token)
    return invite_url(settings, token)


async def by_token(db: AsyncSession, token: str) -> OrgInvitation | None:
    if not 20 <= len(token) <= 64:
        return None
    return await db.scalar(
        select(OrgInvitation).where(OrgInvitation.token_hash == hash_token(token))
    )


async def open_for_email(db: AsyncSession, email: str) -> list[OrgInvitation]:
    rows = await db.scalars(
        select(OrgInvitation).where(
            OrgInvitation.email == normalize_email(email),
            OrgInvitation.status == InvitationStatus.PENDING,
            OrgInvitation.expires_at > now(),
        )
    )
    return list(rows)


async def has_open_invitation(db: AsyncSession, email: str) -> bool:
    return bool(await open_for_email(db, email))


async def pending_in_org(db: AsyncSession, org_id: uuid.UUID, email: str) -> OrgInvitation | None:
    """The invitation that is still pending (open or expired) for ``email`` in ``org_id``."""
    return await db.scalar(
        select(OrgInvitation).where(
            OrgInvitation.org_id == org_id,
            OrgInvitation.email == normalize_email(email),
            OrgInvitation.status == InvitationStatus.PENDING,
        )
    )


async def is_member(db: AsyncSession, org_id: uuid.UUID, email: str) -> bool:
    found = await db.scalar(
        select(OrgMembership.user_id)
        .join(User, User.id == OrgMembership.user_id)
        .where(OrgMembership.org_id == org_id, User.email == normalize_email(email))
    )
    return found is not None


Outcome = Literal["invited", "already_member"]


@dataclass
class InviteResult:
    email: str
    outcome: Outcome
    invitation: OrgInvitation | None = None


def _add_grant(inv: OrgInvitation, form_id: uuid.UUID, role: FormRole) -> None:
    grants = [g for g in inv.form_grants if g.get("formId") != str(form_id)]
    grants.append({"formId": str(form_id), "role": role.value})
    inv.form_grants = grants  # a new list, so SQLAlchemy sees the change


def drop_grant(inv: OrgInvitation, form_id: uuid.UUID) -> bool:
    grants = [g for g in inv.form_grants if g.get("formId") != str(form_id)]
    changed = len(grants) != len(inv.form_grants)
    inv.form_grants = grants
    return changed


def restart(settings: Settings, inv: OrgInvitation) -> None:
    """Queue a fresh email: new expiry; the worker mints a new link (the old one stops)."""
    inv.expires_at = now() + timedelta(days=settings.invite_days)
    inv.token_hash = None
    inv.email_status = InviteEmailStatus.QUEUED
    inv.email_error = None


async def invite(
    db: AsyncSession,
    settings: Settings,
    org: Organization,
    actor: User,
    email: str,
    role: OrgRole,
    *,
    form_grant: tuple[uuid.UUID, FormRole] | None = None,
    ip: str | None = None,
) -> InviteResult:
    """Invite ``email`` to ``org`` (or refresh its pending invitation: the role is updated and
    a new email goes out). The caller commits and enqueues ``send_invitation_email``."""
    address = normalize_email(email)
    if await is_member(db, org.id, address):
        return InviteResult(address, "already_member")
    inv = await pending_in_org(db, org.id, address)
    fresh = inv is None
    if inv is None:
        inv = OrgInvitation(
            org_id=org.id,
            email=address,
            role=role,
            invited_by=actor.id,
            form_grants=[],
            expires_at=now(),
        )
        db.add(inv)
    elif form_grant is None:
        inv.role = role
        inv.invited_by = actor.id
    if form_grant is not None:
        _add_grant(inv, *form_grant)
    restart(settings, inv)
    await db.flush()
    await audit(
        db,
        "org.invite" if fresh else "org.invite_resend",
        org_id=org.id,
        actor_id=actor.id,
        target_type="invitation",
        target_id=inv.id,
        ip=ip,
        meta={
            "email": address,
            "role": inv.role.value,
            **({"form_id": str(form_grant[0])} if form_grant else {}),
        },
    )
    return InviteResult(address, "invited", inv)


async def _grant_forms(db: AsyncSession, inv: OrgInvitation, user: User) -> int:
    granted = 0
    for g in inv.form_grants:
        try:
            form_id = uuid.UUID(str(g.get("formId")))
            role = FormRole(str(g.get("role")))
        except ValueError:
            continue
        form = await db.get(FormRecord, form_id)
        if form is None or form.deleted_at is not None or form.org_id != inv.org_id:
            continue
        perm = await db.get(FormPermission, (form_id, user.id))
        if perm is None:
            db.add(FormPermission(form_id=form_id, user_id=user.id, role=role))
        else:
            perm.role = higher_form_role(perm.role, role)
        granted += 1
    return granted


async def accept(
    db: AsyncSession, inv: OrgInvitation, user: User, *, ip: str | None = None
) -> None:
    """Join ``inv``'s organisation (keeping a higher role someone already has) and get the
    form roles it carries. The caller has checked that the invitation is open and that
    ``user`` owns its address, and commits."""
    membership = await db.get(OrgMembership, (inv.org_id, user.id))
    if membership is None:
        db.add(OrgMembership(org_id=inv.org_id, user_id=user.id, role=inv.role))
    else:
        membership.role = higher_org_role(membership.role, inv.role)
        # An invitation is an admin's decision: keep this membership even if IdP groups change.
        membership.idp_managed = False
        if membership.superadmin_granted:
            # Admin through superadmin: the invited role is what remains without it.
            prior = OrgRole(membership.superadmin_prior_role or inv.role)
            membership.superadmin_prior_role = higher_org_role(prior, inv.role).value
    await db.flush()
    forms = await _grant_forms(db, inv, user)
    inv.status = InvitationStatus.ACCEPTED
    inv.accepted_at = now()
    inv.accepted_user_id = user.id  # the link keeps working, to say it was used
    await audit(
        db,
        "org.invite_accept",
        org_id=inv.org_id,
        actor_id=user.id,
        target_type="invitation",
        target_id=inv.id,
        ip=ip,
        meta={"role": inv.role.value, "forms": forms},
    )


async def accept_all(db: AsyncSession, user: User, *, ip: str | None = None) -> list[OrgInvitation]:
    """Accept every open invitation for ``user``'s address (after a sign-in proved it)."""
    accepted = []
    for inv in await open_for_email(db, user.email):
        await accept(db, inv, user, ip=ip)
        accepted.append(inv)
    return accepted


async def user_for_open_invitation(db: AsyncSession, email: str) -> User | None:
    """The account for ``email``, created when an open invitation is waiting for it."""
    user = await get_user_by_email(db, email)
    if user is None and await has_open_invitation(db, email):
        user = User(email=normalize_email(email))
        db.add(user)
        await db.flush()
    return user


# -- members ----------------------------------------------------------------------------------


async def admin_count(db: AsyncSession, org_id: uuid.UUID) -> int:
    """Admins of ``org_id``. Their rows are locked until commit, so two admins demoting each
    other at the same moment can't leave the organisation without one."""
    rows = await db.scalars(
        select(OrgMembership.user_id)
        .where(OrgMembership.org_id == org_id, OrgMembership.role == OrgRole.ADMIN)
        .with_for_update()
    )
    return len(list(rows))


async def grant_counts(db: AsyncSession, org_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """Forms (not deleted) each person has a role on in ``org_id``."""
    rows = await db.execute(
        select(FormPermission.user_id, func.count())
        .join(FormRecord, FormRecord.id == FormPermission.form_id)
        .where(FormRecord.org_id == org_id, FormRecord.deleted_at.is_(None))
        .group_by(FormPermission.user_id)
    )
    return {uid: int(n) for uid, n in rows.all()}


async def revoke_form_grants(db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> int:
    """Remove ``user_id``'s roles on every form of ``org_id`` (deleted forms included)."""
    form_ids = select(FormRecord.id).where(FormRecord.org_id == org_id).scalar_subquery()
    result = await db.execute(
        delete(FormPermission).where(
            FormPermission.user_id == user_id, FormPermission.form_id.in_(form_ids)
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


# -- the email ----------------------------------------------------------------------------------


async def render(
    db: AsyncSession, settings: Settings, inv: OrgInvitation, url: str
) -> emails.Message:
    from app.branding.service import email_brand, resolve

    org = await db.get(Organization, inv.org_id)
    brand = resolve(settings, org)
    inviter = await db.get(User, inv.invited_by) if inv.invited_by else None
    forms: list[emails.InvitedForm] = []
    for g in inv.form_grants:
        try:
            form = await db.get(FormRecord, uuid.UUID(str(g.get("formId"))))
        except ValueError:
            continue
        if form is None or form.deleted_at is not None:
            continue
        language = str((form.draft_schema.get("settings") or {}).get("language") or "en")
        forms.append(emails.InvitedForm(title=form.title, language=language))
    return emails.invitation_message(
        org_name=brand.name,
        product=settings.brand_name.strip() or "JustForms",
        brand=email_brand(settings, brand),
        inviter=(inviter.display_name or inviter.email) if inviter else None,
        role=inv.role.value,
        forms=forms,
        url=url,
        until=inv.expires_at,
        tz=settings.tz,
        email=inv.email,
        single_sign_on=settings.oidc_enabled,
    )
