"""Демо-данные: заказчик ЧГУ и два пользователя.

    uv run python -m app.seed            # создать, если базы пусты; пароли — в backend/demo_accounts.txt
    uv run python -m app.seed --reset    # сбросить демо-сценарий: заявки и журнал заново, учётки прежние

demo_accounts.txt не попадает в git (.gitignore). Пароли генерируются при первом создании.
"""

import secrets
import sys
from pathlib import Path

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Evidence, JournalEntry, Organization, Procurement, User
from .security import hash_password

ACCOUNTS_FILE = Path(__file__).resolve().parents[1] / "demo_accounts.txt"

ORG = {
    "inn": "2020000570",
    "name": "ФГБОУ ВО «Чеченский государственный университет имени А.А. Кадырова»",
    "short_name": "ЧГУ им. А.А. Кадырова",
    "region": "Чеченская Республика",
    "mailbox": "zakupki@demo.local",
}
USERS = [
    ("zakupki@chesu.demo", "Контрактный управляющий (демо)", "contract_manager"),
    ("kafedra@chesu.demo", "Сотрудник кафедры (демо)", "initiator"),
]


def ensure(db: Session) -> list[tuple[str, str, str]]:
    created: list[tuple[str, str, str]] = []
    org = db.scalar(select(Organization).where(Organization.inn == ORG["inn"]))
    if org is None:
        org = Organization(**ORG)
        db.add(org)
        db.flush()
    for email, name, role in USERS:
        if db.scalar(select(User).where(User.email == email)) is None:
            password = secrets.token_urlsafe(12)
            db.add(User(org_id=org.id, email=email, full_name=name, role=role, password_hash=hash_password(password)))
            created.append((email, role, password))
    return created


def reset(db: Session) -> None:
    """Сброс сценария: журнал удаляется только с флагом сессии (триггер append-only, миграция 0002)."""
    db.execute(text("SET LOCAL app.journal_reset = 'on'"))
    db.execute(delete(JournalEntry))
    db.execute(delete(Procurement))
    db.execute(delete(Evidence))


def main() -> None:
    with SessionLocal() as db:
        if "--reset" in sys.argv:
            reset(db)
        created = ensure(db)
        db.commit()
    if created:
        with ACCOUNTS_FILE.open("a", encoding="utf-8") as f:
            for email, role, password in created:
                f.write(f"{email}\t{role}\t{password}\n")
        print(f"Созданы учётки: {', '.join(e for e, _, _ in created)}; пароли — в {ACCOUNTS_FILE.name}")
    else:
        print("Учётки уже есть" + (", сценарий сброшен" if "--reset" in sys.argv else ""))


if __name__ == "__main__":
    main()
