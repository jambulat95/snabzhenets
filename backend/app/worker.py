"""Фоновый воркер arq: конвейер заявки, таймеры (напоминания, срок сбора), почта, снимки страниц.

    arq app.worker.WorkerSettings

Задачи подключаются по мере готовности модулей (docs/PLAN.md).
"""

import logging
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from .ai.gateway import load_env
from .config import settings
from .spec.service import run_parse

log = logging.getLogger(__name__)
load_env()  # ключи моделей из .env, если воркер запущен не из compose


async def heartbeat(ctx: dict[str, Any]) -> None:
    log.info("воркер жив")


async def parse_spec(ctx: dict[str, Any], procurement_id: int) -> None:
    """Текст заявки → позиции с КТРУ; затем «Проверка спецификации» (ждёт человека)."""
    await run_parse(procurement_id)


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions: list[Any] = [parse_spec]
    cron_jobs = [cron(heartbeat, minute=set(range(0, 60, 5)))]
