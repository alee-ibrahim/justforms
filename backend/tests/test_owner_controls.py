"""Owner-only data controls: editors can't turn off Sensitive on published questions, change
the allowed websites, or put a published form back to draft."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import FormPermission, FormRole, Organization, OrgRole, User
from app.services.users import set_membership
from tests.conftest import RecordingQueue, login, make_client
from tests.helpers import Published, admin_client, field, publish


async def _editor(db: AsyncSession, me: dict[str, Any], pub: Published) -> None:
    user = User(email="editor@example.org")
    db.add(user)
    await db.flush()
    org = await db.get(Organization, uuid.UUID(me["orgs"][0]["id"]))
    assert org is not None
    await set_membership(db, org, user, OrgRole.MEMBER)
    db.add(FormPermission(form_id=uuid.UUID(pub.id), user_id=user.id, role=FormRole.EDITOR))
    await db.commit()


async def _set_sensitive(c: AsyncClient, form_id: str, value: bool) -> None:
    draft = (await c.get(f"/api/v1/forms/{form_id}/draft")).json()
    op = {"op": "add", "path": "/pages/0/elements/0/sensitive", "value": value}
    if not value:
        op = {"op": "remove", "path": "/pages/0/elements/0/sensitive"}
    res = await c.patch(
        f"/api/v1/forms/{form_id}/draft",
        json={"baseRevision": draft["revision"], "patch": [op]},
    )
    assert res.status_code == 200, res.text


async def test_editor_cannot_unflag_sensitive_at_publish(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("id_number", sensitive=True), field("name")])
    await _editor(db, me, pub)
    async with make_client(app) as editor:
        await login(editor, queue, "editor@example.org")
        await _set_sensitive(editor, pub.id, False)
        res = await editor.post(f"/api/v1/forms/{pub.id}/publish")
        assert res.status_code == 403
        body = res.json()
        assert body["detail"] == "sensitive_owner_only"
        assert body["issues"][0]["target"] == "id_number"
        assert "owner" in body["issues"][0]["message"]
        # Flagging (or leaving it on) is fine for editors.
        await _set_sensitive(editor, pub.id, True)
        assert (await editor.post(f"/api/v1/forms/{pub.id}/publish")).status_code == 200
        await _set_sensitive(editor, pub.id, False)
    # The owner may turn it off.
    assert (await client.post(f"/api/v1/forms/{pub.id}/publish")).status_code == 200


async def test_embed_origins_are_owner_only(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")])
    await _editor(db, me, pub)
    async with make_client(app) as editor:
        await login(editor, queue, "editor@example.org")
        res = await editor.patch(
            f"/api/v1/forms/{pub.id}", json={"embedOrigins": ["https://evil.example"]}
        )
        assert res.status_code == 403 and res.json()["detail"] == "embed_origins_owner_only"
        # Unchanged lists and other editor settings still save.
        res = await editor.patch(f"/api/v1/forms/{pub.id}", json={"embedOrigins": []})
        assert res.status_code == 200, res.text
    res = await client.patch(
        f"/api/v1/forms/{pub.id}", json={"embedOrigins": ["https://example.org"]}
    )
    assert res.status_code == 200 and res.json()["embedOrigins"] == ["https://example.org"]


async def test_published_form_cannot_go_back_to_draft(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")])
    res = await client.patch(f"/api/v1/forms/{pub.id}", json={"status": "draft"})
    assert res.status_code == 422 and res.json()["detail"] == "cannot_return_to_draft"
    assert (await client.get(pub.base)).status_code == 200
    # Even if a row says draft, the public link is not live.
    from app.models import FormRecord, FormStatus

    form = await db.get(FormRecord, uuid.UUID(pub.id))
    assert form is not None
    form.status = FormStatus.DRAFT
    await db.commit()
    assert (await client.get(pub.base)).status_code == 404
    body = pub.submit_body({"name": "x"})
    assert (await client.post(f"{pub.base}/submissions", json=body)).status_code == 404


async def test_webhook_urls_are_masked_for_non_owners(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await publish(client, me, [field("name")])
    secret_url = "https://hooks.example.com/catch/123/abc?token=s3cret"
    url = f"/api/v1/forms/{pub.id}/webhooks"
    res = await client.post(url, json={"url": secret_url, "events": ["submission.created"]})
    assert res.status_code == 201, res.text
    assert [h["url"] for h in (await client.get(url)).json()] == [secret_url]
    await _editor(db, me, pub)
    async with make_client(app) as editor:
        await login(editor, queue, "editor@example.org")
        listed = (await editor.get(url)).json()
        assert [h["url"] for h in listed] == ["https://hooks.example.com/…"]
        assert "s3cret" not in (await editor.get(url)).text


def test_mask_url() -> None:
    from app.api.v1.notify import mask_url

    assert mask_url("https://user:pw@example.org:8443/x?y=1") == "https://example.org:8443/…"
    assert mask_url("https://example.org") == "https://example.org"
    assert mask_url("https://example.org/") == "https://example.org"
