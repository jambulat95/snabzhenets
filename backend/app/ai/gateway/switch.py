"""Переключатель оператора «основной провайдер недоступен» (US-23, кабинет оператора Э12).

Кнопка — в API (процесс uvicorn), а шлюз живёт в воркере: Gateway.set_disabled одного процесса
другому не виден. Поэтому флаг общий — множество выключенных провайдеров песочницы в Redis.
Шаг агента читает его перед созданием шлюза (runtime.run_step): следующая задача после нажатия
идёт к резерву, а в журнале у вызова модели — резервная модель.

Redis не ответил — переключатель не действует, шаг работает как обычно: отказ кнопки демо
не должен останавливать агентов. Выключены все провайдеры — шаг падает (AgentNotSure), задачу
делает базовый агент.
"""

import logging
from typing import Any

KEY = "ml:providers_off:{sandbox_id}"

log = logging.getLogger(__name__)


def _redis() -> Any:
    from ...redis_client import redis_client  # настройки ядра — только когда переключатель нужен

    return redis_client


def disabled(sandbox_id: int | None, client: Any = None) -> set[str]:
    """Провайдеры, выключенные оператором в песочнице. Без песочницы (eval, скрипты) — пусто."""
    if sandbox_id is None:
        return set()
    try:
        return set((client or _redis()).smembers(KEY.format(sandbox_id=sandbox_id)))
    except Exception:
        log.warning("Переключатель провайдера (Redis) не ответил — работают все провайдеры")
        return set()


def set_disabled(sandbox_id: int, provider: str, off: bool, client: Any = None) -> set[str]:
    """Выключить или включить провайдер в песочнице; ответ — выключенные после изменения."""
    r = client or _redis()
    key = KEY.format(sandbox_id=sandbox_id)
    if off:
        r.sadd(key, provider)
    else:
        r.srem(key, provider)
    return set(r.smembers(key))


def clear(sandbox_id: int, client: Any = None) -> None:
    """Сброс демо (US-22): все провайдеры снова включены. Redis не ответил — сброс идёт дальше."""
    try:
        (client or _redis()).delete(KEY.format(sandbox_id=sandbox_id))
    except Exception:
        log.warning("Переключатель провайдера (Redis) не ответил при сбросе песочницы")
