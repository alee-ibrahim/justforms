"""approval_steps: notify addresses for steps decided in the studio

A step can be decided only by people with edit access to the form, signed in to the studio
(no approver link, no code). Such a step keeps the addresses that were told it is waiting.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-26 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("approval_steps", sa.Column("notify_to", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("approval_steps", "notify_to")
