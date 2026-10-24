"""baseline: organisations, users, memberships, forms, versions, draft history, audit log

Revision ID: 0001
Revises:
Create Date: 2026-10-23 03:35:11.455007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column(
            "settings", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )
    op.create_table(
        "users",
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("display_name", sa.String(length=200), server_default="", nullable=False),
        sa.Column("oidc_issuer", sa.String(length=500), nullable=True),
        sa.Column("oidc_subject", sa.String(length=255), nullable=True),
        sa.Column("is_superadmin", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("oidc_issuer", "oidc_subject", name=op.f("uq_users_oidc_issuer")),
    )
    op.create_table(
        "audit_log",
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column(
            "meta", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_audit_log_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_audit_log_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(
        "ix_audit_log_org_id_created_at", "audit_log", ["org_id", "created_at"], unique=False
    )
    op.create_table(
        "forms",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=500), server_default="", nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "live",
                "closed",
                "archived",
                name="form_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="draft",
            nullable=False,
        ),
        sa.Column(
            "access_mode",
            sa.Enum(
                "public",
                "otp",
                "staff",
                name="access_mode",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="public",
            nullable=False,
        ),
        sa.Column("draft_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("draft_revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column(
            "settings", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_forms_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_forms_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forms")),
    )
    op.create_index(op.f("ix_forms_org_id"), "forms", ["org_id"], unique=False)
    op.create_index(
        "uq_forms_org_id_slug_live",
        "forms",
        ["org_id", "slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "org_memberships",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "admin",
                "member",
                name="org_role",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_org_memberships_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_org_memberships_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("org_id", "user_id", name=op.f("pk_org_memberships")),
    )
    op.create_index(
        op.f("ix_org_memberships_user_id"), "org_memberships", ["user_id"], unique=False
    )
    op.create_table(
        "form_draft_history",
        sa.Column("form_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("patch", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("inverse_patch", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "actor_type",
            sa.Enum(
                "user",
                "ai",
                name="actor_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("ai_session_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_form_draft_history_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["form_id"],
            ["forms.id"],
            name=op.f("fk_form_draft_history_form_id_forms"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form_draft_history")),
    )
    op.create_index(
        "ix_form_draft_history_form_id_revision",
        "form_draft_history",
        ["form_id", "revision"],
        unique=False,
    )
    op.create_table(
        "form_permissions",
        sa.Column("form_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "owner",
                "editor",
                "viewer",
                name="form_role",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["form_id"],
            ["forms.id"],
            name=op.f("fk_form_permissions_form_id_forms"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_form_permissions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("form_id", "user_id", name=op.f("pk_form_permissions")),
    )
    op.create_index(
        op.f("ix_form_permissions_user_id"), "form_permissions", ["user_id"], unique=False
    )
    op.create_table(
        "form_versions",
        sa.Column("form_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_hash", sa.String(length=64), nullable=False),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["form_id"],
            ["forms.id"],
            name=op.f("fk_form_versions_form_id_forms"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["published_by"],
            ["users.id"],
            name=op.f("fk_form_versions_published_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form_versions")),
        sa.UniqueConstraint("form_id", "version", name=op.f("uq_form_versions_form_id")),
    )
    # forms <-> form_versions reference each other; add this one once both exist.
    op.create_foreign_key(
        "fk_forms_current_version_id_form_versions",
        "forms",
        "form_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_forms_current_version_id_form_versions", "forms", type_="foreignkey")
    op.drop_table("form_versions")
    op.drop_index(op.f("ix_form_permissions_user_id"), table_name="form_permissions")
    op.drop_table("form_permissions")
    op.drop_index("ix_form_draft_history_form_id_revision", table_name="form_draft_history")
    op.drop_table("form_draft_history")
    op.drop_index(op.f("ix_org_memberships_user_id"), table_name="org_memberships")
    op.drop_table("org_memberships")
    op.drop_index(
        "uq_forms_org_id_slug_live",
        table_name="forms",
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index(op.f("ix_forms_org_id"), table_name="forms")
    op.drop_table("forms")
    op.drop_index("ix_audit_log_org_id_created_at", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("users")
    op.drop_table("organizations")
