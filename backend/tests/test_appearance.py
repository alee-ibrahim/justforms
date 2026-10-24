"""Studio appearance preference on the user (docs/ux/FORM-THEME-SCREENS.md section 2)."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from tests.conftest import RecordingQueue, login
from tests.helpers import admin_client


async def test_appearance_defaults_to_light_and_persists(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    assert me["appearance"] == "light"

    res = await client.patch("/api/v1/auth/me", json={"appearance": "dark"})
    assert res.status_code == 200 and res.json()["appearance"] == "dark"
    assert (await client.get("/api/v1/auth/me")).json()["appearance"] == "dark"

    # A new session (another device) gets the saved choice.
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    again = await login(client, queue, "admin@example.org")
    assert again["appearance"] == "dark"

    res = await client.patch("/api/v1/auth/me", json={"appearance": "system"})
    assert res.json()["appearance"] == "system"
    res = await client.patch("/api/v1/auth/me", json={"appearance": "sepia"})
    assert res.status_code == 422
    # An empty patch changes nothing.
    assert (await client.patch("/api/v1/auth/me", json={})).json()["appearance"] == "system"


async def test_appearance_needs_session_and_csrf(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    await admin_client(client, db, settings, queue)
    del client.headers["X-CSRF-Token"]
    res = await client.patch("/api/v1/auth/me", json={"appearance": "dark"})
    assert res.status_code == 403
    client.cookies.clear()
    res = await client.patch("/api/v1/auth/me", json={"appearance": "dark"})
    assert res.status_code == 401
