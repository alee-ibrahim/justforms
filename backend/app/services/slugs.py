"""Form addresses: ``https://<host>/<slug>`` (docs/ux/FORM-THEME-SCREENS.md section 1).

Slugs are unique across the install among forms that are not deleted, and may not be one of
the words the app itself uses at the top level (studio routes, API, static files, document
pages). ``frontend/nginx.conf`` and ``frontend/vite.config.ts`` route ``/<slug>`` to the public
form only for paths that look like a slug and are not studio routes; keep the lists in sync.

Addresses are made from titles by :func:`slugify`; Thaana titles are romanised first (the
official 1977 rules, :mod:`app.text.thaana_latin`). Its twin is ``titleSlug`` in
``frontend/src/thaana/latin.ts``; both run ``spec/slugs/slugs.json``.

When a published form's address changes, the old one is kept as an alias
(:class:`app.models.FormSlugAlias`) that redirects to the new one (301) and stays reserved until
the form is erased.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FormRecord, FormSlugAlias
from app.text.thaana_latin import has_thaana, romanise

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,99}$"
SLUG = re.compile(SLUG_PATTERN)
MAX_LENGTH = 100
# Addresses made from a title are cut to about this many characters, at a word boundary.
TITLE_LENGTH = 60
# What a title without Latin letters used to give: a form at such an address may be offered a
# readable one (the Share page).
GENERIC = re.compile(r"^form(-[0-9]+)?$")

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


def _cut(slug: str, limit: int = TITLE_LENGTH) -> str:
    """At most ``limit`` characters, ending at a word (hyphen) when one ends past a third."""
    if len(slug) <= limit:
        return slug
    head = slug[: limit + 1]
    at = head.rfind("-")
    return head[:at] if at >= limit // 3 else slug[:limit].rstrip("-")


def slugify(text: str, fallback: str = "form") -> str:
    """An address from a title: Thaana romanised, apostrophes dropped (kan'di -> kandi),
    accents folded, anything else a hyphen, cut to about 60 characters at a word."""
    if has_thaana(text):
        text = romanise(text)
    text = re.sub("['\u2019\u02bc]", "", text)
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return _cut(slug).strip("-") or fallback


def is_generic(slug: str) -> bool:
    return GENERIC.match(slug) is not None


def shape_problem(slug: str) -> Problem | None:
    """``invalid`` or ``reserved`` without touching the database."""
    if not SLUG.match(slug):
        return "invalid"
    if slug in RESERVED:
        return "reserved"
    return None


async def taken(db: AsyncSession, slug: str, exclude: uuid.UUID | None = None) -> bool:
    """Used by another form that is not deleted, or kept as another form's earlier address
    (aliases stay reserved while their form is in the trash)."""
    query = select(FormRecord.id).where(FormRecord.slug == slug, FormRecord.deleted_at.is_(None))
    alias = select(FormSlugAlias.id).where(FormSlugAlias.slug == slug)
    if exclude is not None:
        query = query.where(FormRecord.id != exclude)
        alias = alias.where(FormSlugAlias.form_id != exclude)
    if (await db.scalar(query.limit(1))) is not None:
        return True
    return (await db.scalar(alias.limit(1))) is not None


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


async def follow_title(db: AsyncSession, form: FormRecord) -> None:
    """Before the first publish nobody has the link yet: a form still at a generic address
    (``form``, ``form-2``) takes one from its title once the title gives a real one (a title
    written later in the builder or by the AI assistant)."""
    if form.current_version_id is not None or not is_generic(form.slug):
        return
    base = slugify(form.title)
    if not is_generic(base):
        form.slug = await unique_slug(db, base, form.id)


async def find_form(db: AsyncSession, slug: str) -> FormRecord | None:
    """The form (not deleted) at ``slug``, or the one that used to live there: compare
    ``form.slug`` with ``slug`` to tell an alias, which answers with a redirect. Forms in the
    trash don't answer, by their address or an alias."""
    if shape_problem(slug) is not None:
        return None
    form = await db.scalar(
        select(FormRecord).where(FormRecord.slug == slug, FormRecord.deleted_at.is_(None))
    )
    if form is not None:
        return form
    return await db.scalar(
        select(FormRecord)
        .join(FormSlugAlias, FormSlugAlias.form_id == FormRecord.id)
        .where(FormSlugAlias.slug == slug, FormRecord.deleted_at.is_(None))
        .limit(1)
    )


async def aliases(db: AsyncSession, form_id: uuid.UUID) -> list[str]:
    """A form's earlier addresses, newest first."""
    rows = await db.scalars(
        select(FormSlugAlias.slug)
        .where(FormSlugAlias.form_id == form_id)
        .order_by(FormSlugAlias.created_at.desc(), FormSlugAlias.slug)
    )
    return list(rows.all())


async def change(db: AsyncSession, form: FormRecord, new: str, *, keep_old: bool = True) -> None:
    """Move a form to ``new`` (already checked). A published form keeps its old address as an
    alias so shared links still work (``keep_old``); going back to an earlier address drops
    that alias."""
    old = form.slug
    if new == old:
        return
    await db.execute(
        delete(FormSlugAlias).where(FormSlugAlias.form_id == form.id, FormSlugAlias.slug == new)
    )
    published = form.current_version_id is not None
    if keep_old and published and shape_problem(old) is None:
        exists = await db.scalar(select(FormSlugAlias.id).where(FormSlugAlias.slug == old))
        if exists is None:
            db.add(FormSlugAlias(form_id=form.id, slug=old))
    form.slug = new


def public_path(slug: str) -> str:
    return f"/{slug}"
