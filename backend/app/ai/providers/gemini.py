"""Google Gemini API adapter (``JUSTFORMS_AI_PROVIDER=gemini``, ``generateContent``).

Gemini returns opaque "thought signatures" on function-call parts and expects them back on
the next request, so the raw model parts are kept in ``provider_data`` and replayed as is.
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

import httpx

from app.ai.providers.http import post_json
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

DEFAULT_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    name = "gemini"

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
        base = (base_url or DEFAULT_URL).rstrip("/")
        self._url = f"{base}/models/{quote(model, safe='')}:generateContent"
        self.capabilities: set[Capability] = {"tools", "vision"} if vision else {"tools"}
        self._client = client or httpx.AsyncClient(timeout=timeout)

    @staticmethod
    def _parts(msg: ChatMessage) -> list[dict[str, Any]]:
        if msg.role == "assistant" and msg.provider_data and "parts" in msg.provider_data:
            return list(msg.provider_data["parts"])
        parts: list[dict[str, Any]] = []
        for result in msg.tool_results:
            response: dict[str, Any] = {
                "name": result.name,
                "response": {"error": result.content} if result.is_error else result.content,
            }
            if result.call_id and not result.call_id.startswith("gemini-"):
                response["id"] = result.call_id
            parts.append({"functionResponse": response})
        for image in msg.images:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": image.mime,
                        "data": base64.b64encode(image.data).decode(),
                    }
                }
            )
        if msg.text:
            parts.append({"text": msg.text})
        for call in msg.tool_calls:
            parts.append({"functionCall": {"name": call.name, "args": call.arguments}})
        return parts

    def build_request(
        self, system: str, messages: list[ChatMessage], tools: list[ToolSpec], max_tokens: int
    ) -> dict[str, Any]:
        contents: list[dict[str, Any]] = []
        for msg in messages:
            role = "model" if msg.role == "assistant" else "user"
            parts = self._parts(msg)
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"].extend(parts)
            else:
                contents.append({"role": role, "parts": parts})
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "parametersJsonSchema": t.parameters,
                        }
                        for t in tools
                    ]
                }
            ],
            "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
            "generationConfig": {"maxOutputTokens": max_tokens},
        }

    @staticmethod
    def parse_response(data: dict[str, Any]) -> TurnResult:
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            feedback = data.get("promptFeedback") or {}
            raise ProviderError("bad_response", str(feedback.get("blockReason") or "no candidates"))
        candidate = candidates[0] if isinstance(candidates[0], dict) else {}
        parts = (candidate.get("content") or {}).get("parts") or []
        texts: list[str] = []
        calls: list[ToolCall] = []
        for i, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            if "text" in part and not part.get("thought"):
                texts.append(str(part["text"]))
            elif isinstance(part.get("functionCall"), dict):
                fc = part["functionCall"]
                args = fc.get("args")
                calls.append(
                    ToolCall(
                        id=str(fc.get("id") or f"gemini-{i}"),
                        name=str(fc.get("name", "")),
                        arguments=args if isinstance(args, dict) else {},
                        arguments_error=None
                        if isinstance(args, dict) or args is None
                        else "not an object",
                    )
                )
        meta = data.get("usageMetadata") or {}
        return TurnResult(
            text="".join(texts).strip(),
            tool_calls=calls,
            usage=Usage(
                int(meta.get("promptTokenCount", 0)),
                int(meta.get("candidatesTokenCount", 0)) + int(meta.get("thoughtsTokenCount", 0)),
            ),
            stop_reason=str(candidate.get("finishReason") or ""),
            provider_data={"parts": [p for p in parts if isinstance(p, dict)]},
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
        headers = {"x-goog-api-key": self._key}
        return self.parse_response(await post_json(self._client, self._url, body, headers))
