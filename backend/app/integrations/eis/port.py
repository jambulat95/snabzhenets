"""Порт ЕИС: контракты 44-ФЗ по коду товара (поставщики с опытом исполнения контрактов, приказ № 567)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class Contract:
    reg_number: str
    url: str | None
    customer: str
    customer_region: str | None
    supplier_name: str
    supplier_inn: str | None
    signed_at: date | None
    okpd2: str | None
    ktru: str | None
    item_name: str | None
    unit_price: Decimal | None


class EisPort(Protocol):
    def captured_at(self) -> str | None: ...

    def contracts(self, codes: set[str]) -> list[Contract]:
        """Контракты, где есть товар с кодом ОКПД2 или КТРУ из набора (за последние 3 года)."""
        ...
