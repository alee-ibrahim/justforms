"""The submissions query language (app/insights/dsl.py): every operator, repeaters and version
mappings, the policy (sensitive, contact, free text) and injection safety."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.insights import catalogue as cat_mod
from app.insights.dsl import (
    FEWER,
    PEOPLE,
    Policy,
    Query,
    QueryError,
    Where,
    describe,
    run_query,
    submission_where,
)
from app.models import Submission
from tests.insights_fixture import Seeded, seed

TZ = ZoneInfo("UTC")
AI_NO_TEXT = Policy.for_ask(False)
AI_TEXT = Policy(for_ai=True, text_allowed=True)


async def q(
    db: AsyncSession, s: Seeded, query: dict[str, Any], policy: Policy = PEOPLE
) -> dict[str, Any]:
    cat = await cat_mod.load(db, s.form)
    return await run_query(db, cat, s.form.id, Query.model_validate(query), policy=policy, tz=TZ)


async def count(
    db: AsyncSession, s: Seeded, *where: dict[str, Any], any_: list[dict[str, Any]] | None = None
) -> int:
    res = await q(db, s, {"where": list(where), "whereAny": any_ or []})
    return int(res["matched"]["submissions"])


async def test_catalogue_versions_and_mapping(db: AsyncSession) -> None:
    s = await seed(db)
    cat = await cat_mod.load(db, s.form)
    # Mapped fixed questions are read as repeater rows, not listed on their own.
    assert "member1_name" not in cat.questions
    assert cat.repeaters["members"].mapped_version_ids == [s.v1.id]
    # Options merged across versions.
    assert [o.value for o in cat.questions["areas"].options] == [
        "disability",
        "climate",
        "youth",
        "health",
    ]
    assert cat.questions["areas"].versions == [1, 2]
    assert set(cat.for_version(1).repeaters) == {"members"}  # through the mapping
    outline = cat_mod.outline(cat, text_allowed=False)
    keys = [e["key"] for e in outline]
    assert "members" in keys and "national_id" in keys
    nid = next(e for e in outline if e["key"] == "national_id")
    assert "sensitive" in nid["note"]


async def test_operators(db: AsyncSession) -> None:
    s = await seed(db)
    assert await count(db, s) == 5  # the deleted one never counts
    # Multi choice, by value and by label.
    assert (
        await count(db, s, {"field": "areas", "op": "includes_any", "values": ["disability"]}) == 2
    )
    assert (
        await count(
            db, s, {"field": "areas", "op": "includes_any", "values": ["Disability rights"]}
        )
        == 2
    )
    assert (
        await count(db, s, {"field": "areas", "op": "includes_all", "values": ["climate", "youth"]})
        == 2
    )
    assert await count(db, s, {"field": "areas", "op": "excludes", "values": ["climate"]}) == 2
    assert await count(db, s, {"field": "areas", "op": "is_other"}) == 1
    assert await count(db, s, {"field": "areas", "op": "answered"}) == 4
    assert await count(db, s, {"field": "areas", "op": "unanswered"}) == 1  # []
    # Single choice and Other.
    assert await count(db, s, {"field": "atoll", "op": "eq", "value": "male"}) == 2
    assert await count(db, s, {"field": "atoll", "op": "in", "values": ["Malé", "addu"]}) == 4
    assert await count(db, s, {"field": "atoll", "op": "neq", "value": "male"}) == 3
    assert await count(db, s, {"field": "atoll", "op": "is_other"}) == 1
    # Numbers.
    assert await count(db, s, {"field": "staff", "op": "gte", "value": 7}) == 2
    assert await count(db, s, {"field": "staff", "op": "between", "values": [2, 4]}) == 2
    assert await count(db, s, {"field": "staff", "op": "lt", "value": "5"}) == 2
    assert await count(db, s, {"field": "rating", "op": "eq", "value": 5}) == 1
    # Dates (prefixes).
    assert await count(db, s, {"field": "founded", "op": "lt", "value": "2016"}) == 2
    assert await count(db, s, {"field": "founded", "op": "eq", "value": "2019-03"}) == 1
    assert (
        await count(db, s, {"field": "founded", "op": "between", "values": ["2015", "2019"]}) == 2
    )
    # Yes/no.
    assert await count(db, s, {"field": "registered", "op": "eq", "value": True}) == 3
    assert await count(db, s, {"field": "registered", "op": "eq", "value": "no"}) == 2
    # Text.
    assert await count(db, s, {"field": "mission", "op": "contains", "value": "CLIMATE"}) == 2
    assert await count(db, s, {"field": "mission", "op": "contains", "value": "%"}) == 0
    assert await count(db, s, {"field": "org_name", "op": "eq", "value": " reef watch "}) == 1
    assert await count(db, s, {"field": "mission", "op": "contains", "value": "ތަރައްޤީ"}) == 1
    # Files and sensitive: answered only.
    assert await count(db, s, {"field": "logo", "op": "answered"}) == 1
    assert await count(db, s, {"field": "national_id", "op": "answered"}) == 3
    with pytest.raises(QueryError):
        await count(db, s, {"field": "national_id", "op": "eq", "value": "A111111"})
    # Submission fields.
    assert await count(db, s, {"field": "_status", "op": "in", "values": ["new", "in_review"]}) == 3
    assert await count(db, s, {"field": "_submitted", "op": "gte", "value": "2026-02"}) == 3
    assert await count(db, s, {"field": "_version", "op": "eq", "value": 1}) == 2
    assert await count(db, s, {"field": "_version", "op": "gte", "value": 2}) == 3
    # whereAny.
    n = await count(
        db,
        s,
        any_=[
            {"field": "atoll", "op": "eq", "value": "addu"},
            {"field": "staff", "op": "gte", "value": 10},
        ],
    )
    assert n == 2


async def test_groups(db: AsyncSession) -> None:
    s = await seed(db)
    res = await q(db, s, {"groupBy": [{"field": "areas"}]})
    by = {g["key"]["areas"]: g["count"] for g in res["groups"]}
    assert by == {"disability": 2, "climate": 2, "youth": 2, "health": 1, "Other": 1, None: 1}
    assert res["otherAnswers"]["areas"] == [{"text": "Fishing", "count": 1}]
    assert any("overlap" in n for n in res["notes"])
    labels = {g["key"]["areas"]: g["label"]["areas"] for g in res["groups"]}
    assert labels["disability"] == "Disability rights" and labels[None] == "No answer"

    res = await q(db, s, {"groupBy": [{"field": "_submitted", "bucket": "month"}], "sort": "key"})
    assert [(g["key"]["_submitted"], g["count"]) for g in res["groups"]] == [
        ("2026-01", 2),
        ("2026-02", 2),
        ("2026-03", 1),
    ]
    res = await q(
        db, s, {"groupBy": [{"field": "registered"}, {"field": "_version"}], "sort": "key"}
    )
    assert [(g["key"]["registered"], g["key"]["_version"], g["count"]) for g in res["groups"]] == [
        (False, 2, 2),
        (True, 1, 2),
        (True, 2, 1),
    ]
    res = await q(
        db,
        s,
        {
            "aggregates": [
                {"op": "count"},
                {"op": "sum", "field": "staff"},
                {"op": "avg", "field": "staff"},
                {"op": "min", "field": "staff"},
                {"op": "max", "field": "staff"},
                {"op": "median", "field": "staff"},
                {"op": "distinct", "field": "atoll"},
                {"op": "min", "field": "founded"},
            ]
        },
    )
    a = res["aggregates"]
    assert a == {
        "count": 5,
        "sum:staff": 23,
        "avg:staff": 5.75,
        "min:staff": 2,
        "max:staff": 10,
        "median:staff": 5.5,
        "distinct:atoll": 3,
        "min:founded": "2010-01-05",
    }
    res = await q(db, s, {"groupBy": [{"field": "atoll"}], "limit": 1})
    assert len(res["groups"]) == 1 and res["groupsTruncated"]


async def test_repeater_rows_and_mapping(db: AsyncSession) -> None:
    s = await seed(db)
    # Rows: v1 mapped rows (2 + 1) and v2 rows (1 + 3).
    res = await q(db, s, {"aggregates": [{"op": "count"}, {"op": "avg", "field": "member_age"}]})
    assert res["unit"] == "rows of 'Members'"
    assert res["matched"] == {"submissions": 4, "rows": 7}
    assert res["aggregates"]["count"] == 7
    assert res["aggregates"]["avg:member_age"] == pytest.approx(
        (30 + 41 + 25 + 19 + 52 + 47) / 6, abs=0.01
    )
    # A condition on a row question: submissions with at least one such row.
    assert await count(db, s, {"field": "member_age", "op": "gte", "value": 50}) == 1
    assert await count(db, s, {"field": "member_name", "op": "eq", "value": "aisha"}) == 1  # mapped
    # Rows of one repeater, filtered at row level, grouped by a top-level question.
    res = await q(
        db,
        s,
        {
            "where": [{"field": "member_age", "op": "gte", "value": 40}],
            "groupBy": [{"field": "atoll"}],
            "aggregates": [{"op": "count"}, {"op": "max", "field": "member_age"}],
        },
    )
    assert [
        (g["key"]["atoll"], g["count"], g["submissions"], g["max:member_age"])
        for g in res["groups"]
    ] == [("male", 3, 2, 52)]
    # Without a row question in the groups or aggregates, submissions are counted.
    res = await q(
        db,
        s,
        {
            "where": [{"field": "member_age", "op": "gte", "value": 40}],
            "groupBy": [{"field": "atoll"}],
        },
    )
    assert [(g["key"]["atoll"], g["count"]) for g in res["groups"]] == [("male", 2)]
    with pytest.raises(QueryError):
        await q(db, s, {"groupBy": [{"field": "member_name"}, {"field": "nope"}]})


async def test_lists(db: AsyncSession) -> None:
    s = await seed(db)
    res = await q(
        db,
        s,
        {
            "where": [{"field": "areas", "op": "includes_any", "values": ["climate"]}],
            "listLimit": 5,
            "listFields": ["org_name", "member_name", "national_id"][:2],
        },
    )
    assert [i["ref"] for i in res["submissions"]] == [3, 1]
    assert res["submissions"][1]["answers"] == {
        "org_name": "Reef Watch",
        "member_name": "Aisha; Ali",
    }


async def test_policy(db: AsyncSession) -> None:
    s = await seed(db)
    for query in (
        {"groupBy": [{"field": "national_id"}]},
        {"listLimit": 1, "listFields": ["national_id"]},
        {"aggregates": [{"op": "distinct", "field": "national_id"}]},
        {"groupBy": [{"field": "logo"}]},
    ):
        with pytest.raises(QueryError):
            await q(db, s, query)
    # Contact details: grouped or listed for the AI only with reading allowed.
    with pytest.raises(QueryError, match="contact detail"):
        await q(db, s, {"groupBy": [{"field": "contact"}]}, AI_NO_TEXT)
    assert (await q(db, s, {"groupBy": [{"field": "contact"}]}, AI_TEXT))["groups"]
    assert (await q(db, s, {"groupBy": [{"field": "contact"}]}))["groups"]  # people may
    # Free text: only when reading answers is allowed.
    with pytest.raises(QueryError, match="reading answers is off"):
        await q(db, s, {"listLimit": 2, "listFields": ["mission"]}, AI_NO_TEXT)
    with pytest.raises(QueryError):
        await q(db, s, {"groupBy": [{"field": "org_name"}]}, AI_NO_TEXT)
    res = await q(db, s, {"groupBy": [{"field": "areas"}]}, AI_NO_TEXT)
    assert "otherAnswers" not in res  # "Other" texts are answers too
    # Reading off: every group here has fewer than 5 submissions, so they are merged.
    assert [g["key"]["areas"] for g in res["groups"]] == [FEWER]
    assert res["groups"][0]["label"]["areas"].startswith("Fewer than 5 each")
    assert any(
        g["key"]["areas"] == "Other"
        for g in (await q(db, s, {"groupBy": [{"field": "areas"}]}, AI_TEXT))["groups"]
    )
    # ...and listLimit gives submission numbers only; exact dates and min/max are refused.
    res = await q(db, s, {"listLimit": 3}, AI_NO_TEXT)
    assert res["submissions"] and all(set(i) == {"ref"} for i in res["submissions"])
    for query in (
        {"groupBy": [{"field": "founded"}]},
        {"groupBy": [{"field": "founded", "bucket": "day"}]},
        {"aggregates": [{"op": "max", "field": "staff"}]},
        {"aggregates": [{"op": "distinct", "field": "founded"}]},
    ):
        with pytest.raises(QueryError, match="reading answers is off"):
            await q(db, s, query, AI_NO_TEXT)
    assert (await q(db, s, {"groupBy": [{"field": "founded", "bucket": "year"}]}, AI_NO_TEXT))[
        "groups"
    ]
    res = await q(db, s, {"aggregates": [{"op": "avg", "field": "staff"}]}, AI_NO_TEXT)
    assert res["aggregates"]["avg:staff"] is not None  # 5 submissions
    res = await q(
        db,
        s,
        {
            "where": [{"field": "atoll", "op": "eq", "value": "addu"}],
            "aggregates": [{"op": "avg", "field": "staff"}],
        },
        AI_NO_TEXT,
    )
    assert res["aggregates"]["avg:staff"] is None  # 2 submissions
    # Free text and contact details can't be filtered by value either (a probing oracle):
    # answered/unanswered only. People and reading-on may filter.
    for cond in (
        {"field": "mission", "op": "contains", "value": "climate"},
        {"field": "contact", "op": "contains", "value": "a@ex"},
        {"field": "org_name", "op": "eq", "value": "reef watch"},
    ):
        with pytest.raises(QueryError, match="answered/unanswered"):
            await q(db, s, {"where": [cond]}, AI_NO_TEXT)
        await q(db, s, {"where": [cond]}, AI_TEXT)
    res = await q(db, s, {"where": [{"field": "mission", "op": "answered"}]}, AI_NO_TEXT)
    assert res["matched"]["submissions"] >= 2
    res = await q(
        db, s, {"where": [{"field": "mission", "op": "contains", "value": "climate"}]}, AI_TEXT
    )
    assert res["matched"]["submissions"] == 2
    assert (await q(db, s, {"listLimit": 1, "listFields": ["mission"]}, AI_TEXT))["submissions"]


async def test_injection_safe(db: AsyncSession) -> None:
    s = await seed(db)
    nasty = "x'); DROP TABLE submissions; --"
    assert await count(db, s, {"field": "org_name", "op": "eq", "value": nasty}) == 0
    assert await count(db, s, {"field": "mission", "op": "contains", "value": nasty}) == 0
    assert (
        await count(db, s, {"field": "areas", "op": "includes_any", "values": [nasty, "?|"]}) == 0
    )
    with pytest.raises(QueryError):
        await count(db, s, {"field": "founded", "op": "gte", "value": nasty})
    for bad in ("data->>'x'", "Org_name", "a b", "x;--"):
        with pytest.raises(ValidationError):
            Query.model_validate({"where": [{"field": bad, "op": "answered"}]})
    with pytest.raises(ValidationError):
        Query.model_validate({"where": [], "sql": "select 1"})
    with pytest.raises(ValidationError):
        Query.model_validate({"limit": 10_000})
    with pytest.raises(QueryError):
        await count(db, s, {"field": "not_a_question", "op": "answered"})
    assert int(await db.scalar(select(func.count()).select_from(Submission)) or 0) == 6


async def test_submission_where_and_describe(db: AsyncSession) -> None:
    s = await seed(db)
    cat = await cat_mod.load(db, s.form)
    where = Where.model_validate(
        {
            "where": [
                {"field": "areas", "op": "includes_any", "values": ["disability"]},
                {"field": "member_age", "op": "gte", "value": 50},
            ]
        }
    )
    clauses = submission_where(cat, where, TZ)
    seqs = (
        await db.scalars(
            select(Submission.seq).where(
                Submission.form_id == s.form.id, Submission.deleted_at.is_(None), *clauses
            )
        )
    ).all()
    assert seqs == [4]
    text = describe(cat, where)
    assert text == (
        "Submissions where “Areas of work” includes “Disability rights” and"
        " “Member age” is at least 50"
    )
