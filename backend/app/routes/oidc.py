"""OIDC single sign-on endpoints (browser redirects, no tokens in URLs or bodies).

``GET /auth/oidc/start`` sends the browser to the configured provider.
``GET /auth/oidc/callback`` validates the response and always answers with a
redirect to a fixed frontend path: ``/`` (signed in; the refresh cookie is set
exactly as for password login and the SPA obtains its access token from
``/auth/refresh``), ``/register?sso=1`` (verified but unregistered) or
``/login?sso_error=1`` (every kind of failure looks the same).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.auth.jwt_tokens import issue_access_token, issue_refresh_token  # noqa: F401
from app.db.session import get_session
from app.rate_limit import limiter
from app.routes.auth import _client_context, refresh_cookie_max_age
from app.services import oidc_login, oidc_registration
from app.services.oidc import OidcClient, OidcError, get_oidc_client
from app.services.oidc_transactions import begin_transaction, consume_transaction
from app.settings import get_settings

router = APIRouter(prefix="/auth/oidc", tags=["auth"])
_logger = logging.getLogger("app.oidc")

TRANSACTION_COOKIE = "oidc_txn"
COOKIE_PATH = "/api/auth/oidc"
SUCCESS_PATH = "/"
ERROR_PATH = "/login?sso_error=1"
REGISTER_PATH = "/register?sso=1"


def oidc_client_dependency() -> OidcClient | None:
    return get_oidc_client()


def _frontend(path: str) -> str:
    return get_settings().frontend_url.rstrip("/") + path


def _redirect(url: str, status_code: int = 303) -> RedirectResponse:
    response = RedirectResponse(url, status_code=status_code)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _denied(response_cookie_cleanup: bool = True) -> RedirectResponse:
    response = _redirect(_frontend(ERROR_PATH))
    if response_cookie_cleanup:
        response.delete_cookie(TRANSACTION_COOKIE, path=COOKIE_PATH)
    return response


def _audit_failure(session: Session, request: Request, reason: str) -> None:
    write_audit(
        session, actor_id=None, action="auth.sso.login.failure", entity_type="soldier",
        entity_id=None, context={**_client_context(request), "reason": reason},
    )


@router.get("/status")
def oidc_status(client: OidcClient | None = Depends(oidc_client_dependency)) -> JSONResponse:
    return JSONResponse({"enabled": client is not None}, headers={"Cache-Control": "no-store"})


@router.get("/start")
@limiter.limit(lambda: get_settings().oidc_rate_limit)
def oidc_start(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    client: OidcClient | None = Depends(oidc_client_dependency),
):
    if client is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    try:
        # The login page appends remember=0 when "remember me" is unticked; anything
        # else (including no parameter) keeps the remembered default.
        remember = request.query_params.get("remember") != "0"
        auth_request, browser_token = begin_transaction(session, client, remember=remember)
    except OidcError as exc:
        _logger.warning("oidc start failed: %s", exc.code)
        return _denied()
    session.commit()
    redirect = _redirect(auth_request.url, status_code=302)
    redirect.set_cookie(
        key=TRANSACTION_COOKIE, value=browser_token, max_age=client.config.transaction_ttl_seconds,
        httponly=True, secure=get_settings().cookie_secure, samesite="lax", path=COOKIE_PATH,
    )
    return redirect


@router.get("/callback")
@limiter.limit(lambda: get_settings().oidc_rate_limit)
def oidc_callback(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    client: OidcClient | None = Depends(oidc_client_dependency),
):
    if client is None:
        return JSONResponse({"detail": "not_found"}, status_code=404)
    settings = get_settings()
    params = request.query_params
    code, state = params.get("code"), params.get("state")

    try:
        try:
            consumed = consume_transaction(
                session, state=state, browser_token=request.cookies.get(TRANSACTION_COOKIE)
            )
        except OidcError:
            session.commit()  # persist the burn of a transaction used from the wrong browser
            raise
        session.commit()
        if params.get("error") or not code:
            raise OidcError("provider_error")
        verified = client.complete(code=code, code_verifier=consumed.code_verifier, nonce=consumed.nonce)
    except OidcError as exc:
        _audit_failure(session, request, exc.code)
        session.commit()
        return _denied()

    result = oidc_login.authenticate(session, verified)
    if result.kind == "no_match" and result.email and result.ad_username:
        token = oidc_registration.create_context(
            session, issuer=verified.issuer, subject=verified.subject, email=result.email,
            ad_username=result.ad_username, ttl_seconds=client.config.registration_ttl_seconds,
        )
        write_audit(
            session, actor_id=None, action="auth.sso.registration_started",
            entity_type="soldier", entity_id=None, context=_client_context(request),
        )
        session.commit()
        redirect = _redirect(_frontend(REGISTER_PATH))
        redirect.delete_cookie(TRANSACTION_COOKIE, path=COOKIE_PATH)
        redirect.set_cookie(
            key=oidc_registration.REGISTRATION_COOKIE, value=token,
            max_age=client.config.registration_ttl_seconds, httponly=True,
            secure=settings.cookie_secure, samesite="strict", path="/api/auth",
        )
        return redirect
    if result.kind != "login" or result.soldier is None:
        reason = result.reason or "no_match"
        _audit_failure(session, request, reason)
        session.commit()  # keeps a recorded identity conflict
        return _denied()

    soldier = result.soldier
    write_audit(
        session, actor_id=soldier.id, action="auth.sso.login.success", entity_type="soldier",
        entity_id=soldier.id,
        context={**_client_context(request), **({"linked": True} if result.linked else {})},
    )
    # The choice made at /start travels in the browser-bound transaction, never in
    # this request's query string. Remembered -> persistent cookie; else a session
    # cookie with the short sliding token lifetime.
    persist = consumed.remember
    refresh = issue_refresh_token(
        user_id=soldier.id, token_version=soldier.token_version, persist=persist
    )
    session.commit()
    redirect = _redirect(_frontend(SUCCESS_PATH))
    redirect.delete_cookie(TRANSACTION_COOKIE, path=COOKIE_PATH)
    redirect.set_cookie(
        key="refresh_token", value=refresh, max_age=refresh_cookie_max_age(settings, persist),
        httponly=True, secure=settings.cookie_secure, samesite="strict", path="/api/auth",
    )
    return redirect


@router.get("/registration-context")
def registration_context(
    request: Request, session: Session = Depends(get_session)
) -> JSONResponse:
    """The verified identity to prefill (read-only) in the registration form."""
    context = oidc_registration.get_active_context(
        session, request.cookies.get(oidc_registration.REGISTRATION_COOKIE)
    )
    headers = {"Cache-Control": "no-store"}
    if context is None:
        return JSONResponse({"detail": "no_registration_context"}, status_code=404, headers=headers)
    return JSONResponse({"email": context.email, "ad_username": context.ad_username}, headers=headers)
