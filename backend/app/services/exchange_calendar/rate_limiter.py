"""Global Exchange HTTP-attempt gate shared by worker processes."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import timedelta

from requests.adapters import HTTPAdapter
from sqlalchemy import text
from sqlalchemy.engine import Engine


class ExchangeBackoffActive(RuntimeError):
    """The shared Exchange outage backoff has not expired."""


class ExchangeGateUnavailable(RuntimeError):
    """No HTTP attempt is allowed when the database gate fails."""


class ExchangeRateLimiter:
    def __init__(self, gate: object):
        self.gate = gate

    @staticmethod
    def spacing_seconds(rate_per_minute: int) -> float:
        if not 1 <= rate_per_minute <= 200:
            raise ValueError("Exchange rate must be between 1 and 200 per minute")
        return 60.0 / rate_per_minute

    @contextmanager
    def permit(self) -> Iterator[None]:
        with self.gate.permit():
            yield


class InMemoryGate:
    """Single-process fake for deterministic unit tests; production uses DatabaseGate."""

    def __init__(self, rate_per_minute: int = 200, *, clock=time.monotonic, sleeper=time.sleep):
        self.spacing = ExchangeRateLimiter.spacing_seconds(rate_per_minute)
        self.clock = clock
        self.sleeper = sleeper
        self._lock = threading.Lock()
        self._last_start: float | None = None

    @contextmanager
    def permit(self) -> Iterator[None]:
        with self._lock:
            if self._last_start is not None:
                delay = self._last_start + self.spacing - self.clock()
                if delay > 0:
                    self.sleeper(delay)
            self._last_start = self.clock()
            yield


class DatabaseGate:
    """Hold one PostgreSQL advisory lock across an entire HTTP send attempt.

    A dedicated checked-out connection retains the session advisory lock across
    the timestamp commit, so other processes cannot enter during an in-flight
    request. A database failure raises before the adapter calls HTTPAdapter.send.
    """

    _LOCK_KEY = 0x4A55535449434557

    def __init__(self, engine: Engine, rate_per_minute: int = 200, *, sleeper=time.sleep):
        self.engine = engine
        self.spacing = ExchangeRateLimiter.spacing_seconds(rate_per_minute)
        self.sleeper = sleeper

    @contextmanager
    def permit(self) -> Iterator[None]:
        locked = False
        entered = False
        try:
            with self.engine.connect() as connection:
                try:
                    connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": self._LOCK_KEY})
                    locked = True
                    while True:
                        row = connection.execute(
                            text("SELECT clock_timestamp(), last_outbound_request_at, global_backoff_until "
                                 "FROM exchange_calendar_worker_state WHERE id = 1 FOR UPDATE")
                        ).one_or_none()
                        if row is None:
                            raise ExchangeGateUnavailable("Exchange worker state is missing")
                        now, last_start, backoff_until = row
                        if backoff_until is not None and backoff_until > now:
                            raise ExchangeBackoffActive("Exchange is in shared backoff")
                        delay = 0 if last_start is None else (
                            last_start + timedelta(seconds=self.spacing) - now
                        ).total_seconds()
                        if delay <= 0:
                            break
                        connection.commit()
                        self.sleeper(delay)
                    updated = connection.execute(
                        text("UPDATE exchange_calendar_worker_state "
                             "SET last_outbound_request_at = clock_timestamp(), updated_at = clock_timestamp() "
                             "WHERE id = 1")
                    )
                    if updated.rowcount != 1:
                        raise ExchangeGateUnavailable("Exchange worker state update failed")
                    connection.commit()
                    entered = True
                    yield
                finally:
                    connection.rollback()
                    if locked:
                        connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self._LOCK_KEY})
                        connection.commit()
        except ExchangeBackoffActive:
            raise
        except Exception as exc:
            if entered:
                raise
            if isinstance(exc, ExchangeGateUnavailable):
                raise
            raise ExchangeGateUnavailable("Exchange request gate unavailable") from exc


class RateLimitedHTTPAdapter(HTTPAdapter):
    """Wrap each exchangelib HTTP send, including SDK retry sends."""

    permit_factory: Callable[[], AbstractContextManager[None]] | None = None

    def __init__(self, *args, permit: Callable[[], AbstractContextManager[None]] | None = None, **kwargs):
        self._permit = permit or self.permit_factory
        if self._permit is None:
            raise ValueError("Exchange HTTP adapter requires a request gate")
        super().__init__(*args, **kwargs)

    def send(self, request, **kwargs):
        with self._permit():
            response = super().send(request, **kwargs)
            try:
                # Requests normally consumes the body in Session.send(), after
                # the adapter returns. Keep the cross-process permit until EWS
                # has finished receiving the whole SOAP response.
                _ = response.content
            finally:
                response.close()
            return response
