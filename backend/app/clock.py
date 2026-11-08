"""Часы заявки: реальное время + демо-сдвиг «Ускорить время» (таймеры напоминаний и срока сбора)."""

from datetime import UTC, datetime, timedelta

from .models import Procurement


def now(proc: Procurement | None = None) -> datetime:
    shift = proc.time_shift_hours if proc is not None else 0
    return datetime.now(UTC) + timedelta(hours=shift or 0)
