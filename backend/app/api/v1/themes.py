"""Form themes (docs/ux/FORM-THEME-SCREENS.md section 3).

Staff: the organisation's form theme (members read, admins change), a form's overrides and
its own logo (viewers read, editors change), a live preview of unsaved values and theme image
uploads. Public: a form's theme stylesheet, the theme images and form logos, served from this
origin.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy.orm.attributes import flag_modified

from app import ratelimit
from app.api.v1.branding import IMAGE_HEADERS as LOGO_HEADERS
from app.api.v1.common import ApiModel
from app.auth.deps import CurrentUser, DbDep, RedisDep, SettingsDep, StorageDep
from app.branding.images import MAX_BYTES as LOGO_MAX_BYTES
from app.branding.images import BrandImageError, clean_image
from app.config import Settings
from app.models import FormRecord, FormRole, FormVersion, Organization
from app.net import client_ip
from app.permissions import (
    FormEditor,
    FormViewer,
    OrgAdmin,
    OrgMember,
    effective_form_role,
    has_form_role,
    org_role,
)
from app.schemas.theme import FormTheme
from app.services import slugs
from app.services.users import audit
from app.theme import images
from app.theme import logo as form_logos
from app.theme import resolve as themes
from app.theme.fonts import catalogue, font_source, thaana_fonts

router = APIRouter(tags=["themes"])
public = APIRouter(prefix="/public", tags=["themes"])

IMAGE_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "X-Content-Type-Options": "nosniff",
    "Cross-Origin-Resource-Policy": "same-origin",
}
YEAR = "public, max-age=31536000, immutable"


class LogoOut(ApiModel):
    url: str
    mime: str
    width: int
    height: int


class ThemeOut(ApiModel):
    theme: dict[str, Any]
    can_edit: bool
    fonts: dict[str, Any]
    font_source: str | None
    preview: dict[str, Any]
    # Form endpoints only: the organisation's values (what "inherit" means here).
    organisation: dict[str, Any] | None = None
    effective: dict[str, Any] | None = None
    # Form endpoints only: the form's own logo (None: it uses the organisation's).
    logo: LogoOut | None = None


class PreviewIn(ApiModel):
    org_id: uuid.UUID
    # Preview for this form: its own logo is used (the caller must be able to view it).
    form_id: uuid.UUID | None = None
    # Unsaved organisation values; the stored ones when missing.
    organisation: FormTheme | None = None
    # A form's unsaved overrides, on top of the organisation's.
    form: FormTheme | None = None


class ImageOut(ApiModel):
    ref: str
    url: str
    width: int
    height: int


def _check_fonts(settings: Settings, theme: FormTheme) -> None:
    if theme.thaana_font and theme.thaana_font not in thaana_fonts(settings):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_thaana_font")


async def _org(db: DbDep, org_id: uuid.UUID) -> Organization:
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "org_not_found")
    return org


async def _schema(db: DbDep, form: FormRecord) -> dict[str, Any] | None:
    if form.current_version_id:
        version = await db.get(FormVersion, form.current_version_id)
        if version is not None:
            return version.schema
    return form.draft_schema


def _org_out(settings: Settings, org: Organization, can_edit: bool) -> ThemeOut:
    stored = themes.org_theme(org)
    return ThemeOut(
        theme=stored.dump(),
        can_edit=can_edit,
        fonts=catalogue(settings),
        font_source=font_source(settings),
        preview=themes.resolve(settings, org, stored).report(),
    )


@router.get("/orgs/{org_id}/form-theme", response_model=ThemeOut)
async def get_org_theme(
    org_id: uuid.UUID, db: DbDep, settings: SettingsDep, role: OrgMember
) -> ThemeOut:
    return _org_out(settings, await _org(db, org_id), can_edit=role.value == "admin")


@router.put("/orgs/{org_id}/form-theme", response_model=ThemeOut)
async def put_org_theme(
    org_id: uuid.UUID,
    body: FormTheme,
    db: DbDep,
    settings: SettingsDep,
    user: CurrentUser,
    _: OrgAdmin,
) -> ThemeOut:
    _check_fonts(settings, body)
    org = await _org(db, org_id)
    org.settings = {**(org.settings or {}), themes.ORG_KEY: body.dump()}
    flag_modified(org, "settings")
    await audit(
        db, "org.form_theme", org_id=org.id, actor_id=user.id, target_type="org", target_id=org.id
    )
    await db.commit()
    return _org_out(settings, org, can_edit=True)


async def _form_out(db: DbDep, settings: Settings, form: FormRecord, can_edit: bool) -> ThemeOut:
    org = await _org(db, form.org_id)
    own = themes.form_theme(form)
    org_layer = themes.org_theme(org)
    inherited = themes.resolve(settings, org, org_layer)
    result = themes.for_form(settings, org, form, await _schema(db, form))
    own_logo = form_logos.form_logo(form)
    return ThemeOut(
        theme=own.dump(),
        can_edit=can_edit,
        fonts=catalogue(settings),
        font_source=font_source(settings),
        preview=result.report(),
        organisation={
            "theme": org_layer.dump(),
            "resolved": inherited.resolved.model_dump(mode="json", by_alias=True),
        },
        effective=result.chosen.dump(),
        logo=LogoOut.model_validate(own_logo.public()) if own_logo else None,
    )


@router.get("/forms/{form_id}/theme", response_model=ThemeOut)
async def get_form_theme(db: DbDep, settings: SettingsDep, access: FormViewer) -> ThemeOut:
    can_edit = has_form_role(access.role, FormRole.EDITOR)
    return await _form_out(db, settings, access.form, can_edit)


@router.put("/forms/{form_id}/theme", response_model=ThemeOut)
async def put_form_theme(
    body: FormTheme, db: DbDep, settings: SettingsDep, access: FormEditor
) -> ThemeOut:
    _check_fonts(settings, body)
    form = access.form
    rest = {k: v for k, v in (form.settings or {}).items() if k != themes.FORM_KEY}
    dumped = body.dump()
    form.settings = {**rest, **({themes.FORM_KEY: dumped} if dumped != {"colors": {}} else {})}
    flag_modified(form, "settings")
    await audit(
        db,
        "form.theme",
        org_id=form.org_id,
        actor_id=access.user.id,
        target_type="form",
        target_id=form.id,
    )
    await db.commit()
    return await _form_out(db, settings, form, can_edit=True)


@router.post("/themes/preview")
async def preview_theme(
    body: PreviewIn, db: DbDep, settings: SettingsDep, user: CurrentUser
) -> dict[str, Any]:
    """Tokens, fonts, options and contrast adjustments for unsaved values (live preview)."""
    if not user.is_superadmin and await org_role(db, user, body.org_id) is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_org_role")
    org = await _org(db, body.org_id)
    own_logo = None
    if body.form_id is not None:
        form = await db.get(FormRecord, body.form_id)
        role = (
            await effective_form_role(db, user, form)
            if form is not None and form.deleted_at is None and form.org_id == org.id
            else None
        )
        if form is None or role is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "form_not_found")
        own_logo = form_logos.form_logo(form)
    org_layer = body.organisation if body.organisation is not None else themes.org_theme(org)
    layers = [org_layer] + ([body.form] if body.form is not None else [])
    return themes.resolve(settings, org, *layers, own_logo=own_logo).report()


async def _save_logo(db: DbDep, access: FormEditor, entry: dict[str, Any] | None) -> str | None:
    """Set (or with None remove) the form's own logo; returns the replaced object's key."""
    form = access.form
    old = form_logos.form_logo(form)
    rest = {k: v for k, v in (form.settings or {}).items() if k != form_logos.FORM_KEY}
    form.settings = {**rest, **({form_logos.FORM_KEY: entry} if entry else {})}
    flag_modified(form, "settings")
    await audit(
        db,
        "form.logo",
        org_id=form.org_id,
        actor_id=access.user.id,
        target_type="form",
        target_id=form.id,
        meta={"logo": "set" if entry else "removed"},
    )
    await db.commit()
    if old is not None and (entry is None or old.key != entry["key"]):
        return old.key
    return None


@router.put("/forms/{form_id}/logo", response_model=ThemeOut)
async def put_form_logo(
    request: Request, db: DbDep, settings: SettingsDep, storage: StorageDep, access: FormEditor
) -> ThemeOut:
    """The form's own logo, replacing the organisation's on its pages, emails and PDFs. The
    raw file as the request body (PNG or SVG, up to 512 KB), cleaned like branding logos."""
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > LOGO_MAX_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "too_large")
    try:
        img = clean_image("logo", bytes(raw))
    except BrandImageError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.code) from None
    entry = await form_logos.store(storage, access.form.id, img)
    replaced = await _save_logo(db, access, entry)
    if replaced:
        await form_logos.release(db, storage, replaced)
    return await _form_out(db, settings, access.form, can_edit=True)


@router.delete("/forms/{form_id}/logo", response_model=ThemeOut)
async def delete_form_logo(
    db: DbDep, settings: SettingsDep, storage: StorageDep, access: FormEditor
) -> ThemeOut:
    """Back to the organisation's logo."""
    replaced = await _save_logo(db, access, None)
    if replaced:
        await form_logos.release(db, storage, replaced)
    return await _form_out(db, settings, access.form, can_edit=True)


@router.put("/orgs/{org_id}/theme-images", response_model=ImageOut)
async def put_theme_image(
    org_id: uuid.UUID,
    request: Request,
    db: DbDep,
    storage: StorageDep,
    user: CurrentUser,
    _: OrgMember,
) -> ImageOut:
    """A header or background image (raw PNG, JPEG or WebP body), stored re-encoded as WebP.
    Any member may upload (form editors set images on their forms); saving a theme that uses
    it is what needs the right role."""
    org = await _org(db, org_id)
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > images.MAX_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "too_large")
    try:
        img = images.clean_image(bytes(raw))
    except images.ThemeImageError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.code) from None
    await storage.put(images.storage_key(org.id, img.ref), img.data, content_type="image/webp")
    await audit(
        db, "org.theme_image", org_id=org.id, actor_id=user.id, target_type="org", target_id=org.id
    )
    await db.commit()
    return ImageOut(
        ref=img.ref,
        url=themes.image_url(org.id, img.ref) or "",
        width=img.width,
        height=img.height,
    )


# -- public -----------------------------------------------------------------------------------


@public.get("/forms/{form_slug}/theme.css")
async def form_theme_css(
    form_slug: str, request: Request, db: DbDep, redis: RedisDep, settings: SettingsDep
) -> Response:
    """The form's theme as CSS variables (also for closed forms: approver and verify pages
    use it). Unknown forms get an empty stylesheet."""
    await ratelimit.enforce(redis, settings, "branding", client_ip(request, settings) or "-")
    form = await slugs.find_form(db, form_slug)
    org = await db.get(Organization, form.org_id) if form else None
    if form is None or org is None:
        return Response(
            "/* no theme */\n", media_type="text/css", headers={"Cache-Control": "no-cache"}
        )
    result = themes.for_form(settings, org, form, await _schema(db, form))
    etag = f'"{result.version}"'
    versioned = request.query_params.get("v") == result.version
    headers = {
        "Cache-Control": YEAR if versioned else "no-cache",
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }
    if not versioned and request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(result.css(), media_type="text/css", headers=headers)


@public.get("/theme-images/{org_id}/{ref}")
async def theme_image(
    org_id: uuid.UUID,
    ref: str,
    request: Request,
    redis: RedisDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> Response:
    await ratelimit.enforce(redis, settings, "branding", client_ip(request, settings) or "-")
    try:
        key = images.storage_key(org_id, ref)
    except images.ThemeImageError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None
    if not await storage.exists(key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    data = await storage.read(key)
    # Content-addressed: the name changes with the bytes.
    return Response(data, media_type="image/webp", headers={"Cache-Control": YEAR, **IMAGE_HEADERS})


@public.get("/form-logos/{form_id}/{name}")
async def form_logo_image(
    form_id: uuid.UUID,
    name: str,
    request: Request,
    redis: RedisDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> Response:
    """A form's own logo. Sandboxed like branding images and readable from other origins
    (mail clients); content-addressed, so cached for a year."""
    await ratelimit.enforce(redis, settings, "branding", client_ip(request, settings) or "-")
    try:
        key = form_logos.storage_key(form_id, name)
    except form_logos.BadName:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found") from None
    if not await storage.exists(key):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    data = await storage.read(key)
    return Response(
        data,
        media_type=form_logos.mime_for(name),
        headers={"Cache-Control": YEAR, **LOGO_HEADERS},
    )
