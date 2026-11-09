"""Хранилище доказательств: файл по sha256 + строка Evidence + запись в журнале (CLAUDE.md, 1.3).

Подмена файла после записи обнаруживается: хеш файла перестаёт совпадать с хешем в журнале,
а запись журнала защищена цепочкой хешей.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import journal
from ..config import settings
from ..models import Evidence, JournalEntry

EXT = {"screenshot": "jpg", "html": "html", "email": "eml", "attachment": "bin", "document": "docx"}


def root() -> Path:
    return Path(settings.storage_dir)


def path_for(sha: str, kind: str) -> Path:
    return root() / sha[:2] / f"{sha}.{EXT.get(kind, 'bin')}"


def save(
    db: Session,
    *,
    org_id: int,
    procurement_id: int | None,
    data: bytes,
    kind: str,
    url: str | None,
    captured_at: datetime,
    meta: dict[str, Any] | None = None,
) -> Evidence:
    """Сохранить файл (если такого ещё нет) и записать в журнал факт доказательства для заявки."""
    sha = hashlib.sha256(data).hexdigest()
    ev = db.scalar(select(Evidence).where(Evidence.sha256 == sha))
    if ev is None:
        p = path_for(sha, kind)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(data)
        ev = Evidence(sha256=sha, kind=kind, url=url, captured_at=captured_at, path=str(p.relative_to(root())),
                      meta=meta or {})
        db.add(ev)
        db.flush()
    journal.record(
        db, org_id=org_id, procurement_id=procurement_id, action="evidence_saved", actor_kind="agent",
        evidence_sha256=sha, input_ref=url,
        details={"kind": kind, "bytes": len(data), "captured_at": captured_at.isoformat(), **(meta or {})},
    )
    return ev


@dataclass
class Check:
    ok: bool
    file_sha256: str | None
    in_journal: bool
    reason: str | None


def verify(db: Session, ev: Evidence) -> Check:
    """Файл на месте и его хеш совпадает; хеш записан в журнале."""
    p = root() / ev.path
    if not p.exists():
        return Check(False, None, False, "Файл доказательства не найден")
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    found = db.scalar(select(JournalEntry.id).where(JournalEntry.evidence_sha256 == ev.sha256).limit(1))
    in_journal = found is not None
    if actual != ev.sha256:
        return Check(False, actual, in_journal, "Файл изменён после записи: хеш не совпадает")
    if not in_journal:
        return Check(False, actual, False, "Хеш не найден в журнале")
    return Check(True, actual, True, None)
