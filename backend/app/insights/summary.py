"""Per-question summaries for the Insights page (DESIGN 15.4).

Everything is counted with the submissions query language (``app.insights.dsl``) under the
page's filters, so the numbers match what the AI and the filtered list report. Each bar
carries the conditions that select its submissions (``where``), which the studio turns into
a filtered Submissions list.

- Choices and yes/no: count and share per option (of the people who answered), "Other"
  answers with their most common texts, and "No answer".
- Numbers and ratings: min, average, median, max and a histogram.
- Dates: answers per month (per year over long spans).
- Text: how many answered and the newest few answers (masked when sensitive).
- Files and signatures: how many answered.
- Sensitive questions: how many answered only (text examples masked).
- Repeaters: rows, submissions with rows, and the same summaries for their questions,
  counted over rows. Older versions' fixed questions mapped onto a repeater count as rows.
"""

from __future__ import annotations

import math
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, String, cast, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.insights.catalogue import (
    CHOICE_TYPES,
    NUMBER_TYPES,
    OBJECT_TYPES,
    Catalogue,
    Question,
)
from app.insights.dsl import (
    OTHER,
    PEOPLE,
    Compiler,
    Condition,
    Query,
    answer_of,
    answered,
    base_select,
    jget,
    run_query,
)
from app.models import Submission

EXAMPLES = 3
MAX_BINS = 8


def _cond(
    field: str, op: str, value: Any = None, values: list[Any] | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {"field": field, "op": op}
    if value is not None:
        out["value"] = value
    if values is not None:
        out["values"] = values
    return out


def _pct(n: int, of: int) -> float:
    return round(100 * n / of, 1) if of else 0.0


class Summariser:
    def __init__(
        self,
        db: AsyncSession,
        cat: Catalogue,
        form_id: uuid.UUID,
        scope: list[ColumnElement[bool]],
        tz: ZoneInfo,
    ) -> None:
        self.db = db
        self.cat = cat
        self.form_id = form_id
        self.scope = scope
        self.tz = tz

    async def query(self, **kw: Any) -> dict[str, Any]:
        return await run_query(
            self.db,
            self.cat,
            self.form_id,
            Query.model_validate(kw),
            policy=PEOPLE,
            tz=self.tz,
            scope=self.scope,
        )

    # -- kinds ---------------------------------------------------------------------------

    async def choice(self, q: Question, unit_total: int) -> dict[str, Any]:
        # Grouping by a question inside a repeater counts its rows.
        res = await self.query(groupBy=[{"field": q.key}], limit=100)
        counts: dict[Any, int] = {}
        for g in res.get("groups", []):
            key = g["key"][q.key]
            counts[OTHER if key == "Other" and q.type in CHOICE_TYPES else key] = int(g["count"])
        no_answer = counts.pop(None, 0)
        answered_n = unit_total - no_answer
        bars: list[dict[str, Any]] = []
        if q.type == "yes_no":
            for value, label in ((True, "Yes"), (False, "No")):
                n = counts.get(value, 0)
                bars.append(
                    {
                        "key": value,
                        "label": label,
                        "count": n,
                        "percent": _pct(n, answered_n),
                        "where": [_cond(q.key, "eq", value)],
                    }
                )
        else:
            for o in q.options:
                n = counts.get(o.value, 0)
                op = "includes_any" if q.type == "multi_choice" else "eq"
                bars.append(
                    {
                        "key": o.value,
                        "label": o.label,
                        "count": n,
                        "percent": _pct(n, answered_n),
                        "where": [
                            _cond(q.key, op, o.value)
                            if op == "eq"
                            else _cond(q.key, op, values=[o.value])
                        ],
                    }
                )
        out: dict[str, Any] = {
            "kind": "choice",
            "multi": q.type == "multi_choice",
            "answered": answered_n,
            "noAnswer": no_answer,
            "bars": bars,
        }
        if OTHER in counts:
            n = counts[OTHER]
            out["other"] = {
                "count": n,
                "percent": _pct(n, answered_n),
                "texts": res.get("otherAnswers", {}).get(q.key, []),
                "where": [_cond(q.key, "is_other")],
            }
        if res.get("groupsTruncated"):
            out["truncated"] = True
        return out

    async def number(self, q: Question) -> dict[str, Any]:
        res = await self.query(
            where=[_cond(q.key, "answered")],
            aggregates=[
                {"op": "count"},
                {"op": "min", "field": q.key},
                {"op": "avg", "field": q.key},
                {"op": "median", "field": q.key},
                {"op": "max", "field": q.key},
                {"op": "sum", "field": q.key},
            ],
        )
        a = res["aggregates"]
        answered_n = int(res["matched"].get("rows", res["matched"]["submissions"]))
        stats = {k: a.get(f"{k}:{q.key}") for k in ("min", "avg", "median", "max", "sum")}
        lo, hi = stats["min"], stats["max"]
        bins: list[dict[str, Any]] = []
        if lo is not None and hi is not None:
            edges = _edges(q, float(lo), float(hi))
            grouped = await self.query(
                where=[_cond(q.key, "answered")],
                groupBy=[{"field": q.key}],
                aggregates=[{"op": "count"}, {"op": "min", "field": q.key}]
                if q.repeater
                else [{"op": "count"}],
                limit=100,
                sort="key",
            )
            values = {
                float(g["key"][q.key]): int(g["count"])
                for g in grouped.get("groups", [])
                if g["key"][q.key] is not None
            }
            exact = not grouped.get("groupsTruncated")
            for i, (start, end, last) in enumerate(edges):
                if exact:
                    n = sum(c for v, c in values.items() if start <= v < end or (last and v == end))
                else:
                    n = await self._count_between(q, start, end, last)
                where = (
                    [_cond(q.key, "eq", _num(start))]
                    if end - start == 1 and _integral(q)
                    else [
                        _cond(q.key, "gte", _num(start)),
                        _cond(q.key, "lte" if last else "lt", _num(end)),
                    ]
                )
                bins.append(
                    {
                        "key": i,
                        "label": _bin_label(q, start, end, last),
                        "from": _num(start),
                        "to": _num(end),
                        "count": n,
                        "percent": _pct(n, answered_n),
                        "where": where,
                    }
                )
        return {"kind": "number", "answered": answered_n, "stats": stats, "bins": bins}

    async def _count_between(self, q: Question, start: float, end: float, last: bool) -> int:
        res = await self.query(
            where=[_cond(q.key, "gte", start), _cond(q.key, "lte" if last else "lt", end)],
            aggregates=[{"op": "count"}, {"op": "min", "field": q.key}] if q.repeater else [],
        )
        return int(res["matched"].get("rows", res["matched"]["submissions"]))

    async def date(self, q: Question) -> dict[str, Any]:
        agg = [{"op": "count"}] + ([{"op": "min", "field": q.key}] if q.repeater else [])
        res = await self.query(where=[_cond(q.key, "answered")], aggregates=agg)
        answered_n = int(res["matched"].get("rows", res["matched"]["submissions"]))
        bucket = "month"
        span = await self.query(
            where=[_cond(q.key, "answered")],
            aggregates=[{"op": "min", "field": q.key}, {"op": "max", "field": q.key}],
        )
        lo, hi = span["aggregates"].get(f"min:{q.key}"), span["aggregates"].get(f"max:{q.key}")
        if lo and hi and len(lo) >= 7 and len(hi) >= 7:
            months = (int(hi[:4]) - int(lo[:4])) * 12 + int(hi[5:7]) - int(lo[5:7])
            if months > 36:
                bucket = "year"
        grouped = await self.query(
            where=[_cond(q.key, "answered")],
            groupBy=[{"field": q.key, "bucket": bucket}],
            aggregates=agg,
            sort="key",
            limit=100,
        )
        bars = [
            {
                "key": g["key"][q.key],
                "label": g["key"][q.key],
                "count": int(g["count"]),
                "percent": _pct(int(g["count"]), answered_n),
                "where": [_cond(q.key, "eq", g["key"][q.key])],
            }
            for g in grouped.get("groups", [])
            if g["key"][q.key]
        ]
        return {
            "kind": "date",
            "answered": answered_n,
            "bucket": bucket,
            "bars": bars,
            "min": lo,
            "max": hi,
        }

    async def examples(self, q: Question, limit: int = EXAMPLES) -> list[dict[str, Any]]:
        comp = Compiler(self.cat, PEOPLE, self.tz)
        cond = comp.condition(Condition(field=q.key, op="answered"), None, None)
        rows = (
            await self.db.execute(
                select(Submission.seq, Submission.data, Submission.form_version_id)
                .where(*base_select(self.form_id, self.scope), cond)
                .order_by(Submission.seq.desc())
                .limit(limit)
            )
        ).all()
        out = []
        for seq, data, vid in rows:
            text = answer_of(self.cat, q, data or {}, vid)
            out.append({"ref": seq, "text": text[:300]})
        return out

    async def text(self, q: Question) -> dict[str, Any]:
        res = await self.query(
            where=[_cond(q.key, "answered")],
        )
        answered_n = int(res["matched"]["submissions"])
        return {
            "kind": "sensitive" if q.sensitive else "text",
            "answered": answered_n,
            "examples": await self.examples(q),
            "where": [_cond(q.key, "answered")],
        }

    async def presence(self, q: Question, kind: str) -> dict[str, Any]:
        res = await self.query(where=[_cond(q.key, "answered")])
        return {
            "kind": kind,
            "answered": int(res["matched"]["submissions"]),
            "where": [_cond(q.key, "answered")],
        }

    async def rows(self, key: str) -> tuple[int, int]:
        comp = Compiler(self.cat, PEOPLE, self.tz)
        r = comp.rows_lateral(self.cat.repeaters[key], "r")
        sel = (
            select(
                func.count(
                    func.distinct(
                        func.concat(cast(Submission.id, String), ":", cast(r.c.idx, String))
                    )
                ),
                func.count(func.distinct(Submission.id)),
            )
            .select_from(Submission)
            .join(r, true())
            .where(*base_select(self.form_id, self.scope), answered(r.c.value))
        )
        n_rows, n_subs = (await self.db.execute(sel)).one()
        return int(n_rows), int(n_subs)

    # -- one question --------------------------------------------------------------------

    async def question(self, q: Question, total: int, rows_total: int | None) -> dict[str, Any]:
        base: dict[str, Any] = {
            "key": q.key,
            "type": q.type,
            "label": q.label,
            "repeater": q.repeater,
            "versions": q.versions,
            "sensitive": q.sensitive,
        }
        unit_total = rows_total if q.repeater else total
        if q.type in OBJECT_TYPES:
            body = await self.presence(q, q.type)
            if q.repeater:
                body["answered"] = await self._rows_answered(q)
        elif q.sensitive:
            body = await self.text(q)
            if q.repeater:
                body["answered"] = await self._rows_answered(q)
        elif q.type in CHOICE_TYPES or q.type == "yes_no":
            body = await self.choice(q, unit_total or 0)
        elif q.type in NUMBER_TYPES:
            body = await self.number(q)
        elif q.type == "date":
            body = await self.date(q)
        else:
            body = await self.text(q)
            if q.repeater:
                body["answered"] = await self._rows_answered(q)
        return {**base, **body}

    async def _rows_answered(self, q: Question) -> int:
        res = await self.query(
            where=[_cond(q.key, "answered")],
            aggregates=[{"op": "count"}, {"op": "distinct", "field": q.key}]
            if not q.sensitive and q.type not in OBJECT_TYPES
            else [],
        )
        if "rows" in res["matched"]:
            return int(res["matched"]["rows"])
        # Sensitive or file questions can't be aggregated: count rows directly.
        comp = Compiler(self.cat, PEOPLE, self.tz)
        assert q.repeater is not None
        r = comp.rows_lateral(self.cat.repeaters[q.repeater], "r")
        sel = (
            select(func.count())
            .select_from(Submission)
            .join(r, true())
            .where(*base_select(self.form_id, self.scope), answered(jget(r.c.value, q.key)))
        )
        return int(await self.db.scalar(sel) or 0)


def _integral(q: Question) -> bool:
    return q.type == "rating" or bool(getattr(q.element, "integer", False))


def _num(v: float) -> int | float:
    return int(v) if float(v).is_integer() else round(v, 4)


def _nice(step: float) -> float:
    if step <= 0:
        return 1.0
    exp = math.floor(math.log10(step))
    base = step / 10**exp
    for nice in (1, 2, 2.5, 5, 10):
        if base <= nice:
            return nice * 10**exp
    return 10 * 10**exp


def _edges(q: Question, lo: float, hi: float) -> list[tuple[float, float, bool]]:
    """Histogram bins (start, end, last); the last bin includes its end."""
    if q.type == "rating":
        top = int(getattr(q.element, "max", 5))
        return [(float(v), float(v + 1), False) for v in range(1, top + 1)]
    integral = (lo.is_integer() and hi.is_integer()) or _integral(q)
    if integral and hi - lo <= 11:
        return [(v, v + 1, False) for v in (float(x) for x in range(int(lo), int(hi) + 1))]
    if lo == hi:
        return [(lo, hi, True)]
    step = _nice((hi - lo) / MAX_BINS)
    start = math.floor(lo / step) * step
    edges: list[tuple[float, float, bool]] = []
    while start <= hi and len(edges) < 20:
        edges.append((start, start + step, False))
        start += step
    if edges:
        s, e, _ = edges[-1]
        edges[-1] = (s, e, True)
    return edges


def _bin_label(q: Question, start: float, end: float, last: bool) -> str:
    if q.type == "rating":
        return f"{int(start)}"
    if end - start == 1 and start.is_integer():
        return f"{int(start)}"
    if start == end:
        return f"{_num(start)}"
    if _integral(q) and start.is_integer() and end.is_integer():
        top = end if last else end - 1
        return f"{int(start)}\u2013{int(top)}"
    return f"{_num(start)}\u2013{_num(end)}"


async def summarise(
    db: AsyncSession,
    cat: Catalogue,
    form_id: uuid.UUID,
    scope: list[ColumnElement[bool]],
    tz: ZoneInfo,
) -> dict[str, Any]:
    s = Summariser(db, cat, form_id, scope, tz)
    total = int(
        await db.scalar(
            select(func.count()).select_from(Submission).where(*base_select(form_id, scope))
        )
        or 0
    )
    questions: list[dict[str, Any]] = []
    for q in cat.top_level():
        if q.type == "hidden":
            continue
        questions.append(await s.question(q, total, None))
    repeaters: list[dict[str, Any]] = []
    for rep in cat.repeaters.values():
        n_rows, n_subs = await s.rows(rep.key)
        children = [
            await s.question(c, total, n_rows) for c in cat.children(rep.key) if c.type != "hidden"
        ]
        repeaters.append(
            {
                "key": rep.key,
                "type": "repeater",
                "label": rep.label,
                "versions": rep.versions,
                "mapped": bool(rep.mapped_rows),
                "rows": n_rows,
                "submissions": n_subs,
                "avgRows": round(n_rows / n_subs, 2) if n_subs else 0,
                "questions": children,
            }
        )
    return {
        "total": total,
        "questions": questions,
        "repeaters": repeaters,
        "language": cat.language,
    }
