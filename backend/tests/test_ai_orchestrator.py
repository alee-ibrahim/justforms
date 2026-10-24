"""The AI tool loop with a scripted provider: repair, limits, stop, errors, filled-in forms."""

from __future__ import annotations

import asyncio
from typing import Any

from app.ai.orchestrator import BudgetExceeded, run_request
from app.ai.providers.fake import ScriptedProvider, turn
from app.ai.tools import WorkingCopy
from app.ai.types import ChatMessage, ProviderError, TurnResult, Usage
from tests.test_ai_tools import base


async def go(provider: ScriptedProvider, **kwargs: Any) -> Any:
    defaults: dict[str, Any] = {
        "working": WorkingCopy(base()),
        "mode": "edit",
        "language": "en",
        "history": [],
        "request": ChatMessage("user", text="Add a phone question"),
        "max_tool_calls": 40,
        "max_output_tokens": 1000,
        "turn_seconds": 5,
    }
    return await run_request(provider, **{**defaults, **kwargs})


PHONE = ("add_field", {"parentId": "page_1", "field": {"type": "phone", "label": "Phone"}})


async def test_happy_path_streams_steps_and_text() -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    async def emit(name: str, data: dict[str, Any]) -> None:
        events.append((name, data))

    provider = ScriptedProvider([turn(calls=[PHONE]), turn("I added a phone question.")])
    working = WorkingCopy(base())
    out = await go(provider, working=working, emit=emit)
    assert out.status == "ok" and out.changed and out.text == "I added a phone question."
    assert [e["id"] for e in out.working.schema["pages"][0]["elements"]][-1] == "phone"
    # The caller's working copy is untouched until it takes the outcome.
    assert "phone" not in str(working.schema)
    assert [n for n, _ in events] == ["tool.applied", "message.delta"]
    assert events[0][1] == {
        "tool": "add_field",
        "ok": True,
        "action": "Added",
        "label": "Phone",
        "targetId": "phone",
    }
    assert out.usage.input_tokens == 200 and out.usage.output_tokens == 40
    # The provider saw the form, the tools and the tool result.
    first, second = provider.calls
    assert '"id":"email"' in first.system and "add_field" in {t.name for t in first.tools}
    assert second.messages[-1].tool_results[0].content == {"id": "phone"}


async def test_validation_failure_goes_back_and_the_model_repairs() -> None:
    bad = (
        "add_field",
        {"parentId": "page_1", "field": {"type": "number", "label": "Age", "min": 9, "max": 1}},
    )
    fixed = (
        "add_field",
        {"parentId": "page_1", "field": {"type": "number", "label": "Age", "min": 1, "max": 9}},
    )
    provider = ScriptedProvider([turn(calls=[bad]), turn(calls=[fixed]), turn("Added age.")])
    out = await go(provider)
    assert out.status == "ok"
    assert [s["ok"] for s in out.steps] == [False, True]
    assert "min must not exceed max" in out.steps[0]["error"]
    error_result = provider.calls[1].messages[-1].tool_results[0]
    assert error_result.is_error and "min must not exceed max" in error_result.content["error"]


async def test_unparseable_arguments_are_reported_to_the_model() -> None:
    from app.ai.types import ToolCall

    broken = TurnResult(
        "", [ToolCall("c1", "add_field", {}, arguments_error="not valid JSON")], Usage(1, 1)
    )
    provider = ScriptedProvider([broken, turn("Sorry.")])
    out = await go(provider)
    assert out.status == "ok" and not out.changed
    assert out.steps[0]["ok"] is False


async def test_tool_limit() -> None:
    provider = ScriptedProvider(
        [turn(calls=[PHONE, ("get_form", {})]), turn(calls=[("get_form", {})])]
    )
    out = await go(provider, max_tool_calls=2)
    assert out.status == "error" and out.error == "tool_limit"


async def test_too_many_errors_gives_up() -> None:
    bad = ("remove_field", {"id": "nope"})
    provider = ScriptedProvider([turn(calls=[bad] * 6), turn(calls=[bad] * 6), turn("never")])
    out = await go(provider)
    assert out.status == "error" and out.error == "no_valid_result"


async def test_wall_clock() -> None:
    async def slow(_: list[ChatMessage]) -> TurnResult:
        await asyncio.sleep(5)
        return turn("late")

    out = await go(ScriptedProvider([slow]), turn_seconds=0.05)
    assert out.status == "error" and out.error == "timeout"


async def test_stop_between_calls_discards_the_changes() -> None:
    stop = asyncio.Event()

    async def first(_: list[ChatMessage]) -> TurnResult:
        stop.set()
        return turn(calls=[PHONE])

    async def should_cancel() -> bool:
        return stop.is_set()

    provider = ScriptedProvider([first, turn("never")])
    working = WorkingCopy(base())
    out = await go(provider, working=working, should_cancel=should_cancel)
    assert out.status == "cancelled"
    assert len(provider.calls) == 1
    assert "phone" not in str(working.schema)


async def test_task_cancellation_propagates() -> None:
    started = asyncio.Event()

    async def hang(_: list[ChatMessage]) -> TurnResult:
        started.set()
        await asyncio.sleep(30)
        return turn()

    task = asyncio.create_task(go(ScriptedProvider([hang])))
    await started.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected cancellation")


async def test_provider_errors() -> None:
    out = await go(ScriptedProvider([ProviderError("unavailable", "HTTP 503")]))
    assert out.status == "error" and out.error == "provider_unavailable"
    out = await go(ScriptedProvider([ProviderError("bad_response")]))
    assert out.error == "provider_error"


async def test_budget_is_checked_before_each_call_and_charged() -> None:
    charged: list[int] = []
    calls = 0

    async def check() -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise BudgetExceeded

    async def charge(usage: Usage) -> None:
        charged.append(usage.total)

    out = await go(
        ScriptedProvider([turn(calls=[PHONE]), turn("x")]), check_budget=check, charge=charge
    )
    assert out.status == "error" and out.error == "ai_budget_exceeded"
    assert charged == [120]


async def test_filled_in_document_stops_at_once() -> None:
    provider = ScriptedProvider(
        [turn(calls=[("report_filled_in", {"note": "Someone filled this in"}), PHONE])]
    )
    out = await go(provider, working=WorkingCopy(base(), importing=True), mode="import")
    assert out.status == "filled_in" and out.working.filled_in == "Someone filled this in"
    assert len(out.steps) == 1 and len(provider.calls) == 1


async def test_dhivehi_forms_ask_for_thaana() -> None:
    provider = ScriptedProvider([turn("ok")])
    await go(provider, working=WorkingCopy(base("dv")), language="dv")
    assert "Thaana script" in provider.calls[0].system
    provider = ScriptedProvider([turn("ok")])
    await go(provider)
    assert "The form is in English" in provider.calls[0].system


async def test_history_is_sent_before_the_request() -> None:
    provider = ScriptedProvider([turn("ok")])
    history = [ChatMessage("user", text="Make a form"), ChatMessage("assistant", text="Done")]
    await go(provider, history=history)
    assert [m.text for m in provider.calls[0].messages] == [
        "Make a form",
        "Done",
        "Add a phone question",
    ]
