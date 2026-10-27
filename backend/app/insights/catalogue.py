"""The questions of a form across its published versions.

Submissions keep the version they were filled against, and question keys are frozen after
the first publish, so a key means the same question in every version. The catalogue lists
each question once, in the newest version's order, with questions only older versions asked
at the end ("(version N)" after the label, N being the last version that asked them).
Choice options are merged across versions (the newest label wins), so an option a later
version removed still has its label.

Version field mappings (``app/submissions/version_map.py``) make an older version's fixed
questions read as rows of a newer repeater; those questions are not listed on their own.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logic.index import FormIndex
from app.models import FormRecord, FormVersion
from app.schemas.form import (
    FieldElement,
    Form,
    MultiChoiceField,
    Option,
    RepeaterElement,
    SingleChoiceField,
)
from app.submissions import version_map

# Field types whose answers are free text typed by the respondent.
TEXT_TYPES = frozenset({"short_text", "long_text", "hidden", "time"})
# Contact details: sent to an AI provider only when the form allows AI to read answers.
CONTACT_TYPES = frozenset({"email", "phone"})
CHOICE_TYPES = frozenset({"single_choice", "multi_choice"})
NUMBER_TYPES = frozenset({"number", "rating"})
# Answers that are stored objects, not values: only "answered or not".
OBJECT_TYPES = frozenset({"file", "signature"})


@dataclass
class Question:
    key: str
    type: str
    label: str
    element: FieldElement
    repeater: str | None
    sensitive: bool
    options: list[Option]
    versions: list[int]
    # Asked by the newest published version.
    current: bool

    @property
    def option_values(self) -> list[str]:
        return [o.value for o in self.options]

    def option_label(self, value: Any) -> str | None:
        for o in self.options:
            if o.value == value:
                return o.label
        return None

    @property
    def allow_other(self) -> bool:
        return bool(getattr(self.element, "allow_other", False))


@dataclass
class Repeater:
    key: str
    label: str
    children: list[str]
    versions: list[int]
    current: bool
    # Rows read from an older version's fixed questions: per row (child key, old key) pairs.
    mapped_rows: list[list[tuple[str, str]]] = field(default_factory=list)
    # Versions (ids) without the repeater, whose rows come from the mapping.
    mapped_version_ids: list[uuid.UUID] = field(default_factory=list)


@dataclass
class Catalogue:
    language: str
    questions: dict[str, Question]
    repeaters: dict[str, Repeater]
    # version number -> version id, oldest first
    version_ids: dict[int, uuid.UUID]
    # Older questions read as repeater rows (not listed on their own).
    mapped_sources: set[str] = field(default_factory=set)

    def question(self, key: str) -> Question | None:
        return self.questions.get(key)

    def top_level(self) -> list[Question]:
        return [q for q in self.questions.values() if q.repeater is None]

    def children(self, repeater: str) -> list[Question]:
        rep = self.repeaters.get(repeater)
        return [self.questions[k] for k in rep.children if k in self.questions] if rep else []

    def for_version(self, number: int | None) -> Catalogue:
        """Only the questions (and repeaters) a version asked, or mapped rows it fills."""
        if number is None:
            return self
        questions = {
            k: q
            for k, q in self.questions.items()
            if number in q.versions
            or (q.repeater is not None and self._mapped_in(q.repeater, number))
        }
        repeaters = {
            k: r
            for k, r in self.repeaters.items()
            if number in r.versions or self._mapped_in(k, number)
        }
        return Catalogue(
            self.language, questions, repeaters, self.version_ids, set(self.mapped_sources)
        )

    def _mapped_in(self, repeater: str, number: int) -> bool:
        rep = self.repeaters.get(repeater)
        vid = self.version_ids.get(number)
        return bool(rep and rep.mapped_rows and vid in rep.mapped_version_ids)


def _leaf_fields(elements: list[Any]) -> list[FieldElement]:
    out: list[FieldElement] = []
    for el in elements:
        if getattr(el, "kind", None) == "section":
            out.extend(_leaf_fields(el.elements))
        elif getattr(el, "kind", None) == "field":
            out.append(el)
    return out


def build(
    versions: list[tuple[int, uuid.UUID, Form]],
    mappings_raw: Any = None,
) -> Catalogue:
    """``versions``: (number, id, schema) of every published version, any order."""
    ordered = sorted(versions, key=lambda v: v[0])
    newest = ordered[-1][0] if ordered else 0
    language = ordered[-1][2].settings.language if ordered else "en"
    questions: dict[str, Question] = {}
    repeaters: dict[str, Repeater] = {}
    for number, _vid, form in reversed(ordered):
        index = FormIndex.build(form)
        for info in index.elements.values():
            el = info.element
            if isinstance(el, RepeaterElement):
                rep = repeaters.get(el.id)
                if rep is None:
                    label = el.label if number == newest else f"{el.label} (version {number})"
                    rep = repeaters[el.id] = Repeater(el.id, label, [], [], number == newest)
                rep.versions.append(number)
                for child in _leaf_fields(el.elements):
                    if child.id not in rep.children:
                        rep.children.append(child.id)
                continue
            if info.kind != "field":
                continue
            fel: FieldElement = el  # type: ignore[assignment]
            q = questions.get(info.id)
            if q is None:
                label = fel.label if number == newest else f"{fel.label} (version {number})"
                q = questions[info.id] = Question(
                    key=info.id,
                    type=fel.type,
                    label=label,
                    element=fel,
                    repeater=info.repeater_id,
                    sensitive=fel.sensitive,
                    options=[],
                    versions=[],
                    current=number == newest,
                )
            q.versions.append(number)
            if isinstance(fel, SingleChoiceField | MultiChoiceField):
                known = {o.value for o in q.options}
                q.options.extend(o for o in fel.options if o.value not in known)
            # Sensitive in any version stays sensitive.
            q.sensitive = q.sensitive or fel.sensitive
    for q in questions.values():
        q.versions.sort()
    for r in repeaters.values():
        r.versions.sort()

    mapped_sources: set[str] = set()
    version_ids = {n: vid for n, vid, _ in ordered}
    for m in version_map.parse(mappings_raw):
        rep = repeaters.get(m.repeater)
        if rep is None:
            continue
        rows = [[(c, s) for c, s in row if c in rep.children] for row in m.rows]
        rep.mapped_rows = [r for r in rows if r]
        rep.mapped_version_ids = [
            vid for n, vid in version_ids.items() if n not in set(rep.versions)
        ]
        mapped_sources |= m.sources
    for src in mapped_sources:
        q = questions.get(src)
        if q is not None and q.repeater is None and not q.current:
            del questions[src]
    return Catalogue(language, questions, repeaters, version_ids, mapped_sources)


def outline(
    cat: Catalogue, *, text_allowed: bool, sensitive_readable: bool = False
) -> list[dict[str, Any]]:
    """The questions as the AI sees them: key, type, label, options, repeater, and what it
    may do with each. ``text_allowed``: the form allows AI to read answers (text and contact
    details); ``sensitive_readable``: so may sensitive answers be read."""
    out: list[dict[str, Any]] = []

    def entry(q: Question) -> dict[str, Any]:
        e: dict[str, Any] = {"key": q.key, "type": q.type, "label": q.label}
        if q.options:
            e["options"] = [{"value": o.value, "label": o.label} for o in q.options]
            if q.allow_other:
                e["allowOther"] = True
        if len(cat.version_ids) > 1:
            e["versions"] = q.versions
        if q.sensitive:
            e["note"] = (
                "sensitive: answered/unanswered counts in query_submissions; read_answers and"
                " list_submissions return its answers"
                if sensitive_readable
                else "sensitive: answered/unanswered counts only; you never see its answers"
                " (list_submissions shows them to the person)"
            )
        elif q.type in OBJECT_TYPES:
            e["note"] = "file or signature: answered/unanswered only (never names or content)"
        elif q.type in CONTACT_TYPES and not text_allowed:
            e["note"] = (
                "contact detail: filter and count only, you never see the values;"
                " list_submissions shows them to the person"
            )
        elif q.type in TEXT_TYPES and not text_allowed:
            e["note"] = (
                "free text: filter (contains) and count only; reading answers is off;"
                " list_submissions shows the answers to the person"
            )
        return e

    for q in cat.top_level():
        out.append(entry(q))
    for rep in cat.repeaters.values():
        r: dict[str, Any] = {
            "key": rep.key,
            "type": "repeater",
            "label": rep.label,
            "questions": [entry(c) for c in cat.children(rep.key)],
        }
        if rep.mapped_rows:
            r["note"] = "older versions' fixed questions are read as rows of this repeater"
        out.append(r)
    return out


async def load(db: AsyncSession, form: FormRecord) -> Catalogue:
    """The catalogue of ``form``'s published versions (empty when never published)."""
    rows = (
        await db.execute(
            select(FormVersion.version, FormVersion.id, FormVersion.schema).where(
                FormVersion.form_id == form.id
            )
        )
    ).all()
    versions = [(n, vid, Form.model_validate(sch)) for n, vid, sch in rows]
    return build(versions, (form.settings or {}).get("versionMappings"))
