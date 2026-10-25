"""Approval steps decided only in the studio by people with edit access (DESIGN 15.3): no
approver link and no code; notify addresses get a "New response to review" email with a
button to the submission."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals import service as approvals
from app.config import Settings
from app.integrity import verify_submission
from app.models import ApprovalStep, EmailDelivery, FormRole, StepState, Submission, SubmissionEvent
from app.storage import Storage
from tests.conftest import RecordingQueue, login, make_client
from tests.helpers import admin_client
from tests.test_approval_decisions import _decide, _grant, _member
from tests.test_approvals import RESPONDENT, _config, _emails, _form, _send, _submit

TEAM = "team@example.org"
DESK = "desk@example.org"


def _editors(**extra: Any) -> dict[str, Any]:
    return _config(
        steps=[
            {
                "name": "Review",
                "source": "editors",
                "notify": [TEAM.upper(), DESK, TEAM],
                **extra,
            }
        ],
        requestSubject="New registration to review: {answer:full_name} ({reference})",
        requestMessage=(
            "{answer:full_name} submitted a registration on {submitted}. Open it to decide."
        ),
        requestIncludeAnswers=True,
    )


async def _rows(db: AsyncSession, sid: str) -> list[EmailDelivery]:
    return list(
        await db.scalars(
            select(EmailDelivery)
            .where(EmailDelivery.submission_id == uuid.UUID(sid))
            .order_by(EmailDelivery.created_at)
        )
    )


async def test_settings_for_steps_decided_in_the_studio(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    url = f"/api/v1/forms/{pub.id}/approvals"
    res = await client.put(url, json=_editors())
    assert res.status_code == 200, res.text
    step = res.json()["config"]["steps"][0]
    # Lower case, without repeats; no approver address or question.
    assert step["source"] == "editors" and step["notify"] == [TEAM, DESK]
    assert step["email"] is None and step["fieldId"] is None and step["notifyEditors"] is False
    assert res.json()["issues"] == []

    # Notify addresses are checked and limited to 10.
    bad = _editors()
    bad["steps"][0]["notify"] = ["not-an-address"]
    assert (await client.put(url, json=bad)).status_code == 422
    many = _editors()
    many["steps"][0]["notify"] = [f"p{i}@example.org" for i in range(11)]
    assert (await client.put(url, json=many)).status_code == 422
    # Other approver types don't keep notify addresses.
    fixed = _config(
        steps=[
            {
                "name": "Director",
                "source": "fixed",
                "email": "director@example.org",
                "notify": [TEAM],
                "notifyEditors": True,
            }
        ]
    )
    step = (await client.put(url, json=fixed)).json()["config"]["steps"][0]
    assert step["notify"] == [] and step["notifyEditors"] is False


async def test_no_link_only_a_notice_and_only_editors_decide(
    app: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    assert (
        await client.put(f"/api/v1/forms/{pub.id}/approvals", json=_editors())
    ).status_code == 200
    sid = await _submit(client, pub)

    step = await db.scalar(select(ApprovalStep).where(ApprovalStep.submission_id == uuid.UUID(sid)))
    assert step is not None
    assert step.state == StepState.PENDING and step.approver_email is None
    assert step.notify_to == [TEAM, DESK]
    rows = await _rows(db, sid)
    notices = [r for r in rows if r.kind == "approval_notice"]
    assert sorted(r.to_address for r in notices) == sorted([TEAM, DESK])
    assert not [r for r in rows if r.kind == "approval_request"]

    # The notice: the form's wording, a button to the submission, no link to decide, no code,
    # no sensitive answers.
    _row, msg = await _send(db, settings, file_storage, str(notices[0].id))
    assert msg is not None
    assert msg.subject == "New registration to review: Aminath Ali (#0001)"
    assert "Aminath Ali submitted a registration on" in msg.text
    assert "Reference #0001" in msg.text
    sub_url = f"{settings.public_origin}/forms/{pub.id}/submissions?open={sid}"
    assert f"Open in JustForms: {sub_url}" in msg.text
    assert sub_url.replace("&", "&amp;") in (msg.html or "")
    for text in (msg.text, msg.html or ""):
        assert "/a/" not in text and "decision=" not in text
        assert "code" not in text.lower()
        assert ">Approve<" not in text and ">Reject<" not in text
        assert "A123456" not in text  # the sensitive answer
    assert "Only people with edit access to the form can decide." in msg.text
    await db.refresh(step)
    assert step.token_hash is None and step.token_expires_at is None

    # The event log says who decides and who was told.
    ev = await db.scalar(
        select(SubmissionEvent).where(
            SubmissionEvent.submission_id == uuid.UUID(sid),
            SubmissionEvent.type == "approval_requested",
        )
    )
    assert ev is not None
    assert ev.payload["approvers"] == "editors" and ev.payload["notified"] == [TEAM, DESK]
    assert "approverEmail" not in ev.payload

    # Staff detail: waiting, with the notified addresses.
    detail = (await client.get(f"/api/v1/submissions/{sid}")).json()["approval"]
    s1 = detail["steps"][0]
    assert s1["source"] == "editors" and s1["state"] == "pending"
    assert s1["approverEmail"] is None and s1["notifyTo"] == [TEAM, DESK]

    # Send again: the notices again, still no link.
    queue.jobs.clear()
    assert (await client.post(f"/api/v1/submissions/{sid}/approval/resend")).status_code == 202
    again = [await db.get(EmailDelivery, uuid.UUID(i)) for i in _emails(queue)]
    assert sorted((r.kind, r.to_address) for r in again if r) == sorted(
        [("approval_notice", TEAM), ("approval_notice", DESK)]
    )

    # Viewers can't decide; editors can.
    for email, role in (
        ("viewer@example.org", FormRole.VIEWER),
        ("ed@example.org", FormRole.EDITOR),
    ):
        await _member(db, client, me, email)
        await _grant(db, pub.id, email, role)
    url, body = _decide(sid, "approve")
    async with make_client(app) as viewer:
        await login(viewer, queue, "viewer@example.org")
        res = await viewer.post(url, json=body)
        assert res.status_code == 403 and res.json()["detail"] == "insufficient_form_role"
        bulk = await viewer.post(
            f"/api/v1/forms/{pub.id}/submissions/approval/decide",
            json={"items": [{"id": sid, "step": 1}], "decision": "approve"},
        )
        assert bulk.status_code == 403
    async with make_client(app) as editor:
        await login(editor, queue, "ed@example.org")
        res = await editor.post(url, json=body)
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "approved"
        s1 = res.json()["approval"]["steps"][0]
        assert s1["decidedVia"] == "studio" and s1["decidedEmail"] == "ed@example.org"
    sub = await db.get(Submission, uuid.UUID(sid))
    assert sub is not None and (await verify_submission(db, sub)).ok
    # Once decided, a queued notice isn't sent.
    db.expire(step)
    _row, late = await _send(db, settings, file_storage, str(notices[1].id))
    assert late is None


async def test_link_endpoints_are_404_for_studio_steps(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    await client.put(f"/api/v1/forms/{pub.id}/approvals", json=_editors())
    sid = await _submit(client, pub)
    step = await db.scalar(select(ApprovalStep).where(ApprovalStep.submission_id == uuid.UUID(sid)))
    assert step is not None
    # Even a link token planted on such a step opens nothing.
    from datetime import UTC, datetime, timedelta

    token = approvals.new_link_token()
    step.token_hash = approvals.hash_token(token)
    step.token_expires_at = datetime.now(UTC) + timedelta(days=1)
    await db.commit()
    client.cookies.clear()
    base = f"/api/v1/public/approvals/{token}"
    assert (await client.get(base)).status_code == 404
    assert (await client.post(f"{base}/code")).status_code == 404
    assert (await client.post(f"{base}/verify", json={"code": "123456"})).status_code == 404
    assert (await client.get(f"{base}/submission")).status_code == 404
    res = await client.post(f"{base}/decision", json={"decision": "approve", "name": "X"})
    assert res.status_code == 404


async def test_also_email_people_with_edit_access_and_test_emails(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    for email, role in (
        ("viewer@example.org", FormRole.VIEWER),
        ("ed@example.org", FormRole.EDITOR),
    ):
        await _member(db, client, me, email)
        await _grant(db, pub.id, email, role)
    res = await client.put(f"/api/v1/forms/{pub.id}/approvals", json=_editors(notifyEditors=True))
    assert res.status_code == 200, res.text
    sid = await _submit(client, pub)
    rows = [r for r in await _rows(db, sid) if r.kind == "approval_notice"]
    # The notify addresses, the editor and the organisation admin; never the viewer.
    assert sorted(r.to_address for r in rows) == sorted(
        [TEAM, DESK, "ed@example.org", "admin@example.org"]
    )
    assert RESPONDENT not in {r.to_address for r in rows}

    # "Send test emails": the notice (not an approver request) and both outcomes, to the
    # person asking only.
    settings.smtp_host = settings.smtp_host or "localhost"
    queue.jobs.clear()
    res = await client.post(f"/api/v1/forms/{pub.id}/approvals/test")
    assert res.status_code == 202, res.text
    assert res.json()["kinds"] == [
        "test_approval_notice",
        "test_approval_approved",
        "test_approval_rejected",
    ]
    row = await db.scalar(select(EmailDelivery).where(EmailDelivery.kind == "test_approval_notice"))
    assert row is not None and row.to_address == "admin@example.org"
    _row, msg = await _send(db, settings, file_storage, str(row.id))
    assert msg is not None
    assert msg.subject == "[Test] New registration to review: [full_name] (#0000)"
    assert "Open in JustForms:" in msg.text and "/a/" not in msg.text
