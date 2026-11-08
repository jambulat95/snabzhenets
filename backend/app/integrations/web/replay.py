"""Записанные страницы магазинов (data/replay/shops, scripts/record_shops.py + snapshot_shops.py).

Поиск по записанным карточкам — по совпадению слов запроса с названием товара на странице:
так ведёт себя поиск магазина на этих трёх товарах. Живой поиск — в live.py (пилот).
"""

import json
import re
from datetime import datetime
from functools import cached_property
from pathlib import Path
from typing import Any

from ...config import settings
from ...quotes.extract import extract_offer
from .port import Hit, Page, Shop

_WORD = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
STOP = {"для", "и", "в", "на", "с", "по", "шт", "уп", "г", "м2", "м", "the"}


def words(text: str) -> set[str]:
    return {w.casefold()[:6] for w in _WORD.findall(text) if w.casefold() not in STOP and len(w) > 1}


class ReplayWebPrices:
    def __init__(self, base: Path | None = None) -> None:
        self.base = (base or Path(settings.replay_dir)) / "shops"

    @cached_property
    def _shops(self) -> dict[str, Shop]:
        raw: dict[str, Any] = json.loads((self.base / "shops.json").read_text("utf-8"))
        return {k: Shop(key=k, name=v["name"], site=v["site"], region=v.get("region"), price_kind=v.get("price_kind"))
                for k, v in raw.items() if not k.startswith("_")}

    @cached_property
    def _rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = json.loads((self.base / "manifest.json").read_text("utf-8"))
        return [r for r in rows if r["item"] != "robots" and r["status"] == 200 and not r["blocked"]]

    def shops(self) -> list[Shop]:
        return list(self._shops.values())

    def fetch(self, url: str) -> Page:
        row = next((r for r in self._rows if r["url"] == url), None)
        if row is None:
            raise KeyError(f"Страница не записана: {url}")
        shot = row.get("screenshot")
        return Page(
            shop=self._shops[row["shop"]], url=row["url"], html=(self.base.parent / row["file"]).read_bytes(),
            encoding=row["encoding"], fetched_at=datetime.fromisoformat(row["fetched_at"]),
            screenshot=(self.base.parent / shot["file"]).read_bytes() if shot else None,
            screenshot_at=datetime.fromisoformat(shot["taken_at"]) if shot else None,
        )

    @cached_property
    def _titles(self) -> dict[str, str]:
        out = {}
        for r in self._rows:
            offer = extract_offer(self.fetch(r["url"]).text())
            out[r["url"]] = offer.name if offer and offer.name else ""
        return out

    def search(self, query: str) -> list[Hit]:
        q = words(query)
        hits = []
        for r in self._rows:
            title = self._titles[r["url"]]
            common = q & words(title)
            if common:
                hits.append(Hit(shop=self._shops[r["shop"]], url=r["url"], title=title, score=len(common) / len(q)))
        hits.sort(key=lambda h: -h.score)
        return hits
