"""A local, in-process mock OpenID Connect provider for tests.

Synthetic data only: random RSA keys generated per instance, fake subjects and
example.test addresses. It behaves like a real authorization-code + PKCE
provider (it validates ``code_challenge`` / ``code_verifier`` S256, the
exact ``redirect_uri``, client authentication and one-time codes), so the
client under test is exercised against protocol-correct behaviour.

Use it two ways:

* ``provider.transport()`` -> an ``httpx.MockTransport`` for in-process tests
  (no sockets), passed to ``OidcClient(config, transport=...)``.
* ``provider.asgi_app()`` -> a tiny ASGI application for browser tests, served
  by uvicorn; ``/authorize`` shows no UI and immediately redirects back with a
  code for the identity selected via ``/__identity`` (see ``set_identity``).

Failure and tampering knobs are plain attributes (``fail_discovery``,
``token_overrides`` ...) so each negative test flips exactly one thing.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey

ISSUER = "https://idp.example.test"
CLIENT_ID = "justice-test-client"
CLIENT_SECRET = "mock-client-secret-not-real"
REDIRECT_URI = "https://justice.example.test/api/auth/oidc/callback"


@dataclass
class MockIdentity:
    subject: str = "sub-0001"
    email: str | None = "dude@corp.example"
    email_verified: Any = True


@dataclass
class _IssuedCode:
    client_id: str
    redirect_uri: str
    code_challenge: str
    nonce: str
    identity: MockIdentity


@dataclass
class MockOidcProvider:
    issuer: str = ISSUER
    client_id: str = CLIENT_ID
    client_secret: str = CLIENT_SECRET
    redirect_uri: str = REDIRECT_URI
    identity: MockIdentity = field(default_factory=MockIdentity)

    # Failure / tampering knobs ------------------------------------------------
    fail_discovery: bool = False
    fail_jwks: bool = False
    fail_token: bool = False
    metadata_issuer: str | None = None  # override the issuer in the discovery document
    token_overrides: dict[str, Any] = field(default_factory=dict)  # claim name -> value
    drop_claims: set[str] = field(default_factory=set)
    sign_with_foreign_key: bool = False
    header_alg: str = "RS256"
    omit_id_token: bool = False
    omit_s256: bool = False  # advertise no S256 support in discovery

    # Observations --------------------------------------------------------------
    requests: list[httpx.Request] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._keys: list[tuple[str, RSAKey]] = []
        self.rotate_keys(keep_old=False)
        self._foreign = RSAKey.generate_key(2048, {"kid": "foreign", "use": "sig", "alg": "RS256"})
        self._codes: dict[str, _IssuedCode] = {}
        self._nonce_hint = ""

    # Keys ------------------------------------------------------------------------
    def rotate_keys(self, *, keep_old: bool = True) -> str:
        kid = f"key-{secrets.token_hex(4)}"
        key = RSAKey.generate_key(2048, {"kid": kid, "use": "sig", "alg": "RS256"})
        self._keys = ([*self._keys] if keep_old else []) + [(kid, key)]
        self._active_kid = kid
        return kid

    def retire_old_keys(self) -> None:
        self._keys = [(k, v) for k, v in self._keys if k == self._active_kid]

    @property
    def jwks(self) -> dict[str, Any]:
        return KeySet([key for _, key in self._keys]).as_dict(private=False)

    def _signing_key(self) -> RSAKey:
        if self.sign_with_foreign_key:
            return self._foreign
        return dict(self._keys)[self._active_kid]

    # Protocol ------------------------------------------------------------------
    def discovery_document(self) -> dict[str, Any]:
        base = self.issuer
        doc: dict[str, Any] = {
            "issuer": self.metadata_issuer or self.issuer,
            "authorization_endpoint": f"{base}/authorize",
            "token_endpoint": f"{base}/token",
            "jwks_uri": f"{base}/jwks",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
            "code_challenge_methods_supported": [] if self.omit_s256 else ["S256"],
        }
        return doc

    def authorize(self, authorization_url: str, identity: MockIdentity | None = None) -> str:
        """Play the browser + user: validate the request, return the redirect URL.

        Mirrors what a real provider does at its authorization endpoint.
        """
        parts = urlsplit(authorization_url)
        query = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
        assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{self.issuer}/authorize"
        assert query["response_type"] == "code"
        assert query["client_id"] == self.client_id
        assert query["redirect_uri"] == self.redirect_uri, "redirect_uri must match exactly"
        assert query["code_challenge_method"] == "S256"
        assert query["code_challenge"] and query["state"] and query["nonce"]
        assert "openid" in query["scope"].split()
        code = secrets.token_urlsafe(24)
        self._codes[code] = _IssuedCode(
            client_id=query["client_id"],
            redirect_uri=query["redirect_uri"],
            code_challenge=query["code_challenge"],
            nonce=query["nonce"],
            identity=identity or self.identity,
        )
        return f"{self.redirect_uri}?code={code}&state={query['state']}"

    def _id_token(self, issued: _IssuedCode) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "sub": issued.identity.subject,
            "aud": self.client_id,
            "exp": now + 300,
            "iat": now,
            "nonce": issued.nonce,
        }
        if issued.identity.email is not None:
            claims["email"] = issued.identity.email
            claims["email_verified"] = issued.identity.email_verified
        claims.update(self.token_overrides)
        for name in self.drop_claims:
            claims.pop(name, None)
        header = {"alg": self.header_alg, "kid": "foreign" if self.sign_with_foreign_key else self._active_kid}
        if self.header_alg == "none":
            return _unsecured_jwt(header, claims)
        return jwt.encode(header, claims, self._signing_key())

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/.well-known/openid-configuration":
            if self.fail_discovery:
                return httpx.Response(503, json={"error": "unavailable"})
            return httpx.Response(200, json=self.discovery_document())
        if path == "/jwks":
            if self.fail_jwks:
                return httpx.Response(503, json={"error": "unavailable"})
            return httpx.Response(200, json=self.jwks)
        if path == "/token" and request.method == "POST":
            return self._token(request)
        return httpx.Response(404)

    def _token(self, request: httpx.Request) -> httpx.Response:
        if self.fail_token:
            return httpx.Response(500, json={"error": "server_error"})
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        client_id, client_secret = form.get("client_id"), form.get("client_secret")
        auth = request.headers.get("authorization", "")
        if auth.startswith("Basic "):
            user, _, secret = base64.b64decode(auth[6:]).decode().partition(":")
            client_id, client_secret = user, secret
        if client_id != self.client_id or client_secret != self.client_secret:
            return httpx.Response(401, json={"error": "invalid_client"})
        issued = self._codes.pop(form.get("code", ""), None)  # single use
        if issued is None or form.get("grant_type") != "authorization_code":
            return httpx.Response(400, json={"error": "invalid_grant"})
        if form.get("redirect_uri") != issued.redirect_uri:
            return httpx.Response(400, json={"error": "invalid_grant"})
        verifier = form.get("code_verifier", "")
        digest = hashlib.sha256(verifier.encode()).digest()
        if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != issued.code_challenge:
            return httpx.Response(400, json={"error": "invalid_grant"})
        body: dict[str, Any] = {"access_token": "mock-access-token", "token_type": "Bearer", "expires_in": 300}
        if not self.omit_id_token:
            body["id_token"] = self._id_token(issued)
        return httpx.Response(200, json=body)

    # Adapters ------------------------------------------------------------------
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def asgi_app(self):  # pragma: no cover - used by browser tests only
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse, RedirectResponse, Response
        from starlette.routing import Route

        async def discovery(_request):
            return JSONResponse(self.discovery_document())

        async def jwks(_request):
            return JSONResponse(self.jwks)

        async def authorize(request):
            url = f"{self.issuer}/authorize?{request.url.query}"
            return RedirectResponse(self.authorize(url), status_code=302)

        async def token(request):
            raw = httpx.Request("POST", str(request.url), headers=dict(request.headers), content=await request.body())
            result = self._token(raw)
            return Response(result.content, status_code=result.status_code, media_type="application/json")

        async def set_identity(request):
            data = await request.json()
            self.identity = MockIdentity(**data)
            return JSONResponse({"ok": True})

        return Starlette(
            routes=[
                Route("/.well-known/openid-configuration", discovery),
                Route("/jwks", jwks),
                Route("/authorize", authorize),
                Route("/token", token, methods=["POST"]),
                Route("/__identity", set_identity, methods=["POST"]),
            ]
        )


def _unsecured_jwt(header: dict[str, Any], claims: dict[str, Any]) -> str:
    def b64(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{b64(header)}.{b64(claims)}."
