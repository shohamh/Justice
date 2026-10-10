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


def issue_refresh_token(
    *,
    user_id: uuid.UUID,
    token_version: int = 1,
    lifetime_seconds: int | None = None,
    session_id: str | None = None,
    persist: bool = True,
) -> str:
    """Issue a refresh token.

    ``jti`` is unique per token, so a logout can revoke exactly the presented
    token (app.auth.refresh_revocation). ``sid`` identifies the login session
    (one browser/device) and is carried over on rotation via ``session_id``,
    so a logout also revokes a token rotated from the same session by a
    refresh that raced the logout. A fresh login passes no ``session_id`` and
    starts a new session.

    ``persist`` records whether the login chose a persistent cookie ("remember
    me") or a browser-session cookie; ``/auth/refresh`` reads it back and
    passes it on so rotation never turns a session login into a remembered one.
    A persistent token lives ``refresh_token_days`` (90 by default); a
    non-persistent one only ``session_refresh_token_hours`` (12 by default),
    renewed on every rotation (sliding). Tokens issued before this claim existed have none and are treated as
    persistent (see ``token_persists``), which keeps their old behavior.
    """
    settings = get_settings()
    if lifetime_seconds is None:
        lifetime_seconds = (
            settings.refresh_token_days * 24 * 3600
            if persist
            else settings.session_refresh_token_hours * 3600
        )
    exp = _now() + timedelta(seconds=lifetime_seconds)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "tv": token_version,
        "jti": uuid.uuid4().hex,
        "sid": session_id or uuid.uuid4().hex,
        "persist": persist,
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def token_persists(payload: dict[str, Any]) -> bool:
    """Whether a refresh token's cookie should be persistent. Missing claim -> True."""
    return payload.get("persist") is not False


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise InvalidToken(str(exc)) from exc
