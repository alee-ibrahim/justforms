"""What a form's link preview shows, and its image (docs/ux/SHARING-PREVIEW-SCREENS.md).

Stored in ``forms.settings["sharing"]`` (not the versioned schema: it applies on save, like the
form theme)::

    {"title": str | None, "description": str | None,
     "image": {"key": "og/{form_id}/custom-{sha16}.jpg", "sha", "width", "height"} | None}

The title and description default to the live form's. The image is the owner's upload, else a
generated card (:mod:`app.sharing.image`) drawn from the shared title and description, the
organisation's name and logo (or the form's own logo) and the theme's colours. Generated images
are kept in storage under ``og/{form_id}/{version}.png``; ``version`` hashes everything that is
drawn, so publishing a new title or changing the branding or theme gives a new image and a new
URL, made on first request. The address of the image carries the version, so it is cached for a
year.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import re
import uuid
from dataclasses import dataclass, replace
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from redis.asyncio import Redis

from app.branding.service import Brand, image_bytes
from app.branding.service import resolve as resolve_brand
from app.config import Settings
from app.models import FormRecord, Organization
from app.pdf.faces import thaana_face
from app.sharing import image as og
from app.storage import ObjectNotFoundError, Storage
from app.theme import resolve as themes
from app.theme.colors import LIGHT
from app.theme.logo import form_logo

log = logging.getLogger(__name__)

FORM_KEY = "sharing"
TITLE_MAX = 120
DESCRIPTION_MAX = 300
# The meta description: what search results and link cards show before cutting it themselves.
META_DESCRIPTION_MAX = 200
UPLOAD_MAX_BYTES = 5 * 1024 * 1024
UPLOAD_MAX_SIDE = 8000
UPLOAD_FORMATS = {"PNG", "JPEG", "WEBP"}
TARGET_BYTES = 300 * 1024
CUSTOM_NAME = re.compile(r"^custom-[0-9a-f]{16}\.jpg$")
LOCALES = {"en": "en_US", "dv": "dv_MV"}


class ShareImageError(ValueError):
    """``code`` is the API error detail (the studio maps it to copy)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# -- stored values ----------------------------------------------------------------------------


def _clip(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:limit] or None


@dataclass(frozen=True)
class CustomImage:
    form_id: uuid.UUID
    key: str
    sha: str
    width: int
    height: int

    @property
    def version(self) -> str:
        return f"c{self.sha[:15]}"


@dataclass(frozen=True)
class Stored:
    title: str | None = None
    description: str | None = None
    image: CustomImage | None = None


def custom_key(form_id: uuid.UUID, sha: str) -> str:
    return f"og/{form_id}/custom-{sha[:16]}.jpg"


def stored(form: FormRecord) -> Stored:
    raw = (form.settings or {}).get(FORM_KEY)
    if not isinstance(raw, dict):
        return Stored()
    image = None
    img = raw.get("image")
    if isinstance(img, dict) and isinstance(img.get("sha"), str):
        key = custom_key(form.id, img["sha"])
        # Never another form's file (a copied settings blob).
        if img.get("key") == key and CUSTOM_NAME.match(key.rsplit("/", 1)[-1]):
            try:
                width, height = int(img.get("width", 0)), int(img.get("height", 0))
            except (TypeError, ValueError):
                width = height = 0
            image = CustomImage(form.id, key, img["sha"], width, height)
    return Stored(
        title=_clip(raw.get("title"), TITLE_MAX),
        description=_clip(raw.get("description"), DESCRIPTION_MAX),
        image=image,
    )


def with_values(form: FormRecord, **changes: Any) -> dict[str, Any]:
    """``forms.settings`` with the sharing entry updated (``None`` values are dropped)."""
    current = dict((form.settings or {}).get(FORM_KEY) or {})
    current.update(changes)
    current = {k: v for k, v in current.items() if v is not None}
    rest = {k: v for k, v in (form.settings or {}).items() if k != FORM_KEY}
    return {**rest, **({FORM_KEY: current} if current else {})}


# -- text -------------------------------------------------------------------------------------

_MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_MD_MARKS = re.compile(r"(\*\*|__|\*|_|~~|`+)")
_MD_LINE = re.compile(r"^\s{0,3}(#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)", re.MULTILINE)


def plain(text: str | None) -> str:
    """Markdown (form descriptions) as one line of plain text."""
    if not text:
        return ""
    out = _MD_LINK.sub(r"\1", text)
    out = _MD_LINE.sub("", out)
    out = _MD_MARKS.sub("", out)
    return " ".join(out.split())


def shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,.;:") + "…"


# -- the preview ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Preview:
    """Everything a link preview shows for one form."""

    form_id: uuid.UUID
    slug: str
    title: str
    description: str
    site_name: str
    language: str
    url: str  # canonical public address
    card: og.Card
    custom: CustomImage | None
    logo_version: str

    @property
    def locale(self) -> str:
        return LOCALES.get(self.language, "en_US")

    @property
    def version(self) -> str:
        """Changes whenever the image would look different."""
        if self.custom is not None:
            return self.custom.version
        c = self.card
        parts = [
            og.RENDER_VERSION,
            c.title,
            c.description or "",
            c.org_name,
            c.address,
            str(c.rtl),
            json.dumps(c.colors.__dict__, sort_keys=True),
            self.logo_version,
            c.thaana.version,
        ]
        return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]

    @property
    def generated_key(self) -> str:
        return f"og/{self.form_id}/{self.version}.png"

    @property
    def image_path(self) -> str:
        ext = "jpg" if self.custom is not None else "png"
        return f"/api/v1/public/forms/{self.slug}/og.{ext}?v={self.version}"


def _theme_colors(result: themes.ThemeResult) -> og.Colors:
    light = result.light()
    return og.Colors(
        background=light.get("--card", LIGHT["surface"]),
        text=light.get("--foreground", LIGHT["text"]),
        muted=light.get("--muted-foreground", LIGHT["muted_text"]),
        primary=result.colors.primary if result.colors.light else LIGHT["primary"],
        border=light.get("--border", LIGHT["border"]),
    )


def _logo(form: FormRecord | None, brand: Brand) -> tuple[str, Any]:
    """(version, source) of the logo the card shows: the form's own, else the organisation's
    logo, else its icon; ``("", None)`` for none."""
    own = form_logo(form)
    if own is not None:
        return f"f{own.sha[:16]}", own
    for kind in ("logo", "icon"):
        ref = brand.images.get(kind)
        if ref is not None:
            return f"{kind}{ref.sha[:16]}", (brand, kind, ref)
    return "", None


def _address(settings: Settings, slug: str | None) -> str:
    host = re.sub(r"^https?://", "", settings.public_origin)
    return f"{host}/{slug}" if slug else host


def build(
    settings: Settings,
    org: Organization | None,
    form: FormRecord,
    schema: dict[str, Any] | None,
) -> Preview:
    """The preview of ``form`` from ``schema`` (its live version; the draft in the studio for a
    form that was never published)."""
    brand = resolve_brand(settings, org)
    s = (schema or {}).get("settings", {}) or {}
    language = "dv" if s.get("language") == "dv" else "en"
    saved = stored(form)
    title = saved.title or " ".join(str(s.get("title") or form.title or "").split())
    title = title[:TITLE_MAX] or "Untitled form"
    description = saved.description or shorten(plain(s.get("description")), DESCRIPTION_MAX)
    colors = og.Colors()
    logo_version, _ = _logo(form, brand)
    if org is not None:
        theme = themes.for_form(settings, org, form, schema)
        colors = _theme_colors(theme)
        if theme.resolved.logo_placement == "hidden":
            logo_version = ""
    card = og.Card(
        title=title,
        description=description or None,
        org_name=brand.name,
        address=_address(settings, form.slug),
        rtl=language == "dv",
        colors=colors,
        thaana=thaana_face(settings, "image"),
    )
    return Preview(
        form_id=form.id,
        slug=form.slug,
        title=title,
        description=description,
        site_name=brand.name,
        language=language,
        url=f"{settings.public_origin}/{form.slug}",
        card=card,
        custom=saved.image,
        logo_version=logo_version,
    )


async def _logo_bytes(
    form: FormRecord | None, brand: Brand, storage: Storage, wanted: str
) -> tuple[bytes, tuple[int, int]] | None:
    version, source = _logo(form, brand)
    if source is None or not wanted or version != wanted:
        return None
    try:
        if isinstance(source, tuple):
            b, kind, ref = source
            found = await image_bytes(b, kind, storage)
            return (found[0], (ref.width, ref.height)) if found else None
        return await storage.read(source.key), (source.width, source.height)
    except (ObjectNotFoundError, OSError):
        log.warning("link preview: logo missing for form %s", getattr(form, "id", "-"))
        return None


async def _remember(redis: Redis | None, form_id: uuid.UUID, key: str, storage: Storage) -> None:
    """Delete the previous generated image of the form (best effort)."""
    if redis is None:
        return
    try:
        previous = await redis.getset(f"og:last:{form_id}", key)
    except Exception:  # pragma: no cover - Redis trouble only skips the clean-up
        return
    if isinstance(previous, bytes):
        previous = previous.decode()
    if previous and previous != key and previous.startswith(f"og/{form_id}/"):
        await storage.delete(previous)


async def image(
    settings: Settings,
    org: Organization | None,
    form: FormRecord,
    preview: Preview,
    storage: Storage,
    redis: Redis | None = None,
) -> tuple[bytes, str]:
    """(bytes, mime) of the preview image: the upload, or the generated card (made and stored
    on first use)."""
    if preview.custom is not None:
        try:
            return await storage.read(preview.custom.key), "image/jpeg"
        except ObjectNotFoundError:
            log.warning("link preview: uploaded image missing for form %s", form.id)
    key = preview.generated_key
    try:
        return await storage.read(key), "image/png"
    except ObjectNotFoundError:
        pass
    brand = resolve_brand(settings, org)
    logo = await _logo_bytes(form, brand, storage, preview.logo_version)
    card = preview.card
    if logo is not None:
        card = replace(card, logo=logo[0], logo_size=logo[1])
    data = await asyncio.to_thread(og.render, card)
    await storage.put(key, data, content_type="image/png")
    await _remember(redis, form.id, key, storage)
    return data, "image/png"


# -- site-wide card (unknown and unpublished forms) -------------------------------------------


@dataclass(frozen=True)
class SitePreview:
    site_name: str
    url: str
    card: og.Card
    logo_version: str

    @property
    def version(self) -> str:
        c = self.card
        parts = [og.RENDER_VERSION, c.title, c.address, self.logo_version, c.thaana.version]
        return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]

    @property
    def image_path(self) -> str:
        return f"/api/v1/public/og/site.png?v={self.version}"


def build_site(settings: Settings, org: Organization | None) -> SitePreview:
    brand = resolve_brand(settings, org)
    logo_version, _ = _logo(None, brand)
    colors = og.Colors(primary=brand.palette.light.primary) if brand.palette else og.Colors()
    card = og.Card(
        title=brand.name,
        description=None,
        org_name="",
        address=_address(settings, None),
        rtl=og.is_thaana(brand.name),
        colors=colors,
        thaana=thaana_face(settings, "image"),
    )
    return SitePreview(brand.name, f"{settings.public_origin}/", card, logo_version)


async def site_image(
    settings: Settings, org: Organization | None, preview: SitePreview, storage: Storage
) -> bytes:
    key = f"og/site/{preview.version}.png"
    try:
        return await storage.read(key)
    except ObjectNotFoundError:
        pass
    brand = resolve_brand(settings, org)
    logo = await _logo_bytes(None, brand, storage, preview.logo_version)
    card = preview.card
    if logo is not None:
        card = replace(card, logo=logo[0], logo_size=logo[1])
    data = await asyncio.to_thread(og.render, card)
    await storage.put(key, data, content_type="image/png")
    return data


# -- uploads ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class CleanUpload:
    data: bytes
    sha: str
    width: int
    height: int


def clean_upload(raw: bytes) -> CleanUpload:
    """Decode a PNG, JPEG or WebP, crop it to 1.91:1 from the centre, scale it to 1200x630 (or
    smaller, never up) and re-encode it as a JPEG under ~300 KB. Metadata is dropped."""
    if len(raw) > UPLOAD_MAX_BYTES:
        raise ShareImageError("too_large")
    if not raw:
        raise ShareImageError("bad_type")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            if probe.format not in UPLOAD_FORMATS:
                raise ShareImageError("bad_type")
            w, h = probe.size
            if w > UPLOAD_MAX_SIDE or h > UPLOAD_MAX_SIDE or w < 1 or h < 1:
                raise ShareImageError("too_large_pixels")
            probe.verify()
        with Image.open(io.BytesIO(raw)) as opened:
            opened.load()
            img: Image.Image = ImageOps.exif_transpose(opened)
            if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
                rgba = img.convert("RGBA")
                flat = Image.new("RGB", rgba.size, "#FFFFFF")
                flat.paste(rgba, mask=rgba.getchannel("A"))
                img = flat
            else:
                img = img.convert("RGB")
    except ShareImageError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ShareImageError("bad_type") from exc
    if img.width < 200 or img.height < 105:
        raise ShareImageError("too_small")
    ratio = og.WIDTH / og.HEIGHT
    w, h = img.size
    if w / h > ratio:
        new_w = round(h * ratio)
        img = img.crop(((w - new_w) // 2, 0, (w - new_w) // 2 + new_w, h))
    else:
        new_h = round(w / ratio)
        img = img.crop((0, (h - new_h) // 2, w, (h - new_h) // 2 + new_h))
    if img.width > og.WIDTH:
        img = img.resize((og.WIDTH, og.HEIGHT), Image.Resampling.LANCZOS)
    data = b""
    for quality in (88, 82, 75, 68, 60):
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
        data = out.getvalue()
        if len(data) <= TARGET_BYTES:
            break
    return CleanUpload(data, hashlib.sha256(data).hexdigest(), img.width, img.height)
