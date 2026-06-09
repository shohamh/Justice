# L1 Effort-Score Objective Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the CP-SAT solver's `score_per_day` min-max objective with an L1 effort-score objective that minimises the sum of absolute deviations from a free target, making עומס רבעוני equal across all soldiers.

**Architecture:** `effort_offset` and `effort_per_milli` are already computed and injected into every `SoldierInput` before the solver runs (by `inject_effort_scores` in `algorithm_bridge.py`) — they are simply never read by `model.py`. The change replaces the `AddDivisionEquality`-based norm objective with a fully linear L1 formulation: one free `target` IntVar and one `dev[si]` IntVar per soldier, minimising `Σ dev[si] + dist_term`. `EFFORT_SCALE` is moved from `effort_score.py` to `types.py` so the algorithm layer can reference it without importing from services.

**Tech Stack:** OR-Tools CP-SAT (`ortools.sat.python.cp_model`), Python 3.13, pytest, uv

---

## File Map

| File | Change |
|---|---|
| `app/algorithm/types.py` | Add `EFFORT_SCALE = 1_000_000_000` constant |
| `app/services/effort_score.py` | Import `EFFORT_SCALE` from `app.algorithm.types` (remove local definition) |
| `app/algorithm/model.py` | Replace norm/division objective with L1 effort objective |
| `app/algorithm/tests/test_solver.py` | Add `test_effort_objective_l1_prefers_lower_effort_over_lower_score_per_day` |

No changes to: `solver.py`, `reserve.py`, `explain.py`, `diagnose.py`, `algorithm_bridge.py`, any route or service code.

---

## Task 1: Move EFFORT_SCALE to types.py

**Files:**
- Modify: `app/algorithm/types.py`
- Modify: `app/services/effort_score.py`

- [ ] **Step 1: Add EFFORT_SCALE to types.py**

Open `backend/app/algorithm/types.py`. After the imports block (after line 10, before the first `@dataclass`), add:

```python
# Scale factor for converting Decimal effort scores to CP-SAT integers.
# Imported by app/algorithm/model.py and app/services/effort_score.py.
EFFORT_SCALE = 1_000_000_000
```

- [ ] **Step 2: Update effort_score.py to import EFFORT_SCALE**

Open `backend/app/services/effort_score.py`. Replace the existing definition:

```python
# Scale factor for converting Decimal effort scores to CP-SAT integers.
# effort_offset = int(effort_score × EFFORT_SCALE)
# effort_per_milli = int(C_over_D / unit_score_milli × EFFORT_SCALE)
EFFORT_SCALE = 1_000_000_000  # 10^9
```

with:

```python
from app.algorithm.types import EFFORT_SCALE
```

- [ ] **Step 3: Run the scoring and effort tests to confirm nothing broke**

```
cd backend && uv run pytest app/algorithm/tests/ tests/unit/test_scoring_service.py tests/test_model_effort.py -q --no-header
```

Expected: all pass, zero failures.

- [ ] **Step 4: Commit**

```
git add backend/app/algorithm/types.py backend/app/services/effort_score.py
git commit -m "refactor: move EFFORT_SCALE to algorithm/types.py"
```

---

## Task 2: Write the failing test

**Files:**
- Modify: `app/algorithm/tests/test_solver.py`

- [ ] **Step 1: Add the failing test**

Open `backend/app/algorithm/tests/test_solver.py`. Add this import at the top with the existing imports:

```python
from app.algorithm.types import EFFORT_SCALE
```

Then append this test at the end of the file:

```python
def test_effort_objective_l1_prefers_lower_effort_over_lower_score_per_day() -> None:
    """The L1 effort objective should assign the duty to the soldier with lower
    historical effort score (low_effort), even though the old score_per_day
    objective would have preferred high_effort (whose score_per_day is 0).

    Setup:
      - 1 duty: 1 day, score_per_day=1.0  →  _block_score = 1 000 milli
      - unit_score_milli = 1 000, C_over_D = 1.0
        → effort_per_milli = EFFORT_SCALE // 1 000 = 1 000 000

      high_effort: cumulative_score=0, active_days=1000 (spd=0.000)
                   effort_offset = 50% × EFFORT_SCALE (high historical load)
      low_effort:  cumulative_score=5, active_days=50  (spd=0.100)
                   effort_offset = 10% × EFFORT_SCALE (low historical load)

    Old score_per_day objective:
      assigning to high_effort → max_norm = (0+1000)/1000 = 1   ← preferred
      assigning to low_effort  → max_norm = (5000+1000)/50 = 120

    New L1 effort objective:
      assigning to high_effort → efforts {1 500M, 100M} → total dev = 1 400M
      assigning to low_effort  → efforts {500M, 1 100M} → total dev =   600M ← preferred
    """
    dt = uuid4()
    loc = uuid4()
    effort_per_milli = EFFORT_SCALE // 1000  # = 1_000_000

    high_effort = uuid4()
    low_effort = uuid4()

    soldiers = [
        SoldierInput(
            id=high_effort,
            enrolled_at=date(2026, 1, 1),
            cumulative_score=Decimal("0"),
            active_days=1000,
            effort_offset=int(0.5 * EFFORT_SCALE),
            effort_per_milli=effort_per_milli,
        ),
        SoldierInput(
            id=low_effort,
            enrolled_at=date(2026, 1, 1),
            cumulative_score=Decimal("5"),
            active_days=50,
            effort_offset=int(0.1 * EFFORT_SCALE),
            effort_per_milli=effort_per_milli,
        ),
    ]
    duties = [
        DutyBlock(
            id=uuid4(),
            duty_type_id=dt,
            duty_location_id=loc,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            score_per_day=Decimal("1.00"),
        )
    ]

    result = solve(
        soldiers=soldiers,
        duties=duties,
        existing=[],
        settings=SolverSettings(time_limit_seconds=10),
    )
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1
    assert result.assignments[0].soldier_id == low_effort
```

- [ ] **Step 2: Run the new test and confirm it FAILS**

```
cd backend && uv run pytest app/algorithm/tests/test_solver.py::test_effort_objective_l1_prefers_lower_effort_over_lower_score_per_day -v --no-header
```

Expected: **FAILED** — the old objective assigns to `high_effort` (lower score_per_day), not `low_effort`.

---

## Task 3: Implement the L1 effort objective in model.py

**Files:**
- Modify: `app/algorithm/model.py`

- [ ] **Step 1: Update the import line in model.py**

The current import in `model.py`:
```python
from app.algorithm.types import DutyBlock, ExistingAssignment, SoldierInput, SolverSettings
```

Replace with:
```python
from app.algorithm.types import (
    EFFORT_SCALE,
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverSettings,
)
```

- [ ] **Step 2: Remove the norm-based section and replace with L1 effort**

Find the section starting at the comment `# ── Normalised-score expressions` (around line 114) and ending just before `# Hard constraint: max T duty-days` (around line 165). Replace that entire section:

**Remove** (lines ~114–163):
```python
    # ── Normalised-score expressions ─────────────────────────────────────────
    #
    # norm_s = (cumulative_score * 1000 + new_assignment_score) / active_days
    # ...

    # Eligible-only norms for the "raise the floor" secondary objective.
    # ...
    all_norm_exprs: list[LinearExpr] = []
    eligible_norm_exprs: list[LinearExpr] = []
    # Historical tiebreaker: cost of assigning to a soldier with high spd.
    # ...
    hist_penalty_terms: list = []

    for si, s in enumerate(soldier_list):
        if s.active_days == 0:
            continue

        duties_for_s = soldier_duties.get(si, [])
        block_sum = sum(
            _block_score(duty_list[di]) * x[(di, si)]
            for di in duties_for_s
        )

        base = int(s.cumulative_score * 1000)
        cum_total = base + block_sum
        norm = model.NewIntVar(0, 10_000_000, f"norm_s{si}")
        model.AddDivisionEquality(norm, cum_total, s.active_days)
        all_norm_exprs.append(norm)

        if duties_for_s:
            eligible_norm_exprs.append(norm)

        # hist_milli = score_per_day in milli-units (an integer constant, not a variable)
        hist_milli = int(s.cumulative_score * 1000) // s.active_days
        for di in duties_for_s:
            hist_penalty_terms.append(hist_milli * x[(di, si)])

    max_norm_var = None
    if all_norm_exprs:
        max_norm_var = model.NewIntVar(0, 10_000_000, "max_norm")
        model.AddMaxEquality(max_norm_var, all_norm_exprs)
```

**Replace with:**
```python
    # ── Effort-score expressions (L1 objective) ──────────────────────────────
    #
    # projected_effort[si] = effort_offset[si]
    #                       + effort_per_milli[si] × Σ(_block_score(d) × x[di,si])
    #
    # Fully linear — no AddDivisionEquality — which CP-SAT handles efficiently.
    # effort_offset and effort_per_milli are set by inject_effort_scores() in the
    # bridge before solve() is called.  Both default to 0, giving a degenerate
    # but valid objective that falls back to minimising reserve hierarchy distance.
    #
    # Variable bound: effort_score ∈ [0,1] so effort_offset ∈ [0, EFFORT_SCALE].
    # Max increment = C_over_D × EFFORT_SCALE ≤ EFFORT_SCALE.
    # Therefore projected_effort ∈ [0, 2 × EFFORT_SCALE].

    _EFFORT_BOUND = 2 * EFFORT_SCALE

    dev_vars: list[LinearExpr] = []
    target = model.NewIntVar(0, _EFFORT_BOUND, "effort_target")

    for si, s in enumerate(soldier_list):
        duties_for_s = soldier_duties.get(si, [])

        # Total score (×1000) of duties assigned to this soldier
        block_score_milli_sum = sum(
            _block_score(duty_list[di]) * x[(di, si)]
            for di in duties_for_s
        )  # returns 0 (int) when duties_for_s is empty

        # projected effort score in EFFORT_SCALE units
        effort_expr = s.effort_offset + s.effort_per_milli * block_score_milli_sum

        dev = model.NewIntVar(0, _EFFORT_BOUND, f"dev_s{si}")
        model.Add(dev >= effort_expr - target)
        model.Add(dev >= target - effort_expr)
        dev_vars.append(dev)
```

- [ ] **Step 3: Replace the fairness objective section**

Find the section starting at `# Soft objective: hierarchy proximity` down to the end of `build_model` (around lines 229–276). Keep the reserve proximity block unchanged; only replace the final objective block.

The reserve proximity block (keep as-is):
```python
    # Soft objective: hierarchy proximity for reserve blocks
    reserve_dist_terms: list = []
    if reserve_dist is not None:
        gamma_int = int(settings.reserve_hierarchy_weight * 1000)
        for (di, si), var in x.items():
            if duty_list[di].is_reserve:
                dist = reserve_dist.get((di, si), 10)
                reserve_dist_terms.append(gamma_int * dist * var)
```

**Remove** the entire `# ── Fairness objective` block (lines ~237–275):
```python
    # ── Fairness objective ──────────────────────────────────────────────────
    #
    # Fairness goal: all soldiers converge toward the same score_per_day
    # ...

    alpha_int = int(settings.alpha * 1000)
    dist_term = sum(reserve_dist_terms) if reserve_dist_terms else 0
    hist_penalty = sum(hist_penalty_terms) if hist_penalty_terms else 0

    if max_norm_var is not None and alpha_int > 0:
        min_term = 0
        if len(eligible_norm_exprs) > 1:
            min_norm_var = model.NewIntVar(0, 10_000_000, "min_norm_eligible")
            model.AddMinEquality(min_norm_var, eligible_norm_exprs)
            min_term = min_norm_var

        model.Maximize(-alpha_int * max_norm_var + min_term - hist_penalty - dist_term)
    else:
        model.Maximize(-dist_term)
```

**Replace with:**
```python
    # ── Fairness objective (L1 minimise effort variance) ─────────────────────
    #
    # Minimise the sum of absolute deviations of projected effort scores from a
    # free target variable.  The solver drives target to the median of projected
    # efforts.  O(n) auxiliary variables — scales to 5 000+ soldiers.
    #
    # Secondary: reserve hierarchy proximity (dist_term) acts as tiebreaker.
    # ─────────────────────────────────────────────────────────────────────────

    dist_term = sum(reserve_dist_terms) if reserve_dist_terms else 0

    if dev_vars:
        model.Minimize(sum(dev_vars) + dist_term)
    else:
        model.Minimize(dist_term if reserve_dist_terms else 0)
```

- [ ] **Step 4: Run the new test — it should now PASS**

```
cd backend && uv run pytest app/algorithm/tests/test_solver.py::test_effort_objective_l1_prefers_lower_effort_over_lower_score_per_day -v --no-header
```

Expected: **PASSED**

- [ ] **Step 5: Run the full algorithm test suite**

```
cd backend && uv run pytest app/algorithm/tests/ -q --no-header
```

Expected: all pass. Note — `test_solve_determinism` checks `r1.objective_value == r2.objective_value`; this should pass since the new objective is also deterministic given the same seed. Golden fixture tests only check structural correctness (coverage, no overlaps) and remain valid.

- [ ] **Step 6: Run the full backend test suite**

```
cd backend && uv run pytest -q --no-header
```

Expected: all pass.

- [ ] **Step 7: Commit**

```
git add backend/app/algorithm/model.py backend/app/algorithm/tests/test_solver.py
git commit -m "feat: replace score_per_day min-max with L1 effort-score objective in CP-SAT solver"
```

---

## Notes

- `SolverSettings.alpha` is now unused by the model. It is left in place (backward-compatible) and can be repurposed or removed in a future cleanup.
- The `_dict_to_soldier` helper in `test_solver.py` does not read `effort_offset`/`effort_per_milli` from JSON fixtures. Fixture soldiers therefore use the default values of 0 for both fields, which means the golden fixture tests exercise the "no effort history" path (effort is degenerate → dist_term drives assignment). This is correct and intentional.
- `explain.py` and `reserve.py` do not reference the objective — they are unaffected.
