from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fakeredis import FakeAsyncRedis
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import create_session, load_session
from app.config import Settings, get_settings
from app.services.users import create_admin
from tests.conftest import RecordingQueue, login


async def test_meta(client: AsyncClient) -> None:
    res = await client.get("/api/v1/meta")
    assert res.json()["features"] == {
        "ai": False,
        "aiVision": False,
        "oidc": False,
        "oidcAutoRedirect": False,
        "localLogin": True,
        "demo": False,
        "email": False,
        "captcha": "none",
        "captchaBusyThreshold": 1000,
    }
    assert res.json()["thaanaFontCssUrl"].startswith("https://")


def test_font_css_url_setting() -> None:
    import pytest
    from pydantic import ValidationError

    from app.config import Settings

    assert Settings(thaana_font_css_url="").thaana_font_css_url == ""
    assert (
        Settings(thaana_font_css_url="/fonts/faruma.css").thaana_font_css_url == "/fonts/faruma.css"
    )
    with pytest.raises(ValidationError):
        Settings(thaana_font_css_url="http://insecure.example/x.css")


async def test_unknown_email_gets_same_answer_and_no_mail(
    client: AsyncClient, queue: RecordingQueue
) -> None:
    res = await client.post("/api/v1/auth/local/request", json={"email": "nobody@example.org"})
    assert res.status_code == 202
    assert queue.jobs == []


async def test_local_login_flow(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    await create_admin(db, settings, "Admin@Example.org", "Admin")
    await db.commit()

    assert (await client.get("/api/v1/auth/me")).status_code == 401
    me = await login(client, queue, "admin@example.org")
    assert me["email"] == "admin@example.org"
    assert me["isSuperadmin"] is True
    assert me["orgs"][0]["role"] == "admin"
    assert "justforms_session" in client.cookies

    res = await client.get("/api/v1/auth/me")
    assert res.status_code == 200

    # Logout is an unsafe request: needs the CSRF header.
    token = client.headers.pop("X-CSRF-Token")
    assert (await client.post("/api/v1/auth/logout")).status_code == 403
    res = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token})
    assert res.status_code == 200
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_code_is_single_use_and_attempts_are_limited(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    await create_admin(db, settings, "a@example.org")
    await db.commit()
    await client.post("/api/v1/auth/local/request", json={"email": "a@example.org"})
    code = queue.last_code("a@example.org")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(settings.login_code_max_attempts):
        res = await client.post(
            "/api/v1/auth/local/verify", json={"email": "a@example.org", "code": wrong}
        )
        assert res.status_code == 400
    res = await client.post(
        "/api/v1/auth/local/verify", json={"email": "a@example.org", "code": code}
    )
    assert res.status_code == 400, "code must be dead after too many attempts"


async def test_request_rate_limit(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    await create_admin(db, settings, "a@example.org")
    await db.commit()
    statuses = [
        (
            await client.post("/api/v1/auth/local/request", json={"email": "a@example.org"})
        ).status_code
        for _ in range(4)
    ]
    assert statuses == [202, 202, 202, 429]


async def test_cross_origin_requests_are_rejected(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    res = await client.post(
        "/api/v1/auth/local/request",
        json={"email": "a@example.org"},
        headers={"Origin": "https://evil.example"},
    )
    assert res.status_code == 403
    await create_admin(db, settings, "a@example.org")
    await db.commit()
    await login(client, queue, "a@example.org")
    res = await client.post("/api/v1/auth/logout", headers={"Origin": "https://evil.example"})
    assert res.status_code == 403


async def test_csrf_must_match_session(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    await create_admin(db, settings, "a@example.org")
    await db.commit()
    await login(client, queue, "a@example.org")
    client.cookies.set("justforms_csrf", "forged")
    res = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "forged"})
    assert res.status_code == 403


async def test_oidc_routes_disabled_without_issuer(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/login")).status_code == 404


async def test_session_absolute_lifetime(redis: FakeAsyncRedis) -> None:
    settings = Settings(environment="test", session_absolute_seconds=60)
    token, session = await create_session(redis, settings, "user-1")
    assert (await load_session(redis, settings, token)) is not None
    raw = await redis.get(f"session:{session.token_hash}")
    assert raw is not None
    await redis.set(
        f"session:{session.token_hash}",
        raw.replace(str(session.created_at), str(time.time() - 120)),
    )
    assert (await load_session(redis, settings, token)) is None
    assert (await load_session(redis, settings, "not-a-token")) is None


async def test_session_store_keeps_only_token_hash(redis: FakeAsyncRedis) -> None:
    settings = Settings(environment="test")
    token, _ = await create_session(redis, settings, "user-1")
    keys = await redis.keys("session:*")
    assert keys and all(token not in k for k in keys)


def test_empty_env_values_mean_unset() -> None:
    settings = Settings(environment="test", secret_key="", oidc_issuer="", smtp_password="")
    assert settings.secret_key is None and settings.smtp_password is None
    assert settings.local_login_enabled


def test_production_requires_secret_key() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="JUSTFORMS_SECRET_KEY"):
        Settings(environment="production", secret_key="")


# -- demo sign-in code ------------------------------------------------------------------

DEMO_CODE = "480317"


def _demo_settings(**kwargs: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "oidc_issuer": None,
        "public_url": "http://testserver",
        "demo_login_code": DEMO_CODE,
        "demo_login_emails": "Demo@Example.org, other-demo@example.org",
    }
    return Settings(**(values | kwargs))


def test_demo_login_is_off_by_default() -> None:
    settings = Settings(environment="test", demo_login_code="", demo_login_emails="")
    assert settings.demo_login_code is None
    assert settings.demo_login_emails == []
    assert not settings.demo_login_enabled


def test_demo_login_settings_validation() -> None:
    settings = _demo_settings()
    assert settings.demo_login_enabled
    assert settings.demo_login_emails == ["demo@example.org", "other-demo@example.org"]
    # OIDC turns local login, and with it the demo code, off.
    oidc = _demo_settings(oidc_issuer="https://idp.example", oidc_client_id="x")
    assert not oidc.demo_login_enabled

    with pytest.raises(ValidationError, match="JUSTFORMS_DEMO_LOGIN_EMAILS is required"):
        Settings(environment="test", demo_login_code=DEMO_CODE)
    with pytest.raises(ValidationError, match="JUSTFORMS_DEMO_LOGIN_EMAILS is required"):
        Settings(environment="test", demo_login_code=DEMO_CODE, demo_login_emails=" , ")
    with pytest.raises(ValidationError, match="without JUSTFORMS_DEMO_LOGIN_CODE"):
        Settings(environment="test", demo_login_emails="demo@example.org")
    with pytest.raises(ValidationError, match="not an email"):
        Settings(environment="test", demo_login_code=DEMO_CODE, demo_login_emails="demo")
    for bad in ("12345", "1234567", "abcdef", "12 456"):
        with pytest.raises(ValidationError, match="exactly 6 digits"):
            Settings(environment="test", demo_login_code=bad, demo_login_emails="d@example.org")
    for weak in ("000000", "111111", "123456", "654321", "012345", "123123", "121212", "123321"):
        with pytest.raises(ValidationError, match="too easy to guess"):
            Settings(environment="test", demo_login_code=weak, demo_login_emails="d@example.org")


@pytest.fixture
def fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.usefixtures("fresh_settings")
def test_app_refuses_to_start_with_unsafe_demo_login(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import create_app

    monkeypatch.setenv("JUSTFORMS_DEMO_LOGIN_CODE", "123456")
    monkeypatch.setenv("JUSTFORMS_DEMO_LOGIN_EMAILS", "demo@example.org")
    with pytest.raises(ValidationError, match="too easy"):
        create_app()
    get_settings.cache_clear()
    monkeypatch.setenv("JUSTFORMS_DEMO_LOGIN_CODE", DEMO_CODE)
    monkeypatch.delenv("JUSTFORMS_DEMO_LOGIN_EMAILS")
    with pytest.raises(ValidationError, match="JUSTFORMS_DEMO_LOGIN_EMAILS is required"):
        create_app()


@pytest.mark.usefixtures("fresh_settings")
def test_startup_warns_when_demo_login_is_enabled(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.main import create_app

    monkeypatch.setenv("JUSTFORMS_DEMO_LOGIN_CODE", DEMO_CODE)
    monkeypatch.setenv("JUSTFORMS_DEMO_LOGIN_EMAILS", "demo@example.org")
    # Alembic's fileConfig (run by the migration fixture) disables loggers that exist already.
    monkeypatch.setattr(logging.getLogger("app.main"), "disabled", False)
    with caplog.at_level(logging.WARNING, logger="app.main"):
        create_app()
    assert "DEMO LOGIN ENABLED" in caplog.text
    assert DEMO_CODE not in caplog.text


async def test_demo_code_signs_in_allow_listed_email(
    app: Any, client: AsyncClient, db: AsyncSession, queue: RecordingQueue
) -> None:
    settings = _demo_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    await create_admin(db, settings, "demo@example.org")
    await db.commit()

    meta = (await client.get("/api/v1/meta")).json()
    assert meta["features"]["demo"] is True

    # A code must still be requested first (same flow and limits).
    res = await client.post(
        "/api/v1/auth/local/verify", json={"email": "demo@example.org", "code": DEMO_CODE}
    )
    assert res.status_code == 400
    res = await client.post("/api/v1/auth/local/request", json={"email": "Demo@Example.org"})
    assert res.status_code == 202
    res = await client.post(
        "/api/v1/auth/local/verify", json={"email": "DEMO@example.org", "code": DEMO_CODE}
    )
    assert res.status_code == 200, res.text
    assert res.json()["email"] == "demo@example.org"
    # Single use, like an emailed code.
    res = await client.post(
        "/api/v1/auth/local/verify", json={"email": "demo@example.org", "code": DEMO_CODE}
    )
    assert res.status_code == 400


async def test_demo_code_is_rejected_for_other_emails(
    app: Any, client: AsyncClient, db: AsyncSession, queue: RecordingQueue
) -> None:
    settings = _demo_settings()
    app.dependency_overrides[get_settings] = lambda: settings
    await create_admin(db, settings, "admin@example.org")
    await db.commit()
    await client.post("/api/v1/auth/local/request", json={"email": "admin@example.org"})
    res = await client.post(
        "/api/v1/auth/local/verify", json={"email": "admin@example.org", "code": DEMO_CODE}
    )
    assert res.status_code == 400
    # The emailed code still works.
    res = await client.post(
        "/api/v1/auth/local/verify",
        json={"email": "admin@example.org", "code": queue.last_code("admin@example.org")},
    )
    assert res.status_code == 200


async def test_demo_code_is_off_by_default(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    await create_admin(db, settings, "demo@example.org")
    await db.commit()
    await client.post("/api/v1/auth/local/request", json={"email": "demo@example.org"})
    if queue.last_code("demo@example.org") == DEMO_CODE:
        return  # one in a million: the emailed code happens to match
    res = await client.post(
        "/api/v1/auth/local/verify", json={"email": "demo@example.org", "code": DEMO_CODE}
    )
    assert res.status_code == 400
