"""Submissions, their event log and signatures (DESIGN sections 6 and 9)."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.approval import ApprovalState
from app.models.base import IdMixin, TimestampMixin, str_enum


class SubmissionSource(StrEnum):
    JUSTFORMS = "justforms"
    JOTFORM_IMPORT = "jotform_import"


class SubmissionStatus(StrEnum):
    NEW = "new"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class PdfStatus(StrEnum):
    NONE = "none"
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class Submission(IdMixin, TimestampMixin, Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint("form_id", "seq"),
        Index("ix_submissions_form_id_created_at", "form_id", "created_at"),
        Index("ix_submissions_form_id_respondent_email", "form_id", "respondent_email"),
        # Imported rows keep the source's id, so importing the same file twice skips them.
        Index(
            "uq_submissions_form_source_external_id",
            "form_id",
            "source",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"))
    form_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("form_versions.id", ondelete="RESTRICT")
    )
    # Per-form reference number shown to the respondent ("#0042").
    seq: Mapped[int] = mapped_column(Integer)
    status: Mapped[SubmissionStatus] = mapped_column(
        str_enum(SubmissionStatus, "submission_status"),
        default=SubmissionStatus.NEW,
        server_default="new",
    )
    language: Mapped[str] = mapped_column(String(8), default="en", server_default="en")
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Server time of the submit; part of the content hash, so it never changes.
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(1000))
    # Confirmed address of the respondent: from an emailed code (access mode "otp") or the
    # staff session (access mode "staff"). Never a typed-in answer.
    respondent_email: Mapped[str | None] = mapped_column(String(320))
    # SHA-256 (hex) of the canonical submission (DESIGN 9.3); null for rows from before it.
    content_hash: Mapped[str | None] = mapped_column(String(64))
    pdf_status: Mapped[PdfStatus] = mapped_column(
        str_enum(PdfStatus, "pdf_status"), default=PdfStatus.NONE, server_default="none"
    )
    signed_pdf_key: Mapped[str | None] = mapped_column(String(1024))
    pdf_sha256: Mapped[str | None] = mapped_column(String(64))
    # Unguessable id of the public verify page, printed as a QR code on the PDF. Created with
    # the first PDF and kept, so every signed copy of this submission points at the same page.
    verify_token: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Approval workflow (null: the form asked for no approval when this arrived).
    approval_state: Mapped[ApprovalState | None] = mapped_column(
        str_enum(ApprovalState, "approval_state")
    )
    # The step being decided (1-based), or the last one decided once finished.
    approval_step: Mapped[int | None] = mapped_column(Integer)
    # Where the outcome email goes, resolved when the response arrived (None: no email).
    approval_outcome_to: Mapped[str | None] = mapped_column(String(320))
    # Lower-cased text of the non-sensitive answers, for search (sensitive answers are never
    # searchable, DESIGN 14.5).
    search_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Where the row came from; imported rows are historic data (DESIGN 13.3).
    source: Mapped[SubmissionSource] = mapped_column(
        str_enum(SubmissionSource, "submission_source"),
        default=SubmissionSource.JUSTFORMS,
        server_default="justforms",
    )
    external_id: Mapped[str | None] = mapped_column(String(200))
    # Imported file and signature answers: links into the old product, by field id. Not part
    # of the answers or the content hash; the files themselves are not fetched.
    imported_links: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Soft delete: hidden from lists and exports at once, erased by the nightly job later.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExportStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class Export(IdMixin, TimestampMixin, Base):
    """An .xlsx export of a form's submissions (DESIGN 15.2); the file expires after 24 h."""

    __tablename__ = "exports"

    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    format: Mapped[str] = mapped_column(String(10), default="xlsx", server_default="xlsx")
    # The list filters at request time, or an explicit selection of submission ids.
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[ExportStatus] = mapped_column(
        str_enum(ExportStatus, "export_status"),
        default=ExportStatus.PENDING,
        server_default="pending",
    )
    storage_key: Mapped[str | None] = mapped_column(String(1024))
    row_count: Mapped[int | None] = mapped_column(Integer)
    rows_done: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventType(StrEnum):
    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    COMMENT = "comment"
    PDF_GENERATED = "pdf_generated"
    EXPORTED = "exported"
    VIEWED = "viewed"
    DELETED = "deleted"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_DECIDED = "approval_decided"
    APPROVAL_WAITING = "approval_waiting"
    APPROVAL_STOPPED = "approval_stopped"


class SubmissionEvent(IdMixin, Base):
    """Append-only event log, hash-chained per submission (DESIGN 9.4)."""

    __tablename__ = "submission_events"
    __table_args__ = (UniqueConstraint("submission_id", "seq"),)

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[EventType] = mapped_column(str_enum(EventType, "submission_event_type"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class Signature(IdMixin, TimestampMixin, Base):
    """One drawn signature with its audit data (DESIGN 9.1-9.2)."""

    __tablename__ = "signatures"
    __table_args__ = (UniqueConstraint("submission_id", "field_id"),)

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE")
    )
    field_id: Mapped[str] = mapped_column(String(63))
    # [[x, y, t, pressure], ...] per stroke; x/y 0-1 across the pad, t ms since first touch.
    strokes: Mapped[list[Any]] = mapped_column(JSONB)
    strokes_sha256: Mapped[str] = mapped_column(String(64))
    svg_key: Mapped[str] = mapped_column(String(1024))
    png_key: Mapped[str] = mapped_column(String(1024))
    pad_width: Mapped[int] = mapped_column(Integer)
    pad_height: Mapped[int] = mapped_column(Integer)
    device_pixel_ratio: Mapped[float | None] = mapped_column(Float)
    # The respondent's clock (untrusted, informative) and the server's.
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(1000))
    attestation_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    language: Mapped[str] = mapped_column(String(8))
