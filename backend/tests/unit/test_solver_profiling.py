from __future__ import annotations

import threading
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.algorithm import solver as solver_module
from app.algorithm.types import DutyBlock, ExistingAssignment, SoldierInput, SolverSettings
from tests import conftest
from tests.support.profiling import capture_solver_profile, profiling_requested


def _small_problem() -> tuple[
    list[SoldierInput],
    list[DutyBlock],
    list[ExistingAssignment],
    SolverSettings,
]:
    soldiers = [
        SoldierInput(
            id=uuid.UUID(int=1),
            enrolled_at=date(2026, 1, 1),
            cumulative_score=Decimal("0"),
            active_days=100,
        ),
        SoldierInput(
            id=uuid.UUID(int=2),
            enrolled_at=date(2026, 1, 1),
            cumulative_score=Decimal("0"),
            active_days=100,
        ),
    ]
    duties = [
        DutyBlock(
            id=uuid.UUID(int=11),
            duty_type_id=uuid.UUID(int=21),
            duty_location_id=uuid.UUID(int=31),
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            score_per_day=Decimal("1"),
        ),
        DutyBlock(
            id=uuid.UUID(int=12),
            duty_type_id=uuid.UUID(int=21),
            duty_location_id=uuid.UUID(int=31),
            start_date=date(2026, 6, 3),
            end_date=date(2026, 6, 3),
            score_per_day=Decimal("1"),
        ),
    ]
    settings = SolverSettings(
        seed=7,
        time_limit_seconds=2,
        batch_time_limit_seconds=2,
        tiebreak_time_limit_seconds=2,
        batching_enabled=True,
        decomposition="interleaved",
    )
    return soldiers, duties, [], settings


def test_profiled_small_solve_reports_named_non_negative_phases_without_changing_result() -> None:
    soldiers, duties, existing, settings = _small_problem()
    baseline = solver_module.solve(soldiers, duties, existing, settings)

    with capture_solver_profile() as profile:
        profiled = solver_module.solve(soldiers, duties, existing, settings)

    assert {
        "model_construction",
        "solve_primary",
        "solve_tiebreak",
        "batching",
        "post_solve_swap",
    } <= profile.durations.keys()
    assert all(duration >= 0 for duration in profile.durations.values())
    assert profile.closed is True
    assert profiled.assignments == baseline.assignments
    assert profiled.status == baseline.status
    assert profiled.seed == baseline.seed == 7


def test_profiling_disabled_does_not_read_the_profiling_clock(monkeypatch) -> None:
    soldiers, duties, existing, settings = _small_problem()

    def unexpected_clock_read() -> float:
        raise AssertionError("profiling clock read while profiling was disabled")

    monkeypatch.setattr(solver_module.time, "perf_counter", unexpected_clock_read)

    result = solver_module.solve(soldiers, duties, existing, settings)

    assert result.assignments


def test_cancelled_solve_closes_batch_timing_context() -> None:
    soldiers, duties, existing, settings = _small_problem()
    cancel_event = threading.Event()
    cancel_event.set()

    with capture_solver_profile() as profile:
        result = solver_module.solve(
            soldiers,
            duties,
            existing,
            settings,
            cancel_event=cancel_event,
        )

    assert result.status == "CANCELLED"
    assert profile.durations["batching"] >= 0
    assert profile.closed is True


def test_model_construction_failure_closes_and_detaches_profile(monkeypatch) -> None:
    soldiers, duties, existing, settings = _small_problem()

    with monkeypatch.context() as patch:
        patch.setattr(
            solver_module,
            "build_model",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("model failed")),
        )
        with pytest.raises(RuntimeError, match="model failed"):
            with capture_solver_profile() as profile:
                solver_module.solve(soldiers, duties, existing, settings)

    assert profile.closed is True
    assert profile.durations["model_construction"] >= 0
    failed_profile_snapshot = dict(profile.durations)

    solver_module.solve(soldiers, duties, existing, settings)

    assert profile.durations == failed_profile_snapshot


def test_profiling_requires_explicit_test_environment_setting(monkeypatch) -> None:
    monkeypatch.delenv("JUSTICE_TEST_SOLVER_PROFILE", raising=False)
    assert profiling_requested() is False

    monkeypatch.setenv("JUSTICE_TEST_SOLVER_PROFILE", "1")
    assert profiling_requested() is True

    monkeypatch.setenv("JUSTICE_TEST_SOLVER_PROFILE", "0")
    assert profiling_requested() is False


def test_optional_pytest_hook_records_solver_phases_only_when_enabled(monkeypatch) -> None:
    soldiers, duties, existing, settings = _small_problem()
    config = SimpleNamespace(_justice_solver_profiles=[])
    request = SimpleNamespace(
        config=config,
        node=SimpleNamespace(nodeid="tests/unit/test_example.py::test_profiled"),
    )
    monkeypatch.setenv("JUSTICE_TEST_SOLVER_PROFILE", "1")

    fixture = conftest._solver_profile_report.__wrapped__(request)
    next(fixture)
    solver_module.solve(soldiers, duties, existing, settings)
    with pytest.raises(StopIteration):
        next(fixture)

    assert len(config._justice_solver_profiles) == 1
    nodeid, durations, counts = config._justice_solver_profiles[0]
    assert nodeid == request.node.nodeid
    assert durations["model_construction"] >= 0
    assert counts["model_construction"] >= 1
