"""Демо-оператор: сброс сценария перед показом (только DEMO_MODE)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.deps import require_roles
from ..config import settings
from ..db import get_db
from ..models import User
from ..seed import ensure, reset
from . import supplier_sim

router = APIRouter(prefix="/api/demo", tags=["demo"])
operator = require_roles("contract_manager", "admin")


@router.post("/reset")
def demo_reset(user: User = Depends(operator), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Заявки, цены, письма, доказательства и журнал — заново; учётки, поставщики и записанные данные — прежние."""
    if not settings.demo_mode:
        raise HTTPException(403, {"code": "demo_only", "message": "Сброс есть только в демо-режиме."})
    reset(db)
    ensure(db)
    db.commit()
    supplier_sim.reset_state()
    return {"ok": True}
