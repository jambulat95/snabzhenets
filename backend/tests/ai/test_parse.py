import json
from decimal import Decimal
from typing import Any

import pytest

from app.agents.ml.gateway import Gateway, ProviderConfig
from app.agents.ml.gateway.providers import Completion
from app.agents.ml.parse import LLMRequest, normalize_unit, parse_request, postprocess
from app.agents.ml.parse.parser import chunk_ranges
from app.agents.ml.parse.text import contains, parse_quantity, standalone_numbers

TEXT = """Добрый день! Прошу КП:
1. Подшипник 6204-2RS — 10 шт
2. Ремень приводной B-1000, 4 штуки
3. Кабель ВВГнг 3х2,5 — 2,5 м
Только SKF или FAG. Поставка до 30 октября."""
# Строки: 1 приветствие, 2–4 позиции, 5 требования и срок.


def pos(line: int, name: str = "x", **kw: Any) -> dict[str, Any]:
    return {"line": line, "name": name, "article": None, "quantity_raw": None,
            "unit_raw": None} | kw  # fmt: skip


def llm(*positions: dict[str, Any], **kw: Any) -> LLMRequest:
    return LLMRequest.model_validate(
        {"kind": "order", "deadline_raw": None, "requirements": [], "positions": list(positions)}
        | kw
    )


def test_valid_lines_are_ok_and_units_normalized() -> None:
    raw = llm(
        pos(2, article="6204-2RS", quantity_raw="10", unit_raw="шт"),
        pos(3, quantity_raw="4", unit_raw="штуки"),
        pos(4, quantity_raw="2,5", unit_raw="м"),
        requirements=[{"line": 5, "text": "SKF или FAG", "mandatory": True}],
        deadline_raw="до 30 октября",
    )
    res = postprocess(raw, TEXT)
    assert [(p.quantity, p.unit, p.status) for p in res.positions] == [
        (Decimal(10), "шт", "ok"),
        (Decimal(4), "шт", "ok"),
        (Decimal("2.5"), "м", "ok"),
    ]
    assert res.positions[0].source == "1. Подшипник 6204-2RS — 10 шт"
    assert res.requirements[0].source.startswith("Только SKF")
    assert res.deadline_raw == "до 30 октября"
    assert res.possibly_missed == []


def test_positions_are_sorted_by_line() -> None:
    raw = llm(pos(3, quantity_raw="4", unit_raw="штуки"), pos(2, quantity_raw="10", unit_raw="шт"))
    assert [(p.index, p.line) for p in postprocess(raw, TEXT).positions] == [(1, 2), (2, 3)]


def test_line_out_of_range_is_flagged() -> None:
    [p] = postprocess(llm(pos(42, quantity_raw="8", unit_raw="шт")), TEXT).positions
    assert p.status == "needs_review" and "строки 42 нет в запросе" in p.problems


def test_quantity_from_another_line_is_flagged() -> None:
    [p] = postprocess(llm(pos(2, quantity_raw="4", unit_raw="шт")), TEXT).positions
    assert p.quantity is None and p.status == "needs_review"


def test_number_from_article_is_not_a_quantity() -> None:
    text = "Подшипник 6204-2RS"
    [p] = postprocess(llm(pos(1, quantity_raw="2")), text).positions
    assert p.quantity is None and p.status == "needs_review"


def test_missing_quantity_and_unknown_unit_need_review() -> None:
    text = "Манжета 40x60x10\nСальник 30x47 — 5 бобин"
    res = postprocess(llm(pos(1), pos(2, quantity_raw="5", unit_raw="бобин")), text)
    assert res.positions[0].problems == ["количество не указано"]
    assert res.positions[1].problems == ["незнакомая единица «бобин»"]


def test_missing_unit_is_a_note_not_a_problem() -> None:
    [p] = postprocess(llm(pos(1, quantity_raw="10")), "Подшипник 6204 — 10").positions
    assert p.status == "ok" and p.unit is None and p.notes


def test_article_not_in_line_is_dropped() -> None:
    [p] = postprocess(llm(pos(2, article="6205", quantity_raw="10", unit_raw="шт")), TEXT).positions
    assert p.article is None and p.status == "ok" and p.notes


def test_homoglyphs_and_dashes_match() -> None:
    assert contains("Подшипник 6204-2РС — 10 шт", "подшипник 6204–2RS - 10 шт")


def test_missed_lines_are_reported() -> None:
    res = postprocess(llm(pos(2, quantity_raw="10", unit_raw="шт")), TEXT)
    assert res.possibly_missed == [
        "2. Ремень приводной B-1000, 4 штуки",
        "3. Кабель ВВГнг 3х2,5 — 2,5 м",
        "Только SKF или FAG. Поставка до 30 октября.",
    ]


def test_contact_lines_are_not_reported_as_missed() -> None:
    text = "Подшипник 6204 — 10 шт\nИванов, +7 900 123-45-67, ivanov@gamma.demo"
    res = postprocess(llm(pos(1, quantity_raw="10", unit_raw="шт")), text)
    assert res.possibly_missed == []


def test_invented_deadline_is_dropped() -> None:
    assert postprocess(llm(deadline_raw="до 1 ноября"), TEXT).deadline_raw is None


@pytest.mark.parametrize(
    ("n", "k", "expected"),
    [(15, 3, [5, 5, 5]), (16, 3, [6, 5, 5]), (2, 3, [1, 1]), (1, 3, [1])],
)
def test_chunk_ranges_cover_all_lines(n: int, k: int, expected: list[int]) -> None:
    chunks = chunk_ranges(n, k)
    assert [len(c) for c in chunks] == expected
    assert [i for c in chunks for i in c] == list(range(1, n + 1))


@pytest.mark.parametrize(
    ("raw", "value"),
    [("10", 10), ("2,5", Decimal("2.5")), ("1 000", 1000), ("десять", 10), ("пару", None)],
)
def test_parse_quantity(raw: str, value: Decimal | int | None) -> None:
    assert parse_quantity(raw) == (Decimal(value) if value is not None else None)


def test_standalone_numbers_skip_articles_and_sizes() -> None:
    assert standalone_numbers("Подшипник 6204-2RS 40x60x10 — 100 шт, ещё 1 000") == [
        Decimal(100), Decimal(1000)
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("raw", "unit"), [("штуки", "шт"), ("Уп.", "упак"), ("бухты", "бухта"), ("бобин", None)]
)
def test_normalize_unit(raw: str, unit: str | None) -> None:
    assert normalize_unit(raw) == unit


class FakeProvider:
    """Отвечает по номерам строк, которые увидел во входе."""

    def __init__(self) -> None:
        self.cfg = ProviderConfig(name="fake", base_url="", api_key=None, model="fake")
        self.inputs: list[str] = []

    async def complete(self, messages: list[dict[str, str]], json_schema: dict[str, Any],
                       **kw: Any) -> Completion:  # fmt: skip
        data = messages[1]["content"]
        self.inputs.append(data)
        if "requirements" in json_schema["properties"]:
            answer: dict[str, Any] = {"kind": "order", "deadline_raw": "до 30 октября",
                                      "requirements": [{"line": 5, "text": "SKF",
                                                        "mandatory": True}]}  # fmt: skip
        else:
            qty = {"[2]": ("10", "шт"), "[3]": ("4", "штуки"), "[4]": ("2,5", "м")}
            answer = {"positions": [
                pos(int(tag[1:-1]), quantity_raw=q, unit_raw=u)
                for tag, (q, u) in qty.items() if tag in data
            ] + [pos(99)]}  # чужая строка — должна отброситься  # fmt: skip
        return Completion(json.dumps(answer), 10, 10, 1, "stop")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_parse_request_splits_into_chunks_and_merges() -> None:
    fake = FakeProvider()
    res = await parse_request(Gateway([fake]), TEXT, parallel=2)

    assert len(fake.inputs) == 3  # общие поля + 2 куска
    first_chunk = [i for i in fake.inputs if "[1]" in i and "[5]" not in i]
    assert len(first_chunk) == 1 and "[4]" not in first_chunk[0]
    assert [p.line for p in res.positions] == [2, 3, 4]
    assert all(p.status == "ok" for p in res.positions)
    assert res.requirements[0].mandatory and res.possibly_missed == []


def test_unit_normalized_by_model_is_accepted_if_present_in_line() -> None:
    text = "Подшипник 8106 - 6 шт.\nРемень SPA 1250 - 2"
    res = postprocess(
        llm(pos(1, quantity_raw="6", unit_raw="штука"), pos(2, quantity_raw="2", unit_raw="штука")),
        text,
    )
    assert (res.positions[0].unit, res.positions[0].status) == ("шт", "ok")
    assert res.positions[1].status == "needs_review"  # в строке нет единицы — не верим


@pytest.mark.parametrize(
    ("line", "units"),
    [("Болт М12 — 100 Условная единица", {"усл.ед"}), ("Ремень - 15 усл. ед.", {"усл.ед"}),
     ("Провод 1*2,5 — 10 см", {"см"}), ("гайка 30шт", {"шт"})],
)  # fmt: skip
def test_units_in(line: str, units: set[str]) -> None:
    from app.agents.ml.parse.units import units_in

    assert units_in(line) == units


def test_position_without_quantity_on_requirement_line_is_dropped() -> None:
    raw = llm(
        pos(2, quantity_raw="10", unit_raw="шт"),
        pos(5, name="Только SKF или FAG"),
        requirements=[{"line": 5, "text": "SKF или FAG", "mandatory": True}],
    )
    assert [p.line for p in postprocess(raw, TEXT).positions] == [2]


def test_code_taken_as_quantity_goes_to_review() -> None:
    text = "МАНЖЕТА АРМИРОВАННАЯ 65Х140Х10 FKM 30628487 — 61 усл. ед."
    [p] = postprocess(llm(pos(1, quantity_raw="30628487", unit_raw="усл. ед.")), text).positions
    assert p.quantity is None and p.status == "needs_review"


@pytest.mark.parametrize(
    ("name", "source", "qty", "expected"),
    [
        # Код номенклатуры в начале строки модель приняла за номер пункта
        ("ПОДШИПНИК 6024 C3", "1) 30784809 - ПОДШИПНИК 6024 C3, 2 Штука.", "2",
         "30784809 - ПОДШИПНИК 6024 C3"),
        ("Подшипник корпуса", "2363145 «Подшипник корпуса»\t4\tШтука", "4",
         "2363145 - Подшипник корпуса"),
        # «арт. …» отрезан вместе с «или эквивалент»
        ("Пускатель ПМЛ 1501 IP00 110В ВТМ",
         "Пускатель ПМЛ 1501 IP00 110В ВТМ арт. ВТМ00052310 или эквивалент - 10 Штука", "10",
         "Пускатель ПМЛ 1501 IP00 110В ВТМ арт. ВТМ00052310"),
        # Ничего не потеряно — не трогаем; номер пункта и количество — не коды
        ("Подшипник 6205-2RS", "1. Подшипник 6205-2RS — 10 шт", "10", "Подшипник 6205-2RS"),
        ("Болт М8", "12000 Болт М8", "12000", "Болт М8"),
        ("Манжета 1.2-50х70-1", "3. Манжета 1.2-50х70-1 ГОСТ 8752 — 15", "15",
         "Манжета 1.2-50х70-1"),
    ],
)  # fmt: skip
def test_restore_codes(name: str, source: str, qty: str, expected: str) -> None:
    from app.agents.ml.parse.parser import restore_codes

    assert restore_codes(name, source, qty) == expected


def test_signature_without_quantity_is_not_a_position() -> None:
    from app.agents.ml.parse.parser import postprocess
    from app.agents.ml.parse.schemas import LLMPosition, LLMRequest

    text = "1. Подшипник 6204-2RS — 20 шт\nС уважением, Иванов Пётр, +7 900 123-45-67"
    raw = LLMRequest(
        kind="order", deadline_raw=None, requirements=[],
        positions=[
            LLMPosition(line=1, name="Подшипник 6204-2RS", article="6204-2RS", quantity_raw="20",
                        unit_raw="шт"),
            LLMPosition(line=2, name="С уважением, [ФИО], [телефон]", article=None,
                        quantity_raw=None, unit_raw=None),
        ],
    )  # fmt: skip
    assert [p.name for p in postprocess(raw, text).positions] == ["Подшипник 6204-2RS"]


@pytest.mark.parametrize(
    ("line", "qty_raw", "unit_raw", "expected"),
    [
        ("Шайба 8 — 2 тыс. шт", "2", "шт", Decimal(2000)),
        ("Шайба 8 — 2 тыс. шт", "2 тыс.", "шт", Decimal(2000)),
        ("Шайба 8 — 2 тыс. шт", "2", "тыс. шт", Decimal(2000)),
        ("Болт М8 — 1 000 шт", "1 000", "шт", Decimal(1000)),
        ("Болт М8 — 20 шт", "20", "шт", Decimal(20)),
    ],
)
def test_thousands_and_digit_groups(
    line: str, qty_raw: str, unit_raw: str, expected: Decimal
) -> None:
    [p] = postprocess(llm(pos(1, quantity_raw=qty_raw, unit_raw=unit_raw)), line).positions
    assert (p.quantity, p.unit, p.status) == (expected, "шт", "ok")
