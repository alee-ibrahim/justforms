"""Approvals (DESIGN 15.3): a form's approval settings, staff actions on a running
approval, and the public approver page's API.

Approvers have no account. The emailed link (``/a/{token}``) identifies one step; the
approver confirms the address with a one-time code and gets a short-lived bearer token for
that step and link. They see the submission with sensitive answers left out, can download
its non-sensitive files, and approve or reject (a rejection needs a comment).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from pydantic import Field, StringConstraints
from sqlalchemy import select

from app import ratelimit
from app.api.v1.common import ApiModel
from app.api.v1.files import content_disposition
from app.api.v1.notify import mask_email
from app.approvals import service as approvals
from app.approvals import tokens
from app.approvals.config import (
    MAX_STEPS,
    ApprovalConfig,
    active,
    check_config,
    email_questions,
    load_config,
)
from app.auth import respondent as codes
from app.auth.deps import CurrentUser, DbDep, RedisDep, SettingsDep, StorageDep
from app.branding.service import resolve as resolve_brand
from app.logic.index import FormIndex
from app.models import (
    ApprovalState,
    ApprovalStep,
    EmailDelivery,
    FileRecord,
    FileState,
    FormRecord,
    FormRole,
    FormVersion,
    Organization,
    Signature,
    StepState,
    Submission,
    User,
)
from app.net import client_ip
from app.notifications.emails import code_message
from app.notifications.events import APPROVAL_TEST_KINDS
from app.permissions import FormOwner, FormViewer, effective_form_role, has_form_role
from app.queue import JobQueue, get_queue
from app.schemas.form import FileField, Form, SignatureField
from app.services.users import audit
from app.theme.resolve import form_email_brand, page_brand

router = APIRouter(tags=["approvals"])
public = APIRouter(prefix="/public/approvals", tags=["approvals"])
QueueDep = Annotated[JobQueue, Depends(get_queue)]
NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
Reason = Annotated[str, StringConstraints(min_length=1, max_length=2000, strip_whitespace=True)]


# -- settings (studio) ----------------------------------------------------------------------


class EmailQuestion(ApiModel):
    id: str
    label: str


class ApprovalsOut(ApiModel):
    config: ApprovalConfig
    # Problems with the steps against the draft (errors and warnings), 1-based step numbers.
    issues: list[dict[str, Any]]
    email_fields: list[EmailQuestion]
    language: str
    smtp_enabled: bool


async def _schemas(db: DbDep, form: FormRecord) -> tuple[Form, Form | None]:
    draft = Form.model_validate(form.draft_schema)
    live = None
    if form.current_version_id is not None:
        version = await db.get(FormVersion, form.current_version_id)
        if version is not None:
            live = Form.model_validate(version.schema)
    return draft, live


async def _approvals_out(db: DbDep, settings: SettingsDep, form: FormRecord) -> ApprovalsOut:
    draft, live = await _schemas(db, form)
    config = load_config(form.settings)
    return ApprovalsOut(
        config=config,
        issues=[i.as_dict() for i in check_config(config, draft, live)],
        email_fields=[EmailQuestion(id=f.id, label=f.label) for f in email_questions(draft)],
        language=draft.settings.language,
        smtp_enabled=settings.smtp_enabled,
    )


@router.get("/forms/{form_id}/approvals", response_model=ApprovalsOut)
async def get_approvals(db: DbDep, settings: SettingsDep, access: FormViewer) -> ApprovalsOut:
    return await _approvals_out(db, settings, access.form)


@router.put("/forms/{form_id}/approvals", response_model=ApprovalsOut)
async def put_approvals(
    body: ApprovalConfig, db: DbDep, settings: SettingsDep, access: FormOwner
) -> ApprovalsOut | JSONResponse:
    form = access.form
    steps = [
        s.model_copy(
            update={
                "email": str(s.email).lower() if s.source == "fixed" and s.email else None,
                "field_id": s.field_id if s.source == "field" else None,
            }
        )
        for s in body.steps
    ]
    config = body.model_copy(
        update={
            "steps": steps,
            "request_subject": body.request_subject or None,
            "request_message": body.request_message or None,
            "outcome_approved_message": body.outcome_approved_message or None,
            "outcome_rejected_message": body.outcome_rejected_message or None,
            "outcome_reply_to": str(body.outcome_reply_to).lower()
            if body.outcome_reply_to
            else None,
        }
    )
    draft, live = await _schemas(db, form)
    errors = [i for i in check_config(config, draft, live) if i.level == "error"]
    if errors:
        return JSONResponse(
            {"detail": "invalid_approvals", "issues": [i.as_dict() for i in errors]},
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    before = (form.settings or {}).get("approvals")
    form.settings = {**(form.settings or {}), "approvals": config.model_dump(mode="json")}
    await audit(
        db,
        "form.approvals",
        org_id=form.org_id,
        actor_id=access.user.id,
        target_type="form",
        target_id=form.id,
        meta={"before": before, "after": form.settings["approvals"]},
    )
    await db.commit()
    return await _approvals_out(db, settings, form)


@router.post("/forms/{form_id}/approvals/test", status_code=status.HTTP_202_ACCEPTED)
async def send_approval_tests(
    db: DbDep, settings: SettingsDep, redis: RedisDep, queue: QueueDep, access: FormOwner
) -> dict[str, Any]:
    """Send the approver's email (and the outcome emails, when they are on) with sample
    answers and "[Test]" in the subject to the person asking, never to the approvers."""
    if not settings.smtp_enabled:
        raise HTTPException(status.HTTP_409_CONFLICT, "smtp_not_configured")
    config = load_config(access.form.settings)
    if not active(config):
        raise HTTPException(status.HTTP_409_CONFLICT, "approvals_off")
    await ratelimit.enforce(redis, settings, "notify_test", str(access.user.id))
    kinds = list(APPROVAL_TEST_KINDS if config.notify_respondent else APPROVAL_TEST_KINDS[:1])
    rows = [
        EmailDelivery(
            id=uuid.uuid4(),
            form_id=access.form.id,
            submission_id=None,
            kind=kind,
            to_address=access.user.email,
        )
        for kind in kinds
    ]
    db.add_all(rows)
    await audit(
        db,
        "form.approvals_test",
        org_id=access.form.org_id,
        actor_id=access.user.id,
        target_type="form",
        target_id=access.form.id,
    )
    await db.commit()
    for row in rows:
        await queue.enqueue("send_form_email", email_id=str(row.id))
    return {"kinds": kinds, "to": access.user.email}


# -- a running approval (studio) ------------------------------------------------------------


class StopIn(ApiModel):
    reason: Reason


async def _editable(db: DbDep, user: CurrentUser, submission_id: uuid.UUID) -> Submission:
    sub = await db.get(Submission, submission_id)
    form = await db.get(FormRecord, sub.form_id) if sub else None
    role = await effective_form_role(db, user, form) if form and form.deleted_at is None else None
    if sub is None or role is None or sub.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "submission_not_found")
    if not has_form_role(role, FormRole.EDITOR):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_form_role")
    return sub


@router.post("/submissions/{submission_id}/approval/resend", status_code=202)
async def resend_approval(
    submission_id: uuid.UUID, db: DbDep, user: CurrentUser, queue: QueueDep
) -> dict[str, str]:
    """Email the current approver again, with a new link (the old one stops working)."""
    sub = await _editable(db, user, submission_id)
    email_id = await approvals.resend(db, sub)
    if email_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "no_approver_waiting")
    await db.commit()
    await queue.enqueue("send_form_email", email_id=str(email_id))
    return {"status": "sent"}


@router.post("/submissions/{submission_id}/approval/stop")
async def stop_approval(
    submission_id: uuid.UUID, body: StopIn, db: DbDep, user: CurrentUser, queue: QueueDep
) -> dict[str, str]:
    """End a running approval; the status is the staff's to set again."""
    sub = await _editable(db, user, submission_id)
    change = await approvals.stop(db, sub, user.id, body.reason)
    if change is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "approval_not_running")
    form = await db.get(FormRecord, sub.form_id)
    assert form is not None
    await audit(
        db,
        "submission.approval_stop",
        org_id=form.org_id,
        actor_id=user.id,
        target_type="submission",
        target_id=sub.id,
        meta={"reason": body.reason},
    )
    await db.commit()
    await approvals.enqueue(queue, sub, change)
    return {"status": "stopped"}


class DecideIn(ApiModel):
    # The step the person saw; a decision for a step that has moved on is refused.
    step: Annotated[int, Field(ge=1, le=MAX_STEPS)]
    decision: Literal["approve", "reject"]
    comment: Annotated[str, StringConstraints(max_length=2000, strip_whitespace=True)] = ""


class BulkDecideItem(ApiModel):
    id: uuid.UUID
    step: Annotated[int, Field(ge=1, le=MAX_STEPS)]


class BulkDecideIn(ApiModel):
    items: Annotated[list[BulkDecideItem], Field(min_length=1, max_length=200)]
    decision: Literal["approve", "reject"]
    comment: Annotated[str, StringConstraints(max_length=2000, strip_whitespace=True)] = ""


class BulkDecideResult(ApiModel):
    id: uuid.UUID
    seq: int | None
    # "approved" / "rejected": decided now; "already_decided": the step was decided (or the
    # approval ended) first; "not_found": not a submission of this form.
    result: Literal["approved", "rejected", "already_decided", "not_found"]
    decided_name: str | None = None


class BulkDecideOut(ApiModel):
    results: list[BulkDecideResult]


def _staff_name(user: User) -> str:
    return (user.display_name or "").strip() or user.email


async def _decide_in_studio(
    db: DbDep,
    queue: JobQueue,
    sub: Submission,
    form: FormRecord,
    user: User,
    step_no: int,
    approve: bool,
    comment: str,
) -> ApprovalStep:
    """Decide the current step as ``user`` (the caller checked their role). Raises
    :class:`approvals.AlreadyDecided` when the step isn't the one waiting any more."""
    await approvals.lock(db, sub)
    step = await approvals.current_step(db, sub)
    # A step with no approver (the answer with the address was empty) can be decided here too.
    if (
        step is None
        or step.step != step_no
        or step.state not in (StepState.PENDING, StepState.NO_APPROVER)
    ):
        raise approvals.AlreadyDecided
    change = await approvals.decide(
        db,
        sub,
        step,
        approve=approve,
        name=_staff_name(user),
        comment=comment,
        via="studio",
        actor_id=user.id,
        email=user.email,
    )
    meta: dict[str, Any] = {
        "step": step.step,
        "name": step.name,
        "decision": "approved" if approve else "rejected",
        "via": "studio",
    }
    if comment:
        meta["comment"] = comment
    await audit(
        db,
        "submission.approval_decide",
        org_id=form.org_id,
        actor_id=user.id,
        target_type="submission",
        target_id=sub.id,
        meta=meta,
    )
    await db.commit()
    await approvals.enqueue(queue, sub, change)
    return step


async def _decided_by(db: DbDep, submission_id: uuid.UUID, step_no: int) -> dict[str, Any]:
    step = await db.scalar(
        select(ApprovalStep).where(
            ApprovalStep.submission_id == submission_id, ApprovalStep.step == step_no
        )
    )
    return {
        "code": "approval_done",
        "state": step.state.value if step else None,
        "decidedName": step.decided_name if step else None,
        "decidedAt": step.decided_at.isoformat() if step and step.decided_at else None,
        "decidedVia": step.decided_via if step else None,
    }


@router.post("/submissions/{submission_id}/approval/decide")
async def decide_approval(
    submission_id: uuid.UUID, body: DecideIn, db: DbDep, user: CurrentUser, queue: QueueDep
) -> dict[str, Any]:
    """Approve or reject the current step from the studio (editors, owners, admins). It
    counts as that step's decision: the approver's link then only says it's done."""
    sub = await _editable(db, user, submission_id)
    if body.decision == "reject" and not body.comment:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "comment_required")
    form = await db.get(FormRecord, sub.form_id)
    assert form is not None
    try:
        step = await _decide_in_studio(
            db, queue, sub, form, user, body.step, body.decision == "approve", body.comment
        )
    except approvals.AlreadyDecided:
        await db.commit()  # nothing was written; ends the transaction and its lock
        raise HTTPException(
            status.HTTP_409_CONFLICT, await _decided_by(db, submission_id, body.step)
        ) from None
    return {
        "state": step.state.value,
        "status": sub.status.value,
        "approval": await approvals.detail(db, sub),
    }


@router.post("/forms/{form_id}/submissions/approval/decide", response_model=BulkDecideOut)
async def bulk_decide(
    body: BulkDecideIn, db: DbDep, access: FormViewer, queue: QueueDep
) -> BulkDecideOut:
    """Decide the current step of several submissions with one comment. Each one is its own
    change, so one already decided elsewhere doesn't stop the rest."""
    if not has_form_role(access.role, FormRole.EDITOR):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_form_role")
    if body.decision == "reject" and not body.comment:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "comment_required")
    form, user = access.form, access.user
    results: list[BulkDecideResult] = []
    for item in body.items:
        sub = await db.get(Submission, item.id)
        if sub is None or sub.form_id != form.id or sub.deleted_at is not None:
            results.append(BulkDecideResult(id=item.id, seq=None, result="not_found"))
            continue
        seq = sub.seq
        try:
            await _decide_in_studio(
                db, queue, sub, form, user, item.step, body.decision == "approve", body.comment
            )
        except approvals.AlreadyDecided:
            await db.commit()  # nothing was written; ends the transaction and its lock
            who = await _decided_by(db, item.id, item.step)
            results.append(
                BulkDecideResult(
                    id=item.id, seq=seq, result="already_decided", decided_name=who["decidedName"]
                )
            )
            continue
        results.append(
            BulkDecideResult(
                id=item.id,
                seq=seq,
                result="approved" if body.decision == "approve" else "rejected",
            )
        )
    return BulkDecideOut(results=results)


# -- the approver page (public) -------------------------------------------------------------


class CodeIn(ApiModel):
    code: Annotated[str, StringConstraints(pattern=r"^\s*\d{6}\s*$")]


class DecisionIn(ApiModel):
    decision: Literal["approve", "reject"]
    name: Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=True)]
    comment: Annotated[str, StringConstraints(max_length=2000, strip_whitespace=True)] = ""


async def _link(db: DbDep, token: str) -> tuple[ApprovalStep, Submission]:
    step = await approvals.step_by_token(db, token)
    sub = await db.get(Submission, step.submission_id) if step else None
    if step is None or sub is None or sub.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "link_invalid")
    return step, sub


async def _form_of(db: DbDep, sub: Submission) -> tuple[FormRecord, Form]:
    form = await db.get(FormRecord, sub.form_id)
    version = await db.get(FormVersion, sub.form_version_id)
    if form is None or version is None or form.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "link_invalid")
    return form, Form.model_validate(version.schema)


def _state(step: ApprovalStep, sub: Submission) -> str:
    if step.state == StepState.PENDING and sub.approval_state == ApprovalState.PENDING:
        return "pending"
    if step.state in (StepState.APPROVED, StepState.REJECTED):
        return step.state.value
    return "stopped"


async def _authorised(
    db: DbDep, settings: SettingsDep, token: str, authorization: str | None
) -> tuple[ApprovalStep, Submission]:
    step, sub = await _link(db, token)
    bearer = codes.bearer(authorization)
    if bearer is None or not tokens.check(settings, bearer, step.id, step.token_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "code_required")
    return step, sub


@public.get("/{token}")
async def approver_link(
    token: str, request: Request, db: DbDep, redis: RedisDep, settings: SettingsDep
) -> JSONResponse:
    """What the link is for, before the approver confirms their email."""
    await ratelimit.enforce(redis, settings, "approval_link", client_ip(request, settings) or "-")
    step, sub = await _link(db, token)
    form, schema = await _form_of(db, sub)
    org = await db.get(Organization, form.org_id)
    brand = resolve_brand(settings, org)
    body = {
        "state": _state(step, sub),
        "language": schema.settings.language,
        "orgName": brand.name,
        "brand": page_brand(settings, org, form, schema.dump()),
        "formTitle": schema.settings.title or form.title,
        "reference": f"#{sub.seq:04d}",
        "submittedAt": sub.submitted_at.isoformat(),
        "step": step.step,
        "total": await approvals.step_count(db, sub),
        "stepName": step.name,
        "maskedEmail": mask_email(step.approver_email or ""),
        "decidedAt": step.decided_at.isoformat() if step.decided_at else None,
        # Who decided (the name they gave, or the staff member's) and how: "email" or "studio".
        "decidedName": step.decided_name,
        "decidedVia": step.decided_via,
        "codeMinutes": settings.respondent_code_ttl_seconds // 60,
        "thaanaFontCssUrl": settings.thaana_font_css_url,
    }
    return JSONResponse(body, headers=NO_STORE)


@public.post("/{token}/code", status_code=status.HTTP_202_ACCEPTED)
async def approver_code(
    token: str,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    queue: QueueDep,
) -> dict[str, str]:
    """Email a 6-digit code to the step's approver (the address on file, never a typed one)."""
    await ratelimit.enforce(redis, settings, "otp_request_ip", client_ip(request, settings) or "-")
    step, sub = await _link(db, token)
    if _state(step, sub) != "pending" or not step.approver_email:
        raise HTTPException(status.HTTP_409_CONFLICT, "approval_done")
    await ratelimit.enforce(redis, settings, "approval_code", str(step.id))
    form, schema = await _form_of(db, sub)
    org = await db.get(Organization, form.org_id)
    code = await codes.issue_code(redis, settings, step.id, step.approver_email)
    brand = resolve_brand(settings, org)
    msg = code_message(
        org_name=brand.name,
        brand=form_email_brand(settings, org, form, schema.dump()),
        title=schema.settings.title or form.title,
        language=schema.settings.language,
        code=code,
        minutes=settings.respondent_code_ttl_seconds // 60,
    )
    await queue.enqueue(
        "send_email",
        to=step.approver_email,
        subject=msg.subject,
        text=msg.text,
        html=msg.html,
        from_name=msg.from_name,
    )
    return {"status": "sent"}


@public.post("/{token}/verify")
async def approver_verify(
    token: str, body: CodeIn, request: Request, db: DbDep, redis: RedisDep, settings: SettingsDep
) -> JSONResponse:
    await ratelimit.enforce(redis, settings, "otp_verify_ip", client_ip(request, settings) or "-")
    step, sub = await _link(db, token)
    if _state(step, sub) != "pending" or not step.approver_email or not step.token_hash:
        raise HTTPException(status.HTTP_409_CONFLICT, "approval_done")
    result = await codes.verify_code(redis, settings, step.id, step.approver_email, body.code)
    if result != "ok":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"code_{result}")
    return JSONResponse(
        {"token": tokens.issue(settings, step.id, step.approver_email, step.token_hash)},
        headers=NO_STORE,
    )


def _without_sensitive(form: Form, data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Answers for an approver: sensitive ones removed (they are staff-only, DESIGN 14.5).
    Also returns the ids of the sensitive questions that were answered, shown as "Hidden"."""
    index = FormIndex.build(form)
    hidden: list[str] = []
    out = dict(data)
    for info in index.elements.values():
        if info.kind != "field" or not getattr(info.element, "sensitive", False):
            continue
        if info.repeater_id is None:
            if out.pop(info.id, None) is not None:
                hidden.append(info.id)
            continue
        rows = out.get(info.repeater_id)
        if isinstance(rows, list):
            if any(isinstance(r, dict) and info.id in r for r in rows):
                hidden.append(info.id)
            out[info.repeater_id] = [
                {k: v for k, v in r.items() if k != info.id} if isinstance(r, dict) else r
                for r in rows
            ]
    return out, hidden


def _allowed_file_fields(form: Form, kind: type) -> set[str]:
    return {
        info.id
        for info in FormIndex.build(form).elements.values()
        if isinstance(info.element, kind) and not getattr(info.element, "sensitive", False)
    }


@public.get("/{token}/submission")
async def approver_submission(
    token: str,
    db: DbDep,
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    step, sub = await _authorised(db, settings, token, authorization)
    _form, schema = await _form_of(db, sub)
    data, hidden = _without_sensitive(schema, sub.data)
    files = (
        await db.scalars(
            select(FileRecord).where(
                FileRecord.submission_id == sub.id, FileRecord.state == FileState.ATTACHED
            )
        )
    ).all()
    allowed_files = _allowed_file_fields(schema, FileField)
    sigs = (await db.scalars(select(Signature).where(Signature.submission_id == sub.id))).all()
    allowed_sigs = _allowed_file_fields(schema, SignatureField)
    steps = await approvals.steps_of(db, sub)
    body = {
        "schema": schema.dump(),
        "data": data,
        "hidden": hidden,
        "files": {
            str(f.id): {"name": f.original_name, "size": f.size, "mime": f.mime}
            for f in files
            if f.field_id in allowed_files
        },
        "signatures": [s.field_id for s in sigs if s.field_id in allowed_sigs],
        "steps": [
            {
                "step": s.step,
                "name": s.name,
                "state": s.state.value,
                "decidedName": s.decided_name,
                "decidedAt": s.decided_at.isoformat() if s.decided_at else None,
            }
            for s in steps
        ],
        "current": step.step,
    }
    return JSONResponse(body, headers=NO_STORE)


@public.get("/{token}/files/{file_id}", response_model=None)
async def approver_file(
    token: str,
    file_id: uuid.UUID,
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    _step, sub = await _authorised(db, settings, token, authorization)
    _form, schema = await _form_of(db, sub)
    rec = await db.get(FileRecord, file_id)
    if (
        rec is None
        or rec.submission_id != sub.id
        or rec.state != FileState.ATTACHED
        or rec.field_id not in _allowed_file_fields(schema, FileField)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file_not_found")
    url = await storage.presign_download(rec.storage_key, filename=rec.original_name)
    if url is not None:
        return RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    return StreamingResponse(
        storage.iter_chunks(rec.storage_key),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": content_disposition("attachment", rec.original_name),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Length": str(rec.size),
        },
    )


@public.get("/{token}/signatures/{field_id}", response_model=None)
async def approver_signature(
    token: str,
    field_id: str,
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    _step, sub = await _authorised(db, settings, token, authorization)
    _form, schema = await _form_of(db, sub)
    sig = await db.scalar(
        select(Signature).where(Signature.submission_id == sub.id, Signature.field_id == field_id)
    )
    if sig is None or field_id not in _allowed_file_fields(schema, SignatureField):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "signature_not_found")
    return Response(
        await storage.read(sig.png_key),
        media_type="image/png",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, no-store",
        },
    )


@public.post("/{token}/decision")
async def approver_decision(
    token: str,
    body: DecisionIn,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    queue: QueueDep,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    step, sub = await _authorised(db, settings, token, authorization)
    await ratelimit.enforce(redis, settings, "approval_decision", str(step.id))
    if body.decision == "reject" and not body.comment:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "comment_required")
    # Serialise decisions on this submission, then re-read the step under the lock.
    await approvals.lock(db, sub)
    await db.refresh(step)
    if _state(step, sub) != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "approval_done")
    try:
        change = await approvals.decide(
            db, sub, step, approve=body.decision == "approve", name=body.name, comment=body.comment
        )
    except approvals.AlreadyDecided:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "approval_done") from None
    await db.commit()
    await approvals.enqueue(queue, sub, change)
    return JSONResponse(
        {
            "state": step.state.value,
            "decidedAt": (step.decided_at or datetime.now(UTC)).isoformat(),
            "nextStep": sub.approval_step if sub.approval_state == ApprovalState.PENDING else None,
            "final": sub.approval_state != ApprovalState.PENDING,
        },
        headers=NO_STORE,
    )
