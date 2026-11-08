"""Подбор кода КТРУ: кандидаты — поиском по подмножеству справочника (код), выбор — моделью со схемой,
утверждение — человеком. Код, которого нет среди кандидатов, отбрасывается (CLAUDE.md, 2.8)."""

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..ai.contract import TOKEN_BUDGET, Kind
from ..ai.gateway import Gateway, load_prompt

SUBSET = Path(__file__).with_name("ktru_subset.json")
PROMPT = ("pick_ktru", 1)
_WORD = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)


class KtruPick(BaseModel):
    code: str | None
    question: str | None
    reason: str


@cache
def catalog() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = json.loads(SUBSET.read_text("utf-8"))["items"]
    return items


def candidates(text: str, limit: int = 3) -> list[dict[str, Any]]:
    """Кандидаты по совпадению ключевых слов с началом слов позиции; балл — доля совпавших ключей."""
    words = [w.casefold() for w in _WORD.findall(text)]
    scored = []
    for entry in catalog():
        hits = [k for k in entry["keywords"] if any(w.startswith(k) or k in w for w in words)]
        if hits:
            scored.append({"code": entry["code"], "okpd2": entry["okpd2"], "name": entry["name"],
                           "score": round(len(hits) / len(entry["keywords"]), 3), "hits": hits})
    scored.sort(key=lambda c: (-len(c["hits"]), -c["score"], c["code"]))
    best = len(scored[0]["hits"]) if scored else 0
    # Оставляем только кандидатов с тем же главным словом: «бумага» не кандидат для проектора
    return [c for c in scored if len(c["hits"]) >= max(1, best - 2)][:limit]


async def pick(gw: Gateway, item_text: str, cands: list[dict[str, Any]]) -> KtruPick:
    """Выбор модели среди кандидатов. Один кандидат — без модели."""
    if not cands:
        return KtruPick(code=None, question=None, reason="В справочнике демо нет подходящего кода")
    if len(cands) == 1:
        return KtruPick(code=cands[0]["code"], question=None, reason="Единственный подходящий код в справочнике")
    data = item_text + "\n\nКандидаты:\n" + "\n".join(f"- {c['code']}: {c['name']}" for c in cands)
    res = await gw.call(
        prompt=load_prompt(*PROMPT), data=data, schema=KtruPick,
        max_tokens=min(512, TOKEN_BUDGET[Kind.PICK_KTRU]), temperature=0, seed=0,
    )
    out = res.value
    if out.code is not None and out.code not in {c["code"] for c in cands}:
        return KtruPick(code=None, question=out.question, reason="Модель назвала код не из списка — выберите вручную")
    return out
