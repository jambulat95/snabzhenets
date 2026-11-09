"""Вход, выход, текущий пользователь (перенос из A2A Маркет, backend/app/auth/router.py; без песочниц)."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import User
from ..security import hash_password, verify_password
from .deps import COOKIE_NAME, get_current_user
from .sessions import (
    create_session,
    delete_session,
    ip_rate_limited,
    is_locked,
    register_failure,
    reset_failures,
    user_failures_exceeded,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Пароль проверяем и для несуществующей почты: по времени ответа не понять, есть ли учётка
_DUMMY_HASH = hash_password("dummy-password-for-timing")

ROLE_TITLES = {
    "initiator": "Инициатор закупки",
    "contract_manager": "Контрактный управляющий",
    "admin": "Администратор",
}


class LoginRequest(BaseModel):
    email: str
    password: str


class MeResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    role_title: str
    org_id: int
    org_name: str
    demo_mode: bool


def to_me(user: User) -> MeResponse:
    return MeResponse(
        id=user.id, email=user.email, full_name=user.full_name, role=user.role,
        role_title=ROLE_TITLES.get(user.role, user.role), org_id=user.org_id, org_name=user.org.short_name,
        demo_mode=settings.demo_mode,
    )


@router.post("/login", response_model=MeResponse)
def login(data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> MeResponse:
    email = data.email.strip().lower()
    ip = request.client.host if request.client else "unknown"
    if ip_rate_limited(ip) or user_failures_exceeded(email):
        raise HTTPException(429, {"code": "rate_limited", "message": "Слишком много попыток входа. Подождите."})
    if is_locked(email, ip):
        raise HTTPException(
            429, {"code": "locked", "message": f"Слишком много неудачных попыток. Попробуйте через "
                  f"{settings.login_lock_minutes} минут."},
        )
    user = db.scalar(select(User).where(User.email == email))
    password_ok = verify_password(user.password_hash if user else _DUMMY_HASH, data.password)
    if user is None or not password_ok or not user.is_active:
        register_failure(email, ip)
        raise HTTPException(401, {"code": "invalid_credentials", "message": "Неверная почта или пароль."})
    reset_failures(email, ip)
    response.set_cookie(
        COOKIE_NAME, create_session(user.id), max_age=settings.session_ttl_hours * 3600,
        httponly=True, secure=settings.cookie_secure, samesite="lax", path="/",
    )
    return to_me(user)


@router.post("/logout", status_code=204)
def logout(request: Request) -> Response:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        delete_session(token)
    resp = Response(status_code=204)
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)) -> MeResponse:
    return to_me(user)
