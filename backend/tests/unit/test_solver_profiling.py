from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.algorithm import solver as solver_module
from app.algorithm.types import DutyBlock, ExistingAssignment, SoldierInput, SolverSettings
from tests.support.profiling import (
    PROFILE_XDIST_WARNING,
    capture_solver_profile,
    profiling_enabled,
    profiling_requested,
    profiling_warning,
)


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


def test_profiled_solve_from_worker_thread_reports_phases() -> None:
    soldiers, duties, existing, settings = _small_problem()

    with capture_solver_profile() as profile, ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(
            solver_module.solve,
            soldiers,
            duties,
            existing,
            settings,
        ).result()

    assert result.assignments
    assert profile.counts["model_construction"] >= 1
    assert profile.counts["solve_primary"] >= 1


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
        with (
            pytest.raises(RuntimeError, match="model failed"),
            capture_solver_profile() as profile,
        ):
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


def test_requested_profiling_is_disabled_under_xdist(monkeypatch) -> None:
    monkeypatch.setenv("JUSTICE_TEST_SOLVER_PROFILE", "1")
    parallel_config = SimpleNamespace(option=SimpleNamespace(numprocesses=4))

    assert profiling_enabled(parallel_config) is False
    assert profiling_warning(parallel_config) == PROFILE_XDIST_WARNING
    assert "-n 0" in PROFILE_XDIST_WARNING


def test_requested_profiling_is_enabled_for_serial_pytest(monkeypatch) -> None:
    monkeypatch.setenv("JUSTICE_TEST_SOLVER_PROFILE", "1")
    serial_config = SimpleNamespace(option=SimpleNamespace(numprocesses=0))

    assert profiling_enabled(serial_config) is True
    assert profiling_warning(serial_config) is None
