"""Imports from other products (DESIGN 13.5): a Jotform form preview, or a submissions file
with its column mapping, and the report of what came across."""

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import IdMixin, TimestampMixin, str_enum


class ImportKind(StrEnum):
    JOTFORM_HTML = "jotform_html"
    JOTFORM_API = "jotform_api"
    JOTFORM_SUBMISSIONS = "jotform_submissions"


class ImportStatus(StrEnum):
    PREVIEW = "preview"  # parsed, waiting for the user (mapping, "Create draft")
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Import(IdMixin, TimestampMixin, Base):
    __tablename__ = "imports"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    # The created form (form imports) or the target form (submission imports).
    form_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("forms.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ImportKind] = mapped_column(str_enum(ImportKind, "import_kind"))
    status: Mapped[ImportStatus] = mapped_column(
        str_enum(ImportStatus, "import_status"),
        default=ImportStatus.PREVIEW,
        server_default="preview",
    )
    # Form imports: {"form": schema, "language", "detectedLanguage", "sourceUrl", ...}.
    # Submission imports: {"filename", "headers", "sample", "rowCount", "versionId"}.
    source: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    # Uploaded submissions file, kept until the import finishes.
    source_key: Mapped[str | None] = mapped_column(String(1024))
    mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
