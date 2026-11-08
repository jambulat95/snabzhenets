"""Шлюз моделей внутри шага агента (docs/AGENTS.md, разделы 3–5).

Шаг агента синхронный: runner вызывает run(ctx) в потоке воркера. Шлюз асинхронный, поэтому
весь конвейер шага идёт одним asyncio.run — внутри него вызовы могут идти параллельно
(3 слота Qwen).
Шлюз и httpx-клиенты создаются на шаг: клиент нельзя переносить между циклами событий.

Каждая попытка вызова пишется в журнал ядра через ctx.record_model_call. Вызовы укладываются в срок
задачи минус запас базовому агенту и в бюджет токенов. Не справились — AgentNotSure: шаг падает,
runner пишет agent_step_failed и отдаёт задачу базовому агенту.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from .gateway import CallRecord, Gateway, Provider, make_provider, providers_from_env, switch
from .gateway.config import public_model, queue_wait_from_env

# Сколько секунд срока оставить базовому агенту, если шаг с моделью не справится.
BASELINE_RESERVE_S = 15.0

# Провайдер, который не ответил, пропускается и в следующих шагах: воркер — один процесс.
_COOLDOWN: dict[str, float] = {}


class StepContext(Protocol):
    """То, что шлюзу нужно от AgentContext ядра."""

    def time_left(self) -> float: ...

    def tokens_left(self) -> int: ...

    def record_model_call(
        self,
        *,
        provider: str,
        model: str,
        prompt_version: str,
        tokens_in: int,
        tokens_out: int,
        cost_rub: float,
        ms: int | None = None,
        input_text: str | None = None,
        ok: bool = True,
        error: str | None = None,
    ) -> None: ...


class CtxSink:
    """Каждая попытка — запись model_call в журнале ядра; ядро же считает стоимость КП и бюджет."""

    def __init__(self, ctx: StepContext) -> None:
        self.ctx = ctx

    def write(self, record: CallRecord) -> None:
        self.ctx.record_model_call(
            provider=record.provider,
            model=public_model(record.model),
            prompt_version=f"{record.task}.v{record.prompt_version}",
            tokens_in=record.prompt_tokens,
            tokens_out=record.completion_tokens,
            cost_rub=record.cost_rub,
            ms=record.latency_ms,
            # Ядро хеширует то, что передали. Текст контрагента в ядро не отдаём — только наш хеш.
            input_text=record.input_hash,
            ok=record.success,
            error=None if record.success else f"{record.outcome}: {record.error}",
        )


def run_step[T](
    ctx: StepContext,
    pipeline: Callable[[Gateway], Awaitable[T]],
    *,
    providers: list[Provider] | None = None,
    cooldown: dict[str, float] | None = None,
    limit_s: float | None = None,
) -> T:
    """Выполнить асинхронный конвейер ML в синхронном шаге. providers — для тестов;
    limit_s — потолок времени конвейера внутри срока задачи."""

    async def main() -> T:
        own = providers is None
        provs = (
            providers if providers is not None else [make_provider(c) for c in providers_from_env()]
        )
        cool = _COOLDOWN if cooldown is None else cooldown
        budget = ctx.time_left() - BASELINE_RESERVE_S
        if limit_s is not None:
            budget = min(budget, limit_s)
        gw = Gateway(provs, cooldown=cool, queue_wait_s=queue_wait_from_env()).bind(
            CtxSink(ctx),
            deadline=time.monotonic() + budget,
            tokens_left=ctx.tokens_left,
        )
        # US-23: кнопка оператора в API — флаг в Redis, читаем на каждый шаг
        for name in switch.disabled(getattr(getattr(ctx, "task", None), "sandbox_id", None)):
            gw.set_disabled(name)
        try:
            return await pipeline(gw)
        finally:
            if own:
                for p in provs:
                    await p.aclose()

    return asyncio.run(main())
