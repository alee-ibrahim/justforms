"""sec: remember when an org admin role came from OIDC superadmin

An OIDC superadmin is made admin of the default organisation. Until now that admin role stayed
when the IdP took superadmin away; these columns let sign-in undo exactly what it granted.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-27 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "org_memberships",
        sa.Column("superadmin_granted", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "org_memberships",
        sa.Column("superadmin_prior_role", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("org_memberships", "superadmin_prior_role")
    op.drop_column("org_memberships", "superadmin_granted")
