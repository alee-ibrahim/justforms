"""Enqueueing background jobs on the arq worker. The API never sends email inline."""

from __future__ import annotations

from typing import Annotated, Any, Protocol

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings
from fastapi import Depends

from app.config import get_settings


class JobQueue(Protocol):
    async def enqueue(self, function: str, **kwargs: Any) -> None: ...


class ArqQueue:
    def __init__(self) -> None:
        self._pool: ArqRedis | None = None

    async def enqueue(self, function: str, **kwargs: Any) -> None:
        if self._pool is None:
            self._pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
        await self._pool.enqueue_job(function, **kwargs)


_queue = ArqQueue()


async def get_queue() -> JobQueue:
    """FastAPI dependency; tests override it with an in-memory recorder."""
    return _queue


QueueDep = Annotated[JobQueue, Depends(get_queue)]
