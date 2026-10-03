"""OpenID Connect authorization-code + PKCE client (protocol only, no database).

Built on Authlib (authorization request, PKCE S256, ID-token claim rules) and
joserfc (signature and JWKS handling, Authlib's own dependency); nothing
cryptographic is implemented here. The module:

* reads the single trusted issuer from server settings (:func:`load_oidc_config`)
  and stays disabled when the configuration is absent or invalid;
* discovers metadata only from that issuer (``<issuer>/.well-known/openid-configuration``)
  and requires the returned ``issuer`` to match exactly, every endpoint to be
  HTTPS, and S256 PKCE support;
* verifies ID tokens against the issuer JWKS with an explicit asymmetric
  algorithm allowlist, validates ``iss``, ``aud``/``azp``, ``exp``, ``iat``,
  ``nbf``, ``nonce`` and requires a verified email claim;
* refreshes the JWKS at most once per :data:`JWKS_REFRESH_MIN_INTERVAL` seconds
  on an unknown ``kid`` (key rotation) and fails closed on any outage.

Failures raise :class:`OidcError` whose ``code`` is a short internal reason that
is safe to log and audit. Tokens, authorization codes, state, nonce, the
verifier, the client secret, email addresses and other claims are never put in
exceptions, logs or ``repr`` output.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx
from authlib.oauth2.rfc6749.parameters import prepare_grant_uri
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from authlib.oidc.core import CodeIDToken
from joserfc import jwt
from joserfc.errors import InvalidKeyIdError, JoseError
from joserfc.jwk import KeySet

logger = logging.getLogger("app.oidc")

#: Asymmetric algorithms accepted for ID-token signatures. ``none`` and the
#: shared-secret ``HS*`` family are never accepted.
ALLOWED_ID_TOKEN_ALGORITHMS: tuple[str, ...] = (
    "RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512",
)
SCOPE = "openid email"
DISCOVERY_TTL_SECONDS = 3600
JWKS_TTL_SECONDS = 3600
JWKS_REFRESH_MIN_INTERVAL = 60
CLOCK_SKEW_LEEWAY_SECONDS = 60
MAX_TRANSACTION_TTL_SECONDS = 900
MAX_REGISTRATION_TTL_SECONDS = 3600
_MAX_RESPONSE_BYTES = 1_000_000
_HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class OidcError(Exception):
    """An OIDC step failed. ``code`` is a short, loggable reason; never PII."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OidcConfig:
    issuer: str
    client_id: str
    redirect_uri: str
    client_secret: str | None = field(default=None, repr=False)
    transaction_ttl_seconds: int = 300
    registration_ttl_seconds: int = 900
    allow_insecure_local: bool = False


@dataclass(frozen=True)
class AuthorizationRequest:
    """The server-side secrets of one login attempt plus the URL to send the browser to."""

    url: str = field(repr=False)
    state: str = field(repr=False)
    nonce: str = field(repr=False)
    code_verifier: str = field(repr=False)


@dataclass(frozen=True)
class VerifiedIdentity:
    """A validated ID token reduced to what Justice needs. Claims are never logged."""

    issuer: str = field(repr=False)
    subject: str = field(repr=False)
    email: str = field(repr=False)


def _secret_value(value: Any) -> str:
    if value is None:
        return ""
    getter = getattr(value, "get_secret_value", None)
    return (getter() if getter else str(value)).strip()


def _is_valid_url(url: str, *, allow_insecure_local: bool, allow_query: bool) -> bool:
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port  # raises on a malformed port
    except ValueError:
        return False
    del port
    if not host or parts.username or parts.password or parts.fragment:
        return False
    if parts.query and not allow_query:
        return False
    if parts.scheme == "https":
        return True
    return parts.scheme == "http" and allow_insecure_local and host in _LOOPBACK_HOSTS


def load_oidc_config(settings: Any) -> OidcConfig | None:
    """Build the OIDC configuration, or ``None`` (OIDC disabled) if absent or invalid.

    Invalid configuration disables SSO rather than failing application start,
    and nothing about the rejected values is logged.
    """
    issuer = (settings.oidc_issuer or "").strip()
    client_id = (settings.oidc_client_id or "").strip()
    redirect_uri = (settings.oidc_redirect_uri or "").strip()
    if not (issuer or client_id or redirect_uri):
        return None  # not configured: the normal, disabled state
    allow_local = bool(settings.oidc_allow_insecure_local)
    ttl = settings.oidc_transaction_ttl_seconds
    registration_ttl = settings.oidc_registration_ttl_seconds
    valid = (
        bool(client_id)
        and _is_valid_url(issuer, allow_insecure_local=allow_local, allow_query=False)
        and _is_valid_url(redirect_uri, allow_insecure_local=allow_local, allow_query=False)
        and 0 < ttl <= MAX_TRANSACTION_TTL_SECONDS
        and 0 < registration_ttl <= MAX_REGISTRATION_TTL_SECONDS
    )
    if not valid:
        logger.warning("OIDC configuration is invalid; single sign-on is disabled")
        return None
    return OidcConfig(
        issuer=issuer,
        client_id=client_id,
        redirect_uri=redirect_uri,
        client_secret=_secret_value(settings.oidc_client_secret) or None,
        transaction_ttl_seconds=ttl,
        registration_ttl_seconds=registration_ttl,
        allow_insecure_local=allow_local,
    )


class OidcClient:
    """Discovery, JWKS and code-exchange for the one configured issuer."""

    def __init__(
        self,
        config: OidcConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._transport = transport
        self._clock = clock
        self._lock = threading.Lock()
        self._metadata: dict[str, Any] | None = None
        self._metadata_at = 0.0
        self._jwks: KeySet | None = None
        self._jwks_at = 0.0
        self._algorithms: tuple[str, ...] = ALLOWED_ID_TOKEN_ALGORITHMS

    @property
    def config(self) -> OidcConfig:
        return self._config

    # -- HTTP ------------------------------------------------------------------
    def _http(self) -> httpx.Client:
        return httpx.Client(transport=self._transport, timeout=_HTTP_TIMEOUT, follow_redirects=False)

    def _get_json(self, url: str, failure: str) -> Any:
        try:
            with self._http() as http:
                response = http.get(url, headers={"Accept": "application/json"})
            if response.status_code != 200 or len(response.content) > _MAX_RESPONSE_BYTES:
                raise OidcError(failure)
            return response.json()
        except OidcError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcError(failure) from exc

    # -- Discovery ---------------------------------------------------------------
    def metadata(self) -> dict[str, Any]:
        with self._lock:
            now = self._clock()
            if self._metadata is not None and now - self._metadata_at < DISCOVERY_TTL_SECONDS:
                return self._metadata
            url = self._config.issuer.rstrip("/") + "/.well-known/openid-configuration"
            document = self._get_json(url, "discovery_failed")
            self._metadata = self._validate_metadata(document)
            self._metadata_at = now
            return self._metadata

    def _validate_metadata(self, document: Any) -> dict[str, Any]:
        if not isinstance(document, dict):
            raise OidcError("discovery_invalid")
        if document.get("issuer") != self._config.issuer:
            raise OidcError("discovery_issuer_mismatch")
        for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            value = document.get(name)
            if not isinstance(value, str) or not _is_valid_url(
                value, allow_insecure_local=self._config.allow_insecure_local, allow_query=True
            ):
                raise OidcError("discovery_invalid")
        methods = document.get("code_challenge_methods_supported")
        if not isinstance(methods, list) or "S256" not in methods:
            raise OidcError("pkce_unsupported")
        advertised = document.get("id_token_signing_alg_values_supported")
        if advertised is not None:
            if not isinstance(advertised, list):
                raise OidcError("discovery_invalid")
            self._algorithms = tuple(a for a in ALLOWED_ID_TOKEN_ALGORITHMS if a in advertised)
            if not self._algorithms:
                raise OidcError("discovery_invalid")
        return document

    # -- JWKS --------------------------------------------------------------------
    def _key_set(self, *, refresh: bool = False) -> KeySet:
        metadata = self.metadata()
        with self._lock:
            now = self._clock()
            fresh = self._jwks is not None and now - self._jwks_at < JWKS_TTL_SECONDS
            if self._jwks is not None and (
                (not refresh and fresh) or (refresh and now - self._jwks_at < JWKS_REFRESH_MIN_INTERVAL)
            ):
                return self._jwks
            document = self._get_json(metadata["jwks_uri"], "jwks_failed")
            try:
                key_set = KeySet.import_key_set(document)
            except (JoseError, ValueError, TypeError, KeyError) as exc:
                raise OidcError("jwks_failed") from exc
            self._jwks, self._jwks_at = key_set, now
            return key_set

    # -- Authorization request ---------------------------------------------------
    def start(self) -> AuthorizationRequest:
        metadata = self.metadata()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)  # 86 characters, within RFC 7636's 43-128
        url = prepare_grant_uri(
            metadata["authorization_endpoint"],
            self._config.client_id,
            "code",
            redirect_uri=self._config.redirect_uri,
            scope=SCOPE,
            state=state,
            nonce=nonce,
            code_challenge=create_s256_code_challenge(code_verifier),
            code_challenge_method="S256",
        )
        return AuthorizationRequest(url=url, state=state, nonce=nonce, code_verifier=code_verifier)

    # -- Code exchange and ID token validation -------------------------------------
    def complete(self, *, code: str, code_verifier: str, nonce: str) -> VerifiedIdentity:
        """Exchange ``code`` and return the validated identity, or raise :class:`OidcError`."""
        if not code or not code_verifier or not nonce:
            raise OidcError("callback_incomplete")
        id_token = self._exchange_code(code, code_verifier)
        claims = self._validate_id_token(id_token, nonce)
        return self._identity_from_claims(claims)

    def _exchange_code(self, code: str, code_verifier: str) -> str:
        metadata = self.metadata()
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._config.redirect_uri,
            "code_verifier": code_verifier,
        }
        headers = {"Accept": "application/json"}
        auth: tuple[str, str] | None = None
        secret = self._config.client_secret
        if secret is None:
            form["client_id"] = self._config.client_id
        else:
            supported = metadata.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
            if "client_secret_basic" in supported or "client_secret_post" not in supported:
                auth = (self._config.client_id, secret)
            else:
                form["client_id"] = self._config.client_id
                form["client_secret"] = secret
        try:
            with self._http() as http:
                response = http.post(metadata["token_endpoint"], data=form, headers=headers, auth=auth)
            if response.status_code != 200 or len(response.content) > _MAX_RESPONSE_BYTES:
                raise OidcError("token_exchange_failed")
            body = response.json()
        except OidcError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcError("token_exchange_failed") from exc
        if not isinstance(body, dict):
            raise OidcError("token_exchange_failed")
        token = body.get("id_token")
        if not isinstance(token, str) or not token:
            raise OidcError("id_token_missing")
        # Provider access/refresh tokens are deliberately discarded: Justice only
        # needs the authenticated identity.
        return token

    def _decode(self, id_token: str, key_set: KeySet):
        return jwt.decode(id_token, key_set, algorithms=list(self._algorithms))

    def _validate_id_token(self, id_token: str, nonce: str) -> dict[str, Any]:
        key_set = self._key_set()
        try:
            try:
                token = self._decode(id_token, key_set)
            except InvalidKeyIdError:
                token = self._decode(id_token, self._key_set(refresh=True))  # key rotation
            claims = CodeIDToken(
                token.claims,
                token.header,
                options={
                    "iss": {"essential": True, "value": self._config.issuer},
                    "sub": {"essential": True},
                    "aud": {"essential": True, "value": self._config.client_id},
                    "exp": {"essential": True},
                    "iat": {"essential": True},
                },
                params={"nonce": nonce, "client_id": self._config.client_id},
            )
            claims.validate(now=int(self._clock()), leeway=CLOCK_SKEW_LEEWAY_SECONDS)
        except OidcError:
            raise
        except (JoseError, ValueError, TypeError, KeyError) as exc:
            raise OidcError("id_token_invalid") from exc
        self._check_explicit_claims(dict(claims), nonce)
        return dict(claims)

    def _check_explicit_claims(self, claims: dict[str, Any], nonce: str) -> None:
        """Belt and braces for rules the checks above express indirectly."""
        issuer, client_id = self._config.issuer, self._config.client_id
        audience = claims.get("aud")
        audiences = audience if isinstance(audience, list) else [audience]
        subject = claims.get("sub")
        now = self._clock()
        iat = claims.get("iat")
        ok = (
            claims.get("iss") == issuer
            and client_id in audiences
            and (len(audiences) == 1 or claims.get("azp") == client_id)
            and claims.get("azp", client_id) == client_id
            and claims.get("nonce") == nonce
            and isinstance(subject, str) and 0 < len(subject) <= 255
            and isinstance(iat, (int, float)) and iat <= now + CLOCK_SKEW_LEEWAY_SECONDS
        )
        if not ok:
            raise OidcError("id_token_invalid")

    @staticmethod
    def _identity_from_claims(claims: dict[str, Any]) -> VerifiedIdentity:
        email = claims.get("email")
        if not isinstance(email, str) or not email.strip():
            raise OidcError("email_missing")
        verified = claims.get("email_verified")
        if not (verified is True or (isinstance(verified, str) and verified.lower() == "true")):
            raise OidcError("email_not_verified")
        return VerifiedIdentity(issuer=claims["iss"], subject=claims["sub"], email=email.strip())


_client_lock = threading.Lock()
_client: OidcClient | None = None


def get_oidc_client() -> OidcClient | None:
    """The process-wide client for the configured issuer, or ``None`` when disabled."""
    from app.settings import get_settings

    global _client
    config = load_oidc_config(get_settings())
    with _client_lock:
        if config is None:
            _client = None
        elif _client is None or _client.config != config:
            _client = OidcClient(config)
        return _client


def reset_oidc_client() -> None:
    """Drop the cached client (tests, configuration reload)."""
    global _client
    with _client_lock:
        _client = None
