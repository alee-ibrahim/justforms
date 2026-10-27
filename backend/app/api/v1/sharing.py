"""Link previews (docs/ux/SHARING-PREVIEW-SCREENS.md).

Staff: a form's share title, description and image (viewers read, editors change), and the
image itself for the studio's preview (also before the form is published). Public: the image
for published forms and a site-wide card for everything else, served from this origin with a
year's cache for the versioned address. The page tags themselves go out through
``GET /public/frame-ancestors`` (:func:`page_head`), which the web server already asks for every
public form page.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app import ratelimit
from app.api.v1.common import ApiModel
from app.auth.deps import DbDep, RedisDep, SettingsDep, StorageDep
from app.branding.service import org_by_slug
from app.config import Settings
from app.models import FormRecord, FormRole, FormStatus, FormVersion, Organization
from app.net import client_ip
from app.permissions import FormEditor, FormViewer, has_form_role
from app.services import slugs
from app.services.users import audit
from app.sharing import meta
from app.sharing import service as sharing

log = logging.getLogger(__name__)

router = APIRouter(tags=["sharing"])
public = APIRouter(prefix="/public", tags=["sharing"])

YEAR = "public, max-age=31536000, immutable"
SHORT = "public, max-age=300"
IMAGE_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "X-Content-Type-Options": "nosniff",
    # Link-preview services and chat apps fetch it from their own origins.
    "Cross-Origin-Resource-Policy": "cross-origin",
}

ShareTitle = Annotated[str, StringConstraints(max_length=sharing.TITLE_MAX)]
ShareDescription = Annotated[str, StringConstraints(max_length=sharing.DESCRIPTION_MAX)]


class SharingIn(ApiModel):
    title: ShareTitle | None = None
    description: ShareDescription | None = None


class CustomImageOut(ApiModel):
    width: int
    height: int


class SharingOut(ApiModel):
    # Saved overrides (None: the form's own).
    title: str | None
    description: str | None
    # What the preview shows now.
    effective_title: str
    effective_description: str
    default_title: str
    default_description: str
    site_name: str
    url: str
    language: str
    image_url: str  # same-origin, for the studio preview
    custom_image: CustomImageOut | None
    published: bool
    can_edit: bool


async def _live_schema(db: AsyncSession, form: FormRecord) -> dict[str, Any] | None:
    if form.current_version_id is None:
        return None
    version = await db.get(FormVersion, form.current_version_id)
    return version.schema if version is not None else None


async def _studio_preview(
    db: AsyncSession, settings: Settings, form: FormRecord
) -> tuple[Organization | None, sharing.Preview, dict[str, Any]]:
    """The preview from the live version, or from the draft before the first publish."""
    org = await db.get(Organization, form.org_id)
    schema = await _live_schema(db, form) or form.draft_schema
    return org, sharing.build(settings, org, form, schema), schema


async def _out(
    db: AsyncSession, settings: Settings, form: FormRecord, can_edit: bool
) -> SharingOut:
    _, preview, schema = await _studio_preview(db, settings, form)
    saved = sharing.stored(form)
    s = (schema or {}).get("settings", {}) or {}
    default_title = " ".join(str(s.get("title") or form.title or "").split())
    default_desc = sharing.shorten(sharing.plain(s.get("description")), sharing.DESCRIPTION_MAX)
    return SharingOut(
        title=saved.title,
        description=saved.description,
        effective_title=preview.title,
        effective_description=preview.description,
        default_title=default_title,
        default_description=default_desc,
        site_name=preview.site_name,
        url=preview.url,
        language=preview.language,
        image_url=f"/api/v1/forms/{form.id}/sharing/image?v={preview.version}",
        custom_image=(
            CustomImageOut(width=saved.image.width, height=saved.image.height)
            if saved.image
            else None
        ),
        published=form.current_version_id is not None,
        can_edit=can_edit,
    )


@router.get("/forms/{form_id}/sharing", response_model=SharingOut)
async def get_sharing(db: DbDep, settings: SettingsDep, access: FormViewer) -> SharingOut:
    return await _out(db, settings, access.form, has_form_role(access.role, FormRole.EDITOR))


async def _save(db: AsyncSession, access: Any, action: str, **changes: Any) -> None:
    form = access.form
    form.settings = sharing.with_values(form, **changes)
    flag_modified(form, "settings")
    await audit(
        db,
        action,
        org_id=form.org_id,
        actor_id=access.user.id,
        target_type="form",
        target_id=form.id,
    )
    await db.commit()


@router.put("/forms/{form_id}/sharing", response_model=SharingOut)
async def put_sharing(
    body: SharingIn, db: DbDep, settings: SettingsDep, access: FormEditor
) -> SharingOut:
    """The share title and description; empty values go back to the form's own."""
    title = " ".join((body.title or "").split()) or None
    description = " ".join((body.description or "").split()) or None
    await _save(db, access, "form.sharing", title=title, description=description)
    return await _out(db, settings, access.form, can_edit=True)


@router.put("/forms/{form_id}/sharing/image", response_model=SharingOut)
async def put_sharing_image(
    request: Request, db: DbDep, settings: SettingsDep, storage: StorageDep, access: FormEditor
) -> SharingOut:
    """An uploaded preview image (raw PNG, JPEG or WebP body, up to 5 MB), cropped to 1.91:1,
    scaled to 1200x630 and re-encoded as JPEG."""
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > sharing.UPLOAD_MAX_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "too_large")
    try:
        img = await _clean(bytes(raw))
    except sharing.ShareImageError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.code) from None
    form = access.form
    old = sharing.stored(form).image
    key = sharing.custom_key(form.id, img.sha)
    await storage.put(key, img.data, content_type="image/jpeg")
    entry = {"key": key, "sha": img.sha, "width": img.width, "height": img.height}
    await _save(db, access, "form.sharing_image", image=entry)
    if old is not None and old.key != key:
        await storage.delete(old.key)
    return await _out(db, settings, form, can_edit=True)


async def _clean(raw: bytes) -> sharing.CleanUpload:
    return await asyncio.to_thread(sharing.clean_upload, raw)


@router.delete("/forms/{form_id}/sharing/image", response_model=SharingOut)
async def delete_sharing_image(
    db: DbDep, settings: SettingsDep, storage: StorageDep, access: FormEditor
) -> SharingOut:
    """Back to the generated image."""
    old = sharing.stored(access.form).image
    await _save(db, access, "form.sharing_image", image=None)
    if old is not None:
        await storage.delete(old.key)
    return await _out(db, settings, access.form, can_edit=True)


def _image_response(
    request: Request, data: bytes, mime: str, version: str, *, cache: str
) -> Response:
    etag = f'"{version}"'
    headers = {"Cache-Control": cache, "ETag": etag, **IMAGE_HEADERS}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(data, media_type=mime, headers=headers)


@router.get("/forms/{form_id}/sharing/image")
async def studio_image(
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    storage: StorageDep,
    access: FormViewer,
) -> Response:
    """The preview image as it is now (the draft's title before the form is published)."""
    org, preview, _ = await _studio_preview(db, settings, access.form)
    data, mime = await sharing.image(settings, org, access.form, preview, storage, redis)
    versioned = request.query_params.get("v") == preview.version
    cache = "private, max-age=31536000, immutable" if versioned else "private, no-cache"
    return _image_response(request, data, mime, preview.version, cache=cache)


# -- public -----------------------------------------------------------------------------------


def alias_redirect(request: Request, old: str, new: str) -> RedirectResponse:
    """301 from a form's earlier address (an alias) to the same API path under its current
    slug, query kept. Revalidated on every use: the owner may take the old address back."""
    parts = request.url.path.split("/")
    for i in range(1, len(parts)):
        if parts[i - 1] == "forms" and parts[i] == old:
            parts[i] = new
            break
    query = request.url.query
    url = "/".join(parts) + (f"?{query}" if query else "")
    return RedirectResponse(url, status_code=301, headers={"Cache-Control": "no-cache"})


async def _public_form(db: AsyncSession, form_slug: str) -> FormRecord | None:
    """A published form (closed ones too: their address still gets shared), also by an
    earlier address."""
    form = await slugs.find_form(db, form_slug)
    if form is None or form.current_version_id is None:
        return None
    if form.status == FormStatus.ARCHIVED:
        return None
    return form


@public.get("/forms/{form_slug}/og.png")
@public.get("/forms/{form_slug}/og.jpg")
async def public_image(
    form_slug: str,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> Response:
    await ratelimit.enforce(redis, settings, "branding", client_ip(request, settings) or "-")
    form = await _public_form(db, form_slug)
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    if form.slug != form_slug:
        return alias_redirect(request, form_slug, form.slug)
    org = await db.get(Organization, form.org_id)
    preview = sharing.build(settings, org, form, await _live_schema(db, form))
    data, mime = await sharing.image(settings, org, form, preview, storage, redis)
    versioned = request.query_params.get("v") == preview.version
    return _image_response(request, data, mime, preview.version, cache=YEAR if versioned else SHORT)


@public.get("/og/site.png")
async def site_image(
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> Response:
    """The card for the site itself (unknown and unpublished form addresses)."""
    await ratelimit.enforce(redis, settings, "branding", client_ip(request, settings) or "-")
    org = await org_by_slug(db, settings, "_")
    preview = sharing.build_site(settings, org)
    data = await sharing.site_image(settings, org, preview, storage)
    versioned = request.query_params.get("v") == preview.version
    return _image_response(
        request, data, "image/png", preview.version, cache=YEAR if versioned else SHORT
    )


async def page_head(db: AsyncSession, settings: Settings, form: FormRecord | None) -> str:
    """The ``<head>`` tags for a public form address (see :mod:`app.sharing.meta`)."""
    origin = settings.public_origin
    if (
        form is not None
        and form.current_version_id is not None
        and form.status != FormStatus.ARCHIVED
    ):
        org = await db.get(Organization, form.org_id)
        schema = await _live_schema(db, form)
        return meta.form_head(sharing.build(settings, org, form, schema), origin)
    org = await org_by_slug(db, settings, "_")
    return meta.site_head(sharing.build_site(settings, org), origin)
