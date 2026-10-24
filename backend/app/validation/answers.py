"""Server-side validation of submitted answers (DESIGN 5.4, 15; Phase 3).

Mirrors the public renderer's client rules (``frontend/src/renderer/validation.ts``) so a
respondent never sees the server reject something the form accepted, and a tampered client
cannot store answers the form would refuse. Both implementations return the same problem
codes and run the same shared cases in ``spec/validation/answers.json``.

``check_answer`` validates one visible answer; ``validate_submission`` evaluates the form's
logic, strips hidden answers and checks every visible question, including repeater rows.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import regex

from app.logic.engine import evaluate, is_missing
from app.logic.index import FormIndex
from app.schemas.form import (
    DateField,
    EmailField,
    FieldElement,
    FileField,
    Form,
    HiddenField,
    LongTextField,
    MultiChoiceField,
    NumberField,
    PhoneField,
    RatingField,
    RepeaterElement,
    ShortTextField,
    SignatureField,
    SingleChoiceField,
    TimeField,
    YesNoField,
)

EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
TIME = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
PHONE_MV = re.compile(r"^\+960[0-9]{7}$")
PHONE = re.compile(r"^\+[0-9]{6,15}$")
RELATIVE = re.compile(r"^today([+-][0-9]{1,4})?$")

# Caps for text without a maxLength, and for "Other" answers and hidden values.
SHORT_TEXT_CAP = 10_000
LONG_TEXT_CAP = 100_000
OTHER_CAP = 500
# Staff-written patterns run against public input: bound their run time.
PATTERN_TIMEOUT_S = 0.05


@dataclass(frozen=True)
class Problem:
    code: str
    params: dict[str, Any] = field(default_factory=dict)


def resolve_date_bound(bound: str | None, today: date) -> date | None:
    """``2026-01-01``, ``today``, ``today+30`` → a date."""
    if not bound:
        return None
    if DATE.match(bound):
        try:
            return date.fromisoformat(bound)
        except ValueError:
            return None
    m = RELATIVE.match(bound)
    if not m:
        return None
    return today + timedelta(days=int(m.group(1) or 0))


MAX_SAFE = 2**53 - 1  # JSON numbers both sides agree on (and RFC 8785 can hash)


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and abs(value) <= MAX_SAFE
    )


def _fmt_number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def _required_problem(field: FieldElement) -> Problem:
    if isinstance(field, MultiChoiceField):
        return Problem("required", {"n": max(1, field.min_selected or 1)})
    return Problem("required")


def check_answer(
    field: FieldElement,
    value: Any,
    required: bool,
    today: date,
    *,
    date_slack_days: int = 0,
) -> Problem | None:
    """Problem with one answer, or ``None``. ``today`` resolves relative date limits;
    ``date_slack_days`` widens them for respondents in other time zones."""
    if is_missing(value):
        return _required_problem(field) if required else None

    if isinstance(field, ShortTextField | LongTextField):
        if not isinstance(value, str):
            return Problem("invalid")
        cap = field.max_length or (
            SHORT_TEXT_CAP if isinstance(field, ShortTextField) else LONG_TEXT_CAP
        )
        if len(value) > cap:
            return Problem("too_long", {"max": cap})
        if isinstance(field, ShortTextField) and field.pattern:
            try:
                ok = regex.search(field.pattern, value, regex.ASCII, timeout=PATTERN_TIMEOUT_S)
            except regex.error:
                return None  # a broken pattern is a builder problem, not the respondent's
            except TimeoutError:
                ok = None
            if ok is None:
                return Problem("pattern")
        return None

    if isinstance(field, EmailField):
        if not isinstance(value, str) or len(value) > 320:
            return Problem("email")
        return None if EMAIL.match(value.strip()) else Problem("email")

    if isinstance(field, PhoneField):
        if not isinstance(value, str):
            return Problem("phone")
        if value.startswith("+960"):
            return None if PHONE_MV.match(value) else Problem("phone_mv")
        return None if PHONE.match(value) else Problem("phone")

    if isinstance(field, NumberField):
        if not _is_number(value):
            return Problem("number")
        if field.integer and not float(value).is_integer():
            return Problem("integer")
        lo, hi = field.min, field.max
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            if lo is not None and hi is not None:
                return Problem("between", {"min": _fmt_number(lo), "max": _fmt_number(hi)})
            if lo is not None:
                return Problem("at_least", {"min": _fmt_number(lo)})
            return Problem("at_most", {"max": _fmt_number(hi)})  # type: ignore[arg-type]
        return None

    if isinstance(field, DateField):
        if not isinstance(value, str) or not DATE.match(value):
            return Problem("date")
        try:
            day = date.fromisoformat(value)
        except ValueError:
            return Problem("date")
        first = resolve_date_bound(field.min_date, today)
        last = resolve_date_bound(field.max_date, today)
        slack = timedelta(days=date_slack_days)
        if first and field.min_date and field.min_date.startswith("today"):
            first -= slack
        if last and field.max_date and field.max_date.startswith("today"):
            last += slack
        if first and day < first:
            return Problem("date_from", {"date": first.isoformat()})
        if last and day > last:
            return Problem("date_to", {"date": last.isoformat()})
        return None

    if isinstance(field, TimeField):
        return None if isinstance(value, str) and TIME.match(value) else Problem("time")

    if isinstance(field, SingleChoiceField):
        if not isinstance(value, str):
            return Problem("option")
        if value in {o.value for o in field.options}:
            return None
        other_ok = field.allow_other and field.display != "dropdown" and len(value) <= OTHER_CAP
        return None if other_ok else Problem("option")

    if isinstance(field, MultiChoiceField):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return Problem("option")
        allowed = {o.value for o in field.options}
        others = [v for v in value if v not in allowed]
        if len(set(value)) != len(value) or (
            others and (not field.allow_other or len(others) > 1 or len(others[0]) > OTHER_CAP)
        ):
            return Problem("option")
        n = len(value)
        if field.min_selected is not None and n < field.min_selected:
            return Problem("choose_at_least", {"n": field.min_selected})
        if field.max_selected is not None and n > field.max_selected:
            return Problem("choose_at_most", {"n": field.max_selected})
        return None

    if isinstance(field, YesNoField):
        return None if isinstance(value, bool) else Problem("option")

    if isinstance(field, RatingField):
        ok = isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= field.max
        return None if ok else Problem("option")

    if isinstance(field, FileField):
        if not isinstance(value, list) or not all(
            isinstance(v, dict) and isinstance(v.get("fileId"), str) for v in value
        ):
            return Problem("file_invalid")
        if len(value) > field.max_files:
            return Problem("too_many_files", {"n": field.max_files})
        return None

    if isinstance(field, SignatureField):
        strokes = value.get("strokes") if isinstance(value, dict) else None
        return None if isinstance(strokes, list) and strokes else Problem("signature_invalid")

    if isinstance(field, HiddenField):
        ok = (isinstance(value, str) and len(value) <= SHORT_TEXT_CAP) or _is_number(value)
        return None if ok or isinstance(value, bool) else Problem("invalid")

    return None  # pragma: no cover - every field type is handled above


@dataclass
class Validation:
    data: dict[str, Any]  # visible answers only, repeaters padded to minRows
    errors: list[dict[str, Any]]


def _error(
    fid: str, problem: Problem, repeater: str | None = None, row: int | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {"field": fid, "code": problem.code}
    if problem.params:
        out["params"] = problem.params
    if repeater is not None:
        out.update(repeater=repeater, row=row)
    return out


def _has_nul(value: Any) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, list):
        return any(_has_nul(v) for v in value)
    if isinstance(value, dict):
        return any(_has_nul(k) or _has_nul(v) for k, v in value.items())
    return False


def pad_repeaters(form: Form, answers: dict[str, Any]) -> list[dict[str, Any]]:
    """Give repeaters at least ``minRows`` rows, as the renderer shows them; reject
    repeater values that are not lists of objects."""
    errors: list[dict[str, Any]] = []
    for info in FormIndex.build(form).elements.values():
        el = info.element
        if not isinstance(el, RepeaterElement) or info.repeater_id is not None:
            continue
        raw = answers.get(el.id)
        if raw is None:
            raw = []
        if not isinstance(raw, list) or not all(isinstance(r, dict) for r in raw):
            errors.append({"field": el.id, "code": "invalid"})
            continue
        if el.max_rows is not None and len(raw) > el.max_rows:
            errors.append(_error(el.id, Problem("rows_max", {"n": el.max_rows})))
            continue
        if len(raw) < el.min_rows or el.id in answers:
            answers[el.id] = [*raw, *({} for _ in range(el.min_rows - len(raw)))]
    return errors


def validate_submission(
    form: Form, answers: dict[str, Any], today: date, *, date_slack_days: int = 1
) -> Validation:
    """Evaluate logic, strip hidden answers and check every visible question."""
    answers = dict(answers)
    # PostgreSQL JSON cannot store NUL characters; no real answer contains one.
    errors: list[dict[str, Any]] = []
    for key in [k for k, v in answers.items() if _has_nul(k) or _has_nul(v)]:
        errors.append({"field": key, "code": "invalid"})
        del answers[key]
    errors += pad_repeaters(form, answers)
    ev = evaluate(form, answers)
    data = ev.stripped_answers
    index = FormIndex.build(form)
    required = set(ev.required)

    def field_of(fid: str) -> FieldElement | None:
        info = index.elements.get(fid)
        return info.element if info and info.kind == "field" else None  # type: ignore[return-value]

    for fid in ev.visible:
        f = field_of(fid)
        if f is None:
            continue
        problem = check_answer(
            f, data.get(fid), fid in required, today, date_slack_days=date_slack_days
        )
        if problem:
            errors.append(_error(fid, problem))
    for rep_id, rows in ev.rows.items():
        stripped_rows = data.get(rep_id)
        for i, row in enumerate(rows):
            values = stripped_rows[i] if isinstance(stripped_rows, list) else {}
            row_required = set(row.required)
            for fid in row.visible:
                f = field_of(fid)
                if f is None:
                    continue
                problem = check_answer(
                    f, values.get(fid), fid in row_required, today, date_slack_days=date_slack_days
                )
                if problem:
                    errors.append(_error(fid, problem, rep_id, i))
    return Validation(data=data, errors=errors)
