"""Остаток и кратность из текста прайса: «>100», «под заказ», «100 шт/уп».

Перенесено из A2A Маркет (backend/app/catalog/router.py: _dec, _stock, _pack), см. NOTICE.md.
Нужно price_columns.fits: колонку «остаток» узнаём и по текстовым значениям.
"""

import re
from decimal import Decimal, InvalidOperation

_NO_STOCK = {"нет", "нет в наличии", "под заказ", "отсутствует", "ожидается", "-", "—"}
_PLENTY = {"много", "есть", "в наличии", "достаточно"}
STOCK_PLENTY = Decimal("100")  # «много» — без числа; берём столько и пишем об этом в отчёте
_LEADING_NUM_RE = re.compile(r"^(?:[><≥≤]|более|больше|свыше|от|менее|меньше|до)?\s*(\d+(?:[.,]\d+)?)")
_TITLES = {"stock": "Остаток", "pack_qty": "Кратность"}


def _dec(v: object, field: str, *, positive: bool = False) -> Decimal | None:
    if v is None or str(v).strip() == "":
        return None
    s = str(v).replace(" ", "").replace(" ", "").replace(",", ".").replace("₽", "").replace("руб", "")
    try:
        d = Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"«{_TITLES[field]}»: не число ({v})") from e
    if d < 0 or (positive and d == 0):
        raise ValueError(f"«{_TITLES[field]}»: должно быть больше нуля")
    return d


def parse_stock(v: object) -> tuple[Decimal, str | None]:
    """Остаток числом и вид текста: «>100» — число (text); «под заказ», «нет» — 0 (none);
    «много» — STOCK_PLENTY (plenty). Иначе — ValueError."""
    s = str(v).strip().lower() if v is not None else ""
    if not s:
        return Decimal("0"), None
    if s in _NO_STOCK:
        return Decimal("0"), "none"
    if s in _PLENTY:
        return STOCK_PLENTY, "plenty"
    try:
        return _dec(v, "stock") or Decimal("0"), None
    except ValueError:
        m = _LEADING_NUM_RE.match(s)
        if m is None:
            raise
        return Decimal(m.group(1).replace(",", ".")), "text"


def parse_pack(v: object) -> Decimal | None:
    """Кратность: число или число в начале («100 м», «10 шт/уп»)."""
    try:
        return _dec(v, "pack_qty", positive=True)
    except ValueError:
        m = re.match(r"^\s*(\d+(?:[.,]\d+)?)", str(v))
        if m is None or Decimal(m.group(1).replace(",", ".")) <= 0:
            raise
        return Decimal(m.group(1).replace(",", "."))
