"""Сбор цен → анализ по методике → обоснование (машина состояний: COLLECTING → ANALYSIS → JUSTIFICATION_REVIEW).

Сбор завершается, когда ответили все, кому ушёл запрос (или истёк срок по часам заявки), либо человек
нажал «Завершить сбор». Анализ пересчитывается после каждого решения человека по цене.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import journal
from .clock import now
from .evidence import store
from .methodology.engine import ItemIn, QuoteIn, evaluate
from .models import Candidate, Evidence, InboundMessage, PriceQuote, Procurement, User
from .pipeline import Status, transition

COLLECT_HOURS = 48


def deadline_passed(proc: Procurement) -> bool:
    return now(proc) - proc.created_at > timedelta(hours=COLLECT_HOURS)


def collection_complete(db: Session, proc: Procurement) -> bool:
    """Все, кому ушёл запрос, ответили ценами (вопрос без цен — ещё не ответ), писем в разборе нет.
    Или истёк срок сбора по часам заявки."""
    if deadline_passed(proc):
        return True
    pending = db.scalar(select(InboundMessage.id).where(InboundMessage.procurement_id == proc.id,
                                                        InboundMessage.status == "new").limit(1))
    cands = list(db.scalars(select(Candidate).where(Candidate.procurement_id == proc.id, Candidate.selected)))
    if pending is not None or not cands:
        return False
    for c in cands:
        priced = db.scalar(select(PriceQuote.id).where(PriceQuote.candidate_id == c.id).limit(1)) is not None
        if c.request_status != "replied" or not priced:
            return False
    return True


def _evidence_ok(db: Session, sha: str | None) -> bool:
    if not sha:
        return False
    ev = db.scalar(select(Evidence).where(Evidence.sha256 == sha))
    return ev is not None and store.verify(db, ev).ok


def run_analysis(db: Session, proc: Procurement, actor: User | None = None) -> dict[str, object]:
    """Пересчитать методику; при готовности — к проверке обоснования. Коммит — у вызывающего."""
    if proc.status == Status.COLLECTING:
        transition(db, proc, Status.ANALYSIS, actor_kind="human" if actor else "agent", user=actor,
                   details={"reason": "сбор завершён человеком" if actor else
                            ("истёк срок сбора" if deadline_passed(proc) else "ответили все поставщики")})
    cands = {c.id: c for c in db.scalars(select(Candidate).where(Candidate.procurement_id == proc.id))}
    quotes = []
    for q in db.scalars(select(PriceQuote).where(PriceQuote.procurement_id == proc.id)):
        c = cands.get(q.candidate_id) if q.candidate_id else None
        reason = next((ch["reason"] for ch in (c.checks if c else []) if ch["verdict"] in ("deny", "human")), None)
        quotes.append(QuoteIn(
            id=q.id, item_id=q.spec_item_id, channel=q.channel, source=q.source_name, unit_price=q.unit_price,
            vat_mode=q.vat_mode, captured_at=q.captured_at, status=q.status,
            evidence_ok=_evidence_ok(db, q.screenshot_sha256 or q.source_sha256) and
            (q.html_sha256 is None or _evidence_ok(db, q.html_sha256)),
            source_verdict=c.verdict if c else "allow", source_reason=reason,
            delivery_included=q.channel == "email" and any("Доставка" in n for n in q.notes),
            human_decision=q.human_decision, human_reason=q.human_reason,
        ))
    items = [ItemIn(id=i.id, line_no=i.line_no, name=i.name, quantity=i.quantity or 0) for i in proc.items]
    sent = sum(1 for c in cands.values() if c.selected and c.request_status != "none")
    res = evaluate(items, quotes, sent, now(proc), proc.profile)
    res["computed_at"] = datetime.now(UTC).isoformat()  # реальное время расчёта; давность цен — по часам заявки
    proc.analysis = res
    journal.record(db, org_id=proc.org_id, procurement_id=proc.id, action="analysis_done", actor_kind="agent",
                   decision="ready" if res["ready"] else "needs_human",
                   details={"total_nmck": res["total_nmck"],
                            "items": [{k: i[k] for k in ("line_no", "admitted", "cv_pct", "nmck", "ok")}
                                      for i in res["items"]]})
    if res["ready"] and proc.status == Status.ANALYSIS:
        transition(db, proc, Status.JUSTIFICATION_REVIEW, actor_kind="agent",
                   details={"total_nmck": res["total_nmck"]})
    return res
