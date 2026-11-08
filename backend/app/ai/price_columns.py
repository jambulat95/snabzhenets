"""Сопоставление колонок прайса для шага import_price (US-02): поле каталога → колонка файла.

Правила базового агента ищут слова в заголовке и ошибаются на непривычных названиях: «РРЦ»,
«Вход», «Опт от 10 шт», «Код 1С». Модель видит заголовки и описание каждой колонки, которое
собирает код: текст или числа, целые или дробные, порядок величины, до трёх примеров текста.
Значений цен модель не видит (ТЗ: закупочные цены модели не передаём): у числовых колонок —
только тип и порядок.

Ответ модели код сверяет со значениями так же, как их потом разберёт импорт (catalog/router.py):
в ценах и сроке — числа (цену «с НДС» импорт пересчитает без НДС), в остатке — то, что понимает
_stock («28», «>100», «под заказ», «много»), в кратности — то, что понимает _pack («100 шт»,
«10 шт/уп»); в названии — текст, единицы узнаются, артикулы не повторяются, закупка не дороже
цены продажи. Не прошло — поле берут правила, если их колонка подходит. Сопоставление в любом
случае подтверждает человек; уверенность — доля обязательных полей импорта (артикул, название,
цена клиенту), которые нашлись и прошли сверку.
"""

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel

from .gateway import Gateway, load_prompt
from .parse.units import normalize_unit

PROMPT = ("map_columns", 1)
Field = Literal[
    "sku", "name", "brand", "unit", "pack_qty", "group", "purchase_price", "price_end_client",
    "price_distributor", "stock", "safety_stock", "lead_days",
]  # fmt: skip
# Порядок разбора правил базового агента: узкие поля раньше
FIELDS: tuple[str, ...] = (
    "purchase_price", "price_distributor", "safety_stock", "lead_days", "pack_qty", "sku", "brand",
    "group", "unit", "price_end_client", "stock", "name",
)  # fmt: skip
# Как у импорта (catalog/router.REQUIRED): закупки в прайсе для клиентов обычно нет — её считает
# импорт от цены клиенту по наценке группы
REQUIRED = ("sku", "name", "price_end_client")
NUMERIC = {
    "pack_qty", "purchase_price", "price_end_client", "price_distributor", "stock", "safety_stock",
    "lead_days",
}  # fmt: skip
TEXT = {"name", "brand", "group"}
PROFILE_ROWS = 200
EXAMPLES = 3
EXAMPLE_CHARS = 40
# Сверка: доля строк, на которых значение подходит полю
FIT = 0.8
UNIT_FIT = 0.6
UNIQUE_SKU = 0.9
# Ни закупка ≤ цены, ни наоборот на большинстве строк — порядок цен неясен
UNSURE_CONFIDENCE = 0.5

_NUM_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")
_CURRENCY_RE = re.compile(r"(?:₽|руб\.?|р\.?)(?:/[а-яa-z]+\.?)?$", re.IGNORECASE)  # «руб./шт»
_ORDERS = ((10, "единицы"), (100, "десятки"), (1000, "сотни"), (10000, "тысячи"))


class FieldColumn(BaseModel):
    field: Field
    column: int | None


class ColumnMap(BaseModel):
    columns: list[FieldColumn]


def number(raw: Any) -> Decimal | None:
    """Число ячейки: «1 250,50», «980 руб», «12%» — нет (не число поля каталога)."""
    s = str(raw if raw is not None else "").replace(" ", "").replace(" ", "").replace(" ", "")
    s = _CURRENCY_RE.sub("", s)
    if not _NUM_RE.match(s):
        return None
    try:
        return Decimal(s.replace(",", "."))
    except InvalidOperation:
        return None


@dataclass
class Column:
    index: int
    header: str
    values: list[str]  # непустые, первые PROFILE_ROWS строк
    numbers: list[Decimal | None]

    @property
    def numeric_share(self) -> float:
        return sum(n is not None for n in self.numbers) / len(self.values) if self.values else 0.0

    @property
    def row_numbers(self) -> bool:
        """Колонка «№ п/п»: 1, 2, 3… подряд — не остаток, не срок и не кратность."""
        nums = [n for n in self.numbers if n is not None]
        return (
            len(nums) == len(self.numbers) >= 3
            and all(n == n.to_integral_value() for n in nums)
            and all(b - a == 1 for a, b in zip(nums, nums[1:], strict=False))
        )

    def describe(self) -> dict[str, Any]:
        """То, что видит модель: заголовок, тип, порядок величины, примеры текста. Без чисел."""
        out: dict[str, Any] = {"column": self.index, "header": self.header}
        if not self.values:
            out["kind"] = "пусто"
            return out
        nums = [n for n in self.numbers if n is not None]
        if self.numeric_share >= FIT:
            out["kind"] = "числа"
            out["integers"] = all(n == n.to_integral_value() for n in nums)
            mid = median(abs(n) for n in nums)
            out["order"] = next(
                (name for limit, name in _ORDERS if mid < limit), "десятки тысяч и больше"
            )
            return out
        out["kind"] = "текст" if not nums else "текст и числа"
        texts = [v for v, n in zip(self.values, self.numbers, strict=True) if n is None]
        out["examples"] = list(dict.fromkeys(v[:EXAMPLE_CHARS] for v in texts))[:EXAMPLES]
        return out


def columns(headers: list[Any], rows: list[list[Any]]) -> list[Column]:
    out = []
    for i, h in enumerate(headers):
        values = [
            str(r[i]).strip()
            for r in rows[:PROFILE_ROWS]
            if i < len(r) and r[i] is not None and str(r[i]).strip()
        ]
        out.append(Column(i, str(h or "").strip(), values, [number(v) for v in values]))
    return out


def model_input(cols: list[Column]) -> str:
    return json.dumps([c.describe() for c in cols], ensure_ascii=False)


async def ask(gw: Gateway, cols: list[Column]) -> dict[str, int | None]:
    res = await gw.call(
        prompt=load_prompt(*PROMPT),
        data=model_input(cols),
        schema=ColumnMap,
        max_tokens=400,
        seed=0,
    )
    return {fc.field: fc.column for fc in res.value.columns}


def _share(values: list[str], parse: Any) -> float:
    """Доля значений, которые разбор импорта принимает без ошибки строки."""
    ok = 0
    for v in values:
        try:
            parse(v)
        except ValueError:
            continue
        ok += 1
    return ok / len(values)


_NEGATIVE_RE = re.compile(r"^\s*[-−–]\s*\d")


def negative(col: Column) -> bool:
    """Есть отрицательное значение: числом или текстом с минусом любого вида («−5», «- 2»)."""
    return any(n is not None and n < 0 for n in col.numbers) or any(
        _NEGATIVE_RE.match(v) for v in col.values
    )


def fits(field: str, col: Column) -> bool:
    """Значения колонки подходят полю. Пустая колонка не подходит ни одному полю."""
    if not col.values:
        return False
    if field in ("stock", "pack_qty"):
        # Остаток и кратность импорт разбирает и из текста: «>100», «под заказ», «100 шт»
        from .stock_text import parse_pack as _pack
        from .stock_text import parse_stock as _stock

        parse = _stock if field == "stock" else _pack
        # Доля «разбирается» не пропустит колонку, где из десяти остатков один отрицательный:
        # отрицательного остатка и кратности не бывает, такая колонка — не это поле
        return _share(col.values, parse) >= FIT and not col.row_numbers and not negative(col)
    if field in NUMERIC:
        return (
            col.numeric_share >= FIT
            and all(n is None or n >= 0 for n in col.numbers)
            and not col.row_numbers
        )
    if field in TEXT:
        return col.numeric_share < 1 - FIT
    if field == "unit":
        return sum(normalize_unit(v) is not None for v in col.values) / len(col.values) >= UNIT_FIT
    if field == "sku":
        return len(set(col.values)) / len(col.values) >= UNIQUE_SKU
    return True


def price_order(cols: list[Column], mapping: dict[str, int]) -> str:
    """Закупка и цена продажи по строкам: ok — закупка не дороже, swapped — наоборот, unclear."""
    if "purchase_price" not in mapping or "price_end_client" not in mapping:
        return "ok"
    buy, sell = cols[mapping["purchase_price"]], cols[mapping["price_end_client"]]
    pairs = [(b, s) for b, s in zip(buy.numbers, sell.numbers, strict=False) if b and s]
    if not pairs:
        return "unclear"
    cheaper = sum(b <= s for b, s in pairs) / len(pairs)
    if cheaper >= FIT:
        return "ok"
    return "swapped" if cheaper <= 1 - FIT else "unclear"


def merge(
    headers: list[Any],
    rows: list[list[Any]],
    by_model: dict[str, int | None] | None,
    by_rules: dict[str, int],
) -> tuple[dict[str, int], float]:
    """Сопоставление модели, сверенное со значениями, плюс поля правил, которых модель не дала.
    by_model None — модели не было (подозрительный файл): только правила, с той же сверкой."""
    cols = columns(headers, rows)
    has_rows = any(c.values for c in cols)

    def ok(field: str, i: int | None, used: set[int]) -> bool:
        return (
            i is not None
            and 0 <= i < len(cols)
            and i not in used
            and (fits(field, cols[i]) or not has_rows)
        )

    mapping: dict[str, int] = {}
    used: set[int] = set()
    for source in (by_model or {}, by_rules):
        for field in FIELDS:
            i = source.get(field)
            if field not in mapping and ok(field, i, used):
                mapping[field] = i  # type: ignore[assignment]
                used.add(i)  # type: ignore[arg-type]
    # Цену клиенту кто-то предлагал, но её колонка не прошла сверку (текст вместо цен): опт на её
    # место не ставим — агент продавал бы клиентам по оптовой цене. Цену выберет человек. Если же
    # предложенную колонку заняла цена дистрибьютору, это одна и та же цена — её и переносим
    end_rejected = "price_end_client" not in mapping and any(
        (i := source.get("price_end_client")) is not None and i not in used
        for source in (by_model or {}, by_rules)
    )
    if "price_end_client" not in mapping and "price_distributor" in mapping and not end_rejected:
        # Единственная цена продажи — цена клиенту: без неё импорт не загрузит ни одной строки
        mapping["price_end_client"] = mapping.pop("price_distributor")
    confidence = sum(f in mapping for f in REQUIRED) / len(REQUIRED)
    if end_rejected:
        confidence = min(confidence, UNSURE_CONFIDENCE)
    order = price_order(cols, mapping)
    if order == "swapped":
        mapping["purchase_price"], mapping["price_end_client"] = (
            mapping["price_end_client"],
            mapping["purchase_price"],
        )
    elif order == "unclear" or not has_rows:
        confidence = min(confidence, UNSURE_CONFIDENCE)
    return mapping, round(confidence, 2)
