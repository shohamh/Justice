# Slice 2: Hierarchy & Soldiers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the org hierarchy and soldier/account management on top of Slice 1: a `hierarchy_nodes` tree, a scoped `require(action, target)` authorization layer, soldier onboarding/edit/reset-password/soft-delete, admin role assignment, the forced change-password flow, and the Hebrew "אנשי צוות והיררכיה" + profile/change-password UI — every mutation audited.

**Architecture:** A self-referential `hierarchy_nodes` table with a materialized `path_ids` ancestor array (recomputed on move) gives O(1) subtree-membership checks. A pure-function authorization engine (`app/auth/authz.py`) resolves a user's *scope roots* (their own node subtree for a duty_manager; commanded nodes for a commander; everything for admin) and answers `can(user, action, target_node)`; routes call a thin `authorize(...)` helper that raises 403. A `must_change_password` gate dependency blocks all protected endpoints except change-password/logout until the flag clears. All state changes go through `write_audit` in the same transaction.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x (MappedAsDataclass), Alembic, Pydantic v2, Postgres 16 (UUID[] + GIN), pytest + testcontainers, React 18 + Vite + TS, react-i18next, axios, Playwright. Same toolchain as Slice 1.

---

## Spec coverage

Implements design-doc Section 4.1 (`hierarchy_nodes`; `soldiers.hierarchy_node_id` FK), Section 5.1–5.3 (roles, scoped permission matrix rows for view/onboard/reset-password/edit-hierarchy/assign-role, the `require(action, target)` dependency, forced password change), and the Section 7 page surfaces #8 (אנשי צוות והיררכיה) and #11 (פרופיל / change password), plus role-gated sidebar entries. Duties, exemptions, constraints, scoring, and the algorithm remain **out** (slices 3–5).

Decisions locked during brainstorming (2026-05-28):
- **One backend-first plan, one PR.**
- **Onboarding password is optional**: if the onboarder omits it, the system generates a one-time temp password and returns it once; `must_change_password=True` either way.
- **Strict single-step hierarchy nesting**: departments are roots (no parent); every other node's parent must be exactly one level up (`department→branch→group→team`); multiple departments allowed; cycles rejected.
- **Role changes are admin-only** and separate from onboarding (onboarding always creates `role='soldier'`).

## What this slice builds on (already exists from Slice 1)

- `backend/app/db/models.py` — `Soldier` (with nullable `hierarchy_node_id` column, no FK yet), `AuditLog`, `SystemSetting`.
- `backend/app/audit/writer.py` — `write_audit(session, *, actor_id, action, entity_type, entity_id=None, before=None, after=None, context=None)`.
- `backend/app/auth/password.py` — `hash_password`, `verify_password`.
- `backend/app/auth/jwt_tokens.py` — `issue_access_token(*, user_id, role, lifetime_seconds=None)`, `decode_token`.
- `backend/app/auth/deps.py` — `get_current_user(request, session) -> Soldier`.
- `backend/app/routes/auth.py` — `/api/auth/login|refresh|logout`; `app/main.py` `create_app()` wires routers under `/api`.
- `backend/tests/conftest.py` — fixtures `db_admin_url`, `admin_session` (db_admin), `app_session` (app role), `client` (TestClient); session-autouse `_apply_schema` runs `alembic upgrade head` against a throwaway Postgres testcontainer and sets `JWT_SECRET` + a high `LOGIN_RATE_LIMIT`. **New migrations are picked up automatically.**
- Migrations `0001`–`0004`. New migrations are `0005`, `0006`.

## File structure produced by this slice

```
backend/
├── alembic/versions/
│   ├── 0005_create_hierarchy_nodes.py      # new
│   └── 0006_soldiers_hierarchy_fk.py       # new
├── app/
│   ├── db/models.py                        # +HierarchyNode, Soldier FK/relationship
│   ├── auth/
│   │   ├── authz.py                        # new: scope resolution + can() + authorize()
│   │   └── deps.py                         # +require_password_changed, +require_roles
│   ├── services/
│   │   ├── hierarchy.py                    # new: node CRUD + path_ids maintenance
│   │   └── soldiers.py                     # new: onboard/edit/reset/soft-delete/assign-role + temp pw
│   └── routes/
│       ├── auth.py                         # +/api/auth/change-password
│       ├── me.py                           # new: GET /api/me
│       ├── soldiers.py                     # new
│       └── hierarchy.py                    # new
└── tests/
    ├── helpers.py                          # new: create_soldier/create_node/auth_headers
    ├── unit/
    │   ├── test_authz.py                   # new
    │   ├── test_hierarchy_service.py       # new
    │   └── test_password_policy.py         # new
    └── integration/
        ├── test_change_password.py         # new
        ├── test_soldiers_api.py            # new
        ├── test_hierarchy_api.py           # new
        └── test_rbac_matrix.py             # new

frontend/
├── src/
│   ├── api/
│   │   ├── auth.ts                         # +changePassword, +me types
│   │   ├── soldiers.ts                     # new
│   │   └── hierarchy.ts                    # new
│   ├── auth/AuthContext.tsx                # +current user (role/name), refetch /me
│   ├── components/
│   │   ├── Layout.tsx                      # role-gated sidebar
│   │   └── ConfirmDialog.tsx               # new: reason-capturing confirm modal
│   ├── pages/
│   │   ├── ChangePasswordPage.tsx          # new
│   │   ├── ProfilePage.tsx                 # new
│   │   └── TeamHierarchyPage.tsx           # new
│   ├── App.tsx                             # routes + forced-change redirect
│   └── i18n/he.json                        # +strings
└── tests/e2e/
    ├── change_password.spec.ts             # new
    └── soldiers.spec.ts                    # new
```

**File responsibilities:**
- `app/auth/authz.py` — pure authorization. `scope_root_ids(session, user)` and `can(user, action, target_node, roots)` are pure/lookup-only and unit-tested without HTTP; `authorize(session, user, action, target_node)` raises `HTTPException(403)`.
- `app/services/hierarchy.py` — all hierarchy mutations + `path_ids` maintenance; raises `HierarchyError`. No HTTP.
- `app/services/soldiers.py` — onboarding, edits, password reset, soft delete, role assignment, temp-password generation; raises `SoldierError`. No HTTP.
- `app/routes/*.py` — thin: parse request, load targets, `authorize(...)`, call service, return Pydantic models.

---

## Conventions used in this plan

- Backend commands run from `backend/` with `uv`. **Use `git -C <repo-root>` for commits so the shell's working directory stays in `backend/`** (a bare `cd ..` in a chained command leaves you at the repo root where `uv run` finds no project).
- Frontend commands run from `frontend/` with `pnpm`.
- "Run X. Expected: Y." — actually run it and confirm before continuing.
- TDD: write the failing test, see it fail, implement, see it pass, commit. One commit per task (small).
- Repo root is `C:\Users\Shoham\workspace\justice`. Work happens on branch `slice-2-hierarchy-and-soldiers` (already created off `master`).

---

## Phase A — Schema & models

### Task 1: Migration 0005 — `hierarchy_nodes`

**Files:**
- Create: `backend/alembic/versions/0005_create_hierarchy_nodes.py`

- [ ] **Step 1: Create the migration**

```python
"""create hierarchy_nodes

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-28
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# Top-down order. create_table emits CREATE TYPE for this named enum once;
# do NOT also call LEVEL_ENUM.create() (that double-creates — see slice 1 migration 0004).
LEVEL_ENUM = sa.Enum("department", "branch", "group", "team", name="hierarchy_level")


def upgrade() -> None:
    op.create_table(
        "hierarchy_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hierarchy_nodes.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("level", LEVEL_ENUM, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("commander_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("path_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_hierarchy_nodes_parent_id", "hierarchy_nodes", ["parent_id"])
    op.create_index("ix_hierarchy_nodes_level", "hierarchy_nodes", ["level"])
    op.create_index("ix_hierarchy_nodes_commander_id", "hierarchy_nodes", ["commander_id"])
    op.create_index("ix_hierarchy_nodes_path_ids", "hierarchy_nodes", ["path_ids"], postgresql_using="gin")


def downgrade() -> None:
    op.drop_table("hierarchy_nodes")
    LEVEL_ENUM.drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 2: Apply against a fresh testcontainer via the suite bootstrap**

Run: `uv run pytest tests/integration/test_audit_append_only.py -q`
Expected: still `3 passed` — proves `alembic upgrade head` (now including 0005) applies cleanly.

- [ ] **Step 3: Commit**

```bash
git -C .. add backend/alembic/versions/0005_create_hierarchy_nodes.py
git -C .. commit -m "feat(db): hierarchy_nodes table with path_ids (gin)"
```

---

### Task 2: Migration 0006 — `soldiers.hierarchy_node_id` FK

**Files:**
- Create: `backend/alembic/versions/0006_soldiers_hierarchy_fk.py`

- [ ] **Step 1: Create the migration**

```python
"""add soldiers.hierarchy_node_id foreign key

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-28

The column already exists (migration 0004); this only adds the FK now that
hierarchy_nodes exists. ON DELETE SET NULL: deleting a node detaches soldiers
(node deletion is independently guarded in the service layer).
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_soldiers_hierarchy_node",
        "soldiers",
        "hierarchy_nodes",
        ["hierarchy_node_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_soldiers_hierarchy_node", "soldiers", type_="foreignkey")
```

- [ ] **Step 2: Apply**

Run: `uv run pytest tests/integration/test_audit_append_only.py -q`
Expected: `3 passed`.

- [ ] **Step 3: Commit**

```bash
git -C .. add backend/alembic/versions/0006_soldiers_hierarchy_fk.py
git -C .. commit -m "feat(db): FK soldiers.hierarchy_node_id -> hierarchy_nodes"
```

---

### Task 3: `HierarchyNode` ORM model

**Files:**
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Add imports and the model**

In `backend/app/db/models.py`, add `ARRAY` to the postgresql import and `ForeignKey` to the sqlalchemy import, then append the model. The full import block becomes:

```python
from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
```

Append at the end of the file:

```python
class HierarchyNode(Base):
    __tablename__ = "hierarchy_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    level: Mapped[str] = mapped_column(
        Enum("department", "branch", "group", "team", name="hierarchy_level")
    )
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

> Note: `Soldier.hierarchy_node_id` already exists as a column; no ORM-level relationship object is needed for this slice — we query by id.

- [ ] **Step 2: Verify the import graph**

Run: `uv run python -c "from app.db.models import HierarchyNode, Soldier; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git -C .. add backend/app/db/models.py
git -C .. commit -m "feat(db): HierarchyNode ORM model"
```

---

## Phase B — Test helpers

### Task 4: Shared test helpers

**Files:**
- Create: `backend/tests/helpers.py`

- [ ] **Step 1: Create `backend/tests/helpers.py`**

```python
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.auth.jwt_tokens import issue_access_token
from app.auth.password import hash_password
from app.db.models import HierarchyNode, Soldier


def create_node(
    session: Session,
    *,
    level: str,
    name: str,
    parent: HierarchyNode | None = None,
    commander_id: uuid.UUID | None = None,
) -> HierarchyNode:
    """Insert a node and set its materialized path_ids. Test-only shortcut that
    bypasses the service-layer validation (so tests can build arbitrary trees fast)."""
    node = HierarchyNode(level=level, name=name, parent_id=parent.id if parent else None, commander_id=commander_id)
    session.add(node)
    session.flush()  # populate node.id
    node.path_ids = ([*parent.path_ids, node.id] if parent else [node.id])
    session.flush()
    return node


def create_soldier(
    session: Session,
    *,
    personal_number: str,
    role: str = "soldier",
    password: str = "password-1234",
    hierarchy_node_id: uuid.UUID | None = None,
    must_change_password: bool = False,
) -> Soldier:
    s = Soldier(
        personal_number=personal_number,
        full_name=f"Test {personal_number}",
        password_hash=hash_password(password),
        role=role,
        hierarchy_node_id=hierarchy_node_id,
        must_change_password=must_change_password,
    )
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def auth_headers(soldier: Soldier) -> dict[str, str]:
    token = issue_access_token(user_id=soldier.id, role=soldier.role)
    return {"Authorization": f"Bearer {token}"}
```

- [ ] **Step 2: Sanity import**

Run: `uv run python -c "import tests.helpers; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git -C .. add backend/tests/helpers.py
git -C .. commit -m "test: shared helpers for nodes/soldiers/auth headers"
```

---

## Phase C — Hierarchy service (TDD)

### Task 5: `create_node` + level rules + path_ids

**Files:**
- Create: `backend/app/services/hierarchy.py`
- Create: `backend/tests/unit/test_hierarchy_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_hierarchy_service.py
import pytest

from app.services.hierarchy import HierarchyError, create_node
from tests.helpers import create_node as seed_node


def test_create_root_must_be_department(admin_session):
    node = create_node(admin_session, level="department", name="חיל", parent_id=None, actor_id=None)
    admin_session.commit()
    assert node.parent_id is None
    assert node.path_ids == [node.id]


def test_create_non_department_root_rejected(admin_session):
    with pytest.raises(HierarchyError):
        create_node(admin_session, level="branch", name="ענף", parent_id=None, actor_id=None)


def test_create_child_must_be_exactly_one_level_down(admin_session):
    dept = seed_node(admin_session, level="department", name="חיל")
    # branch under department: ok, path extends parent
    branch = create_node(admin_session, level="branch", name="ענף", parent_id=dept.id, actor_id=None)
    admin_session.commit()
    assert branch.path_ids == [dept.id, branch.id]
    # team under department (skipping levels): rejected
    with pytest.raises(HierarchyError):
        create_node(admin_session, level="team", name="צוות", parent_id=dept.id, actor_id=None)


def test_create_writes_audit(admin_session):
    from sqlalchemy import text
    create_node(admin_session, level="department", name="חיל", parent_id=None, actor_id=None)
    admin_session.commit()
    row = admin_session.execute(text(
        "SELECT action FROM audit_log WHERE action='hierarchy_node.create' ORDER BY created_at DESC LIMIT 1"
    )).first()
    assert row is not None
```

- [ ] **Step 2: Run — expect FAIL** (module missing).

Run: `uv run pytest tests/unit/test_hierarchy_service.py -q`
Expected: ImportError on `app.services.hierarchy`.

- [ ] **Step 3: Create `backend/app/services/hierarchy.py`**

```python
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import HierarchyNode

# Top (index 0) to bottom. A node's parent must be exactly one level above it.
LEVEL_ORDER = ["department", "branch", "group", "team"]


class HierarchyError(Exception):
    """Raised on an invalid hierarchy operation (bad level nesting, cycle, guard)."""


def _expected_child_level(parent_level: str) -> str | None:
    i = LEVEL_ORDER.index(parent_level)
    return LEVEL_ORDER[i + 1] if i + 1 < len(LEVEL_ORDER) else None


def create_node(
    session: Session,
    *,
    level: str,
    name: str,
    parent_id: uuid.UUID | None,
    commander_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> HierarchyNode:
    if level not in LEVEL_ORDER:
        raise HierarchyError(f"unknown level: {level}")
    if parent_id is None:
        if level != "department":
            raise HierarchyError("root nodes must be 'department'")
        parent = None
    else:
        parent = session.get(HierarchyNode, parent_id)
        if parent is None:
            raise HierarchyError("parent not found")
        if _expected_child_level(parent.level) != level:
            raise HierarchyError(f"a {parent.level} can only contain {_expected_child_level(parent.level)} nodes")

    node = HierarchyNode(level=level, name=name, parent_id=parent_id, commander_id=commander_id)
    session.add(node)
    session.flush()  # populate node.id
    node.path_ids = ([*parent.path_ids, node.id] if parent is not None else [node.id])
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

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/unit/test_hierarchy_service.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/app/services/hierarchy.py backend/tests/unit/test_hierarchy_service.py
git -C .. commit -m "feat(hierarchy): create_node with strict level nesting + path_ids + audit"
```

---

### Task 6: `move_node` (recompute subtree path_ids, reject cycles)

**Files:**
- Modify: `backend/app/services/hierarchy.py`
- Modify: `backend/tests/unit/test_hierarchy_service.py`

- [ ] **Step 1: Add the failing tests**

Append to `test_hierarchy_service.py`:

```python
from app.services.hierarchy import move_node


def test_move_recomputes_path_ids_for_node_and_descendants(admin_session):
    d1 = seed_node(admin_session, level="department", name="d1")
    b1 = seed_node(admin_session, level="branch", name="b1", parent=d1)
    g1 = seed_node(admin_session, level="group", name="g1", parent=b1)
    t1 = seed_node(admin_session, level="team", name="t1", parent=g1)
    d2 = seed_node(admin_session, level="department", name="d2")
    b2 = seed_node(admin_session, level="branch", name="b2", parent=d2)

    # Move g1 (with t1 under it) from b1 to b2.
    move_node(admin_session, node_id=g1.id, new_parent_id=b2.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(g1)
    admin_session.refresh(t1)
    assert g1.path_ids == [d2.id, b2.id, g1.id]
    assert t1.path_ids == [d2.id, b2.id, g1.id, t1.id]


def test_move_rejects_cycle(admin_session):
    d1 = seed_node(admin_session, level="department", name="d1")
    b1 = seed_node(admin_session, level="branch", name="b1", parent=d1)
    g1 = seed_node(admin_session, level="group", name="g1", parent=b1)
    # Cannot move b1 under its own descendant g1.
    with pytest.raises(HierarchyError):
        move_node(admin_session, node_id=b1.id, new_parent_id=g1.id, actor_id=None)


def test_move_enforces_level_rules(admin_session):
    d1 = seed_node(admin_session, level="department", name="d1")
    b1 = seed_node(admin_session, level="branch", name="b1", parent=d1)
    g1 = seed_node(admin_session, level="group", name="g1", parent=b1)
    d2 = seed_node(admin_session, level="department", name="d2")
    # group directly under department skips a level: rejected.
    with pytest.raises(HierarchyError):
        move_node(admin_session, node_id=g1.id, new_parent_id=d2.id, actor_id=None)
```

- [ ] **Step 2: Run — expect FAIL** (`move_node` missing).

- [ ] **Step 3: Implement `move_node`** — append to `app/services/hierarchy.py`:

```python
from sqlalchemy import select


def move_node(
    session: Session,
    *,
    node_id: uuid.UUID,
    new_parent_id: uuid.UUID | None,
    actor_id: uuid.UUID | None = None,
) -> HierarchyNode:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HierarchyError("node not found")

    if new_parent_id is None:
        if node.level != "department":
            raise HierarchyError("only departments can be roots")
        new_base: list[uuid.UUID] = []
    else:
        if new_parent_id == node_id:
            raise HierarchyError("a node cannot be its own parent")
        parent = session.get(HierarchyNode, new_parent_id)
        if parent is None:
            raise HierarchyError("parent not found")
        if node.id in parent.path_ids:
            raise HierarchyError("cannot move a node under its own descendant")
        if _expected_child_level(parent.level) != node.level:
            raise HierarchyError(f"a {parent.level} can only contain {_expected_child_level(parent.level)} nodes")
        new_base = list(parent.path_ids)

    old_path = list(node.path_ids)
    old_prefix_len = len(old_path)  # old_path ends with node.id
    new_node_path = [*new_base, node.id]

    # Descendants are nodes whose path contains node.id (includes the node itself).
    descendants = session.execute(
        select(HierarchyNode).where(HierarchyNode.path_ids.any(node_id))
    ).scalars().all()

    before = {"parent_id": str(node.parent_id) if node.parent_id else None}
    node.parent_id = new_parent_id
    for d in descendants:
        # Replace the old prefix (…node.id) with the new node path, keep the suffix below it.
        d.path_ids = new_node_path + list(d.path_ids[old_prefix_len:])
    session.flush()

    write_audit(
        session,
        actor_id=actor_id,
        action="hierarchy_node.move",
        entity_type="hierarchy_node",
        entity_id=node.id,
        before=before,
        after={"parent_id": str(new_parent_id) if new_parent_id else None},
    )
    return node
```

> `HierarchyNode.path_ids.any(node_id)` emits the Postgres `node_id = ANY(path_ids)` containment check.

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/unit/test_hierarchy_service.py -q`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/app/services/hierarchy.py backend/tests/unit/test_hierarchy_service.py
git -C .. commit -m "feat(hierarchy): move_node recomputes subtree path_ids, rejects cycles"
```

---

### Task 7: `rename_node`, `set_commander`, `delete_node` (guards)

**Files:**
- Modify: `backend/app/services/hierarchy.py`
- Modify: `backend/tests/unit/test_hierarchy_service.py`

- [ ] **Step 1: Add the failing tests**

Append to `test_hierarchy_service.py`:

```python
from app.services.hierarchy import delete_node, rename_node, set_commander
from tests.helpers import create_soldier


def test_rename_node(admin_session):
    d = seed_node(admin_session, level="department", name="old")
    rename_node(admin_session, node_id=d.id, name="new", actor_id=None)
    admin_session.commit()
    admin_session.refresh(d)
    assert d.name == "new"


def test_set_commander(admin_session):
    d = seed_node(admin_session, level="department", name="d")
    cmd = create_soldier(admin_session, personal_number="8000001", role="commander")
    set_commander(admin_session, node_id=d.id, commander_id=cmd.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(d)
    assert d.commander_id == cmd.id


def test_delete_node_rejected_with_children(admin_session):
    d = seed_node(admin_session, level="department", name="d")
    seed_node(admin_session, level="branch", name="b", parent=d)
    with pytest.raises(HierarchyError):
        delete_node(admin_session, node_id=d.id, actor_id=None)


def test_delete_node_rejected_with_soldiers(admin_session):
    d = seed_node(admin_session, level="department", name="d")
    create_soldier(admin_session, personal_number="8000002", hierarchy_node_id=d.id)
    with pytest.raises(HierarchyError):
        delete_node(admin_session, node_id=d.id, actor_id=None)


def test_delete_empty_node(admin_session):
    d = seed_node(admin_session, level="department", name="d")
    delete_node(admin_session, node_id=d.id, actor_id=None)
    admin_session.commit()
    from app.db.models import HierarchyNode as HN
    assert admin_session.get(HN, d.id) is None
```

- [ ] **Step 2: Run — expect FAIL** (functions missing).

- [ ] **Step 3: Implement — append to `app/services/hierarchy.py`:**

```python
from app.db.models import Soldier


def rename_node(session: Session, *, node_id: uuid.UUID, name: str, actor_id: uuid.UUID | None = None) -> HierarchyNode:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HierarchyError("node not found")
    before = {"name": node.name}
    node.name = name
    write_audit(session, actor_id=actor_id, action="hierarchy_node.rename", entity_type="hierarchy_node",
                entity_id=node.id, before=before, after={"name": name})
    return node


def set_commander(session: Session, *, node_id: uuid.UUID, commander_id: uuid.UUID | None, actor_id: uuid.UUID | None = None) -> HierarchyNode:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HierarchyError("node not found")
    if commander_id is not None and session.get(Soldier, commander_id) is None:
        raise HierarchyError("commander not found")
    before = {"commander_id": str(node.commander_id) if node.commander_id else None}
    node.commander_id = commander_id
    write_audit(session, actor_id=actor_id, action="hierarchy_node.set_commander", entity_type="hierarchy_node",
                entity_id=node.id, before=before, after={"commander_id": str(commander_id) if commander_id else None})
    return node


def delete_node(session: Session, *, node_id: uuid.UUID, actor_id: uuid.UUID | None = None) -> None:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HierarchyError("node not found")
    child = session.execute(
        select(HierarchyNode.id).where(HierarchyNode.parent_id == node_id).limit(1)
    ).first()
    if child is not None:
        raise HierarchyError("cannot delete a node that has children")
    soldier = session.execute(
        select(Soldier.id).where(Soldier.hierarchy_node_id == node_id).limit(1)
    ).first()
    if soldier is not None:
        raise HierarchyError("cannot delete a node that has soldiers assigned")
    write_audit(session, actor_id=actor_id, action="hierarchy_node.delete", entity_type="hierarchy_node",
                entity_id=node.id, before={"name": node.name, "level": node.level})
    session.delete(node)
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/unit/test_hierarchy_service.py -q`
Expected: `12 passed`.

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/app/services/hierarchy.py backend/tests/unit/test_hierarchy_service.py
git -C .. commit -m "feat(hierarchy): rename/set_commander/delete with guards + audit"
```

---

## Phase D — Authorization engine (TDD)

### Task 8: scope resolution + `can()`

**Files:**
- Create: `backend/app/auth/authz.py`
- Create: `backend/tests/unit/test_authz.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_authz.py
from app.auth import authz
from tests.helpers import create_node, create_soldier


def _roots(session, user):
    return authz.scope_root_ids(session, user)


def test_admin_can_everything_globally(admin_session):
    admin = create_soldier(admin_session, personal_number="7000001", role="admin")
    d = create_node(admin_session, level="department", name="d")
    assert authz.can(admin, authz.Action.SOLDIER_CREATE, target_node=d, roots=_roots(admin_session, admin))
    assert authz.can(admin, authz.Action.HIERARCHY_MANAGE, target_node=d, roots=_roots(admin_session, admin))
    assert authz.can(admin, authz.Action.SOLDIER_ASSIGN_ROLE, target_node=d, roots=_roots(admin_session, admin))


def test_duty_manager_scoped_to_own_subtree(admin_session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    dm = create_soldier(admin_session, personal_number="7000002", role="duty_manager", hierarchy_node_id=b.id)
    roots = _roots(admin_session, dm)
    assert authz.can(dm, authz.Action.SOLDIER_CREATE, target_node=b, roots=roots)
    # node outside the DM's subtree
    assert not authz.can(dm, authz.Action.SOLDIER_CREATE, target_node=other, roots=roots)
    # DMs cannot assign roles even in scope
    assert not authz.can(dm, authz.Action.SOLDIER_ASSIGN_ROLE, target_node=b, roots=roots)


def test_commander_read_only_in_commanded_subtree(admin_session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    cmd = create_soldier(admin_session, personal_number="7000003", role="commander")
    # make cmd the commander of b
    b.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    assert authz.can(cmd, authz.Action.SOLDIER_READ, target_node=b, roots=roots)
    assert authz.can(cmd, authz.Action.HIERARCHY_READ, target_node=b, roots=roots)
    assert not authz.can(cmd, authz.Action.SOLDIER_CREATE, target_node=b, roots=roots)


def test_plain_soldier_has_no_management(admin_session):
    d = create_node(admin_session, level="department", name="d")
    s = create_soldier(admin_session, personal_number="7000004", role="soldier", hierarchy_node_id=d.id)
    roots = _roots(admin_session, s)
    assert roots == set()
    assert not authz.can(s, authz.Action.SOLDIER_READ, target_node=d, roots=roots)
```

- [ ] **Step 2: Run — expect FAIL** (module missing).

- [ ] **Step 3: Create `backend/app/auth/authz.py`**

```python
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import HierarchyNode, Soldier


class Action:
    SOLDIER_CREATE = "soldier.create"
    SOLDIER_READ = "soldier.read"
    SOLDIER_UPDATE = "soldier.update"
    SOLDIER_RESET_PASSWORD = "soldier.reset_password"
    SOLDIER_DELETE = "soldier.delete"
    SOLDIER_ASSIGN_ROLE = "soldier.assign_role"
    HIERARCHY_READ = "hierarchy.read"
    HIERARCHY_MANAGE = "hierarchy.manage"


_DM_ACTIONS = {
    Action.SOLDIER_CREATE, Action.SOLDIER_READ, Action.SOLDIER_UPDATE,
    Action.SOLDIER_RESET_PASSWORD, Action.SOLDIER_DELETE,
    Action.HIERARCHY_READ, Action.HIERARCHY_MANAGE,
}
_COMMANDER_ACTIONS = {Action.SOLDIER_READ, Action.HIERARCHY_READ}


def scope_root_ids(session: Session, user: Soldier) -> set[uuid.UUID]:
    """The node ids whose subtrees this user governs.

    - duty_manager: their own assigned node.
    - commander: every node where they are the commander.
    - admin / soldier: none (admin is global; soldier has no scope).
    """
    roots: set[uuid.UUID] = set()
    if user.role == "duty_manager" and user.hierarchy_node_id is not None:
        roots.add(user.hierarchy_node_id)
    commanded = session.execute(
        select(HierarchyNode.id).where(HierarchyNode.commander_id == user.id)
    ).scalars().all()
    roots.update(commanded)
    return roots


def _node_in_scope(target_node: HierarchyNode | None, roots: set[uuid.UUID]) -> bool:
    if target_node is None:
        return False
    return any(r in target_node.path_ids for r in roots)


def can(
    user: Soldier,
    action: str,
    *,
    target_node: HierarchyNode | None,
    roots: set[uuid.UUID],
) -> bool:
    if user.role == "admin":
        return True  # admin: account/role/hierarchy authority, global
    if user.role == "duty_manager":
        return action in _DM_ACTIONS and _node_in_scope(target_node, roots)
    if user.role == "commander":
        return action in _COMMANDER_ACTIONS and _node_in_scope(target_node, roots)
    return False  # plain soldier: management actions denied (self-reads handled at the route)
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/unit/test_authz.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/app/auth/authz.py backend/tests/unit/test_authz.py
git -C .. commit -m "feat(authz): scope resolution + can() permission engine"
```

---

### Task 9: `authorize()` helper + deps (`require_roles`, `require_password_changed`)

**Files:**
- Modify: `backend/app/auth/authz.py`
- Modify: `backend/app/auth/deps.py`

- [ ] **Step 1: Add `authorize()` to `authz.py`**

```python
from fastapi import HTTPException, status


def authorize(session: Session, user: Soldier, action: str, *, target_node: HierarchyNode | None) -> None:
    """Raise 403 unless `user` may perform `action` against `target_node`'s subtree."""
    roots = scope_root_ids(session, user)
    if not can(user, action, target_node=target_node, roots=roots):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
```

- [ ] **Step 2: Add deps to `app/auth/deps.py`**

Append:

```python
from collections.abc import Callable


def require_roles(*roles: str) -> Callable[..., Soldier]:
    """Dependency factory: allow only the given roles (coarse gate, e.g. admin-only)."""

    def _dep(user: Soldier = Depends(get_current_user)) -> Soldier:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        return user

    return _dep


def require_password_changed(user: Soldier = Depends(get_current_user)) -> Soldier:
    """Block protected endpoints while the user still must change their password."""
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="must_change_password")
    return user
```

- [ ] **Step 3: Verify imports compile**

Run: `uv run python -c "from app.auth.authz import authorize; from app.auth.deps import require_roles, require_password_changed; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git -C .. add backend/app/auth/authz.py backend/app/auth/deps.py
git -C .. commit -m "feat(authz): authorize() + require_roles/require_password_changed deps"
```

---

## Phase E — Soldier service & password policy (TDD)

### Task 10: password policy + temp-password generator

**Files:**
- Create: `backend/app/services/soldiers.py`
- Create: `backend/tests/unit/test_password_policy.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_password_policy.py
import pytest

from app.services.soldiers import PasswordPolicyError, generate_temp_password, validate_password


def test_validate_rejects_short_password():
    with pytest.raises(PasswordPolicyError):
        validate_password("short")  # < 10 chars


def test_validate_accepts_long_password():
    validate_password("this-is-long-enough")  # no raise


def test_generated_temp_password_meets_policy():
    pw = generate_temp_password()
    assert len(pw) >= 10
    validate_password(pw)  # must not raise


def test_generated_temp_passwords_differ():
    assert generate_temp_password() != generate_temp_password()
```

- [ ] **Step 2: Run — expect FAIL** (module missing).

- [ ] **Step 3: Create `backend/app/services/soldiers.py`** (policy + generator first)

```python
from __future__ import annotations

import secrets
import string

MIN_PASSWORD_LENGTH = 10


class SoldierError(Exception):
    """Raised on an invalid soldier operation."""


class PasswordPolicyError(SoldierError):
    """Raised when a password fails policy (length-over-complexity, >= 10 chars)."""


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")


def generate_temp_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/unit/test_password_policy.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/app/services/soldiers.py backend/tests/unit/test_password_policy.py
git -C .. commit -m "feat(soldiers): password policy + temp password generator"
```

---

### Task 11: soldier service operations

**Files:**
- Modify: `backend/app/services/soldiers.py`

These are exercised through the API integration tests (Task 14); this task adds the service functions and a direct import check.

- [ ] **Step 1: Append the operations to `app/services/soldiers.py`**

```python
import uuid
from datetime import date
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.auth.password import hash_password
from app.db.models import HierarchyNode, Soldier

ROLES = {"soldier", "commander", "duty_manager", "admin"}


class OnboardResult(NamedTuple):
    soldier: Soldier
    temp_password: str | None  # set only when the system generated the password


def onboard_soldier(
    session: Session,
    *,
    personal_number: str,
    full_name: str,
    hierarchy_node_id: uuid.UUID | None,
    phone: str | None = None,
    password: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> OnboardResult:
    if session.execute(select(Soldier.id).where(Soldier.personal_number == personal_number)).first():
        raise SoldierError("personal_number already exists")
    if hierarchy_node_id is not None and session.get(HierarchyNode, hierarchy_node_id) is None:
        raise SoldierError("hierarchy node not found")

    temp_password: str | None = None
    if password is None:
        password = generate_temp_password()
        temp_password = password
    validate_password(password)

    soldier = Soldier(
        personal_number=personal_number,
        full_name=full_name,
        password_hash=hash_password(password),
        role="soldier",  # role changes are admin-only via assign_role
        hierarchy_node_id=hierarchy_node_id,
        phone=phone,
        must_change_password=True,
    )
    session.add(soldier)
    session.flush()
    write_audit(session, actor_id=actor_id, action="soldier.create", entity_type="soldier",
                entity_id=soldier.id, after={"personal_number": personal_number, "full_name": full_name,
                                             "hierarchy_node_id": str(hierarchy_node_id) if hierarchy_node_id else None})
    return OnboardResult(soldier=soldier, temp_password=temp_password)


def update_soldier(session: Session, *, soldier: Soldier, full_name: str | None, phone: str | None,
                   actor_id: uuid.UUID | None = None) -> Soldier:
    before = {"full_name": soldier.full_name, "phone": soldier.phone}
    if full_name is not None:
        soldier.full_name = full_name
    if phone is not None:
        soldier.phone = phone
    write_audit(session, actor_id=actor_id, action="soldier.update", entity_type="soldier",
                entity_id=soldier.id, before=before, after={"full_name": soldier.full_name, "phone": soldier.phone})
    return soldier


def reset_password(session: Session, *, soldier: Soldier, actor_id: uuid.UUID | None = None) -> str:
    temp = generate_temp_password()
    soldier.password_hash = hash_password(temp)
    soldier.must_change_password = True
    write_audit(session, actor_id=actor_id, action="soldier.reset_password", entity_type="soldier",
                entity_id=soldier.id)
    return temp


def soft_delete(session: Session, *, soldier: Soldier, actor_id: uuid.UUID | None = None) -> Soldier:
    soldier.left_at = date.today()
    write_audit(session, actor_id=actor_id, action="soldier.soft_delete", entity_type="soldier",
                entity_id=soldier.id, after={"left_at": soldier.left_at.isoformat()})
    return soldier


def assign_role(session: Session, *, soldier: Soldier, role: str, actor_id: uuid.UUID | None = None) -> Soldier:
    if role not in ROLES:
        raise SoldierError(f"unknown role: {role}")
    before = {"role": soldier.role}
    soldier.role = role
    write_audit(session, actor_id=actor_id, action="soldier.assign_role", entity_type="soldier",
                entity_id=soldier.id, before=before, after={"role": role})
    return soldier
```

- [ ] **Step 2: Import check**

Run: `uv run python -c "from app.services.soldiers import onboard_soldier, update_soldier, reset_password, soft_delete, assign_role; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git -C .. add backend/app/services/soldiers.py
git -C .. commit -m "feat(soldiers): onboard/update/reset/soft-delete/assign-role services"
```

---

## Phase F — API routes (TDD)

### Task 12: `GET /api/me` + change-password endpoint

**Files:**
- Create: `backend/app/routes/me.py`
- Modify: `backend/app/routes/auth.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_change_password.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_change_password.py
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_soldier


def test_me_returns_current_user(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="6000001", role="admin")
    r = client.get("/api/me", headers=auth_headers(s))
    assert r.status_code == 200
    body = r.json()
    assert body["personal_number"] == "6000001"
    assert body["role"] == "admin"
    assert body["must_change_password"] is False


def test_change_password_clears_flag(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="6000002", password="old-password-123",
                       must_change_password=True)
    r = client.post("/api/auth/change-password", headers=auth_headers(s),
                    json={"current_password": "old-password-123", "new_password": "brand-new-password"})
    assert r.status_code == 200
    admin_session.expire_all()
    refreshed = admin_session.get(type(s), s.id)
    assert refreshed.must_change_password is False


def test_change_password_rejects_wrong_current(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="6000003", password="old-password-123")
    r = client.post("/api/auth/change-password", headers=auth_headers(s),
                    json={"current_password": "wrong", "new_password": "brand-new-password"})
    assert r.status_code == 400


def test_change_password_enforces_min_length(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="6000004", password="old-password-123")
    r = client.post("/api/auth/change-password", headers=auth_headers(s),
                    json={"current_password": "old-password-123", "new_password": "short"})
    assert r.status_code == 422 or r.status_code == 400
```

- [ ] **Step 2: Run — expect FAIL** (404 / missing route).

- [ ] **Step 3: Create `backend/app/routes/me.py`**

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.db.models import Soldier

router = APIRouter(prefix="/me", tags=["me"])


class MeResponse(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    role: str
    must_change_password: bool
    hierarchy_node_id: uuid.UUID | None


@router.get("", response_model=MeResponse)
def me(user: Soldier = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        id=user.id,
        personal_number=user.personal_number,
        full_name=user.full_name,
        role=user.role,
        must_change_password=user.must_change_password,
        hierarchy_node_id=user.hierarchy_node_id,
    )
```

- [ ] **Step 4: Add change-password to `backend/app/routes/auth.py`**

Add imports near the top (alongside existing ones). `BaseModel`, `Field`, `verify_password`, `write_audit`, `get_current_user`, `get_session`, `Soldier`, `HTTPException`, and `status` are already imported in `auth.py` from slice 1 — only add what's missing:

```python
from app.auth.password import hash_password  # add (verify_password already imported)
from app.services.soldiers import PasswordPolicyError, validate_password  # add
```

Add the request model after `LoginResponse`:

```python
class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)
```

Append the endpoint (note: depends on `get_current_user`, NOT on `require_password_changed`, so a must-change user can reach it):

```python
@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(get_current_user),
) -> dict[str, str]:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="wrong_current_password")
    try:
        validate_password(body.new_password)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="password_too_short") from exc
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    write_audit(session, actor_id=user.id, action="auth.password.change", entity_type="soldier", entity_id=user.id)
    session.commit()
    return {"status": "ok"}
```

- [ ] **Step 5: Wire `me` router in `backend/app/main.py`**

Add `from app.routes import me as me_routes` with the other route imports, and `app.include_router(me_routes.router, prefix="/api")` after the auth router include.

- [ ] **Step 6: Run — expect PASS**

Run: `uv run pytest tests/integration/test_change_password.py -q`
Expected: `4 passed`.

- [ ] **Step 7: Commit**

```bash
git -C .. add backend/app/routes/me.py backend/app/routes/auth.py backend/app/main.py backend/tests/integration/test_change_password.py
git -C .. commit -m "feat(api): GET /api/me + POST /api/auth/change-password"
```

---

### Task 13: hierarchy routes

**Files:**
- Create: `backend/app/routes/hierarchy.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_hierarchy_api.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_hierarchy_api.py
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_admin_creates_department_then_branch(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000001", role="admin")
    r = client.post("/api/hierarchy/nodes", headers=auth_headers(admin),
                    json={"level": "department", "name": "חיל", "parent_id": None})
    assert r.status_code == 201
    dept_id = r.json()["id"]
    r2 = client.post("/api/hierarchy/nodes", headers=auth_headers(admin),
                     json={"level": "branch", "name": "ענף", "parent_id": dept_id})
    assert r2.status_code == 201
    assert r2.json()["path_ids"] == [dept_id, r2.json()["id"]]


def test_create_skipping_level_rejected(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5000002", role="admin")
    dept = create_node(admin_session, level="department", name="d")
    admin_session.commit()
    r = client.post("/api/hierarchy/nodes", headers=auth_headers(admin),
                    json={"level": "team", "name": "צוות", "parent_id": str(dept.id)})
    assert r.status_code == 400


def test_plain_soldier_cannot_create_node(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5000003", role="soldier")
    r = client.post("/api/hierarchy/nodes", headers=auth_headers(s),
                    json={"level": "department", "name": "x", "parent_id": None})
    assert r.status_code == 403


def test_get_tree_scoped_for_duty_manager(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    dm = create_soldier(admin_session, personal_number="5000004", role="duty_manager", hierarchy_node_id=b.id)
    admin_session.commit()
    r = client.get("/api/hierarchy/tree", headers=auth_headers(dm))
    assert r.status_code == 200
    ids = {n["id"] for n in r.json()}
    assert str(b.id) in ids
    assert str(other.id) not in ids
```

- [ ] **Step 2: Run — expect FAIL** (404).

- [ ] **Step 3: Create `backend/app/routes/hierarchy.py`**

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, Soldier
from app.db.session import get_session
from app.services import hierarchy as svc

router = APIRouter(prefix="/hierarchy", tags=["hierarchy"])


class NodeOut(BaseModel):
    id: uuid.UUID
    level: str
    name: str
    parent_id: uuid.UUID | None
    commander_id: uuid.UUID | None
    path_ids: list[uuid.UUID]


class CreateNodeRequest(BaseModel):
    level: str = Field(pattern="^(department|branch|group|team)$")
    name: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None


class UpdateNodeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    commander_id: uuid.UUID | None = None


class MoveNodeRequest(BaseModel):
    new_parent_id: uuid.UUID | None = None


def _out(n: HierarchyNode) -> NodeOut:
    return NodeOut(id=n.id, level=n.level, name=n.name, parent_id=n.parent_id,
                   commander_id=n.commander_id, path_ids=list(n.path_ids))


@router.post("/nodes", response_model=NodeOut, status_code=status.HTTP_201_CREATED)
def create_node(body: CreateNodeRequest, session: Session = Depends(get_session),
                user: Soldier = Depends(require_password_changed)) -> NodeOut:
    # Target scope = the parent (or None for a root, which only admin may create).
    parent = session.get(HierarchyNode, body.parent_id) if body.parent_id else None
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=parent)
    try:
        node = svc.create_node(session, level=body.level, name=body.name,
                               parent_id=body.parent_id, actor_id=user.id)
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(node)
    return _out(node)


@router.patch("/nodes/{node_id}", response_model=NodeOut)
def update_node(node_id: uuid.UUID, body: UpdateNodeRequest, session: Session = Depends(get_session),
                user: Soldier = Depends(require_password_changed)) -> NodeOut:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=node)
    try:
        if body.name is not None:
            svc.rename_node(session, node_id=node_id, name=body.name, actor_id=user.id)
        if "commander_id" in body.model_fields_set:
            svc.set_commander(session, node_id=node_id, commander_id=body.commander_id, actor_id=user.id)
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(node)
    return _out(node)


@router.post("/nodes/{node_id}/move", response_model=NodeOut)
def move_node(node_id: uuid.UUID, body: MoveNodeRequest, session: Session = Depends(get_session),
              user: Soldier = Depends(require_password_changed)) -> NodeOut:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=node)
    new_parent = session.get(HierarchyNode, body.new_parent_id) if body.new_parent_id else None
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=new_parent)
    try:
        svc.move_node(session, node_id=node_id, new_parent_id=body.new_parent_id, actor_id=user.id)
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(node)
    return _out(node)


@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_node(node_id: uuid.UUID, session: Session = Depends(get_session),
                user: Soldier = Depends(require_password_changed)) -> None:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=node)
    try:
        svc.delete_node(session, node_id=node_id, actor_id=user.id)
    except svc.HierarchyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()


@router.get("/tree", response_model=list[NodeOut])
def get_tree(session: Session = Depends(get_session),
             user: Soldier = Depends(require_password_changed)) -> list[NodeOut]:
    if user.role == "admin":
        nodes = session.execute(select(HierarchyNode)).scalars().all()
    else:
        roots = scope_root_ids(session, user)
        if not roots:
            return []
        # Any node whose path contains one of the user's scope roots.
        nodes = [
            n for n in session.execute(select(HierarchyNode)).scalars().all()
            if any(r in n.path_ids for r in roots)
        ]
    return [_out(n) for n in nodes]
```

- [ ] **Step 4: Wire the router in `backend/app/main.py`**

Add `from app.routes import hierarchy as hierarchy_routes` and `app.include_router(hierarchy_routes.router, prefix="/api")`.

- [ ] **Step 5: Run — expect PASS**

Run: `uv run pytest tests/integration/test_hierarchy_api.py -q`
Expected: `4 passed`.

- [ ] **Step 6: Commit**

```bash
git -C .. add backend/app/routes/hierarchy.py backend/app/main.py backend/tests/integration/test_hierarchy_api.py
git -C .. commit -m "feat(api): hierarchy node CRUD + move + scoped tree"
```

---

### Task 14: soldier routes

**Files:**
- Create: `backend/app/routes/soldiers.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_soldiers_api.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_soldiers_api.py
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_admin_onboards_without_password_gets_temp(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="4000001", role="admin")
    d = create_node(admin_session, level="department", name="d")
    admin_session.commit()
    r = client.post("/api/soldiers", headers=auth_headers(admin),
                    json={"personal_number": "4100001", "full_name": "טוראי", "hierarchy_node_id": str(d.id)})
    assert r.status_code == 201
    body = r.json()
    assert body["role"] == "soldier"
    assert body["must_change_password"] is True
    assert len(body["temp_password"]) >= 10  # generated and returned once


def test_onboard_with_password_no_temp_returned(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="4000002", role="admin")
    r = client.post("/api/soldiers", headers=auth_headers(admin),
                    json={"personal_number": "4100002", "full_name": "טוראי", "hierarchy_node_id": None,
                          "password": "chosen-password-123"})
    assert r.status_code == 201
    assert r.json()["temp_password"] is None


def test_duty_manager_can_only_onboard_in_scope(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    dm = create_soldier(admin_session, personal_number="4000003", role="duty_manager", hierarchy_node_id=b.id)
    admin_session.commit()
    ok = client.post("/api/soldiers", headers=auth_headers(dm),
                     json={"personal_number": "4100003", "full_name": "x", "hierarchy_node_id": str(b.id)})
    assert ok.status_code == 201
    denied = client.post("/api/soldiers", headers=auth_headers(dm),
                         json={"personal_number": "4100004", "full_name": "x", "hierarchy_node_id": str(other.id)})
    assert denied.status_code == 403


def test_reset_password_returns_temp_and_sets_flag(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="4000005", role="admin")
    target = create_soldier(admin_session, personal_number="4100005")
    r = client.post(f"/api/soldiers/{target.id}/reset-password", headers=auth_headers(admin))
    assert r.status_code == 200
    assert len(r.json()["temp_password"]) >= 10


def test_only_admin_assigns_role(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="4000006", role="admin")
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    dm = create_soldier(admin_session, personal_number="4000007", role="duty_manager", hierarchy_node_id=b.id)
    target = create_soldier(admin_session, personal_number="4100006", hierarchy_node_id=b.id)
    admin_session.commit()
    denied = client.post(f"/api/soldiers/{target.id}/role", headers=auth_headers(dm), json={"role": "commander"})
    assert denied.status_code == 403
    ok = client.post(f"/api/soldiers/{target.id}/role", headers=auth_headers(admin), json={"role": "commander"})
    assert ok.status_code == 200
    assert ok.json()["role"] == "commander"


def test_soft_delete_sets_left_at(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="4000008", role="admin")
    target = create_soldier(admin_session, personal_number="4100007")
    r = client.delete(f"/api/soldiers/{target.id}", headers=auth_headers(admin))
    assert r.status_code == 204
    admin_session.expire_all()
    assert admin_session.get(type(target), target.id).left_at is not None
```

- [ ] **Step 2: Run — expect FAIL** (404).

- [ ] **Step 3: Create `backend/app/routes/soldiers.py`**

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed, require_roles
from app.db.models import HierarchyNode, Soldier
from app.db.session import get_session
from app.services import soldiers as svc

router = APIRouter(prefix="/soldiers", tags=["soldiers"])


class SoldierOut(BaseModel):
    id: uuid.UUID
    personal_number: str
    full_name: str
    role: str
    hierarchy_node_id: uuid.UUID | None
    phone: str | None
    must_change_password: bool
    left_at: str | None


class OnboardRequest(BaseModel):
    personal_number: str = Field(min_length=1, max_length=20)
    full_name: str = Field(min_length=1, max_length=200)
    hierarchy_node_id: uuid.UUID | None = None
    phone: str | None = Field(default=None, max_length=40)
    password: str | None = Field(default=None, max_length=200)


class OnboardResponse(SoldierOut):
    temp_password: str | None


class UpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=40)


class RoleRequest(BaseModel):
    role: str = Field(pattern="^(soldier|commander|duty_manager|admin)$")


def _out(s: Soldier) -> SoldierOut:
    return SoldierOut(id=s.id, personal_number=s.personal_number, full_name=s.full_name, role=s.role,
                      hierarchy_node_id=s.hierarchy_node_id, phone=s.phone,
                      must_change_password=s.must_change_password,
                      left_at=s.left_at.isoformat() if s.left_at else None)


def _load(session: Session, soldier_id: uuid.UUID) -> Soldier:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return s


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


@router.post("", response_model=OnboardResponse, status_code=status.HTTP_201_CREATED)
def onboard(body: OnboardRequest, session: Session = Depends(get_session),
            user: Soldier = Depends(require_password_changed)) -> OnboardResponse:
    target_node = session.get(HierarchyNode, body.hierarchy_node_id) if body.hierarchy_node_id else None
    authorize(session, user, Action.SOLDIER_CREATE, target_node=target_node)
    try:
        result = svc.onboard_soldier(session, personal_number=body.personal_number, full_name=body.full_name,
                                     hierarchy_node_id=body.hierarchy_node_id, phone=body.phone,
                                     password=body.password, actor_id=user.id)
    except svc.PasswordPolicyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="password_too_short") from exc
    except svc.SoldierError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(result.soldier)
    return OnboardResponse(**_out(result.soldier).model_dump(), temp_password=result.temp_password)


@router.get("", response_model=list[SoldierOut])
def list_soldiers(session: Session = Depends(get_session),
                  user: Soldier = Depends(require_password_changed)) -> list[SoldierOut]:
    if user.role == "admin":
        rows = session.execute(select(Soldier)).scalars().all()
        return [_out(s) for s in rows]
    roots = scope_root_ids(session, user)
    if not roots:
        return [_out(user)]  # a plain soldier sees only themselves
    rows = session.execute(select(Soldier)).scalars().all()
    out: list[SoldierOut] = []
    for s in rows:
        node = _node_of(session, s)
        if node is not None and any(r in node.path_ids for r in roots):
            out.append(_out(s))
    return out


@router.get("/{soldier_id}", response_model=SoldierOut)
def get_soldier(soldier_id: uuid.UUID, session: Session = Depends(get_session),
                user: Soldier = Depends(require_password_changed)) -> SoldierOut:
    s = _load(session, soldier_id)
    if s.id != user.id:  # always allowed to read self
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    return _out(s)


@router.patch("/{soldier_id}", response_model=SoldierOut)
def update(soldier_id: uuid.UUID, body: UpdateRequest, session: Session = Depends(get_session),
           user: Soldier = Depends(require_password_changed)) -> SoldierOut:
    s = _load(session, soldier_id)
    authorize(session, user, Action.SOLDIER_UPDATE, target_node=_node_of(session, s))
    svc.update_soldier(session, soldier=s, full_name=body.full_name, phone=body.phone, actor_id=user.id)
    session.commit()
    session.refresh(s)
    return _out(s)


@router.post("/{soldier_id}/reset-password")
def reset_password(soldier_id: uuid.UUID, session: Session = Depends(get_session),
                   user: Soldier = Depends(require_password_changed)) -> dict[str, str]:
    s = _load(session, soldier_id)
    authorize(session, user, Action.SOLDIER_RESET_PASSWORD, target_node=_node_of(session, s))
    temp = svc.reset_password(session, soldier=s, actor_id=user.id)
    session.commit()
    return {"temp_password": temp}


@router.delete("/{soldier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(soldier_id: uuid.UUID, session: Session = Depends(get_session),
           user: Soldier = Depends(require_password_changed)) -> None:
    s = _load(session, soldier_id)
    authorize(session, user, Action.SOLDIER_DELETE, target_node=_node_of(session, s))
    svc.soft_delete(session, soldier=s, actor_id=user.id)
    session.commit()


@router.post("/{soldier_id}/role", response_model=SoldierOut)
def set_role(soldier_id: uuid.UUID, body: RoleRequest, session: Session = Depends(get_session),
             user: Soldier = Depends(require_roles("admin"))) -> SoldierOut:
    # require_roles already enforced admin; also block while the admin must change their own password.
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="must_change_password")
    s = _load(session, soldier_id)
    try:
        svc.assign_role(session, soldier=s, role=body.role, actor_id=user.id)
    except svc.SoldierError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(s)
    return _out(s)
```

- [ ] **Step 4: Wire the router in `backend/app/main.py`**

Add `from app.routes import soldiers as soldier_routes` and `app.include_router(soldier_routes.router, prefix="/api")`.

- [ ] **Step 5: Run — expect PASS**

Run: `uv run pytest tests/integration/test_soldiers_api.py -q`
Expected: `6 passed`.

- [ ] **Step 6: Commit**

```bash
git -C .. add backend/app/routes/soldiers.py backend/app/main.py backend/tests/integration/test_soldiers_api.py
git -C .. commit -m "feat(api): soldier onboard/list/get/update/reset/delete/assign-role"
```

---

### Task 15: RBAC matrix + must-change-password gating (integration)

**Files:**
- Create: `backend/tests/integration/test_rbac_matrix.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/integration/test_rbac_matrix.py
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_must_change_password_blocks_protected_endpoints(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="3000001", role="admin", must_change_password=True)
    # Protected endpoint is blocked...
    r = client.get("/api/soldiers", headers=auth_headers(admin))
    assert r.status_code == 403
    assert r.json()["detail"] == "must_change_password"
    # ...but change-password and /me remain reachable.
    assert client.get("/api/me", headers=auth_headers(admin)).status_code == 200


def test_commander_reads_subtree_cannot_write(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    cmd = create_soldier(admin_session, personal_number="3000002", role="commander")
    b.commander_id = cmd.id
    admin_session.flush()
    member = create_soldier(admin_session, personal_number="3100001", hierarchy_node_id=b.id)
    admin_session.commit()
    # read allowed
    assert client.get(f"/api/soldiers/{member.id}", headers=auth_headers(cmd)).status_code == 200
    # write denied
    denied = client.post("/api/soldiers", headers=auth_headers(cmd),
                         json={"personal_number": "3100002", "full_name": "x", "hierarchy_node_id": str(b.id)})
    assert denied.status_code == 403


def test_soldier_sees_only_self_in_list(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    s = create_soldier(admin_session, personal_number="3000003", role="soldier", hierarchy_node_id=d.id)
    create_soldier(admin_session, personal_number="3100003", hierarchy_node_id=d.id)
    admin_session.commit()
    r = client.get("/api/soldiers", headers=auth_headers(s))
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1 and body[0]["personal_number"] == "3000003"
```

- [ ] **Step 2: Run — expect PASS**

Run: `uv run pytest tests/integration/test_rbac_matrix.py -q`
Expected: `3 passed`.

- [ ] **Step 3: Run the whole backend suite**

Run: `uv run pytest -q`
Expected: all green (slice 1 + slice 2 tests).

- [ ] **Step 4: Commit**

```bash
git -C .. add backend/tests/integration/test_rbac_matrix.py
git -C .. commit -m "test(rbac): scope matrix + must-change-password gating"
```

---

### Task 16: backend lint/format/type gates

**Files:** none (verification + fixes only)

- [ ] **Step 1: Lint**

Run: `uv run ruff check app tests`
Expected: `All checks passed!` (fix anything reported; `uv run ruff check --fix app tests` for the autofixable).

- [ ] **Step 2: Format**

Run: `uv run ruff format app tests` then `uv run ruff format --check app tests`
Expected: `... files already formatted`.

- [ ] **Step 3: Type check**

Run: `uv run mypy app`
Expected: `Success: no issues found`. If mypy flags `path_ids` list invariance or `model_fields_set`, add a precise `# type: ignore[...]` with a short reason, matching the slice-1 approach.

- [ ] **Step 4: Commit (if anything changed)**

```bash
git -C .. add backend
git -C .. commit -m "chore(backend): lint/format/type fixes for slice 2"
```

---

## Phase G — Frontend

### Task 17: API clients + `/me` in AuthContext

**Files:**
- Modify: `frontend/src/api/auth.ts`
- Create: `frontend/src/api/soldiers.ts`
- Create: `frontend/src/api/hierarchy.ts`
- Modify: `frontend/src/auth/AuthContext.tsx`

- [ ] **Step 1: Extend `frontend/src/api/auth.ts`**

Append:

```ts
export interface Me {
  id: string;
  personal_number: string;
  full_name: string;
  role: "soldier" | "commander" | "duty_manager" | "admin";
  must_change_password: boolean;
  hierarchy_node_id: string | null;
}

export async function fetchMe(): Promise<Me> {
  const r = await api.get<Me>("/me");
  return r.data;
}

export async function changePassword(current_password: string, new_password: string): Promise<void> {
  await api.post("/auth/change-password", { current_password, new_password });
}
```

- [ ] **Step 2: Create `frontend/src/api/soldiers.ts`**

```ts
import { api } from "./client";

export interface SoldierDTO {
  id: string;
  personal_number: string;
  full_name: string;
  role: string;
  hierarchy_node_id: string | null;
  phone: string | null;
  must_change_password: boolean;
  left_at: string | null;
}

export interface OnboardResult extends SoldierDTO {
  temp_password: string | null;
}

export async function listSoldiers(): Promise<SoldierDTO[]> {
  return (await api.get<SoldierDTO[]>("/soldiers")).data;
}

export async function onboardSoldier(input: {
  personal_number: string;
  full_name: string;
  hierarchy_node_id: string | null;
  phone?: string | null;
  password?: string | null;
}): Promise<OnboardResult> {
  return (await api.post<OnboardResult>("/soldiers", input)).data;
}

export async function resetSoldierPassword(id: string): Promise<{ temp_password: string }> {
  return (await api.post<{ temp_password: string }>(`/soldiers/${id}/reset-password`)).data;
}

export async function softDeleteSoldier(id: string): Promise<void> {
  await api.delete(`/soldiers/${id}`);
}

export async function assignRole(id: string, role: string): Promise<SoldierDTO> {
  return (await api.post<SoldierDTO>(`/soldiers/${id}/role`, { role })).data;
}
```

- [ ] **Step 3: Create `frontend/src/api/hierarchy.ts`**

```ts
import { api } from "./client";

export interface NodeDTO {
  id: string;
  level: "department" | "branch" | "group" | "team";
  name: string;
  parent_id: string | null;
  commander_id: string | null;
  path_ids: string[];
}

export async function fetchTree(): Promise<NodeDTO[]> {
  return (await api.get<NodeDTO[]>("/hierarchy/tree")).data;
}

export async function createNode(input: {
  level: string;
  name: string;
  parent_id: string | null;
}): Promise<NodeDTO> {
  return (await api.post<NodeDTO>("/hierarchy/nodes", input)).data;
}

export async function renameNode(id: string, name: string): Promise<NodeDTO> {
  return (await api.patch<NodeDTO>(`/hierarchy/nodes/${id}`, { name })).data;
}

export async function moveNode(id: string, new_parent_id: string | null): Promise<NodeDTO> {
  return (await api.post<NodeDTO>(`/hierarchy/nodes/${id}/move`, { new_parent_id })).data;
}

export async function deleteNode(id: string): Promise<void> {
  await api.delete(`/hierarchy/nodes/${id}`);
}
```

- [ ] **Step 4: Update `frontend/src/auth/AuthContext.tsx`** to load `/me`

Replace the file with:

```tsx
import { createContext, useCallback, useContext, useMemo, useState, ReactNode } from "react";

import { changePassword as apiChangePassword, fetchMe, login as apiLogin, logout as apiLogout, Me } from "../api/auth";
import { setAccessToken } from "../api/client";

interface AuthContextValue {
  user: Me | null;
  loggedIn: boolean;
  mustChangePassword: boolean;
  login: (personal_number: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  changePassword: (current: string, next: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);

  const login = useCallback(async (personal_number: string, password: string) => {
    const r = await apiLogin(personal_number, password);
    setAccessToken(r.access_token);
    setUser(await fetchMe());
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      setAccessToken(null);
      setUser(null);
    }
  }, []);

  const changePassword = useCallback(async (current: string, next: string) => {
    await apiChangePassword(current, next);
    setUser(await fetchMe());
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, loggedIn: user !== null, mustChangePassword: user?.must_change_password ?? false, login, logout, changePassword }),
    [user, login, logout, changePassword],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth used outside AuthProvider");
  return ctx;
}
```

- [ ] **Step 5: Typecheck**

Run: `pnpm exec tsc --noEmit`
Expected: passes (Layout/pages updated in later tasks may still reference old shape — if tsc errors only in not-yet-edited files, proceed; they're fixed in Tasks 18–20. To keep this step green, run after Task 20 instead and just commit here.)

- [ ] **Step 6: Commit**

```bash
git -C .. add frontend/src/api frontend/src/auth/AuthContext.tsx
git -C .. commit -m "feat(frontend): soldiers/hierarchy api clients + /me-backed auth context"
```

---

### Task 18: Change-password page + forced-change flow + routes

**Files:**
- Create: `frontend/src/pages/ChangePasswordPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add i18n strings**

Merge into `frontend/src/i18n/he.json` (add these keys):

```json
{
  "change_password": {
    "title": "שינוי סיסמה",
    "current": "סיסמה נוכחית",
    "new": "סיסמה חדשה",
    "submit": "עדכן סיסמה",
    "forced_notice": "עליך לבחור סיסמה חדשה לפני המשך השימוש.",
    "min_length": "הסיסמה חייבת להכיל לפחות 10 תווים.",
    "wrong_current": "הסיסמה הנוכחית שגויה."
  },
  "nav": {
    "home": "ראשי",
    "team_hierarchy": "אנשי צוות והיררכיה",
    "profile": "פרופיל"
  },
  "team": {
    "title": "אנשי צוות והיררכיה",
    "soldiers": "אנשי צוות",
    "add_soldier": "הוסף איש צוות",
    "personal_number": "מספר אישי",
    "full_name": "שם מלא",
    "role": "תפקיד",
    "reset_password": "אפס סיסמה",
    "remove": "הסר",
    "temp_password_is": "סיסמה זמנית: {{pw}}",
    "add_node": "הוסף יחידה",
    "node_name": "שם יחידה"
  },
  "profile": {
    "title": "פרופיל",
    "change_password": "שינוי סיסמה"
  }
}
```

- [ ] **Step 2: Create `frontend/src/pages/ChangePasswordPage.tsx`**

```tsx
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AxiosError } from "axios";

import { useAuth } from "../auth/AuthContext";

export default function ChangePasswordPage() {
  const { t } = useTranslation();
  const { changePassword, mustChangePassword } = useAuth();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (next.length < 10) {
      setError(t("change_password.min_length"));
      return;
    }
    setSubmitting(true);
    try {
      await changePassword(current, next);
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof AxiosError && err.response?.status === 400) {
        const detail = (err.response.data as { detail?: string })?.detail;
        setError(detail === "password_too_short" ? t("change_password.min_length") : t("change_password.wrong_current"));
      } else {
        setError(t("change_password.wrong_current"));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <form onSubmit={onSubmit} className="w-full max-w-sm bg-white shadow rounded-lg p-6 space-y-4" data-testid="change-password-form">
        <h1 className="text-2xl font-bold text-center">{t("change_password.title")}</h1>
        {mustChangePassword && (
          <div className="bg-pending/10 border border-pending/30 text-pending px-3 py-2 text-sm rounded" data-testid="forced-notice">
            {t("change_password.forced_notice")}
          </div>
        )}
        <label className="block">
          <span className="text-sm font-medium">{t("change_password.current")}</span>
          <input type="password" required className="mt-1 block w-full rounded-md border p-2" value={current}
                 onChange={(e) => setCurrent(e.target.value)} data-testid="current-password" />
        </label>
        <label className="block">
          <span className="text-sm font-medium">{t("change_password.new")}</span>
          <input type="password" required className="mt-1 block w-full rounded-md border p-2" value={next}
                 onChange={(e) => setNext(e.target.value)} data-testid="new-password" />
        </label>
        {error && <div className="text-rejected text-sm" data-testid="change-password-error">{error}</div>}
        <button type="submit" disabled={submitting}
                className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white font-medium py-2 rounded-md"
                data-testid="change-password-submit">
          {t("change_password.submit")}
        </button>
      </form>
    </main>
  );
}
```

- [ ] **Step 3: Update `frontend/src/App.tsx`** to add routes + forced redirect

```tsx
import { Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider, useAuth } from "./auth/AuthContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import ProfilePage from "./pages/ProfilePage";
import TeamHierarchyPage from "./pages/TeamHierarchyPage";

function ForcedPasswordGate({ children }: { children: JSX.Element }) {
  const { mustChangePassword } = useAuth();
  if (mustChangePassword) return <Navigate to="/change-password" replace />;
  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/change-password" element={<ChangePasswordPage />} />
          <Route path="/" element={<ForcedPasswordGate><HomePage /></ForcedPasswordGate>} />
          <Route path="/team" element={<ForcedPasswordGate><TeamHierarchyPage /></ForcedPasswordGate>} />
          <Route path="/profile" element={<ForcedPasswordGate><ProfilePage /></ForcedPasswordGate>} />
        </Route>
      </Routes>
    </AuthProvider>
  );
}
```

- [ ] **Step 4: Commit** (pages referenced here are created in Tasks 19–20; tsc is run at Task 21)

```bash
git -C .. add frontend/src/pages/ChangePasswordPage.tsx frontend/src/App.tsx frontend/src/i18n/he.json
git -C .. commit -m "feat(frontend): change-password page + forced-change redirect + routes"
```

---

### Task 19: Profile page + role-gated sidebar

**Files:**
- Create: `frontend/src/pages/ProfilePage.tsx`
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Create `frontend/src/pages/ProfilePage.tsx`**

```tsx
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { useAuth } from "../auth/AuthContext";

export default function ProfilePage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-3">
        <h2 className="text-xl font-semibold">{t("profile.title")}</h2>
        <p>{t("team.full_name")}: {user?.full_name}</p>
        <p>{t("team.personal_number")}: {user?.personal_number}</p>
        <p>{t("team.role")}: {user?.role}</p>
        <Link to="/change-password" className="text-indigo-600 hover:text-indigo-800" data-testid="profile-change-password">
          {t("profile.change_password")}
        </Link>
      </section>
    </Layout>
  );
}
```

- [ ] **Step 2: Update `frontend/src/components/Layout.tsx`** with a role-gated sidebar

```tsx
import { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useAuth } from "../auth/AuthContext";

export default function Layout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { user, logout } = useAuth();
  const role = user?.role;
  const canManageTeam = role === "duty_manager" || role === "admin" || role === "commander";

  return (
    <div className="min-h-screen flex">
      <aside className="w-56 bg-white border-l shadow-sm p-4 space-y-2" data-testid="sidebar">
        <Link to="/" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-home">{t("nav.home")}</Link>
        {canManageTeam && (
          <Link to="/team" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-team">{t("nav.team_hierarchy")}</Link>
        )}
        <Link to="/profile" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-profile">{t("nav.profile")}</Link>
      </aside>
      <div className="flex-1 flex flex-col">
        <header className="bg-white shadow-sm border-b">
          <div className="px-4 py-3 flex items-center justify-between">
            <h1 className="text-lg font-bold">{t("app.title")}</h1>
            <button onClick={() => logout()} className="text-sm text-indigo-600 hover:text-indigo-800" data-testid="logout-button">
              {t("home.logout")}
            </button>
          </div>
        </header>
        <main className="flex-1 px-4 py-6">{children}</main>
      </div>
    </div>
  );
}
```

> The old `mustChangePassword` banner in Layout is removed; the forced-change redirect (Task 18) now handles that case before any Layout page renders.

- [ ] **Step 3: Commit**

```bash
git -C .. add frontend/src/pages/ProfilePage.tsx frontend/src/components/Layout.tsx
git -C .. commit -m "feat(frontend): profile page + role-gated sidebar"
```

---

### Task 20: Team & hierarchy page

**Files:**
- Create: `frontend/src/pages/TeamHierarchyPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/TeamHierarchyPage.tsx`**

```tsx
import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { useAuth } from "../auth/AuthContext";
import { NodeDTO, createNode, fetchTree } from "../api/hierarchy";
import { SoldierDTO, listSoldiers, onboardSoldier, resetSoldierPassword, softDeleteSoldier } from "../api/soldiers";

export default function TeamHierarchyPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [pn, setPn] = useState("");
  const [name, setName] = useState("");
  const [nodeId, setNodeId] = useState("");
  const [tempPw, setTempPw] = useState<string | null>(null);
  const isAdmin = user?.role === "admin";

  async function refresh() {
    setNodes(await fetchTree());
    setSoldiers(await listSoldiers());
  }
  useEffect(() => { void refresh(); }, []);

  async function addSoldier(e: FormEvent) {
    e.preventDefault();
    const res = await onboardSoldier({ personal_number: pn, full_name: name, hierarchy_node_id: nodeId || null });
    setTempPw(res.temp_password);
    setPn(""); setName(""); setNodeId("");
    await refresh();
  }

  async function onReset(id: string) {
    const r = await resetSoldierPassword(id);
    setTempPw(r.temp_password);
  }

  async function onRemove(id: string) {
    if (!confirm(t("team.remove") + "?")) return;
    await softDeleteSoldier(id);
    await refresh();
  }

  async function addDepartment() {
    const nm = prompt(t("team.node_name"));
    if (!nm) return;
    await createNode({ level: "department", name: nm, parent_id: null });
    await refresh();
  }

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-6" data-testid="team-page">
        <h2 className="text-xl font-semibold">{t("team.title")}</h2>

        <div className="flex items-center gap-3">
          <h3 className="font-medium">{t("team.title")}</h3>
          {isAdmin && (
            <button onClick={addDepartment} className="text-sm text-indigo-600" data-testid="add-department">
              {t("team.add_node")}
            </button>
          )}
        </div>
        <ul className="text-sm text-gray-700" data-testid="node-list">
          {nodes.map((n) => (
            <li key={n.id} style={{ paddingInlineStart: `${(n.path_ids.length - 1) * 16}px` }}>
              {n.name} <span className="text-gray-400">({n.level})</span>
            </li>
          ))}
        </ul>

        <form onSubmit={addSoldier} className="flex flex-wrap items-end gap-2" data-testid="onboard-form">
          <label className="block">
            <span className="text-xs">{t("team.personal_number")}</span>
            <input className="block border rounded p-1" value={pn} onChange={(e) => setPn(e.target.value)} required data-testid="onboard-pn" />
          </label>
          <label className="block">
            <span className="text-xs">{t("team.full_name")}</span>
            <input className="block border rounded p-1" value={name} onChange={(e) => setName(e.target.value)} required data-testid="onboard-name" />
          </label>
          <label className="block">
            <span className="text-xs">{t("team.title")}</span>
            <select className="block border rounded p-1" value={nodeId} onChange={(e) => setNodeId(e.target.value)} data-testid="onboard-node">
              <option value="">—</option>
              {nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
            </select>
          </label>
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="onboard-submit">
            {t("team.add_soldier")}
          </button>
        </form>

        {tempPw && <div className="text-sm text-approved" data-testid="temp-password">{t("team.temp_password_is", { pw: tempPw })}</div>}

        <table className="w-full text-sm" data-testid="soldier-table">
          <thead>
            <tr className="text-right text-gray-500">
              <th className="py-1">{t("team.personal_number")}</th>
              <th>{t("team.full_name")}</th>
              <th>{t("team.role")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {soldiers.map((s) => (
              <tr key={s.id} className="border-t" data-testid={`soldier-row-${s.personal_number}`}>
                <td className="py-1">{s.personal_number}</td>
                <td>{s.full_name}</td>
                <td>{s.role}</td>
                <td className="space-x-2 space-x-reverse">
                  <button onClick={() => onReset(s.id)} className="text-indigo-600" data-testid={`reset-${s.personal_number}`}>{t("team.reset_password")}</button>
                  <button onClick={() => onRemove(s.id)} className="text-rejected" data-testid={`remove-${s.personal_number}`}>{t("team.remove")}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </Layout>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git -C .. add frontend/src/pages/TeamHierarchyPage.tsx
git -C .. commit -m "feat(frontend): team & hierarchy management page"
```

---

### Task 21: Frontend gates (typecheck, lint, build)

**Files:** none (verification + fixes)

- [ ] **Step 1: Typecheck**

Run: `pnpm exec tsc --noEmit`
Expected: passes. (If `JSX.Element` is flagged, import `ReactElement` from "react" and use it instead in `ForcedPasswordGate`.) Fix any errors.

- [ ] **Step 2: Lint**

Run: `pnpm lint`
Expected: passes with no warnings.

- [ ] **Step 3: Build**

Run: `pnpm build`
Expected: build succeeds, no warnings.

- [ ] **Step 4: Commit (if anything changed)**

```bash
git -C .. add frontend
git -C .. commit -m "chore(frontend): typecheck/lint/build fixes for slice 2"
```

---

### Task 22: Playwright e2e — forced change + onboarding

**Files:**
- Create: `frontend/tests/e2e/change_password.spec.ts`
- Create: `frontend/tests/e2e/soldiers.spec.ts`

> These run against the live stack. The bootstrap admin (`1000001` / `ChangeMeOnFirstLogin!`) has `must_change_password=true`, so the first test changes it. **The second test depends on the password set by the first** — keep `fullyParallel: false` (already configured) and the file order below.

- [ ] **Step 1: Create `frontend/tests/e2e/change_password.spec.ts`**

```ts
import { test, expect } from "@playwright/test";

// Runs first (alphabetical): logs in as the bootstrap admin and changes the password.
test("forced password change on first login", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill("1000001");
  await page.getByTestId("password-input").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("login-submit").click();
  // forced redirect to change-password
  await expect(page).toHaveURL(/\/change-password$/);
  await expect(page.getByTestId("forced-notice")).toBeVisible();
  await page.getByTestId("current-password").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("new-password").fill("AdminNewPassw0rd");
  await page.getByTestId("change-password-submit").click();
  await expect(page).toHaveURL("/");
  await expect(page.getByTestId("nav-team")).toBeVisible(); // admin sees team nav
});
```

- [ ] **Step 2: Create `frontend/tests/e2e/soldiers.spec.ts`**

```ts
import { test, expect } from "@playwright/test";

async function loginAdmin(page) {
  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill("1000001");
  await page.getByTestId("password-input").fill("AdminNewPassw0rd"); // set by change_password.spec.ts
  await page.getByTestId("login-submit").click();
  await expect(page).toHaveURL("/");
}

test("admin onboards a soldier and gets a temp password", async ({ page }) => {
  await loginAdmin(page);
  await page.getByTestId("nav-team").click();
  await expect(page).toHaveURL(/\/team$/);
  const pn = `91${Date.now() % 100000}`;
  await page.getByTestId("onboard-pn").fill(pn);
  await page.getByTestId("onboard-name").fill("חייל בדיקה");
  await page.getByTestId("onboard-submit").click();
  await expect(page.getByTestId("temp-password")).toBeVisible();
  await expect(page.getByTestId(`soldier-row-${pn}`)).toBeVisible();
});
```

- [ ] **Step 3: Run e2e against the live stack**

Start (separate terminals, from repo root): `docker-compose up -d db`; in `backend/`: `uv run alembic upgrade head && uv run python -m app.scripts.bootstrap && uv run uvicorn app.main:app --port 8000`; in `frontend/`: `pnpm dev`.

Run (from `frontend/`): `pnpm exec playwright test`
Expected: `2 passed`.

> If the bootstrap admin password was already changed in a prior run, reset the local DB first: `docker-compose down -v && docker-compose up -d db`, re-run migrations + bootstrap.

- [ ] **Step 4: Commit**

```bash
git -C .. add frontend/tests/e2e/change_password.spec.ts frontend/tests/e2e/soldiers.spec.ts
git -C .. commit -m "test(e2e): forced password change + admin onboards soldier"
```

---

## Phase H — Finalize

### Task 23: Full verification + PR

**Files:** none

- [ ] **Step 1: Backend full suite + gates**

From `backend/`:
```
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
uv run pytest -q
```
Expected: all green.

- [ ] **Step 2: Frontend gates**

From `frontend/`:
```
pnpm lint
pnpm exec tsc --noEmit
pnpm test
pnpm build
```
Expected: all green.

- [ ] **Step 3: Push the branch and open a PR**

```bash
git -C .. push -u origin slice-2-hierarchy-and-soldiers
```
Then open the PR (gh CLI is not installed — use the printed branch URL) with a summary of slice 2 and a test plan covering the RBAC matrix, must-change-password gate, and hierarchy path_ids maintenance.

---

## Definition of done for Slice 2

- [ ] All tasks completed and committed on `slice-2-hierarchy-and-soldiers`.
- [ ] Migrations `0005`–`0006` apply from scratch; `path_ids` GIN index present; `soldiers.hierarchy_node_id` FK present.
- [ ] Strict single-step nesting enforced on create AND move; cycles rejected; node delete guarded against children/soldiers.
- [ ] `require(action, target)` scope rules hold: admin global; DM manages own subtree; commander reads commanded subtree; plain soldier self-only. Verified by `test_rbac_matrix.py`.
- [ ] `must_change_password` blocks every protected endpoint except `/api/me`, `/api/auth/change-password`, `/api/auth/logout`; clearing it unblocks. Verified in tests and e2e.
- [ ] Onboarding works both modes (temp generated vs onboarder-set); reset-password returns a one-time temp; role assignment is admin-only. All audited.
- [ ] Frontend: forced change-password flow, role-gated sidebar, team/hierarchy page (list/onboard/reset/remove + create department), profile page. Hebrew RTL.
- [ ] All backend + frontend gates green; e2e passes locally.

## What slice 2 deliberately does NOT include

- Duty types/locations, exemptions, personal constraints, duty assignments, scoring, the algorithm → slices 3–5.
- Drag-to-reparent UI (move is API-only this slice; the page lists the tree and creates departments — richer tree editing can come with the duties UI).
- Server-side refresh-token revocation list, audit-log UI, system-settings UI → later slices.
- Commander/DM self-service of their own scope beyond what the matrix specifies.

---

*End of plan.*
