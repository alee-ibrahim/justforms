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
import secrets
import time
import uuid
from dataclasses import dataclass

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey
from redis.asyncio import Redis

from app.auth import codes
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


def _code_key(form_id: uuid.UUID, email: str) -> str:
    # v2: a hash {hmac, attempts} checked atomically (app.auth.codes).
    return f"respondent_code:v2:{_form_email_key(form_id, email)}"


def _lockout_key(form_id: uuid.UUID, email: str) -> str:
    # Per form and address; for approver codes the "form" is the approval step.
    return f"respondent_code_fail:{_form_email_key(form_id, email)}"


async def issue_code(redis: Redis, settings: Settings, form_id: uuid.UUID, email: str) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    await codes.store(
        redis,
        _code_key(form_id, email),
        _code_hmac(settings, form_id, email, code),
        settings.respondent_code_ttl_seconds,
    )
    return code


async def verify_code(
    redis: Redis, settings: Settings, form_id: uuid.UUID, email: str, code: str
) -> str:
    """``ok``, ``wrong`` (try again) or ``expired`` (no code, out of tries, or locked out
    after too many failures: see :mod:`app.auth.codes`)."""
    code = code.strip()
    result = await codes.check(
        redis,
        settings,
        key=_code_key(form_id, email),
        lockout_key=_lockout_key(form_id, email),
        max_attempts=settings.respondent_code_max_attempts,
        matches=lambda stored: codes.same(stored, _code_hmac(settings, form_id, email, code)),
    )
    return "expired" if result == "locked" else result


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
