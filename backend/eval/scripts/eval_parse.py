"""Прогон eval-набора разбора на живой модели: python scripts/eval_parse.py [--limit N]

Отчёт: eval/reports/parse-<время>.json и .md.
"""

import argparse
import asyncio
import json
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from app.ai.contract import TOKEN_BUDGET, Kind
from app.ai.gateway import AgentNotSure, build_gateway_from_env, load_env
from app.ai.parse import parse_request
from app.ai.parse.parser import split_lines
from ml_eval import CaseResult, score_case, summarize

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "data/parse/cases.jsonl"
REPORTS = ROOT / "reports"
THRESHOLD = 0.90


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    load_env(ROOT.parent.parent / ".env")
    gw = build_gateway_from_env()
    cases = [json.loads(x) for x in CASES.read_text(encoding="utf-8").splitlines() if x]
    cases = cases[: args.limit] if args.limit else cases

    results: list[CaseResult] = []
    timings = []
    usage: list[tuple[str, int, int]] = []  # кейс, строк, токенов
    records = gw.sink.records  # type: ignore[attr-defined]
    for i, case in enumerate(cases, start=1):
        started = time.monotonic()
        before = len(records)
        try:
            pred, error = await parse_request(gw, case["text"]), None
        except AgentNotSure as e:
            pred, error = None, str(e)
        timings.append(round(time.monotonic() - started, 1))
        spent = sum(r.prompt_tokens + r.completion_tokens for r in records[before:])
        usage.append((case["id"], len(split_lines(case["text"])), spent))
        res = score_case(case, pred, error)
        results.append(res)
        ok = sum(r.ok for r in res.rows)
        print(
            f"[{i}/{len(cases)}] {case['id']}: {ok}/{len(res.rows)}, {timings[-1]} с, {spent} ток."
        )

    summary = summarize(results)
    holdout_ids = {c["id"] for c in cases if c.get("holdout")}
    summary["holdout_row_accuracy"] = summarize([r for r in results if r.case_id in holdout_ids])[
        "row_accuracy"
    ]
    summary["median_seconds"] = sorted(timings)[len(timings) // 2]
    summary["max_seconds"] = max(timings)
    tokens = sorted(t for _, _, t in usage)
    budget = TOKEN_BUDGET[Kind.PARSE_REQUEST]
    summary["median_tokens"] = tokens[len(tokens) // 2]
    summary["max_tokens"] = tokens[-1]
    summary["token_budget"] = budget
    summary["cost_rub"] = round(sum(r.cost_rub for r in records), 2)
    summary["provider"] = ", ".join(sorted({r.provider for r in records if r.success}))
    summary["over_budget"] = [f"{c} ({n} стр., {t} ток.)" for c, n, t in usage if t > budget]
    summary["biggest"] = [
        f"{c}: {n} стр., {t} ток." for c, n, t in sorted(usage, key=lambda u: -u[2])[:5]
    ]
    summary["threshold"] = THRESHOLD
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    REPORTS.mkdir(parents=True, exist_ok=True)
    data = {"summary": summary, "cases": [asdict(r) for r in results]}
    (REPORTS / f"parse-{stamp}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (REPORTS / f"parse-{stamp}.md").write_text(render_md(summary, results), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"отчёт → {REPORTS / f'parse-{stamp}.md'}")


def render_md(summary: dict[str, object], results: list[CaseResult]) -> str:
    lines = ["# Eval разбора запросов", "", "| Метрика | Значение |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in summary.items() if k != "by_category"]
    lines += ["", "## По категориям", ""]
    by_cat = summary["by_category"]
    assert isinstance(by_cat, dict)
    lines += [f"- {k}: {v:.0%}" for k, v in by_cat.items()]
    lines += ["", "## Ошибки", ""]
    for c in results:
        if c.error:
            lines.append(f"- **{c.case_id}**: {c.error}")
        for r in c.rows:
            if r.ok:
                continue
            what = [
                n
                for n, f in (
                    ("не найдена", not r.found),
                    ("имя", not r.name_ok),
                    ("кол-во", not r.qty_ok),
                    ("ед.", not r.unit_ok),
                )
                if f
            ]
            exp = r.expected
            got = r.got or {}
            lines.append(
                f"- **{c.case_id}** стр. {r.line} [{', '.join(what)}]: ждали "
                f"{exp['name_keys']} {exp['quantity']} {exp['unit']} — получили "
                f"«{got.get('name')}» {got.get('quantity')} {got.get('unit')} "
                f"(как в тексте: {got.get('unit_raw')}) {got.get('problems') or ''}"
            )  # fmt: skip
        for e in c.extras:
            lines.append(f"- **{c.case_id}** лишняя позиция стр. {e['line']}: «{e['name']}»")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    asyncio.run(main())
