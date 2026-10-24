"""imports (Jotform form and submission imports) and the submission source columns

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-24 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def upgrade() -> None:
    op.create_table(
        "imports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "org_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("form_id", sa.Uuid(), sa.ForeignKey("forms.id", ondelete="CASCADE")),
        sa.Column(
            "kind",
            _enum("import_kind", "jotform_html", "jotform_api", "jotform_submissions"),
            nullable=False,
        ),
        sa.Column(
            "status",
            _enum("import_status", "preview", "running", "done", "failed"),
            nullable=False,
            server_default="preview",
        ),
        sa.Column(
            "source", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("source_key", sa.String(1024)),
        sa.Column(
            "mapping", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "report", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "stats", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_imports_org_id", "imports", ["org_id"])
    op.create_index("ix_imports_form_id", "imports", ["form_id"])

    op.add_column(
        "submissions",
        sa.Column(
            "source",
            _enum("submission_source", "justforms", "jotform_import"),
            nullable=False,
            server_default="justforms",
        ),
    )
    op.add_column("submissions", sa.Column("external_id", sa.String(200)))
    op.add_column("submissions", sa.Column("imported_links", postgresql.JSONB()))
    op.create_index(
        "uq_submissions_form_source_external_id",
        "submissions",
        ["form_id", "source", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_submissions_form_source_external_id", table_name="submissions")
    op.drop_column("submissions", "imported_links")
    op.drop_column("submissions", "external_id")
    op.drop_column("submissions", "source")
    op.drop_index("ix_imports_form_id", table_name="imports")
    op.drop_index("ix_imports_org_id", table_name="imports")
    op.drop_table("imports")
