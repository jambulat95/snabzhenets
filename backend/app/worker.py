"""Фоновый воркер arq: конвейер заявки, таймеры (напоминания, срок сбора), почта, снимки страниц.

    arq app.worker.WorkerSettings

Задачи подключаются по мере готовности модулей (docs/PLAN.md).
"""

import asyncio
import logging
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from .ai.gateway import load_env
from .config import settings
from .db import SessionLocal
from .demo import supplier_sim
from .outreach import inbox, outbox, reminders
from .quotes.web_prices import collect as collect_site
from .spec.service import run_parse
from .suppliers.service import run_sourcing

log = logging.getLogger(__name__)
load_env()  # ключи моделей из .env, если воркер запущен не из compose


async def heartbeat(ctx: dict[str, Any]) -> None:
    log.info("воркер жив")


async def parse_spec(ctx: dict[str, Any], procurement_id: int) -> None:
    """Текст заявки → позиции с КТРУ; затем «Проверка спецификации» (ждёт человека)."""
    await run_parse(procurement_id)


async def collect_site_prices(ctx: dict[str, Any], procurement_id: int) -> None:
    """Цены с сайтов магазинов с доказательствами; идёт параллельно с поиском поставщиков."""
    await collect_site(procurement_id)


async def source_suppliers(ctx: dict[str, Any], procurement_id: int) -> None:
    """Поиск и отбор поставщиков, запросы в outbox, переход к сбору цен."""
    await asyncio.to_thread(run_sourcing, procurement_id)
    await mail_tick(ctx)


def _mail_round() -> dict[str, int]:
    with SessionLocal() as db:
        sent = outbox.send_queued(db)
        got = inbox.poll(db)
        due = reminders.tick(db)
        sent += outbox.send_queued(db) if due else 0
    answered = supplier_sim.tick()  # демо: «люди по ту сторону почты»
    return {"sent": sent, "received": got, "reminders": due, "sim_replies": answered}


async def mail_tick(ctx: dict[str, Any]) -> None:
    """Почта: отправить outbox, забрать входящие, напоминания, ответы симулятора (демо)."""
    stats = await asyncio.to_thread(_mail_round)
    if any(stats.values()):
        log.info("почта: %s", stats)


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions: list[Any] = [parse_spec, collect_site_prices, source_suppliers, mail_tick]
    cron_jobs = [
        cron(heartbeat, minute=set(range(0, 60, 5))),
        cron(mail_tick, second={0, 15, 30, 45}, run_at_startup=True, unique=True),
    ]
