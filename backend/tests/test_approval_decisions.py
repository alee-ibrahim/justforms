"""Deciding approval steps in the studio, the approval emails' buttons and custom wording, and
races between an approver's link and the studio (DESIGN 15.3)."""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.approvals import service as approvals
from app.config import Settings
from app.integrity import verify_submission
from app.models import (
    ApprovalStep,
    AuditLog,
    EmailDelivery,
    FormPermission,
    FormRole,
    StepState,
    Submission,
    SubmissionEvent,
    User,
)
from app.notifications import events as notify
from app.pdf.service import approval_lines, generate_pdf
from app.storage import Storage
from tests.conftest import RecordingQueue, login, make_client
from tests.helpers import admin_client
from tests.test_approvals import (
    DIRECTOR,
    RESPONDENT,
    SUPERVISOR,
    _approver_link,
    _config,
    _form,
    _send,
    _sign_in,
    _submit,
)


async def _member(db: AsyncSession, client: AsyncClient, me: dict[str, Any], email: str) -> None:
    """Make ``email`` a member of the admin's organisation (signing in once creates them)."""
    from app.models import OrgMembership, OrgRole

    user = User(email=email, display_name=email.split("@")[0].title())
    db.add(user)
    await db.flush()
    db.add(
        OrgMembership(org_id=uuid.UUID(me["orgs"][0]["id"]), user_id=user.id, role=OrgRole.MEMBER)
    )
    await db.commit()


async def _grant(db: AsyncSession, form_id: str, email: str, role: FormRole) -> None:
    user = await db.scalar(select(User).where(User.email == email))
    assert user is not None
    db.add(FormPermission(form_id=uuid.UUID(form_id), user_id=user.id, role=role))
    await db.commit()


def _decide(
    sid: str, decision: str, step: int = 1, comment: str = ""
) -> tuple[str, dict[str, Any]]:
    return (
        f"/api/v1/submissions/{sid}/approval/decide",
        {"step": step, "decision": decision, "comment": comment},
    )


async def test_who_may_decide_in_the_studio(
    app: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    await client.put(f"/api/v1/forms/{pub.id}/approvals", json=_config())
    sid = await _submit(client, pub)
    for email, role in (
        ("viewer@example.org", FormRole.VIEWER),
        ("editor@example.org", FormRole.EDITOR),
    ):
        await _member(db, client, me, email)
        await _grant(db, pub.id, email, role)
    await _member(db, client, me, "outsider@example.org")

    url, body = _decide(sid, "approve")
    async with make_client(app) as other:
        await login(other, queue, "outsider@example.org")
        assert (await other.post(url, json=body)).status_code == 404
    async with make_client(app) as viewer:
        await login(viewer, queue, "viewer@example.org")
        res = await viewer.post(url, json=body)
        assert res.status_code == 403 and res.json()["detail"] == "insufficient_form_role"
        # Viewers see the steps but not the buttons.
        detail = (await viewer.get(f"/api/v1/submissions/{sid}")).json()
        assert detail["canEdit"] is False
    async with make_client(app) as editor:
        await login(editor, queue, "editor@example.org")
        # Rejecting needs a comment.
        url_r, body_r = _decide(sid, "reject")
        res = await editor.post(url_r, json=body_r)
        assert res.status_code == 422 and res.json()["detail"] == "comment_required"
        # A step that isn't the current one is refused.
        url2, body2 = _decide(sid, "approve", step=2)
        assert (await editor.post(url2, json=body2)).status_code == 409
        res = await editor.post(url, json=body)
        assert res.status_code == 200, res.text
        out = res.json()
        assert out["state"] == "approved" and out["approval"]["step"] == 2
        s1 = out["approval"]["steps"][0]
        assert s1["decidedVia"] == "studio" and s1["decidedEmail"] == "editor@example.org"
        assert s1["decidedName"] == "Editor"
        assert s1["approverEmail"] == SUPERVISOR

    # The decision is in the hash-chained log (with the actor) and the audit log.
    sub = await db.get(Submission, uuid.UUID(sid))
    assert sub is not None
    ev = await db.scalar(
        select(SubmissionEvent)
        .where(SubmissionEvent.submission_id == sub.id, SubmissionEvent.type == "approval_decided")
        .order_by(SubmissionEvent.seq.desc())
    )
    assert ev is not None and ev.actor_id is not None
    assert ev.payload["decidedVia"] == "studio"
    assert ev.payload["decidedByEmail"] == "editor@example.org"
    assert (await verify_submission(db, sub)).ok
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "submission.approval_decide"))
    assert entry is not None and entry.meta["via"] == "studio"
    # The director is asked next, as after a link decision.
    rows = list(await db.scalars(select(EmailDelivery).where(EmailDelivery.to_address == DIRECTOR)))
    assert [r.kind for r in rows] == ["approval_request"]

    # The admin (an owner of every form) decides the last step: final status and PDF job.
    url, body = _decide(sid, "approve", step=2)
    res = await client.post(url, json=body)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "approved"
    assert ("render_submission_pdf", {"submission_id": sid}) in queue.jobs


async def test_studio_decision_invalidates_the_emailed_link(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    await client.put(
        f"/api/v1/forms/{pub.id}/approvals",
        json=_config(steps=[{"name": "Supervisor", "source": "field", "fieldId": "supervisor"}]),
    )
    sid = await _submit(client, pub)
    token = await _approver_link(db, settings, file_storage, queue, SUPERVISOR)
    staff = dict(client.cookies)
    client.cookies.clear()
    bearer = await _sign_in(client, queue, token, SUPERVISOR)
    client.cookies.update(staff)

    url, body = _decide(sid, "reject", comment="Missing the registration certificate.")
    res = await client.post(url, json=body)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "rejected"

    client.cookies.clear()
    link = (await client.get(f"/api/v1/public/approvals/{token}")).json()
    assert link["state"] == "rejected"
    assert link["decidedVia"] == "studio" and link["decidedName"] == "admin@example.org"
    # The approver's session for that step can't decide any more, and no code is sent.
    res = await client.post(
        f"/api/v1/public/approvals/{token}/decision",
        json={"decision": "approve", "name": "Hassan"},
        headers={"Authorization": f"Bearer {bearer}"},
    )
    assert res.status_code == 409 and res.json()["detail"] == "approval_done"
    assert (await client.post(f"/api/v1/public/approvals/{token}/code")).status_code == 409

    # Outcome: the PDF is made again with the record (the staff member's address), then the
    # respondent's email with the comment.
    sub = await db.get(Submission, uuid.UUID(sid))
    assert sub is not None
    lines = await approval_lines(db, sub)
    assert [(ln.outcome, ln.approver_name, ln.approver_email) for ln in lines] == [
        ("rejected", "admin@example.org", "admin@example.org")
    ]
    assert await generate_pdf(db, file_storage, settings, uuid.UUID(sid))
    jobs = await notify.dispatch(db, settings, "submission.pdf_ready", uuid.UUID(sid))
    rows = [await db.get(EmailDelivery, i) for i in jobs.emails]
    outcome = [r for r in rows if r and r.kind == "approval_outcome"]
    assert len(outcome) == 1 and outcome[0].to_address == RESPONDENT
    _row, msg = await _send(db, settings, file_storage, str(outcome[0].id))
    assert msg.subject.startswith("Not approved")
    assert "Missing the registration certificate." in msg.text
    assert msg.attachments


async def test_link_decision_first_then_studio_gets_already_decided(
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
    staff = dict(client.cookies)
    client.cookies.clear()
    bearer = await _sign_in(client, queue, token, SUPERVISOR)
    res = await client.post(
        f"/api/v1/public/approvals/{token}/decision",
        json={"decision": "approve", "name": "Hassan Ali"},
        headers={"Authorization": f"Bearer {bearer}"},
    )
    assert res.status_code == 200
    client.cookies.update(staff)
    # The studio still showed step 1 waiting.
    url, body = _decide(sid, "reject", comment="No.")
    res = await client.post(url, json=body)
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] == "approval_done" and detail["decidedName"] == "Hassan Ali"
    assert detail["decidedVia"] == "email" and detail["state"] == "approved"


async def test_simultaneous_decisions_only_one_wins(
    db_engine: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
) -> None:
    """Two decisions on one step at the same moment (separate connections): the row lock and
    the conditional update let exactly one through."""
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    await client.put(
        f"/api/v1/forms/{pub.id}/approvals",
        json=_config(steps=[{"name": "Supervisor", "source": "field", "fieldId": "supervisor"}]),
    )
    sid = uuid.UUID(await _submit(client, pub))
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async def one(approve: bool) -> str:
        async with maker() as session:
            sub = await session.get(Submission, sid)
            assert sub is not None
            await approvals.lock(session, sub)
            step = await approvals.current_step(session, sub)
            if step is None or step.state != StepState.PENDING:
                await session.rollback()
                return "already"
            await asyncio.sleep(0.05)
            try:
                await approvals.decide(
                    session, sub, step, approve=approve, name="x", comment=None if approve else "n"
                )
            except approvals.AlreadyDecided:
                await session.rollback()
                return "already"
            await session.commit()
            return "decided"

    results = await asyncio.gather(one(True), one(False))
    assert sorted(results) == ["already", "decided"]
    decided = list(
        await db.scalars(
            select(SubmissionEvent).where(
                SubmissionEvent.submission_id == sid, SubmissionEvent.type == "approval_decided"
            )
        )
    )
    assert len(decided) == 1


async def test_decide_guard_refuses_a_step_decided_meanwhile(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    """The conditional update is the last line: a stale in-memory step is not decided twice."""
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    await client.put(f"/api/v1/forms/{pub.id}/approvals", json=_config())
    sid = uuid.UUID(await _submit(client, pub))
    sub = await db.get(Submission, sid)
    assert sub is not None
    await approvals.lock(db, sub)
    step = await approvals.current_step(db, sub)
    assert step is not None
    await approvals.decide(db, sub, step, approve=True, name="A", comment=None)
    await db.commit()
    stale = await db.scalar(select(ApprovalStep).where(ApprovalStep.id == step.id))
    assert stale is not None
    sub.approval_step = 1  # pretend the submission still pointed at step 1
    with pytest.raises(approvals.AlreadyDecided):
        await approvals.decide(db, sub, stale, approve=False, name="B", comment="n")
    await db.rollback()


async def test_bulk_decisions_report_each_submission(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    await client.put(
        f"/api/v1/forms/{pub.id}/approvals",
        json=_config(steps=[{"name": "Supervisor", "source": "field", "fieldId": "supervisor"}]),
    )
    ids = [await _submit(client, pub) for _ in range(3)]
    url = f"/api/v1/forms/{pub.id}/submissions/approval/decide"
    items = [{"id": i, "step": 1} for i in ids]
    res = await client.post(url, json={"items": items, "decision": "reject"})
    assert res.status_code == 422
    # The first is decided through its link meanwhile.
    first = (await client.get(f"/api/v1/submissions/{ids[0]}")).json()
    assert first["approval"]["state"] == "pending"
    res = await client.post(
        f"/api/v1/submissions/{ids[0]}/approval/decide",
        json={"step": 1, "decision": "approve"},
    )
    assert res.status_code == 200
    stranger = str(uuid.uuid4())
    res = await client.post(
        url,
        json={
            "items": [*items, {"id": stranger, "step": 1}],
            "decision": "reject",
            "comment": "Incomplete.",
        },
    )
    assert res.status_code == 200, res.text
    results = {r["id"]: r for r in res.json()["results"]}
    assert results[ids[0]]["result"] == "already_decided"
    assert results[ids[0]]["decidedName"] == "admin@example.org"
    assert results[ids[1]]["result"] == "rejected" and results[ids[2]]["result"] == "rejected"
    assert results[stranger]["result"] == "not_found"
    for sid in ids[1:]:
        detail = (await client.get(f"/api/v1/submissions/{sid}")).json()
        assert detail["status"] == "rejected"
        assert detail["approval"]["steps"][0]["comment"] == "Incomplete."


async def test_request_email_buttons_wording_and_outcome_reply_to(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    url = f"/api/v1/forms/{pub.id}/approvals"
    bad = _config(requestSubject="Review {answer:national_id}")
    res = await client.put(url, json=bad)
    assert res.status_code == 422
    issue = res.json()["issues"][0]
    assert issue["code"] == "unknown_placeholder" and issue["field"] == "request_subject"
    res = await client.put(url, json=_config(requestSubject="Two\nlines"))
    assert res.json()["issues"][0]["code"] == "subject_one_line"
    res = await client.put(
        url,
        json=_config(
            steps=[{"name": "Supervisor", "source": "field", "fieldId": "supervisor"}],
            requestSubject="To review: {answer:full_name} ({reference})",
            requestMessage="{answer:full_name} asked for leave.",
            requestIncludeAnswers=True,
            outcomeApprovedMessage="Good news, {answer:full_name}: your request was approved.",
            outcomeRejectedMessage="Sorry, {answer:full_name}: we can't approve this request.",
            outcomeReplyTo="HR@Example.org",
        ),
    )
    assert res.status_code == 200, res.text
    assert res.json()["config"]["outcomeReplyTo"] == "hr@example.org"
    sid = await _submit(client, pub)

    row = await db.scalar(select(EmailDelivery).where(EmailDelivery.kind == "approval_request"))
    assert row is not None
    _row, msg = await _send(db, settings, file_storage, str(row.id))
    assert msg.subject == "To review: Aminath Ali (#0001)"
    assert "Aminath Ali asked for leave." in msg.text
    token = re.search(r"/a/([A-Za-z0-9_-]+)\?decision=approve", msg.text)
    assert token, msg.text
    assert f"/a/{token.group(1)}?decision=reject" in msg.text
    assert msg.html and f"/a/{token.group(1)}?decision=approve" in msg.html
    assert ">Approve<" in msg.html and ">Reject<" in msg.html
    # Non-sensitive answers only.
    assert "Aminath Ali" in msg.html and "A123456" not in msg.html and "A123456" not in msg.text
    # Opening the buttons' links changes nothing (mail scanners prefetch them).
    staff = dict(client.cookies)
    client.cookies.clear()
    for _ in range(2):
        link = await client.get(f"/api/v1/public/approvals/{token.group(1)}?decision=approve")
        assert link.json()["state"] == "pending"
    client.cookies.update(staff)

    res = await client.post(
        f"/api/v1/submissions/{sid}/approval/decide", json={"step": 1, "decision": "approve"}
    )
    assert res.status_code == 200
    jobs = await notify.dispatch(db, settings, notify.PDF_FAILED, uuid.UUID(sid))
    outcome = await db.get(EmailDelivery, jobs.emails[0])
    assert outcome is not None and outcome.to_address == RESPONDENT
    _row, msg = await _send(db, settings, file_storage, str(outcome.id))
    assert msg.reply_to == "hr@example.org"
    assert "Good news, Aminath Ali: your request was approved." in msg.text
    assert "#0001" in msg.text


async def test_approval_test_emails_go_to_the_owner_only(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    file_storage: Storage,
) -> None:
    settings.smtp_host = "smtp.example.org"
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me)
    url = f"/api/v1/forms/{pub.id}/approvals/test"
    assert (await client.post(url)).status_code == 409  # approvals off
    await client.put(
        f"/api/v1/forms/{pub.id}/approvals",
        json=_config(requestSubject="Review {answer:full_name}", outcomeRejectedMessage="Sorry."),
    )
    res = await client.post(url)
    assert res.status_code == 202, res.text
    assert res.json()["kinds"] == [
        "test_approval_request",
        "test_approval_approved",
        "test_approval_rejected",
    ]
    rows = list(await db.scalars(select(EmailDelivery).where(EmailDelivery.kind.like("test_%"))))
    assert {r.to_address for r in rows} == {"admin@example.org"}
    msgs = {}
    for r in rows:
        _r, m = await _send(db, settings, file_storage, str(r.id))
        msgs[r.kind] = m
    assert msgs["test_approval_request"].subject == "[Test] Review [full_name]"
    assert "?decision=approve" in msgs["test_approval_request"].text
    assert msgs["test_approval_approved"].subject.startswith("[Test] Approved: Leave request")
    assert "Sorry." in msgs["test_approval_rejected"].text
    # No submission was read or made.
    assert (await db.scalar(select(Submission.id))) is None


async def test_studio_can_decide_a_step_without_an_approver(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    me = await admin_client(client, db, settings, queue)
    pub = await _form(client, me, optional=True)
    await client.put(f"/api/v1/forms/{pub.id}/approvals", json=_config(notifyRespondent=False))
    sid = await _submit(client, pub, supervisor=None)
    detail = (await client.get(f"/api/v1/submissions/{sid}")).json()
    assert detail["approval"]["steps"][0]["state"] == "no_approver"
    res = await client.post(
        f"/api/v1/submissions/{sid}/approval/decide", json={"step": 1, "decision": "approve"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["approval"]["step"] == 2
    assert res.json()["approval"]["steps"][1]["state"] == "pending"
