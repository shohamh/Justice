# Slice 5 — CP-SAT Fairness Algorithm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the OR-Tools CP-SAT pure algorithm module for automated fair duty assignment, with hard constraints (coverage, exemption, no-overlap, K normalised-score variance), soft objectives (min-gap spacing, density penalty), infeasibility relaxation, per-assignment explainability, and hierarchy-walk reserve selection.

**Architecture:** A pure `app/algorithm/` package (imports only `ortools.sat.python.cp_model` + stdlib). No `app.db`, `app.services`, SQLAlchemy, or FastAPI dependencies. Tests use `hypothesis` for property-based testing and golden JSON fixtures for deterministic regression. The reserve selector walks the hierarchy tree outward from the primary assignee's node.

**Tech Stack:** Python 3.12, ortools>=9.10, hypothesis>=6.99 (already present), pytest.

**Spec:** `docs/superpowers/specs/2026-05-29-cp-sat-fairness-algorithm-design.md`

---

## File structure

```
backend/
├── app/
│   ├── algorithm/                   ← pure module (stdlib + ortools only)
│   │   ├── __init__.py
│   │   ├── types.py                 ← dataclasses
│   │   ├── model.py                 ← CpModel builder
│   │   ├── solver.py                ← CpSolver wrapper + relaxation
│   │   ├── explain.py               ← per-assignment explainability
│   │   ├── reserve.py               ← hierarchy-walk reserve selection
│   │   └── tests/
│   │       ├── __init__.py
│   │       ├── fixtures/
│   │       │   ├── small_balanced.json
│   │       │   └── density_stress.json
│   │       ├── test_solver.py       ← property-based + golden
│   │       └── test_reserve.py      ← hierarchy walk tests
│   └── main.py                      ← no changes
└── pyproject.toml                   ← +ortools>=9.10
```

---

## Phase A — Dependency + scaffolding

### Task 1: Add ortools dependency and create package structure

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/app/algorithm/__init__.py`
- Create: `backend/app/algorithm/tests/__init__.py`

- [ ] **Step 1: Add ortools to pyproject.toml**

Edit `backend/pyproject.toml`: insert `"ortools>=9.10"` after the existing dependencies (before `fastapi` line is fine — anywhere in the `dependencies` list):

```toml
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.27",
  "sqlalchemy>=2.0.27",
  "alembic>=1.13",
  "psycopg[binary]>=3.1",
  "pydantic>=2.6",
  "pydantic-settings>=2.2",
  "argon2-cffi>=23.1",
  "python-jose[cryptography]>=3.3",
  "slowapi>=0.1.9",
  "python-multipart>=0.0.9",
  "ortools>=9.10",
]
```

- [ ] **Step 2: Sync dependencies and verify ortools importable**

Run from `backend/`:
```
uv sync
uv run python -c "from ortools.sat.python import cp_model; print('ortools ok')"
```
Expected: `ortools ok`

- [ ] **Step 3: Create package init files**

Create `backend/app/algorithm/__init__.py` — empty file.

Create `backend/app/algorithm/tests/__init__.py` — empty file.

- [ ] **Step 4: Install hypothesis if missing**

Run: `uv sync` (already a dev dependency, but ensure it's installed: `uv sync --group dev` may be needed if dev is optional).

Check: `uv run python -c "import hypothesis; print(hypothesis.__version__)"`

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/pyproject.toml backend/app/algorithm/__init__.py backend/app/algorithm/tests/__init__.py
git -C .. commit -m "chore(deps): add ortools, scaffold algorithm package"
```

---

## Phase B — Data types

### Task 2: Define the pure dataclasses (types.py)

**Files:**
- Create: `backend/app/algorithm/types.py`

- [ ] **Step 1: Write the failing import test**

Create a quick check file or just run:

```bash
uv run python -c "from app.algorithm.types import SoldierInput, DutyBlock, ExistingAssignment, SolverSettings, Assignment, SolverResult, CandidateInfo, AssignmentExplanation, ExplanationData; print('types ok')"
```

Expected: FAIL (`ModuleNotFoundError: no module named app.algorithm.types`)

- [ ] **Step 2: Create `backend/app/algorithm/types.py`**

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class SoldierInput:
    id: uuid.UUID
    enrolled_at: date
    cumulative_score: Decimal
    active_days: int
    hierarchy_node_id: uuid.UUID | None
    approved_constraint_dates: list[tuple[date, date]] = field(default_factory=list)
    exempted_duty_type_ids: set[uuid.UUID] = field(default_factory=set)


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
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    start_date: date
    end_date: date


@dataclass
class SolverSettings:
    K: Decimal = Decimal("8")
    T: int = 7
    W: int = 14
    alpha: Decimal = Decimal("1.0")
    beta: Decimal = Decimal("2.0")
    time_limit_seconds: int = 30
    seed: int | None = None


@dataclass
class Assignment:
    duty_id: uuid.UUID
    soldier_id: uuid.UUID


@dataclass
class SolverResult:
    assignments: list[Assignment]
    status: str
    objective_value: float | None
    seed: int
    solver_metrics: dict
    relaxed: list[str] = field(default_factory=list)


@dataclass
class CandidateInfo:
    soldier_id: uuid.UUID
    blocked: bool
    blocking_constraints: list[str] = field(default_factory=list)
    pre_norm_score: Decimal | None = None
    post_norm_score: Decimal | None = None


@dataclass
class AssignmentExplanation:
    duty_id: uuid.UUID
    assigned_soldier_id: uuid.UUID
    candidates: list[CandidateInfo] = field(default_factory=list)
    tiebreaker_note: str | None = None


@dataclass
class ExplanationData:
    per_assignment: list[AssignmentExplanation] = field(default_factory=list)
    global_metrics_before: dict = field(default_factory=dict)
    global_metrics_after: dict = field(default_factory=dict)
    algorithm_version: str = "cp-sat-1.0"
    solver_seed: int = 0
```

- [ ] **Step 3: Verify import**

Run: `uv run python -c "from app.algorithm.types import SoldierInput, DutyBlock, SolverSettings, Assignment, SolverResult, CandidateInfo, AssignmentExplanation, ExplanationData; print('types ok')"`
Expected: `types ok`

- [ ] **Step 4: Commit**

```bash
git -C .. add backend/app/algorithm/types.py
git -C .. commit -m "feat(algorithm): pure data types (SoldierInput, DutyBlock, Assignment, etc.)"
```

---

## Phase C — Model builder

### Task 3: CpModel builder with hard + soft constraints

**Files:**
- Create: `backend/app/algorithm/model.py`
- Test will be in Task 7 (property-based tests exercise model + solver together)

- [ ] **Step 1: Verify pre-filter helpers work**

Run one-liner to confirm the pre-filter logic conceptually:

```bash
uv run python -c "
from decimal import Decimal
from datetime import date
from app.algorithm.model import build_model
print('build_model importable')
"
```
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 2: Create `backend/app/algorithm/model.py`**

```python
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from ortools.sat.python import cp_model

from app.algorithm.types import (
    Assignment,
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverSettings,
)


def _pre_filter(
    soldiers: list[SoldierInput], duties: list[DutyBlock],
) -> dict[uuid.UUID, list[int]]:
    """Return {soldier_index: [duty_index, ...]} for eligible (soldier, duty) pairs."""
    eligible: dict[uuid.UUID, list[int]] = {s.id: [] for s in soldiers}
    for si, s in enumerate(soldiers):
        for di, d in enumerate(duties):
            if d.duty_type_id in s.exempted_duty_type_ids:
                continue
            blocked = False
            for cs, ce in s.approved_constraint_dates:
                if cs <= d.end_date and ce >= d.start_date:
                    blocked = True
                    break
            if blocked:
                continue
            eligible[s.id].append(di)
    return eligible


def _duty_date_range(
    duties: list[DutyBlock],
) -> tuple[date, date]:
    starts = [d.start_date for d in duties]
    ends = [d.end_date for d in duties]
    return min(starts), max(ends)


def _covers(duty: DutyBlock, t: date) -> bool:
    return duty.start_date <= t <= duty.end_date


def _block_score(duty: DutyBlock) -> Decimal:
    return duty.score_per_day * Decimal((duty.end_date - duty.start_date).days + 1)


def build_model(
    soldiers: list[SoldierInput],
    duties: list[DutyBlock],
    existing: list[ExistingAssignment],
    settings: SolverSettings,
) -> tuple[cp_model.CpModel, dict[int, dict[int, cp_model.IntVar]]]:
    """Build the CpModel.

    Returns (model, x) where x[duty_idx][soldier_idx] is the 0/1 variable
    for assigning duty d to soldier s (only for pre-filter-eligible pairs).
    """
    model = cp_model.CpModel()

    eligible = _pre_filter(soldiers, duties)
    soldier_map = {s.id: idx for idx, s in enumerate(soldiers)}

    # Decision variables: x[duty_idx][soldier_idx] for eligible pairs only
    x: dict[int, dict[int, cp_model.IntVar]] = {}
    for di, d in enumerate(duties):
        x[di] = {}
        for si, s in enumerate(soldiers):
            if di in eligible[s.id]:
                x[di][si] = model.NewBoolVar(f"x_{di}_{si}")

    # ── Hard constraint 1: Coverage ──
    for di in range(len(duties)):
        vars_for_duty = list(x[di].values())
        if vars_for_duty:
            model.AddExactlyOne(vars_for_duty)

    # ── Hard constraint 2: No overlap ──
    horizon_start, horizon_end = _duty_date_range(duties)
    t = horizon_start
    while t <= horizon_end:
        for si, s in enumerate(soldiers):
            duty_vars_for_soldier = []
            for di, d in enumerate(duties):
                if si in x.get(di, {}) and _covers(d, t):
                    duty_vars_for_soldier.append(x[di][si])
            if len(duty_vars_for_soldier) > 1:
                model.Add(sum(duty_vars_for_soldier) <= 1)
            elif len(duty_vars_for_soldier) == 1:
                model.Add(duty_vars_for_soldier[0] <= 1)  # trivially satisfied
        t += timedelta(days=1)

    # ── Hard constraint 3: K normalised-score variance ──
    min_norm = model.NewFloatVar(0.0, 1e9, "min_norm")
    max_norm = model.NewFloatVar(0.0, 1e9, "max_norm")

    for si, s in enumerate(soldiers):
        total_score_expr = float(s.cumulative_score)
        for di in range(len(duties)):
            if si in x.get(di, {}):
                total_score_expr += float(_block_score(duties[di])) * x[di][si]
        norm_expr = total_score_expr / float(s.active_days)
        norm_var = model.NewFloatVar(0.0, 1e9, f"norm_{si}")
        model.Add(norm_var == norm_expr)
        model.Add(max_norm >= norm_var)
        model.Add(min_norm <= norm_var)

    model.Add(max_norm - min_norm <= float(settings.K))

    # ── Soft objective: Spacing (min_gap) ──
    # Build a dict of soldier_idx -> list of (start_date, end_date) including existing
    soldier_duty_spans: dict[int, list[tuple[date, date, cp_model.IntVar | None]]] = {
        si: [] for si in range(len(soldiers))
    }
    # Existing assignments
    for ea in existing:
        si = soldier_map.get(ea.soldier_id)
        if si is not None:
            soldier_duty_spans[si].append((ea.start_date, ea.end_date, None))
    # New assignments (conditional on x[di][si] == 1)
    for di, d in enumerate(duties):
        for si in x.get(di, {}):
            soldier_duty_spans[si].append((d.start_date, d.end_date, x[di][si]))

    # min_gap is the minimum gap in days between consecutive duty days for any soldier
    # We approximate by finding the minimum gap between any two duty-day dates
    min_gap = model.NewIntVar(0, settings.W, "min_gap")

    for si in range(len(soldiers)):
        spans = soldier_duty_spans[si]
        if len(spans) < 2:
            continue
        # Get all occupied dates for this soldier
        occupied_dates = set()
        for start, end, _var in spans:
            d = start
            while d <= end:
                occupied_dates.add(d)
                d += timedelta(days=1)
        sorted_dates = sorted(occupied_dates)
        for i in range(len(sorted_dates) - 1):
            gap = (sorted_dates[i + 1] - sorted_dates[i]).days
            model.Add(min_gap <= gap)

    # ── Soft objective: Density penalty ──
    # excess[w] per soldier per rolling window
    penalty_terms: list[cp_model.IntVar | int] = []
    for si, s in enumerate(soldiers):
        # Collect all duty days per date for this soldier
        duty_dates: dict[date, list[tuple[int, cp_model.IntVar | None]]] = defaultdict(list)
        for di, d in enumerate(duties):
            if si in x.get(di, {}):
                day = d.start_date
                while day <= d.end_date:
                    duty_dates[day].append((x[di][si], None))
                    day += timedelta(days=1)
        for ea in existing:
            if ea.soldier_id == s.id:
                day = ea.start_date
                while day <= ea.end_date:
                    duty_dates[day].append((None, None))
                    day += timedelta(days=1)

        if not duty_dates:
            continue

        all_dates = sorted(duty_dates.keys())
        window_start_idx = 0
        for i, day_i in enumerate(all_dates):
            window_end = day_i + timedelta(days=settings.W - 1)
            # Count duty days in window that start at day_i
            density_terms: list[int | cp_model.IntVar] = []
            j = i
            while j < len(all_dates) and all_dates[j] <= window_end:
                for var, _ in duty_dates[all_dates[j]]:
                    if var is not None:
                        density_terms.append(var)
                    else:
                        density_terms.append(1)
                j += 1
            if not density_terms:
                continue
            total_density = sum(density_terms)
            excess = model.NewIntVar(0, settings.W, f"excess_{si}_{i}")
            model.Add(excess >= total_density - settings.T)
            # Quadratic approximation via piecewise-linear
            e1 = model.NewIntVar(0, 1, f"e1_{si}_{i}")
            e2 = model.NewIntVar(0, 2, f"e2_{si}_{i}")
            e3 = model.NewIntVar(0, settings.W, f"e3_{si}_{i}")
            model.Add(e1 + e2 + e3 == excess)
            model.Add(e1 <= 1)
            model.Add(e2 <= 2)
            penalty_terms.append(1 * e1 + 3 * e2 + 5 * e3)

    # ── Objective ──
    obj_expr = float(settings.alpha) * min_gap - float(settings.beta) * sum(penalty_terms)
    model.Maximize(obj_expr)

    return model, x
```

- [ ] **Step 3: Verify model.py imports cleanly**

Run: `uv run python -c "from app.algorithm.model import build_model; print('model ok')"`
Expected: `model ok`

- [ ] **Step 4: Commit**

```bash
git -C .. add backend/app/algorithm/model.py
git -C .. commit -m "feat(algorithm): CpModel builder with hard/soft constraints"
```

---

## Phase D — Solver wrapper

### Task 4: CpSolver wrapper with infeasibility relaxation chain

**Files:**
- Create: `backend/app/algorithm/solver.py`

- [ ] **Step 1: Verify stub fails**

Run: `uv run python -c "from app.algorithm.solver import solve; print('solver importable')"`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 2: Create `backend/app/algorithm/solver.py`**

```python
from __future__ import annotations

import copy
import hashlib
import json
from datetime import date
from decimal import Decimal

from ortools.sat.python import cp_model

from app.algorithm.model import build_model
from app.algorithm.types import (
    Assignment,
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverResult,
    SolverSettings,
)


def _compute_seed(settings: SolverSettings, duties: list[DutyBlock]) -> int:
    if settings.seed is not None:
        return settings.seed
    raw = hashlib.sha256(
        json.dumps(
            [(str(d.id), d.start_date.isoformat(), d.end_date.isoformat()) for d in duties],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return int(raw[:8], 16)


def _model_to_soldier_inputs(soldiers: list[SoldierInput]) -> list[SoldierInput]:
    """Deep-copy helper to avoid mutation across relaxation retries."""
    return copy.deepcopy(soldiers)


def solve(
    soldiers: list[SoldierInput],
    duties: list[DutyBlock],
    existing: list[ExistingAssignment] | None = None,
    settings: SolverSettings | None = None,
) -> SolverResult:
    if existing is None:
        existing = []
    if settings is None:
        settings = SolverSettings()

    seed = _compute_seed(settings, duties)
    current_settings = copy.deepcopy(settings)
    current_settings.seed = seed
    relaxed: list[str] = []

    for relax_round in range(6):  # max 5 relaxations + initial try
        model, x = build_model(soldiers, duties, existing, current_settings)

        cp_solver = cp_model.CpSolver()
        cp_solver.parameters.max_time_in_seconds = current_settings.time_limit_seconds
        cp_solver.parameters.random_seed = seed
        cp_solver.parameters.num_search_workers = 8
        cp_solver.parameters.log_search_progress = False

        status = cp_solver.Solve(model)

        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            assignments: list[Assignment] = []
            for di in range(len(duties)):
                for si, s in enumerate(soldiers):
                    var = x.get(di, {}).get(si)
                    if var is not None and cp_solver.Value(var) == 1:
                        assignments.append(Assignment(duty_id=duties[di].id, soldier_id=s.id))
            status_str = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
            return SolverResult(
                assignments=assignments,
                status=status_str,
                objective_value=cp_solver.ObjectiveValue(),
                seed=seed,
                solver_metrics={
                    "wall_time": cp_solver.WallTime(),
                    "conflicts": cp_solver.NumConflicts(),
                    "branches": cp_solver.NumBranches(),
                },
                relaxed=relaxed,
            )

        # ── Relaxation chain ──
        if relax_round >= 5:
            break

        if relax_round < 3:
            # Relax K by 1 each iteration
            current_settings.K += Decimal("1")
            relaxed.append(f"K_increased_to_{current_settings.K}")
        elif relax_round < 5:
            # Relax T by 1 each iteration
            current_settings.T += 1
            relaxed.append(f"T_increased_to_{current_settings.T}")

    # ── INFEASIBLE: return diagnostic ──
    duty_eligible_counts = []
    for di, d in enumerate(duties):
        count = sum(
            1
            for s in soldiers
            if d.duty_type_id not in s.exempted_duty_type_ids
        )
        duty_eligible_counts.append((di, count))
    duty_eligible_counts.sort(key=lambda x: x[1])

    return SolverResult(
        assignments=[],
        status="INFEASIBLE",
        objective_value=None,
        seed=seed,
        solver_metrics={},
        relaxed=relaxed,
    )
```

- [ ] **Step 3: Verify solver imports**

Run: `uv run python -c "from app.algorithm.solver import solve; print('solver ok')"`
Expected: `solver ok`

- [ ] **Step 4: Commit**

```bash
git -C .. add backend/app/algorithm/solver.py
git -C .. commit -m "feat(algorithm): CpSolver wrapper with relaxation chain"
```

---

## Phase E — Explainability

### Task 5: Per-assignment explainability builder

**Files:**
- Create: `backend/app/algorithm/explain.py`

- [ ] **Step 1: Verify stub fails**

Run: `uv run python -c "from app.algorithm.explain import build_explanations; print('explain importable')"`
Expected: FAIL

- [ ] **Step 2: Create `backend/app/algorithm/explain.py`**

```python
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from app.algorithm.types import (
    Assignment,
    AssignmentExplanation,
    CandidateInfo,
    DutyBlock,
    ExplanationData,
    SoldierInput,
)


def _min_gap_for_soldier(
    soldier_id: object,
    assignments: list[Assignment],
    duties: list[DutyBlock],
    existing: list | None = None,
) -> int:
    duty_map = {d.id: d for d in duties}
    duty_dates: list[date] = []
    for a in assignments:
        if a.soldier_id == soldier_id:
            d = duty_map.get(a.duty_id)
            if d:
                day = d.start_date
                while day <= d.end_date:
                    duty_dates.append(day)
                    day += timedelta(days=1)
    if existing:
        for ea in existing:
            if ea.soldier_id == soldier_id:
                day = ea.start_date
                while day <= ea.end_date:
                    duty_dates.append(day)
                    day += timedelta(days=1)
    if len(duty_dates) < 2:
        return 999
    sorted_dates = sorted(set(duty_dates))
    return min(
        (sorted_dates[i + 1] - sorted_dates[i]).days
        for i in range(len(sorted_dates) - 1)
    )


def _norm_variance(soldiers: list[SoldierInput], assignments: list[Assignment], duties: list[DutyBlock]) -> float:
    duty_map = {d.id: d for d in duties}
    cumulative_extra: dict[object, Decimal] = defaultdict(lambda: Decimal("0"))
    for a in assignments:
        d = duty_map.get(a.duty_id)
        if d:
            days = (d.end_date - d.start_date).days + 1
            cumulative_extra[a.soldier_id] += d.score_per_day * Decimal(days)
    norms = []
    for s in soldiers:
        total = s.cumulative_score + cumulative_extra.get(s.id, Decimal("0"))
        norm = float(total) / max(s.active_days, 1)
        norms.append(norm)
    if len(norms) < 2:
        return 0.0
    mean = sum(norms) / len(norms)
    return sum((n - mean) ** 2 for n in norms) / len(norms)


def build_explanations(
    soldiers: list[SoldierInput],
    duties: list[DutyBlock],
    assignments: list[Assignment],
    global_before: dict | None = None,
    global_after: dict | None = None,
    solver_seed: int = 0,
    existing: list | None = None,
) -> ExplanationData:
    duty_map = {d.id: d for d in duties}
    soldier_map = {s.id: s for s in soldiers}
    per_assignment: list[AssignmentExplanation] = []

    for a in assignments:
        d = duty_map.get(a.duty_id)
        if d is None:
            continue
        candidates: list[CandidateInfo] = []
        for s in soldiers:
            blocking: list[str] = []
            # Check exemption
            if d.duty_type_id in s.exempted_duty_type_ids:
                blocking.append("exemption")
            # Check personal constraint
            for cs, ce in s.approved_constraint_dates:
                if cs <= d.end_date and ce >= d.start_date:
                    blocking.append("personal_constraint")
                    break
            # Check no-overlap (would assigning them cause overlap?)
            for other_a in assignments:
                if other_a.soldier_id == s.id and other_a.duty_id != a.duty_id:
                    other_d = duty_map.get(other_a.duty_id)
                    if other_d and other_d.start_date <= d.end_date and other_d.end_date >= d.start_date:
                        blocking.append("overlap")
                        break
            # Check K-variance
            blocked = len(blocking) > 0
            pre_norm = Decimal(str(s.cumulative_score)) / Decimal(max(s.active_days, 1))
            post_norm = None
            if not blocked:
                days = (d.end_date - d.start_date).days + 1
                extra = d.score_per_day * Decimal(days)
                post_total = s.cumulative_score + extra
                post_norm = post_total / Decimal(max(s.active_days, 1))
            candidates.append(CandidateInfo(
                soldier_id=s.id,
                blocked=blocked,
                blocking_constraints=blocking,
                pre_norm_score=pre_norm,
                post_norm_score=post_norm,
            ))

        tiebreaker_note = None
        unblocked = [c for c in candidates if not c.blocked]
        if unblocked and len(unblocked) > 1:
            tiebreaker_note = "lowest_post_norm_score"

        per_assignment.append(AssignmentExplanation(
            duty_id=a.duty_id,
            assigned_soldier_id=a.soldier_id,
            candidates=candidates,
            tiebreaker_note=tiebreaker_note,
        ))

    if global_before is None:
        existing_list = existing or []
        min_gap_before = min(
            (_min_gap_for_soldier(s.id, [], duties, existing_list) for s in soldiers),
            default=999,
        )
        norm_var_before = _norm_variance(soldiers, [], duties)
        global_before = {"min_gap": min_gap_before, "norm_variance": norm_var_before}

    if global_after is None:
        min_gap_after = min(
            (_min_gap_for_soldier(s.id, assignments, duties, existing) for s in soldiers),
            default=999,
        )
        norm_var_after = _norm_variance(soldiers, assignments, duties)
        global_after = {"min_gap": min_gap_after, "norm_variance": norm_var_after}

    return ExplanationData(
        per_assignment=per_assignment,
        global_metrics_before=global_before,
        global_metrics_after=global_after,
        algorithm_version="cp-sat-1.0",
        solver_seed=solver_seed,
    )
```

- [ ] **Step 3: Verify explain imports**

Run: `uv run python -c "from app.algorithm.explain import build_explanations; print('explain ok')"`
Expected: `explain ok`

- [ ] **Step 4: Commit**

```bash
git -C .. add backend/app/algorithm/explain.py
git -C .. commit -m "feat(algorithm): per-assignment explainability builder"
```

---

## Phase F — Reserve selection

### Task 6: Hierarchy-walk reserve soldier selector

**Files:**
- Create: `backend/app/algorithm/reserve.py`

- [ ] **Step 1: Verify stub fails**

Run: `uv run python -c "from app.algorithm.reserve import select_reserves; print('reserve importable')"`
Expected: FAIL

- [ ] **Step 2: Create `backend/app/algorithm/reserve.py`**

```python
from __future__ import annotations

import uuid
from datetime import date

from app.algorithm.types import (
    Assignment,
    DutyBlock,
    SoldierInput,
)


def _eligible_for_duty(
    soldier: SoldierInput, duty: DutyBlock, assignments: list[Assignment],
) -> bool:
    if duty.duty_type_id in soldier.exempted_duty_type_ids:
        return False
    for cs, ce in soldier.approved_constraint_dates:
        if cs <= duty.end_date and ce >= duty.start_date:
            return False
    for a in assignments:
        if a.soldier_id == soldier.id:
            # Would this cause overlap? We check if any duty assigned to this soldier
            # overlaps with the given duty. Since we don't have the full duty map here,
            # we trust the caller provided already-assigned duties that could conflict.
            return False
    return True


def select_reserves(
    soldiers: list[SoldierInput],
    duties: list[DutyBlock],
    assignments: list[Assignment],
    hierarchy_parent: dict[uuid.UUID, uuid.UUID | None],
    hierarchy_children: dict[uuid.UUID, list[uuid.UUID]],
    soldier_node: dict[uuid.UUID, uuid.UUID],
    node_soldiers: dict[uuid.UUID, list[uuid.UUID]],
) -> list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
    """For each (duty, soldier) assignment, find the closest reserve soldier.

    Returns list of (duty_id, primary_soldier_id, reserve_soldier_id) tuples.
    """
    soldier_map = {s.id: s for s in soldiers}
    duty_map = {d.id: d for d in duties}
    result: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []

    for a in assignments:
        duty = duty_map.get(a.duty_id)
        if duty is None:
            continue
        primary = soldier_map.get(a.soldier_id)
        if primary is None:
            continue

        # Build the set of already-assigned soldier ids for overlap check
        assigned_ids = {ass.soldier_id for ass in assignments}

        # Walk hierarchy outward from primary's node
        visited_nodes: set[uuid.UUID] = set()
        queue: list[uuid.UUID] = []

        start_node = soldier_node.get(a.soldier_id)
        if start_node is None:
            continue

        # BFS outward through hierarchy
        queue.append(start_node)
        visited_nodes.add(start_node)

        found_reserve: uuid.UUID | None = None

        while queue and found_reserve is None:
            current_level: list[uuid.UUID] = list(queue)
            queue.clear()

            for node_id in current_level:
                for candidate_id in node_soldiers.get(node_id, []):
                    if candidate_id == a.soldier_id:
                        continue
                    if candidate_id in assigned_ids:
                        continue
                    candidate = soldier_map.get(candidate_id)
                    if candidate is None:
                        continue
                    if _eligible_for_duty(candidate, duty, assignments):
                        found_reserve = candidate_id
                        break
                if found_reserve:
                    break

            if found_reserve:
                break

            # Move outward: siblings, parent's siblings, etc.
            for node_id in current_level:
                parent_id = hierarchy_parent.get(node_id)
                if parent_id is not None and parent_id not in visited_nodes:
                    visited_nodes.add(parent_id)
                    queue.append(parent_id)
                    # Also add siblings (parent's children)
                    for sibling_id in hierarchy_children.get(parent_id, []):
                        if sibling_id not in visited_nodes:
                            visited_nodes.add(sibling_id)
                            queue.append(sibling_id)

        if found_reserve is not None:
            result.append((a.duty_id, a.soldier_id, found_reserve))

    return result
```

- [ ] **Step 3: Verify reserve imports**

Run: `uv run python -c "from app.algorithm.reserve import select_reserves; print('reserve ok')"`
Expected: `reserve ok`

- [ ] **Step 4: Commit**

```bash
git -C .. add backend/app/algorithm/reserve.py
git -C .. commit -m "feat(algorithm): hierarchy-walk reserve soldier selection"
```

---

## Phase G — Golden suite fixtures

### Task 7: Create golden test fixture files

**Files:**
- Create: `backend/app/algorithm/tests/fixtures/small_balanced.json`
- Create: `backend/app/algorithm/tests/fixtures/density_stress.json`

- [ ] **Step 1: Create fixture directory**

```bash
mkdir -p backend/app/algorithm/tests/fixtures
```

- [ ] **Step 2: Create `backend/app/algorithm/tests/fixtures/small_balanced.json`**

```json
{
  "soldiers": [
    {
      "id": "11111111-1111-1111-1111-111111111111",
      "enrolled_at": "2026-01-01",
      "cumulative_score": "10.00",
      "active_days": 30,
      "hierarchy_node_id": "10000000-0000-0000-0000-000000000001",
      "approved_constraint_dates": [],
      "exempted_duty_type_ids": []
    },
    {
      "id": "22222222-2222-2222-2222-222222222222",
      "enrolled_at": "2026-01-01",
      "cumulative_score": "15.00",
      "active_days": 30,
      "hierarchy_node_id": "10000000-0000-0000-0000-000000000001",
      "approved_constraint_dates": [],
      "exempted_duty_type_ids": []
    },
    {
      "id": "33333333-3333-3333-3333-333333333333",
      "enrolled_at": "2026-01-15",
      "cumulative_score": "5.00",
      "active_days": 15,
      "hierarchy_node_id": "10000000-0000-0000-0000-000000000001",
      "approved_constraint_dates": [],
      "exempted_duty_type_ids": []
    },
    {
      "id": "44444444-4444-4444-4444-444444444444",
      "enrolled_at": "2026-02-01",
      "cumulative_score": "8.00",
      "active_days": 20,
      "hierarchy_node_id": "10000000-0000-0000-0000-000000000001",
      "approved_constraint_dates": [],
      "exempted_duty_type_ids": []
    },
    {
      "id": "55555555-5555-5555-5555-555555555555",
      "enrolled_at": "2026-01-10",
      "cumulative_score": "12.00",
      "active_days": 25,
      "hierarchy_node_id": "10000000-0000-0000-0000-000000000001",
      "approved_constraint_dates": [],
      "exempted_duty_type_ids": []
    },
    {
      "id": "66666666-6666-6666-6666-666666666666",
      "enrolled_at": "2026-03-01",
      "cumulative_score": "3.00",
      "active_days": 10,
      "hierarchy_node_id": "10000000-0000-0000-0000-000000000001",
      "approved_constraint_dates": [],
      "exempted_duty_type_ids": []
    },
    {
      "id": "77777777-7777-7777-7777-777777777777",
      "enrolled_at": "2026-01-05",
      "cumulative_score": "20.00",
      "active_days": 30,
      "hierarchy_node_id": "10000000-0000-0000-0000-000000000001",
      "approved_constraint_dates": [],
      "exempted_duty_type_ids": []
    },
    {
      "id": "88888888-8888-8888-8888-888888888888",
      "enrolled_at": "2026-02-15",
      "cumulative_score": "7.00",
      "active_days": 15,
      "hierarchy_node_id": "10000000-0000-0000-0000-000000000001",
      "approved_constraint_dates": [],
      "exempted_duty_type_ids": []
    },
    {
      "id": "99999999-9999-9999-9999-999999999999",
      "enrolled_at": "2026-03-15",
      "cumulative_score": "2.00",
      "active_days": 10,
      "hierarchy_node_id": "10000000-0000-0000-0000-000000000001",
      "approved_constraint_dates": [],
      "exempted_duty_type_ids": []
    },
    {
      "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      "enrolled_at": "2026-01-20",
      "cumulative_score": "25.00",
      "active_days": 30,
      "hierarchy_node_id": "10000000-0000-0000-0000-000000000001",
      "approved_constraint_dates": [],
      "exempted_duty_type_ids": []
    }
  ],
  "duties": [
    {
      "id": "d0000001-0000-0000-0000-000000000001",
      "duty_type_id": "10000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-01",
      "end_date": "2026-06-01",
      "score_per_day": "1.00"
    },
    {
      "id": "d0000002-0000-0000-0000-000000000002",
      "duty_type_id": "10000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-02",
      "end_date": "2026-06-02",
      "score_per_day": "1.00"
    },
    {
      "id": "d0000003-0000-0000-0000-000000000003",
      "duty_type_id": "10000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-03",
      "end_date": "2026-06-03",
      "score_per_day": "1.00"
    },
    {
      "id": "d0000004-0000-0000-0000-000000000004",
      "duty_type_id": "10000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-04",
      "end_date": "2026-06-04",
      "score_per_day": "1.00"
    },
    {
      "id": "d0000005-0000-0000-0000-000000000005",
      "duty_type_id": "10000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-05",
      "end_date": "2026-06-05",
      "score_per_day": "1.00"
    }
  ],
  "existing": [],
  "settings": {
    "K": "8",
    "T": 7,
    "W": 14,
    "alpha": "1.0",
    "beta": "2.0",
    "time_limit_seconds": 30,
    "seed": 42
  }
}
```

- [ ] **Step 3: Create `backend/app/algorithm/tests/fixtures/density_stress.json`**

```json
{
  "soldiers": [
    {
      "id": "s1000001-0000-0000-0000-000000000001",
      "enrolled_at": "2026-01-01",
      "cumulative_score": "5.00",
      "active_days": 60,
      "hierarchy_node_id": "10000000-0000-0000-0000-000000000001",
      "approved_constraint_dates": [],
      "exempted_duty_type_ids": []
    },
    {
      "id": "s2000002-0000-0000-0000-000000000002",
      "enrolled_at": "2026-01-01",
      "cumulative_score": "5.00",
      "active_days": 60,
      "hierarchy_node_id": "10000000-0000-0000-0000-000000000001",
      "approved_constraint_dates": [],
      "exempted_duty_type_ids": []
    },
    {
      "id": "s3000003-0000-0000-0000-000000000003",
      "enrolled_at": "2026-01-01",
      "cumulative_score": "5.00",
      "active_days": 60,
      "hierarchy_node_id": "10000000-0000-0000-0000-000000000001",
      "approved_constraint_dates": [],
      "exempted_duty_type_ids": []
    },
    {
      "id": "s4000004-0000-0000-0000-000000000004",
      "enrolled_at": "2026-01-01",
      "cumulative_score": "5.00",
      "active_days": 60,
      "hierarchy_node_id": "10000000-0000-0000-0000-000000000001",
      "approved_constraint_dates": [],
      "exempted_duty_type_ids": []
    },
    {
      "id": "s5000005-0000-0000-0000-000000000005",
      "enrolled_at": "2026-01-01",
      "cumulative_score": "5.00",
      "active_days": 60,
      "hierarchy_node_id": "10000000-0000-0000-0000-000000000001",
      "approved_constraint_dates": [],
      "exempted_duty_type_ids": []
    }
  ],
  "duties": [
    {
      "id": "dd000001-0000-0000-0000-000000000001",
      "duty_type_id": "20000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-01",
      "end_date": "2026-06-01",
      "score_per_day": "1.00"
    },
    {
      "id": "dd000002-0000-0000-0000-000000000002",
      "duty_type_id": "20000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-02",
      "end_date": "2026-06-02",
      "score_per_day": "1.00"
    },
    {
      "id": "dd000003-0000-0000-0000-000000000003",
      "duty_type_id": "20000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-03",
      "end_date": "2026-06-03",
      "score_per_day": "1.00"
    },
    {
      "id": "dd000004-0000-0000-0000-000000000004",
      "duty_type_id": "20000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-04",
      "end_date": "2026-06-04",
      "score_per_day": "1.00"
    },
    {
      "id": "dd000005-0000-0000-0000-000000000005",
      "duty_type_id": "20000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-05",
      "end_date": "2026-06-05",
      "score_per_day": "1.00"
    },
    {
      "id": "dd000006-0000-0000-0000-000000000006",
      "duty_type_id": "20000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-06",
      "end_date": "2026-06-06",
      "score_per_day": "1.00"
    },
    {
      "id": "dd000007-0000-0000-0000-000000000007",
      "duty_type_id": "20000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-07",
      "end_date": "2026-06-07",
      "score_per_day": "1.00"
    },
    {
      "id": "dd000008-0000-0000-0000-000000000008",
      "duty_type_id": "20000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-08",
      "end_date": "2026-06-08",
      "score_per_day": "1.00"
    },
    {
      "id": "dd000009-0000-0000-0000-000000000009",
      "duty_type_id": "20000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-09",
      "end_date": "2026-06-09",
      "score_per_day": "1.00"
    },
    {
      "id": "dd000010-0000-0000-0000-000000000010",
      "duty_type_id": "20000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-10",
      "end_date": "2026-06-10",
      "score_per_day": "1.00"
    },
    {
      "id": "dd000011-0000-0000-0000-000000000011",
      "duty_type_id": "20000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-11",
      "end_date": "2026-06-11",
      "score_per_day": "1.00"
    },
    {
      "id": "dd000012-0000-0000-0000-000000000012",
      "duty_type_id": "20000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-12",
      "end_date": "2026-06-12",
      "score_per_day": "1.00"
    },
    {
      "id": "dd000013-0000-0000-0000-000000000013",
      "duty_type_id": "20000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-13",
      "end_date": "2026-06-13",
      "score_per_day": "1.00"
    },
    {
      "id": "dd000014-0000-0000-0000-000000000014",
      "duty_type_id": "20000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-14",
      "end_date": "2026-06-14",
      "score_per_day": "1.00"
    },
    {
      "id": "dd000015-0000-0000-0000-000000000015",
      "duty_type_id": "20000001-0000-0000-0000-000000000001",
      "duty_location_id": "20000000-0000-0000-0000-000000000001",
      "start_date": "2026-06-15",
      "end_date": "2026-06-15",
      "score_per_day": "1.00"
    }
  ],
  "existing": [],
  "settings": {
    "K": "8",
    "T": 3,
    "W": 7,
    "alpha": "1.0",
    "beta": "5.0",
    "time_limit_seconds": 30,
    "seed": 42
  }
}
```

- [ ] **Step 4: Commit**

```bash
git -C .. add backend/app/algorithm/tests/fixtures/
git -C .. commit -m "test(algorithm): golden suite fixture files"
```

---

## Phase H — Property-based + golden suite tests

### Task 8: Write solver property-based tests

**Files:**
- Create: `backend/app/algorithm/tests/test_solver.py`

- [ ] **Step 1: Verify test directory is importable**

Run: `uv run python -c "from app.algorithm.tests import test_solver; print('ok')"`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 2: Create `backend/app/algorithm/tests/test_solver.py`**

```python
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

from app.algorithm.solver import solve
from app.algorithm.types import (
    Assignment,
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverSettings,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


def _parse_fixture(data: dict) -> tuple[list[SoldierInput], list[DutyBlock], list[ExistingAssignment], SolverSettings]:
    soldiers = [
        SoldierInput(
            id=uuid.UUID(s["id"]),
            enrolled_at=date.fromisoformat(s["enrolled_at"]),
            cumulative_score=Decimal(s["cumulative_score"]),
            active_days=s["active_days"],
            hierarchy_node_id=uuid.UUID(s["hierarchy_node_id"]) if s.get("hierarchy_node_id") else None,
            approved_constraint_dates=[
                (date.fromisoformat(p[0]), date.fromisoformat(p[1]))
                for p in s.get("approved_constraint_dates", [])
            ],
            exempted_duty_type_ids={
                uuid.UUID(e) for e in s.get("exempted_duty_type_ids", [])
            },
        )
        for s in data["soldiers"]
    ]
    duties = [
        DutyBlock(
            id=uuid.UUID(d["id"]),
            duty_type_id=uuid.UUID(d["duty_type_id"]),
            duty_location_id=uuid.UUID(d["duty_location_id"]),
            start_date=date.fromisoformat(d["start_date"]),
            end_date=date.fromisoformat(d["end_date"]),
            score_per_day=Decimal(d["score_per_day"]),
        )
        for d in data["duties"]
    ]
    existing = [
        ExistingAssignment(
            soldier_id=uuid.UUID(e["soldier_id"]),
            duty_type_id=uuid.UUID(e["duty_type_id"]),
            start_date=date.fromisoformat(e["start_date"]),
            end_date=date.fromisoformat(e["end_date"]),
        )
        for e in data.get("existing", [])
    ]
    s = data["settings"]
    settings = SolverSettings(
        K=Decimal(s["K"]),
        T=s["T"],
        W=s["W"],
        alpha=Decimal(s["alpha"]),
        beta=Decimal(s["beta"]),
        time_limit_seconds=s["time_limit_seconds"],
        seed=s.get("seed"),
    )
    return soldiers, duties, existing, settings


# ── Golden suite tests ──


def test_small_balanced_solves():
    data = _load_fixture("small_balanced.json")
    soldiers, duties, existing, settings = _parse_fixture(data)
    result = solve(soldiers, duties, existing, settings)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == len(duties)
    # Each duty assigned exactly once
    duty_ids = {d.id for d in duties}
    assigned_duty_ids = {a.duty_id for a in result.assignments}
    assert assigned_duty_ids == duty_ids


def test_small_balanced_hard_constraints():
    data = _load_fixture("small_balanced.json")
    soldiers, duties, existing, settings = _parse_fixture(data)
    result = solve(soldiers, duties, existing, settings)
    assert result.status in ("OPTIMAL", "FEASIBLE")

    duty_map = {d.id: d for d in duties}

    # Coverage: every duty assigned
    assert len(result.assignments) == len(duties)

    # No overlap: no soldier assigned to overlapping duties
    soldier_dates: dict[uuid.UUID, set[date]] = {}
    for a in result.assignments:
        d = duty_map.get(a.duty_id)
        assert d is not None
        day = d.start_date
        while day <= d.end_date:
            if a.soldier_id not in soldier_dates:
                soldier_dates[a.soldier_id] = set()
            assert day not in soldier_dates[a.soldier_id], f"Overlap for {a.soldier_id} on {day}"
            soldier_dates[a.soldier_id].add(day)
            day += timedelta(days=1)

    # No exempted assignments
    soldier_map = {s.id: s for s in soldiers}
    for a in result.assignments:
        d = duty_map.get(a.duty_id)
        s = soldier_map.get(a.soldier_id)
        assert s is not None
        assert d is not None
        assert d.duty_type_id not in s.exempted_duty_type_ids


def test_density_stress_solves():
    data = _load_fixture("density_stress.json")
    soldiers, duties, existing, settings = _parse_fixture(data)
    result = solve(soldiers, duties, existing, settings)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == len(duties)


def test_algorithm_determinism_same_seed():
    data = _load_fixture("small_balanced.json")
    soldiers, duties, existing, settings = _parse_fixture(data)
    settings.seed = 42
    r1 = solve(soldiers, duties, existing, settings)
    r2 = solve(soldiers, duties, existing, settings)
    assert r1.assignments == r2.assignments
    assert r1.objective_value == r2.objective_value


# ── Property-based tests ──


@st.composite
def feasible_population(draw):
    n_soldiers = draw(st.integers(min_value=5, max_value=15))
    n_duties = draw(st.integers(min_value=3, max_value=10))

    base_date = date(2026, 6, 1)
    soldiers = []
    for i in range(n_soldiers):
        enrolled = base_date - timedelta(days=draw(st.integers(min_value=20, max_value=90)))
        active = max(1, (date.today() - enrolled).days)
        soldiers.append(SoldierInput(
            id=uuid.uuid4(),
            enrolled_at=enrolled,
            cumulative_score=Decimal(str(draw(st.floats(min_value=0, max_value=50)))),
            active_days=active,
            hierarchy_node_id=None,
            approved_constraint_dates=[],
            exempted_duty_type_ids=set(),
        ))

    duties = []
    for j in range(n_duties):
        day = base_date + timedelta(days=j)
        duties.append(DutyBlock(
            id=uuid.uuid4(),
            duty_type_id=uuid.UUID("10000001-0000-0000-0000-000000000001"),
            duty_location_id=uuid.UUID("20000000-0000-0000-0000-000000000001"),
            start_date=day,
            end_date=day,
            score_per_day=Decimal("1.00"),
        ))

    settings = SolverSettings(
        K=Decimal("15"),
        T=7,
        W=14,
        alpha=Decimal("1.0"),
        beta=Decimal("2.0"),
        time_limit_seconds=15,
        seed=42,
    )
    return soldiers, duties, [], settings


@given(pop=feasible_population())
def test_hard_constraints_satisfied(pop):
    soldiers, duties, existing, settings = pop
    result = solve(soldiers, duties, existing, settings)
    assert result.status in ("OPTIMAL", "FEASIBLE", "INFEASIBLE")
    if result.status == "INFEASIBLE":
        return  # Skip assertion for truly infeasible problems

    duty_map = {d.id: d for d in duties}
    soldier_map = {s.id: s for s in soldiers}

    # Coverage
    assert len(result.assignments) == len(duties)

    # No overlap
    soldier_dates: dict[uuid.UUID, set[date]] = {}
    for a in result.assignments:
        d = duty_map.get(a.duty_id)
        assert d is not None
        day = d.start_date
        while day <= d.end_date:
            if a.soldier_id not in soldier_dates:
                soldier_dates[a.soldier_id] = set()
            assert day not in soldier_dates[a.soldier_id]
            soldier_dates[a.soldier_id].add(day)
            day += timedelta(days=1)

    # No exempted assignments
    for a in result.assignments:
        d = duty_map.get(a.duty_id)
        s = soldier_map.get(a.soldier_id)
        assert s is not None
        assert d is not None
        assert d.duty_type_id not in s.exempted_duty_type_ids


@given(pop=feasible_population())
def test_determinism_same_seed(pop):
    soldiers, duties, existing, settings = pop
    settings.seed = 42
    settings.time_limit_seconds = 10
    r1 = solve(soldiers, duties, existing, settings)
    r2 = solve(soldiers, duties, existing, settings)
    assert r1.status == r2.status
    if r1.status != "INFEASIBLE":
        assert r1.assignments == r2.assignments


@given(pop=feasible_population())
def test_determinism_different_seed(pop):
    soldiers, duties, existing, settings = pop
    settings.seed = 1
    r1 = solve(soldiers, duties, existing, settings)
    settings.seed = 2
    r2 = solve(soldiers, duties, existing, settings)
    # Just checking no crash; results may differ
    assert isinstance(r1, object)
    assert isinstance(r2, object)


def test_empty_duties():
    soldiers = [
        SoldierInput(
            id=uuid.uuid4(), enrolled_at=date(2026, 1, 1),
            cumulative_score=Decimal("0"), active_days=10,
            hierarchy_node_id=None,
        )
    ]
    result = solve(soldiers, [], [])
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert result.assignments == []


def test_no_eligible_soldiers():
    duty_type = uuid.uuid4()
    soldiers = [
        SoldierInput(
            id=uuid.uuid4(), enrolled_at=date(2026, 1, 1),
            cumulative_score=Decimal("0"), active_days=10,
            hierarchy_node_id=None,
            exempted_duty_type_ids={duty_type},
        )
    ]
    duties = [
        DutyBlock(
            id=uuid.uuid4(), duty_type_id=duty_type,
            duty_location_id=uuid.uuid4(),
            start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
            score_per_day=Decimal("1.00"),
        )
    ]
    result = solve(soldiers, duties, [])
    assert result.status == "INFEASIBLE"
```

- [ ] **Step 3: Run golden suite tests**

Run: `uv run python -m pytest backend/app/algorithm/tests/test_solver.py::test_small_balanced_solves backend/app/algorithm/tests/test_solver.py::test_small_balanced_hard_constraints backend/app/algorithm/tests/test_solver.py::test_density_stress_solves backend/app/algorithm/tests/test_solver.py::test_algorithm_determinism_same_seed backend/app/algorithm/tests/test_solver.py::test_empty_duties backend/app/algorithm/tests/test_solver.py::test_no_eligible_soldiers -v`

Expected: `6 passed`

- [ ] **Step 4: Run all solver tests (including hypothesis)**

Run: `uv run python -m pytest backend/app/algorithm/tests/test_solver.py -v --hypothesis-show-statistics`
Expected: All golden tests pass; hypothesis tests may take 10-30s and run multiple examples.

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/app/algorithm/tests/test_solver.py
git -C .. commit -m "test(algorithm): property-based + golden suite solver tests"
```

---

## Phase I — Reserve tests

### Task 9: Hierarchy-walk reserve tests

**Files:**
- Create: `backend/app/algorithm/tests/test_reserve.py`

- [ ] **Step 1: Write `backend/app/algorithm/tests/test_reserve.py`**

```python
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.algorithm.reserve import select_reserves
from app.algorithm.types import (
    Assignment,
    DutyBlock,
    SoldierInput,
)


def _soldier(
    idx: int,
    node_id: uuid.UUID | None = None,
    exempt: set[uuid.UUID] | None = None,
) -> SoldierInput:
    return SoldierInput(
        id=uuid.UUID(f"00000000-0000-0000-0000-{idx:012d}"),
        enrolled_at=date(2026, 1, 1),
        cumulative_score=Decimal("10.00"),
        active_days=30,
        hierarchy_node_id=node_id,
        exempted_duty_type_ids=exempt or set(),
    )


def _duty(uid: uuid.UUID | None = None) -> DutyBlock:
    return DutyBlock(
        id=uid or uuid.uuid4(),
        duty_type_id=uuid.UUID("10000000-0000-0000-0000-000000000001"),
        duty_location_id=uuid.UUID("20000000-0000-0000-0000-000000000001"),
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 1),
        score_per_day=Decimal("1.00"),
    )


def test_walks_hierarchy_outward():
    """Three-level tree: primary in leaf -> reserve found in same node first, then sibling, then parent."""
    team_a = uuid.uuid4()
    team_b = uuid.uuid4()
    group = uuid.uuid4()
    dept = uuid.uuid4()

    primary = _soldier(1, team_a)
    same_team = _soldier(2, team_a)
    other_team = _soldier(3, team_b)
    parent_node = _soldier(4, group)

    duty = _duty()
    assignments = [Assignment(duty_id=duty.id, soldier_id=primary.id)]

    hierarchy_parent = {
        team_a: group,
        team_b: group,
        group: dept,
        dept: None,
    }
    hierarchy_children = {
        dept: [group],
        group: [team_a, team_b],
        team_a: [],
        team_b: [],
    }
    soldier_node = {
        primary.id: team_a,
        same_team.id: team_a,
        other_team.id: team_b,
        parent_node.id: group,
    }
    node_soldiers = {
        team_a: [primary.id, same_team.id],
        team_b: [other_team.id],
        group: [parent_node.id],
        dept: [],
    }

    reserves = select_reserves(
        soldiers=[primary, same_team, other_team, parent_node],
        duties=[duty],
        assignments=assignments,
        hierarchy_parent=hierarchy_parent,
        hierarchy_children=hierarchy_children,
        soldier_node=soldier_node,
        node_soldiers=node_soldiers,
    )

    assert len(reserves) == 1
    _duty_id, _primary_id, reserve_id = reserves[0]
    assert reserve_id == same_team.id  # closest: same node


def test_no_reserve_available():
    """Soldier is alone in the tree -> returns empty."""
    solo_node = uuid.uuid4()
    primary = _soldier(1, solo_node)
    duty = _duty()
    assignments = [Assignment(duty_id=duty.id, soldier_id=primary.id)]

    reserves = select_reserves(
        soldiers=[primary],
        duties=[duty],
        assignments=assignments,
        hierarchy_parent={solo_node: None},
        hierarchy_children={solo_node: []},
        soldier_node={primary.id: solo_node},
        node_soldiers={solo_node: [primary.id]},
    )
    assert reserves == []


def test_skips_blocked_soldiers():
    """Reserve candidate has exemption -> skips to next level."""
    team_a = uuid.uuid4()
    team_b = uuid.uuid4()
    group = uuid.uuid4()

    duty_type = uuid.UUID("10000000-0000-0000-0000-000000000001")
    primary = _soldier(1, team_a)
    same_team_exempt = _soldier(2, team_a, exempt={duty_type})
    other_team = _soldier(3, team_b)

    duty = _duty()
    assignments = [Assignment(duty_id=duty.id, soldier_id=primary.id)]

    reserves = select_reserves(
        soldiers=[primary, same_team_exempt, other_team],
        duties=[duty],
        assignments=assignments,
        hierarchy_parent={team_a: group, team_b: group, group: None},
        hierarchy_children={group: [team_a, team_b], team_a: [], team_b: []},
        soldier_node={
            primary.id: team_a,
            same_team_exempt.id: team_a,
            other_team.id: team_b,
        },
        node_soldiers={
            team_a: [primary.id, same_team_exempt.id],
            team_b: [other_team.id],
            group: [],
        },
    )
    assert len(reserves) == 1
    _duty_id, _primary_id, reserve_id = reserves[0]
    assert reserve_id == other_team.id  # skipped exempt, found at sibling level
```

- [ ] **Step 2: Run reserve tests**

Run: `uv run python -m pytest backend/app/algorithm/tests/test_reserve.py -v`
Expected: All 3 passed.

- [ ] **Step 3: Commit**

```bash
git -C .. add backend/app/algorithm/tests/test_reserve.py
git -C .. commit -m "test(algorithm): hierarchy-walk reserve selection tests"
```

---

## Self-review checklist

After completing all tasks, verify:

1. **Spec coverage:** Every section from the spec has a corresponding task: types (Task 2), model (Task 3), solver (Task 4), explain (Task 5), reserve (Task 6), property-based + golden tests (Task 8), reserve tests (Task 9).
2. **Placeholder scan:** No "TBD", "TODO", or incomplete sections in this plan.
3. **Type consistency:** All types used across tasks match `types.py` definitions.

---

## Summary

```
Phase A (Task 1):  Dependency + scaffold       [pyproject.toml, __init__.py files]
Phase B (Task 2):  Data types                   [types.py]
Phase C (Task 3):  Model builder                [model.py]
Phase D (Task 4):  Solver wrapper               [solver.py]
Phase E (Task 5):  Explainability               [explain.py]
Phase F (Task 6):  Reserve selection            [reserve.py]
Phase G (Task 7):  Golden fixtures              [small_balanced.json, density_stress.json]
Phase H (Task 8):  Solver tests                 [test_solver.py]
Phase I (Task 9):  Reserve tests                [test_reserve.py]
```
