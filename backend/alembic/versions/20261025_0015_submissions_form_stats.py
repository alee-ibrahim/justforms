"""submissions: covering index for the forms list counts

The forms list counts each form's submissions (all, new, last 7 days, awaiting approval) and
reads the latest ``submitted_at``. This partial index answers that per form without reading
the rows.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-25 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_submissions_form_stats",
        "submissions",
        ["form_id", "submitted_at"],
        postgresql_include=["status", "approval_state"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_submissions_form_stats", table_name="submissions")
