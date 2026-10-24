"""organisation roles admin / creator / member, IdP-managed memberships, invitations

Everyone who was a ``member`` could create forms, so they become ``creator`` (nobody loses
access); the new ``member`` role only opens forms shared with them. Existing memberships are
marked IdP-managed so OIDC group mapping keeps treating them as before (people in no mapped
group lose them at sign-in); memberships created later by invitations or an admin are kept.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-24 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_CHECK = "ck_org_memberships_org_role"


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.drop_constraint(op.f(ROLE_CHECK), "org_memberships", type_="check")
    op.create_check_constraint(
        "org_role", "org_memberships", _in("role", ("admin", "creator", "member"))
    )
    op.execute("UPDATE org_memberships SET role = 'creator' WHERE role = 'member'")
    op.add_column(
        "org_memberships",
        sa.Column("idp_managed", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.execute("UPDATE org_memberships SET idp_managed = true")

    op.create_table(
        "org_invitations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "org_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column(
            "role", _enum("org_invitation_role", "admin", "creator", "member"), nullable=False
        ),
        sa.Column(
            "status",
            _enum("org_invitation_status", "pending", "accepted", "cancelled"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("token_hash", sa.String(64), unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invited_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "form_grants",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "email_status",
            _enum("invite_email_status", "queued", "sent", "failed"),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("email_error", sa.String(500)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("send_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("accepted_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_org_invitations_org_id", "org_invitations", ["org_id"])
    op.create_index("ix_org_invitations_email", "org_invitations", ["email"])
    op.create_index(
        "uq_org_invitations_pending_email",
        "org_invitations",
        ["org_id", "email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_org_invitations_pending_email", table_name="org_invitations")
    op.drop_index("ix_org_invitations_email", table_name="org_invitations")
    op.drop_index("ix_org_invitations_org_id", table_name="org_invitations")
    op.drop_table("org_invitations")
    op.drop_column("org_memberships", "idp_managed")
    op.execute("UPDATE org_memberships SET role = 'member' WHERE role = 'creator'")
    op.drop_constraint(op.f(ROLE_CHECK), "org_memberships", type_="check")
    op.create_check_constraint("org_role", "org_memberships", _in("role", ("admin", "member")))
