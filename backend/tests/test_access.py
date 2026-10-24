"""Per-form roles: listing and replacing grants (DESIGN 7)."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import AuditLog, OrgRole, User
from app.services.users import create_admin, ensure_default_org, set_membership
from tests.conftest import RecordingQueue, login, make_client


async def _member(
    db: AsyncSession,
    settings: Settings,
    email: str,
    name: str = "",
    role: OrgRole = OrgRole.CREATOR,
) -> User:
    org = await ensure_default_org(db, settings)
    user = User(email=email, display_name=name)
    db.add(user)
    await db.flush()
    await set_membership(db, org, user, role)
    await db.commit()
    return user


async def test_access_list_and_replace(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    await create_admin(db, settings, "root@example.org", "Root Admin")
    await _member(db, settings, "owner@example.org", "Aminath Ali")
    await _member(db, settings, "editor@example.org", "Ibrahim Naseer")
    await _member(db, settings, "viewer@example.org")
    outsider = User(email="outsider@example.org")
    db.add(outsider)
    await db.commit()

    me = await login(client, queue, "owner@example.org")
    form = (
        await client.post(f"/api/v1/orgs/{me['orgs'][0]['id']}/forms", json={"title": "F"})
    ).json()
    url = f"/api/v1/forms/{form['id']}/permissions"

    res = await client.get(url)
    assert res.status_code == 200
    body = res.json()
    assert body["canManage"] is True
    assert [(e["email"], e["role"], e["orgAdmin"]) for e in body["entries"]] == [
        ("root@example.org", "owner", True),
        ("owner@example.org", "owner", False),
    ]

    grants = [
        {"email": "owner@example.org", "role": "owner"},
        {"email": "Editor@Example.org", "role": "editor"},
        {"email": "viewer@example.org", "role": "viewer"},
    ]
    res = await client.put(url, json={"grants": grants})
    assert res.status_code == 200, res.text
    assert [(e["email"], e["role"]) for e in res.json()["entries"]][1:] == [
        ("editor@example.org", "editor"),
        ("owner@example.org", "owner"),
        ("viewer@example.org", "viewer"),
    ]
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "form.permissions"))

    # Only organisation members can be added.
    res = await client.put(
        url, json={"grants": [*grants, {"email": "outsider@example.org", "role": "viewer"}]}
    )
    assert res.status_code == 422 and res.json()["detail"]["code"] == "not_a_member"

    # The viewer reads the list but cannot change it; their role works on submissions.
    async with make_client(app) as viewer:
        await login(viewer, queue, "viewer@example.org")
        res = await viewer.get(url)
        assert res.status_code == 200 and res.json()["canManage"] is False
        assert (await viewer.put(url, json={"grants": grants})).status_code == 403
        assert (await viewer.get(f"/api/v1/forms/{form['id']}/submissions")).status_code == 200

    # Removing the viewer takes the form away from them.
    res = await client.put(url, json={"grants": grants[:2]})
    assert res.status_code == 200
    async with make_client(app) as viewer:
        await login(viewer, queue, "viewer@example.org")
        assert (await viewer.get(url)).status_code == 404

    async with make_client(app) as other:
        await login(other, queue, "editor@example.org")
        assert (await other.put(url, json={"grants": grants})).status_code == 403
