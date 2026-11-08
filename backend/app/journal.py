"""Журнал с цепочкой хешей. Пишется в той же транзакции, что и само действие.

Перенесено из A2A Маркет (backend/app/journal/service.py) и адаптировано: цепочка — на организацию,
вместо песочницы/сделки/мандата — заявка; в хеш входит sha256 доказательства. См. NOTICE.md.
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import JournalEntry

GENESIS = "0" * 64
LOCK_BASE = 7_000_000  # ключ advisory-блокировки: одна цепочка на организацию


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


def _cost(value: Decimal | None) -> str | None:
    # Одинаковый вид до и после сохранения в базу (Numeric(12, 4))
    return None if value is None else str(Decimal(value).quantize(Decimal("0.0001")))


def payload(e: JournalEntry) -> dict[str, Any]:
    """Всё, что защищено хешем."""
    return {
        "org_id": e.org_id, "seq": e.seq, "created_at": _iso(e.created_at),
        "procurement_id": e.procurement_id, "actor_kind": e.actor_kind, "actor_user_id": e.actor_user_id,
        "action": e.action, "input_ref": e.input_ref, "decision": e.decision, "rule_code": e.rule_code,
        "model": e.model, "prompt_version": e.prompt_version, "tokens": e.tokens, "cost_rub": _cost(e.cost_rub),
        "evidence_sha256": e.evidence_sha256, "details": e.details or {}, "prev_hash": e.prev_hash,
    }


def compute_hash(e: JournalEntry) -> str:
    data = json.dumps(payload(e), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def record(
    db: Session,
    *,
    org_id: int,
    action: str,
    actor_kind: str,
    procurement_id: int | None = None,
    actor_user_id: int | None = None,
    input_ref: str | None = None,
    decision: str | None = None,
    rule_code: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    tokens: int | None = None,
    cost_rub: Decimal | None = None,
    evidence_sha256: str | None = None,
    details: dict[str, Any] | None = None,
) -> JournalEntry:
    """Добавляет запись. Коммит делает вызывающий код вместе с самим действием."""
    # Блокировка до конца транзакции: две записи не получат один номер
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_BASE + org_id})
    last = db.execute(
        select(JournalEntry.seq, JournalEntry.hash)
        .where(JournalEntry.org_id == org_id)
        .order_by(JournalEntry.seq.desc())
        .limit(1)
    ).first()
    entry = JournalEntry(
        org_id=org_id, seq=last.seq + 1 if last else 1, created_at=datetime.now(UTC),
        procurement_id=procurement_id, actor_kind=actor_kind, actor_user_id=actor_user_id, action=action,
        input_ref=input_ref, decision=decision, rule_code=rule_code, model=model, prompt_version=prompt_version,
        tokens=tokens, cost_rub=cost_rub, evidence_sha256=evidence_sha256,
        details=json.loads(json.dumps(details or {}, ensure_ascii=False, default=str)),
        prev_hash=last.hash if last else GENESIS,
    )
    entry.hash = compute_hash(entry)
    db.add(entry)
    db.flush()
    return entry


@dataclass
class VerifyResult:
    ok: bool
    checked: int
    broken_seq: int | None = None
    reason: str | None = None


def verify_chain(db: Session, org_id: int) -> VerifyResult:
    rows = db.scalars(select(JournalEntry).where(JournalEntry.org_id == org_id).order_by(JournalEntry.seq))
    return verify_entries(rows)


def verify_entries(rows: Iterable[JournalEntry]) -> VerifyResult:
    """Проверка цепочки по записям, упорядоченным по seq. Без базы — можно проверять в тестах."""
    prev, expected, checked = GENESIS, 1, 0
    for e in rows:
        checked += 1
        if e.seq != expected:
            return VerifyResult(False, checked, e.seq, "Пропущена запись перед этой")
        if e.prev_hash != prev:
            return VerifyResult(False, checked, e.seq, "Ссылка на предыдущую запись не совпадает")
        if compute_hash(e) != e.hash:
            return VerifyResult(False, checked, e.seq, "Содержимое записи изменено")
        prev, expected = e.hash, expected + 1
    return VerifyResult(True, checked)
