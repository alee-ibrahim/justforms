"""Scrubbing for error-tracking events (Sentry protocol, also accepted by GlitchTip).

Events must never carry what respondents typed or who they are. The SDKs already run with
``send_default_pii`` off, no local variables, no request bodies and no breadcrumbs; this module
is the last line: :func:`scrub_event` keeps only the parts of an event that describe the
failure (exception types, stack frames without variables, the route, runtime contexts) and
masks emails, phone and ID numbers, tokens and database parameters in every text it keeps.

The browser twin is ``frontend/src/lib/telemetry-scrub.ts``; both run the shared cases in
``spec/telemetry/scrub.json``. The same function cleans events that arrive through the
browser tunnel (``app.telemetry.tunnel``).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

FILTERED = "[Filtered]"

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# Order matters: structured leaks first (whole values), then shapes of personal data.
_TEXT_RULES: list[tuple[re.Pattern[str], str]] = [
    # Pydantic: "input_value='what they typed', input_type=str"
    (re.compile(r"input_value=.*?(?=, input_type=|$)", re.MULTILINE), "input_value=" + FILTERED),
    # SQLAlchemy: "[parameters: (...)]" to the end of the line
    (re.compile(r"\[parameters: [^\n]*"), "[parameters: " + FILTERED + "]"),
    # PostgreSQL: "DETAIL: Key (email)=(a@b.mv) already exists."
    (
        re.compile(r"(Key \([^)\n]*\)=)\([^\n]*?\)(?= already| is not|\.|$)", re.MULTILINE),
        r"\1(" + FILTERED + ")",
    ),
    # Credentials after a keyword: "Bearer abc", "token=abc", "password: abc"
    (
        re.compile(
            r"(?i)\b(bearer|token|authorization|cookie|session|csrf|password|passwd|secret|"
            r"api[_-]?key|code)(\s*[:=]\s*[\"']?|\s+)(?=[^\s\"',;&]*[0-9])[^\s\"',;&]+"
        ),
        r"\1\2" + FILTERED,
    ),
    (re.compile(r"[^\s@<>\"'(),;:/]+@[^\s@<>\"'(),;:/]+\.[A-Za-z]{2,}"), "[email]"),
    # ID card numbers (one capital letter and six digits)
    (re.compile(r"\b[A-Z][0-9]{6}\b"), "[id]"),
    # Phone and other long numbers: 7 to 15 digits, optionally with + and separators
    (re.compile(r"(?<![\w.\-])\+?[0-9](?:[ \-]?[0-9]){6,14}(?![\w.\-])"), "[number]"),
]

# Long opaque strings (tokens, keys, signed links), except UUIDs, which are ids, not secrets.
_TOKEN = re.compile(r"[A-Za-z0-9_\-]{24,}")

# Path segments that are tokens (verify, approver and invitation links carry one).
_SEGMENT = re.compile(r"^[A-Za-z0-9_\-]{16,}$")

MAX_TEXT = 4096


def _secretish(value: str) -> bool:
    """Long, has a digit, not a UUID: a token rather than a word or an identifier."""
    return any(c.isdigit() for c in value) and not _UUID.match(value)


def _token(match: re.Match[str]) -> str:
    value = match.group(0)
    return "[token]" if _secretish(value) else value


def scrub_text(text: str) -> str:
    """Mask personal data and secrets in one piece of text."""
    out = text[:MAX_TEXT]
    for pattern, repl in _TEXT_RULES:
        out = pattern.sub(repl, out)
    return _TOKEN.sub(_token, out)


def scrub_url(url: str) -> str:
    """Scheme, host and path only; token-like path segments masked; no query or fragment."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return FILTERED
    segments = [
        ":token" if _SEGMENT.match(s) and _secretish(s) else s for s in parts.path.split("/")
    ]
    base = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""
    return scrub_text(base + "/".join(segments))


def _scrub_values(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return FILTERED
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, list):
        return [_scrub_values(v, depth + 1) for v in value[:50]]
    if isinstance(value, dict):
        return {str(k): _scrub_values(v, depth + 1) for k, v in list(value.items())[:50]}
    return value


# Top-level event keys kept; everything else (user, extra, breadcrumbs, spans, request bodies,
# modules, debug metadata...) is dropped.
_EVENT_KEYS = frozenset(
    {
        "event_id",
        "timestamp",
        "platform",
        "level",
        "logger",
        "transaction",
        "server_name",
        "release",
        "dist",
        "environment",
        "message",
        "logentry",
        "exception",
        "tags",
        "contexts",
        "request",
        "sdk",
        "fingerprint",
        "type",
    }
)
_CONTEXT_KEYS = frozenset({"runtime", "os", "browser", "device", "app", "trace", "culture"})
_FRAME_KEYS = frozenset(
    {
        "filename",
        "abs_path",
        "module",
        "function",
        "lineno",
        "colno",
        "in_app",
        "context_line",
        "pre_context",
        "post_context",
        "platform",
    }
)


def _scrub_frame(frame: Any) -> Any:
    if not isinstance(frame, dict):
        return None
    out = {k: v for k, v in frame.items() if k in _FRAME_KEYS}  # no "vars"
    for key in ("abs_path", "filename"):
        if isinstance(out.get(key), str) and "://" in out[key]:
            out[key] = scrub_url(out[key])
    for key in ("context_line",):
        if isinstance(out.get(key), str):
            out[key] = scrub_text(out[key])
    for key in ("pre_context", "post_context"):
        if isinstance(out.get(key), list):
            out[key] = [scrub_text(x) if isinstance(x, str) else "" for x in out[key]]
    return out


def _scrub_exception(exc: Any) -> Any:
    if not isinstance(exc, dict):
        return exc
    values = exc.get("values")
    if not isinstance(values, list):
        return {}
    kept = []
    for item in values[:10]:
        if not isinstance(item, dict):
            continue
        entry = {k: item[k] for k in ("type", "module", "mechanism") if k in item}
        if isinstance(item.get("value"), str):
            entry["value"] = scrub_text(item["value"])
        mech = entry.get("mechanism")
        if isinstance(mech, dict):
            entry["mechanism"] = {k: mech[k] for k in ("type", "handled", "synthetic") if k in mech}
        trace = item.get("stacktrace")
        if isinstance(trace, dict) and isinstance(trace.get("frames"), list):
            frames = [f for f in (_scrub_frame(x) for x in trace["frames"][-100:]) if f]
            entry["stacktrace"] = {"frames": frames}
        kept.append(entry)
    return {"values": kept}


def _scrub_request(request: Any) -> Any:
    if not isinstance(request, dict):
        return None
    out: dict[str, Any] = {}
    if isinstance(request.get("url"), str):
        out["url"] = scrub_url(request["url"])
    if isinstance(request.get("method"), str):
        out["method"] = request["method"][:10]
    # No headers, cookies, query string, body or environment.
    return out


def scrub_event(event: dict[str, Any]) -> dict[str, Any]:
    """A copy of ``event`` with only failure details, every text scrubbed."""
    out: dict[str, Any] = {k: v for k, v in event.items() if k in _EVENT_KEYS}
    if "message" in out:
        msg = out["message"]
        out["message"] = (
            scrub_text(msg) if isinstance(msg, str) else _scrub_values(msg) if msg else msg
        )
    if isinstance(out.get("logentry"), dict):
        entry = out["logentry"]
        # The formatted message only: params are where values hide.
        text = entry.get("formatted") or entry.get("message") or ""
        out["logentry"] = {"message": scrub_text(str(text))}
    if "exception" in out:
        out["exception"] = _scrub_exception(out["exception"])
    if "request" in out:
        request = _scrub_request(out["request"])
        if request:
            out["request"] = request
        else:
            del out["request"]
    if isinstance(out.get("transaction"), str):
        out["transaction"] = scrub_url(out["transaction"])
    if isinstance(out.get("tags"), dict):
        out["tags"] = {
            str(k)[:32]: scrub_text(str(v))[:200] for k, v in list(out["tags"].items())[:50]
        }
    elif "tags" in out:
        del out["tags"]
    if isinstance(out.get("contexts"), dict):
        out["contexts"] = {
            k: _scrub_values(v) for k, v in out["contexts"].items() if k in _CONTEXT_KEYS
        }
    elif "contexts" in out:
        del out["contexts"]
    return out


def before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """``sentry_sdk.init(before_send=...)``."""
    return scrub_event(event)
