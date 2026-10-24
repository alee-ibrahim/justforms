"""Optional CAPTCHA on public submits and code requests (DESIGN 14.2).

Providers (``JUSTFORMS_CAPTCHA_PROVIDER``):

- ``altcha``: a self-hosted proof of work. The server hands out a challenge
  ``sha256(salt + n)`` for a secret ``n`` below ``altcha_max_number``, signed with an HMAC of
  the app key; the browser finds ``n`` and sends it back. No third party is involved.
  Compatible with the ALTCHA payload format (base64 JSON with ``algorithm``, ``challenge``,
  ``number``, ``salt``, ``signature``).
- ``turnstile`` and ``hcaptcha``: the provider's widget; the token is checked server-side
  with the provider's siteverify API.

Each form chooses ``off`` (default), ``always`` or ``auto`` ("when busy": after
``captcha_busy_threshold`` responses to the form within an hour).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any, Literal

import httpx
from redis.asyncio import Redis

from app.config import Settings
from app.ratelimit import count

log = logging.getLogger(__name__)

CaptchaMode = Literal["off", "always", "auto"]
BUSY_COUNTER = "form_submits_hour"
CHALLENGE_TTL = 30 * 60

VERIFY_URLS = {
    "turnstile": "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    "hcaptcha": "https://api.hcaptcha.com/siteverify",
}


def form_mode(form_settings: dict[str, Any] | None) -> CaptchaMode:
    mode = (form_settings or {}).get("captcha", "off")
    return mode if mode in ("off", "always", "auto") else "off"


async def required(
    redis: Redis, settings: Settings, form_id: str, form_settings: dict[str, Any] | None
) -> bool:
    """Whether a submit to this form must carry a CAPTCHA token right now."""
    if settings.captcha_provider == "none":
        return False
    mode = form_mode(form_settings)
    if mode == "always":
        return True
    if mode == "auto":
        busy = await count(redis, BUSY_COUNTER, form_id, 3600)
        return busy >= settings.captcha_busy_threshold
    return False


def _altcha_key(settings: Settings) -> bytes:
    return hashlib.sha256(b"justforms:altcha:" + settings.secret_key_bytes).digest()


def _sign(settings: Settings, challenge: str) -> str:
    return hmac.new(_altcha_key(settings), challenge.encode(), "sha256").hexdigest()


def altcha_challenge(settings: Settings) -> dict[str, Any]:
    expires = int(time.time()) + CHALLENGE_TTL
    salt = f"{secrets.token_hex(12)}?expires={expires}"
    number = secrets.randbelow(settings.altcha_max_number)
    challenge = hashlib.sha256(f"{salt}{number}".encode()).hexdigest()
    return {
        "algorithm": "SHA-256",
        "challenge": challenge,
        "maxnumber": settings.altcha_max_number,
        "salt": salt,
        "signature": _sign(settings, challenge),
    }


def public_config(settings: Settings, needed: bool) -> dict[str, Any] | None:
    """What the public form needs to show the check (None when it isn't needed)."""
    if not needed:
        return None
    out: dict[str, Any] = {"provider": settings.captcha_provider}
    if settings.captcha_provider == "altcha":
        out["challenge"] = altcha_challenge(settings)
    else:
        out["siteKey"] = settings.captcha_site_key
    return out


async def _verify_altcha(redis: Redis, settings: Settings, token: str) -> bool:
    try:
        data = json.loads(base64.b64decode(token, validate=True))
        challenge, salt = str(data["challenge"]), str(data["salt"])
        number, signature = int(data["number"]), str(data["signature"])
    except (ValueError, KeyError, TypeError, binascii.Error):
        return False
    if data.get("algorithm") != "SHA-256":
        return False
    if not hmac.compare_digest(_sign(settings, challenge), signature):
        return False
    _, _, expires = salt.partition("?expires=")
    if not expires.isdigit() or int(expires) < time.time():
        return False
    if hashlib.sha256(f"{salt}{number}".encode()).hexdigest() != challenge:
        return False
    # Each solved challenge works once.
    return bool(await redis.set(f"altcha_used:{challenge}", "1", nx=True, ex=CHALLENGE_TTL))


async def _verify_remote(settings: Settings, token: str, ip: str | None) -> bool:
    assert settings.captcha_secret_key is not None
    form = {"secret": settings.captcha_secret_key.get_secret_value(), "response": token}
    if ip:
        form["remoteip"] = ip
    if settings.captcha_provider == "hcaptcha":
        form["sitekey"] = settings.captcha_site_key
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(VERIFY_URLS[settings.captcha_provider], data=form)
        return bool(res.json().get("success"))
    except (httpx.HTTPError, ValueError):
        log.warning("CAPTCHA verification request failed")
        return False


async def verify(redis: Redis, settings: Settings, token: str | None, ip: str | None) -> bool:
    if not token or len(token) > 4096:
        return False
    if settings.captcha_provider == "altcha":
        return await _verify_altcha(redis, settings, token)
    if settings.captcha_provider in VERIFY_URLS:
        return await _verify_remote(settings, token, ip)
    return True
