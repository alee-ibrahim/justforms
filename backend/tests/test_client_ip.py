"""Client IP behind proxies (DESIGN 14.1): a spoofed X-Forwarded-For never becomes the client.

Reproduces the deployment bug where uvicorn trusted every peer (``--forwarded-allow-ips '*'``)
and the web container appended to the client's own X-Forwarded-For: uvicorn took the
left-most hop, which the client wrote.
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import Settings
from app.net import client_ip

NGINX = "10.42.0.7"
REAL = "198.51.100.5"
SPOOF = "203.0.113.99"


def _scope(peer: str, xff: str | None) -> dict[str, Any]:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "client": (peer, 1234),
        "scheme": "http",
        "query_string": b"",
        "server": ("x", 80),
    }


def _settings(trusted: str) -> Settings:
    return Settings(environment="test", trusted_proxies=trusted)


async def _through_uvicorn(scope: dict[str, Any], forwarded_allow_ips: str, s: Settings) -> str:
    """client_ip as the app sees it behind uvicorn's proxy-header middleware."""
    seen: dict[str, str | None] = {}

    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen["ip"] = client_ip(Request(scope), s)

    await ProxyHeadersMiddleware(app, trusted_hosts=forwarded_allow_ips)(scope, None, None)  # type: ignore[arg-type]
    return str(seen["ip"])


@pytest.mark.parametrize("trusted", ["", "10.0.0.0/8"])
async def test_spoofed_left_most_hop_is_ignored(trusted: str) -> None:
    s = _settings(trusted)
    # nginx appended the real address to the header the client sent.
    scope = _scope(NGINX, f"{SPOOF}, {REAL}")
    # uvicorn trusting the same proxies (the shipped default when trusted is empty: loopback).
    allow = trusted or "127.0.0.1"
    got = await _through_uvicorn(scope, allow, s)
    assert got != SPOOF
    assert got == (REAL if trusted else NGINX)


async def test_trusted_chain_gives_the_right_most_untrusted_hop() -> None:
    s = _settings("10.0.0.0/8,172.16.0.0/12")
    scope = _scope(NGINX, f"{SPOOF}, {REAL}, 172.18.0.3")
    assert client_ip(Request(scope), s) == REAL
    assert await _through_uvicorn(scope, "10.0.0.0/8,172.16.0.0/12", s) == REAL


async def test_untrusted_peer_is_the_client_whatever_the_header_says() -> None:
    s = _settings("10.0.0.0/8")
    scope = _scope(REAL, SPOOF)
    assert client_ip(Request(scope), s) == REAL


async def test_web_container_overwrites_with_its_client_address() -> None:
    """The bundled nginx sends X-Forwarded-For: $remote_addr (one hop)."""
    s = _settings("10.0.0.0/8,172.16.0.0/12,192.168.0.0/16")
    assert client_ip(Request(_scope(NGINX, REAL)), s) == REAL
    # A client on a private network: every hop is trusted, the left-most is the client.
    assert client_ip(Request(_scope(NGINX, "192.168.1.20")), s) == "192.168.1.20"
    # No header: the peer.
    assert client_ip(Request(_scope(NGINX, None)), s) == NGINX


async def test_garbage_hop_is_not_returned() -> None:
    s = _settings("10.0.0.0/8")
    assert client_ip(Request(_scope(NGINX, f"{REAL}, not-an-ip")), s) is None


def test_production_refuses_uvicorn_trusting_every_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main
    from app.config import get_settings

    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    monkeypatch.setenv("JUSTFORMS_ENVIRONMENT", "production")
    monkeypatch.setenv("JUSTFORMS_SECRET_KEY", "k" * 48)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="FORWARDED_ALLOW_IPS"):
            main.create_app()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
