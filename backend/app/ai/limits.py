"""Token allowances, size estimates and the one-AI-request-per-person rule.

Allowances: each provider call first *reserves* its worst case (the request's characters / 3
plus ``max_output_tokens``) against the person's and the organisation's daily allowance in
one atomic step, and is refused when that would take either past its cap. After the call the
reservation is replaced by the real usage (estimated from characters when the provider
reports none). So requests running in parallel can't all pass a check before any of them is
charged. The first call of the day always gets through, so an allowance smaller than one
call's worst case still allows one call.

One AI request per person: starting a request (an Ask question or a builder request, on any
form) makes it the person's current one; an older request still running notices within
``CANCEL_POLL_SECONDS`` and stops, as it does when its chat is closed with "fresh".
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from redis.asyncio import Redis

from app.ai.types import ChatMessage, ToolSpec, TurnResult, Usage
from app.config import Settings

CHARS_PER_TOKEN = 3
# An image counts as this many input tokens in the estimate.
IMAGE_TOKENS = 1600
CANCEL_POLL_SECONDS = 0.5
KEY_TTL = 2 * 24 * 3600


class BudgetExceeded(Exception):
    """The person's or organisation's daily token allowance is used up."""


def request_chars(system: str, messages: list[ChatMessage], tools: list[ToolSpec]) -> int:
    """Characters of one provider request (system prompt, conversation, tool results and
    tool definitions)."""
    n = len(system)
    for m in messages:
        n += len(m.text)
        n += sum(len(json.dumps(c.arguments, ensure_ascii=False)) for c in m.tool_calls)
        n += sum(len(json.dumps(r.content, ensure_ascii=False)) for r in m.tool_results)
    n += sum(len(t.description) + len(json.dumps(t.parameters)) for t in tools)
    return n


def estimate_input(system: str, messages: list[ChatMessage], tools: list[ToolSpec]) -> int:
    images = sum(len(m.images) for m in messages)
    return request_chars(system, messages, tools) // CHARS_PER_TOKEN + images * IMAGE_TOKENS + 1


def usage_of(result: TurnResult, estimated_input: int) -> Usage:
    """The provider's usage, or an estimate from characters when it reports none."""
    if result.usage.total:
        return result.usage
    out = len(result.text) + sum(
        len(json.dumps(c.arguments, ensure_ascii=False)) for c in result.tool_calls
    )
    return Usage(estimated_input, out // CHARS_PER_TOKEN + 1)


def _day(settings: Settings) -> str:
    return datetime.now(settings.tz).strftime("%Y%m%d")


def token_keys(settings: Settings, user_id: uuid.UUID, org_id: uuid.UUID) -> tuple[str, str]:
    day = _day(settings)
    return f"ai:tokens:user:{user_id}:{day}", f"ai:tokens:org:{org_id}:{day}"


async def check(redis: Redis, settings: Settings, user_id: uuid.UUID, org_id: uuid.UUID) -> None:
    """Refuse when an allowance is already used up (before a request starts)."""
    used_user, used_org = await redis.mget(*token_keys(settings, user_id, org_id))
    user_cap, org_cap = settings.ai_daily_tokens_per_user, settings.ai_daily_tokens_per_org
    if user_cap and int(used_user or 0) >= user_cap:
        raise BudgetExceeded
    if org_cap and int(used_org or 0) >= org_cap:
        raise BudgetExceeded


async def _add(redis: Redis, keys: tuple[str, ...], amount: int) -> list[int]:
    async with redis.pipeline(transaction=True) as pipe:
        for key in keys:
            pipe.incrby(key, amount)
            pipe.expire(key, KEY_TTL)
        out = await pipe.execute()
    return [int(v) for v in out[::2]]


class Allowance:
    """Reservations for one request's provider calls (see the module docstring)."""

    def __init__(
        self, redis: Redis, settings: Settings, user_id: uuid.UUID, org_id: uuid.UUID
    ) -> None:
        self.redis = redis
        self.keys = token_keys(settings, user_id, org_id)
        self.caps = (settings.ai_daily_tokens_per_user, settings.ai_daily_tokens_per_org)
        self.max_output = settings.ai_max_output_tokens
        self.reserved = 0
        self.reserved_input = 0

    async def reserve(self, estimated_input: int) -> None:
        """Reserve one call's worst case; ``BudgetExceeded`` when it doesn't fit."""
        await self.release()
        estimated_input = max(1, estimated_input)
        amount = estimated_input + self.max_output
        totals = await _add(self.redis, self.keys, amount)
        for total, cap in zip(totals, self.caps, strict=True):
            if cap and total > cap and total - amount > 0:
                await _add(self.redis, self.keys, -amount)
                raise BudgetExceeded
        self.reserved, self.reserved_input = amount, estimated_input

    async def settle(self, usage: Usage) -> None:
        """Replace the reservation with what the call really used."""
        delta = usage.total - self.reserved
        self.reserved = self.reserved_input = 0
        if delta:
            await _add(self.redis, self.keys, delta)

    async def release(self) -> None:
        """A reserved call that didn't return (error, stop, timeout): its input is kept as
        used (the provider may have read it), the rest is given back."""
        if not self.reserved:
            return
        delta = self.reserved_input - self.reserved
        self.reserved = self.reserved_input = 0
        if delta:
            await _add(self.redis, self.keys, delta)


# -- one AI request per person ----------------------------------------------------------


def active_key(user_id: uuid.UUID) -> str:
    return f"ai:active:{user_id}"


def cancel_key(session_id: uuid.UUID) -> str:
    return f"ai:cancel:{session_id}"


async def claim(redis: Redis, user_id: uuid.UUID, ttl: int) -> str:
    """Make a new request the person's current one; returns its token. Older requests of
    the person stop at their next check."""
    token = uuid.uuid4().hex
    await redis.set(active_key(user_id), token, ex=ttl)
    return token


async def is_current(redis: Redis, user_id: uuid.UUID, token: str) -> bool:
    value = await redis.get(active_key(user_id))
    if isinstance(value, bytes):
        value = value.decode()
    return bool(value == token)


async def unclaim(redis: Redis, user_id: uuid.UUID, token: str) -> None:
    if await is_current(redis, user_id, token):
        await redis.delete(active_key(user_id))


async def stop_sessions(redis: Redis, session_ids: list[uuid.UUID]) -> None:
    """Ask the requests running in these chats (if any) to stop."""
    for sid in session_ids:
        await redis.set(cancel_key(sid), "1", ex=300)


def should_stop(
    redis: Redis, user_id: uuid.UUID, session_id: uuid.UUID, token: str
) -> Callable[[], Awaitable[bool]]:
    """The request was stopped, its chat closed, or the person started another request."""

    async def check_() -> bool:
        if await redis.exists(cancel_key(session_id)):
            return True
        return not await is_current(redis, user_id, token)

    return check_


async def run_stoppable(
    work: Callable[[], Awaitable[None]],
    should_cancel: Callable[[], Awaitable[bool]],
    poll: float | None = None,
) -> bool:
    """Run ``work()``, checking ``should_cancel`` every ``poll`` seconds meanwhile (also
    during a provider call or a database query). Returns True when it was stopped."""
    interval = CANCEL_POLL_SECONDS if poll is None else poll

    async def watch() -> None:
        while True:
            await asyncio.sleep(interval)
            if await should_cancel():
                return

    job: asyncio.Future[Any] = asyncio.ensure_future(work())
    watcher: asyncio.Future[Any] = asyncio.ensure_future(watch())
    try:
        done, _ = await asyncio.wait({job, watcher}, return_when=asyncio.FIRST_COMPLETED)
        if job in done:
            job.result()
            return False
        return True
    finally:
        for t in (job, watcher):
            if not t.done():
                t.cancel()
        await asyncio.gather(job, watcher, return_exceptions=True)
