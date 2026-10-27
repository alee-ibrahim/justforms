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
import secrets

from redis.asyncio import Redis

from app.auth import codes
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


def _code_key(email: str) -> str:
    # v2: a hash {hmac, attempts} checked atomically (app.auth.codes).
    return f"login_code:v2:{_email_key(email)}"


def _lockout_key(email: str) -> str:
    return f"login_code_fail:{_email_key(email)}"


async def issue_code(redis: Redis, settings: Settings, email: str) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    await codes.store(
        redis, _code_key(email), _code_hmac(settings, email, code), settings.login_code_ttl_seconds
    )
    return code


def _demo_code_matches(settings: Settings, email: str, code: str) -> bool:
    if not settings.demo_login_enabled or settings.demo_login_code is None:
        return False
    if email not in settings.demo_login_emails:
        return False
    return hmac.compare_digest(settings.demo_login_code.get_secret_value(), code)


async def verify_code(redis: Redis, settings: Settings, email: str, code: str) -> bool:
    """True for the emailed code (or the demo code for an allow-listed address).

    At most ``login_code_max_attempts`` guesses are compared per code, even concurrently, and
    after ``code_lockout_failures`` failures in ``code_lockout_seconds`` the address is locked
    out (this also covers the fixed demo code across code requests)."""
    code = code.strip()

    def matches(stored: str) -> bool:
        return codes.same(stored, _code_hmac(settings, email, code)) or _demo_code_matches(
            settings, email, code
        )

    result = await codes.check(
        redis,
        settings,
        key=_code_key(email),
        lockout_key=_lockout_key(email),
        max_attempts=settings.login_code_max_attempts,
        matches=matches,
    )
    return result == "ok"
