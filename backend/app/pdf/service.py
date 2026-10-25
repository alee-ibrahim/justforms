"""Generate, store and check signed submission PDFs (DESIGN 9.5).

``generate_pdf`` runs in the worker (job ``render_submission_pdf``): it renders the PDF,
signs it with the install's key, stores it at ``pdfs/{form_id}/{submission_id}.pdf`` and
appends a ``pdf_generated`` event with the file's SHA-256. ``check_pdf_against_db`` backs the
studio's "Check a PDF" and ``justforms verify-pdf``.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.integrity import append_event, load_parts, verify_submission
from app.models import (
    EventType,
    FormRecord,
    FormVersion,
    Organization,
    PdfStatus,
    Submission,
    SubmissionEvent,
)
from app.pdf.faces import thaana_face
from app.pdf.render import ApprovalLine, FileInfo, PdfInput, SignatureInfo, render_pdf
from app.pdf.sign import PdfCheck, check_pdf, sign_pdf
from app.schemas.form import Form
from app.signing.keys import known_certificates, signing_identity
from app.storage import Storage

log = logging.getLogger(__name__)


def pdf_key(sub: Submission) -> str:
    return f"pdfs/{sub.form_id}/{sub.id}.pdf"


def new_verify_token() -> str:
    """Unguessable id for the public verify page (printed as a QR code on the PDF)."""
    return secrets.token_urlsafe(16)


def verify_url(settings: Settings, token: str) -> str:
    return f"{settings.public_origin}/v/{token}"


async def approval_lines(db: AsyncSession, sub: Submission) -> list[ApprovalLine]:
    """The printed approval record: decided steps in order (none without approvals)."""
    from app.approvals.service import printed_record

    return await printed_record(db, sub)


async def build_input(
    db: AsyncSession, storage: Storage, settings: Settings, sub: Submission
) -> PdfInput:
    form_rec = await db.get(FormRecord, sub.form_id)
    version = await db.get(FormVersion, sub.form_version_id)
    assert form_rec is not None and version is not None
    org = await db.get(Organization, form_rec.org_id)
    schema_hash, files, sigs = await load_parts(db, sub)
    head = await db.scalar(
        select(SubmissionEvent.hash)
        .where(SubmissionEvent.submission_id == sub.id)
        .order_by(SubmissionEvent.seq.desc())
        .limit(1)
    )
    if not sub.verify_token:
        sub.verify_token = new_verify_token()
    from app.branding.colors import parse_hex
    from app.branding.service import image_bytes, resolve
    from app.theme.logo import form_logo
    from app.theme.resolve import for_form

    brand = resolve(settings, org)
    theme = for_form(settings, org, form_rec, version.schema) if org is not None else None
    accent = parse_hex(theme.colors.primary) if theme and theme.colors.light else None
    # The form's own logo when it has one, else the organisation's.
    logo: bytes | None = None
    logo_px: tuple[int, int] | None = None
    own = form_logo(form_rec)
    if own is not None:
        try:
            logo, logo_px = await storage.read(own.key), (own.width, own.height)
        except Exception:
            log.warning("form logo %s is missing; using the organisation's", own.key)
    logo_ref = brand.images.get("logo")
    if logo is None and logo_ref is not None:
        found = await image_bytes(brand, "logo", storage)
        if found:
            logo, logo_px = found[0], (logo_ref.width, logo_ref.height)
    resolved = theme.resolved if theme else None
    return PdfInput(
        org_name=brand.name,
        logo=logo,
        logo_size=logo_px,
        logo_scale=resolved.logo_size if resolved else "m",
        logo_placement=resolved.logo_placement if resolved else "start",
        show_brand=brand.custom,
        accent=accent,
        form_title=form_rec.title,
        form=Form.model_validate(version.schema),
        version=version.version,
        schema_hash=schema_hash,
        submission_id=str(sub.id),
        seq=sub.seq,
        submitted_at=sub.submitted_at,
        data=sub.data,
        content_hash=sub.content_hash or "",
        chain_head=head,
        tz=settings.tz,
        verify_url=verify_url(settings, sub.verify_token),
        files={str(f.id): FileInfo(f.original_name, f.size) for f in files},
        signatures={
            s.field_id: SignatureInfo(
                field_id=s.field_id,
                png=await storage.read(s.png_key),
                attestation=s.attestation_text,
            )
            for s in sigs
        },
        approvals=await approval_lines(db, sub),
        thaana=thaana_face(settings, "pdf"),
    )


async def generate_pdf(
    db: AsyncSession, storage: Storage, settings: Settings, submission_id: uuid.UUID
) -> bool:
    sub = await db.get(Submission, submission_id)
    if sub is None:
        return False
    try:
        ident = await signing_identity(db, settings)
        src = await build_input(db, storage, settings, sub)
        signed = await sign_pdf(render_pdf(src), ident, tsa_url=settings.pdf_tsa_url)
        key = pdf_key(sub)
        await storage.put(key, signed, content_type="application/pdf")
        digest = hashlib.sha256(signed).hexdigest()
        sub.signed_pdf_key = key
        sub.pdf_sha256 = digest
        sub.pdf_status = PdfStatus.READY
        await append_event(
            db,
            sub,
            EventType.PDF_GENERATED,
            payload={"sha256": digest, "signer": ident.fingerprint},
        )
        await db.commit()
        return True
    except Exception:
        log.exception("PDF generation failed for submission %s", submission_id)
        await db.rollback()
        sub = await db.get(Submission, submission_id)
        if sub is not None:
            sub.pdf_status = PdfStatus.FAILED
            await db.commit()
        return False


@dataclass
class PdfReport:
    """Everything "Check a PDF" says about one file."""

    verdict: str  # genuine | modified | not_ours | unsigned | data_changed | not_found
    pdf: dict[str, Any]
    trusted_signer: bool = False
    submission: dict[str, Any] | None = None
    problems: list[str] = field(default_factory=list)


def _verdict(check: PdfCheck, trusted: bool) -> str | None:
    if not check.signed:
        return "unsigned"
    if not check.intact or not check.covers_whole_file:
        return "modified"
    if not trusted:
        return "not_ours"
    return None


async def check_pdf_against_db(
    db: AsyncSession,
    settings: Settings,
    pdf: bytes,
    *,
    can_see: Any = None,
) -> PdfReport:
    """Check the signature, the signer and the submission it belongs to.

    ``can_see(sub) -> bool`` limits which submissions the caller may learn about (staff
    endpoint); the CLI passes ``None`` (an operator sees everything)."""
    check = await check_pdf(pdf)
    certs = await known_certificates(db, settings)
    trusted = bool(check.signer_fingerprint and check.signer_fingerprint in certs)
    report = PdfReport(verdict="genuine", pdf=asdict(check), trusted_signer=trusted)
    early = _verdict(check, trusted)
    if early:
        report.verdict = early
        report.problems = list(check.problems)
        if early == "not_ours":
            report.problems.append("unknown_signer")
        return report
    sub = None
    if check.submission_id:
        try:
            sub = await db.get(Submission, uuid.UUID(check.submission_id))
        except ValueError:
            sub = None
    if sub is None or (can_see is not None and not await can_see(sub)):
        report.verdict = "not_found"
        return report
    form_rec = await db.get(FormRecord, sub.form_id)
    verification = await verify_submission(db, sub)
    report.submission = {
        "id": str(sub.id),
        "formId": str(sub.form_id),
        "formTitle": form_rec.title if form_rec else "",
        "seq": sub.seq,
        "contentHashInPdf": check.content_hash,
        "contentHashStored": sub.content_hash,
        "contentHashComputed": verification.computed_hash,
        "integrityOk": verification.ok,
    }
    if check.content_hash != verification.computed_hash or not verification.content_ok:
        report.verdict = "data_changed"
        report.problems.append("content_hash_mismatch")
    return report


async def ensure_pdf_requested(sub: Submission) -> bool:
    """Mark a PDF as pending; returns True when a job should be enqueued."""
    if sub.pdf_status in (PdfStatus.PENDING, PdfStatus.READY):
        return False
    sub.pdf_status = PdfStatus.PENDING
    return True


async def check_copy(db: AsyncSession, settings: Settings, sub: Submission, pdf: bytes) -> str:
    """Check a file someone holds against the submission behind a verify link.

    ``genuine``: signed by this install, unchanged, and the latest signed copy; ``older``: the
    same, but a newer copy was signed since (e.g. after an approval); ``modified``: edited
    after signing; ``different``: a genuine PDF of another submission; ``changed``: the
    record no longer matches what was signed; ``not_ours``: unsigned or signed by someone
    else."""
    check = await check_pdf(pdf)
    certs = await known_certificates(db, settings)
    trusted = bool(check.signer_fingerprint and check.signer_fingerprint in certs)
    early = _verdict(check, trusted)
    if early in ("unsigned", "not_ours"):
        return "not_ours"
    if early == "modified":
        return "modified"
    if check.submission_id != str(sub.id):
        return "different"
    verification = await verify_submission(db, sub)
    if not verification.ok or check.content_hash != verification.computed_hash:
        return "changed"
    if sub.pdf_sha256 and hashlib.sha256(pdf).hexdigest() != sub.pdf_sha256:
        return "older"
    return "genuine"
