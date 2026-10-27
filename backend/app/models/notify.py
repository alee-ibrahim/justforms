"""Email notification rules, sent-email log, webhooks and their deliveries (DESIGN 6, 11)."""

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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import IdMixin, TimestampMixin, str_enum


class RuleType(StrEnum):
    OWNER_EMAIL = "owner_email"
    RESPONDENT_RECEIPT = "respondent_receipt"


class NotificationRule(IdMixin, TimestampMixin, Base):
    """One email rule per form and type."""

    __tablename__ = "notification_rules"
    __table_args__ = (UniqueConstraint("form_id", "type"),)

    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"))
    type: Mapped[RuleType] = mapped_column(str_enum(RuleType, "notification_rule_type"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Owner email: explicit addresses (empty = the form's owners).
    recipients: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    include_answers: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    attach_pdf: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Receipt: the email question to send to; None = the confirmed (OTP/staff) address.
    email_field: Mapped[str | None] = mapped_column(String(63))
    # Receipt: also send to a typed address nobody confirmed (rate limited; no answers or PDF
    # unless ``unverified_answers``). Off: only the confirmed address gets a receipt.
    to_unverified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    unverified_answers: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # Custom wording (plain text with placeholders, DESIGN 11.1); None = the built-in text.
    subject: Mapped[str | None] = mapped_column(String(200))
    message: Mapped[str | None] = mapped_column(Text)
    # Where replies go (a Reply-To header); None = replies go to the sender address.
    reply_to: Mapped[str | None] = mapped_column(String(320))


class EmailStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class EmailDelivery(IdMixin, TimestampMixin, Base):
    """Notification emails sent for a form, shown on its Settings page. Never holds bodies."""

    __tablename__ = "email_deliveries"
    __table_args__ = (Index("ix_email_deliveries_form_id_created_at", "form_id", "created_at"),)

    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"))
    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("submissions.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(32))
    to_address: Mapped[str] = mapped_column(String(320))
    status: Mapped[EmailStatus] = mapped_column(
        str_enum(EmailStatus, "email_status"), default=EmailStatus.QUEUED, server_default="queued"
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(500))
    # Non-secret context for the message (e.g. the URL of a webhook that was turned off).
    detail: Mapped[str | None] = mapped_column(String(2000))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Webhook(IdMixin, TimestampMixin, Base):
    __tablename__ = "webhooks"
    __table_args__ = (Index("ix_webhooks_form_id", "form_id"),)

    form_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(String(2000))
    # Signing secret, encrypted with a key derived from JUSTFORMS_SECRET_KEY.
    secret_enc: Mapped[bytes] = mapped_column(LargeBinary)
    # The secret before the last rotation; requests carry both signatures until it expires.
    previous_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    previous_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    events: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    include_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Set when JustForms turned the webhook off (e.g. "failures"); cleared when re-enabled.
    disabled_reason: Mapped[str | None] = mapped_column(String(50))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WebhookDelivery(IdMixin, TimestampMixin, Base):
    """One event sent (and retried) to one webhook. Kept for 30 days."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        Index("ix_webhook_deliveries_webhook_id_created_at", "webhook_id", "created_at"),
        Index("ix_webhook_deliveries_status_next_attempt_at", "status", "next_attempt_at"),
    )

    webhook_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("webhooks.id", ondelete="CASCADE"))
    event_id: Mapped[str] = mapped_column(String(64))
    event: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[DeliveryStatus] = mapped_column(
        str_enum(DeliveryStatus, "webhook_delivery_status"),
        default=DeliveryStatus.PENDING,
        server_default="pending",
    )
    response_code: Mapped[int | None] = mapped_column(Integer)
    response_snippet: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(String(500))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
