import dataclasses
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from app.algorithm import solver as solver_mod
from app.algorithm.solver import _ladder_positions, _solve_component_once
from app.algorithm.types import Assignment, DutyBlock, SoldierInput, SolverResult, SolverSettings


# ── Shared helpers ────────────────────────────────────────────────────────────

def _no_remap(_soldiers, _duties):
    return None


# ── Task 1: _ladder_positions ─────────────────────────────────────────────────

def test_ladder_positions_relaxes_r_before_t():
    settings = SolverSettings(R=15, T=8, relax_r_ceiling=20, relax_t_ceiling=10)
    ladder = _ladder_positions(settings)
    labels = [labels for labels, _ in ladder]
    assert labels == [
        ["R→17"],
        ["R→17", "R→19"],
        ["R→17", "R→19", "R→20"],
        ["R→17", "R→19", "R→20", "T→10"],
    ]
    # Each position's settings carries the cumulative R/T values.
    assert ladder[0][1].R == 17 and ladder[0][1].T == 8
    assert ladder[2][1].R == 20 and ladder[2][1].T == 8
    assert ladder[3][1].R == 20 and ladder[3][1].T == 10


def test_ladder_positions_empty_when_ceiling_equals_base():
    settings = SolverSettings(R=1, T=1, relax_r_ceiling=1, relax_t_ceiling=1)
    assert _ladder_positions(settings) == []


def test_ladder_positions_does_not_mutate_input_settings():
    settings = SolverSettings(R=15, T=8, relax_r_ceiling=20, relax_t_ceiling=10)
    _ladder_positions(settings)
    assert settings.R == 15
    assert settings.T == 8


# ── Task 2: _solve_component_once ────────────────────────────────────────────

def test_solve_component_once_phase0_covers_all_when_capacity_allows():
    soldiers = [
        SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)
        for _ in range(2)
    ]
    dt = uuid4()
    base = date(2026, 6, 1)
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=uuid4(),
                  start_date=base + timedelta(days=i), end_date=base + timedelta(days=i + 1),
                  score_per_day=Decimal("1.00"))
        for i in range(4)
    ]
    settings = SolverSettings(T=8, Wt=14, R=15, Wr=28, time_limit_seconds=5, batch_time_limit_seconds=5)
    result = _solve_component_once(soldiers, duties, [], settings, _no_remap, None)
    assert len(result.assignments) == 4


def test_solve_component_once_leaves_uncoverable_residual():
    # 1 soldier, 2 same-window single-day duties, T=1/Wt=2 caps to 1 duty-day —
    # the second duty cannot be covered no matter what (this call doesn't relax).
    soldier_id = uuid4()
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)]
    dt = uuid4()
    base = date(2026, 6, 1)
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=uuid4(),
                  start_date=base + timedelta(days=i), end_date=base + timedelta(days=i + 1),
                  score_per_day=Decimal("1.00"))
        for i in range(2)
    ]
    settings = SolverSettings(T=1, Wt=2, R=1, Wr=2, time_limit_seconds=5, batch_time_limit_seconds=5)
    result = _solve_component_once(soldiers, duties, [], settings, _no_remap, None)
    assert len(result.assignments) == 1


def test_solve_component_once_does_not_mutate_inputs():
    soldiers = [
        SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, effort_per_milli=5)
    ]
    dt = uuid4()
    base = date(2026, 6, 1)
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=uuid4(),
                  start_date=base, end_date=base + timedelta(days=1), score_per_day=Decimal("1.00"))
    ]
    settings = SolverSettings(T=8, Wt=14, R=15, Wr=28, time_limit_seconds=5, batch_time_limit_seconds=5)
    carry_before = []
    _solve_component_once(soldiers, duties, carry_before, settings, _no_remap, None)
    assert soldiers[0].effort_offset == 0
    assert carry_before == []


# ── Task 3: _probe_with_retry ────────────────────────────────────────────────

def test_probe_with_retry_uses_better_of_two_attempts(monkeypatch):
    soldiers = [SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)]
    dt = uuid4()
    base = date(2026, 6, 1)
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=uuid4(),
                  start_date=base + timedelta(days=i), end_date=base + timedelta(days=i + 1),
                  score_per_day=Decimal("1.00"))
        for i in range(2)
    ]
    calls: list[float] = []

    def fake_solve_component_once(_pool, _duties, _carry, settings, _remap, _cancel):
        calls.append(settings.time_limit_seconds)
        if settings.time_limit_seconds > 5:
            # The "extended time" attempt finds full coverage.
            return SolverResult(assignments=[Assignment(duty_id=duties[0].id, soldier_id=soldiers[0].id),
                                              Assignment(duty_id=duties[1].id, soldier_id=soldiers[0].id)],
                                 status="OPTIMAL", seed=1, relaxed=[])
        return SolverResult(assignments=[Assignment(duty_id=duties[0].id, soldier_id=soldiers[0].id)],
                             status="FEASIBLE", seed=1, relaxed=[])

    monkeypatch.setattr(solver_mod, "_solve_component_once", fake_solve_component_once)
    settings = SolverSettings(time_limit_seconds=5, batch_time_limit_seconds=5)
    result = solver_mod._probe_with_retry(soldiers, duties, [], settings, _no_remap, None)

    assert calls == [5, 10], f"expected one retry at double the time budget, got {calls}"
    assert len(result.assignments) == 2


def test_probe_with_retry_keeps_first_result_if_retry_does_not_improve(monkeypatch):
    soldiers = [SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)]
    dt = uuid4()
    duties = [DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2), score_per_day=Decimal("1.00"))
              for _ in range(2)]

    def fake_solve_component_once(_pool, _duties, _carry, _settings, _remap, _cancel):
        return SolverResult(assignments=[Assignment(duty_id=duties[0].id, soldier_id=soldiers[0].id)],
                             status="FEASIBLE", seed=1, relaxed=[])

    monkeypatch.setattr(solver_mod, "_solve_component_once", fake_solve_component_once)
    settings = SolverSettings(time_limit_seconds=5, batch_time_limit_seconds=5)
    result = solver_mod._probe_with_retry(soldiers, duties, [], settings, _no_remap, None)
    assert len(result.assignments) == 1


def test_probe_with_retry_skips_retry_on_full_coverage(monkeypatch):
    soldiers = [SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)]
    dt = uuid4()
    duties = [DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2), score_per_day=Decimal("1.00"))]
    calls: list[float] = []

    def fake_solve_component_once(_pool, _duties, _carry, settings, _remap, _cancel):
        calls.append(settings.time_limit_seconds)
        return SolverResult(assignments=[Assignment(duty_id=duties[0].id, soldier_id=soldiers[0].id)],
                             status="OPTIMAL", seed=1, relaxed=[])

    monkeypatch.setattr(solver_mod, "_solve_component_once", fake_solve_component_once)
    settings = SolverSettings(time_limit_seconds=5, batch_time_limit_seconds=5)
    solver_mod._probe_with_retry(soldiers, duties, [], settings, _no_remap, None)
    assert calls == [5], "must not retry once full coverage is reached"


# ── Task 4: _search_relaxation_ladder ────────────────────────────────────────

def test_search_relaxation_ladder_finds_minimal_sufficient_position(monkeypatch):
    # Mirrors test_effort_rounds_soft_path_two_groups_relaxes_to_full: base
    # T=2/R=6 covers 4/6, relax_t_ceiling=3 (single ladder step) covers all 6.
    soldiers = [SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)
                for _ in range(2)]
    dt = uuid4()
    base = date(2026, 6, 1)
    duties = [DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=uuid4(),
                        start_date=base + timedelta(days=i), end_date=base + timedelta(days=i + 1),
                        score_per_day=Decimal("1.00")) for i in range(6)]

    probe_settings_seen: list[int] = []

    def fake_solve_component_once(pool, _duties, _carry, settings, _remap, _cancel):
        probe_settings_seen.append(settings.T)
        n = min(settings.T * len(pool), len(duties))
        return SolverResult(
            assignments=[Assignment(duty_id=duties[i].id, soldier_id=pool[0].id) for i in range(n)],
            status="OPTIMAL" if n == len(duties) else "FEASIBLE", seed=1, relaxed=[],
        )

    monkeypatch.setattr(solver_mod, "_solve_component_once", fake_solve_component_once)
    settings = SolverSettings(T=2, R=6, Wt=14, Wr=14, relax_t_ceiling=3, relax_r_ceiling=6,
                              time_limit_seconds=5, batch_time_limit_seconds=5)
    result, labels = solver_mod._search_relaxation_ladder(soldiers, duties, [], settings, _no_remap, None)

    assert labels == ["T→3"]
    assert len(result.assignments) == 6


def test_search_relaxation_ladder_keeps_best_when_even_ceiling_falls_short(monkeypatch):
    soldiers = [SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)]
    dt = uuid4()
    base = date(2026, 6, 1)
    duties = [DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=uuid4(),
                        start_date=base + timedelta(days=i), end_date=base + timedelta(days=i + 1),
                        score_per_day=Decimal("1.00")) for i in range(8)]

    def fake_solve_component_once(pool, _duties, _carry, settings, _remap, _cancel):
        # Best achievable is always settings.T, capped below 8 (the saturation case).
        n = min(settings.T, 6)
        return SolverResult(
            assignments=[Assignment(duty_id=duties[i].id, soldier_id=pool[0].id) for i in range(n)],
            status="FEASIBLE", seed=1, relaxed=[],
        )

    monkeypatch.setattr(solver_mod, "_solve_component_once", fake_solve_component_once)
    settings = SolverSettings(T=2, R=15, Wt=14, Wr=28, relax_t_ceiling=10, relax_r_ceiling=15,
                              time_limit_seconds=5, batch_time_limit_seconds=5)
    result, labels = solver_mod._search_relaxation_ladder(soldiers, duties, [], settings, _no_remap, None)

    assert len(result.assignments) == 6, "best-effort result should be kept even though full coverage is unreachable"
    # relax_t_ceiling=10 from base T=2 takes 4 hops of +2 (4,6,8,10); _ladder_positions
    # returns cumulative labels, so the ceiling position carries all four.
    assert labels == ["T→4", "T→6", "T→8", "T→10"], f"ceiling's cumulative labels are reported alongside the best-effort result, got {labels}"


def test_search_relaxation_ladder_skips_search_when_base_already_covers(monkeypatch):
    soldiers = [SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)]
    dt = uuid4()
    duties = [DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2), score_per_day=Decimal("1.00"))]
    calls = []

    def fake_solve_component_once(pool, _duties, _carry, settings, _remap, _cancel):
        calls.append(settings.T)
        return SolverResult(assignments=[Assignment(duty_id=duties[0].id, soldier_id=pool[0].id)],
                             status="OPTIMAL", seed=1, relaxed=[])

    monkeypatch.setattr(solver_mod, "_solve_component_once", fake_solve_component_once)
    settings = SolverSettings(T=2, R=15, relax_t_ceiling=10, relax_r_ceiling=15,
                              time_limit_seconds=5, batch_time_limit_seconds=5)
    result, labels = solver_mod._search_relaxation_ladder(soldiers, duties, [], settings, _no_remap, None)

    assert calls == [2], "no ladder probes should run when the base attempt already fully covers"
    assert labels == []
    assert len(result.assignments) == 1
