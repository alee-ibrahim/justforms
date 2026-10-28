"""form_friction: anonymous counters for "Where people get stuck"

Per form, version, day and metric (page views, starts, validation errors per question and
code, submissions). No answers and no respondent identity.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-28 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "form_friction",
        sa.Column("form_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("metric", sa.String(length=16), nullable=False),
        sa.Column("page_id", sa.String(length=63), nullable=False),
        sa.Column("field_id", sa.String(length=63), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["form_id"],
            ["forms.id"],
            name=op.f("fk_form_friction_form_id_forms"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "form_id",
            "version",
            "day",
            "metric",
            "page_id",
            "field_id",
            "code",
            name=op.f("pk_form_friction"),
        ),
    )


def downgrade() -> None:
    op.drop_table("form_friction")
