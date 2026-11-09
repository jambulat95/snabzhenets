"""Канал «цена с сайта»: найти карточки товара, извлечь цену кодом, сверить товар моделью, сохранить
доказательный пакет (HTML + снимок, sha256 в журнале) и цену по позиции.

Цена с сайта — розничная и включает НДС; она помечается так и не смешивается с КП молча (ARCHITECTURE, 5).
"""

import logging
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import delete

from .. import journal
from ..ai.contract import TOKEN_BUDGET, Kind
from ..ai.gateway import AgentNotSure, Gateway, MemorySink, load_prompt
from ..ai.replay import gateway as llm_gateway
from ..ai.screening import detect_injection
from ..db import SessionLocal
from ..evidence import store
from ..integrations.web.port import Hit, WebPricePort
from ..integrations.web.replay import ReplayWebPrices
from ..llm_log import record_calls
from ..models import PriceQuote, Procurement, SpecItem
from .extract import extract_offer, visible_text

log = logging.getLogger(__name__)
PROMPT = ("match_page", 1)
MAX_PAGES_PER_ITEM = 4


class PageMatch(BaseModel):
    matches: bool
    confidence: Literal["high", "medium", "low"]
    differences: list[str]
    reason: str


def port() -> WebPricePort:
    return ReplayWebPrices()


async def match(gw: Gateway, item: SpecItem, offer_name: str, description: str | None) -> PageMatch:
    data = (
        f"Позиция: {item.name}\nХарактеристики: {item.characteristics or '—'}\nКод КТРУ: {item.ktru_code}\n\n"
        f"Товар магазина: {offer_name}\nОписание: {(description or '—')[:600]}"
    )
    res = await gw.call(prompt=load_prompt(*PROMPT), data=data, schema=PageMatch, temperature=0, seed=0,
                        max_tokens=min(400, TOKEN_BUDGET[Kind.MATCH_PAGE]))
    return res.value


def verdict(m: PageMatch | None, notes: list[str]) -> str:
    if m is None or (m.matches and m.confidence != "high") or notes:
        return "review"  # решает человек
    return "ok" if m.matches else "rejected"


async def collect(procurement_id: int, web: WebPricePort | None = None, gw: Gateway | None = None) -> int:
    """Собрать цены с сайтов по всем позициям. Возвращает число сохранённых цен."""
    web = web or port()
    sink = MemorySink()
    gw = (gw or llm_gateway()).bind(sink)
    with SessionLocal() as db:
        proc = db.get(Procurement, procurement_id)
        if proc is None:
            return 0
        db.execute(delete(PriceQuote).where(PriceQuote.procurement_id == proc.id, PriceQuote.channel == "site"))
        saved = 0
        for item in proc.items:
            hits: list[Hit] = web.search(item.name)[:MAX_PAGES_PER_ITEM]
            for hit in hits:
                page = web.fetch(hit.url)
                text = page.text()
                offer = extract_offer(text)
                if offer is None:
                    journal.record(db, org_id=proc.org_id, procurement_id=proc.id, action="site_no_price",
                                   actor_kind="agent", input_ref=hit.url, details={"shop": page.shop.name})
                    continue
                notes = list(offer.notes)
                if detect_injection(visible_text(text)[:20000]):
                    notes.append("На странице есть текст, похожий на команды агенту")
                try:
                    m: PageMatch | None = await match(gw, item, offer.name or hit.title, offer.description)
                except AgentNotSure:
                    m = None
                    notes.append("Модель не смогла сверить товар — проверьте вручную")
                if m is not None and not m.matches and m.confidence == "high":
                    journal.record(db, org_id=proc.org_id, procurement_id=proc.id, action="site_mismatch",
                                   actor_kind="agent", input_ref=hit.url,
                                   details={"line_no": item.line_no, "offer": offer.name, "reason": m.reason})
                    continue
                meta = {"shop": page.shop.name, "region": page.shop.region, "line_no": item.line_no}
                html_ev = store.save(db, org_id=proc.org_id, procurement_id=proc.id, data=page.html, kind="html",
                                     url=page.url, captured_at=page.fetched_at, meta=meta)
                shot_ev = None
                if page.screenshot is not None and page.screenshot_at is not None:
                    shot_ev = store.save(db, org_id=proc.org_id, procurement_id=proc.id, data=page.screenshot,
                                         kind="screenshot", url=page.url, captured_at=page.screenshot_at, meta=meta)
                q = PriceQuote(
                    procurement_id=proc.id, spec_item_id=item.id, channel="site", source_name=page.shop.name,
                    source_key=page.shop.key, region=page.shop.region, offer_name=offer.name,
                    unit_price=offer.price.quantize(Decimal("0.01")), currency="RUB", vat_mode="with",
                    price_kind=page.shop.price_kind, url=page.url, captured_at=page.fetched_at,
                    extracted_by=offer.how, html_sha256=html_ev.sha256,
                    screenshot_sha256=shot_ev.sha256 if shot_ev else None,
                    match=m.model_dump() if m else {}, status=verdict(m, notes),
                    notes=notes + ["Розничная цена сайта, включает НДС"],
                )
                db.add(q)
                db.flush()
                journal.record(
                    db, org_id=proc.org_id, procurement_id=proc.id, action="price_from_site", actor_kind="agent",
                    decision=q.status, evidence_sha256=html_ev.sha256, input_ref=page.url,
                    details={"line_no": item.line_no, "shop": page.shop.name, "region": page.shop.region,
                             "price": str(q.unit_price), "extracted_by": offer.how,
                             "screenshot_sha256": q.screenshot_sha256},
                )
                saved += 1
        cost = record_calls(db, org_id=proc.org_id, procurement_id=proc.id, records=sink.records)
        journal.record(db, org_id=proc.org_id, procurement_id=proc.id, action="site_prices_done", actor_kind="agent",
                       details={"saved": saved, "cost_rub": str(cost)})
        db.commit()
        return saved
