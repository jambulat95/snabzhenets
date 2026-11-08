"""Проверки поставщиков — код, не модель (методика: М-05 действующий и не в РНП, М-06 аффилированность).

Вердикты как в движке правил A2A: allow / warn / human / deny; у каждого — код правила и причина.
"""

from dataclasses import dataclass
from typing import Any

from ..inn import is_valid_inn
from ..models import Supplier

RANK = {"allow": 0, "warn": 1, "human": 2, "deny": 3}


@dataclass
class CheckResult:
    code: str
    verdict: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "verdict": self.verdict, "reason": self.reason}


def worst(results: list[CheckResult]) -> str:
    return max((r.verdict for r in results), key=RANK.__getitem__, default="allow")


def single(s: Supplier) -> list[CheckResult]:
    out = []
    if s.inn:
        ok = is_valid_inn(s.inn)
        out.append(CheckResult("ИНН", "allow" if ok else "deny",
                               "Контрольная сумма ИНН верна" if ok else "ИНН с неверной контрольной суммой"))
    elif s.is_demo:
        out.append(CheckResult("ИНН", "allow", "Демо-поставщик: ИНН не задан, чтобы не совпасть с реальной компанией"))
    else:
        out.append(CheckResult("ИНН", "human", "ИНН неизвестен — проверьте поставщика"))
    status = s.egrul_status or "unknown"
    if status == "active":
        out.append(CheckResult("М-05", "allow", "Действующая организация (ЕГРЮЛ)"))
    elif status in ("liquidating", "liquidated"):
        word = "в стадии ликвидации" if status == "liquidating" else "ликвидирована"
        out.append(CheckResult("М-05", "deny", f"Организация {word} (ЕГРЮЛ) — источник ценовой информации не подходит"))
    else:
        out.append(CheckResult("М-05", "human", "Статус в ЕГРЮЛ не проверен"))
    out.append(CheckResult("М-05", "deny", "Есть в реестре недобросовестных поставщиков")
               if s.in_rnp else CheckResult("М-05", "allow", "Нет в реестре недобросовестных поставщиков"))
    return out


def affiliation(a: Supplier, b: Supplier) -> list[str]:
    """Общие признаки двух поставщиков: телефон, адрес, учредитель."""
    common = []
    if a.phone and a.phone == b.phone:
        common.append("телефон")
    if a.address and a.address == b.address:
        common.append("адрес")
    if set(a.founders or []) & set(b.founders or []):
        common.append("учредитель")
    return common
