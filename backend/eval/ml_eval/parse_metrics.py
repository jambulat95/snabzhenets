"""Метрики разбора запроса (раздел 13 ТЗ).

Главная метрика — доля строк, где верны наименование, количество и единица
(порог предложен ТЗ: не ниже 90%). Позиция эталона сопоставляется с ответом
по номеру строки; в одной строке может быть несколько позиций.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.ai.parse import ParsedRequest, Position
from app.ai.parse.text import contains


@dataclass
class RowResult:
    case_id: str
    line: int
    category: str
    found: bool
    name_ok: bool
    qty_ok: bool
    unit_ok: bool
    expected: dict[str, Any]
    got: dict[str, Any] | None

    @property
    def ok(self) -> bool:
        return self.found and self.name_ok and self.qty_ok and self.unit_ok


@dataclass
class CaseResult:
    case_id: str
    source: str
    kind_ok: bool
    rows: list[RowResult]
    extras: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


# Номер пункта списка в названии — ошибка разбора, хотя все ключи на месте: «1. Подшипник…».
_LIST_NO_RE = re.compile(r"^\s*\d{1,3}[.)]\s")


def _name_ok(p: Position, keys: list[str]) -> bool:
    return all(contains(p.name, k) for k in keys) and not _LIST_NO_RE.match(p.name)


def _brief(p: Position) -> dict[str, Any]:
    return {"line": p.line, "name": p.name,
            "quantity": str(p.quantity) if p.quantity is not None else None,
            "unit": p.unit, "unit_raw": p.unit_raw, "status": p.status,
            "problems": p.problems}  # fmt: skip


def score_case(case: dict[str, Any], pred: ParsedRequest | None, error: str | None = None
               ) -> CaseResult:  # fmt: skip
    gold = case["gold"]
    unused = list(pred.positions) if pred else []
    rows = []
    for g in gold["positions"]:
        same_line = [p for p in unused if p.line == g["line"]]
        best = next((p for p in same_line if _name_ok(p, g["name_keys"])), None)
        best = best or (same_line[0] if same_line else None)
        if best is None:
            rows.append(RowResult(case["id"], g["line"], g["category"], False, False, False,
                                  False, g, None))  # fmt: skip
            continue
        unused.remove(best)
        want_qty = Decimal(g["quantity"]) if g["quantity"] is not None else None
        rows.append(RowResult(
            case["id"], g["line"], g["category"], True, _name_ok(best, g["name_keys"]),
            best.quantity == want_qty, best.unit == g["unit"], g, _brief(best),
        ))  # fmt: skip
    return CaseResult(
        case_id=case["id"],
        source=case["source"],
        kind_ok=pred is not None and pred.kind == gold["kind"],
        rows=rows,
        extras=[_brief(p) for p in unused],
        error=error,
    )


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    rows = [r for c in results for r in c.rows]
    n = len(rows) or 1

    def share(pred: Any) -> float:
        return round(sum(1 for r in rows if pred(r)) / n, 4)

    by_cat: dict[str, Counter[str]] = {}
    for r in rows:
        c = by_cat.setdefault(r.category, Counter())
        c["rows"] += 1
        c["ok"] += r.ok
    return {
        "cases": len(results),
        "rows": len(rows),
        "row_accuracy": share(lambda r: r.ok),
        "found": share(lambda r: r.found),
        "name_ok": share(lambda r: r.name_ok),
        "quantity_ok": share(lambda r: r.qty_ok),
        "unit_ok": share(lambda r: r.unit_ok),
        "extra_positions": sum(len(c.extras) for c in results),
        "kind_accuracy": round(sum(c.kind_ok for c in results) / (len(results) or 1), 4),
        "errors": sum(1 for c in results if c.error),
        "by_category": {k: round(v["ok"] / v["rows"], 4) for k, v in sorted(by_cat.items())},
    }
