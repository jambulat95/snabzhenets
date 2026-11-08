"""API «Снабженца». Роутеры доменных модулей подключаются здесь по мере готовности (docs/PLAN.md)."""

from fastapi import FastAPI
from sqlalchemy import create_engine, text

from .auth.router import router as auth_router
from .config import settings
from .evidence.router import router as evidence_router
from .redis_client import redis_client
from .spec.router import router as spec_router

app = FastAPI(title="Снабженец", version="0.1.0")
app.include_router(auth_router)
app.include_router(spec_router)
app.include_router(evidence_router)
_engine = create_engine(settings.database_url, pool_pre_ping=True)


@app.get("/api/health")
def health() -> dict[str, object]:
    """Живы ли база и Redis; в демо-режиме ли сервис."""
    status: dict[str, object] = {"demo_mode": settings.demo_mode}
    try:
        with _engine.connect() as c:
            c.execute(text("select 1"))
        status["db"] = "ok"
    except Exception as e:  # noqa: BLE001 — здоровье показывает причину, а не падает
        status["db"] = f"error: {type(e).__name__}"
    try:
        redis_client.ping()
        status["redis"] = "ok"
    except Exception as e:  # noqa: BLE001
        status["redis"] = f"error: {type(e).__name__}"
    return status
