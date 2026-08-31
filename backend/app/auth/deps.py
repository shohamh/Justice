from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.jwt_tokens import InvalidToken, decode_token
from app.db.models import Soldier
from app.db.session import get_session


def _bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing_token")
    return auth_header.split(" ", 1)[1].strip()


def get_current_user(request: Request, session: Session = Depends(get_session)) -> Soldier:
    token = _bearer_token(request)
    try:
        payload = decode_token(token)
    except InvalidToken as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token"
        ) from exc
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="wrong_token_type")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no_subject")
    user = session.get(Soldier, uuid.UUID(sub))
    if user is None or user.left_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user_not_found")
    request.state.user = user
    return user


def get_optional_current_user(request: Request, session: Session = Depends(get_session)) -> Soldier | None:
    """Resolve a bearer user when present, without rejecting anonymous requests."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token)
        if payload.get("type") != "access" or not payload.get("sub"):
            return None
        user = session.get(Soldier, uuid.UUID(payload["sub"]))
    except (InvalidToken, TypeError, ValueError):
        return None
    if user is None or user.left_at is not None:
        return None
    request.state.user = user
    return user


def require_roles(*roles: str) -> Callable[..., Soldier]:
    """Dependency factory: allow only the given roles (coarse gate, e.g. admin-only)."""

    def _dep(user: Soldier = Depends(get_current_user)) -> Soldier:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        return user

    return _dep


def require_duty_manager_or_admin(
    session: Session = Depends(get_session),
    user: Soldier = Depends(get_current_user),
) -> Soldier:
    """Admin, or a soldier holding at least one DutyManagerScope row."""
    from app.auth.authz import is_duty_manager

    if user.role != "admin" and not is_duty_manager(session, user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return user


def require_password_changed(user: Soldier = Depends(get_current_user)) -> Soldier:
    """Block protected endpoints while the user still must change their password."""
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="must_change_password")
    return user


def require_enrolled(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> Soldier:
    """Block soldier-initiated write actions while intake (enrollment) is still
    pending. Read access is never gated here — only used on write endpoints."""
    from app.db.models import SoldierEnrollmentRequest

    pending = session.execute(
        select(SoldierEnrollmentRequest.id).where(
            SoldierEnrollmentRequest.soldier_id == user.id,
            SoldierEnrollmentRequest.status.in_(("pending", "commander_approved")),
        ).limit(1)
    ).first()
    if pending is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="enrollment_pending")
    return user
