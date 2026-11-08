"""Машина состояний заявки (docs/ARCHITECTURE.md, раздел 2).

Смена состояния — только через transition(): проверка перехода и прав, запись в журнал, изменение —
в одной транзакции (CLAUDE.md, 3.3). Две точки утверждения — только человек (CLAUDE.md, 1.5).
"""

from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import journal
from .models import Procurement, User


class Status(StrEnum):
    DRAFT = "draft"  # создана, агент разбирает текст
    SPEC_REVIEW = "spec_review"  # ✋ человек проверяет спецификацию
    SOURCING = "sourcing"  # поиск и проверка поставщиков
    COLLECTING = "collecting"  # сбор цен: сайты, запросы, ответы
    ANALYSIS = "analysis"  # проверки методики
    JUSTIFICATION_REVIEW = "justification_review"  # ✋ человек проверяет обоснование
    APPROVED = "approved"
    CLOSED = "closed"
    NEEDS_HUMAN = "needs_human"  # эскалация с причиной
    CANCELLED = "cancelled"


TITLES: dict[Status, str] = {
    Status.DRAFT: "Разбор заявки",
    Status.SPEC_REVIEW: "Проверка спецификации",
    Status.SOURCING: "Поиск поставщиков",
    Status.COLLECTING: "Сбор цен",
    Status.ANALYSIS: "Проверка по методике",
    Status.JUSTIFICATION_REVIEW: "Проверка обоснования",
    Status.APPROVED: "Утверждено",
    Status.CLOSED: "Закрыто",
    Status.NEEDS_HUMAN: "Нужен человек",
    Status.CANCELLED: "Отменено",
}

S = Status
ALLOWED: dict[Status, set[Status]] = {
    S.DRAFT: {S.SPEC_REVIEW},
    S.SPEC_REVIEW: {S.SOURCING, S.DRAFT},  # DRAFT — разобрать заново после правки текста
    S.SOURCING: {S.COLLECTING, S.SPEC_REVIEW},
    S.COLLECTING: {S.ANALYSIS},
    S.ANALYSIS: {S.JUSTIFICATION_REVIEW, S.COLLECTING},  # COLLECTING — мало цен, расширить список
    S.JUSTIFICATION_REVIEW: {S.APPROVED, S.COLLECTING},
    S.APPROVED: {S.CLOSED},
    S.CLOSED: set(),
    S.CANCELLED: set(),
    S.NEEDS_HUMAN: set(),  # выход — только resume() в сохранённое состояние
}
# Отменить или передать человеку можно из любого незавершённого состояния
FINAL = {S.APPROVED, S.CLOSED, S.CANCELLED}
# Эти переходы делает только человек — две обязательные точки утверждения
HUMAN_ONLY: dict[tuple[Status, Status], set[str]] = {
    (S.SPEC_REVIEW, S.SOURCING): {"initiator", "contract_manager", "admin"},
    (S.JUSTIFICATION_REVIEW, S.APPROVED): {"contract_manager"},
}


class TransitionError(Exception):
    pass


def check(frm: Status, to: Status, actor_kind: str, role: str | None) -> None:
    """Можно ли перейти. Чистая функция: проверяется в тестах без базы."""
    if to == S.NEEDS_HUMAN or to == S.CANCELLED:
        if frm in FINAL or frm == to:
            raise TransitionError(f"Из состояния «{TITLES[frm]}» нельзя перейти в «{TITLES[to]}»")
        if to == S.CANCELLED and actor_kind != "human":
            raise TransitionError("Отменить заявку может только человек")
        return
    if to not in ALLOWED[frm]:
        raise TransitionError(f"Переход «{TITLES[frm]}» → «{TITLES[to]}» не предусмотрен")
    roles = HUMAN_ONLY.get((frm, to))
    if roles is not None and (actor_kind != "human" or role not in roles):
        raise TransitionError(f"Переход «{TITLES[frm]}» → «{TITLES[to]}» подтверждает человек с нужной ролью")


def transition(
    db: Session,
    proc: Procurement,
    to: Status,
    *,
    actor_kind: str,
    user: User | None = None,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Сменить состояние заявки и записать это в журнал. Коммит — у вызывающего вместе с действием."""
    # Блокировка строки: два воркера не переведут заявку одновременно
    db.execute(select(Procurement.id).where(Procurement.id == proc.id).with_for_update())
    db.refresh(proc)
    frm = Status(proc.status)
    check(frm, to, actor_kind, user.role if user else None)
    if to == S.NEEDS_HUMAN:
        proc.resume_status = frm
        proc.hold_reason = reason
    proc.status = to
    journal.record(
        db, org_id=proc.org_id, procurement_id=proc.id, action="status", actor_kind=actor_kind,
        actor_user_id=user.id if user else None, decision=to,
        details={"from": frm, "to": to, **({"reason": reason} if reason else {}), **(details or {})},
    )


def resume(db: Session, proc: Procurement, user: User, note: str | None = None) -> None:
    """Человек снял эскалацию: заявка возвращается туда, откуда ушла."""
    if proc.status != S.NEEDS_HUMAN or proc.resume_status is None:
        raise TransitionError("Заявка не ждёт человека")
    back = Status(proc.resume_status)
    proc.status, proc.resume_status, proc.hold_reason = back, None, None
    journal.record(
        db, org_id=proc.org_id, procurement_id=proc.id, action="status", actor_kind="human",
        actor_user_id=user.id, decision=back,
        details={"from": S.NEEDS_HUMAN, "to": back, **({"note": note} if note else {})},
    )
