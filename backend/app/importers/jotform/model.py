"""What the Jotform readers produce and the converter consumes.

Both sources (a form's HTML and the Jotform API) are read into the same list of
:class:`JfQuestion` objects in form order, so one converter (``convert.py``) applies the type
mapping of DESIGN 13.2 to either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ItemStatus = Literal["imported", "changed", "skipped"]


@dataclass
class JfOption:
    label: str
    other: bool = False  # the "Other" choice with a free-text box


@dataclass
class JfQuestion:
    """One Jotform question (``control_*``) with what the importer understands of it."""

    qid: str
    type: str  # e.g. "control_textbox"
    label: str = ""
    # The ``q{qid}_{name}`` field name without the prefix; seeds the JustForms id.
    name: str = ""
    required: bool = False
    description: str = ""
    # Sub-labels by part (``first``, ``last``, ``addr_line1``...); ``main`` for one-input types.
    sublabels: dict[str, str] = field(default_factory=dict)
    options: list[JfOption] = field(default_factory=list)
    placeholder: str = ""
    half: bool = False
    # Heading text (``control_head``), collapse title, or text/HTML of ``control_text``.
    text: str = ""
    subtext: str = ""
    html: str = ""
    # Everything else: limits, formats, masks... (see the readers for keys).
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class JfCondition:
    """A Jotform condition as found in the source (``setConditions`` or API properties)."""

    raw: dict[str, Any]


@dataclass
class JfSource:
    title: str = ""
    questions: list[JfQuestion] = field(default_factory=list)
    conditions: list[JfCondition] = field(default_factory=list)
    # True when the source can carry conditions and none were found.
    conditions_checked: bool = True
    form_id: str | None = None
    cover_image: bool = False
    # The cover/header logo's address as found (may be relative), see ``logo.py``.
    logo_url: str | None = None
    # Form-level things found that JustForms does not import.
    extras: list[str] = field(default_factory=list)


@dataclass
class ReportItem:
    qid: str
    jotform_type: str
    label: str
    status: ItemStatus
    justforms_type: str | None = None
    element_id: str | None = None
    notes: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {
            "qid": self.qid,
            "jotformType": self.jotform_type,
            "label": self.label,
            "status": self.status,
            "justformsType": self.justforms_type,
            "elementId": self.element_id,
            "notes": self.notes,
        }


@dataclass
class ConditionReport:
    description: str
    status: Literal["imported", "not_imported"]
    reason: str = ""

    def as_json(self) -> dict[str, Any]:
        return {"description": self.description, "status": self.status, "reason": self.reason}


@dataclass
class ImportReport:
    items: list[ReportItem] = field(default_factory=list)
    conditions: list[ConditionReport] = field(default_factory=list)
    conditions_note: str = ""
    dropped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {"imported": 0, "changed": 0, "skipped": 0}
        for item in self.items:
            out[item.status] += 1
        return out

    def as_json(self) -> dict[str, Any]:
        return {
            "items": [i.as_json() for i in self.items],
            "counts": self.counts(),
            "conditions": [c.as_json() for c in self.conditions],
            "conditionsNote": self.conditions_note,
            "dropped": self.dropped,
            "notes": self.notes,
        }
