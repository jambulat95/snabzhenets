"""Цена со страницы магазина — только кодом, из машиночитаемой разметки (CLAUDE.md, 1.1–1.2).

Порядок: JSON-LD schema.org Product/Offer → microdata itemprop="price". Число дополнительно ищется
в видимом тексте страницы: если его там нет, цена помечается (страница могла отдать разметку от другого
товара или региона). Модель цену не читает.
"""

import html as htmllib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

_JSONLD = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)


@dataclass
class Offer:
    price: Decimal
    currency: str | None
    name: str | None
    availability: str | None
    how: str  # json-ld / microdata
    description: str | None = None
    notes: list[str] = field(default_factory=list)


def _dec(v: Any) -> Decimal | None:
    try:
        d = Decimal(str(v).replace(" ", "").replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return d if d > 0 else None


def _walk(node: Any) -> list[dict[str, Any]]:
    if isinstance(node, list):
        return [x for n in node for x in _walk(n)]
    if isinstance(node, dict):
        found = [node] if "Product" in str(node.get("@type", "")) else []
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                found += _walk(node[key])
        return found
    return []


def _from_jsonld(page: str) -> Offer | None:
    for block in _JSONLD.findall(page):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for prod in _walk(data):
            offers = prod.get("offers")
            offer = offers[0] if isinstance(offers, list) and offers else offers
            if not isinstance(offer, dict):
                continue
            price = _dec(offer.get("price") or offer.get("lowPrice"))
            if price is None:
                continue
            avail = str(offer.get("availability") or "").rsplit("/", 1)[-1] or None
            return Offer(price=price, currency=offer.get("priceCurrency"), name=prod.get("name"),
                         availability=avail, how="json-ld", description=prod.get("description"))
    return None


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'{name}="([^"]*)"', tag)
    return htmllib.unescape(m.group(1)) if m else None


def _from_microdata(page: str) -> Offer | None:
    tags = re.findall(r"<[^>]*itemprop=\"(?:price|priceCurrency|availability|name)\"[^>]*>", page)
    price = next((_dec(_attr(t, "content")) for t in tags if 'itemprop="price"' in t and _attr(t, "content")), None)
    if price is None:
        return None
    cur = next((_attr(t, "content") for t in tags if 'itemprop="priceCurrency"' in t), None)
    avail = next((_attr(t, "href") or _attr(t, "content") for t in tags if 'itemprop="availability"' in t), None)
    h1 = _H1.search(page)
    name = htmllib.unescape(_TAG.sub("", h1.group(1))).strip() if h1 else None
    return Offer(price=price, currency=cur, name=name, availability=(avail or "").rsplit("/", 1)[-1] or None,
                 how="microdata")


def visible_text(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    return re.sub(r"\s+", " ", htmllib.unescape(_TAG.sub(" ", page)))


def price_in_text(price: Decimal, text: str) -> bool:
    """«33 670», «33670», «33 670,00» — в любом из видов, как пишут магазины. Число — целиком:
    цена 670 не «находится» внутри «33 670» (разряды через пробел или неразрывный пробел)."""
    whole = int(price)
    norm = re.sub("[\u00a0\u202f]", " ", text)
    grouped = f"{whole:,}".replace(",", " ")
    return any(
        re.search(rf"(?<!\d)(?<!\d ){re.escape(v)}(?!\d)(?! \d{{3}})", norm) for v in {str(whole), grouped}
    )


def extract_offer(page: str) -> Offer | None:
    offer = _from_jsonld(page) or _from_microdata(page)
    if offer is None:
        return None
    if offer.currency not in (None, "RUB", "RUR"):
        offer.notes.append(f"Валюта {offer.currency} — не рубли")
    if not price_in_text(offer.price, visible_text(page)):
        offer.notes.append("Цены из разметки нет в тексте страницы")
    return offer
