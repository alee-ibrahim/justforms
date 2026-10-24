"""A form's own logo (docs/ux/FORM-THEME-SCREENS.md section 3).

A form may replace the organisation's logo with its own. It is not part of the inheritable
theme or the versioned schema: it lives in ``forms.settings["logo"]``::

    {"key": "form-logos/{form_id}/{sha16}.{png|svg}", "mime", "sha", "width", "height"}

Files are cleaned like branding logos (``app.branding.images.clean_image("logo", ...)``: PNG
decoded and re-encoded, SVG rebuilt from an allow-list) and stored through ``app.storage``.
They are served publicly, content-addressed, from
``/api/v1/public/form-logos/{form_id}/{sha16}.{ext}``. The key always lives under the form's
own id, so a copied settings blob can never point a form at another form's file.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.branding.images import CleanImage
from app.models import FormRecord
from app.storage import Storage

FORM_KEY = "logo"
NAME = re.compile(r"^[0-9a-f]{16}\.(png|svg)$")
MIMES = {"png": "image/png", "svg": "image/svg+xml"}


class BadName(ValueError):
    pass


@dataclass(frozen=True)
class FormLogo:
    form_id: uuid.UUID
    key: str
    mime: str
    sha: str
    width: int
    height: int

    @property
    def name(self) -> str:
        return self.key.rsplit("/", 1)[-1]

    @property
    def url(self) -> str:
        return logo_url(self.form_id, self.name)

    @property
    def is_png(self) -> bool:
        return self.mime == "image/png"

    def public(self) -> dict[str, Any]:
        return {"url": self.url, "mime": self.mime, "width": self.width, "height": self.height}


def storage_key(form_id: uuid.UUID, name: str) -> str:
    if not NAME.match(name):
        raise BadName(name)
    return f"form-logos/{form_id}/{name}"


def logo_url(form_id: uuid.UUID, name: str) -> str:
    return f"/api/v1/public/form-logos/{form_id}/{name}"


def mime_for(name: str) -> str:
    return MIMES[name.rsplit(".", 1)[-1]]


def form_logo(form: FormRecord | None) -> FormLogo | None:
    """The form's own logo, or None (it uses the organisation's)."""
    if form is None:
        return None
    raw = (form.settings or {}).get(FORM_KEY)
    if not isinstance(raw, dict):
        return None
    sha, mime = raw.get("sha"), raw.get("mime")
    if not isinstance(sha, str) or mime not in MIMES.values():
        return None
    ext = "png" if mime == "image/png" else "svg"
    try:
        key = storage_key(form.id, f"{sha[:16]}.{ext}")
    except BadName:
        return None
    if raw.get("key") != key:  # never another form's file
        return None
    try:
        width, height = int(raw.get("width", 0)), int(raw.get("height", 0))
    except (TypeError, ValueError):
        width = height = 0
    return FormLogo(form.id, key, str(mime), sha, width, height)


async def store(storage: Storage, form_id: uuid.UUID, img: CleanImage) -> dict[str, Any]:
    """Store a cleaned image as ``form_id``'s logo; returns the settings entry."""
    sha = hashlib.sha256(img.data).hexdigest()
    key = storage_key(form_id, f"{sha[:16]}.{img.ext}")
    await storage.put(key, img.data, content_type=img.mime)
    return {"key": key, "mime": img.mime, "sha": sha, "width": img.width, "height": img.height}


async def release(db: AsyncSession, storage: Storage, key: str) -> None:
    """Delete a logo object (after the change is committed) unless a form still uses it."""
    query = select(FormRecord.id).where(FormRecord.settings[FORM_KEY]["key"].astext == key)
    if await db.scalar(query.limit(1)) is not None:
        return
    await storage.delete(key)
