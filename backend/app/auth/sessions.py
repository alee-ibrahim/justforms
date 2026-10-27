"""Server-side staff sessions in Redis (DESIGN section 8.1).

The browser holds an opaque random token in the HttpOnly ``justforms_session`` cookie; Redis
stores only its SHA-256, so a Redis dump cannot be replayed as cookies. Sessions expire after
``session_idle_seconds`` without use and ``session_absolute_seconds`` after creation.

CSRF uses the double-submit pattern: a random token is stored in the session and also set as
the readable ``justforms_csrf`` cookie; unsafe requests must echo it in ``X-CSRF-Token``.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass

from fastapi import Response
from redis.asyncio import Redis

from app.config import Settings

SESSION_COOKIE = "justforms_session"
CSRF_COOKIE = "justforms_csrf"
CSRF_HEADER = "X-CSRF-Token"


@dataclass
class Session:
    token_hash: str
    user_id: str
    csrf: str
    created_at: float
    end_session_hint: str | None = None  # id_token for OIDC RP-initiated logout


def _key(token_hash: str) -> str:
    return f"session:{token_hash}"


def _user_key(user_id: str) -> str:
    # The sessions of one person (token hashes), so they can all be ended at once.
    return f"user_sessions:{user_id}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(
    redis: Redis, settings: Settings, user_id: str, *, id_token: str | None = None
) -> tuple[str, Session]:
    token = secrets.token_urlsafe(32)
    session = Session(
        token_hash=hash_token(token),
        user_id=user_id,
        csrf=secrets.token_urlsafe(32),
        created_at=time.time(),
        end_session_hint=id_token,
    )
    payload = {
        "user_id": session.user_id,
        "csrf": session.csrf,
        "created_at": session.created_at,
        "id_token": id_token,
    }
    async with redis.pipeline(transaction=True) as pipe:
        pipe.set(_key(session.token_hash), json.dumps(payload), ex=settings.session_idle_seconds)
        pipe.sadd(_user_key(user_id), session.token_hash)
        pipe.expire(_user_key(user_id), settings.session_absolute_seconds)
        await pipe.execute()
    return token, session


async def load_session(redis: Redis, settings: Settings, token: str | None) -> Session | None:
    if not token:
        return None
    token_hash = hash_token(token)
    raw = await redis.get(_key(token_hash))
    if raw is None:
        return None
    data = json.loads(raw)
    age = time.time() - float(data["created_at"])
    if age > settings.session_absolute_seconds:
        await redis.delete(_key(token_hash))
        return None
    # Sliding idle timeout, capped by the absolute lifetime.
    remaining = int(settings.session_absolute_seconds - age)
    await redis.expire(_key(token_hash), max(1, min(settings.session_idle_seconds, remaining)))
    return Session(
        token_hash=token_hash,
        user_id=data["user_id"],
        csrf=data["csrf"],
        created_at=float(data["created_at"]),
        end_session_hint=data.get("id_token"),
    )


async def delete_session(redis: Redis, session: Session) -> None:
    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(_key(session.token_hash))
        pipe.srem(_user_key(session.user_id), session.token_hash)
        await pipe.execute()


async def revoke_user_sessions(redis: Redis, user_id: object, *, keep: str | None = None) -> int:
    """End every session of ``user_id`` (all but the one with token hash ``keep``): used when
    someone is removed from an organisation, demoted, or loses superadmin. Returns how many."""
    user_key = _user_key(str(user_id))
    members = await redis.smembers(user_key)  # type: ignore[misc]
    hashes = [h.decode() if isinstance(h, bytes) else str(h) for h in members]
    ended = [h for h in hashes if h != keep]
    if not ended:
        return 0
    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(*(_key(h) for h in ended))
        pipe.srem(user_key, *ended)
        results = await pipe.execute()
    return int(results[0] or 0)


def set_session_cookies(
    response: Response, settings: Settings, token: str, session: Session
) -> None:
    common = {
        "path": "/",
        "secure": settings.secure_cookies,
        "samesite": "lax",
        "max_age": settings.session_absolute_seconds,
    }
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)  # type: ignore[arg-type]
    response.set_cookie(CSRF_COOKIE, session.csrf, httponly=False, **common)  # type: ignore[arg-type]


def clear_session_cookies(response: Response, settings: Settings) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=settings.secure_cookies, samesite="lax")


# Sent with a successful sign-in. Clears what a previous app on the same hostname may have left
# in the browser: cached redirects (e.g. "/" pointing at another site) and service workers.
# Not "cookies": the new session cookie is set on the same response. Trade-off: local UI
# preferences in browser storage are dropped and re-read from the account.
CLEAR_SITE_DATA = '"cache", "storage"'


def clear_stale_site_data(response: Response) -> None:
    response.headers["Clear-Site-Data"] = CLEAR_SITE_DATA
