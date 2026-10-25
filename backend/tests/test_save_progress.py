"""Saved progress on the respondent's device: the per-form setting and the public payload."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.services.progress import progress_out, save_progress_days
from tests.conftest import RecordingQueue
from tests.helpers import admin_client, field, publish


def test_setting_defaults_and_bad_values() -> None:
    assert progress_out(None) == {"save_progress": True, "save_progress_days": 7}
    assert save_progress_days({}) == 7
    assert save_progress_days({"saveProgress": False, "saveProgressDays": 3}) is None
    assert save_progress_days({"saveProgressDays": 30}) == 30
    for bad in (0, 500, True, "7", None):
        assert save_progress_days({"saveProgressDays": bad}) == 7


async def test_save_progress_setting(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")])
    slug = pub.form["slug"]

    form = (await client.get(f"/api/v1/forms/{pub.id}")).json()
    assert form["saveProgress"] is True and form["saveProgressDays"] == 7
    live = (await client.get(f"/api/v1/public/forms/{slug}")).json()
    assert live["saveProgress"] == {"days": 7}

    res = await client.patch(f"/api/v1/forms/{pub.id}", json={"saveProgressDays": 14})
    assert res.status_code == 200 and res.json()["saveProgressDays"] == 14
    live = (await client.get(f"/api/v1/public/forms/{slug}")).json()
    assert live["saveProgress"] == {"days": 14}

    res = await client.patch(f"/api/v1/forms/{pub.id}", json={"saveProgress": False})
    assert res.status_code == 200
    assert res.json()["saveProgress"] is False and res.json()["saveProgressDays"] == 14
    live = (await client.get(f"/api/v1/public/forms/{slug}")).json()
    assert live["saveProgress"] is None
    listed = (await client.get(f"/api/v1/orgs/{pub.form['orgId']}/forms")).json()
    items = listed["items"] if isinstance(listed, dict) else listed
    assert next(f for f in items if f["id"] == pub.id)["saveProgress"] is False

    for bad in (0, 91):
        res = await client.patch(f"/api/v1/forms/{pub.id}", json={"saveProgressDays": bad})
        assert res.status_code == 422
