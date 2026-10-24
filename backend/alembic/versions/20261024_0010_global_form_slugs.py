"""form slugs unique across the install (public forms live at /<slug>)

Existing slugs are kept where possible. A slug that an earlier form (by creation time) already
uses, or that is one of the app's own top-level words, gets the first free ``-2``, ``-3``...
suffix. Links to the old ``/f/{org}/{slug}`` address keep working through a redirect, so only
forms renamed here get a new address.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-24 09:00:00
"""

import re
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Snapshot of app.services.slugs.RESERVED when this migration was written.
RESERVED = frozenset(
    {
        "a",
        "about",
        "account",
        "admin",
        "api",
        "app",
        "appearance",
        "approve",
        "approvals",
        "assets",
        "auth",
        "branding",
        "callback",
        "docs",
        "justforms",
        "embed",
        "f",
        "favicon",
        "files",
        "fonts",
        "forms",
        "health",
        "healthz",
        "help",
        "index",
        "login",
        "logout",
        "manifest",
        "me",
        "metrics",
        "new",
        "oauth",
        "profile",
        "public",
        "readyz",
        "robots",
        "settings",
        "sitemap",
        "static",
        "status",
        "theme-fonts",
        "uploads",
        "v",
        "verify",
        "www",
    }
)
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")


def _clean(slug: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", slug.lower()).strip("-")[:100].strip("-")
    return slug or "form"


def renames(rows: list[tuple[Any, str]]) -> dict[Any, str]:
    """New slugs for ``(id, slug)`` rows in creation order: the first form keeps a slug, later
    ones and reserved words get the first free ``-n`` suffix."""
    used: set[str] = set()
    out: dict[Any, str] = {}
    for form_id, slug in rows:
        base = slug if SLUG.match(slug) else _clean(slug)
        new, n = base, 1
        while new in used or new in RESERVED:
            n += 1
            suffix = f"-{n}"
            new = base[: 100 - len(suffix)].rstrip("-") + suffix
        used.add(new)
        if new != slug:
            out[form_id] = new
    return out


def upgrade() -> None:
    op.drop_index("uq_forms_org_id_slug_live", table_name="forms")
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, slug FROM forms WHERE deleted_at IS NULL ORDER BY created_at, id")
    ).all()
    for form_id, new in renames([(r[0], r[1]) for r in rows]).items():
        conn.execute(
            sa.text("UPDATE forms SET slug = :slug WHERE id = :id"), {"slug": new, "id": form_id}
        )
    op.create_index(
        "uq_forms_slug_live",
        "forms",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_forms_slug_live", table_name="forms")
    op.create_index(
        "uq_forms_org_id_slug_live",
        "forms",
        ["org_id", "slug"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
