"""Обезличивание персональных данных до вызова модели (ТЗ §12).

Модели не нужны ни телефон, ни почта, ни ФИО, ни реквизиты: позиции, количества и условия
разбираются без них. Поэтому ПДн заменяются метками ещё в шлюзе — для любой модели,
локальной и облачной. Число строк не меняется: разбор сверяет количество с исходной строкой
по её номеру.

Артикулы и коды товаров («30784809», «ВТМ00052310», «89123456789» без «+7» и без «тел.»)
не трогаем: число считается телефоном только по формату с «+7», скобками или разделителями,
либо по слову рядом («тел.», «моб.»).
"""

import re
from collections import Counter
from dataclasses import dataclass, field

_PHONE_BODY = r"\(?\d{3,4}\)?[\s\-]*\d{2,3}[\s\-]*\d{2}[\s\-]*\d{2}"
# +7 900 123-45-67 и +79001234567; 8 (495) 123-45-67; 8 900 123 45 67
_PHONE_RE = re.compile(
    rf"(?:\+7[\s\-]*{_PHONE_BODY})"
    rf"|(?<![\w\-])8[\s\-]*\(\d{{3,4}}\)[\s\-]*\d{{2,3}}[\s\-]*\d{{2}}[\s\-]*\d{{2}}"
    rf"|(?<![\w\-])8[\s\-]\d{{3}}[\s\-]\d{{3}}[\s\-]\d{{2}}[\s\-]\d{{2}}(?![\w\-])"
)
# Голые цифры — телефон, только если рядом сказано, что это телефон.
_PHONE_BY_WORD_RE = re.compile(
    r"((?<!\w)(?:тел|телефон|моб|мобильный|т\.|phone|tel)\.?\s*[:№]?\s*)(\+?\d[\d\s\-()]{9,16}\d)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_REQUISITES_RE = re.compile(
    r"((?:ИНН(?:/КПП)?|КПП|ОГРНИП|ОГРН|СНИЛС|БИК|р/с|р/сч|к/с|к/сч|расч[её]тный\s+сч[её]т|"
    r"корр?\.?\s*сч[её]т|паспорт(?:\s+серии)?)\.?\s*[:№]?\s*)(\d[\d\s\-/]{7,30}\d)",
    re.IGNORECASE,
)
_NAME = r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?"
_INITIALS = r"[А-ЯЁ]\.[ \t]?[А-ЯЁ]\.?"
_PERSON = rf"{_NAME}(?:[ \t]+{_NAME}){{0,2}}(?:[ \t]+{_INITIALS})?|{_INITIALS}[ \t]?{_NAME}"
_SIGN_WORDS = (
    r"с\s+уважением|контактное\s+лицо|исполнитель|ответственный|менеджер|инженер|снабженец|"
    r"специалист|руководитель|директор|подпись|контакт"
)
# ФИО после слов подписи и контакта в той же строке: «С уважением, Иванов Пётр»,
# «Контактное лицо: Петров И.И.». Слово — целиком («Контактор» — не «контакт»), без учёта
# регистра; имя — только с заглавной: «отдела снабжения» не ФИО.
_SIGNED_NAME_RE = re.compile(
    rf"((?i:{_SIGN_WORDS})(?![А-Яа-яЁё])[^\n:]{{0,30}}?[,:—\-]?[ \t]*)({_PERSON})"
)
# «С уважением,» и имя на следующей строке — только если имя занимает строку или стоит перед
# запятой: «С уважением, отдел снабжения.\nПросим…» — не подпись.
_REGARDS_NEXT_LINE_RE = re.compile(
    rf"((?i:с\s+уважением)[,.!]?[ \t]*\n[ \t]*)({_PERSON})(?=[ \t]*(?:,|$))", re.MULTILINE
)
# ФИО полностью с отчеством где угодно: «Иванов Пётр Сергеевич»
_FULL_NAME_RE = re.compile(rf"\b{_NAME}[ \t]+{_NAME}[ \t]+[А-ЯЁ][а-яё]+(?:вич|вна|ична|ич)\b")
# «Иванов И.И.», «И.И. Иванов»
_SHORT_NAME_RE = re.compile(rf"\b{_NAME}[ \t]+{_INITIALS}|{_INITIALS}[ \t]?{_NAME}\b")


@dataclass(frozen=True)
class Masked:
    text: str
    found: Counter[str] = field(default_factory=Counter)


def anonymize(text: str) -> Masked:
    found: Counter[str] = Counter()

    def sub(pattern: re.Pattern[str], label: str, s: str, keep_prefix: bool = False) -> str:
        def repl(m: re.Match[str]) -> str:
            found[label] += 1
            return (m.group(1) if keep_prefix else "") + f"[{label}]"

        return pattern.sub(repl, s)

    out = sub(_EMAIL_RE, "email", text)
    out = sub(_REQUISITES_RE, "реквизит", out, keep_prefix=True)
    out = sub(_PHONE_BY_WORD_RE, "телефон", out, keep_prefix=True)
    out = sub(_PHONE_RE, "телефон", out)
    out = sub(_SIGNED_NAME_RE, "ФИО", out, keep_prefix=True)
    out = sub(_REGARDS_NEXT_LINE_RE, "ФИО", out, keep_prefix=True)
    out = sub(_FULL_NAME_RE, "ФИО", out)
    out = sub(_SHORT_NAME_RE, "ФИО", out)
    return Masked(out, found)
