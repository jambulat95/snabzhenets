"""Очередь к провайдеру с ограниченным числом одновременных запросов (Ш-15).

У Qwen на ПК три слота llama.cpp, а воркер ядра выполняет до AGENT_THREADS задач сразу, и разбор
запроса шлёт части текста параллельно. Лишние запросы ждут здесь, а не в очереди llama.cpp: там
их время шло бы в таймаут вызова, и задачи падали бы на базового агента. Очередь общая для
процесса (у каждого потока воркера свой цикл asyncio, поэтому замок из threading) и идёт по
порядку прихода: части одной задачи встают в очередь вместе, и задачи заканчиваются по очереди,
а не все разом под конец срока. Ждём опросом, а не в отдельном потоке: отменённая задача
не унесёт с собой занятый слот.
"""

import asyncio
import threading
import time
from collections import deque
from collections.abc import Callable

POLL_S = 0.05


class ProviderBusy(Exception):
    """Слот не освободился за отведённое время: провайдер занят, а не упал."""


class _Queue:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.busy = 0
        self.waiting: deque[object] = deque()
        self.lock = threading.Lock()

    def take(self, ticket: object) -> bool:
        with self.lock:
            if self.busy < self.limit and self.waiting[0] is ticket:
                self.waiting.popleft()
                self.busy += 1
                return True
            return False

    def leave(self, ticket: object) -> None:
        with self.lock:
            if ticket in self.waiting:
                self.waiting.remove(ticket)

    def release(self) -> None:
        with self.lock:
            self.busy -= 1


_QUEUES: dict[str, _Queue] = {}
_LOCK = threading.Lock()


def _queue(name: str, limit: int) -> _Queue:
    with _LOCK:
        q = _QUEUES.get(name)
        if q is None or q.limit != limit:
            q = _QUEUES[name] = _Queue(limit)
        return q


async def acquire(name: str, limit: int | None, wait_s: float) -> Callable[[], None]:
    """Занимает слот провайдера по очереди и возвращает «освободить». Без лимита — сразу."""
    if not limit:
        return lambda: None
    q = _queue(name, limit)
    ticket = object()
    with q.lock:
        q.waiting.append(ticket)
    until = time.monotonic() + max(wait_s, 0.0)
    try:
        while not q.take(ticket):
            if time.monotonic() >= until:
                raise ProviderBusy(f"все {limit} слота заняты {wait_s:.0f} с")
            await asyncio.sleep(POLL_S)
    except BaseException:
        q.leave(ticket)  # не дождался или задачу отменили — место в очереди освобождаем
        raise
    return q.release
