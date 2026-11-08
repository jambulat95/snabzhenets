"""Канонические обозначения: одинаковый товар, записанный по-разному, даёт один ключ.

Это знание предметной области, а не модели:
- подшипники: ZZ = 2Z = 2ZR; 2RS = 2RS1 = 2RSH = 2RSR = DDU = 2РС = 2RZ; ГОСТ 180204 = 6204-2RS;
  «закрытый» без суффикса — любой из закрытых;
- ремни: сечения ГОСТ 0/А/Б/В = Z/A/B/C (кириллическая «В» — это C); буква в скобках главнее;
- манжеты: d×D×h, тип ГОСТ 1.1 = SC, 1.2 = TC (DIN 3760);
- крепёж: М12х50 = М12-6gх50;
- автоматы: 3п = 3P = 3Р; дифавтомат и выключатель нагрузки — другие товары.

Ключ запроса без уточнения («манжета 40х60») совпадает с любым уточнённым ключом товара.
"""

import re
from itertools import product
from typing import Any

_X = r"\s*[xх×*]\s*"
_SEAL_2Z = {"zz", "2z", "2zr", "z2"}
_SEAL_2RS = {"2rs", "2rs1", "2rsh", "2rsr", "ddu", "2рс", "2rsl", "llu", "2rz"}
_BEARING_RE = re.compile(r"(?<![\w.])(6[023]\d{2})(?:[\s-]*([a-zа-я0-9]{2,4}))?(?![\w])")
_GOST_BEARING_RE = re.compile(r"(?<![\w.\-/])(80|180)?([123])([0-2]\d)(?![\w.\-/])")
_BELT_LETTER = r"(spz|spa|spb|spc|z|a|b|c|0|а|б|в|с)"
_BELT_RE = re.compile(r"(?<![\w])" + _BELT_LETTER + r"(?:\s*\(\s*([a-zа-я])\s*\))?\s*-?\s*(\d{3,4})"
                      r"(?![\d])")  # fmt: skip
_BELT_REVERSED_RE = re.compile(r"(?<![\d])(\d{3,4})\s+(spz|spa|spb|spc)\b")
_BELT_SECTION = {"0": "Z", "z": "Z", "а": "A", "a": "A", "б": "B", "b": "B", "в": "C", "c": "C",
                 "с": "C", "spz": "SPZ", "spa": "SPA", "spb": "SPB", "spc": "SPC"}  # fmt: skip
_SEAL_DIM_RE = re.compile(r"(?<![\d.])(\d{2,3})" + _X + r"(\d{2,3})(?:" + _X + r"(\d{1,2}))?")
_SEAL_GOST_TYPE_RE = re.compile(
    r"(?<![\d.])([12]\.[12])-(\d{2,3})" + _X + r"(\d{2,3})(?:" + _X + r"(\d{1,2}))?"
)
_SEAL_DIN_TYPE_RE = re.compile(r"\b(tc|sc)\b")
_FASTENER_RE = re.compile(r"(?<![\w])[mм](\d{1,2})(?:-6g)?(?:" + _X + r"(\d{2,3}))?(?![\d])")
_BOLT_NO_M_RE = re.compile(r"болт\s+(\d{1,2})" + _X + r"(\d{2,3})(?![\d])")
_WASHER_RE = re.compile(r"шайба\s+(?:плоская\s+)?(\d{1,2})(?![\d])")
_BREAKER_POLES_RE = re.compile(r"(?<![\d])([1-4])\s*-?\s*(?:p|п|р|полюс)")
_BREAKER_AMPS_RE = re.compile(r"(?<![\d.,])(\d{1,3})\s*[aа](?![\wа-я])")

# Взаимоисключающие исполнения: если в запросе одно, а у товара другое — это другой товар.
MATERIAL_GROUPS = (
    {"stainless": r"\b(a2|a4|а2|а4|нерж\w*|aisi)\b", "zinc": r"\b(zn|оцинк\w*|цинк\w*)\b|\.016\b"},
    {"fkm": r"\b(fkm|фкм|viton|витон|fpm)\b", "nbr": r"\b(nbr|нбр|бутадиен\w*)\b"},
)


def _prep(text: str) -> str:
    t = text.casefold().replace("ё", "е").replace("–", "-").replace("—", "-")
    t = re.sub(r"sp[аa]", "spa", t)  # «SPА» с кириллической А
    t = re.sub(r"(?<=\d)\s+2\s+(rs|rz|z)\b", r" 2\1", t)  # «6004 2 RZ»
    return " ".join(t.split())


def _bearing(t: str) -> set[str]:
    out: set[str] = set()
    if "подшип" not in t and not re.search(r"\b(skf|fag|nsk|епк)\b", t):
        return out
    closed = bool(re.search(r"закрыт", t))
    for m in _BEARING_RE.finditer(t):
        code, suffix = m.group(1), (m.group(2) or "").replace("-", "")
        seal = "2Z" if suffix in _SEAL_2Z else "2RS" if suffix in _SEAL_2RS else None
        out.add(f"brg:{code}:{seal or ('sealed' if closed else 'open')}")
    for m in _GOST_BEARING_RE.finditer(t):
        prefix, series, code = m.groups()
        seal = {None: "open", "80": "2Z", "180": "2RS"}[prefix]
        if seal == "open" and closed:
            seal = "sealed"
        out.add(f"brg:{ {'1': '60', '2': '62', '3': '63'}[series] }{code}:{seal}")
    return out


def _belt(t: str) -> set[str]:
    if "ремен" not in t and "ремн" not in t:
        return set()
    out = set()
    for m in _BELT_RE.finditer(t):
        letter = m.group(2) if m.group(2) in _BELT_SECTION else m.group(1)
        out.add(f"belt:{_BELT_SECTION[letter]}:{m.group(3)}")
    out |= {f"belt:{_BELT_SECTION[m.group(2)]}:{m.group(1)}" for m in _BELT_REVERSED_RE.finditer(t)}
    return out


def seal_key(d: str, dd: str, h: str | None, kind: str | None) -> str:
    return f"seal:{d}x{dd}" + (f"x{h}" if h else "") + (f":{kind}" if kind else "")


def _seal(t: str) -> set[str]:
    if not re.search(r"манжет|сальник|уплотнение вала", t):
        return set()
    out = set()
    typed_spans = []
    for m in _SEAL_GOST_TYPE_RE.finditer(t):
        out.add(seal_key(m.group(2), m.group(3), m.group(4), m.group(1)))
        typed_spans.append(m.span(2))
    din = _SEAL_DIN_TYPE_RE.search(t)
    kind = ("1.2" if din.group(1) == "tc" else "1.1") if din else None
    for m in _SEAL_DIM_RE.finditer(t):
        if not any(a <= m.start() < b for a, b in typed_spans):
            out.add(seal_key(m.group(1), m.group(2), m.group(3), kind))
    return out


def _fastener(t: str) -> set[str]:
    kind = "bolt" if "болт" in t else "nut" if "гайк" in t else "washer" if "шайб" in t else None
    if kind is None:
        return set()
    if kind == "washer":
        sizes = [m.group(1) for m in _WASHER_RE.finditer(t)]
        sizes += [m.group(1) for m in re.finditer(r"(?<![\w.])(\d{1,2})\s+din\s*125", t)]
        sizes += [m.group(1) for m in re.finditer(r"(?<![\w.])(\d{1,2})\.01\.", t)]
        return {f"washer:M{s}" for s in sizes}
    out = set()
    for m in _FASTENER_RE.finditer(t):
        d, length = m.groups()
        out.add(f"bolt:M{d}x{length}" if kind == "bolt" and length else f"{kind}:M{d}")
    if kind == "bolt":
        out |= {f"bolt:M{m.group(1)}x{m.group(2)}" for m in _BOLT_NO_M_RE.finditer(t)}
    return out


def _breaker(t: str) -> set[str]:
    if not re.search(r"автомат|выключател|ва ?47", t):
        return set()
    if re.search(r"авдт|дифференц|узо|\bвд\d|нагрузки|\bвн-\d", t):
        kind = "rcd"  # дифавтомат, УЗО, выключатель нагрузки — не обычный автомат
    else:
        kind = "brk"
    poles = {m.group(1) for m in _BREAKER_POLES_RE.finditer(t)}
    amps = {m.group(1) for m in _BREAKER_AMPS_RE.finditer(t)}
    return {f"{kind}:{p}P:{a}" for p in poles for a in amps}


def designation_keys(text: str) -> set[str]:
    t = _prep(text)
    return _bearing(t) | _belt(t) | _seal(t) | _fastener(t) | _breaker(t)


def product_keys(p: dict[str, Any]) -> set[str]:
    """Ключи товара каталога: из текста и из атрибутов, со всеми обобщениями."""
    keys = designation_keys(f"{p['name']} {p['article']}")
    a = p.get("attrs") or {}
    if p.get("family") == "seal":
        keys.add(seal_key(a["d"], a["D"], a["h"], a["type"]))
    out = set()
    for k in keys:
        if k.startswith("seal:"):
            dims, _, kind = k[5:].partition(":")
            d, dd, *h = dims.split("x")
            for with_h, with_kind in product((True, False), (True, False)):
                out.add(seal_key(d, dd, h[0] if h and with_h else None,
                                 kind if kind and with_kind else None))  # fmt: skip
        elif k.startswith("brg:") and not k.endswith(":open"):
            out |= {k, k.rsplit(":", 1)[0] + ":sealed"}
        else:
            out.add(k)
    return out


def materials(text: str) -> dict[int, str]:
    """Исполнение по группам: {номер группы: значение}."""
    t = _prep(text)
    found = {}
    for gi, group in enumerate(MATERIAL_GROUPS):
        for value, pattern in group.items():
            if re.search(pattern, t):
                found[gi] = value
                break
    return found


def family(key: str) -> str:
    return key.split(":", 1)[0]
