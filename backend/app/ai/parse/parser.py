"""Разбор текстового запроса в позиции (раздел 6 ТЗ, «Разбор запроса»).

Строки запроса нумеруются. Модель называет номер строки и дословные значения,
код проверяет их по этой строке, сам разбирает количество и приводит единицу.
Не прошла проверка — строка помечается «требует проверки», а не додумывается.

Для скорости позиции разбираются кусками параллельно (по слоту сервера на кусок),
общие поля запроса — отдельным коротким вызовом по всему тексту.
"""

import asyncio
import re

from ..gateway import Gateway, load_prompt
from .schemas import (
    LLMMeta,
    LLMPosition,
    LLMPositions,
    LLMRequest,
    ParsedRequest,
    Position,
    Requirement,
)
from .text import contains, in_thousands, parse_quantity, standalone_numbers, strip_thousands
from .units import normalize_unit, units_in

# Больше — почти наверняка код или номер, принятый за количество: на проверку.
MAX_PLAUSIBLE_QTY = 100_000
# Ответ модели: позиция в JSON — до ~60 токенов, с запасом вдвое; мета — тип, срок, требования
CHUNK_BASE_TOKENS, CHUNK_LINE_TOKENS = 192, 128
META_BASE_TOKENS, META_LINE_TOKENS = 256, 48

POSITIONS_PROMPT = ("parse_positions", 2)
META_PROMPT = ("parse_meta", 3)

_DIGIT_RE = re.compile(r"\d")
# Телефоны и почты в подписи — не позиции.
_CONTACT_RE = re.compile(r"(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}|\S+@\S+")
# Код номенклатуры заказчика в начале строки, после номера пункта: «1) 30784809 - ПОДШИПНИК…»,
# «2363145 «Подшипник…»». Номер пункта короткий (1–3 цифры), код — от 5 цифр или с буквами.
_LEAD_CODE_RE = re.compile(r"^\s*(?:\d{1,3}[.)]\s*)?((?:[A-ZА-ЯЁ]{1,4})?\d{5,})(?![\d.,])")
# Подпись и контакты: «С уважением, Иванов Пётр, +7 900…», «Тел.: …», «e-mail: …».
_SIGNATURE_RE = re.compile(
    r"^\s*(?:с\s+уважением|спасибо|благодар|контактное\s+лицо|исполнитель|тел\b|тел\.|"
    r"моб\b|моб\.|e-?mail|почта|эл\.\s*почта)",
    re.IGNORECASE,
)
# Артикул после «арт.»: «… ВТМ арт. ВТМ00052310 или эквивалент».
_ART_CODE_RE = re.compile(r"\bарт\.?\s*([A-ZА-ЯЁ0-9][\w\-/]*\d[\w\-/]*)", re.IGNORECASE)


def split_lines(text: str) -> list[str]:
    """Непустые строки запроса; номер строки = индекс + 1."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def numbered(lines: list[str], numbers: range) -> str:
    return "\n".join(f"[{n}] {lines[n - 1]}" for n in numbers)


def chunk_ranges(n_lines: int, n_chunks: int) -> list[range]:
    """Делит строки 1..n на n_chunks непрерывных кусков почти равной длины."""
    n_chunks = max(1, min(n_chunks, n_lines))
    size, extra = divmod(n_lines, n_chunks)
    ranges, start = [], 1
    for i in range(n_chunks):
        end = start + size + (1 if i < extra else 0)
        ranges.append(range(start, end))
        start = end
    return ranges


def is_signature(lines: list[str], line: int) -> bool:
    text = lines[line - 1] if 1 <= line <= len(lines) else ""
    return bool(_SIGNATURE_RE.match(text) or _CONTACT_RE.search(text))


def restore_codes(name: str, source: str, quantity_raw: str | None) -> str:
    """Коды из строки, которые модель выкинула из названия, — обратно. Модель путает код
    в начале строки с номером пункта и отрезает «арт. …» вместе с «или эквивалент»; код
    поставщика и заказчика нужен для подбора, поэтому его возвращает код, а не промпт."""
    lead = _LEAD_CODE_RE.match(source)
    if lead and lead.group(1) != (quantity_raw or "").strip() and not contains(name, lead.group(1)):
        name = f"{lead.group(1)} - {name}"
    for m in _ART_CODE_RE.finditer(source):
        if not contains(name, m.group(1)):
            name = f"{name} арт. {m.group(1)}"
    return name


def build_position(index: int, raw: LLMPosition, lines: list[str]) -> Position:
    problems: list[str] = []
    notes: list[str] = []

    valid_line = 1 <= raw.line <= len(lines)
    source = lines[raw.line - 1] if valid_line else ""
    if not valid_line:
        problems.append(f"строки {raw.line} нет в запросе")

    article = raw.article
    if article and not contains(source, article):
        notes.append(f"артикул «{article}» не найден в строке и отброшен")
        article = None

    quantity = None
    unit_raw, unit_thousands = strip_thousands(raw.unit_raw)
    if raw.quantity_raw is None:
        problems.append("количество не указано")
    elif not contains(source, raw.quantity_raw):
        problems.append(f"количество «{raw.quantity_raw}» не найдено в строке")
    else:
        quantity = parse_quantity(raw.quantity_raw)
        if quantity is None:
            problems.append(f"не удалось разобрать количество «{raw.quantity_raw}»")
        elif quantity <= 0:
            problems.append("количество должно быть больше нуля")
            quantity = None
        elif _DIGIT_RE.search(raw.quantity_raw) and quantity not in standalone_numbers(source):
            # «2» из «6204-2RS» — не количество.
            problems.append(f"число {quantity} в строке — часть обозначения, а не количество")
            quantity = None
        elif unit_thousands or in_thousands(source, raw.quantity_raw):
            quantity *= 1000  # «2 тыс. шт»
        if quantity is not None and quantity > MAX_PLAUSIBLE_QTY:
            problems.append(f"подозрительно большое количество {quantity}: похоже на код")
            quantity = None

    unit = None
    if unit_raw is None:
        notes.append("единица не указана, сверить с каталогом")
    elif not contains(source, unit_raw):
        # Модель могла сама привести «шт» к «штука»: принимаем, только если такая
        # единица действительно есть в строке.
        canon = normalize_unit(unit_raw)
        if canon and canon in units_in(source):
            unit = canon
            notes.append(f"единица «{unit_raw}» приведена моделью, в строке есть «{canon}»")
        else:
            problems.append(f"единица «{unit_raw}» не найдена в строке")
    else:
        unit = normalize_unit(unit_raw)
        if unit is None:
            problems.append(f"незнакомая единица «{unit_raw}»")

    return Position(
        index=index,
        line=raw.line,
        source=source,
        name=restore_codes(raw.name, source, raw.quantity_raw),
        article=article,
        quantity=quantity,
        unit=unit,
        unit_raw=unit_raw,
        status="needs_review" if problems else "ok",
        problems=problems,
        notes=notes,
    )


def find_missed(lines: list[str], covered: set[int], deadline: str | None) -> list[str]:
    """Строки с цифрами, не попавшие ни в позицию, ни в требование, ни в срок."""
    missed = []
    for n, line in enumerate(lines, start=1):
        if n in covered or (deadline and contains(line, deadline)):
            continue
        if _DIGIT_RE.search(_CONTACT_RE.sub("", line)):
            missed.append(line)
    return missed


def postprocess(raw: LLMRequest, text: str) -> ParsedRequest:
    lines = split_lines(text)
    # Строку с условием («аналоги согласовывать отдельно») разбор кусками мог принять
    # за позицию: без количества на строке-требовании позиции нет.
    requirement_lines = {r.line for r in raw.requirements}
    kept = [p for p in raw.positions if p.quantity_raw or p.line not in requirement_lines]
    # Подпись и контакты модель иногда отдаёт позицией; без количества это не товар (ТЗ §12:
    # ПДн из подписи не должны попасть и в объект «Запрос»).
    kept = [p for p in kept if p.quantity_raw or not is_signature(lines, p.line)]
    ordered = sorted(kept, key=lambda p: p.line)
    positions = [build_position(i, p, lines) for i, p in enumerate(ordered, start=1)]
    requirements = [
        Requirement(line=r.line, source=lines[r.line - 1], text=r.text, mandatory=r.mandatory)
        for r in raw.requirements
        if 1 <= r.line <= len(lines)
    ]
    deadline = raw.deadline_raw if raw.deadline_raw and contains(text, raw.deadline_raw) else None
    covered = {p.line for p in positions} | {r.line for r in requirements}
    return ParsedRequest(
        kind=raw.kind,
        deadline_raw=deadline,
        requirements=requirements,
        positions=positions,
        possibly_missed=find_missed(lines, covered, deadline),
    )


async def parse_request(
    gateway: Gateway,
    text: str,
    *,
    deal_id: int | str | None = None,
    parallel: int = 3,
) -> ParsedRequest:
    lines = split_lines(text)
    if not lines:
        return ParsedRequest(
            kind="order", deadline_raw=None, requirements=[], positions=[], possibly_missed=[]
        )
    pos_prompt = load_prompt(*POSITIONS_PROMPT)
    meta_prompt = load_prompt(*META_PROMPT)

    async def parse_chunk(numbers: range) -> list[LLMPosition]:
        res = await gateway.call(
            prompt=pos_prompt,
            data=numbered(lines, numbers),
            schema=LLMPositions,
            deal_id=deal_id,
            # По размеру куска: так параллельные части не займут бюджет задачи впустую
            max_tokens=min(2048, CHUNK_BASE_TOKENS + CHUNK_LINE_TOKENS * len(numbers)),
            seed=0,
        )
        # Позиция со строкой из чужого куска — ошибка модели; строка не потеряется,
        # её покажет find_missed.
        return [p for p in res.value.positions if p.line in numbers]

    async def parse_meta() -> LLMMeta:
        res = await gateway.call(
            prompt=meta_prompt,
            data=numbered(lines, range(1, len(lines) + 1)),
            schema=LLMMeta,
            deal_id=deal_id,
            max_tokens=min(1024, META_BASE_TOKENS + META_LINE_TOKENS * len(lines)),
            seed=0,
        )
        return res.value

    chunks = chunk_ranges(len(lines), parallel)
    meta, parts = await asyncio.gather(
        parse_meta(), asyncio.gather(*(parse_chunk(c) for c in chunks))
    )
    raw = LLMRequest(
        kind=meta.kind,
        deadline_raw=meta.deadline_raw,
        requirements=meta.requirements,
        positions=[p for part in parts for p in part],
    )
    return postprocess(raw, text)
