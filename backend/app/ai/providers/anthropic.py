"""Anthropic Messages API adapter (``JUSTFORMS_AI_PROVIDER=anthropic``)."""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.ai.providers.http import post_json, to_json
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

DEFAULT_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str | None = None,
        vision: bool = True,
        timeout: float = 90.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._key = api_key
        self._url = (base_url or DEFAULT_URL).rstrip("/") + "/v1/messages"
        self.capabilities: set[Capability] = {"tools", "vision"} if vision else {"tools"}
        self._client = client or httpx.AsyncClient(timeout=timeout)

    @staticmethod
    def _content(msg: ChatMessage) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for result in msg.tool_results:
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": result.call_id,
                    "content": to_json(result.content),
                    "is_error": result.is_error,
                }
            )
        for image in msg.images:
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.mime,
                        "data": base64.b64encode(image.data).decode(),
                    },
                }
            )
        if msg.text:
            blocks.append({"type": "text", "text": msg.text})
        for call in msg.tool_calls:
            blocks.append(
                {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
            )
        return blocks

    def build_request(
        self, system: str, messages: list[ChatMessage], tools: list[ToolSpec], max_tokens: int
    ) -> dict[str, Any]:
        out: list[dict[str, Any]] = []
        for msg in messages:
            role = "assistant" if msg.role == "assistant" else "user"
            content = self._content(msg)
            if out and out[-1]["role"] == role:
                out[-1]["content"].extend(content)  # the API wants alternating roles
            else:
                out.append({"role": role, "content": content})
        return {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": out,
            "tools": [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ],
        }

    @staticmethod
    def parse_response(data: dict[str, Any]) -> TurnResult:
        texts: list[str] = []
        calls: list[ToolCall] = []
        content = data.get("content")
        if not isinstance(content, list):
            raise ProviderError("bad_response", "no content")
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                texts.append(str(block.get("text", "")))
            elif block.get("type") == "tool_use":
                args = block.get("input")
                calls.append(
                    ToolCall(
                        id=str(block.get("id", "")),
                        name=str(block.get("name", "")),
                        arguments=args if isinstance(args, dict) else {},
                        arguments_error=None if isinstance(args, dict) else "not an object",
                    )
                )
        usage = data.get("usage") or {}
        return TurnResult(
            text="".join(texts).strip(),
            tool_calls=calls,
            usage=Usage(int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))),
            stop_reason=str(data.get("stop_reason") or ""),
        )

    async def run_turn(
        self,
        system: str,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        *,
        max_output_tokens: int,
        stream: Callable[[ProviderEvent], Awaitable[None]] | None = None,
    ) -> TurnResult:
        body = self.build_request(system, messages, tools, max_output_tokens)
        headers = {"x-api-key": self._key, "anthropic-version": API_VERSION}
        return self.parse_response(await post_json(self._client, self._url, body, headers))
