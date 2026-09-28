"""Disposable Gromox smoke test. Never runs without an explicit opt-in."""

import os

import pytest

pytestmark = pytest.mark.exchange_integration


def test_disposable_gromox_probe():
    if os.getenv("JUSTICE_TEST_GROMOX_ENABLED") != "1":
        pytest.skip("Gromox integration is opt-in")
    names = (
        "JUSTICE_TEST_GROMOX_ENDPOINT",
        "JUSTICE_TEST_GROMOX_MAILBOX",
        "JUSTICE_TEST_GROMOX_USERNAME",
        "JUSTICE_TEST_GROMOX_PASSWORD",
    )
    if not all(os.getenv(name) for name in names):
        pytest.skip("Disposable Gromox endpoint and mailbox secrets are absent")
    # A local gate is sufficient for this disposable, single-process smoke run.
    # Production uses DatabaseGate in app.exchange_calendar_worker.
    from app.services.exchange_calendar.ews_client import ExchangeCalendarClient, build_account
    from app.services.exchange_calendar.rate_limiter import ExchangeRateLimiter, InMemoryGate

    account = build_account(
        endpoint=os.environ[names[0]], mailbox=os.environ[names[1]],
        username=os.environ[names[2]], password=os.environ[names[3]],
        auth_type=os.getenv("JUSTICE_TEST_GROMOX_AUTH_TYPE") or None,
        permit=ExchangeRateLimiter(InMemoryGate()).permit,
    )
    ExchangeCalendarClient.from_account(account).probe()
