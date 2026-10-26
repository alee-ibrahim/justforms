"""AI assistant sessions and their transcript (DESIGN sections 6 and 12).

A session belongs to one person on one form. Its ``working_schema`` is the AI's pending
suggestion (``None`` when there is none); nothing reaches the form's draft until the person
applies it. Builder messages hold the person's requests, the AI's replies and its tool steps,
never submission data. "Ask your submissions" chats (mode ``ask``) hold questions, answers
and the counts behind them (never the text of answers the AI read). Both are erased after 90
days.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import IdMixin, TimestampMixin, str_enum


class AiMode(StrEnum):
    CREATE = "create"
    EDIT = "edit"
    IMPORT = "import"
    ASK = "ask"  # "Ask your submissions" (questions about the answers, not form edits)


class AiSessionStatus(StrEnum):
    IDLE = "idle"  # no suggestion pending
    PROPOSAL = "proposal"  # a suggestion is waiting for Apply or Discard
    CLOSED = "closed"  # the person started a new chat


class AiSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_sessions"
    __table_args__ = (Index("ix_ai_sessions_form_id_user_id", "form_id", "user_id"),)

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(200))
    mode: Mapped[AiMode] = mapped_column(str_enum(AiMode, "ai_mode"))
    status: Mapped[AiSessionStatus] = mapped_column(
        str_enum(AiSessionStatus, "ai_session_status"),
        default=AiSessionStatus.IDLE,
        server_default="idle",
    )
    # Draft revision the pending suggestion was made from, and the suggestion itself.
    base_revision: Mapped[int | None] = mapped_column(Integer)
    base_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    working_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Uncertain items flagged by the AI ({targetId, note}) for the pending suggestion.
    flags: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default="[]")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class AiMessage(IdMixin, Base):
    """One entry of a session's transcript: ``user`` (a request) or ``assistant`` (reply,
    tool steps and outcome)."""

    __tablename__ = "ai_messages"
    __table_args__ = (Index("ix_ai_messages_session_id_created_at", "session_id", "created_at"),)

    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_sessions.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
