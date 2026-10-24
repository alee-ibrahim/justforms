"""Phase 2 API: draft undo/redo, versions, duplicate, embed origins and the public form."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.services.users import create_admin
from tests.conftest import RecordingQueue, login


async def _form(
    client: AsyncClient, db: AsyncSession, settings: Settings, q: RecordingQueue, title: str
) -> dict[str, Any]:
    await create_admin(db, settings, "admin@example.org")
    await db.commit()
    me = await login(client, q, "admin@example.org")
    res = await client.post(f"/api/v1/orgs/{me['orgs'][0]['id']}/forms", json={"title": title})
    assert res.status_code == 201, res.text
    return dict(res.json())


def field(fid: str, **extra: Any) -> dict[str, Any]:
    return {"kind": "field", "id": fid, "type": "short_text", "label": fid, **extra}


async def patch(client: AsyncClient, form_id: str, rev: int, ops: list[dict[str, Any]]) -> Any:
    res = await client.patch(
        f"/api/v1/forms/{form_id}/draft", json={"baseRevision": rev, "patch": ops}
    )
    assert res.status_code == 200, res.text
    return res.json()


def ids(draft: dict[str, Any]) -> list[str]:
    return [e["id"] for e in draft["schema"]["pages"][0]["elements"]]


async def test_undo_redo(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    form = await _form(client, db, settings, queue, "Undo")
    fid = form["id"]
    draft = (await client.get(f"/api/v1/forms/{fid}/draft")).json()
    assert draft["canUndo"] is False and draft["canRedo"] is False

    d = await patch(
        client, fid, 1, [{"op": "add", "path": "/pages/0/elements/0", "value": field("a")}]
    )
    d = await patch(
        client, fid, 2, [{"op": "add", "path": "/pages/0/elements/1", "value": field("b")}]
    )
    assert ids(d) == ["a", "b"] and d["canUndo"] and not d["canRedo"]

    res = await client.post(f"/api/v1/forms/{fid}/draft/undo", json={"baseRevision": 3})
    assert res.status_code == 200, res.text
    d = res.json()
    assert ids(d) == ["a"] and d["revision"] == 4 and d["canUndo"] and d["canRedo"]

    d = (await client.post(f"/api/v1/forms/{fid}/draft/undo", json={"baseRevision": 4})).json()
    assert ids(d) == [] and not d["canUndo"] and d["canRedo"]

    # Nothing left to undo: unchanged.
    d = (await client.post(f"/api/v1/forms/{fid}/draft/undo", json={"baseRevision": 5})).json()
    assert d["revision"] == 5

    d = (await client.post(f"/api/v1/forms/{fid}/draft/redo", json={"baseRevision": 5})).json()
    assert ids(d) == ["a"] and d["canRedo"]

    # Stale base revision -> 409.
    res = await client.post(f"/api/v1/forms/{fid}/draft/redo", json={"baseRevision": 1})
    assert res.status_code == 409 and res.json()["revision"] == 6

    # A new edit drops the redo stack.
    d = await patch(
        client, fid, 6, [{"op": "add", "path": "/pages/0/elements/1", "value": field("c")}]
    )
    assert ids(d) == ["a", "c"] and not d["canRedo"]
    d = (await client.post(f"/api/v1/forms/{fid}/draft/undo", json={"baseRevision": 7})).json()
    assert ids(d) == ["a"]


async def test_versions_duplicate_and_embed_origins(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    form = await _form(client, db, settings, queue, "Survey")
    fid = form["id"]
    assert form["orgSlug"] and form["embedOrigins"] == []
    await patch(client, fid, 1, [{"op": "add", "path": "/pages/0/elements/0", "value": field("a")}])
    assert (await client.post(f"/api/v1/forms/{fid}/publish")).status_code == 200

    versions = (await client.get(f"/api/v1/forms/{fid}/versions")).json()
    assert versions[0]["publishedByName"]
    v1 = (await client.get(f"/api/v1/forms/{fid}/versions/1")).json()
    assert v1["schema"]["pages"][0]["elements"][0]["id"] == "a"
    assert (await client.get(f"/api/v1/forms/{fid}/versions/9")).status_code == 404

    res = await client.patch(f"/api/v1/forms/{fid}", json={"embedOrigins": ["https://example.org"]})
    assert res.status_code == 200 and res.json()["embedOrigins"] == ["https://example.org"]
    bad = await client.patch(f"/api/v1/forms/{fid}", json={"embedOrigins": ["javascript:x"]})
    assert bad.status_code == 422

    res = await client.post(f"/api/v1/forms/{fid}/duplicate")
    assert res.status_code == 201, res.text
    copy = res.json()
    assert copy["title"] == "Survey (copy)" and copy["status"] == "draft"
    assert copy["slug"] == "survey-copy"


DV_FORM_PAGE = [
    field("age_text"),
    {"kind": "field", "id": "age", "type": "number", "label": "age", "required": True},
    {
        "kind": "field",
        "id": "guardian",
        "type": "short_text",
        "label": "guardian",
        "required": True,
        "visibleIf": {"field": "age", "op": "lt", "value": 18},
    },
]


async def test_public_form_and_submit(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    form = await _form(client, db, settings, queue, "Apply")
    fid = form["id"]
    base = f"/api/v1/public/forms/{form['slug']}"

    # Not published yet -> 404.
    assert (await client.get(base)).status_code == 404

    await patch(
        client,
        fid,
        1,
        [
            {"op": "add", "path": f"/pages/0/elements/{i}", "value": el}
            for i, el in enumerate(DV_FORM_PAGE)
        ],
    )
    assert (await client.post(f"/api/v1/forms/{fid}/publish")).status_code == 200

    public = client  # same transport; the public API ignores cookies
    res = await public.get(base)
    assert res.status_code == 200, res.text
    live = res.json()
    assert live["version"] == 1 and live["schema"]["settings"]["title"] == "Apply"
    assert "thaanaFontCssUrl" in live

    url = f"{base}/submissions"
    # Required visible question missing -> 422 with the field.
    res = await public.post(url, json={"versionId": live["versionId"], "data": {"age": 15}})
    assert res.status_code == 422
    assert res.json()["errors"] == [{"field": "guardian", "code": "required"}]

    # Hidden answers are stripped; reference numbers count up per form.
    res = await public.post(
        url,
        json={"versionId": live["versionId"], "data": {"age": 30, "guardian": "x", "junk": 1}},
    )
    assert res.status_code == 201, res.text
    assert res.json() == {"seq": 1, "reference": "#0001"}
    res = await public.post(url, json={"versionId": live["versionId"], "data": {"age": 40}})
    assert res.json()["seq"] == 2

    # Stale version -> 409.
    await patch(client, fid, 2, [{"op": "replace", "path": "/settings/title", "value": "Apply 2"}])
    assert (await client.post(f"/api/v1/forms/{fid}/publish")).status_code == 200
    res = await public.post(url, json={"versionId": live["versionId"], "data": {"age": 40}})
    assert res.status_code == 409 and res.json()["detail"] == "version_changed"

    # Closed -> 410.
    assert (
        await client.patch(f"/api/v1/forms/{fid}", json={"status": "closed"})
    ).status_code == 200
    assert (await public.get(base)).status_code == 410


async def test_submissions_list_detail_and_status(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    form = await _form(client, db, settings, queue, "Intake")
    fid = form["id"]
    await patch(
        client, fid, 1, [{"op": "add", "path": "/pages/0/elements/0", "value": field("name")}]
    )
    assert (await client.post(f"/api/v1/forms/{fid}/publish")).status_code == 200
    base = f"/api/v1/public/forms/{form['slug']}"
    live = (await client.get(base)).json()
    for name in ["Aminath", "Ibrahim", "Mariyam"]:
        res = await client.post(
            f"{base}/submissions", json={"versionId": live["versionId"], "data": {"name": name}}
        )
        assert res.status_code == 201

    page = (await client.get(f"/api/v1/forms/{fid}/submissions?limit=2")).json()
    assert [i["seq"] for i in page["items"]] == [3, 2] and page["nextCursor"] == 2
    rest = (await client.get(f"/api/v1/forms/{fid}/submissions?cursor=2")).json()
    assert [i["seq"] for i in rest["items"]] == [1] and rest["nextCursor"] is None
    found = (await client.get(f"/api/v1/forms/{fid}/submissions?q=ibra")).json()
    assert [i["data"]["name"] for i in found["items"]] == ["Ibrahim"]

    sid = page["items"][0]["id"]
    detail = (await client.get(f"/api/v1/submissions/{sid}")).json()
    assert detail["schema"]["pages"][0]["elements"][0]["id"] == "name" and detail["canEdit"]

    res = await client.patch(f"/api/v1/submissions/{sid}", json={"status": "rejected"})
    assert res.status_code == 422
    res = await client.patch(
        f"/api/v1/submissions/{sid}", json={"status": "rejected", "reason": "Duplicate"}
    )
    assert res.status_code == 200 and res.json()["status"] == "rejected"
    stats = (await client.get(f"/api/v1/forms/{fid}/submissions/stats")).json()
    assert stats == {"new": 2, "in_review": 0, "approved": 0, "rejected": 1, "all": 3}
    filtered = (await client.get(f"/api/v1/forms/{fid}/submissions?status=new")).json()
    assert len(filtered["items"]) == 2
