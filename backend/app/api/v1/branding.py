"""Organisation branding (docs/ux/BRANDING-SCREENS.md, DESIGN 18.2).

Staff endpoints (``/orgs/{org_id}/branding``): members read, admins change. Public endpoints
(``/public/branding/{slug}``, ``_`` = the default organisation) serve what every page needs:
the effective branding, its theme stylesheet, the images and a web app manifest. Images are
served from this origin with a sandboxing CSP, so a logo can never run script even when opened
directly.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import Field, StringConstraints, field_validator
from sqlalchemy.orm.attributes import flag_modified

from app import ratelimit
from app.api.v1.common import ApiModel
from app.auth.deps import CurrentUser, DbDep, RedisDep, SettingsDep, StorageDep
from app.branding import service
from app.branding.colors import HEX, palette
from app.branding.images import KINDS, MAX_BYTES, BrandImageError, Kind, clean_image
from app.models import Organization
from app.net import client_ip
from app.permissions import OrgAdmin, OrgMember
from app.services.users import audit

router = APIRouter(tags=["branding"])
public = APIRouter(prefix="/public/branding", tags=["branding"])

IMAGE_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    "X-Content-Type-Options": "nosniff",
    # Logos are public and shown in mail clients on other origins.
    "Cross-Origin-Resource-Policy": "cross-origin",
}
YEAR = "public, max-age=31536000, immutable"
SHORT = "public, max-age=300"


class BrandingIn(ApiModel):
    display_name: Annotated[str, StringConstraints(max_length=80, strip_whitespace=True)] = ""
    primary_color: str | None = None
    support_url: Annotated[str, StringConstraints(max_length=300, strip_whitespace=True)] = ""
    hide_powered_by: bool = False

    @field_validator("primary_color")
    @classmethod
    def _hex(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return None
        if not HEX.match(v):
            raise ValueError("invalid_color")
        return v.upper()

    @field_validator("support_url")
    @classmethod
    def _link(cls, v: str) -> str:
        if v and not service.valid_support_url(v):
            raise ValueError("invalid_support_url")
        return v


class ImageOut(ApiModel):
    url: str
    mime: str
    width: int
    height: int
    own: bool  # uploaded by the organisation (else the instance default)


class BrandingOut(ApiModel):
    display_name: str
    primary_color: str | None
    support_url: str
    hide_powered_by: bool
    images: dict[str, ImageOut | None]
    can_hide_powered_by: bool
    can_edit: bool
    effective: dict[str, Any]
    palette: dict[str, Any] | None
    instance: dict[str, Any] = Field(default_factory=dict)


def _out(settings: Any, org: Organization, can_edit: bool) -> BrandingOut:
    b = service.stored(org)
    brand = service.resolve(settings, org)
    raw = b.get("images")
    own: dict[str, Any] = raw if isinstance(raw, dict) else {}
    images: dict[str, ImageOut | None] = {}
    for kind in KINDS:
        ref = brand.images.get(kind)
        url = brand.image_url(kind)
        images[kind] = (
            ImageOut(url=url, mime=ref.mime, width=ref.width, height=ref.height, own=kind in own)
            if ref is not None and url
            else None
        )
    pal = brand.palette
    return BrandingOut(
        display_name=b.get("displayName") or "",
        primary_color=b.get("primaryColor"),
        support_url=b.get("supportUrl") or "",
        hide_powered_by=bool(b.get("hidePoweredBy")),
        images=images,
        can_hide_powered_by=brand.can_hide_powered_by,
        can_edit=can_edit,
        effective=brand.public(),
        palette=pal.report() if pal else None,
        instance={
            "name": settings.brand_name or org.name or service.JUSTFORMS,
            "primaryColor": settings.brand_primary_color,
            "supportUrl": settings.brand_support_url,
        },
    )


async def _org(db: DbDep, org_id: uuid.UUID) -> Organization:
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "org_not_found")
    return org


def _save(org: Organization, branding: dict[str, Any]) -> None:
    org.settings = {**(org.settings or {}), "branding": branding}
    flag_modified(org, "settings")


@router.get("/orgs/{org_id}/branding", response_model=BrandingOut)
async def get_branding(
    org_id: uuid.UUID, db: DbDep, settings: SettingsDep, role: OrgMember
) -> BrandingOut:
    org = await _org(db, org_id)
    return _out(settings, org, can_edit=role.value == "admin")


@router.put("/orgs/{org_id}/branding", response_model=BrandingOut)
async def put_branding(
    org_id: uuid.UUID,
    body: BrandingIn,
    db: DbDep,
    settings: SettingsDep,
    user: CurrentUser,
    _: OrgAdmin,
) -> BrandingOut:
    org = await _org(db, org_id)
    current = service.stored(org)
    _save(
        org,
        {
            **current,
            "displayName": body.display_name or None,
            "primaryColor": body.primary_color,
            "supportUrl": body.support_url or None,
            "hidePoweredBy": body.hide_powered_by,
        },
    )
    await audit(
        db, "org.branding", org_id=org.id, actor_id=user.id, target_type="org", target_id=org.id
    )
    await db.commit()
    return _out(settings, org, can_edit=True)


@router.put("/orgs/{org_id}/branding/images/{kind}", response_model=BrandingOut)
async def put_image(
    org_id: uuid.UUID,
    kind: Kind,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: CurrentUser,
    _: OrgAdmin,
) -> BrandingOut:
    """The raw file as the request body (``image/png`` or ``image/svg+xml``)."""
    org = await _org(db, org_id)
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > MAX_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "too_large")
    try:
        img = clean_image(kind, bytes(raw))
    except BrandImageError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.code) from None
    sha = hashlib.sha256(img.data).hexdigest()
    key = f"branding/{org.id}/{kind}-{sha[:16]}.{img.ext}"
    await storage.put(key, img.data, content_type=img.mime)
    current = service.stored(org)
    images = dict(current.get("images") or {})
    old = images.get(kind)
    images[kind] = {
        "key": key,
        "mime": img.mime,
        "sha": sha,
        "width": img.width,
        "height": img.height,
    }
    _save(org, {**current, "images": images})
    await audit(
        db,
        "org.branding_image",
        org_id=org.id,
        actor_id=user.id,
        target_type="org",
        target_id=org.id,
    )
    await db.commit()
    if isinstance(old, dict) and old.get("key") and old["key"] != key:
        await storage.delete(old["key"])
    return _out(settings, org, can_edit=True)


@router.delete("/orgs/{org_id}/branding/images/{kind}", response_model=BrandingOut)
async def delete_image(
    org_id: uuid.UUID,
    kind: Kind,
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    user: CurrentUser,
    _: OrgAdmin,
) -> BrandingOut:
    org = await _org(db, org_id)
    current = service.stored(org)
    images = dict(current.get("images") or {})
    old = images.pop(kind, None)
    _save(org, {**current, "images": images})
    await audit(
        db,
        "org.branding_image",
        org_id=org.id,
        actor_id=user.id,
        target_type="org",
        target_id=org.id,
    )
    await db.commit()
    if isinstance(old, dict) and old.get("key"):
        await storage.delete(old["key"])
    return _out(settings, org, can_edit=True)


@router.get("/branding/palette")
async def preview_palette(color: str, _: CurrentUser) -> dict[str, Any]:
    """Tokens and contrast report for a colour (the Settings live preview)."""
    if not HEX.match(color):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_color")
    pal = palette(color)
    return {**pal.report(), "lightTokens": pal.light.tokens(), "darkTokens": pal.dark.tokens()}


# -- public ---------------------------------------------------------------------------------


async def _brand(
    slug: str, request: Request, db: DbDep, redis: RedisDep, settings: SettingsDep
) -> service.Brand:
    await ratelimit.enforce(redis, settings, "branding", client_ip(request, settings) or "-")
    if slug != service.INSTANCE_SLUG and not service.SLUG.match(slug):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    brand = await service.brand_for_slug(db, settings, slug)
    if brand is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return brand


@public.get("/{slug}")
async def public_branding(
    slug: str, request: Request, db: DbDep, redis: RedisDep, settings: SettingsDep
) -> Response:
    brand = await _brand(slug, request, db, redis, settings)
    return Response(
        json.dumps(brand.public()),
        media_type="application/json",
        headers={"Cache-Control": "no-cache"},
    )


@public.get("/{slug}/theme.css")
async def theme_css(
    slug: str, request: Request, db: DbDep, redis: RedisDep, settings: SettingsDep
) -> Response:
    brand = await _brand(slug, request, db, redis, settings)
    pal = brand.palette
    body = pal.css() if pal else "/* no brand colour */\n"
    cache = YEAR if request.query_params.get("v") == brand.version else SHORT
    return Response(body, media_type="text/css", headers={"Cache-Control": cache, **IMAGE_HEADERS})


@public.get("/{slug}/manifest.webmanifest")
async def web_manifest(
    slug: str, request: Request, db: DbDep, redis: RedisDep, settings: SettingsDep
) -> Response:
    brand = await _brand(slug, request, db, redis, settings)
    return Response(
        json.dumps(service.manifest(brand)),
        media_type="application/manifest+json",
        headers={"Cache-Control": SHORT},
    )


@public.get("/{slug}/{kind}")
async def brand_image(
    slug: str,
    kind: Kind,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> Response:
    brand = await _brand(slug, request, db, redis, settings)
    found = await service.image_bytes(brand, kind, storage)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    data, mime = found
    ref = brand.images[kind]
    cache = YEAR if request.query_params.get("v") == ref.sha[:12] else SHORT
    return Response(data, media_type=mime, headers={"Cache-Control": cache, **IMAGE_HEADERS})
