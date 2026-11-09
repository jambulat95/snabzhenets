"""Доказательства: файл (снимок, HTML) и проверка, что он не изменён после записи."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.deps import get_current_user
from ..db import get_db
from ..models import Evidence, JournalEntry, User
from . import store

router = APIRouter(prefix="/api/evidence", tags=["evidence"])
MEDIA = {"screenshot": "image/jpeg", "html": "text/plain; charset=utf-8", "email": "text/plain; charset=utf-8"}


def get_visible(db: Session, sha: str, user: User) -> Evidence:
    ev = db.scalar(select(Evidence).where(Evidence.sha256 == sha))
    # Доказательство видно организации, в журнале которой оно записано
    seen = db.scalar(select(JournalEntry.id).where(JournalEntry.evidence_sha256 == sha,
                                                   JournalEntry.org_id == user.org_id).limit(1))
    if ev is None or seen is None:
        raise HTTPException(404, {"code": "not_found", "message": "Доказательство не найдено."})
    return ev


@router.get("/{sha}/file", response_model=None)
def file(sha: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    ev = get_visible(db, sha, user)
    path = store.root() / ev.path
    if ev.kind in ("html", "email"):
        # HTML магазина отдаём как текст, а не страницу: чужие скрипты в нашем окне не исполняются
        return Response(path.read_bytes(), media_type=MEDIA["html"], headers={"Content-Disposition": "inline"})
    return FileResponse(path, media_type=MEDIA.get(ev.kind, "application/octet-stream"))


@router.get("/{sha}/verify")
def verify(sha: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    ev = get_visible(db, sha, user)
    c = store.verify(db, ev)
    return {"ok": c.ok, "sha256": ev.sha256, "file_sha256": c.file_sha256, "in_journal": c.in_journal,
            "reason": c.reason, "url": ev.url, "captured_at": ev.captured_at, "kind": ev.kind}
