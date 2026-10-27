"""Submission list filters, shared by the table and the Excel export (DESIGN 15.1).

Filters: status, full-text search (non-sensitive answers only), a submitted-at range, a form
version, and per-question filters that compile to JSONB predicates on ``data`` (top-level
questions only):

``{"field": "age", "op": "gte", "value": 18}`` with ``op`` one of ``contains`` (text),
``eq`` / ``neq`` (any scalar), ``gte`` / ``lte`` (numbers; dates as YYYY-MM-DD),
``includes`` (multi choice), ``answered`` / ``unanswered``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Numeric, Select, and_, cast, func, not_, select

from app.insights.catalogue import Catalogue
from app.insights.dsl import Condition, Where, submission_where
from app.models import FormVersion, Submission, SubmissionStatus

FilterOp = Literal["contains", "eq", "neq", "gte", "lte", "includes", "answered", "unanswered"]
Scalar = str | int | float | bool


class FieldFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,62}$")]
    op: FilterOp
    value: Scalar | None = None


class ListFilters(BaseModel):
    """Filters as the studio sends them (query string or export request)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: SubmissionStatus | None = None
    q: Annotated[str, StringConstraints(max_length=200)] | None = None
    from_: date | None = Field(default=None, alias="from")
    to: date | None = None
    version: Annotated[int, Field(ge=1)] | None = None
    fields: Annotated[list[FieldFilter], Field(max_length=20)] = Field(default_factory=list)
    ids: Annotated[list[uuid.UUID], Field(max_length=10_000)] | None = None
    # Conditions in the submissions query language (app/insights/dsl.py): the "Show these
    # submissions" link of an answer and Insights' bars on repeater or "Other" answers.
    where: Annotated[list[Condition], Field(max_length=20)] = Field(default_factory=list)
    where_any: Annotated[list[Condition], Field(max_length=20)] = Field(
        default_factory=list, alias="whereAny"
    )
    # Column order (app/submissions/sort.py); exports use it for "in the current order".
    sort: Annotated[str, StringConstraints(pattern=r"^_?[a-z][a-z0-9_]{0,62}$")] | None = None
    dir: Literal["asc", "desc"] | None = None


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _field_clause(f: FieldFilter) -> Any:
    col = Submission.data
    item = col[f.field]
    text_item = col[f.field].astext
    if f.op == "answered":
        return col.has_key(f.field)
    if f.op == "unanswered":
        return not_(col.has_key(f.field))
    if f.value is None:
        raise ValueError(f"filter on {f.field!r} needs a value")
    if f.op == "contains":
        return and_(
            func.jsonb_typeof(item) == "string",
            text_item.ilike(f"%{_escape_like(str(f.value))}%", escape="\\"),
        )
    if f.op == "eq":
        return col.contains({f.field: f.value})
    if f.op == "neq":
        return not_(col.contains({f.field: f.value}))
    if f.op == "includes":
        return col.contains({f.field: [f.value]})
    # gte / lte: numbers compare as numbers, anything else (dates, times) as text.
    if isinstance(f.value, int | float) and not isinstance(f.value, bool):
        number = cast(text_item, Numeric)
        cond = number >= f.value if f.op == "gte" else number <= f.value
        return and_(func.jsonb_typeof(item) == "number", cond)
    value = str(f.value)
    cond = text_item >= value if f.op == "gte" else text_item <= value
    return and_(func.jsonb_typeof(item) == "string", cond)


def apply_filters(
    query: Select[Any],
    filters: ListFilters,
    tz: ZoneInfo,
    catalogue: Catalogue | None = None,
) -> Select[Any]:
    """Add ``filters`` to a query that selects from ``Submission`` (not deleted). Conditions
    in ``where`` need the form's ``catalogue``; a condition that does not fit the form
    raises ``ValueError``."""
    query = query.where(Submission.deleted_at.is_(None))
    if filters.ids is not None:
        query = query.where(Submission.id.in_(filters.ids))
    if filters.status is not None:
        query = query.where(Submission.status == filters.status)
    if filters.q:
        needle = _escape_like(filters.q.strip().lower())
        query = query.where(Submission.search_text.ilike(f"%{needle}%", escape="\\"))
    if filters.from_:
        start = datetime.combine(filters.from_, time.min, tzinfo=tz)
        query = query.where(Submission.submitted_at >= start)
    if filters.to:
        end = datetime.combine(filters.to + timedelta(days=1), time.min, tzinfo=tz)
        query = query.where(Submission.submitted_at < end)
    if filters.version is not None:
        query = query.where(
            Submission.form_version_id.in_(
                select(FormVersion.id).where(
                    FormVersion.form_id == Submission.form_id,
                    FormVersion.version == filters.version,
                )
            )
        )
    for f in filters.fields:
        query = query.where(_field_clause(f))
    if filters.where or filters.where_any:
        if catalogue is None:
            raise ValueError("conditions need the form's questions")
        where = Where(where=filters.where, where_any=filters.where_any)
        for clause in submission_where(catalogue, where, tz):
            query = query.where(clause)
    return query
