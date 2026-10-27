"""Redis sliding-window rate limits (DESIGN 14.1).

Each limit is ``count`` hits per ``seconds`` for one key (an IP, an email, a form). Hits are
kept in a sorted set scored by time, so the window slides instead of resetting on the minute.
Defaults below can be changed with ``JUSTFORMS_RATE_LIMITS`` (``name=count/seconds,...``) and
turned off with ``JUSTFORMS_RATE_LIMIT_ENABLED=false``.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis

from app.auth.deps import RedisDep, SettingsDep
from app.config import Settings
from app.ids import uuid7
from app.net import client_ip


@dataclass(frozen=True)
class Limit:
    count: int
    seconds: int


DEFAULTS: dict[str, Limit] = {
    # Public (respondent) endpoints.
    "public_form": Limit(120, 60),  # per IP
    "public_submit": Limit(10, 60),  # per IP per form
    "upload_init": Limit(30, 60),  # per IP
    "upload_form": Limit(300, 3600),  # per form
    "upload_bytes": Limit(60, 60),  # local uploads (PUT), per IP
    "otp_request_email": Limit(3, 600),  # per email per form
    "otp_request_ip": Limit(10, 3600),  # per IP
    "otp_verify_ip": Limit(30, 3600),  # per IP
    "captcha_challenge": Limit(60, 60),  # per IP
    "verify": Limit(60, 60),  # verify page, per IP
    "verify_check": Limit(20, 600),  # "Check your copy" uploads, per IP
    "approval_link": Limit(60, 60),  # approver page requests, per IP
    "approval_code": Limit(3, 600),  # approver codes, per step
    "approval_decision": Limit(10, 600),  # approve/reject attempts, per step
    "branding": Limit(300, 60),  # logos, theme and manifest, per IP
    # Staff sign-in.
    "auth": Limit(30, 60),  # per IP
    # Invitations to join an organisation.
    "invite_user": Limit(50, 3600),  # addresses invited, per admin
    "invite_org": Limit(200, 86400),  # addresses invited, per organisation
    "invite_resend": Limit(3, 3600),  # per invitation
    "invite_link": Limit(60, 60),  # invitation page requests, per IP
    # Type-ahead member suggestions (Share page, Invite people).
    "member_search": Limit(120, 60),  # per user
    # "Notify by email" when sharing a form with members.
    "share_notify_user": Limit(50, 3600),  # people emailed, per sharer
    "share_notify_org": Limit(200, 86400),  # people emailed, per organisation
    # AI assistant (studio).
    "ai_request": Limit(40, 3600),  # per user
    "ai_request_org": Limit(400, 3600),  # per organisation
    "ai_import": Limit(10, 3600),  # paper forms read, per user
    # Insights page summaries (each one runs a query per question).
    "insights": Limit(120, 3600),  # per user
    # Notification test emails (to the person asking).
    "notify_test": Limit(5, 3600),  # per user
}


def limits(settings: Settings) -> dict[str, Limit]:
    out = dict(DEFAULTS)
    for entry in settings.rate_limits:
        name, _, spec = entry.partition("=")
        count, _, seconds = spec.partition("/")
        if name.strip() in out and count.strip().isdigit() and seconds.strip().isdigit():
            out[name.strip()] = Limit(int(count), int(seconds))
    return out


def _key(name: str, ident: str) -> str:
    # Hash identifiers so emails never appear in Redis keys.
    return f"rl:{name}:{hashlib.sha256(ident.encode()).hexdigest()[:32]}"


# Sliding window, checked and counted in one step so a concurrent burst can't all pass the
# check before any hit is counted. KEYS[1]: the window; ARGV: now, seconds, limit, n, member
# prefix. Returns nil when the n hits were counted, else the oldest hit's time (as a string).
_TAKE = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local n = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - window)
if redis.call('ZCARD', KEYS[1]) + n > tonumber(ARGV[3]) then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  return oldest[2] or ARGV[1]
end
for i = 1, n do
  redis.call('ZADD', KEYS[1], ARGV[1], ARGV[5] .. ':' .. i)
end
redis.call('EXPIRE', KEYS[1], window)
return nil
"""


async def take(redis: Redis, settings: Settings, name: str, ident: str, n: int) -> int | None:
    """Count ``n`` hits at once, all or nothing. Returns None when allowed, or seconds to wait
    when the ``n`` hits would go over the limit (then none are counted). Atomic."""
    if not settings.rate_limit_enabled or n <= 0:
        return None
    limit = limits(settings)[name]
    now = time.time()
    oldest = await redis.eval(  # type: ignore[misc]
        _TAKE,
        1,
        _key(name, ident),
        repr(now),
        str(limit.seconds),
        str(limit.count),
        str(n),
        str(uuid7()),
    )
    if oldest is None:
        return None
    first = float(oldest.decode() if isinstance(oldest, bytes) else oldest)
    return max(1, int(first + limit.seconds - now) + 1)


async def hit(redis: Redis, settings: Settings, name: str, ident: str) -> int | None:
    """Count one hit. Returns None when allowed, or seconds to wait when over the limit."""
    return await take(redis, settings, name, ident, 1)


async def count(redis: Redis, name: str, ident: str, seconds: int) -> int:
    """Hits for ``ident`` in the last ``seconds`` (without counting a new one)."""
    key = _key(name, ident)
    return int(await redis.zcount(key, time.time() - seconds, "+inf"))


async def record(redis: Redis, name: str, ident: str, seconds: int) -> None:
    """Record a hit without enforcing a limit (used for the "when busy" CAPTCHA counter)."""
    key = _key(name, ident)
    now = time.time()
    async with redis.pipeline(transaction=True) as pipe:
        pipe.zremrangebyscore(key, 0, now - seconds)
        pipe.zadd(key, {str(uuid7()): now})
        pipe.expire(key, seconds)
        await pipe.execute()


def too_many(retry_after: int) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "too_many_requests",
        headers={"Retry-After": str(retry_after)},
    )


async def enforce(redis: Redis, settings: Settings, name: str, ident: str) -> None:
    wait = await hit(redis, settings, name, ident)
    if wait is not None:
        raise too_many(wait)


def per_ip(name: str) -> Any:
    """FastAPI dependency: limit ``name`` per client IP."""

    async def dep(request: Request, redis: RedisDep, settings: SettingsDep) -> None:
        await enforce(redis, settings, name, client_ip(request, settings) or "unknown")

    return Depends(dep)
