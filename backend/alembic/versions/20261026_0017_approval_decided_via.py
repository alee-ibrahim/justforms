"""approval_steps: who decided and how (approver link or studio)

Staff with edit rights can decide the current approval step in the studio. The step records
whether it was decided through the emailed link or the studio, the staff member, and the
address of whoever decided it.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-26 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("approval_steps", sa.Column("decided_via", sa.String(10), nullable=True))
    op.add_column(
        "approval_steps",
        sa.Column(
            "decided_by_id",
            sa.Uuid(),
            sa.ForeignKey(
                "users.id", ondelete="SET NULL", name="fk_approval_steps_decided_by_id_users"
            ),
            nullable=True,
        ),
    )
    op.add_column("approval_steps", sa.Column("decided_email", sa.String(320), nullable=True))
    # Decisions made before this column existed came through the approver's link.
    op.execute(
        "UPDATE approval_steps SET decided_via = 'email', decided_email = approver_email "
        "WHERE state IN ('approved', 'rejected')"
    )


def downgrade() -> None:
    op.drop_column("approval_steps", "decided_email")
    op.drop_column("approval_steps", "decided_by_id")
    op.drop_column("approval_steps", "decided_via")
