"""Production refusals, API docs, cache and cookie hardening."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.db import get_engine
from app.security import SecurityHeadersMiddleware

GOOD_KEY = "k" * 48


def _prod(**kwargs: Any) -> Settings:
    return Settings(**{"environment": "production", "secret_key": GOOD_KEY, **kwargs})


def test_production_refuses_the_demo_login_code() -> None:
    with pytest.raises(ValidationError, match="demo instances only"):
        _prod(demo_login_code="580317", demo_login_emails="demo@example.org")
    # Outside production it is still allowed (demo instances).
    Settings(environment="development", demo_login_code="580317", demo_login_emails="d@e.org")


@pytest.mark.parametrize(
    "key",
    [
        "change-me-long-random-string",
        "CHANGE-ME-please-make-this-at-least-32-bytes",
        "justforms-insecure-development-key",
        "short-but-random-Xq9",
        "x" * 31,
    ],
)
def test_production_refuses_weak_secret_keys(key: str) -> None:
    with pytest.raises(ValidationError, match="JUSTFORMS_SECRET_KEY"):
        _prod(secret_key=key)


def test_production_accepts_a_real_key() -> None:
    assert _prod().secret_key is not None
    # Development keeps working with anything (and the built-in key when unset).
    Settings(environment="development", secret_key="dev")


def test_api_docs_default_off_in_production() -> None:
    assert Settings(environment="development").api_docs_enabled
    assert not _prod().api_docs_enabled
    assert _prod(api_docs="true").api_docs_enabled
    assert not Settings(environment="development", api_docs="false").api_docs_enabled


async def test_production_app_serves_no_api_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import create_app

    monkeypatch.setenv("JUSTFORMS_ENVIRONMENT", "production")
    monkeypatch.setenv("JUSTFORMS_SECRET_KEY", GOOD_KEY)
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    get_settings.cache_clear()
    try:
        app = create_app()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        for path in ("/api/docs", "/api/redoc", "/api/v1/openapi.json"):
            assert (await c.get(path)).status_code == 404, path


def test_sql_errors_hide_bound_parameters() -> None:
    get_engine.cache_clear()
    try:
        assert get_engine().sync_engine.hide_parameters is True
    finally:
        get_engine.cache_clear()


async def _headers(path: str, route_headers: dict[str, str], **request: Any) -> dict[str, str]:
    async def app(scope: Any, receive: Any, send: Any) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(k.lower().encode(), v.encode()) for k, v in route_headers.items()],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    async with AsyncClient(
        transport=ASGITransport(app=SecurityHeadersMiddleware(app)), base_url="http://t"
    ) as c:
        res = await c.get(path, **request)
    return dict(res.headers)


async def test_staff_and_token_responses_are_never_cached() -> None:
    # A staff route that set its own caching (a signature image, a download redirect).
    h = await _headers("/api/v1/signatures/x", {"Cache-Control": "private, max-age=3600"})
    assert h["cache-control"] == "no-store"
    assert (await _headers("/api/v1/auth/me", {}))["cache-control"] == "no-store"
    h = await _headers("/api/v1/public/approvals/tok/files/x", {})
    assert h["cache-control"] == "no-store"
    h = await _headers("/api/v1/public/forms/x", {}, headers={"Authorization": "Bearer t"})
    assert h["cache-control"] == "no-store"


async def test_public_caching_is_kept() -> None:
    year = "public, max-age=31536000, immutable"
    h = await _headers("/api/v1/public/theme-images/a/b", {"Cache-Control": year})
    assert h["cache-control"] == year
    # With a session cookie: the route's own caching stays, otherwise no-store.
    cookie = {"Cookie": "__Host-justforms_session=abc"}
    h = await _headers("/api/v1/public/theme-images/a/b", {"Cache-Control": year}, headers=cookie)
    assert h["cache-control"] == year
    h = await _headers("/api/v1/public/forms/x", {}, headers=cookie)
    assert h["cache-control"] == "no-store"
    assert "cache-control" not in await _headers("/api/v1/public/forms/x", {})


def test_uvicorn_access_log_drops_query_strings() -> None:
    import logging

    from app.main import _AccessLogWithoutQuery

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:0", "GET", "/api/v1/auth/callback?code=SECRET&state=s", "1.1", 302),
        None,
    )
    assert _AccessLogWithoutQuery().filter(record)
    assert "SECRET" not in record.getMessage()
    assert "/api/v1/auth/callback" in record.getMessage()
