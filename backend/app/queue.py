"""Постановка задач воркеру из API (arq)."""

from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from .config import settings

_pool: ArqRedis | None = None


async def enqueue(function: str, *args: Any) -> None:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    await _pool.enqueue_job(function, *args)
