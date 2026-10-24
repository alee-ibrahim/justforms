"""Form addresses: ``https://<host>/<slug>`` (docs/ux/FORM-THEME-SCREENS.md section 1).

Slugs are unique across the install among forms that are not deleted, and may not be one of
the words the app itself uses at the top level (studio routes, API, static files, document
pages). ``frontend/nginx.conf`` and ``frontend/vite.config.ts`` route ``/<slug>`` to the public
form only for paths that look like a slug and are not studio routes; keep the lists in sync.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FormRecord

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,99}$"
SLUG = re.compile(SLUG_PATTERN)
MAX_LENGTH = 100

# Top-level paths the app uses (studio routes, API, static files, document pages) plus words
# kept back for future pages. Single letters are kept for short document links (/a/, /v/, /f/).
RESERVED: frozenset[str] = frozenset(
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

Problem = Literal["invalid", "reserved", "taken"]


def slugify(text: str, fallback: str = "form") -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:60].strip("-")
    return slug or fallback


def shape_problem(slug: str) -> Problem | None:
    """``invalid`` or ``reserved`` without touching the database."""
    if not SLUG.match(slug):
        return "invalid"
    if slug in RESERVED:
        return "reserved"
    return None


async def taken(db: AsyncSession, slug: str, exclude: uuid.UUID | None = None) -> bool:
    query = select(FormRecord.id).where(FormRecord.slug == slug, FormRecord.deleted_at.is_(None))
    if exclude is not None:
        query = query.where(FormRecord.id != exclude)
    return (await db.scalar(query.limit(1))) is not None


async def problem(db: AsyncSession, slug: str, exclude: uuid.UUID | None = None) -> Problem | None:
    found = shape_problem(slug)
    if found is not None:
        return found
    return "taken" if await taken(db, slug, exclude) else None


def _with_suffix(base: str, n: int) -> str:
    suffix = f"-{n}"
    return base[: MAX_LENGTH - len(suffix)].rstrip("-") + suffix


async def unique_slug(db: AsyncSession, base: str, exclude: uuid.UUID | None = None) -> str:
    """``base`` if it is free, else ``base-2``, ``base-3``...; reserved words get a suffix too."""
    base = base[:MAX_LENGTH].strip("-") or "form"
    if not SLUG.match(base):
        base = slugify(base)
    slug, n = base, 1
    while shape_problem(slug) is not None or await taken(db, slug, exclude):
        n += 1
        slug = _with_suffix(base, n)
    return slug


def public_path(slug: str) -> str:
    return f"/{slug}"
