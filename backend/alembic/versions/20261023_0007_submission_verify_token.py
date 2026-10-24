"""submission verify token (public verify page)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-23 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("submissions", sa.Column("verify_token", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_submissions_verify_token", "submissions", ["verify_token"])


def downgrade() -> None:
    op.drop_constraint("uq_submissions_verify_token", "submissions", type_="unique")
    op.drop_column("submissions", "verify_token")
