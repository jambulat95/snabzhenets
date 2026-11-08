from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from .sessions import get_session_user_id

COOKIE_NAME = "session"


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    user_id = get_session_user_id(token) if token else None
    user = db.get(User, user_id) if user_id else None
    if user is None or not user.is_active:
        raise HTTPException(401, {"code": "not_authenticated", "message": "Войдите в систему."})
    return user


def require_roles(*roles: str) -> Callable[[User], User]:
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, {"code": "forbidden", "message": "Недостаточно прав для этого действия."})
        return user

    return dependency
