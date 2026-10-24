"""Fetch a public Jotform page by URL, for the form import (DESIGN 13.1).

Only ``https`` URLs on Jotform's own form hosts are accepted, redirects are followed by hand
and each hop is checked again, every address is resolved and checked by the SSRF guard
(``app.notifications.ssrf``) and the connection goes to the checked address. Responses are
capped in size and time.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.config import Settings
from app.notifications.ssrf import UrlRefused, resolve

ALLOWED_HOSTS = frozenset(
    {
        "form.jotform.com",
        "www.jotform.com",
        "jotform.com",
        "eu.jotform.com",
        "form.jotformeu.com",
        "www.jotformeu.com",
        "hipaa.jotform.com",
        "form.jotform.me",
    }
)
MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 3
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
USER_AGENT = "JustForms-Importer/1.0 (+form import)"


class FetchError(Exception):
    """``code``: ``not_jotform`` | ``invalid_url`` | ``private_address`` | ``dns_failed`` |
    ``too_large`` | ``timeout`` | ``fetch_failed`` | ``not_found``."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def normalise_url(url: str) -> str:
    """A form id alone or a Jotform form URL -> the https URL to fetch."""
    url = url.strip()
    if re.fullmatch(r"\d{10,20}", url):
        return f"https://form.jotform.com/{url}"
    if "://" not in url:
        url = f"https://{url}"
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in ALLOWED_HOSTS:
        raise FetchError("not_jotform")
    if parts.username or parts.password or (parts.port not in (None, 443)):
        raise FetchError("invalid_url")
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))


async def fetch_form_html(
    url: str, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[str, str]:
    """(final URL, HTML). Raises :class:`FetchError`."""
    current = normalise_url(url)
    for _hop in range(MAX_REDIRECTS + 1):
        try:
            target = await resolve(current, settings)
        except UrlRefused as exc:
            raise FetchError(exc.code) from exc
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
                    headers={
                        "Host": target.host,
                        "User-Agent": USER_AGENT,
                        "Accept": "text/html",
                    },
                    extensions={"sni_hostname": target.host},
                ) as res,
            ):
                if res.status_code in (301, 302, 303, 307, 308):
                    location = res.headers.get("location", "")
                    current = normalise_url(urljoin(current, location))
                    continue
                if res.status_code == 404:
                    raise FetchError("not_found")
                if res.status_code != 200:
                    raise FetchError("fetch_failed")
                body = bytearray()
                async for chunk in res.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise FetchError("too_large")
                return current, bytes(body).decode(res.encoding or "utf-8", "replace")
        except httpx.TimeoutException as exc:
            raise FetchError("timeout") from exc
        except httpx.HTTPError as exc:
            raise FetchError("fetch_failed") from exc
    raise FetchError("fetch_failed")
