"""Local staff login with emailed one-time codes, for installs without an IdP (DESIGN 8.1).

Only existing users can log in (created with ``python -m app.cli create-admin`` or added by
an org admin). Codes are 6 digits, stored only as HMAC-SHA256 keyed with the app secret,
valid for ``login_code_ttl_seconds`` and ``login_code_max_attempts`` tries. The request
endpoint answers the same way whether or not the email is known.

Demo instances may set ``JUSTFORMS_DEMO_LOGIN_CODE`` with an allow-list of addresses: for those
addresses that fixed code is accepted in place of the emailed one, through the same request,
attempt and rate limits (a code must still have been requested).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets

from redis.asyncio import Redis

from app.config import Settings

REQUESTS_PER_EMAIL = 3  # per code TTL window
REQUESTS_PER_IP = 10  # per hour


def _email_key(email: str) -> str:
    return hashlib.sha256(email.encode()).hexdigest()


def _code_hmac(settings: Settings, email: str, code: str) -> str:
    return hmac.new(settings.secret_key_bytes, f"{email}:{code}".encode(), "sha256").hexdigest()


async def rate_limited(redis: Redis, settings: Settings, email: str, ip: str | None) -> bool:
    """Count this request; True if the email or IP is over its limit."""
    email_key = f"login_code_rl:email:{_email_key(email)}"
    n = await redis.incr(email_key)
    if n == 1:
        await redis.expire(email_key, settings.login_code_ttl_seconds)
    over = n > REQUESTS_PER_EMAIL
    if ip:
        ip_key = f"login_code_rl:ip:{ip}"
        m = await redis.incr(ip_key)
        if m == 1:
            await redis.expire(ip_key, 3600)
        over = over or m > REQUESTS_PER_IP
    return over


async def issue_code(redis: Redis, settings: Settings, email: str) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    payload = {"hmac": _code_hmac(settings, email, code), "attempts": 0}
    await redis.set(
        f"login_code:{_email_key(email)}", json.dumps(payload), ex=settings.login_code_ttl_seconds
    )
    return code


def _demo_code_matches(settings: Settings, email: str, code: str) -> bool:
    if not settings.demo_login_enabled or settings.demo_login_code is None:
        return False
    if email not in settings.demo_login_emails:
        return False
    return hmac.compare_digest(settings.demo_login_code.get_secret_value(), code)


async def verify_code(redis: Redis, settings: Settings, email: str, code: str) -> bool:
    key = f"login_code:{_email_key(email)}"
    raw = await redis.get(key)
    if raw is None:
        return False
    data = json.loads(raw)
    if data["attempts"] >= settings.login_code_max_attempts:
        await redis.delete(key)
        return False
    code = code.strip()
    if hmac.compare_digest(data["hmac"], _code_hmac(settings, email, code)) or _demo_code_matches(
        settings, email, code
    ):
        await redis.delete(key)  # single use
        return True
    data["attempts"] += 1
    if data["attempts"] >= settings.login_code_max_attempts:
        await redis.delete(key)
    else:
        ttl = await redis.ttl(key)
        await redis.set(key, json.dumps(data), ex=max(ttl, 1))
    return False
