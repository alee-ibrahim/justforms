"""Deterministic providers for tests and local development (no network, no key).

``ScriptedProvider`` plays a list of turns (tool calls and text) in order and records every
request it receives, so tests can check exactly what would have been sent to a provider.

``JUSTFORMS_AI_PROVIDER=fake`` (refused in production) uses ``FileScriptProvider``: a JSON
file (``JUSTFORMS_AI_FAKE_SCRIPT``) of scenarios picked by a word in the person's request::

    {"scenarios": [{"match": "phone", "turns": [
        {"toolCalls": [{"name": "add_field", "arguments": {...}}]},
        {"text": "I added a phone question."}]}],
     "default": [{"text": "Tell me what to change."}]}

Each request plays its scenario from the first turn; a turn may have ``"delay"`` (seconds).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.ai.types import (
    Capability,
    ChatMessage,
    ProviderError,
    ProviderEvent,
    ToolCall,
    ToolSpec,
    TurnResult,
    Usage,
)


@dataclass
class RecordedCall:
    system: str
    messages: list[ChatMessage]
    tools: list[ToolSpec]
    max_output_tokens: int


def turn(
    text: str = "",
    calls: Sequence[tuple[str, dict[str, Any]]] = (),
    *,
    tokens: tuple[int, int] = (100, 20),
) -> TurnResult:
    """A scripted reply: optional text plus tool calls ``(name, arguments)``."""
    return TurnResult(
        text=text,
        tool_calls=[
            ToolCall(id=f"call-{i}", name=n, arguments=a) for i, (n, a) in enumerate(calls)
        ],
        usage=Usage(*tokens),
        stop_reason="tool_use" if calls else "end_turn",
    )


Step = TurnResult | ProviderError | Callable[[list[ChatMessage]], Awaitable[TurnResult]]


@dataclass
class ScriptedProvider:
    """Replays ``steps`` one per ``run_turn`` call; then answers with plain text."""

    steps: list[Step]
    name: str = "fake"
    model: str = "scripted"
    capabilities: set[Capability] = field(default_factory=lambda: {"tools", "vision"})
    calls: list[RecordedCall] = field(default_factory=list)

    async def run_turn(
        self,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        *,
        max_output_tokens: int,
        stream: Callable[[ProviderEvent], Awaitable[None]] | None = None,
    ) -> TurnResult:
        self.calls.append(RecordedCall(system, list(messages), tools, max_output_tokens))
        if not self.steps:
            return turn("Done.")
        step = self.steps.pop(0)
        if isinstance(step, ProviderError):
            raise step
        if callable(step):
            return await step(messages)
        return step

    def sent_text(self) -> str:
        """Everything that would have gone to a provider, as one string (for leak checks)."""
        parts: list[str] = []
        for call in self.calls:
            parts.append(call.system)
            for msg in call.messages:
                parts.append(msg.text)
                parts.extend(json.dumps(c.arguments, ensure_ascii=False) for c in msg.tool_calls)
                parts.extend(json.dumps(r.content, ensure_ascii=False) for r in msg.tool_results)
        return "\n".join(parts)


class FileScriptProvider:
    name = "fake"
    model = "scripted"

    def __init__(self, path: Path | None) -> None:
        self.capabilities: set[Capability] = {"tools", "vision"}
        self._path = path

    def _script(self) -> dict[str, Any]:
        if self._path is None:
            return {"default": [{"text": "The test AI service has no script."}]}
        data = json.loads(self._path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    async def run_turn(
        self,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        *,
        max_output_tokens: int,
        stream: Callable[[ProviderEvent], Awaitable[None]] | None = None,
    ) -> TurnResult:
        last_user = max((i for i, m in enumerate(messages) if m.role == "user"), default=-1)
        request = messages[last_user].text.lower() if last_user >= 0 else ""
        step = sum(1 for m in messages[last_user + 1 :] if m.role == "assistant")
        script = self._script()
        turns: list[dict[str, Any]] = script.get("default", [])
        for scenario in script.get("scenarios", []):
            if str(scenario.get("match", "")).lower() in request:
                turns = scenario.get("turns", [])
                break
        if step >= len(turns):
            return turn("Done.")
        spec = turns[step]
        if spec.get("delay"):
            await asyncio.sleep(float(spec["delay"]))
        if spec.get("error"):
            raise ProviderError(str(spec["error"]))
        return turn(
            str(spec.get("text", "")),
            [(c["name"], c.get("arguments", {})) for c in spec.get("toolCalls", [])],
        )
