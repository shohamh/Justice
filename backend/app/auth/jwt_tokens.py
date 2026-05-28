from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt

from app.settings import get_settings


class InvalidToken(Exception):
    """Raised when a token cannot be decoded or has expired."""


def _now() -> datetime:
    return datetime.now(tz=UTC)


def issue_access_token(
    *, user_id: uuid.UUID, role: str, lifetime_seconds: int | None = None
) -> str:
    settings = get_settings()
    if lifetime_seconds is None:
        lifetime_seconds = settings.access_token_minutes * 60
    exp = _now() + timedelta(seconds=lifetime_seconds)
    payload = {"sub": str(user_id), "role": role, "type": "access", "exp": int(exp.timestamp())}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def issue_refresh_token(*, user_id: uuid.UUID, lifetime_seconds: int | None = None) -> str:
    settings = get_settings()
    if lifetime_seconds is None:
        lifetime_seconds = settings.refresh_token_days * 24 * 3600
    exp = _now() + timedelta(seconds=lifetime_seconds)
    payload = {"sub": str(user_id), "type": "refresh", "exp": int(exp.timestamp())}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise InvalidToken(str(exc)) from exc
