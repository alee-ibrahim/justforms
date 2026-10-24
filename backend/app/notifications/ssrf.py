"""SSRF guard for webhook URLs (DESIGN 11.2).

The host is resolved at delivery time and every address it resolves to must be public, or
inside ``JUSTFORMS_WEBHOOK_ALLOWED_CIDRS``. The request then goes to the checked address (with
the original Host header and TLS server name), so a DNS answer that changes between the check
and the connection (DNS rebinding) cannot reach an internal address. Only ``https`` is
allowed, except ``http`` to allowlisted ranges.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.config import Settings

type IP = ipaddress.IPv4Address | ipaddress.IPv6Address

# Ranges that are never "public", on top of the ipaddress module's own flags.
_EXTRA_BLOCKED = [
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "100.64.0.0/10",  # carrier-grade NAT
        "169.254.0.0/16",  # link-local, cloud metadata
        "192.0.0.0/24",
        "198.18.0.0/15",
        "fc00::/7",
        "fe80::/10",
        "64:ff9b::/96",
    )
]


class UrlRefused(Exception):
    """The URL may not be used. ``code`` is shown to the user as a reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class Target:
    url: str
    host: str
    port: int
    scheme: str
    address: str  # the checked IP to connect to


def _networks(settings: Settings) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    out = []
    for entry in settings.webhook_allowed_cidrs:
        try:
            out.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            continue
    return out


def allowlisted(ip: IP, settings: Settings) -> bool:
    return any(ip in net for net in _networks(settings))


def is_public(ip: IP) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return is_public(ip.ipv4_mapped)
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    ):
        return False
    return not any(ip in net for net in _EXTRA_BLOCKED)


def parse(url: str) -> tuple[str, str, int]:
    """Scheme, host and port of an absolute http(s) URL; raises ``UrlRefused``."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UrlRefused("invalid_url") from exc
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UrlRefused("invalid_url")
    if parts.username or parts.password:
        raise UrlRefused("invalid_url")
    return parts.scheme, parts.hostname, port or (443 if parts.scheme == "https" else 80)


def check_static(url: str, settings: Settings) -> None:
    """Checks that need no DNS (used when a webhook is saved)."""
    scheme, host, _port = parse(url)
    try:
        ip: IP | None = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not is_public(ip) and not allowlisted(ip, settings):
        raise UrlRefused("private_address")
    # http is only for allowlisted internal receivers; with a host name we can only tell at
    # delivery time, so require https unless an allowlist exists.
    if scheme == "http" and (
        (ip is not None and not allowlisted(ip, settings))
        or (ip is None and not settings.webhook_allowed_cidrs)
    ):
        raise UrlRefused("https_required")


async def resolve(url: str, settings: Settings) -> Target:
    """Resolve and check the URL's host; returns the address to connect to."""
    scheme, host, port = parse(url)
    try:
        literal: IP | None = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses: list[IP] = [literal]
    else:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host, port, type=socket.SOCK_STREAM
            )
        except OSError as exc:
            raise UrlRefused("dns_failed") from exc
        addresses = [ipaddress.ip_address(str(info[4][0]).split("%")[0]) for info in infos]
        if not addresses:
            raise UrlRefused("dns_failed")
    for ip in addresses:
        if not is_public(ip) and not allowlisted(ip, settings):
            raise UrlRefused("private_address")
        if scheme == "http" and not allowlisted(ip, settings):
            raise UrlRefused("https_required")
    return Target(url=url, host=host, port=port, scheme=scheme, address=str(addresses[0]))
