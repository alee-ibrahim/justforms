"""Sorting the submissions table (DESIGN 15.1).

``sort`` is a column key: ``_seq`` (reference number), ``_submitted``, ``_status``,
``_approval`` (approval step), ``_respondent`` (respondent email), or the key of a top-level
question in the form's catalogue. Anything else is refused, so no client text reaches SQL.

Answers sort by their type: text alphabetically with the database's ICU root collation when it
has one (Unicode collation; Thaana sorts in its alphabet order, which is its code point
order), numbers and ratings numerically, dates and times chronologically (they are stored as
ISO text), choices by option order (answers typed in "Other" after the options, then by
text), multiple choices by their first option in option order, phone numbers by their digits,
yes/no as No then Yes. Empty answers always come last, in both directions. Every order ends
with the submission id (descending) so pages never repeat or skip a row.
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import (
    ARRAY,
    Boolean,
    Numeric,
    Text,
    case,
    cast,
    func,
    literal,
    null,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.insights.catalogue import OBJECT_TYPES, Catalogue
from app.models import ApprovalState, Submission, SubmissionStatus

SortDir = Literal["asc", "desc"]
META_KEYS = frozenset({"_seq", "_submitted", "_status", "_approval", "_respondent"})
STATUS_ORDER = [
    SubmissionStatus.NEW,
    SubmissionStatus.IN_REVIEW,
    SubmissionStatus.APPROVED,
    SubmissionStatus.REJECTED,
]
APPROVAL_ORDER = [
    ApprovalState.PENDING,
    ApprovalState.APPROVED,
    ApprovalState.REJECTED,
    ApprovalState.STOPPED,
]
COLLATION = "und-x-icu"

_collation: bool | None = None


class SortError(ValueError):
    """The sort key is not a column of this form."""


async def has_icu(db: AsyncSession) -> bool:
    """Whether the database has the ICU root collation (cached per process)."""
    global _collation
    if _collation is None:
        found = await db.scalar(
            text("SELECT 1 FROM pg_collation WHERE collname = :name").bindparams(name=COLLATION)
        )
        _collation = found is not None
    return _collation


def is_default(sort: str | None, direction: SortDir | None) -> bool:
    """No sort, or newest first: the list keeps its reference-number cursor."""
    return sort is None or (sort in ("_seq", "_submitted") and direction != "asc")


def _text(expr: Any, icu: bool) -> Any:
    value = func.nullif(expr, "")
    return value.collate(COLLATION) if icu else value


def _position(values: list[str], expr: Any) -> Any:
    """1-based position of ``expr`` among ``values``; answers outside them go after."""
    if not values:
        return literal(1)
    arr = cast(literal(values, ARRAY(Text)), ARRAY(Text))
    return func.coalesce(func.array_position(arr, expr), len(values) + 1)


def _answer_keys(q_type: str, key: str, options: list[str], icu: bool) -> list[Any]:
    data = Submission.data
    item = data[key]
    raw = item.astext
    kind = func.jsonb_typeof(item)
    if q_type in ("number", "rating"):
        return [case((kind == "number", cast(raw, Numeric)), else_=null())]
    if q_type == "yes_no":
        return [case((kind == "boolean", cast(raw, Boolean)), else_=null())]
    if q_type == "phone":
        digits = func.nullif(func.regexp_replace(raw, r"\D", "", "g"), "")
        return [case((kind == "string", cast(digits, Numeric)), else_=null())]
    if q_type == "single_choice":
        answered = (kind == "string") & (raw != "")
        return [
            case((answered, _position(options, raw)), else_=null()),
            case((answered, _text(raw, icu)), else_=null()),
        ]
    if q_type == "multi_choice":
        elems = func.jsonb_array_elements_text(item).table_valued("value").alias("opt")
        first = (
            select(func.min(_position(options, elems.c.value))).select_from(elems).scalar_subquery()
        )
        has_any = (kind == "array") & (func.jsonb_array_length(case((kind == "array", item))) > 0)
        return [case((has_any, first), else_=null())]
    # Text, email, hidden, date (YYYY-MM-DD), time (HH:MM): text order.
    return [case((kind == "string", _text(raw, icu)), else_=null())]


def order_by(
    sort: str | None,
    direction: SortDir | None,
    cat: Catalogue | None,
    *,
    icu: bool = True,
) -> list[Any]:
    """ORDER BY clauses for a column key; raises :class:`SortError` for unknown keys."""
    desc = direction != "asc"
    if sort is None or sort == "_seq":
        keys: list[Any] = [Submission.seq]
    elif sort == "_submitted":
        keys = [Submission.submitted_at]
    elif sort == "_status":
        keys = [
            case(
                *((Submission.status == s, i) for i, s in enumerate(STATUS_ORDER)),
                else_=len(STATUS_ORDER),
            )
        ]
    elif sort == "_approval":
        keys = [
            case(
                *((Submission.approval_state == s, i) for i, s in enumerate(APPROVAL_ORDER)),
                else_=null(),
            ),
            Submission.approval_step,
        ]
    elif sort == "_respondent":
        keys = [_text(func.lower(Submission.respondent_email), icu)]
    else:
        q = cat.question(sort) if cat is not None else None
        if q is None or q.repeater is not None or q.type in OBJECT_TYPES:
            raise SortError(sort)
        keys = _answer_keys(q.type, q.key, q.option_values, icu)
    clauses = [(k.desc() if desc else k.asc()).nulls_last() for k in keys]
    return [*clauses, Submission.id.desc()]
