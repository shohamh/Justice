# HR Org Hierarchy Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `run_hierarchy_sync`, an async function that fetches all HR org groups via subsystem 1's `HrApiClient`, resolves them level-by-level onto Justice's `HierarchyNode` tree (auto-creating confident matches, holding the rest for review), and records the outcome in a new `HrHierarchySync` table — callable directly for now, not yet wired to a cron.

**Architecture:** A new `app/services/hr/hierarchy_sync.py` built incrementally: a pure topological-sort helper over HR groups' `parentId` chain (no DB), then DB-layer per-group resolution logic reusing the existing `hierarchy.create_node` service (kind→level mapping via an explicit dict, parent-scoped exact-name node matching, never guessing), then the orchestration function tying client-fetch + ordering + resolution + result-recording together inside one transaction with rollback-on-failure. A new `HrHierarchySync` model/table records each run's per-group results and stats for the (not-yet-built) admin review page.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 (`MappedAsDataclass`), Alembic, httpx/respx (for the HR client mock, no Docker needed), pytest/pytest-asyncio, testcontainers-backed Postgres for DB-layer tests.

**Spec:** [docs/superpowers/specs/2026-09-23-hr-hierarchy-sync-design.md](../specs/2026-09-23-hr-hierarchy-sync-design.md)

## Global Constraints

- HR `Group.kind` → Justice level-key mapping (`HR_GROUP_KIND_TO_LEVEL_MAP`) is an explicit dict only — an unmapped kind, or a mapped level key that isn't currently configured in `HierarchyLevelType`, means the group is held. Never guessed.
- A group is confidently placeable only if (1) its kind maps to a currently-valid level key, and (2) its parent is resolvable — `parentId is None` (root, matched-or-created by name among existing root nodes) or `parentId` references another HR group that already resolved *earlier in the same run*. An unresolved parent holds the child too — this falls out of processing order, no separate cascade step.
- Node matching is scoped by `(name, resolved_parent_node_id)` — never a flat name lookup across the whole tree.
- All node creation goes through `app.services.hierarchy.create_node` — never a raw `HierarchyNode(...)` insert — so `path_ids`/level-rank validation/audit logging stay centralized.
- This subsystem never references `system.holding_node_id` — an unresolved group gets no node and no attachment anywhere; it's simply recorded as held. That setting is a subsystem-4 (not yet planned) concern for placing *people*, not groups.
- The whole sync run (fetch + resolve + apply) happens inside one logical unit: the `HrHierarchySync` row's initial insert (marking a run as started) commits separately so a run is visible even if it later fails, but all node creation + the final result write either all land together or all roll back on any unhandled exception (`status="failed"`, `error_message` set, no partial tree).
- `run_hierarchy_sync` is `async def` (it awaits `client.iter_groups()`); the per-group resolution logic it calls is plain sync (SQLAlchemy `Session`, no async DB access anywhere in this codebase).
- Target: 100% test coverage of `hierarchy_sync.py`.
- Current Alembic head at plan-authoring time: `20260923_soldier_hr_profile`. Confirm this is still current (`python -m alembic heads` from `backend/`) before writing the new migration's `down_revision`.
- Valid seeded `HierarchyLevelType.key` values in the test DB template (`backend/tests/support/database.py`): `corps` (rank 1), `division` (2), `unit` (3), `department` (4), `branch` (5), `group` (6), `team` (7). Use these exact keys in test fixtures/mapping examples — not invented level names.

---

## Task 1: `HrHierarchySync` model and migration

**Files:**
- Modify: `backend/app/db/models.py` (add `HrHierarchySync` class)
- Create: `backend/alembic/versions/20260924_hr_hierarchy_sync.py`
- Test: `backend/tests/unit/test_hr_hierarchy_sync_model.py`

**Interfaces:**
- Consumes: nothing new (uses existing `Base`).
- Produces: `HrHierarchySync` model with columns `id`, `status`, `started_at`, `completed_at`, `parsed_state`, `created_count`, `matched_count`, `held_count`, `error_message` — consumed by Task 4 (`run_hierarchy_sync`).

- [ ] **Step 1: Confirm the current Alembic head**

Run (from `backend/`, venv active): `python -m alembic heads`
Note the output. If it is not `20260923_soldier_hr_profile`, use the actual head as this migration's `down_revision` instead.

- [ ] **Step 2: Write the failing model test**

Create `backend/tests/unit/test_hr_hierarchy_sync_model.py`:

```python
from __future__ import annotations

from app.db.models import HrHierarchySync


def test_create_hr_hierarchy_sync_defaults(admin_session):
    run = HrHierarchySync()
    admin_session.add(run)
    admin_session.commit()
    admin_session.refresh(run)

    assert run.id is not None
    assert run.status == "running"
    assert run.started_at is not None
    assert run.completed_at is None
    assert run.parsed_state == []
    assert run.created_count == 0
    assert run.matched_count == 0
    assert run.held_count == 0
    assert run.error_message is None


def test_hr_hierarchy_sync_completed_state_round_trips(admin_session):
    run = HrHierarchySync(
        status="completed",
        parsed_state=[
            {
                "hr_group_id": "g1", "name": "Unit A", "action": "created",
                "resolved_node_id": None, "level": "unit", "reason": None,
            }
        ],
        created_count=1,
        matched_count=0,
        held_count=0,
    )
    admin_session.add(run)
    admin_session.commit()
    admin_session.refresh(run)

    assert run.status == "completed"
    assert run.parsed_state[0]["action"] == "created"
    assert run.created_count == 1


def test_hr_hierarchy_sync_failed_state_round_trips(admin_session):
    run = HrHierarchySync(status="failed", error_message="boom")
    admin_session.add(run)
    admin_session.commit()
    admin_session.refresh(run)

    assert run.status == "failed"
    assert run.error_message == "boom"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_hr_hierarchy_sync_model.py -v` (from `backend/`)
Expected: FAIL — `ImportError: cannot import name 'HrHierarchySync' from 'app.db.models'` (or, if Docker/testcontainers is unavailable in your environment, verify by import only: `python -c "from app.db.models import HrHierarchySync"` should fail the same way — note this plainly in your report if so).

- [ ] **Step 4: Add the `HrHierarchySync` model**

In `backend/app/db/models.py`, add this class. Place it near `SoldierHrProfile` (e.g. directly after it), since both are HR-sync bookkeeping tables:

```python
class HrHierarchySync(Base):
    __tablename__ = "hr_hierarchy_syncs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'running'"), default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    parsed_state: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default_factory=list
    )
    created_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    matched_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    held_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
```

Every field has a default or is `init=False`, so `HrHierarchySync()` is valid with zero arguments (used to insert a "just started" row before anything else is known) — no dataclass-ordering issue since there are no required fields at all.

- [ ] **Step 5: Write the migration**

Create `backend/alembic/versions/20260924_hr_hierarchy_sync.py` (adjust `down_revision` per Step 1 if the head has moved):

```python
"""Add hr_hierarchy_syncs table

Revision ID: 20260924_hr_hierarchy_sync
Revises: 20260923_soldier_hr_profile
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260924_hr_hierarchy_sync"
down_revision = "20260923_soldier_hr_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_hierarchy_syncs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("status", sa.Text(), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parsed_state", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matched_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("held_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("hr_hierarchy_syncs")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/unit/test_hr_hierarchy_sync_model.py -v` (from `backend/`)
Expected: 3 passed. If Docker/testcontainers is unavailable, run `python -m alembic upgrade head` against whatever Postgres you have, or document plainly (with real command output, not just an assertion) what could and couldn't be verified — the last two subsystems on this project established that evidence bar; match it.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/20260924_hr_hierarchy_sync.py backend/tests/unit/test_hr_hierarchy_sync_model.py
git commit -m "feat: add hr_hierarchy_syncs table"
```

---

## Task 2: Topological ordering helper (pure)

**Files:**
- Create: `backend/app/services/hr/hierarchy_sync.py`
- Test: `backend/app/services/hr/tests/test_hierarchy_sync_topo.py`

**Interfaces:**
- Consumes: `HrGroup` from `app.services.hr.schemas` (subsystem 1).
- Produces: `_topological_order(groups: list[HrGroup]) -> list[HrGroup]` — consumed by Task 4 (`run_hierarchy_sync`).

This is the only part of `hierarchy_sync.py` that's pure (no DB) — later tasks add DB-dependent code to the same file, but this function itself never touches a session.

- [ ] **Step 1: Write the failing tests**

Create `backend/app/services/hr/tests/test_hierarchy_sync_topo.py`:

```python
from __future__ import annotations

from app.services.hr.hierarchy_sync import _topological_order
from app.services.hr.schemas import HrGroup


def _group(id: str, name: str, parent_id: str | None = None, kind: str = "unit") -> HrGroup:
    return HrGroup(id=id, name=name, kind=kind, parent_id=parent_id)


def test_topological_order_root_before_children_even_when_input_is_reversed():
    grandchild = _group("gc", "Grandchild", parent_id="c")
    child = _group("c", "Child", parent_id="r")
    root = _group("r", "Root", parent_id=None)

    ordered = _topological_order([grandchild, child, root])

    ids = [g.id for g in ordered]
    assert ids.index("r") < ids.index("c") < ids.index("gc")
    assert len(ordered) == 3


def test_topological_order_multiple_roots_and_interleaved_children():
    r1 = _group("r1", "Root 1")
    r2 = _group("r2", "Root 2")
    c1 = _group("c1", "Child 1", parent_id="r1")
    c2 = _group("c2", "Child 2", parent_id="r2")

    ordered = _topological_order([c1, r1, c2, r2])

    ids = [g.id for g in ordered]
    assert ids.index("r1") < ids.index("c1")
    assert ids.index("r2") < ids.index("c2")
    assert len(ordered) == 4


def test_topological_order_dangling_parent_reference_is_still_included():
    orphan = _group("o", "Orphan", parent_id="missing-parent-id")

    ordered = _topological_order([orphan])

    assert [g.id for g in ordered] == ["o"]


def test_topological_order_cycle_does_not_infinite_loop_and_includes_both():
    a = _group("a", "A", parent_id="b")
    b = _group("b", "B", parent_id="a")

    ordered = _topological_order([a, b])

    assert {g.id for g in ordered} == {"a", "b"}
    assert len(ordered) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest app/services/hr/tests/test_hierarchy_sync_topo.py -v` (from `backend/`)
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.hr.hierarchy_sync'`.

- [ ] **Step 3: Implement `_topological_order`**

Create `backend/app/services/hr/hierarchy_sync.py`:

```python
from __future__ import annotations

from app.services.hr.schemas import HrGroup

# HR's Group.kind -> Justice HierarchyLevelType.key. Unmapped kinds (and
# mapped keys that aren't currently configured in HierarchyLevelType) hold
# the group for review rather than guessing.
# TODO: placeholder kind strings, unconfirmed against real HR API data.
HR_GROUP_KIND_TO_LEVEL_MAP: dict[str, str] = {
    "unit": "unit",
    "department": "department",
    "branch": "branch",
    "mador": "group",
    "team": "team",
}


def _topological_order(groups: list[HrGroup]) -> list[HrGroup]:
    """Order groups so every group appears after its parent (by HR group
    id), when that's determinable. A dangling parent reference or a cycle
    among the remaining groups doesn't raise — those groups are appended
    at the end in their original relative order, and the per-group
    resolution logic (added in Task 3) holds them individually since their
    parent will never appear in the resolved-node map."""
    resolved_ids: set[str] = set()
    ordered: list[HrGroup] = []
    remaining = list(groups)
    while remaining:
        progressed = False
        still_remaining: list[HrGroup] = []
        for group in remaining:
            if group.parent_id is None or group.parent_id in resolved_ids:
                ordered.append(group)
                resolved_ids.add(group.id)
                progressed = True
            else:
                still_remaining.append(group)
        remaining = still_remaining
        if not progressed:
            ordered.extend(remaining)
            break
    return ordered
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest app/services/hr/tests/test_hierarchy_sync_topo.py -v` (from `backend/`)
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hr/hierarchy_sync.py backend/app/services/hr/tests/test_hierarchy_sync_topo.py
git commit -m "feat: add topological ordering helper for HR group hierarchy"
```

---

## Task 3: Per-group resolution (kind mapping, confidence rules, node matching/creation)

**Files:**
- Modify: `backend/app/services/hr/hierarchy_sync.py` (add `GroupResolution`, `_resolve_group`)
- Test: `backend/tests/unit/test_hr_hierarchy_sync.py`

**Interfaces:**
- Consumes: `_topological_order`'s output shape (a `list[HrGroup]`, though this task's tests call `_resolve_group` directly per-group, not through the topo helper); `HierarchyNode` from `app.db.models`; `app.services.hierarchy.create_node`, `app.services.hierarchy.get_level_rank`.
- Produces: `GroupResolution` (dataclass: `hr_group_id`, `name`, `action`, `resolved_node_id`, `level`, `reason`), `_resolve_group(session, group, *, hr_id_to_node_id) -> GroupResolution` — consumed by Task 4 (`run_hierarchy_sync`).

This task's tests are DB-layer (testcontainers Postgres) since node matching/creation needs a real session — no HTTP/client involved yet, so no respx needed here.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_hr_hierarchy_sync.py`:

```python
from __future__ import annotations

import uuid

from app.db.models import HierarchyNode
from app.services.hr.hierarchy_sync import GroupResolution, _resolve_group
from app.services.hr.schemas import HrGroup


def _group(id: str, name: str, parent_id: str | None = None, kind: str = "unit") -> HrGroup:
    return HrGroup(id=id, name=name, kind=kind, parent_id=parent_id)


def test_resolve_group_root_with_no_existing_match_creates_node(admin_session):
    group = _group("hr-1", "New Unit", kind="unit")

    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})
    admin_session.commit()

    assert resolution.action == "created"
    assert resolution.level == "unit"
    assert resolution.reason is None
    node = admin_session.get(HierarchyNode, resolution.resolved_node_id)
    assert node.name == "New Unit"
    assert node.parent_id is None


def test_resolve_group_root_matching_existing_node_by_name(admin_session):
    existing = HierarchyNode(level="unit", name="Existing Unit", parent_id=None, path_ids=[])
    admin_session.add(existing)
    admin_session.flush()
    existing.path_ids = [existing.id]
    admin_session.commit()

    group = _group("hr-1", "Existing Unit", kind="unit")
    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})

    assert resolution.action == "matched"
    assert resolution.resolved_node_id == existing.id
    assert resolution.reason is None


def test_resolve_group_child_with_resolved_parent_creates_under_it(admin_session):
    parent_node_id = uuid.uuid4()
    parent_node = HierarchyNode(level="unit", name="Parent Unit", parent_id=None, path_ids=[])
    admin_session.add(parent_node)
    admin_session.flush()
    parent_node.path_ids = [parent_node.id]
    admin_session.commit()

    group = _group("hr-child", "Child Branch", parent_id="hr-parent", kind="branch")
    resolution = _resolve_group(
        admin_session, group, hr_id_to_node_id={"hr-parent": parent_node.id}
    )
    admin_session.commit()

    assert resolution.action == "created"
    node = admin_session.get(HierarchyNode, resolution.resolved_node_id)
    assert node.parent_id == parent_node.id
    assert node.level == "branch"


def test_resolve_group_unmapped_kind_is_held(admin_session):
    group = _group("hr-1", "Mystery Group", kind="some_unknown_kind")

    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})

    assert resolution.action == "held"
    assert resolution.resolved_node_id is None
    assert "some_unknown_kind" in resolution.reason


def test_resolve_group_mapped_level_not_configured_is_held(admin_session, monkeypatch):
    # HR_GROUP_KIND_TO_LEVEL_MAP only maps to level keys the test DB
    # template happens to seed (see Global Constraints), so exercising the
    # "kind maps to *something*, but that level key isn't configured in
    # HierarchyLevelType" branch needs a map entry pointing at a level key
    # that's guaranteed absent — monkeypatch the module-level dict for the
    # duration of this test rather than relying on DB seeding quirks.
    import app.services.hr.hierarchy_sync as hierarchy_sync_module

    monkeypatch.setitem(
        hierarchy_sync_module.HR_GROUP_KIND_TO_LEVEL_MAP, "ghost_kind", "level_key_that_does_not_exist"
    )
    group = _group("hr-1", "Ghost Group", kind="ghost_kind")

    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})

    assert resolution.action == "held"
    assert resolution.resolved_node_id is None
    assert "level_key_that_does_not_exist" in resolution.reason


def test_resolve_group_unresolved_parent_is_held(admin_session):
    group = _group("hr-child", "Orphaned Child", parent_id="hr-parent-never-resolved", kind="branch")

    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})

    assert resolution.action == "held"
    assert resolution.resolved_node_id is None
    assert "hr-parent-never-resolved" in resolution.reason


def test_resolve_group_same_name_different_parents_both_resolve_independently(admin_session):
    parent_a = HierarchyNode(level="unit", name="Parent A", parent_id=None, path_ids=[])
    parent_b = HierarchyNode(level="unit", name="Parent B", parent_id=None, path_ids=[])
    admin_session.add_all([parent_a, parent_b])
    admin_session.flush()
    parent_a.path_ids = [parent_a.id]
    parent_b.path_ids = [parent_b.id]
    admin_session.commit()

    group_a = _group("hr-a", "Shared Name", parent_id="hr-parent-a", kind="branch")
    group_b = _group("hr-b", "Shared Name", parent_id="hr-parent-b", kind="branch")
    hr_id_to_node_id = {"hr-parent-a": parent_a.id, "hr-parent-b": parent_b.id}

    resolution_a = _resolve_group(admin_session, group_a, hr_id_to_node_id=hr_id_to_node_id)
    admin_session.commit()
    resolution_b = _resolve_group(admin_session, group_b, hr_id_to_node_id=hr_id_to_node_id)
    admin_session.commit()

    assert resolution_a.action == "created"
    assert resolution_b.action == "created"
    assert resolution_a.resolved_node_id != resolution_b.resolved_node_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_hr_hierarchy_sync.py -v` (from `backend/`)
Expected: FAIL — `ImportError: cannot import name 'GroupResolution' from 'app.services.hr.hierarchy_sync'` (or, if Docker is unavailable, verify the same failure at import/collection time and note the DB-dependent assertions couldn't run — same evidence standard as prior subsystems).

- [ ] **Step 3: Implement `GroupResolution` and `_resolve_group`**

Add to `backend/app/services/hr/hierarchy_sync.py` (append — don't touch `_topological_order` or the map constant from Task 2):

```python
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import HierarchyNode
from app.services import hierarchy as hierarchy_service


@dataclass(frozen=True)
class GroupResolution:
    hr_group_id: str
    name: str
    action: str  # "matched" | "created" | "held"
    resolved_node_id: uuid.UUID | None
    level: str | None
    reason: str | None


def _resolve_group(
    session: Session,
    group: HrGroup,
    *,
    hr_id_to_node_id: dict[str, uuid.UUID],
) -> GroupResolution:
    level = HR_GROUP_KIND_TO_LEVEL_MAP.get(group.kind) if group.kind else None
    if level is None:
        return GroupResolution(
            hr_group_id=group.id, name=group.name, action="held",
            resolved_node_id=None, level=None,
            reason=f"unmappable kind: {group.kind!r}",
        )
    if hierarchy_service.get_level_rank(session, level) is None:
        return GroupResolution(
            hr_group_id=group.id, name=group.name, action="held",
            resolved_node_id=None, level=None,
            reason=f"level not configured in Justice: {level!r}",
        )

    if group.parent_id is None:
        parent_node_id: uuid.UUID | None = None
        existing = session.execute(
            select(HierarchyNode).where(
                HierarchyNode.parent_id.is_(None), HierarchyNode.name == group.name
            )
        ).scalar_one_or_none()
    else:
        parent_node_id = hr_id_to_node_id.get(group.parent_id)
        if parent_node_id is None:
            return GroupResolution(
                hr_group_id=group.id, name=group.name, action="held",
                resolved_node_id=None, level=None,
                reason=f"parent group unresolved: {group.parent_id!r}",
            )
        existing = session.execute(
            select(HierarchyNode).where(
                HierarchyNode.parent_id == parent_node_id, HierarchyNode.name == group.name
            )
        ).scalar_one_or_none()

    if existing is not None:
        return GroupResolution(
            hr_group_id=group.id, name=group.name, action="matched",
            resolved_node_id=existing.id, level=level, reason=None,
        )

    node = hierarchy_service.create_node(session, level=level, name=group.name, parent_id=parent_node_id)
    return GroupResolution(
        hr_group_id=group.id, name=group.name, action="created",
        resolved_node_id=node.id, level=level, reason=None,
    )
```

(`HrGroup` is already imported at the top of the file from Task 2 — don't re-import it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_hr_hierarchy_sync.py -v` (from `backend/`)
Expected: 7 passed.

- [ ] **Step 5: Run the pure topo tests too, to confirm no regressions in the same file**

Run: `pytest app/services/hr/tests/test_hierarchy_sync_topo.py -v` (from `backend/`)
Expected: 4 passed (unchanged from Task 2).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/hr/hierarchy_sync.py backend/tests/unit/test_hr_hierarchy_sync.py
git commit -m "feat: add per-group HR hierarchy resolution logic"
```

---

## Task 4: Orchestration (`run_hierarchy_sync`)

**Files:**
- Modify: `backend/app/services/hr/hierarchy_sync.py` (add `run_hierarchy_sync`)
- Modify: `backend/tests/unit/test_hr_hierarchy_sync.py` (append tests)

**Interfaces:**
- Consumes: `HrApiClient.iter_groups` (subsystem 1), `_topological_order` (Task 2), `_resolve_group`/`GroupResolution` (Task 3), `HrHierarchySync` (Task 1).
- Produces: `async def run_hierarchy_sync(session: Session, client: HrApiClient) -> HrHierarchySync` — the subsystem's public entry point, not yet called from anywhere (no cron wiring in this plan).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_hr_hierarchy_sync.py`:

```python
import httpx
import pytest
import respx

from app.db.models import HrHierarchySync
from app.services.hr.client import HrApiClient
from app.services.hr.hierarchy_sync import run_hierarchy_sync


@pytest.mark.asyncio
async def test_run_hierarchy_sync_creates_root_and_child(admin_session):
    groups_payload = [
        {"id": "hr-root", "name": "Root Unit", "kind": "unit", "parentId": None},
        {"id": "hr-child", "name": "Child Branch", "kind": "branch", "parentId": "hr-root"},
    ]
    with respx.mock(base_url="https://hr.example.internal") as mock:
        mock.get("/api/v1/group", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=groups_payload)
        )
        mock.get("/api/v1/group", params={"take": "200", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_hierarchy_sync(admin_session, client)

    assert run.status == "completed"
    assert run.created_count == 2
    assert run.matched_count == 0
    assert run.held_count == 0
    assert len(run.parsed_state) == 2
    assert {entry["action"] for entry in run.parsed_state} == {"created"}


@pytest.mark.asyncio
async def test_run_hierarchy_sync_mixed_matched_created_held(admin_session):
    from app.db.models import HierarchyNode

    existing = HierarchyNode(level="unit", name="Already There", parent_id=None, path_ids=[])
    admin_session.add(existing)
    admin_session.flush()
    existing.path_ids = [existing.id]
    admin_session.commit()

    groups_payload = [
        {"id": "hr-existing", "name": "Already There", "kind": "unit", "parentId": None},
        {"id": "hr-new", "name": "New Root", "kind": "unit", "parentId": None},
        {"id": "hr-bad-kind", "name": "Mystery", "kind": "no_such_kind", "parentId": None},
    ]
    with respx.mock(base_url="https://hr.example.internal") as mock:
        mock.get("/api/v1/group", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=groups_payload)
        )
        mock.get("/api/v1/group", params={"take": "200", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_hierarchy_sync(admin_session, client)

    assert run.status == "completed"
    assert run.matched_count == 1
    assert run.created_count == 1
    assert run.held_count == 1


@pytest.mark.asyncio
async def test_run_hierarchy_sync_empty_group_list(admin_session):
    with respx.mock(base_url="https://hr.example.internal") as mock:
        mock.get("/api/v1/group", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_hierarchy_sync(admin_session, client)

    assert run.status == "completed"
    assert run.created_count == 0
    assert run.matched_count == 0
    assert run.held_count == 0
    assert run.parsed_state == []


@pytest.mark.asyncio
async def test_run_hierarchy_sync_failure_rolls_back_and_records_error(admin_session):
    from sqlalchemy import select

    with respx.mock(base_url="https://hr.example.internal") as mock:
        mock.get("/api/v1/group", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(500, text="HR server error")
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_hierarchy_sync(admin_session, client)

    assert run.status == "failed"
    assert run.error_message is not None
    all_runs = admin_session.execute(select(HrHierarchySync)).scalars().all()
    assert len(all_runs) == 1
    assert all_runs[0].id == run.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_hr_hierarchy_sync.py -v -k run_hierarchy_sync` (from `backend/`)
Expected: FAIL — `ImportError: cannot import name 'run_hierarchy_sync' from 'app.services.hr.hierarchy_sync'`.

- [ ] **Step 3: Implement `run_hierarchy_sync`**

Add to `backend/app/services/hr/hierarchy_sync.py` (append):

```python
from datetime import datetime, timezone
from typing import Any

from app.db.models import HrHierarchySync
from app.services.hr.client import HrApiClient


async def run_hierarchy_sync(session: Session, client: HrApiClient) -> HrHierarchySync:
    run = HrHierarchySync()
    session.add(run)
    session.commit()
    session.refresh(run)

    try:
        groups = [group async for group in client.iter_groups()]
        ordered = _topological_order(groups)

        hr_id_to_node_id: dict[str, uuid.UUID] = {}
        results: list[dict[str, Any]] = []
        created = matched = held = 0

        for group in ordered:
            resolution = _resolve_group(session, group, hr_id_to_node_id=hr_id_to_node_id)
            if resolution.resolved_node_id is not None:
                hr_id_to_node_id[group.id] = resolution.resolved_node_id
            if resolution.action == "created":
                created += 1
            elif resolution.action == "matched":
                matched += 1
            else:
                held += 1
            results.append(
                {
                    "hr_group_id": resolution.hr_group_id,
                    "name": resolution.name,
                    "action": resolution.action,
                    "resolved_node_id": str(resolution.resolved_node_id) if resolution.resolved_node_id else None,
                    "level": resolution.level,
                    "reason": resolution.reason,
                }
            )

        run.parsed_state = results
        run.created_count = created
        run.matched_count = matched
        run.held_count = held
        run.status = "completed"
        run.completed_at = datetime.now(tz=timezone.utc)
        session.commit()
    except Exception as exc:
        session.rollback()
        run.status = "failed"
        run.error_message = str(exc)
        run.completed_at = datetime.now(tz=timezone.utc)
        session.commit()

    return run
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_hr_hierarchy_sync.py -v` (from `backend/`)
Expected: all tests in the file pass — 7 from Task 3 plus 4 from this task, 11 total.

- [ ] **Step 5: Run the full HR test suite together**

Run: `pytest app/services/hr/tests tests/unit/test_hr_hierarchy_sync_model.py tests/unit/test_hr_hierarchy_sync.py -v` (from `backend/`)
Expected: all pass, no regressions against subsystems 1/2's existing tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/hr/hierarchy_sync.py backend/tests/unit/test_hr_hierarchy_sync.py
git commit -m "feat: add run_hierarchy_sync orchestration"
```

---

## Task 5: Coverage check and pytest marker registration

**Files:**
- Modify: `backend/tests/conftest.py` (marker routing, if needed)

**Interfaces:**
- Consumes: nothing new — verifies Tasks 1-4's output meets this plan's coverage bar and fits the existing pytest area-marker system.

- [ ] **Step 1: Check marker routing for the new test files**

`backend/app/services/hr/tests/test_hierarchy_sync_topo.py` is a new stem under the already-swept `app/services/hr/tests/` tree. Read `backend/tests/conftest.py`'s `_AREA_MARKERS` dict directly (a prior subsystem confirmed it's an explicit stem allow-list, not a catch-all) and add `"test_hierarchy_sync_topo": "misc"` if absent, matching the existing HR-client entries' style.

`backend/tests/unit/test_hr_hierarchy_sync_model.py` and `backend/tests/unit/test_hr_hierarchy_sync.py` are new stems under `tests/unit/`, already part of the default `testpaths = ["tests"]` sweep — add `_AREA_MARKERS` entries for both if missing. `hierarchy` (per its `pyproject.toml` description: "hierarchy nodes ... and duty-manager scope") is the natural fit — use that rather than `misc`, since this work is squarely about hierarchy nodes, not general infrastructure.

- [ ] **Step 2: Run the new tests via their resolved markers to confirm routing**

Run (from `backend/`): `pytest tests app/services/hr/tests -m "misc or hierarchy" -v`
Expected: includes `test_hierarchy_sync_topo.py`'s tests (under `misc`) and `test_hr_hierarchy_sync_model.py`/`test_hr_hierarchy_sync.py`'s tests (under `hierarchy`) among the results.

- [ ] **Step 3: Run coverage for `hierarchy_sync.py`**

Run (from `backend/`):
```bash
pytest app/services/hr/tests/test_hierarchy_sync_topo.py tests/unit/test_hr_hierarchy_sync.py --cov=app.services.hr.hierarchy_sync --cov-report=term-missing -v
```
Expected: 100% coverage. If any lines are missed, add a targeted test in the relevant existing test file for that branch and re-run until 100%, or document precisely what remains uncovered and why (e.g. a defensive branch genuinely unreachable in practice) if a good-faith effort doesn't close it.

- [ ] **Step 4: Run the full fast backend suite to confirm no regressions**

Run (from `backend/`): `pytest -q`
Expected: all pass, no new failures introduced. If Docker/testcontainers is unavailable in your environment, note that plainly with real command output and run whatever subset you can (at minimum everything under `app/services/hr/` and the new `tests/unit/test_hr_hierarchy_sync*.py` files) — do not claim full-suite verification you couldn't perform.

- [ ] **Step 5: Commit (if `conftest.py` changed)**

```bash
git add backend/tests/conftest.py
git commit -m "test: route new HR hierarchy sync tests to pytest markers"
```

---

## Self-Review Notes

- **Spec coverage:** explicit kind→level dict with held-not-guessed unmapped values, confidence rules (kind validity + parent resolvability), parent-scoped exact-name node matching, `create_node` reuse (never a raw insert), no `system.holding_node_id` reference anywhere in this subsystem, one-transaction-with-rollback safety, `HrHierarchySync` tracking table — all covered across Tasks 1-4.
- **Deferred by design (per spec's Non-goals):** person/Soldier placement, cron wiring, admin review UI — correctly excluded from this plan.
- **Type consistency:** `GroupResolution.resolved_node_id: uuid.UUID | None` (Task 3) matches `HierarchyNode.id`'s type and is correctly stringified (`str(resolution.resolved_node_id)`) before landing in `HrHierarchySync.parsed_state`'s JSONB (Task 4) — UUIDs aren't natively JSON-serializable, and this plan's code handles that explicitly rather than letting Task 4's `session.commit()` fail on it the way subsystem 2's `divergence.py` originally missed date serialization (a real defect from the final review of that plan) — this plan gets it right the first time by stringifying at the point of construction.
- **Topo-helper/resolution integration:** Task 4's `run_hierarchy_sync` passes `_topological_order`'s output directly into the `_resolve_group` loop, and `hr_id_to_node_id` is populated incrementally as each group resolves — confirmed the loop order matches what Task 2's tests already proved (parent processed before child), so Task 3's parent-lookup-by-`hr_id_to_node_id` logic works correctly when driven by Task 2's ordering, not just in Task 3's own hand-constructed-dict tests.
