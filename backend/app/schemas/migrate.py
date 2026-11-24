"""Ordered upgrades of stored form documents (docs/DESIGN.md section 4.1).

Published versions are immutable (their ``schema_hash`` was taken at publish time), so old
documents are upgraded **on read**: :class:`app.schemas.form.Form` runs :func:`upgrade_form`
before validating, and the ORM upgrades ``draft_schema`` / ``schema`` when rows load
(:mod:`app.models.form`). Each step is idempotent and never mutates its input.

* ``1`` → ``2``: forms no longer have a language. ``settings.language`` is dropped; every text
  now takes its direction from its content, so a Dhivehi form still renders right to left.
  The app has no keyboard of its own any more (people type Dhivehi with their device's
  keyboard), so the former per-question keyboard setting ``inputScript`` is dropped from text
  questions, in any document that still carries it.
"""

from __future__ import annotations

import copy
from typing import Any

CURRENT = "2"

# Former per-question settings that no longer exist; dropped wherever they appear.
_RETIRED_FIELD_KEYS = ("inputScript",)


def _has_retired(elements: Any) -> bool:
    if not isinstance(elements, list):
        return False
    for el in elements:
        if not isinstance(el, dict):
            continue
        if any(k in el for k in _RETIRED_FIELD_KEYS):
            return True
        if _has_retired(el.get("elements")):
            return True
    return False


def _drop_retired(elements: list[Any]) -> None:
    for el in elements:
        if not isinstance(el, dict):
            continue
        for key in _RETIRED_FIELD_KEYS:
            el.pop(key, None)
        children = el.get("elements")
        if isinstance(children, list):
            _drop_retired(children)


def _pages_have_retired(doc: dict[str, Any]) -> bool:
    pages = doc.get("pages")
    return isinstance(pages, list) and any(
        isinstance(p, dict) and _has_retired(p.get("elements")) for p in pages
    )


def _v1_to_v2(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    settings = out.get("settings")
    if isinstance(settings, dict) and "language" in settings:
        settings = dict(settings)
        settings.pop("language")
        out["settings"] = settings
    if _pages_have_retired(out):
        out["pages"] = copy.deepcopy(out["pages"])
        for page in out["pages"]:
            if isinstance(page, dict) and isinstance(page.get("elements"), list):
                _drop_retired(page["elements"])
    out["schemaVersion"] = "2"
    return out


def needs_upgrade(doc: Any) -> bool:
    if not isinstance(doc, dict):
        return False
    version = doc.get("schemaVersion")
    if version == "1":
        return True
    if version is None:
        settings = doc.get("settings")
        if isinstance(settings, dict) and "language" in settings:
            return True
    # Unreleased v2 drafts may still carry a retired setting.
    return version in (None, "1", "2") and _pages_have_retired(doc)


def upgrade_form(doc: dict[str, Any]) -> dict[str, Any]:
    """Return ``doc`` upgraded to the current ``schemaVersion`` (``doc`` itself if current)."""
    if not needs_upgrade(doc):
        return doc
    return _v1_to_v2(doc)
