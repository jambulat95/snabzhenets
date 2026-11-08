"""Нормализация обозначений для поиска по каталогу."""

import re

from ..parse.text import match_key

_SPLIT_RE = re.compile(r"[\s,;()«»\"']+")
_NON_ALNUM_RE = re.compile(r"[^0-9a-zа-я]+")
_DIGIT_RE = re.compile(r"\d")
# Подшипник по ГОСТ: [80|180]<серия 1/2/3><код 00–24> → ISO 60xx/62xx/63xx + исполнение.
_GOST_BEARING_RE = re.compile(r"^(80|180)?([123])(\d\d)$")
_GOST_SERIES = {"1": "60", "2": "62", "3": "63"}
_GOST_SEAL = {None: "", "80": "2z", "180": "2rs"}


def compact(text: str) -> str:
    """«6204-2RS», «6204 2РС», «6204.2rs» → один ключ без разделителей."""
    return _NON_ALNUM_RE.sub("", match_key(text))


def tokens(text: str) -> list[str]:
    return [t for t in _SPLIT_RE.split(match_key(text)) if t]


def digit_tokens(text: str) -> list[str]:
    """Токены с цифрами в компактном виде: размеры, типоразмеры, артикулы."""
    return [c for t in tokens(text) if _DIGIT_RE.search(t) and len(c := compact(t)) >= 2]


def article_candidates(text: str, max_join: int = 3) -> set[str]:
    """Ключи, которыми может быть записан артикул: отдельные токены и склейки соседних.

    «Подшипник 6204 2RS» даёт и «6204», и «62042rs» (= compact("6204-2RS")).
    """
    toks = tokens(text)
    out = set()
    for i in range(len(toks)):
        for j in range(i + 1, min(i + max_join, len(toks)) + 1):
            key = compact("".join(toks[i:j]))
            if _DIGIT_RE.search(key) and len(key) >= 3:
                out.add(key)
    return out


def gost_bearing_to_iso(token: str) -> str | None:
    """«180204» → compact(«6204-2RS»), «80305» → compact(«6305-2Z»). Иначе None."""
    m = _GOST_BEARING_RE.match(compact(token))
    if not m:
        return None
    prefix, series, code = m.groups()
    return compact(f"{_GOST_SERIES[series]}{code}{_GOST_SEAL[prefix]}")
