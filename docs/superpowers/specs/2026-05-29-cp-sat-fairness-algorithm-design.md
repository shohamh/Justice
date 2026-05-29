# CP-SAT Fairness Algorithm — Design

**Date:** 2026-05-29
**Status:** Approved (brainstorm 2026-05-29). Builds on Slice 4 (duty assignments, scoring, transparency) from `master`.

## Goal

Implement the OR-Tools CP-SAT fairness algorithm for automated duty assignment, as specified in Section 6 of the main design doc (`2026-05-27-army-duty-management-design.md`). This is the v1.5 algorithm that runs after Slice 4's manual assignment infrastructure is in place.

## Scope

- **Core solver** (`model.py` + `solver.py`) — CP-SAT batch formulation with hard constraints (coverage, exemption, personal constraint, no overlap, K normalised-score variance) and soft objectives (density penalty, min_gap spacing reward).
- **Explainability builder** (`explain.py`) — per-assignment candidate analysis with rejection reasons and global metrics.
- **Reserve selection** (`reserve.py`) — hierarchy-walk outward from primary assignee to find closest substitute.
- **Property-based + golden suite tests** — random feasible populations, determinism, constraint satisfaction.

**Out of this spec:** API endpoint, DB persistence layer, frontend "הרץ אלגוריתם" button, `reserve_assignments` / `assignment_explanations` DB tables and migrations, personal constraints table. These land in a subsequent phase that bridges the pure algorithm to the FastAPI app.

## Architecture

```
app/algorithm/          ← pure module: no imports from app.db, app.routes, app.services
├── __init__.py
├── types.py            ← Dataclasses: SoldierInput, DutyBlock, Assignment, SolverResult, ExplanationData
├── model.py            ← Builds CpModel: variables, hard constraints, soft objective
├── solver.py           ← CpSolver wrapper: time limit, seed, infeasibility relaxation chain
├── reserve.py          ← Hierarchy-walk reserve soldier selection
└── tests/
    ├── __init__.py
    ├── test_solver.py
    └── test_reserve.py
```

### Purity principle

The `algorithm/` package imports only:
- `ortools.sat.python.cp_model`
- Python stdlib (`dataclasses`, `uuid`, `datetime`, `decimal`, `enum`)

No imports from `app.db`, `app.routes`, `app.services`, SQLAlchemy, FastAPI. A separate `app/services/algorithm.py` bridge layer (future phase) feeds DB data into the pure module and persists results.

## Data types (`types.py`)

```python
@dataclass
class SoldierInput:
    id: uuid.UUID
    enrolled_at: date
    cumulative_score: Decimal        # from scoring service
    active_days: int                 # from scoring service
    hierarchy_node_id: uuid.UUID | None
    approved_constraint_dates: list[tuple[date, date]]  # from personal constraints (future)
    exempted_duty_type_ids: set[uuid.UUID]              # pre-resolved by bridge: duty_type_ids this soldier is exempt from

@dataclass
class DutyBlock:
    id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    score_per_day: Decimal

@dataclass
class ExistingAssignment:
    """An already-published assignment touching the planning window (for spacing checks)."""
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    start_date: date
    end_date: date

@dataclass
class SolverSettings:
    K: Decimal = Decimal("8")        # max normalised-score variance
    T: int = 7                       # density soft cap (duty-days per window)
    W: int = 14                      # rolling window length in days
    alpha: Decimal = Decimal("1.0")  # min_gap weight
    beta: Decimal = Decimal("2.0")   # density penalty weight
    time_limit_seconds: int = 30
    seed: int | None = None          # determinism; default = hash of date range

@dataclass
class Assignment:
    duty_id: uuid.UUID
    soldier_id: uuid.UUID

@dataclass
class SolverResult:
    assignments: list[Assignment]
    status: str                      # "OPTIMAL" | "FEASIBLE" | "INFEASIBLE"
    objective_value: float | None
    seed: int
    solver_metrics: dict             # wall_time, conflicts, branches
    relaxed: list[str]               # which relaxations were applied (empty if none)

@dataclass
class CandidateInfo:
    soldier_id: uuid.UUID
    blocked: bool
    blocking_constraints: list[str]  # e.g. ["exemption", "overlap"]
    pre_norm_score: Decimal | None   # None if blocked
    post_norm_score: Decimal | None

@dataclass
class AssignmentExplanation:
    duty_id: uuid.UUID
    assigned_soldier_id: uuid.UUID
    candidates: list[CandidateInfo]  # all soldiers considered
    tiebreaker_note: str | None      # why this soldier won among unblocked

@dataclass
class ExplanationData:
    per_assignment: list[AssignmentExplanation]
    global_metrics_before: dict      # min_gap, norm_variance
    global_metrics_after: dict
    algorithm_version: str           # e.g. "cp-sat-1.0"
    solver_seed: int
```

## Model formulation (`model.py`)

### Inputs
- `soldiers: list[SoldierInput]`
- `duties: list[DutyBlock]`
- `existing: list[ExistingAssignment]` — assignments touching the planning horizon boundary (for min_gap continuity across batches)
- `settings: SolverSettings`

### Decision variables
- `x[d, s] ∈ {0, 1}` for every (duty, soldier) pair where soldier passes the pre-filter (exemption + personal constraint fast check)
- `min_norm`, `max_norm` — continuous 0..M (large bound)
- `min_gap` — integer 0..W (max window size)
- `excess[w]` — integer 0..W (per window, for piecewise-linear density penalty)

### Pre-filter (domain reduction)
Before adding variables, for each soldier `s` and duty `d`:
- If `d.duty_type_id in s.exempted_duty_type_ids` → skip this pair (exempted)
- If any approved constraint overlaps `[d.start_date, d.end_date]` → skip this pair

These pairs get `x[d,s] = 0` hard-coded (no variable needed). The bridge service layer resolves exemption types → duty type IDs using `exemption_duty_type_map` before passing data to the pure module.

### Hard constraints

1. **Coverage:** `∀ d: sum_s x[d,s] == 1`

2. **No overlap:** For each soldier `s` and each date `t` in the planning horizon:
   `sum_{d: covers(d,t)} x[d,s] ≤ 1`
   Where `covers(d,t)` is true if `d.start_date ≤ t ≤ d.end_date`.

3. **K normalised-score variance:**
   For each soldier `s`:
   `block_score(d) = score_per_day(d) * (d.end_date - d.start_date + 1)`
   `total_score(s) = cum(s) + sum_d block_score(d) * x[d,s]`
   `norm(s) = total_score(s) / active_days(s)`
   Constraints:
   `max_norm ≥ norm(s)` for all s
   `min_norm ≤ norm(s)` for all s
   `max_norm - min_norm ≤ K`

### Soft objective

Two terms:

**Spacing reward:** Maximise `min_gap`, where `min_gap` is the smallest gap (in days) between any soldier's consecutive duty-days, considering both existing assignments and new assignments. `min_gap` is 0 if any soldier has overlapping days.

**Density penalty:** For each soldier `s` and each rolling window `w` of length W:
- Let `density(s,w)` = number of duty-days soldier `s` has in window `w` (from existing + new assignments)
- Penalty = `max(0, density(s,w) - T)^2`, approximated via piecewise-linear slack:
  - `e1 = min(excess, 1)`, cost = 1x
  - `e2 = max(0, min(excess-1, 2))`, cost = 3x  
  - `e3 = max(0, excess-3)`, cost = 5x
  (quadratic approximation by increasing marginal costs)

**Combined objective:**
```
maximise  α * min_gap  -  β * sum_{s,w} density_penalty(s,w)
```

### Solver wrapper (`solver.py`)

```python
def solve(model: CpModel, settings: SolverSettings) -> SolverResult:
```

- Creates `CpSolver` with `max_time_in_seconds` and `random_seed`
- `num_search_workers = 8`
- Calls `solver.Solve(model)`
- Parses response into `SolverResult`

### Infeasibility relaxation chain

If `solver.StatusName()` is `INFEASIBLE`:

1. Increment `K` by 1, log `"relaxed K to {K}"`
2. If still infeasible, increment `T` by 1, log `"relaxed T to {T}"`
3. If still infeasible, return `SolverResult(status="INFEASIBLE")` with a list of duty blocks ordered by fewest eligible soldiers (diagnostic hint for the DM)
4. After each relaxation step, rebuild the model and re-solve

Each relaxation step is capped at 5 iterations (e.g., K += 5, T += 5). If still infeasible, fail.

## Explainability (`explain.py`)

```python
def build_explanations(
    soldiers: list[SoldierInput],
    duties: list[DutyBlock],
    assignments: list[Assignment],
    global_before: dict,
    global_after: dict,
    solver_seed: int,
) -> ExplanationData:
```

For each `(duty → soldier)` in the solution:

1. Collect **all soldiers** as candidates
2. For each candidate, determine if they're blocked by:
   - Exemption (which exemption type)
   - Personal constraint (date range overlap)
   - No-overlap violation (which date)
   - K-variance limit (would push norm beyond K)
3. If blocked: record `blocked=True` and the blocking constraints
4. If not blocked: record pre-solver and post-solver normalised score
5. Among unblocked candidates: record which tiebreaker selected the winner

Global metrics:
- `min_gap` before = min gap considering only existing assignments
- `min_gap` after = min gap after solution
- `norm_variance` before = variance of `cum(s) / active(s)`
- `norm_variance` after = variance of `(cum(s) + add(s)) / active(s)`

## Reserve selection (`reserve.py`)

```python
def select_reserves(
    soldiers: list[SoldierInput],
    duties: list[DutyBlock],
    assignments: list[Assignment],
    hierarchy_parent: dict[uuid.UUID, uuid.UUID | None],          # node_id -> parent_id
    hierarchy_children: dict[uuid.UUID, list[uuid.UUID]],         # node_id -> child_ids
    soldier_node: dict[uuid.UUID, uuid.UUID],                     # soldier_id -> node_id
    node_soldiers: dict[uuid.UUID, list[uuid.UUID]],              # node_id -> soldier_ids
) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:  # (duty_id, primary_id, reserve_id)
```

For each `(duty → soldier)`:

1. Start at the primary soldier's hierarchy node
2. Collect soldiers in the same node (same team/group)
3. If none qualify, move to sibling nodes (same parent), then parent's siblings, etc.
4. At each level, filter by hard constraints (exemption + personal constraint + no overlap for that duty)
5. Pick the first qualifying soldier at the closest level
6. Record `(duty_id, primary_soldier_id, reserve_soldier_id)`

Returns empty list for duties where no reserve can be found (acceptable — some duties have no backup).

## Testing

### Property-based tests (`test_solver.py`)

Using `hypothesis`:

- **`test_hard_constraints_satisfied`**: Generate random feasible populations (5-20 soldiers, 3-10 duties, varied scores/active-days/exemptions). Solve. Assert every hard constraint is satisfied: coverage=1 per duty, no overlap, no exempted assignments, K variance respected.
- **`test_determinism_same_seed`**: Same input + same seed → identical result.
- **`test_determinism_different_seed`**: Same input + different seed → may differ (not asserted, just no crash).
- **`test_more_time_not_worse`**: Short solve (1s) vs longer solve (10s) — longer never has worse objective.
- **`test_infeasibility_relaxation`**: Artificially tight K → solver relaxes and produces feasible solution.
- **`test_empty_duties`**: Empty duty list → empty assignment list.
- **`test_no_eligible_soldiers`**: All soldiers exempted from all duty types → INFEASIBLE.

### Golden suite

2-3 committed synthetic populations (JSON fixtures in `tests/fixtures/`):
- `small_balanced.json`: 10 soldiers, 5 duties, all eligible — expected optimal solution
- `density_stress.json`: 5 soldiers, 15 duties in tight window — exercises density penalty

CI runs the golden suite; metrics must match expected ranges (not exact values, since solver may find alternative optima).

### Reserve tests (`test_reserve.py`)

- `test_walks_hierarchy_outward`: Three-level tree, primary soldier in leaf → reserve found in same node first, then sibling, then parent.
- `test_no_reserve_available`: Soldier is alone in the tree → returns empty.
- `test_skips_blocked_soldiers`: Reserve candidate has exemption → skips to next level.

## Dependencies

Add to `pyproject.toml`:

```
ortools>=9.10
```

Dev dependency:
```
hypothesis>=6.99  (already present)
```

## Out of scope (future phase)

- `app/services/algorithm.py` — bridge: loads data from DB, calls pure module, persists results
- `POST /api/algorithm/run` — API endpoint (DM invokes)
- `reserve_assignments` / `assignment_explanations` DB tables + migrations
- Personal constraints table and approval flow
- Frontend: "הרץ אלגוריתם" button, "?למה קיבלתי" modal
- Online (greedy) mode for ad-hoc duties
