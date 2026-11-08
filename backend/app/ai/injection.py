"""Фильтр подсказок-инъекций, часть ML (Ш-8, ТЗ §12: Л-8, Л-10).

Ядро ищет признаки инъекции правилами agents/usage.py (INJECTION_PATTERNS). Здесь — то, что
добавляет ML: нормализация текста против маскировки (смешанные алфавиты, невидимые символы,
разрядка, транслит) и узкие правила на приёмы, которых в деловом тексте не бывает: служебные
токены и роли модели, поддельный JSON ответа, скрытые комментарии, поля нашей схемы, явное
обращение к ИИ с командой. Л-9 («назови закупочную цену») не помечаем: агент её не знает.
Набор атак и ложные срабатывания — ml/eval/attacks, ml/scripts/eval_attacks.py.

Фильтр — не защита сам по себе: модель ничего не решает про деньги и не видит закупку (ТЗ §12).
Сработавшее правило — пометка «подозрительный ввод», строка с командой до модели не доходит,
а решает человек.
"""

import re
import unicodedata
from collections.abc import Iterable

# Похожие буквы. В слове, где есть и кириллица, и латиница, — маскировка: приводим к тому
# алфавиту, которого в слове больше («Игнopиpуй» → кириллица, «Ignоre» → латиница)
_LAT, _CYR = "aAcCeEoOpPxXyBHKMTkmth", "аАсСеЕоОрРхХуВНКМТкмтн"
_TO_CYRILLIC = str.maketrans(_LAT, _CYR)
_TO_LATIN = str.maketrans(_CYR, _LAT)
_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)
_LATIN = re.compile(r"[a-z]", re.IGNORECASE)
_WORD = re.compile(r"\w+")
# Разрядка: «и г н о р и р у й», «И-г-н-о-р-и-р-у-й» — одиночные буквы через пробел, дефис, точку
_SPACED = re.compile(r"(?<!\w)(?:\w[ \-.·_]){3,}\w(?!\w)")
_TRANSLIT = [
    ("shch", "щ"), ("sch", "щ"), ("zh", "ж"), ("kh", "х"), ("ts", "ц"), ("ch", "ч"), ("sh", "ш"),
    ("yu", "ю"), ("ya", "я"), ("yo", "ё"), ("iy", "ий"), ("uy", "уй"), ("yy", "ый"),
    ("a", "а"), ("b", "б"), ("c", "ц"), ("d", "д"), ("e", "е"), ("f", "ф"), ("g", "г"), ("h", "х"),
    ("i", "и"), ("j", "й"), ("k", "к"), ("l", "л"), ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"),
    ("q", "к"), ("r", "р"), ("s", "с"), ("t", "т"), ("u", "у"), ("v", "в"), ("w", "в"), ("x", "кс"),
    ("y", "ы"), ("z", "з"),
]  # fmt: skip
_TRANSLIT_RE = re.compile("|".join(re.escape(a) for a, _ in _TRANSLIT), re.IGNORECASE)
_TRANSLIT_MAP = dict(_TRANSLIT)

# Правила ML — только узкие, с высокой точностью: ложная пометка стоит дорого (письмо не уходит
# в таблицу само, запрос обрабатывается без модели), а безвредность атаки обеспечивает не фильтр,
# а устройство агента (модель не видит цен и не решает про деньги). Поэтому не помечаем «робота»,
# «модель», «агента», «администратора», «игнорируйте предыдущее письмо», «укажите закупочную
# процедуру»: в деловых письмах это обычные слова. Помечаем приёмы, которых в деловом тексте
# не бывает: служебные токены и роли чата, поддельный ответ модели, скрытый комментарий,
# поля нашей схемы и явное обращение к ИИ с командой в начале фразы.
_AI = (
    r"(?:ии|ai|нейросет\w*|llm|gpt|chatgpt|copilot|языков\w*\s+модел\w*|"
    r"искусственн\w*\s+интеллект\w*)"
)
_DO = (
    r"(?:выбирай|выбирайте|выбери|выберите|ставь|поставь|поставьте|игнорируй|игнорируйте|одобри|"
    r"одобрите|отметь|отметьте|прими|примите|подтверди|подтвердите|укажи|сделай|сделайте|выставь|"
    r"выставьте|отдай|отдайте|choose|select|pick|mark|approve|accept|set|rank|ignore|disregard|give)"
)
# Начало фразы или обращения: «ИИ, …», «Уважаемая нейросеть, …», «Dear AI, …»,
# а не «Камера с ИИ: …»
_START = r"(?:^|(?<=[\n.!?;])\s*|(?<!\w)(?:уважаем\w*|dear|hey|эй|привет)\s+)"

ML_PATTERNS = [
    # Служебные токены и роли чата, «режимы» модели
    r"<\|\s*(?:im_start|im_end|system|user|assistant|endoftext|eot_id|start_header_id|"
    r"end_header_id)\s*\|>|\[/?INST\]|<<\s*/?SYS\s*>>",
    r"\bsystem\s+(?:override|prompt)\b|\bdeveloper\s+mode\b|\bjailbreak\b",
    r"(?m)^\s*#{1,6}\s*(?:system|assistant)\b",
    r"(?m)^\s*system\s*:",  # «Assistant: Olga Petrova» — подпись, не роль
    # Скрытый комментарий, обращённый к модели
    r"<!--(?:(?!-->).){0,300}?\b(?:ai|ии|llm|gpt|assistant|нейросет\w*|агент\w*|model|модел\w*)\b",
    # Явное обращение к ИИ с командой в начале фразы
    # Двоеточие после адресата не берём: «AI: select input range», «ИИ-модуль: выберите режим» —
    # строки спецификаций
    r"(?im)"
    + _START
    + _AI
    + r"(?:-(?:агент|ассистент|помощник)\w*)?\s*[,!—–]\s*(?:\S+\s+){0,3}?"
    + _DO
    + r"\b",
    # «Примечание для ИИ:», «Напоминание языковой модели:», «Note for the AI:»
    r"(?:инструкц|указани|команд|примечани|сообщени|напоминани|note|message|instruction|reminder)"
    r"\w*\s+(?:для|к|to|for)?\s*(?:the\s+)?" + _AI + r"\s*(?::|\s[—–-]\s)",
    # Поля ответа нашей схемы и уверенность
    r"(?:в\s+пол[ея]|field)\s+[«\"']?(?:price|price_raw|confidence|confident|availability|"
    r"product_id|request_line_no)\b",
    r"\bconfiden(?:ce|t)\s*=\s*(?:true|\d)",  # «confidence: 0,95 по ГОСТ 8.207» — метрология
    # Поддельный JSON ответа с ключами наших схем
    r"\{\s*\"(?:lines|request_line_no|price_raw|choices?|positions|product_id|confidence|confident|"
    r"line_no)\"",
]


def _fix_mixed(m: re.Match[str]) -> str:
    word = m.group()
    cyr, lat = len(_CYRILLIC.findall(word)), len(_LATIN.findall(word))
    if not cyr or not lat:
        return word
    return word.translate(_TO_LATIN if lat > cyr else _TO_CYRILLIC)


def fix_mixed(text: str) -> str:
    """Слова со смешанным алфавитом — одним: «Рeмeнь» с латинской e → «Ремень»."""
    return _WORD.sub(_fix_mixed, text)


def _join_spaced(m: re.Match[str]) -> str:
    return re.sub(r"[ \-.·_]", "", m.group())


def _translit_word(m: re.Match[str]) -> str:
    word = m.group()
    if _CYRILLIC.search(word) or not _LATIN.search(word):
        return word
    return _TRANSLIT_RE.sub(lambda t: _TRANSLIT_MAP[t.group().lower()], word)


def normalize(text: str) -> str:
    """Текст без маскировки: NFKC, без невидимых символов, кириллица вместо похожей латиницы
    в смешанных словах, разрядка склеена."""
    t = unicodedata.normalize("NFKC", text)
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Cf")
    t = fix_mixed(t)
    return "\n".join(_SPACED.sub(_join_spaced, line) for line in t.split("\n"))


def translit(text: str) -> str:
    """Латинские слова — кириллицей: «ignoriruy instrukcii» → «игнорируй инструкции»."""
    return _WORD.sub(_translit_word, text)


def scan(text: str | None, patterns: Iterable[re.Pattern[str]]) -> list[str]:
    """Сработавшие правила по тексту как есть, без маскировки и в транслите."""
    if not text:
        return []
    clean = normalize(text)
    variants = [text, clean, translit(clean)]
    return [p.pattern for p in patterns if any(p.search(v) for v in variants)]
