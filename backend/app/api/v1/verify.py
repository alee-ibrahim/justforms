"""Public verify page API (``/v/{token}``, the QR code on every signed PDF).

Status only: whether the document is genuine and its record unchanged, the issuer, the
reference number, when it was issued and the approval outcome. It never returns answers,
names, email addresses or the form's title. Anyone with the PDF can also upload it to check
that their copy is the genuine, latest one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app import ratelimit
from app.auth.deps import DbDep, RedisDep, SettingsDep
from app.branding.service import resolve as resolve_brand
from app.integrity import verify_submission
from app.models import EventType, FormRecord, Organization, Submission, SubmissionEvent
from app.net import client_ip
from app.pdf.service import check_copy
from app.theme.resolve import page_brand

router = APIRouter(prefix="/public/verify", tags=["verify"])

MAX_CHECK_BYTES = 20 * 1024 * 1024
NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


async def _by_token(db: DbDep, token: str) -> Submission:
    if not 10 <= len(token) <= 64:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    sub = await db.scalar(select(Submission).where(Submission.verify_token == token))
    if sub is None or sub.deleted_at is not None or sub.pdf_sha256 is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    # A form in the trash takes its submissions with it (DESIGN 14.5).
    form = await db.get(FormRecord, sub.form_id)
    if form is None or form.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return sub


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


async def approval_summary(db: DbDep, sub: Submission) -> dict[str, Any] | None:
    """The approval outcome for the verify page (None when the form has no approval)."""
    from app.approvals.service import summary

    return await summary(db, sub)


@router.get("/{token}")
async def verify_page(
    token: str, request: Request, db: DbDep, redis: RedisDep, settings: SettingsDep
) -> JSONResponse:
    await ratelimit.enforce(redis, settings, "verify", client_ip(request, settings) or "-")
    sub = await _by_token(db, token)
    form = await db.get(FormRecord, sub.form_id)
    org = await db.get(Organization, form.org_id) if form else None
    issued = await db.scalar(
        select(SubmissionEvent.created_at)
        .where(
            SubmissionEvent.submission_id == sub.id,
            SubmissionEvent.type == EventType.PDF_GENERATED,
        )
        .order_by(SubmissionEvent.seq.desc())
        .limit(1)
    )
    verification = await verify_submission(db, sub)
    brand = resolve_brand(settings, org)
    body = {
        "state": "genuine" if verification.ok else "changed",
        "orgName": brand.name,
        "brand": page_brand(settings, org, form, None) if form else brand.public(),
        "reference": f"#{sub.seq:04d}",
        "issuedAt": _iso(issued),
        "approval": await approval_summary(db, sub),
        "thaanaFontCssUrl": settings.thaana_font_css_url,
    }
    return JSONResponse(body, headers=NO_STORE)


@router.post("/{token}/check")
async def check_copy_upload(
    token: str, request: Request, db: DbDep, redis: RedisDep, settings: SettingsDep
) -> JSONResponse:
    """Check an uploaded copy (raw ``application/pdf`` body) against this document."""
    await ratelimit.enforce(redis, settings, "verify_check", client_ip(request, settings) or "-")
    sub = await _by_token(db, token)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_CHECK_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file_too_large")
    result = await check_copy(db, settings, sub, bytes(body))
    return JSONResponse({"result": result}, headers=NO_STORE)
