"""Sharing with "Notify by email": emailing members given a form role (DESIGN 7, 11.1)."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import worker
from app.config import Settings
from app.models import AuditLog, EmailDelivery, EmailStatus
from app.notifications import events
from app.services.users import create_admin
from app.storage import Storage
from tests.conftest import RecordingQueue, login
from tests.test_access import _member

OWNER = {"email": "owner@example.org", "role": "owner"}
EDITOR = {"email": "editor@example.org", "role": "editor"}
VIEWER = {"email": "viewer@example.org", "role": "viewer"}


async def _setup(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> tuple[str, str]:
    await create_admin(db, settings, "root@example.org", "Root Admin")
    await _member(db, settings, "owner@example.org", "Aminath Ali")
    await _member(db, settings, "editor@example.org", "Ibrahim Naseer")
    await _member(db, settings, "viewer@example.org")
    me = await login(client, queue, "owner@example.org")
    form = (
        await client.post(
            f"/api/v1/orgs/{me['orgs'][0]['id']}/forms", json={"title": "Leave requests"}
        )
    ).json()
    queue.jobs.clear()
    return form["id"], f"/api/v1/forms/{form['id']}/permissions"


async def _shared(db: AsyncSession) -> list[EmailDelivery]:
    rows = await db.scalars(
        select(EmailDelivery)
        .where(EmailDelivery.kind == "form_shared")
        .order_by(EmailDelivery.created_at, EmailDelivery.to_address)
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def test_emails_added_people_only(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    settings.smtp_host = "smtp.example.org"
    form_id, url = await _setup(client, db, settings, queue)
    assert (await client.get(url)).json()["smtpEnabled"] is True
    note = 'Please review <b>these</b> & "approve"\r\nThanks\x07'
    res = await client.put(
        url, json={"grants": [OWNER, EDITOR, VIEWER], "notify": True, "message": note}
    )
    assert res.status_code == 200, res.text
    # The two people added; never the owner making the change.
    rows = await _shared(db)
    assert sorted(r.to_address for r in rows) == ["editor@example.org", "viewer@example.org"]
    assert [fn for fn, _ in queue.jobs] == ["send_form_email", "send_form_email"]
    assert {kw["email_id"] for _, kw in queue.jobs} == {str(r.id) for r in rows}
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "form.permissions_notify"))
    assert entry is not None and entry.meta["with_message"] is True
    assert len(entry.meta["user_ids"]) == 2

    by_to = {r.to_address: r for r in rows}
    editor = await events.render_email(db, settings, file_storage, by_to["editor@example.org"])
    viewer = await events.render_email(db, settings, file_storage, by_to["viewer@example.org"])
    assert editor is not None and viewer is not None
    assert editor.subject == "Aminath Ali shared “Leave requests” with you"
    assert editor.reply_to == "owner@example.org"
    assert "You're now an editor: you can edit the form and manage submissions." in editor.text
    assert f"/forms/{form_id}/edit" in editor.text and "Open the form" in editor.text
    assert "You're now a submissions viewer: you can view and export submissions." in viewer.text
    assert f"/forms/{form_id}/submissions" in viewer.text and "Open the submissions" in viewer.text
    # The note is plain text: escaped in HTML, attributed to the sharer, control chars dropped.
    assert editor.html is not None
    assert "Please review &lt;b&gt;these&lt;/b&gt; &amp; &#34;approve&#34;\nThanks<" in editor.html
    assert "<b>these</b>" not in editor.html and "Aminath Ali</bdi> wrote:" in editor.html
    assert 'Aminath Ali wrote:\nPlease review <b>these</b> & "approve"\nThanks\n' in editor.text

    # Lowering a role, removing someone and saving without notify email nobody.
    queue.jobs.clear()
    viewer_only = {"email": "editor@example.org", "role": "viewer"}
    res = await client.put(url, json={"grants": [OWNER, viewer_only], "notify": True})
    assert res.status_code == 200
    res = await client.put(url, json={"grants": [OWNER, EDITOR, VIEWER]})
    assert res.status_code == 200
    assert len(await _shared(db)) == 2 and queue.jobs == []

    # Raising a role emails that person, worded as a change.
    promoted = {"email": "viewer@example.org", "role": "owner"}
    res = await client.put(url, json={"grants": [OWNER, EDITOR, promoted], "notify": True})
    assert res.status_code == 200
    upgraded = [r for r in await _shared(db) if events.share_detail(r).get("upgraded")]
    assert [r.to_address for r in upgraded] == ["viewer@example.org"]
    msg = await events.render_email(db, settings, file_storage, upgraded[0])
    assert msg is not None
    assert msg.subject == "Aminath Ali changed your access to “Leave requests”"
    assert "You're now an owner" in msg.text and "wrote:" not in msg.text


async def test_worker_sends_and_forgets_the_note(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    db: AsyncSession,
    db_engine: Any,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    settings.smtp_host = "smtp.example.org"
    _form_id, url = await _setup(client, db, settings, queue)
    sent: list[dict[str, Any]] = []

    async def smtp(_settings: Settings, to: str, subject: str, text: str, **kw: Any) -> bool:
        sent.append({"to": to, "subject": subject, "reply_to": kw.get("reply_to")})
        return True

    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "get_sessionmaker", lambda: maker)
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "smtp_send", smtp)
    res = await client.put(
        url, json={"grants": [OWNER, VIEWER], "notify": True, "message": "Hello"}
    )
    assert res.status_code == 200
    for fn, kw in queue.jobs:
        assert fn == "send_form_email"
        assert await worker.send_form_email({"job_try": 1}, **kw)
    assert sent == [
        {
            "to": "viewer@example.org",
            "subject": "Aminath Ali shared “Leave requests” with you",
            "reply_to": "owner@example.org",
        }
    ]
    (row,) = await _shared(db)
    assert row.status == EmailStatus.SENT and "note" not in events.share_detail(row)

    # Access removed before the email goes out: nothing is sent, the note is dropped.
    queue.jobs.clear()
    res = await client.put(url, json={"grants": [OWNER, EDITOR], "notify": True, "message": "x"})
    assert res.status_code == 200
    await client.put(url, json={"grants": [OWNER]})
    ((_fn, kw),) = queue.jobs
    assert await worker.send_form_email({"job_try": 1}, **kw) is False
    assert len(sent) == 1
    late = [r for r in await _shared(db) if r.to_address == "editor@example.org"]
    assert late[0].status == EmailStatus.FAILED and "note" not in events.share_detail(late[0])


async def test_rate_limit_and_smtp_off(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    _form_id, url = await _setup(client, db, settings, queue)
    grants = [OWNER, EDITOR, VIEWER]
    # Email not set up: the option is off and saving still works, without email.
    assert (await client.get(url)).json()["smtpEnabled"] is False
    res = await client.put(url, json={"grants": grants, "notify": True, "message": "Hi"})
    assert res.status_code == 200 and await _shared(db) == [] and queue.jobs == []

    # Too long a note is refused.
    await client.put(url, json={"grants": [OWNER]})
    settings.smtp_host = "smtp.example.org"
    res = await client.put(url, json={"grants": grants, "notify": True, "message": "x" * 501})
    assert res.status_code == 422

    # Over the limit nothing is saved; saving without notify still works.
    settings.rate_limits = ["share_notify_user=1/3600"]
    res = await client.put(url, json={"grants": grants, "notify": True})
    assert res.status_code == 429
    entries = (await client.get(url)).json()["entries"]
    assert [e["email"] for e in entries if not e["orgAdmin"]] == ["owner@example.org"]
    res = await client.put(url, json={"grants": grants, "notify": False})
    assert res.status_code == 200 and await _shared(db) == []
