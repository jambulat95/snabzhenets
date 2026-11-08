"""Заявка → спецификация: разбор текста (ИИ-слой A2A), пробелы кодом, подбор КТРУ.

Запускается в воркере (задача parse_spec): вызовы модели не идут внутри HTTP-запроса (CLAUDE.md, 3.4).
"""

import logging
from typing import Any

from sqlalchemy import delete

from .. import journal
from ..ai.gateway import AgentNotSure, MemorySink, build_gateway_from_env
from ..ai.parse import ParsedRequest, parse_request
from ..ai.screening import detect_injection
from ..db import SessionLocal
from ..llm_log import record_calls
from ..models import Procurement, SpecItem
from ..pipeline import Status, transition
from . import ktru

log = logging.getLogger(__name__)


def gaps(quantity: Any, unit: str | None, problems: list[str]) -> list[str]:
    """Что спросить у сотрудника. Решает код, а не модель."""
    q = []
    if quantity is None:
        q.append("Сколько нужно?")
    if unit is None:
        q.append("В каких единицах (шт., уп., пачка…)?")
    return q


def build_items(parsed: ParsedRequest) -> list[dict[str, Any]]:
    return [
        {
            "line_no": i, "name": p.name, "characteristics": p.article, "quantity": p.quantity, "unit": p.unit,
            "status": p.status, "problems": list(p.problems), "notes": list(p.notes),
            "questions": gaps(p.quantity, p.unit, list(p.problems)), "source": p.source,
        }
        for i, p in enumerate(parsed.positions, start=1)
    ]


async def run_parse(procurement_id: int) -> None:
    with SessionLocal() as db:
        proc = db.get(Procurement, procurement_id)
        if proc is None or proc.status != Status.DRAFT:
            return
        text, org_id = proc.source_text, proc.org_id

    sink = MemorySink()
    gw = build_gateway_from_env().bind(sink)
    suspicious = detect_injection(text)
    try:
        parsed = await parse_request(gw, text)
        items = build_items(parsed)
        for it in items:
            cands = ktru.candidates(" ".join(filter(None, [it["name"], it["characteristics"], it["source"]])))
            it["ktru_candidates"] = cands
            choice = await ktru.pick(gw, f"Позиция: {it['name']}\nСтрока заявки: {it['source']}", cands)
            it["ktru_suggestion"] = choice.model_dump()
            if choice.code:
                it["ktru_code"] = choice.code
                it["okpd2_code"] = next(c["okpd2"] for c in cands if c["code"] == choice.code)
            if choice.question:
                it["questions"].append(choice.question)
    except AgentNotSure as e:
        with SessionLocal() as db:
            proc = db.get(Procurement, procurement_id)
            assert proc is not None
            record_calls(db, org_id=org_id, procurement_id=proc.id, records=sink.records)
            transition(db, proc, Status.NEEDS_HUMAN, actor_kind="agent",
                       reason="Модель не смогла разобрать заявку — заполните позиции вручную",
                       details={"errors": e.errors[:3]})
            db.commit()
        return

    with SessionLocal() as db:
        proc = db.get(Procurement, procurement_id)
        assert proc is not None
        db.execute(delete(SpecItem).where(SpecItem.procurement_id == proc.id))
        for it in items:
            db.add(SpecItem(procurement_id=proc.id, **it))
        proc.parse_meta = {
            "kind": parsed.kind, "deadline_raw": parsed.deadline_raw,
            "requirements": [r.model_dump() for r in parsed.requirements],
            "possibly_missed": parsed.possibly_missed, "suspicious": suspicious,
        }
        cost = record_calls(db, org_id=org_id, procurement_id=proc.id, records=sink.records)
        journal.record(
            db, org_id=org_id, procurement_id=proc.id, action="spec_parsed", actor_kind="agent",
            decision="suspicious" if suspicious else "ok",
            details={"positions": len(items), "questions": sum(len(i["questions"]) for i in items),
                     "cost_rub": str(cost), **({"injection_rules": suspicious} if suspicious else {})},
        )
        transition(db, proc, Status.SPEC_REVIEW, actor_kind="agent")
        db.commit()
