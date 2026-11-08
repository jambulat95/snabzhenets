"""Поиск и отбор поставщиков (SOURCING): ЕИС (срез) + демо-справочник → проверки → ранжирование → выбор.

Затем — запросы ценовой информации в outbox и переход к сбору цен (COLLECTING).
"""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import journal
from ..config import settings
from ..db import SessionLocal
from ..integrations.eis.port import EisPort
from ..integrations.eis.replay import ReplayEis
from ..models import Candidate, Organization, Procurement, Supplier
from ..outreach.outbox import queue_requests
from ..pipeline import Status, transition
from .checks import CheckResult, affiliation, single, worst

SKFO = {"Чеченская Республика", "Республика Дагестан", "Республика Ингушетия", "Кабардино-Балкарская Республика",
        "Карачаево-Черкесская Республика", "Республика Северная Осетия — Алания", "Ставропольский край"}
MAX_SELECTED = 10


def demo_directory() -> list[dict[str, Any]]:
    path = Path(settings.replay_dir) / "demo" / "suppliers.json"
    data: list[dict[str, Any]] = json.loads(path.read_text("utf-8"))["suppliers"]
    return data


def upsert_demo(db: Session, row: dict[str, Any]) -> Supplier:
    s = db.scalar(select(Supplier).where(Supplier.key == row["key"]))
    if s is None:
        s = Supplier(key=row["key"], source="demo", is_demo=True)
        db.add(s)
    s.name, s.region, s.city, s.email, s.phone = row["name"], row["region"], row["city"], row["email"], row["phone"]
    s.address, s.founders = row["address"], row["founders"]
    s.egrul_status, s.in_rnp = row["egrul_status"], row["in_rnp"]
    s.contracts_44fz_3y, s.okpd2, s.inn = row["contracts_44fz_3y"], row["okpd2"], None
    s.meta = {"scenario": row["scenario"]}
    db.flush()
    return s


def region_rank(org: Organization, s: Supplier) -> int:
    if s.region == org.region:
        return 0
    return 1 if s.region in SKFO else 2


def run_sourcing(procurement_id: int, eis: EisPort | None = None) -> None:
    eis = eis or ReplayEis()
    with SessionLocal() as db:
        proc = db.get(Procurement, procurement_id)
        if proc is None or proc.status != Status.SOURCING:
            return
        org = db.get(Organization, proc.org_id)
        assert org is not None
        codes = {c for i in proc.items for c in (i.okpd2_code, i.ktru_code) if c}
        okpd2 = {i.okpd2_code for i in proc.items if i.okpd2_code}

        contracts = eis.contracts(codes)
        journal.record(db, org_id=proc.org_id, procurement_id=proc.id, action="eis_searched", actor_kind="agent",
                       decision="ok" if contracts else "empty",
                       details={"codes": sorted(codes), "contracts": len(contracts), "captured_at": eis.captured_at(),
                                **({} if contracts else {"note": "Срез реестра контрактов ЕИС не подключён — "
                                                                 "используется демо-справочник поставщиков"})})
        # TODO(срез ЕИС): поставщики из contracts → Supplier(source="eis") + демо-двойник адреса для писем

        found: list[tuple[Supplier, list[int], list[dict[str, Any]]]] = []
        if settings.demo_mode:
            for row in demo_directory():
                items = [i.id for i in proc.items if i.okpd2_code in row["okpd2"]]
                if items and okpd2 & set(row["okpd2"]):
                    found.append((upsert_demo(db, row), items, [{"kind": "demo", "title": "Демо-справочник"}]))

        db.execute(delete(Candidate).where(Candidate.procurement_id == proc.id))
        cands: list[tuple[Candidate, list[CheckResult]]] = []
        for sup, items, sources in found:
            res = single(sup)
            cands.append((Candidate(procurement_id=proc.id, supplier_id=sup.id, item_ids=items, sources=sources,
                                    verdict=worst(res)), res))
        # М-06: из двух аффилированных источников в расчёт идёт один — с большим опытом контрактов
        by_id = {sup.id: sup for sup, _, _ in found}
        for i, (a, ra) in enumerate(cands):
            for b, rb in cands[i + 1:]:
                common = affiliation(by_id[a.supplier_id], by_id[b.supplier_id])
                if not common:
                    continue
                sa, sb = by_id[a.supplier_id], by_id[b.supplier_id]
                weaker, w_res, other = (b, rb, sa) if sa.contracts_44fz_3y >= sb.contracts_44fz_3y else (a, ra, sb)
                w_res.append(CheckResult("М-06", "human", f"Признаки аффилированности с «{other.name}»: общий "
                                         f"{', '.join(common)}. Две цены от связанных лиц не считаются независимыми"))
                weaker.verdict = worst(w_res)

        cands.sort(key=lambda t: (t[0].verdict != "allow", region_rank(org, by_id[t[0].supplier_id]),
                                  -by_id[t[0].supplier_id].contracts_44fz_3y))
        selected = 0
        for rank, (c, res) in enumerate(cands, start=1):
            c.rank, c.checks = rank, [r.as_dict() for r in res]
            bad = [r for r in res if r.verdict in ("deny", "human")]
            c.selected = not bad and selected < MAX_SELECTED
            selected += c.selected
            sup = by_id[c.supplier_id]
            where = ("тот же регион", "СКФО", "другой регион")[region_rank(org, sup)]
            chosen = f"Выбран: {where}, контрактов по 44-ФЗ за 3 года: {sup.contracts_44fz_3y}"
            c.reason = bad[0].reason if bad else chosen
            db.add(c)
            db.flush()
            if bad:
                journal.record(db, org_id=proc.org_id, procurement_id=proc.id, action="supplier_excluded",
                               actor_kind="agent", decision=bad[0].verdict, rule_code=bad[0].code,
                               details={"supplier": by_id[c.supplier_id].name, "reason": bad[0].reason})
        journal.record(db, org_id=proc.org_id, procurement_id=proc.id, action="suppliers_selected", actor_kind="agent",
                       decision="ok" if selected >= 5 else "few", rule_code="М-01",
                       details={"found": len(cands), "selected": selected,
                                **({} if selected >= 5 else {"note": "Меньше 5 поставщиков с опытом — запрос "
                                                                     "направлен всем найденным, причина фиксируется"})})
        queue_requests(db, proc, org, [c for c, _ in cands if c.selected])
        transition(db, proc, Status.COLLECTING, actor_kind="agent", details={"requests": selected})
        db.commit()
