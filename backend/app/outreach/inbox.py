"""Входящие письма: ящик учреждения → письмо и вложения как доказательства → привязка к заявке и поставщику."""

import re
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import journal
from ..ai.screening import detect_injection
from ..clock import now
from ..config import settings
from ..evidence import store
from ..integrations.mail import port as mail
from ..models import Candidate, InboundMessage, Organization, OutboundMessage, Procurement, Supplier

TAG = re.compile(r"\[(СН-\d{6})\]")


def text_of(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = part.get_content()
    if part.get_content_type() == "text/html":
        content = re.sub(r"<[^>]+>", " ", content)
    return str(content).strip()


def match(db: Session, msg: EmailMessage, sender: str) -> tuple[Procurement | None, Candidate | None]:
    reply_to = (msg.get("In-Reply-To") or "").strip()
    if reply_to:
        out = db.scalar(select(OutboundMessage).where(OutboundMessage.message_id == reply_to))
        if out is not None:
            cand = db.get(Candidate, out.candidate_id) if out.candidate_id else None
            return db.get(Procurement, out.procurement_id), cand
    tag = TAG.search(str(msg.get("Subject") or ""))
    if tag:
        proc = db.scalar(select(Procurement).where(Procurement.number == tag.group(1)))
        if proc is not None:
            cand = db.scalar(select(Candidate).join(Supplier).where(Candidate.procurement_id == proc.id,
                                                                    Supplier.email == sender))
            return proc, cand
    return None, None


def receive(db: Session, raw: bytes) -> InboundMessage | None:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    assert isinstance(msg, EmailMessage)
    message_id = str(msg.get("Message-ID") or "").strip() or f"<no-id-{hash(raw)}>"
    if db.scalar(select(InboundMessage.id).where(InboundMessage.message_id == message_id)) is not None:
        return None
    sender = parseaddr(str(msg.get("From") or ""))[1].lower()
    proc, cand = match(db, msg, sender)
    org = db.get(Organization, proc.org_id) if proc else db.scalar(select(Organization).limit(1))
    assert org is not None
    try:
        received = parsedate_to_datetime(str(msg["Date"])) if msg["Date"] else datetime.now(UTC)
    except (TypeError, ValueError):
        received = datetime.now(UTC)
    pid = proc.id if proc else None
    raw_ev = store.save(db, org_id=org.id, procurement_id=pid, data=raw, kind="email", url=None,
                        captured_at=received, meta={"from": sender, "subject": str(msg.get("Subject") or "")})
    attachments = []
    for part in msg.iter_attachments():
        data = part.get_content()
        payload = data if isinstance(data, bytes) else str(data).encode("utf-8")
        ev = store.save(db, org_id=org.id, procurement_id=pid, data=payload, kind="attachment", url=None,
                        captured_at=received, meta={"filename": part.get_filename(), "from": sender})
        attachments.append({"filename": part.get_filename(), "content_type": part.get_content_type(),
                            "sha256": ev.sha256, "size": len(payload)})
    body = text_of(msg)
    inbound = InboundMessage(
        procurement_id=pid, candidate_id=cand.id if cand else None, from_email=sender,
        subject=str(msg.get("Subject") or "")[:300], message_id=message_id,
        in_reply_to=(str(msg.get("In-Reply-To") or "").strip() or None), received_at=received, body_text=body,
        attachments=attachments, evidence_sha256=raw_ev.sha256, kind="new" if proc else "unmatched",
        status="new", suspicious=detect_injection(body),
    )
    db.add(inbound)
    if cand is not None and proc is not None:
        cand.request_status, cand.replied_at = "replied", now(proc)
    journal.record(db, org_id=org.id, procurement_id=pid, action="mail_received", actor_kind="system",
                   decision="suspicious" if inbound.suspicious else ("matched" if proc else "unmatched"),
                   evidence_sha256=raw_ev.sha256,
                   details={"from": sender, "subject": inbound.subject, "attachments": len(attachments),
                            **({"injection_rules": inbound.suspicious} if inbound.suspicious else {})})
    return inbound


def poll(db: Session) -> int:
    n = 0
    for raw in mail.fetch_unseen(settings.mailbox, settings.mailbox_password):
        if receive(db, raw) is not None:
            n += 1
        db.commit()
    return n
