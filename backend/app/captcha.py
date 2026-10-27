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
import re
import secrets
import time
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from redis.asyncio import Redis

from app.config import Settings
from app.ratelimit import count

log = logging.getLogger(__name__)

CaptchaMode = Literal["off", "always", "auto"]
BUSY_COUNTER = "form_submits_hour"
CHALLENGE_TTL = 30 * 60
# The action the studio widget sends (Turnstile); a token for another action is refused.
WIDGET_ACTION = "justforms"

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


def _sign(settings: Settings, challenge: str, salt: str) -> str:
    # The challenge is fixed-length hex, so ``challenge:salt`` is unambiguous: the signature
    # binds the exact salt (and with it the expiry) to the challenge.
    msg = f"{challenge}:{salt}".encode()
    return hmac.new(_altcha_key(settings), msg, "sha256").hexdigest()


def altcha_challenge(settings: Settings) -> dict[str, Any]:
    expires = int(time.time()) + CHALLENGE_TTL
    # The trailing "&" (as the ALTCHA library does) ends the salt, so digits of the number
    # can't be moved into the expiry.
    salt = f"{secrets.token_hex(12)}?expires={expires}&"
    number = secrets.randbelow(settings.altcha_max_number)
    challenge = hashlib.sha256(f"{salt}{number}".encode()).hexdigest()
    return {
        "algorithm": "SHA-256",
        "challenge": challenge,
        "maxnumber": settings.altcha_max_number,
        "salt": salt,
        "signature": _sign(settings, challenge, salt),
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


_SALT = re.compile(r"[0-9a-f]{24}\?expires=([0-9]{1,12})&")
_HEX64 = re.compile(r"[0-9a-f]{64}")


async def _verify_altcha(redis: Redis, settings: Settings, token: str) -> bool:
    try:
        data = json.loads(base64.b64decode(token, validate=True))
        challenge, salt = str(data["challenge"]), str(data["salt"])
        number, signature = data["number"], str(data["signature"])
    except (ValueError, KeyError, TypeError, binascii.Error):
        return False
    if data.get("algorithm") != "SHA-256":
        return False
    if type(number) is not int or not 0 <= number <= settings.altcha_max_number:
        return False
    match = _SALT.fullmatch(salt)
    if match is None or _HEX64.fullmatch(challenge) is None:
        return False
    if not hmac.compare_digest(_sign(settings, challenge, salt), signature):
        return False
    now = int(time.time())
    expires = int(match.group(1))
    # Never trust an expiry beyond what this server hands out.
    if expires < now or expires > now + CHALLENGE_TTL + 60:
        return False
    if hashlib.sha256(f"{salt}{number}".encode()).hexdigest() != challenge:
        return False
    # Each solved challenge works once: the marker outlives the challenge itself.
    ttl = expires - now + 60
    return bool(await redis.set(f"altcha_used:{challenge}", "1", nx=True, ex=ttl))


def _expected_hostname(settings: Settings) -> str | None:
    return urlsplit(settings.public_url).hostname


async def _verify_remote(
    settings: Settings,
    token: str,
    ip: str | None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    assert settings.captcha_secret_key is not None
    form = {"secret": settings.captcha_secret_key.get_secret_value(), "response": token}
    if ip:
        form["remoteip"] = ip
    if settings.captcha_provider == "hcaptcha":
        form["sitekey"] = settings.captcha_site_key
    try:
        async with httpx.AsyncClient(timeout=10, transport=transport) as client:
            res = await client.post(VERIFY_URLS[settings.captcha_provider], data=form)
        body = res.json()
    except (httpx.HTTPError, ValueError):
        log.warning("CAPTCHA verification request failed")
        return False
    if not isinstance(body, dict) or body.get("success") is not True:
        return False
    # A token solved on another site that uses the same site key doesn't count.
    hostname = str(body.get("hostname") or "").lower()
    if hostname != (_expected_hostname(settings) or "").lower():
        log.warning("CAPTCHA token was solved on another host")
        return False
    # Tokens solved for another action (another widget with the same key) don't count.
    action = body.get("action")
    return not action or action == WIDGET_ACTION


async def verify(redis: Redis, settings: Settings, token: str | None, ip: str | None) -> bool:
    if not token or len(token) > 4096:
        return False
    if settings.captcha_provider == "altcha":
        return await _verify_altcha(redis, settings, token)
    if settings.captcha_provider in VERIFY_URLS:
        return await _verify_remote(settings, token, ip)
    return True
