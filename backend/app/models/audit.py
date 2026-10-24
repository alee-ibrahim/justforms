"""Org-level audit log: permission changes, publishes, logins, deletions (DESIGN section 6)."""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import IdMixin, TimestampMixin


class AuditLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_org_id_created_at", "org_id", "created_at"),)

    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[uuid.UUID | None] = mapped_column()
    ip: Mapped[str | None] = mapped_column(INET)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
