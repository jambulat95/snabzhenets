"""Порт почты: SMTP для отправки, IMAP для чтения. В демо-режиме — только адреса @demo.local (CLAUDE.md, 1.6)."""

import imaplib
import smtplib
from email.message import EmailMessage

from ...config import settings


class MailBlocked(Exception):
    """Адрес вне демо-домена при DEMO_MODE=true: письмо не отправляется."""


def allowed(address: str) -> bool:
    if not settings.demo_mode:
        return True
    return address.strip().lower().endswith("@" + settings.demo_mail_domain)


def send(msg: EmailMessage) -> None:
    recipients = [a.strip() for field in ("To", "Cc", "Bcc") for a in (msg.get_all(field) or []) for a in a.split(",")]
    blocked = [r for r in recipients if r and not allowed(r)]
    if blocked:
        raise MailBlocked(f"Демо-режим: письма только на @{settings.demo_mail_domain}, а не {', '.join(blocked)}")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
        s.send_message(msg)


def fetch_unseen(mailbox: str, password: str) -> list[bytes]:
    """Новые письма ящика (помечаются прочитанными)."""
    box = imaplib.IMAP4(settings.imap_host, settings.imap_port, timeout=15)
    try:
        box.login(mailbox, password)
        box.select("INBOX")
        _, data = box.search(None, "UNSEEN")
        out = []
        for num in data[0].split():
            _, parts = box.fetch(num, "(RFC822)")
            for part in parts:
                if isinstance(part, tuple):
                    out.append(part[1])
        return out
    finally:
        try:
            box.logout()
        except Exception:  # noqa: BLE001
            pass
