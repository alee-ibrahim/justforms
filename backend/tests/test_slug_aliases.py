"""Readable addresses for Dhivehi titles, and earlier addresses (aliases) that redirect to the
current one (DESIGN, form addresses)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import FormRecord, FormSlugAlias
from app.storage import Storage
from app.submissions import retention
from tests.conftest import RecordingQueue
from tests.helpers import admin_client, field, publish


async def test_thaana_titles_get_romanised_addresses(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    org = me["orgs"][0]["id"]

    async def create(title: str) -> dict[str, str]:
        res = await client.post(
            f"/api/v1/orgs/{org}/forms", json={"title": title, "language": "dv"}
        )
        assert res.status_code == 201, res.text
        return res.json()

    assert (await create("ކަނޑި"))["slug"] == "kandi"
    assert (await create("ކަނޑި"))["slug"] == "kandi-2"
    mixed = await create("Youth programme ޒުވާނުންގެ ޕްރޮގްރާމް 2026")
    assert mixed["slug"] == "youth-programme-zuvaanunge-prograam-2026"
    # Duplicates are named from "<title> (copy)".
    copy = (await client.post(f"/api/v1/forms/{mixed['id']}/duplicate")).json()
    assert copy["slug"] == "youth-programme-zuvaanunge-prograam-2026-copy"
    # The live check suggests a romanised address for Thaana typed into the field.
    check = (await client.get("/api/v1/forms/slug-check", params={"slug": "ޢީދު"})).json()
    assert check["problem"] == "invalid" and check["suggestion"] == "eedhu"


async def test_generic_address_follows_title_until_published(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    """A draft still at ``form`` takes an address from the title written later (in the builder
    or by the AI assistant); after the first publish it never changes by itself."""
    me = await admin_client(client, db, settings, queue)
    org = me["orgs"][0]["id"]
    form = (await client.post(f"/api/v1/orgs/{org}/forms", json={"title": "Form"})).json()
    assert form["slug"] == "form"

    async def retitle(title: str) -> str:
        draft = (await client.get(f"/api/v1/forms/{form['id']}/draft")).json()
        res = await client.patch(
            f"/api/v1/forms/{form['id']}/draft",
            json={
                "baseRevision": draft["revision"],
                "patch": [{"op": "replace", "path": "/settings/title", "value": title}],
            },
        )
        assert res.status_code == 200, res.text
        return str((await client.get(f"/api/v1/forms/{form['id']}")).json()["slug"])

    assert await retitle("ޤައުމީ ދުވަސް") == "qaumee-dhuvas"
    # No longer generic: later titles leave it alone.
    assert await retitle("ޢީދު") == "qaumee-dhuvas"


async def test_changed_address_redirects(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")], title="ފޯމު", language="dv")
    form_id = pub.form["id"]
    # Created before romanisation existed: a generic address.
    await db.execute(
        update(FormRecord).where(FormRecord.id == uuid.UUID(form_id)).values(slug="form-3")
    )
    await db.commit()

    res = await client.patch(f"/api/v1/forms/{form_id}", json={"slug": "foamu"})
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["slug"] == "foamu" and out["previousSlugs"] == ["form-3"]

    # The public API, its link-preview image and theme follow the form.
    res = await client.get("/api/v1/public/forms/form-3?embed=1")
    assert res.status_code == 301
    assert res.headers["location"] == "/api/v1/public/forms/foamu?embed=1"
    assert res.headers["cache-control"] == "no-cache"
    res = await client.get("/api/v1/public/forms/form-3/og.png?v=1")
    assert res.status_code == 301
    assert res.headers["location"] == "/api/v1/public/forms/foamu/og.png?v=1"
    assert (await client.get("/api/v1/public/forms/foamu/og.png")).status_code == 200
    css = await client.get("/api/v1/public/forms/form-3/theme.css")
    assert css.status_code == 200 and "no theme" not in css.text

    # The page (and the embed): the web server turns 401 + X-JustForms-Moved into a 301.
    for uri in ("/form-3", "/form-3/?embed=1"):
        res = await client.get("/api/v1/public/frame-ancestors", headers={"X-Original-URI": uri})
        assert res.status_code == 401 and res.headers["x-justforms-moved"] == "foamu"
    res = await client.get("/api/v1/public/frame-ancestors", headers={"X-Original-URI": "/foamu"})
    assert res.status_code == 204 and "x-justforms-moved" not in res.headers

    # A page opened before the change still submits to the old address.
    sub = await client.post(
        "/api/v1/public/forms/form-3/submissions", json=pub.submit_body({"name": "Aisha"})
    )
    assert sub.status_code == 201, sub.text

    # Another form can't take the old address while it redirects.
    other = (
        await client.post(f"/api/v1/orgs/{me['orgs'][0]['id']}/forms", json={"title": "Other"})
    ).json()
    check = (
        await client.get(
            "/api/v1/forms/slug-check", params={"slug": "form-3", "formId": other["id"]}
        )
    ).json()
    assert check["problem"] == "taken" and check["suggestion"] == "form-3-2"
    res = await client.patch(f"/api/v1/forms/{other['id']}", json={"slug": "form-3"})
    assert res.status_code == 409

    # The form itself may take it back: the alias goes, the newer address becomes one.
    res = await client.patch(f"/api/v1/forms/{form_id}", json={"slug": "form-3"})
    assert res.status_code == 200 and res.json()["previousSlugs"] == ["foamu"]
    assert (await client.get("/api/v1/public/forms/form-3")).status_code == 200
    res = await client.get("/api/v1/public/forms/foamu")
    assert res.status_code == 301 and res.headers["location"] == "/api/v1/public/forms/form-3"


async def test_draft_address_changes_leave_no_alias(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    org = me["orgs"][0]["id"]
    form = (await client.post(f"/api/v1/orgs/{org}/forms", json={"title": "Survey"})).json()
    res = await client.patch(f"/api/v1/forms/{form['id']}", json={"slug": "survey-new"})
    assert res.status_code == 200 and res.json()["previousSlugs"] == []
    check = (await client.get("/api/v1/forms/slug-check", params={"slug": "survey"})).json()
    assert check["available"] is True


async def test_aliases_freed_when_the_form_is_erased(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")], title="Membership")
    form_id = uuid.UUID(pub.form["id"])
    await client.patch(f"/api/v1/forms/{pub.form['id']}", json={"slug": "members"})

    # In the trash: the old address no longer answers, but stays reserved.
    assert (await client.delete(f"/api/v1/forms/{pub.form['id']}")).status_code == 204
    assert (await client.get("/api/v1/public/forms/membership")).status_code == 404
    res = await client.get(
        "/api/v1/public/frame-ancestors", headers={"X-Original-URI": "/membership"}
    )
    assert res.status_code == 204
    check = (await client.get("/api/v1/forms/slug-check", params={"slug": "membership"})).json()
    assert check["problem"] == "taken"

    # Restored: redirects again.
    assert (
        await client.post(f"/api/v1/forms/{pub.form['id']}/restore", json={})
    ).status_code == 200
    assert (await client.get("/api/v1/public/forms/membership")).status_code == 301

    # Erased by the nightly job after the trash period: the address is free.
    await client.delete(f"/api/v1/forms/{pub.form['id']}")
    await db.execute(
        update(FormRecord)
        .where(FormRecord.id == form_id)
        .values(deleted_at=datetime.now(UTC) - timedelta(days=31))
    )
    await db.commit()
    await retention.purge(db, file_storage)
    assert await db.scalar(select(FormSlugAlias).where(FormSlugAlias.form_id == form_id)) is None
    check = (await client.get("/api/v1/forms/slug-check", params={"slug": "membership"})).json()
    assert check["available"] is True
