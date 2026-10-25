"""Approval workflow on submissions (DESIGN 15.3).

When a response arrives on a form that asks for approval, its steps are copied onto the
submission (``approval_steps``) with each approver's address resolved from the answers or the
settings, the status becomes In review, and step 1's approver is emailed a link. Approvers
confirm their email with a one-time code and approve or reject; approving moves to the next
step, rejecting ends the approval. After the last step the status becomes Approved (or
Rejected), the signed PDF is made again with the approval record, and the respondent can be
emailed the outcome with that PDF.

Every change goes through the hash-chained event log (``append_event``). While an approval
runs nobody can set the status by hand; staff can send the approver's email again or stop the
approval, which hands the status back to them.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.config import active, load_config
from app.config import Settings
from app.integrity import append_event
from app.models import (
    ApprovalState,
    ApprovalStep,
    EmailDelivery,
    EventType,
    FormRecord,
    PdfStatus,
    StepState,
    Submission,
    SubmissionStatus,
)
from app.pdf.render import ApprovalLine
from app.queue import JobQueue

EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_link_token() -> str:
    return secrets.token_urlsafe(24)


def approver_url(settings: Settings, token: str) -> str:
    return f"{settings.public_origin}/a/{token}"


def _address(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if EMAIL.match(value) and len(value) <= 320 else None


@dataclass
class Change:
    """What one workflow change needs afterwards (the caller enqueues it after commit)."""

    emails: list[uuid.UUID] = field(default_factory=list)
    # Webhook ``submission.approval_step`` payload changes, in order.
    steps: list[dict[str, Any]] = field(default_factory=list)
    # (from, to) when the status changed because the approval finished.
    status: tuple[SubmissionStatus, SubmissionStatus] | None = None
    render_pdf: bool = False


async def steps_of(db: AsyncSession, sub: Submission) -> list[ApprovalStep]:
    return list(
        await db.scalars(
            select(ApprovalStep)
            .where(ApprovalStep.submission_id == sub.id)
            .order_by(ApprovalStep.step)
        )
    )


def _request_email(db: AsyncSession, sub: Submission, step: ApprovalStep) -> uuid.UUID:
    assert step.approver_email
    row = EmailDelivery(
        id=uuid.uuid4(),
        form_id=sub.form_id,
        submission_id=sub.id,
        kind="approval_request",
        to_address=step.approver_email,
        detail=str(step.id),
    )
    db.add(row)
    return row.id


async def _activate(db: AsyncSession, sub: Submission, step: ApprovalStep, change: Change) -> None:
    sub.approval_step = step.step
    if step.approver_email is None:
        step.state = StepState.NO_APPROVER
        await append_event(
            db,
            sub,
            EventType.APPROVAL_WAITING,
            payload={"step": step.step, "name": step.name, "field": step.field_id},
        )
        change.steps.append({"action": "waiting", "step": step.step, "stepName": step.name})
        return
    step.state = StepState.PENDING
    step.requested_at = datetime.now(UTC)
    await append_event(
        db,
        sub,
        EventType.APPROVAL_REQUESTED,
        payload={"step": step.step, "name": step.name, "approverEmail": step.approver_email},
    )
    change.emails.append(_request_email(db, sub, step))
    change.steps.append(
        {
            "action": "requested",
            "step": step.step,
            "stepName": step.name,
            "approverEmail": step.approver_email,
        }
    )


async def start(db: AsyncSession, sub: Submission, form: FormRecord) -> Change:
    """Copy the form's approval steps onto a new submission and ask step 1 (no-op when the
    form asks for no approval). Call after the ``created`` event."""
    change = Change()
    config = load_config(form.settings)
    if not active(config):
        return change
    rows = []
    for n, cfg in enumerate(config.steps, start=1):
        if cfg.source == "fixed":
            email = _address(cfg.email)
        else:
            email = _address(sub.data.get(cfg.field_id)) if cfg.field_id else None
        row = ApprovalStep(
            id=uuid.uuid4(),
            submission_id=sub.id,
            step=n,
            name=cfg.name,
            source=cfg.source,
            field_id=cfg.field_id if cfg.source == "field" else None,
            approver_email=email,
        )
        db.add(row)
        rows.append(row)
    if config.notify_respondent:
        sub.approval_outcome_to = (
            _address(sub.data.get(config.respondent_email_field))
            if config.respondent_email_field
            else sub.respondent_email
        )
    sub.approval_state = ApprovalState.PENDING
    previous = sub.status
    sub.status = SubmissionStatus.IN_REVIEW
    await db.flush()
    if previous != SubmissionStatus.IN_REVIEW:
        await append_event(
            db,
            sub,
            EventType.STATUS_CHANGED,
            payload={"from": previous.value, "to": sub.status.value, "via": "approval"},
        )
    await _activate(db, sub, rows[0], change)
    return change


async def _finish(
    db: AsyncSession, sub: Submission, outcome: ApprovalState, change: Change, reason: str | None
) -> None:
    sub.approval_state = outcome
    previous = sub.status
    sub.status = (
        SubmissionStatus.APPROVED
        if outcome == ApprovalState.APPROVED
        else SubmissionStatus.REJECTED
    )
    payload: dict[str, Any] = {"from": previous.value, "to": sub.status.value, "via": "approval"}
    if reason:
        payload["reason"] = reason
    await append_event(db, sub, EventType.STATUS_CHANGED, payload=payload)
    change.status = (previous, sub.status)
    # The final PDF carries the approval record; make and sign it again.
    sub.pdf_status = PdfStatus.PENDING
    change.render_pdf = True


class AlreadyDecided(Exception):
    """The step was decided (or the approval ended) before this decision got there."""


async def lock(db: AsyncSession, sub: Submission) -> None:
    """Serialise workflow changes on one submission, then re-read it under the lock."""
    await db.execute(select(Submission.id).where(Submission.id == sub.id).with_for_update())
    await db.refresh(sub)


async def decide(
    db: AsyncSession,
    sub: Submission,
    step: ApprovalStep,
    *,
    approve: bool,
    name: str,
    comment: str | None,
    via: str = "email",
    actor_id: uuid.UUID | None = None,
    email: str | None = None,
) -> Change:
    """Record a decision on ``step``: from the approver's link (``via="email"``) or by a staff
    member in the studio (``via="studio"``, ``actor_id`` and ``email`` are theirs). The caller
    holds :func:`lock`. The step only changes if it is still pending (a conditional update), so
    of two decisions racing for one step the second raises :class:`AlreadyDecided`."""
    change = Change()
    if sub.approval_state != ApprovalState.PENDING or sub.approval_step != step.step:
        raise AlreadyDecided
    decided_email = email if via == "studio" else step.approver_email
    now = datetime.now(UTC)
    result = await db.execute(
        update(ApprovalStep)
        .where(
            ApprovalStep.id == step.id,
            ApprovalStep.state.in_([StepState.PENDING, StepState.NO_APPROVER]),
        )
        .values(
            state=StepState.APPROVED if approve else StepState.REJECTED,
            decided_at=now,
            decided_name=name,
            comment=comment or None,
            decided_via=via,
            decided_by_id=actor_id,
            decided_email=decided_email,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(result, "rowcount", 0) != 1:
        raise AlreadyDecided
    await db.refresh(step)
    payload: dict[str, Any] = {
        "step": step.step,
        "name": step.name,
        "decision": "approved" if approve else "rejected",
        "approverEmail": step.approver_email,
        "approverName": name,
        "decidedVia": via,
    }
    if via == "studio":
        payload["decidedByEmail"] = decided_email
    if comment:
        payload["comment"] = comment
    await append_event(db, sub, EventType.APPROVAL_DECIDED, actor_id=actor_id, payload=payload)
    done: dict[str, Any] = {
        "action": payload["decision"],
        "step": step.step,
        "stepName": step.name,
        "approverEmail": step.approver_email,
        "approverName": name,
        "decidedVia": via,
    }
    if comment:
        done["comment"] = comment
    change.steps.append(done)
    if not approve:
        await _finish(db, sub, ApprovalState.REJECTED, change, comment)
        return change
    following = [s for s in await steps_of(db, sub) if s.step > step.step]
    if following:
        await _activate(db, sub, following[0], change)
    else:
        await _finish(db, sub, ApprovalState.APPROVED, change, None)
    return change


async def current_step(db: AsyncSession, sub: Submission) -> ApprovalStep | None:
    if sub.approval_state != ApprovalState.PENDING or sub.approval_step is None:
        return None
    return await db.scalar(
        select(ApprovalStep).where(
            ApprovalStep.submission_id == sub.id, ApprovalStep.step == sub.approval_step
        )
    )


async def stop(
    db: AsyncSession, sub: Submission, actor_id: uuid.UUID, reason: str
) -> Change | None:
    """End a running approval; the status stays as it is and is the staff's again."""
    step = await current_step(db, sub)
    if step is None:
        return None
    change = Change()
    step.state = StepState.STOPPED
    step.token_hash = None
    sub.approval_state = ApprovalState.STOPPED
    await append_event(
        db,
        sub,
        EventType.APPROVAL_STOPPED,
        actor_id=actor_id,
        payload={"step": step.step, "name": step.name, "reason": reason},
    )
    change.steps.append(
        {"action": "stopped", "step": step.step, "stepName": step.name, "reason": reason}
    )
    return change


async def resend(db: AsyncSession, sub: Submission) -> uuid.UUID | None:
    """Email the current approver again (with a new link; the old one stops working)."""
    step = await current_step(db, sub)
    if step is None or step.state != StepState.PENDING:
        return None
    return _request_email(db, sub, step)


def mint_link(settings: Settings, step: ApprovalStep) -> str:
    """A new link token for ``step`` (stored as a hash); returns the approver URL."""
    token = new_link_token()
    step.token_hash = hash_token(token)
    step.token_expires_at = datetime.now(UTC) + timedelta(days=settings.approval_link_days)
    return approver_url(settings, token)


async def step_by_token(db: AsyncSession, token: str) -> ApprovalStep | None:
    if not 20 <= len(token) <= 64:
        return None
    step = await db.scalar(select(ApprovalStep).where(ApprovalStep.token_hash == hash_token(token)))
    if step is None or step.token_expires_at is None:
        return None
    if step.token_expires_at < datetime.now(UTC) and step.state == StepState.PENDING:
        return None
    return step


async def step_count(db: AsyncSession, sub: Submission) -> int:
    return int(
        await db.scalar(select(func.count()).where(ApprovalStep.submission_id == sub.id)) or 0
    )


async def counts(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = await db.execute(
        select(ApprovalStep.submission_id, func.count())
        .where(ApprovalStep.submission_id.in_(ids))
        .group_by(ApprovalStep.submission_id)
    )
    return {sid: int(n) for sid, n in rows.all()}


async def enqueue(queue: JobQueue, sub: Submission, change: Change) -> None:
    """Jobs after a committed workflow change: emails, webhooks, the final PDF."""
    for email_id in change.emails:
        await queue.enqueue("send_form_email", email_id=str(email_id))
    for extra in change.steps:
        await queue.enqueue(
            "dispatch_event",
            event="submission.approval_step",
            submission_id=str(sub.id),
            extra=extra,
        )
    if change.status is not None:
        await queue.enqueue(
            "dispatch_event",
            event="submission.status_changed",
            submission_id=str(sub.id),
            extra={
                "from": change.status[0].value,
                "to": change.status[1].value,
                "via": "approval",
            },
        )
    if change.render_pdf:
        await queue.enqueue("render_submission_pdf", submission_id=str(sub.id))


# -- read models ----------------------------------------------------------------------------


def step_out(s: ApprovalStep) -> dict[str, Any]:
    return {
        "step": s.step,
        "name": s.name,
        "state": s.state.value,
        "source": s.source,
        "fieldId": s.field_id,
        "approverEmail": s.approver_email,
        "requestedAt": s.requested_at.isoformat() if s.requested_at else None,
        "decidedAt": s.decided_at.isoformat() if s.decided_at else None,
        "decidedName": s.decided_name,
        "decidedEmail": s.decided_email,
        "decidedVia": s.decided_via,
        "comment": s.comment,
    }


async def detail(db: AsyncSession, sub: Submission) -> dict[str, Any] | None:
    """The approval as staff see it in the submission detail."""
    if sub.approval_state is None:
        return None
    steps = await steps_of(db, sub)
    return {
        "state": sub.approval_state.value,
        "step": sub.approval_step,
        "total": len(steps),
        "outcomeTo": sub.approval_outcome_to,
        "steps": [step_out(s) for s in steps],
    }


async def summary(db: AsyncSession, sub: Submission) -> dict[str, Any] | None:
    """Outcome only, for the public verify page: no names, no addresses."""
    if sub.approval_state is None:
        return None
    steps = await steps_of(db, sub)
    state = sub.approval_state.value
    current = next((s for s in steps if s.step == sub.approval_step), None)
    if (
        sub.approval_state == ApprovalState.PENDING
        and current is not None
        and current.state == StepState.NO_APPROVER
    ):
        state = "waiting"
    decided = [s.decided_at for s in steps if s.decided_at is not None]
    finished = sub.approval_state in (ApprovalState.APPROVED, ApprovalState.REJECTED)
    return {
        "state": state,
        "step": sub.approval_step or 1,
        "total": len(steps),
        "decidedAt": max(decided).isoformat() if finished and decided else None,
    }


async def printed_record(db: AsyncSession, sub: Submission) -> list[ApprovalLine]:
    """Decided and stopped steps for the PDF's approval record."""
    if sub.approval_state is None:
        return []
    out: list[ApprovalLine] = []
    for s in await steps_of(db, sub):
        if s.state in (StepState.APPROVED, StepState.REJECTED):
            out.append(
                ApprovalLine(
                    step=s.step,
                    name=s.name,
                    outcome=s.state.value,
                    approver_name=s.decided_name,
                    approver_email=s.decided_email or s.approver_email,
                    decided_at=s.decided_at,
                )
            )
        elif s.state == StepState.STOPPED:
            out.append(ApprovalLine(s.step, s.name, "stopped", None, None, None))
    return out
