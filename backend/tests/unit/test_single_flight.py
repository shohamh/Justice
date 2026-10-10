"""SingleFlight and the coalesced ineligible count: share only concurrent
identical work inside the join window, never across scopes or dates, never
after completion."""
from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from datetime import date

import pytest

from app.services import ineligible_soldiers as svc
from app.services.single_flight import JOIN_WINDOW_SECONDS, SingleFlight, SingleFlightLeaderError

TODAY = date(2026, 10, 9)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0  # exact float sums at the window boundary

    def __call__(self) -> float:
        return self.now


def _start(target: Callable[[], object]) -> threading.Thread:
    thread = threading.Thread(target=target)
    thread.start()
    return thread


def _join_all(*threads: threading.Thread) -> None:
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive()


def _wait_until(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.001)


class _Blocking:
    """A computation that counts its calls and blocks until released."""

    def __init__(self, value: object = 42, error: BaseException | None = None) -> None:
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self.value = value
        self.error = error

    def __call__(self):
        self.calls += 1
        self.started.set()
        assert self.release.wait(5)
        if self.error is not None:
            raise self.error
        return self.value


def test_callers_inside_the_join_window_share_one_computation() -> None:
    clock = FakeClock()
    flight: SingleFlight[object] = SingleFlight("test", clock=clock)
    compute = _Blocking()
    results: list[object] = []

    leader = _start(lambda: results.append(flight.do("k", compute)))
    assert compute.started.wait(5)
    clock.now += JOIN_WINDOW_SECONDS  # still inside (inclusive bound)
    followers = [_start(lambda: results.append(flight.do("k", compute))) for _ in range(4)]
    _wait_until(lambda: flight.waiter_count("k") == 4)
    compute.release.set()
    _join_all(leader, *followers)

    assert compute.calls == 1
    assert results == [42] * 5


def test_caller_after_the_join_window_computes_its_own_value_without_breaking_the_leader() -> None:
    clock = FakeClock()
    flight: SingleFlight[object] = SingleFlight("test", clock=clock)
    leader_compute = _Blocking(value="leader")
    results: dict[str, object] = {}

    leader = _start(lambda: results.__setitem__("leader", flight.do("k", leader_compute)))
    assert leader_compute.started.wait(5)

    clock.now += JOIN_WINDOW_SECONDS + 0.001
    late_calls = 0

    def late_compute() -> str:
        nonlocal late_calls
        late_calls += 1
        return "late"

    # Runs on this thread while the leader is still blocked: computes its own.
    assert flight.do("k", late_compute) == "late"
    assert late_calls == 1

    # The leader's entry survived the late caller: a caller back inside the
    # leader's window still joins it.
    clock.now -= 0.002
    joiner = _start(lambda: results.__setitem__("joiner", flight.do("k", leader_compute)))
    _wait_until(lambda: flight.waiter_count("k") == 1)
    leader_compute.release.set()
    _join_all(leader, joiner)

    assert leader_compute.calls == 1
    assert results == {"leader": "leader", "joiner": "leader"}
    assert flight.waiter_count("k") == 0
    assert flight.do("k", lambda: "fresh") == "fresh"


def test_different_keys_do_not_share() -> None:
    flight: SingleFlight[str] = SingleFlight("test")
    both_running = threading.Barrier(2, timeout=5)
    results: dict[str, str] = {}

    def run(key: str) -> None:
        def compute() -> str:
            both_running.wait()  # BrokenBarrierError if one waited on the other
            return key

        results[key] = flight.do(key, compute)

    threads = [_start(lambda: run("a")), _start(lambda: run("b"))]
    _join_all(*threads)
    assert results == {"a": "a", "b": "b"}


def test_exception_reaches_every_waiter_as_a_chained_fresh_error_and_does_not_poison() -> None:
    flight: SingleFlight[int] = SingleFlight("test")
    leader_error = RuntimeError("boom")
    compute = _Blocking(error=leader_error)
    errors: list[BaseException] = []

    def call() -> None:
        try:
            flight.do("k", compute)
        except Exception as exc:
            errors.append(exc)

    leader = _start(call)
    assert compute.started.wait(5)
    followers = [_start(call) for _ in range(3)]
    _wait_until(lambda: flight.waiter_count("k") == 3)
    compute.release.set()
    _join_all(leader, *followers)

    assert compute.calls == 1
    assert len(errors) == 4
    assert errors.count(leader_error) == 1  # only the leader re-raises the original
    waiter_errors = [error for error in errors if error is not leader_error]
    assert len(waiter_errors) == 3
    assert all(isinstance(error, SingleFlightLeaderError) for error in waiter_errors)
    assert all(error.__cause__ is leader_error for error in waiter_errors)
    assert len({id(error) for error in waiter_errors}) == 3
    assert flight.do("k", lambda: 7) == 7


class _Abort(BaseException):
    pass


def test_base_exception_propagates_only_in_the_leader() -> None:
    flight: SingleFlight[int] = SingleFlight("test")
    compute = _Blocking(error=_Abort())
    outcomes: list[str] = []

    def call() -> None:
        try:
            flight.do("k", compute)
        except _Abort:
            outcomes.append("abort")
        except SingleFlightLeaderError:
            outcomes.append("leader-error")

    leader = _start(call)
    assert compute.started.wait(5)
    follower = _start(call)
    _wait_until(lambda: flight.waiter_count("k") == 1)
    compute.release.set()
    _join_all(leader, follower)

    assert compute.calls == 1
    assert sorted(outcomes) == ["abort", "leader-error"]


def test_no_result_is_kept_after_completion() -> None:
    flight: SingleFlight[int] = SingleFlight("test")
    values = iter([1, 2])
    assert flight.do("k", lambda: next(values)) == 1
    assert flight.do("k", lambda: next(values)) == 2


def _fresh_count_flight(monkeypatch: pytest.MonkeyPatch) -> SingleFlight[int]:
    # A frozen clock keeps every caller inside the join window, however slowly
    # the test threads start.
    flight: SingleFlight[int] = SingleFlight("ineligible_count", clock=FakeClock())
    monkeypatch.setattr(svc, "_count_flight", flight)
    return flight


def test_coalesced_count_never_shares_between_different_scopes(monkeypatch) -> None:
    _fresh_count_flight(monkeypatch)
    seen: list[set[uuid.UUID] | None] = []
    gate = threading.Barrier(2, timeout=5)

    def fake_count(_session, *, roots, as_of) -> int:
        seen.append(roots)
        gate.wait()  # both scopes must be computing at the same time
        return 0 if roots is None else len(roots)

    monkeypatch.setattr(svc, "count_ineligible_soldiers", fake_count)
    team = {uuid.uuid4()}
    results: dict[str, int] = {}
    threads = [
        _start(lambda: results.__setitem__(
            "admin", svc.count_ineligible_soldiers_coalesced(None, roots=None, as_of=TODAY))),
        _start(lambda: results.__setitem__(
            "team", svc.count_ineligible_soldiers_coalesced(None, roots=team, as_of=TODAY))),
    ]
    _join_all(*threads)
    assert results == {"admin": 0, "team": 1}
    assert sorted(seen, key=lambda r: r is None) == [team, None]


def test_coalesced_count_never_shares_between_different_dates(monkeypatch) -> None:
    _fresh_count_flight(monkeypatch)
    seen: list[date] = []
    gate = threading.Barrier(2, timeout=5)

    def fake_count(_session, *, roots, as_of) -> int:
        seen.append(as_of)
        gate.wait()  # both dates must be computing at the same time
        return as_of.day

    monkeypatch.setattr(svc, "count_ineligible_soldiers", fake_count)
    root = uuid.uuid4()
    tomorrow = date(2026, 10, 10)
    results: dict[str, int] = {}
    threads = [
        _start(lambda: results.__setitem__(
            "today", svc.count_ineligible_soldiers_coalesced(None, roots={root}, as_of=TODAY))),
        _start(lambda: results.__setitem__(
            "tomorrow", svc.count_ineligible_soldiers_coalesced(None, roots={root}, as_of=tomorrow))),
    ]
    _join_all(*threads)
    assert results == {"today": 9, "tomorrow": 10}
    assert sorted(seen) == [TODAY, tomorrow]


def test_coalesced_count_shares_identical_scope_and_passes_the_callers_roots(monkeypatch) -> None:
    flight = _fresh_count_flight(monkeypatch)
    calls: list[set[uuid.UUID] | None] = []
    started = threading.Event()
    release = threading.Event()

    def fake_count(_session, *, roots, as_of) -> int:
        calls.append(roots)
        started.set()
        assert release.wait(5)
        return 3

    monkeypatch.setattr(svc, "count_ineligible_soldiers", fake_count)
    root = uuid.uuid4()
    results: list[int] = []

    def call() -> None:
        results.append(svc.count_ineligible_soldiers_coalesced(None, roots={root}, as_of=TODAY))

    leader = _start(call)
    assert started.wait(5)
    follower = _start(call)
    _wait_until(lambda: flight.waiter_count((frozenset({root}), TODAY)) == 1)
    release.set()
    _join_all(leader, follower)
    assert results == [3, 3]
    assert calls == [{root}]
