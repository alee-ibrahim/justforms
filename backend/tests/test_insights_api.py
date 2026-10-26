"""Insights summaries and "Ask your submissions": counts, filters, versions, permissions, the
"Allow AI to read answers" setting, token caps, audit, and what is (never) sent to the AI."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
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
    assert [n for n, _ in evs] == ["tool.applied", "message.delta", "done"]
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
