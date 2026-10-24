"""Answers as text for documents (PDF, Excel). Option labels and typed answers are the form's
content; the words added here ("Yes", "No", "No answer", "Signed") are system text, so English
for every form."""

from __future__ import annotations

import re
from typing import Any

from app.logic.index import FormIndex
from app.schemas.form import (
    FieldElement,
    FileField,
    Form,
    MultiChoiceField,
    PhoneField,
    SignatureField,
    SingleChoiceField,
    YesNoField,
)

WORDS = {"yes": "Yes", "no": "No", "no_answer": "No answer", "signed": "Signed"}

PHONE_960 = re.compile(r"^\+960([0-9]{3})([0-9]{4})$")


def format_phone(value: str) -> str:
    """A phone number grouped for reading: ``+960 777 1234`` for the 7-digit numbers of the
    renderer's default country code. Other numbers are printed as entered (grouping varies by
    country). Display only: stored answers, exports and search keep ``+9607771234``."""
    m = PHONE_960.match(value)
    return f"+960 {m.group(1)} {m.group(2)}" if m else value


def option_label(field: SingleChoiceField | MultiChoiceField, value: Any) -> str:
    for o in field.options:
        if o.value == value:
            return o.label
    return str(value)


def answer_text(
    field: FieldElement,
    value: Any,
    language: str,
    *,
    list_sep: str = ", ",
    display: bool = False,
) -> str:
    """One answer as plain text; empty string when unanswered. ``display`` (documents and
    emails people read) groups phone numbers; exports and search keep the stored form."""
    if value is None or value == "" or value == []:
        return ""
    w = WORDS
    if display and isinstance(field, PhoneField) and isinstance(value, str):
        return format_phone(value)
    if isinstance(field, YesNoField):
        return w["yes"] if value is True else w["no"] if value is False else str(value)
    if isinstance(field, SingleChoiceField):
        return option_label(field, value)
    if isinstance(field, MultiChoiceField):
        if not isinstance(value, list):
            return str(value)
        # Option labels are content: a Dhivehi list takes the Arabic comma.
        sep = "، " if language == "dv" and list_sep == ", " else list_sep
        return sep.join(option_label(field, v) for v in value)
    if isinstance(field, FileField):
        if not isinstance(value, list):
            return ""
        return list_sep.join(str(f.get("name", "file")) for f in value if isinstance(f, dict))
    if isinstance(field, SignatureField):
        return w["signed"]
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, dict | list):
        return str(value)
    return str(value)


def search_text(form: Form, data: dict[str, Any]) -> str:
    """Lower-cased text of the non-sensitive answers (top level and repeater rows)."""
    parts: list[str] = []
    language = form.settings.language
    for info in FormIndex.build(form).elements.values():
        el = info.element
        if info.kind != "field" or getattr(el, "sensitive", False):
            continue
        if isinstance(el, SignatureField):
            continue
        if info.repeater_id is None:
            values = [data.get(info.id)]
        else:
            rows = data.get(info.repeater_id)
            values = (
                [r.get(info.id) for r in rows if isinstance(r, dict)]
                if isinstance(rows, list)
                else []
            )
        for value in values:
            text = answer_text(el, value, language)  # type: ignore[arg-type]
            if text:
                parts.append(text.lower())
    return "\n".join(parts)[:100_000]


MASK = "••••"


def mask(text: str) -> str:
    return MASK + text[-3:] if text else ""


def mask_sensitive(form: Form, data: dict[str, Any]) -> dict[str, Any]:
    """A copy of ``data`` with sensitive answers masked (``••••567``), top level and in
    repeater rows. Unmasking is a separate, logged request (DESIGN 14.5)."""
    index = FormIndex.build(form)
    language = form.settings.language
    out = dict(data)
    for info in index.elements.values():
        el = info.element
        if info.kind != "field" or not getattr(el, "sensitive", False):
            continue
        if info.repeater_id is None:
            if info.id in out:
                out[info.id] = mask(answer_text(el, out[info.id], language))  # type: ignore[arg-type]
            continue
        rows = out.get(info.repeater_id)
        if isinstance(rows, list):
            out[info.repeater_id] = rows = [dict(r) if isinstance(r, dict) else r for r in rows]
            for r in rows:
                if isinstance(r, dict) and info.id in r:
                    r[info.id] = mask(answer_text(el, r[info.id], language))  # type: ignore[arg-type]
    return out
