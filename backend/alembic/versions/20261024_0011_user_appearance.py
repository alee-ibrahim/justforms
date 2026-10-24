"""studio appearance per user: light (default), dark or system

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-24 09:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "appearance",
            sa.Enum(
                "light",
                "dark",
                "system",
                name="appearance",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
            server_default="light",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "appearance")
