"""PAdES signing and verification of submission PDFs with pyHanko (DESIGN 9.5)."""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from typing import Any

from asn1crypto import x509 as asn1_x509
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import fields, signers, timestamps
from pyhanko.sign.validation import async_validate_pdf_signature
from pyhanko_certvalidator import ValidationContext
from pyhanko_certvalidator.registry import SimpleCertificateStore

from app.signing.keys import SigningIdentity

FIELD_NAME = "JustFormsSignature"
KEYWORD = re.compile(
    r"justforms-submission:([0-9a-f-]{36})\s+justforms-content-hash:([0-9a-f]{64})"
)


async def sign_pdf(pdf: bytes, ident: SigningIdentity, *, tsa_url: str | None = None) -> bytes:
    signer = signers.SimpleSigner(
        signing_cert=ident.cert,
        signing_key=ident.key,
        cert_registry=SimpleCertificateStore.from_certs([ident.cert]),
    )
    meta = signers.PdfSignatureMetadata(
        field_name=FIELD_NAME,
        md_algorithm="sha256",
        subfilter=fields.SigSeedSubFilter.PADES,
        reason="Submission record",
        name=ident.subject,
    )
    stamper = timestamps.HTTPTimeStamper(tsa_url) if tsa_url else None
    writer = IncrementalPdfFileWriter(io.BytesIO(pdf))
    out = await signers.async_sign_pdf(
        writer,
        meta,
        signer=signer,
        timestamper=stamper,
        new_field_spec=fields.SigFieldSpec(sig_field_name=FIELD_NAME),
    )
    return out.getvalue()


@dataclass
class PdfCheck:
    """Result of checking a PDF's signature (not yet its submission)."""

    signed: bool = False
    intact: bool = False  # the signed bytes are unchanged
    covers_whole_file: bool = False  # nothing was appended after signing
    signer_fingerprint: str | None = None
    signer_subject: str | None = None
    signed_at: str | None = None
    submission_id: str | None = None
    content_hash: str | None = None
    problems: list[str] = field(default_factory=list)


def _keywords(reader: PdfFileReader) -> str:
    try:
        info: Any = reader.trailer["/Info"]
        return str(info.get("/Keywords", ""))
    except Exception:
        return ""


async def check_pdf(pdf: bytes) -> PdfCheck:
    """Read and cryptographically check the JustForms signature in ``pdf``."""
    result = PdfCheck()
    try:
        reader = PdfFileReader(io.BytesIO(pdf), strict=False)
    except Exception:
        result.problems.append("not_a_pdf")
        return result
    m = KEYWORD.search(_keywords(reader))
    if m:
        result.submission_id, result.content_hash = m.group(1), m.group(2)
    sigs = reader.embedded_signatures
    if not sigs:
        result.problems.append("no_signature")
        return result
    sig = sigs[-1]
    result.signed = True
    cert: asn1_x509.Certificate = sig.signer_cert
    result.signer_fingerprint = hashlib.sha256(cert.dump()).hexdigest()
    result.signer_subject = cert.subject.human_friendly
    # Trust is decided by the caller (fingerprint against the install's certificates);
    # here only integrity is checked, so the self-signed cert is its own trust root.
    ctx = ValidationContext(trust_roots=[cert], allow_fetching=False)
    try:
        status = await async_validate_pdf_signature(sig, ctx)
    except Exception:
        result.problems.append("signature_unreadable")
        return result
    result.intact = bool(status.intact and status.valid)
    coverage = getattr(status, "coverage", None)
    result.covers_whole_file = coverage is not None and coverage.name == "ENTIRE_FILE"
    if status.signer_reported_dt:
        result.signed_at = status.signer_reported_dt.isoformat()
    if not result.intact:
        result.problems.append("modified")
    elif not result.covers_whole_file:
        result.problems.append("modified_after_signing")
    if result.submission_id is None:
        result.problems.append("not_a_justforms_pdf")
    return result
