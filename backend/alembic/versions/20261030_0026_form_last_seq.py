"""forms.last_seq: a per-form reference number counter that never goes down

Reference numbers used to be the form's highest stored number plus one, so erasing the newest
submission freed its number for the next one. The counter starts at the highest number the
form has used: the submissions still stored and the ``submission.erased`` tombstones in
``audit_log`` (which record the erased submission's form and number).

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-30 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Also run by the tests (tests/test_reference_numbers.py).
BACKFILL = """
UPDATE forms AS f
SET last_seq = used.top
FROM (
    SELECT form_id, max(seq) AS top
    FROM (
        SELECT form_id::text AS form_id, seq FROM submissions
        UNION ALL
        SELECT meta->>'form_id', (meta->>'seq')::integer
        FROM audit_log
        WHERE action = 'submission.erased'
          AND meta->>'form_id' IS NOT NULL
          AND meta->>'seq' ~ '^[0-9]{1,9}$'
    ) AS refs
    GROUP BY form_id
) AS used
WHERE used.form_id = f.id::text AND used.top > f.last_seq
"""


def upgrade() -> None:
    op.add_column("forms", sa.Column("last_seq", sa.Integer(), server_default="0", nullable=False))
    op.execute(BACKFILL)


def downgrade() -> None:
    op.drop_column("forms", "last_seq")
