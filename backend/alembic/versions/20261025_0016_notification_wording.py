"""notification_rules: custom subject, message and Reply-To

Owners can replace the subject and opening text of the owner notification and the respondent
receipt (plain text with placeholders) and set a Reply-To address.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-25 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notification_rules", sa.Column("subject", sa.String(200), nullable=True))
    op.add_column("notification_rules", sa.Column("message", sa.Text(), nullable=True))
    op.add_column("notification_rules", sa.Column("reply_to", sa.String(320), nullable=True))


def downgrade() -> None:
    op.drop_column("notification_rules", "reply_to")
    op.drop_column("notification_rules", "message")
    op.drop_column("notification_rules", "subject")
