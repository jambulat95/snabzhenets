"""Eval разбора письма поставщика (Ш-6): python scripts/eval_email.py

Письма eval/email/cases.jsonl: строки запроса, текст письма, эталон по строкам (цена без НДС,
наличие, срок, аналог, упаковка) и ожидание, уходит ли КП в таблицу без снабженца
(уверенность ≥ 0,8). Модель — первый провайдер из LLM_PROVIDERS (../.env).
"""

import asyncio
import json
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.agents.contract import EMAIL_CONFIDENCE_MIN
from app.agents.ml.email_offer import read_letter, verify
from app.agents.ml.gateway import AgentNotSure, build_gateway_from_env, load_env

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "eval/email/cases.jsonl"
REPORTS = ROOT / "eval/reports"
FIELDS = ("availability", "delivery_days", "is_analog", "unit", "pack_size")


def same(a: Any, b: Any) -> bool:
    try:
        return abs(Decimal(str(a)) - Decimal(str(b))) < Decimal("0.01")
    except Exception:
        return a == b


def rules_prices(body: str, request: dict[str, Any]) -> dict[int, Decimal] | None:
    """Цены по правилам базового агента, как в шаге. Ядро (SQLAlchemy) есть только в контейнере:
    на хосте сверка с правилами пропускается."""
    try:
        from app.agents.baseline import parse_email_text
    except ImportError:
        return None
    return {ln.request_line_no: ln.price for ln in parse_email_text(body, request).lines}


async def main() -> None:
    load_env(ROOT.parent / ".env")
    gw = build_gateway_from_env()
    records = gw.sink.records  # type: ignore[attr-defined]
    cases = [json.loads(x) for x in CASES.read_text("utf-8").splitlines() if x]
    rows, results = [], []
    for c in cases:
        request = {"items": c["request"]}
        before, t0 = len(records), time.monotonic()
        try:
            raw = await read_letter(gw, c["body"], request)
            out = verify(raw, c["body"], request, rules_prices(c["body"], request))
            error = None
        except AgentNotSure as e:
            out, error = {"lines": [], "confidence": 0.0, "notes": []}, str(e)
        seconds = round(time.monotonic() - t0, 1)
        tokens = sum(r.prompt_tokens + r.completion_tokens for r in records[before:])
        got = {str(ln["request_line_no"]): ln for ln in out["lines"]}
        for no, gold in c["gold"].items():
            ln = got.get(no)
            fields_ok = ln is not None and all(
                same(ln.get(f), gold[f]) for f in FIELDS if f in gold
            )
            rows.append({
                "case": c["id"], "line": no, "found": ln is not None,
                "price_ok": ln is not None and same(ln["price"], gold["price"]),
                "fields_ok": fields_ok, "gold": gold, "got": ln,
            })  # fmt: skip
        extra = [no for no in got if no not in c["gold"]]
        auto = bool(out["lines"]) and out["confidence"] >= EMAIL_CONFIDENCE_MIN
        checks = {
            "valid_days": out.get("valid_days") == c["valid_days"] if "valid_days" in c else None,
            "delivery_price": same(out.get("delivery_price"), c["delivery_price"])
            if "delivery_price" in c else None,
        }  # fmt: skip
        results.append({
            "case": c["id"], "note": c["note"], "confidence": out["confidence"], "auto": auto,
            "auto_ok": auto == c["auto"], "extra_lines": extra, "checks": checks,
            "tokens": tokens, "seconds": seconds, "error": error, "notes": out.get("notes", []),
        })  # fmt: skip
        flag = "ok" if auto == c["auto"] and not extra else "!!"
        print(f"{flag} {c['id']}: уверенность {out['confidence']}, в таблицу={auto}, {seconds} с")

    n = len(rows)
    summary = {
        "letters": len(cases),
        "lines": n,
        "found": round(sum(r["found"] for r in rows) / n, 4),
        "price_ok": round(sum(r["price_ok"] for r in rows) / n, 4),
        "line_ok": round(sum(r["price_ok"] and r["fields_ok"] for r in rows) / n, 4),
        "extra_lines": sum(len(r["extra_lines"]) for r in results),
        "auto_decision_ok": round(sum(r["auto_ok"] for r in results) / len(results), 4),
        "letter_checks_ok": [
            f"{r['case']}.{k}" for r in results for k, v in r["checks"].items() if v is False
        ],
        "median_seconds": sorted(r["seconds"] for r in results)[len(results) // 2],
        "max_tokens": max(r["tokens"] for r in results),
        "cost_rub": round(sum(r.cost_rub for r in records), 2),
        "provider": ", ".join(sorted({r.provider for r in records if r.success})),
        "errors": sum(1 for r in results if r["error"]),
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"email-{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    path.write_text(
        json.dumps({"summary": summary, "letters": results, "lines": rows}, ensure_ascii=False,
                   indent=1), "utf-8",
    )  # fmt: skip
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for r in rows:
        if not (r["price_ok"] and r["fields_ok"]):
            print(f"  {r['case']} стр.{r['line']}: эталон {r['gold']} → {r['got']}")
    print(f"отчёт → {path}")


if __name__ == "__main__":
    asyncio.run(main())
