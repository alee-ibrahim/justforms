"""Provider-neutral chat types shared by the orchestrator and the adapters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Capability = Literal["tools", "vision", "streaming"]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    # Set when the provider sent arguments that are not a JSON object.
    arguments_error: str | None = None


@dataclass
class ToolResult:
    call_id: str
    name: str
    content: dict[str, Any]
    is_error: bool = False


@dataclass
class ImagePart:
    data: bytes
    mime: str


@dataclass
class ChatMessage:
    role: Literal["user", "assistant", "tool"]
    text: str = ""
    images: list[ImagePart] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    # Opaque data an adapter needs back on the next request (e.g. Gemini thought signatures).
    provider_data: dict[str, Any] | None = None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class TurnResult:
    text: str
    tool_calls: list[ToolCall]
    usage: Usage
    stop_reason: str = ""
    provider_data: dict[str, Any] | None = None


@dataclass
class ProviderEvent:
    """A streamed piece of the reply (text delta)."""

    text: str


class ProviderError(Exception):
    """The provider failed. ``code``: ``unavailable`` (network, 5xx, 429, timeout) or
    ``bad_response`` (the request was refused or the reply could not be read)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class AIProvider(Protocol):
    name: str
    model: str
    capabilities: set[Capability]

    async def run_turn(
        self,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        *,
        max_output_tokens: int,
        stream: Callable[[ProviderEvent], Awaitable[None]] | None = None,
    ) -> TurnResult: ...
