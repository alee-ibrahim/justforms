"""Approval steps of a submission (DESIGN 15.3).

A form's approval settings (``forms.settings["approvals"]``) are copied onto each new
submission as one row per step, with the approver's address resolved from the answers, so
later changes to the settings never affect responses already in approval. The hash-chained
event log (``approval_*`` events) is the record; these rows are the working state.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import IdMixin, TimestampMixin, str_enum


class ApprovalState(StrEnum):
    """The whole approval of one submission."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    STOPPED = "stopped"


class StepState(StrEnum):
    WAITING = "waiting"  # an earlier step is not decided yet
    PENDING = "pending"  # the approver was asked
    NO_APPROVER = "no_approver"  # reached, but the answer with the approver's address is empty
    APPROVED = "approved"
    REJECTED = "rejected"
    STOPPED = "stopped"


class ApprovalStep(IdMixin, TimestampMixin, Base):
    __tablename__ = "approval_steps"
    __table_args__ = (UniqueConstraint("submission_id", "step"),)

    submission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), index=True
    )
    step: Mapped[int] = mapped_column(Integer)  # 1-based
    name: Mapped[str] = mapped_column(String(60))
    # "field": the address came from an email question (field_id); "fixed": from the settings.
    source: Mapped[str] = mapped_column(String(10))
    field_id: Mapped[str | None] = mapped_column(String(63))
    approver_email: Mapped[str | None] = mapped_column(String(320))
    state: Mapped[StepState] = mapped_column(
        str_enum(StepState, "approval_step_state"),
        default=StepState.WAITING,
        server_default="waiting",
    )
    # SHA-256 of the approver's link token; minted when the request email is sent, so sending
    # the email again replaces the link.
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_name: Mapped[str | None] = mapped_column(String(200))
    comment: Mapped[str | None] = mapped_column(Text)
    # How the step was decided: "email" (the approver's link) or "studio" (a staff member with
    # edit rights on the form, ``decided_by_id``). ``decided_email`` is the address of whoever
    # decided: the approver's for a link decision, the staff member's for a studio one.
    decided_via: Mapped[str | None] = mapped_column(String(10))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_email: Mapped[str | None] = mapped_column(String(320))
