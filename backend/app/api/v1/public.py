"""Respondent endpoints: fetch the live form, confirm an email, upload files, submit
(DESIGN 17).

The submit evaluates logic server-side, strips hidden answers, enforces visible required
questions and attaches uploaded files. Uploads start with ``POST .../uploads``; on the
``local`` storage backend the bytes then go to ``PUT /public/uploads/{file_id}``, on ``s3``
straight to the bucket with a presigned POST (DESIGN 10).

Access modes (DESIGN 8.2-8.4): ``public`` needs nothing and uses no cookies; ``otp`` needs a
respondent token from ``.../otp/verify`` (``Authorization: Bearer``); ``staff`` needs a staff
session (cookie, plus the CSRF header on POST). Rate limits and the optional CAPTCHA follow
DESIGN 14.1-14.2.
"""

from __future__ import annotations

import hmac
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import EmailStr, Field, StringConstraints
from sqlalchemy import func, select

from app import captcha, ratelimit
from app.answers import search_text
from app.api.v1.common import ApiModel
from app.api.v1.sharing import page_head
from app.approvals import service as approvals
from app.approvals.config import approver_problems as approval_problems
from app.approvals.config import load_config as load_approvals
from app.auth import respondent as otp
from app.auth.deps import DbDep, RedisDep, SettingsDep, StorageDep, check_origin
from app.auth.sessions import (
    CSRF_HEADER,
    csrf_cookie_name,
    load_session,
    session_cookie_name,
)
from app.branding.service import resolve as resolve_brand
from app.config import Settings
from app.ids import uuid7
from app.integrity import append_event, compute_content_hash
from app.logic.engine import LogicCycleError
from app.models import (
    AccessMode,
    EventType,
    FileRecord,
    FileState,
    FormRecord,
    FormStatus,
    FormVersion,
    Organization,
    PdfStatus,
    Submission,
    User,
)
from app.net import client_ip, user_agent
from app.notifications.emails import code_message
from app.permissions import effective_form_role, org_role
from app.queue import JobQueue, get_queue
from app.schemas.form import Form
from app.services import slugs
from app.services.progress import save_progress_days
from app.services.users import normalize_email
from app.signatures import service as signatures
from app.storage import FileTooLargeError
from app.theme.resolve import form_email_brand, page_brand
from app.uploads import service as uploads
from app.validation.answers import validate_submission

log = logging.getLogger(__name__)

router = APIRouter(prefix="/public", tags=["public"])

Nonce = Annotated[str, StringConstraints(min_length=16, max_length=100)]
QueueDep = Annotated[JobQueue, Depends(get_queue)]


class SubmitIn(ApiModel):
    version_id: uuid.UUID
    data: dict[str, Any]
    upload_nonce: Nonce | None = None
    captcha_token: Annotated[str, StringConstraints(max_length=4096)] | None = None


class OtpRequestIn(ApiModel):
    email: EmailStr
    captcha_token: Annotated[str, StringConstraints(max_length=4096)] | None = None


class OtpVerifyIn(ApiModel):
    email: EmailStr
    code: Annotated[str, StringConstraints(pattern=r"^\s*\d{6}\s*$")]


class OtpVerifyOut(ApiModel):
    token: str
    email: str
    expires_in: int


class SubmitOut(ApiModel):
    seq: int
    reference: str


class UploadIn(ApiModel):
    field_id: Annotated[str, StringConstraints(max_length=63)]
    name: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    size: Annotated[int, Field(ge=0)]
    mime: Annotated[str, StringConstraints(max_length=255)] = ""
    upload_nonce: Nonce


class UploadOut(ApiModel):
    file_id: uuid.UUID
    method: str
    url: str
    fields: dict[str, str]
    headers: dict[str, str]


class FileRefOut(ApiModel):
    file_id: uuid.UUID
    name: str
    size: int
    mime: str


async def form_by_slug(db: DbDep, form_slug: str) -> FormRecord | None:
    if slugs.shape_problem(form_slug) is not None:
        return None
    return await db.scalar(
        select(FormRecord).where(FormRecord.slug == form_slug, FormRecord.deleted_at.is_(None))
    )


async def _live_form(db: DbDep, form_slug: str) -> tuple[FormRecord, FormVersion]:
    form = await form_by_slug(db, form_slug)
    # A draft is never live, even with a published version behind it.
    if form is None or form.current_version_id is None or form.status == FormStatus.DRAFT:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "form_not_found")
    if form.status in (FormStatus.CLOSED, FormStatus.ARCHIVED):
        raise HTTPException(status.HTTP_410_GONE, "form_closed")
    version = await db.get(FormVersion, form.current_version_id)
    if version is None:  # pragma: no cover - FK keeps it
        raise HTTPException(status.HTTP_404_NOT_FOUND, "form_not_found")
    return form, version


def _otp_settings(form: FormRecord) -> tuple[list[str], bool]:
    s = form.settings or {}
    return list(s.get("otpAllowedDomains", [])), bool(s.get("otpOneResponse", False))


async def _staff_email(
    form: FormRecord, request: Request, db: DbDep, redis: RedisDep, settings: Settings
) -> str | None:
    """The signed-in address for a staff-only form. Only people in the form's organisation
    (or with access to the form, or superadmins) count as staff for it."""
    session = await load_session(
        redis, settings, request.cookies.get(session_cookie_name(settings))
    )
    if session is None:
        return None
    if request.method not in ("GET", "HEAD"):
        check_origin(request, settings)
        header = request.headers.get(CSRF_HEADER, "")
        cookie = request.cookies.get(csrf_cookie_name(settings), "")
        if not (
            header
            and hmac.compare_digest(header, cookie)
            and hmac.compare_digest(header, session.csrf)
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "csrf_failed")
    user = await db.get(User, uuid.UUID(session.user_id))
    if user is None:
        return None
    if await org_role(db, user, form.org_id) is None and (
        await effective_form_role(db, user, form) is None
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not_in_organisation")
    return user.email


async def respondent_email(
    form: FormRecord,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: Settings,
    *,
    required: bool = True,
) -> str | None:
    """The confirmed respondent address for ``otp`` and ``staff`` forms (None for public
    forms). Raises 401 when the form needs one and the request has none."""
    if form.access_mode == AccessMode.PUBLIC:
        return None
    if form.access_mode == AccessMode.STAFF:
        email = await _staff_email(form, request, db, redis, settings)
        if email is None and required:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login_required")
        return email
    token = otp.bearer(request.headers.get("authorization"))
    who = otp.read_token(settings, token, form.id) if token else None
    if who is None and required:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "email_code_required")
    return who.email if who else None


async def _already_responded(db: DbDep, form: FormRecord, email: str | None) -> bool:
    if email is None or form.access_mode != AccessMode.OTP or not _otp_settings(form)[1]:
        return False
    found = await db.scalar(
        select(Submission.id).where(
            Submission.form_id == form.id,
            Submission.respondent_email == email,
            Submission.deleted_at.is_(None),
        )
    )
    return found is not None


async def _captcha_config(redis: RedisDep, settings: Settings, form: FormRecord) -> Any:
    needed = await captcha.required(redis, settings, str(form.id), form.settings)
    return captcha.public_config(settings, needed)


@router.get("/forms/{form_slug}")
async def get_public_form(
    form_slug: str,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> JSONResponse:
    await ratelimit.enforce(redis, settings, "public_form", client_ip(request, settings) or "-")
    form, version = await _live_form(db, form_slug)
    org = await db.get(Organization, form.org_id)
    brand = resolve_brand(settings, org)
    email = await respondent_email(form, request, db, redis, settings, required=False)
    locked = form.access_mode != AccessMode.PUBLIC and email is None
    if form.access_mode == AccessMode.STAFF and locked:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login_required")
    schema_settings = version.schema.get("settings", {})
    domains, one_response = _otp_settings(form)
    body: dict[str, Any] = {
        "formId": str(form.id),
        "versionId": str(version.id),
        "version": version.version,
        "orgName": brand.name,
        "brand": page_brand(settings, org, form, version.schema),
        "accessMode": form.access_mode.value,
        "title": schema_settings.get("title", ""),
        "language": schema_settings.get("language", "en"),
        "thaanaFontCssUrl": settings.thaana_font_css_url,
        "maxUploadMb": settings.max_upload_mb,
        "respondentEmail": email,
        "captcha": await _captcha_config(redis, settings, form),
        "schema": None,
    }
    days = save_progress_days(form.settings)
    body["saveProgress"] = {"days": days} if days else None
    if form.access_mode == AccessMode.OTP:
        body["otp"] = {"allowedDomains": domains, "oneResponse": one_response}
    if not locked:
        if await _already_responded(db, form, email):
            raise HTTPException(status.HTTP_409_CONFLICT, "already_responded")
        # The questions stay hidden until the respondent has confirmed their email.
        body["schema"] = version.schema
        # Per-page-load upload session: files can only be attached by the page that sent them.
        body["uploadNonce"] = uploads.new_nonce()
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


@router.get("/forms/{form_slug}/captcha")
async def captcha_challenge(
    form_slug: str,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> JSONResponse:
    """A fresh proof-of-work challenge (altcha) when the first one expired or failed."""
    ip = client_ip(request, settings) or "-"
    await ratelimit.enforce(redis, settings, "captcha_challenge", ip)
    await _live_form(db, form_slug)
    if settings.captcha_provider != "altcha":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no_challenge")
    return JSONResponse(captcha.altcha_challenge(settings), headers={"Cache-Control": "no-store"})


@router.post("/forms/{form_slug}/otp/request", status_code=status.HTTP_202_ACCEPTED)
async def request_code(
    form_slug: str,
    body: OtpRequestIn,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    queue: QueueDep,
) -> dict[str, str]:
    """Email a 6-digit code (DESIGN 8.2). The answer is the same whether or not the address
    has responded before, so it can't be used to learn who has."""
    form, version = await _live_form(db, form_slug)
    if form.access_mode != AccessMode.OTP:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "email_codes_not_used")
    email = normalize_email(body.email)
    ip = client_ip(request, settings)
    await ratelimit.enforce(redis, settings, "otp_request_ip", ip or "-")
    await ratelimit.enforce(redis, settings, "otp_request_email", f"{form.id}:{email}")
    domains, _one = _otp_settings(form)
    if not otp.domain_allowed(email, domains):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "domain_not_allowed")
    if await captcha.required(redis, settings, str(form.id), form.settings) and not (
        await captcha.verify(redis, settings, body.captcha_token, ip)
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "captcha_failed")
    code = await otp.issue_code(redis, settings, form.id, email)
    org = await db.get(Organization, form.org_id)
    schema_settings = version.schema.get("settings", {})
    brand = resolve_brand(settings, org)
    msg = code_message(
        org_name=brand.name,
        brand=form_email_brand(settings, org, form, version.schema),
        title=schema_settings.get("title", "") or form.title,
        language=schema_settings.get("language", "en"),
        code=code,
        minutes=settings.respondent_code_ttl_seconds // 60,
    )
    await queue.enqueue(
        "send_email",
        to=email,
        subject=msg.subject,
        text=msg.text,
        html=msg.html,
        from_name=msg.from_name,
    )
    return {"status": "sent"}


@router.post("/forms/{form_slug}/otp/verify", response_model=OtpVerifyOut)
async def verify_code(
    form_slug: str,
    body: OtpVerifyIn,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> OtpVerifyOut:
    form, _version = await _live_form(db, form_slug)
    if form.access_mode != AccessMode.OTP:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "email_codes_not_used")
    await ratelimit.enforce(redis, settings, "otp_verify_ip", client_ip(request, settings) or "-")
    email = normalize_email(body.email)
    result = await otp.verify_code(redis, settings, form.id, email, body.code)
    if result != "ok":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"code_{result}")
    if await _already_responded(db, form, email):
        raise HTTPException(status.HTTP_409_CONFLICT, "already_responded")
    return OtpVerifyOut(
        token=otp.issue_token(settings, form.id, email),
        email=email,
        expires_in=settings.respondent_token_seconds,
    )


@router.get("/frame-ancestors", status_code=status.HTTP_204_NO_CONTENT)
async def frame_ancestors(
    db: DbDep, settings: SettingsDep, x_original_uri: Annotated[str, Header()] = ""
) -> Response:
    """Asked by nginx (``auth_request``) for every public form page: the CSP
    ``frame-ancestors`` from the form's allowed websites (DESIGN 14.4; no list: any site may
    embed the form), and the page's ``<head>`` tags for link previews (title, description,
    Open Graph and Twitter cards; :func:`app.api.v1.sharing.page_head`), which nginx puts in
    place of the page's placeholder title. Without the tags header the page keeps its own."""
    value = "'self'"
    parts = [unquote(p) for p in urlsplit(x_original_uri).path.split("/") if p]
    form = await form_by_slug(db, parts[0]) if len(parts) == 1 else None
    if form is not None:
        origins = [o for o in (form.settings or {}).get("embedOrigins", []) if o]
        value = " ".join(["'self'", *origins]) if origins else "*"
    headers = {"X-JustForms-Frame-Ancestors": value, "Cache-Control": "no-store"}
    try:
        headers["X-JustForms-Head"] = await page_head(db, settings, form)
    except Exception:  # the page still works with its generic title
        log.exception("link preview tags failed for %s", x_original_uri[:200])
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=headers)


@router.post(
    "/forms/{form_slug}/uploads",
    response_model=UploadOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_upload(
    form_slug: str,
    body: UploadIn,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> UploadOut:
    """Start one file upload for a file question of the live version."""
    await ratelimit.enforce(redis, settings, "upload_init", client_ip(request, settings) or "-")
    form_record, version = await _live_form(db, form_slug)
    await respondent_email(form_record, request, db, redis, settings)
    await ratelimit.enforce(redis, settings, "upload_form", str(form_record.id))
    form = Form.model_validate(version.schema)
    try:
        target = await uploads.start_upload(
            db,
            storage,
            settings,
            form_record=form_record,
            form=form,
            field_id=body.field_id,
            name=body.name,
            size=body.size,
            mime=body.mime,
            nonce=body.upload_nonce,
        )
    except uploads.UploadError as exc:
        raise HTTPException(exc.status, exc.code) from exc
    await db.commit()
    return UploadOut(
        file_id=target.file_id,
        method=target.method,
        url=target.url,
        fields=target.fields,
        headers=target.headers,
    )


@router.put("/uploads/{file_id}", response_model=FileRefOut)
async def receive_upload(
    file_id: uuid.UUID,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    storage: StorageDep,
    token: Annotated[str, Header(alias=uploads.UPLOAD_TOKEN_HEADER)] = "",
) -> FileRefOut:
    """Receive the bytes of an upload (``local`` storage backend only).

    The body is streamed to storage and counted; the request fails with 413 as soon as it
    passes the file's limit, and nothing is kept."""
    if storage.supports_presigned_urls or not uploads.check_upload_token(settings, file_id, token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "upload_not_allowed")
    await ratelimit.enforce(redis, settings, "upload_bytes", client_ip(request, settings) or "-")
    rec = await db.get(FileRecord, file_id)
    if rec is None or rec.state != FileState.PENDING or rec.uploaded_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "upload_not_pending")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > rec.max_size:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file_too_large")
    try:
        info = await storage.put_stream(
            rec.storage_key, request.stream(), content_type=rec.mime, max_bytes=rec.max_size
        )
    except FileTooLargeError as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file_too_large") from exc
    if info.size < 1:
        await storage.delete(rec.storage_key)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "file_empty")
    rec.size = info.size
    rec.uploaded_at = datetime.now(UTC)
    await db.commit()
    return FileRefOut(file_id=rec.id, name=rec.original_name, size=rec.size, mime=rec.mime)


@router.post(
    "/forms/{form_slug}/submissions",
    response_model=SubmitOut,
    status_code=status.HTTP_201_CREATED,
)
async def submit(
    form_slug: str,
    body: SubmitIn,
    request: Request,
    db: DbDep,
    redis: RedisDep,
    settings: SettingsDep,
    storage: StorageDep,
    queue: QueueDep,
) -> Any:
    form_record, version = await _live_form(db, form_slug)
    ip = client_ip(request, settings)
    await ratelimit.enforce(redis, settings, "public_submit", f"{ip}:{form_record.id}")
    email = await respondent_email(form_record, request, db, redis, settings)
    if await _already_responded(db, form_record, email):
        raise HTTPException(status.HTTP_409_CONFLICT, "already_responded")
    if await captcha.required(redis, settings, str(form_record.id), form_record.settings):
        if not body.captcha_token:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "captcha_required")
        if not await captcha.verify(redis, settings, body.captcha_token, ip):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "captcha_failed")
    if body.version_id != version.id:
        return JSONResponse(
            {"detail": "version_changed", "versionId": str(version.id)},
            status_code=status.HTTP_409_CONFLICT,
        )
    form = Form.model_validate(version.schema)
    today = datetime.now(settings.tz).date()
    try:
        checked_answers = validate_submission(form, body.data, today)
    except LogicCycleError as exc:  # pragma: no cover - publish rejects cycles
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "logic_error") from exc
    errors = checked_answers.errors
    stripped = checked_answers.data
    checked = await uploads.check_files(
        db, storage, form_record=form_record, form=form, data=stripped, nonce=body.upload_nonce
    )
    prepared, signature_errors = signatures.prepare(form, stripped)
    approver_errors = approval_problems(load_approvals(form_record.settings), form, stripped, email)
    # One problem per answer: shape problems found first win over later checks.
    seen = {(e["field"], e.get("repeater"), e.get("row")) for e in errors}
    for extra in [
        *(p.as_error() for p in checked.problems),
        *signature_errors,
        *approver_errors,
    ]:
        if (extra["field"], extra.get("repeater"), extra.get("row")) not in seen:
            errors.append(extra)
    if errors:
        await db.rollback()
        return JSONResponse(
            {"detail": "invalid_answers", "errors": errors},
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    uploads.with_file_refs(form, stripped, checked.records)
    # Serialise reference numbers per form. The lock also makes "one response per address"
    # hold under concurrent submits: check again once no other submit can commit meanwhile.
    await db.execute(select(FormRecord.id).where(FormRecord.id == form_record.id).with_for_update())
    if await _already_responded(db, form_record, email):
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "already_responded")
    last = await db.scalar(
        select(func.max(Submission.seq)).where(Submission.form_id == form_record.id)
    )
    seq = (last or 0) + 1
    now = datetime.now(UTC)
    agent = user_agent(request)
    submission = Submission(
        id=uuid7(),
        form_id=form_record.id,
        form_version_id=version.id,
        seq=seq,
        language=form.settings.language,
        data=stripped,
        submitted_at=now,
        ip=ip,
        user_agent=agent,
        respondent_email=email,
        search_text=_search_text(search_text(form, stripped), email),
    )
    db.add(submission)
    await db.flush()
    await uploads.attach_files(storage, checked.records, submission_id=submission.id)
    sig_rows = await signatures.store(
        db, storage, submission, prepared, ip=ip, user_agent=agent, received_at=now
    )
    submission.content_hash = compute_content_hash(
        submission, version.schema_hash, list(checked.records.values()), sig_rows
    )
    created: dict[str, Any] = {"seq": seq, "version": version.version}
    if email:
        created["respondentVia"] = "code" if form_record.access_mode == AccessMode.OTP else "staff"
    await append_event(db, submission, EventType.CREATED, payload=created)
    approval = await approvals.start(db, submission, form_record)
    wants_pdf = bool(sig_rows)
    if wants_pdf:
        submission.pdf_status = PdfStatus.PENDING
    await db.commit()
    await ratelimit.record(redis, captcha.BUSY_COUNTER, str(form_record.id), 3600)
    if wants_pdf:
        await queue.enqueue("render_submission_pdf", submission_id=str(submission.id))
    await queue.enqueue(
        "dispatch_event", event="submission.created", submission_id=str(submission.id)
    )
    await approvals.enqueue(queue, submission, approval)
    return SubmitOut(seq=seq, reference=f"#{seq:04d}")


def _search_text(answers: str, email: str | None) -> str:
    """The respondent's confirmed address is searchable too."""
    return "\n".join(part for part in (answers, (email or "").lower()) if part)
