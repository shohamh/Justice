import json
import logging
import re
import time
import uuid
from datetime import UTC, date, datetime as _dt, timedelta as _td

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from typing import Annotated, Literal
from limits import parse as parse_rate_limit
from pydantic import BaseModel, Field, ValidationError, field_validator
from slowapi.util import get_remote_address
from sqlalchemy import select, update as sa_update, case as sa_case
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.auth import refresh_revocation
from app.auth.deps import get_current_user
from app.auth.jwt_tokens import (
    InvalidToken,
    decode_token,
    issue_access_token,
    issue_refresh_token,
    token_persists,
)
from app.auth.password import hash_password, verify_password
from app.db.models import ExemptionRequestFile, ExemptionType, HierarchyNode, Soldier
from app.db.session import get_session
from app.rate_limit import limiter
from app.services import email_verification as ev_svc
from app.services import password_reset as pwd_reset_svc
from app.services import oidc_registration as oidc_reg
from app.services import registration as reg_svc
from app.services.file_validation import FileValidationError, validate_exemption_file
from app.services.hr_activation import consume_activation_code
from app.services.invite_codes import InviteCodeError, validate_code
from app.services.registration import RegistrationError
from app.services.soldiers import PasswordPolicyError, bump_token_version, validate_password
from app.settings import get_settings
from app.validation import is_valid_israeli_phone

router = APIRouter(prefix="/auth", tags=["auth"])

_logger = logging.getLogger("app.auth")

SSO_REGISTRATION_REFUSED = "registration_unavailable"

_LOCKOUT_THRESHOLD = 10
_LOCKOUT_MINUTES = 15


class LoginRequest(BaseModel):
    personal_number: str = Field(pattern=r"^[0-9]{7,8}$")
    password: str = Field(min_length=1, max_length=200)
    remember_me: bool = False


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class RegisterRequest(BaseModel):
    # Empty is accepted by the schema only so a live OIDC registration context can
    # replace it; the register route rejects a missing code otherwise.
    invite_code: str = Field(default="", max_length=20)
    personal_number: str = Field(min_length=1, max_length=20)
    full_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=200)
    phone: str = Field(max_length=40)
    # Null only for a live OIDC registration (the server then uses the verified email
    # from the context); the register route requires it otherwise.
    email: str | None = Field(default=None, max_length=200)
    gender: str
    is_officer: bool | None = None
    rank: str
    rank_track: Literal["enlisted", "officer", "officer_academic"] | None = None
    enlistment_date: date
    unit_join_date: date | None = None
    mandatory_end_date: date
    discharge_date: date
    last_mitvahim_date: date
    last_alal_date: date | None = None
    has_military_driving_license: bool = False
    military_driving_license_expiry: date | None = None
    food_type: Literal["regular", "vegetarian", "vegan", "gluten_free", "kosher_le_mehadrin"] | None = None
    food_constraints: str | None = Field(default=None, max_length=2000)
    requested_node_id: uuid.UUID
    exemption_requests: list[dict] = []
    personal_constraints: list[dict] = []

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        if not is_valid_israeli_phone(v):
            raise ValueError("invalid_israeli_phone")
        return v

    @field_validator("personal_number")
    @classmethod
    def _validate_personal_number(cls, v: str) -> str:
        reg_svc.validate_personal_number(v)
        return v


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


def _enforce_invite_code_guess_limit(request: Request) -> None:
    """Rate-limit *invalid* invite-code guesses, per IP.

    Deliberately not a blanket @limiter.limit on these routes: soldiers on the
    same base/office network share a NAT IP, and a unit rolling out
    registration with one shared, valid code would exhaust a flat per-IP
    budget on legitimate checks alone (each hitting both /register/nodes and
    /register/validate-code), locking out the next colleague to try. Only
    wrong guesses -- the actual brute-force surface -- count against the
    budget, so a shared valid code never trips it for real registrants.
    """
    limit = parse_rate_limit(get_settings().invite_code_rate_limit)
    identifier = get_remote_address(request)
    if not limiter.limiter.hit(limit, "invite-code-guess", identifier):
        reset_time, _ = limiter.limiter.get_window_stats(limit, "invite-code-guess", identifier)
        retry_after = max(0, int(reset_time - time.time()))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate_limit_exceeded",
            headers={"Retry-After": str(retry_after)},
        )


def _login_account_key(request: Request) -> str:
    """Rate-limit key for /auth/login: the submitted personal_number, falling
    back to client IP if the body is missing/malformed."""
    try:
        raw = getattr(request, "_body", b"") or b""
        data = json.loads(raw)
        pn = data.get("personal_number")
        if pn:
            return f"login-account:{pn}"
    except Exception:
        pass
    return get_remote_address(request)


def _warn_if_insecure_cookie_mismatch(request: Request, settings) -> None:
    if settings.cookie_secure and request.url.scheme != "https":
        _logger.warning(
            "cookie_secure is enabled but this request arrived over %s — the "
            "refresh_token cookie will be silently dropped by the browser. "
            "Set COOKIE_SECURE=false for non-HTTPS environments.",
            request.url.scheme,
        )


def _revoke_presented_refresh_cookie(request: Request) -> None:
    """Revoke the refresh token this browser presented (its jti and login session).

    Used by logout, and by login/registration right before a new session's cookie
    replaces it: a restore refresh for the previous cookie that is answered after
    the new login would otherwise leave the previous user's rotated cookie as the
    browser's last Set-Cookie, and the next refresh would silently run as that
    user. With the old session revoked, that refresh 401s and the user is sent to
    /login instead. A missing, expired, garbage or non-refresh cookie has nothing
    to revoke. Never raises: ``revoke`` logs and fails open on store errors.
    """
    cookie = request.cookies.get("refresh_token")
    if not cookie:
        return
    try:
        payload = decode_token(cookie)
    except InvalidToken:
        return
    if payload.get("type") == "refresh":
        refresh_revocation.revoke(payload)


@router.post("/login", response_model=LoginResponse)
@limiter.limit(lambda: get_settings().login_rate_limit)
@limiter.limit(lambda: get_settings().login_account_rate_limit, key_func=_login_account_key)
def login(
    body: Annotated[LoginRequest, Body()],
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> LoginResponse:
    settings = get_settings()
    _warn_if_insecure_cookie_mismatch(request, settings)
    stmt = select(Soldier).where(
        Soldier.personal_number == body.personal_number, Soldier.left_at.is_(None)
    )
    soldier = session.execute(stmt).scalar_one_or_none()

    if soldier is None:
        write_audit(
            session, actor_id=None, action="auth.login.failure", entity_type="soldier",
            entity_id=None, context={**_client_context(request), "personal_number": body.personal_number},
        )
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")

    # Check lockout
    _now_utc = _dt.now(tz=UTC)
    locked = getattr(soldier, "locked_until", None)
    if locked is not None and locked > _now_utc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="account_locked",
            headers={"Retry-After": str(int((locked - _now_utc).total_seconds()))},
        )

    password_ok = verify_password(body.password, soldier.password_hash)
    activation_consumed = False
    if not password_ok:
        activation_consumed = consume_activation_code(session, soldier_id=soldier.id, code=body.password)

    if not password_ok and not activation_consumed:
        new_count = soldier.failed_login_count + 1
        locked_now = new_count >= _LOCKOUT_THRESHOLD
        session.execute(
            sa_update(Soldier)
            .where(Soldier.id == soldier.id)
            .values(
                failed_login_count=sa_case(
                    (locked_now, 0),
                    else_=new_count,
                ),
                locked_until=sa_case(
                    (locked_now, _now_utc + _td(minutes=_LOCKOUT_MINUTES)),
                    else_=Soldier.locked_until,
                ),
            )
        )
        write_audit(
            session, actor_id=soldier.id, action="auth.login.failure", entity_type="soldier",
            entity_id=soldier.id, context={**_client_context(request), "personal_number": body.personal_number},
        )
        session.commit()
        if locked_now:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="account_locked",
                headers={"Retry-After": str(_LOCKOUT_MINUTES * 60)},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"detail": "invalid_credentials", "attempts": new_count, "max_attempts": _LOCKOUT_THRESHOLD},
        )

    # Successful login (real password or a valid activation code) — reset lockout state
    soldier.failed_login_count = 0
    soldier.locked_until = None

    if activation_consumed:
        # The activation code the soldier just typed becomes their real,
        # temporary password (same shape as onboard_soldier's temp-password
        # flow) so /auth/change-password's current_password check has
        # something real to verify against next — without this, the soldier
        # is stuck: must_change_password blocks every other route and they
        # can never supply a working current_password. Also invalidate any
        # other outstanding sessions, same as a real password change would.
        soldier.password_hash = hash_password(body.password)
        bump_token_version(soldier)

    access = issue_access_token(user_id=soldier.id, role=soldier.role)
    refresh = issue_refresh_token(
        user_id=soldier.id, token_version=soldier.token_version, persist=body.remember_me
    )

    write_audit(
        session,
        actor_id=soldier.id,
        action="auth.login.success",
        entity_type="soldier",
        entity_id=soldier.id,
        context={**_client_context(request), **({"method": "activation_code"} if activation_consumed else {})},
    )
    session.commit()
    # Only after the credentials were accepted: a failed attempt never revokes.
    _revoke_presented_refresh_cookie(request)

    response.set_cookie(
        key="refresh_token",
        value=refresh,
        max_age=settings.refresh_token_days * 24 * 3600 if body.remember_me else None,
        httponly=True,
        secure=get_settings().cookie_secure,
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
    # Revoked at logout (this exact token, or its login session). Fails open if
    # Redis is down -- see app.auth.refresh_revocation.
    if refresh_revocation.is_revoked(payload):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token_revoked")

    soldier = session.get(Soldier, uuid.UUID(payload["sub"]))
    if soldier is None or soldier.left_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user_not_found")

    expected_tv = getattr(soldier, "token_version", 1)
    if payload.get("tv", 1) != expected_tv:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token_revoked"
        )

    settings = get_settings()
    _warn_if_insecure_cookie_mismatch(request, settings)
    access = issue_access_token(user_id=soldier.id, role=soldier.role)
    # Rotation keeps the login session id so a logout of this session also
    # revokes the rotated token. Legacy tokens (no sid) start a new session.
    sid = payload.get("sid")
    # A session (non-remember-me) login stays a session cookie; old tokens persist.
    persist = token_persists(payload)
    refresh = issue_refresh_token(
        user_id=soldier.id,
        token_version=soldier.token_version,
        session_id=sid if isinstance(sid, str) and sid else None,
        persist=persist,
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh,
        max_age=settings.refresh_token_days * 24 * 3600 if persist else None,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/api/auth",
    )
    return LoginResponse(access_token=access, must_change_password=soldier.must_change_password)


@router.post("/logout")
def logout(
    request: Request, response: Response, user: Soldier = Depends(get_current_user)
) -> dict[str, str]:
    """Log out this browser: revoke its refresh token server-side, delete the cookie.

    Revocation is per token/session (jti + sid), never a token_version bump,
    so the user's other devices stay signed in. A missing, expired, garbage or
    non-refresh cookie has nothing to revoke and is not an error. The cookie is
    revoked even if it belongs to a different user than the access token: this
    browser is logging out and is about to drop that cookie anyway. A store
    failure is logged inside ``revoke`` and never fails the logout.
    """
    _revoke_presented_refresh_cookie(request)
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
    bump_token_version(user)
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
async def register(
    request: Request,
    response: Response,
    payload: str = Form(...),
    session: Session = Depends(get_session),
) -> LoginResponse:
    settings = get_settings()
    try:
        body = RegisterRequest.model_validate_json(payload)
    except ValidationError as exc:
        if any(
            error.get("loc") == ("password",)
            and error.get("type") == "string_too_short"
            for error in exc.errors()
        ):
            detail = "password_policy"
        else:
            detail = "registration_invalid"
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        ) from exc

    form = await request.form()
    exemption_files: dict[int, list[tuple[str, str, bytes]]] = {}
    for i in range(len(body.exemption_requests)):
        key = f"exemption_files_{i}"
        parts = [p for p in form.getlist(key) if not isinstance(p, str)]
        row_files: list[tuple[str, str, bytes]] = []
        for part in parts:
            data = await part.read()
            try:
                validate_exemption_file(part.content_type or "", data)
            except FileValidationError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
            row_files.append((part.filename or "file", part.content_type or "", data))
        if row_files:
            exemption_files[i] = row_files

    for i, er in enumerate(body.exemption_requests):
        exemption_type_id = er.get("exemption_type_id")
        if exemption_type_id:
            et = session.get(ExemptionType, exemption_type_id)
            if et is not None and et.is_medical and not exemption_files.get(i):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="medical_exemption_requires_file")

    # The invite code is waived only by a live, browser-held OIDC registration
    # context, decided here from server state; no request field can do it. The
    # row is locked so concurrent final steps serialize on it.
    sso_context = oidc_reg.get_active_context(
        session, request.cookies.get(oidc_reg.REGISTRATION_COOKIE), lock=True
    )
    if sso_context is None and body.email is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="registration_invalid"
        )
    if sso_context is None and not body.invite_code.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid invite code")
    if sso_context is not None and not oidc_reg.still_unmatched(session, sso_context):
        session.commit()  # keep the recorded conflict, refuse generically
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=SSO_REGISTRATION_REFUSED)

    try:
        soldier, created_requests = reg_svc.register(
            session,
            invite_code=body.invite_code,
            require_invite_code=sso_context is None,
            email_verified=sso_context is not None,
            personal_number=body.personal_number,
            full_name=body.full_name,
            password=body.password,
            phone=body.phone,
            email=sso_context.email if sso_context is not None else body.email,
            gender=body.gender,
            is_officer=body.is_officer,
            rank=body.rank,
            rank_track=body.rank_track,
            enlistment_date=body.enlistment_date,
            unit_join_date=body.unit_join_date,
            mandatory_end_date=body.mandatory_end_date,
            discharge_date=body.discharge_date,
            last_mitvahim_date=body.last_mitvahim_date,
            last_alal_date=body.last_alal_date,
            has_military_driving_license=body.has_military_driving_license,
            military_driving_license_expiry=body.military_driving_license_expiry,
            food_type=body.food_type,
            food_constraints=body.food_constraints,
            requested_node_id=body.requested_node_id,
            exemption_requests=body.exemption_requests,
            personal_constraints=body.personal_constraints,
        )
        session.flush()
        if sso_context is not None:
            oidc_reg.bind_and_consume(session, sso_context, soldier)

        # reg_svc.register() returns created_requests in the exact order it
        # inserted them (the same order as body.exemption_requests), so
        # zipping by position lines up each ExemptionRequest with the files
        # uploaded for its row. (ExemptionRequest.id is a random UUID, so an
        # id-ordered re-query would NOT reproduce this order.)
        for i, req in enumerate(created_requests):
            for filename, content_type, data in exemption_files.get(i, []):
                session.add(ExemptionRequestFile(
                    exemption_request_id=req.id,
                    file_name=re.sub(r"[^\w.\-]", "_", filename).replace("..", "_")[:200],
                    content_type=content_type,
                    data=data,
                    uploaded_by=soldier.id,
                ))

        session.commit()
    except oidc_reg.OidcRegistrationRefused as exc:
        session.rollback()
        _logger.warning("sso registration refused: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=SSO_REGISTRATION_REFUSED)
    except (InviteCodeError, RegistrationError) as exc:
        session.rollback()
        detail = str(exc)
        if sso_context is not None and detail in oidc_reg.COLLISION_DETAILS:
            detail = SSO_REGISTRATION_REFUSED  # never say which value collided
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    # Registration signs the new soldier in: retire the session this browser had.
    _revoke_presented_refresh_cookie(request)
    access = issue_access_token(user_id=soldier.id, role=soldier.role)
    refresh = issue_refresh_token(user_id=soldier.id, token_version=soldier.token_version)
    response.set_cookie(
        key="refresh_token", value=refresh,
        max_age=settings.refresh_token_days * 24 * 3600,
        httponly=True, secure=get_settings().cookie_secure, samesite="strict", path="/api/auth",
    )
    if sso_context is not None:
        response.delete_cookie(oidc_reg.REGISTRATION_COOKIE, path="/api/auth")
    return LoginResponse(access_token=access, must_change_password=False)


@router.get("/register/nodes", response_model=list[NodeOut])
def register_nodes(
    request: Request,
    response: Response,
    invite_code: str | None = None,
    session: Session = Depends(get_session),
) -> list[NodeOut]:
    from sqlalchemy import select as sa_select
    # A live OIDC registration context (browser cookie) stands in for the invite code.
    has_context = oidc_reg.get_active_context(
        session, request.cookies.get(oidc_reg.REGISTRATION_COOKIE)
    ) is not None
    if not has_context and invite_code is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invite_code_required")
    if not has_context and not (invite_code and validate_code(session, code=invite_code)):
        if invite_code:
            _enforce_invite_code_guess_limit(request)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid_invite_code")
    nodes = session.execute(sa_select(HierarchyNode)).scalars().all()
    commander_ids = {n.commander_id for n in nodes if n.commander_id}
    commanders: dict[uuid.UUID, str] = {}
    if commander_ids:
        commanders = {
            s.id: s.full_name
            for s in session.execute(
                sa_select(Soldier).where(Soldier.id.in_(commander_ids))
            ).scalars().all()
        }
    return [
        NodeOut(
            id=n.id, name=n.name, level=n.level,
            path_ids=n.path_ids,
            commander_name=commanders.get(n.commander_id) if n.commander_id else None,
            parent_id=n.parent_id,
        )
        for n in nodes
    ]


@router.get("/register/validate-code")
def validate_invite_code(
    code: str,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> dict:
    valid = validate_code(session, code=code)
    if not valid:
        _enforce_invite_code_guess_limit(request)
    return {"valid": valid}


@router.post("/forgot-password", response_model=ForgotPasswordChannelsResponse)
@limiter.limit(get_settings().login_rate_limit)
def forgot_password_check(
    body: Annotated[ForgotPasswordCheckRequest, Body()],
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> ForgotPasswordChannelsResponse:
    # Always return the same response to prevent user enumeration.
    # The actual available channels are revealed only to the account holder via the /send endpoint.
    pwd_reset_svc.available_channels(session, personal_number=body.personal_number)  # called to keep timing consistent
    return ForgotPasswordChannelsResponse(channels=["telegram", "email"])


@router.post("/forgot-password/send", status_code=200)
@limiter.limit(get_settings().login_rate_limit)
def forgot_password_send(
    body: Annotated[ForgotPasswordSendRequest, Body()],
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> dict:
    # Always call available_channels (same DB work as the check endpoint) so
    # timing is consistent whether or not the personal_number exists.
    pwd_reset_svc.available_channels(session, personal_number=body.personal_number)
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


class PublicExemptionTypeOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    is_medical: bool


@router.get("/exemption-types", response_model=list[PublicExemptionTypeOut])
@limiter.limit("60/minute")
def list_public_exemption_types(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> list[PublicExemptionTypeOut]:
    types = session.execute(
        select(ExemptionType)
        .where(ExemptionType.is_commander_exemption.is_(False))
        .order_by(ExemptionType.name)
    ).scalars().all()
    return [PublicExemptionTypeOut(id=et.id, name=et.name, description=et.description, is_medical=et.is_medical) for et in types]


@router.get("/rank-ladder")
@limiter.limit("60/minute")
def public_rank_ladder(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> dict:
    """Unauthenticated read of the ordered rank ladder.

    The registration page (a public route) needs the rank list to populate its
    mandatory rank picker, so it cannot use the authenticated admin-facing
    GET /soldiers/rank-ladder. The ladder is non-sensitive ordering data — it
    was a hardcoded, fully public frontend constant before it moved
    server-side — so it is exposed here alongside the other public,
    registration-facing reads (/auth/register/nodes, /auth/exemption-types),
    rate-limited the same way. Writing the intervals stays admin-only.
    """
    from app.services.rank_advancement import get_rank_ladder

    return get_rank_ladder(session)
