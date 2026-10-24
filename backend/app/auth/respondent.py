"""Respondent access for forms that ask people to confirm their email (DESIGN 8.2).

1. ``request_code``: a 6-digit code, stored only as an HMAC keyed with the app secret, valid
   for ``respondent_code_ttl_seconds`` and ``respondent_code_max_attempts`` tries. The API
   answers 202 whether or not the address may respond, so it can't be used to probe.
2. ``verify_code``: on success a respondent token is issued: a JWT (HS256, key derived from
   the app secret) with ``form_id``, ``email`` and ``exp``. The public form keeps it in
   memory and sends ``Authorization: Bearer``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey
from redis.asyncio import Redis

from app.config import Settings

AUDIENCE = "justforms-respondent"


@dataclass
class Respondent:
    form_id: uuid.UUID
    email: str


def _form_email_key(form_id: uuid.UUID, email: str) -> str:
    return hashlib.sha256(f"{form_id}:{email}".encode()).hexdigest()


def _code_hmac(settings: Settings, form_id: uuid.UUID, email: str, code: str) -> str:
    return hmac.new(
        settings.secret_key_bytes, f"respondent:{form_id}:{email}:{code}".encode(), "sha256"
    ).hexdigest()


def _token_key(settings: Settings) -> OctKey:
    raw = hashlib.sha256(b"justforms:respondent-token:" + settings.secret_key_bytes).digest()
    return OctKey.import_key(raw)


def domain_allowed(email: str, domains: list[str]) -> bool:
    if not domains:
        return True
    host = email.rsplit("@", 1)[-1].lower()
    return any(host == d.lower().lstrip("@") for d in domains)


async def issue_code(redis: Redis, settings: Settings, form_id: uuid.UUID, email: str) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    payload = {"hmac": _code_hmac(settings, form_id, email, code), "attempts": 0}
    await redis.set(
        f"respondent_code:{_form_email_key(form_id, email)}",
        json.dumps(payload),
        ex=settings.respondent_code_ttl_seconds,
    )
    return code


async def verify_code(
    redis: Redis, settings: Settings, form_id: uuid.UUID, email: str, code: str
) -> str:
    """``ok``, ``wrong`` (try again) or ``expired`` (no code, or out of tries)."""
    key = f"respondent_code:{_form_email_key(form_id, email)}"
    raw = await redis.get(key)
    if raw is None:
        return "expired"
    data = json.loads(raw)
    if data["attempts"] >= settings.respondent_code_max_attempts:
        await redis.delete(key)
        return "expired"
    if hmac.compare_digest(data["hmac"], _code_hmac(settings, form_id, email, code.strip())):
        await redis.delete(key)
        return "ok"
    data["attempts"] += 1
    if data["attempts"] >= settings.respondent_code_max_attempts:
        await redis.delete(key)
        return "expired"
    ttl = await redis.ttl(key)
    await redis.set(key, json.dumps(data), ex=max(ttl, 1))
    return "wrong"


def issue_token(settings: Settings, form_id: uuid.UUID, email: str) -> str:
    now = int(time.time())
    claims = {
        "aud": AUDIENCE,
        "form_id": str(form_id),
        "email": email,
        "iat": now,
        "exp": now + settings.respondent_token_seconds,
    }
    return jwt.encode({"alg": "HS256"}, claims, _token_key(settings))


def read_token(settings: Settings, token: str, form_id: uuid.UUID) -> Respondent | None:
    try:
        decoded = jwt.decode(token, _token_key(settings), algorithms=["HS256"])
        registry = jwt.JWTClaimsRegistry(
            aud={"essential": True, "value": AUDIENCE},
            exp={"essential": True},
            form_id={"essential": True, "value": str(form_id)},
            email={"essential": True},
        )
        registry.validate(decoded.claims)
    except (JoseError, ValueError):
        return None
    return Respondent(form_id=form_id, email=str(decoded.claims["email"]))


def bearer(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None
