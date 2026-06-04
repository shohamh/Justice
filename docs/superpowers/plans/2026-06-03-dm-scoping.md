# DM Scoping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace single-node DM scoping with a multi-node `DutyManagerScope` table; gate DM appointment on commander rank רסן+; implicitly grant/revoke `duty_manager` role when scope is assigned/removed.

**Architecture:** New `duty_manager_scope` table stores `(duty_manager_id, hierarchy_node_id)` pairs. `scope_root_ids()` in `authz.py` queries this table for DMs instead of reading `Soldier.hierarchy_node_id`. A new service handles assigning/removing scope entries, implicitly toggling the `duty_manager` role. A new router exposes the operations. Existing DMs are seeded via migration.

**Tech Stack:** Python/FastAPI, SQLAlchemy 2.x (mapped_column), Alembic, pytest + testcontainers

---

## File Map

| Action | Path |
|--------|------|
| Modify | `backend/app/db/models.py` |
| Create | `backend/alembic/versions/0032_dm_scope.py` |
| Modify | `backend/app/services/eligibility.py` |
| Modify | `backend/app/auth/authz.py` |
| Create | `backend/app/services/dm_scope.py` |
| Create | `backend/app/routes/dm_scope.py` |
| Modify | `backend/app/main.py` |
| Create | `backend/app/services/tests/test_dm_scope.py` |
| Create | `backend/app/routes/tests/test_dm_scope_routes.py` |

---

## Task 1: DutyManagerScope model + migration

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/0032_dm_scope.py`
- Create: `backend/app/services/tests/test_dm_scope.py` (first two tests)

- [ ] **Step 1: Write failing tests for model + table**

Create `backend/app/services/tests/test_dm_scope.py`:

```python
from __future__ import annotations

import uuid
import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import DutyManagerScope
from tests.helpers import create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_duty_manager_scope_insert(admin_session):
    """DutyManagerScope row can be inserted and its id auto-populated."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    entry = DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id)
    admin_session.add(entry)
    admin_session.commit()
    admin_session.refresh(entry)
    assert entry.id is not None


def test_duty_manager_scope_unique_constraint(admin_session):
    """Duplicate (duty_manager_id, hierarchy_node_id) raises IntegrityError."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    admin_session.commit()
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    with pytest.raises(IntegrityError):
        admin_session.commit()
    admin_session.rollback()
```

- [ ] **Step 2: Run tests — expect FAIL (DutyManagerScope not defined)**

```
cd backend && uv run pytest app/services/tests/test_dm_scope.py -v
```
Expected: `ImportError` or `AttributeError` — `DutyManagerScope` doesn't exist yet.

- [ ] **Step 3: Add DutyManagerScope to models.py**

Add after the `CommanderNotificationScope` class in `backend/app/db/models.py`:

```python
class DutyManagerScope(Base):
    __tablename__ = "duty_manager_scope"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    duty_manager_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id", ondelete="CASCADE")
    )
    __table_args__ = (
        sa.UniqueConstraint("duty_manager_id", "hierarchy_node_id", name="uq_dm_scope"),
    )
```

- [ ] **Step 4: Create migration `backend/alembic/versions/0032_dm_scope.py`**

```python
"""duty_manager_scope table — multi-node DM scoping, seeds existing DMs

Revision ID: 0032
Revises: 0031
Create Date: 2026-06-03
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "duty_manager_scope",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), primary_key=True,
        ),
        sa.Column("duty_manager_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hierarchy_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["duty_manager_id"], ["soldiers.id"],
            ondelete="CASCADE", name="fk_dm_scope_soldier",
        ),
        sa.ForeignKeyConstraint(
            ["hierarchy_node_id"], ["hierarchy_nodes.id"],
            ondelete="CASCADE", name="fk_dm_scope_node",
        ),
        sa.UniqueConstraint("duty_manager_id", "hierarchy_node_id", name="uq_dm_scope"),
    )
    # Seed existing duty managers from their current hierarchy_node_id
    op.get_bind().execute(sa.text("""
        INSERT INTO duty_manager_scope (id, duty_manager_id, hierarchy_node_id)
        SELECT gen_random_uuid(), id, hierarchy_node_id
        FROM soldiers
        WHERE role = 'duty_manager' AND hierarchy_node_id IS NOT NULL
    """))


def downgrade() -> None:
    op.drop_table("duty_manager_scope")
```

- [ ] **Step 5: Run tests — expect PASS**

```
cd backend && uv run pytest app/services/tests/test_dm_scope.py::test_duty_manager_scope_insert app/services/tests/test_dm_scope.py::test_duty_manager_scope_unique_constraint -v
```
Expected: both PASS.

- [ ] **Step 6: Commit**

```
git add backend/app/db/models.py backend/alembic/versions/0032_dm_scope.py backend/app/services/tests/test_dm_scope.py
git commit -m "feat: add DutyManagerScope model and migration 0032"
```

---

## Task 2: RANKS_RASAN_AND_ABOVE in eligibility.py

**Files:**
- Modify: `backend/app/services/eligibility.py`
- Modify: `backend/app/services/tests/test_dm_scope.py` (add test)

- [ ] **Step 1: Write failing test**

Append to `backend/app/services/tests/test_dm_scope.py`:

```python
def test_ranks_rasan_and_above_contents():
    from app.services.eligibility import RANKS_RASAN_AND_ABOVE
    assert RANKS_RASAN_AND_ABOVE[0] == "רסן"
    assert "סרן" not in RANKS_RASAN_AND_ABOVE
    assert "סאל" in RANKS_RASAN_AND_ABOVE
    assert "אלוף" in RANKS_RASAN_AND_ABOVE
```

- [ ] **Step 2: Run test — expect FAIL**

```
cd backend && uv run pytest app/services/tests/test_dm_scope.py::test_ranks_rasan_and_above_contents -v
```
Expected: `ImportError` — `RANKS_RASAN_AND_ABOVE` not defined.

- [ ] **Step 3: Add constant to eligibility.py**

Add after the `OFFICER_RANKS` list in `backend/app/services/eligibility.py`:

```python
RANKS_RASAN_AND_ABOVE = OFFICER_RANKS[OFFICER_RANKS.index("רסן"):]
# ["רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף"]
```

- [ ] **Step 4: Run test — expect PASS**

```
cd backend && uv run pytest app/services/tests/test_dm_scope.py::test_ranks_rasan_and_above_contents -v
```

- [ ] **Step 5: Commit**

```
git add backend/app/services/eligibility.py backend/app/services/tests/test_dm_scope.py
git commit -m "feat: add RANKS_RASAN_AND_ABOVE to eligibility"
```

---

## Task 3: Update authz.py — scope_root_ids, new actions, rank check

**Files:**
- Modify: `backend/app/auth/authz.py`
- Modify: `backend/app/services/tests/test_dm_scope.py` (add authz tests)

- [ ] **Step 1: Write failing tests**

Append to `backend/app/services/tests/test_dm_scope.py`:

```python
def test_scope_root_ids_dm_multi_node(admin_session):
    """DM with two DutyManagerScope entries gets both node IDs as roots."""
    node1 = create_node(admin_session, level="division", name=f"div1_{_uid()}")
    node2 = create_node(admin_session, level="division", name=f"div2_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node1.id))
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node2.id))
    admin_session.commit()

    from app.auth.authz import scope_root_ids
    roots = scope_root_ids(admin_session, dm)
    assert node1.id in roots
    assert node2.id in roots


def test_scope_root_ids_dm_no_entries(admin_session):
    """DM with no scope entries gets empty root set (not the old hierarchy_node_id)."""
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin_session.commit()

    from app.auth.authz import scope_root_ids
    roots = scope_root_ids(admin_session, dm)
    assert roots == set()


def test_dm_scope_manage_requires_rasan(admin_session):
    """Commander with rank רסן can DM_SCOPE_MANAGE their node; rank סרן cannot."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    high_cmd = create_soldier(admin_session, personal_number=f"cmd_h_{_uid()}", role="commander")
    high_cmd.rank = "רסן"
    high_cmd.hierarchy_node_id = node.id
    node.commander_id = high_cmd.id
    low_cmd = create_soldier(admin_session, personal_number=f"cmd_l_{_uid()}", role="commander")
    low_cmd.rank = "סרן"
    admin_session.commit()

    from app.auth.authz import can, scope_root_ids, Action
    roots_h = scope_root_ids(admin_session, high_cmd)
    roots_l = scope_root_ids(admin_session, low_cmd)

    assert can(high_cmd, Action.DM_SCOPE_MANAGE, target_node=node, roots=roots_h)
    assert not can(low_cmd, Action.DM_SCOPE_MANAGE, target_node=node, roots=roots_l)


def test_dm_scope_manage_null_rank_denied(admin_session):
    """Commander with null rank cannot DM_SCOPE_MANAGE."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    cmd = create_soldier(admin_session, personal_number=f"cmd_{_uid()}", role="commander")
    cmd.rank = None
    node.commander_id = cmd.id
    cmd.hierarchy_node_id = node.id
    admin_session.commit()

    from app.auth.authz import can, scope_root_ids, Action
    roots = scope_root_ids(admin_session, cmd)
    assert not can(cmd, Action.DM_SCOPE_MANAGE, target_node=node, roots=roots)
```

- [ ] **Step 2: Run tests — expect FAIL**

```
cd backend && uv run pytest app/services/tests/test_dm_scope.py::test_scope_root_ids_dm_multi_node app/services/tests/test_dm_scope.py::test_dm_scope_manage_requires_rasan -v
```
Expected: FAIL — `scope_root_ids` still uses `hierarchy_node_id`; `DM_SCOPE_MANAGE` not defined.

- [ ] **Step 3: Update authz.py**

Replace the full `backend/app/auth/authz.py` with:

```python
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyManagerScope, HierarchyNode, Soldier
from app.services.eligibility import RANKS_RASAN_AND_ABOVE


class Action:
    SOLDIER_CREATE = "soldier.create"
    SOLDIER_READ = "soldier.read"
    SOLDIER_UPDATE = "soldier.update"
    SOLDIER_RESET_PASSWORD = "soldier.reset_password"
    SOLDIER_DELETE = "soldier.delete"
    SOLDIER_ASSIGN_ROLE = "soldier.assign_role"
    HIERARCHY_READ = "hierarchy.read"
    HIERARCHY_MANAGE = "hierarchy.manage"
    EXEMPTION_GRANT = "exemption.grant"
    EXEMPTION_READ = "exemption.read"
    CONSTRAINT_SUBMIT = "constraint.submit"
    CONSTRAINT_READ = "constraint.read"
    CONSTRAINT_APPROVE = "constraint.approve"
    ASSIGNMENT_MANAGE = "assignment.manage"
    SCORE_ADJUST = "score.adjust"
    ALGORITHM_RUN = "algorithm.run"
    SWAP_APPROVE = "swap.approve"
    ENROLLMENT_APPROVE = "enrollment.approve"
    DM_SCOPE_MANAGE = "dm_scope.manage"


_DM_ACTIONS = {
    Action.SOLDIER_CREATE,
    Action.SOLDIER_READ,
    Action.SOLDIER_UPDATE,
    Action.SOLDIER_RESET_PASSWORD,
    Action.SOLDIER_DELETE,
    Action.HIERARCHY_READ,
    Action.HIERARCHY_MANAGE,
    Action.EXEMPTION_GRANT,
    Action.EXEMPTION_READ,
    Action.CONSTRAINT_READ,
    Action.CONSTRAINT_APPROVE,
    Action.SWAP_APPROVE,
    Action.ASSIGNMENT_MANAGE,
    Action.SCORE_ADJUST,
    Action.ALGORITHM_RUN,
    Action.ENROLLMENT_APPROVE,
}
_COMMANDER_ACTIONS = {
    Action.SOLDIER_READ,
    Action.HIERARCHY_READ,
    Action.EXEMPTION_GRANT,
    Action.EXEMPTION_READ,
    Action.CONSTRAINT_READ,
    Action.CONSTRAINT_APPROVE,
    Action.SWAP_APPROVE,
    Action.ENROLLMENT_APPROVE,
}

_DM_GLOBAL_ACTIONS = {
    Action.ALGORITHM_RUN,
    Action.ASSIGNMENT_MANAGE,
    Action.SWAP_APPROVE,
}


def scope_root_ids(session: Session, user: Soldier) -> set[uuid.UUID]:
    """The node ids whose subtrees this user governs."""
    roots: set[uuid.UUID] = set()
    if user.role == "duty_manager":
        dm_nodes = (
            session.execute(
                select(DutyManagerScope.hierarchy_node_id).where(
                    DutyManagerScope.duty_manager_id == user.id
                )
            )
            .scalars()
            .all()
        )
        roots.update(dm_nodes)
    commanded = (
        session.execute(select(HierarchyNode.id).where(HierarchyNode.commander_id == user.id))
        .scalars()
        .all()
    )
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
        return True
    if user.role == "duty_manager":
        if action in _DM_GLOBAL_ACTIONS:
            return True
        return action in _DM_ACTIONS and _node_in_scope(target_node, roots)
    if user.role == "commander":
        if action == Action.DM_SCOPE_MANAGE:
            return (
                bool(user.rank and user.rank in RANKS_RASAN_AND_ABOVE)
                and _node_in_scope(target_node, roots)
            )
        return action in _COMMANDER_ACTIONS and _node_in_scope(target_node, roots)
    return False


def authorize(
    session: Session, user: Soldier, action: str, *, target_node: HierarchyNode | None
) -> None:
    """Raise 403 unless `user` may perform `action` against `target_node`'s subtree."""
    roots = scope_root_ids(session, user)
    if not can(user, action, target_node=target_node, roots=roots):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
```

- [ ] **Step 4: Run all authz tests — expect PASS**

```
cd backend && uv run pytest app/services/tests/test_dm_scope.py -k "scope_root_ids or dm_scope_manage" -v
```

- [ ] **Step 5: Run full test suite to catch regressions**

```
cd backend && uv run pytest -v
```
Expected: all existing tests still PASS.

- [ ] **Step 6: Commit**

```
git add backend/app/auth/authz.py backend/app/services/tests/test_dm_scope.py
git commit -m "feat: update authz scope_root_ids to use DutyManagerScope, add DM_SCOPE_MANAGE action"
```

---

## Task 4: DM scope service — assign + remove

**Files:**
- Create: `backend/app/services/dm_scope.py`
- Modify: `backend/app/services/tests/test_dm_scope.py` (add service tests)

- [ ] **Step 1: Write failing tests**

Append to `backend/app/services/tests/test_dm_scope.py`:

```python
def test_assign_dm_scope_grants_dm_role(admin_session):
    """assign_dm_scope on a soldier grants duty_manager role."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    s = create_soldier(admin_session, personal_number=f"s_{_uid()}", role="soldier")

    from app.services.dm_scope import assign_dm_scope
    assign_dm_scope(admin_session, soldier_id=s.id, node_id=node.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(s)

    assert s.role == "duty_manager"


def test_assign_dm_scope_idempotent(admin_session):
    """Calling assign_dm_scope twice for the same (soldier, node) returns the same entry."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    s = create_soldier(admin_session, personal_number=f"s_{_uid()}", role="soldier")

    from app.services.dm_scope import assign_dm_scope
    e1 = assign_dm_scope(admin_session, soldier_id=s.id, node_id=node.id, actor_id=None)
    admin_session.commit()
    e2 = assign_dm_scope(admin_session, soldier_id=s.id, node_id=node.id, actor_id=None)
    admin_session.commit()

    assert e1.id == e2.id


def test_assign_dm_scope_does_not_downgrade_admin(admin_session):
    """assign_dm_scope does not change the role of an admin."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    from app.services.dm_scope import assign_dm_scope
    assign_dm_scope(admin_session, soldier_id=admin.id, node_id=node.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(admin)

    assert admin.role == "admin"


def test_remove_dm_scope_downgrades_to_soldier_when_last(admin_session):
    """Removing the last scope entry downgrades role to soldier."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    entry = DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id)
    admin_session.add(entry)
    admin_session.commit()
    admin_session.refresh(entry)

    from app.services.dm_scope import remove_dm_scope
    remove_dm_scope(admin_session, entry_id=entry.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(dm)

    assert dm.role == "soldier"


def test_remove_dm_scope_downgrades_to_commander_if_commands_node(admin_session):
    """Removing the last scope entry keeps role=commander if soldier commands a node."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    node.commander_id = dm.id
    entry = DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id)
    admin_session.add(entry)
    admin_session.commit()
    admin_session.refresh(entry)

    from app.services.dm_scope import remove_dm_scope
    remove_dm_scope(admin_session, entry_id=entry.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(dm)

    assert dm.role == "commander"


def test_remove_dm_scope_keeps_dm_role_if_other_entries_remain(admin_session):
    """Removing one of multiple scope entries does not downgrade the role."""
    node1 = create_node(admin_session, level="division", name=f"div1_{_uid()}")
    node2 = create_node(admin_session, level="division", name=f"div2_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    e1 = DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node1.id)
    e2 = DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node2.id)
    admin_session.add_all([e1, e2])
    admin_session.commit()
    admin_session.refresh(e1)

    from app.services.dm_scope import remove_dm_scope
    remove_dm_scope(admin_session, entry_id=e1.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(dm)

    assert dm.role == "duty_manager"
```

- [ ] **Step 2: Run tests — expect FAIL**

```
cd backend && uv run pytest app/services/tests/test_dm_scope.py -k "assign_dm or remove_dm" -v
```
Expected: `ImportError` — `app.services.dm_scope` doesn't exist.

- [ ] **Step 3: Create `backend/app/services/dm_scope.py`**

```python
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyManagerScope, HierarchyNode, Soldier


class DmScopeError(Exception):
    pass


def assign_dm_scope(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    node_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> DutyManagerScope:
    if session.get(Soldier, soldier_id) is None:
        raise DmScopeError("soldier not found")
    if session.get(HierarchyNode, node_id) is None:
        raise DmScopeError("node not found")

    existing = session.execute(
        select(DutyManagerScope).where(
            DutyManagerScope.duty_manager_id == soldier_id,
            DutyManagerScope.hierarchy_node_id == node_id,
        )
    ).scalar_one_or_none()
    if existing:
        return existing

    entry = DutyManagerScope(duty_manager_id=soldier_id, hierarchy_node_id=node_id)
    session.add(entry)

    soldier = session.get(Soldier, soldier_id)
    assert soldier is not None
    if soldier.role not in ("duty_manager", "admin"):
        soldier.role = "duty_manager"

    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="dm_scope.assign",
        entity_type="duty_manager_scope",
        entity_id=entry.id,
        after={"soldier_id": str(soldier_id), "node_id": str(node_id)},
    )
    return entry


def remove_dm_scope(
    session: Session,
    *,
    entry_id: uuid.UUID,
    actor_id: uuid.UUID | None,
) -> None:
    entry = session.get(DutyManagerScope, entry_id)
    if entry is None:
        raise DmScopeError("scope entry not found")

    soldier_id = entry.duty_manager_id
    session.delete(entry)
    session.flush()

    remaining = session.execute(
        select(func.count()).where(DutyManagerScope.duty_manager_id == soldier_id)
    ).scalar_one()

    if remaining == 0:
        soldier = session.get(Soldier, soldier_id)
        if soldier is not None and soldier.role == "duty_manager":
            commanded = session.execute(
                select(func.count()).where(HierarchyNode.commander_id == soldier_id)
            ).scalar_one()
            soldier.role = "commander" if commanded > 0 else "soldier"

    write_audit(
        session,
        actor_id=actor_id,
        action="dm_scope.remove",
        entity_type="duty_manager_scope",
        entity_id=entry_id,
    )
```

- [ ] **Step 4: Run service tests — expect PASS**

```
cd backend && uv run pytest app/services/tests/test_dm_scope.py -v
```

- [ ] **Step 5: Commit**

```
git add backend/app/services/dm_scope.py backend/app/services/tests/test_dm_scope.py
git commit -m "feat: add DM scope service with assign/remove and implicit role grant/revoke"
```

---

## Task 5: DM scope routes + wire into main.py

**Files:**
- Create: `backend/app/routes/dm_scope.py`
- Modify: `backend/app/main.py`
- Create: `backend/app/routes/tests/test_dm_scope_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `backend/app/routes/tests/test_dm_scope_routes.py`:

```python
from __future__ import annotations

import uuid
import pytest

from app.db.models import DutyManagerScope
from tests.helpers import auth_headers, create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_assign_scope_as_admin(client, admin_session):
    """Admin can POST /duty-manager-scope to assign a soldier as DM."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    resp = client.post(
        "/api/duty-manager-scope",
        json={"soldier_id": str(soldier.id), "node_id": str(node.id)},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["duty_manager_id"] == str(soldier.id)
    assert data["hierarchy_node_id"] == str(node.id)
    admin_session.refresh(soldier)
    assert soldier.role == "duty_manager"


def test_assign_scope_commander_low_rank_forbidden(client, admin_session):
    """Commander with rank סרן (below רסן) cannot assign DM scope."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    cmd = create_soldier(admin_session, personal_number=f"cmd_{_uid()}", role="commander")
    cmd.rank = "סרן"
    node.commander_id = cmd.id
    cmd.hierarchy_node_id = node.id
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")

    resp = client.post(
        "/api/duty-manager-scope",
        json={"soldier_id": str(soldier.id), "node_id": str(node.id)},
        headers=auth_headers(cmd),
    )
    assert resp.status_code == 403


def test_assign_scope_commander_rasan_allowed(client, admin_session):
    """Commander with rank רסן can assign DM scope within their subtree."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    cmd = create_soldier(admin_session, personal_number=f"cmd_{_uid()}", role="commander")
    cmd.rank = "רסן"
    node.commander_id = cmd.id
    cmd.hierarchy_node_id = node.id
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")

    resp = client.post(
        "/api/duty-manager-scope",
        json={"soldier_id": str(soldier.id), "node_id": str(node.id)},
        headers=auth_headers(cmd),
    )
    assert resp.status_code == 201


def test_remove_scope_as_admin(client, admin_session):
    """Admin can DELETE /duty-manager-scope/{id}; role downgrades to soldier."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    entry = DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id)
    admin_session.add(entry)
    admin_session.commit()
    admin_session.refresh(entry)

    resp = client.delete(f"/api/duty-manager-scope/{entry.id}", headers=auth_headers(admin))
    assert resp.status_code == 200
    admin_session.refresh(dm)
    assert dm.role == "soldier"


def test_list_scope(client, admin_session):
    """GET /duty-manager-scope?soldier_id=... returns that soldier's scope entries."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    entry = DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id)
    admin_session.add(entry)
    admin_session.commit()

    resp = client.get(
        f"/api/duty-manager-scope?soldier_id={dm.id}",
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["hierarchy_node_id"] == str(node.id)
```

- [ ] **Step 2: Run tests — expect FAIL**

```
cd backend && uv run pytest app/routes/tests/test_dm_scope_routes.py -v
```
Expected: `404` or connection error — router not registered yet.

- [ ] **Step 3: Create `backend/app/routes/dm_scope.py`**

```python
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import DutyManagerScope, HierarchyNode
from app.db.session import get_session
from app.services import dm_scope as svc

router = APIRouter(prefix="/duty-manager-scope", tags=["duty_manager_scope"])


class AssignRequest(BaseModel):
    soldier_id: uuid.UUID
    node_id: uuid.UUID


class ScopeEntryOut(BaseModel):
    id: uuid.UUID
    duty_manager_id: uuid.UUID
    hierarchy_node_id: uuid.UUID


@router.post("", response_model=ScopeEntryOut, status_code=status.HTTP_201_CREATED)
def assign_scope(
    body: AssignRequest,
    session: Session = Depends(get_session),
    user=Depends(require_password_changed),
) -> ScopeEntryOut:
    target_node = session.get(HierarchyNode, body.node_id)
    authorize(session, user, Action.DM_SCOPE_MANAGE, target_node=target_node)
    try:
        entry = svc.assign_dm_scope(
            session, soldier_id=body.soldier_id, node_id=body.node_id, actor_id=user.id
        )
        session.commit()
        return ScopeEntryOut(
            id=entry.id,
            duty_manager_id=entry.duty_manager_id,
            hierarchy_node_id=entry.hierarchy_node_id,
        )
    except svc.DmScopeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/{entry_id}", status_code=status.HTTP_200_OK)
def remove_scope(
    entry_id: uuid.UUID,
    session: Session = Depends(get_session),
    user=Depends(require_password_changed),
) -> dict:
    entry = session.get(DutyManagerScope, entry_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")
    target_node = session.get(HierarchyNode, entry.hierarchy_node_id)
    authorize(session, user, Action.DM_SCOPE_MANAGE, target_node=target_node)
    try:
        svc.remove_dm_scope(session, entry_id=entry_id, actor_id=user.id)
        session.commit()
        return {"status": "ok"}
    except svc.DmScopeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("", response_model=list[ScopeEntryOut])
def list_scope(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user=Depends(require_password_changed),
) -> list[ScopeEntryOut]:
    entries = (
        session.execute(
            select(DutyManagerScope).where(DutyManagerScope.duty_manager_id == soldier_id)
        )
        .scalars()
        .all()
    )
    return [
        ScopeEntryOut(
            id=e.id,
            duty_manager_id=e.duty_manager_id,
            hierarchy_node_id=e.hierarchy_node_id,
        )
        for e in entries
    ]
```

- [ ] **Step 4: Wire router into `backend/app/main.py`**

Add import:
```python
from app.routes import dm_scope as dm_scope_routes
```

Add inside `create_app()` after the last `include_router` call:
```python
app.include_router(dm_scope_routes.router, prefix="/api")
```

- [ ] **Step 5: Run route tests — expect PASS**

```
cd backend && uv run pytest app/routes/tests/test_dm_scope_routes.py -v
```

- [ ] **Step 6: Run full test suite**

```
cd backend && uv run pytest -v
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```
git add backend/app/routes/dm_scope.py backend/app/main.py backend/app/routes/tests/test_dm_scope_routes.py
git commit -m "feat: add DM scope routes — assign/remove/list duty manager scope"
```
