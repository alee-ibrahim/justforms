from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import FormDraftHistory
from app.services.users import create_admin
from tests.conftest import RecordingQueue, login


async def _admin(
    client: AsyncClient, db: AsyncSession, settings: Settings, q: RecordingQueue
) -> str:
    await create_admin(db, settings, "admin@example.org")
    await db.commit()
    me = await login(client, q, "admin@example.org")
    return me["orgs"][0]["id"]


def add_field(field: dict[str, Any], index: int = 0) -> list[dict[str, Any]]:
    return [{"op": "add", "path": f"/pages/0/elements/{index}", "value": field}]


NAME = {"kind": "field", "id": "full_name", "type": "short_text", "label": "Full name"}


async def test_create_edit_publish(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    org_id = await _admin(client, db, settings, queue)
    res = await client.post(f"/api/v1/orgs/{org_id}/forms", json={"title": "Contact us"})
    assert res.status_code == 201, res.text
    form = res.json()
    assert form["slug"] == "contact-us"
    assert form["role"] == "owner"
    assert form["status"] == "draft"

    draft = (await client.get(f"/api/v1/forms/{form['id']}/draft")).json()
    assert draft["revision"] == 1
    assert draft["schema"]["settings"] == {"language": "en", "title": "Contact us"}

    res = await client.patch(
        f"/api/v1/forms/{form['id']}/draft", json={"baseRevision": 1, "patch": add_field(NAME)}
    )
    assert res.status_code == 200, res.text
    assert res.json()["revision"] == 2
    assert res.json()["schema"]["pages"][0]["elements"][0]["id"] == "full_name"

    # Stale revision -> 409 with the current revision.
    res = await client.patch(
        f"/api/v1/forms/{form['id']}/draft", json={"baseRevision": 1, "patch": []}
    )
    assert res.status_code == 409
    assert res.json()["revision"] == 2

    # Invalid result (logic cycle) -> 422, draft unchanged.
    cyclic = {**NAME, "id": "a", "visibleIf": {"field": "a", "op": "empty"}}
    res = await client.patch(
        f"/api/v1/forms/{form['id']}/draft",
        json={"baseRevision": 2, "patch": add_field(cyclic, 1)},
    )
    assert res.status_code == 422
    assert "cycle" in res.text

    # Bad patch path -> 422.
    res = await client.patch(
        f"/api/v1/forms/{form['id']}/draft",
        json={"baseRevision": 2, "patch": [{"op": "remove", "path": "/pages/9"}]},
    )
    assert res.status_code == 422

    # Title rename is reflected in the list.
    res = await client.patch(
        f"/api/v1/forms/{form['id']}/draft",
        json={
            "baseRevision": 2,
            "patch": [{"op": "replace", "path": "/settings/title", "value": "Contact"}],
        },
    )
    assert res.status_code == 200
    listed = (await client.get(f"/api/v1/orgs/{org_id}/forms")).json()
    assert [f["title"] for f in listed] == ["Contact"]

    history = await db.scalar(select(func.count()).select_from(FormDraftHistory))
    assert history == 2

    res = await client.post(f"/api/v1/forms/{form['id']}/publish")
    assert res.status_code == 200, res.text
    assert res.json()["version"] == 1
    got = (await client.get(f"/api/v1/forms/{form['id']}")).json()
    assert got["status"] == "live" and got["currentVersion"] == 1
    versions = (await client.get(f"/api/v1/forms/{form['id']}/versions")).json()
    assert [v["version"] for v in versions] == [1]


async def test_dv_form_and_publish_rejects_blank_label(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    org_id = await _admin(client, db, settings, queue)
    form = (
        await client.post(f"/api/v1/orgs/{org_id}/forms", json={"title": "ފޯމު", "language": "dv"})
    ).json()
    assert form["slug"] == "foamu"  # romanised (official 1977 rules)
    assert form["title"] == "ފޯމު"
    draft = (await client.get(f"/api/v1/forms/{form['id']}/draft")).json()
    assert draft["schema"]["settings"]["language"] == "dv"
    blank = {**NAME, "label": ""}
    res = await client.patch(
        f"/api/v1/forms/{form['id']}/draft", json={"baseRevision": 1, "patch": add_field(blank)}
    )
    assert res.status_code == 200
    res = await client.post(f"/api/v1/forms/{form['id']}/publish")
    assert res.status_code == 422
    assert res.json()["issues"][0]["code"] == "blank_text"


async def test_slugs_are_unique_per_org(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    org_id = await _admin(client, db, settings, queue)
    slugs = [
        (await client.post(f"/api/v1/orgs/{org_id}/forms", json={"title": "Survey"})).json()["slug"]
        for _ in range(3)
    ]
    assert slugs == ["survey", "survey-2", "survey-3"]


async def test_soft_delete(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    org_id = await _admin(client, db, settings, queue)
    form = (await client.post(f"/api/v1/orgs/{org_id}/forms", json={"title": "X"})).json()
    assert (await client.delete(f"/api/v1/forms/{form['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/forms/{form['id']}")).status_code == 404
    assert (await client.get(f"/api/v1/orgs/{org_id}/forms")).json() == []
