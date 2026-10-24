"""approval workflow: steps per submission, approval state and events

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-23 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
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
)
NEW_EVENTS = (
    *OLD_EVENTS,
    "approval_requested",
    "approval_decided",
    "approval_waiting",
    "approval_stopped",
)
EVENT_CHECK = "ck_submission_events_submission_event_type"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "approval_steps",
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("field_id", sa.String(length=63), nullable=True),
        sa.Column("approver_email", sa.String(length=320), nullable=True),
        sa.Column(
            "state",
            sa.Enum(
                "waiting",
                "pending",
                "no_approver",
                "approved",
                "rejected",
                "stopped",
                name="approval_step_state",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="waiting",
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_name", sa.String(length=200), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["submissions.id"],
            name=op.f("fk_approval_steps_submission_id_submissions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_steps")),
        sa.UniqueConstraint("submission_id", "step", name=op.f("uq_approval_steps_submission_id")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_approval_steps_token_hash")),
    )
    op.create_index(
        op.f("ix_approval_steps_submission_id"), "approval_steps", ["submission_id"], unique=False
    )
    op.add_column(
        "submissions",
        sa.Column(
            "approval_state",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                "stopped",
                name="approval_state",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
    )
    op.add_column("submissions", sa.Column("approval_step", sa.Integer(), nullable=True))
    op.add_column(
        "submissions", sa.Column("approval_outcome_to", sa.String(length=320), nullable=True)
    )
    op.drop_constraint(op.f(EVENT_CHECK), "submission_events", type_="check")
    op.create_check_constraint(
        "submission_event_type", "submission_events", _in("type", NEW_EVENTS)
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM submission_events WHERE type NOT IN "
        f"({', '.join(repr(v) for v in OLD_EVENTS)})"
    )
    op.drop_constraint(op.f(EVENT_CHECK), "submission_events", type_="check")
    op.create_check_constraint(
        "submission_event_type", "submission_events", _in("type", OLD_EVENTS)
    )
    op.drop_constraint(op.f("ck_submissions_approval_state"), "submissions", type_="check")
    op.drop_column("submissions", "approval_outcome_to")
    op.drop_column("submissions", "approval_step")
    op.drop_column("submissions", "approval_state")
    op.drop_index(op.f("ix_approval_steps_submission_id"), table_name="approval_steps")
    op.drop_table("approval_steps")
