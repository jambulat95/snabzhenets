"""Сессии в Redis и защита входа от перебора (перенос из A2A Маркет, backend/app/auth/sessions.py)."""

import secrets

from ..config import settings
from ..redis_client import redis_client

SESSION_PREFIX = "session:"
FAIL_PREFIX = "login_fail:"
RATE_PREFIX = "login_rate:"
LOOPBACK = {"127.0.0.1", "::1"}


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    redis_client.setex(SESSION_PREFIX + token, settings.session_ttl_hours * 3600, user_id)
    return token


def get_session_user_id(token: str) -> int | None:
    value = redis_client.get(SESSION_PREFIX + token)
    return int(value) if value else None  # type: ignore[arg-type]


def delete_session(token: str) -> None:
    redis_client.delete(SESSION_PREFIX + token)


def rate_exceeded(kind: str, value: str, limit: int, window_seconds: int = 60) -> bool:
    key = f"{RATE_PREFIX}{kind}:{value}"
    count = int(redis_client.incr(key))  # type: ignore[arg-type]
    if count == 1:
        redis_client.expire(key, window_seconds)
    return count > limit


def ip_rate_limited(ip: str) -> bool:
    return ip not in LOOPBACK and rate_exceeded("ip", ip, settings.login_rate_per_ip)


def user_failures_exceeded(email: str) -> bool:
    count = redis_client.get(f"{RATE_PREFIX}user_fail:{email}")
    return count is not None and int(count) >= settings.login_user_fail_limit  # type: ignore[arg-type]


def _key(email: str, ip: str) -> str:
    return f"{FAIL_PREFIX}{email}:{ip}"


def is_locked(email: str, ip: str) -> bool:
    count = redis_client.get(_key(email, ip))
    return count is not None and int(count) >= settings.login_max_attempts  # type: ignore[arg-type]


def register_failure(email: str, ip: str) -> None:
    for key in (_key(email, ip), f"{RATE_PREFIX}user_fail:{email}"):
        if int(redis_client.incr(key)) == 1:  # type: ignore[arg-type]
            redis_client.expire(key, settings.login_lock_minutes * 60)


def reset_failures(email: str, ip: str) -> None:
    redis_client.delete(_key(email, ip))
