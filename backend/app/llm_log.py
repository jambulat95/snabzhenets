"""Вызовы моделей — в журнал: модель, версия промпта, токены, стоимость (CLAUDE.md, 2.6).
Текст входа в журнал не пишется — только его хеш (он уже в CallRecord)."""

from decimal import Decimal

from sqlalchemy.orm import Session

from . import journal
from .ai.gateway import CallRecord


def record_calls(db: Session, *, org_id: int, procurement_id: int | None, records: list[CallRecord]) -> Decimal:
    total = Decimal("0")
    for r in records:
        cost = Decimal(str(r.cost_rub)).quantize(Decimal("0.0001"))
        total += cost
        journal.record(
            db, org_id=org_id, procurement_id=procurement_id, action="model_call", actor_kind="agent",
            decision=r.outcome, model=f"{r.provider}/{r.model}", prompt_version=f"{r.task}.v{r.prompt_version}",
            tokens=r.prompt_tokens + r.completion_tokens, cost_rub=cost,
            details={"latency_ms": r.latency_ms, "attempt": r.attempt, "input_sha256": r.input_hash,
                     "pii_masked": r.pii_masked, **({"error": r.error[:300]} if r.error else {})},
        )
    return total
