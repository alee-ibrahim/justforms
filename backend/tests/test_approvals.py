"""Approval workflow (DESIGN 15.3): settings, publish checks, the approver page, decisions,
emails, webhooks, the status lock and the printed record."""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from arq import Retry
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import worker
from app.config import Settings
from app.integrity import verify_submission
from app.models import (
    ApprovalState,
    ApprovalStep,
    EmailDelivery,
    StepState,
    Submission,
    SubmissionStatus,
    Webhook,
    WebhookDelivery,
)
from app.notifications import events as notify
from app.notifications import webhooks as wh
from app.pdf.service import approval_lines, generate_pdf
from app.storage import Storage
from tests.conftest import RecordingQueue
from tests.helpers import Published, admin_client, field, publish
from tests.test_signatures import signature_value

SUPERVISOR = "boss@example.org"
DIRECTOR = "director@example.org"
RESPONDENT = "applicant@example.org"


async def _form(client: AsyncClient, me: dict[str, Any], *, optional: bool = False) -> Published:
    return await publish(
        client,
        me,
        [
            field("full_name", required=True),
            field("my_email", "email", required=True, label="Your email"),
            field("supervisor", "email", required=not optional, label="Supervisor's email"),
            field("national_id", sensitive=True),
            field("sign", "signature", required=True, attestation="I confirm."),
        ],
        title="Leave request",
    )


def _config(**extra: Any) -> dict[str, Any]:
    return {
        "enabled": True,
        "steps": [
            {"name": "Supervisor", "source": "field", "fieldId": "supervisor"},
            {"name": "Director", "source": "fixed", "email": DIRECTOR.upper()},
        ],
        "notifyRespondent": True,
        "respondentEmailField": "my_email",
        **extra,
    }


async def _submit(client: AsyncClient, pub: Published, supervisor: str | None = SUPERVISOR) -> str:
    data: dict[str, Any] = {
        "full_name": "Aminath Ali",
        "my_email": RESPONDENT,
        "national_id": "A123456",
        "sign": signature_value(),
    }
    if supervisor:
        data["supervisor"] = supervisor
    res = await client.post(f"{pub.base}/submissions", json=pub.submit_body(data))
    assert res.status_code == 201, res.text
    page = (await client.get(f"/api/v1/forms/{pub.id}/submissions?status=in_review")).json()
    return str(page["items"][0]["id"])


async def _send(db: AsyncSession, settings: Settings, storage: Storage, email_id: str) -> Any:
    """What the worker does for one notification email: render (mints approver links)."""
    row = await db.get(EmailDelivery, uuid.UUID(email_id))
    assert row is not None
    msg = await notify.render_email(db, settings, storage, row)
    notify.mark_sent(row)
    await db.commit()
    return row, msg


def _emails(queue: RecordingQueue) -> list[str]:
    return [kw["email_id"] for fn, kw in queue.jobs if fn == "send_form_email"]


async def _approver_link(
    db: AsyncSession, settings: Settings, storage: Storage, queue: RecordingQueue, to: str
) -> str:
    for email_id in reversed(_emails(queue)):
        row = await db.get(EmailDelivery, uuid.UUID(email_id))
        if row and row.kind == "approval_request" and row.to_address == to:
            _row, msg = await _send(db, settings, storage, email_id)
            assert msg is not None
            match = re.search(r"/a/([A-Za-z0-9_-]+)", msg.text)
            assert match, msg.text
            return match.group(1)
    raise AssertionError(f"no approval email to {to}")


async def _sign_in(client: AsyncClient, queue: RecordingQueue, token: str, email: str) -> str:
    res = await client.post(f"/api/v1/public/approvals/{token}/code")
    assert res.status_code == 202, res.text
    code = queue.last_code(email)
    res = await client.post(f"/api/v1/public/approvals/{token}/verify", json={"code": code})
    assert res.status_code == 200, res.text
    return str(res.json()["token"])


async def test_settings_are_checked_and_owner_only(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me, optional=True)
    url = f"/api/v1/forms/{pub.id}/approvals"
    got = (await client.get(url)).json()
    assert got["config"]["enabled"] is False and got["issues"] == []
    assert [f["id"] for f in got["emailFields"]] == ["my_email", "supervisor"]

    bad = _config(steps=[{"name": "A", "source": "field", "fieldId": "full_name"}])
    res = await client.put(url, json=bad)
    assert res.status_code == 422 and res.json()["issues"][0]["code"] == "source_not_email"
    res = await client.put(url, json=_config(steps=[{"name": "A", "source": "fixed"}]))
    assert res.json()["issues"][0]["code"] == "email_missing"
    res = await client.put(url, json=_config(steps=[{"name": "A", "source": "field"}]))
    assert res.json()["issues"][0]["code"] == "field_missing"
    four = _config(steps=[{"name": str(i), "source": "fixed", "email": DIRECTOR} for i in range(4)])
    assert (await client.put(url, json=four)).status_code == 422

    res = await client.put(url, json=_config())
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["config"]["steps"][1]["email"] == DIRECTOR  # normalised
    # The optional supervisor question is a warning, not an error.
    assert [(i["step"], i["code"], i["level"]) for i in body["issues"]] == [
        (1, "source_optional", "warning")
    ]


async def test_publish_needs_the_approver_question(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    assert (
        await client.put(f"/api/v1/forms/{pub.id}/approvals", json=_config())
    ).status_code == 200
    draft = (await client.get(f"/api/v1/forms/{pub.id}/draft")).json()
    ids = [e["id"] for e in draft["schema"]["pages"][0]["elements"]]
    res = await client.patch(
        f"/api/v1/forms/{pub.id}/draft",
        json={
            "baseRevision": draft["revision"],
            "patch": [{"op": "remove", "path": f"/pages/0/elements/{ids.index('supervisor')}"}],
        },
    )
    assert res.status_code == 200, res.text
    res = await client.post(f"/api/v1/forms/{pub.id}/publish")
    assert res.status_code == 422
    assert res.json()["issues"][0]["code"] == "approval_source_missing"
    got = (await client.get(f"/api/v1/forms/{pub.id}/approvals")).json()
    assert got["issues"][0]["code"] == "source_missing"


async def test_two_step_approval_end_to_end(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    await client.put(f"/api/v1/forms/{pub.id}/approvals", json=_config())
    hook = Webhook(
        form_id=uuid.UUID(pub.id),
        url="https://hooks.example.org/x",
        secret_enc=wh.encrypt(settings, wh.new_secret()),
        events=["submission.approval_step", "submission.status_changed"],
    )
    db.add(hook)
    await db.commit()
    sid = await _submit(client, pub)

    detail = (await client.get(f"/api/v1/submissions/{sid}")).json()
    assert detail["status"] == "in_review"
    assert detail["approval"]["state"] == "pending" and detail["approval"]["step"] == 1
    steps = detail["approval"]["steps"]
    assert [(s["name"], s["state"], s["approverEmail"]) for s in steps] == [
        ("Supervisor", "pending", SUPERVISOR),
        ("Director", "waiting", DIRECTOR),
    ]
    assert detail["approval"]["outcomeTo"] == RESPONDENT
    assert [e["type"] for e in reversed(detail["events"])][:3] == [
        "created",
        "status_changed",
        "approval_requested",
    ]
    listed = (await client.get(f"/api/v1/forms/{pub.id}/submissions")).json()["items"][0]
    assert listed["approval"] == {"state": "pending", "step": 1, "total": 2}

    # Staff can't set the status while the approval runs; bulk changes skip it.
    res = await client.patch(f"/api/v1/submissions/{sid}", json={"status": "approved"})
    assert res.status_code == 409 and res.json()["detail"] == "approval_in_progress"
    res = await client.post(
        f"/api/v1/forms/{pub.id}/submissions/bulk",
        json={"ids": [sid], "action": "status", "status": "approved"},
    )
    assert res.json() == {"changed": 0}

    # Step 1: the supervisor's link, code and the submission without sensitive answers.
    token = await _approver_link(db, settings, file_storage, queue, SUPERVISOR)
    staff_cookies = dict(client.cookies)
    client.cookies.clear()
    link = (await client.get(f"/api/v1/public/approvals/{token}")).json()
    assert link["state"] == "pending" and link["stepName"] == "Supervisor"
    assert link["total"] == 2 and link["maskedEmail"] == "b•••@example.org"
    assert "A123456" not in str(link)
    assert (await client.get(f"/api/v1/public/approvals/{token}/submission")).status_code == 401
    bearer = await _sign_in(client, queue, token, SUPERVISOR)
    auth = {"Authorization": f"Bearer {bearer}"}
    view = (await client.get(f"/api/v1/public/approvals/{token}/submission", headers=auth)).json()
    assert view["data"]["full_name"] == "Aminath Ali"
    assert "national_id" not in view["data"] and view["hidden"] == ["national_id"]
    assert view["signatures"] == ["sign"]
    sig = await client.get(f"/api/v1/public/approvals/{token}/signatures/sign", headers=auth)
    assert sig.status_code == 200 and sig.content.startswith(b"\x89PNG")
    # Rejecting needs a comment; approving moves on to the director.
    res = await client.post(
        f"/api/v1/public/approvals/{token}/decision",
        json={"decision": "reject", "name": "Hassan Ali"},
        headers=auth,
    )
    assert res.status_code == 422
    res = await client.post(
        f"/api/v1/public/approvals/{token}/decision",
        json={"decision": "approve", "name": "Hassan Ali"},
        headers=auth,
    )
    assert res.status_code == 200, res.text
    assert res.json() == {**res.json(), "state": "approved", "nextStep": 2, "final": False}
    again = await client.post(
        f"/api/v1/public/approvals/{token}/decision",
        json={"decision": "approve", "name": "Hassan Ali"},
        headers=auth,
    )
    assert again.status_code == 409 and again.json()["detail"] == "approval_done"
    assert (await client.get(f"/api/v1/public/approvals/{token}")).json()["state"] == "approved"

    # Step 2: the fixed director address.
    token2 = await _approver_link(db, settings, file_storage, queue, DIRECTOR)
    bearer2 = await _sign_in(client, queue, token2, DIRECTOR)
    res = await client.post(
        f"/api/v1/public/approvals/{token2}/decision",
        json={"decision": "approve", "name": "Mariyam Hassan", "comment": "Fine."},
        headers={"Authorization": f"Bearer {bearer2}"},
    )
    assert res.json()["final"] is True

    client.cookies.update(staff_cookies)
    detail = (await client.get(f"/api/v1/submissions/{sid}")).json()
    assert detail["status"] == "approved" and detail["approval"]["state"] == "approved"
    assert detail["pdfStatus"] == "pending"
    assert ("render_submission_pdf", {"submission_id": sid}) in queue.jobs
    events = [kw for fn, kw in queue.jobs if fn == "dispatch_event"]
    actions = [e["extra"]["action"] for e in events if e["event"] == "submission.approval_step"]
    assert actions == ["requested", "approved", "requested", "approved"]
    final = [e for e in events if e["event"] == "submission.status_changed"]
    assert final[-1]["extra"] == {"from": "in_review", "to": "approved", "via": "approval"}
    jobs = await notify.dispatch(
        db, settings, "submission.approval_step", uuid.UUID(sid), extra={"action": "approved"}
    )
    assert len(jobs.webhook_deliveries) == 1
    delivery = await db.get(WebhookDelivery, jobs.webhook_deliveries[0])
    assert delivery is not None and delivery.payload["change"] == {"action": "approved"}
    assert delivery.payload["submission"]["data"]["national_id"] == "[redacted]"

    # The final PDF carries the record; then the outcome email goes out with it.
    sub = await db.get(Submission, uuid.UUID(sid))
    assert sub is not None
    lines = await approval_lines(db, sub)
    assert [(ln.step, ln.outcome, ln.approver_name, ln.approver_email) for ln in lines] == [
        (1, "approved", "Hassan Ali", SUPERVISOR),
        (2, "approved", "Mariyam Hassan", DIRECTOR),
    ]
    assert await generate_pdf(db, file_storage, settings, uuid.UUID(sid))
    jobs = await notify.dispatch(db, settings, "submission.pdf_ready", uuid.UUID(sid))
    rows = [await db.get(EmailDelivery, i) for i in jobs.emails]
    outcome = [r for r in rows if r and r.kind == "approval_outcome"]
    assert len(outcome) == 1 and outcome[0].to_address == RESPONDENT
    _row, msg = await _send(db, settings, file_storage, str(outcome[0].id))
    assert msg.subject.startswith("Approved: Leave request")
    assert msg.attachments and msg.attachments[0][0] == "submission-0001.pdf"
    # Only once.
    again_jobs = await notify.dispatch(db, settings, "submission.pdf_ready", uuid.UUID(sid))
    assert not again_jobs.emails

    await db.refresh(sub)
    assert (await verify_submission(db, sub)).ok
    verify = (await client.get(f"/api/v1/public/verify/{sub.verify_token}")).json()
    assert verify["approval"]["state"] == "approved" and verify["approval"]["total"] == 2
    assert verify["approval"]["decidedAt"]

    # Finished: the status is the staff's again, and the record stays.
    res = await client.patch(f"/api/v1/submissions/{sid}", json={"status": "in_review"})
    assert res.status_code == 200
    assert res.json()["approval"]["state"] == "approved"


async def test_rejection_ends_the_approval(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    await client.put(f"/api/v1/forms/{pub.id}/approvals", json=_config())
    sid = await _submit(client, pub)
    token = await _approver_link(db, settings, file_storage, queue, SUPERVISOR)
    client.cookies.clear()
    bearer = await _sign_in(client, queue, token, SUPERVISOR)
    res = await client.post(
        f"/api/v1/public/approvals/{token}/decision",
        json={"decision": "reject", "name": "Hassan Ali", "comment": "Dates clash with an audit."},
        headers={"Authorization": f"Bearer {bearer}"},
    )
    assert res.json()["final"] is True
    sub = await db.get(Submission, uuid.UUID(sid))
    assert sub is not None
    await db.refresh(sub)
    assert sub.status == SubmissionStatus.REJECTED
    assert sub.approval_state == ApprovalState.REJECTED
    steps = list(await db.scalars(select(ApprovalStep).order_by(ApprovalStep.step)))
    assert [s.state for s in steps] == [StepState.REJECTED, StepState.WAITING]
    # The director is never asked.
    assert not [
        e
        for e in await db.scalars(select(EmailDelivery))
        if e.kind == "approval_request" and e.to_address == DIRECTOR
    ]
    # A PDF failure still sends the outcome, without the file.
    jobs = await notify.dispatch(db, settings, notify.PDF_FAILED, uuid.UUID(sid))
    row = await db.get(EmailDelivery, jobs.emails[0])
    assert row is not None and row.kind == "approval_outcome"
    _row, msg = await _send(db, settings, file_storage, str(row.id))
    assert msg.subject.startswith("Not approved")
    assert "Dates clash with an audit." in msg.text and not msg.attachments
    lines = await approval_lines(db, sub)
    assert [(ln.step, ln.outcome) for ln in lines] == [(1, "rejected")]


async def test_missing_approver_waits_until_stopped(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me, optional=True)
    await client.put(f"/api/v1/forms/{pub.id}/approvals", json=_config(notifyRespondent=False))
    sid = await _submit(client, pub, supervisor=None)
    detail = (await client.get(f"/api/v1/submissions/{sid}")).json()
    assert detail["approval"]["steps"][0]["state"] == "no_approver"
    assert detail["approval"]["outcomeTo"] is None
    assert detail["events"][0]["type"] == "approval_waiting"
    assert (await client.post(f"/api/v1/submissions/{sid}/approval/resend")).status_code == 409
    res = await client.post(f"/api/v1/submissions/{sid}/approval/stop", json={"reason": "No boss"})
    assert res.status_code == 200
    detail = (await client.get(f"/api/v1/submissions/{sid}")).json()
    assert detail["approval"]["state"] == "stopped"
    assert detail["events"][0]["type"] == "approval_stopped"
    assert detail["events"][0]["payload"]["reason"] == "No boss"
    res = await client.patch(f"/api/v1/submissions/{sid}", json={"status": "approved"})
    assert res.status_code == 200 and res.json()["status"] == "approved"
    assert (
        await client.post(f"/api/v1/submissions/{sid}/approval/stop", json={"reason": "x"})
    ).status_code == 409


async def test_resend_replaces_the_link(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    await client.put(f"/api/v1/forms/{pub.id}/approvals", json=_config())
    sid = await _submit(client, pub)
    first = await _approver_link(db, settings, file_storage, queue, SUPERVISOR)
    staff = dict(client.cookies)
    client.cookies.clear()
    bearer = await _sign_in(client, queue, first, SUPERVISOR)
    client.cookies.update(staff)
    assert (await client.post(f"/api/v1/submissions/{sid}/approval/resend")).status_code == 202
    second = await _approver_link(db, settings, file_storage, queue, SUPERVISOR)
    assert second != first
    client.cookies.clear()
    assert (await client.get(f"/api/v1/public/approvals/{first}")).status_code == 404
    assert (await client.get(f"/api/v1/public/approvals/{second}")).status_code == 200
    # A session from the old link is over too.
    res = await client.get(
        f"/api/v1/public/approvals/{second}/submission",
        headers={"Authorization": f"Bearer {bearer}"},
    )
    assert res.status_code == 401
    # Without a staff session nobody can act on the approval from the studio side.
    assert (await client.post(f"/api/v1/submissions/{sid}/approval/resend")).status_code == 401


# --- The worker commits the approver link before it sends the email ---------------------


class _CommitFails(AsyncSession):
    async def commit(self) -> None:
        raise OSError("database went away")


def _use_worker(
    monkeypatch: pytest.MonkeyPatch,
    db_engine: Any,
    settings: Settings,
    storage: Storage,
    smtp: Any,
    session_class: type[AsyncSession] = AsyncSession,
) -> None:
    maker = async_sessionmaker(db_engine, class_=session_class, expire_on_commit=False)
    smtp_settings = settings.model_copy(update={"smtp_host": "smtp.example.org"})
    monkeypatch.setattr(worker, "get_sessionmaker", lambda: maker)
    monkeypatch.setattr(worker, "get_settings", lambda: smtp_settings)
    monkeypatch.setattr(worker, "get_storage", lambda: storage)
    monkeypatch.setattr(worker, "smtp_send", smtp)


async def _request_email(db: AsyncSession, queue: RecordingQueue, to: str) -> str:
    for email_id in reversed(_emails(queue)):
        row = await db.get(EmailDelivery, uuid.UUID(email_id))
        if row and row.kind == "approval_request" and row.to_address == to:
            return email_id
    raise AssertionError(f"no approval email to {to}")


def _token(text: str) -> str:
    match = re.search(r"/a/([A-Za-z0-9_-]+)", text)
    assert match, text
    return match.group(1)


async def _link_status(client: AsyncClient, token: str) -> int:
    return (await client.get(f"/api/v1/public/approvals/{token}")).status_code


async def test_worker_link_works_as_soon_as_the_email_is_sent(
    client: AsyncClient,
    db: AsyncSession,
    db_engine: Any,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    await client.put(f"/api/v1/forms/{pub.id}/approvals", json=_config())
    await _submit(client, pub)
    email_id = await _request_email(db, queue, SUPERVISOR)
    seen: list[tuple[str, int]] = []

    async def smtp(_s: Settings, to: str, subject: str, text: str, **_kw: Any) -> bool:
        # The approver opens the link while the email is still being handed over.
        token = _token(text)
        seen.append((token, await _link_status(client, token)))
        return True

    _use_worker(monkeypatch, db_engine, settings, file_storage, smtp)
    assert await worker.send_form_email({"job_try": 1}, email_id=email_id) is True
    assert len(seen) == 1 and seen[0][1] == 200
    db.expire_all()
    row = await db.get(EmailDelivery, uuid.UUID(email_id))
    assert row is not None and row.status == "sent" and row.attempts == 1


async def test_worker_sends_nothing_when_the_link_cannot_be_saved(
    client: AsyncClient,
    db: AsyncSession,
    db_engine: Any,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    await client.put(f"/api/v1/forms/{pub.id}/approvals", json=_config())
    sid = await _submit(client, pub)
    first = await _approver_link(db, settings, file_storage, queue, SUPERVISOR)
    assert (await client.post(f"/api/v1/submissions/{sid}/approval/resend")).status_code == 202
    email_id = await _request_email(db, queue, SUPERVISOR)
    sent: list[str] = []

    async def smtp(_s: Settings, to: str, subject: str, text: str, **_kw: Any) -> bool:
        sent.append(_token(text))
        return True

    _use_worker(monkeypatch, db_engine, settings, file_storage, smtp, _CommitFails)
    with pytest.raises(Retry):
        await worker.send_form_email({"job_try": 1}, email_id=email_id)
    assert sent == []
    # Nothing changed: the earlier link still works and the email is still queued.
    assert await _link_status(client, first) == 200
    db.expire_all()
    row = await db.get(EmailDelivery, uuid.UUID(email_id))
    assert row is not None and row.status == "queued" and row.attempts == 0

    # The retry (database back) sends a working link and the earlier one stops working.
    _use_worker(monkeypatch, db_engine, settings, file_storage, smtp)
    assert await worker.send_form_email({"job_try": 2}, email_id=email_id) is True
    assert len(sent) == 1
    assert await _link_status(client, sent[0]) == 200
    assert await _link_status(client, first) == 404


async def test_worker_retry_after_smtp_failure_leaves_one_valid_link(
    client: AsyncClient,
    db: AsyncSession,
    db_engine: Any,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    await client.put(f"/api/v1/forms/{pub.id}/approvals", json=_config())
    await _submit(client, pub)
    email_id = await _request_email(db, queue, SUPERVISOR)
    tokens: list[str] = []

    async def smtp(_s: Settings, to: str, subject: str, text: str, **_kw: Any) -> bool:
        tokens.append(_token(text))
        if len(tokens) == 1:
            raise ConnectionError("smtp down")
        return True

    _use_worker(monkeypatch, db_engine, settings, file_storage, smtp)
    with pytest.raises(Retry):
        await worker.send_form_email({"job_try": 1}, email_id=email_id)
    db.expire_all()
    row = await db.get(EmailDelivery, uuid.UUID(email_id))
    assert row is not None and row.status == "queued" and row.attempts == 1
    assert row.last_error and "smtp down" in row.last_error

    assert await worker.send_form_email({"job_try": 2}, email_id=email_id) is True
    assert len(tokens) == 2 and tokens[0] != tokens[1]
    assert await _link_status(client, tokens[0]) == 404
    assert await _link_status(client, tokens[1]) == 200
    db.expire_all()
    row = await db.get(EmailDelivery, uuid.UUID(email_id))
    assert row is not None and row.status == "sent" and row.attempts == 2
