"""Tests for the shared Exchange request gate."""

import pytest

from app.services.exchange_calendar.rate_limiter import ExchangeRateLimiter


def test_rate_is_bounded():
    assert ExchangeRateLimiter.spacing_seconds(200) == pytest.approx(0.3)
    assert ExchangeRateLimiter.spacing_seconds(60) == pytest.approx(1)
    with pytest.raises(ValueError):
        ExchangeRateLimiter.spacing_seconds(201)



def test_adapter_gates_every_send(monkeypatch):
    from contextlib import contextmanager

    from requests import Response
    from requests.adapters import HTTPAdapter

    from app.services.exchange_calendar.rate_limiter import RateLimitedHTTPAdapter

    events = []

    @contextmanager
    def permit():
        events.append("enter")
        yield
        events.append("exit")

    def fake_send(self, request, **kwargs):
        events.append("send")
        return Response()

    monkeypatch.setattr(HTTPAdapter, "send", fake_send)
    adapter = RateLimitedHTTPAdapter(permit=permit)
    adapter.send(object())
    adapter.send(object())
    assert events == ["enter", "send", "exit"] * 2


def test_two_instances_never_overlap():
    from threading import Event, Thread

    from app.services.exchange_calendar.rate_limiter import InMemoryGate

    gate = InMemoryGate(rate_per_minute=200)
    first = ExchangeRateLimiter(gate)
    second = ExchangeRateLimiter(gate)
    entered = Event()
    release = Event()
    order = []

    def one():
        with first.permit():
            order.append("first")
            entered.set()
            assert release.wait(2)

    def two():
        with second.permit():
            order.append("second")

    t1 = Thread(target=one)
    t2 = Thread(target=two)
    t1.start()
    assert entered.wait(2)
    t2.start()
    assert order == ["first"]
    release.set()
    t1.join(2)
    t2.join(2)
    assert not t1.is_alive() and not t2.is_alive()
    assert order == ["first", "second"]




def test_database_gate_persists_start_and_serializes_across_instances():
    from datetime import UTC, datetime
    from threading import Event, Lock, Thread
    from types import SimpleNamespace

    from app.services.exchange_calendar.rate_limiter import DatabaseGate

    class Engine:
        def __init__(self):
            self.lock = Lock()
            self.last_start = None
            self.starts = []

        def connect(self):
            engine = self

            class Connection:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    pass

                def execute(self, statement, params=None):
                    sql = str(statement)
                    if "pg_advisory_lock" in sql:
                        engine.lock.acquire()
                    elif "pg_advisory_unlock" in sql:
                        engine.lock.release()
                    elif "SELECT clock_timestamp" in sql:
                        return SimpleNamespace(one_or_none=lambda: (datetime.now(UTC), engine.last_start, None))
                    elif "UPDATE exchange_calendar_worker_state" in sql:
                        engine.last_start = datetime.now(UTC)
                        engine.starts.append(engine.last_start)
                        return SimpleNamespace(rowcount=1)
                    return SimpleNamespace()

                def commit(self):
                    pass

                def rollback(self):
                    pass

            return Connection()

    engine = Engine()
    first = DatabaseGate(engine)
    second = DatabaseGate(engine)
    entered = Event()
    release = Event()
    observations = []

    def one():
        with first.permit():
            assert engine.last_start is not None
            observations.append("first")
            entered.set()
            assert release.wait(2)

    def two():
        with second.permit():
            assert len(engine.starts) == 2
            observations.append("second")

    t1, t2 = Thread(target=one), Thread(target=two)
    t1.start()
    assert entered.wait(2)
    t2.start()
    assert observations == ["first"]
    release.set()
    t1.join(2)
    t2.join(2)
    assert observations == ["first", "second"]
    assert (engine.starts[1] - engine.starts[0]).total_seconds() >= 0.29


def test_database_failure_fails_closed():
    from app.services.exchange_calendar.rate_limiter import DatabaseGate, ExchangeGateUnavailable

    class BrokenEngine:
        def connect(self):
            raise RuntimeError("database unavailable")

    with pytest.raises(ExchangeGateUnavailable), DatabaseGate(BrokenEngine()).permit():
        pytest.fail("HTTP attempt began without database gate")




@pytest.mark.database
def test_postgres_gate_serializes_process_connections(app_engine):
    from threading import Event, Thread

    from sqlalchemy import text

    from app.services.exchange_calendar.rate_limiter import DatabaseGate

    with app_engine.begin() as connection:
        connection.execute(text("INSERT INTO exchange_calendar_worker_state (id) VALUES (1) ON CONFLICT DO NOTHING"))

    first = DatabaseGate(app_engine)
    second = DatabaseGate(app_engine)
    entered = Event()
    release = Event()
    starts = []
    errors = []

    def run_one():
        try:
            with first.permit(), app_engine.connect() as connection:
                starts.append(connection.execute(text("SELECT last_outbound_request_at FROM exchange_calendar_worker_state WHERE id=1")).scalar_one())
                entered.set()
                assert release.wait(5)
        except BaseException as exc:
            errors.append(exc)

    def run_two():
        try:
            with second.permit(), app_engine.connect() as connection:
                starts.append(connection.execute(text("SELECT last_outbound_request_at FROM exchange_calendar_worker_state WHERE id=1")).scalar_one())
        except BaseException as exc:
            errors.append(exc)

    one, two = Thread(target=run_one), Thread(target=run_two)
    one.start()
    assert entered.wait(5)
    two.start()
    assert len(starts) == 1
    release.set()
    one.join(5)
    two.join(5)
    assert not errors
    assert not one.is_alive() and not two.is_alive()
    assert len(starts) == 2
    assert (starts[1] - starts[0]).total_seconds() >= 0.29



def test_adapter_holds_gate_through_response_consumption(monkeypatch):
    from contextlib import contextmanager

    from requests.adapters import HTTPAdapter

    from app.services.exchange_calendar.rate_limiter import RateLimitedHTTPAdapter

    events = []

    @contextmanager
    def permit():
        events.append("permit")
        yield
        events.append("release")

    class SlowResponse:
        @property
        def content(self):
            events.append("consume")
            return b"<soap/>"

        def close(self):
            events.append("close")

    def send(self, request, **kwargs):
        events.append("http-send")
        return SlowResponse()

    monkeypatch.setattr(HTTPAdapter, "send", send)
    response = RateLimitedHTTPAdapter(permit=permit).send(object())
    assert response is not None
    assert events == ["permit", "http-send", "consume", "close", "release"]
