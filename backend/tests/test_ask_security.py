"""Ask your submissions: abuse and privacy regressions (allowances, one request per person,
query time limits, value counts, size caps, reading off, stored lists, untrusted answers)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import limits
from app.ai.providers.fake import ScriptedProvider, turn
from app.ai.types import ChatMessage, TurnResult
from app.api.v1.ai import get_ai_provider
from app.config import Settings
from app.insights import ask as ask_mod
from app.insights import catalogue
from app.insights.dsl import Condition
from app.models import (
    AiMessage,
    AuditLog,
    FormRecord,
    FormVersion,
    Organization,
    Submission,
    User,
)
from tests.conftest import RecordingQueue
from tests.helpers import admin_client, field
from tests.insights_fixture import Seeded, seed


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


def events(body: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in body.split("\n\n"):
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


async def open_chat(client: AsyncClient, fid: str, fresh: bool = False) -> str:
    res = await client.post(f"/api/v1/forms/{fid}/ask/sessions", json={"fresh": fresh})
    assert res.status_code == 200, res.text
    return str(res.json()["id"])


async def ask(client: AsyncClient, fid: str, question: str) -> list[tuple[str, dict[str, Any]]]:
    sid = await open_chat(client, fid)
    res = await client.post(
        f"/api/v1/forms/{fid}/ask/sessions/{sid}/messages", json={"content": question}
    )
    assert res.status_code == 200, res.text
    return events(res.text)


async def multi_choice_form(db: AsyncSession, subs: int, options: int = 40) -> FormRecord:
    opts = [{"value": f"o{i}", "label": f"Option {i}"} for i in range(options)]
    sch = {
        "schemaVersion": "1",
        "settings": {"title": "T"},
        "pages": [
            {
                "id": "p1",
                "elements": [
                    field("a", "multi_choice", label="A", options=opts),
                    field("b", "multi_choice", label="B", options=opts),
                ],
            }
        ],
    }
    org = Organization(name="O", slug=f"o-{uuid.uuid4().hex[:6]}")
    db.add(org)
    await db.flush()
    form = FormRecord(
        org_id=org.id, slug=f"f-{uuid.uuid4().hex[:6]}", title="T", draft_schema=sch, settings={}
    )
    db.add(form)
    await db.flush()
    v = FormVersion(
        form_id=form.id, version=1, schema=sch, schema_hash=hashlib.sha256(b"x").hexdigest()
    )
    db.add(v)
    await db.flush()
    form.current_version_id = v.id
    values = [o["value"] for o in opts]
    for i in range(subs):
        db.add(
            Submission(
                form_id=form.id,
                form_version_id=v.id,
                seq=i + 1,
                data={"a": values, "b": values},
                submitted_at=datetime.now(UTC),
                language="en",
            )
        )
    await db.commit()
    return form


# -- M2: allowance and one request per person ---------------------------------------------


async def test_budget_parallel_overshoot(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
    redis: Any,
) -> None:
    """Regression: four questions at once (on four forms) against a 1,000-token allowance
    all passed the check before any was charged and used 3,800 tokens. Now each provider
    call reserves its worst case first, and a person runs one AI request at a time."""
    settings.ai_daily_tokens_per_user = 1000
    await admin_client(client, db, settings, queue)
    forms = [await seed(db) for _ in range(4)]

    async def slow(messages: list[ChatMessage]) -> TurnResult:
        await asyncio.sleep(0.5)
        return turn("ok", tokens=(900, 50))

    provider.steps.extend([slow] * 4)
    sids = [await open_chat(client, str(f.form.id)) for f in forms]
    results = await asyncio.gather(
        *[
            client.post(
                f"/api/v1/forms/{f.form.id}/ask/sessions/{sid}/messages", json={"content": "q"}
            )
            for f, sid in zip(forms, sids, strict=True)
        ]
    )
    outs = [[e for e, _ in events(r.text)] for r in results]
    assert sum(1 for o in outs if "message.delta" in o) <= 1
    assert all(r.status_code in (200, 429) for r in results)
    user = await db.scalar(select(User).where(User.email == "admin@example.org"))
    assert user is not None
    used = int(await redis.get(limits.token_keys(settings, user.id, forms[0].org.id)[0]) or 0)
    # At most the allowance, plus the input estimate of one call that was stopped mid-way.
    assert used <= 1000 + 5000


async def test_fresh_chat_stops_the_running_answer(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    """Regression: "fresh" closed the chat but its answer kept running (and spending)."""
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    sid = await open_chat(client, fid)
    asked = asyncio.Event()

    async def hang(messages: list[ChatMessage]) -> TurnResult:
        asked.set()
        await asyncio.sleep(30)
        raise AssertionError("not reached")

    provider.steps.append(hang)

    async def reopen() -> None:
        await asked.wait()
        await open_chat(client, fid, fresh=True)

    start = time.monotonic()
    res, _ = await asyncio.wait_for(
        asyncio.gather(
            client.post(f"/api/v1/forms/{fid}/ask/sessions/{sid}/messages", json={"content": "q"}),
            reopen(),
        ),
        15,
    )
    assert time.monotonic() - start < 10
    assert [e for e, _ in events(res.text)][-2:] == ["cancelled", "done"]


async def test_a_new_question_elsewhere_stops_the_running_one(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    await admin_client(client, db, settings, queue)
    one, two = await seed(db), await seed(db)
    sid_one = await open_chat(client, str(one.form.id))
    sid_two = await open_chat(client, str(two.form.id))
    asked = asyncio.Event()

    async def hang(messages: list[ChatMessage]) -> TurnResult:
        asked.set()
        await asyncio.sleep(30)
        raise AssertionError("not reached")

    provider.steps.extend([hang, turn("5 submissions.")])

    async def second() -> Any:
        await asked.wait()
        return await client.post(
            f"/api/v1/forms/{two.form.id}/ask/sessions/{sid_two}/messages", json={"content": "q"}
        )

    first, other = await asyncio.wait_for(
        asyncio.gather(
            client.post(
                f"/api/v1/forms/{one.form.id}/ask/sessions/{sid_one}/messages",
                json={"content": "q"},
            ),
            second(),
        ),
        15,
    )
    assert "cancelled" in [e for e, _ in events(first.text)]
    assert dict(events(other.text))["message.delta"]["text"] == "5 submissions."


# -- M5: database time limits -------------------------------------------------------------


async def test_cartesian_group_by(db: AsyncSession, settings: Settings) -> None:
    """Regression: grouping by two multi-choice questions joined options x options rows per
    submission (1.5 s for one submission with 1000 options each). It is refused now."""
    form = await multi_choice_form(db, subs=3)
    cat = await catalogue.load(db, form)
    tools = ask_mod.Tools(db, cat, form.id, tz=settings.tz, read_allowed=False)
    start = time.monotonic()
    ok, content, _step = await tools.run(
        "query_submissions",
        {"groupBy": [{"field": "a"}, {"field": "b"}], "aggregates": [{"op": "count"}]},
    )
    assert not ok and "at most one multi-choice" in content["error"]
    assert time.monotonic() - start < 2
    ok, content, _ = await tools.run("query_submissions", {"groupBy": [{"field": "a"}]})
    assert ok and content["matched"]["submissions"] == 3


async def _active_sleeps(db: AsyncSession) -> int:
    return int(
        await db.scalar(
            text(
                "select count(*) from pg_stat_activity where state = 'active'"
                " and query ilike '%pg_sleep%' and pid <> pg_backend_pid()"
            )
        )
        or 0
    )


async def test_statement_timeout_stops_a_slow_query(
    db: AsyncSession, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = await seed(db)
    monkeypatch.setattr(ask_mod, "QUERY_TIMEOUT_SECONDS", 0.3)
    real = ask_mod.run_query

    async def slow(*args: Any, **kwargs: Any) -> dict[str, Any]:
        await args[0].execute(text("SELECT pg_sleep(5)"))
        return await real(*args, **kwargs)

    monkeypatch.setattr(ask_mod, "run_query", slow)
    tools = ask_mod.Tools(
        db, await catalogue.load(db, s.form), s.form.id, tz=settings.tz, read_allowed=False
    )
    start = time.monotonic()
    ok, content, step = await tools.run("query_submissions", {})
    assert not ok and step["error"] == "timeout" and "took longer" in content["error"]
    assert time.monotonic() - start < 3
    assert await _active_sleeps(db) == 0
    # The session is still usable for the next call.
    monkeypatch.setattr(ask_mod, "run_query", real)
    ok, content, _ = await tools.run("query_submissions", {})
    assert ok and content["matched"]["submissions"] == 5


async def test_cartesian_timeout_cancels_db(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: when the turn timed out during a long query, the query kept running in
    Postgres, the stream died with PendingRollbackError and the answer was recorded as
    "cancelled" with 0 tokens. Now the query is cancelled, the answer is stored with a fresh
    session as a timeout, and the tokens used are kept."""
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    monkeypatch.setattr(settings, "ai_turn_seconds", 1)
    real = ask_mod.run_query

    async def slow(*args: Any, **kwargs: Any) -> dict[str, Any]:
        await args[0].execute(text("SELECT pg_sleep(8)"))
        return await real(*args, **kwargs)

    monkeypatch.setattr(ask_mod, "run_query", slow)
    provider.steps.extend([turn(calls=[("query_submissions", {})]), turn("x")])
    start = time.monotonic()
    evs = await ask(client, fid, "q")
    assert time.monotonic() - start < 6
    assert ("error", {"code": "timeout"}) in evs
    await asyncio.sleep(0.5)
    assert await _active_sleeps(db) == 0
    stored = (await client.get(f"/api/v1/forms/{fid}/ask")).json()["messages"][-1]["content"]
    assert stored["status"] == "error" and stored["error"] == "timeout"
    row = await db.scalar(select(AuditLog).where(AuditLog.action == "ai.ask"))
    assert row is not None and row.meta["error"] == "timeout" and row.meta["tokensIn"] == 100


# -- L1: value counts ---------------------------------------------------------------------


def test_condition_value_count_is_validated() -> None:
    from pydantic import ValidationError

    for bad in (
        {"field": "_submitted", "op": "gt"},
        {"field": "staff", "op": "between", "values": [1]},
        {"field": "staff", "op": "lt", "values": [1, 2]},
        {"field": "atoll", "op": "eq"},
        {"field": "atoll", "op": "in", "values": []},
        {"field": "atoll", "op": "eq", "value": "a", "values": ["b"]},
    ):
        with pytest.raises(ValidationError):
            Condition.model_validate(bad)
    for good in (
        {"field": "staff", "op": "answered"},
        {"field": "staff", "op": "between", "values": [1, 3]},
        {"field": "atoll", "op": "eq", "value": False},
        {"field": "atoll", "op": "in", "values": ["a", "b"]},
    ):
        Condition.model_validate(good)


async def test_condition_without_value_internal_error(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
) -> None:
    """Regression: a model-written condition without a value raised an IndexError, the whole
    answer failed as "internal" and the audit recorded 0 tokens. It is a tool error now."""
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)
    provider.steps.extend(
        [
            turn(calls=[("query_submissions", {})]),
            turn(calls=[("query_submissions", {"where": [{"field": "_submitted", "op": "gt"}]})]),
            turn("5 submissions."),
        ]
    )
    evs = await ask(client, fid, "q")
    names = [n for n, _ in evs]
    assert names[:2] == ["tool.applied", "tool.error"] and "error" not in names
    assert dict(evs)["done"]["usage"]["in"] == 300


async def test_internal_error_keeps_the_tokens_used(
    client: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    queue: RecordingQueue,
    provider: ScriptedProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = await setup(client, db, settings, queue)
    fid = str(s.form.id)

    async def broken(self: Any, name: str, args: dict[str, Any]) -> Any:
        raise RuntimeError("bug")

    monkeypatch.setattr(ask_mod.Tools, "run", broken)
    provider.steps.extend([turn(calls=[("query_submissions", {})]), turn("x")])
    evs = await ask(client, fid, "q")
    assert ("error", {"code": "internal"}) in evs
    assert dict(evs)["done"]["usage"] == {"in": 100, "out": 20}
    row = await db.scalar(select(AuditLog).where(AuditLog.action == "ai.ask"))
    assert row is not None and row.meta["tokensIn"] == 100
    msgs = (await db.scalars(select(AiMessage).where(AiMessage.role == "assistant"))).all()
    assert msgs[-1].content["error"] == "internal"
