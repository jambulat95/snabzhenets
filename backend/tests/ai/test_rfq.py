from datetime import date
from decimal import Decimal

import pytest

from app.agents.ml.parse import LLMRequest, ParsedRequest, Position, Requirement, postprocess
from app.agents.ml.parse.rfq import parse_due, structured_requirement, to_rfq
from app.agents.ml.parse.schemas import LLMPosition

TODAY = date(2026, 10, 19)


def pos(line: int, name: str, qty: str | None, unit: str | None, **kw: object) -> Position:
    return Position(
        index=line, line=line, source=f"{line}. {name}", name=name, article=kw.get("article"),
        quantity=Decimal(qty) if qty else None, unit=unit, unit_raw=kw.get("unit_raw", unit),
        status="needs_review" if kw.get("problems") else "ok", problems=kw.get("problems", []),
    )  # type: ignore[arg-type]  # fmt: skip


def req(line: int, text: str, mandatory: bool = True) -> Requirement:
    return Requirement(line=line, source=text, text=text, mandatory=mandatory)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Только SKF", ("бренд", "SKF")),
        ("производитель: Timken", ("бренд", "Timken")),
        ("подшипники фирмы skf, не китай", ("бренд", "SKF")),
        ("по ГОСТ 520-2011", ("стандарт", "ГОСТ 520")),
        ("манжеты DIN 3760", ("стандарт", "DIN 3760")),
        ("класс точности Р6", ("класс точности", "P6")),
        ("только ИЭК", ("бренд", "IEK")),  # написание по-русски — тот же бренд
        ("автоматы ИЭК (IEK)", ("бренд", "IEK")),
        ("SKF или FAG", None),  # «или» атрибутом не выразить
        ("производитель любой", None),
        ("оплата по факту поставки", None),
    ],
)
def test_structured_requirement(text: str, expected: tuple[str, str] | None) -> None:
    assert structured_requirement(text) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("до 25.10", date(2026, 10, 25)),
        ("к 05.11.2026", date(2026, 11, 5)),
        ("поставка 20 ноября", date(2026, 11, 20)),
        ("до 15 мая", date(2027, 5, 15)),  # прошедшая дата без года — следующий год
        ("в течение 10 дней", None),
        (None, None),
    ],
)
def test_parse_due(raw: str | None, expected: date | None) -> None:
    assert parse_due(raw, TODAY) == expected


def test_to_rfq_places_requirements_where_core_can_check_them() -> None:
    parsed = ParsedRequest(
        kind="order",
        deadline_raw="до 30.10",
        positions=[
            pos(1, "Подшипник 6205-2RS", "10", "шт"),
            pos(2, "Манжета 40x62x10", "20", "шт"),
            pos(3, "Гайка М14", None, None, problems=["количество не указано"]),
        ],
        requirements=[
            req(1, "только SKF"),  # строка 1, сверяется с карточкой
            req(2, "фторкаучук FKM"),  # строка 2, свободный текст — в характеристики
            req(4, "без аналогов"),
            req(5, "доставка до склада в Казани", mandatory=False),
            req(6, "оплата с отсрочкой 30 дней"),  # просьба об отсрочке — в payment (ПР-6)
        ],
        possibly_missed=["Тел. отдела 1234"],
    )

    content, notes = to_rfq(parsed, TODAY)

    one, two, three = content["items"]
    assert one["must_have"] == [{"attribute": "бренд", "value": "SKF"}]
    assert two["characteristics"] == "фторкаучук FKM" and "must_have" not in two
    assert three["recognized"] is False and three["quantity"] == "1"
    assert "must_have" not in content  # свободный текст не попал в отсекающие
    assert content["allow_analogs"] is False
    assert content["kind"] == "order"
    assert content["delivery"] == {
        "region": "доставка до склада в Казани",
        "due_date": "2026-10-30",
    }
    assert content["payment"] == {"kind": "deferral", "days": 30}
    assert not any("отсрочкой" in n for n in notes)
    assert any("Строка 3" in n for n in notes)
    assert any("Тел. отдела" in n for n in notes)


def test_article_is_kept_in_name_and_budget_kind_mapped() -> None:
    parsed = ParsedRequest(
        kind="budget_estimate", deadline_raw=None, requirements=[], possibly_missed=[],
        positions=[pos(1, "Ремень клиновой", "4", "шт", article="B-1000")],
    )  # fmt: skip
    content, notes = to_rfq(parsed, TODAY)
    assert content["kind"] == "budget"
    assert content["items"][0]["name"] == "Ремень клиновой B-1000"
    assert notes == []


def test_lines_not_understood_become_unrecognized_items_in_text_order() -> None:
    text = (
        "Заявка 7:\n1. Подшипник 6205-2RS — 10 шт\n2. что-то непонятное\nБюджет 5000 руб\n"
        "Только SKF\nС уважением, Иванов, +7 900 123-45-67"
    )
    parsed = ParsedRequest(
        kind="order", deadline_raw=None, possibly_missed=["Бюджет 5000 руб"],
        positions=[pos(2, "Подшипник 6205-2RS", "10", "шт")], requirements=[req(5, "Только SKF")],
    )  # fmt: skip

    content, notes = to_rfq(parsed, TODAY, text)

    first, second = content["items"]
    assert (first["line_no"], first["name"], first.get("recognized", True)) == (
        1,
        "Подшипник 6205-2RS",
        True,
    )
    assert (second["line_no"], second["name"], second["recognized"]) == (
        2,
        "что-то непонятное",
        False,
    )
    assert not any("Бюджет" in n for n in notes)  # бюджет разбирают правила, не «пропущено»
    assert content["must_have"] == [{"attribute": "бренд", "value": "SKF"}]


def test_category_requirement_applies_only_to_matching_items() -> None:
    parsed = ParsedRequest(
        kind="order", deadline_raw=None, possibly_missed=[],
        positions=[pos(1, "Подшипник 6205-2RS", "20", "шт"), pos(2, "Ремень A-1250", "8", "шт")],
        requirements=[req(3, "Подшипники только SKF")],
    )  # fmt: skip
    content, _ = to_rfq(parsed, TODAY)
    bearing, belt = content["items"]
    assert bearing["must_have"] == [{"attribute": "бренд", "value": "SKF"}]
    assert "must_have" not in belt and "must_have" not in content


def test_budget_and_parsed_deadline_are_not_repeated_in_notes() -> None:
    parsed = ParsedRequest(
        kind="order", deadline_raw="до 30.10", possibly_missed=[],
        positions=[pos(1, "Подшипник 6205-2RS", "10", "шт")],
        requirements=[req(2, "Бюджет 5000 руб"), req(3, "Срок поставки до 30.10")],
    )  # fmt: skip
    content, notes = to_rfq(parsed, TODAY)
    assert content["delivery"] == {"due_date": "2026-10-30"}
    assert notes == []


def test_unclear_line_taken_for_condition_stays_an_unrecognized_item() -> None:
    text = "Заявка 1:\n1. Подшипник 6205-2RS — 10 шт\n2. что-то непонятное\nОплата по факту"
    parsed = ParsedRequest(
        kind="order", deadline_raw=None, possibly_missed=[],
        positions=[pos(2, "Подшипник 6205-2RS", "10", "шт")],
        requirements=[req(3, "что-то непонятное", mandatory=False), req(4, "Оплата по факту")],
    )  # fmt: skip
    content, notes = to_rfq(parsed, TODAY, text)
    assert [(it["name"], it.get("recognized", True)) for it in content["items"]] == [
        ("Подшипник 6205-2RS", True),
        ("что-то непонятное", False),
    ]
    assert any("Оплата по факту" in n for n in notes)  # настоящее условие — снабженцу


def test_no_analogs_on_a_position_line_applies_to_that_line_only() -> None:
    first = pos(1, "Подшипник 6205-2RS без аналогов", "8", "шт")
    first = first.model_copy(update={"source": "1. Подшипник 6205-2RS без аналогов — 8 шт"})
    parsed = ParsedRequest(
        kind="order", deadline_raw=None, possibly_missed=[],
        positions=[first, pos(2, "Ремень A-1250", "2", "шт")],
        requirements=[req(2, "аналоги не предлагать")],
    )  # fmt: skip
    content, _ = to_rfq(parsed, TODAY)
    one, two = content["items"]
    assert one["allow_analogs"] is False and one["name"] == "Подшипник 6205-2RS"
    assert two["allow_analogs"] is False
    assert "allow_analogs" not in content


def test_schema_limits_are_kept() -> None:
    many = [pos(i, f"Болт М{i}", "1", "шт") for i in range(1, 503)]
    parsed = ParsedRequest(
        kind="order", deadline_raw=None, requirements=[], possibly_missed=[], positions=many
    )
    content, notes = to_rfq(parsed, TODAY)
    assert len(content["items"]) == 500 and any("первые 500" in n for n in notes)


def test_one_note_about_a_unit_that_is_not_in_the_line() -> None:
    text = "Подшипник 6205 — 5"
    raw = LLMRequest(
        kind="order", deadline_raw=None, requirements=[],
        positions=[
            LLMPosition(
                line=1, name="Подшипник 6205", article=None, quantity_raw="5", unit_raw="шт"
            )
        ],
    )  # fmt: skip
    notes = to_rfq(postprocess(raw, text), None, text)[1]
    assert notes == ["Строка 1: единица «шт» не найдена в строке."]
