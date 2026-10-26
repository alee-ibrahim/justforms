"""Review changes and Discard changes: GET /draft/changes and POST /draft/discard."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import FormPermission, FormRole, OrgRole, User
from app.models.audit import AuditLog
from app.services.users import create_admin, ensure_default_org, set_membership
from tests.conftest import RecordingQueue, login, make_client


def field(fid: str, **extra: Any) -> dict[str, Any]:
    return {"kind": "field", "id": fid, "type": "short_text", "label": fid, **extra}


async def patch(client: AsyncClient, form_id: str, rev: int, ops: list[dict[str, Any]]) -> Any:
    res = await client.patch(
        f"/api/v1/forms/{form_id}/draft", json={"baseRevision": rev, "patch": ops}
    )
    assert res.status_code == 200, res.text
    return res.json()


async def published_form(
    client: AsyncClient, db: AsyncSession, settings: Settings, q: RecordingQueue
) -> tuple[str, int]:
    """A form published with questions a and b; returns (id, draft revision)."""
    await create_admin(db, settings, "admin@example.org")
    await db.commit()
    me = await login(client, q, "admin@example.org")
    res = await client.post(f"/api/v1/orgs/{me['orgs'][0]['id']}/forms", json={"title": "Review"})
    fid = res.json()["id"]
    d = await patch(
        client,
        fid,
        1,
        [
            {"op": "add", "path": "/pages/0/elements/0", "value": field("a")},
            {"op": "add", "path": "/pages/0/elements/1", "value": field("b")},
        ],
    )
    assert (await client.post(f"/api/v1/forms/{fid}/publish")).status_code == 200
    return fid, d["revision"]


async def test_changes_before_first_publish(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    await create_admin(db, settings, "admin@example.org")
    await db.commit()
    me = await login(client, queue, "admin@example.org")
    res = await client.post(f"/api/v1/orgs/{me['orgs'][0]['id']}/forms", json={"title": "New"})
    fid = res.json()["id"]
    body = (await client.get(f"/api/v1/forms/{fid}/draft/changes")).json()
    assert body["baseVersion"] is None and body["hasChanges"] is True and body["pages"] == []
    # Nothing to go back to.
    res = await client.post(f"/api/v1/forms/{fid}/draft/discard", json={"baseRevision": 1})
    assert res.status_code == 409 and res.json()["detail"] == "never_published"


async def test_changes_and_discard(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    fid, rev = await published_form(client, db, settings, queue)
    body = (await client.get(f"/api/v1/forms/{fid}/draft/changes")).json()
    assert body["baseVersion"] == 1 and body["hasChanges"] is False and body["revision"] == rev

    d = await patch(
        client,
        fid,
        rev,
        [
            {"op": "replace", "path": "/pages/0/elements/0/label", "value": "Name"},
            {"op": "remove", "path": "/pages/0/elements/1"},
            {"op": "add", "path": "/pages/-", "value": {"id": "page_2", "elements": []}},
        ],
    )
    d = await patch(
        client, fid, d["revision"], [{"op": "replace", "path": "/settings/title", "value": "R2"}]
    )
    body = (await client.get(f"/api/v1/forms/{fid}/draft/changes")).json()
    assert body["hasChanges"] is True and body["revision"] == d["revision"]
    assert body["summary"] == (
        "1 page added, 1 question removed, 1 question changed, 1 form setting changed"
    )
    assert [p["pageId"] for p in body["pages"]] == ["page_1", "page_2"]
    assert {e["id"]: e["status"] for e in body["pages"][0]["elements"]} == {
        "a": "changed",
        "b": "removed",
    }
    assert body["settings"][0]["summary"] == "Form title changed"

    # A stale revision is a conflict.
    res = await client.post(f"/api/v1/forms/{fid}/draft/discard", json={"baseRevision": rev})
    assert res.status_code == 409 and res.json()["detail"] == "revision_conflict"

    res = await client.post(
        f"/api/v1/forms/{fid}/draft/discard", json={"baseRevision": d["revision"]}
    )
    assert res.status_code == 200, res.text
    after = res.json()
    live = (await client.get(f"/api/v1/forms/{fid}/versions/1")).json()["schema"]
    assert after["schema"] == live
    assert after["revision"] == d["revision"] + 1 and after["canUndo"] is True
    assert (await client.get(f"/api/v1/forms/{fid}")).json()["title"] == "Review"
    body = (await client.get(f"/api/v1/forms/{fid}/draft/changes")).json()
    assert body["hasChanges"] is False

    # Recorded in the audit log.
    rows = (await db.scalars(select(AuditLog).where(AuditLog.action == "form.draft_discard"))).all()
    assert len(rows) == 1 and rows[0].meta["version"] == 1

    # One undo brings every discarded change back.
    res = await client.post(
        f"/api/v1/forms/{fid}/draft/undo", json={"baseRevision": after["revision"]}
    )
    assert res.status_code == 200
    restored = res.json()
    assert restored["schema"]["settings"]["title"] == "R2"
    assert [p["id"] for p in restored["schema"]["pages"]] == ["page_1", "page_2"]

    # Discarding when nothing changed leaves the draft and the history alone.
    await client.post(
        f"/api/v1/forms/{fid}/draft/redo", json={"baseRevision": restored["revision"]}
    )
    clean = (await client.get(f"/api/v1/forms/{fid}/draft")).json()
    res = await client.post(
        f"/api/v1/forms/{fid}/draft/discard", json={"baseRevision": clean["revision"]}
    )
    assert res.status_code == 200 and res.json()["revision"] == clean["revision"]
    rows = (await db.scalars(select(AuditLog).where(AuditLog.action == "form.draft_discard"))).all()
    assert len(rows) == 1


async def test_roles(
    client: AsyncClient,
    app: Any,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    fid, rev = await published_form(client, db, settings, queue)
    d = await patch(
        client, fid, rev, [{"op": "add", "path": "/pages/0/elements/-", "value": field("c")}]
    )
    org = await ensure_default_org(db, settings)
    for role in ("viewer", "editor"):
        user = User(email=f"{role}@example.org")
        db.add(user)
        await db.flush()
        await set_membership(db, org, user, OrgRole.MEMBER)
        db.add(FormPermission(form_id=fid, user_id=user.id, role=FormRole(role)))
    await db.commit()

    async with make_client(app) as viewer:
        await login(viewer, queue, "viewer@example.org")
        assert (await viewer.get(f"/api/v1/forms/{fid}/draft/changes")).status_code == 403
        res = await viewer.post(
            f"/api/v1/forms/{fid}/draft/discard", json={"baseRevision": d["revision"]}
        )
        assert res.status_code == 403

    async with make_client(app) as editor:
        await login(editor, queue, "editor@example.org")
        body = (await editor.get(f"/api/v1/forms/{fid}/draft/changes")).json()
        assert body["summary"] == "1 question added"
        res = await editor.post(
            f"/api/v1/forms/{fid}/draft/discard", json={"baseRevision": d["revision"]}
        )
        assert res.status_code == 200
        assert [e["id"] for e in res.json()["schema"]["pages"][0]["elements"]] == ["a", "b"]
