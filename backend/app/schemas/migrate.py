"""Ordered upgrades of stored form documents (docs/DESIGN.md section 4.1).

Published versions are immutable (their ``schema_hash`` was taken at publish time), so old
documents are upgraded **on read**: :class:`app.schemas.form.Form` runs :func:`upgrade_form`
before validating, and the ORM upgrades ``draft_schema`` / ``schema`` when rows load
(:mod:`app.models.form`). Each step is idempotent and never mutates its input.

* ``1`` → ``2``: forms no longer have a language. ``settings.language`` is dropped; every text
  now takes its direction from its content, so a Dhivehi form still renders right to left.
  In a former ``dv`` form, a text question whose keyboard was ``auto`` (on because of the form
  language) keeps the Thaana keyboard: it becomes ``thaana`` unless its label is Thaana,
  where ``auto`` already turns it on.
"""

from __future__ import annotations

import copy
from typing import Any

from app.schemas.direction import has_thaana

CURRENT = "2"


def _keep_thaana_keyboard(elements: list[Any]) -> None:
    for el in elements:
        if not isinstance(el, dict):
            continue
        if el.get("kind") == "field" and el.get("type") in ("short_text", "long_text"):
            script = el.get("inputScript", "auto")
            if script == "auto" and not has_thaana(str(el.get("label") or "")):
                el["inputScript"] = "thaana"
        children = el.get("elements")
        if isinstance(children, list):
            _keep_thaana_keyboard(children)


def _v1_to_v2(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    settings = out.get("settings")
    if isinstance(settings, dict) and "language" in settings:
        settings = dict(settings)
        language = settings.pop("language")
        out["settings"] = settings
        if language == "dv" and isinstance(out.get("pages"), list):
            out["pages"] = copy.deepcopy(out["pages"])
            for page in out["pages"]:
                if isinstance(page, dict) and isinstance(page.get("elements"), list):
                    _keep_thaana_keyboard(page["elements"])
    out["schemaVersion"] = "2"
    return out


def needs_upgrade(doc: Any) -> bool:
    if not isinstance(doc, dict):
        return False
    if doc.get("schemaVersion") in (None, "1"):
        settings = doc.get("settings")
        return doc.get("schemaVersion") == "1" or (
            isinstance(settings, dict) and "language" in settings
        )
    return False


def upgrade_form(doc: dict[str, Any]) -> dict[str, Any]:
    """Return ``doc`` upgraded to the current ``schemaVersion`` (``doc`` itself if current)."""
    if not needs_upgrade(doc):
        return doc
    return _v1_to_v2(doc)
