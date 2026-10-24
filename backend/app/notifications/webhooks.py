"""Webhooks: secrets, payloads, signing and delivery with retries (DESIGN 11.2).

Requests are signed like Standard Webhooks / Stripe::

    JustForms-Webhook-Id: evt_...
    JustForms-Webhook-Timestamp: 1761207302
    JustForms-Webhook-Signature: v1=<hex HMAC-SHA256(secret, f"{id}.{timestamp}.{body}")>

The HMAC key is the whole secret string (``whsec_...``) as UTF-8. After a rotation the
header carries both signatures (``v1=new,v1=old``) for 24 hours. Receivers should reject
timestamps more than 5 minutes old; see ``docs/webhooks.md`` for verifiers.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.ids import uuid7
from app.logic.index import FormIndex
from app.models import (
    DeliveryStatus,
    FormRecord,
    FormVersion,
    Submission,
    Webhook,
    WebhookDelivery,
)
from app.notifications.ssrf import UrlRefused, resolve
from app.schemas.form import FileField, Form, SignatureField

log = logging.getLogger(__name__)

EVENTS = (
    "submission.created",
    "submission.status_changed",
    "submission.comment_added",
    "submission.pdf_ready",
    "submission.approval_step",
)
TEST_EVENT = "test"
# Seconds to wait after the 1st, 2nd, ... failed attempt; 8 attempts in total.
RETRY_DELAYS = (60, 300, 1800, 7200, 21600, 43200, 86400)
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
AUTO_DISABLE_AFTER = 20
ROTATION_OVERLAP = timedelta(hours=24)
SNIPPET_BYTES = 1024
REDACTED = "[redacted]"


# -- secrets --------------------------------------------------------------------------------


def _fernet(settings: Settings) -> Fernet:
    digest = hashlib.sha256(b"justforms:webhook-secret:" + settings.secret_key_bytes).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def new_secret() -> str:
    return "whsec_" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")


def encrypt(settings: Settings, secret: str) -> bytes:
    return _fernet(settings).encrypt(secret.encode())


def decrypt(settings: Settings, blob: bytes) -> str:
    return _fernet(settings).decrypt(blob).decode()


def active_secrets(settings: Settings, hook: Webhook, now: datetime) -> list[str]:
    out = [decrypt(settings, hook.secret_enc)]
    if (
        hook.previous_secret_enc is not None
        and hook.previous_expires_at is not None
        and hook.previous_expires_at > now
    ):
        with contextlib.suppress(InvalidToken):
            out.append(decrypt(settings, hook.previous_secret_enc))
    return out


def rotate(settings: Settings, hook: Webhook, now: datetime) -> str:
    secret = new_secret()
    hook.previous_secret_enc = hook.secret_enc
    hook.previous_expires_at = now + ROTATION_OVERLAP
    hook.secret_enc = encrypt(settings, secret)
    return secret


# -- signing --------------------------------------------------------------------------------


def sign(secret: str, event_id: str, timestamp: int, body: bytes) -> str:
    message = f"{event_id}.{timestamp}.".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def signature_header(secrets_: list[str], event_id: str, timestamp: int, body: bytes) -> str:
    return ",".join(f"v1={sign(s, event_id, timestamp, body)}" for s in secrets_)


def verify(
    secret: str,
    headers: dict[str, str],
    body: bytes,
    *,
    tolerance: int = 300,
    now: float | None = None,
) -> bool:
    """Reference verifier (the same check a receiver should make)."""
    lower = {k.lower(): v for k, v in headers.items()}
    event_id = lower.get("justforms-webhook-id", "")
    ts = lower.get("justforms-webhook-timestamp", "")
    if not event_id or not ts.isdigit():
        return False
    if abs((now if now is not None else time.time()) - int(ts)) > tolerance:
        return False
    expected = sign(secret, event_id, int(ts), body)
    for part in lower.get("justforms-webhook-signature", "").split(","):
        version, _, value = part.strip().partition("=")
        if version == "v1" and hmac.compare_digest(value, expected):
            return True
    return False


def new_event_id() -> str:
    return f"evt_{uuid7().hex}"


# -- payloads -------------------------------------------------------------------------------


def submission_url(settings: Settings, sub: Submission) -> str:
    return f"{settings.public_origin}/forms/{sub.form_id}/submissions?open={sub.id}"


def webhook_data(
    settings: Settings, form: Form, data: dict[str, Any], *, include_sensitive: bool
) -> dict[str, Any]:
    """Answers for a webhook: sensitive ones redacted, files and signatures as app links."""
    index = FormIndex.build(form)
    base = settings.public_origin

    def convert(field_id: str, value: Any) -> Any:
        info = index.elements.get(field_id)
        el = info.element if info else None
        if el is not None and getattr(el, "sensitive", False) and not include_sensitive:
            return REDACTED
        if isinstance(el, FileField) and isinstance(value, list):
            return [
                {**f, "url": f"{base}/api/v1/files/{f.get('fileId')}"}
                for f in value
                if isinstance(f, dict)
            ]
        if isinstance(el, SignatureField) and isinstance(value, dict):
            return {**value, "signed": True}
        return value

    out: dict[str, Any] = {}
    for key, value in data.items():
        info = index.elements.get(key)
        if info is not None and info.kind == "repeater" and isinstance(value, list):
            out[key] = [
                {k: convert(k, v) for k, v in row.items()} if isinstance(row, dict) else row
                for row in value
            ]
        else:
            out[key] = convert(key, value)
    return out


async def build_payload(
    db: AsyncSession,
    settings: Settings,
    sub: Submission,
    event: str,
    event_id: str,
    *,
    include_sensitive: bool,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    form_rec = await db.get(FormRecord, sub.form_id)
    version = await db.get(FormVersion, sub.form_version_id)
    assert form_rec is not None and version is not None
    form = Form.model_validate(version.schema)
    submission: dict[str, Any] = {
        "id": str(sub.id),
        "seq": sub.seq,
        "reference": f"#{sub.seq:04d}",
        "status": sub.status.value,
        "language": sub.language,
        "submittedAt": sub.submitted_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "contentHash": f"sha256:{sub.content_hash}" if sub.content_hash else None,
        "respondentEmail": sub.respondent_email,
        "data": webhook_data(settings, form, sub.data, include_sensitive=include_sensitive),
        "url": submission_url(settings, sub),
    }
    if event == "submission.pdf_ready":
        submission["pdf"] = {
            "url": f"{settings.public_origin}/api/v1/submissions/{sub.id}/pdf",
            "sha256": sub.pdf_sha256,
        }
    payload: dict[str, Any] = {
        "id": event_id,
        "type": event,
        "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "form": {
            "id": str(form_rec.id),
            "slug": form_rec.slug,
            "url": f"{settings.public_origin}/{form_rec.slug}",
            "version": version.version,
        },
        "submission": submission,
    }
    if extra:
        payload["change"] = extra
    return payload


def test_payload(form_rec: FormRecord, event_id: str) -> dict[str, Any]:
    return {
        "id": event_id,
        "type": TEST_EVENT,
        "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "form": {"id": str(form_rec.id), "slug": form_rec.slug},
        "message": "Test event from JustForms. Your endpoint is reachable.",
    }


# -- queueing -------------------------------------------------------------------------------


async def hooks_for(db: AsyncSession, form_id: uuid.UUID, event: str) -> list[Webhook]:
    rows = await db.scalars(
        select(Webhook).where(Webhook.form_id == form_id, Webhook.enabled.is_(True))
    )
    return [h for h in rows if event in (h.events or [])]


async def create_deliveries(
    db: AsyncSession,
    settings: Settings,
    sub: Submission,
    event: str,
    *,
    extra: dict[str, Any] | None = None,
) -> list[uuid.UUID]:
    """One pending delivery per enabled webhook subscribed to ``event``."""
    hooks = await hooks_for(db, sub.form_id, event)
    if not hooks:
        return []
    event_id = new_event_id()
    ids: list[uuid.UUID] = []
    for hook in hooks:
        payload = await build_payload(
            db,
            settings,
            sub,
            event,
            event_id,
            include_sensitive=hook.include_sensitive,
            extra=extra,
        )
        row = WebhookDelivery(
            id=uuid7(),
            webhook_id=hook.id,
            event_id=event_id,
            event=event,
            payload=payload,
            next_attempt_at=datetime.now(UTC),
        )
        db.add(row)
        ids.append(row.id)
    await db.flush()
    return ids


# -- delivery -------------------------------------------------------------------------------


def _pinned_url(url: str, address: str) -> str:
    parts = urlsplit(url)
    host = f"[{address}]" if ":" in address else address
    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


async def send(
    settings: Settings,
    url: str,
    body: bytes,
    headers: dict[str, str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[int | None, str, str | None, int]:
    """POST once. Returns (status code, response snippet, error, duration ms)."""
    started = time.monotonic()
    try:
        target = await resolve(url, settings)
    except UrlRefused as exc:
        return None, "", exc.code, 0
    host_header = urlsplit(url).netloc.rsplit("@", 1)[-1]
    try:
        async with httpx.AsyncClient(
            timeout=settings.webhook_timeout_seconds,
            follow_redirects=False,
            transport=transport,
        ) as client:
            res = await client.post(
                _pinned_url(url, target.address),
                content=body,
                headers={**headers, "Host": host_header},
                extensions={"sni_hostname": target.host},
            )
            snippet = res.content[:SNIPPET_BYTES].decode("utf-8", "replace")
            return res.status_code, snippet, None, int((time.monotonic() - started) * 1000)
    except httpx.TimeoutException:
        return None, "", "timeout", int((time.monotonic() - started) * 1000)
    except httpx.HTTPError as exc:
        log.info("webhook delivery failed: %s", type(exc).__name__)
        return None, "", "connection_failed", int((time.monotonic() - started) * 1000)


async def deliver(
    db: AsyncSession,
    settings: Settings,
    delivery_id: uuid.UUID,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[int | None, Webhook | None]:
    """Attempt one delivery. Returns (seconds until the next retry or None, the webhook if it
    was just turned off after repeated failures)."""
    row = await db.get(WebhookDelivery, delivery_id)
    if row is None or row.status != DeliveryStatus.PENDING:
        return None, None
    hook = await db.get(Webhook, row.webhook_id)
    now = datetime.now(UTC)
    if hook is None or not hook.enabled:
        row.status = DeliveryStatus.FAILED
        row.error = "webhook_off"
        row.next_attempt_at = None
        await db.commit()
        return None, None
    body = json.dumps(row.payload, ensure_ascii=False, separators=(",", ":")).encode()
    ts = int(now.timestamp())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "JustForms-Webhooks/1",
        "JustForms-Webhook-Id": row.event_id,
        "JustForms-Webhook-Timestamp": str(ts),
        "JustForms-Webhook-Signature": signature_header(
            active_secrets(settings, hook, now), row.event_id, ts, body
        ),
    }
    code, snippet, error, duration = await send(
        settings, hook.url, body, headers, transport=transport
    )
    row.attempt += 1
    row.response_code = code
    row.response_snippet = snippet or None
    row.error = error
    row.duration_ms = duration
    disabled: Webhook | None = None
    retry: int | None = None
    if code is not None and 200 <= code < 300:
        row.status = DeliveryStatus.SUCCEEDED
        row.delivered_at = now
        row.next_attempt_at = None
        if row.event != TEST_EVENT:
            hook.consecutive_failures = 0
    elif row.attempt < MAX_ATTEMPTS and row.event != TEST_EVENT:
        retry = RETRY_DELAYS[row.attempt - 1]
        row.next_attempt_at = now + timedelta(seconds=retry)
        if error is None and code is not None:
            row.error = f"http_{code}"
    else:
        row.status = DeliveryStatus.FAILED
        row.next_attempt_at = None
        if error is None and code is not None:
            row.error = f"http_{code}"
        if row.event != TEST_EVENT:
            hook.consecutive_failures += 1
            if hook.consecutive_failures >= AUTO_DISABLE_AFTER:
                hook.enabled = False
                hook.disabled_reason = "failures"
                disabled = hook
    await db.commit()
    return retry, disabled


async def due_deliveries(db: AsyncSession, now: datetime) -> list[uuid.UUID]:
    """Pending deliveries whose time has come (safety net if a queued job was lost)."""
    rows = await db.scalars(
        select(WebhookDelivery.id)
        .where(
            WebhookDelivery.status == DeliveryStatus.PENDING,
            WebhookDelivery.next_attempt_at <= now - timedelta(minutes=2),
        )
        .limit(500)
    )
    return list(rows)


async def purge_old(db: AsyncSession, now: datetime) -> int:
    from sqlalchemy import delete

    result = await db.execute(
        delete(WebhookDelivery).where(WebhookDelivery.created_at < now - timedelta(days=30))
    )
    await db.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
