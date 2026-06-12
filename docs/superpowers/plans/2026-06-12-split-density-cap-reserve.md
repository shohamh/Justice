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

# Phase 2 — Configurable T/R/W + relaxation ceilings (system settings + per-run override)

Spec: Phase 2 section of [the design doc](../specs/2026-06-12-split-density-cap-reserve-design.md). Phase 1 (Tasks 1–5) must be complete first.

### Task 6: Make relaxation ceilings configurable on `SolverSettings`

**Files:**
- Modify: `backend/app/algorithm/types.py` (SolverSettings)
- Modify: `backend/app/algorithm/solver.py` (relaxation loop — replace `R_MAX`/`T_MAX` constants)
- Test: `backend/app/algorithm/tests/test_solver.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/app/algorithm/tests/test_solver.py`. Ten single-day **reserve** duties in one window force one soldier (via coverage) to take all 10. Only the R cap binds (reserve duties don't count toward T). With the default `relax_r_ceiling=11`, R relaxes 7→9→11 and 11≥10 is feasible. With `relax_r_ceiling=9`, R maxes at 9<10 → infeasible.

```python
def test_relax_r_ceiling_is_configurable() -> None:
    soldier_id = uuid4()
    duty_type = uuid4()
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100)]
    base = date(2026, 6, 1)
    duties = [_single_day_duty(base + timedelta(days=i), duty_type, is_reserve=True)
              for i in range(10)]  # 10 reserve duty-days in a 14-day window

    # Default ceiling 11: R reaches 11 ≥ 10 → feasible.
    ok = solve(soldiers, duties, [],
               SolverSettings(T=7, R=7, W=14, time_limit_seconds=5))
    assert ok.status in ("OPTIMAL", "FEASIBLE")
    assert "R→11" in ok.relaxed

    # Ceiling lowered to 9: R caps at 9 < 10 → infeasible.
    bad = solve(soldiers, duties, [],
                SolverSettings(T=7, R=7, W=14, relax_r_ceiling=9, relax_t_ceiling=9,
                               time_limit_seconds=5))
    assert bad.status == "INFEASIBLE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest app/algorithm/tests/test_solver.py::test_relax_r_ceiling_is_configurable -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'relax_r_ceiling'`.

- [ ] **Step 3: Add the fields and use them in the solver**

In `backend/app/algorithm/types.py`, add to `SolverSettings` (after `batch_time_limit_seconds`):

```python
    # Density relaxation ceilings (see solver._infeasibility_relaxation_chain).
    relax_t_ceiling: int = 9
    relax_r_ceiling: int = 11
```

In `backend/app/algorithm/solver.py`, replace the Phase 1 constants

```python
    R_MAX = 11
    T_MAX = 9
```

with reads from the (mutable copy of) settings:

```python
    R_MAX = current.relax_r_ceiling
    T_MAX = current.relax_t_ceiling
```

(Place these after `current = dataclasses.replace(settings)` so they reflect the configured ceilings. The rest of the loop is unchanged.)

- [ ] **Step 4: Run the new test and the full algorithm suite**

Run: `uv run pytest app/algorithm/tests/test_solver.py::test_relax_r_ceiling_is_configurable -v`
Expected: PASS

Run: `uv run pytest app/algorithm/ -q`
Expected: PASS (default ceilings 9/11 reproduce Phase 1 behavior).

- [ ] **Step 5: Commit**

```bash
git add app/algorithm/types.py app/algorithm/solver.py app/algorithm/tests/test_solver.py
git commit -m "feat: make density relaxation ceilings configurable on SolverSettings"
```

---

### Task 7: Resolve T/R/W + ceilings from system settings and per-run overrides

Extract the inline settings resolution in `run_algorithm_job` into a pure, testable helper `resolve_solver_settings(session, settings_json)`, and add the new keys (`R`, `relax_t_ceiling`, `relax_r_ceiling`).

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py:556-585` (extract helper, call it)
- Test: `backend/app/services/tests/test_algorithm_bridge.py` (add cases)

- [ ] **Step 1: Write the failing test**

Add to `backend/app/services/tests/test_algorithm_bridge.py` (created in Task 4). Uses `admin_session` + the `set_setting` loader. Asserts (a) system-setting fallbacks are read when `settings_json` omits a key, and (b) `settings_json` overrides win.

```python
from decimal import Decimal

from app.services.algorithm_bridge import resolve_solver_settings
from app.services.settings_loader import set_setting


def test_resolve_solver_settings_uses_system_defaults(admin_session):
    set_setting(admin_session, "algorithm.max_duties_per_window", 6, actor_id=None)
    set_setting(admin_session, "algorithm.max_total_duties_per_window", 10, actor_id=None)
    set_setting(admin_session, "algorithm.window_days", 21, actor_id=None)
    set_setting(admin_session, "algorithm.relax_t_ceiling", 8, actor_id=None)
    set_setting(admin_session, "algorithm.relax_r_ceiling", 12, actor_id=None)
    admin_session.flush()

    s = resolve_solver_settings(admin_session, {})
    assert s.T == 6
    assert s.R == 10
    assert s.W == 21
    assert s.relax_t_ceiling == 8
    assert s.relax_r_ceiling == 12


def test_resolve_solver_settings_per_run_overrides_win(admin_session):
    set_setting(admin_session, "algorithm.max_total_duties_per_window", 10, actor_id=None)
    admin_session.flush()
    # Per-run settings_json overrides the system R.
    s = resolve_solver_settings(admin_session, {"T": 5, "R": 9, "W": 14})
    assert s.T == 5
    assert s.R == 9
    assert s.W == 14


def test_resolve_solver_settings_falls_back_to_hardcoded_defaults(admin_session):
    # No system settings set, no overrides → dataclass defaults.
    s = resolve_solver_settings(admin_session, {})
    assert s.T == 7
    assert s.R == 7
    assert s.W == 14
    assert s.relax_t_ceiling == 9
    assert s.relax_r_ceiling == 11
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest app/services/tests/test_algorithm_bridge.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_solver_settings'`.

- [ ] **Step 3: Extract the helper and add the new keys**

In `backend/app/services/algorithm_bridge.py`, add a module-level function (near the top, after imports). It must `from app.algorithm.types import SolverSettings` and `from app.services.settings_loader import get_setting` (already imported in the module — reuse the existing import if present at module scope, otherwise import locally):

```python
def resolve_solver_settings(session: Session, settings_json: dict) -> "SolverSettings":
    """Resolve solver settings from per-run overrides (settings_json) layered over
    system-setting defaults, falling back to SolverSettings' own dataclass defaults.

    Per-run keys win over system settings; system settings win over hardcoded defaults.
    """
    from app.algorithm.types import SolverSettings
    from app.services.settings_loader import get_setting

    def _setting_decimal(key: str, default: str) -> Decimal:
        try:
            return Decimal(str(get_setting(session, key)))
        except Exception:
            return Decimal(default)

    def _setting_int(key: str, default: int) -> int:
        try:
            return int(get_setting(session, key))
        except Exception:
            return default

    def _setting_bool(key: str, default: bool) -> bool:
        try:
            return bool(get_setting(session, key))
        except Exception:
            return default

    return SolverSettings(
        T=int(settings_json.get("T", _setting_int("algorithm.max_duties_per_window", 7))),
        R=int(settings_json.get("R", _setting_int("algorithm.max_total_duties_per_window", 7))),
        W=int(settings_json.get("W", _setting_int("algorithm.window_days", 14))),
        alpha=Decimal(str(settings_json.get("alpha", 1.0))),
        time_limit_seconds=int(settings_json.get("time_limit_seconds", 30)),
        reserve_hierarchy_weight=_setting_decimal("fairness.reserve_hierarchy_weight", "0.5"),
        effort_resolution=_setting_int("fairness.effort_resolution", 10_000),
        batching_enabled=_setting_bool("algorithm.batching_enabled", True),
        batch_size=_setting_int("algorithm.batch_size", 50),
        batch_time_limit_seconds=_setting_int("algorithm.batch_time_limit_seconds", 10),
        relax_t_ceiling=int(settings_json.get("relax_t_ceiling", _setting_int("algorithm.relax_t_ceiling", 9))),
        relax_r_ceiling=int(settings_json.get("relax_r_ceiling", _setting_int("algorithm.relax_r_ceiling", 11))),
    )
```

Then in `run_algorithm_job`, replace the inline `settings = SolverSettings(...)` block (and its three local `_setting_*` helpers, lines ~557-585) with:

```python
                settings = resolve_solver_settings(session, job.settings_json)
                standby_multiplier = Decimal(str(
                    _setting_one(session, "scoring.reserve_standby_multiplier", "0.2")
                ))
```

Note: `standby_multiplier` previously used the local `_setting_decimal`. To avoid re-introducing the local helpers, define a tiny module-level `_setting_one` OR keep a single local `_setting_decimal` just for `standby_multiplier`. Simplest: keep one local helper for standby:

```python
                settings = resolve_solver_settings(session, job.settings_json)

                def _setting_decimal(key: str, default: str) -> Decimal:
                    try:
                        return Decimal(str(get_setting(session, key)))
                    except Exception:
                        return Decimal(default)

                standby_multiplier = _setting_decimal("scoring.reserve_standby_multiplier", "0.2")
```

(Keep the rest of `run_algorithm_job` — `load_duty_blocks_from_shifts`, the `W=settings.W` usages, etc. — unchanged.)

- [ ] **Step 4: Run the bridge tests and the algorithm-route integration tests**

Run: `uv run pytest app/services/tests/test_algorithm_bridge.py -v`
Expected: PASS

Run: `uv run pytest tests/integration/test_algorithm_routes.py -q`
Expected: PASS (job execution still resolves settings).

- [ ] **Step 5: Commit**

```bash
git add app/services/algorithm_bridge.py app/services/tests/test_algorithm_bridge.py
git commit -m "feat: resolve T/R/W and relax ceilings from system settings + per-run overrides"
```

---

### Task 8: Add `R` to per-run schema and reject `T > R` on job submit

**Files:**
- Modify: `backend/app/routes/algorithm.py:53-58` (SolverSettingsIn), `:329-376` (create_job validation)
- Test: `backend/tests/integration/test_algorithm_routes.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_algorithm_routes.py`:

```python
def test_create_job_rejects_T_greater_than_R(client, admin_session):
    dm, _node = _setup_dm(admin_session, "route_alg_tr")
    shift, _dt, _loc = _make_shift(admin_session, "route_tr", "2027-07-02")
    create_soldier(admin_session, personal_number="route_soldier_tr", role="soldier")

    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"T": 9, "R": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 5},
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "t_exceeds_r"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_algorithm_routes.py::test_create_job_rejects_T_greater_than_R -v`
Expected: FAIL — currently returns 202 (no validation; `R` is also an unknown field).

- [ ] **Step 3: Add `R` to the schema and validate in create_job**

In `backend/app/routes/algorithm.py`, add `R` to `SolverSettingsIn`:

```python
class SolverSettingsIn(BaseModel):
    K: int = 8
    T: int = 7
    R: int = 7
    W: int = 14
    alpha: float = 1.0
    time_limit_seconds: int = 30
```

In `create_job`, right after the `if body.mode not in (...)` check, add:

```python
    if body.settings.T > body.settings.R:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="t_exceeds_r")
```

- [ ] **Step 4: Run the test and the existing route tests**

Run: `uv run pytest tests/integration/test_algorithm_routes.py -q`
Expected: PASS (existing `test_create_job_returns_202` still passes — its settings omit `R`, which defaults to 7 ≥ T=7).

- [ ] **Step 5: Commit**

```bash
git add app/routes/algorithm.py tests/integration/test_algorithm_routes.py
git commit -m "feat: add R to per-run solver settings and reject T>R on job submit"
```

---

### Task 9: Reject invariant violations on system-settings PUT

**Files:**
- Modify: `backend/app/routes/system_settings.py:38-50` (update_settings)
- Test: `backend/tests/integration/test_system_settings_density.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_system_settings_density.py`:

```python
from __future__ import annotations

from tests.helpers import auth_headers, create_soldier


def _admin(session, personal_number: str):
    return create_soldier(session, personal_number=personal_number, role="admin")


def test_put_rejects_T_greater_than_R(client, admin_session):
    admin = _admin(admin_session, "sysset_admin_1")
    resp = client.put(
        "/api/admin/system-settings",
        json={"settings": {
            "algorithm.max_duties_per_window": 9,
            "algorithm.max_total_duties_per_window": 7,
        }},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "t_exceeds_r"


def test_put_rejects_t_ceiling_above_r_ceiling(client, admin_session):
    admin = _admin(admin_session, "sysset_admin_2")
    resp = client.put(
        "/api/admin/system-settings",
        json={"settings": {
            "algorithm.relax_t_ceiling": 12,
            "algorithm.relax_r_ceiling": 11,
        }},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "relax_ceiling_invalid"


def test_put_accepts_valid_density_settings(client, admin_session):
    admin = _admin(admin_session, "sysset_admin_3")
    resp = client.put(
        "/api/admin/system-settings",
        json={"settings": {
            "algorithm.max_duties_per_window": 7,
            "algorithm.max_total_duties_per_window": 10,
            "algorithm.window_days": 14,
            "algorithm.relax_t_ceiling": 9,
            "algorithm.relax_r_ceiling": 11,
        }},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    body = resp.json()["settings"]
    assert body["algorithm.max_total_duties_per_window"] == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_system_settings_density.py -v`
Expected: FAIL — first two tests get 200 (no validation today).

- [ ] **Step 3: Add invariant validation to update_settings**

In `backend/app/routes/system_settings.py`, replace the body of `update_settings` (the loop + re-read) with a version that first merges the incoming values over the existing ones and validates the density invariants before writing:

```python
from fastapi import HTTPException, status

_DENSITY_DEFAULTS = {
    "algorithm.max_duties_per_window": 7,
    "algorithm.max_total_duties_per_window": 7,
    "algorithm.relax_t_ceiling": 9,
    "algorithm.relax_r_ceiling": 11,
}


@router.put("", response_model=SettingsOut)
def update_settings(
    body: UpdateSettingsBody,
    session: Session = Depends(get_session),
    user=Depends(require_roles("admin")),
) -> SettingsOut:
    existing = {r.key: r.value for r in session.execute(select(SystemSetting)).scalars().all()}
    merged = {**existing, **body.settings}

    def _density(key: str) -> int:
        return int(merged.get(key, _DENSITY_DEFAULTS[key]))

    t = _density("algorithm.max_duties_per_window")
    r = _density("algorithm.max_total_duties_per_window")
    t_ceil = _density("algorithm.relax_t_ceiling")
    r_ceil = _density("algorithm.relax_r_ceiling")

    if t > r:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="t_exceeds_r")
    if t_ceil > r_ceil or t > t_ceil or r > r_ceil:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="relax_ceiling_invalid")

    for key, value in body.settings.items():
        if key in _HIDDEN_KEYS:
            continue
        set_setting(session, key=key, value=value, actor_id=user.id)
    session.commit()
    rows = session.execute(select(SystemSetting)).scalars().all()
    return SettingsOut(settings={r.key: r.value for r in rows if r.key not in _HIDDEN_KEYS})
```

(Add the `HTTPException, status` import to the existing `from fastapi import ...` line at the top.)

- [ ] **Step 4: Run the test and the existing settings behavior**

Run: `uv run pytest tests/integration/test_system_settings_density.py -q`
Expected: PASS

Run: `uv run pytest tests/integration/test_rbac_matrix.py -q`
Expected: PASS (no regression in settings auth).

- [ ] **Step 5: Commit**

```bash
git add app/routes/system_settings.py tests/integration/test_system_settings_density.py
git commit -m "feat: reject T>R and invalid relaxation ceilings on system-settings PUT"
```

---

### Task 10: `GET /algorithm/defaults` for resolved density defaults

**Files:**
- Modify: `backend/app/routes/algorithm.py` (new endpoint + response schema)
- Test: `backend/tests/integration/test_algorithm_routes.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_algorithm_routes.py`:

```python
def test_algorithm_defaults_returns_resolved_settings(client, admin_session):
    from app.services.settings_loader import set_setting
    dm, _node = _setup_dm(admin_session, "route_alg_def")
    set_setting(admin_session, "algorithm.max_total_duties_per_window", 10, actor_id=None)
    admin_session.commit()

    resp = client.get("/api/algorithm/defaults", headers=auth_headers(dm))
    assert resp.status_code == 200
    body = resp.json()
    assert body["T"] == 7
    assert body["R"] == 10
    assert body["W"] == 14
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_algorithm_routes.py::test_algorithm_defaults_returns_resolved_settings -v`
Expected: FAIL — 404, endpoint does not exist.

- [ ] **Step 3: Add the endpoint**

In `backend/app/routes/algorithm.py`, add a response schema near the other Pydantic models:

```python
class AlgorithmDefaultsOut(BaseModel):
    T: int
    R: int
    W: int
```

And the endpoint (e.g. after `create_job`):

```python
@router.get("/defaults", response_model=AlgorithmDefaultsOut)
def get_algorithm_defaults(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> AlgorithmDefaultsOut:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    from app.services.algorithm_bridge import resolve_solver_settings
    s = resolve_solver_settings(session, {})
    return AlgorithmDefaultsOut(T=s.T, R=s.R, W=s.W)
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/integration/test_algorithm_routes.py::test_algorithm_defaults_returns_resolved_settings -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/routes/algorithm.py tests/integration/test_algorithm_routes.py
git commit -m "feat: add GET /algorithm/defaults for resolved density defaults"
```

---

### Task 11: Frontend — add `R` to per-run override form, seed from `/algorithm/defaults`

**Files:**
- Modify: `frontend/src/api/algorithm.ts` (SolverSettings type + getAlgorithmDefaults)
- Modify: `frontend/src/components/AlgorithmRunForm.tsx` (DEFAULT_SETTINGS, field list, fetch defaults)

- [ ] **Step 1: Add `R` to the type and a defaults fetcher**

In `frontend/src/api/algorithm.ts`, add `R` to `SolverSettings`:

```typescript
export interface SolverSettings {
  K: number;
  T: number;
  R: number;
  W: number;
  alpha: number;
  beta: number;
  time_limit_seconds: number;
}
```

And add a fetcher:

```typescript
export interface AlgorithmDefaults {
  T: number;
  R: number;
  W: number;
}

export async function getAlgorithmDefaults(): Promise<AlgorithmDefaults> {
  return (await api.get<AlgorithmDefaults>("/algorithm/defaults")).data;
}
```

- [ ] **Step 2: Wire `R` and defaults into the form**

In `frontend/src/components/AlgorithmRunForm.tsx`:

Update `DEFAULT_SETTINGS` and the imports:

```typescript
import { SolverSettings, submitJob, getAlgorithmDefaults } from "../api/algorithm";

const DEFAULT_SETTINGS: SolverSettings = {
  K: 8, T: 7, R: 7, W: 14, alpha: 1.0, beta: 2.0, time_limit_seconds: 30,
};
```

Add an effect that seeds T/R/W from the backend on mount (after the existing `useEffect` for `loadShifts`):

```typescript
  useEffect(() => {
    void getAlgorithmDefaults()
      .then(d => setSettings(s => ({ ...s, T: d.T, R: d.R, W: d.W })))
      .catch(() => { /* keep hardcoded defaults if unavailable */ });
  }, []);
```

Add `R` to the advanced-options field list:

```typescript
          {(["K", "T", "R", "W", "alpha", "beta", "time_limit_seconds"] as const).map(key => (
```

- [ ] **Step 3: Lint and unit-test the frontend**

Run (from `frontend/`): `pnpm lint`
Expected: zero warnings.

Run: `pnpm test`
Expected: PASS (no existing tests broken; the type change compiles).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/algorithm.ts frontend/src/components/AlgorithmRunForm.tsx
git commit -m "feat: add R to per-run override form, seed T/R/W from /algorithm/defaults"
```

---

### Task 12: Frontend — density-caps group in System Settings

**Files:**
- Modify: `frontend/src/pages/SystemSettingsPage.tsx` (SETTING_GROUPS)

- [ ] **Step 1: Add the settings group**

In `frontend/src/pages/SystemSettingsPage.tsx`, add a new entry to `SETTING_GROUPS` (place it just before the existing `"פירוק ואצווה (אלגוריתם)"` group):

```typescript
  {
    label: "מגבלות צפיפות (אלגוריתם)",
    settings: [
      { key: "algorithm.max_duties_per_window", label: "מכסת תורנויות (ללא רזרבה) בחלון", description: "מספר תורנויות אמת מרבי לחייל בכל חלון נע (T). חייב להיות קטן או שווה למכסה הכוללת.", type: "number", defaultValue: 7 },
      { key: "algorithm.max_total_duties_per_window", label: "מכסת תורנויות כוללת (כולל רזרבה) בחלון", description: "מספר התורנויות הכולל המרבי לחייל בכל חלון נע, כולל רזרבה (R).", type: "number", defaultValue: 7 },
      { key: "algorithm.window_days", label: "אורך החלון (ימים)", description: "אורך החלון הנע בימים שבו נספרות המכסות (W).", type: "number", defaultValue: 14 },
      { key: "algorithm.relax_t_ceiling", label: "תקרת הרפיה — תורנויות (ללא רזרבה)", description: "הערך המרבי שאליו ניתן להרפות את מכסת תורנויות האמת כשאין פתרון (ברירת מחדל 9).", type: "number", defaultValue: 9 },
      { key: "algorithm.relax_r_ceiling", label: "תקרת הרפיה — תורנויות כוללת", description: "הערך המרבי שאליו ניתן להרפות את המכסה הכוללת כשאין פתרון (ברירת מחדל 11).", type: "number", defaultValue: 11 },
    ],
  },
```

- [ ] **Step 2: Lint and build the frontend**

Run (from `frontend/`): `pnpm lint`
Expected: zero warnings.

Run: `pnpm test`
Expected: PASS.

- [ ] **Step 3: Manual verification (optional)**

If the dev stack is running, open System Settings as an admin and confirm the new "מגבלות צפיפות (אלגוריתם)" group renders with five number fields. Saving with T > R should surface the `t_exceeds_r` error.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/SystemSettingsPage.tsx
git commit -m "feat: add density-caps group to system settings UI"
```

---

## Self-Review Notes

- **Spec coverage (Phase 1):** §1 settings → Task 1; §2 bridge → Task 4; §3 model split → Task 2; §4 relaxation → Task 3; §5 tests → Tasks 2, 3, 5.
- **Spec coverage (Phase 2):** P2§1 SolverSettings ceilings + P2§2 solver → Task 6; P2§3 bridge → Task 7; P2§4 per-run schema → Task 8 (+ Task 11 frontend); P2§5 `/algorithm/defaults` → Task 10 (+ Task 11 seed); P2§6 system-settings UI → Task 12; P2§7 validation → Task 8 (job submit) + Task 9 (settings PUT).
- **Type consistency:** `R`, `relax_t_ceiling`, `relax_r_ceiling` (all `int`) named identically across `SolverSettings`, the bridge resolver, `SolverSettingsIn`, the system-setting keys, and the frontend `SolverSettings` type. The `/algorithm/defaults` payload (`{T,R,W}`) matches `AlgorithmDefaults` and the form's seed effect.
- **Invariant `T ≤ R`:** Phase 1 baseline 7=7. Phase 2 enforces it at both write paths (job submit, settings PUT) plus `t_ceiling ≤ r_ceiling` and baseline ≤ own ceiling, preserving `T ≤ R` through relaxation for any admin-chosen values.
- **Settings precedence:** per-run `settings_json` > system setting > dataclass default, implemented once in `resolve_solver_settings` and reused by both the job runner and `/algorithm/defaults`.
