"""Порт «страницы магазинов»: поиск товара и загрузка страницы со снимком (docs/ARCHITECTURE.md, 7)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class Shop:
    key: str
    name: str
    site: str
    region: str | None
    price_kind: str | None


@dataclass(frozen=True)
class Page:
    shop: Shop
    url: str
    html: bytes
    encoding: str
    fetched_at: datetime
    screenshot: bytes | None
    screenshot_at: datetime | None

    def text(self) -> str:
        return self.html.decode(self.encoding, errors="replace")


@dataclass(frozen=True)
class Hit:
    shop: Shop
    url: str
    title: str
    score: float


class WebPricePort(Protocol):
    def shops(self) -> list[Shop]: ...

    def search(self, query: str) -> list[Hit]:
        """Карточки товаров, подходящие запросу, — по всем магазинам."""
        ...

    def fetch(self, url: str) -> Page: ...
