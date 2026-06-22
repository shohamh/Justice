# Saturation-Aware Relaxation & Diagnosis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `effort_rounds` decomposition so relaxing R/T ceilings restarts the whole component (not just the leftover residual), using binary search to bound the cost; when even the ceiling provably can't cover everything, surface a specific, actionable explanation (which duty types are saturating the eligible pool, and when) instead of a generic message and a misleading "raise the ceiling" recommendation.

**Architecture:** `solver.py` gains a small ladder of pure helper functions (`_ladder_positions` → `_solve_component_once` → `_probe_with_retry` → `_search_relaxation_ladder`) that replace the old "patch the residual" Phase 2 loop inside `_effort_round_solve`. A new `app/algorithm/saturation.py` module (pure, no DB imports, matching the rest of `app/algorithm/`) analyzes any duties still unassigned after the search is exhausted and emits `SaturationCluster` records, carried through `BatchResult` → `job.batch_results` (JSONB) → `IssuesTab.tsx`.

**Tech Stack:** Python (OR-Tools CP-SAT), pytest, TypeScript/React, Vitest.

**Reference spec:** `docs/superpowers/specs/2026-06-22-saturation-aware-relaxation-design.md`

---

## File Structure

- Modify: `backend/app/algorithm/solver.py` — new helpers + rewired `_effort_round_solve`.
- Modify: `backend/app/algorithm/types.py` — new `SaturationCluster` dataclass, extend `BatchResult`.
- Create: `backend/app/algorithm/saturation.py` — clustering + per-cluster eligibility/competing-duty-type analysis.
- Create: `backend/app/algorithm/tests/test_relaxation_search.py` — unit tests for the new solver helpers.
- Create: `backend/app/algorithm/tests/test_saturation.py` — unit tests for clustering/analysis.
- Modify: `backend/app/algorithm/tests/test_solver.py` — no behavior changes expected, but re-verify after the rewire (Task 6).
- Modify: `backend/app/services/algorithm_bridge.py` — serialize `saturation_clusters` in `_postprocess_batch_results` and `_br_to_dict`.
- Modify: `backend/app/services/tests/test_algorithm_bridge_batch.py` — add a remap test for `saturation_clusters`.
- Modify: `frontend/src/api/algorithm.ts` — `SaturationCluster` type, extend `BatchResult`.
- Modify: `frontend/src/components/IssuesTab.tsx` — render cluster explanations, suppress misleading recommendation.
- Create: `frontend/src/components/IssuesTab.test.tsx` — render tests for the new behavior.

---

## Task 1: `_ladder_positions` helper

**Files:**
- Modify: `backend/app/algorithm/solver.py` (add after `_relax_step`, currently ending around line 459)
- Test: `backend/app/algorithm/tests/test_relaxation_search.py`

- [ ] **Step 1: Write the failing test**

Create `backend/app/algorithm/tests/test_relaxation_search.py`:

```python
import dataclasses

from app.algorithm.solver import _ladder_positions
from app.algorithm.types import SolverSettings


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
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`, with `.venv` activated): `pytest app/algorithm/tests/test_relaxation_search.py -v`
Expected: FAIL with `ImportError: cannot import name '_ladder_positions'`

- [ ] **Step 3: Write the implementation**

In `backend/app/algorithm/solver.py`, add immediately after the `_relax_step` function (after its closing `return None` around line 459):

```python
def _ladder_positions(settings: SolverSettings) -> list[tuple[list[str], SolverSettings]]:
    """Cumulative relaxation steps from `settings`' base R/T up to its ceilings.

    Reuses `_relax_step` so labels/order exactly match the existing graduated
    ladder (R first in hops of 2 to relax_r_ceiling, then T to relax_t_ceiling).
    Returns [(cumulative_labels, settings_at_that_position), ...]. Position 0
    (the unrelaxed base) is NOT included — callers try that separately first,
    since it's the cheap/common case and needs no ladder at all.
    """
    positions: list[tuple[list[str], SolverSettings]] = []
    current = dataclasses.replace(settings)
    labels: list[str] = []
    while True:
        label = _relax_step(current)
        if label is None:
            break
        labels = labels + [label]
        positions.append((labels, dataclasses.replace(current)))
    return positions
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest app/algorithm/tests/test_relaxation_search.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/solver.py backend/app/algorithm/tests/test_relaxation_search.py
git commit -m "feat: add relaxation ladder position helper for solver restarts"
```

---

## Task 2: `_solve_component_once` — one full Phase0+1+2 attempt at a given R/T

**Files:**
- Modify: `backend/app/algorithm/solver.py`
- Test: `backend/app/algorithm/tests/test_relaxation_search.py`

This extracts the existing Phase 0 (whole-component hard solve) + Phase 1 (disjoint effort-sorted rounds) + a single Phase 2 soft-coverage pass into one pure, restartable function. It must not mutate its `full_pool`/`carry` inputs (each call is an independent attempt).

- [ ] **Step 1: Write the failing test**

Add to `backend/app/algorithm/tests/test_relaxation_search.py`:

```python
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from app.algorithm.solver import _solve_component_once
from app.algorithm.types import DutyBlock, SoldierInput


def _no_remap(_soldiers, _duties):
    return None


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/algorithm/tests/test_relaxation_search.py -v`
Expected: FAIL with `ImportError: cannot import name '_solve_component_once'`

- [ ] **Step 3: Write the implementation**

Add to `backend/app/algorithm/solver.py`, after `_ladder_positions`:

```python
RemapRdFn = Callable[[Sequence[SoldierInput], Sequence[DutyBlock]], dict[tuple[int, int], int] | None]


def _solve_component_once(
    full_pool: Sequence[SoldierInput],
    component_duties: Sequence[DutyBlock],
    carry: Sequence[ExistingAssignment],
    settings: SolverSettings,
    remap_rd: RemapRdFn,
    cancel_event: threading.Event | None,
) -> SolverResult:
    """One complete attempt to cover `component_duties` at `settings`' R/T.

    Phase 0: whole-component hard `==1` solve (cheap path when fully coverable).
    Phase 1: disjoint effort-sorted rounds at the same R/T (no relaxation).
    Phase 2: one soft-coverage pass over whatever's still unassigned — also no
    relaxation here; trying a *higher* R/T is the caller's job (see
    `_search_relaxation_ladder`), which calls this function again from scratch.

    Pure: does not mutate `full_pool` or `carry`. Returns assignments
    referencing the original duty/soldier ids, scoped to this attempt only.
    """
    pool = [dataclasses.replace(s) for s in full_pool]
    soldier_by_id = {s.id: s for s in pool}
    duty_by_id = {d.id: d for d in component_duties}
    local_carry = list(carry)
    residual = list(component_duties)
    assignments: list[Assignment] = []
    seed = settings.seed if settings.seed is not None else DEFAULT_SOLVER_SEED

    def _absorb_local(result: SolverResult) -> None:
        for a in result.assignments:
            d = duty_by_id[a.duty_id]
            local_carry.append(ExistingAssignment(
                soldier_id=a.soldier_id, duty_type_id=d.duty_type_id,
                start_date=d.start_date, end_date=d.end_date, is_reserve=d.is_reserve,
            ))
            s = soldier_by_id[a.soldier_id]
            s.effort_offset += s.effort_per_milli * _block_score(d)
            assignments.append(a)
        covered = {a.duty_id for a in result.assignments}
        residual[:] = [d for d in residual if d.id not in covered]

    # ── Phase 0: single hard-coverage solve of the WHOLE component ─────────
    solver0, x0, st0 = _solve_with_settings(
        pool, residual, local_carry, settings, reserve_dist=remap_rd(pool, residual),
        cancel_event=cancel_event,
    )
    if cancel_event is not None and cancel_event.is_set():
        return SolverResult(assignments=[], status="CANCELLED", seed=seed, relaxed=[])
    if solver0.StatusName(st0) in ("OPTIMAL", "FEASIBLE"):
        phase0 = [
            Assignment(duty_id=residual[di].id, soldier_id=pool[si].id)
            for (di, si), v in x0.items() if solver0.Value(v)
        ]
        _absorb_local(SolverResult(assignments=phase0, status=solver0.StatusName(st0), seed=seed, relaxed=[]))
        return SolverResult(assignments=assignments, status="OPTIMAL", seed=seed, relaxed=[])

    # ── Phase 1: disjoint effort-sorted rounds at this attempt's R/T ───────
    base_settings = dataclasses.replace(settings, time_limit_seconds=settings.batch_time_limit_seconds)
    group_pool = sorted(pool, key=lambda s: (s.effort_offset, str(s.id)))
    rsc = max(1, settings.round_soldier_count)
    for gi in range(0, len(group_pool), rsc):
        if not residual:
            break
        group = group_pool[gi:gi + rsc]
        res = _solve_soft_coverage(
            group, residual, local_carry, base_settings, reserve_dist=remap_rd(group, residual),
            cancel_event=cancel_event,
        )
        if res.status == "CANCELLED":
            return SolverResult(assignments=[], status="CANCELLED", seed=res.seed, relaxed=[])
        _absorb_local(res)

    # ── Phase 2: full pool, one soft-coverage pass over the leftover ───────
    if residual:
        res = _solve_soft_coverage(
            pool, residual, local_carry, base_settings, reserve_dist=remap_rd(pool, residual),
            cancel_event=cancel_event,
        )
        if res.status == "CANCELLED":
            return SolverResult(assignments=[], status="CANCELLED", seed=res.seed, relaxed=[])
        if res.assignments:
            _absorb_local(res)

    if not assignments:
        status = "INFEASIBLE" if component_duties else "OPTIMAL"
    elif residual:
        status = "FEASIBLE"
    else:
        status = "OPTIMAL"
    return SolverResult(assignments=assignments, status=status, seed=seed, relaxed=[])
```

Add `RemapRdFn` to imports if `Callable`/`Sequence` aren't already imported — they are (line 6: `from collections.abc import Callable, Sequence`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest app/algorithm/tests/test_relaxation_search.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/solver.py backend/app/algorithm/tests/test_relaxation_search.py
git commit -m "feat: extract _solve_component_once as a restartable per-position probe"
```

---

## Task 3: `_probe_with_retry` — extended-time retry on any shortfall

**Files:**
- Modify: `backend/app/algorithm/solver.py`
- Test: `backend/app/algorithm/tests/test_relaxation_search.py`

Every probe that doesn't reach exact full coverage gets one retry with doubled time budgets before its result is accepted, so wall-clock jitter near a time limit doesn't produce a false "can't be covered" verdict. Tested with a monkeypatched `_solve_component_once` so the test is deterministic and fast (no reliance on real CP-SAT timing).

- [ ] **Step 1: Write the failing test**

Add to `backend/app/algorithm/tests/test_relaxation_search.py`:

```python
from app.algorithm import solver as solver_mod
from app.algorithm.types import Assignment, SolverResult


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/algorithm/tests/test_relaxation_search.py -v`
Expected: FAIL with `AttributeError: module 'app.algorithm.solver' has no attribute '_probe_with_retry'`

- [ ] **Step 3: Write the implementation**

Add to `backend/app/algorithm/solver.py`, after `_solve_component_once`:

```python
def _probe_with_retry(
    full_pool: Sequence[SoldierInput],
    component_duties: Sequence[DutyBlock],
    carry: Sequence[ExistingAssignment],
    settings: SolverSettings,
    remap_rd: RemapRdFn,
    cancel_event: threading.Event | None,
) -> SolverResult:
    """Probe at `settings`' R/T; if it falls short of full coverage, retry once
    with doubled time budgets before accepting the shortfall. This guards
    against wall-clock jitter near a time limit producing a false "can't be
    covered" verdict for this ladder position (don't accept 1-duty noise).
    """
    result = _solve_component_once(full_pool, component_duties, carry, settings, remap_rd, cancel_event)
    if result.status == "CANCELLED" or len(result.assignments) == len(component_duties):
        return result
    extended = dataclasses.replace(
        settings,
        time_limit_seconds=settings.time_limit_seconds * 2,
        batch_time_limit_seconds=settings.batch_time_limit_seconds * 2,
    )
    retry = _solve_component_once(full_pool, component_duties, carry, extended, remap_rd, cancel_event)
    if retry.status == "CANCELLED":
        return retry
    return retry if len(retry.assignments) > len(result.assignments) else result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest app/algorithm/tests/test_relaxation_search.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/solver.py backend/app/algorithm/tests/test_relaxation_search.py
git commit -m "feat: retry under-covered probes once with doubled time budget"
```

---

## Task 4: `_search_relaxation_ladder` — binary search over ladder positions

**Files:**
- Modify: `backend/app/algorithm/solver.py`
- Test: `backend/app/algorithm/tests/test_relaxation_search.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/app/algorithm/tests/test_relaxation_search.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/algorithm/tests/test_relaxation_search.py -v`
Expected: FAIL with `AttributeError: module 'app.algorithm.solver' has no attribute '_search_relaxation_ladder'`

- [ ] **Step 3: Write the implementation**

Add to `backend/app/algorithm/solver.py`, after `_probe_with_retry`:

```python
def _search_relaxation_ladder(
    full_pool: Sequence[SoldierInput],
    component_duties: Sequence[DutyBlock],
    carry: Sequence[ExistingAssignment],
    settings: SolverSettings,
    remap_rd: RemapRdFn,
    cancel_event: threading.Event | None,
) -> tuple[SolverResult, list[str]]:
    """Binary-search the graduated R/T relaxation ladder for the lowest position
    that fully covers `component_duties`, doing a full Phase0+1+2 restart per
    probe (not a residual patch — see `_solve_component_once`). Each probe gets
    an extended-time retry (see `_probe_with_retry`) before its result is
    trusted. Returns (best_result, relax_labels_used); `best_result` never
    regresses to a worse attempt even while searching for a cheaper position.
    """
    def better(a: SolverResult, b: SolverResult) -> SolverResult:
        total = len(component_duties)
        if len(a.assignments) == total:
            return a
        if len(b.assignments) == total:
            return b
        return a if len(a.assignments) >= len(b.assignments) else b

    base_result = _probe_with_retry(full_pool, component_duties, carry, settings, remap_rd, cancel_event)
    if base_result.status == "CANCELLED":
        return base_result, []
    best = base_result
    if len(best.assignments) == len(component_duties):
        return best, []

    ladder = _ladder_positions(settings)
    if not ladder:
        return best, []

    top_labels, top_settings = ladder[-1]
    top_result = _probe_with_retry(full_pool, component_duties, carry, top_settings, remap_rd, cancel_event)
    if top_result.status == "CANCELLED":
        return top_result, []
    best = better(best, top_result)
    if len(top_result.assignments) < len(component_duties):
        # Proven (after retry) shortfall even at the ceiling — searching the
        # middle of the ladder can only do worse than the ceiling did.
        return best, top_labels

    # Ceiling fully covers — binary-search [0, len(ladder)-2] for a cheaper position.
    chosen_labels, chosen_result = top_labels, top_result
    lo, hi = 0, len(ladder) - 2
    while lo <= hi:
        mid = (lo + hi) // 2
        labels, mid_settings = ladder[mid]
        mid_result = _probe_with_retry(full_pool, component_duties, carry, mid_settings, remap_rd, cancel_event)
        if mid_result.status == "CANCELLED":
            return mid_result, []
        best = better(best, mid_result)
        if len(mid_result.assignments) == len(component_duties):
            chosen_labels, chosen_result = labels, mid_result
            hi = mid - 1
        else:
            lo = mid + 1
    return chosen_result, chosen_labels
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest app/algorithm/tests/test_relaxation_search.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/solver.py backend/app/algorithm/tests/test_relaxation_search.py
git commit -m "feat: binary-search the relaxation ladder for the minimal sufficient restart"
```

---

## Task 5: Wire `_search_relaxation_ladder` into `_effort_round_solve`

**Files:**
- Modify: `backend/app/algorithm/solver.py:559-699` (the per-component Phase 0/1/2 block inside `_effort_round_solve`)

This replaces the old "absorb incrementally, relax the residual" block with one call to the search driver, then absorbs its final chosen result into the outer `carry`/`all_assignments`/soldier `effort_offset` state (same bookkeeping the old code did, just sourced from one result instead of three interleaved phases).

- [ ] **Step 1: Replace the per-component block**

In `backend/app/algorithm/solver.py`, inside `_effort_round_solve`, replace everything from:

```python
        t0 = time.monotonic()
        assignments_before = len(all_assignments)
        component_relaxed: list[str] = []

        full_pool = [work[si] for si in soldier_idxs]
        residual = [duties[di] for di in duty_idxs]

        def _absorb(result: SolverResult) -> None:
```

through the end of the per-component block (down to and including the `if progress_cb: progress_cb(done, n_components)` right before the `all_assignments.sort(...)` line that closes the function) — i.e. everything from line ~559 to ~702 — with:

```python
        t0 = time.monotonic()
        full_pool = [work[si] for si in soldier_idxs]
        component_duties = [duties[di] for di in duty_idxs]

        component_result, component_relaxed = _search_relaxation_ladder(
            full_pool, component_duties, carry, settings, _remap_rd, cancel_event,
        )
        if component_result.status == "CANCELLED":
            return SolverResult(
                assignments=[], status="CANCELLED",
                seed=(settings.seed if settings.seed is not None else DEFAULT_SOLVER_SEED),
                relaxed=relaxed,
                batch_results=batch_results,
            )

        assigned_ids_here = {a.duty_id for a in component_result.assignments}
        for a in component_result.assignments:
            d = duty_by_id[a.duty_id]
            carry.append(ExistingAssignment(
                soldier_id=a.soldier_id, duty_type_id=d.duty_type_id,
                start_date=d.start_date, end_date=d.end_date, is_reserve=d.is_reserve,
            ))
            s = soldier_by_id[a.soldier_id]
            s.effort_offset += s.effort_per_milli * _block_score(d)
            all_assignments.append(a)

        assigned_here = len(component_result.assignments)
        total_here = len(component_duties)
        if assigned_here == 0 and total_here > 0:
            comp_outcome = "INFEASIBLE"
        elif assigned_here < total_here:
            comp_outcome = "FEASIBLE"
        else:
            comp_outcome = "OPTIMAL"
        batch_results.append(BatchResult(
            batch_index=len(batch_results),
            component_index=done - 1,
            date_from=min(d.start_date for d in component_duties),
            date_to=max(d.end_date for d in component_duties),
            duty_count=total_here,
            soldier_count=len(full_pool),
            assigned_count=assigned_here,
            unassigned_count=total_here - assigned_here,
            outcome=comp_outcome,
            relaxations=component_relaxed,
            wall_time_seconds=round(time.monotonic() - t0, 3),
            shifts=[
                BatchShiftFill(shift_id=d.id, required_count=1, assigned_count=1 if d.id in assigned_ids_here else 0)
                for d in component_duties
            ],
        ))
        relaxed.extend(component_relaxed)

        if progress_cb:
            progress_cb(done, n_components)
```

Note: the `solver0`/`x0`/`_remap_rd` closure, `duty_by_id`, `soldier_by_id` are already defined earlier in `_effort_round_solve` and remain unchanged — only the body of the per-component loop changes. The `BatchShiftFill` "no eligible soldiers" branch above this block (for `soldier_idxs` empty) is untouched.

- [ ] **Step 2: Run the full existing solver test suite**

Run: `pytest app/algorithm/tests/test_solver.py -v`
Expected: PASS, all tests — in particular:
- `test_effort_rounds_covers_what_calendar_drops`
- `test_effort_rounds_respects_ceilings_leaves_partial`
- `test_effort_rounds_soft_path_two_groups_relaxes_to_full`
- `test_effort_rounds_two_groups_cover_all`
- `test_effort_rounds_small_component_single_round`
- `test_batched_reserve_carryforward_counts_toward_R_not_T`

If any fail, compare against the pre-change behavior traced in the design spec (`docs/superpowers/specs/2026-06-22-saturation-aware-relaxation-design.md`) — the position-0 (unrelaxed) path through `_solve_component_once` must behave identically to the old Phase 0/1/2 sequence for these fixtures.

- [ ] **Step 3: Run the full backend test suite (fast subset)**

Run: `pytest -q` (from `backend/`)
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/algorithm/solver.py
git commit -m "fix: restart whole component on relaxation instead of patching residual"
```

---

## Task 6: `SaturationCluster` type + clustering/analysis module

**Files:**
- Modify: `backend/app/algorithm/types.py`
- Create: `backend/app/algorithm/saturation.py`
- Test: `backend/app/algorithm/tests/test_saturation.py`

- [ ] **Step 1: Write the failing test**

Create `backend/app/algorithm/tests/test_saturation.py`:

```python
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

from app.algorithm.saturation import analyze_saturation
from app.algorithm.types import Assignment, DutyBlock, ExistingAssignment, SoldierInput


def test_analyze_saturation_reports_zero_free_and_competing_duty_types():
    competing_type_a = uuid4()
    competing_type_b = uuid4()
    saturated_type = uuid4()
    loc = uuid4()
    base = date(2026, 7, 6)
    end = base + timedelta(days=9)

    soldier_a = SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)
    soldier_b = SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)
    full_pool = [soldier_a, soldier_b]

    unassigned_duty = DutyBlock(id=uuid4(), duty_type_id=saturated_type, duty_location_id=loc,
                                start_date=base, end_date=end, score_per_day=Decimal("1.00"))

    # Both soldiers are already committed elsewhere during the unassigned duty's window.
    existing = [
        ExistingAssignment(soldier_id=soldier_a.id, duty_type_id=competing_type_a,
                           start_date=base, end_date=end, is_reserve=True),
        ExistingAssignment(soldier_id=soldier_b.id, duty_type_id=competing_type_b,
                           start_date=base, end_date=end, is_reserve=True),
    ]

    duty_by_id = {unassigned_duty.id: unassigned_duty}
    clusters = analyze_saturation(
        unassigned=[unassigned_duty], full_pool=full_pool, all_assignments=[],
        existing=existing, duty_by_id=duty_by_id,
    )

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.date_from == base
    assert cluster.date_to == end
    assert cluster.shift_ids == [unassigned_duty.id]
    assert cluster.eligible_pool_size == 2
    assert cluster.free_count == 0
    competing = dict(cluster.competing_duty_types)
    assert competing[competing_type_a] == 1
    assert competing[competing_type_b] == 1


def test_analyze_saturation_groups_overlapping_duties_into_one_cluster():
    dt = uuid4()
    loc = uuid4()
    base = date(2026, 7, 6)
    d1 = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                  start_date=base, end_date=base + timedelta(days=9), score_per_day=Decimal("1.00"))
    d2 = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                  start_date=base, end_date=base + timedelta(days=8), score_per_day=Decimal("1.00"))
    # Disjoint date range -> separate cluster.
    d3 = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                  start_date=base + timedelta(days=30), end_date=base + timedelta(days=39),
                  score_per_day=Decimal("1.00"))
    soldier = SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)

    clusters = analyze_saturation(
        unassigned=[d1, d2, d3], full_pool=[soldier], all_assignments=[], existing=[],
        duty_by_id={d.id: d for d in (d1, d2, d3)},
    )

    by_size = sorted(len(c.shift_ids) for c in clusters)
    assert by_size == [1, 2]


def test_analyze_saturation_reports_free_soldiers_when_not_saturated():
    dt = uuid4()
    loc = uuid4()
    base = date(2026, 7, 6)
    duty = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                     start_date=base, end_date=base + timedelta(days=1), score_per_day=Decimal("1.00"))
    soldier = SoldierInput(id=uuid4(), enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)

    clusters = analyze_saturation(
        unassigned=[duty], full_pool=[soldier], all_assignments=[], existing=[],
        duty_by_id={duty.id: duty},
    )
    assert clusters[0].free_count == 1
    assert clusters[0].competing_duty_types == []


def test_analyze_saturation_returns_empty_for_no_unassigned_duties():
    assert analyze_saturation(unassigned=[], full_pool=[], all_assignments=[], existing=[], duty_by_id={}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/algorithm/tests/test_saturation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.algorithm.saturation'`

- [ ] **Step 3: Add `SaturationCluster` to types.py**

In `backend/app/algorithm/types.py`, after the `BatchShiftFill` dataclass (after its closing line, before `@dataclass\nclass BatchResult:`):

```python
@dataclass
class SaturationCluster:
    """Diagnostic: a group of date-overlapping duties left unassigned because
    every eligible soldier is already committed elsewhere on those exact dates.

    Raising R/T density ceilings cannot fix this — it's a proven structural
    shortfall (free_count == 0), reached only after the relaxation search
    (see solver._search_relaxation_ladder) has exhausted the ceiling.
    """
    date_from: date
    date_to: date
    shift_ids: list[uuid.UUID]
    eligible_pool_size: int
    free_count: int
    competing_duty_types: list[tuple[uuid.UUID, int]]
```

Then add the field to `BatchResult`:

```python
@dataclass
class BatchResult:
    """Diagnostic record for one calendar-window batch."""
    batch_index: int          # global sequential index across all components
    component_index: int      # which connected component
    date_from: date
    date_to: date
    duty_count: int           # total duty slots in batch
    soldier_count: int
    assigned_count: int
    unassigned_count: int
    outcome: str              # "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "CANCELLED"
    relaxations: list[str]    # e.g. ["R→17", "R→19"]
    wall_time_seconds: float
    shifts: list[BatchShiftFill] = field(default_factory=list)
    saturation_clusters: list[SaturationCluster] = field(default_factory=list)
```

(Only the new `saturation_clusters` line is added; everything else in `BatchResult` is unchanged.)

- [ ] **Step 4: Create `saturation.py`**

Create `backend/app/algorithm/saturation.py`:

```python
"""Diagnose why duties remain unassigned after the relaxation search is
exhausted (see solver._search_relaxation_ladder). Pure module: no DB imports,
matching the rest of app/algorithm/.
"""
from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import date

from app.algorithm.types import (
    Assignment,
    DutyBlock,
    ExistingAssignment,
    SaturationCluster,
    SoldierInput,
)


def _eligible(soldier: SoldierInput, duty: DutyBlock) -> bool:
    """Mirrors solver._eligible_pairs' filter for a single (soldier, duty) pair."""
    if duty.duty_type_id in soldier.exempted_duty_type_ids:
        return False
    for cs, ce in soldier.approved_constraint_dates:
        if cs < duty.end_date and ce >= duty.start_date:
            return False
    if duty.eligible_node_ids is not None and soldier.hierarchy_node_id is not None:
        if soldier.hierarchy_node_id not in duty.eligible_node_ids:
            return False
    return True


def _date_ranges_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    """Exclusive-end-date overlap, matching DutyBlock's [start_date, end_date) convention."""
    return a_start < b_end and b_start < a_end


def _cluster_by_date_overlap(duties: Sequence[DutyBlock]) -> list[list[DutyBlock]]:
    """Group duties into transitively date-overlapping clusters (union-find).

    O(n^2) pairwise comparison — fine here since `duties` is only the small
    leftover-unassigned set, never the full duty list.
    """
    n = len(duties)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if _date_ranges_overlap(duties[i].start_date, duties[i].end_date,
                                    duties[j].start_date, duties[j].end_date):
                union(i, j)

    groups: dict[int, list[DutyBlock]] = {}
    for i, d in enumerate(duties):
        groups.setdefault(find(i), []).append(d)
    return list(groups.values())


def _analyze_cluster(
    cluster_duties: Sequence[DutyBlock],
    full_pool: Sequence[SoldierInput],
    commitments_by_soldier: dict[uuid.UUID, list[tuple[date, date, uuid.UUID]]],
) -> SaturationCluster:
    date_from = min(d.start_date for d in cluster_duties)
    date_to = max(d.end_date for d in cluster_duties)

    eligible_total = 0
    free_count = 0
    competing: Counter[uuid.UUID] = Counter()

    for soldier in full_pool:
        if not any(_eligible(soldier, d) for d in cluster_duties):
            continue
        eligible_total += 1
        commitments = commitments_by_soldier.get(soldier.id, [])
        busy_duty_types = [
            duty_type_id for (start, end, duty_type_id) in commitments
            if _date_ranges_overlap(start, end, date_from, date_to)
        ]
        if busy_duty_types:
            competing.update(busy_duty_types)
        else:
            free_count += 1

    return SaturationCluster(
        date_from=date_from,
        date_to=date_to,
        shift_ids=[d.id for d in cluster_duties],
        eligible_pool_size=eligible_total,
        free_count=free_count,
        competing_duty_types=sorted(competing.items(), key=lambda kv: -kv[1]),
    )


def analyze_saturation(
    unassigned: Sequence[DutyBlock],
    full_pool: Sequence[SoldierInput],
    all_assignments: Sequence[Assignment],
    existing: Sequence[ExistingAssignment],
    duty_by_id: dict[uuid.UUID, DutyBlock],
) -> list[SaturationCluster]:
    """Cluster `unassigned` duties by date overlap and explain each cluster:
    how many eligible soldiers exist, how many are free, and what duty types
    the busy ones are already committed to during that window.
    """
    if not unassigned:
        return []

    commitments_by_soldier: dict[uuid.UUID, list[tuple[date, date, uuid.UUID]]] = {}
    for e in existing:
        commitments_by_soldier.setdefault(e.soldier_id, []).append(
            (e.start_date, e.end_date, e.duty_type_id)
        )
    for a in all_assignments:
        d = duty_by_id[a.duty_id]
        commitments_by_soldier.setdefault(a.soldier_id, []).append(
            (d.start_date, d.end_date, d.duty_type_id)
        )

    clusters = _cluster_by_date_overlap(list(unassigned))
    return [_analyze_cluster(c, full_pool, commitments_by_soldier) for c in clusters]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest app/algorithm/tests/test_saturation.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/algorithm/types.py backend/app/algorithm/saturation.py backend/app/algorithm/tests/test_saturation.py
git commit -m "feat: add saturation cluster analysis for unassignable duties"
```

---

## Task 7: Wire saturation analysis into `_effort_round_solve`

**Files:**
- Modify: `backend/app/algorithm/solver.py` (imports + the per-component block from Task 5)

- [ ] **Step 1: Add the import**

In `backend/app/algorithm/solver.py`, add to the existing imports block (after the `from app.algorithm.types import (...)` block):

```python
from app.algorithm.saturation import analyze_saturation
```

- [ ] **Step 2: Compute and attach clusters in the per-component block**

In the per-component block written in Task 5, insert before the `batch_results.append(BatchResult(...))` call:

```python
        still_unassigned = [d for d in component_duties if d.id not in assigned_ids_here]
        saturation_clusters = (
            analyze_saturation(still_unassigned, full_pool, all_assignments, existing, duty_by_id)
            if still_unassigned else []
        )
```

Then add `saturation_clusters=saturation_clusters,` as a new keyword argument to the `BatchResult(...)` call (alongside `shifts=[...]`).

- [ ] **Step 3: Write a regression test wiring it end-to-end**

Add to `backend/app/algorithm/tests/test_solver.py` (near the other `effort_rounds` tests, e.g. after `test_effort_rounds_two_groups_cover_all`):

```python
def test_effort_round_solve_attaches_saturation_clusters_on_shortfall() -> None:
    # 1 soldier, 1 existing commitment covering the same window as 1 unassignable
    # duty (same duty_type both real, T cap of 1 already consumed) — the
    # eligible pool (1 soldier) is fully busy, so the leftover duty must carry
    # a saturation cluster naming the soldier's existing duty type.
    competing_type = uuid4()
    saturated_type = uuid4()
    soldier_id = uuid4()
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"), active_days=100)]
    base = date(2026, 6, 1)
    existing = [ExistingAssignment(soldier_id=soldier_id, duty_type_id=competing_type,
                                   start_date=base, end_date=base + timedelta(days=1), is_reserve=False)]
    duties = [_single_day_duty(base, saturated_type, is_reserve=False)]
    from app.algorithm.solver import _effort_round_solve
    res = _effort_round_solve(
        soldiers, duties, existing,
        SolverSettings(T=1, Wt=2, R=1, Wr=2, relax_t_ceiling=1, relax_r_ceiling=1,
                      round_soldier_count=50, batch_time_limit_seconds=10, time_limit_seconds=10),
        reserve_dist=None, cancel_event=None,
    )
    assert len(res.assignments) == 0
    assert len(res.batch_results) == 1
    clusters = res.batch_results[0].saturation_clusters
    assert len(clusters) == 1
    assert clusters[0].free_count == 0
    assert dict(clusters[0].competing_duty_types) == {competing_type: 1}
```

- [ ] **Step 4: Run test to verify it fails, then passes**

Run: `pytest app/algorithm/tests/test_solver.py -k saturation_clusters -v`
Expected first: FAIL (no `saturation_clusters` populated, or `AttributeError`)
After Step 1-2: PASS

- [ ] **Step 5: Run the full algorithm test suite**

Run: `pytest app/algorithm/tests/ -v`
Expected: PASS, all tests

- [ ] **Step 6: Commit**

```bash
git add backend/app/algorithm/solver.py backend/app/algorithm/tests/test_solver.py
git commit -m "feat: attach saturation cluster diagnostics to batch results on shortfall"
```

---

## Task 8: Serialize `saturation_clusters` through `algorithm_bridge.py`

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py:738-794` (`_postprocess_batch_results`, `_br_to_dict`)
- Modify: `backend/app/services/tests/test_algorithm_bridge_batch.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/app/services/tests/test_algorithm_bridge_batch.py`:

```python
from app.algorithm.types import SaturationCluster


def test_postprocess_remaps_saturation_cluster_shift_ids():
    """SaturationCluster.shift_ids hold block UUIDs (same as BatchShiftFill.shift_id)
    until the bridge remaps them to real DutyShift UUIDs."""
    shift_id = uuid.uuid4()
    block_a = uuid.uuid4()
    competing_type = uuid.uuid4()
    block_to_shift = {block_a: shift_id}

    br = BatchResult(
        batch_index=0,
        component_index=0,
        date_from=date(2026, 7, 6),
        date_to=date(2026, 7, 14),
        duty_count=1,
        soldier_count=2,
        assigned_count=0,
        unassigned_count=1,
        outcome="FEASIBLE",
        relaxations=["R→20"],
        wall_time_seconds=0.1,
        shifts=[BatchShiftFill(shift_id=block_a, required_count=1, assigned_count=0)],
        saturation_clusters=[
            SaturationCluster(
                date_from=date(2026, 7, 6), date_to=date(2026, 7, 14),
                shift_ids=[block_a], eligible_pool_size=57, free_count=0,
                competing_duty_types=[(competing_type, 42)],
            )
        ],
    )

    processed = _postprocess_batch_results([br], block_to_shift)

    assert len(processed[0].saturation_clusters) == 1
    cluster = processed[0].saturation_clusters[0]
    assert cluster.shift_ids == [shift_id]
    assert cluster.eligible_pool_size == 57
    assert cluster.competing_duty_types == [(competing_type, 42)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/services/tests/test_algorithm_bridge_batch.py -v`
Expected: FAIL — `processed[0].saturation_clusters[0].shift_ids == [block_a]` (not remapped) since `_postprocess_batch_results` doesn't touch the field yet.

- [ ] **Step 3: Update `_postprocess_batch_results`**

In `backend/app/services/algorithm_bridge.py`, change the `processed.append(...)` line inside `_postprocess_batch_results` from:

```python
        processed.append(dataclasses.replace(br, shifts=aggregated_shifts))
```

to:

```python
        remapped_clusters = [
            dataclasses.replace(
                sc, shift_ids=[block_to_shift.get(sid, sid) for sid in sc.shift_ids]
            )
            for sc in br.saturation_clusters
        ]
        processed.append(dataclasses.replace(
            br, shifts=aggregated_shifts, saturation_clusters=remapped_clusters,
        ))
```

- [ ] **Step 4: Update `_br_to_dict`**

In the same file, in `_br_to_dict`, add a new key after `"shifts": [...]`:

```python
        "saturation_clusters": [
            {
                "date_from": sc.date_from.isoformat(),
                "date_to": sc.date_to.isoformat(),
                "shift_ids": [str(sid) for sid in sc.shift_ids],
                "eligible_pool_size": sc.eligible_pool_size,
                "free_count": sc.free_count,
                "competing_duty_types": [
                    {"duty_type_id": str(dt), "count": count} for dt, count in sc.competing_duty_types
                ],
            }
            for sc in br.saturation_clusters
        ],
```

(So the full returned dict has `"shifts": [...], "saturation_clusters": [...] ,` — comma-separated keys, in that order for readability; exact key order doesn't matter functionally.)

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest app/services/tests/test_algorithm_bridge_batch.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the full backend test suite**

Run: `pytest -q` (from `backend/`)
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/algorithm_bridge.py backend/app/services/tests/test_algorithm_bridge_batch.py
git commit -m "feat: serialize saturation_clusters through the algorithm bridge"
```

---

## Task 9: Frontend types

**Files:**
- Modify: `frontend/src/api/algorithm.ts`

- [ ] **Step 1: Add the types**

In `frontend/src/api/algorithm.ts`, after the `BatchShiftFill` interface (before `BatchResult`):

```typescript
export interface SaturationClusterCompeting {
  duty_type_id: string;
  count: number;
}

export interface SaturationCluster {
  date_from: string;
  date_to: string;
  shift_ids: string[];
  eligible_pool_size: number;
  free_count: number;
  competing_duty_types: SaturationClusterCompeting[];
}
```

Then add a field to `BatchResult`:

```typescript
export interface BatchResult {
  batch_index: number;
  component_index: number;
  date_from: string;
  date_to: string;
  duty_count: number;
  soldier_count: number;
  assigned_count: number;
  unassigned_count: number;
  outcome: "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "CANCELLED";
  relaxations: string[];
  wall_time_seconds: number;
  shifts: BatchShiftFill[];
  saturation_clusters: SaturationCluster[];
}
```

(Only the new `saturation_clusters` line is added.)

- [ ] **Step 2: Type-check**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: PASS, no new errors (other files referencing `BatchResult` literals will need the new field — fixed in Task 10).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/algorithm.ts
git commit -m "feat: add SaturationCluster type to algorithm API types"
```

---

## Task 10: Render saturation explanations in `IssuesTab.tsx`

**Files:**
- Modify: `frontend/src/components/IssuesTab.tsx`
- Create: `frontend/src/components/IssuesTab.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/IssuesTab.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import IssuesTab from "./IssuesTab";
import { AlgorithmJob, BatchResult } from "../api/algorithm";
import { DutyType } from "../api/dutyConfig";

function makeJob(batchResults: BatchResult[]): AlgorithmJob {
  return {
    id: "job-1",
    status: "done",
    mode: "shadow",
    planning_start: "2026-07-01",
    planning_end: "2026-08-01",
    started_at: null,
    finished_at: null,
    error_message: null,
    progress_message: null,
    proposals: [],
    solver_metrics: {},
    relaxed: [],
    reasons: [],
    batch_results: batchResults,
    result_metadata: null,
  };
}

const dutyTypes: DutyType[] = [
  { id: "dt-a", name: "שמירה כללית", score_per_day: "1", description: null, active: true },
  { id: "dt-b", name: "תורנות מטבח", score_per_day: "1", description: null, active: true },
];

const SATURATED_BATCH: BatchResult = {
  batch_index: 0,
  component_index: 0,
  date_from: "2026-07-06",
  date_to: "2026-07-14",
  duty_count: 1,
  soldier_count: 57,
  assigned_count: 0,
  unassigned_count: 1,
  outcome: "FEASIBLE",
  relaxations: ["R→20", "T→10"],
  wall_time_seconds: 140,
  shifts: [{ shift_id: "shift-1", required_count: 1, assigned_count: 0 }],
  saturation_clusters: [
    {
      date_from: "2026-07-06",
      date_to: "2026-07-14",
      shift_ids: ["shift-1"],
      eligible_pool_size: 57,
      free_count: 0,
      competing_duty_types: [
        { duty_type_id: "dt-a", count: 42 },
        { duty_type_id: "dt-b", count: 15 },
      ],
    },
  ],
};

test("renders saturation cluster explanation naming competing duty types", () => {
  render(
    <IssuesTab
      job={makeJob([SATURATED_BATCH])}
      dutyTypes={dutyTypes}
      shiftNames={{ "shift-1": "משמרת בוקר" }}
      shiftsById={{}}
    />
  );
  expect(screen.getByText(/57/)).toBeInTheDocument();
  expect(screen.getByText(/שמירה כללית/)).toBeInTheDocument();
  expect(screen.getByText(/תורנות מטבח/)).toBeInTheDocument();
  expect(screen.getByText(/42/)).toBeInTheDocument();
  expect(screen.getByText(/15/)).toBeInTheDocument();
});

test("does not recommend raising relax ceiling when shortfall is saturation-dominated", () => {
  render(
    <IssuesTab
      job={makeJob([SATURATED_BATCH])}
      dutyTypes={dutyTypes}
      shiftNames={{ "shift-1": "משמרת בוקר" }}
      shiftsById={{}}
      onRerun={() => {}}
    />
  );
  expect(screen.queryByText(/relax_r_ceiling/)).not.toBeInTheDocument();
  expect(screen.queryByText(/הרץ שוב עם הגדרות מומלצות/)).not.toBeInTheDocument();
});

test("still recommends raising relax ceiling for non-saturated relaxation shortfalls", () => {
  const nonSaturatedBatch: BatchResult = {
    ...SATURATED_BATCH,
    saturation_clusters: [],
  };
  render(
    <IssuesTab
      job={makeJob([nonSaturatedBatch])}
      dutyTypes={dutyTypes}
      shiftNames={{ "shift-1": "משמרת בוקר" }}
      shiftsById={{}}
      onRerun={() => {}}
    />
  );
  expect(screen.getByText(/relax_r_ceiling/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm test -- IssuesTab`
Expected: FAIL — `result_metadata: null` type mismatch is fine (matches `AlgorithmJob`), but the saturation text assertions fail since `IssuesTab` doesn't render cluster explanations yet, and the "still recommends" test currently passes already (existing behavior) while the "does not recommend" test fails (current code doesn't suppress).

- [ ] **Step 3: Update `IssuesTab.tsx`**

In `frontend/src/components/IssuesTab.tsx`, add the import:

```tsx
import { AlgorithmJob, BatchResult, SaturationCluster } from "../api/algorithm";
```

Add two new helper functions after `collectUnfilledShifts` (before `interface DiagnosticResult`):

```tsx
function buildClusterMap(batchResults: BatchResult[]): Map<string, SaturationCluster> {
  const map = new Map<string, SaturationCluster>();
  for (const br of batchResults) {
    for (const sc of br.saturation_clusters ?? []) {
      for (const sid of sc.shift_ids) {
        map.set(sid, sc);
      }
    }
  }
  return map;
}

function describeCluster(cluster: SaturationCluster, dutyTypeNames: Record<string, string>): string {
  const competing = cluster.competing_duty_types
    .map((c) => `${c.count} ב${dutyTypeNames[c.duty_type_id] ?? c.duty_type_id.slice(0, 8)}`)
    .join(", ");
  const base = `${cluster.eligible_pool_size} חיילים כשירים לתקופה זו (${cluster.date_from} – ${cluster.date_to}) משובצים כבר במלואם`;
  return competing
    ? `${base} (${competing}) — שקול לשנות את תאריכי המשמרת או להרחיב את הכשירות`
    : `${base} — שקול לשנות את תאריכי המשמרת או להרחיב את הכשירות`;
}
```

Update `collectUnfilledShifts`'s signature and body to accept and use the cluster map:

```tsx
function collectUnfilledShifts(
  batchResults: BatchResult[],
  shiftNames: Record<string, string>,
  shiftsById: Record<string, DutyShift>,
  clusterMap: Map<string, SaturationCluster>,
  dutyTypeNames: Record<string, string>,
): UnfilledShift[] {
  const result: UnfilledShift[] = [];
  for (const br of batchResults) {
    for (const sf of br.shifts) {
      const missing = sf.required_count - sf.assigned_count;
      if (missing <= 0) continue;
      const cluster = sf.shift_id ? clusterMap.get(sf.shift_id) : undefined;
      let reason = "לא ידוע";
      if (cluster) reason = describeCluster(cluster, dutyTypeNames);
      else if (br.outcome === "INFEASIBLE") reason = "אין פתרון אפשרי — חסרים חיילים כשירים או קיימים אילוצים מנוגדים";
      else if (br.relaxations.length > 0) reason = `מגבלות הוגמשו (${br.relaxations.join(", ")}) אך לא נמצאו מספיק חיילים`;
      else reason = "אין מספיק חיילים כשירים לאותה תקופה";
      const shift = sf.shift_id ? shiftsById[sf.shift_id] : undefined;
      result.push({
        shiftId: sf.shift_id,
        shiftName: sf.shift_id ? (shiftNames[sf.shift_id] ?? sf.shift_id.slice(0, 8)) : "—",
        batchIndex: br.batch_index,
        dateFrom: shift?.start_date ?? br.date_from,
        dateTo: shift?.end_date ?? br.date_to,
        required: sf.required_count,
        assigned: sf.assigned_count,
        missing,
        reason,
      });
    }
  }
  return result;
}
```

Update `analyzeBatches` to skip relaxation tallying for saturation-dominated batches:

```tsx
function analyzeBatches(batchResults: BatchResult[]): DiagnosticResult {
  let rCeilingHitCount = 0;
  let tCeilingHitCount = 0;
  let infeasibleCount = 0;
  let maxR: number | null = null;
  let maxT: number | null = null;

  for (const br of batchResults) {
    if (br.outcome === "INFEASIBLE") infeasibleCount++;
    const saturated = (br.saturation_clusters ?? []).length > 0;
    if (saturated) continue;
    for (const rel of br.relaxations) {
      const rMatch = rel.match(/^R→(\d+)$/);
      const tMatch = rel.match(/^T→(\d+)$/);
      if (rMatch) {
        rCeilingHitCount++;
        const val = parseInt(rMatch[1]);
        if (maxR === null || val > maxR) maxR = val;
      }
      if (tMatch) {
        tCeilingHitCount++;
        const val = parseInt(tMatch[1]);
        if (maxT === null || val > maxT) maxT = val;
      }
    }
  }
  return { rCeilingHitCount, tCeilingHitCount, infeasibleCount, currentRCeiling: maxR, currentTCeiling: maxT };
}
```

Finally, update the component body to wire `dutyTypes` (currently unused as `_dutyTypes`) and pass the new arguments:

```tsx
export default function IssuesTab({ job, dutyTypes, shiftNames, shiftsById, onRerun }: Props) {
  const batchResults = job.batch_results ?? [];
  const dutyTypeNames = Object.fromEntries(dutyTypes.map((dt) => [dt.id, dt.name]));
  const clusterMap = buildClusterMap(batchResults);
  const unfilledShifts = collectUnfilledShifts(batchResults, shiftNames, shiftsById, clusterMap, dutyTypeNames);
  const diagnostics = analyzeBatches(batchResults);
```

(Only the `dutyTypes` parameter name and the two new lines/arguments change; the rest of the function body is unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- IssuesTab`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full frontend test suite and linter**

Run: `npm test` and `npm run lint` (from `frontend/`)
Expected: PASS, zero lint warnings

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/IssuesTab.tsx frontend/src/components/IssuesTab.test.tsx
git commit -m "feat: explain saturation clusters in Issues tab, suppress misleading recommendation"
```

---

## Final Verification

- [ ] Run the full backend suite: `pytest -q` (from `backend/`) — expect PASS.
- [ ] Run the full backend slow suite once: `pytest --slow -q` (from `backend/`) — expect PASS (this is the gate that exercises large-scale CP-SAT runs; the binary-search restart changes the cost profile of `effort_rounds`, worth confirming nothing regresses to a timeout).
- [ ] Run the full frontend suite: `npm test` and `npm run lint` (from `frontend/`) — expect PASS, zero lint warnings.
- [ ] Optionally replay the originally-diagnosed job dump through `app/scripts/replay_solver.py` (the file used throughout this investigation) and confirm it now reaches `802/802` or reports a `saturation_clusters` explanation instead of a bare "FEASIBLE 794/802".
