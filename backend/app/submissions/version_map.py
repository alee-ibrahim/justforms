"""Version field mappings (DESIGN 15.2): an older version's fixed questions read as the rows
of a repeater in a newer version.

A form that asked for "Contact 1", "Contact 2"... as separate questions and later turned them
into a repeater keeps its old submissions on the old version. A mapping, stored in the form's
settings as ``versionMappings``, tells the export which old questions make up each row::

    [{"repeater": "contacts",
      "rows": [{"contact_name": "contact1_name", "contact_phone": "contact1_phone"},
               {"contact_name": "contact2_name", "contact_phone": "contact2_phone"}]}]

Each row maps a question inside the repeater to a question of the older version. For a
submission whose version has no such repeater, the mapped rows are read from its answers in
order; a row whose questions are all empty is skipped. Answers are never changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.logic.index import FormIndex
from app.schemas.form import Form, RepeaterElement

MAX_MAPPINGS = 20
MAX_ROWS = 100
MAX_ROW_FIELDS = 50


@dataclass(frozen=True)
class VersionMapping:
    repeater: str
    rows: tuple[tuple[tuple[str, str], ...], ...]  # per row: (repeater question, old question)

    @property
    def sources(self) -> set[str]:
        return {src for row in self.rows for _child, src in row}

    def as_json(self) -> dict[str, Any]:
        return {"repeater": self.repeater, "rows": [dict(row) for row in self.rows]}


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def parse(raw: Any) -> list[VersionMapping]:
    """The mappings stored in a form's settings; anything malformed is ignored."""
    out: list[VersionMapping] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("repeater"), str):
            continue
        rows = []
        for row in item.get("rows") or []:
            if isinstance(row, dict):
                pairs = tuple((str(k), str(v)) for k, v in row.items() if isinstance(v, str) and v)
                if pairs:
                    rows.append(pairs)
        if rows:
            out.append(VersionMapping(item["repeater"], tuple(rows)))
    return out


def mapped_rows(mapping: VersionMapping, data: dict[str, Any]) -> list[dict[str, Any]]:
    """The repeater rows an older submission's fixed answers make, empty rows skipped."""
    out = []
    for row in mapping.rows:
        values = {child: data.get(src) for child, src in row}
        if any(not _empty(v) for v in values.values()):
            out.append({k: v for k, v in values.items() if not _empty(v)})
    return out


def has_repeater(form: Form, repeater_id: str) -> bool:
    info = FormIndex.build(form).elements.get(repeater_id)
    return info is not None and isinstance(info.element, RepeaterElement)


def problems(mappings: list[VersionMapping], current: Form, older: list[Form]) -> list[str]:
    """What is wrong with mappings about to be saved: ``current`` is the form with the
    repeaters (the draft), ``older`` its published versions."""
    out: list[str] = []
    index = FormIndex.build(current)
    old_fields: set[str] = set()
    for form in older:
        for fid, old in FormIndex.build(form).elements.items():
            if old.kind == "field" and old.repeater_id is None:
                old_fields.add(fid)
    seen_repeaters: set[str] = set()
    seen_sources: set[str] = set()
    for m in mappings:
        info = index.elements.get(m.repeater)
        if info is None or not isinstance(info.element, RepeaterElement):
            out.append(f"{m.repeater}: not a repeater of this form")
            continue
        if info.repeater_id is not None:
            out.append(f"{m.repeater}: repeaters inside repeaters cannot be mapped")
        if m.repeater in seen_repeaters:
            out.append(f"{m.repeater}: mapped twice")
        seen_repeaters.add(m.repeater)
        children = {
            fid
            for fid, child in index.elements.items()
            if child.repeater_id == m.repeater and child.kind == "field"
        }
        for row in m.rows:
            for child, src in row:
                if child not in children:
                    out.append(f"{m.repeater}: {child} is not a question in the repeater")
                if src not in old_fields:
                    out.append(f"{m.repeater}: {src} is not a question of a published version")
                elif src in index.elements and index.elements[src].repeater_id is None:
                    out.append(f"{m.repeater}: {src} is still a question of the form")
                if src in seen_sources:
                    out.append(f"{m.repeater}: {src} is mapped twice")
                seen_sources.add(src)
    return out
