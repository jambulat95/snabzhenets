"""Сумма прописью: 353780.67 → «Триста пятьдесят три тысячи семьсот восемьдесят рублей 67 копеек»."""

from decimal import ROUND_HALF_UP, Decimal

_ONES_M = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_ONES_F = ["", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_TEENS = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать",
          "семнадцать", "восемнадцать", "девятнадцать"]
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят",
         "девяносто"]
_HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот",
             "девятьсот"]
# (формы: 1, 2–4, 5+), род
_SCALES = [(("", "", ""), "m"), (("тысяча", "тысячи", "тысяч"), "f"), (("миллион", "миллиона", "миллионов"), "m"),
           (("миллиард", "миллиарда", "миллиардов"), "m")]


def plural(n: int, forms: tuple[str, str, str]) -> str:
    n = abs(n) % 100
    if 10 < n < 20:
        return forms[2]
    n %= 10
    return forms[0] if n == 1 else forms[1] if 2 <= n <= 4 else forms[2]


def _triad(n: int, gender: str) -> list[str]:
    out = [_HUNDREDS[n // 100]]
    rest = n % 100
    if 10 <= rest < 20:
        out.append(_TEENS[rest - 10])
    else:
        out.append(_TENS[rest // 10])
        out.append((_ONES_F if gender == "f" else _ONES_M)[rest % 10])
    return [w for w in out if w]


def number_words(n: int) -> str:
    if n == 0:
        return "ноль"
    parts: list[str] = []
    for i, (forms, gender) in enumerate(_SCALES):
        chunk = (n // 1000 ** i) % 1000
        if chunk == 0:
            continue
        words = _triad(chunk, gender)
        if i > 0:
            words.append(plural(chunk, forms))
        parts = words + parts
    return " ".join(parts)


def rubles(amount: Decimal) -> str:
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rub = int(amount)
    kop = int((amount - rub) * 100)
    rub_word = plural(rub, ("рубль", "рубля", "рублей"))
    kop_word = plural(kop, ("копейка", "копейки", "копеек"))
    text = f"{number_words(rub)} {rub_word} {kop:02d} {kop_word}"
    return text[0].upper() + text[1:]
