# Reserve Duty Assignments (רזרבה) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reserve duty assignments (רזרבות) — algorithm-assigned on-call soldiers per shift, linked to their primaries by hierarchy proximity, with הקפצה (call-up) and dismissal actions, per-day score multipliers, and a shift detail panel in the unit calendar.

**Architecture:** Extend `DutyAssignment` with `is_reserve`/`called_up_from`/`called_up_to`; new `DutyDismissal` and `DutyReserveLink` tables replace the old `reserve_assignments` table. The CP-SAT solver runs one combined pass over primary + reserve `DutyBlock`s, with a soft hierarchy-distance term in the objective. Scoring reads per-day multipliers from system settings. Existing swap infrastructure works for reserve assignments unchanged.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, OR-Tools CP-SAT, Pydantic v2, React 18 + Vite + TS, TanStack Query. Same toolchain as prior slices.

---

## Spec reference

[`docs/superpowers/specs/2026-05-31-reserve-assignments-design.md`](../specs/2026-05-31-reserve-assignments-design.md)

## File structure

**Backend — new files:**
- `backend/alembic/versions/0025_reserve_assignments.py`
- `backend/app/services/reserves.py` — call_up, dismiss, get_shift_reserve_detail
- `backend/app/routes/reserves.py` — REST endpoints
- `backend/tests/unit/test_reserves.py`
- `backend/tests/unit/test_scoring_reserve.py`

**Backend — modified files:**
- `backend/app/db/models.py` — DutyType columns, DutyShift column, DutyAssignment columns, new DutyDismissal + DutyReserveLink models, remove ReserveAssignment
- `backend/app/algorithm/types.py` — `is_reserve` on DutyBlock, `ReserveLink` dataclass, `reserve_hierarchy_weight` on SolverSettings
- `backend/app/algorithm/reserve.py` — rewrite: `link_reserves` + `compute_reserve_dist`
- `backend/app/algorithm/model.py` — add `reserve_dist` param + hierarchy weight objective term
- `backend/app/algorithm/tests/test_reserve.py` — update for new API
- `backend/app/services/algorithm_bridge.py` — extend `load_duty_blocks_from_shifts`, rewrite `persist_results`, update `run_algorithm_job`
- `backend/app/services/scoring.py` — extend `effective_duty_days` with multiplier
- `backend/app/services/duty_config.py` — add reserve fields to `update_duty_type`
- `backend/app/routes/duty_config.py` — add reserve fields to DutyType schemas
- `backend/app/routes/shifts.py` — add `reserve_count_override` + `calculated_reserve_count`
- `backend/app/main.py` — register reserves router

**Frontend — new files:**
- `frontend/src/api/reserves.ts`
- `frontend/src/components/ShiftReservePanel.tsx`

**Frontend — modified files:**
- `frontend/src/pages/DutyConfigPage.tsx` — reserve_ratio, reserve_minimum fields
- `frontend/src/pages/DutyManagementPage.tsx` — reserve_count_override on shift form
- `frontend/src/components/UnitCalendar.tsx` — `"N + Mר"` badge
- `frontend/src/i18n/he.json` — new keys

---

## Task 1: DB model + migration 0025

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/0025_reserve_assignments.py`

- [ ] **Step 1: Add columns to DutyType**

In `backend/app/db/models.py`, inside `class DutyType` after `requirements`:

```python
    reserve_ratio: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), server_default=text("0.000"), default=Decimal("0.000")
    )
    reserve_minimum: Mapped[int] = mapped_column(
        server_default=text("0"), default=0
    )
```

- [ ] **Step 2: Add column to DutyShift**

Inside `class DutyShift` after `dm_locked`:

```python
    reserve_count_override: Mapped[int | None] = mapped_column(
        nullable=True, default=None
    )
```

- [ ] **Step 3: Add columns to DutyAssignment**

Inside `class DutyAssignment` after `duty_shift_id`:

```python
    is_reserve: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    called_up_from: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    called_up_to: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
```

- [ ] **Step 4: Add DutyDismissal model**

After `class DutyDayOverride`:

```python
class DutyDismissal(Base):
    __tablename__ = "duty_dismissals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    duty_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_assignments.id", ondelete="CASCADE")
    )
    dismissed_from: Mapped[date] = mapped_column(Date)
    dismissed_to: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 5: Add DutyReserveLink model**

After `class DutyDismissal`:

```python
class DutyReserveLink(Base):
    __tablename__ = "duty_reserve_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    reserve_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_assignments.id", ondelete="CASCADE")
    )
    primary_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_assignments.id", ondelete="CASCADE"), unique=True
    )
    hierarchy_distance: Mapped[int] = mapped_column(server_default=text("0"), default=0)
```

- [ ] **Step 6: Remove ReserveAssignment**

Delete the entire `class ReserveAssignment(Base):` block from `models.py` (lines ~486–498).

- [ ] **Step 7: Verify import**

Run: `cd backend && .venv/Scripts/python.exe -c "import app.db.models; print('OK')"`
Expected: `OK`

- [ ] **Step 8: Write migration**

Create `backend/alembic/versions/0025_reserve_assignments.py`:

```python
"""reserve assignments — duty_dismissals, duty_reserve_links, new columns

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DutyType new columns
    op.add_column("duty_types", sa.Column("reserve_ratio", sa.Numeric(4, 3), server_default=sa.text("0.000"), nullable=False))
    op.add_column("duty_types", sa.Column("reserve_minimum", sa.Integer(), server_default=sa.text("0"), nullable=False))

    # DutyShift new column
    op.add_column("duty_shifts", sa.Column("reserve_count_override", sa.Integer(), nullable=True))

    # DutyAssignment new columns
    op.add_column("duty_assignments", sa.Column("is_reserve", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("duty_assignments", sa.Column("called_up_from", sa.Date(), nullable=True))
    op.add_column("duty_assignments", sa.Column("called_up_to", sa.Date(), nullable=True))

    # duty_dismissals table
    op.create_table(
        "duty_dismissals",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("duty_assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dismissed_from", sa.Date(), nullable=False),
        sa.Column("dismissed_to", sa.Date(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["duty_assignment_id"], ["duty_assignments.id"], ondelete="CASCADE", name="fk_duty_dismissals_assignment"),
        sa.ForeignKeyConstraint(["created_by"], ["soldiers.id"], ondelete="SET NULL", name="fk_duty_dismissals_created_by"),
    )

    # duty_reserve_links table
    op.create_table(
        "duty_reserve_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("reserve_assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("primary_assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hierarchy_distance", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(["reserve_assignment_id"], ["duty_assignments.id"], ondelete="CASCADE", name="fk_reserve_links_reserve"),
        sa.ForeignKeyConstraint(["primary_assignment_id"], ["duty_assignments.id"], ondelete="CASCADE", name="fk_reserve_links_primary"),
        sa.UniqueConstraint("primary_assignment_id", name="uq_reserve_links_primary"),
    )

    # Drop old reserve_assignments table
    op.drop_table("reserve_assignments")


def downgrade() -> None:
    op.create_table(
        "reserve_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("duty_assignment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reserve_soldier_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
    )
    op.drop_table("duty_reserve_links")
    op.drop_table("duty_dismissals")
    op.drop_column("duty_assignments", "called_up_to")
    op.drop_column("duty_assignments", "called_up_from")
    op.drop_column("duty_assignments", "is_reserve")
    op.drop_column("duty_shifts", "reserve_count_override")
    op.drop_column("duty_types", "reserve_minimum")
    op.drop_column("duty_types", "reserve_ratio")
```

- [ ] **Step 9: Apply and verify reversibility**

Run:
```
cd backend && .venv/Scripts/alembic upgrade head
cd backend && .venv/Scripts/alembic downgrade -1 && .venv/Scripts/alembic upgrade head
```
Expected: ends at `0025`, no error.

- [ ] **Step 10: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/0025_reserve_assignments.py
git commit -m "feat(reserve): DB model + migration 0025"
```

---

## Task 2: Algorithm types — DutyBlock.is_reserve + ReserveLink + SolverSettings.reserve_hierarchy_weight

**Files:**
- Modify: `backend/app/algorithm/types.py`

- [ ] **Step 1: Add `is_reserve` to DutyBlock**

In `backend/app/algorithm/types.py`, change `class DutyBlock`:

```python
@dataclass
class DutyBlock:
    """A duty block (shift) to be assigned to a soldier."""
    id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    score_per_day: Decimal
    is_reserve: bool = False
```

- [ ] **Step 2: Add ReserveLink dataclass**

After `class ReserveEntry`, add:

```python
@dataclass
class ReserveLink:
    """A (reserve_assignment_id, primary_assignment_id, distance) tuple from post-solve linking."""
    reserve_assignment_id: uuid.UUID
    primary_assignment_id: uuid.UUID
    hierarchy_distance: int
```

- [ ] **Step 3: Add reserve_hierarchy_weight to SolverSettings**

In `class SolverSettings`, add after `seed`:

```python
    reserve_hierarchy_weight: Decimal = Decimal("0.5")
```

- [ ] **Step 4: Verify existing tests still pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/algorithm/tests/ -q`
Expected: all pass (adding a default field doesn't break anything).

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/types.py
git commit -m "feat(reserve): algorithm types — DutyBlock.is_reserve, ReserveLink, reserve_hierarchy_weight"
```

---

## Task 3: Rewrite algorithm/reserve.py — link_reserves + compute_reserve_dist

**Files:**
- Modify: `backend/app/algorithm/reserve.py`
- Modify: `backend/app/algorithm/tests/test_reserve.py`

- [ ] **Step 1: Write failing tests for link_reserves**

Replace the contents of `backend/app/algorithm/tests/test_reserve.py`:

```python
from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.algorithm.types import Assignment, DutyBlock, ReserveLink, SoldierInput
from app.algorithm.reserve import link_reserves, compute_reserve_dist


def _block(is_reserve: bool = False, start: date = date(2026, 6, 1), end: date = date(2026, 6, 1)) -> DutyBlock:
    return DutyBlock(
        id=uuid4(), duty_type_id=uuid4(), duty_location_id=uuid4(),
        start_date=start, end_date=end, score_per_day=Decimal("1"), is_reserve=is_reserve,
    )


def test_link_reserves_one_primary_one_reserve():
    shift_id = uuid4()
    primary_block = _block(is_reserve=False)
    reserve_block = _block(is_reserve=True)

    primary_soldier = uuid4()
    reserve_soldier = uuid4()
    node = uuid4()

    primary_assignment_id = uuid4()
    reserve_assignment_id = uuid4()

    # Both in same node → distance 0
    soldier_node = {primary_soldier: node, reserve_soldier: node}
    hierarchy_parent: dict = {node: None}

    links = link_reserves(
        primary_assignments=[(primary_assignment_id, primary_soldier, shift_id)],
        reserve_assignments=[(reserve_assignment_id, reserve_soldier, shift_id)],
        soldier_node=soldier_node,
        hierarchy_parent=hierarchy_parent,
        hierarchy_children={node: []},
    )
    assert len(links) == 1
    assert links[0].reserve_assignment_id == reserve_assignment_id
    assert links[0].primary_assignment_id == primary_assignment_id
    assert links[0].hierarchy_distance == 0


def test_link_reserves_prefers_closest():
    shift_id = uuid4()
    root = uuid4(); child_a = uuid4(); child_b = uuid4()
    primary_soldier = uuid4(); reserve_close = uuid4(); reserve_far = uuid4()

    # primary in child_a, reserve_close in child_a (dist 0), reserve_far in root (dist 1)
    soldier_node = {primary_soldier: child_a, reserve_close: child_a, reserve_far: root}
    hierarchy_parent = {child_a: root, child_b: root, root: None}
    hierarchy_children = {root: [child_a, child_b], child_a: [], child_b: []}

    primary_id = uuid4(); reserve_close_id = uuid4(); reserve_far_id = uuid4()
    links = link_reserves(
        primary_assignments=[(primary_id, primary_soldier, shift_id)],
        reserve_assignments=[
            (reserve_close_id, reserve_close, shift_id),
            (reserve_far_id, reserve_far, shift_id),
        ],
        soldier_node=soldier_node,
        hierarchy_parent=hierarchy_parent,
        hierarchy_children=hierarchy_children,
    )
    # The one primary should be linked to the closest reserve
    assert len(links) == 1
    assert links[0].primary_assignment_id == primary_id
    assert links[0].reserve_assignment_id == reserve_close_id
    assert links[0].hierarchy_distance == 0


def test_link_reserves_reserve_covers_multiple_primaries():
    shift_id = uuid4()
    node = uuid4()
    p1, p2, r = uuid4(), uuid4(), uuid4()
    soldier_node = {p1: node, p2: node, r: node}
    hierarchy_parent = {node: None}

    p1_id, p2_id, r_id = uuid4(), uuid4(), uuid4()
    links = link_reserves(
        primary_assignments=[(p1_id, p1, shift_id), (p2_id, p2, shift_id)],
        reserve_assignments=[(r_id, r, shift_id)],
        soldier_node=soldier_node,
        hierarchy_parent=hierarchy_parent,
        hierarchy_children={node: []},
    )
    assert len(links) == 2
    assert all(lk.reserve_assignment_id == r_id for lk in links)
    assert {lk.primary_assignment_id for lk in links} == {p1_id, p2_id}


def test_compute_reserve_dist_same_node_is_zero():
    shift_id = uuid4()
    node = uuid4()
    primary_soldier = uuid4(); reserve_soldier = uuid4()
    soldier_node = {primary_soldier: node, reserve_soldier: node}

    primary_block = _block(is_reserve=False)
    reserve_block = _block(is_reserve=True)
    block_to_shift = {primary_block.id: shift_id, reserve_block.id: shift_id}

    soldiers = [
        SoldierInput(id=primary_soldier, enrolled_at=date(2026,1,1), cumulative_score=Decimal("0"), active_days=100),
        SoldierInput(id=reserve_soldier, enrolled_at=date(2026,1,1), cumulative_score=Decimal("0"), active_days=100),
    ]
    hierarchy_parent = {node: None}

    dist = compute_reserve_dist(
        soldiers=soldiers,
        duties=[primary_block, reserve_block],
        block_to_shift=block_to_shift,
        hierarchy_parent=hierarchy_parent,
        soldier_node=soldier_node,
    )
    # reserve block is index 1; reserve_soldier is index 1
    assert dist.get((1, 1), 99) == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/algorithm/tests/test_reserve.py -v`
Expected: FAIL — `ImportError: cannot import name 'link_reserves'`

- [ ] **Step 3: Rewrite algorithm/reserve.py**

```python
from __future__ import annotations

import uuid
from collections import deque
from collections.abc import Sequence

from app.algorithm.types import DutyBlock, ReserveLink, SoldierInput


def _node_ancestors(node_id: uuid.UUID, hierarchy_parent: dict[uuid.UUID, uuid.UUID | None]) -> set[uuid.UUID]:
    """All ancestor node IDs including node_id itself."""
    path: set[uuid.UUID] = set()
    current: uuid.UUID | None = node_id
    while current is not None:
        path.add(current)
        current = hierarchy_parent.get(current)
    return path


def _hierarchy_distance(node_a: uuid.UUID, node_b: uuid.UUID,
                         hierarchy_parent: dict[uuid.UUID, uuid.UUID | None]) -> int:
    """Symmetric-difference distance: len(ancestors(a) Δ ancestors(b))."""
    return len(_node_ancestors(node_a, hierarchy_parent).symmetric_difference(
        _node_ancestors(node_b, hierarchy_parent)
    ))


def link_reserves(
    primary_assignments: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]],
    reserve_assignments: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]],
    soldier_node: dict[uuid.UUID, uuid.UUID],
    hierarchy_parent: dict[uuid.UUID, uuid.UUID | None],
    hierarchy_children: dict[uuid.UUID, list[uuid.UUID]],
) -> list[ReserveLink]:
    """For each primary assignment, find the closest reserve (by hierarchy distance)
    in the same shift. One reserve may cover multiple primaries.

    Args:
        primary_assignments: list of (assignment_id, soldier_id, shift_id)
        reserve_assignments: list of (assignment_id, soldier_id, shift_id)
        soldier_node, hierarchy_parent, hierarchy_children: from build_hierarchy_maps
    Returns:
        list of ReserveLink — one per primary assignment
    """
    # Group reserves by shift
    reserves_by_shift: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID]]] = {}
    for r_assign_id, r_soldier_id, shift_id in reserve_assignments:
        reserves_by_shift.setdefault(shift_id, []).append((r_assign_id, r_soldier_id))

    links: list[ReserveLink] = []
    for p_assign_id, p_soldier_id, shift_id in primary_assignments:
        candidates = reserves_by_shift.get(shift_id)
        if not candidates:
            continue
        p_node = soldier_node.get(p_soldier_id)
        if p_node is None:
            # no hierarchy node — pick first reserve, distance 10
            r_assign_id, _ = candidates[0]
            links.append(ReserveLink(
                reserve_assignment_id=r_assign_id,
                primary_assignment_id=p_assign_id,
                hierarchy_distance=10,
            ))
            continue

        best_assign_id: uuid.UUID | None = None
        best_dist = 999
        for r_assign_id, r_soldier_id in candidates:
            r_node = soldier_node.get(r_soldier_id)
            if r_node is None:
                dist = 10
            else:
                dist = _hierarchy_distance(p_node, r_node, hierarchy_parent)
            if dist < best_dist:
                best_dist = dist
                best_assign_id = r_assign_id

        if best_assign_id is not None:
            links.append(ReserveLink(
                reserve_assignment_id=best_assign_id,
                primary_assignment_id=p_assign_id,
                hierarchy_distance=best_dist,
            ))

    return links


def compute_reserve_dist(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    block_to_shift: dict[uuid.UUID, uuid.UUID],
    hierarchy_parent: dict[uuid.UUID, uuid.UUID | None],
    soldier_node: dict[uuid.UUID, uuid.UUID],
) -> dict[tuple[int, int], int]:
    """Precompute hierarchy distance from each candidate reserve soldier to the
    nearest primary-eligible soldier for the same shift.

    Returns dict mapping (duty_index, soldier_index) → int distance,
    populated only for reserve blocks.
    """
    from collections import defaultdict

    duty_list = list(duties)
    soldier_list = list(soldiers)

    # Collect unique soldier nodes per shift (from primary blocks)
    shift_primary_nodes: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for d in duty_list:
        if not d.is_reserve:
            shift_id = block_to_shift.get(d.id)
            if shift_id is not None:
                for s in soldier_list:
                    node = soldier_node.get(s.id)
                    if node:
                        shift_primary_nodes[shift_id].add(node)

    result: dict[tuple[int, int], int] = {}
    for di, d in enumerate(duty_list):
        if not d.is_reserve:
            continue
        shift_id = block_to_shift.get(d.id)
        primary_nodes = shift_primary_nodes.get(shift_id, set()) if shift_id else set()
        for si, s in enumerate(soldier_list):
            s_node = soldier_node.get(s.id)
            if s_node is None or not primary_nodes:
                result[(di, si)] = 10
            else:
                result[(di, si)] = min(
                    _hierarchy_distance(s_node, pn, hierarchy_parent)
                    for pn in primary_nodes
                )
    return result
```

- [ ] **Step 4: Run tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/algorithm/tests/test_reserve.py -v`
Expected: all 4 pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/reserve.py backend/app/algorithm/tests/test_reserve.py
git commit -m "feat(reserve): link_reserves + compute_reserve_dist replacing select_reserves"
```

---

## Task 4: Algorithm model — hierarchy-distance soft term

**Files:**
- Modify: `backend/app/algorithm/model.py`
- Modify: `backend/app/algorithm/tests/test_solver.py`

- [ ] **Step 1: Write a failing test**

Append to `backend/app/algorithm/tests/test_solver.py`:

```python
def test_reserve_blocks_prefer_closer_soldier() -> None:
    """With two soldiers in different hierarchy nodes, the reserve block should
    be assigned to the soldier closer to the primary candidate nodes."""
    root = uuid4(); node_a = uuid4(); node_b = uuid4()
    dt = uuid4(); loc = uuid4()

    s_close = uuid4(); s_far = uuid4()

    soldiers = [
        SoldierInput(id=s_close, enrolled_at=date(2026,1,1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=node_a),
        SoldierInput(id=s_far, enrolled_at=date(2026,1,1), cumulative_score=Decimal("0"),
                     active_days=100, hierarchy_node_id=node_b),
    ]
    shift_id = uuid4()
    # One primary block + one reserve block on different days so no overlap issue
    primary_block = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                               start_date=date(2026,6,1), end_date=date(2026,6,1),
                               score_per_day=Decimal("1"), is_reserve=False)
    reserve_block = DutyBlock(id=uuid4(), duty_type_id=dt, duty_location_id=loc,
                               start_date=date(2026,6,2), end_date=date(2026,6,2),
                               score_per_day=Decimal("0.2"), is_reserve=True)
    block_to_shift = {primary_block.id: shift_id, reserve_block.id: shift_id}

    # s_close is in node_a (same as primary candidates' node), s_far in node_b
    # hierarchy: root -> node_a, root -> node_b
    hierarchy_parent = {node_a: root, node_b: root, root: None}
    soldier_node = {s_close: node_a, s_far: node_b}

    from app.algorithm.reserve import compute_reserve_dist
    reserve_dist = compute_reserve_dist(
        soldiers=soldiers,
        duties=[primary_block, reserve_block],
        block_to_shift=block_to_shift,
        hierarchy_parent=hierarchy_parent,
        soldier_node=soldier_node,
    )

    settings = SolverSettings(time_limit_seconds=10, reserve_hierarchy_weight=Decimal("5.0"))
    result = solve(soldiers=soldiers, duties=[primary_block, reserve_block],
                   existing=[], settings=settings, reserve_dist=reserve_dist)

    assert result.status in ("OPTIMAL", "FEASIBLE")
    # Find which soldier got the reserve block
    reserve_assignment = next(a for a in result.assignments if a.duty_id == reserve_block.id)
    # s_close (node_a, same node as primary candidates) should be preferred
    assert reserve_assignment.soldier_id == s_close
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/algorithm/tests/test_solver.py::test_reserve_blocks_prefer_closer_soldier -v`
Expected: FAIL — `TypeError: solve() got an unexpected keyword argument 'reserve_dist'`

- [ ] **Step 3: Update build_model signature and add hierarchy term**

In `backend/app/algorithm/model.py`, change the `build_model` signature:

```python
def build_model(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = None,
) -> tuple[CpModel, dict[tuple[int, int], IntVar]]:
```

At the end of `build_model`, replace:

```python
    objective = -(sum(density_terms) if density_terms else 0)
    model.Maximize(objective)
    return model, x
```

with:

```python
    # Soft objective: hierarchy proximity for reserve blocks
    reserve_dist_terms: list = []
    if reserve_dist is not None:
        gamma_int = int(settings.reserve_hierarchy_weight * 1000)
        for (di, si), var in x.items():
            if duty_list[di].is_reserve:
                dist = reserve_dist.get((di, si), 10)
                reserve_dist_terms.append(gamma_int * dist * var)

    objective = (
        -(sum(density_terms) if density_terms else 0)
        - (sum(reserve_dist_terms) if reserve_dist_terms else 0)
    )
    model.Maximize(objective)
    return model, x
```

- [ ] **Step 4: Update solve() to accept and forward reserve_dist**

In `backend/app/algorithm/solver.py`, update `solve`:

```python
def solve(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = None,
) -> SolverResult:
    """Build the CP-SAT model and solve it. Returns assignments + metrics."""
    return _infeasibility_relaxation_chain(soldiers, duties, existing, settings, reserve_dist)
```

Update `_infeasibility_relaxation_chain` signature and forward:

```python
def _infeasibility_relaxation_chain(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = None,
) -> SolverResult:
```

Inside `_infeasibility_relaxation_chain`, change the `_solve_with_settings` calls to pass `reserve_dist`:

```python
        solver, x, status = _solve_with_settings(soldiers, duties, existing, current, reserve_dist)
```

Update `_solve_with_settings`:

```python
def _solve_with_settings(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = None,
) -> tuple[CpSolver, dict[tuple[int, int], IntVar], int]:
    model, x = build_model(soldiers, duties, existing, settings, reserve_dist)
    ...
```

- [ ] **Step 5: Run tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/algorithm/tests/ -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/algorithm/model.py backend/app/algorithm/solver.py backend/app/algorithm/tests/test_solver.py
git commit -m "feat(reserve): hierarchy-distance soft objective term in CP-SAT model"
```

---

## Task 5: reserve_count_for_shift + extend load_duty_blocks_from_shifts

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py`
- Modify: `backend/tests/unit/test_shift_generation.py` (add reserve count test)

- [ ] **Step 1: Write failing test for reserve_count_for_shift**

Append to `backend/tests/unit/test_shift_generation.py`:

```python
from app.db.models import DutyLocation, DutyType, DutyShift
from app.services.algorithm_bridge import reserve_count_for_shift
from decimal import Decimal


def test_reserve_count_formula(admin_session):
    dt = DutyType(name="שמירה-rc", score_per_day=Decimal("1"), reserve_ratio=Decimal("0.200"), reserve_minimum=0)
    loc = DutyLocation(name="עמדה-rc")
    admin_session.add(dt); admin_session.add(loc); admin_session.flush()
    shift = DutyShift(duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date(2026,6,1), end_date=date(2026,6,1),
                      required_count=20)
    admin_session.add(shift); admin_session.flush()
    # ceil(20 × 0.2) = 4
    assert reserve_count_for_shift(admin_session, shift=shift) == 4


def test_reserve_count_minimum(admin_session):
    dt = DutyType(name="שמירה-rmin", score_per_day=Decimal("1"), reserve_ratio=Decimal("0.100"), reserve_minimum=3)
    loc = DutyLocation(name="עמדה-rmin")
    admin_session.add(dt); admin_session.add(loc); admin_session.flush()
    shift = DutyShift(duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date(2026,6,1), end_date=date(2026,6,1),
                      required_count=5)
    admin_session.add(shift); admin_session.flush()
    # ceil(5 × 0.1) = 1, but minimum is 3
    assert reserve_count_for_shift(admin_session, shift=shift) == 3


def test_reserve_count_override(admin_session):
    dt = DutyType(name="שמירה-rov", score_per_day=Decimal("1"), reserve_ratio=Decimal("0.200"), reserve_minimum=0)
    loc = DutyLocation(name="עמדה-rov")
    admin_session.add(dt); admin_session.add(loc); admin_session.flush()
    shift = DutyShift(duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date(2026,6,1), end_date=date(2026,6,1),
                      required_count=20, reserve_count_override=7)
    admin_session.add(shift); admin_session.flush()
    assert reserve_count_for_shift(admin_session, shift=shift) == 7
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/Scripts/python.exe -m pytest backend/tests/unit/test_shift_generation.py -k "reserve_count" -v`
Expected: FAIL — `cannot import name 'reserve_count_for_shift'`

- [ ] **Step 3: Implement reserve_count_for_shift**

In `backend/app/services/algorithm_bridge.py`, add this function after the imports (after `load_soldier_inputs`):

```python
import math


def reserve_count_for_shift(session: Session, *, shift: DutyShift) -> int:
    """Effective reserve count for a shift: override if set, else max(minimum, ceil(ratio × count))."""
    if shift.reserve_count_override is not None:
        return shift.reserve_count_override
    dt = session.get(DutyType, shift.duty_type_id)
    if dt is None:
        return 0
    ratio = float(dt.reserve_ratio or 0)
    minimum = int(dt.reserve_minimum or 0)
    calculated = math.ceil(shift.required_count * ratio)
    return max(minimum, calculated)
```

Also add `import math` and `from app.db.models import DutyShift` to the imports at the top of `algorithm_bridge.py` (DutyShift is already imported, just add `math`).

- [ ] **Step 4: Extend load_duty_blocks_from_shifts to emit reserve blocks**

Replace `load_duty_blocks_from_shifts` in `algorithm_bridge.py`:

```python
def load_duty_blocks_from_shifts(
    session: Session,
    *,
    shift_ids: list[uuid.UUID],
    standby_multiplier: Decimal = Decimal("0.2"),
) -> tuple[list[DutyBlock], dict[uuid.UUID, uuid.UUID]]:
    """Expand DutyShift rows into primary + reserve DutyBlocks.

    Returns (all_blocks, block_to_shift_map). Reserve blocks have
    is_reserve=True and score_per_day scaled by standby_multiplier.
    """
    shifts = session.execute(select(DutyShift).where(DutyShift.id.in_(shift_ids))).scalars().all()

    type_ids = {s.duty_type_id for s in shifts}
    types_q = session.execute(select(DutyType).where(DutyType.id.in_(type_ids))).scalars().all()
    score_map = {dt.id: dt.score_per_day for dt in types_q}

    blocks: list[DutyBlock] = []
    block_to_shift: dict[uuid.UUID, uuid.UUID] = {}

    for shift in shifts:
        score = score_map.get(shift.duty_type_id, Decimal("1.00"))
        # Primary blocks
        for _ in range(shift.required_count):
            block_id = uuid.uuid4()
            blocks.append(DutyBlock(
                id=block_id,
                duty_type_id=shift.duty_type_id,
                duty_location_id=shift.duty_location_id,
                start_date=shift.start_date,
                end_date=shift.end_date,
                score_per_day=score,
                is_reserve=False,
            ))
            block_to_shift[block_id] = shift.id
        # Reserve blocks
        r_count = reserve_count_for_shift(session, shift=shift)
        r_score = score * standby_multiplier
        for _ in range(r_count):
            block_id = uuid.uuid4()
            blocks.append(DutyBlock(
                id=block_id,
                duty_type_id=shift.duty_type_id,
                duty_location_id=shift.duty_location_id,
                start_date=shift.start_date,
                end_date=shift.end_date,
                score_per_day=r_score,
                is_reserve=True,
            ))
            block_to_shift[block_id] = shift.id

    return blocks, block_to_shift
```

- [ ] **Step 5: Run tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_shift_generation.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/algorithm_bridge.py backend/tests/unit/test_shift_generation.py
git commit -m "feat(reserve): reserve_count_for_shift + reserve blocks in load_duty_blocks_from_shifts"
```

---

## Task 6: persist_results + run_algorithm_job — wire reserve assignments and links

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py`

- [ ] **Step 1: Update persist_results to create reserve DutyAssignments + DutyReserveLinks**

Replace the `persist_results` function in `algorithm_bridge.py`. First update the import block at the top to include the new models and remove `ReserveAssignment`:

```python
from app.db.models import (
    AlgorithmJob,
    AssignmentExplanation,
    DutyAssignment,
    DutyReserveLink,
    DutyShift,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionType,
    HierarchyNode,
    PersonalConstraint,
    Soldier,
    SoldierExemption,
)
```

Replace `persist_results`:

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
) -> None:
    """Insert algorithm_draft assignments, explanations, and reserve links."""
    from app.algorithm.reserve import link_reserves

    duty_map = {d.id: d for d in duty_blocks}
    explanation_map = {e.duty_id: e for e in explanation_data.per_assignment}

    # Separate primary and reserve assignments by shift
    primary_assignments: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []
    reserve_assignments: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]] = []

    for a in result.assignments:
        block: DutyBlock = duty_map[a.duty_id]
        shift_id = block_to_shift_map.get(a.duty_id) if block_to_shift_map else None
        da = DutyAssignment(
            soldier_id=a.soldier_id,
            duty_type_id=block.duty_type_id,
            duty_location_id=block.duty_location_id,
            start_date=block.start_date,
            end_date=block.end_date,
            status="algorithm_draft",
            created_by=actor_id,
            notes=None,
            duty_shift_id=shift_id,
            is_reserve=block.is_reserve,
        )
        session.add(da)
        session.flush()

        if not block.is_reserve:
            exp = explanation_map.get(a.duty_id)
            if exp is not None:
                payload = _explanation_payload(exp, dm_view=True, soldier_names=soldier_names)
                payload["global_before"] = explanation_data.global_metrics_before
                payload["global_after"] = explanation_data.global_metrics_after
                session.add(AssignmentExplanation(
                    duty_assignment_id=da.id,
                    payload=payload,
                    algorithm_version=explanation_data.algorithm_version,
                    solver_seed=str(explanation_data.solver_seed),
                ))

        write_audit(
            session, actor_id=actor_id, action="algorithm.proposal.create",
            entity_type="duty_assignment", entity_id=da.id,
            after={"status": "algorithm_draft", "is_reserve": block.is_reserve},
            context={"job_id": str(job.id)},
        )

        if shift_id:
            if block.is_reserve:
                reserve_assignments.append((da.id, a.soldier_id, shift_id))
            else:
                primary_assignments.append((da.id, a.soldier_id, shift_id))

    # Build reserve links
    if primary_assignments and reserve_assignments and soldier_node is not None:
        links = link_reserves(
            primary_assignments=primary_assignments,
            reserve_assignments=reserve_assignments,
            soldier_node=soldier_node,
            hierarchy_parent=hierarchy_parent or {},
            hierarchy_children=hierarchy_children or {},
        )
        for link in links:
            session.add(DutyReserveLink(
                reserve_assignment_id=link.reserve_assignment_id,
                primary_assignment_id=link.primary_assignment_id,
                hierarchy_distance=link.hierarchy_distance,
            ))
```

- [ ] **Step 2: Update run_algorithm_job to use new functions and remove select_reserves**

Replace the `run_algorithm_job` function. The key changes:
- Pass `reserve_dist` to `solve`
- Pass hierarchy maps to `persist_results`
- Remove `select_reserves` and `reserves` param

```python
def run_algorithm_job(job_id: uuid.UUID, actor_id: uuid.UUID | None) -> None:
    """Background task: load data, run solver, persist results."""
    from app.algorithm.explain import build_explanations
    from app.algorithm.reserve import compute_reserve_dist
    from app.algorithm.solver import solve
    from app.db.session import session_scope
    from app.services.settings_loader import get_setting

    with session_scope() as session:
        job = session.get(AlgorithmJob, job_id)
        if job is None:
            return

        job.status = "running"
        job.started_at = datetime.now(tz=timezone.utc)
        session.commit()

        try:
            def _setting_decimal(key: str, default: str) -> Decimal:
                try:
                    return Decimal(str(get_setting(session, key)))
                except Exception:
                    return Decimal(default)

            settings = SolverSettings(
                K=Decimal(str(job.settings_json.get("K", 8))),
                T=int(job.settings_json.get("T", 7)),
                W=int(job.settings_json.get("W", 14)),
                alpha=Decimal(str(job.settings_json.get("alpha", 1.0))),
                beta=Decimal(str(job.settings_json.get("beta", 2.0))),
                time_limit_seconds=int(job.settings_json.get("time_limit_seconds", 30)),
                reserve_hierarchy_weight=_setting_decimal("fairness.reserve_hierarchy_weight", "0.5"),
            )
            standby_multiplier = _setting_decimal("scoring.reserve_standby_multiplier", "0.2")

            shift_ids = [uuid.UUID(s) for s in job.shift_ids]
            duties, block_to_shift_map = load_duty_blocks_from_shifts(
                session, shift_ids=shift_ids, standby_multiplier=standby_multiplier,
            )

            if not duties:
                job.status = "failed"
                job.error_message = "no_shifts_selected"
                job.finished_at = datetime.now(tz=timezone.utc)
                session.commit()
                return

            planning_start = min(d.start_date for d in duties)
            planning_end = max(d.end_date for d in duties)

            soldiers = load_soldier_inputs(session, as_of=planning_start)
            existing = load_existing_assignments(
                session, planning_start=planning_start, planning_end=planning_end, W=settings.W,
            )

            if not soldiers:
                job.status = "failed"
                job.error_message = "no_soldiers_or_duties"
                job.finished_at = datetime.now(tz=timezone.utc)
                session.commit()
                return

            hier_parent, hier_children, soldier_node, node_soldiers = build_hierarchy_maps(session)

            reserve_dist = compute_reserve_dist(
                soldiers=soldiers, duties=duties, block_to_shift=block_to_shift_map,
                hierarchy_parent=hier_parent, soldier_node=soldier_node,
            )

            result = solve(soldiers, duties, existing, settings, reserve_dist=reserve_dist)

            if result.status == "INFEASIBLE":
                from app.algorithm.diagnose import diagnose_infeasibility
                dt_names = {dt.id: dt.name for dt in session.execute(select(DutyType)).scalars().all()}
                reasons = diagnose_infeasibility(soldiers, duties, existing, dt_names)
                job.status = "failed"
                job.error_message = json.dumps({
                    "relaxed": result.relaxed, "status": "INFEASIBLE", "reasons": reasons,
                })
                job.finished_at = datetime.now(tz=timezone.utc)
                session.commit()
                return

            explanation_data = build_explanations(
                soldiers=soldiers, duties=duties, assignments=result.assignments,
                global_before={}, global_after={}, solver_seed=result.seed,
            )

            soldier_names = {s.id: s.full_name for s in session.execute(select(Soldier)).scalars().all()}

            persist_results(
                session, job=job, result=result, explanation_data=explanation_data,
                duty_blocks=duties, soldier_names=soldier_names, actor_id=actor_id,
                block_to_shift_map=block_to_shift_map,
                hierarchy_parent=hier_parent, hierarchy_children=hier_children,
                soldier_node=soldier_node,
            )

            session.refresh(job)
            if job.status == "failed":
                session.rollback()
                return

            job.status = "done"
            job.finished_at = datetime.now(tz=timezone.utc)
            session.commit()

        except Exception as exc:
            session.rollback()
            with session_scope() as err_session:
                err_job = err_session.get(AlgorithmJob, job_id)
                if err_job is not None:
                    err_job.status = "failed"
                    err_job.error_message = str(exc)
                    err_job.finished_at = datetime.now(tz=timezone.utc)
                    err_session.commit()
```

- [ ] **Step 3: Verify import**

Run: `cd backend && .venv/Scripts/python.exe -c "from app.services.algorithm_bridge import persist_results; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/algorithm_bridge.py
git commit -m "feat(reserve): persist_results creates reserve DutyAssignments + DutyReserveLinks"
```

---

## Task 7: Scoring — extend effective_duty_days with multiplier

**Files:**
- Modify: `backend/app/services/scoring.py`
- Create: `backend/tests/unit/test_scoring_reserve.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_scoring_reserve.py`:

```python
from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.db.models import DutyAssignment, DutyDismissal, DutyLocation, DutyType, Soldier
from app.services import scoring as svc
from app.services.settings_loader import set_setting


def _seed(session):
    dt = DutyType(name="שמירה-score", score_per_day=Decimal("1"))
    loc = DutyLocation(name="עמדה-score")
    s_primary = Soldier(personal_number="sp01", full_name="Primary", password_hash="x",
                        role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False)
    s_reserve = Soldier(personal_number="sr01", full_name="Reserve", password_hash="x",
                        role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False)
    session.add_all([dt, loc, s_primary, s_reserve])
    session.flush()
    return dt, loc, s_primary, s_reserve


def test_standby_reserve_score(admin_session):
    dt, loc, s_primary, s_reserve = _seed(admin_session)
    set_setting(admin_session, "scoring.reserve_standby_multiplier", Decimal("0.2"), actor_id=None)
    assign = DutyAssignment(
        soldier_id=s_reserve.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        status="published", is_reserve=True,
    )
    admin_session.add(assign); admin_session.flush()
    scores = svc.duty_score_by_soldier(admin_session)
    # 2 days × 1.0 score_per_day × 0.2 standby = 0.4
    assert scores.get(s_reserve.id, Decimal("0")) == Decimal("0.4")


def test_called_up_reserve_score(admin_session):
    dt, loc, s_primary, s_reserve = _seed(admin_session)
    set_setting(admin_session, "scoring.reserve_standby_multiplier", Decimal("0.2"), actor_id=None)
    set_setting(admin_session, "scoring.reserve_called_up_multiplier", Decimal("1.3"), actor_id=None)
    # 2-day assignment, called up for all of it
    assign = DutyAssignment(
        soldier_id=s_reserve.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        status="published", is_reserve=True,
        called_up_from=date(2026, 6, 1), called_up_to=date(2026, 6, 2),
    )
    admin_session.add(assign); admin_session.flush()
    scores = svc.duty_score_by_soldier(admin_session)
    # 2 days × 1.0 × 1.3 = 2.6
    assert scores.get(s_reserve.id, Decimal("0")) == Decimal("2.6")


def test_dismissed_primary_score(admin_session):
    dt, loc, s_primary, s_reserve = _seed(admin_session)
    set_setting(admin_session, "scoring.dismissed_multiplier", Decimal("0.0"), actor_id=None)
    assign = DutyAssignment(
        soldier_id=s_primary.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 3),
        status="published", is_reserve=False,
    )
    admin_session.add(assign); admin_session.flush()
    dismissal = DutyDismissal(
        duty_assignment_id=assign.id,
        dismissed_from=date(2026, 6, 2), dismissed_to=date(2026, 6, 3),
    )
    admin_session.add(dismissal); admin_session.flush()
    scores = svc.duty_score_by_soldier(admin_session)
    # day 1 normal (1.0), days 2-3 dismissed (0.0) = 1.0 total
    assert scores.get(s_primary.id, Decimal("0")) == Decimal("1.0")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_scoring_reserve.py -v`
Expected: FAIL — scoring doesn't know about is_reserve or DutyDismissal yet.

- [ ] **Step 3: Rewrite effective_duty_days in scoring.py**

Replace the `effective_duty_days` function and update `duty_score_by_soldier`:

```python
def _get_multiplier_setting(session: Session, key: str, default: str) -> Decimal:
    from app.services.settings_loader import SettingNotFound, get_setting
    try:
        return Decimal(str(get_setting(session, key)))
    except SettingNotFound:
        return Decimal(default)


def effective_duty_days(
    session: Session, *, date_from: date | None = None, date_to: date | None = None
) -> list[tuple[date, uuid.UUID, uuid.UUID, Decimal]]:
    """Expand every published assignment to (date, effective_soldier_id, duty_type_id, multiplier).

    Multiplier depends on:
    - Primary assignment: 1.0, or dismissed_multiplier if a DutyDismissal covers that day
    - Reserve assignment: called_up_multiplier if in called-up range, else standby_multiplier
    Overrides (replacements) still reassign effective_soldier_id.
    """
    from app.db.models import DutyDismissal

    standby_mult = _get_multiplier_setting(session, "scoring.reserve_standby_multiplier", "0.2")
    called_up_mult = _get_multiplier_setting(session, "scoring.reserve_called_up_multiplier", "1.3")
    dismissed_mult = _get_multiplier_setting(session, "scoring.dismissed_multiplier", "0.0")

    assignments = (
        session.execute(select(DutyAssignment).where(DutyAssignment.status == "published"))
        .scalars().all()
    )
    overrides = {
        (o.duty_assignment_id, o.date): o
        for o in session.execute(select(DutyDayOverride)).scalars().all()
    }
    # Dismissals: {assignment_id: [(from, to), ...]}
    dismissal_ranges: dict[uuid.UUID, list[tuple[date, date]]] = {}
    for d in session.execute(select(DutyDismissal)).scalars().all():
        dismissal_ranges.setdefault(d.duty_assignment_id, []).append(
            (d.dismissed_from, d.dismissed_to)
        )

    out: list[tuple[date, uuid.UUID, uuid.UUID, Decimal]] = []
    for a in assignments:
        day = a.start_date
        while day <= a.end_date:
            if (date_from is None or day >= date_from) and (date_to is None or day <= date_to):
                ov = overrides.get((a.id, day))
                eff = ov.effective_soldier_id if ov is not None else a.soldier_id
                if eff is not None:
                    # Determine multiplier
                    if a.is_reserve:
                        if (a.called_up_from is not None and a.called_up_to is not None
                                and a.called_up_from <= day <= a.called_up_to):
                            mult = called_up_mult
                        else:
                            mult = standby_mult
                    else:
                        ranges = dismissal_ranges.get(a.id, [])
                        if any(df <= day <= dt for df, dt in ranges):
                            mult = dismissed_mult
                        else:
                            mult = Decimal("1.0")
                    out.append((day, eff, a.duty_type_id, mult))
            day += timedelta(days=1)
    return out
```

Update `duty_score_by_soldier`:

```python
def duty_score_by_soldier(session: Session) -> dict[uuid.UUID, Decimal]:
    scores = _duty_type_scores(session)
    out: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    for _day, eff, dtid, mult in effective_duty_days(session):
        out[eff] += scores.get(dtid, Decimal("0")) * mult
    return out
```

Update `soldier_score_breakdown` to unpack 4 values:

```python
def soldier_score_breakdown(session: Session, *, soldier_id: uuid.UUID) -> dict[str, Any]:
    scores = _duty_type_scores(session)
    dt_names = {dt.id: dt.name for dt in session.execute(select(DutyType)).scalars().all()}
    by_type: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    for _day, eff, dtid, mult in effective_duty_days(session):
        if eff == soldier_id:
            by_type[dtid] += scores.get(dtid, Decimal("0")) * mult
    per_type = [
        {
            "duty_type_id": dtid,
            "duty_type_name": dt_names.get(dtid),
            "score": score,
        }
        for dtid, score in by_type.items()
    ]
    adjustments = (
        session.execute(
            select(ScoreAdjustment).where(ScoreAdjustment.soldier_id == soldier_id)
            .order_by(ScoreAdjustment.created_at)
        ).scalars().all()
    )
    return {"per_type": per_type, "adjustments": list(adjustments)}
```

- [ ] **Step 4: Run tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_scoring_reserve.py tests/unit/ -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scoring.py backend/tests/unit/test_scoring_reserve.py
git commit -m "feat(reserve): scoring with per-day multipliers (standby, called-up, dismissed)"
```

---

## Task 8: Reserve services (call_up_reserve, dismiss_primary, get_shift_reserve_detail)

**Files:**
- Create: `backend/app/services/reserves.py`
- Create: `backend/tests/unit/test_reserves.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_reserves.py`:

```python
from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.db.models import DutyAssignment, DutyDismissal, DutyLocation, DutyShift, DutyType, Soldier
from app.services import reserves as svc


def _seed(session):
    dt = DutyType(name="שמירה-res", score_per_day=Decimal("1"))
    loc = DutyLocation(name="עמדה-res")
    s = Soldier(personal_number="srv01", full_name="A", password_hash="x",
                role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False)
    r = Soldier(personal_number="srv02", full_name="B", password_hash="x",
                role="soldier", enrolled_at=date(2026, 1, 1), must_change_password=False)
    session.add_all([dt, loc, s, r]); session.flush()
    shift = DutyShift(duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date(2026, 6, 1), end_date=date(2026, 6, 7),
                      required_count=1)
    session.add(shift); session.flush()
    primary = DutyAssignment(
        soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 7),
        status="published", is_reserve=False, duty_shift_id=shift.id,
    )
    reserve = DutyAssignment(
        soldier_id=r.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 7),
        status="published", is_reserve=True, duty_shift_id=shift.id,
    )
    session.add_all([primary, reserve]); session.flush()
    return shift, primary, reserve, s, r


def test_call_up_reserve_sets_range(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    svc.call_up_reserve(
        admin_session, assignment=reserve,
        from_date=date(2026, 6, 3), to_date=date(2026, 6, 7), actor_id=None,
    )
    assert reserve.called_up_from == date(2026, 6, 3)
    assert reserve.called_up_to == date(2026, 6, 7)


def test_call_up_reserve_rejects_non_reserve(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    try:
        svc.call_up_reserve(
            admin_session, assignment=primary,
            from_date=date(2026, 6, 1), to_date=date(2026, 6, 3), actor_id=None,
        )
        assert False, "expected ReserveError"
    except svc.ReserveError as e:
        assert str(e) == "not_a_reserve"


def test_call_up_reserve_rejects_out_of_range(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    try:
        svc.call_up_reserve(
            admin_session, assignment=reserve,
            from_date=date(2026, 5, 1), to_date=date(2026, 5, 5), actor_id=None,
        )
        assert False, "expected ReserveError"
    except svc.ReserveError as e:
        assert str(e) == "date_out_of_range"


def test_dismiss_primary_creates_record(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    dismissal = svc.dismiss_primary(
        admin_session, assignment=primary,
        from_date=date(2026, 6, 5), to_date=date(2026, 6, 7),
        reason="חופש", actor_id=None,
    )
    assert dismissal.dismissed_from == date(2026, 6, 5)
    assert dismissal.dismissed_to == date(2026, 6, 7)
    assert dismissal.reason == "חופש"


def test_dismiss_primary_rejects_reserve(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    try:
        svc.dismiss_primary(
            admin_session, assignment=reserve,
            from_date=date(2026, 6, 1), to_date=date(2026, 6, 2),
            reason=None, actor_id=None,
        )
        assert False, "expected ReserveError"
    except svc.ReserveError as e:
        assert str(e) == "not_a_primary"


def test_dismiss_primary_rejects_overlapping_dismissal(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    svc.dismiss_primary(admin_session, assignment=primary,
                        from_date=date(2026, 6, 3), to_date=date(2026, 6, 5), reason=None, actor_id=None)
    admin_session.flush()
    try:
        svc.dismiss_primary(admin_session, assignment=primary,
                            from_date=date(2026, 6, 4), to_date=date(2026, 6, 6), reason=None, actor_id=None)
        assert False, "expected ReserveError"
    except svc.ReserveError as e:
        assert str(e) == "overlapping_dismissal"


def test_delete_dismissal(admin_session):
    shift, primary, reserve, s, r = _seed(admin_session)
    dismissal = svc.dismiss_primary(admin_session, assignment=primary,
                                    from_date=date(2026, 6, 5), to_date=date(2026, 6, 7),
                                    reason=None, actor_id=None)
    admin_session.flush()
    svc.delete_dismissal(admin_session, dismissal=dismissal, actor_id=None)
    admin_session.flush()
    from sqlalchemy import select
    from app.db.models import DutyDismissal
    remaining = admin_session.execute(select(DutyDismissal)).scalars().all()
    assert len(remaining) == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_reserves.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.reserves'`

- [ ] **Step 3: Implement services/reserves.py**

Create `backend/app/services/reserves.py`:

```python
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyAssignment, DutyDismissal, DutyReserveLink


class ReserveError(Exception):
    """Raised on invalid reserve operations."""


def call_up_reserve(
    session: Session,
    *,
    assignment: DutyAssignment,
    from_date: date,
    to_date: date,
    actor_id: uuid.UUID | None = None,
) -> DutyAssignment:
    """Record הקפצה on a reserve assignment. Replaces any prior call-up range."""
    if not assignment.is_reserve:
        raise ReserveError("not_a_reserve")
    if from_date < assignment.start_date or to_date > assignment.end_date:
        raise ReserveError("date_out_of_range")
    if to_date < from_date:
        raise ReserveError("bad_date_range")
    before = {"called_up_from": assignment.called_up_from, "called_up_to": assignment.called_up_to}
    assignment.called_up_from = from_date
    assignment.called_up_to = to_date
    session.flush()
    write_audit(
        session, actor_id=actor_id, action="reserve.call_up",
        entity_type="duty_assignment", entity_id=assignment.id,
        before=before,
        after={"called_up_from": from_date.isoformat(), "called_up_to": to_date.isoformat()},
    )
    return assignment


def dismiss_primary(
    session: Session,
    *,
    assignment: DutyAssignment,
    from_date: date,
    to_date: date,
    reason: str | None,
    actor_id: uuid.UUID | None = None,
) -> DutyDismissal:
    """Record a dismissal on a primary assignment. Validates no overlap with existing dismissals."""
    if assignment.is_reserve:
        raise ReserveError("not_a_primary")
    if from_date < assignment.start_date or to_date > assignment.end_date:
        raise ReserveError("date_out_of_range")
    if to_date < from_date:
        raise ReserveError("bad_date_range")
    # Check for overlapping dismissals
    existing = session.execute(
        select(DutyDismissal).where(DutyDismissal.duty_assignment_id == assignment.id)
    ).scalars().all()
    for d in existing:
        if d.dismissed_from <= to_date and d.dismissed_to >= from_date:
            raise ReserveError("overlapping_dismissal")
    dismissal = DutyDismissal(
        duty_assignment_id=assignment.id,
        dismissed_from=from_date,
        dismissed_to=to_date,
        reason=reason,
        created_by=actor_id,
    )
    session.add(dismissal)
    session.flush()
    write_audit(
        session, actor_id=actor_id, action="reserve.dismiss",
        entity_type="duty_dismissal", entity_id=dismissal.id,
        after={
            "duty_assignment_id": str(assignment.id),
            "dismissed_from": from_date.isoformat(),
            "dismissed_to": to_date.isoformat(),
            "reason": reason,
        },
    )
    return dismissal


def delete_dismissal(
    session: Session,
    *,
    dismissal: DutyDismissal,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Remove a dismissal record. Audited."""
    write_audit(
        session, actor_id=actor_id, action="reserve.dismiss_delete",
        entity_type="duty_dismissal", entity_id=dismissal.id,
        before={
            "dismissed_from": dismissal.dismissed_from.isoformat(),
            "dismissed_to": dismissal.dismissed_to.isoformat(),
        },
    )
    session.delete(dismissal)


def get_shift_reserve_detail(session: Session, *, shift_id: uuid.UUID) -> dict[str, Any]:
    """Return all primary and reserve assignments for a shift with call-up, dismissal, and link data."""
    assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.duty_shift_id == shift_id,
            DutyAssignment.status.in_(["published", "algorithm_draft"]),
        )
    ).scalars().all()

    primary_ids = {a.id for a in assignments if not a.is_reserve}
    reserve_ids = {a.id for a in assignments if a.is_reserve}

    # Load links
    links = session.execute(
        select(DutyReserveLink).where(DutyReserveLink.primary_assignment_id.in_(primary_ids))
    ).scalars().all()
    primary_to_reserve = {lk.primary_assignment_id: lk for lk in links}
    reserve_to_primaries: dict[uuid.UUID, list[uuid.UUID]] = {}
    for lk in links:
        reserve_to_primaries.setdefault(lk.reserve_assignment_id, []).append(lk.primary_assignment_id)

    # Load dismissals for primary assignments
    dismissals_by_assignment: dict[uuid.UUID, list[DutyDismissal]] = {}
    if primary_ids:
        for d in session.execute(
            select(DutyDismissal).where(DutyDismissal.duty_assignment_id.in_(primary_ids))
        ).scalars().all():
            dismissals_by_assignment.setdefault(d.duty_assignment_id, []).append(d)

    primaries = []
    for a in assignments:
        if a.is_reserve:
            continue
        link = primary_to_reserve.get(a.id)
        primaries.append({
            "assignment_id": a.id,
            "soldier_id": a.soldier_id,
            "start_date": a.start_date,
            "end_date": a.end_date,
            "status": a.status,
            "dismissals": [
                {"id": d.id, "from": d.dismissed_from, "to": d.dismissed_to, "reason": d.reason}
                for d in dismissals_by_assignment.get(a.id, [])
            ],
            "reserve_assignment_id": link.reserve_assignment_id if link else None,
            "reserve_hierarchy_distance": link.hierarchy_distance if link else None,
        })

    reserves = []
    for a in assignments:
        if not a.is_reserve:
            continue
        reserves.append({
            "assignment_id": a.id,
            "soldier_id": a.soldier_id,
            "start_date": a.start_date,
            "end_date": a.end_date,
            "status": a.status,
            "called_up_from": a.called_up_from,
            "called_up_to": a.called_up_to,
            "primary_assignment_ids": reserve_to_primaries.get(a.id, []),
        })

    return {"primaries": primaries, "reserves": reserves}
```

- [ ] **Step 4: Run tests**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_reserves.py -v`
Expected: all 7 pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/reserves.py backend/tests/unit/test_reserves.py
git commit -m "feat(reserve): call_up_reserve, dismiss_primary, delete_dismissal, get_shift_reserve_detail services"
```

---

## Task 9: DutyType config + DutyShift route updates

**Files:**
- Modify: `backend/app/routes/duty_config.py`
- Modify: `backend/app/services/duty_config.py`
- Modify: `backend/app/routes/shifts.py`

- [ ] **Step 1: Add reserve fields to DutyType schemas in duty_config.py**

In `backend/app/routes/duty_config.py`, update `DutyTypeOut`:

```python
class DutyTypeOut(BaseModel):
    id: uuid.UUID
    name: str
    score_per_day: Decimal
    description: str | None
    active: bool
    requirements: dict[str, Any] = {}
    reserve_ratio: Decimal = Decimal("0.000")
    reserve_minimum: int = 0
```

Update `CreateDutyTypeRequest` (add optional fields):

```python
class CreateDutyTypeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    score_per_day: Decimal = Field(ge=0)
    description: str | None = Field(default=None, max_length=1000)
    reserve_ratio: Decimal = Field(default=Decimal("0.000"), ge=0, le=1)
    reserve_minimum: int = Field(default=0, ge=0)
```

Update `UpdateDutyTypeRequest`:

```python
class UpdateDutyTypeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    score_per_day: Decimal | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=1000)
    active: bool | None = None
    requirements: dict[str, Any] | None = None
    reserve_ratio: Decimal | None = Field(default=None, ge=0, le=1)
    reserve_minimum: int | None = Field(default=None, ge=0)
```

Update `_dt_out`:

```python
def _dt_out(d: DutyType) -> DutyTypeOut:
    return DutyTypeOut(
        id=d.id, name=d.name, score_per_day=d.score_per_day,
        description=d.description, active=d.active,
        requirements=d.requirements or {},
        reserve_ratio=d.reserve_ratio or Decimal("0.000"),
        reserve_minimum=d.reserve_minimum or 0,
    )
```

Update the `create_duty_type` route body to pass new fields:

```python
        dt = svc.create_duty_type(
            session,
            name=body.name,
            score_per_day=body.score_per_day,
            description=body.description,
            reserve_ratio=body.reserve_ratio,
            reserve_minimum=body.reserve_minimum,
            actor_id=user.id,
        )
```

Update the `update_duty_type` route to pass new fields:

```python
        svc.update_duty_type(
            session, duty_type=dt,
            name=body.name, score_per_day=body.score_per_day,
            description=body.description, active=body.active,
            requirements=body.requirements,
            reserve_ratio=body.reserve_ratio,
            reserve_minimum=body.reserve_minimum,
            actor_id=user.id,
        )
```

- [ ] **Step 2: Update create_duty_type and update_duty_type in duty_config.py service**

In `backend/app/services/duty_config.py`, update `create_duty_type`:

```python
def create_duty_type(
    session: Session,
    *,
    name: str,
    score_per_day: Decimal,
    description: str | None = None,
    reserve_ratio: Decimal = Decimal("0.000"),
    reserve_minimum: int = 0,
    actor_id: uuid.UUID | None = None,
) -> DutyType:
    if score_per_day < 0:
        raise DutyConfigError("score_per_day must be >= 0")
    if session.execute(select(DutyType.id).where(DutyType.name == name)).first():
        raise DutyConfigError("name_taken")
    dt = DutyType(
        name=name, score_per_day=score_per_day, description=description,
        reserve_ratio=reserve_ratio, reserve_minimum=reserve_minimum,
    )
    session.add(dt)
    session.flush()
    write_audit(
        session, actor_id=actor_id, action="duty_type.create",
        entity_type="duty_type", entity_id=dt.id,
        after={"name": name, "score_per_day": str(score_per_day),
               "reserve_ratio": str(reserve_ratio), "reserve_minimum": reserve_minimum},
    )
    return dt
```

In `update_duty_type`, add the reserve fields to the before/after snapshot and update logic. Find the `update_duty_type` function and add after the existing field updates:

```python
    if reserve_ratio is not None:
        before["reserve_ratio"] = str(duty_type.reserve_ratio)
        duty_type.reserve_ratio = reserve_ratio
    if reserve_minimum is not None:
        before["reserve_minimum"] = duty_type.reserve_minimum
        duty_type.reserve_minimum = reserve_minimum
```

Also update the function signature to accept the new params:

```python
def update_duty_type(
    session: Session,
    *,
    duty_type: DutyType,
    name: str | None,
    score_per_day: Decimal | None,
    description: str | None,
    actor_id: uuid.UUID | None = None,
    requirements: dict | None = None,
    reserve_ratio: Decimal | None = None,
    reserve_minimum: int | None = None,
) -> DutyType:
```

- [ ] **Step 3: Add reserve_count_override to DutyShift routes**

In `backend/app/routes/shifts.py`, update `ShiftOut`:

```python
class ShiftOut(BaseModel):
    id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    required_count: int
    notes: str | None
    assigned_count: int
    fill_status: str
    reserve_count_override: int | None = None
    calculated_reserve_count: int | None = None
```

Update `CreateShiftRequest` and `UpdateShiftRequest`:

```python
class CreateShiftRequest(BaseModel):
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    required_count: int = Field(default=1, ge=1)
    notes: str | None = Field(default=None, max_length=1000)
    reserve_count_override: int | None = Field(default=None, ge=0)


class UpdateShiftRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    required_count: int | None = Field(default=None, ge=1)
    notes: str | None = None
    reserve_count_override: int | None = Field(default=None, ge=0)
```

Update `_out` to include reserve info. Import `reserve_count_for_shift` and the DutyType model. In the `_out` function, the `ShiftWithFill` doesn't have reserve data, so compute it inline:

```python
def _out(s: svc.ShiftWithFill, session: Session | None = None) -> ShiftOut:
    calculated = None
    if session is not None:
        from app.services.algorithm_bridge import reserve_count_for_shift
        from app.db.models import DutyShift as DutyShiftModel
        shift_obj = session.get(DutyShiftModel, s.id)
        if shift_obj is not None:
            calculated = reserve_count_for_shift(session, shift=shift_obj)
    return ShiftOut(
        id=s.id, duty_type_id=s.duty_type_id, duty_location_id=s.duty_location_id,
        start_date=s.start_date, end_date=s.end_date,
        required_count=s.required_count, notes=s.notes,
        assigned_count=s.assigned_count, fill_status=s.fill_status,
        reserve_count_override=s.reserve_count_override,
        calculated_reserve_count=calculated,
    )
```

Add `reserve_count_override` to `ShiftWithFill` in `backend/app/services/shifts.py`:

```python
@dataclass
class ShiftWithFill:
    id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    required_count: int
    notes: str | None
    created_by: uuid.UUID | None
    assigned_count: int
    fill_status: str
    reserve_count_override: int | None = None
```

Update `_to_with_fill` and `list_shifts` in `shifts.py` to include `reserve_count_override=shift.reserve_count_override`.

Update the `create_shift` route to accept and pass `reserve_count_override`. Update `update_shift` similarly.

Update all `_out(s)` calls in `shifts.py` routes to `_out(s, session)`.

- [ ] **Step 4: Verify import**

Run: `cd backend && .venv/Scripts/python.exe -c "from app.routes import duty_config, shifts; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/duty_config.py backend/app/services/duty_config.py backend/app/routes/shifts.py backend/app/services/shifts.py
git commit -m "feat(reserve): DutyType reserve fields + DutyShift reserve_count_override in routes"
```

---

## Task 10: New API routes + main.py wiring

**Files:**
- Create: `backend/app/routes/reserves.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create routes/reserves.py**

```python
from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, DutyDismissal, Soldier
from app.db.session import get_session
from app.services import reserves as svc

router = APIRouter(tags=["reserves"])


class CallUpRequest(BaseModel):
    from_date: date
    to_date: date


class DismissRequest(BaseModel):
    from_date: date
    to_date: date
    reason: str | None = Field(default=None, max_length=1000)


class DismissalOut(BaseModel):
    id: uuid.UUID
    duty_assignment_id: uuid.UUID
    dismissed_from: date
    dismissed_to: date
    reason: str | None
    created_at: datetime


class AssignmentOut(BaseModel):
    assignment_id: uuid.UUID
    soldier_id: uuid.UUID
    start_date: date
    end_date: date
    status: str


class PrimaryDetailOut(AssignmentOut):
    dismissals: list[DismissalOut]
    reserve_assignment_id: uuid.UUID | None
    reserve_hierarchy_distance: int | None


class ReserveDetailOut(AssignmentOut):
    called_up_from: date | None
    called_up_to: date | None
    primary_assignment_ids: list[uuid.UUID]


class ShiftReserveDetailOut(BaseModel):
    primaries: list[PrimaryDetailOut]
    reserves: list[ReserveDetailOut]


def _dismissal_out(d: dict) -> DismissalOut:
    return DismissalOut(
        id=d["id"], duty_assignment_id=d.get("duty_assignment_id", uuid.uuid4()),
        dismissed_from=d["from"], dismissed_to=d["to"], reason=d["reason"],
        created_at=datetime.now(),
    )


def _load_assignment(session: Session, assignment_id: uuid.UUID) -> DutyAssignment:
    a = session.get(DutyAssignment, assignment_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return a


@router.get("/shifts/{shift_id}/reserve-detail", response_model=ShiftReserveDetailOut)
def get_reserve_detail(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ShiftReserveDetailOut:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    detail = svc.get_shift_reserve_detail(session, shift_id=shift_id)
    primaries = [
        PrimaryDetailOut(
            assignment_id=p["assignment_id"], soldier_id=p["soldier_id"],
            start_date=p["start_date"], end_date=p["end_date"], status=p["status"],
            dismissals=[
                DismissalOut(
                    id=d["id"], duty_assignment_id=p["assignment_id"],
                    dismissed_from=d["from"], dismissed_to=d["to"],
                    reason=d["reason"], created_at=datetime.now(),
                ) for d in p["dismissals"]
            ],
            reserve_assignment_id=p["reserve_assignment_id"],
            reserve_hierarchy_distance=p["reserve_hierarchy_distance"],
        )
        for p in detail["primaries"]
    ]
    reserves = [
        ReserveDetailOut(
            assignment_id=r["assignment_id"], soldier_id=r["soldier_id"],
            start_date=r["start_date"], end_date=r["end_date"], status=r["status"],
            called_up_from=r["called_up_from"], called_up_to=r["called_up_to"],
            primary_assignment_ids=r["primary_assignment_ids"],
        )
        for r in detail["reserves"]
    ]
    return ShiftReserveDetailOut(primaries=primaries, reserves=reserves)


@router.post("/duty-assignments/{assignment_id}/call-up", response_model=dict)
def call_up(
    assignment_id: uuid.UUID,
    body: CallUpRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    a = _load_assignment(session, assignment_id)
    try:
        svc.call_up_reserve(session, assignment=a, from_date=body.from_date,
                            to_date=body.to_date, actor_id=user.id)
    except svc.ReserveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return {"called_up_from": a.called_up_from, "called_up_to": a.called_up_to}


@router.post("/duty-assignments/{assignment_id}/dismissals", response_model=DismissalOut,
             status_code=status.HTTP_201_CREATED)
def dismiss(
    assignment_id: uuid.UUID,
    body: DismissRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> DismissalOut:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    a = _load_assignment(session, assignment_id)
    try:
        d = svc.dismiss_primary(session, assignment=a, from_date=body.from_date,
                                to_date=body.to_date, reason=body.reason, actor_id=user.id)
    except svc.ReserveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(d)
    return DismissalOut(
        id=d.id, duty_assignment_id=d.duty_assignment_id,
        dismissed_from=d.dismissed_from, dismissed_to=d.dismissed_to,
        reason=d.reason, created_at=d.created_at,
    )


@router.delete("/duty-assignments/{assignment_id}/dismissals/{dismissal_id}",
               status_code=status.HTTP_204_NO_CONTENT)
def delete_dismissal(
    assignment_id: uuid.UUID,
    dismissal_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    d = session.get(DutyDismissal, dismissal_id)
    if d is None or d.duty_assignment_id != assignment_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        svc.delete_dismissal(session, dismissal=d, actor_id=user.id)
    except svc.ReserveError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
```

- [ ] **Step 2: Register in main.py**

In `backend/app/main.py`, add after the shifts import:

```python
from app.routes import reserves as reserve_routes
```

And after `app.include_router(shift_routes.router, prefix="/api")`:

```python
    app.include_router(reserve_routes.router, prefix="/api")
```

- [ ] **Step 3: Smoke-test**

Run: `cd backend && .venv/Scripts/python.exe -c "from app.main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Run full test suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest tests/ -q --tb=short 2>&1 | tail -10`
Expected: all passing (pre-existing authz failure is the only expected FAIL).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/reserves.py backend/app/main.py
git commit -m "feat(reserve): reserve API routes — call-up, dismissal, shift reserve-detail"
```

---

## Task 11: Frontend — API client + DutyType/DutyShift forms + i18n + System Settings

**Files:**
- Create: `frontend/src/api/reserves.ts`
- Modify: `frontend/src/pages/DutyConfigPage.tsx`
- Modify: `frontend/src/pages/DutyManagementPage.tsx`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Create frontend/src/api/reserves.ts**

```typescript
import { api } from "./client";

export interface DismissalRecord {
  id: string;
  duty_assignment_id: string;
  dismissed_from: string;
  dismissed_to: string;
  reason: string | null;
  created_at: string;
}

export interface PrimaryDetail {
  assignment_id: string;
  soldier_id: string;
  start_date: string;
  end_date: string;
  status: string;
  dismissals: DismissalRecord[];
  reserve_assignment_id: string | null;
  reserve_hierarchy_distance: number | null;
}

export interface ReserveDetail {
  assignment_id: string;
  soldier_id: string;
  start_date: string;
  end_date: string;
  status: string;
  called_up_from: string | null;
  called_up_to: string | null;
  primary_assignment_ids: string[];
}

export interface ShiftReserveDetail {
  primaries: PrimaryDetail[];
  reserves: ReserveDetail[];
}

export async function getShiftReserveDetail(shiftId: string): Promise<ShiftReserveDetail> {
  return (await api.get<ShiftReserveDetail>(`/shifts/${shiftId}/reserve-detail`)).data;
}

export async function callUpReserve(assignmentId: string, from_date: string, to_date: string): Promise<void> {
  await api.post(`/duty-assignments/${assignmentId}/call-up`, { from_date, to_date });
}

export async function dismissPrimary(
  assignmentId: string,
  from_date: string,
  to_date: string,
  reason?: string,
): Promise<DismissalRecord> {
  return (await api.post<DismissalRecord>(`/duty-assignments/${assignmentId}/dismissals`, { from_date, to_date, reason })).data;
}

export async function deleteDismissal(assignmentId: string, dismissalId: string): Promise<void> {
  await api.delete(`/duty-assignments/${assignmentId}/dismissals/${dismissalId}`);
}
```

- [ ] **Step 2: Add i18n keys to he.json**

In `frontend/src/i18n/he.json`, add inside the root object:

```json
  "reserve_ratio": "יחס רזרבה",
  "reserve_minimum": "מינימום רזרבה",
  "reserve_count_override": "ספירת רזרבה מותאמת",
  "reserve_calculated_count": "ספירת רזרבה מחושבת",
  "reserve_label": "ר",
  "reserve_standby": "רזרבה",
  "reserve_called_up": "הוקפץ",
  "reserve_dismissed": "משוחרר",
  "call_up_action": "הקפצה",
  "dismiss_action": "שחרור",
  "reserve_covers": "מכסה",
  "reserve_detail_title": "פירוט רזרבה",
  "primary_soldiers": "חיילים ראשיים",
  "reserve_soldiers": "רזרבות",
  "dismissed_from_to": "משוחרר {{from}}–{{to}}",
  "called_up_from_to": "הוקפץ {{from}}–{{to}}",
  "reserve_score_standby_multiplier": "מכפיל ניקוד רזרבה — המתנה",
  "reserve_score_called_up_multiplier": "מכפיל ניקוד רזרבה — הקפצה",
  "dismissed_score_multiplier": "מכפיל ניקוד — שחרור",
  "reserve_hierarchy_weight": "משקל קרבה היררכית לרזרבות"
```

- [ ] **Step 3: Add reserve_ratio and reserve_minimum to DutyType form in DutyConfigPage.tsx**

In `frontend/src/pages/DutyConfigPage.tsx`, find the DutyType create/edit modal/form fields and add:

```tsx
<div>
  <label className="block text-sm font-medium mb-1">{t("reserve_ratio")}</label>
  <input
    type="number" min="0" max="1" step="0.001"
    className="border rounded px-2 py-1 w-full"
    value={form.reserve_ratio ?? "0.000"}
    onChange={e => setForm(f => ({ ...f, reserve_ratio: e.target.value }))}
  />
  <p className="text-xs text-gray-500 mt-1">
    {t("reserve_calculated_count")}: {Math.ceil((form.required_count || 0) * parseFloat(form.reserve_ratio || "0"))}
  </p>
</div>
<div>
  <label className="block text-sm font-medium mb-1">{t("reserve_minimum")}</label>
  <input
    type="number" min="0" step="1"
    className="border rounded px-2 py-1 w-full"
    value={form.reserve_minimum ?? 0}
    onChange={e => setForm(f => ({ ...f, reserve_minimum: parseInt(e.target.value) || 0 }))}
  />
</div>
```

Include `reserve_ratio` and `reserve_minimum` in the create/update mutation body.

- [ ] **Step 4: Add reserve_count_override to Shift form in DutyManagementPage.tsx**

In the shift create/edit form, add:

```tsx
<div>
  <label className="block text-sm font-medium mb-1">
    {t("reserve_count_override")}
    {data?.calculated_reserve_count != null && (
      <span className="text-xs text-gray-500 ms-2">({t("reserve_calculated_count")}: {data.calculated_reserve_count})</span>
    )}
  </label>
  <input
    type="number" min="0" step="1" placeholder={String(data?.calculated_reserve_count ?? "")}
    className="border rounded px-2 py-1 w-full"
    value={form.reserve_count_override ?? ""}
    onChange={e => setForm(f => ({ ...f, reserve_count_override: e.target.value === "" ? null : parseInt(e.target.value) }))}
  />
</div>
```

- [ ] **Step 5: Add four new system settings rows**

In the system settings component/page (look for where `scoring.*` settings are rendered), add rows for:
- `scoring.reserve_standby_multiplier` — label from `t("reserve_score_standby_multiplier")`, default 0.2
- `scoring.reserve_called_up_multiplier` — label from `t("reserve_score_called_up_multiplier")`, default 1.3
- `scoring.dismissed_multiplier` — label from `t("dismissed_score_multiplier")`, default 0.0
- `fairness.reserve_hierarchy_weight` — label from `t("reserve_hierarchy_weight")`, default 0.5

- [ ] **Step 6: TypeScript check**

Run: `cd frontend && pnpm exec tsc --noEmit 2>&1 | grep -v node_modules | head -20`
Expected: no new errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/reserves.ts frontend/src/i18n/he.json frontend/src/pages/DutyConfigPage.tsx frontend/src/pages/DutyManagementPage.tsx
git commit -m "feat(reserve): frontend API client, DutyType/Shift forms, i18n, system settings"
```

---

## Task 12: Frontend — Unit Calendar badge + ShiftReservePanel

**Files:**
- Create: `frontend/src/components/ShiftReservePanel.tsx`
- Modify: `frontend/src/components/UnitCalendar.tsx`

- [ ] **Step 1: Create ShiftReservePanel.tsx**

```tsx
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  getShiftReserveDetail,
  callUpReserve,
  dismissPrimary,
  deleteDismissal,
} from "../api/reserves";

interface Props {
  shiftId: string;
  onClose: () => void;
}

export default function ShiftReservePanel({ shiftId, onClose }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery(
    ["shiftReserveDetail", shiftId],
    () => getShiftReserveDetail(shiftId),
  );

  const [callUpForm, setCallUpForm] = useState<{ assignmentId: string; from: string; to: string } | null>(null);
  const [dismissForm, setDismissForm] = useState<{ assignmentId: string; from: string; to: string; reason: string } | null>(null);

  const callUpMutation = useMutation(
    ({ id, from, to }: { id: string; from: string; to: string }) =>
      callUpReserve(id, from, to),
    { onSuccess: () => { qc.invalidateQueries(["shiftReserveDetail", shiftId]); setCallUpForm(null); } },
  );

  const dismissMutation = useMutation(
    ({ id, from, to, reason }: { id: string; from: string; to: string; reason: string }) =>
      dismissPrimary(id, from, to, reason || undefined),
    { onSuccess: () => { qc.invalidateQueries(["shiftReserveDetail", shiftId]); setDismissForm(null); } },
  );

  const deleteDismissalMutation = useMutation(
    ({ assignmentId, dismissalId }: { assignmentId: string; dismissalId: string }) =>
      deleteDismissal(assignmentId, dismissalId),
    { onSuccess: () => qc.invalidateQueries(["shiftReserveDetail", shiftId]) },
  );

  if (isLoading || !data) return <div className="p-4">{t("loading", "טוען...")}</div>;

  return (
    <div className="p-4 border rounded bg-white shadow-lg max-w-lg" dir="rtl">
      <div className="flex justify-between items-center mb-3">
        <h3 className="font-bold text-lg">{t("reserve_detail_title")}</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-700">✕</button>
      </div>

      {/* Primary soldiers */}
      <section className="mb-4">
        <h4 className="font-semibold text-sm text-gray-600 mb-2">{t("primary_soldiers")}</h4>
        {data.primaries.map(p => (
          <div key={p.assignment_id} className="border-b py-2 flex flex-col gap-1">
            <div className="flex justify-between items-center">
              <span className="font-medium text-sm">{p.soldier_id}</span>
              <button
                className="text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded"
                onClick={() => setDismissForm({ assignmentId: p.assignment_id, from: p.start_date, to: p.end_date, reason: "" })}
              >
                {t("dismiss_action")}
              </button>
            </div>
            {p.reserve_assignment_id && (
              <span className="text-xs text-gray-500">
                {t("reserve_standby")}: {p.reserve_assignment_id.slice(0, 8)}… (מרחק {p.reserve_hierarchy_distance ?? "?"})
              </span>
            )}
            {p.dismissals.map(d => (
              <div key={d.id} className="flex items-center gap-2 text-xs text-red-600">
                <span>{t("reserve_dismissed")} {d.dismissed_from}–{d.dismissed_to}</span>
                <button
                  className="underline text-gray-400"
                  onClick={() => deleteDismissalMutation.mutate({ assignmentId: p.assignment_id, dismissalId: d.id })}
                >
                  ביטול
                </button>
              </div>
            ))}
          </div>
        ))}
      </section>

      {/* Reserve soldiers */}
      <section>
        <h4 className="font-semibold text-sm text-gray-600 mb-2">{t("reserve_soldiers")}</h4>
        {data.reserves.map(r => (
          <div key={r.assignment_id} className="border-b py-2 flex flex-col gap-1">
            <div className="flex justify-between items-center">
              <span className="font-medium text-sm">{r.soldier_id}</span>
              <button
                className="text-xs bg-blue-100 text-blue-800 px-2 py-0.5 rounded"
                onClick={() => setCallUpForm({ assignmentId: r.assignment_id, from: r.start_date, to: r.end_date })}
              >
                {t("call_up_action")}
              </button>
            </div>
            {r.called_up_from && (
              <span className="text-xs text-blue-600 font-medium">
                {t("reserve_called_up")} {r.called_up_from}–{r.called_up_to}
              </span>
            )}
            <span className="text-xs text-gray-500">
              {t("reserve_covers")}: {r.primary_assignment_ids.length > 0 ? `${r.primary_assignment_ids.length} חיילים` : "—"}
            </span>
          </div>
        ))}
      </section>

      {/* Call-up form */}
      {callUpForm && (
        <div className="mt-4 p-3 bg-blue-50 rounded">
          <h5 className="font-semibold text-sm mb-2">{t("call_up_action")}</h5>
          <div className="flex gap-2 mb-2">
            <input type="date" className="border rounded px-2 py-1 text-sm flex-1"
              value={callUpForm.from}
              onChange={e => setCallUpForm(f => f && ({ ...f, from: e.target.value }))} />
            <input type="date" className="border rounded px-2 py-1 text-sm flex-1"
              value={callUpForm.to}
              onChange={e => setCallUpForm(f => f && ({ ...f, to: e.target.value }))} />
          </div>
          <div className="flex gap-2">
            <button
              className="bg-blue-600 text-white text-sm px-3 py-1 rounded"
              onClick={() => callUpMutation.mutate({ id: callUpForm.assignmentId, from: callUpForm.from, to: callUpForm.to })}
            >
              אשר הקפצה
            </button>
            <button className="text-sm text-gray-600" onClick={() => setCallUpForm(null)}>ביטול</button>
          </div>
        </div>
      )}

      {/* Dismiss form */}
      {dismissForm && (
        <div className="mt-4 p-3 bg-amber-50 rounded">
          <h5 className="font-semibold text-sm mb-2">{t("dismiss_action")}</h5>
          <div className="flex gap-2 mb-2">
            <input type="date" className="border rounded px-2 py-1 text-sm flex-1"
              value={dismissForm.from}
              onChange={e => setDismissForm(f => f && ({ ...f, from: e.target.value }))} />
            <input type="date" className="border rounded px-2 py-1 text-sm flex-1"
              value={dismissForm.to}
              onChange={e => setDismissForm(f => f && ({ ...f, to: e.target.value }))} />
          </div>
          <input type="text" placeholder="סיבה (אופציונלי)" className="border rounded px-2 py-1 text-sm w-full mb-2"
            value={dismissForm.reason}
            onChange={e => setDismissForm(f => f && ({ ...f, reason: e.target.value }))} />
          <div className="flex gap-2">
            <button
              className="bg-amber-600 text-white text-sm px-3 py-1 rounded"
              onClick={() => dismissMutation.mutate({ id: dismissForm.assignmentId, from: dismissForm.from, to: dismissForm.to, reason: dismissForm.reason })}
            >
              אשר שחרור
            </button>
            <button className="text-sm text-gray-600" onClick={() => setDismissForm(null)}>ביטול</button>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Update UnitCalendar.tsx to show reserve badge and hook up panel**

In `frontend/src/components/UnitCalendar.tsx`, find where shift/duty blocks are rendered. Add:

1. Fetch reserve count alongside existing data. Since `ShiftOut` now includes `calculated_reserve_count`, use it from the existing shifts query.

2. In the shift block render, show reserve count badge:

```tsx
{/* Inside the shift block cell, after showing required_count or assigned_count: */}
{shift.calculated_reserve_count != null && shift.calculated_reserve_count > 0 && (
  <span className="text-xs text-purple-600 ms-1">
    +{shift.calculated_reserve_count}{t("reserve_label")}
  </span>
)}
```

3. Add click handler that opens `ShiftReservePanel` in a modal/drawer. Add state:

```tsx
const [reservePanelShiftId, setReservePanelShiftId] = useState<string | null>(null);
```

In the shift block onClick (or add one if it doesn't have one yet):

```tsx
onClick={() => setReservePanelShiftId(shift.id)}
```

Render the panel (conditionally) alongside the calendar:

```tsx
{reservePanelShiftId && (
  <div className="fixed inset-0 bg-black bg-opacity-20 flex items-center justify-center z-50"
       onClick={() => setReservePanelShiftId(null)}>
    <div onClick={e => e.stopPropagation()}>
      <ShiftReservePanel
        shiftId={reservePanelShiftId}
        onClose={() => setReservePanelShiftId(null)}
      />
    </div>
  </div>
)}
```

- [ ] **Step 3: TypeScript check**

Run: `cd frontend && pnpm exec tsc --noEmit 2>&1 | grep -v node_modules | head -20`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ShiftReservePanel.tsx frontend/src/components/UnitCalendar.tsx
git commit -m "feat(reserve): unit calendar reserve badge + ShiftReservePanel with הקפצה and dismissal"
```

---

## Self-review

**Spec coverage:**

- §2.1 DutyType columns → Task 1 ✅
- §2.2 DutyShift column → Task 1 ✅
- §2.3 DutyAssignment columns → Task 1 ✅
- §2.4 duty_dismissals → Task 1 ✅
- §2.5 duty_reserve_links + UNIQUE(primary_assignment_id) → Task 1 ✅
- §2.6 Drop reserve_assignments → Task 1 ✅
- §2.7 system_settings keys → Task 10 (four keys listed in system settings step) ✅, reserve_hierarchy_weight default seeded via SolverSettings default ✅
- §3.1 DutyBlock.is_reserve → Task 2 ✅
- §3.2 Reserve block generation + standby_multiplier → Task 5 ✅
- §3.3 Combined pass no-overlap/min-gap → enforced by existing constraints since all blocks enter one solve ✅
- §3.4 γ hierarchy term → Task 4 ✅
- §3.5 Post-solve link_reserves → Task 6 ✅
- §3.6 persist_results → Task 6 ✅
- §4.1 Multiplier lookup in scoring → Task 7 ✅
- §4.2 load_soldier_inputs uses new duty_score_by_soldier → already calls duty_score_by_soldier which is updated ✅
- §5.1 reserve services → Task 8 ✅
- §5.2 הקפצה + dismiss DM-only (ASSIGNMENT_MANAGE) → Task 10 routes call authorize(ASSIGNMENT_MANAGE) ✅
- §6 API routes → Task 10 ✅
- §7.1 DutyType form → Task 11 ✅
- §7.2 Shift form → Task 11 ✅
- §7.3 Calendar badge → Task 12 ✅
- §7.4 Shift detail panel → Task 12 ✅
- §7.5 System settings → Task 11 ✅
- §8 Migration 0025 → Task 1 ✅
- Swap system works for reserves unchanged → no changes needed (SwapRequest targets DutyAssignment regardless of is_reserve) ✅

**No placeholder scan issues found.**

**Type consistency check:**
- `ReserveLink` used in Tasks 3, 6 — consistent field names ✅
- `DutyDismissal` used in Tasks 1, 7, 8, 10 — consistent ✅
- `call_up_reserve` signature in Task 8 matches usage in Task 10 ✅
- `effective_duty_days` returns 4-tuple in Task 7; `duty_score_by_soldier` unpacks all 4 in Task 7 ✅
- `reserve_count_for_shift` imported in Task 5 and Task 9 — same import path ✅
