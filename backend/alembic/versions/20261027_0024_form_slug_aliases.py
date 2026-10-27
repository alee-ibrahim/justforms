"""form_slug_aliases: earlier form addresses redirect to the current one

When an owner changes a form's address, the old one is kept here and answers with a 301 to
the new address. Aliases are reserved like live slugs and go when the form is erased.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-27 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "form_slug_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("form_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["form_id"],
            ["forms.id"],
            name=op.f("fk_form_slug_aliases_form_id_forms"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_form_slug_aliases")),
        sa.UniqueConstraint("slug", name=op.f("uq_form_slug_aliases_slug")),
    )
    op.create_index(
        op.f("ix_form_slug_aliases_form_id"), "form_slug_aliases", ["form_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_form_slug_aliases_form_id"), table_name="form_slug_aliases")
    op.drop_table("form_slug_aliases")
