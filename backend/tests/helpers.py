"""Shared helpers for API tests: an admin session and a published form."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.services.users import create_admin
from tests.conftest import RecordingQueue, login


def field(fid: str, type_: str = "short_text", **extra: Any) -> dict[str, Any]:
    return {"kind": "field", "id": fid, "type": type_, "label": fid, **extra}


@dataclass
class Published:
    form: dict[str, Any]
    live: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.form["id"])

    @property
    def base(self) -> str:
        return f"/api/v1/public/forms/{self.form['slug']}"

    def submit_body(self, data: dict[str, Any], **extra: Any) -> dict[str, Any]:
        return {
            "versionId": self.live["versionId"],
            "data": data,
            "uploadNonce": self.live["uploadNonce"],
            **extra,
        }


async def admin_client(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    email: str = "admin@example.org",
) -> dict[str, Any]:
    await create_admin(db, settings, email)
    await db.commit()
    return await login(client, queue, email)


async def publish(
    client: AsyncClient,
    me: dict[str, Any],
    elements: list[dict[str, Any]],
    *,
    title: str = "Form",
    language: str = "en",
    pages: list[dict[str, Any]] | None = None,
) -> Published:
    """Create a form with ``elements`` on one page (or explicit ``pages``) and publish it."""
    res = await client.post(
        f"/api/v1/orgs/{me['orgs'][0]['id']}/forms", json={"title": title, "language": language}
    )
    assert res.status_code == 201, res.text
    form = res.json()
    draft = (await client.get(f"/api/v1/forms/{form['id']}/draft")).json()
    ops: list[dict[str, Any]] = (
        [{"op": "replace", "path": "/pages", "value": pages}]
        if pages is not None
        else [
            {"op": "add", "path": f"/pages/0/elements/{i}", "value": el}
            for i, el in enumerate(elements)
        ]
    )
    res = await client.patch(
        f"/api/v1/forms/{form['id']}/draft",
        json={"baseRevision": draft["revision"], "patch": ops},
    )
    assert res.status_code == 200, res.text
    res = await client.post(f"/api/v1/forms/{form['id']}/publish")
    assert res.status_code == 200, res.text
    form = (await client.get(f"/api/v1/forms/{form['id']}")).json()
    live = (await client.get(f"/api/v1/public/forms/{form['slug']}")).json()
    return Published(form, live)
