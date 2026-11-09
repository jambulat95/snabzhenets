"""Ответы поставщиков → цены по позициям (канал «письмо»).

Модель только находит в письме, к какой строке запроса относится цена (A2A read_letter), код сверяет
каждое число с текстом письма (A2A verify). Вложение Excel превращается в текст таблицы и проходит тот же
путь. Цены приводятся к «с НДС» — как цены сайтов, чтобы их можно было сравнивать (М-08).
На вопрос поставщика агент отвечает только из полей спецификации; остальное — человеку.
"""

import io
import logging
import re
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from openpyxl import load_workbook
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import journal
from ..ai.contract import TOKEN_BUDGET, Kind
from ..ai.email_offer import VAT, letter_numbers, read_letter, vat_mode, verify
from ..ai.gateway import AgentNotSure, Gateway, MemorySink, build_gateway_from_env, load_prompt
from ..db import SessionLocal
from ..evidence import store
from ..llm_log import record_calls
from ..models import Candidate, InboundMessage, PriceQuote, Procurement, SpecItem
from ..outreach.outbox import queue_answer

log = logging.getLogger(__name__)
QUESTION_PROMPT = ("supplier_question", 1)
PRICE_LIST_DATE = re.compile(r"прайс[-\s]?лист\w*\s+от\s+(\d{2})\.(\d{2})\.(\d{4})", re.IGNORECASE)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class SupplierQuestion(BaseModel):
    is_question: bool
    item_line: int | None
    topic: Literal["original_or_compatible", "quantity", "delivery", "other"]
    summary: str


def xlsx_text(data: bytes) -> str:
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    rows = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).replace(".0", "") if isinstance(c, float) and c.is_integer() else str(c)
                     for c in row if c is not None]
            if cells:
                rows.append(" | ".join(cells))
    return "\n".join(rows)


def letter_with_attachments(m: InboundMessage) -> tuple[str, str]:
    """Текст письма плюс таблицы из Excel-вложений; второе значение — способ (letter / excel)."""
    parts, how = [m.body_text], "letter"
    for a in m.attachments:
        if a["content_type"] == XLSX or (a.get("filename") or "").lower().endswith(".xlsx"):
            ev_path = store.path_for(a["sha256"], "attachment")
            parts.append(f"\nВложение {a.get('filename')}:\n" + xlsx_text(ev_path.read_bytes()))
            how = "excel"
    return "\n".join(parts), how


def request_of(items: list[SpecItem]) -> dict[str, Any]:
    """Строки запроса — в том порядке, в каком они были в письме поставщику."""
    return {"items": [{"line_no": n, "name": i.name, "quantity": str(i.quantity), "unit": i.unit}
                      for n, i in enumerate(items, start=1)]}


def price_date(text: str, received: datetime) -> tuple[datetime, str | None]:
    m = PRICE_LIST_DATE.search(text)
    if not m:
        return received, None
    d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), tzinfo=UTC)
    return d, f"Цена по прайс-листу от {d:%d.%m.%Y} — дата цены взята из письма"


def answer_text(q: SupplierQuestion, items: list[SpecItem], city: str, deadline: str | None) -> str | None:
    """Ответ только из полей спецификации. None — ответить нечем, решает человек."""
    item = items[q.item_line - 1] if q.item_line and 0 < q.item_line <= len(items) else None
    if q.topic == "original_or_compatible":
        pool = [item] if item else items
        for it in pool:
            text = f"{it.name} {it.characteristics or ''}".lower()
            if "оригинал" in text:
                return (f"Добрый день! По позиции «{it.name}»: нужны оригинальные товары — так указано в запросе. "
                        "Совместимые аналоги не рассматриваются.")
            if "совместим" in text or "аналог" in text:
                return f"Добрый день! По позиции «{it.name}»: совместимые товары допускаются, укажите это в ответе."
        return None
    if q.topic == "quantity" and item is not None and item.quantity:
        return f"Добрый день! По позиции «{item.name}»: нужно {item.quantity.normalize():f} {item.unit}."
    if q.topic == "delivery":
        when = f" Срок: {deadline}." if deadline else ""
        return (f"Добрый день! Доставка до г. {city}, укажите, пожалуйста, её стоимость отдельно или включите "
                f"в цену.{when}")
    return None


async def classify(gw: Gateway, body: str, items: list[SpecItem]) -> SupplierQuestion:
    data = body[:4000] + "\n\nПозиции запроса:\n" + "\n".join(f"{n}. {i.name}" for n, i in enumerate(items, 1))
    res = await gw.call(prompt=load_prompt(*QUESTION_PROMPT), data=data, schema=SupplierQuestion, temperature=0,
                        seed=0, max_tokens=min(300, TOKEN_BUDGET[Kind.SUPPLIER_QUESTION]))
    return res.value


def save_quotes(db: Session, proc: Procurement, cand: Candidate, m: InboundMessage, items: list[SpecItem],
                out: dict[str, Any], text: str, how: str, when: datetime, date_note: str | None,
                review: bool) -> int:
    n = 0
    sup = cand.supplier
    vat = vat_mode(text)
    numbers = letter_numbers(text)
    for ln in out["lines"]:
        item = items[ln["request_line_no"] - 1]
        net = Decimal(ln["price"])  # verify отдаёт цену без НДС, если в письме прямо «с НДС»
        problems = [x for x in out["notes"] if x.startswith(f"Строка {ln['request_line_no']}:")]
        notes = list(problems)
        if vat == "with":
            # verify делит цену «с НДС» на 1,22; берём исходное число из письма, а не обратный пересчёт
            back = (net * VAT).quantize(Decimal("0.01"), ROUND_HALF_UP)
            exact = [n for n in numbers if abs(n - back) <= Decimal("0.05")]
            gross, vat_label = (exact[0] if exact else back), "with"
        elif vat == "without":
            gross, vat_label = (net * VAT).quantize(Decimal("0.01"), ROUND_HALF_UP), "without"
            notes.append("Цена в письме без НДС — приведена к цене с НДС 22 % для сравнения")
        else:
            gross, vat_label = net, "unknown"
            notes.append("НДС в письме не указан однозначно — проверьте")
        if date_note:
            notes.append(date_note)
        if ln.get("is_analog"):
            notes.append("Поставщик предлагает аналог")
        status = "review" if (review or problems or ln.get("is_analog") or vat_label == "unknown") else "ok"
        q = PriceQuote(
            procurement_id=proc.id, spec_item_id=item.id, channel="email", source_name=sup.name, source_key=sup.key,
            region=sup.region, offer_name=ln["name"], unit_price=gross, currency="RUB",
            vat_mode=vat_label, price_kind="КП поставщика", url=None, captured_at=when,
            extracted_by=how, html_sha256=None, screenshot_sha256=None, source_sha256=m.evidence_sha256,
            candidate_id=cand.id, match={}, status=status,
            notes=notes + (["Доставка до заказчика включена в предложение"] if "Доставка" in m.body_text else []),
        )
        db.add(q)
        db.flush()
        journal.record(db, org_id=proc.org_id, procurement_id=proc.id, action="price_from_letter", actor_kind="agent",
                       decision=status, evidence_sha256=m.evidence_sha256,
                       details={"line_no": item.line_no, "supplier": sup.name, "price": str(gross), "how": how,
                                "confidence": out["confidence"]})
        n += 1
    return n


def peers(db: Session, proc: Procurement, items: list[SpecItem]) -> dict[int, list[Decimal]]:
    """Цены других источников по строкам запроса (без НДС, за единицу): по ним verify проверяет,
    что число — цена за единицу, а не сумма или цена за упаковку другого размера."""
    out: dict[int, list[Decimal]] = {}
    for n, it in enumerate(items, start=1):
        rows = db.scalars(select(PriceQuote).where(PriceQuote.spec_item_id == it.id, PriceQuote.status == "ok",
                                                   PriceQuote.vat_mode == "with"))
        out[n] = [(q.unit_price / VAT).quantize(Decimal("0.01"), ROUND_HALF_UP) for q in rows]
    return out


async def process(procurement_id: int, gw: Gateway | None = None) -> int:
    """Разобрать новые ответы поставщиков заявки. Возвращает число новых цен."""
    sink = MemorySink()
    gw = (gw or build_gateway_from_env()).bind(sink)
    total = 0
    with SessionLocal() as db:
        proc = db.get(Procurement, procurement_id)
        if proc is None:
            return 0
        msgs = db.scalars(select(InboundMessage).where(InboundMessage.procurement_id == proc.id,
                                                       InboundMessage.status == "new",
                                                       InboundMessage.candidate_id.is_not(None)))
        for m in list(msgs):
            # Каждое письмо — своя транзакция: блокировка журнала не держится, пока ждём модель по следующему
            db.commit()
            cand = db.get(Candidate, m.candidate_id)
            assert cand is not None
            items = [i for i in proc.items if i.id in cand.item_ids]
            text, how = letter_with_attachments(m)
            request = request_of(items)
            try:
                raw = await read_letter(gw, text, request)
            except AgentNotSure:
                m.kind, m.status = "other", "needs_human"
                continue
            out = verify(raw, text, request, peer_prices=peers(db, proc, items))
            if out["lines"]:
                when, note = price_date(text, m.received_at)
                review = bool(m.suspicious) or raw.addressed_to_agent
                total += save_quotes(db, proc, cand, m, items, out, text, how, when, note, review)
                m.kind, m.status = "offer", "parsed"
                continue
            try:
                q = await classify(gw, m.body_text, items)
            except AgentNotSure:
                m.kind, m.status = "other", "needs_human"
                continue
            if not q.is_question:
                m.kind, m.status = "other", "needs_human"
                continue
            m.kind = "question"
            reply = answer_text(q, items, "Грозный", (proc.parse_meta or {}).get("deadline_raw"))
            if reply is None:
                m.status = "needs_human"
                journal.record(db, org_id=proc.org_id, procurement_id=proc.id, action="question_to_human",
                               actor_kind="agent", details={"supplier": cand.supplier.name, "question": q.summary})
                continue
            queue_answer(db, proc, cand, m.from_email, m.message_id, m.subject, reply + "\n\nС уважением,\n"
                         "контрактная служба (ответ подготовлен агентом по данным спецификации)")
            m.status = "parsed"
            journal.record(db, org_id=proc.org_id, procurement_id=proc.id, action="question_answered",
                           actor_kind="agent", details={"supplier": cand.supplier.name, "topic": q.topic,
                                                        "question": q.summary})
        record_calls(db, org_id=proc.org_id, procurement_id=proc.id, records=sink.records)
        db.commit()
    return total
