from datetime import UTC, date, datetime, timedelta
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

    worker = ExchangeCalendarWorker(Repo(), Client(), bootstrap=lambda at: None, clock=lambda: now)
    assert worker.run_once(now) is False
    assert seen[0]["reachable"] is False
    assert seen[0]["backoff_until"] == now + timedelta(seconds=60)
    assert "private" not in seen[0]["error"]



@pytest.mark.parametrize("source_date", [date(2024, 1, 1), date(2028, 1, 1)])
def test_tracked_event_projects_outside_creation_window(monkeypatch, source_date):
    from uuid import uuid4

    from app.services.exchange_calendar import worker as worker_module
    from app.services.exchange_calendar.worker import SqlCalendarRepository

    source_id = uuid4()
    observed = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def scalar(self, statement):
            return SimpleNamespace(exchange_item_id="ews-1")

        def get(self, model, key):
            return SimpleNamespace(start_date=source_date)

    class Factory:
        def __call__(self):
            return Session()

    def project_source(session, kind, key, *, today):
        observed.append(today)
        return "still official"

    monkeypatch.setattr(worker_module, "project_source", project_source)
    repository = SqlCalendarRepository(Factory(), "worker")
    job = SimpleNamespace(source_type="duty_shift", source_id=source_id)
    assert repository.project(job, datetime(2026, 10, 1, tzinfo=UTC)) == "still official"
    assert observed == [source_date]





def test_reconciliation_repairs_remote_edit_despite_matching_local_hash():
    from uuid import uuid4

    source_id = uuid4()
    now = datetime(2026, 10, 1, tzinfo=UTC)
    snapshot = SimpleNamespace(
        source_key=f"duty_shift:{source_id}", content_hash="same",
        start=now, problems=(),
    )
    job = SimpleNamespace(source_type="duty_shift", source_id=source_id, reason="backfill")
    calls = []

    class Repo:
        def claim(self, at):
            return job

        def current(self, claimed):
            return SimpleNamespace(exchange_item_id="ews", exchange_change_key="ck", content_hash="same")

        def project(self, claimed, at):
            return snapshot

        def complete(self, claimed, result, at):
            calls.append(result.action)

    class Client:
        def probe(self):
            pass

        def matches(self, event, item_id):
            calls.append("remote-read")
            return False

        def upsert(self, event, item_id, change_key):
            calls.append("remote-update")
            return SimpleNamespace(action="updated", item_id="ews", change_key="ck2")

    worker = ExchangeCalendarWorker(Repo(), Client(), bootstrap=lambda at: None)
    assert worker.run_once(now)
    assert calls == ["remote-read", "remote-update", "updated"]


def test_cancellation_recovers_remote_item_when_local_id_was_not_persisted():
    from uuid import uuid4

    source_id = uuid4()
    now = datetime(2026, 10, 1, tzinfo=UTC)
    job = SimpleNamespace(source_type="duty_shift", source_id=source_id, reason="user_change")
    calls = []

    class Repo:
        def claim(self, at):
            return job

        def current(self, claimed):
            return SimpleNamespace(exchange_item_id=None, exchange_change_key=None, content_hash=None)

        def project(self, claimed, at):
            return None

        def complete(self, claimed, result, at):
            calls.append(result.action)

    class Client:
        def probe(self):
            pass

        def cancel(self, source_key, item_id):
            calls.append((source_key, item_id))

    worker = ExchangeCalendarWorker(Repo(), Client(), bootstrap=lambda at: None)
    assert worker.run_once(now)
    assert calls == [(f"duty_shift:{source_id}", None), "cancelled"]




@pytest.mark.parametrize("error_name", ["ErrorTimeoutExpired", "ErrorInternalServerTransientError"])
def test_exchangelib_transient_errors_remain_retryable(error_name):
    from exchangelib import errors

    now = datetime(2026, 10, 1, tzinfo=UTC)
    job = SimpleNamespace(attempt_count=2)
    worker = ExchangeCalendarWorker(object(), object(), bootstrap=lambda at: None, jitter=lambda: 0)
    result = worker._failure(getattr(errors, error_name)("secret server detail"), job, now)
    assert result.retry_at is not None and result.retry_at > now
    assert result.error_category == "exchange_unavailable"
    assert "secret" not in result.error_message




def test_failed_probe_blocks_claims_and_persists_shared_outage():
    from exchangelib.errors import ErrorTimeoutExpired

    now = datetime(2026, 10, 1, tzinfo=UTC)
    calls = []

    class Repo:
        def probe_result(self, at, **kwargs):
            calls.append(("probe-result", kwargs))

        def claim(self, at):
            calls.append(("claim", at))
            return None

    class Client:
        def probe(self):
            calls.append(("probe", None))
            raise ErrorTimeoutExpired("offline secret")

    worker = ExchangeCalendarWorker(Repo(), Client(), bootstrap=lambda at: None, clock=lambda: now)
    assert worker.run_once(now) is False
    assert worker.run_once(now + timedelta(seconds=1)) is False
    assert [name for name, _ in calls] == ["probe", "probe-result"]
    assert calls[1][1]["backoff_until"] == now + timedelta(seconds=60)




def test_server_busy_honors_requested_five_minute_backoff():
    from exchangelib.errors import ErrorServerBusy

    now = datetime(2026, 10, 1, tzinfo=UTC)
    job = SimpleNamespace(attempt_count=1)
    worker = ExchangeCalendarWorker(object(), object(), bootstrap=lambda at: None)
    result = worker._failure(ErrorServerBusy("busy", back_off=300), job, now)
    assert result.retry_at == now + timedelta(minutes=5)
    assert result.global_backoff_until == result.retry_at


@pytest.mark.database
def test_new_busy_result_cannot_shorten_shared_backoff(app_engine):
    from sqlalchemy.orm import sessionmaker

    from app.db.models import ExchangeCalendarWorkerState
    from app.services.exchange_calendar.worker import SqlCalendarRepository

    factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    repository = SqlCalendarRepository(factory, "worker-a")
    now = datetime(2026, 10, 1, tzinfo=UTC)
    repository.probe_result(now, reachable=False, backoff_until=now + timedelta(minutes=5))
    repository.probe_result(now + timedelta(minutes=1), reachable=False, backoff_until=now + timedelta(minutes=2))
    with factory() as session:
        assert session.get(ExchangeCalendarWorkerState, 1).global_backoff_until == now + timedelta(minutes=5)




@pytest.mark.database
def test_retry_merges_into_queued_edit_during_lease(app_engine):
    from uuid import uuid4

    from sqlalchemy import select
    from sqlalchemy.orm import sessionmaker

    from app.db.models import ExchangeCalendarOutbox, ExchangeCalendarSyncItem
    from app.services.exchange_calendar.worker import SqlCalendarRepository, WorkerOutcome

    factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    source_id = uuid4()
    now = datetime(2026, 10, 1, tzinfo=UTC)
    retry_at = now + timedelta(minutes=5)
    with factory.begin() as session:
        session.add(ExchangeCalendarSyncItem(source_type="duty_shift", source_id=source_id, status="in_progress"))
        leased = ExchangeCalendarOutbox(
            source_type="duty_shift", source_id=source_id, reason="prior_edit",
            priority=50, status="leased", lease_owner="worker-a",
            lease_expires_at=now + timedelta(minutes=10), attempt_count=1,
        )
        sibling = ExchangeCalendarOutbox(
            source_type="duty_shift", source_id=source_id, reason="user_change",
            priority=100, status="queued", attempt_count=0,
        )
        session.add_all([leased, sibling])
        session.flush()
        leased_id, sibling_id = leased.id, sibling.id
    repo = SqlCalendarRepository(factory, "worker-a")
    assert repo.complete(
        SimpleNamespace(id=leased_id),
        WorkerOutcome("failed", error_category="exchange_unavailable", error_message="Exchange request failed", retry_at=retry_at),
        now,
    )
    with factory() as session:
        jobs = {job.id: job for job in session.scalars(select(ExchangeCalendarOutbox)).all()}
        assert jobs[leased_id].status == "completed"
        assert jobs[sibling_id].status == "queued"
        assert jobs[sibling_id].reason == "user_change"
        assert jobs[sibling_id].priority == 100
        assert jobs[sibling_id].next_attempt_at >= retry_at
