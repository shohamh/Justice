from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token") from exc
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="wrong_token_type")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no_subject")
    user = session.get(Soldier, uuid.UUID(sub))
    if user is None or user.left_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user_not_found")
    return user
