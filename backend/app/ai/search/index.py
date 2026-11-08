"""Подбор позиции запроса по каталогу поставщика (раздел 6 ТЗ, «Подбор по каталогу»).

Кандидатов дают три источника: артикул (точно и по префиксу, с переводом
обозначений подшипников ГОСТ → ISO), триграммы наименования и BGE-M3.
Затем код пересчитывает оценку и штрафует кандидатов, в которых нет чисел
из запроса: «6205» не должен уступить место «6204» из-за похожего текста.

Это прототип в памяти: каталог ~1–2 тыс. позиций. Для бэкенда то же самое
ложится на pg_trgm + pgvector.
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..parse.text import match_key
from .designations import designation_keys, materials, product_keys
from .embed import Embedder
from .normalize import article_candidates, compact, digit_tokens, gost_bearing_to_iso

POOL = 30
W_DENSE, W_TRGM, W_ARTICLE = 0.45, 0.35, 0.20


@dataclass(frozen=True)
class Candidate:
    sku: str
    name: str
    article: str
    analog_key: str
    confidence: float
    signals: dict[str, Any] = field(default_factory=dict)


def trigrams(text: str) -> set[str]:
    out: set[str] = set()
    for word in match_key(text).split():
        w = f"  {word} "
        out.update(w[i : i + 3] for i in range(len(w) - 2))
    return out


_LETTER_RE = re.compile(r"[^\W\d_]")
CODE_HIT = 0.85


class CatalogIndex:
    def __init__(self, products: list[dict[str, Any]], embedder: Embedder) -> None:
        self.products = products
        self.embedder = embedder
        self._by_article: dict[str, list[int]] = defaultdict(list)
        # Коды поставщика (sku): строку «PS-10001 — 5 шт» находим по коду. Отдельно от артикулов:
        # числовой код из 1С («6205», «1000») совпал бы с обозначением или количеством в запросе
        self._by_code: dict[str, list[int]] = defaultdict(list)
        for i, p in enumerate(products):
            self._by_article[compact(p["article"])].append(i)
            for code in p.get("aliases", ()):
                self._by_code[compact(code)].append(i)
        texts = [f"{p['name']} {p['article']}" for p in products]
        self._trgm = [trigrams(t) for t in texts]
        self._compact = [compact(t) for t in texts]
        self._vectors = embedder.encode([p["name"] for p in products])
        self._design = [product_keys(p) for p in products]
        self._materials = [materials(t) for t in texts]
        self._by_design: dict[str, list[int]] = defaultdict(list)
        for i, keys in enumerate(self._design):
            for key in keys:
                self._by_design[key].append(i)

    def _article_hits(self, keys: set[str], whole: str = "") -> dict[int, float]:
        hits: dict[int, float] = {}
        for key in keys:
            for i in self._by_article.get(key, []):
                hits[i] = 1.0
            # Код с буквами («PS-00300») или запрос — ровно код: точно; чисто цифровой код в
            # тексте строки — только подсказка, не «уверенное» совпадение
            exact = bool(_LETTER_RE.search(key)) or key == whole
            for i in self._by_code.get(key, []):
                hits[i] = max(hits.get(i, 0.0), CODE_HIT if exact else 0.5)
        # Префикс: «6204-2RS» в запросе, «6204-2RSH» в каталоге.
        for art, idx in self._by_article.items():
            for key in keys:
                if len(key) >= 4 and art != key and 0 < len(art) - len(key) <= 3:
                    if art.startswith(key):
                        for i in idx:
                            hits.setdefault(i, 0.7)
        return hits

    def search(self, name: str, article: str | None = None, k: int = 3) -> list[Candidate]:
        query = f"{name} {article or ''}".strip()
        keys = article_candidates(query)
        nums = digit_tokens(query)
        gost = {t: iso for t in nums if (iso := gost_bearing_to_iso(t))}
        keys |= set(gost.values())
        art = self._article_hits(keys, compact(query))

        q_trgm = trigrams(query)
        trgm = np.array([len(q_trgm & t) / (len(q_trgm) or 1) for t in self._trgm])
        cos = self._vectors @ self.embedder.encode([query])[0]

        q_design = designation_keys(query)
        q_materials = materials(query)
        design_hits = {i for k in q_design for i in self._by_design.get(k, [])}

        pool = set(art) | design_hits
        pool |= set(np.argsort(-trgm)[:POOL]) | set(np.argsort(-cos)[:POOL])
        scored = []
        for i in pool:
            doc = self._compact[i]
            covered = [t for t in nums if t in doc or (t in gost and gost[t] in doc)]
            num_cover = len(covered) / len(nums) if nums else 1.0
            dense = float(np.clip((cos[i] - 0.4) / 0.5, 0, 1))
            base = W_DENSE * dense + W_TRGM * float(trgm[i]) + W_ARTICLE * art.get(i, 0.0)
            if art.get(i) == 1.0:
                base = max(base, 0.9)  # точное совпадение артикула
                num_cover = 1.0  # цифры запроса — это и есть артикул
            elif art.get(i) == CODE_HIT:
                # Код поставщика: уверенно, но ниже совпавшего обозначения — «A1250» в запросе
                # скорее ремень A-1250, чем товар, у которого такой код в 1С
                base = max(base, CODE_HIT)
                num_cover = 1.0
            # Обозначение совпало (с учётом ГОСТ↔ISO, ZZ=2Z и т.п.) — сильнейший сигнал;
            # у обоих есть обозначения, но разные (6205 против 6204, 2RS против открытого,
            # дифавтомат против автомата) — штраф.
            design_match = i in design_hits
            design_conflict = bool(q_design) and bool(self._design[i]) and not design_match
            if design_match:
                base = max(base, 0.92)
                num_cover = 1.0
            elif design_conflict:
                base *= 0.35
            # Другое исполнение: нержавейка против цинка, FKM против NBR.
            material_conflict = [g for g, v in q_materials.items()
                                 if self._materials[i].get(g, v) != v]  # fmt: skip
            if material_conflict:
                base *= 0.5
            conf = base * (0.25 + 0.75 * num_cover)
            signals = {
                "article": art.get(i, 0.0), "trgm": round(float(trgm[i]), 3),
                "cos": round(float(cos[i]), 3), "num_cover": round(num_cover, 2),
                "gost_to_iso": any(t in gost and gost[t] in doc and t not in doc for t in nums),
                "design": "match" if design_match else "conflict" if design_conflict else None,
                "material_conflict": bool(material_conflict),
            }  # fmt: skip
            scored.append((conf, i, signals))
        scored.sort(key=lambda x: -x[0])
        return [
            Candidate(
                sku=self.products[i]["sku"],
                name=self.products[i]["name"],
                article=self.products[i]["article"],
                analog_key=self.products[i]["analog_key"],
                confidence=round(conf, 3),
                signals=sig,
            )  # fmt: skip
            for conf, i, sig in scored[:k]
        ]
