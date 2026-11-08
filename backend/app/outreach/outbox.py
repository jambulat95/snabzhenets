"""Outbox: письма создаются в транзакции шага, отправляются задачей send_queued (повтор не шлёт дважды).

Юридически значимый текст — только из шаблонов Jinja, без генерации моделью (CLAUDE.md, 1.4).
"""

import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import journal
from ..clock import now
from ..config import settings
from ..integrations.mail import port as mail
from ..models import Candidate, Organization, OutboundMessage, Procurement

_env = Environment(loader=FileSystemLoader(Path(__file__).with_name("templates")), autoescape=False,
                   keep_trailing_newline=True)
REPLY_DAYS = 2
KIND_HEADER = "X-Snabzhenets-Kind"


def qty(v: Any) -> str:
    s = f"{v:f}".rstrip("0").rstrip(".") if v is not None else "?"
    return s.replace(".", ",")


def _message_id() -> str:
    return f"<{uuid.uuid4().hex}@{settings.demo_mail_domain if settings.demo_mode else 'snabzhenets'}>"


def queue_requests(db: Session, proc: Procurement, org: Organization, cands: list[Candidate]) -> int:
    reply_by = (now(proc) + timedelta(days=REPLY_DAYS)).strftime("%d.%m.%Y")
    n = 0
    for c in cands:
        items = [i for i in proc.items if i.id in c.item_ids]
        body = _env.get_template("request.txt.j2").render(
            org=org, number=proc.number, reply_by=reply_by, city="Грозный",
            deadline_raw=(proc.parse_meta or {}).get("deadline_raw"),
            items=[{"name": i.name, "qty": qty(i.quantity), "unit": i.unit, "ktru_code": i.ktru_code} for i in items],
        )
        db.add(OutboundMessage(
            procurement_id=proc.id, candidate_id=c.id, kind="request", to_email=c.supplier.email or "",
            subject=f"Запрос ценовой информации [{proc.number}]", body=body, message_id=_message_id(),
        ))
        c.request_status = "queued"
        n += 1
    return n


def queue_reminder(db: Session, proc: Procurement, org: Organization, c: Candidate) -> None:
    first = db.scalar(select(OutboundMessage).where(OutboundMessage.candidate_id == c.id,
                                                    OutboundMessage.kind == "request"))
    assert first is not None
    body = _env.get_template("reminder.txt.j2").render(
        org=org, number=proc.number, sent_on=(first.sent_at or first.created_at).strftime("%d.%m.%Y"),
        reply_by=(now(proc) + timedelta(days=1)).strftime("%d.%m.%Y"),
    )
    db.add(OutboundMessage(procurement_id=proc.id, candidate_id=c.id, kind="reminder", to_email=first.to_email,
                           subject=f"Напоминание: запрос ценовой информации [{proc.number}]", body=body,
                           message_id=_message_id(), in_reply_to=first.message_id))
    c.request_status = "reminded"


def queue_answer(db: Session, proc: Procurement, c: Candidate, to: str, in_reply_to: str, subject: str,
                 body: str) -> None:
    db.add(OutboundMessage(procurement_id=proc.id, candidate_id=c.id, kind="answer", to_email=to,
                           subject=subject if subject.lower().startswith("re:") else f"Re: {subject}", body=body,
                           message_id=_message_id(), in_reply_to=in_reply_to))


def to_email(m: OutboundMessage, org: Organization) -> EmailMessage:
    e = EmailMessage()
    e["From"] = org.mailbox
    e["To"] = m.to_email
    e["Subject"] = m.subject
    e["Message-ID"] = m.message_id
    e["Date"] = format_datetime(datetime.now(UTC))
    e[KIND_HEADER] = m.kind
    if m.in_reply_to:
        e["In-Reply-To"] = m.in_reply_to
        e["References"] = m.in_reply_to
    e.set_content(m.body)
    return e


def send_queued(db: Session) -> int:
    rows = db.scalars(select(OutboundMessage).where(OutboundMessage.status == "queued").order_by(OutboundMessage.id))
    sent = 0
    for m in list(rows):
        proc = db.get(Procurement, m.procurement_id)
        assert proc is not None
        org = db.get(Organization, proc.org_id)
        assert org is not None
        c = db.get(Candidate, m.candidate_id) if m.candidate_id else None
        try:
            mail.send(to_email(m, org))
            m.status, m.sent_at = "sent", datetime.now(UTC)
            if c is not None and m.kind in ("request", "reminder"):
                c.last_sent_at = now(proc)
                if m.kind == "request":
                    c.request_status = "sent"
            sent += 1
            decision = "sent"
        except mail.MailBlocked as e:
            m.status, m.error, decision = "blocked", str(e), "blocked"
        except OSError as e:
            m.status, m.error, decision = "failed", f"{type(e).__name__}: {e}", "failed"
        journal.record(db, org_id=proc.org_id, procurement_id=proc.id, action=f"mail_{m.kind}", actor_kind="agent",
                       decision=decision, details={"to": m.to_email, "subject": m.subject, "message_id": m.message_id,
                                                   **({"error": m.error[:200]} if m.error else {})})
        db.commit()
    return sent
