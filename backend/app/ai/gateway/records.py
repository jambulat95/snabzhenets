"""Учёт вызовов моделей (сущность «Вызов модели», раздел 7 ТЗ)."""

import json
from collections.abc import Awaitable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

# ok — ответ прошёл схему; invalid — ответ пришёл, но не прошёл схему;
# unavailable — провайдер не ответил (сеть, таймаут, HTTP-ошибка).
Outcome = Literal["ok", "invalid", "unavailable"]


@dataclass(frozen=True)
class CallRecord:
    task: str
    prompt_version: int
    provider: str
    model: str
    attempt: int
    success: bool
    outcome: Outcome
    error: str | None
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    cost_rub: float
    # Хеш входа, а не сам текст: в логе не должно быть данных контрагента.
    input_hash: str
    tokens_per_s: float | None = None
    deal_id: int | str | None = None
    # Сколько ПДн заменено метками до вызова (телефоны, почта, ФИО, реквизиты)
    pii_masked: int = 0
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class CallSink(Protocol):
    def write(self, record: CallRecord) -> Awaitable[None] | None: ...


class MemorySink:
    def __init__(self) -> None:
        self.records: list[CallRecord] = []

    def write(self, record: CallRecord) -> None:
        self.records.append(record)


class JsonlSink:
    """Локальный файл для eval-прогонов. В задачах агентов вызовы пишет ядро: runtime.CtxSink."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def write(self, record: CallRecord) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
