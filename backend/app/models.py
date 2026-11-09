"""Модель данных «Снабженца» (docs/ARCHITECTURE.md, раздел 4). Деньги и количества — Numeric/Decimal."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Organization(Base):
    """Заказчик: учреждение, от имени которого идут запросы."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    inn: Mapped[str] = mapped_column(String(12), unique=True)
    kpp: Mapped[str | None] = mapped_column(String(9))
    name: Mapped[str] = mapped_column(String(300))
    short_name: Mapped[str] = mapped_column(String(100))
    region: Mapped[str] = mapped_column(String(100))
    mailbox: Mapped[str] = mapped_column(String(200))  # ящик, с которого уходят запросы


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    # initiator — сотрудник подразделения; contract_manager — контрактная служба, утверждает; admin — настройки
    role: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    org: Mapped[Organization] = relationship()


class Procurement(Base):
    """Заявка: от текста сотрудника до утверждённого обоснования НМЦК."""

    __tablename__ = "procurements"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    number: Mapped[str | None] = mapped_column(String(20), unique=True)  # СН-000001
    title: Mapped[str] = mapped_column(String(200))
    source_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), index=True)  # pipeline.Status
    # Состояние, в которое вернуться после NEEDS_HUMAN
    resume_status: Mapped[str | None] = mapped_column(String(30))
    hold_reason: Mapped[str | None] = mapped_column(Text)
    profile: Mapped[str] = mapped_column(String(40), default="mer567_v1")  # профиль методики
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    collect_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Что агент вынес из текста помимо позиций: срок, требования, строки, которые могли потеряться
    parse_meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Демо: «Ускорить время» сдвигает часы заявки (таймеры напоминаний и срока сбора)
    time_shift_hours: Mapped[int] = mapped_column(Integer, default=0)
    # Последний расчёт по методике (methodology.engine): вердикты, средние, CV, НМЦК
    analysis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    items: Mapped[list["SpecItem"]] = relationship(
        back_populates="procurement", order_by="SpecItem.line_no", cascade="all, delete-orphan"
    )


class SpecItem(Base):
    """Позиция спецификации."""

    __tablename__ = "spec_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    procurement_id: Mapped[int] = mapped_column(ForeignKey("procurements.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(500))
    characteristics: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    unit: Mapped[str | None] = mapped_column(String(20))
    ktru_code: Mapped[str | None] = mapped_column(String(30))
    okpd2_code: Mapped[str | None] = mapped_column(String(20))
    # Кандидаты КТРУ из справочника (код, название, балл) и выбор модели — подсказка человеку
    ktru_candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    ktru_suggestion: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok / needs_review
    problems: Mapped[list[str]] = mapped_column(JSON, default=list)  # блокируют подтверждение
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    questions: Mapped[list[str]] = mapped_column(JSON, default=list)  # что уточнить у инициатора
    source: Mapped[str | None] = mapped_column(Text)  # строка заявки, откуда позиция

    procurement: Mapped[Procurement] = relationship(back_populates="items")


class Evidence(Base):
    """Доказательство: файл в хранилище по sha256 (снимок страницы, HTML, письмо, вложение)."""

    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(20))  # screenshot / html / email / attachment
    url: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    path: Mapped[str] = mapped_column(String(300))
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class JournalEntry(Base):
    """Запись журнала. Только добавление: UPDATE и DELETE запрещены триггером (кроме сброса демо)."""

    __tablename__ = "journal"
    __table_args__ = (UniqueConstraint("org_id", "seq"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # номер в цепочке организации
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    procurement_id: Mapped[int | None] = mapped_column(ForeignKey("procurements.id"), index=True)
    actor_kind: Mapped[str] = mapped_column(String(10))  # human / agent / system
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(50))
    input_ref: Mapped[str | None] = mapped_column(String(200))
    decision: Mapped[str | None] = mapped_column(String(30))
    rule_code: Mapped[str | None] = mapped_column(String(20), index=True)
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    tokens: Mapped[int | None] = mapped_column(Integer)
    cost_rub: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class PriceQuote(Base):
    """Цена по позиции из одного источника (сайт, письмо, контракт ЕИС) — с доказательством."""

    __tablename__ = "price_quotes"

    id: Mapped[int] = mapped_column(primary_key=True)
    procurement_id: Mapped[int] = mapped_column(ForeignKey("procurements.id", ondelete="CASCADE"), index=True)
    spec_item_id: Mapped[int] = mapped_column(ForeignKey("spec_items.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(20))  # site / email / eis_contract
    source_name: Mapped[str] = mapped_column(String(200))  # магазин или поставщик
    source_key: Mapped[str | None] = mapped_column(String(50))
    region: Mapped[str | None] = mapped_column(String(100))
    offer_name: Mapped[str | None] = mapped_column(String(500))  # как товар назван в источнике
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    vat_mode: Mapped[str] = mapped_column(String(20))  # with / without / unknown
    price_kind: Mapped[str | None] = mapped_column(String(30))  # розничная / для юрлиц
    url: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # когда цена зафиксирована
    extracted_by: Mapped[str] = mapped_column(String(30))  # json-ld / microdata / letter …
    html_sha256: Mapped[str | None] = mapped_column(String(64))
    screenshot_sha256: Mapped[str | None] = mapped_column(String(64))
    # Сверка «тот ли товар» (модель) и итог: ok — в расчёт, rejected — нет, review — решает человек
    match: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20))
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Исходный документ цены, кроме страницы сайта: письмо (исходник .eml) или вложение
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id", ondelete="SET NULL"))
    # Решение человека поверх автоматики: include / exclude, с причиной (CLAUDE.md, 1.5)
    human_decision: Mapped[str | None] = mapped_column(String(10))
    human_reason: Mapped[str | None] = mapped_column(Text)


class Supplier(Base):
    """Поставщик: найден в ЕИС (контракты), в истории заказчика или в демо-справочнике."""

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)  # ИНН или ключ демо-поставщика
    inn: Mapped[str | None] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(300))
    region: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(300))
    founders: Mapped[list[str]] = mapped_column(JSON, default=list)
    egrul_status: Mapped[str | None] = mapped_column(String(20))  # active / liquidating / liquidated
    in_rnp: Mapped[bool] = mapped_column(Boolean, default=False)
    contracts_44fz_3y: Mapped[int] = mapped_column(Integer, default=0)
    okpd2: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(20))  # eis / demo
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Candidate(Base):
    """Поставщик в заявке: что покрывает, откуда найден, проверки, выбран ли и почему."""

    __tablename__ = "candidates"
    __table_args__ = (UniqueConstraint("procurement_id", "supplier_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    procurement_id: Mapped[int] = mapped_column(ForeignKey("procurements.id", ondelete="CASCADE"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    item_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # [{code, verdict, reason}]
    verdict: Mapped[str] = mapped_column(String(10))  # allow / warn / human / deny
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str | None] = mapped_column(Text)
    request_status: Mapped[str] = mapped_column(String(20), default="none")  # none/queued/sent/reminded/replied
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    supplier: Mapped[Supplier] = relationship()


class OutboundMessage(Base):
    """Исходящее письмо (outbox): пишется в транзакции шага, отправляется отдельной задачей."""

    __tablename__ = "outbound_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    procurement_id: Mapped[int] = mapped_column(ForeignKey("procurements.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))  # request / reminder / answer
    to_email: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    message_id: Mapped[str] = mapped_column(String(200), unique=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued / sent / blocked / failed
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InboundMessage(Base):
    """Входящее письмо: исходник — доказательство (sha256), разбор — дальше по конвейеру."""

    __tablename__ = "inbound_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    procurement_id: Mapped[int | None] = mapped_column(ForeignKey("procurements.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    from_email: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(300))
    message_id: Mapped[str] = mapped_column(String(200), unique=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(200))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    body_text: Mapped[str] = mapped_column(Text)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    evidence_sha256: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20), default="new")  # offer / question / other / unmatched
    status: Mapped[str] = mapped_column(String(20), default="new")  # new / parsed / needs_human
    suspicious: Mapped[list[str]] = mapped_column(JSON, default=list)
