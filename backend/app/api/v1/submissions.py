"""Studio submission endpoints (DESIGN 15, 17).

List with filters and cursor paging; counts by status; detail with the submission's own
schema version, files, signatures and activity; status changes, comments, bulk actions and
deletes; revealing a sensitive answer (logged); the integrity check; the signed PDF; checking
an uploaded PDF; Excel exports. Sensitive answers are always masked in lists and details.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from pydantic import Field, StringConstraints, ValidationError
from sqlalchemy import func, select

from app.answers import answer_text, mask_sensitive
from app.api.v1.common import ApiModel
from app.api.v1.files import PREVIEWABLE, content_disposition
from app.approvals import service as approvals
from app.auth.deps import CurrentUser, DbDep, SettingsDep, StorageDep
from app.importers.imported_files import pending_links, stored_entry, stored_files
from app.integrity import append_event, verify_submission
from app.logic.index import FormIndex
from app.models import (
    ApprovalState,
    EventType,
    Export,
    ExportStatus,
    FormRecord,
    FormRole,
    FormVersion,
    PdfStatus,
    Signature,
    Submission,
    SubmissionEvent,
    SubmissionStatus,
    User,
)
from app.pdf.service import check_pdf_against_db, ensure_pdf_requested
from app.permissions import FormViewer, effective_form_role, has_form_role
from app.queue import JobQueue, get_queue
from app.schemas.form import Form
from app.services.users import audit
from app.submissions.query import FieldFilter, ListFilters, apply_filters
from app.submissions.retention import erase

router = APIRouter(tags=["submissions"])

QueueDep = Annotated[JobQueue, Depends(get_queue)]
MAX_PDF_CHECK_BYTES = 50 * 1024 * 1024
Reason = Annotated[str, StringConstraints(max_length=2000, strip_whitespace=True)]


class SubmissionSummary(ApiModel):
    id: uuid.UUID
    seq: int
    status: SubmissionStatus
    language: str
    version: int
    created_at: datetime
    submitted_at: datetime
    # Confirmed address (emailed code or staff sign-in); never a typed-in answer.
    respondent_email: str | None = None
    data: dict[str, Any]
    # Running or finished approval: {state, step, total}; None when the form asked for none.
    approval: dict[str, Any] | None = None
    # "justforms", or "jotform_import" for rows brought in from an export (DESIGN 13.3).
    source: str = "justforms"


class SubmissionPage(ApiModel):
    items: list[SubmissionSummary]
    next_cursor: int | None
    total: int


class SignatureOut(ApiModel):
    id: uuid.UUID
    field_id: str
    signed_at: datetime | None
    received_at: datetime
    ip: str | None
    user_agent: str | None
    attestation: str
    strokes_sha256: str
    image_url: str


class EventOut(ApiModel):
    seq: int
    type: EventType
    actor_name: str | None
    payload: dict[str, Any]
    created_at: datetime


class ImportedFileOut(ApiModel):
    """A file or signature image copied from the source product; not part of the answers,
    the content hash or the signature audit trail."""

    field_id: str
    index: int
    kind: Literal["file", "signature"]
    name: str
    mime: str
    size: int
    fetched_at: str | None = None
    # GET it (``?preview=1`` shows images inline).
    url: str


class SubmissionDetail(SubmissionSummary):
    form_id: uuid.UUID
    schema_: dict[str, Any] = Field(alias="schema")
    can_edit: bool
    can_delete: bool
    content_hash: str | None
    pdf_status: PdfStatus
    signatures: list[SignatureOut]
    events: list[EventOut]
    pdf_sha256: str | None = None
    # Hashes kept out of the respondent's PDF; staff see them here (DESIGN 9.5).
    schema_hash: str | None = None
    chain_head: str | None = None
    # Imported rows: the source's submission id, the file/signature links that have no stored
    # copy, by field id, and the stored copies (DESIGN 13.3, "Imported files").
    external_id: str | None = None
    imported_links: dict[str, list[str]] | None = None
    imported_files: list[ImportedFileOut] = Field(default_factory=list)


class StatusPatch(ApiModel):
    status: SubmissionStatus
    reason: Reason | None = None


class CommentIn(ApiModel):
    text: Annotated[str, StringConstraints(min_length=1, max_length=4000, strip_whitespace=True)]


class RevealIn(ApiModel):
    field_id: Annotated[str, StringConstraints(max_length=63)]
    row: Annotated[int, Field(ge=0)] | None = None


class BulkIn(ApiModel):
    ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=1000)]
    action: Literal["status", "delete"]
    status: SubmissionStatus | None = None
    reason: Reason | None = None


class BulkOut(ApiModel):
    changed: int


class ExportIn(ApiModel):
    status: SubmissionStatus | None = None
    q: Annotated[str, StringConstraints(max_length=200)] | None = None
    from_: date | None = Field(default=None, alias="from")
    to: date | None = None
    version: int | None = None
    fields: list[FieldFilter] = Field(default_factory=list)
    ids: Annotated[list[uuid.UUID], Field(max_length=10_000)] | None = None


class ExportOut(ApiModel):
    id: uuid.UUID
    status: ExportStatus
    row_count: int | None
    rows_done: int
    expires_at: datetime | None
    download_url: str | None


class VerifyOut(ApiModel):
    ok: bool
    content_ok: bool
    chain_ok: bool
    chain_length: int
    broken_at: int | None
    problems: list[str]


class PdfStatusOut(ApiModel):
    pdf_status: PdfStatus


# -- helpers --------------------------------------------------------------------------------


async def _form_of(db: DbDep, version_id: uuid.UUID) -> tuple[Form, int]:
    version = await db.get(FormVersion, version_id)
    assert version is not None
    return Form.model_validate(version.schema), version.version


def _list_filters(
    status_: SubmissionStatus | None,
    q: str | None,
    from_: date | None,
    to: date | None,
    version: int | None,
    filter_: str | None,
) -> ListFilters:
    try:
        fields = [FieldFilter.model_validate(f) for f in json.loads(filter_)] if filter_ else []
        return ListFilters.model_validate(
            {
                "status": status_,
                "q": q,
                "from": from_,
                "to": to,
                "version": version,
                "fields": fields,
            }
        )
    except (ValueError, TypeError, ValidationError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_filter") from exc


@router.get("/forms/{form_id}/submissions", response_model=SubmissionPage)
async def list_submissions(
    db: DbDep,
    access: FormViewer,
    settings: SettingsDep,
    status_: Annotated[SubmissionStatus | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    version: Annotated[int | None, Query(ge=1)] = None,
    filter_: Annotated[str | None, Query(alias="filter", max_length=4000)] = None,
    cursor: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SubmissionPage:
    filters = _list_filters(status_, q, from_, to, version, filter_)
    try:
        base = apply_filters(
            select(Submission).where(Submission.form_id == access.form.id), filters, settings.tz
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_filter") from exc
    total = int(await db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    query = base if cursor is None else base.where(Submission.seq < cursor)
    rows = (await db.scalars(query.order_by(Submission.seq.desc()).limit(limit + 1))).all()
    forms: dict[uuid.UUID, tuple[Form, int]] = {}
    items = []
    totals = await approvals.counts(
        db, [s.id for s in rows[:limit] if s.approval_state is not None]
    )
    for s in rows[:limit]:
        if s.form_version_id not in forms:
            forms[s.form_version_id] = await _form_of(db, s.form_version_id)
        form, number = forms[s.form_version_id]
        items.append(
            SubmissionSummary(
                id=s.id,
                seq=s.seq,
                status=s.status,
                language=s.language,
                version=number,
                created_at=s.created_at,
                submitted_at=s.submitted_at,
                respondent_email=s.respondent_email,
                data=mask_sensitive(form, s.data),
                source=s.source.value,
                approval=(
                    {
                        "state": s.approval_state.value,
                        "step": s.approval_step,
                        "total": totals.get(s.id, 0),
                    }
                    if s.approval_state is not None
                    else None
                ),
            )
        )
    return SubmissionPage(
        items=items,
        next_cursor=items[-1].seq if len(rows) > limit and items else None,
        total=total,
    )


@router.get("/forms/{form_id}/submissions/stats", response_model=dict[str, int])
async def submission_stats(db: DbDep, access: FormViewer) -> dict[str, int]:
    rows = await db.execute(
        select(Submission.status, func.count())
        .where(Submission.form_id == access.form.id, Submission.deleted_at.is_(None))
        .group_by(Submission.status)
    )
    counts = {s.value: 0 for s in SubmissionStatus}
    for st, n in rows.all():
        counts[st.value if isinstance(st, SubmissionStatus) else str(st)] = n
    counts["all"] = sum(counts.values())
    return counts


async def _load(
    db: DbDep, user: CurrentUser, submission_id: uuid.UUID
) -> tuple[Submission, FormRecord, FormRole]:
    sub = await db.get(Submission, submission_id)
    form = await db.get(FormRecord, sub.form_id) if sub else None
    role = await effective_form_role(db, user, form) if form and form.deleted_at is None else None
    if sub is None or form is None or role is None or sub.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "submission_not_found")
    return sub, form, role


Loaded = Annotated[tuple[Submission, FormRecord, FormRole], Depends(_load)]


async def _events(db: DbDep, sub: Submission) -> list[EventOut]:
    rows = (
        await db.execute(
            select(SubmissionEvent, User.display_name, User.email)
            .outerjoin(User, User.id == SubmissionEvent.actor_id)
            .where(SubmissionEvent.submission_id == sub.id)
            .order_by(SubmissionEvent.seq.desc())
        )
    ).all()
    return [
        EventOut(
            seq=ev.seq,
            type=ev.type,
            actor_name=(name or email) if (name or email) else None,
            payload=ev.payload,
            created_at=ev.created_at,
        )
        for ev, name, email in rows
    ]


async def _detail(db: DbDep, sub: Submission, role: FormRole) -> SubmissionDetail:
    version = await db.get(FormVersion, sub.form_version_id)
    assert version is not None
    form = Form.model_validate(version.schema)
    sigs = (await db.scalars(select(Signature).where(Signature.submission_id == sub.id))).all()
    events = await _events(db, sub)
    return SubmissionDetail(
        id=sub.id,
        form_id=sub.form_id,
        seq=sub.seq,
        status=sub.status,
        language=sub.language,
        version=version.version,
        created_at=sub.created_at,
        submitted_at=sub.submitted_at,
        respondent_email=sub.respondent_email,
        data=mask_sensitive(form, sub.data),
        source=sub.source.value,
        external_id=sub.external_id,
        imported_links=pending_links(sub.imported_links) or None,
        imported_files=[
            ImportedFileOut(
                field_id=field_id,
                index=i,
                kind=e.get("kind", "file"),
                name=e.get("name", "file"),
                mime=e.get("mime", "application/octet-stream"),
                size=int(e.get("size", 0)),
                fetched_at=e.get("fetchedAt"),
                url=f"/api/v1/submissions/{sub.id}/imported-files/{field_id}/{i}",
            )
            for field_id, i, e in stored_files(sub.imported_links)
        ],
        schema_=version.schema,
        can_edit=has_form_role(role, FormRole.EDITOR),
        can_delete=has_form_role(role, FormRole.OWNER),
        content_hash=sub.content_hash,
        pdf_status=sub.pdf_status,
        signatures=[
            SignatureOut(
                id=s.id,
                field_id=s.field_id,
                signed_at=s.signed_at,
                received_at=s.received_at,
                ip=str(s.ip) if s.ip else None,
                user_agent=s.user_agent,
                attestation=s.attestation_text,
                strokes_sha256=s.strokes_sha256,
                image_url=f"/api/v1/signatures/{s.id}/image",
            )
            for s in sigs
        ],
        events=events,
        approval=await approvals.detail(db, sub),
        pdf_sha256=sub.pdf_sha256,
        schema_hash=version.schema_hash,
        chain_head=await db.scalar(
            select(SubmissionEvent.hash)
            .where(SubmissionEvent.submission_id == sub.id)
            .order_by(SubmissionEvent.seq.desc())
            .limit(1)
        ),
    )


async def _set_status(
    db: DbDep,
    sub: Submission,
    form: FormRecord,
    user: User,
    new: SubmissionStatus,
    reason: str | None,
) -> bool:
    if new == SubmissionStatus.REJECTED and not reason:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "reason_required")
    if sub.approval_state == ApprovalState.PENDING:
        # The approval decides while it runs; staff stop it first to take over.
        raise HTTPException(status.HTTP_409_CONFLICT, "approval_in_progress")
    previous = sub.status
    if previous == new:
        return False
    sub.status = new
    payload: dict[str, Any] = {"from": previous.value, "to": new.value}
    if reason:
        payload["reason"] = reason
    await append_event(db, sub, EventType.STATUS_CHANGED, actor_id=user.id, payload=payload)
    await audit(
        db,
        "submission.status",
        org_id=form.org_id,
        actor_id=user.id,
        target_type="submission",
        target_id=sub.id,
        meta=payload,
    )
    return True


async def _status_event(
    queue: JobQueue, sub: Submission, previous: SubmissionStatus, new: SubmissionStatus
) -> None:
    await queue.enqueue(
        "dispatch_event",
        event="submission.status_changed",
        submission_id=str(sub.id),
        extra={"from": previous.value, "to": new.value},
    )


async def _soft_delete(db: DbDep, sub: Submission, form: FormRecord, user: User) -> None:
    await append_event(db, sub, EventType.DELETED, actor_id=user.id)
    sub.deleted_at = datetime.now(UTC)
    await audit(
        db,
        "submission.delete",
        org_id=form.org_id,
        actor_id=user.id,
        target_type="submission",
        target_id=sub.id,
        meta={"seq": sub.seq},
    )


# -- one submission -------------------------------------------------------------------------


@router.get("/submissions/{submission_id}", response_model=SubmissionDetail)
async def get_submission(db: DbDep, loaded: Loaded) -> SubmissionDetail:
    sub, _form, role = loaded
    return await _detail(db, sub, role)


@router.get("/forms/{form_id}/submissions/seq/{seq}", response_model=SubmissionDetail)
async def get_submission_by_reference(
    seq: Annotated[int, Path(ge=1)], db: DbDep, access: FormViewer
) -> SubmissionDetail:
    """One submission by its reference number (#0047 is 47): the viewer's linkable address."""
    sub = await db.scalar(
        select(Submission).where(
            Submission.form_id == access.form.id,
            Submission.seq == seq,
            Submission.deleted_at.is_(None),
        )
    )
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "submission_not_found")
    return await _detail(db, sub, access.role)


@router.patch("/submissions/{submission_id}", response_model=SubmissionDetail)
async def patch_submission(
    body: StatusPatch, db: DbDep, user: CurrentUser, loaded: Loaded, queue: QueueDep
) -> SubmissionDetail:
    sub, form, role = loaded
    if not has_form_role(role, FormRole.EDITOR):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_form_role")
    previous = sub.status
    changed = await _set_status(db, sub, form, user, body.status, body.reason)
    await db.commit()
    if changed:
        await _status_event(queue, sub, previous, body.status)
    await db.refresh(sub)
    return await _detail(db, sub, role)


@router.post(
    "/submissions/{submission_id}/comments",
    response_model=SubmissionDetail,
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    body: CommentIn, db: DbDep, user: CurrentUser, loaded: Loaded, queue: QueueDep
) -> SubmissionDetail:
    """Comments are plain text and part of the hash-chained activity log; viewers can comment."""
    sub, _form, role = loaded
    await append_event(db, sub, EventType.COMMENT, actor_id=user.id, payload={"text": body.text})
    await db.commit()
    await queue.enqueue(
        "dispatch_event",
        event="submission.comment_added",
        submission_id=str(sub.id),
        extra={"comment": body.text, "by": user.email},
    )
    return await _detail(db, sub, role)


@router.post("/submissions/{submission_id}/reveal")
async def reveal_sensitive(
    body: RevealIn, db: DbDep, user: CurrentUser, loaded: Loaded
) -> dict[str, Any]:
    """Unmask one sensitive answer (editors and owners); every reveal is logged."""
    sub, _form, role = loaded
    if not has_form_role(role, FormRole.EDITOR):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_form_role")
    form, _n = await _form_of(db, sub.form_version_id)
    info = FormIndex.build(form).elements.get(body.field_id)
    if info is None or not getattr(info.element, "sensitive", False):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "field_not_found")
    value: Any = None
    payload: dict[str, Any] = {"field": body.field_id}
    if info.repeater_id is not None:
        rows = sub.data.get(info.repeater_id)
        if isinstance(rows, list) and body.row is not None and body.row < len(rows):
            row = rows[body.row]
            value = row.get(body.field_id) if isinstance(row, dict) else None
        payload.update(repeater=info.repeater_id, row=body.row)
    else:
        value = sub.data.get(body.field_id)
    await append_event(db, sub, EventType.VIEWED, actor_id=user.id, payload=payload)
    await db.commit()
    return {"value": answer_text(info.element, value, form.settings.language)}  # type: ignore[arg-type]


@router.delete("/submissions/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_submission(
    db: DbDep,
    user: CurrentUser,
    loaded: Loaded,
    storage: StorageDep,
    hard: bool = False,
) -> Response:
    """Owners delete: soft by default (erased after 30 days), ``?hard=true`` erases now."""
    sub, form, role = loaded
    if not has_form_role(role, FormRole.OWNER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_form_role")
    if hard:
        await erase(db, storage, sub, reason="owner", actor_id=user.id)
    else:
        await _soft_delete(db, sub, form, user)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- many submissions -----------------------------------------------------------------------


@router.post("/forms/{form_id}/submissions/bulk", response_model=BulkOut)
async def bulk_action(body: BulkIn, db: DbDep, access: FormViewer, queue: QueueDep) -> BulkOut:
    """Change status (editors) or delete (owners) several submissions of one form."""
    needed = FormRole.OWNER if body.action == "delete" else FormRole.EDITOR
    if not has_form_role(access.role, needed):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_form_role")
    if body.action == "status" and body.status is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "status_required")
    subs = (
        await db.scalars(
            select(Submission)
            .where(
                Submission.id.in_(body.ids),
                Submission.form_id == access.form.id,
                Submission.deleted_at.is_(None),
            )
            .order_by(Submission.seq)
        )
    ).all()
    changed = 0
    moved: list[tuple[Submission, SubmissionStatus]] = []
    for sub in subs:
        previous = sub.status
        if body.action == "delete":
            await _soft_delete(db, sub, access.form, access.user)
            changed += 1
        elif sub.approval_state == ApprovalState.PENDING:
            continue  # running approvals keep their status
        elif body.status is not None and await _set_status(
            db, sub, access.form, access.user, body.status, body.reason
        ):
            changed += 1
            moved.append((sub, previous))
    await db.commit()
    for sub, previous in moved:
        assert body.status is not None
        await _status_event(queue, sub, previous, body.status)
    return BulkOut(changed=changed)


def _export_out(e: Export) -> ExportOut:
    return ExportOut(
        id=e.id,
        status=e.status,
        row_count=e.row_count,
        rows_done=e.rows_done,
        expires_at=e.expires_at,
        download_url=f"/api/v1/exports/{e.id}/download" if e.status == ExportStatus.READY else None,
    )


@router.post(
    "/forms/{form_id}/exports", response_model=ExportOut, status_code=status.HTTP_201_CREATED
)
async def start_export(body: ExportIn, db: DbDep, access: FormViewer, queue: QueueDep) -> ExportOut:
    """Export the matching (or selected) submissions to .xlsx in the worker. Viewers get
    sensitive answers masked."""
    filters = ListFilters.model_validate(body.model_dump(by_alias=True)).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    filters["maskSensitive"] = not has_form_role(access.role, FormRole.EDITOR)
    export = Export(form_id=access.form.id, requested_by=access.user.id, filters=filters)
    db.add(export)
    await db.commit()
    await queue.enqueue("export_submissions", export_id=str(export.id))
    return _export_out(export)


async def _load_export(db: DbDep, user: CurrentUser, export_id: uuid.UUID) -> Export:
    export = await db.get(Export, export_id)
    form = await db.get(FormRecord, export.form_id) if export else None
    role = await effective_form_role(db, user, form) if form and form.deleted_at is None else None
    if export is None or role is None or export.requested_by != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "export_not_found")
    return export


@router.get("/exports/{export_id}", response_model=ExportOut)
async def get_export(export_id: uuid.UUID, db: DbDep, user: CurrentUser) -> ExportOut:
    return _export_out(await _load_export(db, user, export_id))


@router.get("/exports/{export_id}/download", response_model=None)
async def download_export(
    export_id: uuid.UUID, db: DbDep, user: CurrentUser, storage: StorageDep
) -> Response:
    export = await _load_export(db, user, export_id)
    if export.status != ExportStatus.READY or not export.storage_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "export_not_ready")
    form = await db.get(FormRecord, export.form_id)
    name = f"{form.slug if form else 'form'}-submissions-{export.created_at:%Y%m%d}.xlsx"
    url = await storage.presign_download(export.storage_key, filename=name)
    if url is not None:
        return RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    return StreamingResponse(
        storage.iter_chunks(export.storage_key),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": content_disposition("attachment", name),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/submissions/{submission_id}/verify", response_model=VerifyOut)
async def verify(db: DbDep, loaded: Loaded) -> VerifyOut:
    """Recompute the content hash and the activity log's hash chain (DESIGN 9.4)."""
    sub, _form, _role = loaded
    v = await verify_submission(db, sub)
    return VerifyOut(
        ok=v.ok,
        content_ok=v.content_ok,
        chain_ok=v.chain_ok,
        chain_length=v.chain_length,
        broken_at=v.broken_at,
        problems=v.problems,
    )


@router.get("/submissions/{submission_id}/pdf", response_model=None)
async def download_pdf(db: DbDep, loaded: Loaded, storage: StorageDep) -> Response:
    sub, _form, _role = loaded
    if sub.pdf_status != PdfStatus.READY or not sub.signed_pdf_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pdf_not_ready")
    name = f"submission-{sub.seq:04d}.pdf"
    url = await storage.presign_download(sub.signed_pdf_key, filename=name)
    if url is not None:
        return RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    return StreamingResponse(
        storage.iter_chunks(sub.signed_pdf_key),
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition("attachment", name),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/submissions/{submission_id}/pdf", response_model=PdfStatusOut)
async def request_pdf(db: DbDep, loaded: Loaded, queue: QueueDep) -> PdfStatusOut:
    """Create the signed PDF now (any submission; signature forms get one automatically)."""
    sub, _form, _role = loaded
    if sub.pdf_status == PdfStatus.FAILED:
        sub.pdf_status = PdfStatus.NONE
    start = await ensure_pdf_requested(sub)
    await db.commit()
    if start:
        await queue.enqueue("render_submission_pdf", submission_id=str(sub.id))
    return PdfStatusOut(pdf_status=sub.pdf_status)


@router.get("/submissions/{submission_id}/imported-files/{field_id}/{index}", response_model=None)
async def download_imported_file(
    field_id: Annotated[str, StringConstraints(max_length=63)],
    index: Annotated[int, Field(ge=0, le=1000)],
    loaded: Loaded,
    storage: StorageDep,
    preview: Annotated[bool, Query()] = False,
) -> Response:
    """A stored copy of an imported file or signature (viewer and up). Sent as an
    attachment like uploads; ``?preview=1`` shows raster images inline under a sandbox CSP."""
    sub, _form, _role = loaded
    try:
        entry = stored_entry(sub.imported_links, field_id, index)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file_not_found") from None
    name, mime = str(entry.get("name", "file")), str(entry.get("mime", ""))
    inline = preview and mime in PREVIEWABLE
    if not inline:
        url = await storage.presign_download(entry["key"], filename=name)
        if url is not None:
            return RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    return StreamingResponse(
        storage.iter_chunks(entry["key"]),
        media_type=mime if inline else "application/octet-stream",
        headers={
            "Content-Disposition": content_disposition("inline" if inline else "attachment", name),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/signatures/{signature_id}/image", response_model=None)
async def signature_image(
    signature_id: uuid.UUID, db: DbDep, user: CurrentUser, storage: StorageDep
) -> Response:
    sig = await db.get(Signature, signature_id)
    if sig is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "signature_not_found")
    await _load(db, user, sig.submission_id)
    return Response(
        await storage.read(sig.png_key),
        media_type="image/png",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.post("/pdf-checks")
async def check_pdf_upload(
    request: Request, db: DbDep, user: CurrentUser, settings: SettingsDep
) -> dict[str, Any]:
    """Check an uploaded PDF (raw ``application/pdf`` body): signature, signer and whether
    it still matches its submission. Submissions the caller cannot see are "not found"."""
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_PDF_CHECK_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file_too_large")

    async def can_see(sub: Submission) -> bool:
        form = await db.get(FormRecord, sub.form_id)
        return bool(form and form.deleted_at is None and await effective_form_role(db, user, form))

    report = await check_pdf_against_db(db, settings, bytes(body), can_see=can_see)
    return {
        "verdict": report.verdict,
        "trustedSigner": report.trusted_signer,
        "signedAt": report.pdf.get("signed_at"),
        "signerFingerprint": report.pdf.get("signer_fingerprint"),
        "signerSubject": report.pdf.get("signer_subject"),
        "submission": report.submission,
        "problems": report.problems,
    }
