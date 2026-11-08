"""Разбор запроса → содержимое объекта «Запрос» ядра (backend/schemas/rfq.schema.json).

В отсекающие и желательные требования идёт только то, что ядро сверяет с карточкой товара
точным равенством: бренд, класс точности, стандарт. Атрибут, которого нет в карточке, ядро
считает неподтверждённым, и такое КП не идёт в выбор (ПК-3). Поэтому свободный текст туда
не кладём: условие строки — в её характеристики, общее условие — в заметки снабженцу.
"""

import re
from datetime import date
from typing import Any

from .parser import split_lines
from .schemas import ParsedRequest, Position, Requirement
from .text import contains

# Бренды тестовых каталогов и частые в запросах; по ним узнаём требование «бренд».
BRANDS = (
    "SKF", "FAG", "INA", "NSK", "NTN", "Timken", "Koyo", "ZWZ", "ГПЗ", "ЕПК",
    "Optibelt", "Gates", "ContiTech", "Bando", "Megadyne", "Corteco", "Trelleborg", "Elring",
    "БРТ", "IEK", "EKF", "DKC", "ABB", "Schneider", "Legrand", "Wilo", "Grundfos", "KSB",
)  # fmt: skip
# Другие написания тех же брендов: «ИЭК» в заявке и «IEK» в карточке — один бренд
BRAND_ALIASES = {
    "ИЭК": "IEK", "ЕКФ": "EKF", "СКФ": "SKF", "ФАГ": "FAG", "НСК": "NSK", "Тимкен": "Timken",
    "Континентал": "ContiTech", "Оптибелт": "Optibelt", "Гейтс": "Gates", "Кортеко": "Corteco",
}  # fmt: skip
_BRAND_NAMES = {b.casefold(): b for b in BRANDS} | {
    a.casefold(): b for a, b in BRAND_ALIASES.items()
}
_BRAND_RE = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(b) for b in (*BRANDS, *BRAND_ALIASES)) + r")(?![\w-])",
    re.IGNORECASE,
)
_BRAND_WORD_RE = re.compile(
    # Только латиница: «производитель любой» — не бренд; кириллические бренды есть в BRANDS
    r"(?:бренд\w*|марк[аиуе]|производител\w*)\s*[:\-–—]?\s*[«\"]?([A-Za-z][\w&.\-]{1,30})"
)
_STANDARD_RE = re.compile(r"(?<![\w-])(ГОСТ\s*Р?|DIN|ISO|ТУ)\s*([\d][\d.]*)", re.IGNORECASE)
_PRECISION_RE = re.compile(r"класс\w*\s+точност\w*\s*[:\-–—]?\s*([PРpр]?\s?\d)", re.IGNORECASE)
_NO_ANALOGS_RE = re.compile(
    r"без\s+аналог|аналог\w*\s+не\s+(?:предлаг|принима|рассматрива)|только\s+оригинал",
    re.IGNORECASE,
)
_NO_ANALOGS_TAIL_RE = re.compile(
    r"[\s,;(—–-]*\(?\s*(?:без\s+аналог\w*|только\s+оригинал\w*)\s*\)?[\s,;)]*", re.IGNORECASE
)
_DEFERRAL_RE = re.compile(r"отсрочк", re.IGNORECASE)
_DAYS_RE = re.compile(
    r"(\d{1,3})\s*(?:календарн\w*\s+|рабоч\w*\s+)?(?:дн|день|дня|дней)", re.IGNORECASE
)
_DELIVERY_RE = re.compile(r"доставк|адрес|склад", re.IGNORECASE)
# Признаки условия поставки. «Условие» без них — скорее непонятая строка: модель мета-разбора
# иногда относит туда мусор («что-то непонятное»), и строка пропала бы из запроса.
_CONDITION_RE = re.compile(
    r"оплат|отсроч|предоплат|доставк|адрес|склад|отгруз|самовывоз|сертифик|паспорт|документ|"
    r"гаранти|аналог|оригинал|эквивалент|бренд|марк|производ|гост|din|iso|\bту\b|срок|только|"
    r"обязательн|желательн|возможност|упаков|маркир|сч[её]т|ндс|кп\b|предложени|цен|бюджет|"
    r"класс|стандарт|качеств|нов(ый|ые|ая)|не\s+(ранее|позднее|более|менее)",
    re.IGNORECASE,
)
_RULES_ONLY_RE = re.compile(r"\s*(?:бюджет|срок|поставка\s+до|нужно\s+(?:к|до))", re.IGNORECASE)

_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}  # fmt: skip
_DMY_RE = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?(?!\d)")
_DM_TEXT_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s+(январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|"
    r"декабр)\w*(?:\s+(\d{4}))?",
    re.IGNORECASE,
)

KIND = {"order": "order", "budget_estimate": "budget"}
# Пределы схемы rfq ядра (deals/contracts.py): строка, позиции, требования у строки
MAX_TEXT, MAX_LINES, MAX_REQUIREMENTS = 4000, 500, 50

# Строки, которые не позиция: обращение, просьба, подпись, контакты, условия для правил ядра.
_NOT_ITEM_RE = re.compile(
    r"^(?:добр|здравствуй|уважаем|прош|просим|спасибо|благодар|с уважением|заранее|тел|"
    r"моб|e-?mail|почт|контакт|исп\.|исполнител|менеджер|отдел|срок|поставка|доставка|"
    r"нужно к|нужно до|бюджет|оплат)",
    re.IGNORECASE,
)
_CONTACT_RE = re.compile(r"(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}|\S+@\S+")
_BULLET_RE = re.compile(r"^\s*(?:\d+[.)]\s+|[-•*·]\s*)")


def brands_in(text: str) -> set[str]:
    """Бренды из списка BRANDS, упомянутые в тексте, в каноническом написании."""
    return {_canon_brand(m.group(1)) for m in _BRAND_RE.finditer(text)}


def structured_requirement(text: str) -> tuple[str, str] | None:
    """«только SKF» → («бренд», «SKF»). Не узнали или несколько вариантов («SKF или FAG») — None:
    «или» в атрибуте ядра не выразить, а угадывать нельзя."""
    brands = {_canon_brand(m.group(1)) for m in _BRAND_RE.finditer(text)}
    if len(brands) == 1:
        return "бренд", next(iter(brands))
    if not brands and (m := _BRAND_WORD_RE.search(text)):
        return "бренд", m.group(1)
    standards = {(s.upper().replace(" ", ""), n.rstrip(".")) for s, n in _STANDARD_RE.findall(text)}
    if len(standards) == 1:
        kind, number = next(iter(standards))
        kind = "ГОСТ Р" if kind == "ГОСТР" else kind
        # «ГОСТ 520-2011» → «ГОСТ 520»: год редакции в карточках не пишут
        return "стандарт", f"{kind} {number}"
    if m := _PRECISION_RE.search(text):
        value = m.group(1).replace(" ", "").upper().replace("Р", "P")
        return "класс точности", value
    return None


def _canon_brand(found: str) -> str:
    return _BRAND_NAMES[found.casefold()]


def brand_key(name: str | None) -> str:
    """Бренд для сравнения: известный — в каноническом написании («ИЭК» → iek), иначе как есть."""
    n = " ".join(str(name or "").split())
    return _BRAND_NAMES.get(n.casefold(), n).casefold()


def parse_due(raw: str | None, today: date) -> date | None:
    """«до 25.10», «к 25.10.2026», «25 октября» → дата. Относительные сроки («10 дней») — None."""
    if not raw:
        return None
    if m := _DMY_RE.search(raw):
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
    elif m := _DM_TEXT_RE.search(raw):
        stem = m.group(2).casefold()
        day, year = int(m.group(1)), m.group(3)
        month = next(v for k, v in _MONTHS.items() if stem.startswith(k))
    else:
        return None
    y = (2000 + int(year) if len(year) == 2 else int(year)) if year else today.year
    try:
        due = date(y, month, day)
    except ValueError:
        return None
    if not year and due < today:
        due = date(y + 1, month, day)
    return due


def _item(no: int, p: Position, notes: list[str]) -> dict[str, Any]:
    name = p.name
    if p.article and p.article.casefold() not in name.casefold():
        name = f"{name} {p.article}"
    item: dict[str, Any] = {"line_no": no, "source_text": p.source, "name": name}
    if p.quantity is None:
        # Количество не нашли в тексте — не выдумываем: строку поправит снабженец
        item.update(quantity="1", unit=p.unit or "шт", recognized=False)
    else:
        item.update(quantity=str(p.quantity), unit=p.unit or p.unit_raw or "шт")
        # Про единицу уже сказала проверка строки — вторая заметка ей только противоречит
        if not p.unit and not any("единиц" in problem for problem in p.problems):
            notes.append(
                f"Строка {no}: единица «{p.unit_raw}» незнакома — проверьте."
                if p.unit_raw
                else f"Строка {no}: единица не указана — поставлено «шт», проверьте."
            )
    if p.problems:
        notes.append(f"Строка {no}: {'; '.join(p.problems)}.")
    return item


def is_item_candidate(line: str) -> bool:
    """Непонятая строка, которая может быть позицией: её покажем снабженцу с recognized=false."""
    return not (
        line.endswith(":")
        or _NOT_ITEM_RE.match(_BULLET_RE.sub("", line))
        or _CONTACT_RE.search(line)
        or _NO_ANALOGS_RE.search(line)
    )


def scoped_items(text: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """«Подшипники только SKF» относится к подшипникам, а не ко всему запросу: общее требование
    ядро проверяет на каждой строке, и ремни с кабелем выпали бы из выбора."""
    stems = {w[:6] for w in re.findall(r"[а-яё]{5,}", text.casefold())}
    return [
        it
        for it in items
        if it.get("recognized", True) and any(st in it["name"].casefold() for st in stems)
    ]


def to_rfq(
    parsed: ParsedRequest, today: date | None = None, text: str | None = None
) -> tuple[dict[str, Any], list[str]]:
    """Содержимое rfq и заметки снабженцу. Бюджет и потолки рассылки здесь не заполняются.

    С текстом запроса строки, которые не стали ни позицией, ни требованием, ни сроком,
    идут позициями с recognized=false (не додумываем, ТЗ §6): с ними разослать нельзя,
    снабженец поправит или удалит.
    """
    today = today or date.today()
    notes: list[str] = []
    entries: list[tuple[int, Position | str]] = [(p.line, p) for p in parsed.positions]
    # Условие на строке позиции — её характеристика; общее «условие» без признаков условия
    # и без бренда/стандарта — непонятая строка, она пойдёт позицией с recognized=false
    position_lines = {p.line for p in parsed.positions}
    requirements = [
        r
        for r in parsed.requirements
        if r.line in position_lines
        or _CONDITION_RE.search(r.text)
        or structured_requirement(r.text) is not None
    ]
    if text is not None:
        covered = {p.line for p in parsed.positions} | {r.line for r in requirements}
        for n, line in enumerate(split_lines(text), start=1):
            deadline = parsed.deadline_raw and contains(line, parsed.deadline_raw)
            if n not in covered and not deadline and is_item_candidate(line):
                entries.append((n, line))
    by_line: dict[int, dict[str, Any]] = {}
    items = []
    for no, (line_no, entry) in enumerate(sorted(entries, key=lambda e: e[0]), start=1):
        if isinstance(entry, str):
            item = {
                "line_no": no, "source_text": entry, "name": _BULLET_RE.sub("", entry) or entry,
                "quantity": "1", "unit": "шт", "recognized": False,
            }  # fmt: skip
            notes.append(f"Строка {no}: не удалось разобрать — заполните вручную или удалите.")
        else:
            item = _item(no, entry, notes)
        items.append(item)
        by_line.setdefault(line_no, item)

    for item in items:
        source, name = str(item.get("source_text") or ""), str(item["name"])
        if item.get("recognized", True) and _NO_ANALOGS_RE.search(source):
            # «Подшипник 6205 без аналогов — 8 шт»: запрет только для этой строки
            item["allow_analogs"] = False
            item["name"] = _NO_ANALOGS_TAIL_RE.sub(" ", name).strip() or name

    content: dict[str, Any] = {"items": items, "kind": KIND[parsed.kind]}
    delivery: dict[str, Any] = {}
    if due := parse_due(parsed.deadline_raw, today):
        delivery["due_date"] = due.isoformat()
    elif parsed.deadline_raw:
        notes.append(f"Срок «{parsed.deadline_raw}» не удалось привести к дате — укажите дату.")
    for r in requirements:
        targets = [by_line[r.line]] if r.line in by_line else scoped_items(r.text, items)
        if not targets:
            _place_requirement(r, content, None, delivery, notes)
        for item in targets:
            _place_requirement(r, content, item, delivery, notes)
    if delivery:
        content["delivery"] = delivery
    if text is None:
        for line in parsed.possibly_missed:
            notes.append(f"Возможно, пропущено: «{line}».")
    if not items:
        notes.append("В тексте не найдено ни одной позиции.")
    fit_schema(content, notes)
    return content, notes


def payment_request(text: str) -> dict[str, Any] | None:
    """«Нужна отсрочка 30 дней» → просьба об отсрочке (ПР-6 решает ядро у поставщика)."""
    if not _DEFERRAL_RE.search(text):
        return None
    m = _DAYS_RE.search(text)
    days = int(m.group(1)) if m and 1 <= int(m.group(1)) <= 180 else None
    return {"kind": "deferral", **({"days": days} if days else {})}


def fit_schema(content: dict[str, Any], notes: list[str]) -> None:
    """Пределы схемы rfq: лишнее обрезаем с заметкой снабженцу, а не роняем разбор."""
    items = content["items"]
    if len(items) > MAX_LINES:
        notes.append(f"Позиций {len(items)} — в запрос вошли первые {MAX_LINES}.")
        del items[MAX_LINES:]
    for owner in [content, *items]:
        for key in ("must_have", "nice_to_have"):
            if len(owner.get(key, [])) > MAX_REQUIREMENTS:
                notes.append(f"Требований больше {MAX_REQUIREMENTS} — лишние не вошли.")
                del owner[key][MAX_REQUIREMENTS:]
    for owner in [*items, content.get("delivery") or {}]:
        for key, value in owner.items():
            if isinstance(value, str) and len(value) > MAX_TEXT:
                owner[key] = value[:MAX_TEXT]


def _place_requirement(
    r: Requirement,
    content: dict[str, Any],
    item: dict[str, Any] | None,
    delivery: dict[str, Any],
    notes: list[str],
) -> None:
    if _NO_ANALOGS_RE.search(r.text):
        (item if item is not None else content)["allow_analogs"] = False
        return
    if (payment := payment_request(r.text)) is not None:
        content["payment"] = payment
        return
    if _RULES_ONLY_RE.match(r.text) and (
        r.text.casefold().startswith("бюджет") or "due_date" in delivery
    ):
        return  # бюджет и разобранный срок кладут правила и дата; в заметках не дублируем
    key = "must_have" if r.mandatory else "nice_to_have"
    target = item if item is not None else content
    if (pair := structured_requirement(r.text)) is not None:
        target.setdefault(key, []).append({"attribute": pair[0], "value": pair[1]})
    elif item is not None:
        item["characteristics"] = "; ".join(x for x in (item.get("characteristics"), r.text) if x)
    elif _DELIVERY_RE.search(r.text) and "region" not in delivery:
        delivery["region"] = r.text
    else:
        kind = "обязательное" if r.mandatory else "желательное"
        notes.append(
            f"Условие «{r.text}» ({kind}) не перенесено в запрос — добавьте при необходимости."
        )
