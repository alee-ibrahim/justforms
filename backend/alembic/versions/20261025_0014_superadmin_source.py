"""superadmin source: local (create-admin) or oidc (superadmin group mapping)

OIDC sign-in only takes away superadmin it granted. Existing superadmins were made with
create-admin, so they are marked ``local``.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-25 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "superadmin_source",
            sa.Enum(
                "local",
                "oidc",
                name="superadmin_source",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=True,
        ),
    )
    op.execute("UPDATE users SET superadmin_source = 'local' WHERE is_superadmin")


def downgrade() -> None:
    op.drop_column("users", "superadmin_source")
