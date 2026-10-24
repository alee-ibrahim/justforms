"""FastAPI dependencies for staff authentication and CSRF protection (DESIGN section 14.3)."""

from __future__ import annotations

import hmac
import uuid
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, Session, load_session
from app.config import Settings, get_settings
from app.db import get_session as get_db
from app.models import User
from app.redis import get_redis
from app.storage import Storage, get_storage

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

DbDep = Annotated[AsyncSession, Depends(get_db)]
RedisDep = Annotated[Redis, Depends(get_redis)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def storage_dep() -> Storage:
    """FastAPI dependency for the configured storage backend; tests override it."""
    return get_storage()


StorageDep = Annotated[Storage, Depends(storage_dep)]


def check_origin(request: Request, settings: Settings) -> None:
    """Reject unsafe cross-origin requests. Browsers always send Origin on such requests."""
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    allowed = {settings.public_origin, *(o.rstrip("/") for o in settings.cors_origins)}
    if origin is not None and origin.rstrip("/") not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "origin_not_allowed")


async def origin_guard(request: Request, settings: SettingsDep) -> None:
    check_origin(request, settings)


async def optional_session(
    request: Request,
    redis: RedisDep,
    settings: SettingsDep,
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> Session | None:
    return await load_session(redis, settings, token)


async def require_session(
    request: Request,
    settings: SettingsDep,
    session: Annotated[Session | None, Depends(optional_session)],
) -> Session:
    if session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not_authenticated")
    if request.method not in SAFE_METHODS:
        check_origin(request, settings)
        header = request.headers.get(CSRF_HEADER, "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not (
            header
            and hmac.compare_digest(header, cookie)
            and hmac.compare_digest(header, session.csrf)
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "csrf_failed")
    return session


async def current_user(db: DbDep, session: Annotated[Session, Depends(require_session)]) -> User:
    user = await db.get(User, uuid.UUID(session.user_id))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not_authenticated")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
CurrentSession = Annotated[Session, Depends(require_session)]
