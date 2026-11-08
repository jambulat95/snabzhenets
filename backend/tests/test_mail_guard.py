from email.message import EmailMessage

import pytest

from app.config import settings
from app.integrations.mail import port as mail


def msg(to: str) -> EmailMessage:
    m = EmailMessage()
    m["From"] = "zakupki@demo.local"
    m["To"] = to
    m["Subject"] = "тест"
    m.set_content("тест")
    return m


def test_demo_mode_blocks_real_addresses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "demo_mode", True)
    sent: list[EmailMessage] = []
    monkeypatch.setattr(mail.smtplib, "SMTP", lambda *a, **k: (_ for _ in ()).throw(AssertionError("SMTP вызван")))
    for address in ("sales@regard.ru", "info@example.com", "x@demo.local.evil.ru", "a@demo.local, b@gmail.com"):
        with pytest.raises(mail.MailBlocked):
            mail.send(msg(address))
    assert sent == []


def test_demo_addresses_allowed() -> None:
    assert mail.allowed("grozny-office@demo.local")
    assert mail.allowed("  Musaev@Demo.Local ")
    assert not mail.allowed("demo.local@gmail.com")
