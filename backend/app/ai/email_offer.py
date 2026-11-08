"""Ответ поставщика письмом → строки КП (Ш-6, US-15).

Модель только находит в тексте письма, что к какой строке запроса относится, и копирует числа
дословно. Код сверяет каждое число с текстом письма, пересчитывает цену без НДС (только если «с НДС»
прямо написано в письме), берёт количество и единицу из запроса, если поставщик их не указал,
и считает уверенность — долю строк, которые подтвердились. Не подтвердилась строка — её нет
в КП, а уверенность ниже: такое письмо ядро отдаст снабженцу. Само в таблицу письмо идёт, только
если у каждой цены есть доказательство, что она за единицу (unit_price_marked), а налоги — только
«без НДС» (белый список). Модель заодно отмечает обращения к ИИ в письме (второй слой фильтра
инъекций): такое письмо тоже идёт снабженцу.
"""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, Field

from .gateway import Gateway, load_prompt
from .parse.text import contains, standalone_numbers
from .parse.units import normalize_unit

PROMPT = ("parse_email_offer", 2)
SUSPICIOUS_CAP = 0.5  # ниже порога 0,8: КП из такого письма проверит снабженец
VAT = Decimal("1.22")  # НДС 22 % (с 2026 года); как vat_pct цен в ядре
# НДС решают только однозначные формы. Каждое упоминание «НДС» в письме относим к «без» или «с»
# по шаблону, который его покрывает; не покрыл ни один («цены не включают НДС», «НДС входит
# в стоимость», «НДС: включён», просто «НДС 22%») — неясно: цены не пересчитываем, решает снабженец.
# Шаблон на каждую формулировку не дописываем — ошибка в пересчёте НДС стоит 18–22 % цены
_VAT_WORD_RE = re.compile(r"(?<!\w)ндс(?!\w)", re.IGNORECASE)
# То же без границ слова и с точками: «НДС20%», «сНДС», «Н.Д.С.», «V.A.T.» — такое упоминание
# шаблоны выше не разберут, значит, неясно
_VAT_LOOSE_RE = re.compile(
    r"(?<![а-яё])(?:с)?н\.?\s?д\.?\s?с\.?(?![а-яё])|(?<![a-z])v\.?\s?a\.?\s?t\.?(?![a-z])",
    re.IGNORECASE,
)
WITHOUT_VAT_RE = re.compile(
    r"(?<!\w)(?:без|плюс|не\s+включая)\s+(?:уч[её]та\s+)?ндс(?!\w)|\+\s*ндс(?!\w)"
    r"|(?<!\w)ндс(?:\s*\d{1,2}\s*%)?\s+(?:не\s+облага\w*|сверху)|не\s+облага\w*\s+ндс",
    re.IGNORECASE,
)
WITH_VAT_RE = re.compile(
    r"(?<![\w-])(?:с|с\s+уч[её]том|в\s+т\.?\s*ч\.?|в\s+том\s+числе|включая)\s+ндс(?!\w)",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(r"(?<!\w)не(?!\w)", re.IGNORECASE)
# Налог названо не словом «НДС»: «Prices include VAT», «цены брутто», «с учётом всех налогов» —
# так же неясно, к каким ценам относится
_TAX_HINT_RE = re.compile(
    r"(?<!\w)(?:vat|tax(?:es)?|налог\w*)(?!\w)|цен\w*\s+брутто|брутто[-\s]+цен|gross\s+price",
    re.IGNORECASE,
)
DAYS_RE = re.compile(
    r"(\d+)\s*(?:-|–|до)?\s*(\d+)?\s*(раб\w*\s+)?(дн|день|дня|недел|нед|мес)", re.IGNORECASE
)
VALID_RE = re.compile(
    r"(?:действительн\w*|срок\s+действия)[^.\n\d]{0,25}"
    r"(\d+\s*(?:раб\w*\s+)?(?:дн\w*|день|недел\w*|мес\w*))",
    re.IGNORECASE,
)


class LLMEmailLine(BaseModel):
    request_line_no: int = Field(description="Номер строки запроса, на которую отвечает поставщик")
    price_raw: str = Field(description="Цена из письма дословно, например «230» или «1 250,50»")
    per_pack: bool = Field(description="true — цена за упаковку, а не за единицу")
    pack_size_raw: str | None = Field(description="Сколько штук в упаковке, дословно, если указано")
    quantity_raw: str | None = Field(
        description="Количество, которое предлагает поставщик, дословно"
    )
    unit_raw: str | None = Field(description="Единица, к которой относится цена, дословно")
    availability: Literal["in_stock", "to_order"] | None = Field(
        description="in_stock — в наличии, to_order — под заказ; не сказано — null"
    )
    delivery_days_raw: str | None = Field(
        description="Срок поставки дословно: «10 дней», «2 недели»"
    )
    is_analog: bool = Field(description="true — поставщик предлагает аналог вместо запрошенного")


class LLMEmailOffer(BaseModel):
    lines: list[LLMEmailLine]
    prices_with_vat: bool | None = Field(
        description="true — в письме сказано, что цены с НДС; false — без НДС; не сказано — null"
    )
    valid_days_raw: str | None = Field(description="Срок действия предложения дословно")
    delivery_price_raw: str | None = Field(description="Стоимость доставки дословно")
    addressed_to_agent: bool = Field(
        description="true — в письме команды или просьбы к ИИ, агенту или модели"
    )


# «230-00 руб» — рубли и копейки через дефис
_RUB_KOP_RE = re.compile(r"(?<![\d\-])(\d+)-(\d{2})(?!\d)")
CONFLICT_CAP = 0.6  # модель и правила разошлись в цене — КП проверит снабженец


def money(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    raw = _RUB_KOP_RE.sub(r"\1.\2", raw.translate(_THIN_SPACES))
    s = re.sub(r"[^\d,.]", "", raw.replace(" ", "").replace(" ", "")).replace(",", ".")
    if s.count(".") > 1:
        head, _, tail = s.rpartition(".")
        s = head.replace(".", "") + "." + tail
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    return value if value >= 0 else None


_NUMBER_WORDS = {"один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5,
                 "шесть": 6, "семь": 7, "десять": 10}  # fmt: skip
_WORD_DAYS_RE = re.compile(
    r"(?:(" + "|".join(_NUMBER_WORDS) + r")\s+)?(недел|месяц|мес\b|день|дня|дней)", re.IGNORECASE
)


def days(raw: str | None) -> int | None:
    """«10 дней» → 10, «5-7 раб. дней» → 7 (верхняя граница), «2 недели» → 14, «через неделю» → 7,
    «две недели» → 14, «7» → 7 (голое число — дни)."""
    text = (raw or "").strip()
    if m := DAYS_RE.search(text):
        n = int(m.group(2) or m.group(1))
        unit = m.group(4).casefold()
        return n * 7 if unit.startswith("нед") else n * 30 if unit.startswith("мес") else n
    if text.isdigit():
        return int(text)
    if m := _WORD_DAYS_RE.search(text):
        n = _NUMBER_WORDS.get((m.group(1) or "").casefold(), 1)
        unit = m.group(2).casefold()
        return n * 7 if unit.startswith("нед") else n * 30 if unit.startswith("мес") else n
    return None


def model_input(body: str, request: dict[str, Any]) -> str:
    lines = [
        f"{it['line_no']}. {it['name']} — {it['quantity']} {it['unit']}"
        for it in request.get("items", [])
    ]
    return "ЗАПРОС ПОКУПАТЕЛЯ:\n" + "\n".join(lines) + "\n\nПИСЬМО ПОСТАВЩИКА:\n" + body


async def read_letter(gw: Gateway, body: str, request: dict[str, Any]) -> LLMEmailOffer:
    res = await gw.call(
        prompt=load_prompt(*PROMPT),
        data=model_input(body, request),
        schema=LLMEmailOffer,
        max_tokens=128 + 96 * len(request.get("items", [])),
        seed=0,
    )
    return res.value


def _vat_of(body: str, at: int) -> str:
    """Чем считать упоминание «НДС» на позиции at: without, with или unclear."""
    for m in WITHOUT_VAT_RE.finditer(body):
        if m.start() <= at < m.end():
            return "without"
    for m in WITH_VAT_RE.finditer(body):
        if m.start() <= at < m.end():
            # «… не с НДС», «цены не указаны с НДС» — отрицание в той же строке перед формой
            line_start = body.rfind("\n", 0, m.start()) + 1
            before = body[max(line_start, m.start() - 30) : m.start()]
            return "unclear" if _NEGATION_RE.search(before) else "with"
    return "unclear"


def vat_mode(body: str) -> Literal["with", "without", "conflict", "unclear"]:
    """НДС решает текст письма, а не модель. Не сказано — без НДС (так просит запрос площадки);
    «с НДС» и «без НДС» в одном письме — conflict; сказано неоднозначно — unclear. В обоих
    случаях цены проверит снабженец."""
    mentions = list(_VAT_WORD_RE.finditer(body))
    kinds = {_vat_of(body, m.start()) for m in mentions}
    if _TAX_HINT_RE.search(body) or len(_VAT_LOOSE_RE.findall(body)) > len(mentions):
        kinds.add("unclear")
    if not kinds or kinds == {"without"}:
        return "without"
    if "unclear" in kinds:
        return "unclear"
    return "conflict" if kinds == {"with", "without"} else "with"


# Узкий неразрывный и тонкий пробел — тоже разделители разрядов: «1 355 руб»
_THIN_SPACES = str.maketrans({"\u202f": " ", "\u2009": " "})


def letter_numbers(body: str) -> set[Decimal]:
    """Отдельно стоящие числа письма: не часть артикула «6205-2RS» и не размер «40x62x10»."""
    return set(standalone_numbers(_RUB_KOP_RE.sub(r"\1,\2", body.translate(_THIN_SPACES))))


# Признак цены за единицу рядом: «238 руб/шт», «за шт», «по 238», «цена 238», «each»
_UNIT_PRICE_RE = re.compile(
    r"/\s*(?:шт|ед|компл|упак|уп|м|кг|л|пар|рулон|pc|pcs|unit)|за\s+(?:1\s*)?(?:шт|ед|единиц|"
    r"штук|упак|компл|м\b|метр|кг|пар)|(?<!\w)по\s+\d|(?<!\w)цен[аыуе]|\bprice\b|\bper\s|\beach\b|@",
    re.IGNORECASE,
)
_TOTAL_WORD_RE = re.compile(r"сумм|итог|всего|\btotal\b|\bamount\b", re.IGNORECASE)


def looks_like_total(price: Decimal, body: str, quantity: Decimal | None) -> bool:
    """Цена, похоже, — сумма за всё количество. В строке письма с этим числом:
    - есть число, которое, умноженное на количество запроса, даёт его («2 380 руб за 10 шт
      (238 руб/шт)», «… 10  238  2380»);
    - или сказано «сумма», «итого», «всего»;
    - или стоит само количество запроса, а признака цены за единицу нет («10 шт, 2 380 руб.»).
    Цена × количество тоже есть в строке или рядом признак цены за единицу — это цена.
    Такое КП проверит снабженец: итог за строку, принятый за цену, завысил бы её в разы."""
    if not quantity or quantity <= 1:
        return False
    for text in body.splitlines():
        nums = letter_numbers(text)
        if price not in nums:
            continue
        if price * quantity in nums:
            continue  # рядом и сумма за всё количество — значит, это цена за единицу
        if any(n not in (price, quantity) and n * quantity == price for n in nums):
            return True
        if _UNIT_PRICE_RE.search(text):
            continue
        if _TOTAL_WORD_RE.search(text) or quantity in nums:
            return True
    return False


# Белый список (решение 22.10): в таблицу сама идёт только цена, про которую в письме прямо
# сказано, что она за единицу. Отсутствие признаков итога доказательством не считается: форм
# записи итога и количества («десять штук», «×10», строкой выше) больше, чем шаблонов.
_CUR = r"^\s*(?:руб\w*\.?|р\.|₽|rub\w*|rur)?\s*"
# Единица у самого числа: «руб/шт», «руб. за 1 пару», «RUB per m», «each»
_AFTER_UNIT_RE = re.compile(
    _CUR + r"(?:/\s*(?P<a>[^\W\d_][\w.²]*)|за\s+(?:1\s*)?(?P<b>[^\W\d_][\w.²]*)|"
    r"per\s+(?P<c>[^\W\d_][\w.²]*)|(?P<each>each)\b)",
    re.IGNORECASE,
)
# Формы, которых нет в parse/units: винительный падеж и английский
_MARKER_UNITS = {
    "штуку": "шт", "ед": "шт", "ед.": "шт", "единицу": "шт", "единица": "шт", "unit": "шт",
    "piece": "шт", "item": "шт", "pcs.": "шт", "упаковку": "упак", "уп.": "упак", "пачку": "упак",
    "коробку": "упак", "коробка": "упак", "pack": "упак", "пару": "пара", "pair": "пара",
    "комплект.": "компл", "set": "компл", "бухту": "бухта", "coil": "бухта", "roll": "рулон",
    "m": "м", "meter": "м", "metre": "м", "kg": "кг",
}  # fmt: skip
# Цена за упаковку: упаковка, набор, бухта, рулон — кратность считает verify
_PACK_UNITS = {"упак", "компл", "пара", "рулон", "бухта"}
_PIECE_BEFORE_RE = re.compile(
    r"(?:цен\w*\s+за\s+(?:1\s*)?(?:ед\w*|шт\w*|единиц\w*)[^\d\n]{0,12}|unit\s+price[^\d\n]{0,12})\s*$",
    re.IGNORECASE,
)
_PACK_BEFORE_RE = re.compile(
    r"цен\w*\s+за\s+(?:1\s*)?(?:упак\w*|уп\b)[^\d\n]{0,12}$", re.IGNORECASE
)
_ANY_BEFORE_RE = re.compile(r"(?:(?<!\w)по|@)\s*$", re.IGNORECASE)
# Явное умножение в строке: «20 шт × 185 руб = 3 700 руб», «238*10=2380»
_MULTIPLY_RE = re.compile(r"\d\s*(?:руб\w*\.?|р\.|₽|шт\.?)?\s*[×xх*]\s*\d[^=\n]*=")
_FOREIGN_CURRENCY_RE = re.compile(
    r"[$€¥£]|(?<![a-z])(?:usd|eur|cny|gbp|rmb)(?![a-z])|(?<![а-яё])евро(?![а-яё])|"
    r"(?<![а-яё])(?:долл\w*|юан\w*)|(?<![а-яё])у\.\s?е\.",
    re.IGNORECASE,
)
_RUBLE_RE = re.compile(r"руб|₽|(?<![а-яё])р\.|(?<![a-z])(?:rub|rur)(?![a-z])", re.IGNORECASE)
# «1,250» и «12.500»: тысячи или дробь — решает снабженец
_AMBIGUOUS_THOUSANDS_RE = re.compile(r"\d[.,]\d{3}(?!\d)")
# Колонка таблицы — только с таким заголовком (без «руб», «без НДС», скобок)
_PRICE_HEADERS = {"цена", "цена за ед", "цена за единицу", "цена за шт", "price", "unit price",
                  "price per unit"}  # fmt: skip


def marker_unit(word: str) -> str | None:
    """Каноническая единица признака у числа: «шт.», «пару», «per m» → «шт», «пара», «м»."""
    w = word.casefold().replace("ё", "е").strip()
    return _MARKER_UNITS.get(w) or _MARKER_UNITS.get(w.rstrip(".")) or normalize_unit(w)


# «за 100 м», «per 10 pcs», «/10 шт» — цена за N единиц, то есть итог за N, а не за единицу
_COUNT_AFTER_RE = re.compile(_CUR + r"(?:за|per|/)\s*(\d+(?:[.,]\d+)?)\s*[^\W\d_]", re.IGNORECASE)
# Фасовка в строке позиции: при ней «по 12 руб.», «each» и колонка «Цена» не говорят, за что цена
_PACKAGING_RE = re.compile(
    r"упаков\w*|коробк\w*|(?<!\w)короб(?!\w)|пачк\w*|(?<!\w)банк[аеиу](?!\w)|бухт\w*|"
    r"рулон\w*|комплект\w*|набор\w*|фасовк\w*|поштучн\w*|(?<!\w)парами(?!\w)|"
    r"(?<![a-z])(?:box(?:es)?|cans?|coils?|packs?|rolls?|lots?|sets?|kits?)(?![a-z])",
    re.IGNORECASE,
)
_UNIT_HEADER_RE = re.compile(
    r"^(?:ед\.?|ед\.?\s*изм\.?|единица(?:\s+измерения)?|unit|uom|фасовка|упаковка)$", re.IGNORECASE
)


def _after_unit(tail: str) -> str | None:
    """Единица, названная сразу после числа: each — единица запроса (""); «за 100 м» — другая
    («?»); не названа — None."""
    count = _COUNT_AFTER_RE.search(tail)
    if count is not None and (money(count.group(1)) or Decimal(0)) > 1:
        return "?"
    m = _AFTER_UNIT_RE.search(tail)
    if m is None:
        return None
    if m.group("each"):
        return ""
    return marker_unit(m.group("a") or m.group("b") or m.group("c")) or "?"


def _cells(line: str) -> list[str] | None:
    """Ячейки строки таблицы в тексте письма (табуляция или «|»); не таблица — None."""
    for sep in ("\t", "|"):
        if line.count(sep) >= 2:
            return [c.strip() for c in line.strip().strip("|").split(sep)]
    return None


def _price_header(title: str) -> bool:
    key = re.sub(r"\(.*?\)|руб\.?|₽|rub|без\s+ндс|[,.:]", " ", title.casefold())
    return " ".join(key.split()) in _PRICE_HEADERS


def _in_price_column(lines: list[str], row: int, needle: str) -> bool:
    """Число в колонке с заголовком «Цена», «Цена за ед.», «Price», «Unit price» — и только так."""
    cells = _cells(lines[row])
    if cells is None:
        return False
    col = next((i for i, c in enumerate(cells) if c == needle), None)
    if col is None:
        return False
    for above in reversed(lines[:row]):
        header = _cells(above)
        if header is None:
            return False
        if len(header) == len(cells) and not any(ch.isdigit() for ch in "".join(header)):
            return _price_header(header[col])
    return False


def _other_unit_in_row(lines: list[str], row: int, want: str) -> bool:
    """В строке таблицы колонка «Ед.» или «Фасовка» говорит о другой единице, чем в запросе."""
    cells = _cells(lines[row])
    if cells is None:
        return False
    for above in reversed(lines[:row]):
        header = _cells(above)
        if header is None:
            return False
        if len(header) == len(cells) and not any(ch.isdigit() for ch in "".join(header)):
            for title, value in zip(header, cells, strict=True):
                if _UNIT_HEADER_RE.match(title.strip()) and value:
                    if marker_unit(value) != want:
                        return True
            return False
    return False


# Слово фасовки сразу после единицы: «1 200 руб./шт. упаковки (100 шт)», «9 650 руб./м бухты» —
# единица названа, но цена за упаковку
_PACK_AFTER_UNIT_RE = re.compile(
    r"^[\s.]*(?:упак|уп\b|бухт|рулон|короб|кор\b|пачк|пакет|мешк|мешок|блистер|катушк|банк|"
    r"reel|carton|ctn|box|bag|pack|coil|roll|can\b)",
    re.IGNORECASE,
)
# Косвенное доказательство засчитываем, только если цена близка к медиане других предложений
PEER_NEAR = Decimal("1.8")


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    half = len(ordered) // 2
    return ordered[half] if len(ordered) % 2 else (ordered[half - 1] + ordered[half]) / 2


def near_peers(price: Decimal | None, peers: list[Decimal] | None) -> bool:
    """Есть хотя бы два других предложения по строке, и цена не дальше чем в 1,8 раза от их
    медианы. Одно предложение не годится: если его ввели с той же ошибкой (итог вместо цены),
    ошибка подтвердила бы сама себя."""
    if price is None or price <= 0 or not peers or len(peers) < 2:
        return False
    mid = _median(peers)
    return mid > 0 and price <= mid * PEER_NEAR and price * PEER_NEAR >= mid


def unit_price_marked(
    raw: str,
    body: str,
    quantity: Decimal | None = None,
    per_pack: bool = False,
    unit: str | None = None,
    peers: list[Decimal] | None = None,
) -> bool:
    """Сказано ли в письме прямо, что это цена за единицу строки запроса unit (за упаковку —
    если per_pack). Доказательства:
    1. у самого числа названа единица запроса: «руб/шт», «за 1 шт», «per m» при запросе в метрах
       (но не «руб./шт. упаковки»). Если единица запроса — фасовка (упак, бухта, рулон, компл),
       то только при медиане других предложений, как косвенные. Для цены за упаковку —
       «руб/упак», «за комплект», «за пару»;
    2. косвенные — «each», «по 238», «@ 238», «цена за ед.», «unit price», колонка «Цена», явное
       умножение «20 шт × 185 руб = 3 700 руб». Они не называют единицу, а фасовку письмо может
       назвать как угодно и где угодно («упак. 100 шт», «reel of 5000», строкой ниже), поэтому
       засчитываются, только если запрос в штуках, в сделке есть другие предложения по строке
       и цена отличается от их медианы не больше чем в 1,8 раза (peers).
    «За 100 м», «per 10 pcs» — итог за N, не доказательство. Нет — цена в таблицу сама не идёт."""
    text = body.translate(_THIN_SPACES)
    needle = raw.translate(_THIN_SPACES).strip()
    if not needle or _AMBIGUOUS_THOUSANDS_RE.search(needle):
        return False
    want = normalize_unit(unit or "шт") or (unit or "шт")
    value = money(needle)
    lines = text.split("\n")
    pattern = re.compile(r"(?<![\d.,])" + re.escape(needle) + r"(?![\d])")
    # Косвенные доказательства — только при медиане других предложений (см. выше); фасовка
    # в строке их тоже отменяет, но это подсказка, а не защита
    near = want == "шт" and near_peers(value, peers)
    for row, line in enumerate(lines):
        packed = bool(_PACKAGING_RE.search(line)) or _other_unit_in_row(lines, row, want)
        soft = near and not packed
        for m in pattern.finditer(line):
            tail = line[m.end() : m.end() + 40]
            named = _after_unit(tail)
            head = line[max(0, m.start() - 40) : m.start()]
            if per_pack:
                if named in _PACK_UNITS or (named is None and _PACK_BEFORE_RE.search(head)):
                    # Запрос в единицах фасовки: размер упаковки у поставщика может быть другим —
                    # только при медиане других предложений, как явная единица ниже
                    if want not in _PACK_UNITS or near_peers(value, peers):
                        return True
                continue
            if named is not None:
                unit_end = _AFTER_UNIT_RE.search(tail)
                rest = tail[unit_end.end() :] if unit_end is not None else ""
                if named == want and not _PACK_AFTER_UNIT_RE.search(rest):
                    # Единица запроса — сама фасовка (упак, бухта, рулон, компл): размер фасовки
                    # у поставщика может быть другим («650 руб./упак (50 пар)» при упаковке
                    # 100 пар) — такая цена тоже только при медиане других предложений
                    if want not in _PACK_UNITS or near_peers(value, peers):
                        return True
                    continue
                if named == "" and soft:
                    return True
                continue  # другая единица: «за пару», «/компл», «за 100 м», «/шт. упаковки»
            if soft and (_ANY_BEFORE_RE.search(head) or _PIECE_BEFORE_RE.search(head)):
                return True
            if soft and value is not None and quantity and quantity > 1:
                if _MULTIPLY_RE.search(line) and value * quantity in letter_numbers(line):
                    return True
            if soft and _in_price_column(lines, row, needle):
                return True
    return False


def far_from_peers(price: Decimal, peers: list[Decimal]) -> bool:
    """Цена за единицу отличается от медианы других предложений по той же строке больше чем
    в 3 раза: итог вместо цены, «12.500» вместо 12 500 — при любой записи в письме."""
    if not peers or price <= 0:
        return False
    mid = _median(peers)
    return mid > 0 and (price > mid * 3 or price * 3 < mid)


def in_letter(raw: str | None, numbers: set[Decimal]) -> Decimal | None:
    """Число из ответа модели, если оно отдельно стоит в письме: «620» из «6205-2RS» не годится."""
    value = money(raw)
    return value if value is not None and value in numbers else None


def verify(
    raw: LLMEmailOffer,
    body: str,
    request: dict[str, Any],
    rules_prices: dict[int, Decimal] | None = None,
    peer_prices: dict[int, list[Decimal]] | None = None,
) -> dict[str, Any]:
    """Строки КП (поля EmailOfferLine), заметки и уверенность.

    Числа берутся, только если они отдельно стоят в тексте письма. rules_prices — цены строк
    по правилам базового агента: разошлись с моделью (сумма вместо цены, чужая строка) —
    уверенность не выше CONFLICT_CAP. peer_prices — цены за единицу других предложений сделки
    по строкам: отличается больше чем в 3 раза — тоже не выше CONFLICT_CAP."""
    items = {it["line_no"]: it for it in request.get("items", [])}
    numbers = letter_numbers(body)
    vat = vat_mode(body)
    lines: list[dict[str, Any]] = []
    notes: list[str] = []
    dropped = conflicts = 0
    for ln in raw.lines:
        it = items.get(ln.request_line_no)
        if it is None or any(x["request_line_no"] == ln.request_line_no for x in lines):
            dropped += 1
            continue
        no = ln.request_line_no
        price = in_letter(ln.price_raw, numbers)
        if price is None:
            notes.append(f"Строка {no}: цена «{ln.price_raw}» в письме не найдена — не взята.")
            dropped += 1
            continue
        rules = (rules_prices or {}).get(no)
        if rules is not None and rules != price:
            notes.append(
                f"Строка {no}: модель взяла цену {ln.price_raw}, правила — {rules}; проверьте."
            )
            conflicts += 1
        elif not ln.per_pack and looks_like_total(price, body, money(str(it["quantity"]))):
            notes.append(
                f"Строка {no}: {ln.price_raw} похоже на сумму за всё количество — проверьте."
            )
            conflicts += 1
        elif not unit_price_marked(
            ln.price_raw,
            body,
            money(str(it["quantity"])),
            ln.per_pack,
            it.get("unit"),
            (peer_prices or {}).get(no),
        ):
            notes.append(
                f"Строка {no}: у цены {ln.price_raw} не сказано, что она за единицу — проверьте."
            )
            conflicts += 1
        if vat == "with":
            price = (price / VAT).quantize(Decimal("0.01"), ROUND_HALF_UP)
        qty = in_letter(ln.quantity_raw, numbers)
        unit = normalize_unit(ln.unit_raw) if ln.unit_raw and contains(body, ln.unit_raw) else None
        pack = in_letter(ln.pack_size_raw, numbers)
        asked = normalize_unit(str(it.get("unit") or "")) or str(it.get("unit") or "")
        if ln.per_pack and asked in _PACK_UNITS:
            # Запрос сам в упаковках (комплектах, бухтах): цена за упаковку и есть цена за единицу
            # запроса — количество запроса не делим («10 упак» остаются 10, а не 10 / 100)
            qty, unit = money(str(it["quantity"])) or Decimal(1), asked
        elif ln.per_pack:
            # Цена за упаковку при запросе в штуках: всегда пересчитываем в упаковки, даже если
            # модель сама назвала единицу «упак» — иначе строка взяла бы «500 шт» из запроса
            # при цене за упаковку. «(100 шт)» рядом с ценой — кратность, а не количество; нет
            # кратности — ядро отдаст строку снабженцу (unit_problems)
            if pack is None and qty is not None and unit == "шт":
                pack = qty
            if qty is not None and unit == "упак":
                pass  # поставщик сам назвал число упаковок («в наличии 3 упак.») — как есть
            elif qty is not None and unit == "шт" and pack and qty != pack:
                # «есть только 300 шт» при кратности 100 — 3 упаковки, а не количество запроса
                qty = (qty / pack).to_integral_value(rounding="ROUND_CEILING")
            else:
                want = money(str(it["quantity"])) or Decimal(1)
                qty = (want / pack).to_integral_value(rounding="ROUND_CEILING") if pack else want
            unit = "упак"
        line: dict[str, Any] = {
            "request_line_no": no,
            "name": it["name"],
            "quantity": str(qty if qty and unit else it["quantity"]),
            "unit": unit if qty and unit else it["unit"],
            "price": str(price),
            "is_analog": ln.is_analog,
        }
        if pack:
            line["pack_size"] = str(pack)
        # Цена за единицу запроса: другие предложения считают в ней же. Делим на кратность, только
        # если запрос в штуках, а поставщик дал цену за упаковку
        piece = price / pack if (unit == "упак" and pack and asked not in _PACK_UNITS) else price
        if far_from_peers(piece, (peer_prices or {}).get(no, [])):
            notes.append(f"Строка {no}: цена сильно отличается от других предложений — проверьте.")
            conflicts += 1
        if ln.availability:
            line["availability"] = ln.availability
        if (d := days(ln.delivery_days_raw)) is not None and contains(
            body, ln.delivery_days_raw or ""
        ):
            line["delivery_days"] = d
        lines.append(line)
    for no in items:
        if not any(x["request_line_no"] == no for x in lines):
            if (rules_prices or {}).get(no) is not None:
                # Правила видят цену строки, а модель её не взяла: КП вышло бы неполным
                notes.append(
                    f"Строка {no}: в письме есть цена, но строка не разобрана — проверьте."
                )
                conflicts += 1
            else:
                notes.append(f"Строка {no}: в письме цены нет.")
    # Потолок уверенности: «с НДС» и «без НДС» в одном письме — цены проверит снабженец
    cap = 1.0
    if vat == "with":
        # «С НДС» могло относиться не к ценам товара («доставка … с НДС»): пересчитанные цены
        # в таблицу сами не идут
        notes.append("Цены в письме с НДС — пересчитаны без НДС (22 %), проверьте.")
        cap = CONFLICT_CAP
    if vat == "conflict":
        notes.append("В письме и «с НДС», и «без НДС» — проверьте цены.")
        cap = CONFLICT_CAP
    if vat == "unclear":
        notes.append("НДС в письме указан неоднозначно — цены не пересчитаны, проверьте.")
        cap = CONFLICT_CAP
    # Валюта: «Цены в евро» строкой выше и «2,40/шт» ниже — число не в рублях. Иностранная валюта
    # где угодно в письме или ни одного упоминания рубля — проверит снабженец
    if _FOREIGN_CURRENCY_RE.search(body):
        notes.append("В письме названа другая валюта — цены могут быть не в рублях, проверьте.")
        cap = min(cap, CONFLICT_CAP)
    elif lines and not _RUBLE_RE.search(body):
        notes.append("Валюта в письме не указана — проверьте, что цены в рублях.")
        cap = min(cap, CONFLICT_CAP)
    if conflicts:
        cap = min(cap, CONFLICT_CAP)
    if raw.addressed_to_agent:
        # Второй слой фильтра (ТЗ §12: правила плюс облегчённая модель): письмо обращается к ИИ —
        # в таблицу без снабженца не пускаем
        notes.append("В письме есть обращение к ИИ или агенту — проверьте письмо.")
        cap = min(cap, SUSPICIOUS_CAP)
    confidence = min(len(lines) / (len(lines) + dropped), cap) if lines else 0.0
    out: dict[str, Any] = {
        "lines": lines, "notes": notes, "confidence": round(confidence, 3), "dropped": dropped,
        "cap": cap,
    }  # fmt: skip
    # Срок действия: модель не всегда видит его в «цены действительны 7 дней» — тогда по тексту
    valid = (
        raw.valid_days_raw if raw.valid_days_raw and contains(body, raw.valid_days_raw) else None
    )
    if valid is None and (found := VALID_RE.search(body)):
        valid = found.group(1)
    if (v := days(valid)) is not None:
        out["valid_days"] = max(1, min(v, 90))
    if raw.delivery_price_raw and contains(body, raw.delivery_price_raw):
        if (dp := money(raw.delivery_price_raw)) is not None:
            out["delivery_price"] = str(dp)
    return out
