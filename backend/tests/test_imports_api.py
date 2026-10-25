"""Jotform import endpoints (DESIGN 13): form preview -> draft, fetch by URL, and the
submissions import with mapping, the worker job, dedupe and the imported links."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.importers import service
from app.importers.jotform import fetch
from app.importers.jotform.fetch import FetchError, fetch_form_html
from app.models import FormPermission, FormRole, Submission, SubmissionEvent, User
from app.notifications.ssrf import Target
from app.storage import Storage
from tests.conftest import RecordingQueue, login, make_client
from tests.helpers import admin_client

FIXTURES = Path(__file__).parent / "fixtures" / "jotform"


def html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


async def _preview(client: AsyncClient, me: dict[str, Any], **body: Any) -> Any:
    return await client.post(f"/api/v1/orgs/{me['orgs'][0]['id']}/imports/jotform/html", json=body)


async def _imported_form(client: AsyncClient, me: dict[str, Any], name: str) -> str:
    res = await _preview(client, me, html=html(name))
    assert res.status_code == 201, res.text
    res = await client.post(f"/api/v1/imports/{res.json()['id']}/form", json={})
    assert res.status_code == 201, res.text
    return str(res.json()["formId"])


async def test_html_preview_and_create_draft(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    res = await _preview(client, me, html=html("all_controls.html"))
    assert res.status_code == 201, res.text
    preview = res.json()
    assert preview["status"] == "preview" and preview["kind"] == "jotform_html"
    assert preview["language"] == "en" and preview["detectedLanguage"] == "en"
    assert preview["pageCount"] == 2 and preview["fieldCount"] > 20
    assert preview["jotformFormId"] == "200000000000002"
    assert preview["report"]["counts"]["skipped"] == 2
    assert preview["formId"] is None
    # Nothing is created yet.
    forms = (await client.get(f"/api/v1/orgs/{me['orgs'][0]['id']}/forms")).json()
    assert forms == []

    res = await client.post(f"/api/v1/imports/{preview['id']}/form", json={"title": "Sign-up 2026"})
    assert res.status_code == 201, res.text
    form_id = res.json()["formId"]
    form = (await client.get(f"/api/v1/forms/{form_id}")).json()
    assert form["title"] == "Sign-up 2026" and form["status"] == "draft"
    assert form["captcha"] == "auto" and form["role"] == "owner"
    draft = (await client.get(f"/api/v1/forms/{form_id}/draft")).json()
    assert draft["schema"]["settings"]["submitLabel"] == "Sign me up"
    assert draft["schema"]["pages"][1]["title"] == "Details"
    # Created once.
    again = await client.post(f"/api/v1/imports/{preview['id']}/form", json={})
    assert again.status_code == 409
    got = (await client.get(f"/api/v1/imports/{preview['id']}")).json()
    assert got["status"] == "done" and got["formId"] == form_id


async def test_language_override_and_errors(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    res = await _preview(client, me, html=html("dhivehi_form.html"))
    assert res.json()["language"] == "dv"
    res = await _preview(client, me, html=html("dhivehi_form.html"), language="en")
    assert res.json()["language"] == "en" and res.json()["detectedLanguage"] == "dv"
    res = await client.post(f"/api/v1/imports/{res.json()['id']}/form", json={"language": "dv"})
    draft = (await client.get(f"/api/v1/forms/{res.json()['formId']}/draft")).json()
    assert draft["schema"]["settings"]["language"] == "dv"

    embed = '<iframe src="https://form.jotform.com/200000000000009"></iframe>'
    res = await _preview(client, me, html=embed)
    assert res.status_code == 422
    assert res.json() == {
        "detail": "not_a_jotform",
        "formUrl": "https://form.jotform.com/200000000000009",
    }
    assert (await _preview(client, me)).status_code == 422
    assert (await _preview(client, me, html="<p>x</p>", url="1")).status_code == 422
    res = await _preview(client, me, url="https://example.org/form")
    assert res.status_code == 422 and res.json()["detail"] == "fetch_not_jotform"


async def test_url_import_uses_fetch(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    me = await admin_client(client, db, settings, queue)
    calls: list[str] = []

    async def fake_fetch(url: str, _settings: Settings, **_: Any) -> tuple[str, str]:
        calls.append(url)
        return "https://form.jotform.com/200000000000001", html("registration_form.html")

    monkeypatch.setattr("app.api.v1.imports.fetch_form_html", fake_fetch)
    res = await _preview(client, me, url="https://form.jotform.com/200000000000001")
    assert res.status_code == 201, res.text
    assert calls == ["https://form.jotform.com/200000000000001"]
    assert res.json()["sourceUrl"] == "https://form.jotform.com/200000000000001"
    assert res.json()["report"]["counts"] == {"imported": 74, "changed": 5, "skipped": 0}


async def test_collapsible_sections_as_steps_option(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    res = await _preview(client, me, html=html("registration_form.html"))
    preview = res.json()
    assert preview["collapseSections"] == 5 and preview["collapseAsPages"] is True
    assert preview["pageCount"] == 5
    assert preview["schema"]["pages"][1]["title"] == "GOVERNANCE STRUCTURE"

    res = await client.patch(
        f"/api/v1/imports/{preview['id']}/options", json={"collapseAsPages": False}
    )
    assert res.status_code == 200, res.text
    sections = res.json()
    assert sections["collapseAsPages"] is False and sections["pageCount"] == 1
    assert sections["fieldCount"] == preview["fieldCount"]
    assert any("shown open" in n for n in sections["report"]["notes"])
    assert sections["report"]["logo"] == preview["report"]["logo"]

    res = await client.patch(
        f"/api/v1/imports/{preview['id']}/options", json={"collapseAsPages": True}
    )
    assert res.json()["pageCount"] == 5
    res = await client.post(f"/api/v1/imports/{preview['id']}/form", json={})
    draft = (await client.get(f"/api/v1/forms/{res.json()['formId']}/draft")).json()
    assert [p["title"] for p in draft["schema"]["pages"]][-1] == "DISCLAIMER AND SIGNATURE"
    res = await client.patch(
        f"/api/v1/imports/{preview['id']}/options", json={"collapseAsPages": False}
    )
    assert res.status_code == 409

    # Asked for up front, and not offered for a form without collapsible sections.
    res = await _preview(client, me, html=html("registration_form.html"), collapseAsPages=False)
    assert res.json()["pageCount"] == 1 and res.json()["collapseAsPages"] is False
    res = await _preview(client, me, html=html("all_controls.html"))
    assert res.json()["collapseSections"] == 0
    res = await client.patch(
        f"/api/v1/imports/{res.json()['id']}/options", json={"collapseAsPages": True}
    )
    assert res.status_code == 422


async def test_fetch_guard(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(url: str, _settings: Settings) -> Target:
        host = httpx.URL(url).host
        if host == "form.jotform.com":
            return Target(url=url, host=host, port=443, scheme="https", address="203.0.113.9")
        from app.notifications.ssrf import UrlRefused

        raise UrlRefused("private_address")

    monkeypatch.setattr(fetch, "resolve", resolve)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/redirect-out":
            return httpx.Response(302, headers={"location": "https://example.org/x"})
        if request.url.path == "/big":
            return httpx.Response(200, content=b"a" * (fetch.MAX_BYTES + 1))
        if request.url.path == "/hop":
            return httpx.Response(301, headers={"location": "/200000000000001"})
        return httpx.Response(200, text="<html>ok</html>")

    transport = httpx.MockTransport(handler)
    final, body = await fetch_form_html("form.jotform.com/hop", settings, transport=transport)
    assert final == "https://form.jotform.com/200000000000001" and "ok" in body
    # Connects to the checked address, with the real host name.
    assert seen[0].url.host == "203.0.113.9" and seen[0].headers["host"] == "form.jotform.com"
    with pytest.raises(FetchError) as out:
        await fetch_form_html(
            "https://form.jotform.com/redirect-out", settings, transport=transport
        )
    assert out.value.code == "not_jotform"
    with pytest.raises(FetchError) as big:
        await fetch_form_html("https://form.jotform.com/big", settings, transport=transport)
    assert big.value.code == "too_large"


async def _publish(client: AsyncClient, form_id: str) -> None:
    res = await client.post(f"/api/v1/forms/{form_id}/publish")
    assert res.status_code == 200, res.text


async def _upload(client: AsyncClient, form_id: str, data: bytes, name: str) -> Any:
    return await client.post(
        f"/api/v1/forms/{form_id}/imports/submissions",
        params={"filename": name},
        content=data,
        headers={"Content-Type": "text/csv"},
    )


async def test_submissions_import_end_to_end(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    form_id = await _imported_form(client, me, "registration_form.html")
    csv_bytes = (FIXTURES / "registration_submissions.csv").read_bytes()

    res = await _upload(client, form_id, csv_bytes, "export.csv")
    assert res.status_code == 409 and res.json()["detail"] == "not_published"
    await _publish(client, form_id)

    res = await _upload(client, form_id, csv_bytes, "export.csv")
    assert res.status_code == 201, res.text
    up = res.json()
    assert up["rowCount"] == 4 and up["version"] == 1 and up["filename"] == "export.csv"
    targets = [c["target"] for c in up["columns"]]
    assert targets[0] == "meta:submitted_at" and "ignore" not in targets
    assert up["columns"][1]["samples"][:2] == ["Riverside Volunteers", "Hill Garden Club"]
    assert {"value": "field:group_name", "label": "Group Name", "type": "short_text"} in up[
        "targets"
    ]

    # Ignore the acronym column; preview the first rows.
    targets[2] = "ignore"
    res = await client.put(f"/api/v1/imports/{up['id']}/mapping", json={"columns": targets})
    assert res.status_code == 200, res.text
    preview = res.json()
    assert preview["hasSubmissionId"] and preview["duplicateTargets"] == []
    assert preview["problems"] == 1  # the bad email in row 3
    first = preview["rows"][0]
    assert first["row"] == 2
    cells = {c["column"]: c for c in first["cells"]}
    assert 2 not in cells
    assert cells[1]["text"] == "Riverside Volunteers"
    assert cells[0]["text"] == "2025-03-14 09:12"
    bad = [c for c in preview["rows"][1]["cells"] if c["problem"]]
    assert [(c["column"], c["problem"]) for c in bad] == [(7, "email")]

    dup = list(targets)
    dup[3] = "field:group_name"
    res = await client.put(f"/api/v1/imports/{up['id']}/mapping", json={"columns": dup})
    assert res.json()["duplicateTargets"] == ["field:group_name"]
    bad_target = await client.put(
        f"/api/v1/imports/{up['id']}/mapping", json={"columns": ["field:nope"] * 53}
    )
    assert bad_target.status_code == 422
    res = await client.post(f"/api/v1/imports/{up['id']}/start", json={})
    assert res.status_code == 422 and res.json()["detail"] == "mapping_duplicate"
    await client.put(f"/api/v1/imports/{up['id']}/mapping", json={"columns": targets})

    res = await client.post(f"/api/v1/imports/{up['id']}/start", json={"status": "in_review"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "running"
    assert queue.jobs[-1] == ("import_submissions", {"import_id": up["id"]})
    again = await client.post(f"/api/v1/imports/{up['id']}/start", json={})
    assert again.status_code == 409

    assert await service.run_submissions_import(db, file_storage, settings, uuid.UUID(up["id"]))
    done = (await client.get(f"/api/v1/imports/{up['id']}")).json()
    assert done["status"] == "done"
    report = done["report"]
    assert report["imported"] == 3 and report["skippedDuplicate"] == 1
    assert report["cellsDropped"] == 1 and report["droppedByColumn"] == {"Email": 1}
    assert report["links"] == 4 and report["dedupe"] is True
    assert report["problemRows"] == [
        {"row": 3, "column": "Email", "problem": "email", "value": "not-an-email"}
    ]
    assert not await file_storage.exists(f"imports/{up['id']}/source.csv")

    page = (
        await client.get(f"/api/v1/forms/{form_id}/submissions", params={"status": "in_review"})
    ).json()
    assert page["total"] == 3
    assert {s["source"] for s in page["items"]} == {"jotform_import"}
    rows = (
        await db.scalars(select(Submission).where(Submission.form_id == uuid.UUID(form_id)))
    ).all()
    by_ext = {r.external_id: r for r in rows}
    first_sub = by_ext["6100000000000000001"]
    assert first_sub.data["group_name"] == "Riverside Volunteers"
    assert "acronym" not in first_sub.data
    assert first_sub.submitted_at.isoformat().startswith("2025-03-14")
    assert str(first_sub.ip) == "192.0.2.10"
    assert first_sub.content_hash
    detail = (await client.get(f"/api/v1/submissions/{first_sub.id}")).json()
    assert detail["source"] == "jotform_import"
    assert detail["externalId"] == "6100000000000000001"
    assert set(detail["importedLinks"]) == {"group_profile", "signature"}
    assert detail["events"][0]["payload"]["imported"] is True
    assert detail["events"][0]["payload"]["jotformSubmissionId"] == "6100000000000000001"
    verify = (await client.get(f"/api/v1/submissions/{first_sub.id}/verify")).json()
    assert verify["ok"] is True
    events = (
        await db.scalars(
            select(SubmissionEvent).where(SubmissionEvent.submission_id == first_sub.id)
        )
    ).all()
    assert len(events) == 1
    # Imported rows send no notifications or webhooks.
    assert not any(job == "dispatch_event" for job, _ in queue.jobs)

    # The same file again adds nothing.
    res = await _upload(client, form_id, csv_bytes, "export.csv")
    second = res.json()
    await client.put(
        f"/api/v1/imports/{second['id']}/mapping",
        json={"columns": [c["target"] for c in second["columns"]]},
    )
    await client.post(f"/api/v1/imports/{second['id']}/start", json={})
    assert await service.run_submissions_import(db, file_storage, settings, uuid.UUID(second["id"]))
    report2 = (await client.get(f"/api/v1/imports/{second['id']}")).json()["report"]
    assert report2["imported"] == 0 and report2["skippedDuplicate"] == 4
    history = (await client.get(f"/api/v1/forms/{form_id}/imports")).json()
    assert [h["id"] for h in history] == [second["id"], up["id"]]


async def test_submissions_import_needs_owner(
    app: Any, client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    form_id = await _imported_form(client, me, "dhivehi_form.html")
    await _publish(client, form_id)
    res = await _upload(client, form_id, b"Submission ID,x\n1,2\n", "a.csv")
    assert res.status_code == 201
    import_id = res.json()["id"]
    editor = User(email="editor@example.org")
    db.add(editor)
    await db.flush()
    db.add(FormPermission(form_id=uuid.UUID(form_id), user_id=editor.id, role=FormRole.EDITOR))
    await db.commit()
    async with make_client(app) as other:
        await login(other, queue, "editor@example.org")
        assert (await _upload(other, form_id, b"a\n1\n", "a.csv")).status_code == 403
        assert (await other.get(f"/api/v1/imports/{import_id}")).status_code == 404
    bad = await _upload(client, form_id, b"", "empty.csv")
    assert bad.status_code == 422 and bad.json()["detail"] == "file_empty"
    nothing = await client.post(f"/api/v1/imports/{import_id}/start", json={})
    assert nothing.status_code == 422 and nothing.json()["detail"] == "nothing_mapped"
