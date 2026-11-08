"""Схемы разбора запроса.

LLM* — то, что возвращает модель: номера строк и дословные значения, без пересчётов.
Остальное — результат после проверки кодом. Формат ParsedRequest — предложение
для объекта «Запрос», ещё не согласован с бэкендом.
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

RequestKind = Literal["order", "budget_estimate"]


class LLMPosition(BaseModel):
    line: int = Field(description="Номер строки запроса с этой позицией")
    name: str = Field(description="Наименование с характеристиками, как в запросе")
    article: str | None = Field(description="Артикул или обозначение дословно, если есть")
    quantity_raw: str | None = Field(description="Количество дословно, например «10» или «2,5»")
    unit_raw: str | None = Field(description="Единица дословно, например «шт», «штуки», «м»")


class LLMPositions(BaseModel):
    positions: list[LLMPosition]


class LLMRequirement(BaseModel):
    line: int = Field(description="Номер строки запроса с требованием")
    text: str = Field(description="Требование коротко")
    mandatory: bool = Field(description="true — отсекающее, false — желательное")


class LLMMeta(BaseModel):
    kind: RequestKind
    deadline_raw: str | None = Field(description="Срок поставки дословно, если указан")
    requirements: list[LLMRequirement]


class LLMRequest(LLMMeta, LLMPositions):
    """Объединённый ответ: позиции из кусков + общие поля запроса."""


class Position(BaseModel):
    index: int
    line: int
    source: str
    name: str
    article: str | None
    quantity: Decimal | None
    unit: str | None  # каноническая единица, см. units.py
    unit_raw: str | None
    status: Literal["ok", "needs_review"]
    # Блокирующие проблемы: из-за них строка уходит на проверку.
    problems: list[str] = []
    # Не блокируют, но видны человеку и следующим шагам.
    notes: list[str] = []


class Requirement(BaseModel):
    line: int
    source: str
    text: str
    mandatory: bool


class ParsedRequest(BaseModel):
    kind: RequestKind
    deadline_raw: str | None
    requirements: list[Requirement]
    positions: list[Position]
    # Строки запроса с цифрами, которые не попали ни в одну позицию или требование.
    possibly_missed: list[str]
