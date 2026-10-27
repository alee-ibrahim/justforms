"""notification_rules: receipts to unconfirmed addresses are opt-in

Receipts go to the confirmed respondent address. Sending to an address typed into an email
question (that nobody confirmed) is a separate opt-in, rate limited, and leaves out the answers
and the signed PDF unless the owner also allows them. Existing receipts sent to an email
question keep sending, without answers.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-27 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification_rules",
        sa.Column("to_unverified", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "notification_rules",
        sa.Column("unverified_answers", sa.Boolean(), server_default="false", nullable=False),
    )
    op.execute(
        "UPDATE notification_rules SET to_unverified = true "
        "WHERE type = 'respondent_receipt' AND email_field IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("notification_rules", "unverified_answers")
    op.drop_column("notification_rules", "to_unverified")
