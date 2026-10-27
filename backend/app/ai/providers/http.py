"""HTTP helper shared by the adapters: one retry on transient failures, no secrets in errors."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from app.ai.types import ProviderError

log = logging.getLogger(__name__)

RETRY_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504, 529})


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    *,
    retries: int = 1,
) -> dict[str, Any]:
    for attempt in range(retries + 1):
        try:
            res = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            if attempt < retries:
                continue
            raise ProviderError("unavailable", "timeout") from exc
        except httpx.HTTPError as exc:
            if attempt < retries:
                await asyncio.sleep(1)
                continue
            raise ProviderError("unavailable", type(exc).__name__) from exc
        if res.status_code in RETRY_STATUS and attempt < retries:
            await asyncio.sleep(1 + attempt)
            continue
        if res.status_code in RETRY_STATUS:
            raise ProviderError("unavailable", f"HTTP {res.status_code}")
        if res.status_code >= 400:
            # Only the status and the provider's error type are logged: the body can quote
            # the request (answers, form text).
            log.warning(
                "AI provider refused the request: HTTP %s (%s)",
                res.status_code,
                error_type(res),
            )
            raise ProviderError("bad_response", f"HTTP {res.status_code}")
        try:
            data = res.json()
        except ValueError as exc:
            raise ProviderError("bad_response", "reply is not JSON") from exc
        if not isinstance(data, dict):
            raise ProviderError("bad_response", "reply is not an object")
        return data
    raise ProviderError("unavailable")  # pragma: no cover


_ERROR_TYPE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


def error_type(res: httpx.Response) -> str:
    """The provider's error type or code (``invalid_request_error``, ``INVALID_ARGUMENT``),
    never its message."""
    try:
        data = res.json()
    except ValueError:
        return "unknown"
    err = data.get("error") if isinstance(data, dict) else None
    candidates: list[Any] = []
    if isinstance(err, dict):
        candidates += [err.get("type"), err.get("status"), err.get("code")]
    if isinstance(data, dict):
        candidates.append(data.get("type"))
    for value in candidates:
        if isinstance(value, (str, int)) and _ERROR_TYPE.match(str(value)):
            return str(value)
    return "unknown"


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a Pydantic JSON Schema portable across providers: no titles or defaults,
    ``$ref``s inlined (no ``$defs``), ``anyOf [X, null]`` collapsed to ``X``."""

    defs: dict[str, Any] = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                rest = {k: v for k, v in node.items() if k != "$ref"}
                return walk({**defs[ref.removeprefix("#/$defs/")], **rest})
            any_of = node.get("anyOf")
            if isinstance(any_of, list):
                non_null = [
                    s for s in any_of if not (isinstance(s, dict) and s.get("type") == "null")
                ]
                if len(non_null) == 1:
                    rest = {k: v for k, v in node.items() if k != "anyOf"}
                    return walk({**rest, **non_null[0]})
            out: dict[str, Any] = {}
            for key, value in node.items():
                if key in ("title", "default", "$defs"):
                    continue
                if key == "properties" and isinstance(value, dict):
                    # Property names are data here, never schema keywords.
                    out[key] = {name: walk(prop) for name, prop in value.items()}
                    continue
                out[key] = walk(value)
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    cleaned = walk(schema)
    assert isinstance(cleaned, dict)
    cleaned.setdefault("type", "object")
    cleaned.setdefault("properties", {})
    return cleaned
