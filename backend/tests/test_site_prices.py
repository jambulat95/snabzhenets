import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.integrations.web.replay import ReplayWebPrices
from app.quotes.extract import extract_offer, price_in_text
from app.quotes.web_prices import PageMatch, verdict

REPLAY = Path(__file__).resolve().parents[2] / "data" / "replay"
MANIFEST = json.loads((REPLAY / "shops" / "manifest.json").read_text("utf-8"))
PAGES = [r for r in MANIFEST if r["item"] != "robots"]


@pytest.mark.parametrize("row", PAGES, ids=lambda r: f"{r['shop']}-{r['item']}")
def test_recorded_pages_give_price_from_markup(row: dict) -> None:
    html = (REPLAY / row["file"]).read_bytes().decode(row["encoding"], errors="replace")
    offer = extract_offer(html)
    assert offer is not None
    assert offer.price == Decimal(row["markup_price"])
    assert offer.currency in ("RUB", "RUR")
    assert offer.notes == []  # цена из разметки есть и в видимом тексте


def test_jsonld_graph_and_list_offers() -> None:
    page = """<script type="application/ld+json">{"@graph": [{"@type": "Product", "name": "Бумага",
      "offers": [{"@type": "Offer", "price": "499.90", "priceCurrency": "RUB"}]}]}</script><p>499,90 ₽</p>"""
    offer = extract_offer(page)
    assert offer is not None and offer.price == Decimal("499.90") and offer.how == "json-ld"


def test_microdata_and_h1_name() -> None:
    page = '<h1>Картридж HP 59A</h1><meta itemprop="price" content="13532"><span>13 532 руб.</span>'
    offer = extract_offer(page)
    assert offer is not None and offer.price == Decimal("13532") and offer.name == "Картридж HP 59A"


def test_price_missing_from_text_is_flagged() -> None:
    page = '<script type="application/ld+json">{"@type":"Product","offers":{"price":"100"}}</script><p>Цена 900</p>'
    offer = extract_offer(page)
    assert offer is not None and offer.notes == ["Цены из разметки нет в тексте страницы"]


def test_no_markup_no_price() -> None:
    assert extract_offer("<p>Цена 33 670 ₽</p>") is None  # из текста цену не берём — только разметка


def test_price_in_text_formats() -> None:
    assert price_in_text(Decimal("33670"), "Цена: 33 670 ₽")
    assert price_in_text(Decimal("33670.00"), "33670 руб")
    assert not price_in_text(Decimal("670"), "33 670 ₽ 1670")


def test_replay_search_finds_right_cards() -> None:
    web = ReplayWebPrices(REPLAY)
    projector = web.search("Проектор для аудитории")
    assert projector and all("Проектор" in h.title for h in projector)
    paper = web.search("Бумага А4 80 г/м2")
    assert paper and all("Бумага" in h.title for h in paper)
    assert {h.shop.region for h in paper} == {"Москва", "Махачкала"}


def m(matches: bool, confidence: str) -> PageMatch:
    return PageMatch(matches=matches, confidence=confidence, differences=[], reason="")  # type: ignore[arg-type]


def test_verdict_leaves_doubt_to_human() -> None:
    assert verdict(m(True, "high"), []) == "ok"
    assert verdict(m(True, "medium"), []) == "review"
    assert verdict(m(False, "high"), []) == "rejected"
    assert verdict(None, []) == "review"
    assert verdict(m(True, "high"), ["Цены из разметки нет в тексте страницы"]) == "review"
