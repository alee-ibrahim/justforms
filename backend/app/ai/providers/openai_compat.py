"""OpenAI-compatible Chat Completions adapter (``JUSTFORMS_AI_PROVIDER=openai_compat``).

Covers OpenAI, Azure OpenAI (through its OpenAI-compatible endpoint), OpenRouter and local
servers such as vLLM, Ollama and LM Studio. The model must support tool calling. The API key
is optional (local servers usually need none).
"""

from __future__ import annotations

import base64
import json
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

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


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str | None = None,
        vision: bool = False,
        timeout: float = 90.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._key = api_key
        base = base_url.rstrip("/")
        self._url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        # OpenAI's own API takes max_completion_tokens; most compatible servers max_tokens.
        host = urlparse(base).hostname or ""
        self._token_param = (
            "max_completion_tokens" if host.endswith("api.openai.com") else "max_tokens"
        )
        self.capabilities: set[Capability] = {"tools", "vision"} if vision else {"tools"}
        self._client = client or httpx.AsyncClient(timeout=timeout)

    @staticmethod
    def _messages(system: str, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for msg in messages:
            if msg.role == "assistant":
                item: dict[str, Any] = {"role": "assistant", "content": msg.text or None}
                if msg.tool_calls:
                    item["tool_calls"] = [
                        {
                            "id": c.id,
                            "type": "function",
                            "function": {"name": c.name, "arguments": to_json(c.arguments)},
                        }
                        for c in msg.tool_calls
                    ]
                out.append(item)
                continue
            for result in msg.tool_results:
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.call_id,
                        "content": to_json(
                            {"error": result.content} if result.is_error else result.content
                        ),
                    }
                )
            if msg.images:
                parts: list[dict[str, Any]] = [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{img.mime};base64,{base64.b64encode(img.data).decode()}"
                        },
                    }
                    for img in msg.images
                ]
                if msg.text:
                    parts.append({"type": "text", "text": msg.text})
                out.append({"role": "user", "content": parts})
            elif msg.text:
                out.append({"role": "user", "content": msg.text})
        return out

    def build_request(
        self, system: str, messages: list[ChatMessage], tools: list[ToolSpec], max_tokens: int
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": self._messages(system, messages),
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ],
            "tool_choice": "auto",
            self._token_param: max_tokens,
        }

    @staticmethod
    def parse_response(data: dict[str, Any]) -> TurnResult:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderError("bad_response", "no choices")
        message = choices[0].get("message") or {}
        calls: list[ToolCall] = []
        for i, call in enumerate(message.get("tool_calls") or []):
            fn = call.get("function") or {}
            raw = fn.get("arguments")
            args: Any
            error = None
            if isinstance(raw, dict):
                args = raw
            else:
                try:
                    args = json.loads(raw or "{}")
                except (TypeError, ValueError):
                    args, error = {}, "the arguments were not valid JSON"
            if not isinstance(args, dict):
                args, error = {}, "the arguments were not a JSON object"
            calls.append(
                ToolCall(
                    id=str(call.get("id") or f"call-{i}"),
                    name=str(fn.get("name", "")),
                    arguments=args,
                    arguments_error=error,
                )
            )
        usage = data.get("usage") or {}
        content = message.get("content")
        return TurnResult(
            text=content.strip() if isinstance(content, str) else "",
            tool_calls=calls,
            usage=Usage(int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))),
            stop_reason=str(choices[0].get("finish_reason") or ""),
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
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        return self.parse_response(await post_json(self._client, self._url, body, headers))
