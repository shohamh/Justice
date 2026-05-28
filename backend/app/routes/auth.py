from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.auth.deps import get_current_user
from app.auth.jwt_tokens import InvalidToken, decode_token, issue_access_token, issue_refresh_token
from app.auth.password import verify_password
from app.db.models import Soldier
from app.db.session import get_session
from app.rate_limit import limiter
from app.settings import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    personal_number: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=200)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool


def _client_context(request: Request) -> dict[str, str]:
    return {
        "ip": request.client.host if request.client else "",
        "user_agent": request.headers.get("user-agent", ""),
    }


@router.post("/login", response_model=LoginResponse)
@limiter.limit(lambda: get_settings().login_rate_limit)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> LoginResponse:
    settings = get_settings()
    stmt = select(Soldier).where(
        Soldier.personal_number == body.personal_number, Soldier.left_at.is_(None)
    )
    soldier = session.execute(stmt).scalar_one_or_none()

    if soldier is None or not verify_password(body.password, soldier.password_hash):
        write_audit(
            session,
            actor_id=soldier.id if soldier is not None else None,
            action="auth.login.failure",
            entity_type="soldier",
            entity_id=soldier.id if soldier is not None else None,
            context={**_client_context(request), "personal_number": body.personal_number},
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

    access = issue_access_token(user_id=soldier.id, role=soldier.role)
    refresh = issue_refresh_token(user_id=soldier.id)

    write_audit(
        session,
        actor_id=soldier.id,
        action="auth.login.success",
        entity_type="soldier",
        entity_id=soldier.id,
        context=_client_context(request),
    )
    session.commit()

    response.set_cookie(
        key="refresh_token",
        value=refresh,
        max_age=settings.refresh_token_days * 24 * 3600,
        httponly=True,
        secure=False,  # set to True behind TLS in slice 7; left False so local dev over http works
        samesite="strict",
        path="/api/auth",
    )
    return LoginResponse(access_token=access, must_change_password=soldier.must_change_password)


@router.post("/refresh", response_model=LoginResponse)
def refresh(
    request: Request, response: Response, session: Session = Depends(get_session)
) -> LoginResponse:
    cookie = request.cookies.get("refresh_token")
    if not cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no_refresh_cookie")
    try:
        payload = decode_token(cookie)
    except InvalidToken as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_refresh_token"
        ) from exc
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="wrong_token_type")

    soldier = session.get(Soldier, uuid.UUID(payload["sub"]))
    if soldier is None or soldier.left_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user_not_found")

    access = issue_access_token(user_id=soldier.id, role=soldier.role)
    return LoginResponse(access_token=access, must_change_password=soldier.must_change_password)


@router.post("/logout")
def logout(response: Response, user: Soldier = Depends(get_current_user)) -> dict[str, str]:
    response.delete_cookie(key="refresh_token", path="/api/auth")
    return {"status": "ok"}
