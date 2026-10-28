"""Where people get stuck: anonymous friction counters from the public form.

The public form reports which pages a visit reached, when it started answering, and which
validation problem (field key and problem code, never the value) it was shown. Reports carry a
random per-visit id that lives in the respondent's tab (sessionStorage) and is used here only
to count each thing once per visit: Redis keeps a hash of it for a day, the database keeps
daily counters per form, version, metric, page, question and code (``form_friction``). Nothing
identifies a respondent and no cookies are read.

Owners can turn it off per form (Settings > Access, ``frictionInsights``); it is on by default.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.logic.index import FormIndex
from app.models import FormFriction
from app.schemas.form import Form

Metric = Literal["view", "start", "error", "submit"]
WINDOW_DAYS = 30
VISIT_TTL_SECONDS = 86_400
MAX_EVENTS = 50
VISIT_PATTERN = r"^[A-Za-z0-9_-]{16,64}$"

# Problem codes of both validation twins plus the server-only ones (uploads, signatures,
# approvals). Anything else is ignored.
CODES = frozenset(
    {
        "required",
        "invalid",
        "too_long",
        "pattern",
        "email",
        "phone",
        "phone_mv",
        "number",
        "integer",
        "between",
        "at_least",
        "at_most",
        "date",
        "date_from",
        "date_to",
        "time",
        "option",
        "choose_at_least",
        "choose_at_most",
        "file_invalid",
        "file_missing",
        "file_type",
        "file_too_large",
        "too_many_files",
        "signature_invalid",
        "signature_small",
        "rows_max",
        "approver_domain",
        "approver_is_respondent",
    }
)
_ID = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def enabled(settings: dict[str, Any] | None) -> bool:
    """The per-form setting: on unless the owner turned it off."""
    return (settings or {}).get("frictionInsights", True) is not False


@dataclass(frozen=True)
class Counter:
    metric: Metric
    page_id: str = ""
    field_id: str = ""
    code: str = ""

    @property
    def member(self) -> str:
        return f"{self.metric}|{self.page_id}|{self.field_id}|{self.code}"


def counters(form: Form, events: list[dict[str, Any]]) -> list[Counter]:
    """The valid counters among a client's events (unknown pages, questions or codes are
    dropped silently: a report never says what exists)."""
    index = FormIndex.build(form)
    pages = {p.id for p in form.pages}
    out: dict[str, Counter] = {}
    for ev in events[:MAX_EVENTS]:
        kind = ev.get("type")
        page = ev.get("page")
        if kind == "start":
            c = Counter("start")
        elif kind == "page" and isinstance(page, str) and page in pages:
            c = Counter("view", page_id=page)
        elif kind == "error":
            fid, code = ev.get("field"), ev.get("code")
            if not (isinstance(fid, str) and _ID.match(fid) and code in CODES):
                continue
            info = index.elements.get(fid)
            if info is None or info.kind not in ("field", "repeater"):
                continue
            c = Counter(
                "error",
                page_id=form.pages[info.page_index].id,
                field_id=fid,
                code=str(code),
            )
        else:
            continue
        out[c.member] = c
    return list(out.values())


def _visit_key(form_id: uuid.UUID, visit: str) -> str:
    digest = hashlib.sha256(f"{form_id}:{visit}".encode()).hexdigest()[:32]
    return f"friction:{digest}"


async def _increment(
    db: AsyncSession, form_id: uuid.UUID, version: int, day: date, items: list[Counter]
) -> None:
    if not items:
        return
    rows = [
        {
            "form_id": form_id,
            "version": version,
            "day": day,
            "metric": c.metric,
            "page_id": c.page_id,
            "field_id": c.field_id,
            "code": c.code,
            "count": 1,
        }
        for c in items
    ]
    stmt = insert(FormFriction).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["form_id", "version", "day", "metric", "page_id", "field_id", "code"],
        set_={"count": FormFriction.count + 1},
    )
    await db.execute(stmt)


async def record(
    db: AsyncSession,
    redis: Redis,
    *,
    form_id: uuid.UUID,
    version: int,
    form: Form,
    visit: str,
    events: list[dict[str, Any]],
    day: date,
) -> int:
    """Count a visit's new events once each. Returns how many counters went up."""
    items = counters(form, events)
    if not items:
        return 0
    key = _visit_key(form_id, visit)
    fresh: list[Counter] = []
    async with redis.pipeline(transaction=True) as pipe:
        for c in items:
            pipe.sadd(key, c.member)
        pipe.expire(key, VISIT_TTL_SECONDS)
        results = await pipe.execute()
    fresh = [c for c, added in zip(items, results[: len(items)], strict=True) if added]
    await _increment(db, form_id, version, day, fresh)
    return len(fresh)


async def record_submit(db: AsyncSession, *, form_id: uuid.UUID, version: int, day: date) -> None:
    await _increment(db, form_id, version, day, [Counter("submit")])


async def summary(
    db: AsyncSession, form_id: uuid.UUID, today: date, days: int = WINDOW_DAYS
) -> dict[str, Any]:
    """Totals for the last ``days`` days (all versions): visits per page, starts, submissions,
    and validation problems per question and code."""
    since = today - timedelta(days=days - 1)
    rows = (
        await db.execute(
            select(
                FormFriction.metric,
                FormFriction.page_id,
                FormFriction.field_id,
                FormFriction.code,
                func.sum(FormFriction.count),
            )
            .where(FormFriction.form_id == form_id, FormFriction.day >= since)
            .group_by(
                FormFriction.metric, FormFriction.page_id, FormFriction.field_id, FormFriction.code
            )
        )
    ).all()
    views: dict[str, int] = {}
    starts = submits = 0
    fields: dict[str, dict[str, Any]] = {}
    codes: dict[str, int] = defaultdict(int)
    for metric, page_id, field_id, code, total in rows:
        n = int(total or 0)
        if metric == "view":
            views[page_id] = views.get(page_id, 0) + n
        elif metric == "start":
            starts += n
        elif metric == "submit":
            submits += n
        elif metric == "error":
            entry = fields.setdefault(
                field_id, {"field": field_id, "page": page_id, "total": 0, "codes": {}}
            )
            entry["total"] += n
            entry["codes"][code] = entry["codes"].get(code, 0) + n
            codes[code] += n
    top = sorted(fields.values(), key=lambda f: (-f["total"], f["field"]))
    return {
        "from": since.isoformat(),
        "to": today.isoformat(),
        "days": days,
        "pages": [{"page": p, "visits": n} for p, n in views.items()],
        "started": starts,
        "submitted": submits,
        "fields": top,
        "codes": [
            {"code": c, "count": n} for c, n in sorted(codes.items(), key=lambda x: (-x[1], x[0]))
        ],
    }
