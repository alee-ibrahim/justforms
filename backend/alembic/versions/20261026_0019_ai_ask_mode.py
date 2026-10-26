"""ai_sessions: mode "ask" for "Ask your submissions" chats

One chat per person and form, like the builder's; its messages are the questions, the
answers and how each number was counted (DESIGN 12.6).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-26 18:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MODE_CHECK = "ck_ai_sessions_ai_mode"


def _in(values: tuple[str, ...]) -> str:
    return "mode IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.drop_constraint(op.f(MODE_CHECK), "ai_sessions", type_="check")
    op.create_check_constraint("ai_mode", "ai_sessions", _in(("create", "edit", "import", "ask")))


def downgrade() -> None:
    op.execute("DELETE FROM ai_sessions WHERE mode = 'ask'")
    op.drop_constraint(op.f(MODE_CHECK), "ai_sessions", type_="check")
    op.create_check_constraint("ai_mode", "ai_sessions", _in(("create", "edit", "import")))
