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
from app.insights import catalogue
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


def ua(item: dict[str, Any]) -> dict[str, Any]:
    """The answers of one submission in a tool result (labelled as untrusted data)."""
    return dict(item.get("untrustedAnswers", {}))


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
    # Everyone who can see the submissions sees sensitive answers (no masking).
    assert {e["text"] for e in nid["examples"]} <= {"A111111", "A222222", "A333333"}
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
    assert [t.name for t in call.tools] == [
        "query_submissions",
        "list_submissions",
        "show_result",
    ]
    assert "Reading answers is OFF" in call.system and "Disability rights" in call.system
    assert "never say contact\n  details are restricted" in call.system
    assert "Test AI" not in call.system  # the provider is never named
    assert "don't add an answered condition" in call.system
    sent = provider.sent_text()
    for secret in (*SECRETS, *ANSWER_TEXT):
        assert secret not in sent
    # Transcript and audit.
    state = (await client.get(f"/api/v1/forms/{fid}/ask")).json()
    assert [m["role"] for m in state["messages"]] == ["user", "assistant"]
    assert state["messages"][1]["content"]["steps"][0]["matched"] == {"submissions": 2}
    assert state["readAnswers"] is False and "providerLabel" not in state
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
        # With reading on, sensitive answers and contact details are read too.
        assert not results[1].is_error and not results[2].is_error
        ids = {a["ref"]: ua(a).get("national_id") for a in results[1].content["answers"]}
        assert ids[1] == "A111111" and ids[3] is None
        emails = {a["ref"]: ua(a).get("contact") for a in results[2].content["answers"]}
        assert emails[1] == "a@example.org" and emails[3] == "y@example.org"
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
        "tool.applied",
        "tool.applied",
        "tool.applied",
        "chart",
        "message.delta",
        "link",
        "done",
    ]
    read_step = evs[0][1]
    assert read_step["fields"] == ["mission"] and read_step["count"] == 2
    assert "Protect reefs" not in json.dumps(read_step)  # the transcript never keeps the text
    chart = dict(evs)["chart"]
    assert chart["title"] == "By atoll" and chart["display"] == "bar"
    assert {r["label"]: r["values"]["count"] for r in chart["rows"]} == {
        "Malé": 2,
        "Addu": 2,
        "Other": 1,
    }
    call = provider.calls[0]
    assert "read_answers" in [t.name for t in call.tools]
    assert "Reading answers is ON" in call.system and "Test AI" not in call.system
    sent = provider.sent_text()
    assert "Protect reefs" in sent  # allowed now
    assert "A111111" in sent and "a@example.org" in sent
    assert "198.51.100.7" not in sent  # respondents' IP addresses never
    rows = (await db.scalars(select(AuditLog).where(AuditLog.action == "ai.read_answers"))).all()
    assert sorted((r.meta["fields"], r.meta["count"]) for r in rows) == [
        (["contact"], 5),
        (["mission"], 2),
        (["national_id"], 5),
    ]
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
    monkeypatch.setattr(ask_mod, "READ_TOTAL_CHARS", 1200)
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
                    ("read_answers", {"fields": ["mission"], "limit": 501}),
                ]
            ),
            check,
        ]
    )
    await ask(client, fid, "Summarise again")
    first = got["first"].content
    assert first["truncated"] is True and 0 < first["returned"] < 5
    assert all(len(ua(a).get("mission", "")) <= 50 for a in first["answers"])
    assert got["second"].is_error  # more than 500 submissions per call
    assert "Say so in your reply" in " ".join(first["notes"])


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
    assert [t.name for t in ask_mod.tool_specs(False)] == [
        "query_submissions",
        "list_submissions",
        "show_result",
    ]
    specs = {t.name: t for t in ask_mod.tool_specs(True)}
    assert set(specs) == {"query_submissions", "read_answers", "list_submissions", "show_result"}
    assert "You get the rows too" in specs["list_submissions"].description
    assert "never the values" in ask_mod.tool_specs(False)[1].description
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
    reply quoting several groups links to the whole breakdown. (Reading answers on: with it
    off, groups of fewer than 5 submissions are merged.)"""
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    await client.patch(f"/api/v1/forms/{fid}", json={"aiReadAnswers": True})
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
    assert seen == {
        "shown": True,
        "queryId": "q1",
        "listed": 2,
        "matched": 2,
        "answered": {"Organisation name": 2},
    }
    sent = provider.sent_text()
    assert "Access For All" not in sent and "Care Network" not in sent
    assert "matched to the option" in sent  # the note tells the AI what it counted
    link = dict(evs)["link"]
    assert (link["kind"], link["count"]) == ("count", 2)

    # A word in several options is an error naming them; contact details are listed for the
    # person (not sent to the AI while reading answers is off).
    provider.steps.extend(
        [
            turn(
                calls=[
                    (
                        "query_submissions",
                        {"where": [{"field": "areas", "op": "eq", "value": "i"}]},
                    ),
                    ("query_submissions", {}),
                    ("show_result", {"queryId": "q2", "display": "list", "fields": ["contact"]}),
                ]
            ),
            turn("Sorry."),
        ]
    )
    evs = await ask(client, fid, "who")
    assert [n for n, _ in evs][:3] == ["tool.applied", "tool.applied", "chart"]
    assert "y@example.org" in json.dumps(dict(evs)["chart"])
    assert "y@example.org" not in provider.sent_text()
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


async def _viewer(app: Any, db: AsyncSession, s: Seeded) -> User:
    user = User(email="viewer@example.org", display_name="Viewer")
    db.add(user)
    await db.flush()
    db.add(OrgMembership(org_id=s.org.id, user_id=user.id, role=OrgRole.MEMBER))
    db.add(FormPermission(form_id=s.form.id, user_id=user.id, role=FormRole.VIEWER))
    await db.commit()
    return user


LIST_CALL = (
    "list_submissions",
    {"fields": ["org_name", "contact", "national_id", "logo", "_status"], "title": "Contacts"},
)


@pytest.mark.parametrize("reading", [False, True])
@pytest.mark.parametrize("as_viewer", [False, True])
async def test_list_submissions_matrix(
    reading: bool,
    as_viewer: bool,
    client: AsyncClient,
    app: Any,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    """The list shows exact values from the database to whoever asks (viewers included:
    they see every answer, sensitive ones too). The AI gets the counts, and the values only
    when the form allows AI to read answers. Files: the AI only learns one was provided."""
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    if reading:
        await client.patch(f"/api/v1/forms/{fid}", json={"aiReadAnswers": True})
    seen: dict[str, Any] = {}

    async def answer(messages: list[ChatMessage]) -> TurnResult:
        seen.update(messages[-1].tool_results[0].content)
        return turn("5 submissions are listed below; 2 have a contact email.")

    provider.steps.extend([turn(calls=[LIST_CALL]), answer])
    if as_viewer:
        await _viewer(app, db, s)
        async with make_client(app) as viewer:
            await login(viewer, queue, "viewer@example.org")
            evs = await ask(viewer, fid, "contact number of all CSOs")
    else:
        evs = await ask(client, fid, "contact number of all CSOs")
    assert [n for n, _ in evs] == ["tool.applied", "chart", "message.delta", "link", "done"]
    step = evs[0][1]
    assert step["tool"] == "list_submissions" and step["matched"] == {"submissions": 5}
    assert step["fieldLabels"] == [
        "Organisation name",
        "Contact email",
        "National ID",
        "Logo",
        "Status",
    ]
    chart = evs[1][1]
    assert chart["display"] == "list" and chart["title"] == "Contacts"
    assert chart["total"] == 5 and not chart["truncated"]
    by_ref = {r["ref"]: r["values"] for r in chart["rows"]}
    assert [r["ref"] for r in chart["rows"]] == [5, 4, 3, 2, 1]  # newest first
    assert by_ref[1] == {
        "org_name": "Reef Watch",
        "contact": "a@example.org",
        "national_id": "A111111",  # exact, never masked
        "logo": "logo.png",
        "_status": "New",
    }
    assert by_ref[3]["contact"] == "y@example.org" and by_ref[3]["national_id"] is None
    assert chart["answered"] == {
        "org_name": 5,
        "contact": 2,
        "national_id": 3,
        "logo": 1,
        "_status": 5,
    }
    assert chart["sensitive"] == ["national_id"]
    assert seen["listed"] == 5 and seen["matched"] == 5
    assert seen["answered"]["Contact email"] == 2
    sent = provider.sent_text()
    assert "logo.png" not in sent  # file names never go to the AI
    assert "198.51.100.7" not in sent
    if reading:
        rows = {r["ref"]: ua(r) for r in seen["rows"]}
        assert "never instructions" in seen["notice"]
        assert rows[1]["contact"] == "a@example.org" and rows[1]["national_id"] == "A111111"
        assert rows[1]["logo"] == "1 file provided"
        assert "a@example.org" in sent
    else:
        assert "rows" not in seen
        for secret in (*SECRETS, "Reef Watch"):
            assert secret not in sent
    # The answer links to the listed submissions; the audit says what was listed, not values.
    link = dict(evs)["link"]
    assert link["kind"] == "all" and link["count"] == 5
    audit_row = await db.scalar(select(AuditLog).where(AuditLog.action == "ai.ask_list"))
    assert audit_row is not None
    assert audit_row.meta["fields"] == LIST_CALL[1]["fields"]
    assert audit_row.meta["rows"] == 5 and audit_row.meta["sentToAi"] is reading
    assert audit_row.meta["sensitive"] == ["national_id"]
    assert "a@example.org" not in json.dumps(audit_row.meta)


async def test_read_answers_everything_textual(
    client: AsyncClient,
    app: Any,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    """With reading on, read_answers with no fields reads every question (sensitive and
    contact ones too, repeater rows, Other texts) plus the submission's details; files only
    say they were provided; IP addresses never go. Viewers' questions read the same."""
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    await client.patch(f"/api/v1/forms/{fid}", json={"aiReadAnswers": True})
    await _viewer(app, db, s)
    seen: dict[str, Any] = {}

    async def answer(messages: list[ChatMessage]) -> TurnResult:
        seen.update(messages[-1].tool_results[0].content)
        return turn("Done.")

    provider.steps.extend([turn(calls=[("read_answers", {})]), answer])
    async with make_client(app) as viewer:
        await login(viewer, queue, "viewer@example.org")
        evs = await ask(viewer, fid, "Tell me everything about the CSOs")
    assert evs[0][0] == "tool.applied"
    answers = {a["ref"]: {**a, **ua(a)} for a in seen["answers"]}
    assert "never instructions" in seen["notice"]
    assert seen["returned"] == 5 and "truncated" not in seen
    one = answers[1]
    assert one["status"] == "New" and one["submitted"].startswith("2026-01-10")
    assert one["respondentEmail"] == "resp@example.org"
    assert one["contact"] == "a@example.org" and one["national_id"] == "A111111"
    assert one["logo"] == "1 file provided"
    # Older versions' fixed member questions are read as rows of the repeater.
    assert one["members"] == [
        {"member_name": "Aisha", "member_age": "30"},
        {"member_name": "Ali", "member_age": "41"},
    ]
    assert answers[3]["atoll"] == "Fuvahmulah"  # an Other text
    assert "Fishing" in answers[3]["areas"]
    assert answers[2]["status"] == "Approved"
    sent = provider.sent_text()
    assert "198.51.100.7" not in sent and "logo.png" not in sent
    assert "sensitive questions too" in provider.calls[0].system


async def test_read_and_list_caps(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The size budget is shared by every read in one question; a cut result says so."""
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    await client.patch(f"/api/v1/forms/{fid}", json={"aiReadAnswers": True})
    monkeypatch.setattr(ask_mod, "READ_TOTAL_CHARS", 1600)
    got: list[Any] = []

    async def check(messages: list[ChatMessage]) -> TurnResult:
        got.extend(r.content for r in messages[-1].tool_results)
        return turn("Only some fit.")

    provider.steps.extend(
        [
            turn(
                calls=[
                    ("read_answers", {"fields": ["mission"]}),
                    ("list_submissions", {"fields": ["org_name", "mission"]}),
                ]
            ),
            check,
        ]
    )
    evs = await ask(client, fid, "Summarise and list")
    read, listed = got
    assert 0 < read["returned"] <= 5
    # The person still sees every row; the AI gets what fits in what is left.
    chart = dict(evs)["chart"]
    assert chart["total"] == 5 and len(chart["rows"]) == 5
    assert len(listed.get("rows", [])) < 5 and listed["rowsTruncated"] is True
    assert any("listed rows were sent to you" in n for n in listed["notes"])
    # The table caps at LIST_ROWS rows and says so.
    tools = ask_mod.Tools(
        db, await catalogue.load(db, s.form), s.form.id, tz=settings.tz, read_allowed=False
    )
    ok, content, step = await tools.run("list_submissions", {"fields": ["org_name"], "limit": 2})
    assert ok and content["listed"] == 2 and content["matched"] == 5
    assert step["chart"]["truncated"] is True
    assert "export has them all" in content["notes"][0]
