"""The form's logo (Jotform's cover image), for the form import (DESIGN 13.1).

A Jotform form shows its logo as the page cover (``<div id="formCoverLogo">`` with an
``<img class="form-page-cover-image">``) or, in older themes, as a header image
(``<img class="header-logo-top">`` inside ``.header-logo``). The API path reads the same
picture from the form's properties when they carry one (best effort).

The file is downloaded while the preview is made, so the report is accurate before a draft
exists:

- ``https`` only, and only from Jotform's upload/CDN hosts (:data:`ALLOWED_HOSTS`);
- every address is resolved and checked by the SSRF guard (``app.notifications.ssrf``) and
  the connection goes to the checked address; redirects are followed by hand, at most
  :data:`MAX_REDIRECTS`, each hop checked again;
- 10 seconds and :data:`MAX_BYTES` (512 KB) at most.

It is then cleaned like a branding logo (``clean_image("logo", ...)``: PNG decoded and
re-encoded, SVG rebuilt from an allow-list). Jotform logos are often JPEG (sometimes WebP or
GIF): rather than refusing them, those are decoded with Pillow, scaled down to at most
:data:`CONVERT_MAX_SIDE` px a side and re-encoded as PNG (first frame for animations), then
cleaned the same way; if the PNG would be over 512 KB it is scaled down further.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from app.branding.images import MAX_BYTES, MAX_SIDE, BrandImageError, CleanImage, clean_image
from app.config import Settings
from app.importers.dom import Node
from app.notifications.ssrf import UrlRefused, resolve

ALLOWED_HOSTS = frozenset(
    {
        # Uploaded form files are served from the account's Jotform host ...
        "www.jotform.com",
        "jotform.com",
        "form.jotform.com",
        "eu.jotform.com",
        "www.jotformeu.com",
        "form.jotformeu.com",
        "hipaa.jotform.com",
        "form.jotform.me",
        # ... and from Jotform's file and CDN hosts.
        "files.jotform.com",
        "cdn.jotfor.ms",
    }
)
MAX_REDIRECTS = 3
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
USER_AGENT = "JustForms-Importer/1.0 (+form import)"
CONVERT_FORMATS = {"JPEG", "WEBP", "GIF"}
CONVERT_MAX_SIDE = 1024

REASONS = {
    "host": "The logo is on a host JustForms doesn't download from.",
    "too_large": "The logo is larger than 512 KB.",
    "bad_type": "The logo isn't a PNG, SVG, JPEG, WebP or GIF image.",
    "svg_unsafe": "The logo is an SVG with content JustForms doesn't allow (such as scripts).",
    "svg_no_size": "The logo is an SVG without a size.",
    "too_large_pixels": "The logo is larger than 4096 pixels a side.",
    "fetch": "The logo couldn't be downloaded.",
}


class LogoError(Exception):
    """``code``: a key of :data:`REASONS`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class LogoResult:
    image: CleanImage | None
    report: dict[str, Any]


def report(status: str, reason: str | None = None, source: str | None = None) -> dict[str, Any]:
    return {"status": status, "reason": reason, "source": source}


# -- finding it ------------------------------------------------------------------------------


def find_logo_url(root: Node) -> str | None:
    """The ``src`` of the form's cover/header logo in Jotform's HTML, as written."""

    def cover(n: Node) -> bool:
        if n.tag != "img" or not n.get("src").strip():
            return False
        if n.has_class("form-page-cover-image") or n.has_class("header-logo-top"):
            return True
        parent = n.parent
        while parent is not None:
            if parent.id == "formCoverLogo" or parent.has_class("header-logo"):
                return True
            parent = parent.parent
        return False

    img = root.find(cover)
    return img.get("src").strip() if img is not None else None


API_KEYS = ("formCoverImg", "formCoverImage", "formImage", "formLogo", "logo", "headerImage")


def api_logo_url(properties: dict[str, Any]) -> str | None:
    """Best effort: the first property that looks like an image URL."""
    for key in API_KEYS:
        value = properties.get(key)
        if isinstance(value, dict):
            value = value.get("url") or value.get("src")
        if isinstance(value, str) and re.match(r"^(https?:)?//", value.strip(), re.I):
            return value.strip()
    return None


def absolute(src: str, base: str | None) -> str:
    return urljoin(base or "https://form.jotform.com/", src.strip())


# -- downloading -----------------------------------------------------------------------------


def _check(url: str) -> str:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise LogoError("host") from None
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in ALLOWED_HOSTS:
        raise LogoError("host")
    if parts.username or parts.password or port not in (None, 443):
        raise LogoError("host")
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))


async def fetch_logo(
    url: str, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> bytes:
    """The logo's bytes; raises :class:`LogoError` (``host``, ``too_large`` or ``fetch``)."""
    current = _check(url)
    for _hop in range(MAX_REDIRECTS + 1):
        try:
            target = await resolve(current, settings)
        except UrlRefused:
            raise LogoError("host") from None
        parts = urlsplit(current)
        host = f"[{target.address}]" if ":" in target.address else target.address
        pinned = urlunsplit(("https", host, parts.path or "/", parts.query, ""))
        try:
            async with (
                httpx.AsyncClient(
                    timeout=TIMEOUT, follow_redirects=False, transport=transport
                ) as client,
                client.stream(
                    "GET",
                    pinned,
                    headers={"Host": target.host, "User-Agent": USER_AGENT, "Accept": "image/*"},
                    extensions={"sni_hostname": target.host},
                ) as res,
            ):
                if res.status_code in (301, 302, 303, 307, 308):
                    current = _check(urljoin(current, res.headers.get("location", "")))
                    continue
                if res.status_code != 200:
                    raise LogoError("fetch")
                length = res.headers.get("content-length", "")
                if length.isdigit() and int(length) > MAX_BYTES:
                    raise LogoError("too_large")
                body = bytearray()
                async for chunk in res.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise LogoError("too_large")
                return bytes(body)
        except httpx.HTTPError:
            raise LogoError("fetch") from None
    raise LogoError("fetch")


# -- cleaning --------------------------------------------------------------------------------


def _to_png(raw: bytes) -> bytes:
    """A JPEG, WebP or GIF re-encoded as PNG (at most CONVERT_MAX_SIDE px, under 512 KB)."""
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            if probe.format not in CONVERT_FORMATS:
                raise LogoError("bad_type")
            width, height = probe.size
        if width > MAX_SIDE or height > MAX_SIDE:
            raise LogoError("too_large_pixels")
        with Image.open(io.BytesIO(raw)) as img:
            img.seek(0)
            frame = ImageOps.exif_transpose(img) or img
            frame = frame.convert(
                "RGBA" if "A" in frame.getbands() or "transparency" in img.info else "RGB"
            )
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise LogoError("bad_type") from None
    side = CONVERT_MAX_SIDE
    while True:
        copy = frame.copy()
        copy.thumbnail((side, side))
        out = io.BytesIO()
        copy.save(out, format="PNG", optimize=True)
        if out.tell() <= MAX_BYTES or side <= 128:
            break
        side //= 2
    if out.tell() > MAX_BYTES:
        raise LogoError("too_large")
    return out.getvalue()


def clean_logo(raw: bytes) -> CleanImage:
    """PNG or SVG cleaned as a branding logo; JPEG/WebP/GIF converted to PNG first."""
    if len(raw) > MAX_BYTES:
        raise LogoError("too_large")
    try:
        return clean_image("logo", raw)
    except BrandImageError as exc:
        if exc.code != "bad_type":
            raise LogoError(exc.code) from None
    try:
        return clean_image("logo", _to_png(raw))
    except BrandImageError as exc:
        raise LogoError(exc.code if exc.code in REASONS else "bad_type") from None


async def import_logo(src: str | None, base: str | None, settings: Settings) -> LogoResult:
    """Find, download and clean the logo at ``src`` (relative to ``base``)."""
    if not src:
        return LogoResult(None, report("none"))
    if src.startswith("data:"):
        return LogoResult(None, report("not_imported", REASONS["host"], None))
    url = absolute(src, base)
    try:
        raw = await fetch_logo(url, settings)
        img = clean_logo(raw)
    except LogoError as exc:
        return LogoResult(None, report("not_imported", REASONS[exc.code], url))
    return LogoResult(img, report("imported", None, url))
