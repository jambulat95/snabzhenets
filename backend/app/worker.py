"""Фоновый воркер arq: конвейер заявки, таймеры (напоминания, срок сбора), почта, снимки страниц.

    arq app.worker.WorkerSettings

Задачи подключаются по мере готовности модулей (docs/PLAN.md). Пока — только пульс для проверки.
"""

import logging
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from .config import settings

log = logging.getLogger(__name__)


async def heartbeat(ctx: dict[str, Any]) -> None:
    log.info("воркер жив")


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions: list[Any] = []
    cron_jobs = [cron(heartbeat, minute=set(range(0, 60, 5)))]
