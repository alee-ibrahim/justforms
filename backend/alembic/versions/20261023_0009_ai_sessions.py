"""ai assistant: sessions and messages

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-23 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_sessions",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("form_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column(
            "mode",
            sa.Enum(
                "create",
                "edit",
                "import",
                name="ai_mode",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "idle",
                "proposal",
                "closed",
                name="ai_session_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="idle",
            nullable=False,
        ),
        sa.Column("base_revision", sa.Integer(), nullable=True),
        sa.Column("base_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("working_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "flags", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["form_id"], ["forms.id"], name=op.f("fk_ai_sessions_form_id_forms"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_ai_sessions_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_ai_sessions_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_sessions")),
    )
    op.create_index(
        "ix_ai_sessions_form_id_user_id", "ai_sessions", ["form_id", "user_id"], unique=False
    )
    op.create_table(
        "ai_messages",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["ai_sessions.id"],
            name=op.f("fk_ai_messages_session_id_ai_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_messages")),
    )
    op.create_index(
        "ix_ai_messages_session_id_created_at",
        "ai_messages",
        ["session_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_messages_session_id_created_at", table_name="ai_messages")
    op.drop_table("ai_messages")
    op.drop_index("ix_ai_sessions_form_id_user_id", table_name="ai_sessions")
    op.drop_table("ai_sessions")
