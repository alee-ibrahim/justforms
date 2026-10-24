"""Organisations, users and memberships (DESIGN section 6)."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import IdMixin, TimestampMixin, str_enum


class OrgRole(StrEnum):
    """Organisation roles (DESIGN 7): admin > creator (can create forms) > member."""

    ADMIN = "admin"
    CREATOR = "creator"
    MEMBER = "member"


class Appearance(StrEnum):
    """How the studio looks for this person (docs/ux/FORM-THEME-SCREENS.md section 2)."""

    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class Organization(IdMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("oidc_issuer", "oidc_subject"),)

    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    oidc_issuer: Mapped[str | None] = mapped_column(String(500))
    oidc_subject: Mapped[str | None] = mapped_column(String(255))
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    appearance: Mapped[Appearance] = mapped_column(
        str_enum(Appearance, "appearance"), default=Appearance.LIGHT, server_default="light"
    )


class OrgMembership(TimestampMixin, Base):
    __tablename__ = "org_memberships"

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[OrgRole] = mapped_column(str_enum(OrgRole, "org_role"))
    # Granted by OIDC sign-in (default organisation, group mapping or automatic join). When
    # group mapping is on, the IdP is authoritative for these: someone in no mapped group
    # loses them at sign-in. Memberships from invitations or an admin are kept.
    idp_managed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    CANCELLED = "cancelled"


class InviteEmailStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class OrgInvitation(IdMixin, TimestampMixin, Base):
    """An emailed invitation to join an organisation (docs/ux/PEOPLE-SCREENS.md).

    Accepted when someone signs in with ``email`` (email code or OIDC) while it is pending and
    not expired; the link only prefills the sign-in page. The link token is stored as a
    SHA-256 hash and minted by the worker right before the email goes out, so a resend
    replaces it. ``form_grants`` are form roles given on acceptance (sharing a form with
    someone outside the organisation): ``[{"formId": "...", "role": "viewer"}]``.
    """

    __tablename__ = "org_invitations"
    __table_args__ = (
        # One open invitation per address and organisation.
        Index(
            "uq_org_invitations_pending_email",
            "org_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_org_invitations_email", "email"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(CITEXT)
    role: Mapped[OrgRole] = mapped_column(str_enum(OrgRole, "org_invitation_role"))
    status: Mapped[InvitationStatus] = mapped_column(
        str_enum(InvitationStatus, "org_invitation_status"),
        default=InvitationStatus.PENDING,
        server_default="pending",
    )
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    form_grants: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    email_status: Mapped[InviteEmailStatus] = mapped_column(
        str_enum(InviteEmailStatus, "invite_email_status"),
        default=InviteEmailStatus.QUEUED,
        server_default="queued",
    )
    email_error: Mapped[str | None] = mapped_column(String(500))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    send_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
