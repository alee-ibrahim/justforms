"""The tool loop (DESIGN 12.3): call the provider, run its tool calls against the working
copy, send the results back, and repeat until it stops calling tools.

Limits: ``max_tool_calls`` tool calls and ``turn_seconds`` per request, a token allowance
checked before every provider call, and a stop request checked between calls. A request that
does not finish leaves the working copy it was given untouched (the caller keeps the old one).
"""

from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from app.ai.limits import BudgetExceeded, estimate_input, run_stoppable, usage_of
from app.ai.prompts import Mode, system_prompt
from app.ai.tools import StepResult, WorkingCopy, compact, tool_specs
from app.ai.types import AIProvider, ChatMessage, ProviderError, ToolResult, Usage

log = logging.getLogger(__name__)

# After this many failed tool calls in one request the assistant gives up.
MAX_TOOL_ERRORS = 12

Emit = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class TurnOutcome:
    status: Literal["ok", "cancelled", "error", "filled_in"]
    working: WorkingCopy
    text: str = ""
    error: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    changed: bool = False


async def _never() -> bool:
    return False


async def _noop(*_: Any) -> None:
    return None


async def run_request(
    provider: AIProvider,
    *,
    working: WorkingCopy,
    mode: Mode,
    language: str,
    history: list[ChatMessage],
    request: ChatMessage,
    max_tool_calls: int,
    max_output_tokens: int,
    turn_seconds: float,
    emit: Emit = _noop,
    should_cancel: Callable[[], Awaitable[bool]] = _never,
    check_budget: Callable[[int], Awaitable[None]] = _noop,
    charge: Callable[[Usage], Awaitable[None]] = _noop,
) -> TurnOutcome:
    copy_ = WorkingCopy(
        copy.deepcopy(working.schema),
        importing=working.importing,
        flags=list(working.flags),
    )
    outcome = TurnOutcome(status="ok", working=copy_)
    tools = tool_specs(importing=working.importing)
    system = system_prompt(mode=mode, language=language, form_json=compact(copy_.schema))
    messages = [*history, request]
    used = errors = 0

    async def loop() -> None:
        nonlocal used, errors
        while True:
            if await should_cancel():
                outcome.status = "cancelled"
                return
            estimated = estimate_input(system, messages, tools)
            await check_budget(estimated)
            result = await provider.run_turn(
                system, messages, tools, max_output_tokens=max_output_tokens
            )
            usage = usage_of(result, estimated)
            outcome.usage.input_tokens += usage.input_tokens
            outcome.usage.output_tokens += usage.output_tokens
            await charge(usage)
            if result.text:
                await emit("message.delta", {"text": result.text})
            messages.append(
                ChatMessage(
                    "assistant",
                    text=result.text,
                    tool_calls=result.tool_calls,
                    provider_data=result.provider_data,
                )
            )
            if not result.tool_calls:
                outcome.text = result.text
                return
            results: list[ToolResult] = []
            for call in result.tool_calls:
                if used >= max_tool_calls:
                    outcome.status, outcome.error = "error", "tool_limit"
                    return
                used += 1
                if call.arguments_error:
                    message = f"Invalid arguments: {call.arguments_error}"
                    step = StepResult(False, {"error": message}, action=call.name, error=message)
                else:
                    step = copy_.run(call.name, call.arguments)
                outcome.changed = outcome.changed or step.changed
                entry: dict[str, Any] = {
                    "tool": call.name,
                    "ok": step.ok,
                    "action": step.action,
                    "label": step.label,
                    "targetId": step.target_id,
                }
                if not step.ok:
                    entry["error"] = step.error
                    errors += 1
                outcome.steps.append(entry)
                await emit("tool.applied" if step.ok else "tool.error", entry)
                results.append(ToolResult(call.id, call.name, step.result, is_error=not step.ok))
                if copy_.filled_in is not None:
                    break
            messages.append(ChatMessage("tool", tool_results=results))
            if copy_.filled_in is not None:
                outcome.status = "filled_in"
                return
            if errors >= MAX_TOOL_ERRORS:
                outcome.status, outcome.error = "error", "no_valid_result"
                return

    try:
        async with asyncio.timeout(turn_seconds):
            if await run_stoppable(loop, should_cancel):
                outcome.status = "cancelled"
    except TimeoutError:
        outcome.status, outcome.error = "error", "timeout"
    except ProviderError as exc:
        outcome.status = "error"
        outcome.error = "provider_unavailable" if exc.code == "unavailable" else "provider_error"
    except BudgetExceeded:
        outcome.status, outcome.error = "error", "ai_budget_exceeded"
    except Exception:
        # Anything else: the request failed, but the tokens already used are still recorded.
        log.exception("ai: the request failed")
        outcome.status, outcome.error = "error", "internal"
    return outcome
