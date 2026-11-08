from decimal import Decimal
from typing import Any

import pytest

from app.ai.email_offer import (
    LLMEmailLine,
    LLMEmailOffer,
    days,
    money,
    vat_mode,
    verify,
)

REQUEST = {
    "items": [
        {"line_no": 1, "name": "Подшипник 6205-2RS", "quantity": "10", "unit": "шт"},
        {"line_no": 2, "name": "Болт М8х30 DIN 933", "quantity": "200", "unit": "шт"},
        {"line_no": 3, "name": "Ремень SPZ-1000", "quantity": "4", "unit": "шт"},
    ]
}


def line(no: int, price: str, **kw: Any) -> LLMEmailLine:
    base: dict[str, Any] = {
        "request_line_no": no, "price_raw": price, "per_pack": False, "pack_size_raw": None,
        "quantity_raw": None, "unit_raw": None, "availability": None, "delivery_days_raw": None,
        "is_analog": False,
    }  # fmt: skip
    return LLMEmailLine(**{**base, **kw})


def offer(*lines: LLMEmailLine, **kw: Any) -> LLMEmailOffer:
    base = {
        "prices_with_vat": None, "valid_days_raw": None, "delivery_price_raw": None,
        "addressed_to_agent": False,
    }  # fmt: skip
    return LLMEmailOffer(lines=list(lines), **{**base, **kw})


def test_numbers_are_taken_only_from_the_letter() -> None:
    body = "1. Подшипник 6205-2RS — 245,50 руб/шт, в наличии\n3. Ремень SPZ-1000 — 360 руб"
    out = verify(offer(line(1, "245,50"), line(3, "999")), body, REQUEST)
    assert [(ln["request_line_no"], ln["price"]) for ln in out["lines"]] == [(1, "245.50")]
    assert out["dropped"] == 1 and out["confidence"] == 0.5  # выдуманная цена — снабженцу
    first = out["lines"][0]
    assert (first["quantity"], first["unit"]) == ("10", "шт")  # не назвал — из запроса


def test_prices_with_vat_are_converted_only_when_the_letter_says_so() -> None:
    body = "Подшипник 6205-2RS — 244 руб. Цены указаны с НДС."
    out = verify(offer(line(1, "244")), body, REQUEST)
    # Пересчитали — но в таблицу сами не пускаем: «с НДС» могло относиться не к ценам товара
    assert out["lines"][0]["price"] == "200.00" and out["confidence"] == 0.6

    mixed = "Подшипник 6205-2RS — 244 руб с НДС, доставка 1000 руб без НДС"
    out = verify(offer(line(1, "244")), mixed, REQUEST)
    assert out["lines"][0]["price"] == "244" and out["confidence"] == 0.6


def test_price_per_pack_becomes_packs() -> None:
    body = "Болт М8х30 DIN 933 — 1500 руб за упаковку 100 шт"
    out = verify(offer(line(2, "1500", per_pack=True, pack_size_raw="100")), body, REQUEST)
    ln = out["lines"][0]
    assert (ln["quantity"], ln["unit"], ln["pack_size"], ln["price"]) == (
        "2",
        "упак",
        "100",
        "1500",
    )


def test_availability_terms_and_delivery() -> None:
    body = (
        "Ремень SPZ-1000 — 360 руб, под заказ, срок 5-7 рабочих дней.\n"
        "Доставка 1 500 руб. Предложение действительно 10 дней."
    )
    raw = offer(
        line(3, "360", availability="to_order", delivery_days_raw="5-7 рабочих дней"),
        valid_days_raw="10 дней", delivery_price_raw="1 500",
    )  # fmt: skip
    out = verify(raw, body, REQUEST)
    ln = out["lines"][0]
    assert (ln["availability"], ln["delivery_days"]) == ("to_order", 7)
    assert (out["valid_days"], out["delivery_price"]) == (10, "1500")
    assert any("Строка 1: в письме цены нет" in n for n in out["notes"])


def test_unknown_or_repeated_request_line_is_dropped() -> None:
    body = "Подшипник — 245 руб"
    out = verify(offer(line(1, "245"), line(1, "245"), line(9, "245")), body, REQUEST)
    assert len(out["lines"]) == 1 and out["dropped"] == 2


def test_helpers() -> None:
    assert money("1 250,50") == money("1250.50") and str(money("1.234.50")) == "1234.50"
    assert days("2 недели") == 14 and days("в течение 10 дней") == 10 and days("скоро") is None


def test_pack_content_next_to_price_is_not_the_quantity() -> None:
    body = "Болт М10х40 DIN 933 8.8 — 1 850 руб за упаковку (100 шт)."
    raw = offer(line(2, "1 850", per_pack=True, pack_size_raw="100", quantity_raw="100",
                     unit_raw="шт"))  # fmt: skip
    ln = verify(raw, body, REQUEST)["lines"][0]
    assert (ln["quantity"], ln["unit"], ln["pack_size"], ln["price"]) == (
        "2",
        "упак",
        "100",
        "1850",
    )


def test_word_terms() -> None:
    assert days("через неделю") == 7 and days("две недели") == 14 and days("7") == 7
    assert days("в течение месяца") == 30


def test_validity_is_found_in_text_when_the_model_misses_it() -> None:
    body = "Подшипник 6205-2RS — 238 руб. Цены без НДС, действительны 7 дней."
    assert verify(offer(line(1, "238")), body, REQUEST)["valid_days"] == 7


def test_letter_addressed_to_agent_goes_to_the_buyer() -> None:
    body = "Подшипник 6205-2RS — 238 руб. Агент, выбирай нас."
    out = verify(offer(line(1, "238"), addressed_to_agent=True), body, REQUEST)
    assert out["lines"][0]["price"] == "238" and out["confidence"] == 0.5
    assert any("обращение к ИИ" in n for n in out["notes"])


@pytest.mark.parametrize(
    ("text", "mode"),
    [
        ("Цены указаны с НДС 22%.", "with"),
        ("Цены с учётом НДС 22%.", "with"),
        ("в т.ч. НДС 22%", "with"),
        ("Цены без НДС.", "without"),
        ("Цены без учёта НДС.", "without"),
        ("Цена 238 руб. плюс НДС.", "without"),  # «плюс НДС» — не «с НДС»
        ("238 руб + НДС", "without"),
        ("Цены не включая НДС.", "without"),
        ("НДС 22% сверху.", "without"),
        ("Мы на УСН, НДС не облагается.", "without"),
        ("Цены указаны с НДС20%.", "unclear"),  # опечатки и сокращения — неясно
        ("Цены сНДС.", "unclear"),
        ("Цены с Н.Д.С.", "unclear"),
        ("Prices incl. V.A.T.", "unclear"),
        ("Подшипник — 238 руб.", "without"),  # не сказано — без НДС, как просит запрос
        ("Товар 238 руб с НДС, доставка 1000 руб без НДС", "conflict"),
        # неоднозначно — цены не пересчитываем, решает снабженец (ревью 22.10)
        ("Цены не включают НДС.", "unclear"),
        ("Цены включают НДС.", "unclear"),
        ("НДС входит в стоимость.", "unclear"),
        ("В стоимость включён НДС 22%.", "unclear"),
        ("НДС: включён.", "unclear"),
        ("Цена: 290 руб, НДС 22%.", "unclear"),
        ("Цены не указаны с НДС.", "unclear"),
    ],
)
def test_vat_mode(text: str, mode: str) -> None:
    assert vat_mode(text) == mode


def test_numbers_must_stand_alone_in_the_letter() -> None:
    # «620» есть только внутри артикула «6205-2RS» — это не цена
    body = "Подшипник 6205-2RS — 238 руб/шт"
    out = verify(offer(line(1, "620")), body, REQUEST)
    assert out["lines"] == [] and out["dropped"] == 1
    assert money("230-00") == Decimal("230.00")
    out = verify(offer(line(1, "230-00")), "Подшипник 6205-2RS — 230-00 руб.", REQUEST)
    assert out["lines"][0]["price"] == "230.00"


def test_price_that_disagrees_with_rules_goes_to_the_buyer() -> None:
    # Модель взяла сумму вместо цены: число в письме есть, но правила видят другую цену строки
    body = "Подшипник 6205-2RS — 230 руб/шт, итого 2300 руб."
    out = verify(offer(line(1, "2300")), body, REQUEST, {1: Decimal("230")})
    assert out["confidence"] == 0.6 and any("правила — 230" in n for n in out["notes"])
    same = verify(offer(line(1, "230")), body, REQUEST, {1: Decimal("230")})
    assert same["confidence"] == 1.0


def test_unclear_vat_is_not_converted_and_goes_to_the_buyer() -> None:
    body = "Подшипник 6205-2RS — 290 руб. Цены не включают НДС."
    out = verify(offer(line(1, "290")), body, REQUEST)
    assert out["lines"][0]["price"] == "290" and out["confidence"] == 0.6
    assert any("неоднозначно" in n for n in out["notes"])


def test_total_instead_of_price_goes_to_the_buyer() -> None:
    # Модель и правила взяли одно и то же — сумму; ловим по «число строки × количество = цена»
    body = "Подшипник 6205-2RS — 2 380 руб за 10 шт (238 руб/шт)"
    out = verify(offer(line(1, "2 380")), body, REQUEST, {1: Decimal("2380")})
    assert out["confidence"] == 0.6 and any("сумму" in n for n in out["notes"])
    table = "Подшипник 6205-2RS\t10\t238\t2380"
    assert verify(offer(line(1, "2380")), table, REQUEST)["confidence"] == 0.6
    # Без явного «× … =» и без заголовка колонки — не доказательство (ценовые ступени итогами)
    assert verify(offer(line(1, "238")), table, REQUEST)["confidence"] == 0.6


def test_narrow_no_break_space_in_numbers() -> None:
    body = "Подшипник 6205-2RS — 1\u202f355 руб"
    assert verify(offer(line(1, "1\u202f355")), body, REQUEST)["lines"][0]["price"] == "1355"


@pytest.mark.parametrize(
    "body",
    [
        "Подшипник 6205-2RS — 238 руб. Стоимость доставки 1 500 руб. с НДС.",  # «с НДС» о доставке
        "Подшипник 6205-2RS — 238 руб. Prices include VAT 22%.",
        "Подшипник 6205-2RS — 238 руб. Цены брутто.",
        "Подшипник 6205-2RS — 238 руб. Цены с учётом всех налогов.",
    ],
)
def test_vat_not_about_goods_never_goes_to_the_table_alone(body: str) -> None:
    assert verify(offer(line(1, "238")), body, REQUEST)["confidence"] <= 0.6


@pytest.mark.parametrize(
    ("body", "raw", "auto"),
    [
        ("1. Подшипник 6205-2RS — 10 шт, 2 380 руб.", "2 380", False),  # только итог
        ("Подшипник 6205-2RS — 10 шт на сумму 2 380 руб.", "2 380", False),
        ("Подшипник 6205-2RS — 10 шт по 238 руб.", "238", True),
        ("Подшипник 6205-2RS — 238 руб/шт, итого 2 380 руб.", "238", True),
        ("Подшипник 6205-2RS — 10 шт, цена за ед.: 238 руб.", "238", True),
        ("Bearing 6205-2RS — 238 RUB each", "238", True),
        # нет «за единицу» у цены — к снабженцу (белый список, ревью 22.10)
        ("Подшипник 6205-2RS — 10 шт, цена 238 руб.", "238", False),
        ("Подшипник 6205-2RS — 238 руб, в наличии 10 шт, итого 2380", "238", False),
        # шестое ревью 22.10: единица признака должна совпадать с единицей запроса (шт)
        ("Ремень SPZ-1000 — 710 руб. за пару (2 шт)", "710", False),
        ("Подшипник 6205-2RS — 476 руб. за комплект из 2 шт", "476", False),
        ("Подшипник 6205-2RS — 2 380 руб./компл. (10 шт)", "2 380", False),
        ("Подшипник 6205-2RS — по 2 380 руб. за упаковку из 10 шт", "2 380", False),
        ("Подшипник 6205-2RS: 10 шт — 2 380 руб., 100 шт — 23 800 руб.", "2 380", False),
        ("Подшипник 6205-2RS — 238 руб. за 1 шт.", "238", True),
        ("Наименование | Кол-во | Общая цена\nПодшипник 6205-2RS | 12 | 2 856", "2 856", False),
        ("Наименование | Кол-во | Цена, всего\nПодшипник 6205-2RS | 12 | 2 856", "2 856", False),
        ("Наименование | Кол-во | Цена, руб.\nПодшипник 6205-2RS | 12 | 238", "238", True),
        # белый список: «238 руб» без «за единицу» — к снабженцу, даже если количества рядом нет
        ("Подшипник 6205-2RS — 238 руб, срок поставки 2 недели", "238", False),
        # пятое ревью 22.10: количество словами, «×10», строкой выше, через пустые строки
        ("Подшипник 6205-2RS — десять штук, 2 380 руб.", "2 380", False),
        ("Подшипник 6205-2RS ×10 — 2 380 руб.", "2 380", False),
        ("1) Подшипник 6205-2RS — 10\n2 380 руб.", "2 380", False),
        ("Подшипник 6205-2RS — 10 шт.\n\n\nЦена: 2 380 руб.", "2 380", False),
        ("Подшипник 6205-2RS — 12.500 руб/шт", "12.500", False),  # точка в тысячах
        ("Наименование | Кол-во | Цена партии\nПодшипник 6205-2RS | 12 | 2 856", "2 856", False),
        ("6204-2RS: 10 шт × 238 руб = 2 380 руб", "238", True),
        ("№\tНаименование\tЦена, руб\n1\tПодшипник 6205-2RS\t238", "238", True),
        ("№\tНаименование\tКол-во\tСумма\n1\tПодшипник 6205-2RS\t10\t2380", "2380", False),
        ("Подшипник 6205-2RS — 10 шт, итоговая цена 2 380 руб.", "2 380", False),
        ("Bearing 6205-2RS, 10 pcs, total price 2380 RUB", "2380", False),
        ("Подшипник 6205-2RS — 238*10=2380 руб.", "2380", False),
        ("Подшипник 6205-2RS, 10 шт.\nСтоимость: 2 380 руб.", "2 380", False),  # итог строкой ниже
        ("Подшипник 6205-2RS — 10 шт, цена партии 2 380 руб.", "2 380", False),
        ("6205-2RS — 10 шт 2 380 р; SPZ-1000 — 4 шт по 355 р", "2 380", False),  # две позиции
        ("Bearing 6205-2RS — 1,250 RUB each", "1,250", False),  # запятая: 1250 или 1,25
    ],
)
def test_line_total_is_not_taken_as_unit_price(body: str, raw: str, auto: bool) -> None:
    # С другими предложениями по строке (медиана 238–245): верное — само, неверное — снабженцу
    out = verify(offer(line(1, raw)), body, REQUEST, None, PEERS)
    assert (out["confidence"] >= 0.8) is auto, out["notes"]
    if not auto:  # и без медианы неверное не проходит
        assert verify(offer(line(1, raw)), body, REQUEST)["confidence"] < 0.8


def test_pack_marker_counts_only_for_pack_price() -> None:
    body = "Подшипник 6205-2RS — 2 380 руб./упак. (10 шт)"
    # Модель не отметила цену за упаковку — «/упак» не доказывает цену за штуку
    assert verify(offer(line(1, "2 380")), body, REQUEST)["confidence"] == 0.6


def test_price_far_from_other_offers_goes_to_the_buyer() -> None:
    body = "Подшипник 6205-2RS — 2 380 руб/шт"  # «за шт» есть, но это явно итог за 10
    out = verify(
        offer(line(1, "2 380")), body, REQUEST, None, {1: [Decimal("238"), Decimal("245")]}
    )
    assert out["confidence"] == 0.6 and any("других предложений" in n for n in out["notes"])
    near = verify(offer(line(1, "2 380")), body, REQUEST, None, {1: [Decimal("2300")]})
    assert near["confidence"] == 1.0


def test_marker_unit_must_match_request_unit() -> None:
    cable = {
        "items": [{"line_no": 1, "name": "Кабель ВВГнг 3х2,5", "quantity": "100", "unit": "м"}]
    }
    per_m = verify(offer(line(1, "96.50")), "Кабель ВВГнг 3х2,5 — 96.50 RUB per m", cable)
    assert per_m["confidence"] == 1.0
    roll = verify(offer(line(1, "9 650")), "Кабель ВВГнг 3х2,5 — 9 650 руб/рулон 100 м", cable)
    assert roll["confidence"] == 0.6  # цена за рулон при запросе в метрах
    pack = verify(
        offer(line(2, "1 850", per_pack=True, pack_size_raw="100")),
        "Болт М8х30 DIN 933 — 1 850 руб за упаковку (100 шт)",
        REQUEST,
    )
    assert pack["confidence"] == 1.0  # цена за упаковку с кратностью — в упаковках


PEERS = {1: [Decimal("238"), Decimal("245")]}


def req(unit: str, quantity: str = "10", name: str = "Товар Т-1") -> dict[str, Any]:
    return {"items": [{"line_no": 1, "name": name, "quantity": quantity, "unit": unit}]}


@pytest.mark.parametrize(
    ("unit", "body", "raw", "auto"),
    [
        # седьмое ревью 22.10: «по», «each», колонка «Цена» не называют единицу —
        # при запросе не в штуках они не доказательство
        ("компл", "Ремень SPZ-1000 — по 355 руб.", "355", False),
        ("компл", "Belt SPZ-1000 — 355 RUB each", "355", False),
        ("компл", "Наименование | Цена\nРемень SPZ-1000 | 355 |", "355", False),
        ("пара", "Перчатки — по 22,50 руб. (продаются поштучно)", "22,50", False),
        ("упак", "Болт М8х30 — по 12 руб., упаковка 100 шт", "12", False),
        ("м", "Кабель — по 9 650 руб. за 100 м", "9 650", False),
        ("м", "Кабель — @ 9 650 руб. (бухта 100 м)", "9 650", False),
        ("кг", "Краска — по 1 450 руб. (банка 4,5 кг)", "1 450", False),
        # явная единица запроса у числа — доказательство при любой единице
        ("компл", "Ремень SPZ-1000 — 710 руб./компл.", "710", True),
        ("м", "Кабель — 96,50 руб. за 1 м", "96,50", True),
        ("кг", "Краска — 322 руб/кг", "322", True),
        # запрос в штуках, но рядом фасовка — «по», «each», колонка не доказательство
        ("шт", "Болт М8х30 — по 1 200 руб., упаковка 100 шт", "1 200", False),
        ("шт", "Bolt M8x30 — 1 200 RUB each (box of 100)", "1 200", False),
        ("шт", "Наименование | Ед. | Цена |\nБолт М8х30 | упак | 1 200 |", "1 200", False),
        ("шт", "Подшипник — по 2 380 руб. за 10 шт.", "2 380", False),
        ("шт", "Bearing — @ 2380 RUB per 10 pcs", "2380", False),
        # и без фасовки — по-прежнему доказательство
        ("шт", "Подшипник 6205-2RS — по 238 руб.", "238", True),
        ("шт", "Bearing 6205-2RS — 238 RUB each", "238", True),
        ("шт", "Наименование | Ед. | Цена, руб |\nПодшипник 6205-2RS | шт | 238 |", "238", True),
    ],
)
def test_packaging_or_other_unit_disables_indirect_evidence(
    unit: str, body: str, raw: str, auto: bool
) -> None:
    price = Decimal(raw.replace(" ", "").replace(",", "."))
    peers = {1: [price * Decimal("1.1"), price * Decimal("0.95")]}
    out = verify(offer(line(1, raw)), body, req(unit), None, peers)
    assert (out["confidence"] >= 0.8) is auto, out["notes"]
    if not auto:
        assert verify(offer(line(1, raw)), body, req(unit))["confidence"] < 0.8


@pytest.mark.parametrize(
    "body",
    [
        "Подшипник 6205-2RS — по 238 руб.",
        "Bearing 6205-2RS — 238 RUB each",
        "6204-2RS: 10 шт × 238 руб = 2 380 руб",
        "№\tНаименование\tЦена, руб\n1\tПодшипник 6205-2RS\t238",
    ],
)
def test_indirect_evidence_needs_other_offers(body: str) -> None:
    # Восьмое ревью 22.10: «по», «each», колонка, умножение не называют единицу, а фасовку письмо
    # может назвать как угодно — без других предложений по строке такое КП проверит снабженец
    assert verify(offer(line(1, "238")), body, REQUEST)["confidence"] == 0.6
    assert verify(offer(line(1, "238")), body, REQUEST, None, PEERS)["confidence"] == 1.0


@pytest.mark.parametrize(
    ("body", "raw"),
    [
        ("Ремень SPZ-1000 — по 710 руб. (2 шт в упак.)", "710"),  # медиана 355: в 2 раза
        ("Болт М8х30 — по 1 200 руб., упак. 100 шт", "1 200"),
        ("Болт М8х30 — 1 200 руб./шт. упаковки (100 шт)", "1 200"),
    ],
)
def test_indirect_or_packed_price_far_from_median_goes_to_the_buyer(body: str, raw: str) -> None:
    peers = {1: [Decimal("355")]} if "710" in raw else {1: [Decimal("12"), Decimal("13")]}
    assert verify(offer(line(1, raw)), body, REQUEST, None, peers)["confidence"] < 0.8
    assert verify(offer(line(1, raw)), body, REQUEST)["confidence"] < 0.8


def test_line_the_model_missed_but_rules_priced_goes_to_the_buyer() -> None:
    # Qwen пропускает строку «6305-2RS — 530 руб» (E-003): правила цену видят — КП неполное
    body = "Подшипник 6205-2RS — 238 руб/шт\nБолт М8х30 DIN 933 — 12 руб/шт"
    out = verify(offer(line(1, "238")), body, REQUEST, {1: Decimal("238"), 2: Decimal("12")})
    assert out["confidence"] == 0.6 and any("не разобрана" in n for n in out["notes"])


@pytest.mark.parametrize(
    ("unit", "body", "raw", "pack_median"),
    [
        # девятое ревью 22.10: единица запроса — фасовка, а у поставщика фасовка другого размера
        ("упак", "Перчатки нитриловые — 650 руб./упак (50 пар)", "650", "1300"),
        ("бухта", "Кабель ВВГнг 3х2,5 — 4 825 руб./бухта (50 м)", "4 825", "9650"),
        ("рулон", "Плёнка — 450 руб./рулон (150 м)", "450", "900"),
        ("компл", "Ремни SPZ-1000 — 710 руб./компл. (2 шт)", "710", "1420"),
    ],
)
def test_pack_unit_price_needs_close_median(
    unit: str, body: str, raw: str, pack_median: str
) -> None:
    rq = req(unit)
    assert verify(offer(line(1, raw)), body, rq)["confidence"] < 0.8  # без других предложений
    far = {1: [Decimal(pack_median), Decimal(pack_median) * Decimal("1.05")]}
    assert verify(offer(line(1, raw)), body, rq, None, far)["confidence"] < 0.8  # в 2 раза
    price = Decimal(raw.replace(" ", ""))
    near = {1: [price, price * Decimal("1.05")]}
    assert verify(offer(line(1, raw)), body, rq, None, near)["confidence"] == 1.0


def test_one_peer_is_not_a_median() -> None:
    # Одно другое предложение могли ввести с той же ошибкой — подтверждать им нельзя
    body = "Подшипник 6205-2RS — по 2 380 руб."
    assert (
        verify(offer(line(1, "2 380")), body, REQUEST, None, {1: [Decimal("2380")]})["confidence"]
        < 0.8
    )


@pytest.mark.parametrize(
    "body",
    [
        # десятое ревью 22.10: валюта названа не у числа
        "Цены указаны в евро.\nПодшипник 6205-2RS SKF — 2,40/шт",
        "Prices in USD.\nBearing 6205-2RS — 2.60/pc",
        "Подшипник 6205-2RS — $2.60/шт",
        "Подшипник 6205-2RS — €2,40/шт",
        "Подшипник 6205-2RS — 2,40/шт, цены в у.е.",
        "Подшипник 6205-2RS — 280/шт",  # валюты нет вовсе — сверки с правилами тоже нет
    ],
)
def test_prices_not_clearly_in_rubles_go_to_the_buyer(body: str) -> None:
    raw = next(r for r in ("2,40", "2.60", "280") if r in body)
    assert verify(offer(line(1, raw)), body, REQUEST)["confidence"] == 0.6


def test_rubles_and_euro_words_in_names_stay_automatic() -> None:
    body = "Поддон европоддон — 238 руб/шт"
    assert verify(offer(line(1, "238")), body, REQUEST)["confidence"] == 1.0


def test_pack_request_with_pack_price_keeps_requested_quantity() -> None:
    # Финальное ревью 22.10, живой Qwen: per_pack=true при запросе в упаковках — не 10 / 100
    rq = req("упак", quantity="10", name="Перчатки нитриловые (упаковка 100 шт)")
    body = "Перчатки нитриловые — 1 300 руб./упак (100 шт)"
    raw = offer(line(1, "1 300", per_pack=True, pack_size_raw="100"))
    alone = verify(raw, body, rq)
    assert (alone["lines"][0]["quantity"], alone["lines"][0]["unit"]) == ("10", "упак")
    assert alone["confidence"] < 0.8  # без других предложений — снабженцу
    near = {1: [Decimal("1300"), Decimal("1350")]}
    out = verify(raw, body, rq, None, near)
    assert out["confidence"] == 1.0 and out["lines"][0]["quantity"] == "10"
    far = {1: [Decimal("2600"), Decimal("2700")]}  # упаковка у поставщика вдвое меньше
    assert verify(raw, body, rq, None, far)["confidence"] < 0.8


@pytest.mark.parametrize("unit_raw", ["упак", None])
def test_pack_price_for_piece_request_is_always_converted(unit_raw: str | None) -> None:
    # Финальное ревью 22.10: модель назвала единицу «упак» — пересчёт в упаковки всё равно нужен,
    # иначе «500 шт × 1 200 руб.» вместо 5 упаковок
    rq = req("шт", quantity="500", name="Болт М8х30 DIN 933")
    body = "Болт М8х30 DIN 933 — 1 200 руб./упак (100 шт)"
    raw = offer(line(1, "1 200", per_pack=True, pack_size_raw="100", unit_raw=unit_raw))
    out = verify(raw, body, rq)
    ln = out["lines"][0]
    assert (ln["quantity"], ln["unit"], ln["pack_size"], ln["price"]) == (
        "5",
        "упак",
        "100",
        "1200",
    )


@pytest.mark.parametrize(
    ("body", "qty_raw", "unit_raw", "packs"),
    [
        # Финальное ревью 22.10: количество из письма не затирается количеством запроса
        ("Болт М8х30 — в наличии 3 упак., цена 1 200 руб./упак (100 шт)", "3", "упак", "3"),
        ("Болт М8х30 — 1 200 руб./упак (100 шт), есть только 300 шт", "300", "шт", "3"),
        ("Болт М8х30 — 1 200 руб./упак (100 шт)", "100", "шт", "5"),  # «(100 шт)» — кратность
        ("Болт М8х30 — 1 200 руб./упак (100 шт)", None, None, "5"),
    ],
)
def test_pack_price_keeps_quantity_from_letter(
    body: str, qty_raw: str | None, unit_raw: str | None, packs: str
) -> None:
    rq = req("шт", quantity="500", name="Болт М8х30 DIN 933")
    raw = offer(line(1, "1 200", per_pack=True, pack_size_raw="100", quantity_raw=qty_raw,
                     unit_raw=unit_raw))  # fmt: skip
    ln = verify(raw, body, rq)["lines"][0]
    assert (ln["quantity"], ln["unit"], ln["pack_size"]) == (packs, "упак", "100")
