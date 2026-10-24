"""Client address and user agent of a request, as recorded in audit data."""

from __future__ import annotations

import ipaddress

from fastapi import Request

from app.config import Settings

MAX_USER_AGENT = 1000


def _trusted(addr: str, settings: Settings) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    for entry in settings.trusted_proxies:
        try:
            if ip in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def client_ip(request: Request, settings: Settings) -> str | None:
    """The peer address, or the right-most untrusted ``X-Forwarded-For`` hop when the peer
    is a trusted proxy (DESIGN 14.1)."""
    peer = request.client.host if request.client else None
    if peer is None:
        return None
    if not _trusted(peer, settings):
        return _valid(peer)
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(hops):
        if not _trusted(hop, settings):
            return _valid(hop)
    return _valid(peer)


def _valid(addr: str) -> str | None:
    try:
        return str(ipaddress.ip_address(addr))
    except ValueError:
        return None


def user_agent(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    return ua[:MAX_USER_AGENT] if ua else None
