"""Staff authentication endpoints (DESIGN sections 8.1 and 17)."""

from __future__ import annotations

import logging
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
from app.auth.oidc import OIDCError, get_oidc_client
from app.auth.sessions import (
    clear_session_cookies,
    create_session,
    delete_session,
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
from app.queue import JobQueue, get_queue
from app.ratelimit import per_ip
from app.services import invitations
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
    ip = request.client.host if request.client else None
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
    ip = request.client.host if request.client else None
    mark_login(user)
    # The code proved the address: accept the invitations waiting for it.
    await invitations.accept_all(db, user, ip=ip)
    await audit(db, "auth.login", actor_id=user.id, ip=ip, meta={"method": "local"})
    await db.commit()
    token, session = await create_session(redis, settings, str(user.id))
    set_session_cookies(response, settings, token, session)
    return await build_me(db, user)


# -- OIDC -------------------------------------------------------------------------------


def _require_oidc(settings: SettingsDep) -> None:
    if not settings.oidc_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "oidc_disabled")


@router.get("/login", dependencies=[Depends(_require_oidc), AuthLimited])
async def oidc_login(
    redis: RedisDep, settings: SettingsDep, next: Annotated[str | None, Query()] = None
) -> RedirectResponse:
    try:
        url = await get_oidc_client(settings).start(redis, next)
    except OIDCError as exc:
        log.warning("OIDC login failed to start: %s", exc)
        return RedirectResponse("/login?error=sso_unavailable", status.HTTP_302_FOUND)
    return RedirectResponse(url, status.HTTP_302_FOUND)


def _claim_email(claims: dict[str, Any]) -> str | None:
    for key in ("email", "preferred_username", "upn"):
        value = claims.get(key)
        if isinstance(value, str) and "@" in value:
            return normalize_email(value)
    return None


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


async def upsert_oidc_user(db: DbDep, settings: SettingsDep, claims: dict[str, Any]) -> User:
    issuer, subject = str(claims["iss"]), str(claims["sub"])
    email = _claim_email(claims)
    user = await db.scalar(
        select(User).where(User.oidc_issuer == issuer, User.oidc_subject == subject)
    )
    # First sign-in of a person JustForms didn't know (not even from an invitation).
    new_user = False
    if user is None:
        if email is None:
            raise OIDCError("id_token has no email claim")
        user = await get_user_by_email(db, email)
        if user is not None and user.oidc_subject not in (None, subject):
            raise OIDCError("email already linked to another identity")
        if user is None:
            new_user = True
            user = User(email=email)
            db.add(user)
        user.oidc_issuer, user.oidc_subject = issuer, subject
    elif email and email != user.email and await get_user_by_email(db, email) is None:
        user.email = email
    name = claims.get("name") or claims.get("preferred_username")
    if isinstance(name, str) and name:
        user.display_name = name[:200]
    mark_login(user)
    await db.flush()

    org = await ensure_default_org(db, settings)
    membership = await db.get(OrgMembership, (org.id, user.id))
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
    if settings.oidc_group_mapping and groups is not None:
        role: OrgRole | None = None
        if groups & set(settings.oidc_admin_groups):
            role = OrgRole.ADMIN
        elif groups & set(settings.oidc_creator_groups):
            role = OrgRole.CREATOR
        elif groups & set(settings.oidc_member_groups):
            role = OrgRole.MEMBER
        if role is not None:
            membership = await set_membership(db, org, user, role)
            membership.idp_managed = True
        elif membership is not None and membership.idp_managed:
            # The IdP is authoritative for what it granted: no mapped group, no role. People
            # an admin invited or added keep theirs.
            await db.delete(membership)
    elif (
        not settings.oidc_group_mapping
        and new_user
        and membership is None
        and settings.oidc_default_role != "none"
    ):
        membership = await set_membership(db, org, user, OrgRole(settings.oidc_default_role))
        membership.idp_managed = True
    # Invitations for this address. Not when the IdP says the address isn't verified.
    if claims.get("email_verified") is not False:
        await invitations.accept_all(db, user)
    await db.flush()
    return user


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
        return RedirectResponse("/login?error=sso_failed", status.HTTP_302_FOUND)
    try:
        claims, id_token, next_path = await get_oidc_client(settings).finish(redis, code, state)
        user = await upsert_oidc_user(db, settings, claims)
    except OIDCError as exc:
        await db.rollback()
        log.warning("OIDC callback rejected: %s", exc)
        return RedirectResponse("/login?error=sso_failed", status.HTTP_302_FOUND)
    await audit(
        db,
        "auth.login",
        actor_id=user.id,
        ip=request.client.host if request.client else None,
        meta={"method": "oidc"},
    )
    await db.commit()
    token, session = await create_session(redis, settings, str(user.id), id_token=id_token)
    response = RedirectResponse(next_path, status.HTTP_302_FOUND)
    set_session_cookies(response, settings, token, session)
    return response
