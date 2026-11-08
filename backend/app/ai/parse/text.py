"""Сравнение фрагментов с исходным текстом и разбор количеств кодом."""

import re
from decimal import Decimal, InvalidOperation

# Кириллица, похожая на латиницу, и привычная транслитерация обозначений:
# «6204-2РС» и «6204-2RS» должны совпасть. Ключ только для сравнения,
# поэтому r/p и s/c намеренно склеиваются.
_HOMOGLYPHS = str.maketrans("авесмнкорстухrs", "abecmhkopctyxpc")
_DASHES = str.maketrans({c: "-" for c in "‐‑‒–—―−"})
_QUOTES = str.maketrans({c: '"' for c in "«»„“”"})
_TIMES = str.maketrans({"×": "x", "*": "x"})

# Разряды через пробел («1 000») — только если первая группа 1–3 цифры:
# «6204 100» — это обозначение и количество, а не 6 204 100.
_NUM = r"(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,]\d+)?"
_NUMBER_RE = re.compile(_NUM)
# Отдельно стоящее число: не часть артикула «6204-2RS» и не размер «40x60x10».
_STANDALONE_RE = re.compile(r"(?<![\w\-./×*])" + _NUM + r"(?!\d|[\-./,x×*]\d)")

_NUMBER_WORDS = {
    "один": 1, "одна": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
    "одиннадцать": 11, "двенадцать": 12, "пятнадцать": 15, "двадцать": 20,
    "тридцать": 30, "сорок": 40, "пятьдесят": 50, "сто": 100,
}  # fmt: skip


def match_key(text: str) -> str:
    """Ключ для сравнения: регистр, ё, тире, кавычки, «×», похожие буквы, пробелы."""
    t = text.casefold().replace("ё", "е")
    t = t.translate(_DASHES).translate(_QUOTES).translate(_TIMES).translate(_HOMOGLYPHS)
    return " ".join(t.split())


def contains(haystack: str, needle: str) -> bool:
    return bool(needle.strip()) and match_key(needle) in match_key(haystack)


_THOUSANDS_RE = re.compile(r"^\s*(?:тыс\.?|тысяч\w*)\s*", re.IGNORECASE)


def strip_thousands(raw: str | None) -> tuple[str | None, bool]:
    """«тыс. шт» → («шт», True): тысячи, которые модель отнесла к единице."""
    if raw is None or not (m := _THOUSANDS_RE.match(raw)):
        return raw, False
    return raw[m.end() :] or None, True


def in_thousands(source: str, quantity_raw: str) -> bool:
    """«2 тыс. шт»: «тыс.» в самом количестве или сразу после него в строке."""
    if re.search(r"тыс\.?|тысяч", quantity_raw, re.IGNORECASE):
        return True
    m = re.search(re.escape(quantity_raw.strip()) + r"(?!\d)", source)
    return m is not None and bool(_THOUSANDS_RE.match(source[m.end() :]))


def standalone_numbers(text: str) -> list[Decimal]:
    return [_to_decimal(m.group()) for m in _STANDALONE_RE.finditer(text.translate(_TIMES))]


def _to_decimal(digits: str) -> Decimal:
    return Decimal(digits.replace(" ", "").replace("\u00a0", "").replace(",", "."))


def parse_quantity(raw: str) -> Decimal | None:
    """Число из фрагмента вида «10», «2,5», «1 000», «десять». Иначе None."""
    m = _NUMBER_RE.search(raw)
    if m:
        try:
            return _to_decimal(m.group())
        except InvalidOperation:
            return None
    words = raw.casefold().replace("ё", "е").split()
    value = _NUMBER_WORDS.get(words[0].strip(" .,")) if words else None
    return Decimal(value) if value is not None else None
