"""Staff authentication endpoints (DESIGN sections 8.1 and 17)."""

from __future__ import annotations

import logging
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import EmailStr, Field
from sqlalchemy import select

from app.api.v1.common import ApiModel
from app.auth import local
from app.auth.deps import (
    CurrentSession,
    CurrentUser,
    DbDep,
    RedisDep,
    SettingsDep,
    origin_guard,
)
from app.auth.oidc import (
    STATE_TTL_SECONDS,
    OIDCError,
    get_oidc_client,
    state_cookie_name,
    state_digest,
    state_matches,
)
from app.auth.sessions import (
    clear_session_cookies,
    create_session,
    delete_session,
    revoke_user_sessions,
    set_session_cookies,
)
from app.email import login_code_message
from app.models import (
    Appearance,
    Organization,
    OrgMembership,
    OrgRole,
    SuperadminSource,
    User,
)
from app.net import client_ip
from app.permissions import ORG_ROLE_RANK
from app.queue import JobQueue, get_queue
from app.ratelimit import per_ip
from app.services import invitations
from app.services.invitations import revoke_form_grants
from app.services.users import (
    audit,
    ensure_default_org,
    get_user_by_email,
    mark_login,
    normalize_email,
    set_membership,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class OrgSummary(ApiModel):
    id: uuid.UUID
    name: str
    slug: str
    role: OrgRole


class Me(ApiModel):
    id: uuid.UUID
    email: str
    display_name: str
    is_superadmin: bool
    # Studio appearance: light (default), dark or system (follow the device).
    appearance: Appearance = Appearance.LIGHT
    orgs: list[OrgSummary]


async def build_me(db: DbDep, user: User) -> Me:
    if user.is_superadmin:
        rows = (await db.execute(select(Organization).order_by(Organization.name))).scalars()
        orgs = [OrgSummary(id=o.id, name=o.name, slug=o.slug, role=OrgRole.ADMIN) for o in rows]
    else:
        result = await db.execute(
            select(Organization, OrgMembership.role)
            .join(OrgMembership, OrgMembership.org_id == Organization.id)
            .where(OrgMembership.user_id == user.id)
            .order_by(Organization.name)
        )
        orgs = [OrgSummary(id=o.id, name=o.name, slug=o.slug, role=r) for o, r in result.all()]
    return Me(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_superadmin=user.is_superadmin,
        appearance=user.appearance,
        orgs=orgs,
    )


@router.get("/me", response_model=Me)
async def me(db: DbDep, user: CurrentUser) -> Me:
    return await build_me(db, user)


class MePatch(ApiModel):
    appearance: Appearance | None = None


@router.patch("/me", response_model=Me)
async def patch_me(body: MePatch, db: DbDep, user: CurrentUser) -> Me:
    """The signed-in person's own preferences."""
    if body.appearance is not None:
        user.appearance = body.appearance
    await db.commit()
    return await build_me(db, user)


class LogoutResponse(ApiModel):
    logout_url: str | None = None


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    response: Response,
    redis: RedisDep,
    settings: SettingsDep,
    session: CurrentSession,
) -> LogoutResponse:
    await delete_session(redis, session)
    clear_session_cookies(response, settings)
    url = None
    if settings.oidc_enabled:
        url = await get_oidc_client(settings).end_session_url(session.end_session_hint)
    return LogoutResponse(logout_url=url)


# -- local one-time-code login ----------------------------------------------------------


class LocalRequest(ApiModel):
    email: EmailStr


class LocalVerify(ApiModel):
    email: EmailStr
    code: Annotated[str, Field(min_length=6, max_length=6, pattern=r"^\d{6}$")]


def _require_local(settings: SettingsDep) -> None:
    if not settings.local_login_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "local_login_disabled")


LocalOnly = [Depends(_require_local), Depends(origin_guard)]
AuthLimited = per_ip("auth")


@router.post("/local/request", status_code=status.HTTP_202_ACCEPTED, dependencies=LocalOnly)
async def local_request(
    body: LocalRequest,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    queue: Annotated[JobQueue, Depends(get_queue)],
) -> dict[str, str]:
    email = normalize_email(body.email)
    ip = client_ip(request, settings)
    if await local.rate_limited(redis, settings, email, ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_requests")
    # People with an open invitation get a code too: signing in with it accepts the invitation.
    known = await get_user_by_email(db, email) is not None
    if known or await invitations.has_open_invitation(db, email):
        code = await local.issue_code(redis, settings, email)
        from app.branding.service import INSTANCE_SLUG, brand_for_slug

        brand = await brand_for_slug(db, settings, INSTANCE_SLUG)
        name = brand.name if brand else "JustForms"
        subject, text = login_code_message(code, settings.login_code_ttl_seconds // 60, name)
        await queue.enqueue("send_email", to=email, subject=subject, text=text, from_name=name)
    # Same answer whether or not the address is known.
    return {"status": "sent"}


@router.post("/local/verify", response_model=Me, dependencies=[*LocalOnly, AuthLimited])
async def local_verify(
    body: LocalVerify,
    request: Request,
    response: Response,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> Me:
    email = normalize_email(body.email)
    if not await local.verify_code(redis, settings, email, body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_code")
    user = await invitations.user_for_open_invitation(db, email)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_code")
    ip = client_ip(request, settings)
    mark_login(user)
    # The code proved the address: accept the invitations waiting for it.
    await invitations.accept_all(db, user, ip=ip)
    await audit(db, "auth.login", actor_id=user.id, ip=ip, meta={"method": "local"})
    await db.commit()
    token, session = await create_session(redis, settings, str(user.id))
    set_session_cookies(response, settings, token, session)
    return await build_me(db, user)


# -- OIDC -------------------------------------------------------------------------------


_EMAIL_HINT = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _require_oidc(settings: SettingsDep) -> None:
    if not settings.oidc_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "oidc_disabled")


@router.get("/login", dependencies=[Depends(_require_oidc), AuthLimited])
async def oidc_login(
    request: Request,
    redis: RedisDep,
    settings: SettingsDep,
    next: Annotated[str | None, Query()] = None,
    login_hint: Annotated[str | None, Query(max_length=320)] = None,
) -> RedirectResponse:
    # Only an email address is passed on as a hint (invitation links); anything else is dropped.
    hint = normalize_email(login_hint) if login_hint and _EMAIL_HINT.match(login_hint) else None
    try:
        url, state = await get_oidc_client(settings).start(redis, next, hint)
    except OIDCError as exc:
        log.warning("OIDC login failed to start: %s", exc)
        return RedirectResponse("/login?error=sso_unavailable", status.HTTP_302_FOUND)
    response = RedirectResponse(url, status.HTTP_302_FOUND)
    # Only this browser can finish this sign-in: the callback must carry the matching cookie,
    # so nobody can send someone a callback link that signs them into another account.
    response.set_cookie(
        state_cookie_name(settings),
        state_digest(state),
        max_age=STATE_TTL_SECONDS,
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    return response


def _claim_email(settings: SettingsDep, claims: dict[str, Any]) -> tuple[str | None, bool]:
    """The address in the ID token and whether the IdP vouches for it (DESIGN 8.1).

    ``email`` counts as verified with ``email_verified: true`` (exactly) or when the operator
    trusts the IdP's addresses (JUSTFORMS_OIDC_TRUST_EMAIL). Other claims (usernames, UPNs) are
    read only when listed in JUSTFORMS_OIDC_EMAIL_FALLBACK_CLAIMS, and are verified only when
    trusted: they are login names, not checked addresses.
    """
    value = claims.get("email")
    if isinstance(value, str) and "@" in value:
        verified = claims.get("email_verified") is True or settings.oidc_trust_email
        return normalize_email(value), verified
    for key in settings.oidc_email_fallback_claims:
        value = claims.get(key)
        if isinstance(value, str) and "@" in value:
            return normalize_email(value), settings.oidc_trust_email
    return None, False


def _claim_groups(settings: SettingsDep, claims: dict[str, Any]) -> set[str] | None:
    """The person's IdP groups, or None when the IdP left them out of the token.

    Entra ID drops the groups claim when someone is in too many groups ("group overage") and
    sends ``_claim_names`` (or ``hasgroups``) pointing at Microsoft Graph instead.
    """
    name = settings.oidc_groups_claim
    raw = claims.get(name)
    if raw is None:
        claim_names = claims.get("_claim_names")
        if (isinstance(claim_names, dict) and name in claim_names) or claims.get("hasgroups"):
            return None
        return set()
    return {str(g) for g in raw} if isinstance(raw, list) else set()


async def _sync_superadmin(db: DbDep, settings: SettingsDep, user: User, groups: set[str]) -> None:
    """Grant or take away superadmin from JUSTFORMS_OIDC_SUPERADMIN_GROUPS (DESIGN 7)."""
    matched = sorted(groups & set(settings.oidc_superadmin_groups))
    if matched and not user.is_superadmin:
        user.is_superadmin = True
        user.superadmin_source = SuperadminSource.OIDC
        await audit(
            db,
            "user.superadmin_grant",
            target_type="user",
            target_id=user.id,
            meta={"source": "oidc", "groups": matched},
        )
    elif not matched and user.is_superadmin and user.superadmin_source == SuperadminSource.OIDC:
        # Only what OIDC granted: superadmins made with create-admin keep it.
        user.is_superadmin = False
        user.superadmin_source = None
        await audit(
            db,
            "user.superadmin_revoke",
            target_type="user",
            target_id=user.id,
            meta={"source": "oidc"},
        )


async def _link_by_email(
    db: DbDep, settings: SettingsDep, email: str | None, verified: bool, subject: str
) -> User | None:
    """First sign-in of an identity: the existing account to link, or None for a new one.
    Raises OIDCError when the sign-in must be refused."""
    if email is None:
        raise OIDCError("id_token has no email claim")
    if not verified:
        # Never link to, or take, an address on the IdP's unverified word ("nOAuth").
        raise OIDCError(
            "the IdP does not vouch for the email address (no email_verified=true); set "
            "JUSTFORMS_OIDC_TRUST_EMAIL only if its email claim is administrator-managed"
        )
    existing = await get_user_by_email(db, email)
    if existing is None:
        return None
    if existing.oidc_subject not in (None, subject):
        raise OIDCError("email already linked to another identity")
    if existing.is_superadmin and not settings.oidc_trust_email:
        log.warning(
            "OIDC sign-in matches superadmin %s by email; not linked automatically. Bind it with "
            "`python -m app.cli create-admin --email %s --oidc-subject %s`, or set "
            "JUSTFORMS_OIDC_TRUST_EMAIL=true if the IdP's email claim is administrator-managed.",
            existing.email,
            existing.email,
            subject,
        )
        raise OIDCError("superadmin accounts are not linked by email")
    return existing


async def _end_superadmin_admin(
    db: DbDep, org: Organization, membership: OrgMembership, mapped: OrgRole | None
) -> OrgMembership | None:
    """Superadmin was taken away: undo the default-organisation admin role it granted, back to
    the group-mapped role (``mapped``, with group mapping) or the role held before."""
    role = mapped
    if role is None and membership.superadmin_prior_role:
        role = OrgRole(membership.superadmin_prior_role)
    before = membership.role
    membership.superadmin_granted = False
    membership.superadmin_prior_role = None
    meta: dict[str, Any] = {"before": before.value, "source": "oidc_superadmin_revoke"}
    result: OrgMembership | None = membership
    if role is None:
        await db.delete(membership)
        meta["role"] = None
        meta["forms_revoked"] = await revoke_form_grants(db, org.id, membership.user_id)
        result = None
    else:
        membership.role = role
        meta["role"] = role.value
    await audit(
        db,
        "org.member_role",
        org_id=org.id,
        target_type="user",
        target_id=membership.user_id,
        meta=meta,
    )
    return result


def _mapped_role(settings: SettingsDep, groups: set[str] | None) -> OrgRole | None:
    if not settings.oidc_group_mapping or groups is None:
        return None
    if groups & set(settings.oidc_admin_groups):
        return OrgRole.ADMIN
    if groups & set(settings.oidc_creator_groups):
        return OrgRole.CREATOR
    if groups & set(settings.oidc_member_groups):
        return OrgRole.MEMBER
    return None


async def upsert_oidc_user(
    db: DbDep, settings: SettingsDep, claims: dict[str, Any]
) -> tuple[User, bool]:
    """The account for these ID token claims, with roles synced. Returns the user and whether
    this sign-in took access away (then the person's other sessions should end)."""
    issuer, subject = str(claims["iss"]), str(claims["sub"])
    email, verified = _claim_email(settings, claims)
    user = await db.scalar(
        select(User).where(User.oidc_issuer == issuer, User.oidc_subject == subject)
    )
    # First sign-in of a person JustForms didn't know (not even from an invitation).
    new_user = False
    if user is None:
        user = await _link_by_email(db, settings, email, verified, subject)
        if user is None:
            assert email is not None
            new_user = True
            user = User(email=email)
            db.add(user)
        user.oidc_issuer, user.oidc_subject = issuer, subject
    elif verified and email and email != user.email and await get_user_by_email(db, email) is None:
        # Only an address the IdP vouches for replaces the stored one (invitations follow it).
        user.email = email
    name = claims.get("name") or claims.get("preferred_username")
    if isinstance(name, str) and name:
        user.display_name = name[:200]
    mark_login(user)
    await db.flush()

    was_superadmin = user.is_superadmin
    org = await ensure_default_org(db, settings)
    membership = await db.get(OrgMembership, (org.id, user.id))
    role_before = membership.role if membership is not None else None
    groups = _claim_groups(settings, claims)
    if groups is None and (settings.oidc_group_mapping or settings.oidc_superadmin_groups):
        log.warning(
            "OIDC sign-in of %s: the ID token has no %r claim because the IdP left the groups "
            "out (Entra ID group overage: _claim_names/hasgroups). Roles and superadmin are "
            "left unchanged. Emit only the groups assigned to the application instead.",
            user.email,
            settings.oidc_groups_claim,
        )
    if groups is not None and settings.oidc_superadmin_groups:
        await _sync_superadmin(db, settings, user, groups)
    # Superadmin from an IdP group (granted or confirmed now): also admin of the default org.
    oidc_superadmin = (
        groups is not None
        and bool(groups & set(settings.oidc_superadmin_groups))
        and user.is_superadmin
        and user.superadmin_source == SuperadminSource.OIDC
    )
    mapped = _mapped_role(settings, groups)
    # Admin only through an IdP superadmin group that no longer applies: undo that first.
    if (
        membership is not None
        and membership.superadmin_granted
        and groups is not None
        and not oidc_superadmin
    ):
        membership = await _end_superadmin_admin(db, org, membership, mapped)
        if membership is not None and settings.oidc_group_mapping:
            membership.idp_managed = True
    if settings.oidc_group_mapping and groups is not None and not oidc_superadmin:
        # An admin role the mapping didn't grant (an invitation, an admin's change) is not
        # lowered by it: an admin can change it.
        kept_admin = (
            membership is not None
            and not membership.idp_managed
            and membership.role == OrgRole.ADMIN
            and mapped != OrgRole.ADMIN
        )
        if mapped is not None and not kept_admin:
            membership = await set_membership(db, org, user, mapped)
            membership.idp_managed = True
        elif mapped is None and membership is not None and membership.idp_managed:
            # The IdP is authoritative for what it granted: no mapped group, no role. People
            # an admin invited or added keep theirs. Their roles on the org's forms go too.
            await db.delete(membership)
            revoked = await revoke_form_grants(db, org.id, user.id)
            await audit(
                db,
                "org.member_remove",
                org_id=org.id,
                target_type="user",
                target_id=user.id,
                meta={"role": membership.role.value, "source": "oidc", "forms_revoked": revoked},
            )
            membership = None
    elif (
        not settings.oidc_group_mapping
        and new_user
        and membership is None
        and settings.oidc_default_role != "none"
    ):
        membership = await set_membership(db, org, user, OrgRole(settings.oidc_default_role))
        membership.idp_managed = True
    if oidc_superadmin:
        if membership is None or membership.role != OrgRole.ADMIN:
            prior: OrgRole | None = membership.role if membership is not None else None
            if settings.oidc_group_mapping and groups is not None:
                prior = mapped
            membership = await set_membership(db, org, user, OrgRole.ADMIN)
            # Admin because of superadmin: undone (back to `prior`, or removed) when the IdP
            # takes superadmin away. Not IdP-managed: group mapping doesn't lower it meanwhile.
            membership.superadmin_granted = True
            membership.superadmin_prior_role = prior.value if prior is not None else None
            membership.idp_managed = False
        elif membership.superadmin_granted and settings.oidc_group_mapping:
            # What remains without superadmin follows the groups.
            membership.superadmin_prior_role = mapped.value if mapped is not None else None
        if role_before != OrgRole.ADMIN:
            await audit(
                db,
                "org.member_role",
                org_id=org.id,
                target_type="user",
                target_id=user.id,
                meta={
                    "before": role_before.value if role_before else None,
                    "role": OrgRole.ADMIN.value,
                    "source": "oidc_superadmin",
                },
            )
    role_after = membership.role if membership is not None else None
    reduced = (was_superadmin and not user.is_superadmin) or (
        role_before is not None
        and (role_after is None or ORG_ROLE_RANK[role_after] < ORG_ROLE_RANK[role_before])
    )
    # Invitations for this address, only when the IdP vouches for it.
    if verified:
        await invitations.accept_all(db, user)
    await db.flush()
    return user, reduced


@router.get("/callback", dependencies=[Depends(_require_oidc), AuthLimited])
async def oidc_callback(
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error or not code or not state:
        return _sso_failed(settings)
    # Login CSRF, best effort: a state cookie from another sign-in is refused. A missing cookie
    # is allowed: on phones the IdP (an authenticator broker, in-app browser or custom tab)
    # often finishes in another browser context. The server-side state below is still single
    # use and carries the PKCE verifier and nonce.
    cookie = request.cookies.get(state_cookie_name(settings))
    if cookie is None:
        log.info("OIDC callback: no state cookie, relying on the server-side state")
    elif not state_matches(state, cookie):
        log.warning("OIDC callback rejected: state cookie belongs to another sign-in")
        return _sso_failed(settings)
    else:
        log.info("OIDC callback: state cookie matches")
    try:
        claims, id_token, next_path = await get_oidc_client(settings).finish(redis, code, state)
        user, reduced = await upsert_oidc_user(db, settings, claims)
    except OIDCError as exc:
        await db.rollback()
        log.warning("OIDC callback rejected: %s", exc)
        return _sso_failed(settings)
    await audit(
        db,
        "auth.login",
        actor_id=user.id,
        ip=client_ip(request, settings),
        meta={"method": "oidc"},
    )
    await db.commit()
    if reduced:
        # The IdP took access away: end the person's other sessions.
        await revoke_user_sessions(redis, user.id)
    token, session = await create_session(redis, settings, str(user.id), id_token=id_token)
    response = RedirectResponse(next_path, status.HTTP_302_FOUND)
    set_session_cookies(response, settings, token, session)
    response.delete_cookie(
        state_cookie_name(settings), path="/", secure=settings.secure_cookies, samesite="lax"
    )
    return response


def _sso_failed(settings: SettingsDep) -> RedirectResponse:
    response = RedirectResponse("/login?error=sso_failed", status.HTTP_302_FOUND)
    response.delete_cookie(
        state_cookie_name(settings), path="/", secure=settings.secure_cookies, samesite="lax"
    )
    return response
