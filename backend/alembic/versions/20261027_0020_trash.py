"""trash: who deleted a form or submission, the "restored" event, the trash index

Deleted forms and submissions stay restorable for JUSTFORMS_TRASH_DAYS (DESIGN 14.5). Existing
deletions get their deleter from the submission's latest "deleted" event and the form's
"form.delete" audit entry.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-27 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_EVENTS = (
    "created",
    "status_changed",
    "comment",
    "pdf_generated",
    "exported",
    "viewed",
    "deleted",
    "approval_requested",
    "approval_decided",
    "approval_waiting",
    "approval_stopped",
)
NEW_EVENTS = (*OLD_EVENTS, "restored")
EVENT_CHECK = "ck_submission_events_submission_event_type"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.add_column("forms", sa.Column("deleted_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_forms_deleted_by_users"),
        "forms",
        "users",
        ["deleted_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("submissions", sa.Column("deleted_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_submissions_deleted_by_users"),
        "submissions",
        "users",
        ["deleted_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_submissions_form_trash",
        "submissions",
        ["form_id", "deleted_at"],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    op.drop_constraint(op.f(EVENT_CHECK), "submission_events", type_="check")
    op.create_check_constraint(
        "submission_event_type", "submission_events", _in("type", NEW_EVENTS)
    )
    # Backfill who deleted what is already in the trash.
    op.execute(
        """
        UPDATE submissions s SET deleted_by = (
            SELECT e.actor_id FROM submission_events e
            WHERE e.submission_id = s.id AND e.type = 'deleted'
            ORDER BY e.seq DESC LIMIT 1
        )
        WHERE s.deleted_at IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE forms f SET deleted_by = (
            SELECT a.actor_id FROM audit_log a
            WHERE a.target_id = f.id AND a.action = 'form.delete'
            ORDER BY a.created_at DESC LIMIT 1
        )
        WHERE f.deleted_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM submission_events WHERE type = 'restored'")
    op.drop_constraint(op.f(EVENT_CHECK), "submission_events", type_="check")
    op.create_check_constraint(
        "submission_event_type", "submission_events", _in("type", OLD_EVENTS)
    )
    op.drop_index(
        "ix_submissions_form_trash",
        table_name="submissions",
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    op.drop_constraint(op.f("fk_submissions_deleted_by_users"), "submissions", type_="foreignkey")
    op.drop_column("submissions", "deleted_by")
    op.drop_constraint(op.f("fk_forms_deleted_by_users"), "forms", type_="foreignkey")
    op.drop_column("forms", "deleted_by")
