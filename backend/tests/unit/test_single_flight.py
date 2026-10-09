"""SingleFlight and the coalesced ineligible count: share only concurrent
identical work, never across scopes, never after completion."""
from __future__ import annotations

import threading
import time
import uuid
from datetime import date

import pytest

from app.services import ineligible_soldiers as svc
from app.services.single_flight import SingleFlight


def _start(target, *args) -> threading.Thread:
    thread = threading.Thread(target=target, args=args)
    thread.start()
    return thread


def test_concurrent_callers_with_the_same_key_share_one_computation() -> None:
    flight: SingleFlight[int] = SingleFlight()
    started = threading.Event()
    release = threading.Event()
    calls = 0
    results: list[int] = []

    def compute() -> int:
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(5)
        return 42

    leader = _start(lambda: results.append(flight.do("k", compute)))
    assert started.wait(5)
    followers = [_start(lambda: results.append(flight.do("k", compute))) for _ in range(4)]
    time.sleep(0.3)  # let the followers park on the leader's call
    release.set()
    for thread in (leader, *followers):
        thread.join(5)
    assert calls == 1
    assert results == [42] * 5


def test_different_keys_do_not_share() -> None:
    flight: SingleFlight[str] = SingleFlight()
    both_running = threading.Barrier(2, timeout=5)
    results: dict[str, str] = {}

    def run(key: str) -> None:
        def compute() -> str:
            both_running.wait()  # deadlocks (BrokenBarrierError) if one waited on the other
            return key

        results[key] = flight.do(key, compute)

    threads = [_start(run, "a"), _start(run, "b")]
    for thread in threads:
        thread.join(5)
    assert results == {"a": "a", "b": "b"}


def test_exception_reaches_every_waiter_and_does_not_poison_later_calls() -> None:
    flight: SingleFlight[int] = SingleFlight()
    started = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def failing() -> int:
        started.set()
        assert release.wait(5)
        raise RuntimeError("boom")

    def call() -> None:
        try:
            flight.do("k", failing)
        except RuntimeError as exc:
            errors.append(exc)

    leader = _start(call)
    assert started.wait(5)
    followers = [_start(call) for _ in range(3)]
    release.set()
    for thread in (leader, *followers):
        thread.join(5)
    assert len(errors) == 4
    assert flight.do("k", lambda: 7) == 7


def test_no_result_is_kept_after_completion() -> None:
    flight: SingleFlight[int] = SingleFlight()
    values = iter([1, 2])
    assert flight.do("k", lambda: next(values)) == 1
    assert flight.do("k", lambda: next(values)) == 2


def _record_roots(monkeypatch: pytest.MonkeyPatch):
    seen: list[set[uuid.UUID] | None] = []
    gate = threading.Barrier(2, timeout=5)

    def fake_count(_session, *, roots, as_of) -> int:
        seen.append(roots)
        gate.wait()  # both scopes must be computing at the same time
        return 0 if roots is None else len(roots)

    monkeypatch.setattr(svc, "count_ineligible_soldiers", fake_count)
    return seen


def test_coalesced_count_never_shares_between_different_scopes(monkeypatch) -> None:
    seen = _record_roots(monkeypatch)
    team = {uuid.uuid4()}
    results: dict[str, int] = {}
    today = date(2026, 10, 9)
    threads = [
        _start(lambda: results.__setitem__("admin", svc.count_ineligible_soldiers_coalesced(
            None, roots=None, as_of=today))),
        _start(lambda: results.__setitem__("team", svc.count_ineligible_soldiers_coalesced(
            None, roots=team, as_of=today))),
    ]
    for thread in threads:
        thread.join(5)
    assert results == {"admin": 0, "team": 1}
    assert sorted(seen, key=lambda r: r is None) == [team, None]


def test_coalesced_count_shares_identical_scope_and_passes_the_callers_roots(monkeypatch) -> None:
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
    today = date(2026, 10, 9)
    results: list[int] = []

    def call() -> None:
        results.append(svc.count_ineligible_soldiers_coalesced(None, roots={root}, as_of=today))

    leader = _start(call)
    assert started.wait(5)
    follower = _start(call)
    time.sleep(0.3)  # let the follower park on the leader's call
    release.set()
    for thread in (leader, follower):
        thread.join(5)
    assert results == [3, 3]
    assert calls == [{root}]
