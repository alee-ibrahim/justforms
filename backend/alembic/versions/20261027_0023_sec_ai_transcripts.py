"""ai_messages: Ask transcripts no longer keep listed rows

Lists shown in an Ask answer are now stored as what was listed (questions, conditions, order)
and read again from the database when the answer is opened. Rows stored by earlier versions
(answers, sensitive ones and respondent emails included) are removed; those lists are marked
``expired`` and the studio says to ask again.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-27 12:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


STRIP_ROWS = """
        UPDATE ai_messages
        SET content = jsonb_set(
            content,
            '{charts}',
            (
                SELECT coalesce(
                    jsonb_agg(
                        CASE
                            WHEN c->>'display' = 'list' AND (c->'spec') IS NULL
                            THEN (c - 'rows')
                                || jsonb_build_object('rows', '[]'::jsonb, 'expired', true)
                            ELSE c
                        END
                        ORDER BY ord
                    ),
                    '[]'::jsonb
                )
                FROM jsonb_array_elements(content->'charts') WITH ORDINALITY AS t(c, ord)
            )
        )
        WHERE role = 'assistant'
          AND jsonb_typeof(content->'charts') = 'array'
          AND EXISTS (
              SELECT 1 FROM jsonb_array_elements(content->'charts') AS e(c)
              WHERE c->>'display' = 'list' AND (c->'spec') IS NULL
          )
"""


def upgrade() -> None:
    op.execute(STRIP_ROWS)


def downgrade() -> None:
    # The removed rows are not restored (they should not have been kept).
    pass
