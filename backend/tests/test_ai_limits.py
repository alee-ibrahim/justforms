"""Token reservations (no overshoot when requests run in parallel) and stopping a request."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fakeredis import FakeAsyncRedis

from app.ai import limits
from app.ai.limits import Allowance, BudgetExceeded
from app.ai.types import Usage
from app.config import Settings


def settings(user: int, org: int = 0) -> Settings:
    return Settings(
        environment="test",
        ai_daily_tokens_per_user=user,
        ai_daily_tokens_per_org=org,
        ai_max_output_tokens=1000,
    )


async def used(redis: FakeAsyncRedis, s: Settings, user: uuid.UUID, org: uuid.UUID) -> list[int]:
    return [int(v or 0) for v in await redis.mget(*limits.token_keys(s, user, org))]


async def test_parallel_reservations_never_pass_the_cap() -> None:
    redis = FakeAsyncRedis()
    s = settings(10_000)
    user, org = uuid.uuid4(), uuid.uuid4()
    allowances = [Allowance(redis, s, user, org) for _ in range(10)]

    async def one(a: Allowance) -> bool:
        try:
            await a.reserve(2000)  # 2000 + 1000 output each
        except BudgetExceeded:
            return False
        await asyncio.sleep(0.01)
        await a.settle(Usage(1500, 500))
        return True

    results = await asyncio.gather(*(one(a) for a in allowances))
    assert sum(results) == 3  # 3 x 3000 fit in 10,000; the 4th would pass it
    assert (await used(redis, s, user, org))[0] == 3 * 2000


async def test_first_call_of_the_day_and_refunds() -> None:
    redis = FakeAsyncRedis()
    s = settings(500, org=100_000)
    user, org = uuid.uuid4(), uuid.uuid4()
    a = Allowance(redis, s, user, org)
    # A cap below one call's worst case still allows the day's first call...
    await a.reserve(100)
    await a.settle(Usage(80, 20))
    assert await used(redis, s, user, org) == [100, 100]
    # ...but not a second one that would pass it.
    with pytest.raises(BudgetExceeded):
        await a.reserve(100)
    assert await used(redis, s, user, org) == [100, 100]
    # A call that never returned keeps its input estimate and gives back the rest.
    b = Allowance(redis, settings(0, org=0), user, org)
    await b.reserve(450)
    await b.release()
    assert await used(redis, s, user, org) == [550, 550]
    with pytest.raises(BudgetExceeded):
        await limits.check(redis, s, user, org)


async def test_a_newer_request_stops_the_older_one() -> None:
    redis = FakeAsyncRedis()
    user, sid = uuid.uuid4(), uuid.uuid4()
    first = await limits.claim(redis, user, 60)
    stop_first = limits.should_stop(redis, user, sid, first)
    assert not await stop_first()
    started = asyncio.Event()

    async def slow() -> None:
        started.set()
        await asyncio.sleep(30)

    async def newer() -> None:
        await started.wait()
        await limits.claim(redis, user, 60)

    stopped, _ = await asyncio.wait_for(
        asyncio.gather(limits.run_stoppable(slow, stop_first, poll=0.02), newer()), 5
    )
    assert stopped is True
    # Closing the chat ("fresh") stops it too.
    second = await limits.claim(redis, user, 60)
    stop_second = limits.should_stop(redis, user, sid, second)
    assert not await stop_second()
    await limits.stop_sessions(redis, [sid])
    assert await stop_second()
