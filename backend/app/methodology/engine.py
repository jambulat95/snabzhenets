"""Движок методики: проверки М-01…М-09, средняя, коэффициент вариации, НМЦК. Только код и Decimal.

Паттерн вердиктов — из движка правил A2A (allow / warn / human / deny). Параметры — в профиле
(mer567_v1.json), а не в коде (CLAUDE.md, 3.7). Решение человека («исключить», «допустить») имеет
приоритет над автоматикой, кроме deny по давности и доказательству — их человек не отменяет.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from pathlib import Path
from typing import Any

CENT = Decimal("0.01")
RANK = {"allow": 0, "warn": 1, "human": 2, "deny": 3}


@cache
def profile(pid: str = "mer567_v1") -> dict[str, Any]:
    data: dict[str, Any] = json.loads(Path(__file__).with_name(f"{pid}.json").read_text("utf-8"))
    return data


@dataclass
class QuoteIn:
    id: int
    item_id: int
    channel: str
    source: str
    unit_price: Decimal
    vat_mode: str
    captured_at: datetime
    status: str  # ok / review / rejected (сверка товара, разбор письма)
    evidence_ok: bool
    source_verdict: str  # allow / warn / human / deny — проверки поставщика (М-05, М-06)
    source_reason: str | None
    delivery_included: bool
    human_decision: str | None
    human_reason: str | None


@dataclass
class ItemIn:
    id: int
    line_no: int
    name: str
    quantity: Decimal


@dataclass
class Verdict:
    code: str
    verdict: str
    reason: str


@dataclass
class QuoteOut:
    id: int
    admitted: bool
    verdicts: list[Verdict] = field(default_factory=list)


def check_quote(q: QuoteIn, now: datetime, p: dict[str, Any]) -> QuoteOut:
    v: list[Verdict] = []
    age = now - q.captured_at
    if age > timedelta(days=p["max_age_days"]):
        v.append(Verdict("М-03", "deny", f"Цена от {q.captured_at:%d.%m.%Y} — старше {p['max_age_days']} дней"))
    if q.status == "rejected":
        v.append(Verdict("М-04", "deny", "Товар в источнике не соответствует позиции"))
    elif q.status == "review":
        v.append(Verdict("М-04", "human", "Цену или товар нужно подтвердить человеку"))
    if q.source_verdict in ("deny", "human"):
        v.append(Verdict("М-05", q.source_verdict, q.source_reason or "Источник не прошёл проверку"))
    elif q.channel == "site":
        v.append(Verdict("М-05", "warn", "Открытый источник (сайт магазина): реквизиты продавца не проверялись"))
    if q.vat_mode == "unknown":
        v.append(Verdict("М-08", "human", "Не ясно, включён ли НДС — цена несопоставима"))
    if not q.delivery_included:
        v.append(Verdict("М-08", "warn", "Доставка до заказчика в цену не входит"))
    if not q.evidence_ok:
        v.append(Verdict("М-09", "deny", "Нет доказательства или файл изменён после записи"))

    hard = any(x.verdict == "deny" and x.code in ("М-03", "М-09") for x in v)
    if q.human_decision == "exclude":
        v.append(Verdict("ЧЕЛ", "deny", f"Исключено человеком: {q.human_reason or 'без причины'}"))
        return QuoteOut(q.id, False, v)
    if q.human_decision == "include" and not hard:
        v.append(Verdict("ЧЕЛ", "allow", f"Допущено человеком: {q.human_reason or 'без причины'}"))
        return QuoteOut(q.id, True, v)
    admitted = all(x.verdict in ("allow", "warn") for x in v)
    return QuoteOut(q.id, admitted, v)


def money(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def stats(prices: list[Decimal]) -> tuple[Decimal | None, Decimal | None]:
    """Средняя и коэффициент вариации (σ по n−1, как в п. 3.20 рекомендаций)."""
    n = len(prices)
    if n == 0:
        return None, None
    mean = sum(prices, Decimal(0)) / n
    if n < 2:
        return mean, None
    var = sum(((x - mean) ** 2 for x in prices), Decimal(0)) / (n - 1)
    return mean, (var.sqrt() / mean) if mean else None


def evaluate(items: list[ItemIn], quotes: list[QuoteIn], requests_sent: int, now: datetime,
             pid: str = "mer567_v1") -> dict[str, Any]:
    p = profile(pid)
    cv_max = Decimal(p["cv_max"])
    checked = {q.id: check_quote(q, now, p) for q in quotes}
    out_items = []
    total = Decimal(0)
    ready = True
    for it in items:
        mine = [q for q in quotes if q.item_id == it.id]
        admitted = [q for q in mine if checked[q.id].admitted]
        mean, cv = stats([q.unit_price for q in admitted])
        verdicts = []
        if len(admitted) < p["min_prices"]:
            verdicts.append(Verdict("М-02", "human", f"Подходящих цен {len(admitted)} из {p['min_prices']} нужных"))
        if cv is not None and cv > cv_max:
            text = (f"Коэффициент вариации {cv * 100:.1f} % > {cv_max * 100:.0f} %: цены неоднородны — "
                    "добавьте цены или исключите выброс с причиной")
            verdicts.append(Verdict("М-07", "human", text))
        nmck = money(mean * it.quantity) if mean is not None else None
        ok = not verdicts and nmck is not None
        ready &= ok
        total += nmck or 0
        out_items.append({
            "item_id": it.id, "line_no": it.line_no, "name": it.name, "quantity": str(it.quantity),
            "admitted": len(admitted), "quotes": len(mine),
            "mean": str(money(mean)) if mean is not None else None,
            "cv_pct": str((cv * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)) if cv is not None else None,
            "nmck": str(nmck) if nmck is not None else None, "ok": ok,
            "verdicts": [v.__dict__ for v in verdicts],
        })
    general = []
    if requests_sent < p["min_requests"]:
        general.append(Verdict("М-01", "warn", f"Запросов отправлено {requests_sent} — меньше {p['min_requests']}; "
                                               "причина фиксируется в обосновании").__dict__)
    else:
        general.append(Verdict("М-01", "allow", f"Запросов отправлено {requests_sent}").__dict__)
    return {
        "profile": p["id"], "method": p["title"], "source": p["source"], "computed_at": now.isoformat(),
        "ready": ready, "total_nmck": str(money(total)) if ready else None, "items": out_items, "general": general,
        "quotes": {str(qid): {"admitted": r.admitted, "verdicts": [v.__dict__ for v in r.verdicts]}
                   for qid, r in checked.items()},
    }
