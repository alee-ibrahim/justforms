"""Shared async Redis client (sessions, one-time codes, OIDC state)."""

from functools import lru_cache

from redis.asyncio import Redis

from app.config import get_settings


@lru_cache
def _client() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


async def get_redis() -> Redis:
    """FastAPI dependency; tests override it with fakeredis."""
    return _client()
