"""A small, safe query language over a form's submissions.

The AI's ``query_submissions`` tool, the Insights page and the "Show these submissions" link
all use it. A query is JSON (validated by the Pydantic models below) and is compiled to
SQLAlchemy Core over the JSONB answers: question keys and values only ever reach the
database as bound parameters, and every key must be a question of the form's catalogue, so
nothing the model writes becomes SQL.

    {"where": [{"field": "interests", "op": "includes_any", "values": ["disability"]}],
     "groupBy": [{"field": "island"}],
     "aggregates": [{"op": "count"}, {"op": "avg", "field": "age"}],
     "listLimit": 10, "listFields": ["org_name"]}

Conditions in ``where`` must all hold; at least one in ``whereAny`` must hold (when given).
Besides question keys, ``_status``, ``_submitted`` (the date it arrived, ``YYYY-MM-DD``) and
``_version`` describe the submission itself.

Repeaters: a condition on a question inside a repeater holds when at least one row matches.
When a group, an aggregate or a listed question is inside a repeater, the query counts rows of
that repeater instead of submissions (conditions on that repeater then apply to the row
itself). Older versions' fixed questions mapped onto a repeater (version field mappings) are
read as rows too.

Who sees what is decided by a ``Policy``: sensitive questions only ever give answered /
unanswered counts; for the AI, unless the form allows AI to read answers, contact details
(email, phone) and free-text answers can be filtered and counted but are never grouped,
listed or returned.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel
from sqlalchemy import (
    BigInteger,
    Boolean,
    ColumnElement,
    Numeric,
    Select,
    String,
    Text,
    and_,
    case,
    cast,
    column,
    exists,
    false,
    func,
    literal,
    literal_column,
    not_,
    or_,
    select,
    true,
    type_coerce,
    union_all,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.answers import answer_text
from app.insights.catalogue import (
    CHOICE_TYPES,
    CONTACT_TYPES,
    NUMBER_TYPES,
    OBJECT_TYPES,
    TEXT_TYPES,
    Catalogue,
    Question,
    Repeater,
)
from app.models import Submission, SubmissionStatus
from app.submissions import version_map

META_STATUS = "_status"
META_SUBMITTED = "_submitted"
META_VERSION = "_version"
META_FIELDS = (META_STATUS, META_SUBMITTED, META_VERSION)

# Group key of answers that are not one of the options (Unicode noncharacters, never typed).
OTHER = "\ufdd0other\ufdd0"

Op = Literal[
    "eq",
    "neq",
    "in",
    "not_in",
    "contains",
    "gt",
    "gte",
    "lt",
    "lte",
    "between",
    "includes_any",
    "includes_all",
    "excludes",
    "is_other",
    "answered",
    "unanswered",
]
Scalar = bool | int | float | str
NO_VALUE_OPS = frozenset({"answered", "unanswered", "is_other"})
ONE_VALUE_OPS = frozenset({"contains", "gt", "gte", "lt", "lte"})
Key = Annotated[
    str, StringConstraints(pattern=r"^(_status|_submitted|_version|[a-z][a-z0-9_]{0,62})$")
]
DATEISH = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
MAX_GROUPS = 100
MAX_LIST = 50
LIST_TEXT_CHARS = 300


class QueryError(ValueError):
    """The query does not fit the form (unknown key, wrong operator, not allowed)."""


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", alias_generator=to_camel, validate_by_name=True, validate_by_alias=True
    )


class Condition(_Model):
    """One condition on a question (by key) or on the submission (_status, _submitted,
    _version)."""

    field: Key = Field(description="Question key, or _status, _submitted, _version")
    op: Op = Field(
        description=(
            "eq/neq/in/not_in: equals (choices: option value or label; yes_no: true/false;"
            " text: case-insensitive). contains: text contains. gt/gte/lt/lte/between: numbers,"
            " dates (YYYY, YYYY-MM or YYYY-MM-DD). includes_any/includes_all/excludes: options"
            " ticked in a multi choice. is_other: answered with an 'Other' text."
            " answered/unanswered."
        )
    )
    value: Scalar | None = Field(default=None, description="The value for one-value operators")
    values: list[Scalar] | None = Field(
        default=None,
        max_length=100,
        description="Values for in, not_in, includes_any, includes_all, excludes, between [lo, hi]",
    )

    @model_validator(mode="after")
    def _value_count(self) -> Condition:
        """The number of values fits the operator (the compiler relies on it)."""
        if self.op in NO_VALUE_OPS:
            return self
        n = len(self.values) if self.values is not None else (0 if self.value is None else 1)
        if self.values is not None and self.value is not None:
            raise ValueError("give value or values, not both")
        if self.op in ONE_VALUE_OPS and n != 1:
            raise ValueError(f"{self.op} needs exactly one value")
        if self.op == "between" and n != 2:
            raise ValueError("between needs two values: [low, high]")
        if n == 0:
            raise ValueError(f"{self.op} needs a value")
        return self


class GroupBy(_Model):
    field: Key
    bucket: Literal["value", "day", "month", "year"] = Field(
        default="value", description="Dates and _submitted: day, month or year"
    )


class Aggregate(_Model):
    op: Literal["count", "sum", "avg", "min", "max", "median", "distinct"]
    field: Key | None = Field(default=None, description="Not needed for count")


class Query(_Model):
    """Count, group and aggregate the form's submissions (or the rows of one repeater)."""

    where: list[Condition] = Field(default_factory=list, max_length=20)
    where_any: list[Condition] = Field(
        default_factory=list, max_length=20, description="At least one of these must hold"
    )
    group_by: list[GroupBy] = Field(default_factory=list, max_length=2)
    aggregates: list[Aggregate] = Field(
        default_factory=list, max_length=8, description="Default: count"
    )
    list_limit: int = Field(
        default=0, ge=0, le=MAX_LIST, description="Also list up to this many matching submissions"
    )
    list_fields: list[Key] = Field(
        default_factory=list, max_length=10, description="Answers to show for listed submissions"
    )
    limit: int = Field(default=30, ge=1, le=MAX_GROUPS, description="Most groups returned")
    sort: Literal["count", "key"] = "count"


class Where(_Model):
    """Conditions only (the "Show these submissions" link, list filters)."""

    where: list[Condition] = Field(default_factory=list, max_length=20)
    where_any: list[Condition] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True)
class Policy:
    """``for_ai``: the caller is the AI. ``text_allowed``: free text answers may be grouped and
    listed; ``contact_allowed``: so may contact details (email, phone). People: always; the
    AI: only when the form allows AI to read answers. Sensitive questions only ever give
    answered/unanswered counts here, for everyone (their values reach the AI only through
    ``read_answers``, see ``app.insights.ask``)."""

    for_ai: bool = False
    text_allowed: bool = True
    contact_allowed: bool = True


PEOPLE = Policy()


# --------------------------------------------------------------------------------------
# JSONB helpers
# --------------------------------------------------------------------------------------


# The path that reads a JSONB scalar as text (a constant, never user input).
_SCALAR: ColumnElement[Any] = literal_column("'{}'::text[]")


def _jsonb(text: str) -> ColumnElement[Any]:
    return cast(literal(text, String), JSONB)


def jget(base: Any, key: str) -> ColumnElement[Any]:
    return type_coerce(base, JSONB)[key]


def answered(x: ColumnElement[Any]) -> ColumnElement[bool]:
    return and_(
        func.coalesce(func.jsonb_typeof(x), "null") != "null",
        x != _jsonb('""'),
        x != _jsonb("[]"),
        x != _jsonb("{}"),
    )


def _as_array(x: ColumnElement[Any]) -> ColumnElement[Any]:
    return case((func.jsonb_typeof(x) == "array", x), else_=_jsonb("[]"))


def _number(x: ColumnElement[Any]) -> ColumnElement[Any]:
    return case(
        (func.jsonb_typeof(x) == "number", cast(x.op("#>>", return_type=Text)(_SCALAR), Numeric))
    )


def _text(x: ColumnElement[Any]) -> ColumnElement[Any]:
    return case((func.jsonb_typeof(x) == "string", x.op("#>>", return_type=Text)(_SCALAR)))


_NON_WORD = re.compile(r"[\W_]+")


def _words(text: str) -> str:
    """Lower-case words separated by single spaces, padded so ``in`` matches whole words."""
    joined = _NON_WORD.sub(" ", text.casefold()).strip()
    return f" {joined} " if joined else ""


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# --------------------------------------------------------------------------------------
# Compiling
# --------------------------------------------------------------------------------------


class Compiler:
    def __init__(self, cat: Catalogue, policy: Policy, tz: ZoneInfo) -> None:
        self.cat = cat
        self.policy = policy
        self.tz = tz
        self.notes: list[str] = []

    # -- what may be used --------------------------------------------------------------

    def question(self, key: str) -> Question:
        q = self.cat.question(key)
        if q is None:
            raise QueryError(f"{key!r} is not a question of this form")
        return q

    def _check_values_use(self, q: Question, what: str) -> None:
        """Grouping, listing, distinct and value aggregates reveal answers."""
        if q.sensitive:
            raise QueryError(f"{q.key!r} is sensitive: only answered/unanswered counts")
        if q.type in OBJECT_TYPES:
            raise QueryError(f"{q.key!r} is a {q.type}: only answered/unanswered counts")
        if q.type in CONTACT_TYPES and not self.policy.contact_allowed:
            raise QueryError(
                f"{q.key!r} is a contact detail and reading answers is off for this form: it"
                f" can't be {what} here (list_submissions shows it to the person instead)"
            )
        if q.type in TEXT_TYPES and not self.policy.text_allowed:
            raise QueryError(
                f"{q.key!r} is free text and reading answers is off for this form: it can't"
                f" be {what} (filter it with contains and count instead)"
            )

    # -- repeater rows -------------------------------------------------------------------

    def rows_lateral(self, rep: Repeater, name: str) -> Any:
        """(value jsonb, idx) for every row of ``rep`` in the current submission, including
        rows read from mapped older questions."""
        tv = (
            func.jsonb_array_elements(_as_array(jget(Submission.data, rep.key)))
            .table_valued(column("value", JSONB), with_ordinality="idx", name=f"{name}_a")
            .render_derived()
        )
        parts: list[Select[Any]] = [
            select(tv.c.value.label("value"), cast(tv.c.idx, BigInteger).label("idx")).correlate(
                Submission
            )
        ]
        if rep.mapped_rows and rep.mapped_version_ids:
            for i, row in enumerate(rep.mapped_rows):
                args: list[Any] = []
                for child, src in row:
                    args += [literal(child, String), jget(Submission.data, src)]
                parts.append(
                    select(
                        func.jsonb_build_object(*args).label("value"),
                        literal(-(i + 1), BigInteger).label("idx"),
                    )
                    .correlate(Submission)
                    .where(
                        Submission.form_version_id.in_(rep.mapped_version_ids),
                        or_(*(answered(jget(Submission.data, src)) for _c, src in row)),
                    )
                )
        body = parts[0] if len(parts) == 1 else union_all(*parts)
        return body.subquery().lateral(name)

    # -- conditions ----------------------------------------------------------------------

    def _values(self, c: Condition) -> list[Scalar]:
        if c.values is not None:
            return list(c.values)
        return [] if c.value is None else [c.value]

    def _one(self, c: Condition) -> Scalar:
        vals = self._values(c)
        if len(vals) != 1:
            raise QueryError(f"{c.field}: {c.op} needs exactly one value")
        return vals[0]

    def _choice_value(self, q: Question, v: Scalar) -> str:
        s = str(v).strip()
        if s in q.option_values:
            return s
        for o in q.options:
            if o.label.strip().casefold() == s.casefold():
                return o.value
        # Loose wording ("human rights" for "HUMAN RIGHTS AND GENDER"): one option whose label
        # or value contains the words is taken (with a note); several are an error naming them.
        words = _words(s)
        hits = (
            [o for o in q.options if words in _words(o.label) or words in _words(o.value)]
            if words
            else []
        )
        if len(hits) == 1:
            self.notes.append(f"{s!r} was matched to the option {hits[0].label!r} of {q.key!r}")
            return hits[0].value
        if len(hits) > 1:
            listed = "; ".join(f"{o.value} ({o.label})" for o in hits[:10])
            raise QueryError(
                f"{s!r} matches several options of {q.key!r}: {listed}. Use their values"
                " (several values count submissions with any of them)."
            )
        self.notes.append(f"{s!r} is not an option of {q.key!r}; matched as typed")
        return s

    def _bool(self, q: Question, v: Scalar) -> bool:
        if isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in ("true", "yes", "1"):
            return True
        if s in ("false", "no", "0"):
            return False
        raise QueryError(f"{q.key}: use true or false")

    def _num(self, key: str, v: Scalar) -> float:
        if isinstance(v, bool):
            raise QueryError(f"{key}: expected a number")
        try:
            return float(v)
        except ValueError:
            raise QueryError(f"{key}: expected a number, got {v!r}") from None

    def _date(self, key: str, v: Scalar) -> str:
        s = str(v).strip()
        if not DATEISH.match(s):
            raise QueryError(f"{key}: dates are YYYY, YYYY-MM or YYYY-MM-DD, got {s!r}")
        return s

    def _date_cmp(self, text: ColumnElement[Any], op: str, vals: list[str]) -> ColumnElement[bool]:
        def pre(v: str) -> ColumnElement[Any]:
            return func.substr(text, 1, len(v))

        if op in ("eq", "in"):
            return or_(*(pre(v) == v for v in vals))
        if op in ("neq", "not_in"):
            return and_(text.isnot(None), *(pre(v) != v for v in vals))
        v = vals[0]
        if op == "gt":
            return pre(v) > v
        if op == "gte":
            return pre(v) >= v
        if op == "lt":
            return pre(v) < v
        if op == "lte":
            return pre(v) <= v
        if op == "between":
            if len(vals) != 2:
                raise QueryError("between needs two values")
            return and_(pre(vals[0]) >= vals[0], pre(vals[1]) <= vals[1])
        raise QueryError(f"{op} does not apply to dates")

    def _meta(self, c: Condition) -> ColumnElement[bool]:
        vals = self._values(c)
        if c.field == META_STATUS:
            allowed = {s.value for s in SubmissionStatus}
            for v in vals:
                if str(v) not in allowed:
                    raise QueryError(f"_status is one of {sorted(allowed)}")
            statuses = [SubmissionStatus(str(v)) for v in vals]
            if c.op in ("eq", "in"):
                return Submission.status.in_(statuses)
            if c.op in ("neq", "not_in"):
                return Submission.status.notin_(statuses)
            raise QueryError("_status takes eq, neq, in or not_in")
        if c.field == META_SUBMITTED:
            text = func.to_char(func.timezone(str(self.tz), Submission.submitted_at), "YYYY-MM-DD")
            return self._date_cmp(text, c.op, [self._date(c.field, v) for v in vals])
        # _version
        numbers = [int(self._num(c.field, v)) for v in vals]
        known = self.cat.version_ids
        if c.op in ("eq", "in", "neq", "not_in"):
            ids = [known[n] for n in numbers if n in known]
            clause = Submission.form_version_id.in_(ids) if ids else false()
            return clause if c.op in ("eq", "in") else not_(clause)
        if c.op in ("gt", "gte", "lt", "lte", "between"):
            if c.op == "between" and len(numbers) != 2:
                raise QueryError("between needs two values")
            lo, hi = (numbers[0], numbers[1]) if c.op == "between" else (None, None)
            n = numbers[0] if numbers else 0
            pick = {
                "gt": lambda v: v > n,
                "gte": lambda v: v >= n,
                "lt": lambda v: v < n,
                "lte": lambda v: v <= n,
                "between": lambda v: lo is not None and hi is not None and lo <= v <= hi,
            }[c.op]
            ids = [vid for num, vid in known.items() if pick(num)]
            return Submission.form_version_id.in_(ids) if ids else false()
        raise QueryError(f"_version does not take {c.op}")

    def value_condition(
        self, q: Question, x: ColumnElement[Any], c: Condition
    ) -> ColumnElement[bool]:
        """``c`` on the answer ``x`` (jsonb) of question ``q``."""
        op = c.op
        if op == "answered":
            return answered(x)
        if op == "unanswered":
            return not_(answered(x))
        if q.sensitive or q.type in OBJECT_TYPES:
            raise QueryError(f"{q.key!r}: only answered/unanswered")
        t = q.type
        if t in CHOICE_TYPES:
            if op == "is_other":
                if t == "single_choice":
                    return and_(answered(x), _text(x).notin_(q.option_values or [""]))
                el = func.jsonb_array_elements_text(_as_array(x)).table_valued("value")
                return exists(
                    select(literal(1))
                    .select_from(el)
                    .where(el.c.value.notin_(q.option_values or [""]))
                )
            vals = [self._choice_value(q, v) for v in self._values(c)]
            if not vals and op not in ("answered", "unanswered"):
                raise QueryError(f"{q.key}: {op} needs a value")
            if t == "single_choice":
                txt = _text(x)
                if op in ("eq", "in", "includes_any", "includes_all"):
                    if op == "includes_all" and len(set(vals)) > 1:
                        return false()
                    return txt.in_(vals)
                if op in ("neq", "not_in", "excludes"):
                    return and_(answered(x), txt.notin_(vals))
                if op == "contains":
                    return txt.ilike(f"%{_escape_like(str(vals[0]))}%", escape="\\")
                raise QueryError(f"{q.key}: {op} does not apply to a single choice")
            arr = _as_array(x)
            values = cast(literal(vals, ARRAY(String)), ARRAY(String))
            if op in ("eq", "includes_any", "in", "contains"):
                return arr.op("?|", return_type=Boolean)(values)
            if op == "includes_all":
                return arr.op("?&", return_type=Boolean)(values)
            if op in ("neq", "not_in", "excludes"):
                return and_(answered(x), not_(arr.op("?|", return_type=Boolean)(values)))
            raise QueryError(f"{q.key}: {op} does not apply to a multi choice")
        if t == "yes_no":
            if op in ("eq", "neq"):
                v = self._bool(q, self._one(c))
                clause = x == _jsonb("true" if v else "false")
                return clause if op == "eq" else and_(answered(x), not_(clause))
            raise QueryError(f"{q.key}: yes/no takes eq or neq")
        if t in NUMBER_TYPES:
            num = _number(x)
            vals_n = [self._num(q.key, v) for v in self._values(c)]
            if op in ("eq", "in"):
                return num.in_(vals_n)
            if op in ("neq", "not_in"):
                return and_(num.isnot(None), num.notin_(vals_n))
            if op == "between":
                if len(vals_n) != 2:
                    raise QueryError("between needs two values")
                return and_(num >= vals_n[0], num <= vals_n[1])
            if op in ("gt", "gte", "lt", "lte") and len(vals_n) == 1:
                nv = vals_n[0]
                return {"gt": num > nv, "gte": num >= nv, "lt": num < nv, "lte": num <= nv}[op]
            raise QueryError(f"{q.key}: {op} does not apply to a number")
        if t == "date":
            return self._date_cmp(_text(x), op, [self._date(q.key, v) for v in self._values(c)])
        # text, time, email, phone, hidden
        txt = _text(x)
        vals_s = [str(v) for v in self._values(c)]
        if op == "contains":
            return txt.ilike(f"%{_escape_like(str(self._one(c)))}%", escape="\\")
        if op in ("eq", "in"):
            return func.lower(func.btrim(txt)).in_([v.strip().lower() for v in vals_s])
        if op in ("neq", "not_in"):
            return and_(
                answered(x), func.lower(func.btrim(txt)).notin_([v.strip().lower() for v in vals_s])
            )
        if op in ("gt", "gte", "lt", "lte", "between") and t == "time":
            if op == "between":
                return and_(txt >= vals_s[0], txt <= vals_s[1])
            sv = vals_s[0]
            return {"gt": txt > sv, "gte": txt >= sv, "lt": txt < sv, "lte": txt <= sv}[op]
        raise QueryError(f"{q.key}: {op} does not apply to text")

    def condition(self, c: Condition, unit: Repeater | None, rows: Any) -> ColumnElement[bool]:
        if c.field in META_FIELDS:
            return self._meta(c)
        q = self.question(c.field)
        if q.repeater is None:
            return self.value_condition(q, jget(Submission.data, q.key), c)
        rep = self.cat.repeaters[q.repeater]
        if unit is not None and unit.key == rep.key and rows is not None:
            return self.value_condition(q, jget(rows.c.value, q.key), c)
        r = self.rows_lateral(rep, f"x_{rep.key}")
        return exists(
            select(literal(1))
            .select_from(r)
            .where(self.value_condition(q, jget(r.c.value, q.key), c))
        )

    def conditions(
        self, where: list[Condition], where_any: list[Condition], unit: Repeater | None, rows: Any
    ) -> list[ColumnElement[bool]]:
        out = [self.condition(c, unit, rows) for c in where]
        if where_any:
            out.append(or_(*(self.condition(c, unit, rows) for c in where_any)))
        return out

    # -- groups and aggregates -----------------------------------------------------------

    def unit_of(self, query: Query) -> Repeater | None:
        keys = [g.field for g in query.group_by] + [a.field for a in query.aggregates if a.field]
        reps = {
            q.repeater
            for k in keys
            if k not in META_FIELDS and (q := self.question(k)).repeater is not None
        }
        if len(reps) > 1:
            raise QueryError("group or aggregate over one repeater at a time")
        return self.cat.repeaters[reps.pop()] if reps else None

    def answer(self, q: Question, rows: Any) -> ColumnElement[Any]:
        if q.repeater is None:
            return jget(Submission.data, q.key)
        if rows is None:
            raise QueryError(f"{q.key!r} is inside a repeater")
        return jget(rows.c.value, q.key)


def submission_where(
    cat: Catalogue, where: Where | None, tz: ZoneInfo, policy: Policy = PEOPLE
) -> list[ColumnElement[bool]]:
    """Submission-level clauses for list filters ("Show these submissions")."""
    if where is None:
        return []
    comp = Compiler(cat, policy, tz)
    return comp.conditions(where.where, where.where_any, None, None)


# --------------------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------------------


def _key_out(q: Question | None, field_: str, raw: Any) -> Any:
    if raw is None:
        return None
    if field_ == META_VERSION:
        return int(raw)
    if q is not None and q.type in NUMBER_TYPES:
        d = Decimal(str(raw))
        return int(d) if d == d.to_integral_value() else float(d)
    if q is not None and q.type == "yes_no":
        return raw == "true"
    return str(raw)


def _label(q: Question | None, field_: str, key: Any) -> str:
    if key is None:
        return "No answer"
    if key == OTHER:
        return "Other"
    if field_ == META_STATUS:
        return {
            "new": "New",
            "in_review": "In review",
            "approved": "Approved",
            "rejected": "Rejected",
        }.get(str(key), str(key))
    if field_ == META_VERSION:
        return f"Version {key}"
    if q is not None and q.type == "yes_no":
        return "Yes" if key is True else "No"
    if q is not None and q.type in CHOICE_TYPES:
        return q.option_label(key) or str(key)
    return str(key)


def _num_out(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, Decimal):
        f = float(v)
        return int(f) if f.is_integer() else round(f, 2)
    if isinstance(v, float):
        return int(v) if v.is_integer() else round(v, 2)
    return v


def base_select(form_id: uuid.UUID, extra: list[ColumnElement[bool]]) -> list[ColumnElement[bool]]:
    return [Submission.form_id == form_id, Submission.deleted_at.is_(None), *extra]


async def run_query(
    db: AsyncSession,
    cat: Catalogue,
    form_id: uuid.UUID,
    query: Query,
    *,
    policy: Policy,
    tz: ZoneInfo,
    scope: list[ColumnElement[bool]] | None = None,
) -> dict[str, Any]:
    """Run ``query``; ``scope`` adds submission-level clauses (the page's filters)."""
    comp = Compiler(cat, policy, tz)
    unit = comp.unit_of(query)
    rows = comp.rows_lateral(unit, "r") if unit else None
    conds = comp.conditions(query.where, query.where_any, unit, rows)
    base = base_select(form_id, list(scope or []))

    def from_(sel: Any) -> Any:
        sel = sel.select_from(Submission)
        if rows is not None:
            sel = sel.join(rows, true())
        return sel

    unit_key: Any = (
        func.concat(cast(Submission.id, String), ":", cast(rows.c.idx, String))
        if rows is not None
        else Submission.id
    )

    # Validate group, aggregate and list keys before running anything.
    group_specs: list[tuple[GroupBy, Question | None]] = []
    for g in query.group_by:
        if g.field in META_FIELDS:
            group_specs.append((g, None))
            continue
        q = comp.question(g.field)
        comp._check_values_use(q, "grouped")
        if q.type in CONTACT_TYPES | TEXT_TYPES and g.bucket != "value":
            raise QueryError(f"{q.key}: bucket only applies to dates")
        group_specs.append((g, q))
    if sum(1 for _g, gq in group_specs if gq is not None and gq.type == "multi_choice") > 1:
        # Each would multiply the rows per submission by its ticked options.
        raise QueryError(
            "group by at most one multi-choice question at a time; filter by the other"
            " (includes_any) and run one query per option instead"
        )
    agg_specs: list[tuple[Aggregate, Question | None]] = []
    for a in query.aggregates or [Aggregate(op="count")]:
        if a.op == "count":
            agg_specs.append((a, None))
            continue
        if not a.field or a.field in META_FIELDS:
            raise QueryError(f"{a.op} needs a question key")
        q = comp.question(a.field)
        comp._check_values_use(q, "aggregated")
        if a.op in ("sum", "avg", "median") and q.type not in NUMBER_TYPES:
            raise QueryError(f"{a.op} needs a number or rating question, {q.key!r} is {q.type}")
        if a.op in ("min", "max") and q.type not in NUMBER_TYPES | {"date", "time"}:
            raise QueryError(f"{a.op} needs a number, rating, date or time question")
        agg_specs.append((a, q))
    list_qs: list[Question] = []
    for k in query.list_fields:
        if k in META_FIELDS:
            continue
        q = comp.question(k)
        comp._check_values_use(q, "listed")
        list_qs.append(q)

    out: dict[str, Any] = {"unit": "submissions" if unit is None else f"rows of {unit.label!r}"}

    # Totals.
    total_sel = from_(
        select(
            func.count(func.distinct(Submission.id)),
            func.count(func.distinct(unit_key)) if rows is not None else literal(0),
        )
    ).where(*base, *conds)
    subs, row_count = (await db.execute(total_sel)).one()
    out["matched"] = {"submissions": int(subs)}
    if rows is not None:
        out["matched"]["rows"] = int(row_count)

    def agg_expr(a: Aggregate, q: Question | None) -> ColumnElement[Any]:
        if a.op == "count":
            return func.count(func.distinct(unit_key))
        assert q is not None
        x = comp.answer(q, rows)
        if a.op == "distinct":
            return func.count(func.distinct(x.op("#>>", return_type=Text)(_SCALAR)))
        val = _number(x) if q.type in NUMBER_TYPES else _text(x)
        if a.op == "median":
            return func.percentile_cont(0.5).within_group(val)
        fn: Any = {"sum": func.sum, "avg": func.avg, "min": func.min, "max": func.max}[a.op]
        return fn(val)

    def agg_name(a: Aggregate) -> str:
        return a.op if a.op == "count" else f"{a.op}:{a.field}"

    if group_specs:
        sel_cols: list[Any] = []
        joins: list[Any] = []
        for i, (g, gq) in enumerate(group_specs):
            sel_cols.append(group_expr(comp, g, gq, rows, joins, i).label(f"g{i}"))
        aggs = [agg_expr(a, aq).label(f"a{j}") for j, (a, aq) in enumerate(agg_specs)]
        subs_col = func.count(func.distinct(Submission.id)).label("subs")
        sel = from_(select(*sel_cols, *aggs, subs_col))
        for j in joins:
            sel = sel.outerjoin(j, true())
        sel = sel.where(*base, *conds).group_by(*[f"g{i}" for i in range(len(group_specs))])
        if query.sort == "key":
            sel = sel.order_by(
                *[column(f"g{i}").asc().nulls_last() for i in range(len(group_specs))]
            )
        else:
            sel = sel.order_by(
                column("a0").desc(),
                *[column(f"g{i}").asc().nulls_last() for i in range(len(group_specs))],
            )
        result = (await db.execute(sel.limit(query.limit + 1))).all()
        groups = []
        for row in result[: query.limit]:
            m = row._mapping
            key: dict[str, Any] = {}
            labels: dict[str, str] = {}
            for i, (g, gq) in enumerate(group_specs):
                k = _key_out(gq, g.field, m[f"g{i}"]) if m[f"g{i}"] != OTHER else OTHER
                key[g.field] = "Other" if k == OTHER else k
                labels[g.field] = _label(gq, g.field, k)
            entry: dict[str, Any] = {"key": key, "label": labels}
            for j, (a, _q) in enumerate(agg_specs):
                entry[agg_name(a)] = _num_out(m[f"a{j}"])
            if rows is not None:
                entry["submissions"] = int(m["subs"])
            groups.append(entry)
        out["groups"] = groups
        if len(result) > query.limit:
            out["groupsTruncated"] = True
        if any(gq is not None and gq.type == "multi_choice" for _g, gq in group_specs):
            comp.notes.append("a submission can tick several options, so groups overlap")
        # "Other" texts, when they may be shown.
        for _g, gq in group_specs:
            if gq is not None and gq.type in CHOICE_TYPES and policy.text_allowed:
                texts = await other_texts(db, comp, gq, rows, base, conds, from_)
                if texts:
                    out.setdefault("otherAnswers", {})[gq.key] = texts
    else:
        sel = from_(select(*[agg_expr(a, aq) for a, aq in agg_specs])).where(*base, *conds)
        vals = (await db.execute(sel)).one()
        out["aggregates"] = {
            agg_name(a): _num_out(v) for (a, _q), v in zip(agg_specs, vals, strict=True)
        }

    if query.list_limit:
        out["submissions"] = await list_refs(
            db, cat, comp, base, conds, from_, list_qs, query.list_limit
        )
    if comp.notes:
        out["notes"] = list(dict.fromkeys(comp.notes))
    return out


def group_expr(
    comp: Compiler, g: GroupBy, q: Question | None, rows: Any, joins: list[Any], i: int
) -> ColumnElement[Any]:
    if g.field == META_STATUS:
        return cast(Submission.status, String)
    if g.field == META_VERSION:
        cases = [(Submission.form_version_id == vid, n) for n, vid in comp.cat.version_ids.items()]
        return case(*cases) if cases else literal(None)
    if g.field == META_SUBMITTED:
        fmt = {"value": "YYYY-MM-DD", "day": "YYYY-MM-DD", "month": "YYYY-MM", "year": "YYYY"}[
            g.bucket
        ]
        return func.to_char(func.timezone(str(comp.tz), Submission.submitted_at), fmt)
    assert q is not None
    x = comp.answer(q, rows)
    if q.type == "multi_choice":
        el = func.jsonb_array_elements_text(_as_array(x)).table_valued("value").lateral(f"m{i}")
        joins.append(el)
        return case(
            (el.c.value.in_(q.option_values or [""]), el.c.value),
            (el.c.value.is_(None), None),
            else_=literal(OTHER),
        )
    if q.type == "single_choice":
        t = _text(x)
        return case(
            (t.in_(q.option_values or [""]), t),
            (t.is_(None), None),
            (t == "", None),
            else_=literal(OTHER),
        )
    if q.type == "yes_no":
        return case((func.jsonb_typeof(x) == "boolean", x.op("#>>", return_type=Text)(_SCALAR)))
    if q.type in NUMBER_TYPES:
        return _number(x)
    if q.type == "date":
        n = {"value": 10, "day": 10, "month": 7, "year": 4}[g.bucket]
        return func.substr(_text(x), 1, n)
    return case((answered(x), func.btrim(_text(x))))


async def other_texts(
    db: AsyncSession,
    comp: Compiler,
    q: Question,
    rows: Any,
    base: list[ColumnElement[bool]],
    conds: list[ColumnElement[bool]],
    from_: Any,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """The most common "Other" texts of a choice question (count each)."""
    x = comp.answer(q, rows)
    val: Any
    if q.type == "multi_choice":
        el = func.jsonb_array_elements_text(_as_array(x)).table_valued("value").lateral("ot")
        val = el.c.value
        sel = from_(select(val, func.count())).join(el, true())
    else:
        val = _text(x)
        sel = from_(select(val, func.count()))
    sel = (
        sel.where(*base, *conds, val.isnot(None), val != "", val.notin_(q.option_values or [""]))
        .group_by(val)
        .order_by(func.count().desc(), val)
        .limit(limit)
    )
    return [
        {"text": str(t)[:LIST_TEXT_CHARS], "count": int(n)}
        for t, n in (await db.execute(sel)).all()
    ]


def _rows_of(
    cat: Catalogue, rep_key: str, data: dict[str, Any], version_id: uuid.UUID
) -> list[dict[str, Any]]:
    rep = cat.repeaters[rep_key]
    rows = data.get(rep_key)
    out = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    if rep.mapped_rows and version_id in rep.mapped_version_ids:
        mapping = version_map.VersionMapping(rep.key, tuple(tuple(r) for r in rep.mapped_rows))
        out += version_map.mapped_rows(mapping, data)
    return out


def answer_of(
    cat: Catalogue, q: Question, data: dict[str, Any], version_id: uuid.UUID, *, sep: str = "; "
) -> str:
    """One question's answer(s) in a submission as text (repeater rows joined)."""
    if q.repeater is None:
        values = [data.get(q.key)]
    else:
        values = [r.get(q.key) for r in _rows_of(cat, q.repeater, data, version_id)]
    texts = [answer_text(q.element, v, cat.language) for v in values]
    return sep.join(t for t in texts if t)


async def list_refs(
    db: AsyncSession,
    cat: Catalogue,
    comp: Compiler,
    base: list[ColumnElement[bool]],
    conds: list[ColumnElement[bool]],
    from_: Any,
    fields: list[Question],
    limit: int,
) -> list[dict[str, Any]]:
    ids = from_(select(Submission.id)).where(*base, *conds).distinct().subquery()
    sel = (
        select(Submission.seq, Submission.submitted_at, Submission.data, Submission.form_version_id)
        .where(Submission.id.in_(select(ids.c.id)))
        .order_by(Submission.seq.desc())
        .limit(limit)
    )
    out = []
    for seq, submitted, data, vid in (await db.execute(sel)).all():
        item: dict[str, Any] = {
            "ref": seq,
            "submitted": submitted.astimezone(comp.tz).date().isoformat(),
        }
        if fields:
            item["answers"] = {
                q.key: answer_of(cat, q, data or {}, vid)[:LIST_TEXT_CHARS] for q in fields
            }
        out.append(item)
    return out


# --------------------------------------------------------------------------------------
# Describing (the "How this was calculated" disclosure and the list filter chip)
# --------------------------------------------------------------------------------------

_OP_WORDS = {
    "eq": "is",
    "neq": "is not",
    "in": "is one of",
    "not_in": "is none of",
    "contains": "contains",
    "gt": "is more than",
    "gte": "is at least",
    "lt": "is less than",
    "lte": "is at most",
    "between": "is between",
    "includes_any": "includes",
    "includes_all": "includes all of",
    "excludes": "doesn't include",
    "is_other": "has an \u201cOther\u201d answer",
    "answered": "is answered",
    "unanswered": "is not answered",
}


def _field_name(cat: Catalogue, key: str) -> str:
    if key == META_STATUS:
        return "Status"
    if key == META_SUBMITTED:
        return "Submitted"
    if key == META_VERSION:
        return "Version"
    q = cat.question(key)
    return f"\u201c{q.label}\u201d" if q else key


def describe_condition(cat: Catalogue, c: Condition) -> str:
    name = _field_name(cat, c.field)
    words = _OP_WORDS.get(c.op, c.op)
    if c.op in ("answered", "unanswered", "is_other"):
        return f"{name} {words}"
    q = cat.question(c.field)
    vals = c.values if c.values is not None else ([] if c.value is None else [c.value])

    def show(v: Scalar) -> str:
        if c.field == META_STATUS:
            return _label(None, META_STATUS, v)
        if q is not None and q.type == "yes_no":
            return "Yes" if str(v).lower() in ("true", "yes", "1") else "No"
        if q is not None and q.type in CHOICE_TYPES:
            lab = q.option_label(v)
            return f"\u201c{lab or v}\u201d"
        return f"\u201c{v}\u201d" if isinstance(v, str) else str(v)

    if c.op == "between" and len(vals) == 2:
        return f"{name} is between {show(vals[0])} and {show(vals[1])}"
    joined = (
        " or ".join(show(v) for v in vals)
        if c.op not in ("includes_all",)
        else " and ".join(show(v) for v in vals)
    )
    return f"{name} {words} {joined}".strip()


def describe(cat: Catalogue, query: Query | Where) -> str:
    parts = [describe_condition(cat, c) for c in query.where]
    if query.where_any:
        parts.append("(" + " or ".join(describe_condition(cat, c) for c in query.where_any) + ")")
    text = "All submissions" if not parts else "Submissions where " + " and ".join(parts)
    if isinstance(query, Query) and query.group_by:
        text += ", grouped by " + " and ".join(_field_name(cat, g.field) for g in query.group_by)
    return text
