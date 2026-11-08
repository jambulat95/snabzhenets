"""Срез открытого реестра контрактов ЕИС (data/replay/eis/contracts.json). Пока может быть пуст."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from ...config import settings
from .port import Contract


class ReplayEis:
    def __init__(self, base: Path | None = None) -> None:
        self.path = (base or Path(settings.replay_dir)) / "eis" / "contracts.json"
        self._raw: dict[str, Any] = json.loads(self.path.read_text("utf-8")) if self.path.exists() else {}

    def captured_at(self) -> str | None:
        value = self._raw.get("captured_at")
        return str(value) if value else None

    def contracts(self, codes: set[str]) -> list[Contract]:
        out = []
        for c in self._raw.get("contracts", []):
            if not ({c.get("okpd2"), c.get("ktru")} & codes):
                continue
            out.append(Contract(
                reg_number=c["reg_number"], url=c.get("url"), customer=c["customer"],
                customer_region=c.get("customer_region"), supplier_name=c["supplier_name"],
                supplier_inn=c.get("supplier_inn"),
                signed_at=date.fromisoformat(c["signed_at"]) if c.get("signed_at") else None,
                okpd2=c.get("okpd2"), ktru=c.get("ktru"), item_name=c.get("item_name"),
                unit_price=Decimal(str(c["unit_price"])) if c.get("unit_price") is not None else None,
            ))
        return out
