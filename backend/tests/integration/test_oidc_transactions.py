"""One-time, browser-bound OIDC transactions persisted server-side."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.models import OidcTransaction
from app.services.oidc import OidcClient, OidcError
from app.services.oidc_transactions import begin_transaction, consume_transaction
from tests.support.mock_oidc import MockOidcProvider
from tests.unit.test_oidc_service import make_config


@pytest.fixture
def oidc_client() -> OidcClient:
    return OidcClient(make_config(), transport=MockOidcProvider().transport())


def test_begin_returns_request_and_browser_token_and_stores_only_hashes_of_lookup_keys(
    admin_session, oidc_client
):
    request, browser_token = begin_transaction(admin_session, oidc_client)
    admin_session.commit()
    row = admin_session.execute(select(OidcTransaction)).scalar_one()
    assert row.nonce == request.nonce and row.code_verifier == request.code_verifier
    assert request.state not in (row.state_hash, row.browser_hash)
    assert browser_token not in (row.state_hash, row.browser_hash)
    assert len(row.state_hash) == 64 and len(row.browser_hash) == 64
    assert row.consumed_at is None
    ttl = row.expires_at - row.created_at
    assert timedelta(seconds=250) < ttl <= timedelta(seconds=301)


def test_consume_returns_nonce_and_verifier_once(admin_session, oidc_client):
    request, browser = begin_transaction(admin_session, oidc_client)
    admin_session.commit()
    consumed = consume_transaction(admin_session, state=request.state, browser_token=browser)
    admin_session.commit()
    assert consumed.nonce == request.nonce and consumed.code_verifier == request.code_verifier
    with pytest.raises(OidcError) as excinfo:  # replay
        consume_transaction(admin_session, state=request.state, browser_token=browser)
    assert excinfo.value.code == "transaction_invalid"


def test_unknown_state_is_rejected(admin_session, oidc_client):
    _request, browser = begin_transaction(admin_session, oidc_client)
    admin_session.commit()
    with pytest.raises(OidcError) as excinfo:
        consume_transaction(admin_session, state="not-a-real-state", browser_token=browser)
    assert excinfo.value.code == "transaction_invalid"


@pytest.mark.parametrize("browser_token", [None, "", "someone-elses-cookie"])
def test_wrong_browser_is_rejected_and_burns_the_transaction(admin_session, oidc_client, browser_token):
    request, browser = begin_transaction(admin_session, oidc_client)
    admin_session.commit()
    with pytest.raises(OidcError) as excinfo:
        consume_transaction(admin_session, state=request.state, browser_token=browser_token)
    assert excinfo.value.code == "browser_mismatch"
    admin_session.commit()
    with pytest.raises(OidcError):  # the legitimate browser cannot reuse a burnt transaction
        consume_transaction(admin_session, state=request.state, browser_token=browser)


def test_expired_transaction_is_rejected(admin_session, oidc_client):
    request, browser = begin_transaction(admin_session, oidc_client)
    admin_session.commit()
    later = datetime.now(timezone.utc) + timedelta(seconds=301)
    with pytest.raises(OidcError) as excinfo:
        consume_transaction(admin_session, state=request.state, browser_token=browser, now=later)
    assert excinfo.value.code == "transaction_invalid"


def test_concurrent_consumption_succeeds_exactly_once(admin_engine, admin_session, oidc_client):
    request, browser = begin_transaction(admin_session, oidc_client)
    admin_session.commit()
    factory = sessionmaker(bind=admin_engine, expire_on_commit=False)
    barrier = threading.Barrier(4)
    results: list[str] = []

    def worker() -> None:
        with factory() as session:
            barrier.wait()
            try:
                consume_transaction(session, state=request.state, browser_token=browser)
                session.commit()
                results.append("ok")
            except OidcError:
                session.rollback()
                results.append("denied")

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["denied", "denied", "denied", "ok"]


def test_begin_purges_long_expired_rows(admin_session, oidc_client):
    old_request, _ = begin_transaction(admin_session, oidc_client)
    admin_session.commit()
    row = admin_session.execute(select(OidcTransaction)).scalar_one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(days=2)
    admin_session.commit()
    begin_transaction(admin_session, oidc_client)
    admin_session.commit()
    rows = admin_session.execute(select(OidcTransaction)).scalars().all()
    assert len(rows) == 1 and rows[0].nonce != old_request.nonce
