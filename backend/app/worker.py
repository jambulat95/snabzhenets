"""Фоновый воркер arq: конвейер заявки, таймеры (напоминания, срок сбора), почта, снимки страниц.

    arq app.worker.WorkerSettings

Задачи подключаются по мере готовности модулей (docs/PLAN.md).
"""

import asyncio
import logging
from typing import Any

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select

from .ai.gateway import load_env
from .analysis import collection_complete, run_analysis
from .config import settings
from .db import SessionLocal
from .demo import supplier_sim
from .models import InboundMessage, Procurement
from .outreach import inbox, outbox, reminders
from .pipeline import Status
from .quotes import email_prices
from .quotes.web_prices import collect as collect_site
from .spec.service import run_parse
from .suppliers.service import run_sourcing

log = logging.getLogger(__name__)
# Задачи, которые пишут в базу и ждут модель, идут по одной: иначе одна держит блокировку журнала
# в ожидании модели, а другая ждёт эту блокировку в цикле событий — и встают обе
DB_JOBS = asyncio.Lock()
load_env()  # ключи моделей из .env, если воркер запущен не из compose


async def heartbeat(ctx: dict[str, Any]) -> None:
    log.info("воркер жив")


async def parse_spec(ctx: dict[str, Any], procurement_id: int) -> None:
    """Текст заявки → позиции с КТРУ; затем «Проверка спецификации» (ждёт человека)."""
    async with DB_JOBS:
        await run_parse(procurement_id)


async def collect_site_prices(ctx: dict[str, Any], procurement_id: int) -> None:
    """Цены с сайтов магазинов с доказательствами; идёт параллельно с поиском поставщиков."""
    async with DB_JOBS:
        await collect_site(procurement_id)


async def source_suppliers(ctx: dict[str, Any], procurement_id: int) -> None:
    """Поиск и отбор поставщиков, запросы в outbox, переход к сбору цен."""
    async with DB_JOBS:
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


def _collecting_with_news() -> tuple[list[int], list[int]]:
    """Заявки на сборе: с неразобранными письмами и все (для проверки завершения сбора)."""
    with SessionLocal() as db:
        ids = [p.id for p in db.scalars(select(Procurement).where(Procurement.status == Status.COLLECTING))]
        news = [pid for pid in ids if db.scalar(select(InboundMessage.id).where(
            InboundMessage.procurement_id == pid, InboundMessage.status == "new").limit(1)) is not None]
    return news, ids


def _send_now() -> None:
    with SessionLocal() as db:
        outbox.send_queued(db)


def _maybe_analyse(pid: int) -> None:
    with SessionLocal() as db:
        proc = db.get(Procurement, pid)
        if proc is not None and proc.status == Status.COLLECTING and collection_complete(db, proc):
            run_analysis(db, proc)
            db.commit()


async def mail_tick(ctx: dict[str, Any]) -> None:
    """Почта: outbox, входящие, напоминания, ответы симулятора; разбор писем в цены; конец сбора → анализ."""
    async with DB_JOBS:
        await _mail_tick()


async def _mail_tick() -> None:
    stats = await asyncio.to_thread(_mail_round)
    news, collecting = await asyncio.to_thread(_collecting_with_news)
    for pid in news:
        stats["prices"] = stats.get("prices", 0) + await email_prices.process(pid)
    if news:
        await asyncio.to_thread(_send_now)  # ответы на вопросы поставщиков — сразу, не ждать следующего такта
    for pid in collecting:
        await asyncio.to_thread(_maybe_analyse, pid)
    if any(stats.values()):
        log.info("почта: %s", stats)


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions: list[Any] = [parse_spec, collect_site_prices, source_suppliers, mail_tick]
    cron_jobs = [
        cron(heartbeat, minute=set(range(0, 60, 5))),
        cron(mail_tick, second={0, 15, 30, 45}, unique=True),
    ]
