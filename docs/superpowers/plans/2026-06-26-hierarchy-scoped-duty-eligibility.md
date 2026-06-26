# Hierarchy-Scoped Duty Eligibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a DM restrict a duty type, shift template, or individual shift to specific hierarchy nodes (e.g. ענף פוקוס), with subtree-aware eligibility matching, replacing today's broken exact-node-match.

**Architecture:** Add `eligible_node_ids` to `DutyType` and `ShiftTemplate` (mirroring the column that already exists on `DutyShift`). Replace every inline exact-match eligibility check with a single shared `node_in_scope()` helper that does ancestry (`path_ids`) matching and excludes soldiers with no hierarchy node when a scope is set. Manual-creation UI flows (duty type, template, standalone shift) get the cascade default in the **frontend** by pre-filling the picker from the parent's value when the modal opens; the only **backend** cascade copy is template→generated-shift, since that path has no per-instance form.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), CP-SAT via OR-Tools (algorithm), React + TypeScript + i18next (frontend), pytest (backend tests).

Spec: [docs/superpowers/specs/2026-06-25-hierarchy-scoped-duty-eligibility-design.md](../specs/2026-06-25-hierarchy-scoped-duty-eligibility-design.md)

---

## Task 1: Add `node_in_scope()` helper and `path_ids` on `SoldierInput`

**Files:**
- Modify: `backend/app/algorithm/types.py:15-27` (SoldierInput dataclass), append helper function near top
- Test: `backend/app/algorithm/tests/test_types.py` (new file)

- [ ] **Step 1: Write the failing test**

```python
# backend/app/algorithm/tests/test_types.py
from __future__ import annotations

import uuid

from app.algorithm.types import node_in_scope


def test_node_in_scope_none_scope_means_unrestricted() -> None:
    assert node_in_scope(None, [uuid.uuid4()]) is True
    assert node_in_scope(None, []) is True


def test_node_in_scope_exact_node_match() -> None:
    node = uuid.uuid4()
    assert node_in_scope([node], [node]) is True


def test_node_in_scope_descendant_matches_ancestor_scope() -> None:
    root = uuid.uuid4()
    child = uuid.uuid4()
    # soldier's path_ids includes every ancestor up to itself (materialized path)
    assert node_in_scope([root], [root, child]) is True


def test_node_in_scope_unrelated_node_does_not_match() -> None:
    scoped = uuid.uuid4()
    other_root = uuid.uuid4()
    other_child = uuid.uuid4()
    assert node_in_scope([scoped], [other_root, other_child]) is False


def test_node_in_scope_unassigned_soldier_excluded_when_scope_set() -> None:
    assert node_in_scope([uuid.uuid4()], []) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/algorithm/tests/test_types.py -v`
Expected: FAIL with `ImportError: cannot import name 'node_in_scope'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/algorithm/types.py`, add this function right after the `EFFORT_SCALE` constant (before the `SoldierInput` dataclass, line 14):

```python
def node_in_scope(scope_node_ids: list[uuid.UUID] | None, soldier_path_ids: list[uuid.UUID]) -> bool:
    """True if a soldier is within an eligibility scope.

    `scope_node_ids` is None for "unrestricted" (everyone matches). Otherwise a
    soldier matches if any scoped node is itself or an ancestor of it —
    `soldier_path_ids` is the materialized root-to-self path (see
    HierarchyNode.path_ids), so this is a plain set-intersection subtree check.
    A soldier with no hierarchy node (empty path_ids) never matches a set scope.
    """
    if scope_node_ids is None:
        return True
    return any(n in soldier_path_ids for n in scope_node_ids)
```

Then add a `path_ids` field to `SoldierInput` (after `hierarchy_node_id` on line 22):

```python
@dataclass
class SoldierInput:
    """A soldier eligible for duty assignment."""
    id: uuid.UUID
    enrolled_at: date
    cumulative_score: Decimal
    active_days: int
    hierarchy_node_id: uuid.UUID | None = None
    path_ids: list[uuid.UUID] = field(default_factory=list)
    approved_constraint_dates: list[tuple[date, date]] = field(default_factory=list)
    exempted_duty_type_ids: set[uuid.UUID] = field(default_factory=set)
    # Effort-based fairness fields (set by algorithm_bridge after loading duty blocks)
    effort_offset: int = 0      # int(effort_score × EFFORT_SCALE) — historical quarterly share
    effort_per_milli: int = 0   # int(C_over_D / unit_score_milli × EFFORT_SCALE) — per-milli contribution
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/algorithm/tests/test_types.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/types.py backend/app/algorithm/tests/test_types.py
git commit -m "feat: add subtree-aware node_in_scope helper and SoldierInput.path_ids"
```

---

## Task 2: Wire `node_in_scope()` into the solver's component decomposition

**Files:**
- Modify: `backend/app/algorithm/solver.py:175-177`
- Test: `backend/app/algorithm/tests/test_solver.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/app/algorithm/tests/test_solver.py`:

```python
def test_eligible_pairs_subtree_match() -> None:
    """A soldier in a sub-team under a scoped node is eligible (subtree match,
    not exact match)."""
    from app.algorithm.solver import _eligible_pairs

    root = uuid4()
    child = uuid4()
    s_in_subtree = uuid4()
    s_outside = uuid4()
    s_unassigned = uuid4()
    dt = uuid4()

    soldiers = [
        SoldierInput(id=s_in_subtree, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=child, path_ids=[root, child]),
        SoldierInput(id=s_outside, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=uuid4(), path_ids=[uuid4()]),
        SoldierInput(id=s_unassigned, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=None, path_ids=[]),
    ]
    duty = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=uuid4(),
                      start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                      score_per_day=Decimal("1"), eligible_node_ids=[root])

    pairs = _eligible_pairs(soldiers, [duty])
    eligible_soldier_idxs = {si for _, si in pairs}
    assert eligible_soldier_idxs == {0}  # only s_in_subtree (idx 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/algorithm/tests/test_solver.py::test_eligible_pairs_subtree_match -v`
Expected: FAIL — `eligible_soldier_idxs` includes `{0, 1, 2}` (today's exact-match-only check lets everyone through because `s.hierarchy_node_id not in d.eligible_node_ids` is the only guard, and it doesn't even exclude the unassigned soldier).

- [ ] **Step 3: Write minimal implementation**

In `backend/app/algorithm/solver.py`, replace lines 175-177:

```python
            if d.eligible_node_ids is not None and s.hierarchy_node_id is not None:
                if s.hierarchy_node_id not in d.eligible_node_ids:
                    continue
```

with:

```python
            if not node_in_scope(d.eligible_node_ids, s.path_ids):
                continue
```

Add `node_in_scope` to the existing `from app.algorithm.types import (...)` block at the top of the file (after `ExistingAssignment`, alphabetical with the rest):

```python
from app.algorithm.types import (
    Assignment,
    BatchResult,
    BatchShiftFill,
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverResult,
    SolverSettings,
    node_in_scope,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/algorithm/tests/test_solver.py::test_eligible_pairs_subtree_match -v`
Expected: PASS

- [ ] **Step 5: Run the full solver test file to check for regressions**

Run: `cd backend && pytest app/algorithm/tests/test_solver.py -v`
Expected: All PASS (existing reserve-distance tests at lines ~425-516 use soldiers with no `path_ids` set, which defaults to `[]` via `field(default_factory=list)` — they don't set `eligible_node_ids` on their duties, so `node_in_scope` always returns `True` for them and behavior is unchanged)

- [ ] **Step 6: Commit**

```bash
git add backend/app/algorithm/solver.py backend/app/algorithm/tests/test_solver.py
git commit -m "fix: subtree-aware eligibility matching in solver component decomposition"
```

---

## Task 3: Wire `node_in_scope()` into `build_model`'s eligibility pre-filter

**Files:**
- Modify: `backend/app/algorithm/model.py:317-332`
- Test: `backend/app/algorithm/tests/test_solver.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/app/algorithm/tests/test_solver.py`:

```python
def test_solve_excludes_soldier_outside_scope() -> None:
    """End-to-end: a duty scoped to one branch is never assigned to a soldier
    from a different branch, even if that soldier is otherwise idle."""
    root_a = uuid4()
    root_b = uuid4()
    s_in_scope = uuid4()
    s_out_of_scope = uuid4()
    dt = uuid4()
    loc = uuid4()

    soldiers = [
        SoldierInput(id=s_in_scope, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=root_a, path_ids=[root_a]),
        SoldierInput(id=s_out_of_scope, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=root_b, path_ids=[root_b]),
    ]
    duty = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                      start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                      score_per_day=Decimal("1"), eligible_node_ids=[root_a])

    result = solve(soldiers, [duty], [], SolverSettings(time_limit_seconds=10, batching_enabled=False))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1
    assert result.assignments[0].soldier_id == s_in_scope
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/algorithm/tests/test_solver.py::test_solve_excludes_soldier_outside_scope -v`
Expected: FAIL — `build_model`'s pre-filter currently lets `s_out_of_scope` through too (exact-match check with `s.hierarchy_node_id not in d.eligible_node_ids`, where `root_b not in [root_a]` is True, so it should actually already exclude it correctly here since this is an exact match case... but to actually prove subtree fix, the assertion that matters is in Task 2; this test mainly proves `build_model`'s path is wired through `node_in_scope` too, not regressed). If it unexpectedly passes already, proceed directly to Step 3 to do the wiring anyway (required for Task 4's subtree case) and re-run to confirm still passes.

- [ ] **Step 3: Write minimal implementation**

In `backend/app/algorithm/model.py`, replace lines 327-329:

```python
            if d.eligible_node_ids is not None and s.hierarchy_node_id is not None:
                if s.hierarchy_node_id not in d.eligible_node_ids:
                    continue
```

with:

```python
            if not node_in_scope(d.eligible_node_ids, s.path_ids):
                continue
```

Add `node_in_scope` to the existing import block at the top of the file:

```python
from app.algorithm.types import (
    EFFORT_SCALE,
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverSettings,
    node_in_scope,
)
```

- [ ] **Step 4: Add a subtree-match end-to-end case and verify**

Append a second test to `backend/app/algorithm/tests/test_solver.py`:

```python
def test_solve_subtree_match_end_to_end() -> None:
    """A soldier in a sub-team under the scoped node is assignable; one outside
    the subtree, with no other duties competing, is not."""
    root = uuid4()
    child = uuid4()
    s_in_subtree = uuid4()
    s_outside = uuid4()
    dt = uuid4()
    loc = uuid4()

    soldiers = [
        SoldierInput(id=s_in_subtree, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=child, path_ids=[root, child]),
        SoldierInput(id=s_outside, enrolled_at=date(2026, 1, 1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=uuid4(), path_ids=[uuid4()]),
    ]
    duty = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                      start_date=date(2026, 6, 1), end_date=date(2026, 6, 1),
                      score_per_day=Decimal("1"), eligible_node_ids=[root])

    result = solve(soldiers, [duty], [], SolverSettings(time_limit_seconds=10, batching_enabled=False))
    assert result.status in ("OPTIMAL", "FEASIBLE")
    assert len(result.assignments) == 1
    assert result.assignments[0].soldier_id == s_in_subtree
```

Run: `cd backend && pytest app/algorithm/tests/test_solver.py -k "scope or subtree" -v`
Expected: All PASS

- [ ] **Step 5: Run the full algorithm test suite for regressions**

Run: `cd backend && pytest -m algorithm -q`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/algorithm/model.py backend/app/algorithm/tests/test_solver.py
git commit -m "fix: subtree-aware eligibility matching in build_model pre-filter"
```

---

## Task 4: Populate `SoldierInput.path_ids` in `load_soldier_inputs`

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py:126-254`
- Test: `backend/app/services/tests/test_algorithm_bridge.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/app/services/tests/test_algorithm_bridge.py`:

```python
def test_load_soldier_inputs_populates_path_ids(admin_session):
    from datetime import date as _date
    from app.services.algorithm_bridge import load_soldier_inputs
    from tests.helpers import create_node, create_soldier

    root = create_node(admin_session, level="division", name="div_pathids")
    child = create_node(admin_session, level="unit", name="unit_pathids", parent=root)
    soldier = create_soldier(admin_session, personal_number="pathids_1", hierarchy_node_id=child.id)
    admin_session.commit()

    inputs = load_soldier_inputs(admin_session, as_of=_date(2026, 6, 1))
    by_id = {s.id: s for s in inputs}
    assert by_id[soldier.id].path_ids == [root.id, child.id]


def test_load_soldier_inputs_unassigned_soldier_has_empty_path_ids(admin_session):
    from datetime import date as _date
    from app.services.algorithm_bridge import load_soldier_inputs
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="pathids_2")
    admin_session.commit()

    inputs = load_soldier_inputs(admin_session, as_of=_date(2026, 6, 1))
    by_id = {s.id: s for s in inputs}
    assert by_id[soldier.id].path_ids == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_algorithm_bridge.py -k path_ids -v`
Expected: FAIL — `path_ids == []` assertion fails for the assigned soldier (actual is `[]` since nothing populates it yet, so actually it's the first test that fails: `by_id[soldier.id].path_ids == [root.id, child.id]` fails since actual is `[]`)

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/algorithm_bridge.py`, inside `load_soldier_inputs` (around line 128, right after the `soldiers = (...)` query), add a lookup map:

```python
    node_path_map: dict[uuid.UUID, list[uuid.UUID]] = {
        n.id: list(n.path_ids)
        for n in session.execute(select(HierarchyNode.id, HierarchyNode.path_ids)).all()
    }
```

Then in the `result.append(SoldierInput(...))` block (around line 244-253), add the `path_ids` argument:

```python
        result.append(
            SoldierInput(
                id=s.id,
                enrolled_at=s.enrolled_at,
                cumulative_score=cum,
                active_days=ad,
                hierarchy_node_id=s.hierarchy_node_id,
                path_ids=node_path_map.get(s.hierarchy_node_id, []) if s.hierarchy_node_id else [],
                approved_constraint_dates=soldier_constraints.get(s.id, []),
                exempted_duty_type_ids=combined_exempt,
            )
        )
```

Note: `session.execute(select(HierarchyNode.id, HierarchyNode.path_ids)).all()` returns `Row` tuples — `n.id` and `n.path_ids` work via Row's attribute access since both are named columns.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_algorithm_bridge.py -k path_ids -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run full algorithm_bridge test suite for regressions**

Run: `cd backend && pytest app/services/tests/test_algorithm_bridge.py app/services/tests/test_algorithm_bridge_batch.py app/services/tests/test_algorithm_bridge_persist.py -q`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/algorithm_bridge.py backend/app/services/tests/test_algorithm_bridge.py
git commit -m "feat: populate SoldierInput.path_ids in load_soldier_inputs"
```

---

## Task 5: Add `eligible_node_ids` columns to `DutyType` and `ShiftTemplate`

**Files:**
- Modify: `backend/app/db/models.py:140-171` (DutyType), `backend/app/db/models.py:386-419` (ShiftTemplate)
- Create: `backend/alembic/versions/<auto>_add_eligible_node_ids_to_duty_types_and_templates.py`

- [ ] **Step 1: Add the columns to the models**

In `backend/app/db/models.py`, add to `DutyType` (after `instructions`, before `created_at`, i.e. after line 169):

```python
    eligible_node_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True, default=None
    )
```

Add to `ShiftTemplate` (after `notes`, before `created_by`, i.e. after line 409):

```python
    eligible_node_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True, default=None
    )
```

(`ARRAY` and `UUID` are already imported in this file — `DutyShift.eligible_node_ids` uses the identical type at line ~377.)

- [ ] **Step 2: Generate the migration**

Run: `cd backend && alembic revision -m "add eligible_node_ids to duty_types and shift_templates"`

This creates a new file under `backend/alembic/versions/` with an auto-generated revision id and `down_revision = "0059"` (the current head). Open it and replace the `upgrade`/`downgrade` bodies:

```python
def upgrade() -> None:
    op.add_column(
        "duty_types",
        sa.Column("eligible_node_ids", postgresql.ARRAY(sa.UUID(as_uuid=True)), nullable=True),
    )
    op.add_column(
        "shift_templates",
        sa.Column("eligible_node_ids", postgresql.ARRAY(sa.UUID(as_uuid=True)), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shift_templates", "eligible_node_ids")
    op.drop_column("duty_types", "eligible_node_ids")
```

Ensure the file's imports include `from sqlalchemy.dialects import postgresql` (matching `36d8af34a3d6_add_eligible_node_ids_to_duty_shifts.py`'s pattern) — `alembic revision` scaffolds the imports for you, but double check `postgresql` is present; add it if not.

- [ ] **Step 3: Apply the migration**

Run: `cd backend && alembic upgrade head`
Expected: Output ends with the new revision id, no errors.

- [ ] **Step 4: Verify the columns exist**

Run: `cd backend && python -c "from app.db.models import DutyType, ShiftTemplate; print(DutyType.eligible_node_ids, ShiftTemplate.eligible_node_ids)"`
Expected: Prints both column descriptors without raising.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/
git commit -m "feat: add eligible_node_ids column to DutyType and ShiftTemplate"
```

---

## Task 6: `DutyType` service + route support for `eligible_node_ids`

**Files:**
- Modify: `backend/app/services/duty_config.py:24-73` (create_duty_type), `:76-146` (update_duty_type)
- Modify: `backend/app/routes/duty_config.py:32-46` (DutyTypeOut), `:49-68` (CreateDutyTypeRequest), `:70-91` (UpdateDutyTypeRequest), `:93-109` (_dt_out), `:119-146` (create_duty_type), `:148-183` (update_duty_type)
- Test: `backend/app/services/tests/test_duty_config.py` (new file)

- [ ] **Step 1: Write the failing test**

```python
# backend/app/services/tests/test_duty_config.py
from __future__ import annotations

from decimal import Decimal

from app.services.duty_config import create_duty_type, update_duty_type
from tests.helpers import create_node


def test_create_duty_type_with_eligible_node_ids(admin_session):
    node = create_node(admin_session, level="division", name="div_dt1")
    dt = create_duty_type(
        admin_session,
        name="dt_with_scope",
        score_per_day=Decimal("1.00"),
        eligible_node_ids=[node.id],
    )
    admin_session.commit()
    assert dt.eligible_node_ids == [node.id]


def test_create_duty_type_without_eligible_node_ids_defaults_to_none(admin_session):
    dt = create_duty_type(admin_session, name="dt_unscoped", score_per_day=Decimal("1.00"))
    admin_session.commit()
    assert dt.eligible_node_ids is None


def test_update_duty_type_sets_and_clears_eligible_node_ids(admin_session):
    node = create_node(admin_session, level="division", name="div_dt2")
    dt = create_duty_type(admin_session, name="dt_update_scope", score_per_day=Decimal("1.00"))
    admin_session.commit()

    update_duty_type(
        admin_session, duty_type=dt, name=None, score_per_day=None, description=None,
        eligible_node_ids=[node.id],
    )
    admin_session.commit()
    assert dt.eligible_node_ids == [node.id]

    update_duty_type(
        admin_session, duty_type=dt, name=None, score_per_day=None, description=None,
        eligible_node_ids=None,
    )
    admin_session.commit()
    assert dt.eligible_node_ids is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_duty_config.py -v`
Expected: FAIL — `TypeError: create_duty_type() got an unexpected keyword argument 'eligible_node_ids'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/duty_config.py`, add `eligible_node_ids` to `create_duty_type`'s signature (after `is_external: bool = False,` on line 37):

```python
    is_external: bool = False,
    eligible_node_ids: list[uuid.UUID] | None = None,
    actor_id: uuid.UUID | None = None,
```

and pass it into the `DutyType(...)` constructor (after `is_external=is_external,` on line 55):

```python
        is_external=is_external,
        eligible_node_ids=eligible_node_ids,
```

For `update_duty_type`, use a sentinel so an explicit `None` clears it (matching the existing `_UNSET`/`...`-sentinel convention in `shifts.py` and `shift_templates.py`). Add the param with `object = ...` (after `is_external: bool | None = None,` on line 92):

```python
    is_external: bool | None = None,
    eligible_node_ids: object = ...,
```

and the assignment (after the `is_external` block at line 130):

```python
    if is_external is not None:
        duty_type.is_external = is_external
    if eligible_node_ids is not ...:
        duty_type.eligible_node_ids = eligible_node_ids  # type: ignore[assignment]  # None means clear
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_duty_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Wire the route layer**

In `backend/app/routes/duty_config.py`:

Add to `DutyTypeOut` (after `is_external: bool = False` on line 46):

```python
    is_external: bool = False
    eligible_node_ids: list[uuid.UUID] | None = None
```

Add to `CreateDutyTypeRequest` (after `is_external: bool  # required — no default`):

```python
    is_external: bool  # required — no default
    eligible_node_ids: list[uuid.UUID] | None = None
```

Add to `UpdateDutyTypeRequest` (after `is_external: bool | None = None`):

```python
    is_external: bool | None = None
    eligible_node_ids: list[uuid.UUID] | None = None
```

In `_dt_out` (after `is_external=d.is_external,` on line 108):

```python
        is_external=d.is_external,
        eligible_node_ids=d.eligible_node_ids,
```

In `create_duty_type` route handler, pass it through the `svc.create_duty_type(...)` call (after `is_external=body.is_external,`):

```python
            is_external=body.is_external,
            eligible_node_ids=body.eligible_node_ids,
```

In `update_duty_type` route handler, since `UpdateDutyTypeRequest.eligible_node_ids` defaults to `None` and the service now uses a `...`-sentinel to distinguish "clear" from "not provided", use the `model_fields_set` pattern (matching `update_shift`/`update_template` in the other routers). Replace the `svc.update_duty_type(...)` call:

```python
    try:
        extra: dict = {}
        if "eligible_node_ids" in body.model_fields_set:
            extra["eligible_node_ids"] = body.eligible_node_ids
        svc.update_duty_type(
            session,
            duty_type=dt,
            name=body.name,
            score_per_day=body.score_per_day,
            description=body.description,
            actor_id=user.id,
            requirements=body.requirements,
            reserve_ratio=body.reserve_ratio,
            reserve_minimum=body.reserve_minimum,
            contact_name=body.contact_name,
            contact_phone=body.contact_phone,
            start_time=body.start_time,
            end_time=body.end_time,
            instructions=body.instructions,
            is_external=body.is_external,
            **extra,
        )
```

- [ ] **Step 6: Run the full duty_config-related test suite**

Run: `cd backend && pytest -m duty -q`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/duty_config.py backend/app/routes/duty_config.py backend/app/services/tests/test_duty_config.py
git commit -m "feat: support eligible_node_ids on DutyType create/update"
```

---

## Task 7: `ShiftTemplate` service + route support for `eligible_node_ids`, and cascade into `generate_shifts`

**Files:**
- Modify: `backend/app/services/shift_templates.py:82-125` (create_template), `:135-188` (update_template), `:227-267` (generate_shifts)
- Modify: `backend/app/routes/shift_templates.py:19-34` (TemplateOut), `:36-49` (CreateTemplateRequest), `:51-63` (UpdateTemplateRequest), `:79-85` (_out), route handlers
- Test: `backend/app/services/tests/test_shift_templates.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/app/services/tests/test_shift_templates.py`:

```python
import uuid
from datetime import date as _date
from decimal import Decimal

from app.db.models import DutyLocation
from app.services.duty_config import create_duty_type
from app.services.shift_templates import create_template, generate_shifts, update_template
from tests.helpers import create_node


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _make_duty_type_and_location(session):
    dt = create_duty_type(session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    session.add(loc)
    session.flush()
    return dt, loc


def test_create_template_with_eligible_node_ids(admin_session):
    node = create_node(admin_session, level="division", name="div_tpl1")
    dt, loc = _make_duty_type_and_location(admin_session)
    tpl = create_template(
        admin_session, name="tpl_scoped", duty_type_id=dt.id, duty_location_id=loc.id,
        weekdays=[1], eligible_node_ids=[node.id],
    )
    admin_session.commit()
    assert tpl.eligible_node_ids == [node.id]


def test_update_template_clears_eligible_node_ids(admin_session):
    node = create_node(admin_session, level="division", name="div_tpl2")
    dt, loc = _make_duty_type_and_location(admin_session)
    tpl = create_template(
        admin_session, name="tpl_clear", duty_type_id=dt.id, duty_location_id=loc.id,
        weekdays=[1], eligible_node_ids=[node.id],
    )
    admin_session.commit()

    update_template(admin_session, tpl=tpl, eligible_node_ids=None)
    admin_session.commit()
    assert tpl.eligible_node_ids is None


def test_generate_shifts_copies_template_scope_onto_each_shift(admin_session):
    node = create_node(admin_session, level="division", name="div_tpl3")
    dt, loc = _make_duty_type_and_location(admin_session)
    tpl = create_template(
        admin_session, name="tpl_generate_scope", duty_type_id=dt.id, duty_location_id=loc.id,
        recurrence_type="daily", weekdays=[], eligible_node_ids=[node.id],
    )
    admin_session.commit()

    created = generate_shifts(admin_session, tpl=tpl, range_start=_date(2026, 6, 1), range_end=_date(2026, 6, 1))
    admin_session.commit()
    assert len(created) == 1
    assert created[0].eligible_node_ids == [node.id]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_shift_templates.py -v`
Expected: FAIL — `TypeError: create_template() got an unexpected keyword argument 'eligible_node_ids'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/shift_templates.py`:

Add `eligible_node_ids` to `create_template`'s signature (after `notes: str | None = None,` on line 96):

```python
    notes: str | None = None,
    eligible_node_ids: list[uuid.UUID] | None = None,
    actor_id: uuid.UUID | None = None,
```

and pass it to the `ShiftTemplate(...)` constructor (after `notes=notes,` on line 112):

```python
        notes=notes,
        eligible_node_ids=eligible_node_ids,
        created_by=actor_id,
```

Add `eligible_node_ids` to `update_template`'s signature, using the same `...`-sentinel convention already used for `auto_roll_until`/`notes` in this function (after `notes: object = ...,` on line 149):

```python
    notes: object = ...,
    eligible_node_ids: object = ...,
    actor_id: uuid.UUID | None = None,
```

and the assignment (after the `notes` block at line 174):

```python
    if notes is not ...:
        tpl.notes = notes  # type: ignore[assignment]
    if eligible_node_ids is not ...:
        tpl.eligible_node_ids = eligible_node_ids  # type: ignore[assignment]
```

In `generate_shifts`, add `eligible_node_ids=tpl.eligible_node_ids` to the `DutyShift(...)` constructor (after `generated_from_template_id=tpl.id,` on line 253):

```python
            generated_from_template_id=tpl.id,
            eligible_node_ids=tpl.eligible_node_ids,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_shift_templates.py -v`
Expected: PASS

- [ ] **Step 5: Wire the route layer**

In `backend/app/routes/shift_templates.py`:

Add to `TemplateOut` (after `notes: str | None` on line 33):

```python
    notes: str | None
    eligible_node_ids: list[uuid.UUID] | None = None
```

Add to `CreateTemplateRequest` (after `notes: str | None = Field(default=None, max_length=1000)`):

```python
    notes: str | None = Field(default=None, max_length=1000)
    eligible_node_ids: list[uuid.UUID] | None = None
```

Add to `UpdateTemplateRequest` (after `notes: str | None = None`):

```python
    notes: str | None = None
    eligible_node_ids: list[uuid.UUID] | None = None
```

In `_out` (after `auto_roll_until=t.auto_roll_until, notes=t.notes,` on line 84):

```python
        active=t.active, auto_roll=t.auto_roll, auto_roll_until=t.auto_roll_until, notes=t.notes,
        eligible_node_ids=t.eligible_node_ids,
    )
```

In `create_template` route handler, pass it through (after `notes=body.notes, actor_id=user.id,`):

```python
            notes=body.notes, eligible_node_ids=body.eligible_node_ids, actor_id=user.id,
```

In `update_template` route handler, add it to the existing `extra` dict pattern (alongside `notes`/`auto_roll_until`):

```python
    extra: dict = {}
    if "notes" in body.model_fields_set:
        extra["notes"] = body.notes
    if "auto_roll_until" in body.model_fields_set:
        extra["auto_roll_until"] = body.auto_roll_until
    if "eligible_node_ids" in body.model_fields_set:
        extra["eligible_node_ids"] = body.eligible_node_ids
```

- [ ] **Step 6: Run the full duty-area test suite for regressions**

Run: `cd backend && pytest -m duty -q`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/shift_templates.py backend/app/routes/shift_templates.py backend/app/services/tests/test_shift_templates.py
git commit -m "feat: support eligible_node_ids on ShiftTemplate and cascade it into generated shifts"
```

---

## Task 8: `DutyShift` service + route support for `eligible_node_ids` on creation and read

**Files:**
- Modify: `backend/app/services/shifts.py:23-37` (ShiftWithFill), `:72-91` (_to_with_fill), `:94-146` (create_shift)
- Modify: `backend/app/routes/shifts.py:23-37` (ShiftOut), `:39-49` (CreateShiftRequest), `:60-82` (_out), `:105-130` (create_shift handler)
- Test: `backend/app/services/tests/test_shifts.py` (new file)

- [ ] **Step 1: Write the failing test**

```python
# backend/app/services/tests/test_shifts.py
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.db.models import DutyLocation
from app.services.duty_config import create_duty_type
from app.services.shifts import create_shift, get_shift_fill
from tests.helpers import create_node


def _make_duty_type_and_location(session, name_suffix: str):
    dt = create_duty_type(session, name=f"dt_shift_{name_suffix}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_shift_{name_suffix}")
    session.add(loc)
    session.flush()
    return dt, loc


def test_create_shift_with_eligible_node_ids(admin_session):
    node = create_node(admin_session, level="division", name="div_shift1")
    dt, loc = _make_duty_type_and_location(admin_session, "1")
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        eligible_node_ids=[node.id],
    )
    admin_session.commit()
    assert shift.eligible_node_ids == [node.id]


def test_get_shift_fill_exposes_eligible_node_ids(admin_session):
    node = create_node(admin_session, level="division", name="div_shift2")
    dt, loc = _make_duty_type_and_location(admin_session, "2")
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        eligible_node_ids=[node.id],
    )
    admin_session.commit()
    fill = get_shift_fill(admin_session, shift_id=shift.id)
    assert fill is not None
    assert fill.eligible_node_ids == [node.id]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_shifts.py -v`
Expected: FAIL — `TypeError: create_shift() got an unexpected keyword argument 'eligible_node_ids'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/shifts.py`:

Add `eligible_node_ids` to the `ShiftWithFill` dataclass (after `reserve_count_override: int | None = None` on line 36):

```python
    reserve_count_override: int | None = None
    eligible_node_ids: list[uuid.UUID] | None = None
```

Add it to `_to_with_fill`'s return (after `reserve_count_override=shift.reserve_count_override,` on line 90):

```python
        reserve_count_override=shift.reserve_count_override,
        eligible_node_ids=shift.eligible_node_ids,
    )
```

Add `eligible_node_ids` to `create_shift`'s signature (after `reserve_count_override: int | None = None,` on line ~103):

```python
    reserve_count_override: int | None = None,
    eligible_node_ids: list[uuid.UUID] | None = None,
    actor_id: uuid.UUID | None = None,
```

and pass it to the `DutyShift(...)` constructor (after `reserve_count_override=reserve_count_override,`):

```python
        reserve_count_override=reserve_count_override,
        eligible_node_ids=eligible_node_ids,
        created_by=actor_id,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_shifts.py -v`
Expected: PASS

- [ ] **Step 5: Wire the route layer**

In `backend/app/routes/shifts.py`:

Add to `ShiftOut` (after `calculated_reserve_count: int | None = None` on line 36):

```python
    calculated_reserve_count: int | None = None
    eligible_node_ids: list[uuid.UUID] | None = None
```

Add to `CreateShiftRequest` (after `reserve_count_override: int | None = Field(default=None, ge=0)` on line 48):

```python
    reserve_count_override: int | None = Field(default=None, ge=0)
    eligible_node_ids: list[uuid.UUID] | None = None
```

In `_out` (after `calculated_reserve_count=calculated,` on line 80):

```python
        calculated_reserve_count=calculated,
        eligible_node_ids=s.eligible_node_ids,
        status=s.status,
    )
```

In the `create_shift` route handler, pass it through the `svc.create_shift(...)` call (after `reserve_count_override=body.reserve_count_override,`):

```python
            reserve_count_override=body.reserve_count_override,
            eligible_node_ids=body.eligible_node_ids,
            actor_id=user.id,
```

(`UpdateShiftRequest` already has `eligible_node_ids` and the update route handler already wires it through `extra` — no change needed there.)

- [ ] **Step 6: Run the full duty-area test suite for regressions**

Run: `cd backend && pytest -m duty -q`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/shifts.py backend/app/routes/shifts.py backend/app/services/tests/test_shifts.py
git commit -m "feat: support eligible_node_ids on shift creation and expose it on read"
```

---

## Task 9: Subtree-aware + unassigned-excluding eligibility in the candidate-listing endpoint

**Files:**
- Modify: `backend/app/routes/shifts.py:230-312` (get_shift_candidates)

This endpoint currently has its own inline copy of the exact-match check (`if shift.eligible_node_ids and si.hierarchy_node_id not in shift.eligible_node_ids: continue`). It already builds a `node_map: dict[uuid.UUID, HierarchyNode]` later in the function (for `hierarchy_path_ids` in the response) — move that lookup earlier and reuse it for the eligibility check itself, switching to `node_in_scope`.

There is no existing test file for this router (`backend/app/routes/tests/` only covers `test_candidate_rank.py` and `test_commander_dashboard.py`, neither of which exercises this endpoint), so this task does not add a new route-level test — the underlying `node_in_scope` logic is already covered by Task 1-3's tests, and this task is a thin call-site swap. Treat the existing `pytest -m duty -q` run in Step 3 as the regression gate.

- [ ] **Step 1: Make the edit**

In `backend/app/routes/shifts.py`, inside `get_shift_candidates`, the current code is:

```python
    from app.db.models import HierarchyNode
    node_map: dict[uuid.UUID, HierarchyNode] = {
        n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()
    }

    soldier_inputs = load_soldier_inputs(session, as_of=shift.start_date)

    result: list[ShiftCandidateOut] = []
    for si in soldier_inputs:
        if si.id in already_on_shift:
            continue
        if shift.duty_type_id in si.exempted_duty_type_ids:
            continue
        if shift.eligible_node_ids and si.hierarchy_node_id not in shift.eligible_node_ids:
            continue
        soldier = soldier_map.get(si.id)
        if soldier is None:
            continue
```

Replace the eligibility check (keep everything else, including the `node_map` construction location and the later `node = node_map.get(...)` / `path_ids = [...]` lines further down which still compute the response's `hierarchy_path_ids` field):

```python
    from app.algorithm.types import node_in_scope
    from app.db.models import HierarchyNode
    node_map: dict[uuid.UUID, HierarchyNode] = {
        n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()
    }

    soldier_inputs = load_soldier_inputs(session, as_of=shift.start_date)

    result: list[ShiftCandidateOut] = []
    for si in soldier_inputs:
        if si.id in already_on_shift:
            continue
        if shift.duty_type_id in si.exempted_duty_type_ids:
            continue
        soldier_node = node_map.get(si.hierarchy_node_id) if si.hierarchy_node_id else None
        soldier_path_ids = list(soldier_node.path_ids) if soldier_node else []
        if not node_in_scope(shift.eligible_node_ids, soldier_path_ids):
            continue
        soldier = soldier_map.get(si.id)
        if soldier is None:
            continue
```

Further down in the same loop, the existing code does:

```python
        node = node_map.get(si.hierarchy_node_id) if si.hierarchy_node_id else None
        path_ids = [str(pid) for pid in node.path_ids] if node and node.path_ids else []
```

This is now redundant with `soldier_node`/`soldier_path_ids` computed above — replace it with:

```python
        path_ids = [str(pid) for pid in soldier_path_ids]
```

- [ ] **Step 2: Manual sanity check of the diff**

Re-read the full edited function to confirm `soldier_node`/`soldier_path_ids` are computed once per loop iteration before any `continue`, and that the later `path_ids` line no longer redefines `node` (avoid an unused-variable lint warning — `node` should no longer appear anywhere in this function after the edit; confirm with a search).

Run: `grep -n "node_map.get(si.hierarchy_node_id)" backend/app/routes/shifts.py`
Expected: Exactly one occurrence (the `soldier_node = ...` line), not two.

- [ ] **Step 3: Run the full duty-area test suite for regressions**

Run: `cd backend && pytest -m duty -q`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/shifts.py
git commit -m "fix: subtree-aware eligibility and unassigned-soldier exclusion in candidate listing"
```

---

## Task 10: Frontend API types — `eligible_node_ids` on DutyType, ShiftTemplate, DutyShift

**Files:**
- Modify: `frontend/src/api/dutyConfig.ts`
- Modify: `frontend/src/api/shiftTemplates.ts`
- Modify: `frontend/src/api/shifts.ts`

No test step — these are pure TypeScript interface additions with no runtime logic. Verified by the TypeScript compiler in Task 11-13's `npm run lint` step.

- [ ] **Step 1: `frontend/src/api/dutyConfig.ts`**

Add to the `DutyType` interface (after `is_external: boolean;` on line 26):

```typescript
  is_external: boolean;
  eligible_node_ids: string[] | null;
```

Add to `createDutyType`'s input type (after `is_external: boolean;` on line 58):

```typescript
  is_external: boolean;
  eligible_node_ids?: string[] | null;
```

Add to `updateDutyType`'s input type (after `is_external: boolean;` on line 76):

```typescript
    is_external: boolean;
    eligible_node_ids: string[] | null;
```

- [ ] **Step 2: `frontend/src/api/shiftTemplates.ts`**

Add to the `ShiftTemplate` interface (after `notes: string | null;` on line 19):

```typescript
  notes: string | null;
  eligible_node_ids: string[] | null;
```

Add to `CreateTemplateInput` (after `notes?: string | null;` on line 34):

```typescript
  notes?: string | null;
  eligible_node_ids?: string[] | null;
```

(`UpdateTemplateInput` is `Partial<Omit<CreateTemplateInput, ...> & {...}>` — it automatically picks up `eligible_node_ids` as optional once it's on `CreateTemplateInput`, no separate edit needed.)

- [ ] **Step 3: `frontend/src/api/shifts.ts`**

Add to the `DutyShift` interface (after `calculated_reserve_count?: number | null;` on line 16):

```typescript
  calculated_reserve_count?: number | null;
  eligible_node_ids?: string[] | null;
```

Add to `CreateShiftInput` (after `reserve_count_override?: number | null;` on line 26):

```typescript
  reserve_count_override?: number | null;
  eligible_node_ids?: string[] | null;
```

Add to `UpdateShiftInput` (after `reserve_count_override?: number | null;` on line 34):

```typescript
  reserve_count_override?: number | null;
  eligible_node_ids?: string[] | null;
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/dutyConfig.ts frontend/src/api/shiftTemplates.ts frontend/src/api/shifts.ts
git commit -m "feat: add eligible_node_ids to duty type, template, and shift API types"
```

---

## Task 11: i18n keys for the shared "eligible units" picker section

**Files:**
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add the new namespace**

In `frontend/src/i18n/he.json`, the file is one big JSON object whose last top-level key is `"score_adjustment"` (ending at the final `}` before the file's closing `}`). Add a comma after that object's closing `}` and insert a new top-level key:

```json
  "score_adjustment": {
    ...
    "soldier_placeholder": "— בחר חייל —"
  },
  "hierarchy_scope": {
    "title": "הגבלת זכאות ליחידות",
    "help": "אם לא נבחרו יחידות, כל החיילים זכאים. בחירת יחידה כוללת את כל היחידות שמתחתיה."
  }
}
```

(Keep the existing `algorithm.select_eligible_nodes` key as-is — it's still used as the helper caption inside `SubHierarchySelector` itself, which is shared across all four usages.)

- [ ] **Step 2: Verify valid JSON**

Run: `cd frontend && node -e "JSON.parse(require('fs').readFileSync('src/i18n/he.json', 'utf8')); console.log('valid')"`
Expected: `valid`

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/he.json
git commit -m "feat: add hierarchy_scope i18n keys for eligible-units picker"
```

---

## Task 12: Wire `SubHierarchySelector` into `DutyTypeFormModal`

**Files:**
- Modify: `frontend/src/components/DutyTypeFormModal.tsx`

- [ ] **Step 1: Add state and import**

Add the import (after line 4, alongside the other imports):

```typescript
import SubHierarchySelector from "./SubHierarchySelector";
```

Add state (after `const [eligOpen, setEligOpen] = useState(false);` on line 30):

```typescript
  const [eligOpen, setEligOpen] = useState(false);
  const [scopeNodeIds, setScopeNodeIds] = useState<string[]>(initial?.eligible_node_ids ?? []);
```

- [ ] **Step 2: Include it in the submit payload**

In `handleSubmit`, add `eligible_node_ids: scopeNodeIds.length > 0 ? scopeNodeIds : null,` to the `payload` object (after `is_external: isExternal === "true",` on line 69):

```typescript
      const payload = {
        name,
        score_per_day: score,
        reserve_ratio: reserveRatio,
        reserve_minimum: parseInt(reserveMin) || 0,
        contact_name: contactName || null,
        contact_phone: contactPhone || null,
        start_time: startTime || null,
        end_time: endTime || null,
        instructions: instructions || null,
        is_external: isExternal === "true",
        eligible_node_ids: scopeNodeIds.length > 0 ? scopeNodeIds : null,
      };
```

- [ ] **Step 3: Add the picker UI**

Add a new collapsible section after the existing "Eligibility section" `<div>` block (after its closing `</div>` on line 276, before the `{error && ...}` line):

```tsx
          {/* Hierarchy scope section */}
          <div className="border dark:border-gray-600 rounded p-3">
            <p className="text-sm font-medium text-gray-700 dark:text-gray-200 mb-1">{t("hierarchy_scope.title")}</p>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">{t("hierarchy_scope.help")}</p>
            <SubHierarchySelector value={scopeNodeIds} onChange={setScopeNodeIds} />
          </div>

          {error && <p className="text-red-500 text-xs">{error}</p>}
```

(This replaces the standalone `{error && <p className="text-red-500 text-xs">{error}</p>}` line — make sure not to duplicate it.)

- [ ] **Step 4: Manual verification (no automated frontend test exists for this modal)**

Run: `cd frontend && npm run lint`
Expected: No new errors/warnings (zero-warnings enforced per CLAUDE.md).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DutyTypeFormModal.tsx
git commit -m "feat: add hierarchy scope picker to DutyTypeFormModal"
```

---

## Task 13: Wire `SubHierarchySelector` into `ShiftTemplateFormModal`, defaulting from the chosen duty type

**Files:**
- Modify: `frontend/src/components/ShiftTemplateFormModal.tsx`

- [ ] **Step 1: Add state and import**

Add the import (after line 14):

```typescript
import SubHierarchySelector from "./SubHierarchySelector";
```

Add state (after `const [notes, setNotes] = useState(initial?.notes ?? "");` on line 172):

```typescript
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [scopeNodeIds, setScopeNodeIds] = useState<string[]>(
    initial?.eligible_node_ids ?? localDutyTypes.find((d) => d.id === dtId)?.eligible_node_ids ?? []
  );
```

(On create, this seeds the picker from the initially-selected duty type's scope — `dtId` defaults to `propDutyTypes[0]?.id` per line 155. On edit, `initial.eligible_node_ids` wins.)

- [ ] **Step 2: Re-default when the duty type changes (create mode only)**

Add an effect after the state declarations (need `useEffect` — add it to the existing `useState` import on line 1):

```typescript
import { useState, useEffect } from "react";
```

```typescript
  useEffect(() => {
    if (!initial) {
      setScopeNodeIds(localDutyTypes.find((d) => d.id === dtId)?.eligible_node_ids ?? []);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dtId]);
```

(Only re-defaults on create, matching the spec's "pre-populated ... editable before saving" — once a user has touched the picker, changing `dtId` again will still re-default it since there's no separate "touched" flag; this matches the simpler of the two reasonable behaviors and is consistent with how `dtId` itself resets other create-only fields in this form.)

- [ ] **Step 3: Include it in both submit payloads**

In `handleSubmit`, add `eligible_node_ids: scopeNodeIds.length > 0 ? scopeNodeIds : null,` to both the `UpdateTemplateInput` and `CreateTemplateInput` objects:

```typescript
      if (initial) {
        const input: UpdateTemplateInput = {
          name, recurrence_type: recurrenceType, weekdays, duration_days,
          start_time: startTime, end_time: endTime,
          required_count: count, auto_roll: autoRoll, auto_roll_until: autoRollUntil || null,
          notes: notes || null, eligible_node_ids: scopeNodeIds.length > 0 ? scopeNodeIds : null,
        };
        await updateTemplate(initial.id, input);
      } else {
        const input: CreateTemplateInput = {
          name, duty_type_id: dtId, duty_location_id: locId,
          recurrence_type: recurrenceType, weekdays, duration_days,
          start_time: startTime, end_time: endTime,
          required_count: count, auto_roll: autoRoll, auto_roll_until: autoRollUntil || null,
          notes: notes || null, eligible_node_ids: scopeNodeIds.length > 0 ? scopeNodeIds : null,
        };
        await createTemplate(input);
      }
```

- [ ] **Step 4: Add the picker UI**

Add a new section after the notes `<label>` block (after its closing `</label>` on line 506, before the `{error && ...}` line):

```tsx
            <div className="border dark:border-gray-600 rounded p-3">
              <p className="text-sm font-medium text-gray-700 dark:text-gray-200 mb-1">{t("hierarchy_scope.title")}</p>
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">{t("hierarchy_scope.help")}</p>
              <SubHierarchySelector value={scopeNodeIds} onChange={setScopeNodeIds} />
            </div>

            {error && <p className="text-red-500 text-xs">{error}</p>}
```

- [ ] **Step 5: Lint**

Run: `cd frontend && npm run lint`
Expected: No new errors/warnings.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ShiftTemplateFormModal.tsx
git commit -m "feat: add hierarchy scope picker to ShiftTemplateFormModal, defaulted from duty type"
```

---

## Task 14: Wire `SubHierarchySelector` into `ShiftFormModal`, defaulting from the chosen duty type

**Files:**
- Modify: `frontend/src/components/ShiftFormModal.tsx`

- [ ] **Step 1: Add state and import**

Add the import (after line 6):

```typescript
import SubHierarchySelector from "./SubHierarchySelector";
```

Add state (after `const [reserveOverride, setReserveOverride] = useState(existing?.reserve_count_override?.toString() ?? "");` on line 27):

```typescript
  const [reserveOverride, setReserveOverride] = useState(existing?.reserve_count_override?.toString() ?? "");
  const [scopeNodeIds, setScopeNodeIds] = useState<string[]>(
    existing?.eligible_node_ids ?? dutyTypes.find((d) => d.id === dtId)?.eligible_node_ids ?? []
  );
```

- [ ] **Step 2: Re-default when the duty type changes (create mode only)**

Add `useEffect` to the import on line 1:

```typescript
import { useState, useEffect } from "react";
```

Add the effect after the state declarations:

```typescript
  useEffect(() => {
    if (!existing) {
      setScopeNodeIds(dutyTypes.find((d) => d.id === dtId)?.eligible_node_ids ?? []);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dtId]);
```

- [ ] **Step 3: Include it in both submit payloads**

In `handleSubmit`, add `eligible_node_ids` to both branches:

```typescript
      if (existing) {
        await updateShift(existing.id, {
          start_date: startDate,
          end_date: exclusiveEndDate,
          required_count: count,
          notes: notes || null,
          reserve_count_override: reserveOverride === "" ? null : parseInt(reserveOverride),
          eligible_node_ids: scopeNodeIds.length > 0 ? scopeNodeIds : null,
        });
      } else {
        const input: CreateShiftInput = {
          duty_type_id: dtId,
          duty_location_id: locId,
          start_date: startDate,
          end_date: exclusiveEndDate,
          required_count: count,
          notes: notes || null,
          reserve_count_override: reserveOverride === "" ? null : parseInt(reserveOverride),
          eligible_node_ids: scopeNodeIds.length > 0 ? scopeNodeIds : null,
        };
        await createShift(input);
      }
```

- [ ] **Step 4: Add the picker UI**

Add a new section after the reserve-override `<label>` block (after its closing `</label>` on line 148, before `{error && ...}`):

```tsx
          <div className="border dark:border-gray-600 rounded p-2">
            <p className="text-sm font-medium text-gray-700 dark:text-gray-200 mb-1">{t("hierarchy_scope.title")}</p>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">{t("hierarchy_scope.help")}</p>
            <SubHierarchySelector value={scopeNodeIds} onChange={setScopeNodeIds} />
          </div>
          {error && <p className="text-red-500 text-xs">{error}</p>}
```

- [ ] **Step 5: Lint**

Run: `cd frontend && npm run lint`
Expected: No new errors/warnings.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ShiftFormModal.tsx
git commit -m "feat: add hierarchy scope picker to ShiftFormModal, defaulted from duty type"
```

---

## Task 15: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the fast backend suite**

Run: `cd backend && pytest -q`
Expected: All PASS (existing `-n auto` parallel default; this does not include the 8 slow CP-SAT tests).

- [ ] **Step 2: Run the algorithm + duty marker subset explicitly**

Run: `cd backend && pytest -m "algorithm or duty" -q`
Expected: All PASS.

- [ ] **Step 3: Run frontend unit tests and lint**

Run: `cd frontend && npm test && npm run lint`
Expected: All PASS, zero lint warnings.

- [ ] **Step 4: Manual smoke check via the dev stack**

Run: `.\dev.ps1` from the repo root, then in the browser:
1. Open the duty-config page, create a duty type, expand "הגבלת זכאות ליחידות", select a branch node, save. Re-open it and confirm the selection persisted.
2. Create a shift template for that duty type — confirm the scope picker pre-fills with the duty type's selected node, then clear it and save.
3. Use "generate shifts" on that template for a short date range, then open one of the generated shifts' candidate list — confirm only soldiers within the originally-scoped subtree (or everyone, if you cleared it in step 2) appear, and that soldiers with no hierarchy assignment are excluded whenever a scope is set.

This step has no automated assertion — it's a final human sanity check before merging, since the cascade behavior spans three UI surfaces and the CP-SAT solver.

- [ ] **Step 5: Report results to the user**

Summarize pass/fail for each step above; do not mark the plan complete until Steps 1-3 are all green.
