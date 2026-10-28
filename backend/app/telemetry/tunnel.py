"""Same-origin tunnel for browser error reports (the Sentry SDK's ``tunnel`` option).

Browsers post Sentry envelopes to ``/api/v1/telemetry/envelope`` instead of the error tracker,
so the tracker can stay on an internal address and the page needs no extra CSP origin. The
tunnel is not an open proxy:

- the destination is never taken from the request: it is always the configured browser DSN's
  envelope endpoint, and the envelope's own ``dsn`` must name that DSN's key and project;
- only ``event`` and ``client_report`` items pass (no sessions, replays, attachments,
  transactions, profiles or user feedback), and every event is scrubbed again
  (:func:`app.telemetry.scrub.scrub_event`);
- bodies over :data:`MAX_ENVELOPE_BYTES` are refused and callers are rate limited per IP.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Dsn, parse_dsn
from app.telemetry.scrub import scrub_event

MAX_ENVELOPE_BYTES = 200 * 1024
MAX_ITEMS = 20
FORWARD_TIMEOUT_S = 5.0
ALLOWED_ITEMS = frozenset({"event", "client_report"})
_ENVELOPE_HEADER_KEYS = ("event_id", "sent_at", "dsn", "sdk")


class EnvelopeError(ValueError):
    """The body is not an envelope for the configured DSN."""


@dataclass(frozen=True)
class Envelope:
    body: bytes
    items: int


def _read_line(data: bytes, pos: int) -> tuple[bytes, int]:
    end = data.find(b"\n", pos)
    if end < 0:
        return data[pos:], len(data)
    return data[pos:end], end + 1


def _json(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise EnvelopeError("bad json") from exc


def _same_dsn(header_dsn: Any, dsn: Dsn) -> bool:
    if not isinstance(header_dsn, str):
        return False
    given = parse_dsn(header_dsn)
    return (
        given is not None
        and given.public_key == dsn.public_key
        and given.project_id == dsn.project_id
    )


def clean_envelope(data: bytes, dsn: Dsn) -> Envelope:
    """Parse, filter and scrub an envelope for ``dsn``; raises :class:`EnvelopeError`."""
    if len(data) > MAX_ENVELOPE_BYTES:
        raise EnvelopeError("too large")
    raw_header, pos = _read_line(data, 0)
    header = _json(raw_header)
    if not isinstance(header, dict) or not _same_dsn(header.get("dsn"), dsn):
        raise EnvelopeError("wrong dsn")
    out = [json.dumps({k: header[k] for k in _ENVELOPE_HEADER_KEYS if k in header}).encode()]
    kept = 0
    seen = 0
    while pos < len(data):
        raw_item, pos = _read_line(data, pos)
        if not raw_item.strip():
            continue
        seen += 1
        if seen > MAX_ITEMS:
            raise EnvelopeError("too many items")
        item = _json(raw_item)
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            raise EnvelopeError("bad item header")
        length = item.get("length")
        if isinstance(length, int) and not isinstance(length, bool):
            if length < 0 or pos + length > len(data):
                raise EnvelopeError("bad length")
            payload = data[pos : pos + length]
            pos += length
            if pos < len(data) and data[pos : pos + 1] == b"\n":
                pos += 1
        else:
            payload, pos = _read_line(data, pos)
        kind = item["type"]
        if kind not in ALLOWED_ITEMS:
            continue
        body = _json(payload)
        if not isinstance(body, dict):
            raise EnvelopeError("bad payload")
        if kind == "event":
            body = scrub_event(body)
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        out.append(json.dumps({"type": kind, "length": len(encoded)}).encode())
        out.append(encoded)
        kept += 1
    return Envelope(body=b"\n".join(out) + b"\n", items=kept)


async def forward(envelope: Envelope, dsn: Dsn, client: httpx.AsyncClient | None = None) -> int:
    """Send to the DSN's envelope endpoint; returns the upstream status code."""
    headers = {
        "Content-Type": "application/x-sentry-envelope",
        "X-Sentry-Auth": (
            f"Sentry sentry_version=7, sentry_key={dsn.public_key}, "
            "sentry_client=justforms-tunnel/1"
        ),
    }
    own = client is None
    http = client or httpx.AsyncClient(
        timeout=FORWARD_TIMEOUT_S, follow_redirects=False, trust_env=False
    )
    try:
        res = await http.post(dsn.envelope_url, content=envelope.body, headers=headers)
        return res.status_code
    finally:
        if own:
            await http.aclose()
