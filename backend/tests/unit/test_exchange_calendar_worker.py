from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services.exchange_calendar.worker import ExchangeCalendarWorker


def test_startup_probe_and_six_hour_bootstrap():
    calls = []

    class Repository:
        def claim(self, now):
            return None

    class Client:
        def probe(self):
            calls.append("probe")

    worker = ExchangeCalendarWorker(Repository(), Client(), bootstrap=lambda now: calls.append("bootstrap"))
    now = datetime(2026, 10, 1, tzinfo=UTC)
    for at in (now, now + timedelta(minutes=14), now + timedelta(minutes=15), now + timedelta(hours=6)):
        assert worker.run_once(at) is False
    assert calls == ["probe", "bootstrap", "probe", "probe", "bootstrap"]


def test_worker_claims_and_projects_latest_before_ews():
    calls = []
    snapshot = SimpleNamespace(content_hash="new", source_key="justice:test", problems=())
    job = SimpleNamespace(id=1, source_type="duty_shift", source_id=2)

    class Repository:
        def claim(self, now):
            calls.append("claim")
            return job

        def project(self, claimed, now):
            calls.append("project")
            return snapshot

        def current(self, claimed):
            return SimpleNamespace(exchange_item_id=None, exchange_change_key=None, content_hash=None)

        def complete(self, claimed, result, now, **kwargs):
            calls.append("complete")

    class Client:
        def probe(self):
            calls.append("probe")

        def upsert(self, item, item_id, change_key):
            calls.append("upsert")
            return SimpleNamespace(item_id="ews", change_key="ck", action="created")

    worker = ExchangeCalendarWorker(Repository(), Client(), bootstrap=lambda now: calls.append("bootstrap"))
    assert worker.run_once(datetime(2026, 10, 1, tzinfo=UTC))
    assert calls == ["probe", "bootstrap", "claim", "project", "upsert", "complete"]



def test_unchanged_content_skips_ews_and_cancelled_source_sends_cancellation():
    from uuid import uuid4

    calls = []
    source_id = uuid4()
    job = SimpleNamespace(id=uuid4(), source_type="duty_shift", source_id=source_id, attempt_count=1)
    snapshot = SimpleNamespace(
        source_key=f"duty_shift:{source_id}", content_hash="same",
        start=datetime(2026, 10, 1, tzinfo=UTC), problems=(),
    )

    class Repo:
        def __init__(self):
            self.snapshot = snapshot
            self.results = []

        def claim(self, now):
            return job

        def current(self, claimed):
            return SimpleNamespace(exchange_item_id="ews", exchange_change_key="ck", content_hash="same")

        def project(self, claimed, now):
            return self.snapshot

        def complete(self, claimed, result, now, **kwargs):
            self.results.append(result)

    class Client:
        def probe(self):
            pass

        def upsert(self, *args):
            raise AssertionError("unchanged content sent EWS update")

        def cancel(self, key, item_id):
            calls.append((key, item_id))

    repo = Repo()
    worker = ExchangeCalendarWorker(repo, Client(), bootstrap=lambda now: None)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    assert worker.run_once(now)
    assert repo.results[-1].action == "unchanged"
    repo.snapshot = None
    assert worker.run_once(now + timedelta(minutes=1))
    assert calls == [(f"duty_shift:{source_id}", "ews")]
    assert repo.results[-1].action == "cancelled"


def test_server_busy_sets_shared_backoff_and_preserves_job():
    from exchangelib.errors import ErrorServerBusy

    now = datetime(2026, 10, 1, tzinfo=UTC)
    job = SimpleNamespace(attempt_count=2)
    worker = ExchangeCalendarWorker(object(), object(), bootstrap=lambda at: None)
    result = worker._failure(ErrorServerBusy("secret detail"), job, now)
    assert result.retry_at > now
    assert result.global_backoff_until == result.retry_at
    assert "secret" not in result.error_message
    assert worker._failure(ValueError("secret detail"), job, now).retry_at is None




def test_stale_owner_cannot_persist_outcome():
    from contextlib import contextmanager
    from uuid import uuid4

    from app.services.exchange_calendar.worker import SqlCalendarRepository, WorkerOutcome

    now = datetime(2026, 10, 1, tzinfo=UTC)
    claimed = SimpleNamespace(id=uuid4())

    class Session:
        def scalar(self, statement):
            return SimpleNamespace(
                status="leased", lease_owner="new-owner",
                lease_expires_at=now + timedelta(minutes=5),
            )

    class Factory:
        @contextmanager
        def begin(self):
            yield Session()

    repository = SqlCalendarRepository(Factory(), "old-owner")
    assert repository.complete(claimed, WorkerOutcome("created", item_id="stale"), now) is False




@pytest.mark.database
def test_repository_seeds_state_and_keeps_active_shared_backoff(app_engine):
    from sqlalchemy.orm import sessionmaker

    from app.db.models import ExchangeCalendarWorkerState
    from app.services.exchange_calendar.worker import SqlCalendarRepository

    factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    repository = SqlCalendarRepository(factory, "worker-a")
    now = datetime(2026, 10, 1, tzinfo=UTC)
    repository.heartbeat(now)
    with factory.begin() as session:
        state = session.get(ExchangeCalendarWorkerState, 1)
        assert state is not None
        state.global_backoff_until = now + timedelta(minutes=5)
    repository.probe_result(now + timedelta(minutes=1), reachable=True)
    with factory() as session:
        assert session.get(ExchangeCalendarWorkerState, 1).global_backoff_until == now + timedelta(minutes=5)



def test_busy_probe_sets_shared_backoff():
    from exchangelib.errors import ErrorServerBusy

    seen = []
    now = datetime(2026, 10, 1, tzinfo=UTC)

    class Repo:
        def probe_result(self, at, **kwargs):
            seen.append(kwargs)

    class Client:
        def probe(self):
            raise ErrorServerBusy("private EWS text")

    worker = ExchangeCalendarWorker(Repo(), Client(), bootstrap=lambda at: None)
    assert worker.run_once(now) is False
    assert seen[0]["reachable"] is False
    assert seen[0]["backoff_until"] == now + timedelta(seconds=60)
    assert "private" not in seen[0]["error"]
