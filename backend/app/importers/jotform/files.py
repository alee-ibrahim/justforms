"""Downloading the files behind imported Jotform links (DESIGN 13.3, "Imported files").

An imported submission keeps its file and signature answers as links into Jotform
(``submissions.imported_links``). Jotform serves uploads only to a signed-in session or with
an API key, so these links are fetched with the account's key:

- ``https`` only, and only from Jotform's hosts (:data:`app.importers.jotform.logo.ALLOWED_HOSTS`);
- every address is resolved and checked by the SSRF guard (``app.notifications.ssrf``) and
  the connection goes to the checked address; redirects are followed by hand, at most
  :data:`MAX_REDIRECTS`, each hop checked again;
- the key goes in the ``APIKEY`` header (never in the URL, so it is not written to access
  logs) and only to the host of the stored link: Jotform answers with a redirect to a
  short-lived file URL, which is fetched without it;
- 60 seconds per file, and the body is capped while it streams.

The key is never stored: callers pass it in from the environment for one run.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import Settings
from app.importers.jotform.logo import ALLOWED_HOSTS
from app.notifications.ssrf import UrlRefused, resolve

MAX_REDIRECTS = 3
TIMEOUT = httpx.Timeout(60.0, connect=10.0)
USER_AGENT = "JustForms-Importer/1.0 (+file import)"
# Imported signature images: a drawn signature is a few KB; anything far bigger is not one.
SIGNATURE_MAX_BYTES = 2 * 1024 * 1024
SIGNATURE_MAX_SIDE = 4096
SIGNATURE_FORMATS = {"PNG", "JPEG", "GIF", "WEBP"}

REASONS = {
    "host": "The link is not on a Jotform host JustForms downloads from.",
    "auth": "Jotform asked for a sign-in: the API key is missing or has no access.",
    "not_found": "Jotform no longer has this file.",
    "too_large": "The file is larger than the question allows.",
    "bad_type": "The file's contents don't match a type the question accepts.",
    "fetch": "The file couldn't be downloaded.",
}


class FileFetchError(Exception):
    """``code``: a key of :data:`REASONS`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class Fetched:
    data: bytes
    # The file name from the link (percent-decoded), and the type the server declared.
    name: str
    mime: str


def check_url(url: str) -> str:
    """The normalised URL, or :class:`FileFetchError` ``host``."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        raise FileFetchError("host") from None
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in ALLOWED_HOSTS:
        raise FileFetchError("host")
    if parts.username or parts.password or port not in (None, 443):
        raise FileFetchError("host")
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))


def link_name(url: str) -> str:
    """The file name at the end of a link (``.../Signature.png`` -> ``Signature.png``)."""
    path = urlsplit(url).path
    return unquote(path.rsplit("/", 1)[-1]) or "file"


async def fetch_file(
    url: str,
    settings: Settings,
    *,
    api_key: str | None,
    max_bytes: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Fetched:
    """Download one Jotform-hosted file. Raises :class:`FileFetchError`."""
    first = check_url(url)
    first_host = urlsplit(first).hostname
    current = first
    for _hop in range(MAX_REDIRECTS + 1):
        try:
            target = await resolve(current, settings)
        except UrlRefused:
            raise FileFetchError("host") from None
        parts = urlsplit(current)
        host = f"[{target.address}]" if ":" in target.address else target.address
        pinned = urlunsplit(("https", host, parts.path or "/", parts.query, ""))
        headers = {"Host": target.host, "User-Agent": USER_AGENT}
        if api_key and parts.hostname == first_host:
            headers["APIKEY"] = api_key
        try:
            async with (
                httpx.AsyncClient(
                    timeout=TIMEOUT, follow_redirects=False, transport=transport
                ) as client,
                client.stream(
                    "GET", pinned, headers=headers, extensions={"sni_hostname": target.host}
                ) as res,
            ):
                if res.status_code in (301, 302, 303, 307, 308):
                    location = urljoin(current, res.headers.get("location", ""))
                    if "/login" in urlsplit(location).path:
                        raise FileFetchError("auth")
                    current = check_url(location)
                    continue
                if res.status_code in (401, 403):
                    raise FileFetchError("auth")
                if res.status_code in (404, 410):
                    raise FileFetchError("not_found")
                if res.status_code != 200:
                    raise FileFetchError("fetch")
                length = res.headers.get("content-length", "")
                if length.isdigit() and int(length) > max_bytes:
                    raise FileFetchError("too_large")
                body = bytearray()
                async for chunk in res.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise FileFetchError("too_large")
                mime = res.headers.get("content-type", "").split(";")[0].strip().lower()
                return Fetched(bytes(body), link_name(url), mime)
        except httpx.HTTPError:
            raise FileFetchError("fetch") from None
    raise FileFetchError("fetch")


def signature_png(raw: bytes) -> tuple[bytes, int, int]:
    """An imported signature image decoded and re-encoded as PNG (nothing but pixels is
    kept). Returns ``(png, width, height)``; raises :class:`FileFetchError` ``bad_type`` or
    ``too_large``."""
    if len(raw) > SIGNATURE_MAX_BYTES:
        raise FileFetchError("too_large")
    try:
        with Image.open(io.BytesIO(raw)) as img:
            if img.format not in SIGNATURE_FORMATS:
                raise FileFetchError("bad_type")
            width, height = img.size
            if width > SIGNATURE_MAX_SIDE or height > SIGNATURE_MAX_SIDE:
                raise FileFetchError("too_large")
            img.seek(0)
            frame = ImageOps.exif_transpose(img) or img
            frame = frame.convert(
                "RGBA" if "A" in frame.getbands() or "transparency" in img.info else "RGB"
            )
            out = io.BytesIO()
            frame.save(out, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise FileFetchError("bad_type") from None
    return out.getvalue(), frame.width, frame.height
