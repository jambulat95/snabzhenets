"""Один товар двумя строками запроса: «6205 2RS» и «6205-2RS», «A-1250» латиницей и кириллицей.

Иначе поставщик считает их разными позициями, а в счёте и УПД товар идёт дважды. Строки сливаются,
количество складывается, снабженец видит заметку и подтверждает черновик сам. Сомнение — не сливаем:
бренд, исполнение, требования или числа в названии разошлись — это разные товары.
"""

import re
from decimal import Decimal
from typing import Any

from ..search.designations import designation_keys, materials
from ..search.normalize import compact, digit_tokens
from .rfq import brands_in

# Что может отличаться у одного товара: остальное (единица, требования, аналоги) должно совпасть
_OWN_FIELDS = {"line_no", "source_text", "name", "quantity", "recognized"}
_LINE_NOTE_RE = re.compile(r"^Строка (\d+)")
MAX_SOURCE = 4000


def _digits(name: str) -> str:
    return compact("".join(digit_tokens(name)))


def same_item(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if {k: v for k, v in a.items() if k not in _OWN_FIELDS} != {
        k: v for k, v in b.items() if k not in _OWN_FIELDS
    }:
        return False
    first, second = str(a["name"]), str(b["name"])
    if compact(first) == compact(second):
        return True
    keys = designation_keys(first)
    return (
        bool(keys)
        and keys == designation_keys(second)
        and _digits(first) == _digits(second)
        and brands_in(first) == brands_in(second)
        and materials(first) == materials(second)
    )


def merge_duplicates(
    items: list[dict[str, Any]], notes: list[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Позиции без дублей и заметки с новыми номерами строк. Непонятые строки не сливаем."""
    kept: list[dict[str, Any]] = []
    numbers: dict[int, int] = {}
    merged: list[str] = []
    for item in items:
        twin = None
        if item.get("recognized", True):
            twin = next((k for k in kept if k.get("recognized", True) and same_item(k, item)), None)
        if twin is None:
            numbers[item["line_no"]] = len(kept) + 1
            kept.append({**item, "line_no": len(kept) + 1})
            continue
        numbers[item["line_no"]] = twin["line_no"]
        before, added = Decimal(str(twin["quantity"])), Decimal(str(item["quantity"]))
        twin["quantity"] = str(before + added)
        source = f"{twin.get('source_text') or ''}; {item.get('source_text') or ''}"
        twin["source_text"] = source[:MAX_SOURCE]
        merged.append(
            f"«{twin['name']}» указан несколько раз, строки объединены: "
            f"{before} + {added} = {before + added} {twin['unit']}."
        )
    if not merged:
        return items, notes
    renumbered = [
        _LINE_NOTE_RE.sub(lambda m: f"Строка {numbers.get(int(m[1]), m[1])}", note)
        for note in notes
    ]
    return kept, renumbered + merged
