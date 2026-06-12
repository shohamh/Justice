# Split Density Cap into T (real duties) and R (incl. reserve) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the solver's single per-window density cap with two caps — `T` (non-reserve duty-days, baseline 7) and `R` (all duty-days incl. reserve, baseline 7) — and relax `R` before `T` on infeasibility.

**Architecture:** The CP-SAT model emits up to two rolling-window constraints per soldier: the T cap counts only non-reserve duty-days, the R cap counts all. `ExistingAssignment` gains an `is_reserve` flag so published reserve duties count toward R but not T. The relaxation chain loosens R (7→9→11 in hops of 2) before T (7→9 in hops of 2).

**Tech Stack:** Python, OR-Tools CP-SAT, SQLAlchemy, pytest. Run all commands from `backend/`.

**Invariant:** `T <= R` at all times. Relaxation sequence: `(T7,R7) → (T7,R9) → (T7,R11) → (T9,R11) → INFEASIBLE`.

Spec: [docs/superpowers/specs/2026-06-12-split-density-cap-reserve-design.md](../specs/2026-06-12-split-density-cap-reserve-design.md)

---

### Task 1: Add `R` to `SolverSettings` and `is_reserve` to `ExistingAssignment`

**Files:**
- Modify: `backend/app/algorithm/types.py:43-71` (ExistingAssignment, SolverSettings)
- Test: `backend/app/algorithm/tests/test_solver.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/app/algorithm/tests/test_solver.py`:

```python
def test_settings_and_existing_have_reserve_caps() -> None:
    # R defaults to 7 and is independent of T.
    s = SolverSettings()
    assert s.T == 7
    assert s.R == 7
    s2 = SolverSettings(T=7, R=11)
    assert s2.R == 11
    # ExistingAssignment carries an is_reserve flag, default False.
    ea = ExistingAssignment(
        soldier_id=uuid4(), duty_type_id=uuid4(),
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
    )
    assert ea.is_reserve is False
    ea_r = ExistingAssignment(
        soldier_id=uuid4(), duty_type_id=uuid4(),
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
        is_reserve=True,
    )
    assert ea_r.is_reserve is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest app/algorithm/tests/test_solver.py::test_settings_and_existing_have_reserve_caps -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'R'` (or `is_reserve`).

- [ ] **Step 3: Add the fields**

In `backend/app/algorithm/types.py`, add `is_reserve` to `ExistingAssignment`:

```python
@dataclass
class ExistingAssignment:
    """An already-published assignment for min_gap continuity."""
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    start_date: date
    end_date: date
    is_reserve: bool = False
```

In `SolverSettings`, add `R` next to `T` and update the docstring:

```python
@dataclass
class SolverSettings:
    """CP-SAT solver configuration.

    T: non-reserve (real) duty-day cap per rolling window
    R: total duty-day cap per rolling window (incl. reserve); invariant T <= R
    W: rolling window length in days
    alpha: score-preference weight (higher = stronger preference for low-score soldiers)
    """
    T: int = 7
    R: int = 7
    W: int = 14
```

(Leave the remaining `SolverSettings` fields — `alpha`, `time_limit_seconds`, etc. — unchanged, just shifted below `W`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest app/algorithm/tests/test_solver.py::test_settings_and_existing_have_reserve_caps -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/algorithm/types.py app/algorithm/tests/test_solver.py
git commit -m "feat: add R cap to SolverSettings and is_reserve to ExistingAssignment"
```

---

### Task 2: Split the window constraint into T (non-reserve) and R (all)

**Files:**
- Modify: `backend/app/algorithm/model.py:182-243` (the rolling-window density block)
- Test: `backend/app/algorithm/tests/test_solver.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/app/algorithm/tests/test_solver.py`. This builds 3 non-reserve + 3 reserve single-day duties all inside one 6-day window for a single soldier, with `T=2, R=5, W=14`. Coverage forces the soldier to take all 6, which is infeasible — but we test the model directly (no relaxation) to assert the caps are enforced: the model must be INFEASIBLE because total 6 > R=5. Then with `R=6` it becomes feasible, and we assert at most 2 non-reserve are assigned.

```python
def _single_day_duty(dt: date, duty_type, *, is_reserve: bool) -> DutyBlock:
    return DutyBlock(
        id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
        start_date=dt, end_date=dt, score_per_day=Decimal("1.00"),
        is_reserve=is_reserve,
    )


def test_window_caps_split_reserve_and_real() -> None:
    soldier_id = uuid4()
    duty_type = uuid4()
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100)]
    base = date(2026, 6, 1)
    real = [_single_day_duty(base + timedelta(days=i), duty_type, is_reserve=False)
            for i in range(3)]
    reserve = [_single_day_duty(base + timedelta(days=3 + i), duty_type, is_reserve=True)
               for i in range(3)]
    duties = real + reserve  # 6 duties, all within a 14-day window

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5

    # T=2, R=5: must cover all 6, but 6 > R=5 → INFEASIBLE.
    model, _ = build_model(soldiers=soldiers, duties=duties, existing=[],
                           settings=SolverSettings(T=2, R=5, W=14))
    assert solver.Solve(model) == cp_model.INFEASIBLE

    # T=2, R=6: total fits under R, but only 2 of the 3 real duties may be taken...
    # coverage still forces all 3 real → infeasible on T=2.
    model2, _ = build_model(soldiers=soldiers, duties=duties, existing=[],
                            settings=SolverSettings(T=2, R=6, W=14))
    assert solver.Solve(model2) == cp_model.INFEASIBLE

    # T=3, R=6: 3 real (== T) + 3 reserve (total 6 == R) → feasible.
    model3, x3 = build_model(soldiers=soldiers, duties=duties, existing=[],
                             settings=SolverSettings(T=3, R=6, W=14))
    assert solver.Solve(model3) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assigned_real = sum(
        solver.Value(x3[(di, 0)])
        for di, d in enumerate(duties) if not d.is_reserve
    )
    assert assigned_real == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest app/algorithm/tests/test_solver.py::test_window_caps_split_reserve_and_real -v`
Expected: FAIL — with the current single cap reading `T`, `SolverSettings(T=2, R=5)` caps total at 2 (not 5), so the first assertion's INFEASIBLE holds for the wrong reason, and `model3` (T=3) would cap total at 3 and be INFEASIBLE, failing the feasibility assertion.

- [ ] **Step 3: Implement the split constraint**

In `backend/app/algorithm/model.py`, read `R` alongside `T` near the top of `build_model` (after `T = settings.T` at line ~60):

```python
    W = settings.W
    T = settings.T
    R = settings.R
```

Replace the window-constraint block (the `for si, s in enumerate(soldier_list):` loop spanning lines ~192-243) with a version that tallies reserve vs non-reserve separately. The existing pre-fix counting must split by `ExistingAssignment.is_reserve`, and the variable list must be split by `duty_list[di].is_reserve`:

```python
    # Pre-split existing duty-days per soldier into all vs non-reserve dates,
    # so the T cap (non-reserve) and R cap (all) can be counted independently.
    existing_all_by_soldier = {
        s.id: _existing_dates_by_soldier(existing, s.id) for s in soldier_list
    }
    existing_real_by_soldier = {
        s.id: _existing_dates_by_soldier(
            [e for e in existing if not e.is_reserve], s.id
        )
        for s in soldier_list
    }

    for si, s in enumerate(soldier_list):
        si_duties = soldier_duties.get(si, [])
        existing_all = existing_all_by_soldier.get(s.id, set())
        existing_real = existing_real_by_soldier.get(s.id, set())

        if not si_duties and not existing_all:
            continue

        # Sort eligible duties by start_date for binary-search window lookup.
        si_duties_sorted = sorted(si_duties, key=lambda di: duty_list[di].start_date)
        starts_sorted: list[date] = [duty_list[di].start_date for di in si_duties_sorted]
        ends_sorted: list[date] = [duty_list[di].end_date for di in si_duties_sorted]

        all_relevant: set[date] = set(existing_all)
        for di in si_duties:
            all_relevant.add(duty_list[di].start_date)
            all_relevant.add(duty_list[di].end_date)
        if not all_relevant:
            continue

        min_d = min(all_relevant)
        max_d = max(all_relevant)
        sorted_existing_all = sorted(existing_all)
        sorted_existing_real = sorted(existing_real)

        ws = min_d
        while ws <= max_d:
            we = ws + timedelta(days=W - 1)

            existing_all_fixed = (
                bisect.bisect_right(sorted_existing_all, we)
                - bisect.bisect_left(sorted_existing_all, ws)
            )
            existing_real_fixed = (
                bisect.bisect_right(sorted_existing_real, we)
                - bisect.bisect_left(sorted_existing_real, ws)
            )

            right = bisect.bisect_right(starts_sorted, we)
            vars_all: list[IntVar] = []
            vars_real: list[IntVar] = []
            for i in range(right):
                if ends_sorted[i] < ws:
                    continue
                di = si_duties_sorted[i]
                var = x[(di, si)]
                vars_all.append(var)
                if not duty_list[di].is_reserve:
                    vars_real.append(var)

            # R cap: all duty-days (reserve + real) in the window.
            if vars_all or existing_all_fixed:
                model.Add(existing_all_fixed + sum(vars_all) <= R)
            # T cap: non-reserve duty-days only.
            if vars_real or existing_real_fixed:
                model.Add(existing_real_fixed + sum(vars_real) <= T)

            ws += timedelta(days=1)
```

- [ ] **Step 4: Run the new test and the full algorithm suite**

Run: `uv run pytest app/algorithm/tests/test_solver.py::test_window_caps_split_reserve_and_real -v`
Expected: PASS

Run: `uv run pytest app/algorithm/ -q`
Expected: PASS (existing density/relaxation/golden tests still green — with `R` defaulting to `T`'s old value of 7, the R cap is at least as tight as before only where reserves exist; pre-existing fixtures use no reserves so behavior is unchanged).

- [ ] **Step 5: Commit**

```bash
git add app/algorithm/model.py app/algorithm/tests/test_solver.py
git commit -m "feat: split window density cap into T (real) and R (incl. reserve)"
```

---

### Task 3: Relax R before T in the infeasibility chain

**Files:**
- Modify: `backend/app/algorithm/solver.py:288-302` (relaxation loop)
- Test: `backend/app/algorithm/tests/test_solver.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/app/algorithm/tests/test_solver.py`. One soldier must cover 8 real single-day duties inside a 14-day window. Baseline `T=7, R=7` is infeasible (8 > 7). The chain must relax R first (7→9), which makes total feasible; but the T cap (8 real > 7) is still violated, so it then relaxes T (7→9). Assert ordering: an `R→` entry appears before any `T→` entry, and the result is feasible.

```python
def test_relaxation_relaxes_R_before_T() -> None:
    soldier_id = uuid4()
    duty_type = uuid4()
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100)]
    base = date(2026, 6, 1)
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                  start_date=base + timedelta(days=i), end_date=base + timedelta(days=i),
                  score_per_day=Decimal("1.00"), is_reserve=False)
        for i in range(8)  # 8 real duty-days in a 14-day window
    ]
    result = solve(soldiers, duties, [],
                   SolverSettings(T=7, R=7, W=14, time_limit_seconds=5))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    r_idx = next((i for i, r in enumerate(result.relaxed) if r.startswith("R")), None)
    t_idx = next((i for i, r in enumerate(result.relaxed) if r.startswith("T")), None)
    assert r_idx is not None, f"expected R relaxation, got {result.relaxed}"
    assert t_idx is not None, f"expected T relaxation, got {result.relaxed}"
    assert r_idx < t_idx, f"R must relax before T, got {result.relaxed}"
    # R relaxes in hops of 2 capped at 11; T in hops of 2 capped at 9.
    assert "R→9" in result.relaxed
    assert "T→9" in result.relaxed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest app/algorithm/tests/test_solver.py::test_relaxation_relaxes_R_before_T -v`
Expected: FAIL — current chain only relaxes `T` (no `R→` entries), so `r_idx` is `None`.

- [ ] **Step 3: Rewrite the relaxation loop**

In `backend/app/algorithm/solver.py`, replace the `max_t = max(current.T, current.W)` line and the `if status_name == "INFEASIBLE":` block (lines ~288-306) with two-stage R-then-T relaxation. Caps: `R` up to 11 in hops of 2, then `T` up to 9 in hops of 2.

```python
    # Two-stage density relaxation. R (total, incl. reserve) loosens first in
    # hops of 2 up to 11, absorbing reserve overload before real-duty fairness
    # is touched. Then T (real only) loosens in hops of 2 up to 9. The invariant
    # T <= R holds throughout: R reaches 11 before T leaves 7.
    R_MAX = 11
    T_MAX = 9

    while True:
        solver, x, status = _solve_with_settings(soldiers, duties, existing, current, reserve_dist, cancel_event=cancel_event)
        status_name = solver.StatusName(status)

        # UNKNOWN means StopSearch() fired before a solution was found — treat as cancelled
        if status_name not in ("OPTIMAL", "FEASIBLE", "INFEASIBLE"):
            return SolverResult(assignments=[], status="CANCELLED", seed=(current.seed if current.seed is not None else DEFAULT_SOLVER_SEED), relaxed=relaxed)

        if status_name == "INFEASIBLE":
            if current.R < R_MAX:
                current.R = min(R_MAX, current.R + 2)
                relaxed.append(f"R→{current.R}")
                continue
            if current.T < T_MAX:
                current.T = min(T_MAX, current.T + 2)
                relaxed.append(f"T→{current.T}")
                continue
            return SolverResult(
                assignments=[], status="INFEASIBLE",
                seed=(current.seed if current.seed is not None else DEFAULT_SOLVER_SEED), relaxed=relaxed,
            )
```

(The success path below this block — building `assignments`, sorting, returning `SolverResult` — stays unchanged.)

- [ ] **Step 4: Run the new test and the full algorithm suite**

Run: `uv run pytest app/algorithm/tests/test_solver.py::test_relaxation_relaxes_R_before_T -v`
Expected: PASS

Run: `uv run pytest app/algorithm/ -q`
Expected: PASS. Note: `test_infeasibility_relaxation` (line ~116) uses `SolverSettings(T=1, W=2)` with `R` defaulting to 7 — coverage forces 2 duty-days, infeasible on T=1; the chain now relaxes R (already ≥2, no effect on the binding T cap) up to 11, then T (1→3→5→7→9), reaching a feasible T. `result.relaxed` is still non-empty, so that test stays green. If it regresses, update its assertion to `assert any(r.startswith("T") for r in result.relaxed)`.

- [ ] **Step 5: Commit**

```bash
git add app/algorithm/solver.py app/algorithm/tests/test_solver.py
git commit -m "feat: relax R before T in density infeasibility chain"
```

---

### Task 4: Populate `is_reserve` when loading existing assignments in the bridge

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py:352-360` (ExistingAssignment construction)
- Test: `backend/app/services/tests/test_algorithm_bridge.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `backend/app/services/tests/test_algorithm_bridge.py`. Uses the shared `admin_session`, `soldier`, `duty_type`, `location` fixtures (re-exported via `app/services/tests/conftest.py`). Inserts one published real and one published reserve assignment, then asserts the loader carries `is_reserve` through.

```python
from datetime import date

from app.db.models import DutyAssignment
from app.services.algorithm_bridge import load_existing_assignments


def test_load_existing_assignments_carries_is_reserve(
    admin_session, soldier, duty_type, location
):
    admin_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 10), end_date=date(2026, 6, 10),
        status="published", is_reserve=False,
    ))
    admin_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=duty_type.id,
        duty_location_id=location.id,
        start_date=date(2026, 6, 11), end_date=date(2026, 6, 11),
        status="published", is_reserve=True,
    ))
    admin_session.flush()

    loaded = load_existing_assignments(
        admin_session,
        planning_start=date(2026, 6, 1),
        planning_end=date(2026, 6, 30),
        W=14,
    )
    by_start = {e.start_date: e for e in loaded}
    assert by_start[date(2026, 6, 10)].is_reserve is False
    assert by_start[date(2026, 6, 11)].is_reserve is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest app/services/tests/test_algorithm_bridge.py -v`
Expected: FAIL — `assert by_start[date(2026, 6, 11)].is_reserve is True` fails because the loader hardcodes the default `False`.

- [ ] **Step 3: Populate the flag**

In `backend/app/services/algorithm_bridge.py`, add `is_reserve=a.is_reserve` to the `ExistingAssignment(...)` construction (the list comprehension at lines ~352-359):

```python
    return [
        ExistingAssignment(
            soldier_id=a.soldier_id,
            duty_type_id=a.duty_type_id,
            start_date=a.start_date,
            end_date=a.end_date,
            is_reserve=a.is_reserve,
        )
        for a in rows
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest app/services/tests/test_algorithm_bridge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/algorithm_bridge.py app/services/tests/test_algorithm_bridge.py
git commit -m "feat: carry is_reserve from published rows into ExistingAssignment"
```

---

### Task 5: Existing reserve duty-days count toward R but not T (integration test)

**Files:**
- Test: `backend/app/algorithm/tests/test_solver.py`

This task adds no production code — it locks in the cross-cutting behavior from Tasks 1, 2, and 4: a published **reserve** `ExistingAssignment` consumes R headroom but leaves T headroom intact.

- [ ] **Step 1: Write the failing-then-passing test**

Add to `backend/app/algorithm/tests/test_solver.py`. A soldier has 2 existing **reserve** duty-days in a window. We then ask the model to assign 1 new real duty in the same window with `T=1, R=2`. Real load = 1 (≤ T=1, ok because existing reserves don't count toward T). Total load = 2 existing reserve + 1 new = 3 > R=2 → INFEASIBLE. With `R=3` it becomes feasible. This proves the existing reserve days hit R but not T.

```python
def test_existing_reserve_counts_toward_R_not_T() -> None:
    soldier_id = uuid4()
    duty_type = uuid4()
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100)]
    base = date(2026, 6, 1)
    # Two existing PUBLISHED RESERVE duty-days in the window.
    existing = [
        ExistingAssignment(soldier_id=soldier_id, duty_type_id=duty_type,
                           start_date=base, end_date=base, is_reserve=True),
        ExistingAssignment(soldier_id=soldier_id, duty_type_id=duty_type,
                           start_date=base + timedelta(days=1),
                           end_date=base + timedelta(days=1), is_reserve=True),
    ]
    # One NEW REAL duty in the same window.
    duties = [_single_day_duty(base + timedelta(days=2), duty_type, is_reserve=False)]

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5

    # T=1 satisfied (1 real ≤ 1, existing reserves don't count toward T),
    # but R=2 violated (2 reserve + 1 real = 3 > 2) → INFEASIBLE.
    model, _ = build_model(soldiers=soldiers, duties=duties, existing=existing,
                           settings=SolverSettings(T=1, R=2, W=14))
    assert solver.Solve(model) == cp_model.INFEASIBLE

    # R=3 gives headroom for the total → FEASIBLE, real duty assigned.
    model2, x2 = build_model(soldiers=soldiers, duties=duties, existing=existing,
                             settings=SolverSettings(T=1, R=3, W=14))
    assert solver.Solve(model2) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.Value(x2[(0, 0)]) == 1
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest app/algorithm/tests/test_solver.py::test_existing_reserve_counts_toward_R_not_T -v`
Expected: PASS (Tasks 1–2 already implement the behavior; this test guards it).

- [ ] **Step 3: Run the full backend suite**

Run: `uv run pytest -q`
Expected: PASS — no regressions across algorithm and service suites.

- [ ] **Step 4: Commit**

```bash
git add app/algorithm/tests/test_solver.py
git commit -m "test: existing reserve duty-days count toward R but not T"
```

---

## Self-Review Notes

- **Spec coverage:** §1 settings → Task 1; §2 bridge → Task 4; §3 model split → Task 2; §4 relaxation → Task 3; §5 tests → spread across Tasks 2, 3, 5.
- **Type consistency:** `R` (int), `is_reserve` (bool) used identically in types, model, bridge, and tests. Relaxation entries use the existing `"X→N"` string format (matching the current `T→` convention) so `result.relaxed` stays parseable.
- **Invariant `T ≤ R`:** baseline 7=7; R reaches 11 before T leaves 7; T capped at 9 < 11. Holds at every step.
