"""Lease renewal and fencing protect slow EWS operations."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, text

from app.db.models import ExchangeCalendarOutbox
from app.services.exchange_calendar.worker import ExchangeCalendarWorker


def test_worker_claim_timestamp_is_fresh_after_slow_probe_and_bootstrap():
    now = datetime(2026, 10, 2, tzinfo=UTC)
    clock = [now]
    claimed = []

    class Repository:
        def claim(self, at):
            claimed.append(at)
            return None

    class Client:
        def probe(self):
            clock[0] += timedelta(minutes=4)

    def bootstrap(at):
        clock[0] += timedelta(minutes=4)

    worker = ExchangeCalendarWorker(
        Repository(), Client(), bootstrap=bootstrap, clock=lambda: clock[0]
    )
    assert worker.run_once(now) is False
    assert claimed == [now + timedelta(minutes=8)]


def test_lease_renews_during_blocking_work_and_stops_after_exit():
    from app.services.exchange_calendar.lease import maintain_lease

    renewed = Event()
    calls = []

    def renew():
        calls.append(1)
        if len(calls) >= 2:
            renewed.set()
        return True

    with maintain_lease(renew, interval=0.01):
        assert renewed.wait(2), "lease was not renewed while work was blocked"
    count = len(calls)
    assert count >= 2


def test_client_cannot_mutate_after_ownership_lost_during_lookup():
    from app.services.exchange_calendar.ews_client import ExchangeCalendarClient
    from app.services.exchange_calendar.lease import LeaseLost, maintain_lease

    owned = [True]
    mutations = []

    class Store:
        def find(self, key):
            owned[0] = False
            return SimpleNamespace()

        def delete(self, item):
            mutations.append(item)

    with maintain_lease(lambda: owned[0], interval=60), pytest.raises(LeaseLost):
        ExchangeCalendarClient(Store()).cancel("duty_shift:test", None)
    assert mutations == []


def test_http_guard_checks_ownership_after_waiting_for_global_permit(monkeypatch):
    from requests import Request, Response
    from requests.adapters import HTTPAdapter

    from app.services.exchange_calendar.lease import LeaseLost, maintain_lease
    from app.services.exchange_calendar.rate_limiter import RateLimitedHTTPAdapter

    owned = [True]
    sent = []

    @contextmanager
    def permit():
        owned[0] = False
        yield

    def send(*args, **kwargs):
        sent.append(1)
        response = Response()
        response._content = b""
        return response

    monkeypatch.setattr(HTTPAdapter, "send", send)
    with maintain_lease(lambda: owned[0], interval=60), pytest.raises(LeaseLost):
        RateLimitedHTTPAdapter(permit=permit).send(
            Request("POST", "https://offline.test").prepare()
        )
    assert sent == []


def test_renewal_rejects_expired_or_reclaimed_generation(admin_session):
    from app.services.exchange_calendar.outbox import claim_next_job, enqueue_source, renew_lease

    admin_session.execute(delete(ExchangeCalendarOutbox))
    now = datetime.now(UTC) + timedelta(seconds=1)
    enqueue_source(admin_session, "duty_shift", uuid4(), priority=100, reason="test")
    job = claim_next_job(admin_session, worker_id="one", now=now)
    assert renew_lease(
        admin_session,
        job.id,
        worker_id="one",
        attempt_count=job.attempt_count,
        now=now + timedelta(minutes=4),
    )
    admin_session.refresh(job)
    assert job.lease_expires_at > now + timedelta(minutes=8)
    assert not renew_lease(
        admin_session, job.id, worker_id="other", attempt_count=job.attempt_count, now=now
    )
    assert not renew_lease(
        admin_session, job.id, worker_id="one", attempt_count=job.attempt_count - 1, now=now
    )
    assert not renew_lease(
        admin_session,
        job.id,
        worker_id="one",
        attempt_count=job.attempt_count,
        now=now + timedelta(minutes=10),
    )


def test_inflight_source_lock_prevents_reclaim_of_expired_lease(admin_session, admin_engine):
    from app.services.exchange_calendar.outbox import claim_next_job, enqueue_source, lease_lock_key

    admin_session.execute(delete(ExchangeCalendarOutbox))
    now = datetime.now(UTC) + timedelta(seconds=1)
    enqueue_source(admin_session, "duty_shift", uuid4(), priority=100, reason="test")
    job = claim_next_job(admin_session, worker_id="one", now=now)
    admin_session.commit()
    with admin_engine.connect() as connection:
        key = lease_lock_key(job.id)
        connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
        try:
            assert (
                claim_next_job(admin_session, worker_id="two", now=now + timedelta(minutes=10))
                is None
            )
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
    assert (
        claim_next_job(admin_session, worker_id="two", now=now + timedelta(minutes=10)) is not None
    )
