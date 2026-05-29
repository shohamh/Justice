# CP-SAT Fairness Algorithm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the pure CP-SAT fairness algorithm module (solver + explainability + reserve selection) as described in `docs/superpowers/specs/2026-05-29-cp-sat-fairness-algorithm-design.md`.

**Architecture:** Pure Python module under `backend/app/algorithm/` with no imports from `app.db`, `app.routes`, or `app.services`. CP-SAT model builder and solver wrapper are separate files (`model.py`, `solver.py`), plus `explain.py` and `reserve.py` for post-processing. Property-based tests with `hypothesis` and golden fixtures.

**Tech Stack:** Python 3.12, OR-Tools CP-SAT 9.10+, pytest + hypothesis, dataclasses (no Pydantic in the pure module).

---

## File structure

```
backend/
├── pyproject.toml                                  # +ortools>=9.10
├── app/algorithm/
│   ├── __init__.py
│   ├── types.py                                    # Pure dataclasses
│   ├── model.py                                    # build_model() — CP-SAT variables, hard constraints, soft objective
│   ├── solver.py                                   # solve() — wrapper, infeasibility relaxation chain
│   ├── explain.py                                  # build_explanations() — per-assignment candidate analysis
│   ├── reserve.py                                  # select_reserves() — hierarchy-walk outward
│   └── tests/
│       ├── __init__.py
│       ├── fixtures/
│       │   ├── small_balanced.json
│       │   └── density_stress.json
│       ├── test_solver.py
│       └── test_reserve.py
```

## Tasks

### Task 1: Add OR-Tools dependency

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add `ortools` to dependencies**

Edit `backend/pyproject.toml`, add `"ortools>=9.10"` to the `dependencies` list.

- [ ] **Step 2: Install and verify**

Run (from `backend/`): `uv sync; uv run python -c "from ortools.sat.python.cp_model import CpModel, CpSolver; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "deps(ortools): add OR-Tools CP-SAT 9.10+"
```

---

### Task 2: Create `types.py` — pure data types

**Files:**
- Create: `backend/app/algorithm/__init__.py`
- Create: `backend/app/algorithm/types.py`

- [ ] **Step 1: Write the empty init file**

```python
```

- [ ] **Step 2: Write `types.py`**

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
    hierarchy_node_id: uuid.UUID | None = None
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
    objective_value: float | None = None
    seed: int = 0
    solver_metrics: dict = field(default_factory=dict)
    relaxed: list[str] = field(default_factory=list)


@dataclass
class CandidateInfo:
    soldier_id: uuid.UUID
    blocked: bool = False
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


@dataclass
class ReserveEntry:
    duty_id: uuid.UUID
    primary_soldier_id: uuid.UUID
    reserve_soldier_id: uuid.UUID
```

- [ ] **Step 3: Verify imports**

Run: `uv run python -c "from app.algorithm.types import SoldierInput, DutyBlock, SolverSettings, Assignment, SolverResult, CandidateInfo, AssignmentExplanation, ExplanationData, ReserveEntry; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/app/algorithm/__init__.py backend/app/algorithm/types.py
git commit -m "feat(algorithm): pure data types for solver input/output"
```

---

### Task 3: Create `model.py` — CP-SAT model builder

**Files:**
- Create: `backend/app/algorithm/tests/__init__.py`
- Create: `backend/app/algorithm/tests/test_solver.py` (first test)
- Create: `backend/app/algorithm/model.py`

- [ ] **Step 1: Write the empty tests init file**

```python
```

- [ ] **Step 2: Write the first test**

```python
# backend/app/algorithm/tests/test_solver.py
from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.algorithm.model import build_model
from app.algorithm.types import DutyBlock, ExistingAssignment, SoldierInput, SolverSettings


def test_build_model_basic():
    soldier_id = uuid4()
    duty_id = uuid4()
    soldiers = [
        SoldierInput(
            id=soldier_id,
            enrolled_at=date(2026, 1, 1),
            cumulative_score=Decimal("0"),
            active_days=100,
        )
    ]
    duties = [
        DutyBlock(
            id=duty_id,
            duty_type_id=uuid4(),
            duty_location_id=uuid4(),
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            score_per_day=Decimal("1.00"),
        )
    ]
    existing: list[ExistingAssignment] = []
    settings = SolverSettings()
    model = build_model(soldiers=soldiers, duties=duties, existing=existing, settings=settings)
    assert model is not None
```

- [ ] **Step 3: Run — expect FAIL**

Run: `uv run pytest backend/app/algorithm/tests/test_solver.py::test_build_model_basic -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.algorithm.model'`

- [ ] **Step 4: Write `model.py`**

This is the core of the algorithm. The model builder takes soldiers + duties + existing assignments + settings and returns a `CpModel` with all hard constraints and the soft objective.

```python
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Sequence

from ortools.sat.python.cp_model import CpModel, IntVar, LinearExpr

from app.algorithm.types import DutyBlock, ExistingAssignment, SoldierInput, SolverSettings


def _block_score(d: DutyBlock) -> int:
    """Total score for completing the entire block, in milli-units (x1000 for integer math)."""
    days = (d.end_date - d.start_date).days + 1
    return int(d.score_per_day * Decimal(days) * 1000)


def _duty_dates(d: DutyBlock) -> list[date]:
    dt = d.start_date
    result: list[date] = []
    while dt <= d.end_date:
        result.append(dt)
        dt += timedelta(days=1)
    return result


def _existing_dates_by_soldier(
    existing: Sequence[ExistingAssignment], soldier_id: uuid.UUID
) -> set[date]:
    result: set[date] = set()
    for ea in existing:
        if ea.soldier_id == soldier_id:
            dt = ea.start_date
            while dt <= ea.end_date:
                result.add(dt)
                dt += timedelta(days=1)
    return result


def build_model(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
) -> tuple[CpModel, dict[tuple[int, int], IntVar]]:
    model = CpModel()
    duty_list = list(duties)
    soldier_list = list(soldiers)
    W = settings.W
    T = settings.T

    # Build lookup maps
    exempt_map: dict[uuid.UUID, set[uuid.UUID]] = {}
    for s in soldier_list:
        exempt_map[s.id] = s.exempted_duty_type_ids

    constraint_map: dict[uuid.UUID, set[date]] = {}
    for s in soldier_list:
        dates: set[date] = set()
        for cs, ce in s.approved_constraint_dates:
            dt = cs
            while dt <= ce:
                dates.add(dt)
                dt += timedelta(days=1)
        constraint_map[s.id] = dates

    # Pre-filter eligible (duty, soldier) pairs
    eligible: list[tuple[int, int]] = []
    soldier_duties: dict[int, list[int]] = defaultdict(list)
    for di, d in enumerate(duty_list):
        for si, s in enumerate(soldier_list):
            if d.duty_type_id in exempt_map.get(s.id, set()):
                continue
            constrained_dates = constraint_map.get(s.id, set())
            if any(dt in constrained_dates for dt in _duty_dates(d)):
                continue
            eligible.append((di, si))
            soldier_duties[si].append(di)

    # Decision variables: x[di, si] = 1 if soldier si gets duty di
    x: dict[tuple[int, int], IntVar] = {}
    for di, si in eligible:
        x[(di, si)] = model.NewBoolVar(f"x_d{di}_s{si}")

    # Hard constraint 1: Coverage — every duty assigned to exactly one soldier
    for di in range(len(duty_list)):
        vars_for_d = [x[(di, si)] for (dii, si) in eligible if dii == di]
        model.Add(sum(vars_for_d) == 1)

    # Hard constraint 2: No overlap — a soldier cannot be assigned two duties covering the same day
    all_dates_set: set[date] = set()
    for d in duty_list:
        all_dates_set.update(_duty_dates(d))

    for si, s in enumerate(soldier_list):
        existing_dates = _existing_dates_by_soldier(existing, s.id)
        for t in sorted(all_dates_set):
            day_vars = [x[(di, si)] for di in soldier_duties.get(si, [])
                        if _duty_dates(duty_list[di]).count(t) > 0]
            if not day_vars:
                continue
            if t in existing_dates:
                model.Add(sum(day_vars) == 0)
            else:
                model.Add(sum(day_vars) <= 1)

    # Hard constraint 3: K normalised-score variance
    norm_exprs: list[LinearExpr] = []
    for si, s in enumerate(soldier_list):
        if s.active_days == 0:
            continue
        block_sum = sum(
            _block_score(duty_list[di]) * x[(di, si)]
            for di in soldier_duties.get(si, [])
        )
        base = int(s.cumulative_score * 1000)
        total = base + block_sum
        norm = int(total / s.active_days)
        norm_exprs.append(norm)

    if norm_exprs:
        min_norm = model.NewIntVar(0, 10_000_000, "min_norm")
        max_norm = model.NewIntVar(0, 10_000_000, "max_norm")
        model.AddMinEquality(min_norm, norm_exprs)
        model.AddMaxEquality(max_norm, norm_exprs)
        K_int = int(settings.K * 1000)
        model.Add(max_norm - min_norm <= K_int)

    # Soft objective: minimise density penalty
    # For each soldier and each rolling window of length W:
    # penalty = max(0, density - T)^2, approximated piecewise-linearly
    beta_int = int(settings.beta * 1000)
    density_terms: list[LinearExpr] = []

    for si, s in enumerate(soldier_list):
        soldier_dates = _existing_dates_by_soldier(existing, s.id)
        for di in soldier_duties.get(si, []):
            soldier_dates.update(_duty_dates(duty_list[di]))
        if not soldier_dates:
            continue

        min_d = min(soldier_dates)
        max_d = max(soldier_dates)
        ws = min_d
        while ws <= max_d:
            we = ws + timedelta(days=W - 1)
            fixed = sum(1 for dt_iter in soldier_dates
                        if ws <= dt_iter <= we and dt_iter < ws)  # existing only
            # Actually, soldier_dates includes both existing and variable duty dates
            # We need to separate: existing dates are fixed, variable dates depend on x
            existing_fixed = len([dt_iter for dt_iter in
                                  _existing_dates_by_soldier(existing, s.id)
                                  if ws <= dt_iter <= we])
            var_for_window: list[IntVar] = []
            for di in soldier_duties.get(si, []):
                d = duty_list[di]
                if any(ws <= dt <= we for dt in _duty_dates(d)):
                    var_for_window.append(x[(di, si)])
                    break

            if not var_for_window and existing_fixed <= T:
                ws += timedelta(days=1)
                continue

            total_density = existing_fixed + (sum(var_for_window) if var_for_window else 0)

            excess = model.NewIntVar(0, W, f"excess_s{si}_w{ws}")
            model.Add(excess >= total_density - T)
            model.Add(excess >= 0)

            # Piecewise-linear: 1x, 3x, 5x marginal costs
            e1 = model.NewIntVar(0, 1, f"e1_s{si}_w{ws}")
            model.Add(e1 <= excess)
            model.Add(e1 * 2 >= excess)
            e2 = model.NewIntVar(0, 2, f"e2_s{si}_w{ws}")
            model.Add(e2 <= excess - 1)
            model.Add(e2 >= 0)
            model.Add(e2 * 2 >= excess - 1)
            e3 = model.NewIntVar(0, W, f"e3_s{si}_w{ws}")
            model.Add(e3 <= excess - 3)
            model.Add(e3 >= 0)

            cost = e1 + 3 * e2 + 5 * e3
            density_terms.append(beta_int * cost)

            ws += timedelta(days=1)

    objective = -(sum(density_terms) if density_terms else 0)
    model.Maximize(objective)
    return model, x
```

- [ ] **Step 5: Run — expect PASS**

Run: `uv run pytest backend/app/algorithm/tests/test_solver.py::test_build_model_basic -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/algorithm/tests/__init__.py backend/app/algorithm/tests/test_solver.py backend/app/algorithm/model.py
git commit -m "feat(algorithm): CP-SAT model builder with hard constraints and density objective"
```

---

### Task 4: Create `solver.py` — solve wrapper + infeasibility chain

**Files:**
- Create: `backend/app/algorithm/solver.py`
- Modify: `backend/app/algorithm/tests/test_solver.py` (add solve tests)

- [ ] **Step 1: Write the solve test**

Append to `backend/app/algorithm/tests/test_solver.py`:

```python
import hashlib

from app.algorithm.solver import solve, infeasibility_relaxation_chain
from app.algorithm.types import SolverResult


def test_solve_basic():
    soldier_id = uuid4()
    duty_id = uuid4()
    soldiers = [
        SoldierInput(
            id=soldier_id,
            enrolled_at=date(2026, 1, 1),
            cumulative_score=Decimal("0"),
            active_days=100,
        )
    ]
    duties = [
        DutyBlock(
            id=duty_id,
            duty_type_id=uuid4(),
            duty_location_id=uuid4(),
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            score_per_day=Decimal("1.00"),
        )
    ]
    existing: list[ExistingAssignment] = []
    settings = SolverSettings(time_limit_seconds=10)
    result = solve(soldiers=soldiers, duties=duties, existing=existing, settings=settings)
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1
    assert result.assignments[0].soldier_id == soldier_id


def test_solve_determinism():
    soldier_id = uuid4()
    duties = [DutyBlock(id=uuid4(), duty_type_id=uuid4(), duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
                        score_per_day=Decimal("1.00"))]
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100)]
    settings = SolverSettings(seed=42, time_limit_seconds=10)
    r1 = solve(soldiers, duties, [], settings)
    r2 = solve(soldiers, duties, [], settings)
    assert r1.assignments == r2.assignments
    assert r1.objective_value == r2.objective_value


def test_solve_no_eligible_soldiers():
    soldier_id = uuid4()
    exempt_type = uuid4()
    duty_type = exempt_type  # soldier exempted from this exact duty type
    duties = [DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                        score_per_day=Decimal("1.00"))]
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100,
                             exempted_duty_type_ids={exempt_type})]
    result = solve(soldiers, duties, [], SolverSettings(time_limit_seconds=5))
    assert result.status == "INFEASIBLE"
    assert len(result.assignments) == 0


def test_infeasibility_relaxation():
    # 2 soldiers, 10 duties all on the same day -> impossible to avoid overlap
    # With tight K, it may be infeasible; relaxation should help
    soldier_a = uuid4()
    soldier_b = uuid4()
    duty_type = uuid4()
    soldiers = [
        SoldierInput(id=soldier_a, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100),
        SoldierInput(id=soldier_b, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("10"), active_days=100),
    ]
    duties = [
        DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                  start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                  score_per_day=Decimal("1.00"))
        for _ in range(3)  # 3 duties on same day, 2 soldiers -> overlap unavoidable
    ]
    # Tight K=1 will make this infeasible due to score difference
    result = solve(soldiers, duties, [], SolverSettings(K=Decimal("1"), time_limit_seconds=5))
    # Should still find a solution via relaxation
    assert result.status in ("OPTIMAL", "FEASIBLE")
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest backend/app/algorithm/tests/test_solver.py::test_solve_basic -v`
Expected: FAIL — `ImportError` for `app.algorithm.solver`

- [ ] **Step 3: Write `solver.py`**

```python
from __future__ import annotations

from typing import Sequence

from ortools.sat.python.cp_model import CpSolver, IntVar

from app.algorithm.model import build_model
from app.algorithm.types import (
    Assignment,
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverResult,
    SolverSettings,
)


from app.algorithm.model import build_model


def solve(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
) -> SolverResult:
    """Build the CP-SAT model and solve it. Returns assignments + metrics."""
    return _infeasibility_relaxation_chain(soldiers, duties, existing, settings)


def _solve_with_settings(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
) -> tuple[CpSolver, dict[tuple[int, int], IntVar], int]:
    model, x = build_model(soldiers, duties, existing, settings)
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = settings.time_limit_seconds
    if settings.seed is not None:
        solver.parameters.random_seed = settings.seed
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    return solver, x, status


def _infeasibility_relaxation_chain(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
) -> SolverResult:
    current = SolverSettings(
        K=settings.K, T=settings.T, W=settings.W,
        alpha=settings.alpha, beta=settings.beta,
        time_limit_seconds=settings.time_limit_seconds,
        seed=settings.seed,
    )
    relaxed: list[str] = []
    duty_list = list(duties)
    soldier_list = list(soldiers)

    for attempt in range(5):
        solver, x, status = _solve_with_settings(soldiers, duties, existing, current)
        status_name = solver.StatusName(status)

        if status_name == "INFEASIBLE":
            if attempt < 3:
                current.K = current.K + 1
                relaxed.append(f"K→{current.K}")
                continue
            elif attempt < 4:
                current.T = current.T + 1
                relaxed.append(f"T→{current.T}")
                continue
            else:
                return SolverResult(
                    assignments=[], status="INFEASIBLE",
                    seed=current.seed or 0, relaxed=relaxed,
                )

        assignments: list[Assignment] = []
        for (di, si), var in x.items():
            if solver.Value(var):
                assignments.append(Assignment(
                    duty_id=duty_list[di].id,
                    soldier_id=soldier_list[si].id,
                ))

        # Sort by duty_id for deterministic output
        assignments.sort(key=lambda a: a.duty_id)

        return SolverResult(
            assignments=assignments,
            status=status_name,
            objective_value=solver.ObjectiveValue() if status_name in ("OPTIMAL", "FEASIBLE") else None,
            seed=current.seed or 0,
            solver_metrics={
                "wall_time": solver.WallTime(),
                "conflicts": solver.NumConflicts(),
                "branches": solver.NumBranches(),
            },
            relaxed=relaxed,
        )

    return SolverResult(assignments=[], status="INFEASIBLE", seed=current.seed or 0, relaxed=relaxed)
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest backend/app/algorithm/tests/test_solver.py -v`
Expected: all tests pass (basic + determinism + no eligible + relaxation)

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/solver.py backend/app/algorithm/tests/test_solver.py
git commit -m "feat(algorithm): CP-SAT solver wrapper with infeasibility relaxation chain"
```

---

### Task 5: Create `explain.py` — explanation builder

**Files:**
- Create: `backend/app/algorithm/explain.py`
- Create: `backend/app/algorithm/tests/test_explain.py` (new test file)

- [ ] **Step 1: Write the explain test**

```python
# backend/app/algorithm/tests/test_explain.py
from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.algorithm.explain import build_explanations
from app.algorithm.types import Assignment, CandidateInfo, DutyBlock, ExplanationData, SoldierInput


def test_build_explanations_basic():
    soldier_id = uuid4()
    duty_id = uuid4()
    soldiers = [SoldierInput(id=soldier_id, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100)]
    duties = [DutyBlock(id=duty_id, duty_type_id=uuid4(), duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
                        score_per_day=Decimal("1.00"))]
    assignments = [Assignment(duty_id=duty_id, soldier_id=soldier_id)]
    result = build_explanations(
        soldiers=soldiers,
        duties=duties,
        assignments=assignments,
        global_before={"min_gap": 0, "norm_variance": 0},
        global_after={"min_gap": 5, "norm_variance": 1},
        solver_seed=42,
    )
    assert len(result.per_assignment) == 1
    assert result.per_assignment[0].duty_id == duty_id
    assert result.per_assignment[0].assigned_soldier_id == soldier_id
    assert any(
        c.soldier_id == soldier_id and not c.blocked
        for c in result.per_assignment[0].candidates
    )
    assert result.algorithm_version == "cp-sat-1.0"
    assert result.solver_seed == 42


def test_explain_blocked_candidate():
    soldier_a = uuid4()
    soldier_b = uuid4()
    exempt_type = uuid4()
    duty_type = exempt_type
    soldiers = [
        SoldierInput(id=soldier_a, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100),
        SoldierInput(id=soldier_b, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100,
                     exempted_duty_type_ids={duty_type}),
    ]
    duties = [DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
                        score_per_day=Decimal("1.00"))]
    assignments = [Assignment(duty_id=duties[0].id, soldier_id=soldier_a)]
    result = build_explanations(soldiers, duties, assignments, {}, {}, 42)
    entry = result.per_assignment[0]
    blocked = [c for c in entry.candidates if c.blocked]
    unblocked = [c for c in entry.candidates if not c.blocked]
    assert len(blocked) == 1
    assert "exemption" in blocked[0].blocking_constraints
    assert len(unblocked) == 1
    assert unblocked[0].soldier_id == soldier_a
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest backend/app/algorithm/tests/test_explain.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `explain.py`**

```python
from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Sequence

from app.algorithm.types import (
    Assignment,
    AssignmentExplanation,
    CandidateInfo,
    DutyBlock,
    ExplanationData,
    SoldierInput,
)


def build_explanations(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    assignments: Sequence[Assignment],
    global_before: dict,
    global_after: dict,
    solver_seed: int,
) -> ExplanationData:
    soldier_map = {s.id: s for s in soldiers}
    duty_map = {d.id: d for d in duties}
    assignment_map = {a.duty_id: a.soldier_id for a in assignments}

    per_assignment: list[AssignmentExplanation] = []
    for a in assignments:
        duty = duty_map[a.duty_id]
        assigned_soldier = soldier_map[a.soldier_id]
        candidates: list[CandidateInfo] = []

        for s in soldiers:
            blocking: list[str] = []
            # Check exemption
            if duty.duty_type_id in s.exempted_duty_type_ids:
                blocking.append("exemption")
            # Check personal constraint
            for cs, ce in s.approved_constraint_dates:
                if cs <= duty.end_date and ce >= duty.start_date:
                    blocking.append("personal_constraint")
                    break
            # Check no-overlap with other assignments in this batch
            for other_a in assignments:
                if other_a.soldier_id == s.id and other_a.duty_id != a.duty_id:
                    other_duty = duty_map[other_a.duty_id]
                    if other_duty.start_date <= duty.end_date and other_duty.end_date >= duty.start_date:
                        blocking.append("overlap")
                        break

            pre = s.cumulative_score
            block_score = duty.score_per_day * Decimal((duty.end_date - duty.start_date).days + 1)
            post = pre + block_score if s.id == a.soldier_id else pre

            candidates.append(CandidateInfo(
                soldier_id=s.id,
                blocked=len(blocking) > 0,
                blocking_constraints=blocking,
                pre_norm_score=pre / Decimal(s.active_days) if s.active_days > 0 else None,
                post_norm_score=post / Decimal(s.active_days) if s.active_days > 0 else None,
            ))

        per_assignment.append(AssignmentExplanation(
            duty_id=a.duty_id,
            assigned_soldier_id=a.soldier_id,
            candidates=candidates,
            tiebreaker_note="Selected by solver objective optimisation",
        ))

    return ExplanationData(
        per_assignment=per_assignment,
        global_metrics_before=dict(global_before),
        global_metrics_after=dict(global_after),
        algorithm_version="cp-sat-1.0",
        solver_seed=solver_seed,
    )
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest backend/app/algorithm/tests/test_explain.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/explain.py backend/app/algorithm/tests/test_explain.py
git commit -m "feat(algorithm): explanation builder for per-assignment candidate analysis"
```

---

### Task 6: Create `reserve.py` — hierarchy-walk reserve selection

**Files:**
- Create: `backend/app/algorithm/reserve.py`
- Create: `backend/app/algorithm/tests/test_reserve.py`

- [ ] **Step 1: Write the reserve test**

```python
# backend/app/algorithm/tests/test_reserve.py
from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.algorithm.reserve import select_reserves
from app.algorithm.types import Assignment, DutyBlock, ReserveEntry, SoldierInput


def test_select_reserves_basic_hierarchy_walk():
    team_a = uuid4()
    team_b = uuid4()
    group = uuid4()
    soldier_primary = uuid4()
    soldier_backup = uuid4()

    soldiers = [
        SoldierInput(id=soldier_primary, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100,
                     hierarchy_node_id=team_a),
        SoldierInput(id=soldier_backup, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100,
                     hierarchy_node_id=team_b),
    ]
    duties = [DutyBlock(id=uuid4(), duty_type_id=uuid4(), duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
                        score_per_day=Decimal("1.00"))]
    assignments = [Assignment(duty_id=duties[0].id, soldier_id=soldier_primary)]

    hierarchy_parent = {team_a: group, team_b: group, group: None}
    hierarchy_children = {group: [team_a, team_b], team_a: [], team_b: []}
    soldier_node = {soldier_primary: team_a, soldier_backup: team_b}
    node_soldiers = {team_a: [soldier_primary], team_b: [soldier_backup]}

    result = select_reserves(
        soldiers=soldiers,
        duties=duties,
        assignments=assignments,
        hierarchy_parent=hierarchy_parent,
        hierarchy_children=hierarchy_children,
        soldier_node=soldier_node,
        node_soldiers=node_soldiers,
    )
    assert len(result) == 1
    assert result[0].duty_id == duties[0].id
    assert result[0].primary_soldier_id == soldier_primary
    assert result[0].reserve_soldier_id == soldier_backup


def test_no_reserve_available():
    solo = uuid4()
    team = uuid4()
    soldiers = [SoldierInput(id=solo, enrolled_at=date(2026, 1, 1),
                             cumulative_score=Decimal("0"), active_days=100,
                             hierarchy_node_id=team)]
    duties = [DutyBlock(id=uuid4(), duty_type_id=uuid4(), duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                        score_per_day=Decimal("1.00"))]
    assignments = [Assignment(duty_id=duties[0].id, soldier_id=solo)]
    result = select_reserves(
        soldiers=soldiers, duties=duties, assignments=assignments,
        hierarchy_parent={team: None}, hierarchy_children={team: []},
        soldier_node={solo: team}, node_soldiers={team: [solo]},
    )
    assert len(result) == 0


def test_reserve_skips_exempted_soldier():
    primary = uuid4()
    backup = uuid4()
    team_a = uuid4()
    team_b = uuid4()
    group = uuid4()
    duty_type = uuid4()

    soldiers = [
        SoldierInput(id=primary, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100,
                     hierarchy_node_id=team_a),
        SoldierInput(id=backup, enrolled_at=date(2026, 1, 1),
                     cumulative_score=Decimal("0"), active_days=100,
                     hierarchy_node_id=team_b,
                     exempted_duty_type_ids={duty_type}),
    ]
    duties = [DutyBlock(id=uuid4(), duty_type_id=duty_type, duty_location_id=uuid4(),
                        start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                        score_per_day=Decimal("1.00"))]
    assignments = [Assignment(duty_id=duties[0].id, soldier_id=primary)]

    result = select_reserves(
        soldiers=soldiers, duties=duties, assignments=assignments,
        hierarchy_parent={team_a: group, team_b: group, group: None},
        hierarchy_children={group: [team_a, team_b], team_a: [], team_b: []},
        soldier_node={primary: team_a, backup: team_b},
        node_soldiers={team_a: [primary], team_b: [backup]},
    )
    # backup is exempted, so no reserve found
    assert len(result) == 0
```

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest backend/app/algorithm/tests/test_reserve.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `reserve.py`**

```python
from __future__ import annotations

import uuid
from collections import deque
from datetime import date
from typing import Sequence

from app.algorithm.types import Assignment, DutyBlock, ReserveEntry, SoldierInput


def select_reserves(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    assignments: Sequence[Assignment],
    hierarchy_parent: dict[uuid.UUID, uuid.UUID | None],
    hierarchy_children: dict[uuid.UUID, list[uuid.UUID]],
    soldier_node: dict[uuid.UUID, uuid.UUID],
    node_soldiers: dict[uuid.UUID, list[uuid.UUID]],
) -> list[ReserveEntry]:
    duty_map = {d.id: d for d in duties}
    soldier_map = {s.id: s for s in soldiers}
    results: list[ReserveEntry] = []

    for a in assignments:
        duty = duty_map[a.duty_id]
        primary_id = a.soldier_id
        primary_node = soldier_node.get(primary_id)
        if primary_node is None:
            continue

        # BFS outward from the primary's node
        visited_nodes: set[uuid.UUID] = set()
        queue: deque[tuple[uuid.UUID, int]] = deque()
        queue.append((primary_node, 0))
        visited_nodes.add(primary_node)

        reserve_candidates: list[tuple[uuid.UUID, int]] = []  # (soldier_id, distance)

        while queue:
            node_id, distance = queue.popleft()
            # Check soldiers in this node
            for sid in node_soldiers.get(node_id, []):
                if sid == primary_id:
                    continue
                s = soldier_map.get(sid)
                if s is None:
                    continue
                # Check hard constraints
                if duty.duty_type_id in s.exempted_duty_type_ids:
                    continue
                if any(cs <= duty.end_date and ce >= duty.start_date
                       for cs, ce in s.approved_constraint_dates):
                    continue
                # Check overlap with this soldier's other assignments in the batch
                overlapping = False
                for other_a in assignments:
                    if other_a.soldier_id == sid:
                        other_duty = duty_map.get(other_a.duty_id)
                        if other_duty and other_duty.start_date <= duty.end_date and other_duty.end_date >= duty.start_date:
                            overlapping = True
                            break
                if overlapping:
                    continue
                reserve_candidates.append((sid, distance))

            # Add siblings (same parent) and parent's siblings
            parent = hierarchy_parent.get(node_id)
            if parent is not None and parent not in visited_nodes:
                visited_nodes.add(parent)
                # Parent itself
                for sid in node_soldiers.get(parent, []):
                    if sid == primary_id:
                        continue
                    s = soldier_map.get(sid)
                    if s is None:
                        continue
                    reserve_candidates.append((sid, distance + 1))
                # Siblings of parent
                for sibling in hierarchy_children.get(parent, []):
                    if sibling not in visited_nodes:
                        visited_nodes.add(sibling)
                        queue.append((sibling, distance + 1))

        # Pick closest candidate (smallest distance)
        if reserve_candidates:
            reserve_candidates.sort(key=lambda x: x[1])
            best_id, best_dist = reserve_candidates[0]
            results.append(ReserveEntry(
                duty_id=a.duty_id,
                primary_soldier_id=primary_id,
                reserve_soldier_id=best_id,
            ))

    return results
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest backend/app/algorithm/tests/test_reserve.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/reserve.py backend/app/algorithm/tests/test_reserve.py
git commit -m "feat(algorithm): hierarchy-walk reserve soldier selection"
```

---

### Task 7: Golden fixtures + property-based tests

**Files:**
- Create: `backend/app/algorithm/tests/fixtures/small_balanced.json`
- Create: `backend/app/algorithm/tests/fixtures/density_stress.json`
- Modify: `backend/app/algorithm/tests/test_solver.py` (add golden + property tests)

- [ ] **Step 1: Create `small_balanced.json`**

```json
{
  "description": "10 soldiers, 5 duties, all eligible, varied scores and active days",
  "soldiers": [
    {"id": "s0000001-0000-0000-0000-000000000001", "enrolled_at": "2026-01-01", "cumulative_score": "2.00", "active_days": 100, "hierarchy_node_id": null, "approved_constraint_dates": [], "exempted_duty_type_ids": []},
    {"id": "s0000001-0000-0000-0000-000000000002", "enrolled_at": "2026-01-01", "cumulative_score": "5.00", "active_days": 100, "hierarchy_node_id": null, "approved_constraint_dates": [], "exempted_duty_type_ids": []},
    {"id": "s0000001-0000-0000-0000-000000000003", "enrolled_at": "2026-01-01", "cumulative_score": "1.00", "active_days": 50, "hierarchy_node_id": null, "approved_constraint_dates": [], "exempted_duty_type_ids": []},
    {"id": "s0000001-0000-0000-0000-000000000004", "enrolled_at": "2026-01-01", "cumulative_score": "0.00", "active_days": 100, "hierarchy_node_id": null, "approved_constraint_dates": [], "exempted_duty_type_ids": []},
    {"id": "s0000001-0000-0000-0000-000000000005", "enrolled_at": "2026-01-01", "cumulative_score": "3.00", "active_days": 75, "hierarchy_node_id": null, "approved_constraint_dates": [], "exempted_duty_type_ids": []},
    {"id": "s0000001-0000-0000-0000-000000000006", "enrolled_at": "2026-02-01", "cumulative_score": "0.00", "active_days": 80, "hierarchy_node_id": null, "approved_constraint_dates": [], "exempted_duty_type_ids": []},
    {"id": "s0000001-0000-0000-0000-000000000007", "enrolled_at": "2026-01-15", "cumulative_score": "4.00", "active_days": 90, "hierarchy_node_id": null, "approved_constraint_dates": [], "exempted_duty_type_ids": []},
    {"id": "s0000001-0000-0000-0000-000000000008", "enrolled_at": "2026-01-01", "cumulative_score": "1.50", "active_days": 100, "hierarchy_node_id": null, "approved_constraint_dates": [], "exempted_duty_type_ids": []},
    {"id": "s0000001-0000-0000-0000-000000000009", "enrolled_at": "2026-01-01", "cumulative_score": "2.50", "active_days": 60, "hierarchy_node_id": null, "approved_constraint_dates": [], "exempted_duty_type_ids": []},
    {"id": "s0000001-0000-0000-0000-000000000010", "enrolled_at": "2026-03-01", "cumulative_score": "0.00", "active_days": 30, "hierarchy_node_id": null, "approved_constraint_dates": [], "exempted_duty_type_ids": []}
  ],
  "duties": [
    {"id": "d0000001-0000-0000-0000-000000000001", "duty_type_id": "t0000001-0000-0000-0000-000000000001", "duty_location_id": "l0000001-0000-0000-0000-000000000001", "start_date": "2026-06-01", "end_date": "2026-06-01", "score_per_day": "1.00"},
    {"id": "d0000001-0000-0000-0000-000000000002", "duty_type_id": "t0000001-0000-0000-0000-000000000002", "duty_location_id": "l0000001-0000-0000-0000-000000000002", "start_date": "2026-06-02", "end_date": "2026-06-02", "score_per_day": "1.00"},
    {"id": "d0000001-0000-0000-0000-000000000003", "duty_type_id": "t0000001-0000-0000-0000-000000000001", "duty_location_id": "l0000001-0000-0000-0000-000000000001", "start_date": "2026-06-03", "end_date": "2026-06-04", "score_per_day": "1.00"},
    {"id": "d0000001-0000-0000-0000-000000000004", "duty_type_id": "t0000001-0000-0000-0000-000000000002", "duty_location_id": "l0000001-0000-0000-0000-000000000002", "start_date": "2026-06-05", "end_date": "2026-06-05", "score_per_day": "2.00"},
    {"id": "d0000001-0000-0000-0000-000000000005", "duty_type_id": "t0000001-0000-0000-0000-000000000001", "duty_location_id": "l0000001-0000-0000-0000-000000000001", "start_date": "2026-06-06", "end_date": "2026-06-06", "score_per_day": "1.00"}
  ],
  "existing": [],
  "settings": {"K": "8", "T": 7, "W": 14, "alpha": "1.0", "beta": "2.0", "time_limit_seconds": 30}
}
```

- [ ] **Step 2: Create `density_stress.json`**

```json
{
  "description": "5 soldiers, 15 duties in a tight 7-day window, tests density penalty",
  "soldiers": [
    {"id": "s0000002-0000-0000-0000-000000000001", "enrolled_at": "2026-01-01", "cumulative_score": "0.00", "active_days": 150, "hierarchy_node_id": null, "approved_constraint_dates": [], "exempted_duty_type_ids": []},
    {"id": "s0000002-0000-0000-0000-000000000002", "enrolled_at": "2026-01-01", "cumulative_score": "5.00", "active_days": 150, "hierarchy_node_id": null, "approved_constraint_dates": [], "exempted_duty_type_ids": []},
    {"id": "s0000002-0000-0000-0000-000000000003", "enrolled_at": "2026-01-01", "cumulative_score": "10.00", "active_days": 150, "hierarchy_node_id": null, "approved_constraint_dates": [], "exempted_duty_type_ids": []},
    {"id": "s0000002-0000-0000-0000-000000000004", "enrolled_at": "2026-01-01", "cumulative_score": "3.00", "active_days": 150, "hierarchy_node_id": null, "approved_constraint_dates": [], "exempted_duty_type_ids": []},
    {"id": "s0000002-0000-0000-0000-000000000005", "enrolled_at": "2026-01-01", "cumulative_score": "2.00", "active_days": 150, "hierarchy_node_id": null, "approved_constraint_dates": [], "exempted_duty_type_ids": []}
  ],
  "duties": [
    {"id": "d0000002-0000-0000-0000-000000000001", "duty_type_id": "t0000002-0000-0000-0000-000000000001", "duty_location_id": "l0000002-0000-0000-0000-000000000001", "start_date": "2026-06-01", "end_date": "2026-06-01", "score_per_day": "1.00"},
    {"id": "d0000002-0000-0000-0000-000000000002", "duty_type_id": "t0000002-0000-0000-0000-000000000001", "duty_location_id": "l0000002-0000-0000-0000-000000000001", "start_date": "2026-06-01", "end_date": "2026-06-01", "score_per_day": "1.00"},
    {"id": "d0000002-0000-0000-0000-000000000003", "duty_type_id": "t0000002-0000-0000-0000-000000000001", "duty_location_id": "l0000002-0000-0000-0000-000000000001", "start_date": "2026-06-01", "end_date": "2026-06-01", "score_per_day": "1.00"},
    {"id": "d0000002-0000-0000-0000-000000000004", "duty_type_id": "t0000002-0000-0000-0000-000000000001", "duty_location_id": "l0000002-0000-0000-0000-000000000001", "start_date": "2026-06-02", "end_date": "2026-06-02", "score_per_day": "1.00"},
    {"id": "d0000002-0000-0000-0000-000000000005", "duty_type_id": "t0000002-0000-0000-0000-000000000001", "duty_location_id": "l0000002-0000-0000-0000-000000000001", "start_date": "2026-06-02", "end_date": "2026-06-02", "score_per_day": "1.00"},
    {"id": "d0000002-0000-0000-0000-000000000006", "duty_type_id": "t0000002-0000-0000-0000-000000000002", "duty_location_id": "l0000002-0000-0000-0000-000000000002", "start_date": "2026-06-03", "end_date": "2026-06-03", "score_per_day": "2.00"},
    {"id": "d0000002-0000-0000-0000-000000000007", "duty_type_id": "t0000002-0000-0000-0000-000000000002", "duty_location_id": "l0000002-0000-0000-0000-000000000002", "start_date": "2026-06-03", "end_date": "2026-06-03", "score_per_day": "2.00"},
    {"id": "d0000002-0000-0000-0000-000000000008", "duty_type_id": "t0000002-0000-0000-0000-000000000001", "duty_location_id": "l0000002-0000-0000-0000-000000000001", "start_date": "2026-06-04", "end_date": "2026-06-05", "score_per_day": "1.00"},
    {"id": "d0000002-0000-0000-0000-000000000009", "duty_type_id": "t0000002-0000-0000-0000-000000000002", "duty_location_id": "l0000002-0000-0000-0000-000000000002", "start_date": "2026-06-04", "end_date": "2026-06-04", "score_per_day": "2.00"},
    {"id": "d0000002-0000-0000-0000-000000000010", "duty_type_id": "t0000002-0000-0000-0000-000000000001", "duty_location_id": "l0000002-0000-0000-0000-000000000001", "start_date": "2026-06-05", "end_date": "2026-06-06", "score_per_day": "1.00"},
    {"id": "d0000002-0000-0000-0000-000000000011", "duty_type_id": "t0000002-0000-0000-0000-000000000002", "duty_location_id": "l0000002-0000-0000-0000-000000000002", "start_date": "2026-06-05", "end_date": "2026-06-05", "score_per_day": "2.00"},
    {"id": "d0000002-0000-0000-0000-000000000012", "duty_type_id": "t0000002-0000-0000-0000-000000000001", "duty_location_id": "l0000002-0000-0000-0000-000000000001", "start_date": "2026-06-06", "end_date": "2026-06-06", "score_per_day": "1.00"},
    {"id": "d0000002-0000-0000-0000-000000000013", "duty_type_id": "t0000002-0000-0000-0000-000000000001", "duty_location_id": "l0000002-0000-0000-0000-000000000001", "start_date": "2026-06-06", "end_date": "2026-06-06", "score_per_day": "1.00"},
    {"id": "d0000002-0000-0000-0000-000000000014", "duty_type_id": "t0000002-0000-0000-0000-000000000002", "duty_location_id": "l0000002-0000-0000-0000-000000000002", "start_date": "2026-06-07", "end_date": "2026-06-07", "score_per_day": "2.00"},
    {"id": "d0000002-0000-0000-0000-000000000015", "duty_type_id": "t0000002-0000-0000-0000-000000000001", "duty_location_id": "l0000002-0000-0000-0000-000000000001", "start_date": "2026-06-07", "end_date": "2026-06-07", "score_per_day": "1.00"}
  ],
  "existing": [],
  "settings": {"K": "8", "T": 7, "W": 14, "alpha": "1.0", "beta": "2.0", "time_limit_seconds": 30}
}
```

- [ ] **Step 3: Add property-based and golden tests**

Append to `backend/app/algorithm/tests/test_solver.py`:

```python
import json
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

from app.algorithm.solver import solve
from app.algorithm.types import DutyBlock, ExistingAssignment, SoldierInput, SolverSettings


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("fixture_name", ["small_balanced.json", "density_stress.json"])
def test_golden_fixture(fixture_name):
    path = FIXTURES / fixture_name
    data = json.loads(path.read_text())
    soldiers = [_dict_to_soldier(sd) for sd in data["soldiers"]]
    duties = [_dict_to_duty(dd) for dd in data["duties"]]
    existing = [_dict_to_existing(ed) for ed in data.get("existing", [])]
    settings_dict = data["settings"]
    settings = SolverSettings(
        K=Decimal(settings_dict["K"]),
        T=settings_dict["T"],
        W=settings_dict["W"],
        alpha=Decimal(settings_dict.get("alpha", "1.0")),
        beta=Decimal(settings_dict.get("beta", "2.0")),
        time_limit_seconds=settings_dict.get("time_limit_seconds", 30),
    )

    result = solve(soldiers, duties, existing, settings)
    assert result.status in ("OPTIMAL", "FEASIBLE"), f"{fixture_name}: {result.status}"
    assert len(result.assignments) == len(duties), f"{fixture_name}: {len(result.assignments)} != {len(duties)}"

    # Verify coverage: every duty assigned
    assigned_duty_ids = {a.duty_id for a in result.assignments}
    all_duty_ids = {d.id for d in duties}
    assert assigned_duty_ids == all_duty_ids, "Not all duties assigned"

    # Verify no soldier assigned overlapping duties
    soldier_dates: dict[uuid.UUID, set[date]] = {}
    duty_map = {d.id: d for d in duties}
    for a in result.assignments:
        d = duty_map[a.duty_id]
        dates = set()
        dt = d.start_date
        while dt <= d.end_date:
            if dt in soldier_dates.get(a.soldier_id, set()):
                pytest.fail(f"Overlap: soldier {a.soldier_id} assigned two duties on {dt}")
            dates.add(dt)
            dt += timedelta(days=1)
        soldier_dates.setdefault(a.soldier_id, set()).update(dates)


def _dict_to_soldier(d: dict) -> SoldierInput:
    return SoldierInput(
        id=uuid.UUID(d["id"]),
        enrolled_at=date.fromisoformat(d["enrolled_at"]),
        cumulative_score=Decimal(d["cumulative_score"]),
        active_days=d["active_days"],
        hierarchy_node_id=uuid.UUID(d["hierarchy_node_id"]) if d.get("hierarchy_node_id") else None,
        approved_constraint_dates=[(date.fromisoformat(c[0]), date.fromisoformat(c[1]))
                                    for c in d.get("approved_constraint_dates", [])],
        exempted_duty_type_ids={uuid.UUID(x) for x in d.get("exempted_duty_type_ids", [])},
    )


def _dict_to_duty(d: dict) -> DutyBlock:
    return DutyBlock(
        id=uuid.UUID(d["id"]),
        duty_type_id=uuid.UUID(d["duty_type_id"]),
        duty_location_id=uuid.UUID(d["duty_location_id"]),
        start_date=date.fromisoformat(d["start_date"]),
        end_date=date.fromisoformat(d["end_date"]),
        score_per_day=Decimal(d["score_per_day"]),
    )


def _dict_to_existing(d: dict) -> ExistingAssignment:
    return ExistingAssignment(
        soldier_id=uuid.UUID(d["soldier_id"]),
        duty_type_id=uuid.UUID(d["duty_type_id"]),
        start_date=date.fromisoformat(d["start_date"]),
        end_date=date.fromisoformat(d["end_date"]),
    )


@given(
    st.lists(
        st.builds(
            SoldierInput,
            id=st.uuids(),
            enrolled_at=st.dates(),
            cumulative_score=st.decimals(min_value=0, max_value=100),
            active_days=st.integers(min_value=10, max_value=500),
            exempted_duty_type_ids=st.sets(st.uuids(), max_size=2),
        ),
        min_size=2,
        max_size=6,
    ),
    st.lists(
        st.builds(
            DutyBlock,
            id=st.uuids(),
            duty_type_id=st.uuids(),
            duty_location_id=st.uuids(),
            start_date=st.dates(),
            end_date=st.dates(),
            score_per_day=st.decimals(min_value=1, max_value=5),
        ),
        min_size=1,
        max_size=4,
    ),
)
def test_hypothesis_property(hyp_soldiers, hyp_duties):
    # Skip if there are no eligible soldiers for any duty
    if not _any_eligible(hyp_soldiers, hyp_duties):
        return

    settings = SolverSettings(time_limit_seconds=10)
    result = solve(hyp_soldiers, hyp_duties, [], settings)

    if result.status in ("OPTIMAL", "FEASIBLE"):
        # Coverage
        assert len(result.assignments) == len(hyp_duties)
        # No exempted assignments
        duty_map = {d.id: d for d in hyp_duties}
        soldier_map = {s.id: s for s in hyp_soldiers}
        for a in result.assignments:
            d = duty_map[a.duty_id]
            s = soldier_map[a.soldier_id]
            assert d.duty_type_id not in s.exempted_duty_type_ids


def _any_eligible(soldiers, duties) -> bool:
    for d in duties:
        for s in soldiers:
            if d.duty_type_id not in s.exempted_duty_type_ids:
                return True
    return False
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest backend/app/algorithm/tests/test_solver.py -v --timeout=120`
Expected: All tests pass (basic solve + determinism + no eligible + relaxation + 2 golden fixtures + hypothesis)

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/tests/fixtures/small_balanced.json backend/app/algorithm/tests/fixtures/density_stress.json backend/app/algorithm/tests/test_solver.py
git commit -m "test(algorithm): golden fixtures and property-based tests"
```

---

### Task 8: Lint, type-check, full suite

**Files:** none (verification)

- [ ] **Step 1: Run ruff check**

Run (from `backend/`): `uv run ruff check app/algorithm`
Expected: no errors. Fix any (unused imports, line length) and re-run.

- [ ] **Step 2: Run mypy**

Run (from `backend/`): `uv run mypy app/algorithm`
Expected: no errors. Note: OR-Types types may not ship stubs — if mypy complains, add `# type: ignore[import-untyped]` on the ortools import in `model.py`.

- [ ] **Step 3: Run the full algorithm test suite**

Run (from `backend/`): `uv run pytest app/algorithm/tests -v --timeout=120`
Expected: all tests pass.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "chore(algorithm): lint + type fixes" || echo "nothing to fix"
```
