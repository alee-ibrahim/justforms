"""Atomic checks of emailed one-time codes (staff login, respondent and approver codes).

A code is stored as a Redis hash ``{hmac, attempts}``. Checking a guess first *reserves* an
attempt in one Lua script (``HINCRBY attempts``; refused once the count goes past the maximum)
and only then compares, so concurrent guesses can't all read ``attempts=0``: at most
``max_attempts`` guesses are ever compared per code (DESIGN 14.1).

The same script counts attempts on a second key that outlives the code (``lockout_key``):
after ``code_lockout_failures`` failed guesses within ``code_lockout_seconds`` every check is
refused, whatever codes are requested in between. A correct code gives its attempt back.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import Literal

from redis.asyncio import Redis

from app.config import Settings

Result = Literal["ok", "wrong", "expired", "locked"]

# KEYS[1]: code hash, KEYS[2]: failure counter.
# ARGV[1]: max attempts per code, ARGV[2]: failures before lockout, ARGV[3]: lockout window.
# Returns {status, hmac, last}; status is "expired", "locked" or "try".
_RESERVE = """
if redis.call('EXISTS', KEYS[1]) == 0 then return {'expired', '', 0} end
local fails = tonumber(redis.call('GET', KEYS[2]) or '0')
if fails >= tonumber(ARGV[2]) then
  redis.call('DEL', KEYS[1])
  return {'locked', '', 0}
end
local n = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
local max = tonumber(ARGV[1])
if n > max then
  redis.call('DEL', KEYS[1])
  return {'expired', '', 0}
end
local f = redis.call('INCR', KEYS[2])
if f == 1 then redis.call('EXPIRE', KEYS[2], ARGV[3]) end
local digest = redis.call('HGET', KEYS[1], 'hmac') or ''
local last = 0
if n >= max then
  redis.call('DEL', KEYS[1])
  last = 1
end
return {'try', digest, last}
"""


async def store(redis: Redis, key: str, digest: str, ttl: int) -> None:
    """Store a new code (replacing the previous one, which also resets its attempts)."""
    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(key)
        pipe.hset(key, mapping={"hmac": digest, "attempts": 0})
        pipe.expire(key, ttl)
        await pipe.execute()


def _text(value: object) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


async def check(
    redis: Redis,
    settings: Settings,
    *,
    key: str,
    lockout_key: str,
    max_attempts: int,
    matches: Callable[[str], bool],
) -> Result:
    """Check one guess. ``matches(stored_hmac)`` is only called for a reserved attempt."""
    status, digest, last = await redis.eval(  # type: ignore[misc]
        _RESERVE,
        2,
        key,
        lockout_key,
        str(max_attempts),
        str(settings.code_lockout_failures),
        str(settings.code_lockout_seconds),
    )
    status = _text(status)
    if status != "try":
        return "locked" if status == "locked" else "expired"
    digest = _text(digest)
    if digest and matches(digest):
        # Single use: the last attempt deleted the code already; otherwise only the request
        # that deletes it wins (two concurrent correct guesses can't both sign in).
        if int(last) or await redis.delete(key):
            if await redis.decr(lockout_key) <= 0:
                await redis.delete(lockout_key)
            return "ok"
        return "expired"
    return "expired" if int(last) else "wrong"


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
