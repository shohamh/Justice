"""OIDC protocol service against the local mock provider (no DB, no sockets)."""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from app.services.oidc import OidcClient, OidcConfig, OidcError, load_oidc_config
from tests.support.mock_oidc import (
    CLIENT_ID,
    CLIENT_SECRET,
    ISSUER,
    REDIRECT_URI,
    MockIdentity,
    MockOidcProvider,
)


def make_config(**overrides) -> OidcConfig:
    values = dict(
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        transaction_ttl_seconds=300,
        registration_ttl_seconds=900,
        allow_insecure_local=False,
    )
    values.update(overrides)
    return OidcConfig(**values)


@pytest.fixture
def provider() -> MockOidcProvider:
    return MockOidcProvider()


@pytest.fixture
def client(provider) -> OidcClient:
    return OidcClient(make_config(), transport=provider.transport())


def run_flow(client: OidcClient, provider: MockOidcProvider, *, identity: MockIdentity | None = None):
    request = client.start()
    redirect = provider.authorize(request.url, identity)
    code = parse_qs(urlsplit(redirect).query)["code"][0]
    return client.complete(code=code, code_verifier=request.code_verifier, nonce=request.nonce)


def expect_error(client, provider, code: str | None = None, **flow):
    with pytest.raises(OidcError) as excinfo:
        run_flow(client, provider, **flow)
    if code is not None:
        assert excinfo.value.code == code
    return excinfo.value


# --- configuration ---------------------------------------------------------------


class FakeSettings:
    oidc_issuer = ISSUER
    oidc_client_id = CLIENT_ID
    oidc_client_secret = CLIENT_SECRET
    oidc_redirect_uri = REDIRECT_URI
    oidc_transaction_ttl_seconds = 300
    oidc_registration_ttl_seconds = 900
    oidc_allow_insecure_local = False

    def __init__(self, **overrides):
        for key, value in overrides.items():
            setattr(self, key, value)


def test_config_is_disabled_when_absent():
    assert load_oidc_config(FakeSettings(oidc_issuer="", oidc_client_id="", oidc_redirect_uri="")) is None


def test_config_valid():
    config = load_oidc_config(FakeSettings())
    assert config is not None
    assert (config.issuer, config.client_id, config.redirect_uri) == (ISSUER, CLIENT_ID, REDIRECT_URI)


@pytest.mark.parametrize(
    "overrides",
    [
        {"oidc_issuer": "http://idp.example.test"},  # plain http outside local development
        {"oidc_issuer": "https://idp.example.test?x=1"},
        {"oidc_issuer": "https://user:pw@idp.example.test"},
        {"oidc_issuer": "https://idp.example.test#frag"},
        {"oidc_client_id": ""},
        {"oidc_redirect_uri": ""},
        {"oidc_redirect_uri": "http://justice.example.test/cb"},
        {"oidc_redirect_uri": "https://justice.example.test/cb#frag"},
        {"oidc_redirect_uri": "https://justice.example.test/cb?x=1"},
        {"oidc_redirect_uri": "/relative/callback"},
        {"oidc_transaction_ttl_seconds": 0},
        {"oidc_transaction_ttl_seconds": 3600},
        {"oidc_registration_ttl_seconds": 0},
    ],
)
def test_config_invalid_values_disable_oidc(overrides):
    assert load_oidc_config(FakeSettings(**overrides)) is None


def test_config_http_only_for_loopback_with_explicit_flag():
    local = dict(
        oidc_issuer="http://localhost:9000",
        oidc_redirect_uri="http://localhost:5173/api/auth/oidc/callback",
    )
    assert load_oidc_config(FakeSettings(**local)) is None
    assert load_oidc_config(FakeSettings(**local, oidc_allow_insecure_local=True)) is not None
    remote = dict(oidc_issuer="http://idp.example.test", oidc_allow_insecure_local=True)
    assert load_oidc_config(FakeSettings(**remote)) is None


def test_config_does_not_expose_secret_in_repr():
    config = load_oidc_config(FakeSettings())
    assert CLIENT_SECRET not in repr(config)


# --- authorization request -----------------------------------------------------------


def test_start_builds_code_flow_with_pkce_s256(client, provider):
    request = client.start()
    parts = urlsplit(request.url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{ISSUER}/authorize"
    assert query["response_type"] == "code"
    assert query["client_id"] == CLIENT_ID
    assert query["redirect_uri"] == REDIRECT_URI
    assert query["scope"].split() == ["openid", "email"]
    assert query["code_challenge_method"] == "S256"
    digest = hashlib.sha256(request.code_verifier.encode()).digest()
    assert query["code_challenge"] == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert 43 <= len(request.code_verifier) <= 128
    assert query["state"] == request.state and query["nonce"] == request.nonce
    assert len(request.state) >= 32 and len(request.nonce) >= 32
    assert CLIENT_SECRET not in request.url
    assert request.code_verifier not in request.url


def test_start_values_are_random_per_transaction(client):
    first, second = client.start(), client.start()
    assert len({first.state, second.state}) == 2
    assert len({first.nonce, second.nonce}) == 2
    assert len({first.code_verifier, second.code_verifier}) == 2


def test_start_discovers_only_from_the_configured_issuer(client, provider):
    client.start()
    urls = {str(r.url) for r in provider.requests}
    assert urls == {f"{ISSUER}/.well-known/openid-configuration"}


def test_start_refuses_provider_without_s256(provider):
    provider.omit_s256 = True
    client = OidcClient(make_config(), transport=provider.transport())
    with pytest.raises(OidcError) as excinfo:
        client.start()
    assert excinfo.value.code == "pkce_unsupported"


def test_discovery_issuer_must_match_exactly(provider):
    provider.metadata_issuer = "https://evil.example.test"
    client = OidcClient(make_config(), transport=provider.transport())
    with pytest.raises(OidcError) as excinfo:
        client.start()
    assert excinfo.value.code == "discovery_issuer_mismatch"


def test_discovery_rejects_insecure_endpoints(provider):
    original = provider.discovery_document

    def doc():
        data = original()
        data["token_endpoint"] = "http://idp.example.test/token"
        return data

    provider.discovery_document = doc
    client = OidcClient(make_config(), transport=provider.transport())
    with pytest.raises(OidcError) as excinfo:
        client.start()
    assert excinfo.value.code == "discovery_invalid"


def test_discovery_outage_denies(provider):
    provider.fail_discovery = True
    client = OidcClient(make_config(), transport=provider.transport())
    with pytest.raises(OidcError) as excinfo:
        client.start()
    assert excinfo.value.code == "discovery_failed"


# --- code exchange and ID token validation --------------------------------------------


def test_complete_returns_verified_identity(client, provider):
    identity = run_flow(client, provider, identity=MockIdentity(subject="abc-123", email="Dude@Corp.Example"))
    assert identity.issuer == ISSUER
    assert identity.subject == "abc-123"
    assert identity.email == "Dude@Corp.Example"  # raw claim; the caller normalizes
    assert "abc-123" not in repr(identity) and "Corp" not in repr(identity)


def test_complete_authenticates_with_client_secret_basic(client, provider):
    run_flow(client, provider)
    token_requests = [r for r in provider.requests if r.url.path == "/token"]
    assert len(token_requests) == 1
    assert token_requests[0].headers["authorization"].startswith("Basic ")
    assert CLIENT_SECRET not in token_requests[0].content.decode()


def test_complete_sends_verifier_and_exact_redirect_uri(client, provider):
    request = client.start()
    redirect = provider.authorize(request.url)
    code = parse_qs(urlsplit(redirect).query)["code"][0]
    client.complete(code=code, code_verifier=request.code_verifier, nonce=request.nonce)
    body = parse_qs([r for r in provider.requests if r.url.path == "/token"][0].content.decode())
    assert body["code_verifier"] == [request.code_verifier]
    assert body["redirect_uri"] == [REDIRECT_URI]
    assert body["grant_type"] == ["authorization_code"]


def test_wrong_pkce_verifier_is_rejected(client, provider):
    request = client.start()
    code = parse_qs(urlsplit(provider.authorize(request.url)).query)["code"][0]
    with pytest.raises(OidcError) as excinfo:
        client.complete(code=code, code_verifier="x" * 50, nonce=request.nonce)
    assert excinfo.value.code == "token_exchange_failed"


def test_authorization_code_is_single_use(client, provider):
    request = client.start()
    code = parse_qs(urlsplit(provider.authorize(request.url)).query)["code"][0]
    client.complete(code=code, code_verifier=request.code_verifier, nonce=request.nonce)
    with pytest.raises(OidcError):
        client.complete(code=code, code_verifier=request.code_verifier, nonce=request.nonce)


def test_nonce_mismatch_is_rejected(client, provider):
    request = client.start()
    code = parse_qs(urlsplit(provider.authorize(request.url)).query)["code"][0]
    with pytest.raises(OidcError) as excinfo:
        client.complete(code=code, code_verifier=request.code_verifier, nonce="a-different-nonce")
    assert excinfo.value.code == "id_token_invalid"


def test_missing_nonce_claim_is_rejected(client, provider):
    provider.drop_claims = {"nonce"}
    expect_error(client, provider, "id_token_invalid")


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://evil.example.test"},
        {"iss": ISSUER + "/"},
        {"aud": "another-client"},
        {"aud": ["another-client", "yet-another"]},
        {"aud": [CLIENT_ID, "other"], "azp": "other"},
        {"exp": int(time.time()) - 3600},
        {"iat": int(time.time()) + 3600},
        {"nbf": int(time.time()) + 3600},
    ],
)
def test_invalid_claims_are_rejected(client, provider, overrides):
    provider.token_overrides = overrides
    expect_error(client, provider, "id_token_invalid")


@pytest.mark.parametrize("claim", ["iss", "aud", "exp", "iat", "sub"])
def test_missing_required_claims_are_rejected(client, provider, claim):
    provider.drop_claims = {claim}
    expect_error(client, provider, "id_token_invalid")


def test_multiple_audiences_require_matching_azp(client, provider):
    provider.token_overrides = {"aud": [CLIENT_ID, "other"], "azp": CLIENT_ID}
    assert run_flow(client, provider).subject == "sub-0001"
    provider.token_overrides = {"aud": [CLIENT_ID, "other"]}
    expect_error(client, provider, "id_token_invalid")


def test_signature_from_unknown_key_is_rejected(client, provider):
    provider.sign_with_foreign_key = True
    expect_error(client, provider, "id_token_invalid")


def test_unsigned_token_is_rejected(client, provider):
    provider.header_alg = "none"
    expect_error(client, provider, "id_token_invalid")


def test_missing_id_token_is_rejected(client, provider):
    provider.omit_id_token = True
    expect_error(client, provider, "id_token_missing")


@pytest.mark.parametrize("verified", [False, "false", None, "yes", 1, 0])
def test_unverified_email_is_rejected(client, provider, verified):
    expect_error(
        client, provider, "email_not_verified",
        identity=MockIdentity(email="dude@corp.example", email_verified=verified),
    )


def test_missing_email_verified_claim_is_rejected(client, provider):
    provider.drop_claims = {"email_verified"}
    expect_error(client, provider, "email_not_verified")


def test_string_true_email_verified_is_accepted(client, provider):
    identity = run_flow(client, provider, identity=MockIdentity(email_verified="true"))
    assert identity.email == "dude@corp.example"


@pytest.mark.parametrize("email", [None, "", "   ", 42])
def test_missing_or_blank_email_is_rejected(client, provider, email):
    provider.token_overrides = {"email": email}
    if email is None:
        provider.token_overrides = {}
        provider.drop_claims = {"email"}
    expect_error(client, provider, "email_missing")


def test_token_endpoint_failure_denies(client, provider):
    provider.fail_token = True
    expect_error(client, provider, "token_exchange_failed")


def test_wrong_client_secret_denies(provider):
    client = OidcClient(make_config(client_secret="wrong-secret"), transport=provider.transport())
    expect_error(client, provider, "token_exchange_failed")


# --- JWKS --------------------------------------------------------------------------


def test_jwks_outage_denies_login(client, provider):
    provider.fail_jwks = True
    expect_error(client, provider, "jwks_failed")


def test_key_rotation_refreshes_jwks_once(provider):
    clock = [time.time()]
    client = OidcClient(make_config(), transport=provider.transport(), clock=lambda: clock[0])
    run_flow(client, provider)  # caches the first key set
    provider.rotate_keys(keep_old=False)
    clock[0] += 120  # past the refresh throttle
    assert run_flow(client, provider).subject == "sub-0001"


def test_unknown_key_refresh_is_throttled(provider):
    clock = [time.time()]
    client = OidcClient(make_config(), transport=provider.transport(), clock=lambda: clock[0])
    run_flow(client, provider)
    jwks_calls = lambda: len([r for r in provider.requests if r.url.path == "/jwks"])  # noqa: E731
    before = jwks_calls()
    provider.sign_with_foreign_key = True
    for _ in range(5):
        expect_error(client, provider, "id_token_invalid")
    assert jwks_calls() - before <= 1  # bounded refresh, not one fetch per bad token


# --- redaction -------------------------------------------------------------------------


def test_failures_never_log_codes_tokens_state_nonce_or_email(client, provider, caplog):
    caplog.set_level(logging.DEBUG)
    request = client.start()
    code = parse_qs(urlsplit(provider.authorize(request.url)).query)["code"][0]
    provider.token_overrides = {"iss": "https://evil.example.test"}
    with pytest.raises(OidcError):
        client.complete(code=code, code_verifier=request.code_verifier, nonce=request.nonce)
    log_text = caplog.text
    for secret in (code, request.state, request.nonce, request.code_verifier, CLIENT_SECRET, "dude@corp.example", "mock-access-token"):
        assert secret not in log_text
    error = OidcError("id_token_invalid")
    assert "dude@corp.example" not in str(error)
