"""Uploaded files (DESIGN sections 6 and 10).

A row is created ``pending`` when a respondent starts an upload (object under ``tmp/``). On
submit the file is checked (size, magic bytes, sha256), moved under ``files/`` and marked
``attached``. Pending rows that are never attached become ``orphaned`` and their objects are
deleted by the nightly cleanup job.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import IdMixin, TimestampMixin, str_enum


class FileState(StrEnum):
    PENDING = "pending"
    ATTACHED = "attached"
    ORPHANED = "orphaned"


class ScanStatus(StrEnum):
    NOT_SCANNED = "not_scanned"
    CLEAN = "clean"
    INFECTED = "infected"


class FileRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "files"
    __table_args__ = (
        Index("ix_files_submission_id", "submission_id"),
        Index("ix_files_state_created_at", "state", "created_at"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"))
    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE")
    )
    field_id: Mapped[str] = mapped_column(String(63))
    storage_key: Mapped[str] = mapped_column(String(1024))
    original_name: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(255))
    # Declared size at upload start; replaced by the stored object's size on attach.
    size: Mapped[int] = mapped_column(BigInteger)
    # Largest size the upload may reach (field limit capped by JUSTFORMS_MAX_UPLOAD_MB).
    max_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[FileState] = mapped_column(
        str_enum(FileState, "file_state"), default=FileState.PENDING, server_default="pending"
    )
    scan_status: Mapped[ScanStatus] = mapped_column(
        str_enum(ScanStatus, "scan_status"),
        default=ScanStatus.NOT_SCANNED,
        server_default="not_scanned",
    )
    # sha256 of the per-page-load upload nonce; submit must present the same nonce.
    upload_session: Mapped[str] = mapped_column(String(64))
    # Set when the bytes have arrived (local backend) or were confirmed on attach (s3).
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
