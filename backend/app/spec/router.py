"""API заявок: создание из текста, просмотр, правка спецификации, подтверждение человеком."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import journal
from ..auth.deps import get_current_user
from ..db import get_db
from ..models import JournalEntry, PriceQuote, Procurement, SpecItem, User
from ..pipeline import TITLES, Status, TransitionError, transition
from ..queue import enqueue
from . import ktru

router = APIRouter(prefix="/api", tags=["procurements"])


def err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


class CreateIn(BaseModel):
    text: str = Field(min_length=3, max_length=20000)
    title: str | None = Field(default=None, max_length=200)


class ItemIn(BaseModel):
    name: str | None = Field(default=None, max_length=500)
    characteristics: str | None = None
    quantity: Decimal | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=20)
    ktru_code: str | None = None


class ItemOut(BaseModel):
    id: int
    line_no: int
    name: str
    characteristics: str | None
    quantity: Decimal | None
    unit: str | None
    ktru_code: str | None
    okpd2_code: str | None
    ktru_candidates: list[dict[str, Any]]
    ktru_suggestion: dict[str, Any] | None
    status: str
    problems: list[str]
    notes: list[str]
    questions: list[str]
    source: str | None


class JournalOut(BaseModel):
    seq: int
    created_at: datetime
    actor_kind: str
    action: str
    decision: str | None
    model: str | None
    prompt_version: str | None
    tokens: int | None
    cost_rub: Decimal | None
    details: dict[str, Any]
    hash: str


class QuoteOut(BaseModel):
    id: int
    spec_item_id: int
    channel: str
    source_name: str
    region: str | None
    offer_name: str | None
    unit_price: Decimal
    vat_mode: str
    price_kind: str | None
    url: str | None
    captured_at: datetime
    extracted_by: str
    html_sha256: str | None
    screenshot_sha256: str | None
    match: dict[str, Any]
    status: str
    notes: list[str]


class ProcurementOut(BaseModel):
    id: int
    number: str | None
    title: str
    status: str
    status_title: str
    hold_reason: str | None
    source_text: str
    created_at: datetime
    parse_meta: dict[str, Any]
    items: list[ItemOut] = []
    quotes: list[QuoteOut] = []
    journal: list[JournalOut] = []


def to_out(p: Procurement, db: Session | None = None) -> ProcurementOut:
    out = ProcurementOut(
        id=p.id, number=p.number, title=p.title, status=p.status, status_title=TITLES[Status(p.status)],
        hold_reason=p.hold_reason, source_text=p.source_text, created_at=p.created_at, parse_meta=p.parse_meta or {},
    )
    if db is not None:
        out.items = [ItemOut.model_validate(i, from_attributes=True) for i in p.items]
        quotes = db.scalars(select(PriceQuote).where(PriceQuote.procurement_id == p.id).order_by(PriceQuote.id))
        out.quotes = [QuoteOut.model_validate(q, from_attributes=True) for q in quotes]
        rows = db.scalars(select(JournalEntry).where(JournalEntry.procurement_id == p.id).order_by(JournalEntry.seq))
        out.journal = [JournalOut.model_validate(r, from_attributes=True) for r in rows]
    return out


def get_own(db: Session, pid: int, user: User) -> Procurement:
    p = db.get(Procurement, pid)
    if p is None or p.org_id != user.org_id:
        raise err(404, "not_found", "Заявка не найдена.")
    return p


def title_from(text: str) -> str:
    first = next((ln.strip(" -•\t") for ln in text.splitlines() if ln.strip()), "Заявка")
    return first[:80] + ("…" if len(first) > 80 else "")


@router.post("/procurements", response_model=ProcurementOut, status_code=201)
async def create(
    data: CreateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProcurementOut:
    p = Procurement(org_id=user.org_id, title=data.title or title_from(data.text), source_text=data.text,
                    status=Status.DRAFT, created_by=user.id, parse_meta={})
    db.add(p)
    db.flush()
    p.number = f"СН-{p.id:06d}"
    journal.record(db, org_id=p.org_id, procurement_id=p.id, action="created", actor_kind="human",
                   actor_user_id=user.id, details={"number": p.number, "chars": len(data.text)})
    db.commit()
    await enqueue("parse_spec", p.id)
    return to_out(p)


@router.get("/procurements", response_model=list[ProcurementOut])
def list_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[ProcurementOut]:
    rows = db.scalars(select(Procurement).where(Procurement.org_id == user.org_id).order_by(Procurement.id.desc()))
    return [to_out(p) for p in rows]


@router.get("/procurements/{pid}", response_model=ProcurementOut)
def get_one(pid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProcurementOut:
    return to_out(get_own(db, pid, user), db)


def editable(p: Procurement) -> None:
    if p.status != Status.SPEC_REVIEW:
        raise err(409, "not_editable", "Спецификацию можно править только на шаге «Проверка спецификации».")


def apply_ktru(item: SpecItem, code: str | None) -> None:
    if code is None:
        item.ktru_code = item.okpd2_code = None
        return
    entry = next((e for e in ktru.catalog() if e["code"] == code), None)
    if entry is None:
        raise err(422, "unknown_ktru", f"Кода {code} нет в справочнике.")
    item.ktru_code, item.okpd2_code = entry["code"], entry["okpd2"]


@router.patch("/procurements/{pid}/items/{item_id}", response_model=ProcurementOut)
def edit_item(pid: int, item_id: int, data: ItemIn, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)) -> ProcurementOut:
    p = get_own(db, pid, user)
    editable(p)
    item = db.get(SpecItem, item_id)
    if item is None or item.procurement_id != p.id:
        raise err(404, "not_found", "Позиция не найдена.")
    changes = data.model_dump(exclude_unset=True)
    for field in ("name", "characteristics", "quantity", "unit"):
        if field in changes:
            setattr(item, field, changes[field])
    if "ktru_code" in changes:
        apply_ktru(item, changes["ktru_code"])
    # Человек поправил — вопросы, на которые он ответил полем, снимаем
    item.questions = [q for q in item.questions
                      if not ((q.startswith("Сколько") and item.quantity) or (q.startswith("В каких") and item.unit)
                              or ("ktru_code" in changes and item.ktru_code and q in (item.ktru_suggestion or {}).get(
                                  "question", "")))]
    if not item.problems and not item.questions:
        item.status = "ok"
    journal.record(db, org_id=p.org_id, procurement_id=p.id, action="spec_item_edited", actor_kind="human",
                   actor_user_id=user.id, details={"line_no": item.line_no, "fields": sorted(changes)})
    db.commit()
    return to_out(p, db)


@router.post("/procurements/{pid}/items", response_model=ProcurementOut)
def add_item(pid: int, data: ItemIn, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)) -> ProcurementOut:
    p = get_own(db, pid, user)
    editable(p)
    if not data.name:
        raise err(422, "name_required", "Укажите наименование.")
    item = SpecItem(procurement_id=p.id, line_no=max((i.line_no for i in p.items), default=0) + 1, name=data.name,
                    characteristics=data.characteristics, quantity=data.quantity, unit=data.unit,
                    ktru_candidates=ktru.candidates(data.name), problems=[], notes=["добавлено вручную"],
                    questions=[], status="ok")
    apply_ktru(item, data.ktru_code)
    db.add(item)
    journal.record(db, org_id=p.org_id, procurement_id=p.id, action="spec_item_added", actor_kind="human",
                   actor_user_id=user.id, details={"line_no": item.line_no})
    db.commit()
    db.refresh(p)
    return to_out(p, db)


@router.delete("/procurements/{pid}/items/{item_id}", response_model=ProcurementOut)
def delete_item(pid: int, item_id: int, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)) -> ProcurementOut:
    p = get_own(db, pid, user)
    editable(p)
    item = db.get(SpecItem, item_id)
    if item is None or item.procurement_id != p.id:
        raise err(404, "not_found", "Позиция не найдена.")
    db.delete(item)
    journal.record(db, org_id=p.org_id, procurement_id=p.id, action="spec_item_deleted", actor_kind="human",
                   actor_user_id=user.id, details={"line_no": item.line_no, "name": item.name})
    db.commit()
    db.refresh(p)
    return to_out(p, db)


def blockers(p: Procurement) -> list[str]:
    """Что мешает подтвердить спецификацию. Проверяет код."""
    out = []
    if not p.items:
        out.append("В спецификации нет позиций")
    for i in p.items:
        if i.quantity is None or i.unit is None:
            out.append(f"Позиция {i.line_no}: не указано количество или единица")
        if i.ktru_code is None:
            out.append(f"Позиция {i.line_no}: не выбран код КТРУ")
    return out


@router.post("/procurements/{pid}/confirm-spec", response_model=ProcurementOut)
async def confirm_spec(
    pid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProcurementOut:
    """✋ Первая точка утверждения: человек подтверждает спецификацию, агент идёт искать поставщиков."""
    p = get_own(db, pid, user)
    problems = blockers(p)
    if problems:
        raise err(422, "spec_incomplete", "; ".join(problems))
    try:
        transition(db, p, Status.SOURCING, actor_kind="human", user=user,
                   details={"positions": len(p.items), "ktru": [i.ktru_code for i in p.items]})
    except TransitionError as e:
        raise err(409, "bad_transition", str(e)) from e
    db.commit()
    await enqueue("collect_site_prices", p.id)
    return to_out(p, db)


@router.get("/ktru")
def ktru_catalog(user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    return [{k: e[k] for k in ("code", "okpd2", "name")} for e in ktru.catalog()]


@router.get("/journal/verify")
def verify(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    res = journal.verify_chain(db, user.org_id)
    return {"ok": res.ok, "checked": res.checked, "broken_seq": res.broken_seq, "reason": res.reason}
