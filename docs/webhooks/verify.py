"""Reference verifier for JustForms webhooks (Python 3.9+, standard library only).

Usage in a receiver::

    ok = verify(secret, request.headers, raw_body)  # raw_body: the exact bytes received

Reject the request when ``ok`` is false. Use the raw body, not re-serialised JSON.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping

TOLERANCE_SECONDS = 300


def verify(
    secret: str,
    headers: Mapping[str, str],
    body: bytes,
    *,
    now: float | None = None,
    tolerance: int = TOLERANCE_SECONDS,
) -> bool:
    lower = {k.lower(): v for k, v in headers.items()}
    event_id = lower.get("justforms-webhook-id", "")
    timestamp = lower.get("justforms-webhook-timestamp", "")
    if not event_id or not timestamp.isdigit():
        return False
    current = time.time() if now is None else now
    if abs(current - int(timestamp)) > tolerance:
        return False  # too old (or from the future): possible replay
    message = f"{event_id}.{timestamp}.".encode() + body
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    # During a secret rotation the header carries two signatures: "v1=...,v1=...".
    for part in lower.get("justforms-webhook-signature", "").split(","):
        version, _, value = part.strip().partition("=")
        if version == "v1" and hmac.compare_digest(value, expected):
            return True
    return False
