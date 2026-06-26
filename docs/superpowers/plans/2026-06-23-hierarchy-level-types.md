# Hierarchy Level Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move hierarchy level types (corps/division/unit/.../team) out of hardcoded lists into a DB-backed, reorderable catalog that admins/duty-managers can extend via a drag-and-drop UI, and let any HIERARCHY_MANAGE-capable user change a node's level when editing it.

**Architecture:** New `hierarchy_level_types` table (key/label/rank) replaces the `LEVEL_ORDER` constant on both backend and frontend. `HierarchyNode.level` stays a free-text column (converted from a Postgres enum to `varchar(50)`) — enforcement of "child rank > parent rank" moves from a hardcoded list comparison to a DB rank lookup in `services/hierarchy.py`. Frontend gets a typed API client + `useLevelTypes()` hook that all dropdowns/badges read from instead of local constants.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), React + `@dnd-kit/sortable` (frontend, new dependency alongside the already-installed `@dnd-kit/core`).

---

## Important pre-existing context

- `HierarchyNode.level` is currently a **Postgres ENUM** (`hierarchy_level`), not a varchar, despite the spec saying it "remains a plain varchar" — the spec author assumed it was already a varchar. This plan converts it to `varchar(50)` as part of the migration; this is required for custom level keys to be insertable at all.
- `services/hierarchy.py::create_node` and `move_node` currently have **no level/rank validation at all** (the spec's "hotfix" mentioned in the background — confirmed by running `pytest tests/unit/test_hierarchy_service.py`, where `test_non_top_level_root_rejected` currently fails with "DID NOT RAISE"). This plan reinstates validation using DB ranks and removes/replaces the two tests that assumed root nodes must be `corps`.
- No frontend test files exist for `HierarchyTree`/`RenameNodeDialog`/`AddChildNodeDialog`/`AddRootNodeDialog` today, so there is nothing to "update" there per the spec's testing section — this plan does not add new frontend test files, consistent with current project convention for these components.
- `tests/conftest.py::_truncate_tables` truncates a fixed table list before every test and re-seeds `system_settings`. `hierarchy_level_types` must be added to that list and re-seeded the same way, or tests will see stale/duplicate level types across runs.

---

## File Structure

**Backend — new/modified:**
- Create: `backend/alembic/versions/0059_hierarchy_level_types.py`
- Modify: `backend/app/db/models.py` (new `HierarchyLevelType` model; `HierarchyNode.level` becomes `String(50)`)
- Modify: `backend/app/services/hierarchy.py` (rank-based validation, new level-type service functions)
- Modify: `backend/app/routes/hierarchy.py` (new level-type endpoints, `PATCH /nodes/{id}` extended, `CreateNodeRequest` regex removed)
- Modify: `backend/app/auth/authz.py` (new `Action.HIERARCHY_LEVEL_TYPE_MANAGE`)
- Modify: `backend/tests/conftest.py` (truncate + reseed `hierarchy_level_types`)
- Modify: `backend/tests/unit/test_hierarchy_service.py`
- Modify: `backend/tests/integration/test_hierarchy_api.py`

**Frontend — new/modified:**
- Create: `frontend/src/api/levelTypes.ts`
- Modify: `frontend/src/api/hierarchy.ts` (`updateNode` accepts `level`)
- Create: `frontend/src/hooks/useLevelTypes.ts`
- Create: `frontend/src/components/EditNodeDialog.tsx` (replaces `RenameNodeDialog.tsx`)
- Delete: `frontend/src/components/RenameNodeDialog.tsx`
- Modify: `frontend/src/components/AddChildNodeDialog.tsx`
- Modify: `frontend/src/components/AddRootNodeDialog.tsx`
- Modify: `frontend/src/components/HierarchyTree.tsx`
- Modify: `frontend/src/i18n/he.json`
- Modify: `frontend/package.json` (add `@dnd-kit/sortable`, `@dnd-kit/utilities`)

---

### Task 1: Migration — `hierarchy_level_types` table + convert `level` column

**Files:**
- Create: `backend/alembic/versions/0059_hierarchy_level_types.py`

- [ ] **Step 1: Write the migration**

```python
"""create hierarchy_level_types; convert hierarchy_nodes.level to varchar

Revision ID: 0059
Revises: 0058
Create Date: 2026-06-23
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None

_SEED_TYPES = [
    ("corps", "אגף", 1),
    ("division", "מערך", 2),
    ("unit", "יחידה", 3),
    ("department", "מרכז", 4),
    ("branch", "ענף", 5),
    ("group", "מדור", 6),
    ("team", "צוות", 7),
]


def upgrade() -> None:
    op.create_table(
        "hierarchy_level_types",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("key", sa.String(length=50), nullable=False, unique=True),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False, unique=True),
    )

    rows = ", ".join(
        f"(gen_random_uuid(), '{key}', '{label}', {rank})" for key, label, rank in _SEED_TYPES
    )
    op.execute(
        f"INSERT INTO hierarchy_level_types (id, key, label, rank) VALUES {rows}"
    )

    # hierarchy_nodes.level was a Postgres ENUM (hierarchy_level); convert to a
    # plain varchar so admin-defined custom level keys can be stored.
    op.execute(
        "ALTER TABLE hierarchy_nodes ALTER COLUMN level TYPE varchar(50) USING level::text"
    )
    op.execute("DROP TYPE IF EXISTS hierarchy_level")


def downgrade() -> None:
    LEVEL_ENUM = sa.Enum(
        "corps", "division", "unit", "department", "branch", "group", "team",
        name="hierarchy_level",
    )
    LEVEL_ENUM.create(op.get_bind(), checkfirst=True)
    op.execute(
        "ALTER TABLE hierarchy_nodes ALTER COLUMN level TYPE hierarchy_level USING level::hierarchy_level"
    )
    op.drop_table("hierarchy_level_types")
```

- [ ] **Step 2: Run the migration against the dev DB**

Run (from `backend/`, venv active): `alembic upgrade head`
Expected: prints `Running upgrade 0058 -> 0059, create hierarchy_level_types; convert hierarchy_nodes.level to varchar` with no errors.

- [ ] **Step 3: Sanity-check via psql or a quick script**

Run: `alembic current`
Expected: `0059 (head)`

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0059_hierarchy_level_types.py
git commit -m "feat: add hierarchy_level_types table, convert hierarchy_nodes.level to varchar"
```

---

### Task 2: `HierarchyLevelType` model + `HierarchyNode.level` type change

**Files:**
- Modify: `backend/app/db/models.py:102-125` (the `HierarchyNode` class)

- [ ] **Step 1: Update `HierarchyNode.level` and add `HierarchyLevelType`**

In `backend/app/db/models.py`, replace the `level` column definition (currently `Enum("corps", ..., name="hierarchy_level")`) with a plain `String(50)`, and add a new model directly above `class HierarchyNode(Base):`:

```python
class HierarchyLevelType(Base):
    __tablename__ = "hierarchy_level_types"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    key: Mapped[str] = mapped_column(String(50), unique=True)
    label: Mapped[str] = mapped_column(String(200))
    rank: Mapped[int] = mapped_column(Integer, unique=True)


class HierarchyNode(Base):
    __tablename__ = "hierarchy_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    level: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id"), nullable=True, default=None
    )
    commander_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id"), nullable=True, default=None
    )
    # NOT NULL at the DB level; the hierarchy service always assigns this before commit.
    path_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

(Only the `level` line and the new `HierarchyLevelType` class change — everything else in `HierarchyNode` stays as-is.)

- [ ] **Step 2: Verify the app still imports cleanly**

Run: `python -c "from app.db import models"` (from `backend/`, venv active)
Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat: add HierarchyLevelType model, change HierarchyNode.level to varchar"
```

---

### Task 3: Test infra — truncate/reseed `hierarchy_level_types`

**Files:**
- Modify: `backend/tests/conftest.py:121-263`

- [ ] **Step 1: Add the table to the truncate list and re-seed after truncation**

In `backend/tests/conftest.py`, add `"hierarchy_level_types"` to `_ALL_DATA_TABLES` (anywhere before `"hierarchy_nodes"`, since nodes reference level *keys* only, not a FK — order doesn't matter for CASCADE here, but keep it readable next to `hierarchy_nodes`):

```python
    "system_settings",
    "soldiers",
    "hierarchy_level_types",
    "hierarchy_nodes",
]
```

Add a seed-defaults list next to `_SYSTEM_SETTINGS_DEFAULTS`:

```python
_LEVEL_TYPE_DEFAULTS = [
    ("corps", "אגף", 1),
    ("division", "מערך", 2),
    ("unit", "יחידה", 3),
    ("department", "מרכז", 4),
    ("branch", "ענף", 5),
    ("group", "מדור", 6),
    ("team", "צוות", 7),
]
```

Extend `_truncate_tables` to re-insert these after the truncate, in the same `with admin_engine.begin() as conn:` block, right after the `system_settings` re-insert:

```python
        level_type_rows = ", ".join(
            f"(gen_random_uuid(), '{key}', '{label}', {rank})"
            for key, label, rank in _LEVEL_TYPE_DEFAULTS
        )
        conn.execute(text(f"INSERT INTO hierarchy_level_types (id, key, label, rank) VALUES {level_type_rows}"))
```

- [ ] **Step 2: Run the existing hierarchy test suite to confirm the fixture works**

Run: `pytest tests/unit/test_hierarchy_service.py tests/integration/test_hierarchy_api.py -q`
Expected: same failure as before (`test_non_top_level_root_rejected` still fails — that test is fixed in Task 4) and no new errors about `hierarchy_level_types` being empty or duplicated.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/conftest.py
git commit -m "test: truncate and reseed hierarchy_level_types between tests"
```

---

### Task 4: Rank-based validation in `create_node` / `move_node`

**Files:**
- Modify: `backend/app/services/hierarchy.py:1-52`
- Modify: `backend/tests/unit/test_hierarchy_service.py:52-70`

- [ ] **Step 1: Replace the two outdated root-restriction tests with rank-based ones**

In `backend/tests/unit/test_hierarchy_service.py`, replace `test_create_root_must_be_corps` and `test_non_top_level_root_rejected` (lines 52-61) with:

```python
def test_create_root_allows_any_level(admin_session):
    node = create_node(admin_session, level="division", name="מערך", parent_id=None, actor_id=None)
    admin_session.commit()
    assert node.parent_id is None
    assert node.path_ids == [node.id]


def test_create_child_rejects_rank_not_below_parent(admin_session):
    branch = seed_node(admin_session, level="branch", name="b")  # rank 5
    with pytest.raises(HierarchyError):
        create_node(admin_session, level="department", name="d", parent_id=branch.id, actor_id=None)  # rank 4 <= 5


def test_create_node_rejects_unknown_level(admin_session):
    with pytest.raises(HierarchyError):
        create_node(admin_session, level="not_a_real_level", name="x", parent_id=None, actor_id=None)
```

Also add, after `test_move_allows_any_level_below` (currently lines 41-49):

```python
def test_move_rejects_rank_not_below_new_parent(admin_session):
    dept = seed_node(admin_session, level="department", name="d")  # rank 4
    branch = seed_node(admin_session, level="branch", name="b", parent=dept)  # rank 5
    other_branch = seed_node(admin_session, level="branch", name="b2")  # rank 5
    with pytest.raises(HierarchyError):
        move_node(admin_session, node_id=branch.id, new_parent_id=other_branch.id, actor_id=None)  # 5 <= 5
```

- [ ] **Step 2: Run the new/updated tests to verify they fail**

Run: `pytest tests/unit/test_hierarchy_service.py -k "rank or allows_any_level or rejects_unknown_level" -q`
Expected: `test_create_root_allows_any_level` and `test_create_node_rejects_unknown_level` pass already (no behavior change needed for those), but `test_create_child_rejects_rank_not_below_parent` and `test_move_rejects_rank_not_below_new_parent` FAIL (no rank check exists yet).

- [ ] **Step 3: Implement `_get_level_rank` and wire it into `create_node` / `move_node`**

In `backend/app/services/hierarchy.py`, replace the top of the file (imports + `LEVEL_ORDER` + `create_node`) with:

```python
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import HierarchyLevelType, HierarchyNode, Soldier


class HierarchyError(Exception):
    """Raised on an invalid hierarchy operation (cycle, guard)."""


def _get_level_rank(session: Session, level_key: str) -> int | None:
    return session.execute(
        select(HierarchyLevelType.rank).where(HierarchyLevelType.key == level_key)
    ).scalar_one_or_none()


def create_node(
    session: Session,
    *,
    level: str,
    name: str,
    parent_id: uuid.UUID | None,
    commander_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> HierarchyNode:
    level_rank = _get_level_rank(session, level)
    if level_rank is None:
        raise HierarchyError(f"unknown level: {level}")
    if parent_id is None:
        parent = None
    else:
        parent = session.get(HierarchyNode, parent_id)
        if parent is None:
            raise HierarchyError("parent not found")
        parent_rank = _get_level_rank(session, parent.level)
        if parent_rank is None or level_rank <= parent_rank:
            raise HierarchyError("child level must rank below parent level")

    node = HierarchyNode(
        level=level, name=name, parent_id=parent_id, commander_id=commander_id, path_ids=[]
    )
    session.add(node)
    session.flush()  # populate node.id
    node.path_ids = [*parent.path_ids, node.id] if parent is not None else [node.id]
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="hierarchy_node.create",
        entity_type="hierarchy_node",
        entity_id=node.id,
        after={"level": level, "name": name, "parent_id": str(parent_id) if parent_id else None},
    )
    return node
```

Then, in `move_node`, insert the rank check right after the parent lookup (after `parent = session.get(HierarchyNode, new_parent_id)` / before `if node.id in parent.path_ids:`):

```python
        if node.id in parent.path_ids:
            raise HierarchyError("cannot move a node under its own descendant")
        node_rank = _get_level_rank(session, node.level)
        parent_rank = _get_level_rank(session, parent.level)
        if node_rank is None or parent_rank is None or node_rank <= parent_rank:
            raise HierarchyError("node level must rank below new parent level")
        new_base = list(parent.path_ids)
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/unit/test_hierarchy_service.py -q`
Expected: all PASS.

- [ ] **Step 5: Run the full hierarchy area to catch regressions**

Run: `pytest -m hierarchy -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/hierarchy.py backend/tests/unit/test_hierarchy_service.py
git commit -m "feat: reinstate create/move level validation using DB-backed ranks"
```

---

### Task 5: `create_level_type` / `delete_level_type` service functions

**Files:**
- Modify: `backend/app/services/hierarchy.py`
- Modify: `backend/tests/unit/test_hierarchy_service.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_hierarchy_service.py`:

```python
from app.db.models import HierarchyLevelType
from app.services.hierarchy import create_level_type, delete_level_type


def test_create_level_type_appends_at_max_rank_plus_one(admin_session):
    lt = create_level_type(admin_session, key="platoon", label="מחלקה", actor_id=None)
    admin_session.commit()
    assert lt.rank == 8  # 7 seeded types, ranks 1..7


def test_create_level_type_rejects_duplicate_key(admin_session):
    with pytest.raises(HierarchyError):
        create_level_type(admin_session, key="branch", label="ענף 2", actor_id=None)


def test_delete_level_type_rejected_if_in_use(admin_session):
    branch_type = admin_session.execute(
        select(HierarchyLevelType).where(HierarchyLevelType.key == "branch")
    ).scalar_one()
    seed_node(admin_session, level="branch", name="b")
    with pytest.raises(HierarchyError):
        delete_level_type(admin_session, id=branch_type.id, actor_id=None)


def test_delete_level_type_succeeds_when_unused(admin_session):
    lt = create_level_type(admin_session, key="platoon", label="מחלקה", actor_id=None)
    admin_session.commit()
    delete_level_type(admin_session, id=lt.id, actor_id=None)
    admin_session.commit()
    assert admin_session.get(HierarchyLevelType, lt.id) is None
```

`select` is already imported in this test file via `from sqlalchemy import text` — add `select` too: change the top import line to `from sqlalchemy import select, text`.

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/unit/test_hierarchy_service.py -k level_type -q`
Expected: FAIL with `ImportError: cannot import name 'create_level_type'`.

- [ ] **Step 3: Implement the two functions**

Append to `backend/app/services/hierarchy.py` (after `delete_node`, at the end of the file):

```python
def create_level_type(
    session: Session, *, key: str, label: str, actor_id: uuid.UUID | None = None
) -> HierarchyLevelType:
    existing = session.execute(
        select(HierarchyLevelType.id).where(HierarchyLevelType.key == key)
    ).first()
    if existing is not None:
        raise HierarchyError(f"level type key already exists: {key}")
    max_rank = session.execute(select(func.max(HierarchyLevelType.rank))).scalar_one() or 0
    level_type = HierarchyLevelType(key=key, label=label, rank=max_rank + 1)
    session.add(level_type)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="hierarchy_level_type.create",
        entity_type="hierarchy_level_type",
        entity_id=level_type.id,
        after={"key": key, "label": label, "rank": level_type.rank},
    )
    return level_type


def delete_level_type(
    session: Session, *, id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    level_type = session.get(HierarchyLevelType, id)
    if level_type is None:
        raise HierarchyError("level type not found")
    in_use = session.execute(
        select(HierarchyNode.id).where(HierarchyNode.level == level_type.key).limit(1)
    ).first()
    if in_use is not None:
        raise HierarchyError("cannot delete a level type that is in use")
    write_audit(
        session,
        actor_id=actor_id,
        action="hierarchy_level_type.delete",
        entity_type="hierarchy_level_type",
        entity_id=level_type.id,
        before={"key": level_type.key, "label": level_type.label},
    )
    session.delete(level_type)
```

Add `func` to the sqlalchemy import line at the top: `from sqlalchemy import func, select`.

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/unit/test_hierarchy_service.py -k level_type -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hierarchy.py backend/tests/unit/test_hierarchy_service.py
git commit -m "feat: add create_level_type/delete_level_type service functions"
```

---

### Task 6: `reorder_level_types` service function

**Files:**
- Modify: `backend/app/services/hierarchy.py`
- Modify: `backend/tests/unit/test_hierarchy_service.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_hierarchy_service.py`:

```python
from app.services.hierarchy import ReorderViolation, reorder_level_types


def test_reorder_level_types_happy_path(admin_session):
    types = admin_session.execute(
        select(HierarchyLevelType).order_by(HierarchyLevelType.rank)
    ).scalars().all()
    reversed_ids = [t.id for t in reversed(types)]
    reorder_level_types(admin_session, ordered_ids=reversed_ids, actor_id=None)
    admin_session.commit()
    by_id = {
        t.id: t.rank
        for t in admin_session.execute(select(HierarchyLevelType)).scalars().all()
    }
    assert by_id[reversed_ids[0]] == 1
    assert by_id[reversed_ids[-1]] == len(reversed_ids)


def test_reorder_level_types_rejects_partial_id_list(admin_session):
    types = admin_session.execute(
        select(HierarchyLevelType).order_by(HierarchyLevelType.rank)
    ).scalars().all()
    with pytest.raises(HierarchyError):
        reorder_level_types(admin_session, ordered_ids=[types[0].id], actor_id=None)


def test_reorder_level_types_detects_tree_violation(admin_session):
    dept = seed_node(admin_session, level="department", name="d")  # rank 4
    seed_node(admin_session, level="branch", name="b", parent=dept)  # rank 5
    types = {
        t.key: t
        for t in admin_session.execute(select(HierarchyLevelType)).scalars().all()
    }
    # Move "branch" (currently rank 5) above "department" (rank 4) -> would invert the pair.
    ordered = sorted(types.values(), key=lambda t: t.rank)
    ordered_ids = [t.id for t in ordered]
    dept_pos = next(i for i, t in enumerate(ordered) if t.key == "department")
    branch_pos = next(i for i, t in enumerate(ordered) if t.key == "branch")
    ordered_ids[dept_pos], ordered_ids[branch_pos] = ordered_ids[branch_pos], ordered_ids[dept_pos]
    with pytest.raises(ReorderViolation) as exc_info:
        reorder_level_types(admin_session, ordered_ids=ordered_ids, actor_id=None)
    assert len(exc_info.value.violations) == 1
    assert exc_info.value.violations[0]["parent"] == "d (מרכז)"
    assert exc_info.value.violations[0]["child"] == "b (ענף)"
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/unit/test_hierarchy_service.py -k reorder_level_types -q`
Expected: FAIL with `ImportError: cannot import name 'reorder_level_types'`.

- [ ] **Step 3: Implement `ReorderViolation` and `reorder_level_types`**

Append to `backend/app/services/hierarchy.py`:

```python
class ReorderViolation(HierarchyError):
    def __init__(self, violations: list[dict[str, str]]):
        self.violations = violations
        super().__init__("reorder_would_violate_tree")


def reorder_level_types(
    session: Session, *, ordered_ids: list[uuid.UUID], actor_id: uuid.UUID | None = None
) -> list[HierarchyLevelType]:
    all_types = session.execute(select(HierarchyLevelType)).scalars().all()
    if {t.id for t in all_types} != set(ordered_ids) or len(ordered_ids) != len(all_types):
        raise HierarchyError("ordered_ids must contain exactly all existing level type ids")

    new_rank_by_id = {type_id: i + 1 for i, type_id in enumerate(ordered_ids)}
    new_rank_by_key = {t.key: new_rank_by_id[t.id] for t in all_types}
    label_by_key = {t.key: t.label for t in all_types}

    nodes = session.execute(select(HierarchyNode)).scalars().all()
    nodes_by_id = {n.id: n for n in nodes}
    violations: list[dict[str, str]] = []
    for node in nodes:
        if node.parent_id is None:
            continue
        parent = nodes_by_id.get(node.parent_id)
        if parent is None:
            continue
        child_rank = new_rank_by_key.get(node.level)
        parent_rank = new_rank_by_key.get(parent.level)
        if child_rank is None or parent_rank is None:
            continue
        if child_rank <= parent_rank:
            violations.append(
                {
                    "parent": f"{parent.name} ({label_by_key[parent.level]})",
                    "child": f"{node.name} ({label_by_key[node.level]})",
                }
            )
    if violations:
        raise ReorderViolation(violations)

    before = {t.key: t.rank for t in all_types}
    for t in all_types:
        t.rank = new_rank_by_id[t.id]
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="hierarchy_level_type.reorder",
        entity_type="hierarchy_level_type",
        before={"ranks": before},
        after={"ranks": {t.key: t.rank for t in all_types}},
    )
    return sorted(all_types, key=lambda t: t.rank)
```

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/unit/test_hierarchy_service.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hierarchy.py backend/tests/unit/test_hierarchy_service.py
git commit -m "feat: add reorder_level_types with tree-violation detection"
```

---

### Task 7: `Action.HIERARCHY_LEVEL_TYPE_MANAGE`

**Files:**
- Modify: `backend/app/auth/authz.py:15-69`

- [ ] **Step 1: Add the action and register it as DM-global**

In `backend/app/auth/authz.py`, add to `class Action`:

```python
    HIERARCHY_LEVEL_TYPE_MANAGE = "hierarchy.level_type_manage"
```

And add it to `_DM_GLOBAL_ACTIONS` (same set `SHIFT_MANAGE` and `ALGORITHM_RUN` are in, since level-type management is a global catalog, not scoped to a node subtree):

```python
_DM_GLOBAL_ACTIONS = {
    Action.ALGORITHM_RUN,
    Action.SHIFT_MANAGE,
    Action.HIERARCHY_LEVEL_TYPE_MANAGE,
}
```

- [ ] **Step 2: Verify import**

Run: `python -c "from app.auth.authz import Action; print(Action.HIERARCHY_LEVEL_TYPE_MANAGE)"`
Expected: prints `hierarchy.level_type_manage`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/auth/authz.py
git commit -m "feat: add HIERARCHY_LEVEL_TYPE_MANAGE action for admin/duty_manager"
```

---

### Task 8: Level-type API routes

**Files:**
- Modify: `backend/app/routes/hierarchy.py`
- Modify: `backend/tests/integration/test_hierarchy_api.py`

- [ ] **Step 1: Write the failing integration tests**

Add to `backend/tests/integration/test_hierarchy_api.py`:

```python
def test_list_level_types_ordered_by_rank(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5000010", role="soldier")
    r = client.get("/api/hierarchy/level-types", headers=auth_headers(s))
    assert r.status_code == 200
    ranks = [t["rank"] for t in r.json()]
    assert ranks == sorted(ranks)


def test_create_level_type_as_admin(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000011", role="admin")
    r = client.post(
        "/api/hierarchy/level-types",
        headers=auth_headers(admin),
        json={"key": "platoon", "label": "מחלקה"},
    )
    assert r.status_code == 201
    assert r.json()["key"] == "platoon"


def test_create_level_type_rejects_soldier(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5000012", role="soldier")
    r = client.post(
        "/api/hierarchy/level-types",
        headers=auth_headers(s),
        json={"key": "platoon", "label": "מחלקה"},
    )
    assert r.status_code == 403


def test_create_level_type_duplicate_key_409(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000013", role="admin")
    r = client.post(
        "/api/hierarchy/level-types",
        headers=auth_headers(admin),
        json={"key": "branch", "label": "ענף 2"},
    )
    assert r.status_code == 409


def test_delete_level_type_in_use_409(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000014", role="admin")
    create_node(admin_session, level="branch", name="b")
    admin_session.commit()
    branch_id = admin_session.execute(
        text("SELECT id FROM hierarchy_level_types WHERE key = 'branch'")
    ).scalar_one()
    r = client.delete(f"/api/hierarchy/level-types/{branch_id}", headers=auth_headers(admin))
    assert r.status_code == 409


def test_reorder_level_types_violation_returns_409_with_violations(
    client: TestClient, admin_session: Session
):
    admin = create_soldier(admin_session, personal_number="5000015", role="admin")
    dept = create_node(admin_session, level="department", name="d")
    create_node(admin_session, level="branch", name="b", parent=dept)
    admin_session.commit()
    rows = admin_session.execute(
        text("SELECT id, key FROM hierarchy_level_types ORDER BY rank")
    ).all()
    ordered_ids = [str(r.id) for r in rows]
    dept_pos = next(i for i, r in enumerate(rows) if r.key == "department")
    branch_pos = next(i for i, r in enumerate(rows) if r.key == "branch")
    ordered_ids[dept_pos], ordered_ids[branch_pos] = ordered_ids[branch_pos], ordered_ids[dept_pos]
    r = client.put(
        "/api/hierarchy/level-types/reorder",
        headers=auth_headers(admin),
        json={"ordered_ids": ordered_ids},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["detail"] == "reorder_would_violate_tree"
    assert len(r.json()["detail"]["violations"]) == 1
```

Add the missing import at the top of the test file: `from sqlalchemy import text`.

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/integration/test_hierarchy_api.py -k level_type -q`
Expected: FAIL with 404s (routes don't exist yet).

- [ ] **Step 3: Implement the routes**

In `backend/app/routes/hierarchy.py`, add these imports at the top (alongside the existing ones):

```python
from app.db.models import HierarchyLevelType
```

Add new Pydantic models near the other `*Request`/`*Out` models:

```python
class LevelTypeOut(BaseModel):
    id: uuid.UUID
    key: str
    label: str
    rank: int


class CreateLevelTypeRequest(BaseModel):
    key: str = Field(min_length=1, max_length=50)
    label: str = Field(min_length=1, max_length=200)


class ReorderLevelTypesRequest(BaseModel):
    ordered_ids: list[uuid.UUID]


def _level_type_out(t: HierarchyLevelType) -> LevelTypeOut:
    return LevelTypeOut(id=t.id, key=t.key, label=t.label, rank=t.rank)
```

Add the new endpoints at the end of the file (after `get_tree`):

```python
@router.get("/level-types", response_model=list[LevelTypeOut])
def list_level_types(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[LevelTypeOut]:
    types = session.execute(
        select(HierarchyLevelType).order_by(HierarchyLevelType.rank)
    ).scalars().all()
    return [_level_type_out(t) for t in types]


@router.post("/level-types", response_model=LevelTypeOut, status_code=status.HTTP_201_CREATED)
def create_level_type_route(
    body: CreateLevelTypeRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> LevelTypeOut:
    authorize(session, user, Action.HIERARCHY_LEVEL_TYPE_MANAGE, target_node=None)
    try:
        level_type = svc.create_level_type(
            session, key=body.key, label=body.label, actor_id=user.id
        )
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    session.refresh(level_type)
    return _level_type_out(level_type)


@router.put("/level-types/reorder", response_model=list[LevelTypeOut])
def reorder_level_types_route(
    body: ReorderLevelTypesRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[LevelTypeOut]:
    authorize(session, user, Action.HIERARCHY_LEVEL_TYPE_MANAGE, target_node=None)
    try:
        types = svc.reorder_level_types(session, ordered_ids=body.ordered_ids, actor_id=user.id)
    except svc.ReorderViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"detail": "reorder_would_violate_tree", "violations": exc.violations},
        ) from exc
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return [_level_type_out(t) for t in types]


@router.delete("/level-types/{level_type_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_level_type_route(
    level_type_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    authorize(session, user, Action.HIERARCHY_LEVEL_TYPE_MANAGE, target_node=None)
    try:
        svc.delete_level_type(session, id=level_type_id, actor_id=user.id)
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
```

Also import `Action` (already imported) and `authorize` (already imported) — no new imports needed beyond `HierarchyLevelType`.

- [ ] **Step 4: Run tests to confirm they pass**

Run: `pytest tests/integration/test_hierarchy_api.py -q`
Expected: all PASS.

- [ ] **Step 5: Run full hierarchy area**

Run: `pytest -m hierarchy -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/hierarchy.py backend/tests/integration/test_hierarchy_api.py
git commit -m "feat: add /hierarchy/level-types CRUD + reorder endpoints"
```

---

### Task 9: `PATCH /hierarchy/nodes/{id}` — level change + dynamic `CreateNodeRequest`

**Files:**
- Modify: `backend/app/routes/hierarchy.py`
- Modify: `backend/app/services/hierarchy.py`
- Modify: `backend/tests/integration/test_hierarchy_api.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/integration/test_hierarchy_api.py`:

```python
def test_patch_node_changes_level_when_valid(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000016", role="admin")
    dept = create_node(admin_session, level="department", name="d")
    branch = create_node(admin_session, level="branch", name="b", parent=dept)
    admin_session.commit()
    r = client.patch(
        f"/api/hierarchy/nodes/{branch.id}",
        headers=auth_headers(admin),
        json={"level": "group"},
    )
    assert r.status_code == 200
    assert r.json()["level"] == "group"


def test_patch_node_rejects_level_violating_position(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000017", role="admin")
    dept = create_node(admin_session, level="department", name="d")
    branch = create_node(admin_session, level="branch", name="b", parent=dept)
    admin_session.commit()
    r = client.patch(
        f"/api/hierarchy/nodes/{branch.id}",
        headers=auth_headers(admin),
        json={"level": "corps"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid_level_for_position"


def test_create_node_with_custom_level_type(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000018", role="admin")
    dept = create_node(admin_session, level="department", name="d")
    admin_session.commit()
    r0 = client.post(
        "/api/hierarchy/level-types",
        headers=auth_headers(admin),
        json={"key": "platoon", "label": "מחלקה"},
    )
    assert r0.status_code == 201
    r = client.post(
        "/api/hierarchy/nodes",
        headers=auth_headers(admin),
        json={"level": "platoon", "name": "מחלקה א", "parent_id": str(dept.id)},
    )
    assert r.status_code == 201
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/integration/test_hierarchy_api.py -k "patch_node_changes_level or patch_node_rejects_level or custom_level_type" -q`
Expected: FAIL — `CreateNodeRequest.level` regex rejects `"platoon"` (422), and `UpdateNodeRequest` has no `level` field so it's silently ignored (the PATCH test would get a 200 but `level` unchanged).

- [ ] **Step 3: Add `change_level` service function**

In `backend/app/services/hierarchy.py`, append (after `delete_level_type`, or anywhere after `_get_level_rank` is defined):

```python
def change_node_level(
    session: Session, *, node_id: uuid.UUID, level: str, actor_id: uuid.UUID | None = None
) -> HierarchyNode:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HierarchyError("node not found")
    new_rank = _get_level_rank(session, level)
    if new_rank is None:
        raise HierarchyError("unknown level: " + level)

    if node.parent_id is not None:
        parent = session.get(HierarchyNode, node.parent_id)
        parent_rank = _get_level_rank(session, parent.level) if parent else None
        if parent_rank is None or new_rank <= parent_rank:
            raise HierarchyError("invalid_level_for_position")

    children = session.execute(
        select(HierarchyNode).where(HierarchyNode.parent_id == node_id)
    ).scalars().all()
    if children:
        child_ranks = [_get_level_rank(session, c.level) for c in children]
        if any(r is None for r in child_ranks) or new_rank >= min(child_ranks):
            raise HierarchyError("invalid_level_for_position")

    before = {"level": node.level}
    node.level = level
    write_audit(
        session,
        actor_id=actor_id,
        action="hierarchy_node.change_level",
        entity_type="hierarchy_node",
        entity_id=node.id,
        before=before,
        after={"level": level},
    )
    return node
```

- [ ] **Step 4: Wire it into the route, extend `UpdateNodeRequest`, and drop the `CreateNodeRequest` regex**

In `backend/app/routes/hierarchy.py`:

Replace the `CreateNodeRequest.level` field:

```python
class CreateNodeRequest(BaseModel):
    level: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
```

Replace `UpdateNodeRequest`:

```python
class UpdateNodeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    commander_id: uuid.UUID | None = None
    level: str | None = Field(default=None, min_length=1, max_length=50)
```

In `update_node`, add the level branch inside the existing `try:` block (after the `set_commander` call):

```python
        if body.name is not None:
            svc.rename_node(session, node_id=node_id, name=body.name, actor_id=user.id)
        if "commander_id" in body.model_fields_set:
            svc.set_commander(
                session, node_id=node_id, commander_id=body.commander_id, actor_id=user.id
            )
        if body.level is not None:
            svc.change_node_level(session, node_id=node_id, level=body.level, actor_id=user.id)
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
```

(The existing `except` clause already maps `HierarchyError` to 400; `invalid_level_for_position` is a plain string message so `str(exc)` returns exactly `"invalid_level_for_position"`, matching the spec's expected detail.)

- [ ] **Step 5: Run tests to confirm they pass**

Run: `pytest tests/integration/test_hierarchy_api.py -q`
Expected: all PASS.

- [ ] **Step 6: Run unit + integration hierarchy tests together**

Run: `pytest -m hierarchy -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/hierarchy.py backend/app/services/hierarchy.py backend/tests/integration/test_hierarchy_api.py
git commit -m "feat: allow changing a node's level via PATCH, accept dynamic level keys on create"
```

---

### Task 10: Full backend regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the fast suite**

Run: `pytest -q` (from `backend/`, venv active)
Expected: all PASS (no regressions from the enum->varchar conversion or the routes/service rewrite — pay special attention to `app/scripts/seed.py` callers and anything importing `LEVEL_ORDER`, which no longer exists).

- [ ] **Step 2: Grep for any remaining references to the removed `LEVEL_ORDER` constant**

Run: `grep -rn "LEVEL_ORDER" backend/`
Expected: no matches (the only prior definition was in `services/hierarchy.py`, now removed).

- [ ] **Step 3: Commit (only if Step 1 required fixes)**

If no fixes were needed, skip this step. Otherwise:

```bash
git add -A backend/
git commit -m "fix: resolve regressions from hierarchy level-type rework"
```

---

### Task 11: Frontend — `api/levelTypes.ts`

**Files:**
- Create: `frontend/src/api/levelTypes.ts`

- [ ] **Step 1: Write the typed API client**

```typescript
import { api } from "./client";

export interface LevelTypeDTO {
  id: string;
  key: string;
  label: string;
  rank: number;
}

export async function listLevelTypes(): Promise<LevelTypeDTO[]> {
  return (await api.get<LevelTypeDTO[]>("/hierarchy/level-types")).data;
}

export async function createLevelType(key: string, label: string): Promise<LevelTypeDTO> {
  return (await api.post<LevelTypeDTO>("/hierarchy/level-types", { key, label })).data;
}

export async function reorderLevelTypes(orderedIds: string[]): Promise<LevelTypeDTO[]> {
  return (await api.put<LevelTypeDTO[]>("/hierarchy/level-types/reorder", { ordered_ids: orderedIds })).data;
}

export async function deleteLevelType(id: string): Promise<void> {
  await api.delete(`/hierarchy/level-types/${id}`);
}
```

- [ ] **Step 2: Verify it compiles**

Run: `npx tsc --noEmit` (from `frontend/`)
Expected: no errors referencing `api/levelTypes.ts`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/levelTypes.ts
git commit -m "feat: add typed API client for hierarchy level types"
```

---

### Task 12: Frontend — `useLevelTypes` hook

**Files:**
- Create: `frontend/src/hooks/useLevelTypes.ts`

- [ ] **Step 1: Write the hook**

```typescript
import { useEffect, useState } from "react";
import { LevelTypeDTO, listLevelTypes } from "../api/levelTypes";

export function useLevelTypes() {
  const [levelTypes, setLevelTypes] = useState<LevelTypeDTO[]>([]);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLevelTypes(await listLevelTypes());
  }

  useEffect(() => {
    void refresh().finally(() => setLoading(false));
  }, []);

  return { levelTypes, loading, refresh };
}
```

- [ ] **Step 2: Verify it compiles**

Run: `npx tsc --noEmit` (from `frontend/`)
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useLevelTypes.ts
git commit -m "feat: add useLevelTypes hook"
```

---

### Task 13: Add `@dnd-kit/sortable` dependency

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install the package**

Run (from `frontend/`): `npm install @dnd-kit/sortable@^8.0.0 @dnd-kit/utilities@^3.2.2`
Expected: `package.json` and `package-lock.json` updated; `@dnd-kit/sortable` and `@dnd-kit/utilities` appear under `dependencies`.

- [ ] **Step 2: Verify it installed correctly**

Run: `npm ls @dnd-kit/sortable @dnd-kit/utilities` (from `frontend/`)
Expected: both listed with no `UNMET DEPENDENCY` errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "build: add @dnd-kit/sortable and @dnd-kit/utilities"
```

---

### Task 14: Frontend — `EditNodeDialog.tsx` (replaces `RenameNodeDialog.tsx`)

**Files:**
- Create: `frontend/src/components/EditNodeDialog.tsx`
- Delete: `frontend/src/components/RenameNodeDialog.tsx`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add new translation keys**

In `frontend/src/i18n/he.json`, inside the `"team"` object (near the existing `"rename_node"` key at line 175), add:

```json
    "edit_node": "עריכת יחידה",
    "level": "דרגה",
    "level_type_manager": "ניהול סוגי דרגות",
    "level_type_new_label": "תווית לסוג חדש",
    "level_type_add": "הוסף",
    "level_type_save_order": "שמור סדר",
    "level_type_delete_in_use": "לא ניתן למחוק סוג בשימוש",
    "level_type_reorder_violations": "הסדר החדש יפר את ההיררכיה הקיימת:",
```

Leave `"rename_node": "שינוי שם"` in place (still used as the dialog's section header for the name field, or can be removed if unused elsewhere — check with `grep -rn "team.rename_node" frontend/src` before removing; if only `RenameNodeDialog.tsx` used it, it's safe to delete it from `he.json` too once that file is deleted in Step 3).

- [ ] **Step 2: Extend `updateNode` to accept a `level`**

In `frontend/src/api/hierarchy.ts`, change the `updateNode` signature (it currently only accepts `name`/`commander_id`):

```typescript
export async function updateNode(id: string, input: { name?: string; commander_id?: string | null; level?: string }): Promise<NodeDTO> {
  return (await api.patch<NodeDTO>(`/hierarchy/nodes/${id}`, input)).data;
}
```

- [ ] **Step 3: Write `EditNodeDialog.tsx`**

```tsx
import { FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  DndContext,
  DragEndEvent,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { updateNode } from "../api/hierarchy";
import {
  LevelTypeDTO,
  createLevelType,
  deleteLevelType,
  reorderLevelTypes,
} from "../api/levelTypes";
import { useLevelTypes } from "../hooks/useLevelTypes";

interface Props {
  nodeId: string;
  currentName: string;
  currentLevel: string;
  parentRank: number | null;
  minChildRank: number | null;
  isAdmin: boolean;
  nodesUsingLevel: (key: string) => boolean;
  onClose: () => void;
  onRenamed: () => void;
}

function SortableLevelTypeRow({
  type,
  canDelete,
  onDelete,
}: {
  type: LevelTypeDTO;
  canDelete: boolean;
  onDelete: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: type.id });
  const style = { transform: CSS.Transform.toString(transform), transition };

  return (
    <li
      ref={setNodeRef}
      style={style}
      className="flex items-center gap-2 py-1 px-1 text-sm"
      data-testid={`level-type-row-${type.key}`}
    >
      <span {...attributes} {...listeners} className="cursor-grab text-gray-400 select-none">⠿</span>
      <span className="text-xs text-gray-400 w-6 text-center">{type.rank}</span>
      <span className="flex-1">{type.label}</span>
      {canDelete && (
        <button
          type="button"
          className="text-red-500 hover:underline text-xs"
          onClick={onDelete}
          data-testid={`level-type-delete-${type.key}`}
        >
          ✕
        </button>
      )}
    </li>
  );
}

export default function EditNodeDialog({
  nodeId,
  currentName,
  currentLevel,
  parentRank,
  minChildRank,
  isAdmin,
  nodesUsingLevel,
  onClose,
  onRenamed,
}: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState(currentName);
  const [level, setLevel] = useState(currentLevel);
  const { levelTypes, refresh } = useLevelTypes();
  const [orderedTypes, setOrderedTypes] = useState<LevelTypeDTO[] | null>(null);
  const [reorderDirty, setReorderDirty] = useState(false);
  const [violations, setViolations] = useState<{ parent: string; child: string }[] | null>(null);
  const [newTypeLabel, setNewTypeLabel] = useState("");
  const [managerOpen, setManagerOpen] = useState(false);

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  const validLevelOptions = levelTypes.filter((lt) => {
    if (parentRank !== null && lt.rank <= parentRank) return false;
    if (minChildRank !== null && lt.rank >= minChildRank) return false;
    return true;
  });

  const displayTypes = orderedTypes ?? levelTypes;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await updateNode(nodeId, { name, level: level !== currentLevel ? level : undefined });
    onRenamed();
    onClose();
  }

  function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const base = orderedTypes ?? levelTypes;
    const oldIndex = base.findIndex((t) => t.id === active.id);
    const newIndex = base.findIndex((t) => t.id === over.id);
    setOrderedTypes(arrayMove(base, oldIndex, newIndex));
    setReorderDirty(true);
    setViolations(null);
  }

  async function onSaveOrder() {
    if (!orderedTypes) return;
    try {
      await reorderLevelTypes(orderedTypes.map((t) => t.id));
      setReorderDirty(false);
      setOrderedTypes(null);
      setViolations(null);
      await refresh();
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: { violations?: { parent: string; child: string }[] } } } })
        ?.response?.data?.detail;
      if (detail?.violations) {
        setViolations(detail.violations);
      } else {
        alert(t("errors.generic"));
      }
    }
  }

  async function onAddType(e: FormEvent) {
    e.preventDefault();
    if (!newTypeLabel.trim()) return;
    const key = newTypeLabel.trim().toLowerCase().replace(/\s+/g, "_");
    await createLevelType(key, newTypeLabel.trim());
    setNewTypeLabel("");
    await refresh();
  }

  async function onDeleteType(type: LevelTypeDTO) {
    if (nodesUsingLevel(type.key)) return;
    await deleteLevelType(type.id);
    await refresh();
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()} data-testid="edit-node-dialog">
        <h3 className="font-semibold mb-4 dark:text-gray-100">{t("team.edit_node")}</h3>
        <form onSubmit={onSubmit} className="space-y-3">
          <input className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={name} onChange={(e) => setName(e.target.value)} required data-testid="edit-node-name-input" />
          <select className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={level} onChange={(e) => setLevel(e.target.value)} data-testid="edit-node-level-select">
            {validLevelOptions.map((lt) => (
              <option key={lt.id} value={lt.key}>{lt.label}</option>
            ))}
          </select>
          <div className="flex justify-end gap-2">
            <button type="button" className="border rounded px-3 py-1 dark:border-gray-600 dark:text-gray-300" onClick={onClose}>{t("team.cancel")}</button>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="edit-node-submit">{t("duty_config.save")}</button>
          </div>
        </form>

        {isAdmin && (
          <div className="mt-4 border-t pt-3 dark:border-gray-600">
            <button
              type="button"
              className="text-sm text-indigo-600 dark:text-indigo-300"
              onClick={() => setManagerOpen((v) => !v)}
              data-testid="level-type-manager-toggle"
            >
              {t("team.level_type_manager")}
            </button>

            {managerOpen && (
              <div className="mt-2 space-y-2" data-testid="level-type-manager">
                <DndContext sensors={sensors} onDragEnd={onDragEnd}>
                  <SortableContext items={displayTypes.map((t) => t.id)} strategy={verticalListSortingStrategy}>
                    <ul>
                      {displayTypes.map((type) => (
                        <SortableLevelTypeRow
                          key={type.id}
                          type={type}
                          canDelete={!nodesUsingLevel(type.key)}
                          onDelete={() => void onDeleteType(type)}
                        />
                      ))}
                    </ul>
                  </SortableContext>
                </DndContext>

                {violations && (
                  <div className="text-xs text-red-500" data-testid="level-type-violations">
                    <p>{t("team.level_type_reorder_violations")}</p>
                    <ul>
                      {violations.map((v, i) => (
                        <li key={i}>{v.parent} → {v.child}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {reorderDirty && (
                  <button
                    type="button"
                    className="bg-indigo-600 text-white px-2 py-1 rounded text-xs"
                    onClick={() => void onSaveOrder()}
                    data-testid="level-type-save-order"
                  >
                    {t("team.level_type_save_order")}
                  </button>
                )}

                <form onSubmit={(e) => void onAddType(e)} className="flex gap-1">
                  <input
                    className="border rounded p-1 flex-1 text-xs dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                    value={newTypeLabel}
                    onChange={(e) => setNewTypeLabel(e.target.value)}
                    placeholder={t("team.level_type_new_label")}
                    data-testid="level-type-new-input"
                  />
                  <button type="submit" className="bg-indigo-600 text-white px-2 py-1 rounded text-xs" data-testid="level-type-add-submit">
                    {t("team.level_type_add")}
                  </button>
                </form>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Delete the old component**

Run: `rm frontend/src/components/RenameNodeDialog.tsx` (or use your editor's delete)

- [ ] **Step 5: Verify it compiles**

Run: `npx tsc --noEmit` (from `frontend/`)
Expected: errors only in `HierarchyTree.tsx` (still importing `RenameNodeDialog` — fixed in Task 16). No errors in `EditNodeDialog.tsx` itself.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/EditNodeDialog.tsx frontend/src/i18n/he.json
git rm frontend/src/components/RenameNodeDialog.tsx
git commit -m "feat: replace RenameNodeDialog with EditNodeDialog (level dropdown + level-type manager)"
```

---

### Task 15: Frontend — `AddChildNodeDialog` / `AddRootNodeDialog` use `useLevelTypes`

**Files:**
- Modify: `frontend/src/components/AddChildNodeDialog.tsx`
- Modify: `frontend/src/components/AddRootNodeDialog.tsx`

- [ ] **Step 1: Rewrite `AddChildNodeDialog.tsx`**

```tsx
import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NodeDTO, createNode } from "../api/hierarchy";
import { useLevelTypes } from "../hooks/useLevelTypes";

interface Props {
  parent: NodeDTO;
  onClose: () => void;
  onCreated: () => void;
}

export default function AddChildNodeDialog({ parent, onClose, onCreated }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const { levelTypes } = useLevelTypes();

  const parentType = levelTypes.find((lt) => lt.key === parent.level);
  const possibleLevels = parentType
    ? levelTypes.filter((lt) => lt.rank > parentType.rank).sort((a, b) => a.rank - b.rank)
    : [];
  const [level, setLevel] = useState("");

  useEffect(() => {
    if (!level && possibleLevels.length > 0) setLevel(possibleLevels[0].key);
  }, [possibleLevels, level]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await createNode({ level, name, parent_id: parent.id });
    onCreated();
    onClose();
  }

  if (levelTypes.length === 0 || possibleLevels.length === 0) return null;

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96" onClick={(e) => e.stopPropagation()} data-testid="add-child-dialog">
        <h3 className="font-semibold mb-4 dark:text-gray-100">{t("team.add_child_node")}: {parent.name}</h3>
        <form onSubmit={onSubmit} className="space-y-3">
          <select className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={level} onChange={(e) => setLevel(e.target.value)} data-testid="child-level">
            {possibleLevels.map((lt) => (
              <option key={lt.key} value={lt.key}>{lt.label}</option>
            ))}
          </select>
          <input className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("team.node_name")} required data-testid="child-name" />
          <div className="flex justify-end gap-2">
            <button type="button" className="border rounded px-3 py-1 dark:border-gray-600 dark:text-gray-300" onClick={onClose}>{t("team.cancel")}</button>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="child-submit">{t("team.add_node")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Rewrite `AddRootNodeDialog.tsx`**

```tsx
import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { createNode } from "../api/hierarchy";
import { useLevelTypes } from "../hooks/useLevelTypes";

interface Props {
  onClose: () => void;
  onCreated: () => void;
}

export default function AddRootNodeDialog({ onClose, onCreated }: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const { levelTypes } = useLevelTypes();
  const sortedTypes = [...levelTypes].sort((a, b) => a.rank - b.rank);
  const [level, setLevel] = useState("");

  useEffect(() => {
    if (!level && sortedTypes.length > 0) setLevel(sortedTypes[0].key);
  }, [sortedTypes, level]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await createNode({ level, name, parent_id: null });
    onCreated();
    onClose();
  }

  return (
    <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-96" onClick={(e) => e.stopPropagation()} data-testid="add-root-dialog">
        <h3 className="font-semibold mb-4 dark:text-gray-100">{t("team.add_root_node")}</h3>
        <form onSubmit={onSubmit} className="space-y-3">
          <select className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={level} onChange={(e) => setLevel(e.target.value)} data-testid="root-level">
            {sortedTypes.map((lt) => (
              <option key={lt.key} value={lt.key}>{lt.label}</option>
            ))}
          </select>
          <input className="border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("team.node_name")} required data-testid="root-name" />
          <div className="flex justify-end gap-2">
            <button type="button" className="border rounded px-3 py-1 dark:border-gray-600 dark:text-gray-300" onClick={onClose}>{t("team.cancel")}</button>
            <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="root-submit">{t("team.add_node")}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify compile**

Run: `npx tsc --noEmit` (from `frontend/`)
Expected: no new errors in these two files.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AddChildNodeDialog.tsx frontend/src/components/AddRootNodeDialog.tsx
git commit -m "feat: drive level dropdowns from useLevelTypes instead of hardcoded LEVEL_ORDER"
```

---

### Task 16: Frontend — `HierarchyTree.tsx` rank-based logic + `EditNodeDialog` wiring

**Files:**
- Modify: `frontend/src/components/HierarchyTree.tsx`

- [ ] **Step 1: Remove `LEVEL_ORDER`, add a default-color fallback, use the hook**

Replace the constants block (lines 31-40):

```typescript
const LEVEL_COLORS: Record<string, string> = {
  division: "text-purple-700 dark:text-purple-300 bg-purple-50 dark:bg-purple-950",
  unit: "text-indigo-700 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-950",
  department: "text-blue-700 dark:text-blue-300 bg-blue-50 dark:bg-blue-950",
  branch: "text-green-700 dark:text-green-300 bg-green-50 dark:bg-green-950",
  group: "text-yellow-700 dark:text-yellow-300 bg-yellow-50 dark:bg-yellow-950",
  team: "text-gray-700 bg-gray-100 dark:text-gray-300 dark:bg-gray-700",
};
const DEFAULT_LEVEL_COLOR = "text-slate-700 bg-slate-100 dark:text-slate-300 dark:bg-slate-700";
```

(Drop the `LEVEL_ORDER` line entirely.)

Add the import at the top, alongside the other component imports:

```typescript
import EditNodeDialog from "./EditNodeDialog";
import { useLevelTypes } from "../hooks/useLevelTypes";
```

Remove the `import RenameNodeDialog from "./RenameNodeDialog";` line.

- [ ] **Step 2: Use the level type's label for the badge instead of an i18n lookup**

`DroppableNodeRow` currently renders:

```tsx
      <span className={`text-xs px-1.5 py-0.5 rounded ${LEVEL_COLORS[node.level] ?? ""}`}>
        {t(`team.level_${node.level}`)}
      </span>
```

Add a `levelLabel: string` prop to `DroppableNodeRow`'s props interface and destructuring, and use it:

```tsx
      <span className={`text-xs px-1.5 py-0.5 rounded ${LEVEL_COLORS[node.level] ?? DEFAULT_LEVEL_COLOR}`}>
        {levelLabel}
      </span>
```

- [ ] **Step 3: Add `useLevelTypes()` to the main component, compute rank-based `canHaveChildren`, thread label + new props down**

In `export default function HierarchyTree(...)`, add right after the existing `useState` calls:

```typescript
  const { levelTypes } = useLevelTypes();
  const rankByKey = new Map(levelTypes.map((lt) => [lt.key, lt.rank]));
  const maxRank = levelTypes.length > 0 ? Math.max(...levelTypes.map((lt) => lt.rank)) : 0;
  const labelByKey = new Map(levelTypes.map((lt) => [lt.key, lt.label]));
```

Replace `canHaveChildrenFn`:

```typescript
  const canHaveChildrenFn = (level: string) => {
    const rank = rankByKey.get(level);
    return rank !== undefined && rank < maxRank;
  };
```

In `renderNode`, pass `levelLabel={labelByKey.get(node.level) ?? node.level}` into `<DroppableNodeRow ... />`.

- [ ] **Step 4: Swap the dialog at the bottom of the component**

Replace:

```tsx
      {renameDialog && (
        <RenameNodeDialog nodeId={renameDialog.id} currentName={renameDialog.name} onClose={() => setRenameDialog(null)} onRenamed={onChanged} />
      )}
```

with:

```tsx
      {renameDialog && (() => {
        const parent = nodes.find((n) => n.id === renameDialog.parent_id);
        const parentRank = parent ? rankByKey.get(parent.level) ?? null : null;
        const childRanks = nodes
          .filter((n) => n.parent_id === renameDialog.id)
          .map((n) => rankByKey.get(n.level))
          .filter((r): r is number => r !== undefined);
        const minChildRank = childRanks.length > 0 ? Math.min(...childRanks) : null;
        return (
          <EditNodeDialog
            nodeId={renameDialog.id}
            currentName={renameDialog.name}
            currentLevel={renameDialog.level}
            parentRank={parentRank}
            minChildRank={minChildRank}
            isAdmin={isAdmin}
            nodesUsingLevel={(key) => nodes.some((n) => n.level === key)}
            onClose={() => setRenameDialog(null)}
            onRenamed={onChanged}
          />
        );
      })()}
```

- [ ] **Step 5: Verify compile**

Run: `npx tsc --noEmit` (from `frontend/`)
Expected: no errors.

- [ ] **Step 6: Run lint**

Run: `npm run lint` (from `frontend/`)
Expected: 0 warnings/errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/HierarchyTree.tsx
git commit -m "feat: drive HierarchyTree level display/ordering from DB level types"
```

---

### Task 17: Manual verification in the running app

**Files:** none (verification only)

- [ ] **Step 1: Start the dev stack**

Run: `.\dev.ps1` (from repo root)
Expected: backend, frontend, and bot start cleanly; migration `0059` applies on boot.

- [ ] **Step 2: Exercise the new UI as an admin**

In the browser at `http://localhost:5173`, navigate to the team/hierarchy page as an admin user:
- Open the edit (✎) dialog on an existing node — confirm the level dropdown shows only valid levels for that node's position, and the "ניהול סוגי דרגות" section is visible and collapsible.
- Add a new custom level type via the manager's input + "הוסף" button — confirm it appears in the sortable list and shows up as a future option for `AddChildNodeDialog`'s level dropdown for a node whose rank is below it.
- Drag-reorder two level types and confirm "שמור סדר" appears; click it and confirm the new order persists after a page reload.
- Attempt a reorder that would invert an existing parent/child pair — confirm the inline violation list appears instead of a toast, and the order is not saved.
- Try deleting a level type that's currently in use by a node — confirm the ✕ button is hidden/disabled for it, but a delete on an unused custom type succeeds.
- Change an existing node's level via the dropdown and save — confirm the badge and child-add behavior update accordingly.

- [ ] **Step 3: Confirm no regressions for non-admin roles**

Log in as a `duty_manager` and a `commander` — confirm the level-type manager section is hidden for `commander` (not in `_DM_GLOBAL_ACTIONS`... actually `isAdmin` prop gates the section; confirm it matches the intended admin/DM-only visibility) and that read-only tree views (e.g. `CommandDashboardPage`) still render level badges correctly with the new label-based lookup.

- [ ] **Step 4: Stop the dev stack**

Press Ctrl+C in the terminal running `dev.ps1`.

---

## Self-review notes (already applied above)

- Spec's "Add level: str | None to UpdateNodeRequest" and the regex removal on `CreateNodeRequest` — covered in Task 9.
- Spec's enforcement table row "Change node's level: new_rank > parent_rank AND new_rank < min(children ranks)" — implemented exactly in `change_node_level` (Task 9).
- Spec's reorder violation response shape (`{"detail": "reorder_would_violate_tree", "violations": [...]}`) — implemented in Task 8's route and verified by the integration test.
- Spec note "remove the restriction on moving non-corps nodes to root" — confirmed no such restriction exists in current `move_node` code (only the rank check applies, and rank checks are skipped entirely when `new_parent_id is None`), so no separate change was needed beyond Task 4's rank check.
- Spec's note that frontend tests referencing `LEVEL_ORDER` should be updated — none exist in the current codebase, so this plan introduces no new frontend test files, matching existing convention for these dialog components.
