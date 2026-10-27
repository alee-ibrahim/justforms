"""ALTCHA payloads can't be spliced or replayed; siteverify answers must match this host."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Any

import httpx
import pytest
from fakeredis import FakeAsyncRedis
from pydantic import SecretStr

from app import captcha
from app.config import Settings


def _settings(**update: Any) -> Settings:
    return Settings(
        environment="test", secret_key="x" * 40, captcha_provider="altcha", **update
    )


def _solve(ch: dict[str, Any]) -> int:
    return next(
        i
        for i in range(ch["maxnumber"] + 1)
        if hashlib.sha256(f"{ch['salt']}{i}".encode()).hexdigest() == ch["challenge"]
    )


def _token(payload: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(payload).encode()).decode()


def _payload(ch: dict[str, Any], number: int, **over: Any) -> dict[str, Any]:
    base = {k: ch[k] for k in ("algorithm", "challenge", "salt", "signature")}
    return {**base, "number": number, **over}


async def test_altcha_salt_splice_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(altcha_max_number=1000)
    redis = FakeAsyncRedis(decode_responses=True)
    for _ in range(50):  # need a number with at least two digits to splice
        ch = captcha.altcha_challenge(s)
        n = _solve(ch)
        if n >= 10:
            break
    full = f"{ch['salt']}{n}"
    spliced = _payload(ch, int(full[-1]), salt=full[:-1])
    assert hashlib.sha256(f"{spliced['salt']}{spliced['number']}".encode()).hexdigest() == (
        ch["challenge"]
    )
    later = time.time() + 10 * 24 * 3600
    monkeypatch.setattr(captcha.time, "time", lambda: later)
    assert not await captcha._verify_altcha(redis, s, _token(spliced))
    assert not await captcha._verify_altcha(redis, s, _token(_payload(ch, n)))


async def test_altcha_signature_binds_salt_and_caps_expiry() -> None:
    s = _settings(altcha_max_number=1000)
    redis = FakeAsyncRedis(decode_responses=True)
    ch = captcha.altcha_challenge(s)
    n = _solve(ch)
    # A forged later expiry with a valid-looking salt fails the signature.
    far = int(time.time()) + 10 * 24 * 3600
    salt = ch["salt"].split("?")[0] + f"?expires={far}&"
    challenge = hashlib.sha256(f"{salt}{n}".encode()).hexdigest()
    forged = _payload(ch, n, salt=salt, challenge=challenge)
    assert not await captcha._verify_altcha(redis, s, _token(forged))
    # Even correctly signed (leaked key), an expiry beyond the TTL is refused.
    forged["signature"] = captcha._sign(s, challenge, salt)
    assert not await captcha._verify_altcha(redis, s, _token(forged))
    # Out-of-range numbers are refused before hashing.
    assert not await captcha._verify_altcha(redis, s, _token(_payload(ch, 1001)))
    assert not await captcha._verify_altcha(redis, s, _token(_payload(ch, -1)))
    assert not await captcha._verify_altcha(redis, s, _token(_payload(ch, True)))
    assert await captcha._verify_altcha(redis, s, _token(_payload(ch, n)))


async def test_altcha_used_marker_lasts_until_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(altcha_max_number=1000)
    redis = FakeAsyncRedis(decode_responses=True)
    ch = captcha.altcha_challenge(s)
    tok = _token(_payload(ch, _solve(ch)))
    assert await captcha._verify_altcha(redis, s, tok)
    ttl = await redis.ttl(f"altcha_used:{ch['challenge']}")
    expires = int(ch["salt"].split("expires=")[1].rstrip("&"))
    assert ttl >= expires - int(time.time())
    # Replays fail while the marker lives, and after it is gone the challenge has expired.
    assert not await captcha._verify_altcha(redis, s, tok)
    await redis.flushall()
    later = time.time() + captcha.CHALLENGE_TTL + 61
    monkeypatch.setattr(captcha.time, "time", lambda: later)
    assert not await captcha._verify_altcha(redis, s, tok)


def _remote(provider: str = "turnstile") -> Settings:
    return Settings(
        environment="test",
        secret_key="x" * 40,
        captcha_provider=provider,
        captcha_site_key="site",
        captcha_secret_key=SecretStr("secret"),
        public_url="https://forms.example.org",
    )


@pytest.mark.parametrize(
    ("body", "ok"),
    [
        ({"success": True, "hostname": "forms.example.org"}, True),
        ({"success": True, "hostname": "FORMS.example.org", "action": "justforms"}, True),
        ({"success": True, "hostname": "evil.example"}, False),
        ({"success": True}, False),
        ({"success": True, "hostname": "forms.example.org", "action": "login"}, False),
        ({"success": False, "hostname": "forms.example.org"}, False),
        ({"success": "yes", "hostname": "forms.example.org"}, False),
    ],
)
async def test_siteverify_checks_hostname_and_action(body: dict[str, Any], ok: bool) -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=body))
    for provider in ("turnstile", "hcaptcha"):
        assert await captcha._verify_remote(_remote(provider), "tok", None, transport) is ok
