"""Task 10 independent-review additions to the OIDC protocol tests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from joserfc import jwt

from app.services.oidc import DISCOVERY_TTL_SECONDS, JWKS_TTL_SECONDS, OidcClient
from tests.support.mock_oidc import CLIENT_ID, ISSUER, MockOidcProvider
from tests.unit.test_oidc_service import expect_error, make_config, run_flow


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class _HsConfusionProvider(MockOidcProvider):
    """Issues an HS256 token keyed with the provider's *public* key material.

    The classic algorithm-confusion attack: a verifier that trusts the token's
    ``alg`` and is handed the RSA public key as an HMAC secret would accept it.
    """

    def _id_token(self, issued) -> str:
        now = int(time.time())
        claims = {
            "iss": self.issuer, "sub": "attacker", "aud": self.client_id,
            "exp": now + 300, "iat": now, "nonce": issued.nonce,
            "email": "victim@corp.example", "email_verified": True,
        }
        header = {"alg": "HS256", "typ": "JWT", "kid": self._active_kid}
        signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
        secrets_to_try = json.dumps(self.jwks["keys"][-1]).encode()
        signature = hmac.new(secrets_to_try, signing_input.encode(), hashlib.sha256).digest()
        return f"{signing_input}.{_b64(signature)}"


def test_hs256_algorithm_confusion_token_is_rejected():
    provider = _HsConfusionProvider()
    client = OidcClient(make_config(), transport=provider.transport())
    expect_error(client, provider, "id_token_invalid")


class _Ps256Provider(MockOidcProvider):
    def __post_init__(self) -> None:
        super().__post_init__()
        from joserfc.jwk import RSAKey

        # A key that is not bound to RS256, so PS256 signatures verify at the key level.
        self._keys = [(self._active_kid, RSAKey.generate_key(2048, {"kid": self._active_kid, "use": "sig"}))]

    def _id_token(self, issued) -> str:
        now = int(time.time())
        claims = {
            "iss": self.issuer, "sub": "s", "aud": self.client_id, "exp": now + 300,
            "iat": now, "nonce": issued.nonce, "email": "a@corp.example", "email_verified": True,
        }
        return jwt.encode({"alg": "PS256", "kid": self._active_kid}, claims, self._signing_key(), algorithms=["PS256"])


def test_signature_algorithm_outside_the_providers_advertised_list_is_rejected():
    """Discovery advertises RS256 only; a validly signed PS256 token must not pass."""
    provider = _Ps256Provider()
    client = OidcClient(make_config(), transport=provider.transport())
    expect_error(client, provider, "id_token_invalid")


def test_azp_that_is_not_this_client_is_rejected_even_with_a_single_audience(client, provider):
    provider.token_overrides = {"azp": "another-client"}
    expect_error(client, provider, "id_token_invalid")


def test_token_expired_beyond_leeway_is_rejected_and_just_inside_it_is_not(client, provider):
    provider.token_overrides = {"exp": int(time.time()) - 600}
    expect_error(client, provider, "id_token_invalid")
    provider.token_overrides = {"exp": int(time.time()) - 10}
    assert run_flow(client, provider).subject


@pytest.fixture
def provider():
    return MockOidcProvider()


@pytest.fixture
def client(provider):
    return OidcClient(make_config(), transport=provider.transport())


def test_expired_discovery_cache_is_not_served_when_the_provider_is_down(provider):
    clock = [time.time()]
    client = OidcClient(make_config(), transport=provider.transport(), clock=lambda: clock[0])
    client.start()
    provider.fail_discovery = True
    clock[0] += DISCOVERY_TTL_SECONDS + 1
    with pytest.raises(Exception) as excinfo:
        client.start()
    assert getattr(excinfo.value, "code", None) == "discovery_failed"


def test_expired_jwks_cache_is_not_served_when_the_provider_is_down(provider):
    clock = [time.time()]
    client = OidcClient(make_config(), transport=provider.transport(), clock=lambda: clock[0])
    run_flow(client, provider)
    provider.fail_jwks = True
    clock[0] += JWKS_TTL_SECONDS + 1
    # keep the token fresh relative to the advanced clock
    expect_error(client, provider, "jwks_failed")


def test_discovery_redirects_are_not_followed(provider):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(302, headers={"location": "https://evil.example.test/x"})
        return httpx.Response(404)

    client = OidcClient(make_config(), transport=httpx.MockTransport(handler))
    with pytest.raises(Exception) as excinfo:
        client.start()
    assert getattr(excinfo.value, "code", None) == "discovery_failed"


def test_issuer_constant_is_https():
    assert ISSUER.startswith("https://") and CLIENT_ID
