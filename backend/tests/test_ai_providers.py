"""Provider adapters: request translation, reply parsing, retries and errors (no network)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.ai.providers import make_provider
from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.gemini import GeminiProvider
from app.ai.providers.openai_compat import OpenAICompatProvider
from app.ai.tools import tool_specs
from app.ai.types import ChatMessage, ImagePart, ProviderError, ToolCall, ToolResult
from app.config import Settings

KEY = "test-key-not-real"


class Recorder:
    def __init__(self, *replies: tuple[int, Any]) -> None:
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, body = self.replies.pop(0)
        return httpx.Response(status, json=body)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))

    def body(self, i: int = -1) -> dict[str, Any]:
        return dict(json.loads(self.requests[i].content))


def conversation() -> list[ChatMessage]:
    return [
        ChatMessage("user", text="Read this", images=[ImagePart(b"\xff\xd8jpeg", "image/jpeg")]),
        ChatMessage(
            "assistant",
            text="Adding",
            tool_calls=[ToolCall("t1", "add_page", {"title": "Two"})],
        ),
        ChatMessage("tool", tool_results=[ToolResult("t1", "add_page", {"pageId": "page_2"})]),
    ]


async def test_anthropic_round_trip() -> None:
    rec = Recorder(
        (503, {"error": "overloaded"}),
        (
            200,
            {
                "type": "message",
                "content": [
                    {"type": "text", "text": "Sure."},
                    {"type": "tool_use", "id": "t2", "name": "get_form", "input": {}},
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 50, "output_tokens": 7},
            },
        ),
    )
    p = AnthropicProvider(model="model-x", api_key=KEY, client=rec.client())
    out = await p.run_turn("SYSTEM", conversation(), tool_specs(), max_output_tokens=321)
    assert len(rec.requests) == 2  # one retry on 503
    req = rec.requests[-1]
    assert req.url == "https://api.anthropic.com/v1/messages"
    assert req.headers["x-api-key"] == KEY and req.headers["anthropic-version"]
    body = rec.body()
    assert body["model"] == "model-x" and body["max_tokens"] == 321 and body["system"] == "SYSTEM"
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant", "user"]
    assert body["messages"][0]["content"][0]["type"] == "image"
    assert body["messages"][1]["content"][1] == {
        "type": "tool_use",
        "id": "t1",
        "name": "add_page",
        "input": {"title": "Two"},
    }
    result = body["messages"][2]["content"][0]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "t1"
    assert json.loads(result["content"]) == {"pageId": "page_2"}
    assert {t["name"] for t in body["tools"]} >= {"add_field", "set_logic"}
    assert out.text == "Sure." and out.tool_calls[0].name == "get_form"
    assert out.usage.input_tokens == 50 and out.usage.output_tokens == 7


async def test_gemini_round_trip_replays_thought_signatures() -> None:
    reply = {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"text": "thinking", "thought": True},
                        {
                            "functionCall": {
                                "id": "fc1",
                                "name": "add_page",
                                "args": {"title": "A"},
                            },
                            "thoughtSignature": "sig==",
                        },
                    ],
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 3,
            "thoughtsTokenCount": 2,
        },
    }
    rec = Recorder(
        (200, reply), (200, {"candidates": [{"content": {"parts": [{"text": "Done"}]}}]})
    )
    p = GeminiProvider(model="gem-x", api_key=KEY, client=rec.client())
    out = await p.run_turn(
        "SYS", [ChatMessage("user", text="hi")], tool_specs(), max_output_tokens=99
    )
    req = rec.requests[0]
    assert str(req.url).endswith("/models/gem-x:generateContent")
    assert req.headers["x-goog-api-key"] == KEY and KEY not in str(req.url)
    body = rec.body(0)
    assert body["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert body["generationConfig"]["maxOutputTokens"] == 99
    decls = body["tools"][0]["functionDeclarations"]
    assert all("parametersJsonSchema" in d for d in decls)
    assert out.text == "" and out.tool_calls[0].id == "fc1"
    assert out.usage.output_tokens == 5
    # Next request: the model's parts come back unchanged, the result carries the call id.
    history = [
        ChatMessage("user", text="hi"),
        ChatMessage("assistant", tool_calls=out.tool_calls, provider_data=out.provider_data),
        ChatMessage("tool", tool_results=[ToolResult("fc1", "add_page", {"pageId": "page_2"})]),
    ]
    final = await p.run_turn("SYS", history, tool_specs(), max_output_tokens=99)
    body = rec.body(1)
    assert body["contents"][1]["role"] == "model"
    assert body["contents"][1]["parts"][1]["thoughtSignature"] == "sig=="
    assert body["contents"][2]["parts"][0]["functionResponse"] == {
        "name": "add_page",
        "response": {"pageId": "page_2"},
        "id": "fc1",
    }
    assert final.text == "Done"


async def test_gemini_blocked_prompt_is_an_error() -> None:
    rec = Recorder((200, {"promptFeedback": {"blockReason": "SAFETY"}}))
    p = GeminiProvider(model="g", api_key=KEY, client=rec.client())
    with pytest.raises(ProviderError) as exc:
        await p.run_turn("s", [ChatMessage("user", text="x")], [], max_output_tokens=10)
    assert exc.value.code == "bad_response"


async def test_openai_compat_round_trip_and_bad_json() -> None:
    reply = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "a",
                            "type": "function",
                            "function": {"name": "get_form", "arguments": "{}"},
                        },
                        {
                            "id": "b",
                            "type": "function",
                            "function": {"name": "add_page", "arguments": "{oops"},
                        },
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4},
    }
    rec = Recorder((200, reply))
    p = OpenAICompatProvider(
        model="local", base_url="http://llm.internal:11434/v1", client=rec.client()
    )
    out = await p.run_turn("SYS", conversation(), tool_specs(), max_output_tokens=77)
    req = rec.requests[0]
    assert str(req.url) == "http://llm.internal:11434/v1/chat/completions"
    assert "authorization" not in req.headers  # no key for a local server
    body = rec.body()
    assert body["max_tokens"] == 77 and body["tool_choice"] == "auto"
    msgs = body["messages"]
    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert msgs[1]["content"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert msgs[2]["tool_calls"][0]["function"] == {
        "name": "add_page",
        "arguments": '{"title":"Two"}',
    }
    assert msgs[3] == {"role": "tool", "tool_call_id": "t1", "content": '{"pageId":"page_2"}'}
    assert out.tool_calls[0].arguments_error is None
    assert out.tool_calls[1].arguments_error == "the arguments were not valid JSON"


async def test_openai_uses_max_completion_tokens_and_bearer_key() -> None:
    rec = Recorder((200, {"choices": [{"message": {"content": "hi"}}]}))
    p = OpenAICompatProvider(
        model="m", base_url="https://api.openai.com/v1", api_key=KEY, client=rec.client()
    )
    out = await p.run_turn("s", [ChatMessage("user", text="x")], [], max_output_tokens=5)
    assert rec.body()["max_completion_tokens"] == 5
    assert rec.requests[0].headers["authorization"] == f"Bearer {KEY}"
    assert out.text == "hi"


@pytest.mark.parametrize(("status", "code"), [(400, "bad_response"), (500, "unavailable")])
async def test_http_errors(status: int, code: str) -> None:
    rec = Recorder((status, {"error": "x"}), (status, {"error": "x"}))
    p = AnthropicProvider(model="m", api_key=KEY, client=rec.client())
    with pytest.raises(ProviderError) as exc:
        await p.run_turn("s", [ChatMessage("user", text="x")], [], max_output_tokens=10)
    assert exc.value.code == code and KEY not in str(exc.value)


def test_factory_and_capabilities() -> None:
    assert make_provider(Settings(environment="test")) is None
    s = Settings(environment="test", ai_provider="gemini", ai_model="g", ai_api_key=KEY)
    assert {"vision"} <= make_provider(s, vision=True).capabilities  # type: ignore[union-attr]
    s = Settings(
        environment="test", ai_provider="openai_compat", ai_model="m", ai_base_url="http://x/v1"
    )
    assert make_provider(s) is not None
    assert make_provider(s, vision=True) is None  # local models: no vision unless configured
    s = Settings(
        environment="test",
        ai_provider="openai_compat",
        ai_model="m",
        ai_base_url="http://x/v1",
        ai_vision=True,
        ai_vision_model="vl",
    )
    assert make_provider(s, vision=True).model == "vl"  # type: ignore[union-attr]
    s = Settings(
        environment="test", ai_provider="anthropic", ai_model="a", ai_api_key=KEY, ai_vision=False
    )
    assert make_provider(s, vision=True) is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ai_provider": "gemini"},
        {"ai_provider": "gemini", "ai_model": "g"},
        {"ai_provider": "openai_compat", "ai_model": "m"},
        {"ai_provider": "fake", "environment": "production", "secret_key": "x"},
    ],
)
def test_settings_validation(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        Settings(**{"environment": "test", **kwargs})


async def test_refused_request_logs_the_error_type_not_the_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A provider's error body can quote the request (answers, form text): only the status
    and the error type are logged."""
    body = {
        "type": "error",
        "error": {"type": "invalid_request_error", "message": "bad value 'A111111 secret'"},
    }
    rec = Recorder((400, body))
    p = AnthropicProvider(model="m", api_key=KEY, client=rec.client())
    with caplog.at_level("WARNING"), pytest.raises(ProviderError):
        await p.run_turn("s", [ChatMessage("user", text="x")], [], max_output_tokens=10)
    logged = caplog.text
    assert "HTTP 400" in logged and "invalid_request_error" in logged
    assert "A111111" not in logged and "bad value" not in logged


async def test_missing_usage_is_estimated() -> None:
    """Some OpenAI-compatible servers report no usage: the allowance is charged an estimate
    from characters instead of nothing."""
    from app.ai.limits import usage_of

    rec = Recorder((200, {"choices": [{"message": {"content": "x" * 300}}]}))
    p = OpenAICompatProvider(model="m", base_url="http://llm/v1", api_key=None, client=rec.client())
    out = await p.run_turn("s", [ChatMessage("user", text="y")], [], max_output_tokens=500)
    assert out.usage.total == 0
    usage = usage_of(out, 1234)
    assert usage.input_tokens == 1234 and usage.output_tokens == 101
