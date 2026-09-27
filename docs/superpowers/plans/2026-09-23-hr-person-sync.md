# HR Person Sync Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `run_person_sync`, an async function that fetches all HR users, creates/updates/holds/flags-vanished `Soldier`/`SoldierHrProfile` rows accordingly, reruns dependent logic on relevant changes, and aborts safely on anomalous data — plus two small retrofits to subsystem 3 so person placement has a durable HR-group-id → node-id lookup.

**Architecture:** `app/services/hr/person_sync.py` built incrementally: a placement resolver (reads a new `HrHierarchyNodeMap` table), per-person create/hold/update logic (reusing subsystem 2's `map_hr_user`/`HR_OWNED_FIELDS`/`record_sync_divergence` and existing dependent-logic functions), and the orchestration entry point tying fetch + anomaly-check + the per-person loop + vanished-detection together — each person's DB work committed independently. Subsystem 3's `_resolve_group` gets a small additive patch: it now also upserts `HrHierarchyNodeMap` and scopes its existing-node match by `level` in addition to `(name, parent)`.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 (`MappedAsDataclass`), Alembic, httpx/respx, pytest/pytest-asyncio, testcontainers-backed Postgres for DB-layer tests.

**Spec:** [docs/superpowers/specs/2026-09-23-hr-person-sync-design.md](../specs/2026-09-23-hr-person-sync-design.md)

## Global Constraints

- `password_hash`/`role` are **never** written for a person who links to an *existing* Justice soldier (whether previously manually enrolled or already HR-linked) — only genuinely new `Soldier` rows get the placeholder password (`hash_password(secrets.token_hex(16))`) + `must_change_password=True`, matching Excel import's exact precedent.
- `hierarchy_node_id` is set **only at `Soldier` creation time**. It is never rewritten on update, for any already-existing soldier (manually enrolled or already HR-linked) — node placement changes go through the repo's existing, separate hierarchy-transfer-request mechanism, not this sync. This is a deliberate scope boundary, not an oversight.
- `HR_OWNED_FIELDS` (subsystem 2) governs which fields respect `overridden_fields`/`record_sync_divergence` on update. `is_officer`/`is_career` are **not** in that set (they're derived outputs, never manually editable per `SOLDIER_EDITABLE_FIELDS`) — always set directly from `MappedSoldierFields` on both create and update, no override tracking needed.
- Dependent-logic reruns (`app.services.soldiers._reset_rank_advancement`, `app.services.duty_eligibility_watch.recheck_soldier_assignments`) fire only when `rank`, `mandatory_end_date`, or `discharge_date` *actually changed* during an update — never on create, never when the change was skipped due to being locally overridden. `_reset_rank_advancement` is a private (underscore-prefixed) helper in `soldiers.py` with no existing external-module precedent for reuse — imported directly anyway, since duplicating its rank-ladder recompute logic would be worse than the minor privacy-convention break.
- Each person's DB work commits independently (`session.commit()` per successful person). An unhandled exception while processing one person rolls back just that person's changes, records an `HrPersonSyncError` row, and processing continues — never aborts the whole run.
- The anomaly check runs **before** any group/person data is touched, comparing this run's fetched count against the last `status="completed"` run's `total_fetched`, using `hr_sync.min_fraction_of_last_run` (new `SystemSetting`, default `0.5`, read via `get_setting`/`SettingNotFound` — no `get_setting_float` exists, so this is read as a plain string and cast). A first-ever run (no prior completed run) always proceeds.
- `sync_status="vanished"` is a flag only — no soft-delete, no notification to the affected soldier, no hierarchy change. A previously-`"vanished"` profile that reappears in a later run flips back to `"synced"`.
- `HrHierarchyNodeMap` is a join table (`hr_group_id` unique, `node_id` unique FK), not a column on `HierarchyNode` — keeps HR-sync bookkeeping in its own bounded context, consistent with `SoldierHrProfile` (subsystem 2) not living on `Soldier`.
- Current Alembic head at plan-authoring time: `20260924_hr_hierarchy_sync`. Confirm this is still current (`python -m alembic heads` from `backend/`) before writing each new migration's `down_revision`.
- `NotificationType` gains one new enum value, `hr_sync_anomaly_aborted`, via `ALTER TYPE notification_type ADD VALUE IF NOT EXISTS ...` (Postgres can't drop enum values, so `downgrade()` is a no-op `pass`, matching existing repo precedent).
- Target: 100% test coverage of `person_sync.py`; the `hierarchy_sync.py` retrofit's new lines covered by extending subsystem 3's existing test files.
- Docker/Postgres is expected to be available (confirmed working throughout subsystem 3's implementation) — DB-layer tasks should run for real against live Postgres, with the `DATABASE_URL`/`DB_ADMIN_URL` host rewritten from `db` to `localhost` (this shell isn't under `dev.ps1`).

---

## Task 1: Subsystem 3 retrofit — `HrHierarchyNodeMap` + `_resolve_group` patch

**Files:**
- Modify: `backend/app/db/models.py` (add `HrHierarchyNodeMap`)
- Create: `backend/alembic/versions/20260925_hr_hierarchy_node_map.py`
- Modify: `backend/app/services/hr/hierarchy_sync.py` (patch `_resolve_group`)
- Modify: `backend/tests/unit/test_hr_hierarchy_sync.py` (append tests)

**Interfaces:**
- Consumes: nothing new from this plan; extends subsystem 3's already-merged `_resolve_group`.
- Produces: `HrHierarchyNodeMap` model; `_resolve_group` now upserts it on both `"matched"` and `"created"` outcomes, and its existing-node lookup is scoped by `(name, parent_id, level)` instead of `(name, parent_id)` — consumed by Task 3 (`resolve_placement_node_id`).

- [ ] **Step 1: Confirm the current Alembic head**

Run (from `backend/`, venv active): `python -m alembic heads`. If it is not `20260924_hr_hierarchy_sync`, use the actual head as this migration's `down_revision`.

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/unit/test_hr_hierarchy_sync.py`:

```python
def test_resolve_group_matched_upserts_node_map(admin_session):
    from app.db.models import HierarchyNode, HrHierarchyNodeMap

    existing = HierarchyNode(level="unit", name="Mapped Unit", parent_id=None, path_ids=[])
    admin_session.add(existing)
    admin_session.flush()
    existing.path_ids = [existing.id]
    admin_session.commit()

    group = _group("hr-map-1", "Mapped Unit", kind="unit")
    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})
    admin_session.commit()

    assert resolution.action == "matched"
    row = admin_session.execute(
        select(HrHierarchyNodeMap).where(HrHierarchyNodeMap.hr_group_id == "hr-map-1")
    ).scalar_one()
    assert row.node_id == existing.id


def test_resolve_group_created_upserts_node_map(admin_session):
    from app.db.models import HrHierarchyNodeMap

    group = _group("hr-map-2", "Brand New Unit", kind="unit")
    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})
    admin_session.commit()

    assert resolution.action == "created"
    row = admin_session.execute(
        select(HrHierarchyNodeMap).where(HrHierarchyNodeMap.hr_group_id == "hr-map-2")
    ).scalar_one()
    assert row.node_id == resolution.resolved_node_id


def test_resolve_group_node_map_upsert_is_idempotent_across_runs(admin_session):
    from app.db.models import HrHierarchyNodeMap

    group = _group("hr-map-3", "Idempotent Unit", kind="unit")
    _resolve_group(admin_session, group, hr_id_to_node_id={})
    admin_session.commit()
    # Re-resolve the same group in a later "run" — should match (not create
    # a duplicate node) and update the same map row, not insert a second one.
    resolution2 = _resolve_group(admin_session, group, hr_id_to_node_id={})
    admin_session.commit()

    assert resolution2.action == "matched"
    rows = admin_session.execute(
        select(HrHierarchyNodeMap).where(HrHierarchyNodeMap.hr_group_id == "hr-map-3")
    ).scalars().all()
    assert len(rows) == 1


def test_resolve_group_same_name_different_level_no_longer_ambiguous(admin_session):
    from app.db.models import HierarchyNode

    existing_team = HierarchyNode(level="team", name="Signal", parent_id=None, path_ids=[])
    admin_session.add(existing_team)
    admin_session.flush()
    existing_team.path_ids = [existing_team.id]
    admin_session.commit()

    # A "unit"-kind HR group with the same name and same (root) parent as
    # the existing "team" node must NOT be treated as ambiguous — different
    # level means it's a different real-world entity, so this should create
    # a new node rather than holding on "ambiguous match".
    group = _group("hr-map-4", "Signal", kind="unit")
    resolution = _resolve_group(admin_session, group, hr_id_to_node_id={})
    admin_session.commit()

    assert resolution.action == "created"
    assert resolution.resolved_node_id != existing_team.id
```

(`_group`, `_resolve_group`, `select` are already imported at the top of this test file from earlier tasks on subsystem 3 — reuse them, don't re-import.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/test_hr_hierarchy_sync.py -v -k "node_map or same_name_different_level"` (from `backend/`)
Expected: FAIL — `ImportError: cannot import name 'HrHierarchyNodeMap' from 'app.db.models'`.

- [ ] **Step 4: Add the `HrHierarchyNodeMap` model**

In `backend/app/db/models.py`, add this class directly after `HrHierarchySync`:

```python
class HrHierarchyNodeMap(Base):
    __tablename__ = "hr_hierarchy_node_map"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    hr_group_id: Mapped[str] = mapped_column(Text, unique=True)
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id", ondelete="CASCADE"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 5: Write the migration**

Create `backend/alembic/versions/20260925_hr_hierarchy_node_map.py` (adjust `down_revision` per Step 1 if needed):

```python
"""Add hr_hierarchy_node_map table

Revision ID: 20260925_hr_hierarchy_node_map
Revises: 20260924_hr_hierarchy_sync
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260925_hr_hierarchy_node_map"
down_revision = "20260924_hr_hierarchy_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_hierarchy_node_map",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("hr_group_id", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "node_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hierarchy_nodes.id", ondelete="CASCADE"), nullable=False, unique=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("hr_hierarchy_node_map")
```

- [ ] **Step 6: Patch `_resolve_group`**

In `backend/app/services/hr/hierarchy_sync.py`, add `HrHierarchyNodeMap` to the existing `from app.db.models import HierarchyNode, HrHierarchySync` import line (merge, don't duplicate).

Change the existing-node match query (currently filters by `parent_id`/`name` only) to also filter by `level`:

```python
    matches = session.execute(
        select(HierarchyNode).where(
            HierarchyNode.parent_id.is_(None) if parent_node_id is None
            else HierarchyNode.parent_id == parent_node_id,
            HierarchyNode.name == group.name,
            HierarchyNode.level == level,
        )
    ).scalars().all()
```

Add a small upsert helper above `_resolve_group`:

```python
def _upsert_group_node_map(session: Session, *, hr_group_id: str, node_id: uuid.UUID) -> None:
    existing = session.execute(
        select(HrHierarchyNodeMap).where(HrHierarchyNodeMap.hr_group_id == hr_group_id)
    ).scalar_one_or_none()
    if existing is None:
        session.add(HrHierarchyNodeMap(hr_group_id=hr_group_id, node_id=node_id))
    else:
        existing.node_id = node_id
```

Call it right before both success returns — the `"matched"` branch (after `if len(matches) == 1:`) and the `"created"` branch (after `node = hierarchy_service.create_node(...)`):

```python
    if len(matches) == 1:
        existing = matches[0]
        _upsert_group_node_map(session, hr_group_id=group.id, node_id=existing.id)
        return GroupResolution(
            hr_group_id=group.id, name=group.name, action="matched",
            resolved_node_id=existing.id, level=level, reason=None,
        )
```

```python
    node = hierarchy_service.create_node(session, level=level, name=group.name, parent_id=parent_node_id)
    _upsert_group_node_map(session, hr_group_id=group.id, node_id=node.id)
    return GroupResolution(
        hr_group_id=group.id, name=group.name, action="created",
        resolved_node_id=node.id, level=level, reason=None,
    )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/unit/test_hr_hierarchy_sync.py -v` (from `backend/`, with `DATABASE_URL`/`DB_ADMIN_URL` rewritten to `localhost`)
Expected: all tests in the file pass, including the 4 new ones.

- [ ] **Step 8: Run the full HR test suite to confirm no regressions**

Run: `pytest app/services/hr/tests tests/unit/test_hr_hierarchy_sync_model.py tests/unit/test_hr_hierarchy_sync.py -v` (from `backend/`)
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/20260925_hr_hierarchy_node_map.py backend/app/services/hr/hierarchy_sync.py backend/tests/unit/test_hr_hierarchy_sync.py
git commit -m "feat: add HrHierarchyNodeMap and scope node matching by level"
```

---

## Task 2: `HrPersonSync` / `HrPersonSyncError` models, migration, setting, notification type

**Files:**
- Modify: `backend/app/db/models.py` (add `HrPersonSync`, `HrPersonSyncError`, add `hr_sync_anomaly_aborted` to `NotificationType`)
- Create: `backend/alembic/versions/20260925_hr_person_sync.py`
- Test: `backend/tests/unit/test_hr_person_sync_model.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `HrPersonSync` (columns per spec), `HrPersonSyncError` (`id`, `hr_person_sync_id` FK, `personal_number`, `error_message`, `created_at`), `NotificationType.hr_sync_anomaly_aborted` — consumed by Task 6 (`run_person_sync`).

- [ ] **Step 1: Confirm the current Alembic head**

Run: `python -m alembic heads` (from `backend/`). If it is not `20260925_hr_hierarchy_node_map` (Task 1's migration), use the actual head.

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/unit/test_hr_person_sync_model.py`:

```python
from __future__ import annotations

from app.db.models import HrPersonSync, HrPersonSyncError


def test_create_hr_person_sync_defaults(admin_session):
    run = HrPersonSync()
    admin_session.add(run)
    admin_session.commit()
    admin_session.refresh(run)

    assert run.id is not None
    assert run.status == "running"
    assert run.started_at is not None
    assert run.completed_at is None
    assert run.total_fetched == 0
    assert run.created_count == 0
    assert run.updated_count == 0
    assert run.held_count == 0
    assert run.vanished_count == 0
    assert run.error_count == 0
    assert run.error_message is None


def test_hr_person_sync_completed_state_round_trips(admin_session):
    run = HrPersonSync(
        status="completed", total_fetched=10, created_count=3, updated_count=5,
        held_count=1, vanished_count=1, error_count=0,
    )
    admin_session.add(run)
    admin_session.commit()
    admin_session.refresh(run)

    assert run.status == "completed"
    assert run.total_fetched == 10
    assert run.created_count == 3


def test_hr_person_sync_aborted_anomaly_state_round_trips(admin_session):
    run = HrPersonSync(status="aborted_anomaly", total_fetched=2, error_message="too few users")
    admin_session.add(run)
    admin_session.commit()
    admin_session.refresh(run)

    assert run.status == "aborted_anomaly"
    assert run.error_message == "too few users"


def test_create_hr_person_sync_error(admin_session):
    run = HrPersonSync()
    admin_session.add(run)
    admin_session.commit()
    admin_session.refresh(run)

    error = HrPersonSyncError(
        hr_person_sync_id=run.id, personal_number="1234567", error_message="boom",
    )
    admin_session.add(error)
    admin_session.commit()
    admin_session.refresh(error)

    assert error.id is not None
    assert error.hr_person_sync_id == run.id
    assert error.personal_number == "1234567"
    assert error.error_message == "boom"
    assert error.created_at is not None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/test_hr_person_sync_model.py -v` (from `backend/`)
Expected: FAIL — `ImportError: cannot import name 'HrPersonSync' from 'app.db.models'`.

- [ ] **Step 4: Add the models and notification type**

In `backend/app/db/models.py`, add these two classes directly after `HrHierarchyNodeMap`:

```python
class HrPersonSync(Base):
    __tablename__ = "hr_person_syncs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'running'"), default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    total_fetched: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    created_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    updated_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    held_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    vanished_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    error_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)


class HrPersonSyncError(Base):
    __tablename__ = "hr_person_sync_errors"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    hr_person_sync_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hr_person_syncs.id", ondelete="CASCADE")
    )
    personal_number: Mapped[str] = mapped_column(Text)
    error_message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

In `backend/app/db/models.py`, find the `NotificationType` enum class and add one new member at the end of its existing list (exact insertion point: match the class's current last member and append after it):

```python
    hr_sync_anomaly_aborted = "hr_sync_anomaly_aborted"
```

- [ ] **Step 5: Write the migration**

Create `backend/alembic/versions/20260925_hr_person_sync.py` (adjust `down_revision` per Step 1 if needed):

```python
"""Add hr_person_syncs and hr_person_sync_errors tables, hr_sync_anomaly_aborted notification type

Revision ID: 20260925_hr_person_sync
Revises: 20260925_hr_hierarchy_node_map
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260925_hr_person_sync"
down_revision = "20260925_hr_hierarchy_node_map"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hr_person_syncs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("status", sa.Text(), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_fetched", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("updated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("held_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("vanished_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_table(
        "hr_person_sync_errors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "hr_person_sync_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("hr_person_syncs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("personal_number", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'hr_sync_anomaly_aborted'")


def downgrade() -> None:
    op.drop_table("hr_person_sync_errors")
    op.drop_table("hr_person_syncs")
    # Postgres cannot drop enum values; matches existing repo convention
    # (see b7c8d9e0f1a2_add_qualification_expiry_notification_types.py) of
    # not reversing ALTER TYPE ... ADD VALUE in downgrade.
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/test_hr_person_sync_model.py -v` (from `backend/`)
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/20260925_hr_person_sync.py backend/tests/unit/test_hr_person_sync_model.py
git commit -m "feat: add hr_person_syncs/hr_person_sync_errors tables and hr_sync_anomaly_aborted notification type"
```

---

## Task 3: Placement resolution

**Files:**
- Create: `backend/app/services/hr/person_sync.py`
- Test: `backend/tests/unit/test_hr_person_sync.py`

**Interfaces:**
- Consumes: `HrUser` from `app.services.hr.schemas`; `HrHierarchyNodeMap` from `app.db.models` (Task 1); `get_setting`/`SettingNotFound` from `app.services.settings_loader`.
- Produces: `resolve_placement_node_id(session, user: HrUser) -> uuid.UUID` — consumed by Task 4 (`_apply_new_person`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_hr_person_sync.py`:

```python
from __future__ import annotations

import uuid

from app.db.models import HierarchyNode, HrHierarchyNodeMap
from app.services.hr.person_sync import resolve_placement_node_id
from app.services.hr.schemas import HrUser
from app.services.settings_loader import set_setting


def _hr_user(**overrides: object) -> HrUser:
    defaults: dict[str, object] = dict(
        full_name="ישראל ישראלי", personal_number="ps-1",
        team_id=None, mador_id=None, branch_id=None,
        department_id=None, shetach_id=None, unit_id=None,
    )
    defaults.update(overrides)
    return HrUser(**defaults)


def _node(session, name: str) -> HierarchyNode:
    node = HierarchyNode(level="unit", name=name, parent_id=None, path_ids=[])
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    session.commit()
    return node


def _holding_node(session) -> HierarchyNode:
    node = _node(session, "Holding")
    set_setting(session, "system.holding_node_id", str(node.id), actor_id=None)
    session.commit()
    return node


def test_resolve_placement_prefers_team_id_over_others(admin_session):
    team_node = _node(admin_session, "Team Node")
    mador_node = _node(admin_session, "Mador Node")
    admin_session.add_all([
        HrHierarchyNodeMap(hr_group_id="team-1", node_id=team_node.id),
        HrHierarchyNodeMap(hr_group_id="mador-1", node_id=mador_node.id),
    ])
    admin_session.commit()

    user = _hr_user(team_id="team-1", mador_id="mador-1")
    node_id = resolve_placement_node_id(admin_session, user)

    assert node_id == team_node.id


def test_resolve_placement_falls_back_through_priority_order(admin_session):
    branch_node = _node(admin_session, "Branch Node")
    admin_session.add(HrHierarchyNodeMap(hr_group_id="branch-1", node_id=branch_node.id))
    admin_session.commit()

    # team_id and mador_id present but unresolved; branch_id resolves.
    user = _hr_user(team_id="team-unresolved", mador_id="mador-unresolved", branch_id="branch-1")
    node_id = resolve_placement_node_id(admin_session, user)

    assert node_id == branch_node.id


def test_resolve_placement_no_ids_present_uses_holding_node(admin_session):
    holding = _holding_node(admin_session)

    user = _hr_user()
    node_id = resolve_placement_node_id(admin_session, user)

    assert node_id == holding.id


def test_resolve_placement_unresolved_ids_use_holding_node(admin_session):
    holding = _holding_node(admin_session)

    user = _hr_user(team_id="nonexistent", unit_id="also-nonexistent")
    node_id = resolve_placement_node_id(admin_session, user)

    assert node_id == holding.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_hr_person_sync.py -v` (from `backend/`)
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.hr.person_sync'`.

- [ ] **Step 3: Implement `resolve_placement_node_id`**

Create `backend/app/services/hr/person_sync.py`:

```python
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import HrHierarchyNodeMap
from app.services.hr.schemas import HrUser
from app.services.settings_loader import SettingNotFound, get_setting

# Priority order for which org-unit id determines a person's placement.
# TODO: placeholder order, unconfirmed against real HR data — see design
# doc's "Open questions" section.
_PLACEMENT_ID_PRIORITY = ("team_id", "mador_id", "branch_id", "department_id", "shetach_id", "unit_id")


def _holding_node_id(session: Session) -> uuid.UUID:
    try:
        return uuid.UUID(get_setting(session, "system.holding_node_id"))
    except SettingNotFound as exc:
        raise RuntimeError("system.holding_node_id is not bootstrapped") from exc


def resolve_placement_node_id(session: Session, user: HrUser) -> uuid.UUID:
    for field_name in _PLACEMENT_ID_PRIORITY:
        group_id = getattr(user, field_name)
        if group_id is None:
            continue
        mapping = session.execute(
            select(HrHierarchyNodeMap).where(HrHierarchyNodeMap.hr_group_id == group_id)
        ).scalar_one_or_none()
        if mapping is not None:
            return mapping.node_id
    return _holding_node_id(session)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_hr_person_sync.py -v` (from `backend/`)
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hr/person_sync.py backend/tests/unit/test_hr_person_sync.py
git commit -m "feat: add HR person placement resolution"
```

---

## Task 4: New-person creation and held-for-review handling

**Files:**
- Modify: `backend/app/services/hr/person_sync.py` (append `_apply_new_person`, `_mark_held`)
- Modify: `backend/tests/unit/test_hr_person_sync.py` (append tests)

**Interfaces:**
- Consumes: `resolve_placement_node_id` (Task 3); `map_hr_user`, `MappedSoldierFields`, `HeldForReview` from `app.services.hr.mapping` (subsystem 2); `SoldierHrProfile`, `Soldier` from `app.db.models`.
- Produces: `_apply_new_person(session, user: HrUser, mapped: MappedSoldierFields) -> tuple[Soldier, SoldierHrProfile]`, `_mark_held(session, user: HrUser, held: HeldForReview) -> SoldierHrProfile` — consumed by Task 6 (`run_person_sync`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_hr_person_sync.py`:

```python
import secrets

from app.db.models import Soldier, SoldierHrProfile
from app.services.hr.mapping import HeldForReview, MappedSoldierFields, map_hr_user
from app.services.hr.person_sync import _apply_new_person, _mark_held


def _mapped(**overrides: object) -> MappedSoldierFields:
    defaults: dict[str, object] = dict(full_name="ישראל ישראלי", personal_number="ps-new-1")
    defaults.update(overrides)
    return MappedSoldierFields(**defaults)


def test_apply_new_person_creates_soldier_with_placeholder_password(admin_session):
    holding = _holding_node(admin_session)
    user = _hr_user(personal_number="ps-new-1", full_name="ישראל ישראלי")
    mapped = _mapped()

    soldier, profile = _apply_new_person(admin_session, user, mapped)
    admin_session.commit()

    assert soldier.personal_number == "ps-new-1"
    assert soldier.must_change_password is True
    assert soldier.hierarchy_node_id == holding.id
    assert profile.soldier_id == soldier.id
    assert profile.sync_status == "synced"


def test_apply_new_person_links_existing_soldier_without_touching_password(admin_session):
    from tests.helpers import create_soldier

    _holding_node(admin_session)
    existing = create_soldier(admin_session, personal_number="ps-existing-1")
    original_hash = existing.password_hash
    original_role = existing.role

    user = _hr_user(personal_number="ps-existing-1", full_name=existing.full_name)
    mapped = _mapped(personal_number="ps-existing-1", full_name=existing.full_name)

    soldier, profile = _apply_new_person(admin_session, user, mapped)
    admin_session.commit()

    assert soldier.id == existing.id
    assert soldier.password_hash == original_hash
    assert soldier.role == original_role
    assert profile.soldier_id == existing.id


def test_mark_held_creates_profile_without_soldier(admin_session):
    user = _hr_user(personal_number="ps-held-1")
    held = HeldForReview(personal_number="ps-held-1", reasons=["unmappable rank: 'x'"])

    profile = _mark_held(admin_session, user, held)
    admin_session.commit()

    assert profile.soldier_id is None
    assert profile.sync_status == "held_for_review"
    assert "unmappable rank" in profile.review_reason
    assert admin_session.query(Soldier).filter_by(personal_number="ps-held-1").first() is None


def test_mark_held_updates_existing_held_profile_not_duplicate(admin_session):
    user = _hr_user(personal_number="ps-held-2")
    held1 = HeldForReview(personal_number="ps-held-2", reasons=["first reason"])
    held2 = HeldForReview(personal_number="ps-held-2", reasons=["second reason"])

    _mark_held(admin_session, user, held1)
    admin_session.commit()
    _mark_held(admin_session, user, held2)
    admin_session.commit()

    rows = admin_session.query(SoldierHrProfile).filter_by(personal_number="ps-held-2").all()
    assert len(rows) == 1
    assert "second reason" in rows[0].review_reason
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_hr_person_sync.py -v -k "apply_new_person or mark_held"` (from `backend/`)
Expected: FAIL — `ImportError: cannot import name '_apply_new_person' from 'app.services.hr.person_sync'`.

- [ ] **Step 3: Implement `_apply_new_person` and `_mark_held`**

Add to `backend/app/services/hr/person_sync.py` (append):

```python
import secrets

from app.audit.writer import write_audit
from app.auth.password import hash_password
from app.db.models import Soldier, SoldierHrProfile
from app.services.hr.mapping import HeldForReview, MappedSoldierFields


def _find_or_create_soldier_hr_profile(session: Session, personal_number: str) -> SoldierHrProfile:
    profile = session.execute(
        select(SoldierHrProfile).where(SoldierHrProfile.personal_number == personal_number)
    ).scalar_one_or_none()
    if profile is None:
        profile = SoldierHrProfile(personal_number=personal_number, raw_dto={})
        session.add(profile)
        session.flush()
    return profile


def _apply_new_person(
    session: Session, user: HrUser, mapped: MappedSoldierFields,
) -> tuple[Soldier, SoldierHrProfile]:
    soldier = session.execute(
        select(Soldier).where(Soldier.personal_number == mapped.personal_number)
    ).scalar_one_or_none()

    if soldier is None:
        node_id = resolve_placement_node_id(session, user)
        soldier = Soldier(
            personal_number=mapped.personal_number,
            full_name=mapped.full_name,
            password_hash=hash_password(secrets.token_hex(16)),
            must_change_password=True,
            hierarchy_node_id=node_id,
            email=mapped.email,
            phone=mapped.phone,
            profile_picture_url=mapped.profile_picture_url,
            gender=mapped.gender,
            rank=mapped.rank,
            rank_track=mapped.rank_track,
            is_officer=mapped.is_officer,
            is_career=mapped.is_career,
            enlistment_date=mapped.enlistment_date,
            mandatory_end_date=mapped.mandatory_end_date,
            discharge_date=mapped.discharge_date,
        )
        session.add(soldier)
        session.flush()

    profile = _find_or_create_soldier_hr_profile(session, mapped.personal_number)
    profile.soldier_id = soldier.id
    profile.raw_dto = user.model_dump(by_alias=True)
    profile.sync_status = "synced"
    profile.review_reason = None
    profile.last_synced_at = datetime.now(tz=timezone.utc)
    return soldier, profile


def _mark_held(session: Session, user: HrUser, held: HeldForReview) -> SoldierHrProfile:
    profile = _find_or_create_soldier_hr_profile(session, held.personal_number)
    profile.raw_dto = user.model_dump(by_alias=True)
    profile.sync_status = "held_for_review"
    profile.review_reason = "; ".join(held.reasons)
    profile.last_synced_at = datetime.now(tz=timezone.utc)
    return profile
```

Add `from datetime import datetime, timezone` to the file's existing top-of-file imports (merge with any already present — check first).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_hr_person_sync.py -v` (from `backend/`)
Expected: all pass (4 from Task 3 + 4 new = 8).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hr/person_sync.py backend/tests/unit/test_hr_person_sync.py
git commit -m "feat: add HR person creation and held-for-review handling"
```

---

## Task 5: Existing-person update logic

**Files:**
- Modify: `backend/app/services/hr/person_sync.py` (append `_apply_existing_person`)
- Modify: `backend/tests/unit/test_hr_person_sync.py` (append tests)

**Interfaces:**
- Consumes: `HR_OWNED_FIELDS` from `app.services.hr.mapping` (subsystem 2); `record_sync_divergence` from `app.services.hr.divergence` (subsystem 2); `_reset_rank_advancement` from `app.services.soldiers`; `recheck_soldier_assignments` from `app.services.duty_eligibility_watch`.
- Produces: `_apply_existing_person(session, profile: SoldierHrProfile, user: HrUser, mapped: MappedSoldierFields) -> None` — consumed by Task 6 (`run_person_sync`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_hr_person_sync.py`:

```python
from app.services.hr.person_sync import _apply_existing_person


def _linked_profile(session, soldier) -> SoldierHrProfile:
    profile = SoldierHrProfile(
        personal_number=soldier.personal_number, raw_dto={}, soldier_id=soldier.id, sync_status="synced",
    )
    session.add(profile)
    session.commit()
    return profile


def test_apply_existing_person_updates_non_overridden_field(admin_session):
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="ps-upd-1")
    profile = _linked_profile(admin_session, soldier)
    user = _hr_user(personal_number="ps-upd-1")
    mapped = _mapped(personal_number="ps-upd-1", phone="050-1112222")

    _apply_existing_person(admin_session, profile, user, mapped)
    admin_session.commit()
    admin_session.refresh(soldier)

    assert soldier.phone == "050-1112222"


def test_apply_existing_person_skips_overridden_field_and_records_divergence(admin_session):
    from sqlalchemy import select as sa_select
    from tests.helpers import create_soldier
    from app.db.models import AuditLog

    soldier = create_soldier(admin_session, personal_number="ps-upd-2")
    soldier.phone = "050-0000000"
    admin_session.commit()
    profile = _linked_profile(admin_session, soldier)
    profile.overridden_fields = ["phone"]
    admin_session.commit()

    user = _hr_user(personal_number="ps-upd-2")
    mapped = _mapped(personal_number="ps-upd-2", phone="050-9998888")

    _apply_existing_person(admin_session, profile, user, mapped)
    admin_session.commit()
    admin_session.refresh(soldier)

    assert soldier.phone == "050-0000000"
    entries = admin_session.execute(
        sa_select(AuditLog).where(AuditLog.action == "hr_sync.field_skipped_overridden")
    ).scalars().all()
    assert len(entries) == 1


def test_apply_existing_person_reruns_dependent_logic_on_rank_change(admin_session, monkeypatch):
    from tests.helpers import create_soldier
    import app.services.hr.person_sync as person_sync_module

    soldier = create_soldier(admin_session, personal_number="ps-upd-3")
    profile = _linked_profile(admin_session, soldier)
    user = _hr_user(personal_number="ps-upd-3")
    mapped = _mapped(personal_number="ps-upd-3", rank="רסל")

    calls = []
    monkeypatch.setattr(
        person_sync_module, "_reset_rank_advancement",
        lambda session, s, *, since: calls.append(("rank", s.id)),
    )
    monkeypatch.setattr(
        person_sync_module, "recheck_soldier_assignments",
        lambda session, soldier_id: calls.append(("eligibility", soldier_id)),
    )

    _apply_existing_person(admin_session, profile, user, mapped)
    admin_session.commit()

    assert ("rank", soldier.id) in calls
    assert ("eligibility", soldier.id) in calls


def test_apply_existing_person_does_not_rerun_dependent_logic_when_untracked_field_changes(admin_session, monkeypatch):
    from tests.helpers import create_soldier
    import app.services.hr.person_sync as person_sync_module

    soldier = create_soldier(admin_session, personal_number="ps-upd-4")
    profile = _linked_profile(admin_session, soldier)
    user = _hr_user(personal_number="ps-upd-4")
    mapped = _mapped(personal_number="ps-upd-4", phone="050-1231234")

    calls = []
    monkeypatch.setattr(
        person_sync_module, "_reset_rank_advancement",
        lambda session, s, *, since: calls.append("rank"),
    )
    monkeypatch.setattr(
        person_sync_module, "recheck_soldier_assignments",
        lambda session, soldier_id: calls.append("eligibility"),
    )

    _apply_existing_person(admin_session, profile, user, mapped)
    admin_session.commit()

    assert calls == []


def test_apply_existing_person_flips_vanished_back_to_synced(admin_session):
    from tests.helpers import create_soldier

    soldier = create_soldier(admin_session, personal_number="ps-upd-5")
    profile = _linked_profile(admin_session, soldier)
    profile.sync_status = "vanished"
    admin_session.commit()

    user = _hr_user(personal_number="ps-upd-5")
    mapped = _mapped(personal_number="ps-upd-5")

    _apply_existing_person(admin_session, profile, user, mapped)
    admin_session.commit()

    assert profile.sync_status == "synced"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_hr_person_sync.py -v -k apply_existing_person` (from `backend/`)
Expected: FAIL — `ImportError: cannot import name '_apply_existing_person' from 'app.services.hr.person_sync'`.

- [ ] **Step 3: Implement `_apply_existing_person`**

Add to `backend/app/services/hr/person_sync.py` (append):

```python
from datetime import date

from app.services.duty_eligibility_watch import recheck_soldier_assignments
from app.services.hr.divergence import record_sync_divergence
from app.services.hr.mapping import HR_OWNED_FIELDS
from app.services.soldiers import _reset_rank_advancement

_DEPENDENT_LOGIC_TRIGGER_FIELDS = frozenset({"rank", "mandatory_end_date", "discharge_date"})


def _apply_existing_person(
    session: Session, profile: SoldierHrProfile, user: HrUser, mapped: MappedSoldierFields,
) -> None:
    soldier = session.get(Soldier, profile.soldier_id)
    changed_dependent_field = False

    for field_name in HR_OWNED_FIELDS:
        if field_name == "personal_number":
            continue
        new_value = getattr(mapped, field_name)
        if field_name in profile.overridden_fields:
            old_value = getattr(soldier, field_name)
            if old_value != new_value:
                record_sync_divergence(
                    session, soldier_hr_profile_id=profile.id, field_name=field_name,
                    hr_value=new_value, local_value=old_value,
                )
            continue
        old_value = getattr(soldier, field_name)
        if field_name in _DEPENDENT_LOGIC_TRIGGER_FIELDS and old_value != new_value:
            changed_dependent_field = True
        setattr(soldier, field_name, new_value)

    soldier.is_officer = mapped.is_officer
    soldier.is_career = mapped.is_career

    if changed_dependent_field:
        _reset_rank_advancement(session, soldier, since=date.today())
        recheck_soldier_assignments(session, soldier.id)

    profile.raw_dto = user.model_dump(by_alias=True)
    profile.sync_status = "synced"
    profile.last_synced_at = datetime.now(tz=timezone.utc)
```

Note: `_reset_rank_advancement`/`recheck_soldier_assignments` are called as **module-level names** (`_reset_rank_advancement(...)`, not `soldiers._reset_rank_advancement(...)`) specifically so the tests' `monkeypatch.setattr(person_sync_module, "_reset_rank_advancement", ...)` can intercept them — import them directly by name (`from app.services.soldiers import _reset_rank_advancement`, `from app.services.duty_eligibility_watch import recheck_soldier_assignments`), not via a module alias.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_hr_person_sync.py -v` (from `backend/`)
Expected: all pass (8 from Tasks 3-4 + 5 new = 13).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hr/person_sync.py backend/tests/unit/test_hr_person_sync.py
git commit -m "feat: add HR person update logic with override-aware field application"
```

---

## Task 6: Orchestration (`run_person_sync`)

**Files:**
- Modify: `backend/app/services/hr/person_sync.py` (append `run_person_sync` and its helpers)
- Modify: `backend/tests/unit/test_hr_person_sync.py` (append tests)

**Interfaces:**
- Consumes: `HrApiClient.iter_users` (subsystem 1); `map_hr_user` (subsystem 2); `_apply_new_person`/`_mark_held` (Task 4); `_apply_existing_person` (Task 5); `HrPersonSync`/`HrPersonSyncError` (Task 2); `create_notification`/`NotificationType` from `app.services.notifications`.
- Produces: `async def run_person_sync(session: Session, client: HrApiClient) -> HrPersonSync` — the subsystem's public entry point, not yet called from anywhere (no cron wiring in this plan).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_hr_person_sync.py`:

```python
import httpx
import respx

from app.db.models import HrPersonSync, HrPersonSyncError, Notification
from app.services.hr.person_sync import run_person_sync


def _user_payload(personal_number: str, **overrides: object) -> dict:
    payload = {"personalNumber": personal_number, "fullName": f"Soldier {personal_number}"}
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_run_person_sync_creates_new_people(admin_session):
    _holding_node(admin_session)
    payload = [_user_payload("ps-run-1"), _user_payload("ps-run-2")]
    with respx.mock(base_url="https://hr.example.internal") as mock:
        mock.get("/api/v1/user", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=payload)
        )
        mock.get("/api/v1/user", params={"take": "200", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_person_sync(admin_session, client)

    assert run.status == "completed"
    assert run.total_fetched == 2
    assert run.created_count == 2


@pytest.mark.asyncio
async def test_run_person_sync_marks_vanished_person(admin_session):
    from tests.helpers import create_soldier
    from app.db.models import SoldierHrProfile

    _holding_node(admin_session)
    soldier = create_soldier(admin_session, personal_number="ps-vanish-1")
    admin_session.add(SoldierHrProfile(
        personal_number="ps-vanish-1", raw_dto={}, soldier_id=soldier.id, sync_status="synced",
    ))
    admin_session.commit()

    with respx.mock(base_url="https://hr.example.internal") as mock:
        mock.get("/api/v1/user", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_person_sync(admin_session, client)

    assert run.status == "completed"
    assert run.vanished_count == 1
    profile = admin_session.execute(
        select(SoldierHrProfile).where(SoldierHrProfile.personal_number == "ps-vanish-1")
    ).scalar_one()
    assert profile.sync_status == "vanished"


@pytest.mark.asyncio
async def test_run_person_sync_aborts_on_anomaly_and_notifies_admins(admin_session):
    from tests.helpers import create_soldier

    admin = create_soldier(admin_session, personal_number="ps-admin-1", role="admin")
    prior_run = HrPersonSync(status="completed", total_fetched=100)
    admin_session.add(prior_run)
    admin_session.commit()

    with respx.mock(base_url="https://hr.example.internal") as mock:
        mock.get("/api/v1/user", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=[_user_payload("ps-only-one")])
        )
        mock.get("/api/v1/user", params={"take": "200", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_person_sync(admin_session, client)

    assert run.status == "aborted_anomaly"
    assert run.error_message is not None
    notifications = admin_session.execute(
        select(Notification).where(Notification.soldier_id == admin.id)
    ).scalars().all()
    assert len(notifications) == 1
    assert notifications[0].type == NotificationType.hr_sync_anomaly_aborted


@pytest.mark.asyncio
async def test_run_person_sync_first_run_has_no_baseline_and_proceeds(admin_session):
    _holding_node(admin_session)
    with respx.mock(base_url="https://hr.example.internal") as mock:
        mock.get("/api/v1/user", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=[_user_payload("ps-first-1")])
        )
        mock.get("/api/v1/user", params={"take": "200", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_person_sync(admin_session, client)

    assert run.status == "completed"
    assert run.created_count == 1


@pytest.mark.asyncio
async def test_run_person_sync_per_person_error_does_not_abort_run(admin_session, monkeypatch):
    import app.services.hr.person_sync as person_sync_module

    _holding_node(admin_session)
    payload = [_user_payload("ps-err-1"), _user_payload("ps-err-2")]

    original = person_sync_module._apply_new_person
    call_count = {"n": 0}

    def _flaky_apply_new_person(session, user, mapped):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated failure")
        return original(session, user, mapped)

    monkeypatch.setattr(person_sync_module, "_apply_new_person", _flaky_apply_new_person)

    with respx.mock(base_url="https://hr.example.internal") as mock:
        mock.get("/api/v1/user", params={"take": "200", "page": "1"}).mock(
            return_value=httpx.Response(200, json=payload)
        )
        mock.get("/api/v1/user", params={"take": "200", "page": "2"}).mock(
            return_value=httpx.Response(200, json=[])
        )
        async with HrApiClient(base_url="https://hr.example.internal", api_key="test-key") as client:
            run = await run_person_sync(admin_session, client)

    assert run.status == "completed"
    assert run.created_count == 1
    assert run.error_count == 1
    errors = admin_session.execute(
        select(HrPersonSyncError).where(HrPersonSyncError.hr_person_sync_id == run.id)
    ).scalars().all()
    assert len(errors) == 1
    assert errors[0].personal_number == "ps-err-1"
```

Add `import pytest`, `from sqlalchemy import select`, and `from app.db.models import NotificationType` to the test file's top-of-file imports if not already present (check first — `pytest` is likely already imported for `@pytest.mark.asyncio` markers elsewhere in the file from earlier tasks; `select` is used bare in this task's new tests — `select(Notification)`, `select(SoldierHrProfile)`, `select(HrPersonSyncError)` — and was not imported by any earlier task in this file, only aliased inline as `sa_select` in one Task 5 test).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_hr_person_sync.py -v -k run_person_sync` (from `backend/`)
Expected: FAIL — `ImportError: cannot import name 'run_person_sync' from 'app.services.hr.person_sync'`.

- [ ] **Step 3: Implement `run_person_sync`**

Add to `backend/app/services/hr/person_sync.py` (append):

```python
from app.db.models import HrPersonSync, HrPersonSyncError, NotificationType, Soldier
from app.services.hr.client import HrApiClient
from app.services.hr.mapping import map_hr_user
from app.services.notifications import create_notification


def _min_fraction_of_last_run(session: Session) -> float:
    try:
        return float(get_setting(session, "hr_sync.min_fraction_of_last_run"))
    except SettingNotFound:
        return 0.5


def _notify_admins_of_anomaly(session: Session, run: HrPersonSync) -> None:
    admins = session.execute(select(Soldier).where(Soldier.role == "admin")).scalars().all()
    for admin in admins:
        create_notification(
            session, soldier_id=admin.id, type=NotificationType.hr_sync_anomaly_aborted,
            title="HR sync aborted: unexpectedly few users returned",
            body=run.error_message,
        )


async def run_person_sync(session: Session, client: HrApiClient) -> HrPersonSync:
    run = HrPersonSync()
    session.add(run)
    session.commit()
    session.refresh(run)

    users = [user async for user in client.iter_users()]
    run.total_fetched = len(users)

    last_completed = session.execute(
        select(HrPersonSync)
        .where(HrPersonSync.status == "completed", HrPersonSync.id != run.id)
        .order_by(HrPersonSync.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if last_completed is not None and last_completed.total_fetched > 0:
        fraction = len(users) / last_completed.total_fetched
        if fraction < _min_fraction_of_last_run(session):
            run.status = "aborted_anomaly"
            run.error_message = (
                f"fetched {len(users)} users, below {_min_fraction_of_last_run(session):.0%} "
                f"of last run's {last_completed.total_fetched}"
            )
            run.completed_at = datetime.now(tz=timezone.utc)
            _notify_admins_of_anomaly(session, run)
            session.commit()
            return run

    seen_personal_numbers: set[str] = set()
    created = updated = held = error_count = 0

    for user in users:
        seen_personal_numbers.add(user.personal_number)
        try:
            mapped = map_hr_user(user)
            if isinstance(mapped, HeldForReview):
                _mark_held(session, user, mapped)
                held += 1
            else:
                profile = session.execute(
                    select(SoldierHrProfile).where(SoldierHrProfile.personal_number == mapped.personal_number)
                ).scalar_one_or_none()
                if profile is not None and profile.soldier_id is not None:
                    _apply_existing_person(session, profile, user, mapped)
                    updated += 1
                else:
                    _apply_new_person(session, user, mapped)
                    created += 1
            session.commit()
        except Exception as exc:
            session.rollback()
            session.add(HrPersonSyncError(
                hr_person_sync_id=run.id, personal_number=user.personal_number, error_message=str(exc),
            ))
            session.commit()
            error_count += 1

    vanished = 0
    linked_profiles = session.execute(
        select(SoldierHrProfile).where(
            SoldierHrProfile.soldier_id.is_not(None), SoldierHrProfile.sync_status == "synced",
        )
    ).scalars().all()
    for profile in linked_profiles:
        if profile.personal_number not in seen_personal_numbers:
            profile.sync_status = "vanished"
            vanished += 1
    session.commit()

    run.created_count = created
    run.updated_count = updated
    run.held_count = held
    run.vanished_count = vanished
    run.error_count = error_count
    run.status = "completed"
    run.completed_at = datetime.now(tz=timezone.utc)
    session.commit()
    return run
```

Add `from app.services.hr.schemas import HrUser` if not already present from Task 3, and move all new top-of-file-appropriate imports (`HrApiClient`, `map_hr_user`, `create_notification`, `HrPersonSync`, `HrPersonSyncError`, `NotificationType`) up to the file's existing import block rather than leaving them here — consolidate every import added across Tasks 3-6 into one clean top-of-file block before committing (a prior subsystem on this project had a plan-mandated mid-file-imports defect fixed after final review; get it right the first time here).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_hr_person_sync.py -v` (from `backend/`)
Expected: all pass (13 from Tasks 3-5 + 5 new = 18).

- [ ] **Step 5: Run the full HR test suite together**

Run: `pytest app/services/hr/tests tests/unit/test_hr_hierarchy_sync_model.py tests/unit/test_hr_hierarchy_sync.py tests/unit/test_hr_person_sync_model.py tests/unit/test_hr_person_sync.py -v` (from `backend/`)
Expected: all pass, no regressions.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/hr/person_sync.py backend/tests/unit/test_hr_person_sync.py
git commit -m "feat: add run_person_sync orchestration"
```

---

## Task 7: Coverage check and pytest marker registration

**Files:**
- Modify: `backend/tests/conftest.py` (marker routing, if needed)

**Interfaces:**
- Consumes: nothing new — verifies Tasks 1-6's output meets this plan's coverage bar and fits the existing pytest area-marker system.

- [ ] **Step 1: Check marker routing for the new test files**

Read `backend/tests/conftest.py`'s `_AREA_MARKERS` dict directly. Add `"test_hr_person_sync_model"` and `"test_hr_person_sync"` if absent — `soldiers` is the natural fit (per its `pyproject.toml` description: "soldier profile, soldier listing, Excel import"), consistent with how subsystem 2's person-adjacent test files were routed. Confirm `test_hr_hierarchy_sync`/`test_hr_hierarchy_sync_model` (subsystem 3, already routed to `hierarchy`) don't need any change from this plan's Task 1 additions to those same files.

- [ ] **Step 2: Run the new tests via their resolved markers to confirm routing**

Run (from `backend/`): `pytest tests app/services/hr/tests -m "misc or hierarchy or soldiers" -v`
Expected: includes this plan's new test files among the results.

- [ ] **Step 3: Run coverage for `person_sync.py`**

Run (from `backend/`):
```bash
pytest tests/unit/test_hr_person_sync.py tests/unit/test_hr_person_sync_model.py --cov=app.services.hr.person_sync --cov-report=term-missing -v
```
Expected: 100% coverage. If any lines are missed, add a targeted test in the relevant existing test file for that branch and re-run until 100%, or document precisely what remains uncovered and why.

- [ ] **Step 4: Confirm the `hierarchy_sync.py` retrofit's new lines are covered**

Run (from `backend/`):
```bash
pytest app/services/hr/tests/test_hierarchy_sync_topo.py tests/unit/test_hr_hierarchy_sync.py --cov=app.services.hr.hierarchy_sync --cov-report=term-missing -v
```
Expected: still 100% (Task 1's new lines — the `_upsert_group_node_map` helper and the `level` filter — should already be covered by Task 1's own tests).

- [ ] **Step 5: Run the full fast backend suite to confirm no regressions**

Run (from `backend/`): `pytest -q`
Expected: all pass, no new failures introduced. A pre-existing, unrelated flake in `test_active_days_reference_settings.py` (a midnight date-boundary comparison, confirmed unrelated to HR sync on prior subsystems of this same project) is not a regression if it recurs — note it plainly if seen, don't chase it.

- [ ] **Step 6: Commit (if `conftest.py` changed)**

```bash
git add backend/tests/conftest.py
git commit -m "test: route new HR person sync tests to pytest markers"
```

---

## Self-Review Notes

- **Spec coverage:** placeholder password + `must_change_password` for new people only, `hierarchy_node_id` set only at creation, `HR_OWNED_FIELDS`-scoped override-aware updates, dependent-logic reruns only on tracked-field changes, vanished flag-only semantics with un-vanishing on reappearance, anomaly abort with admin notification, per-person rollback-and-continue error handling, the two subsystem-3 retrofits (`HrHierarchyNodeMap` upsert, `level`-scoped matching) — all covered across Tasks 1-7.
- **Deferred by design (per spec's Non-goals):** activation codes, admin review UI, cron wiring, Excel password export/import — correctly excluded.
- **Type consistency:** `resolve_placement_node_id` (Task 3) returns `uuid.UUID`, matches `Soldier.hierarchy_node_id`'s type exactly as consumed in Task 4's `_apply_new_person`. `_apply_new_person`/`_mark_held`'s signatures (Task 4) match exactly how Task 6's `run_person_sync` calls them. `_apply_existing_person` (Task 5) is called with the same `(session, profile, user, mapped)` shape Task 6 uses.
- **Import consolidation reminder:** Task 6's final step explicitly calls out consolidating all of Tasks 3-6's incrementally-added imports into one clean top-of-file block, directly addressing the exact mid-file-import defect class a prior subsystem on this project had to fix after its final review — getting it right the first time here.
