"""Forms, versions, draft history and per-form permissions (DESIGN section 6).

The draft and every version store a document that validates against
:class:`app.schemas.form.Form`; that schema is the source of truth, these tables only hold it.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import IdMixin, TimestampMixin, str_enum


class FormStatus(StrEnum):
    DRAFT = "draft"
    LIVE = "live"
    CLOSED = "closed"
    ARCHIVED = "archived"


class AccessMode(StrEnum):
    PUBLIC = "public"
    OTP = "otp"
    STAFF = "staff"


class FormRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class ActorType(StrEnum):
    USER = "user"
    AI = "ai"


class FormRecord(IdMixin, TimestampMixin, Base):
    """A form. Named ``FormRecord`` to avoid clashing with the schema's ``Form``."""

    __tablename__ = "forms"
    __table_args__ = (
        # Slugs are unique across the install among forms that are not deleted: a public form
        # lives at /<slug> (app.services.slugs).
        Index(
            "uq_forms_slug_live",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(500), default="", server_default="")
    status: Mapped[FormStatus] = mapped_column(
        str_enum(FormStatus, "form_status"), default=FormStatus.DRAFT, server_default="draft"
    )
    access_mode: Mapped[AccessMode] = mapped_column(
        str_enum(AccessMode, "access_mode"), default=AccessMode.PUBLIC, server_default="public"
    )
    draft_schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
    draft_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "form_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_forms_current_version_id_form_versions",
        )
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Who moved the form to the trash (shown in the trash; DESIGN 14.5).
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class FormSlugAlias(IdMixin, Base):
    """An earlier address of a form: ``/<slug>`` answers with a 301 to the form's current
    address (DESIGN 18.3). Kept while the form exists (the trash included) and reserved like a
    live slug, so no other form can take it; erasing the form frees it (cascade)."""

    __tablename__ = "form_slug_aliases"

    form_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forms.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FormVersion(IdMixin, TimestampMixin, Base):
    """Immutable published snapshot of a form's schema."""

    __tablename__ = "form_versions"
    __table_args__ = (UniqueConstraint("form_id", "version"),)

    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
    schema_hash: Mapped[str] = mapped_column(String(64))
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FormDraftHistory(IdMixin, TimestampMixin, Base):
    """One applied draft edit as an RFC 6902 patch plus its inverse (undo)."""

    __tablename__ = "form_draft_history"
    __table_args__ = (Index("ix_form_draft_history_form_id_revision", "form_id", "revision"),)

    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer)
    patch: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    inverse_patch: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    actor_type: Mapped[ActorType] = mapped_column(str_enum(ActorType, "actor_type"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    ai_session_id: Mapped[uuid.UUID | None] = mapped_column()
    # Set by undo; cleared entries form the redo stack until the next normal edit drops them.
    undone: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class FormPermission(TimestampMixin, Base):
    __tablename__ = "form_permissions"

    form_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forms.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[FormRole] = mapped_column(str_enum(FormRole, "form_role"))
