import uuid
from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from typing import Annotated
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.auth.deps import get_current_user
from app.auth.jwt_tokens import InvalidToken, decode_token, issue_access_token, issue_refresh_token
from app.auth.password import hash_password, verify_password
from app.db.models import HierarchyNode, Soldier
from app.db.session import get_session
from app.rate_limit import limiter
from app.services import email_verification as ev_svc
from app.services import password_reset as pwd_reset_svc
from app.services import registration as reg_svc
from app.services.invite_codes import InviteCodeError, validate_code
from app.services.registration import RegistrationError
from app.services.soldiers import PasswordPolicyError, validate_password
from app.settings import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    personal_number: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=200)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class RegisterRequest(BaseModel):
    invite_code: str = Field(min_length=1, max_length=20)
    personal_number: str = Field(min_length=1, max_length=20)
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=10, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=200)
    gender: str | None = None
    is_officer: bool | None = None
    rank: str | None = None
    bahad1_graduate: bool = False
    enlistment_date: date | None = None
    mandatory_end_date: date | None = None
    discharge_date: date | None = None
    last_mitvahim_date: date | None = None
    last_alal_date: date | None = None
    requested_node_id: uuid.UUID
    exemption_requests: list[dict] = []
    personal_constraints: list[dict] = []


class ForgotPasswordCheckRequest(BaseModel):
    personal_number: str = Field(min_length=1, max_length=20)


class ForgotPasswordChannelsResponse(BaseModel):
    channels: list[str]


class ForgotPasswordSendRequest(BaseModel):
    personal_number: str = Field(min_length=1, max_length=20)
    channel: str = Field(pattern="^(telegram|email)$")


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=100)
    new_password: str = Field(min_length=1, max_length=200)


class NodeOut(BaseModel):
    id: uuid.UUID
    name: str
    level: str
    path_ids: list[uuid.UUID]
    commander_name: str | None
    parent_id: uuid.UUID | None


def _client_context(request: Request) -> dict[str, str]:
    return {
        "ip": request.client.host if request.client else "",
        "user_agent": request.headers.get("user-agent", ""),
    }


@router.post("/login", response_model=LoginResponse)
@limiter.limit(get_settings().login_rate_limit)
def login(
    body: Annotated[LoginRequest, Body()],
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


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(get_current_user),
) -> dict[str, str]:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="wrong_current_password"
        )
    try:
        validate_password(body.new_password)
    except PasswordPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="password_too_short"
        ) from exc
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    write_audit(
        session,
        actor_id=user.id,
        action="auth.password.change",
        entity_type="soldier",
        entity_id=user.id,
    )
    session.commit()
    return {"status": "ok"}


@router.post("/register", response_model=LoginResponse)
def register(
    body: RegisterRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> LoginResponse:
    settings = get_settings()
    try:
        soldier = reg_svc.register(
            session,
            invite_code=body.invite_code,
            personal_number=body.personal_number,
            full_name=body.full_name,
            password=body.password,
            phone=body.phone,
            email=body.email,
            gender=body.gender,
            is_officer=body.is_officer,
            rank=body.rank,
            bahad1_graduate=body.bahad1_graduate,
            enlistment_date=body.enlistment_date,
            mandatory_end_date=body.mandatory_end_date,
            discharge_date=body.discharge_date,
            last_mitvahim_date=body.last_mitvahim_date,
            last_alal_date=body.last_alal_date,
            requested_node_id=body.requested_node_id,
            exemption_requests=body.exemption_requests,
            personal_constraints=body.personal_constraints,
        )
        session.commit()
    except (InviteCodeError, RegistrationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    access = issue_access_token(user_id=soldier.id, role=soldier.role)
    refresh = issue_refresh_token(user_id=soldier.id)
    response.set_cookie(
        key="refresh_token", value=refresh,
        max_age=settings.refresh_token_days * 24 * 3600,
        httponly=True, secure=False, samesite="strict", path="/api/auth",
    )
    return LoginResponse(access_token=access, must_change_password=False)


@router.get("/register/nodes", response_model=list[NodeOut])
def register_nodes(session: Session = Depends(get_session)) -> list[NodeOut]:
    from sqlalchemy import select as sa_select
    nodes = session.execute(sa_select(HierarchyNode)).scalars().all()
    result = []
    for n in nodes:
        commander_name: str | None = None
        if n.commander_id:
            s = session.get(Soldier, n.commander_id)
            commander_name = s.full_name if s else None
        result.append(NodeOut(
            id=n.id, name=n.name, level=n.level,
            path_ids=n.path_ids, commander_name=commander_name, parent_id=n.parent_id,
        ))
    return result


@router.get("/register/validate-code")
def validate_invite_code(code: str, session: Session = Depends(get_session)) -> dict:
    return {"valid": validate_code(session, code=code)}


@router.post("/forgot-password", response_model=ForgotPasswordChannelsResponse)
@limiter.limit(get_settings().login_rate_limit)
def forgot_password_check(
    body: Annotated[ForgotPasswordCheckRequest, Body()],
    request: Request,
    session: Session = Depends(get_session),
) -> ForgotPasswordChannelsResponse:
    channels = pwd_reset_svc.available_channels(session, personal_number=body.personal_number)
    return ForgotPasswordChannelsResponse(channels=channels)


@router.post("/forgot-password/send", status_code=200)
@limiter.limit(get_settings().login_rate_limit)
def forgot_password_send(
    body: Annotated[ForgotPasswordSendRequest, Body()],
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    pwd_reset_svc.create_and_send(session, personal_number=body.personal_number, channel=body.channel)
    session.commit()
    return {}


@router.post("/reset-password", status_code=200)
def reset_password(
    body: ResetPasswordRequest,
    session: Session = Depends(get_session),
) -> dict:
    result = pwd_reset_svc.redeem_reset_token(session, token=body.token, new_password=body.new_password)
    if result == "ok":
        session.commit()
        return {}
    session.rollback()
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)


@router.post("/verify-email", status_code=200)
def verify_email(
    body: VerifyEmailRequest,
    session: Session = Depends(get_session),
) -> dict:
    result = ev_svc.verify_token(session, token=body.token)
    if result == "ok":
        session.commit()
        return {}
    session.rollback()
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result)
