# Algorithm Run Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After an algorithm run, show per-batch diagnostic details — how the solver split groups, how each batch went (outcome, relaxations, fill counts), per-shift fill status, and an actionable Issues tab that surfaces unfilled shifts and recommends parameter changes.

**Architecture:** Add `BatchResult` / `BatchShiftFill` dataclasses to `types.py`; collect them in `solver.py` during `_decomposed_solve`; post-process in `algorithm_bridge.py` to fill real shift UUIDs and persist; expose via `JobOut` / `ProposalOut` API schemas; replace the single proposals view in `AlgorithmPage.tsx` with a three-tab `AlgorithmJobTabs` component (Proposals · Batches · Issues).

**Tech Stack:** Python dataclasses (algorithm layer), SQLAlchemy JSONB column (DB), FastAPI Pydantic schemas (API), React + Tailwind (frontend), Vitest (frontend tests), pytest (backend tests).

---

## File Map

| File | Change |
|------|--------|
| `backend/app/algorithm/types.py` | Add `BatchShiftFill`, `BatchResult` dataclasses; add `batch_results` field to `SolverResult` |
| `backend/alembic/versions/0045_batch_results.py` | New migration: add `batch_results` JSONB to `algorithm_jobs`; add `batch_index` int to `duty_assignments` |
| `backend/app/db/models.py` | Add `batch_results` and (on `DutyAssignment`) `batch_index` columns |
| `backend/app/algorithm/solver.py` | Collect `BatchResult` per batch in `_decomposed_solve`; populate `SolverResult.batch_results` |
| `backend/app/algorithm/tests/test_solver.py` | Unit test: `_decomposed_solve` returns correct `batch_results` counts |
| `backend/app/services/algorithm_bridge.py` | Post-process shift IDs in `batch_results`; write to `job.batch_results`; stamp `batch_index` on `DutyAssignment` in `persist_results` |
| `backend/app/routes/algorithm.py` | Add `batch_results: list[dict]` to `JobOut`; add `batch_index: int \| None` to `ProposalOut`; populate in `get_job` / `_proposals_for_job` |
| `backend/tests/integration/test_algorithm_routes.py` | Integration test: `GET /algorithm/jobs/{id}` returns `batch_results` and proposals with `batch_index` |
| `frontend/src/api/algorithm.ts` | Add `BatchShiftFill`, `BatchResult` interfaces; add `batch_results` to `AlgorithmJob`; add `batch_index` to `ProposalRow` |
| `frontend/src/components/AlgorithmJobTabs.tsx` | **New** — tab container (Proposals / Batches / Issues) |
| `frontend/src/components/BatchesTab.tsx` | **New** — accordion: component → batch rows → shift fill table |
| `frontend/src/components/IssuesTab.tsx` | **New** — unfilled shifts table + diagnostics bullets + recommendations + re-run button |
| `frontend/src/pages/AlgorithmPage.tsx` | Replace `AlgorithmProposalTable` + `FailurePanel` with `AlgorithmJobTabs` for done/failed jobs |

---

## Task 1: BatchResult dataclasses + SolverResult.batch_results

**Files:**
- Modify: `backend/app/algorithm/types.py`

- [ ] **Step 1: Write the failing test**

```python
# In backend/app/algorithm/tests/test_solver.py — add at end of file

def test_decomposed_solve_returns_batch_results() -> None:
    """_decomposed_solve collects BatchResult with correct counts per batch."""
    from app.algorithm.solver import solve
    from app.algorithm.types import BatchResult

    soldier_ids = [uuid4() for _ in range(3)]
    duty_type_id = uuid4()
    duty_location_id = uuid4()
    soldiers = [
        SoldierInput(
            id=sid,
            enrolled_at=date(2026, 1, 1),
            cumulative_score=Decimal("0"),
            active_days=200,
        )
        for sid in soldier_ids
    ]
    # Two duties far apart → two calendar batches (window=28 days)
    duties = [
        DutyBlock(
            id=uuid4(),
            duty_type_id=duty_type_id,
            duty_location_id=duty_location_id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            score_per_day=Decimal("1.00"),
        ),
        DutyBlock(
            id=uuid4(),
            duty_type_id=duty_type_id,
            duty_location_id=duty_location_id,
            start_date=date(2026, 7, 15),
            end_date=date(2026, 7, 15),
            score_per_day=Decimal("1.00"),
        ),
    ]
    s = SolverSettings(batch_window_days=28)
    result = solve(soldiers, duties, [], s)

    assert len(result.batch_results) >= 2, "expected at least 2 batches for duties 44 days apart"
    for br in result.batch_results:
        assert isinstance(br, BatchResult)
        assert br.duty_count >= 1
        assert br.soldier_count >= 1
        assert br.outcome in ("OPTIMAL", "FEASIBLE", "INFEASIBLE", "CANCELLED")
        assert br.wall_time_seconds >= 0.0
    total_assigned = sum(br.assigned_count for br in result.batch_results)
    assert total_assigned == len(result.assignments)
```

- [ ] **Step 2: Run test to confirm it fails**

```
cd backend
uv run pytest app/algorithm/tests/test_solver.py::test_decomposed_solve_returns_batch_results -v
```
Expected: `AttributeError: ... BatchResult` (type not yet defined).

- [ ] **Step 3: Add BatchShiftFill, BatchResult to types.py and batch_results to SolverResult**

In `backend/app/algorithm/types.py`, add after the `SolverSettings` dataclass and before `Assignment`:

```python
@dataclass
class BatchShiftFill:
    """Per-shift fill summary within one batch."""
    shift_id: uuid.UUID | None  # None until bridge fills it from block_to_shift
    required_count: int
    assigned_count: int


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
```

Then update `SolverResult` to add `batch_results`:

```python
@dataclass
class SolverResult:
    """Complete solver output with status, assignments, and metrics."""
    assignments: list[Assignment]
    status: str
    objective_value: float | None = None
    seed: int = 0
    solver_metrics: dict[str, Any] = field(default_factory=dict)
    relaxed: list[str] = field(default_factory=list)
    batch_results: list[BatchResult] = field(default_factory=list)
```

- [ ] **Step 4: Run test again to confirm it passes**

```
cd backend
uv run pytest app/algorithm/tests/test_solver.py::test_decomposed_solve_returns_batch_results -v
```
Expected: FAIL — `batch_results` field exists now but solver doesn't populate it yet. The assertion `len(result.batch_results) >= 2` will fail with `0 >= 2`. That's expected — Task 3 fixes the solver.

- [ ] **Step 5: Commit**

```
git add backend/app/algorithm/types.py backend/app/algorithm/tests/test_solver.py
git commit -m "feat: add BatchResult/BatchShiftFill dataclasses and SolverResult.batch_results field"
```

---

## Task 2: Alembic migration — batch_results + batch_index columns

**Files:**
- Create: `backend/alembic/versions/0045_batch_results.py`
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Verify existing migration numbering**

```
ls backend/alembic/versions/ | sort | tail -5
```
Expected: last file is `0044_forced_callup_multiplier.py` — confirm 0045 is free.

- [ ] **Step 2: Add DB columns to models.py**

In `backend/app/db/models.py`, in the `AlgorithmJob` class (after `progress_message` around line 555), add:

```python
    batch_results: Mapped[list[Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )
```

In the `DutyAssignment` class (find where `is_reserve` is defined, add after it):

```python
    batch_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
```

You also need to add `Integer` to the sqlalchemy import at the top of models.py if it isn't already imported. Check the existing imports and add it:
```python
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, Text, UniqueConstraint, text
```
(or add `Integer` to the existing import line — look at what's already there).

Also verify `JSONB` is already imported (it's used for `shift_ids` and `settings_json`) — no change needed if so.

- [ ] **Step 3: Create the migration file**

Create `backend/alembic/versions/0045_batch_results.py`:

```python
"""add batch_results to algorithm_jobs and batch_index to duty_assignments

Revision ID: 0045
Revises: 0044
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "algorithm_jobs",
        sa.Column("batch_results", JSONB, nullable=True),
    )
    op.add_column(
        "duty_assignments",
        sa.Column("batch_index", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("duty_assignments", "batch_index")
    op.drop_column("algorithm_jobs", "batch_results")
```

- [ ] **Step 4: Run the migration**

```
cd backend
uv run alembic upgrade head
```
Expected: `Running upgrade 0044 -> 0045, add batch_results to algorithm_jobs and batch_index to duty_assignments`

- [ ] **Step 5: Commit**

```
git add backend/alembic/versions/0045_batch_results.py backend/app/db/models.py
git commit -m "feat: add batch_results JSONB and batch_index int columns via migration 0045"
```

---

## Task 3: solver.py — collect BatchResult per batch

**Files:**
- Modify: `backend/app/algorithm/solver.py`

The goal: inside `_decomposed_solve`, after each call to `_infeasibility_relaxation_chain`, collect timing and counts into a `BatchResult`. The solver only knows `DutyBlock` IDs — `shift_id` stays `None` (the bridge fills it in Task 4).

- [ ] **Step 1: Verify the test from Task 1 still fails for the right reason**

```
cd backend
uv run pytest app/algorithm/tests/test_solver.py::test_decomposed_solve_returns_batch_results -v
```
Expected: FAIL with `assert 0 >= 2` (batch_results list is empty).

- [ ] **Step 2: Update the import in solver.py**

At the top of `backend/app/algorithm/solver.py`, the types import needs `BatchResult` and `BatchShiftFill`. Find the line that imports from `app.algorithm.types` and add them:

```python
from app.algorithm.types import (
    Assignment,
    AssignmentExplanation,
    BatchResult,
    BatchShiftFill,
    DutyBlock,
    ExistingAssignment,
    ExplanationData,
    ReserveEntry,
    ReserveLink,
    SoldierInput,
    SolverResult,
    SolverSettings,
    EFFORT_SCALE,
)
```

(Match whatever is actually imported — just add `BatchResult, BatchShiftFill` to the existing list.)

- [ ] **Step 3: Add timing import**

At the top of `solver.py`, `import time` should already be present or add it:
```python
import time
```

- [ ] **Step 4: Modify _decomposed_solve to collect BatchResult**

In `_decomposed_solve`, the loop starts at line ~207:

```python
    for done, (soldier_idxs, batch) in enumerate(plan, start=1):
```

We need `component_index` too. The plan was built from components; reconstruct component index by tracking it. Currently `plan` is a flat list of `(soldier_idxs, batch_duty_idxs)` with no component index stored. We need to store it during plan construction.

Replace the plan-building section (the `plan: list` declaration and loop) with:

```python
    plan: list[tuple[int, list[int], list[int]]] = []  # (component_index, soldier_idxs, batch_duty_idxs)
    for comp_idx, (duty_idxs, soldier_idxs) in enumerate(components):
        if not soldier_idxs:
            continue
        duty_idxs = sorted(duty_idxs, key=lambda di: (duties[di].start_date, str(duties[di].id)))
        for batch in _calendar_window_batches(duty_idxs, duties, settings.batch_window_days):
            if batch:
                plan.append((comp_idx, soldier_idxs, batch))
```

Then update the loop that uses `plan`:

```python
    batch_results: list[BatchResult] = []
    all_assignments: list[Assignment] = []
    relaxed: list[str] = []
    carry_existing: list[ExistingAssignment] = list(existing)

    for done, (comp_idx, soldier_idxs, batch) in enumerate(plan, start=1):
        sub_soldiers = [work[si] for si in soldier_idxs]
        sub_duties = [duties[di] for di in batch]
        sub_rd: dict[tuple[int, int], int] | None = None
        if reserve_dist is not None:
            sub_rd = {}
            for local_di, gdi in enumerate(batch):
                for i, gsi in enumerate(soldier_idxs):
                    v = reserve_dist.get((gdi, gsi))
                    if v is not None:
                        sub_rd[(local_di, i)] = v

        t0 = time.monotonic()
        res = _infeasibility_relaxation_chain(
            sub_soldiers, sub_duties, carry_existing, batch_settings, sub_rd,
            cancel_event=cancel_event,
        )
        wall_time = time.monotonic() - t0

        if res.status == "CANCELLED":
            return res
        relaxed.extend(res.relaxed)
        all_assignments.extend(res.assignments)

        # Collect batch diagnostic data (shift_id=None — bridge fills real UUIDs)
        assigned_duty_ids = {a.duty_id for a in res.assignments}
        shifts_fill: list[BatchShiftFill] = []
        # Group by DutyBlock ID (each block maps to one shift slot)
        for di in batch:
            block = duties[di]
            shifts_fill.append(BatchShiftFill(
                shift_id=None,
                required_count=1,
                assigned_count=1 if block.id in assigned_duty_ids else 0,
            ))

        batch_results.append(BatchResult(
            batch_index=done - 1,
            component_index=comp_idx,
            date_from=min(duties[di].start_date for di in batch),
            date_to=max(duties[di].end_date for di in batch),
            duty_count=len(batch),
            soldier_count=len(soldier_idxs),
            assigned_count=len(res.assignments),
            unassigned_count=len(batch) - len(res.assignments),
            outcome=res.status,
            relaxations=list(res.relaxed),
            wall_time_seconds=round(wall_time, 3),
            shifts=shifts_fill,
        ))

        # Feed-forward carry
        for a in res.assignments:
            d = duty_by_id[a.duty_id]
            carry_existing.append(ExistingAssignment(
                soldier_id=a.soldier_id, duty_type_id=d.duty_type_id,
                start_date=d.start_date, end_date=d.end_date,
                is_reserve=d.is_reserve,
            ))
            s = soldier_by_id[a.soldier_id]
            s.effort_offset += s.effort_per_milli * _block_score(d)

        if progress_cb:
            progress_cb(done, total)

    all_assignments.sort(key=lambda a: a.duty_id)
    assigned_ids = {a.duty_id for a in all_assignments}
    status = "OPTIMAL" if len(assigned_ids) == len(duties) else "FEASIBLE"
    if not all_assignments and duties:
        status = "INFEASIBLE"
    return SolverResult(
        assignments=all_assignments,
        status=status,
        seed=(settings.seed if settings.seed is not None else DEFAULT_SOLVER_SEED),
        relaxed=relaxed,
        batch_results=batch_results,
    )
```

- [ ] **Step 5: Run the test**

```
cd backend
uv run pytest app/algorithm/tests/test_solver.py::test_decomposed_solve_returns_batch_results -v
```
Expected: PASS.

- [ ] **Step 6: Run full solver test suite**

```
cd backend
uv run pytest app/algorithm/tests/ -v -q
```
Expected: all pass.

- [ ] **Step 7: Commit**

```
git add backend/app/algorithm/solver.py
git commit -m "feat: collect BatchResult per batch in _decomposed_solve"
```

---

## Task 4: algorithm_bridge.py — post-process shift IDs + stamp batch_index

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py`

Two changes:
1. After `solve()` returns, aggregate `BatchShiftFill` entries by shift ID using `block_to_shift_map`, and write the final `batch_results` JSON to `job.batch_results`.
2. In `persist_results`, stamp `DutyAssignment.batch_index` from a new argument.

- [ ] **Step 1: Write the test**

Create `backend/app/services/tests/test_algorithm_bridge_batch.py`:

```python
"""Tests for batch_results post-processing in algorithm_bridge."""
import uuid
from datetime import date
from decimal import Decimal

from app.algorithm.types import (
    Assignment, BatchResult, BatchShiftFill, SolverResult,
)
from app.services.algorithm_bridge import _postprocess_batch_results


def _make_result(block_ids: list[uuid.UUID], shift_id: uuid.UUID) -> SolverResult:
    shifts_fill = [
        BatchShiftFill(shift_id=None, required_count=1, assigned_count=1)
        for _ in block_ids
    ]
    br = BatchResult(
        batch_index=0,
        component_index=0,
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 1),
        duty_count=len(block_ids),
        soldier_count=1,
        assigned_count=len(block_ids),
        unassigned_count=0,
        outcome="OPTIMAL",
        relaxations=[],
        wall_time_seconds=0.1,
        shifts=shifts_fill,
    )
    return SolverResult(
        assignments=[Assignment(duty_id=bid, soldier_id=uuid.uuid4()) for bid in block_ids],
        status="OPTIMAL",
        batch_results=[br],
    )


def test_postprocess_aggregates_by_shift():
    shift_id = uuid.uuid4()
    block_a = uuid.uuid4()
    block_b = uuid.uuid4()
    block_to_shift = {block_a: shift_id, block_b: shift_id}
    result = _make_result([block_a, block_b], shift_id)

    processed = _postprocess_batch_results(result.batch_results, block_to_shift)

    assert len(processed) == 1
    br = processed[0]
    assert len(br.shifts) == 1
    sf = br.shifts[0]
    assert sf.shift_id == shift_id
    assert sf.required_count == 2
    assert sf.assigned_count == 2
```

- [ ] **Step 2: Run test to confirm it fails**

```
cd backend
uv run pytest app/services/tests/test_algorithm_bridge_batch.py -v
```
Expected: `ImportError: cannot import name '_postprocess_batch_results'`

- [ ] **Step 3: Add _postprocess_batch_results helper and update run_algorithm_job**

In `backend/app/services/algorithm_bridge.py`:

**Add helper function** (after `resolve_solver_settings`, before `run_algorithm_job`):

```python
def _postprocess_batch_results(
    batch_results: list,
    block_to_shift: dict[uuid.UUID, uuid.UUID],
) -> list:
    """Replace per-block BatchShiftFill entries with per-shift aggregates.

    The solver emits one BatchShiftFill per DutyBlock (shift_id=None).
    This function groups by real shift UUID and sums required/assigned counts.
    Returns a new list of BatchResult with aggregated shifts.
    """
    from app.algorithm.types import BatchResult, BatchShiftFill
    import dataclasses

    processed = []
    for br in batch_results:
        shift_required: dict[uuid.UUID, int] = {}
        shift_assigned: dict[uuid.UUID, int] = {}
        for sf in br.shifts:
            # sf.shift_id is None — resolve from the block position via block_to_shift.
            # The block itself is not stored in BatchShiftFill; we rely on block_to_shift
            # to contain all block IDs that appear in this batch.  Entries whose block_id
            # is not in block_to_shift are skipped (shouldn't happen in practice).
            pass  # resolved below via block-level grouping
        # Re-group: iterate over shifts fill using the block ordering stored in br.shifts.
        # Since each BatchShiftFill corresponds to one block, we need the block IDs.
        # The bridge must pass block_ids_per_batch for precise mapping; for now we can
        # reconstruct by using all block_to_shift entries that belong to this batch's date range.
        # Simpler approach: the bridge passes block_ids alongside batch_results.
        # We use a different approach: store block_id temporarily in BatchShiftFill.
        # See the solver change in Task 3 — currently shift_id=None and we have no block_id.
        # We update BatchShiftFill to also store block_id temporarily.
        # For now, aggregate over all blocks that map to this batch via date range matching is
        # too fragile. Instead, the solver stores block UUIDs as shift_id temporarily.
        # ACTUAL APPROACH: solver stores block.id in BatchShiftFill.shift_id as a temporary
        # stand-in; this function then replaces block UUIDs with shift UUIDs via block_to_shift.
        for sf in br.shifts:
            if sf.shift_id is None:
                continue
            sid = block_to_shift.get(sf.shift_id, sf.shift_id)
            shift_required[sid] = shift_required.get(sid, 0) + sf.required_count
            shift_assigned[sid] = shift_assigned.get(sid, 0) + sf.assigned_count

        aggregated_shifts = [
            BatchShiftFill(
                shift_id=sid,
                required_count=req,
                assigned_count=shift_assigned.get(sid, 0),
            )
            for sid, req in shift_required.items()
        ]
        processed.append(dataclasses.replace(br, shifts=aggregated_shifts))
    return processed
```

**IMPORTANT:** The approach above requires the solver to store `block.id` in `BatchShiftFill.shift_id` (not `None`) so this function can look it up. Update the solver (Task 3) change: instead of `shift_id=None`, use `shift_id=block.id`.

Go back to `solver.py` and change `_decomposed_solve`'s `BatchShiftFill` creation to:

```python
        shifts_fill: list[BatchShiftFill] = []
        for di in batch:
            block = duties[di]
            shifts_fill.append(BatchShiftFill(
                shift_id=block.id,  # temporary: bridge replaces with real DutyShift UUID
                required_count=1,
                assigned_count=1 if block.id in assigned_duty_ids else 0,
            ))
```

**Also update the test in Task 1** to not assert `sf.shift_id is None` — instead assert it's a UUID.

**In `run_algorithm_job`**, after `result = solve(...)` and before `persist_results(...)`:

```python
                # Post-process batch_results: replace block UUIDs with shift UUIDs
                processed_batch_results = _postprocess_batch_results(
                    result.batch_results, block_to_shift_map
                )

                # Serialise batch_results to JSONB-compatible list of dicts
                import dataclasses as _dc
                def _br_to_dict(br) -> dict:
                    return {
                        "batch_index": br.batch_index,
                        "component_index": br.component_index,
                        "date_from": br.date_from.isoformat(),
                        "date_to": br.date_to.isoformat(),
                        "duty_count": br.duty_count,
                        "soldier_count": br.soldier_count,
                        "assigned_count": br.assigned_count,
                        "unassigned_count": br.unassigned_count,
                        "outcome": br.outcome,
                        "relaxations": br.relaxations,
                        "wall_time_seconds": br.wall_time_seconds,
                        "shifts": [
                            {
                                "shift_id": str(sf.shift_id) if sf.shift_id else None,
                                "required_count": sf.required_count,
                                "assigned_count": sf.assigned_count,
                            }
                            for sf in br.shifts
                        ],
                    }
                job.batch_results = [_br_to_dict(br) for br in processed_batch_results]
```

Add this block immediately before the `explanation_data = build_explanations(...)` call.

Also build an assignment→batch_index lookup to pass to `persist_results`. After the `_br_to_dict` block:

```python
                # Build duty_id → batch_index map for stamping on DutyAssignment rows
                duty_to_batch: dict[uuid.UUID, int] = {}
                for br in processed_batch_results:
                    for a in result.assignments:
                        # match by checking if this assignment's duty was in this batch
                        pass  # use the original batch_results which have batch_index
                # Simpler: iterate result.batch_results (pre-processed, has per-block shifts)
                duty_to_batch = {}
                for br in result.batch_results:
                    for sf in br.shifts:
                        if sf.shift_id is not None:  # sf.shift_id is block.id at this point
                            duty_to_batch[sf.shift_id] = br.batch_index
```

Then update the `persist_results(...)` call to pass `duty_to_batch`:

```python
                persist_results(
                    session,
                    job=job,
                    result=result,
                    explanation_data=explanation_data,
                    duty_blocks=duties,
                    soldier_names=soldier_names,
                    actor_id=actor_id,
                    block_to_shift_map=block_to_shift_map,
                    hierarchy_parent=hier_parent,
                    hierarchy_children=hier_children,
                    soldier_node=soldier_node,
                    duty_to_batch=duty_to_batch,
                )
```

**Update `persist_results` signature** to accept `duty_to_batch` and stamp it:

```python
def persist_results(
    session: Session,
    *,
    job: AlgorithmJob,
    result: SolverResult,
    explanation_data: ExplanationData,
    duty_blocks: list,
    soldier_names: dict[uuid.UUID, str],
    actor_id: uuid.UUID | None,
    block_to_shift_map: dict[uuid.UUID, uuid.UUID] | None = None,
    hierarchy_parent: dict[uuid.UUID, uuid.UUID | None] | None = None,
    hierarchy_children: dict[uuid.UUID, list[uuid.UUID]] | None = None,
    soldier_node: dict[uuid.UUID, uuid.UUID] | None = None,
    duty_to_batch: dict[uuid.UUID, int] | None = None,
) -> None:
```

Inside `persist_results`, in the `for a in result.assignments:` loop where `da` is created, add after `da.id = uuid.uuid4()`:

```python
        if duty_to_batch:
            da.batch_index = duty_to_batch.get(a.duty_id)
```

- [ ] **Step 4: Run the test**

```
cd backend
uv run pytest app/services/tests/test_algorithm_bridge_batch.py -v
```
Expected: PASS.

- [ ] **Step 5: Run solver tests to ensure the block.id change didn't break them**

```
cd backend
uv run pytest app/algorithm/tests/ -v -q
```
Expected: all pass.

- [ ] **Step 6: Commit**

```
git add backend/app/services/algorithm_bridge.py backend/app/algorithm/solver.py backend/app/services/tests/test_algorithm_bridge_batch.py
git commit -m "feat: post-process batch_results shift UUIDs in bridge and stamp batch_index on assignments"
```

---

## Task 5: API schema — JobOut.batch_results + ProposalOut.batch_index

**Files:**
- Modify: `backend/app/routes/algorithm.py`
- Modify: `backend/tests/integration/test_algorithm_routes.py`

- [ ] **Step 1: Write the failing integration test**

In `backend/tests/integration/test_algorithm_routes.py`, add a new test at the end:

```python
def test_get_job_returns_batch_results(client, admin_headers, db_session):
    """GET /algorithm/jobs/{id} returns batch_results list and proposals with batch_index."""
    from app.db.models import AlgorithmJob
    import uuid, json

    # Create a job row with fake batch_results
    job = AlgorithmJob(
        planning_start=date(2026, 6, 1),
        planning_end=date(2026, 6, 30),
        shift_ids=[],
        settings_json={},
        mode="shadow",
        status="done",
        batch_results=[{
            "batch_index": 0,
            "component_index": 0,
            "date_from": "2026-06-01",
            "date_to": "2026-06-30",
            "duty_count": 2,
            "soldier_count": 5,
            "assigned_count": 2,
            "unassigned_count": 0,
            "outcome": "OPTIMAL",
            "relaxations": [],
            "wall_time_seconds": 0.5,
            "shifts": [],
        }],
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    resp = client.get(f"/algorithm/jobs/{job.id}", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "batch_results" in body
    assert len(body["batch_results"]) == 1
    assert body["batch_results"][0]["outcome"] == "OPTIMAL"
    assert body["batch_results"][0]["assigned_count"] == 2
```

- [ ] **Step 2: Run test to confirm it fails**

```
cd backend
uv run pytest tests/integration/test_algorithm_routes.py::test_get_job_returns_batch_results -v
```
Expected: FAIL — `KeyError: 'batch_results'` (field not in JobOut).

- [ ] **Step 3: Update schemas and GET endpoint in algorithm.py**

In `backend/app/routes/algorithm.py`:

Update `ProposalOut`:
```python
class ProposalOut(BaseModel):
    assignment_id: uuid.UUID
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    status: str
    reserve_assignment_id: uuid.UUID | None
    norm_score_before: float | None
    norm_score_after: float | None
    duty_shift_id: uuid.UUID | None = None
    candidate_rank: int | None = None
    candidate_pool_size: int | None = None
    batch_index: int | None = None
```

Update `JobOut`:
```python
class JobOut(BaseModel):
    id: uuid.UUID
    status: str
    mode: str
    planning_start: date
    planning_end: date
    started_at: Any
    finished_at: Any
    error_message: str | None
    progress_message: str | None
    proposals: list[ProposalOut]
    solver_metrics: dict[str, Any]
    relaxed: list[str]
    reasons: list[str]
    batch_results: list[dict] = Field(default_factory=list)
```

Find the `get_job` endpoint (it calls `_proposals_for_job` and constructs `JobOut`). Locate where `JobOut(...)` is constructed and add `batch_results=job.batch_results or []`:

```python
    return JobOut(
        id=job.id,
        status=job.status,
        mode=job.mode,
        planning_start=job.planning_start,
        planning_end=job.planning_end,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_message=job.error_message,
        progress_message=job.progress_message,
        proposals=proposals,
        solver_metrics=metrics,
        relaxed=relaxed,
        reasons=reasons,
        batch_results=job.batch_results or [],
    )
```

Also update `_proposals_for_job` to include `batch_index` in each `ProposalOut`. Find where `ProposalOut(...)` is instantiated and add `batch_index=a.batch_index`:

```python
        out.append(ProposalOut(
            assignment_id=a.id,
            soldier_id=a.soldier_id,
            duty_type_id=a.duty_type_id,
            duty_location_id=a.duty_location_id,
            start_date=a.start_date,
            end_date=a.end_date,
            status=a.status,
            reserve_assignment_id=reserve_id,
            norm_score_before=pre_score,
            norm_score_after=post_score,
            duty_shift_id=a.duty_shift_id,
            candidate_rank=rank,
            candidate_pool_size=pool_size,
            batch_index=a.batch_index,
        ))
```

- [ ] **Step 4: Run the integration test**

```
cd backend
uv run pytest tests/integration/test_algorithm_routes.py::test_get_job_returns_batch_results -v
```
Expected: PASS.

- [ ] **Step 5: Run full integration suite**

```
cd backend
uv run pytest tests/integration/test_algorithm_routes.py -v -q
```
Expected: all pass.

- [ ] **Step 6: Commit**

```
git add backend/app/routes/algorithm.py backend/tests/integration/test_algorithm_routes.py
git commit -m "feat: expose batch_results and batch_index in JobOut/ProposalOut API schemas"
```

---

## Task 6: Frontend types + AlgorithmJobTabs + BatchesTab

**Files:**
- Modify: `frontend/src/api/algorithm.ts`
- Create: `frontend/src/components/AlgorithmJobTabs.tsx`
- Create: `frontend/src/components/BatchesTab.tsx`
- Modify: `frontend/src/pages/AlgorithmPage.tsx`

- [ ] **Step 1: Update frontend types**

In `frontend/src/api/algorithm.ts`, add after `ProposalRow`:

```typescript
export interface BatchShiftFill {
  shift_id: string | null;
  required_count: number;
  assigned_count: number;
}

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
}
```

Update `ProposalRow` to add `batch_index`:
```typescript
export interface ProposalRow {
  assignment_id: string;
  soldier_id: string;
  duty_type_id: string;
  duty_location_id: string;
  start_date: string;
  end_date: string;
  status: string;
  reserve_soldier_id: string | null;
  norm_score_before: number | null;
  norm_score_after: number | null;
  duty_shift_id: string | null;
  candidate_rank: number | null;
  candidate_pool_size: number | null;
  batch_index: number | null;
}
```

Update `AlgorithmJob` to add `batch_results`:
```typescript
export interface AlgorithmJob {
  id: string;
  status: "pending" | "running" | "done" | "failed";
  mode: string;
  planning_start: string;
  planning_end: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  progress_message: string | null;
  proposals: ProposalRow[];
  solver_metrics: Record<string, number>;
  relaxed: string[];
  reasons: string[];
  batch_results: BatchResult[];
}
```

- [ ] **Step 2: Create BatchesTab.tsx**

Create `frontend/src/components/BatchesTab.tsx`:

```tsx
import { useState } from "react";
import { BatchResult } from "../api/algorithm";

interface Props {
  batchResults: BatchResult[];
  shiftNames: Record<string, string>;
}

const OUTCOME_BADGE: Record<string, string> = {
  OPTIMAL: "bg-green-100 dark:bg-green-900 text-green-700 dark:text-green-300",
  FEASIBLE: "bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300",
  INFEASIBLE: "bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300",
  CANCELLED: "bg-gray-100 dark:bg-gray-700 text-gray-500",
};

const OUTCOME_LABEL: Record<string, string> = {
  OPTIMAL: "אופטימלי",
  FEASIBLE: "אפשרי",
  INFEASIBLE: "לא ניתן",
  CANCELLED: "בוטל",
};

export default function BatchesTab({ batchResults, shiftNames }: Props) {
  const [expandedBatch, setExpandedBatch] = useState<number | null>(null);

  if (batchResults.length === 0) {
    return (
      <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-8" dir="rtl">
        אין נתוני אצוות לריצה זו
      </p>
    );
  }

  // Group by component_index
  const byComponent = batchResults.reduce<Record<number, BatchResult[]>>((acc, br) => {
    (acc[br.component_index] ??= []).push(br);
    return acc;
  }, {});

  const componentIndices = Object.keys(byComponent).map(Number).sort((a, b) => a - b);

  return (
    <div className="space-y-4 text-sm" dir="rtl">
      {componentIndices.map(compIdx => {
        const batches = byComponent[compIdx];
        const soldierCount = batches[0]?.soldier_count ?? 0;
        return (
          <div key={compIdx} className="border dark:border-gray-600 rounded-lg overflow-hidden">
            <div className="bg-gray-50 dark:bg-gray-700 px-4 py-2 font-medium text-xs text-gray-700 dark:text-gray-300">
              קבוצה {compIdx + 1} — {soldierCount} חיילים, {batches.length} אצוות
            </div>
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b dark:border-gray-600 text-gray-500 dark:text-gray-400">
                  <th className="px-3 py-2 text-right font-medium">תאריכים</th>
                  <th className="px-3 py-2 text-center font-medium">משבצות</th>
                  <th className="px-3 py-2 text-center font-medium">שובץ</th>
                  <th className="px-3 py-2 text-center font-medium">לא שובץ</th>
                  <th className="px-3 py-2 text-center font-medium">תוצאה</th>
                  <th className="px-3 py-2 text-center font-medium">הרפיות</th>
                  <th className="px-3 py-2 text-center font-medium">זמן</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {batches.map(br => (
                  <>
                    <tr
                      key={br.batch_index}
                      className="border-b dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700/50 cursor-pointer"
                      onClick={() => setExpandedBatch(expandedBatch === br.batch_index ? null : br.batch_index)}
                    >
                      <td className="px-3 py-2 text-right">{br.date_from} – {br.date_to}</td>
                      <td className="px-3 py-2 text-center">{br.duty_count}</td>
                      <td className="px-3 py-2 text-center text-green-700 dark:text-green-400">{br.assigned_count}</td>
                      <td className={`px-3 py-2 text-center ${br.unassigned_count > 0 ? "text-red-600 dark:text-red-400 font-medium" : "text-gray-400"}`}>
                        {br.unassigned_count}
                      </td>
                      <td className="px-3 py-2 text-center">
                        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${OUTCOME_BADGE[br.outcome] ?? OUTCOME_BADGE.CANCELLED}`}>
                          {OUTCOME_LABEL[br.outcome] ?? br.outcome}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-center">
                        {br.relaxations.length > 0
                          ? <span className="text-amber-600 dark:text-amber-400">{br.relaxations.join(", ")}</span>
                          : <span className="text-gray-400">—</span>
                        }
                      </td>
                      <td className="px-3 py-2 text-center text-gray-500">{br.wall_time_seconds}s</td>
                      <td className="px-3 py-2 text-center text-gray-400">
                        {br.shifts.length > 0 ? (expandedBatch === br.batch_index ? "▲" : "▼") : ""}
                      </td>
                    </tr>
                    {expandedBatch === br.batch_index && br.shifts.length > 0 && (
                      <tr key={`${br.batch_index}-detail`}>
                        <td colSpan={8} className="bg-gray-50 dark:bg-gray-900/30 px-4 py-3">
                          <table className="w-full text-xs">
                            <thead>
                              <tr className="text-gray-400 dark:text-gray-500">
                                <th className="text-right pb-1 font-medium">משמרת</th>
                                <th className="text-center pb-1 font-medium">נדרש</th>
                                <th className="text-center pb-1 font-medium">שובץ</th>
                                <th className="text-center pb-1 font-medium">חסר</th>
                              </tr>
                            </thead>
                            <tbody>
                              {br.shifts.map((sf, i) => {
                                const missing = sf.required_count - sf.assigned_count;
                                const name = sf.shift_id ? (shiftNames[sf.shift_id] ?? sf.shift_id.slice(0, 8)) : "—";
                                return (
                                  <tr key={i} className="border-t dark:border-gray-700">
                                    <td className="py-1 text-right">{name}</td>
                                    <td className="py-1 text-center">{sf.required_count}</td>
                                    <td className="py-1 text-center text-green-700 dark:text-green-400">{sf.assigned_count}</td>
                                    <td className={`py-1 text-center ${missing > 0 ? "text-red-600 dark:text-red-400 font-medium" : "text-gray-400"}`}>
                                      {missing > 0 ? missing : "—"}
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 3: Create AlgorithmJobTabs.tsx**

Create `frontend/src/components/AlgorithmJobTabs.tsx`:

```tsx
import { useState } from "react";
import { AlgorithmJob } from "../api/algorithm";
import { DutyType } from "../api/dutyConfig";
import { SoldierDTO } from "../api/soldiers";
import AlgorithmProposalTable from "./AlgorithmProposalTable";
import BatchesTab from "./BatchesTab";
import IssuesTab from "./IssuesTab";

interface Props {
  job: AlgorithmJob;
  jobId: string;
  soldiers: SoldierDTO[];
  dutyTypes: DutyType[];
  onProposalUpdate: (updated: AlgorithmJob) => void;
}

type Tab = "proposals" | "batches" | "issues";

export default function AlgorithmJobTabs({ job, jobId, soldiers, dutyTypes, onProposalUpdate }: Props) {
  const [tab, setTab] = useState<Tab>("proposals");

  const hasAnyUnfilled = job.batch_results.some(br => br.unassigned_count > 0);
  const hasInfeasible = job.batch_results.some(br => br.outcome === "INFEASIBLE");
  const hasIssues = hasAnyUnfilled || hasInfeasible || job.status === "failed";

  const shiftNames: Record<string, string> = {};
  // DutyTypes available but shift names need to be loaded; pass empty map for now
  // (shift names are stored in DutyShift which isn't loaded here — show shift ID prefix)

  const tabs: { id: Tab; label: string; badge?: string }[] = [
    { id: "proposals", label: "הצעות" },
    { id: "batches", label: "אצוות" },
    {
      id: "issues",
      label: "בעיות",
      badge: hasIssues ? "!" : undefined,
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex gap-1 border-b dark:border-gray-600" dir="rtl">
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t.id
                ? "border-indigo-500 text-indigo-600 dark:text-indigo-400"
                : "border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
            }`}
          >
            {t.label}
            {t.badge && (
              <span className="mr-1.5 px-1.5 py-0.5 rounded-full bg-amber-500 text-white text-xs font-bold">
                {t.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {tab === "proposals" && (
        <AlgorithmProposalTable
          job={job}
          jobId={jobId}
          soldiers={soldiers}
          dutyTypes={dutyTypes}
          onProposalUpdate={onProposalUpdate}
          isDraft={job.proposals.some(p => p.status === "algorithm_draft")}
        />
      )}

      {tab === "batches" && (
        <BatchesTab batchResults={job.batch_results} shiftNames={shiftNames} />
      )}

      {tab === "issues" && (
        <IssuesTab
          job={job}
          dutyTypes={dutyTypes}
          shiftNames={shiftNames}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Update AlgorithmPage.tsx to use AlgorithmJobTabs**

In `frontend/src/pages/AlgorithmPage.tsx`:

Add import:
```tsx
import AlgorithmJobTabs from "../components/AlgorithmJobTabs";
```

Remove imports for `AlgorithmProposalTable` and `FailurePanel` (they are now used inside `AlgorithmJobTabs` and `IssuesTab` respectively, so `AlgorithmPage` no longer needs them directly).

Replace the job detail rendering section (the `{selectedJob.status === "failed" && ...}` and `{selectedJob.status === "done" && ...}` blocks) with:

```tsx
            {/* Job detail: tabs for done/failed; legacy plain view for others */}
            {(selectedJob.status === "done" || selectedJob.status === "failed") && (
              <AlgorithmJobTabs
                job={selectedJob}
                jobId={selectedJobId!}
                soldiers={soldiers}
                dutyTypes={dutyTypes}
                onProposalUpdate={setSelectedJob}
              />
            )}
```

- [ ] **Step 5: Run frontend type check**

```
cd frontend
pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 6: Run frontend lint**

```
cd frontend
pnpm lint
```
Expected: exit 0.

- [ ] **Step 7: Add batch column + filter dropdown to AlgorithmProposalTable.tsx**

In `frontend/src/components/AlgorithmProposalTable.tsx`, add:

At the top of the component function, add batch filter state:
```tsx
  const hasBatches = job.proposals.some(p => p.batch_index != null);
  const batchIndices = hasBatches
    ? [...new Set(job.proposals.map(p => p.batch_index).filter((b): b is number => b != null))].sort((a, b) => a - b)
    : [];
  const [batchFilter, setBatchFilter] = useState<number | null>(null);
```

Below the existing filter/sort controls (wherever the table header controls live), add the batch filter dropdown when `hasBatches`:
```tsx
      {hasBatches && (
        <select
          value={batchFilter ?? ""}
          onChange={e => setBatchFilter(e.target.value === "" ? null : Number(e.target.value))}
          className="text-xs border dark:border-gray-600 rounded px-2 py-1 dark:bg-gray-700 dark:text-gray-100"
        >
          <option value="">כל האצוות</option>
          {batchIndices.map(bi => (
            <option key={bi} value={bi}>אצווה {bi + 1}</option>
          ))}
        </select>
      )}
```

Apply the batch filter to the proposals list passed to the table (filter before rendering rows):
```tsx
  const filteredProposals = batchFilter != null
    ? job.proposals.filter(p => p.batch_index === batchFilter)
    : job.proposals;
```
Use `filteredProposals` instead of `job.proposals` when building table rows.

Add a **Batch** column to the proposals table. In the column definitions (wherever `ColDef` objects are built), add:
```tsx
    ...(hasBatches ? [{
      key: "batch_index" as const,
      header: "אצווה",
      render: (p: ProposalRow) => p.batch_index != null
        ? <span className="px-1.5 py-0.5 rounded bg-indigo-100 dark:bg-indigo-900 text-indigo-700 dark:text-indigo-300 text-xs font-mono">B{p.batch_index}</span>
        : <span className="text-gray-400">—</span>,
    }] : []),
```

- [ ] **Step 8: Run frontend type check and lint**

```
cd frontend
pnpm tsc --noEmit && pnpm lint
```
Expected: no errors.

- [ ] **Step 9: Commit**

```
git add frontend/src/api/algorithm.ts frontend/src/components/AlgorithmJobTabs.tsx frontend/src/components/BatchesTab.tsx frontend/src/components/AlgorithmProposalTable.tsx frontend/src/pages/AlgorithmPage.tsx
git commit -m "feat: add AlgorithmJobTabs with BatchesTab, batch column in proposals, and update frontend types"
```

---

## Task 7: IssuesTab — diagnostics + recommendations + re-run button

**Files:**
- Create: `frontend/src/components/IssuesTab.tsx`

This tab has three sections:
1. Partially/fully unfilled shifts table
2. Auto-generated diagnostics bullets
3. Recommendations + "re-run with recommended settings" button

The re-run button needs to call back to `AlgorithmPage` to open the run form with pre-filled settings. The `IssuesTab` is rendered inside `AlgorithmJobTabs` which is rendered inside `AlgorithmPage`. Pass an `onRerun` callback through the chain.

- [ ] **Step 1: Create IssuesTab.tsx**

Create `frontend/src/components/IssuesTab.tsx`:

```tsx
import { AlgorithmJob, BatchResult } from "../api/algorithm";
import { DutyType } from "../api/dutyConfig";
import FailurePanel from "./FailurePanel";

interface Props {
  job: AlgorithmJob;
  dutyTypes: DutyType[];
  shiftNames: Record<string, string>;
  onRerun?: (overrides: Record<string, number>) => void;
}

interface UnfilledShift {
  shiftId: string | null;
  shiftName: string;
  batchIndex: number;
  dateFrom: string;
  dateTo: string;
  required: number;
  assigned: number;
  missing: number;
  reason: string;
}

function collectUnfilledShifts(batchResults: BatchResult[], shiftNames: Record<string, string>): UnfilledShift[] {
  const result: UnfilledShift[] = [];
  for (const br of batchResults) {
    for (const sf of br.shifts) {
      const missing = sf.required_count - sf.assigned_count;
      if (missing <= 0) continue;
      let reason = "לא ידוע";
      if (br.outcome === "INFEASIBLE") reason = "לא ניתן לפתרון";
      else if (br.relaxations.length > 0) reason = "הגיע לתקרת הרפיה";
      else reason = "אין מספיק חיילים כשירים";
      result.push({
        shiftId: sf.shift_id,
        shiftName: sf.shift_id ? (shiftNames[sf.shift_id] ?? sf.shift_id.slice(0, 8)) : "—",
        batchIndex: br.batch_index,
        dateFrom: br.date_from,
        dateTo: br.date_to,
        required: sf.required_count,
        assigned: sf.assigned_count,
        missing,
        reason,
      });
    }
  }
  return result;
}

interface DiagnosticResult {
  rCeilingHitCount: number;
  tCeilingHitCount: number;
  infeasibleCount: number;
  currentRCeiling: number | null;
  currentTCeiling: number | null;
}

function analyzeBatches(batchResults: BatchResult[]): DiagnosticResult {
  let rCeilingHitCount = 0;
  let tCeilingHitCount = 0;
  let infeasibleCount = 0;
  let maxR: number | null = null;
  let maxT: number | null = null;

  for (const br of batchResults) {
    if (br.outcome === "INFEASIBLE") infeasibleCount++;
    for (const rel of br.relaxations) {
      // relaxations look like "R→17" or "T→10"
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

export default function IssuesTab({ job, dutyTypes, shiftNames, onRerun }: Props) {
  const batchResults = job.batch_results ?? [];
  const unfilledShifts = collectUnfilledShifts(batchResults, shiftNames);
  const diagnostics = analyzeBatches(batchResults);

  const hasAnyIssue =
    unfilledShifts.length > 0 ||
    diagnostics.infeasibleCount > 0 ||
    job.status === "failed";

  const recommendations: { label: string; key: string; value: number }[] = [];
  if (diagnostics.rCeilingHitCount > 0 && diagnostics.currentRCeiling !== null) {
    recommendations.push({
      label: `הגדל relax_r_ceiling ל-${diagnostics.currentRCeiling + 4}`,
      key: "relax_r_ceiling",
      value: diagnostics.currentRCeiling + 4,
    });
  }
  if (diagnostics.tCeilingHitCount > 0 && diagnostics.currentTCeiling !== null) {
    recommendations.push({
      label: `הגדל relax_t_ceiling ל-${diagnostics.currentTCeiling + 2}`,
      key: "relax_t_ceiling",
      value: diagnostics.currentTCeiling + 2,
    });
  }

  if (!hasAnyIssue) {
    return (
      <p className="text-sm text-green-600 dark:text-green-400 text-center py-8" dir="rtl">
        ✓ לא נמצאו בעיות בריצה זו
      </p>
    );
  }

  return (
    <div className="space-y-6 text-sm" dir="rtl">
      {/* Section 1: Failed state from old FailurePanel */}
      {job.status === "failed" && job.error_message !== "cancelled_by_user" && (
        <FailurePanel relaxed={job.relaxed} reasons={job.reasons} />
      )}

      {/* Section 2: Unfilled shifts */}
      {unfilledShifts.length > 0 && (
        <div>
          <h3 className="font-semibold mb-2 text-gray-800 dark:text-gray-200">
            משמרות לא מאוישות במלואן
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs border dark:border-gray-600 rounded">
              <thead className="bg-gray-50 dark:bg-gray-700">
                <tr className="text-gray-500 dark:text-gray-400">
                  <th className="px-3 py-2 text-right font-medium">משמרת</th>
                  <th className="px-3 py-2 text-center font-medium">תאריכים</th>
                  <th className="px-3 py-2 text-center font-medium">נדרש</th>
                  <th className="px-3 py-2 text-center font-medium">שובץ</th>
                  <th className="px-3 py-2 text-center font-medium text-red-600 dark:text-red-400">חסר</th>
                  <th className="px-3 py-2 text-center font-medium">אצווה</th>
                  <th className="px-3 py-2 text-right font-medium">סיבה</th>
                </tr>
              </thead>
              <tbody>
                {unfilledShifts.map((sf, i) => (
                  <tr key={i} className="border-t dark:border-gray-700">
                    <td className="px-3 py-1.5 text-right">{sf.shiftName}</td>
                    <td className="px-3 py-1.5 text-center">{sf.dateFrom} – {sf.dateTo}</td>
                    <td className="px-3 py-1.5 text-center">{sf.required}</td>
                    <td className="px-3 py-1.5 text-center text-green-700 dark:text-green-400">{sf.assigned}</td>
                    <td className="px-3 py-1.5 text-center text-red-600 dark:text-red-400 font-medium">{sf.missing}</td>
                    <td className="px-3 py-1.5 text-center text-gray-500">B{sf.batchIndex}</td>
                    <td className="px-3 py-1.5 text-right text-gray-600 dark:text-gray-400">{sf.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Section 3: Diagnostics */}
      {(diagnostics.rCeilingHitCount > 0 || diagnostics.tCeilingHitCount > 0 || diagnostics.infeasibleCount > 0) && (
        <div>
          <h3 className="font-semibold mb-2 text-gray-800 dark:text-gray-200">אבחון</h3>
          <ul className="space-y-1 text-gray-700 dark:text-gray-300 text-xs">
            {diagnostics.rCeilingHitCount > 0 && diagnostics.currentRCeiling !== null && (
              <li>⚠ {diagnostics.rCeilingHitCount} אצוות הגיעו לתקרת R ({diagnostics.currentRCeiling}) — שקול להגדיל</li>
            )}
            {diagnostics.tCeilingHitCount > 0 && diagnostics.currentTCeiling !== null && (
              <li>⚠ {diagnostics.tCeilingHitCount} אצוות הגיעו לתקרת T ({diagnostics.currentTCeiling}) — שקול להגדיל</li>
            )}
            {diagnostics.infeasibleCount > 0 && (
              <li>✗ {diagnostics.infeasibleCount} אצוות נשארו ללא פתרון — ייתכן שאין מספיק חיילים כשירים</li>
            )}
          </ul>
        </div>
      )}

      {/* Section 4: Recommendations + re-run */}
      {recommendations.length > 0 && onRerun && (
        <div>
          <h3 className="font-semibold mb-2 text-gray-800 dark:text-gray-200">המלצות</h3>
          <ul className="space-y-1 text-xs text-gray-700 dark:text-gray-300 mb-3">
            {recommendations.map((r, i) => (
              <li key={i}>→ {r.label}</li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => onRerun(Object.fromEntries(recommendations.map(r => [r.key, r.value])))}
            className="px-4 py-2 bg-indigo-600 text-white text-xs rounded hover:bg-indigo-700"
          >
            הרץ שוב עם הגדרות מומלצות
          </button>
        </div>
      )}

      {diagnostics.infeasibleCount > 0 && recommendations.length === 0 && (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          לא ניתן להציע שינוי פרמטרים — ייתכן שחסרים חיילים כשירים לחלק מהמשמרות.
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Wire onRerun through the component chain**

In `AlgorithmJobTabs.tsx`, update `Props` and pass `onRerun` down to `IssuesTab`:

```tsx
interface Props {
  job: AlgorithmJob;
  jobId: string;
  soldiers: SoldierDTO[];
  dutyTypes: DutyType[];
  onProposalUpdate: (updated: AlgorithmJob) => void;
  onRerun?: (overrides: Record<string, number>) => void;
}
```

In the render, pass `onRerun` to `IssuesTab`:
```tsx
      {tab === "issues" && (
        <IssuesTab
          job={job}
          dutyTypes={dutyTypes}
          shiftNames={shiftNames}
          onRerun={onRerun}
        />
      )}
```

In `AlgorithmPage.tsx`, pass `onRerun` to `AlgorithmJobTabs`. First add state for pre-filled settings overrides:

```tsx
  const [rerunOverrides, setRerunOverrides] = useState<Record<string, number> | null>(null);

  function handleRerun(overrides: Record<string, number>) {
    setRerunOverrides(overrides);
    setShowRunForm(true);
  }
```

Pass to `AlgorithmJobTabs`:
```tsx
              <AlgorithmJobTabs
                job={selectedJob}
                jobId={selectedJobId!}
                soldiers={soldiers}
                dutyTypes={dutyTypes}
                onProposalUpdate={setSelectedJob}
                onRerun={handleRerun}
              />
```

Update `AlgorithmRunForm` to accept `initialOverrides?: Record<string, number>` and apply them. In `AlgorithmRunForm.tsx`, update `Props`:

```typescript
interface Props {
  dutyTypes: DutyType[];
  onJobSubmitted: (jobId: string) => void;
  initialOverrides?: Record<string, number>;
}
```

In the component body, add a `useEffect` that applies overrides when they change:

```typescript
  useEffect(() => {
    if (initialOverrides && Object.keys(initialOverrides).length > 0) {
      setSettings(s => ({ ...s, ...initialOverrides }));
      setShowSettings(true);
    }
  }, [initialOverrides]);
```

Pass `initialOverrides={rerunOverrides ?? undefined}` when rendering `AlgorithmRunForm` in `AlgorithmPage.tsx`.

Also reset overrides when the drawer closes:
```tsx
  function handleCloseRunForm() {
    setShowRunForm(false);
    setRerunOverrides(null);
  }
```
Replace `onClick={() => setShowRunForm(false)}` with `onClick={handleCloseRunForm}`.

- [ ] **Step 3: Run frontend type check and lint**

```
cd frontend
pnpm tsc --noEmit && pnpm lint
```
Expected: no errors.

- [ ] **Step 4: Commit**

```
git add frontend/src/components/IssuesTab.tsx frontend/src/components/AlgorithmJobTabs.tsx frontend/src/pages/AlgorithmPage.tsx frontend/src/components/AlgorithmRunForm.tsx
git commit -m "feat: add IssuesTab with diagnostics, recommendations, and re-run button"
```

---

## Task 8: Final verification

- [ ] **Step 1: Run full backend test suite**

```
cd backend
uv run pytest -q
```
Expected: all tests pass (no failures).

- [ ] **Step 2: Run frontend tests and lint**

```
cd frontend
pnpm test --run && pnpm lint
```
Expected: all pass, 0 lint warnings.

- [ ] **Step 3: Manual smoke test**

Start the dev server:
```
.\dev.ps1 -NoBot
```

1. Navigate to http://localhost:5173/algorithm
2. Run the algorithm on a set of shifts
3. When the run completes, verify:
   - Three tabs appear: הצעות / אצוות / בעיות
   - Proposals tab shows existing proposals with batch column if batch_index is set
   - Batches tab shows component accordion with batch rows and correct dates/counts
   - Issues tab: if any shift is unfilled, shows the unfilled shifts table and diagnostics
4. For a run with legacy data (no batch_results), verify Batches tab shows "אין נתוני אצוות לריצה זו"

- [ ] **Step 4: Final commit**

```
git add -A
git commit -m "chore: algorithm run diagnostics — final cleanup"
```

---

## Implementation Notes

**Tricky: BatchShiftFill.shift_id temporary use**
The solver has no DB access; it stores `block.id` in `BatchShiftFill.shift_id` as a temporary stand-in. The bridge's `_postprocess_batch_results` replaces these block UUIDs with real DutyShift UUIDs using `block_to_shift_map`. This is a deliberate two-pass design.

**Legacy jobs**
`job.batch_results` is `None` for jobs created before this feature. The API returns `[]` (empty list). All frontend components handle empty `batch_results` gracefully with a "no data" message.

**INFEASIBLE job vs partially-filled**
A job with `status=="failed"` and `error_message` containing `"INFEASIBLE"` was entirely infeasible (old path — bridge sets `job.status="failed"` before `persist_results`). The new path emits a `done` job with some `BatchResult.outcome=="INFEASIBLE"` for individual batches where relaxation failed. Both cases are surfaced in the Issues tab.
