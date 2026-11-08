"""Напоминания поставщикам, которые не ответили за REMIND_AFTER_H часов (по часам заявки — с демо-сдвигом)."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import now
from ..models import Candidate, Organization, Procurement
from ..pipeline import Status
from .outbox import queue_reminder

REMIND_AFTER_H = 24


def tick(db: Session) -> int:
    n = 0
    for proc in db.scalars(select(Procurement).where(Procurement.status == Status.COLLECTING)):
        org = db.get(Organization, proc.org_id)
        assert org is not None
        for c in db.scalars(select(Candidate).where(Candidate.procurement_id == proc.id,
                                                    Candidate.request_status == "sent")):
            if c.last_sent_at and now(proc) - c.last_sent_at >= timedelta(hours=REMIND_AFTER_H):
                queue_reminder(db, proc, org, c)
                n += 1
    db.commit()
    return n
