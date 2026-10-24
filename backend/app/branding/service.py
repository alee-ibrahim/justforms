"""Effective branding: an organisation's settings over the instance defaults over JustForms.

Stored in ``organizations.settings["branding"]``::

    {"displayName": str | None, "primaryColor": "#RRGGBB" | None, "supportUrl": str | None,
     "hidePoweredBy": bool,
     "images": {"logo": {"key", "mime", "sha", "width", "height"}, "logo_dark": ..., "icon": ...}}

Instance defaults come from ``JUSTFORMS_BRAND_*`` (``app/config.py``); their image files are read,
validated and cleaned like uploads and cached by modification time. The sign-in page and other
places without an organisation use the default organisation (``JUSTFORMS_DEFAULT_ORG_SLUG``),
reached through the pseudo-slug ``_``.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.branding.colors import HEX, Palette, palette
from app.branding.images import KINDS, BrandImageError, CleanImage, Kind, clean_image
from app.config import Settings
from app.models import Organization
from app.storage import Storage

log = logging.getLogger(__name__)

JUSTFORMS = "JustForms"
INSTANCE_SLUG = "_"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SUPPORT_URL = re.compile(r"^(https://[^\s<>\"']{3,}|mailto:[^\s<>\"']{3,})$")


@dataclass(frozen=True)
class ImageRef:
    mime: str
    sha: str
    width: int
    height: int
    key: str | None = None  # storage key (organisation uploads)
    path: Path | None = None  # instance file


@dataclass
class Brand:
    slug: str  # org slug or "_"
    name: str
    primary: str | None
    support_url: str | None
    powered_by: bool
    can_hide_powered_by: bool
    images: dict[str, ImageRef] = field(default_factory=dict)

    @property
    def palette(self) -> Palette | None:
        return palette(self.primary) if self.primary else None

    @property
    def version(self) -> str:
        parts = [self.name, self.primary or "", self.support_url or "", str(self.powered_by)]
        parts += [f"{k}:{v.sha}" for k, v in sorted(self.images.items())]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]

    @property
    def custom(self) -> bool:
        return bool(self.images or self.primary or self.name != JUSTFORMS)

    def image_url(self, kind: str) -> str | None:
        ref = self.images.get(kind)
        if ref is None:
            return None
        return f"/api/v1/public/branding/{self.slug}/{kind}?v={ref.sha[:12]}"

    def public(self) -> dict[str, Any]:
        """What pages need: names, same-origin URLs, flags. No storage keys or paths."""
        return {
            "name": self.name,
            "custom": self.custom,
            "logoUrl": self.image_url("logo"),
            "logoDarkUrl": self.image_url("logo_dark"),
            "iconUrl": self.image_url("icon"),
            "supportUrl": self.support_url,
            "poweredBy": self.powered_by,
            "themeUrl": (
                f"/api/v1/public/branding/{self.slug}/theme.css?v={self.version}"
                if self.primary
                else None
            ),
            "manifestUrl": (
                f"/api/v1/public/branding/{self.slug}/manifest.webmanifest?v={self.version}"
            ),
            "version": self.version,
        }


def stored(org: Organization | None) -> dict[str, Any]:
    raw = (org.settings or {}).get("branding") if org is not None else None
    return raw if isinstance(raw, dict) else {}


# -- instance files ---------------------------------------------------------------------------

_instance_cache: dict[Path, tuple[float, CleanImage | None]] = {}


def instance_image(path: Path | None, kind: Kind) -> CleanImage | None:
    if path is None:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        log.warning("branding file %s is missing", path)
        return None
    hit = _instance_cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    img: CleanImage | None
    try:
        img = clean_image(kind, path.read_bytes())
    except BrandImageError as exc:
        log.warning("branding file %s refused: %s", path, exc.code)
        img = None
    _instance_cache[path] = (mtime, img)
    return img


def _instance_files(settings: Settings) -> dict[str, Path | None]:
    return {
        "logo": settings.brand_logo_file,
        "logo_dark": settings.brand_logo_dark_file,
        "icon": settings.brand_icon_file,
    }


# -- resolution -------------------------------------------------------------------------------


def resolve(settings: Settings, org: Organization | None, slug: str | None = None) -> Brand:
    b = stored(org)
    images: dict[str, ImageRef] = {}
    org_images = b.get("images") if isinstance(b.get("images"), dict) else {}
    for kind in KINDS:
        ref = org_images.get(kind) if org_images else None
        if isinstance(ref, dict) and ref.get("key"):
            images[kind] = ImageRef(
                mime=ref["mime"],
                sha=ref["sha"],
                width=int(ref.get("width", 0)),
                height=int(ref.get("height", 0)),
                key=ref["key"],
            )
            continue
        path = _instance_files(settings)[kind]
        img = instance_image(path, kind)
        if img is not None and path is not None:
            images[kind] = ImageRef(
                mime=img.mime,
                sha=hashlib.sha256(img.data).hexdigest(),
                width=img.width,
                height=img.height,
                path=path,
            )
    primary = b.get("primaryColor") or settings.brand_primary_color
    if primary and not HEX.match(primary):
        log.warning("ignoring invalid brand colour %r", primary)
        primary = None
    always = settings.brand_powered_by == "always"
    name = (
        (b.get("displayName") or "").strip()
        or settings.brand_name.strip()
        or (org.name if org is not None else "")
        or JUSTFORMS
    )
    return Brand(
        slug=slug or (org.slug if org is not None else INSTANCE_SLUG),
        name=name,
        primary=primary.upper() if primary else None,
        support_url=b.get("supportUrl") or settings.brand_support_url,
        powered_by=always or not bool(b.get("hidePoweredBy")),
        can_hide_powered_by=not always,
        images=images,
    )


async def org_by_slug(db: AsyncSession, settings: Settings, slug: str) -> Organization | None:
    target = settings.default_org_slug if slug == INSTANCE_SLUG else slug
    return await db.scalar(select(Organization).where(Organization.slug == target))


async def brand_for_slug(db: AsyncSession, settings: Settings, slug: str) -> Brand | None:
    """``None`` for an unknown organisation (the instance slug always resolves)."""
    org = await org_by_slug(db, settings, slug)
    if org is None and slug != INSTANCE_SLUG:
        return None
    return resolve(settings, org, slug)


async def brand_for_org_id(db: AsyncSession, settings: Settings, org_id: uuid.UUID | None) -> Brand:
    org = await db.get(Organization, org_id) if org_id else None
    return resolve(settings, org)


async def image_bytes(brand: Brand, kind: str, storage: Storage) -> tuple[bytes, str] | None:
    ref = brand.images.get(kind)
    if ref is None:
        return None
    if ref.key:
        return await storage.read(ref.key), ref.mime
    if ref.path:
        img = instance_image(ref.path, kind)  # type: ignore[arg-type]
        return (img.data, img.mime) if img else None
    return None


def manifest(brand: Brand) -> dict[str, Any]:
    icons: list[dict[str, str]] = []
    icon = brand.images.get("icon")
    if icon is not None:
        size = "any" if icon.mime == "image/svg+xml" else f"{icon.width}x{icon.height}"
        icons.append({"src": brand.image_url("icon") or "", "sizes": size, "type": icon.mime})
    else:
        icons = [
            {"src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml"},
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ]
    pal = brand.palette
    return {
        "name": brand.name,
        "short_name": brand.name[:12],
        "start_url": "/forms",
        "scope": "/",
        "display": "standalone",
        "background_color": "#F3F5F9",
        "theme_color": pal.light.primary if pal else "#F3F5F9",
        "icons": icons,
    }


def valid_support_url(value: str) -> bool:
    return len(value) <= 300 and bool(SUPPORT_URL.match(value))


def email_brand(settings: Settings, brand: Brand) -> Any:
    """The email view of ``brand`` (``app.notifications.emails.EmailBrand``)."""
    from app.notifications.emails import EmailBrand

    pal = brand.palette
    logo = None
    for kind in ("logo", "icon"):
        ref = brand.images.get(kind)
        if ref is not None and ref.mime == "image/png":
            logo = f"{settings.public_origin}{brand.image_url(kind)}"
            break
    return EmailBrand(
        name=brand.name,
        logo_url=logo,
        support_url=brand.support_url,
        powered_by=brand.powered_by,
        custom=brand.custom,
        button_bg=pal.light.primary if pal else "#3B3FC1",
        button_fg=pal.light.foreground if pal else "#FFFFFF",
    )
