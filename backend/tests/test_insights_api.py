"""Insights summaries and "Ask your submissions": counts, filters, versions, permissions, the
"Allow AI to read answers" setting, token caps, audit, and what is (never) sent to the AI."""

from __future__ import annotations

import asyncio
import gc
import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.fake import ScriptedProvider, turn
from app.ai.types import ChatMessage, TurnResult
from app.api.v1.ai import get_ai_provider
from app.config import Settings
from app.insights import ask as ask_mod
from app.models import AuditLog, FormPermission, FormRole, OrgMembership, OrgRole, User
from tests.conftest import RecordingQueue, login, make_client
from tests.helpers import admin_client
from tests.insights_fixture import Seeded, seed

SECRETS = ("A111111", "A222222", "a@example.org", "y@example.org")
ANSWER_TEXT = ("Reef Watch", "Protect reefs", "Sports and climate clubs")


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        oidc_issuer=None,
        public_url="http://testserver",
        ai_provider="fake",
        ai_provider_label="Test AI",
    )


@pytest.fixture
def provider() -> ScriptedProvider:
    return ScriptedProvider([])


@pytest.fixture
def app(app: Any, provider: ScriptedProvider) -> Any:
    app.dependency_overrides[get_ai_provider] = lambda: provider
    return app


def events(text: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in text.split("\n\n"):
        lines = dict(
            line.split(": ", 1)
            for line in block.splitlines()
            if not line.startswith(":") and ": " in line
        )
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


async def setup(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue, **kw: Any
) -> Seeded:
    await admin_client(client, db, settings, queue)
    return await seed(db, **kw)


async def ask(client: AsyncClient, fid: str, text: str) -> list[tuple[str, dict[str, Any]]]:
    res = await client.post(f"/api/v1/forms/{fid}/ask/sessions", json={})
    assert res.status_code == 200, res.text
    sid = res.json()["id"]
    res = await client.post(
        f"/api/v1/forms/{fid}/ask/sessions/{sid}/messages", json={"content": text}
    )
    assert res.status_code == 200, res.text
    return events(res.text)


def by(items: list[dict[str, Any]], key: str = "key") -> dict[Any, dict[str, Any]]:
    return {i[key]: i for i in items}


async def test_insights_summaries(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    res = await client.get(f"/api/v1/forms/{fid}/insights")
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["total"] == 5
    qs = by(out["questions"])
    areas = qs["areas"]
    assert areas["kind"] == "choice" and areas["multi"] and areas["answered"] == 4
    bars = by(areas["bars"])
    assert {k: b["count"] for k, b in bars.items()} == {
        "disability": 2,
        "climate": 2,
        "youth": 2,
        "health": 1,
    }
    assert (
        bars["disability"]["percent"] == 50.0 and bars["disability"]["label"] == "Disability rights"
    )
    assert areas["other"]["count"] == 1 and areas["other"]["texts"] == [
        {"text": "Fishing", "count": 1}
    ]
    assert areas["noAnswer"] == 1
    atoll = qs["atoll"]
    assert {b["key"]: b["count"] for b in atoll["bars"]} == {"male": 2, "addu": 2}
    assert atoll["other"]["texts"][0]["text"] == "Fuvahmulah"
    reg = qs["registered"]
    assert [(b["label"], b["count"]) for b in reg["bars"]] == [("Yes", 3), ("No", 2)]
    staff = qs["staff"]
    assert staff["kind"] == "number" and staff["answered"] == 4
    assert staff["stats"] == {"min": 2, "avg": 5.75, "median": 5.5, "max": 10, "sum": 23}
    assert sum(b["count"] for b in staff["bins"]) == 4
    rating = qs["rating"]
    assert [b["label"] for b in rating["bins"]] == ["1", "2", "3", "4", "5"]
    assert [b["count"] for b in rating["bins"]] == [1, 0, 1, 1, 1]
    founded = qs["founded"]
    assert founded["kind"] == "date" and founded["bucket"] == "year"
    assert [(b["label"], b["count"]) for b in founded["bars"]] == [
        ("2010", 1),
        ("2015", 1),
        ("2019", 1),
        ("2021", 1),
    ]
    mission = qs["mission"]
    assert mission["kind"] == "text" and mission["answered"] == 5
    assert [e["ref"] for e in mission["examples"]] == [5, 4, 3]
    nid = qs["national_id"]
    assert nid["kind"] == "sensitive" and nid["answered"] == 3
    assert all(e["text"].startswith("••••") for e in nid["examples"])
    assert "A333333" not in res.text and "A111111" not in res.text
    assert qs["logo"]["kind"] == "file" and qs["logo"]["answered"] == 1
    assert "member1_name" not in qs  # read as rows of the repeater
    rep = by(out["repeaters"])["members"]
    assert (rep["rows"], rep["submissions"], rep["mapped"]) == (7, 4, True)
    age = by(rep["questions"])["member_age"]
    assert age["answered"] == 6 and age["stats"]["max"] == 52

    # Filters: status, version, conditions.
    out = (await client.get(f"/api/v1/forms/{fid}/insights?status=new")).json()
    assert out["total"] == 2
    out = (await client.get(f"/api/v1/forms/{fid}/insights?version=1")).json()
    assert out["total"] == 2 and by(out["repeaters"])["members"]["rows"] == 3
    where = json.dumps({"where": [{"field": "areas", "op": "includes_any", "values": ["climate"]}]})
    out = (await client.get(f"/api/v1/forms/{fid}/insights", params={"where": where})).json()
    assert out["total"] == 2
    bad = json.dumps({"where": [{"field": "nope", "op": "answered"}]})
    res = await client.get(f"/api/v1/forms/{fid}/insights", params={"where": bad})
    assert res.status_code == 422


async def test_every_bar_opens_its_submissions(
    client: AsyncClient, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    """A bar's conditions select exactly the submissions it counts (the click-through)."""
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    out = (await client.get(f"/api/v1/forms/{fid}/insights")).json()
    checked = 0
    for q in out["questions"]:
        for bar in [*q.get("bars", []), *([q["other"]] if "other" in q else [])]:
            if q["kind"] == "number":
                continue
            res = await client.get(
                f"/api/v1/forms/{fid}/submissions",
                params={"where": json.dumps({"where": bar["where"]})},
            )
            assert res.status_code == 200, res.text
            assert res.json()["total"] == bar["count"], (q["key"], bar)
            checked += 1
    assert checked > 10
    # The export takes the same conditions; a bad one is refused up front.
    res = await client.post(
        f"/api/v1/forms/{fid}/exports", json={"where": [{"field": "nope", "op": "answered"}]}
    )
    assert res.status_code == 422


async def test_ask_how_many_ticked(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    seen: dict[str, Any] = {}

    async def answer(messages: list[ChatMessage]) -> TurnResult:
        result = messages[-1].tool_results[0].content
        seen.update(result)
        n = result["matched"]["submissions"]
        return turn(f"{n} of 5 submissions ticked Disability rights.")

    provider.steps.extend(
        [
            turn(
                calls=[
                    (
                        "query_submissions",
                        {
                            "where": [
                                {"field": "areas", "op": "includes_any", "values": ["disability"]}
                            ]
                        },
                    )
                ]
            ),
            answer,
        ]
    )
    evs = await ask(client, fid, "How many CSOs want to know about disability rights?")
    assert [n for n, _ in evs] == ["tool.applied", "message.delta", "link", "done"]
    step = evs[0][1]
    assert step["matched"] == {"submissions": 2}
    assert step["description"] == ("Submissions where “Areas of work” includes “Disability rights”")
    assert step["where"]["where"][0]["field"] == "areas"
    assert evs[1][1]["text"] == "2 of 5 submissions ticked Disability rights."
    assert seen["queryId"] == "q1"
    # Reading answers is off: the tool isn't offered, and no answer text went out.
    call = provider.calls[0]
    assert [t.name for t in call.tools] == ["query_submissions", "show_result"]
    assert "Reading answers is OFF" in call.system and "Disability rights" in call.system
    sent = provider.sent_text()
    for secret in (*SECRETS, *ANSWER_TEXT):
        assert secret not in sent
    # Transcript and audit.
    state = (await client.get(f"/api/v1/forms/{fid}/ask")).json()
    assert [m["role"] for m in state["messages"]] == ["user", "assistant"]
    assert state["messages"][1]["content"]["steps"][0]["matched"] == {"submissions": 2}
    assert state["readAnswers"] is False and state["providerLabel"] == "Test AI"
    row = await db.scalar(select(AuditLog).where(AuditLog.action == "ai.ask"))
    assert row is not None and row.meta["toolCalls"] == 1 and row.meta["outcome"] == "ok"
    assert "disability" not in json.dumps(row.meta).lower()
    # The builder's assistant keeps its own chat.
    res = await client.post(f"/api/v1/forms/{fid}/ai/sessions", json={})
    assert (
        res.status_code == 200 and res.json()["id"] != state["id"] and res.json()["messages"] == []
    )


async def test_ask_summary_with_read_answers(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    # Owners turn it on; it is off by default.
    assert (await client.get(f"/api/v1/forms/{fid}")).json()["aiReadAnswers"] is False
    res = await client.patch(f"/api/v1/forms/{fid}", json={"aiReadAnswers": True})
    assert res.status_code == 200 and res.json()["aiReadAnswers"] is True

    async def summarise(messages: list[ChatMessage]) -> TurnResult:
        results = messages[-1].tool_results
        assert results[0].content["returned"] == 2
        assert results[1].is_error and "can't be read" in results[1].content["error"]
        assert results[2].is_error  # contact details never
        return turn(
            calls=[
                ("query_submissions", {"groupBy": [{"field": "atoll"}]}),
            ]
        )

    provider.steps.extend(
        [
            turn(
                calls=[
                    (
                        "read_answers",
                        {
                            "fields": ["mission"],
                            "where": [{"field": "mission", "op": "contains", "value": "climate"}],
                        },
                    ),
                    ("read_answers", {"fields": ["national_id"]}),
                    ("read_answers", {"fields": ["contact"]}),
                ]
            ),
            summarise,
            turn(calls=[("show_result", {"queryId": "q1", "display": "bar", "title": "By atoll"})]),
            turn("Two missions mention climate: reef protection and youth climate clubs."),
        ]
    )
    evs = await ask(client, fid, "Summarise the missions that mention climate")
    names = [n for n, _ in evs]
    assert names == [
        "tool.applied",
        "tool.error",
        "tool.error",
        "tool.applied",
        "chart",
        "message.delta",
        "link",
        "done",
    ]
    read_step = evs[0][1]
    assert read_step["fields"] == ["mission"] and read_step["count"] == 2
    assert "Protect reefs" not in json.dumps(read_step)  # the transcript never keeps the text
    chart = evs[4][1]
    assert chart["title"] == "By atoll" and chart["display"] == "bar"
    assert {r["label"]: r["values"]["count"] for r in chart["rows"]} == {
        "Malé": 2,
        "Addu": 2,
        "Other": 1,
    }
    call = provider.calls[0]
    assert "read_answers" in [t.name for t in call.tools]
    assert "Reading answers is ON" in call.system and "Test AI" in call.system
    sent = provider.sent_text()
    assert "Protect reefs" in sent  # allowed now
    for secret in SECRETS:
        assert secret not in sent
    rows = (await db.scalars(select(AuditLog).where(AuditLog.action == "ai.read_answers"))).all()
    assert [(r.meta["fields"], r.meta["count"]) for r in rows] == [(["mission"], 2)]
    stored = (await client.get(f"/api/v1/forms/{fid}/ask")).json()["messages"][1]["content"]
    assert "Protect reefs" not in json.dumps(stored)
    assert stored["charts"][0]["title"] == "By atoll"


async def test_read_answers_refused_when_off_and_capped(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    # Off: a call to it (the model invents it) is refused and nothing is read.
    provider.steps.extend(
        [turn(calls=[("read_answers", {"fields": ["mission"]})]), turn("I can't.")]
    )
    evs = await ask(client, fid, "Summarise")
    assert evs[0][0] == "tool.error"
    assert "Protect reefs" not in provider.sent_text()
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "ai.read_answers")) is None

    # On: limits per call and in all.
    await client.patch(f"/api/v1/forms/{fid}", json={"aiReadAnswers": True})
    monkeypatch.setattr(ask_mod, "READ_TOTAL_CHARS", 120)
    got: dict[str, Any] = {}

    async def check(messages: list[ChatMessage]) -> TurnResult:
        got["first"] = messages[-1].tool_results[0]
        got["second"] = messages[-1].tool_results[1]
        return turn("ok")

    provider.steps.extend(
        [
            turn(
                calls=[
                    ("read_answers", {"fields": ["mission", "org_name"], "maxChars": 50}),
                    ("read_answers", {"fields": ["mission"], "limit": 500}),
                ]
            ),
            check,
        ]
    )
    await ask(client, fid, "Summarise again")
    first = got["first"].content
    assert first["truncated"] is True and 0 < first["returned"] < 5
    assert all(len(a.get("mission", "")) <= 50 for a in first["answers"])
    assert got["second"].is_error  # more than 200 submissions per call


async def test_ask_permissions(
    client: AsyncClient,
    app: Any,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    users = {}
    for email, role in (
        ("viewer@example.org", FormRole.VIEWER),
        ("editor@example.org", FormRole.EDITOR),
        ("other@example.org", None),
    ):
        user = User(email=email, display_name=email)
        db.add(user)
        await db.flush()
        db.add(OrgMembership(org_id=s.org.id, user_id=user.id, role=OrgRole.MEMBER))
        if role:
            db.add(FormPermission(form_id=s.form.id, user_id=user.id, role=role))
        users[email] = user
    await db.commit()
    mine = (await client.post(f"/api/v1/forms/{fid}/ask/sessions", json={})).json()["id"]
    async with make_client(app) as viewer:
        await login(viewer, queue, "viewer@example.org")
        assert (await viewer.get(f"/api/v1/forms/{fid}/insights")).status_code == 200
        provider.steps.extend(
            [
                turn(
                    calls=[("query_submissions", {"listLimit": 5, "listFields": ["national_id"]})]
                ),
                turn(calls=[("query_submissions", {"listLimit": 5, "listFields": ["org_name"]})]),
                turn("Done."),
            ]
        )
        evs = await ask(viewer, fid, "List the organisations")
        # Sensitive answers are refused for viewers and everyone else alike; free text is off.
        assert [n for n, _ in evs][:2] == ["tool.error", "tool.error"]
        # Another person's chat is invisible; only owners change the setting.
        res = await viewer.post(
            f"/api/v1/forms/{fid}/ask/sessions/{mine}/messages", json={"content": "x"}
        )
        assert res.status_code == 404
        assert (
            await viewer.patch(f"/api/v1/forms/{fid}", json={"aiReadAnswers": True})
        ).status_code == 403
    async with make_client(app) as editor:
        await login(editor, queue, "editor@example.org")
        assert (
            await editor.patch(f"/api/v1/forms/{fid}", json={"aiReadAnswers": True})
        ).status_code == 403
    async with make_client(app) as other:
        await login(other, queue, "other@example.org")
        assert (await other.get(f"/api/v1/forms/{fid}/insights")).status_code in (403, 404)
        assert (await other.post(f"/api/v1/forms/{fid}/ask/sessions", json={})).status_code in (
            403,
            404,
        )


async def test_ask_hidden_without_a_provider(
    client: AsyncClient, app: Any, db: AsyncSession, settings: Settings, queue: RecordingQueue
) -> None:
    from fastapi import HTTPException

    def off() -> None:
        raise HTTPException(404, "ai_disabled")

    app.dependency_overrides[get_ai_provider] = off
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    assert (await client.get(f"/api/v1/forms/{fid}/ask")).status_code == 404
    assert (await client.post(f"/api/v1/forms/{fid}/ask/sessions", json={})).status_code == 404
    # Insights needs no AI.
    assert (await client.get(f"/api/v1/forms/{fid}/insights")).status_code == 200


def test_tools_offered() -> None:
    assert [t.name for t in ask_mod.tool_specs(False)] == ["query_submissions", "show_result"]
    specs = {t.name: t for t in ask_mod.tool_specs(True)}
    assert set(specs) == {"query_submissions", "read_answers", "show_result"}
    params = specs["query_submissions"].parameters
    assert "$defs" not in json.dumps(params) and "where" in params["properties"]
    assert uuid  # imported for fixtures elsewhere


async def test_ask_link_is_the_counted_answer(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    """A reply "2 of 5 ticked X" links to the 2 (the group the reply names), not to all 5; a
    reply quoting several groups links to the whole breakdown."""
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    provider.steps.extend(
        [
            turn(calls=[("query_submissions", {"groupBy": [{"field": "areas"}]})]),
            turn("2 of 5 submissions ticked Disability rights."),
        ]
    )
    evs = await ask(client, fid, "How many want to know about disability?")
    link = dict(evs)["link"]
    assert (link["kind"], link["count"], link["total"]) == ("group", 2, 5)
    assert link["where"]["where"] == [
        {"field": "areas", "op": "includes_any", "value": None, "values": ["disability"]}
    ]
    assert link["description"] == "Submissions where “Areas of work” includes “Disability rights”"
    res = await client.get(
        f"/api/v1/forms/{fid}/submissions", params={"where": json.dumps(link["where"])}
    )
    assert res.json()["total"] == 2
    stored = (await client.get(f"/api/v1/forms/{fid}/ask")).json()["messages"][-1]["content"]
    assert stored["link"] == link

    provider.steps.extend(
        [
            turn(calls=[("query_submissions", {"groupBy": [{"field": "atoll"}]})]),
            turn("By atoll: Malé 2, Addu 2 and Fuvahmulah 1 (written in as Other)."),
        ]
    )
    link = dict(await ask(client, fid, "Breakdown by atoll"))["link"]
    assert link["kind"] == "breakdown" and link["count"] == 5
    assert link["where"] == {"where": [], "whereAny": []}

    # A filtered count beats the total it is "of".
    provider.steps.extend(
        [
            turn(calls=[("query_submissions", {})]),
            turn(
                calls=[
                    (
                        "query_submissions",
                        {"where": [{"field": "registered", "op": "eq", "value": True}]},
                    )
                ]
            ),
            turn("3 of 5 submissions are registered."),
        ]
    )
    link = dict(await ask(client, fid, "How many are registered?"))["link"]
    assert (link["kind"], link["count"], link["queryId"]) == ("count", 3, "q2")


async def test_ask_who_lists_submissions_without_sending_names(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    """A loose option word matches the one option it names; "who" lists the matching
    submissions with the name question for the person, while the AI gets only counts."""
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    seen: dict[str, Any] = {}

    async def listed(messages: list[ChatMessage]) -> TurnResult:
        seen.update(messages[-1].tool_results[0].content)
        return turn("2 organisations want to know about Disability rights. They are listed below.")

    where = [{"field": "areas", "op": "includes_any", "values": ["RIGHTS"]}]
    provider.steps.extend(
        [
            turn(calls=[("query_submissions", {"where": where})]),
            turn(calls=[("show_result", {"queryId": "q1", "display": "list"})]),
            listed,
        ]
    )
    evs = await ask(client, fid, "who want to know about rights")
    assert [n for n, _ in evs] == ["tool.applied", "chart", "message.delta", "link", "done"]
    step = evs[0][1]
    assert step["matched"] == {"submissions": 2}
    assert step["description"] == "Submissions where “Areas of work” includes “Disability rights”"
    chart = evs[1][1]
    assert chart["display"] == "list" and chart["columns"] == ["org_name"]
    assert chart["columnLabels"] == {"org_name": "Organisation name"}
    assert chart["total"] == 2 and not chart["truncated"]
    assert sorted(r["values"]["org_name"] for r in chart["rows"]) == [
        "Access For All",
        "Care Network",
    ]
    assert all(r["label"] == f"#{r['ref']}" for r in chart["rows"])
    assert seen == {"shown": True, "listed": 2, "matched": 2}
    sent = provider.sent_text()
    assert "Access For All" not in sent and "Care Network" not in sent
    assert "matched to the option" in sent  # the note tells the AI what it counted
    link = dict(evs)["link"]
    assert (link["kind"], link["count"]) == ("count", 2)

    # A word in several options is an error naming them; contact details are never listed.
    provider.steps.extend(
        [
            turn(
                calls=[
                    (
                        "query_submissions",
                        {"where": [{"field": "areas", "op": "eq", "value": "i"}]},
                    ),
                    ("query_submissions", {}),
                    ("show_result", {"queryId": "q1", "display": "list", "fields": ["contact"]}),
                ]
            ),
            turn("Sorry."),
        ]
    )
    evs = await ask(client, fid, "who")
    assert [n for n, _ in evs][:3] == ["tool.applied", "tool.applied", "tool.error"]
    one = ask_mod.Query.model_validate(
        {"where": [{"field": "areas", "op": "includes_any", "values": ["rights", "a"]}]}
    )
    assert one.where[0].values == ["rights", "a"]


async def test_ask_tool_database_error_is_a_tool_error(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A query the database refuses fails that call only; the answer still completes and is
    stored (the session stays usable)."""
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    real = ask_mod.run_query
    calls = 0

    async def flaky(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            await args[0].execute(text("SELECT 1/0"))  # a real database error
        return await real(*args, **kwargs)

    monkeypatch.setattr(ask_mod, "run_query", flaky)
    provider.steps.extend(
        [
            turn(calls=[("query_submissions", {})]),
            turn(calls=[("query_submissions", {})]),
            turn("5 submissions."),
        ]
    )
    evs = await ask(client, fid, "How many?")
    assert [n for n, _ in evs] == ["tool.error", "tool.applied", "message.delta", "link", "done"]
    assert evs[0][1]["error"] == "database"
    assert "division" not in provider.sent_text()
    stored = (await client.get(f"/api/v1/forms/{fid}/ask")).json()["messages"][-1]["content"]
    assert stored["status"] == "ok" and stored["text"] == "5 submissions."


async def test_ask_stream_dropped_mid_answer(
    app: Any,
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
    redis: Any,
) -> None:
    """Regression: the connection closing (a proxy timeout, a closed tab) while the AI is
    still answering, after a tool call that queried the database. The stream used to touch
    the request's expired ORM objects there (MissingGreenlet) and left a queue getter
    pending. Now the stop is recorded, the lock is released and nothing raises."""
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    sid = (await client.post(f"/api/v1/forms/{fid}/ask/sessions", json={})).json()["id"]
    never = asyncio.Event()

    async def hang(messages: list[ChatMessage]) -> TurnResult:
        await never.wait()
        raise AssertionError("not reached")

    where = [{"field": "areas", "op": "includes_any", "values": ["climate"]}]
    provider.steps.extend([turn(calls=[("query_submissions", {"where": where})]), hang])
    path = f"/api/v1/forms/{fid}/ask/sessions/{sid}/messages"
    cookies = "; ".join(f"{k}={v}" for k, v in client.cookies.items())
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/json"),
            (b"cookie", cookies.encode()),
            (b"x-csrf-token", client.headers["X-CSRF-Token"].encode()),
        ],
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 50000),
    }
    body = json.dumps({"content": "Which ones work on climate?"}).encode()
    sent: list[dict[str, Any]] = []
    gone = asyncio.Event()
    requested = False

    async def receive() -> dict[str, Any]:
        nonlocal requested
        if not requested:
            requested = True
            return {"type": "http.request", "body": body, "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)
        chunk = message.get("body", b"") if message["type"] == "http.response.body" else b""
        if b"tool.applied" in chunk:
            gone.set()  # the tool ran against the database; now the client goes away

    loop = asyncio.get_running_loop()
    errors: list[dict[str, Any]] = []
    loop.set_exception_handler(lambda _loop, ctx: errors.append(ctx))
    try:
        await asyncio.wait_for(app(scope, receive, send), 20)
        await asyncio.sleep(0.05)
        gc.collect()
    finally:
        loop.set_exception_handler(None)
    assert sent[0]["type"] == "http.response.start" and sent[0]["status"] == 200
    assert gone.is_set()
    assert not errors, errors  # e.g. "Task was destroyed but it is pending!"
    assert not await redis.exists(f"ai:lock:{sid}")
    stored = (await client.get(f"/api/v1/forms/{fid}/ask")).json()["messages"]
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[1]["content"]["status"] == "cancelled"
    rows = (await db.scalars(select(AuditLog).where(AuditLog.action == "ai.ask"))).all()
    assert [r.meta["outcome"] for r in rows] == ["cancelled"]
    # The chat is free again: the next question is answered.
    provider.steps.append(turn("2 of 5 work on climate."))
    evs = await ask(client, fid, "And now?")
    assert dict(evs)["message.delta"]["text"] == "2 of 5 work on climate."


async def test_ask_stream_keeps_a_quiet_connection_open(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While the AI is quiet the stream sends comment lines, so proxies don't close it."""
    from app.api.v1 import insights as insights_api

    monkeypatch.setattr(insights_api, "HEARTBEAT_SECONDS", 0.05)
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)

    async def slow(messages: list[ChatMessage]) -> TurnResult:
        await asyncio.sleep(0.3)
        return turn("5 submissions.")

    provider.steps.append(slow)
    res = await client.post(f"/api/v1/forms/{fid}/ask/sessions", json={})
    sid = res.json()["id"]
    res = await client.post(
        f"/api/v1/forms/{fid}/ask/sessions/{sid}/messages", json={"content": "How many?"}
    )
    assert ": keep-alive" in res.text
    assert [n for n, _ in events(res.text)] == ["message.delta", "done"]
