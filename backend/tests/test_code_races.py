"""Concurrent guesses at one-time codes and bursts against rate limits (DESIGN 14.1).

Before the atomic checks, N concurrent guesses all read ``attempts=0`` and were all compared,
and a burst of N hits all passed the rate limit's check before any was counted.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from fakeredis import FakeAsyncRedis

from app import ratelimit
from app.auth import local, respondent
from app.config import Settings

EMAIL = "victim@example.org"
DEMO_CODE = "580317"


def _settings(**kwargs: Any) -> Settings:
    return Settings(environment="test", secret_key="x" * 40, oidc_issuer=None, **kwargs)


def _guesses(real: str, n: int = 300) -> list[str]:
    return [g for g in (f"{i:06d}" for i in range(n + 1)) if g != real][:n]


@pytest.fixture
def r() -> FakeAsyncRedis:
    return FakeAsyncRedis(decode_responses=True)


async def test_concurrent_login_guesses_compare_at_most_max_attempts(
    r: FakeAsyncRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(code_lockout_failures=1000)
    real = await local.issue_code(r, settings, EMAIL)
    compared = 0
    original = local._code_hmac

    def counting(s: Settings, e: str, c: str) -> str:
        nonlocal compared
        compared += 1
        return original(s, e, c)

    monkeypatch.setattr(local, "_code_hmac", counting)
    results = await asyncio.gather(
        *(local.verify_code(r, settings, EMAIL, g) for g in [*_guesses(real), real])
    )
    assert compared == settings.login_code_max_attempts
    assert not any(results)  # the real code came too late: the code was used up


async def test_concurrent_respondent_guesses_compare_at_most_max_attempts(
    r: FakeAsyncRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(code_lockout_failures=1000)
    form_id = uuid.uuid4()
    real = await respondent.issue_code(r, settings, form_id, EMAIL)
    compared = 0
    original = respondent._code_hmac

    def counting(*args: Any) -> str:
        nonlocal compared
        compared += 1
        return original(*args)

    monkeypatch.setattr(respondent, "_code_hmac", counting)
    results = await asyncio.gather(
        *(respondent.verify_code(r, settings, form_id, EMAIL, g) for g in _guesses(real))
    )
    assert compared == settings.respondent_code_max_attempts
    assert results.count("wrong") == settings.respondent_code_max_attempts - 1
    assert set(results) == {"wrong", "expired"}
    assert await respondent.verify_code(r, settings, form_id, EMAIL, real) == "expired"


async def test_correct_code_still_works_and_is_single_use(r: FakeAsyncRedis) -> None:
    settings = _settings()
    real = await local.issue_code(r, settings, EMAIL)
    assert not await local.verify_code(r, settings, EMAIL, "000000" if real != "000000" else "1")
    assert await local.verify_code(r, settings, EMAIL, real)
    assert not await local.verify_code(r, settings, EMAIL, real)
    # Concurrent correct guesses: only one signs in.
    real = await local.issue_code(r, settings, EMAIL)
    results = await asyncio.gather(*(local.verify_code(r, settings, EMAIL, real) for _ in range(5)))
    assert results.count(True) == 1


async def test_failures_lock_the_address_out_across_codes(r: FakeAsyncRedis) -> None:
    settings = _settings(code_lockout_failures=7)
    wrong = 0
    for _ in range(3):  # three code requests, five tries each
        real = await local.issue_code(r, settings, EMAIL)
        for g in _guesses(real, settings.login_code_max_attempts):
            await local.verify_code(r, settings, EMAIL, g)
            wrong += 1
    assert wrong == 15
    real = await local.issue_code(r, settings, EMAIL)
    assert not await local.verify_code(r, settings, EMAIL, real)  # locked out
    assert int(await r.get(local._lockout_key(EMAIL)) or 0) == 7
    # Another address is not affected.
    other = await local.issue_code(r, settings, "someone@example.org")
    assert await local.verify_code(r, settings, "someone@example.org", other)


async def test_successful_sign_in_does_not_count_as_a_failure(r: FakeAsyncRedis) -> None:
    settings = _settings(code_lockout_failures=3)
    for _ in range(5):
        real = await local.issue_code(r, settings, EMAIL)
        assert await local.verify_code(r, settings, EMAIL, real)
    assert await r.get(local._lockout_key(EMAIL)) is None


async def test_demo_code_is_locked_out_too(r: FakeAsyncRedis) -> None:
    settings = _settings(
        demo_login_code=DEMO_CODE, demo_login_emails=EMAIL, code_lockout_failures=6
    )
    for _ in range(2):
        real = await local.issue_code(r, settings, EMAIL)
        await asyncio.gather(
            *(
                local.verify_code(r, settings, EMAIL, g)
                for g in _guesses(real, 50)
                if g != DEMO_CODE
            )
        )
    await local.issue_code(r, settings, EMAIL)
    assert not await local.verify_code(r, settings, EMAIL, DEMO_CODE)


async def test_approval_step_lockout(r: FakeAsyncRedis) -> None:
    """Approver codes use the respondent codes keyed by the step: locked out per step."""
    settings = _settings(code_lockout_failures=5)
    step = uuid.uuid4()
    for _ in range(2):
        real = await respondent.issue_code(r, settings, step, EMAIL)
        await asyncio.gather(
            *(respondent.verify_code(r, settings, step, EMAIL, g) for g in _guesses(real, 20))
        )
    real = await respondent.issue_code(r, settings, step, EMAIL)
    assert await respondent.verify_code(r, settings, step, EMAIL, real) == "expired"
    other_step = uuid.uuid4()
    real = await respondent.issue_code(r, settings, other_step, EMAIL)
    assert await respondent.verify_code(r, settings, other_step, EMAIL, real) == "ok"


async def test_rate_limit_burst_allows_only_the_limit(r: FakeAsyncRedis) -> None:
    settings = _settings()
    limit = ratelimit.limits(settings)["auth"]
    out = await asyncio.gather(*(ratelimit.hit(r, settings, "auth", "1.2.3.4") for _ in range(300)))
    assert sum(1 for o in out if o is None) == limit.count
    assert all(o is not None and 1 <= o <= limit.seconds + 1 for o in out[limit.count :])


async def test_rate_limit_take_burst_is_all_or_nothing(r: FakeAsyncRedis) -> None:
    settings = _settings(rate_limits="invite_user=10/3600")
    out = await asyncio.gather(
        *(ratelimit.take(r, settings, "invite_user", "admin", 3) for _ in range(10))
    )
    assert sum(1 for o in out if o is None) == 3  # 9 of 10 counted
    assert await ratelimit.count(r, "invite_user", "admin", 3600) == 9
