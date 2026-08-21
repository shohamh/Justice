# Commander/Duty-Officer Deputy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a commander or duty-officer (אחראי תורנויות) define one or more time-limited deputies who gain the same permissions for the duration of a start/end date window, with zero ongoing maintenance.

**Architecture:** A new `role_deputies` table records `(principal_id, deputy_id, role, start_date, end_date)`. All authorization is computed live, per-request — no background job. Two new functions in `app/auth/authz.py` (`commanded_node_ids`, `dm_scope_node_ids`) are the single source of truth for "which hierarchy nodes does this soldier govern," each returning the soldier's own scope unioned with the scope of anyone they're currently an active deputy for. Every other file that currently queries `HierarchyNode.commander_id`/`DutyManagerScope` directly is refactored to call these two functions instead, so deputy-awareness propagates everywhere automatically. Notifications get a parallel, smaller extension.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (dataclass-style declarative models), Alembic, pytest + testcontainers (backend). React 18, TypeScript, Vitest + Testing Library (frontend).

## Global Constraints

- No recursion: a deputy cannot themselves have a sub-deputy — enforced at creation time.
- `end_date >= start_date`; both required (no open-ended deputies).
- A soldier may be deputy for multiple different principals simultaneously; a principal may have multiple deputies simultaneously.
- "Active" = `start_date <= today <= end_date`, evaluated live — never materialized/synced.
- Deputy assignment: self-service (principal only, if they currently hold the role) or admin. No one else.
- Out of scope, deliberately untouched: `routes/me.py`/`routes/soldiers.py`'s "direct commander" display logic, `services/hierarchy.py`'s commander-reassignment mutation, `services/dm_scope.py`'s scope-assignment mutation, `SwapManagerApproval.commander_id`, `CommanderNotificationScope` rows themselves (only their *usage* in notification cascades is extended).

---

## File Structure

**Backend — new files:**
- `backend/alembic/versions/<rev>_create_role_deputies.py` — migration
- `backend/app/services/deputies.py` — create/list/revoke a deputy grant
- `backend/app/routes/deputies.py` — `POST/GET /deputies`, `DELETE /deputies/{id}`

**Backend — modified files:**
- `backend/app/db/models.py` — add `RoleDeputy`
- `backend/app/auth/authz.py` — add `commanded_node_ids`/`dm_scope_node_ids`; refactor `is_commander`/`is_duty_manager`/`scope_root_ids`/`can_view_medical_document`
- `backend/app/services/authority.py` — refactor `_commanded_nodes`/`_dm_scope_nodes` and every function that currently inlines its own commander/DM-scope query
- `backend/app/routes/commander_dashboard.py` — refactor `_commander_node`
- `backend/app/routes/range_qualification_visibility.py` — refactor `_resolve_roots`
- `backend/app/routes/exemption_requests.py` — refactor the inline DM-scope lookup
- `backend/app/services/hierarchy_transfers.py` — refactor `list_pending_for_approver`
- `backend/app/services/notifications.py` — add `_active_deputy_ids`; extend `cascade_to_commanders`, `notify_duty_managers_in_scope`, `notify_duty_managers_of_request`, `notify_enrollment_received`
- `backend/app/routes/me.py` — add `active_deputy_grants` to `MeResponse`
- `backend/app/main.py` — register the new router

**Frontend — new files:**
- `frontend/src/api/deputies.ts`
- `frontend/src/components/DeputiesPanel.tsx`
- `frontend/src/components/DeputiesPanel.test.tsx`
- `frontend/src/components/ActiveDeputyBanner.tsx`
- `frontend/src/components/ActiveDeputyBanner.test.tsx`

**Frontend — modified files:**
- `frontend/src/pages/ProfilePage.tsx` — render `DeputiesPanel` (self-service)
- `frontend/src/components/UnifiedSoldierModal.tsx` — render `DeputiesPanel` (admin)
- `frontend/src/pages/HomePage.tsx` — render `ActiveDeputyBanner`
- `frontend/src/api/auth.ts` — add `active_deputy_grants` to the `Me` interface
- `frontend/src/i18n/he.json` — new `deputies.*` keys

---

## Task 1: `role_deputies` table and `RoleDeputy` model

**Files:**
- Create: `backend/alembic/versions/<rev>_create_role_deputies.py`
- Modify: `backend/app/db/models.py`
- Test: `backend/tests/unit/test_migration_<rev>_role_deputies.py`

**Interfaces:**
- Produces: `RoleDeputy` model with fields `id, principal_id, deputy_id, role, start_date, end_date, created_by, created_at`; table `role_deputies` with unique `(principal_id, deputy_id, role)` and check `end_date >= start_date`.

- [ ] **Step 1: Generate the migration file**

Run (from `backend/`, with the venv active):

```bash
alembic revision -m "create role_deputies table"
```

This creates a file named `<rev>_create_role_deputies.py` with a random 12-hex-char revision id and `down_revision` set to whatever the current head is. Note the generated `<rev>` value — you'll need it for the test file name and the `REVISION`/`DOWN_REVISION` constants in Step 4.

- [ ] **Step 2: Write the migration body**

Replace the generated file's `upgrade`/`downgrade` functions (keep the auto-generated header/revision/down_revision lines as-is):

```python
def upgrade() -> None:
    op.create_table(
        "role_deputies",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), primary_key=True,
        ),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("deputy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role", sa.Enum("commander", "duty_manager", name="deputy_role"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["principal_id"], ["soldiers.id"], ondelete="CASCADE", name="fk_role_deputy_principal"),
        sa.ForeignKeyConstraint(["deputy_id"], ["soldiers.id"], ondelete="CASCADE", name="fk_role_deputy_deputy"),
        sa.ForeignKeyConstraint(["created_by"], ["soldiers.id"], ondelete="SET NULL", name="fk_role_deputy_created_by"),
        sa.UniqueConstraint("principal_id", "deputy_id", "role", name="uq_role_deputy"),
        sa.CheckConstraint("end_date >= start_date", name="ck_role_deputy_date_range"),
    )


def downgrade() -> None:
    op.drop_table("role_deputies")
    op.execute("DROP TYPE IF EXISTS deputy_role")
```

Also add this import near the top of the file if not already present (the generated template already imports `sqlalchemy as sa` and `from alembic import op`; add the postgresql dialect import too):

```python
from sqlalchemy.dialects import postgresql
```

- [ ] **Step 3: Add the `RoleDeputy` model**

In `backend/app/db/models.py`, add this class immediately after `class DutyManagerScope` (which ends around line 1394 with its `__table_args__`):

```python
class RoleDeputy(Base):
    __tablename__ = "role_deputies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    deputy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(Enum("commander", "duty_manager", name="deputy_role"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    __table_args__ = (
        sa.UniqueConstraint("principal_id", "deputy_id", "role", name="uq_role_deputy"),
        sa.CheckConstraint("end_date >= start_date", name="ck_role_deputy_date_range"),
    )
```

`date`, `datetime`, `Enum`, `Date`, `DateTime`, `text`, `ForeignKey`, `UUID`, and `sa` are already imported at the top of `models.py` — no new imports needed there.

- [ ] **Step 4: Write the migration test**

Create `backend/tests/unit/test_migration_<rev>_role_deputies.py` (substitute the actual revision id from Step 1 for `<rev>` in the filename and the `REVISION` constant below; find the head revision your migration revises from — the value alembic wrote into `down_revision` in Step 1 — and use it as `DOWN_REVISION`):

```python
"""Tests for migration <rev> (create role_deputies table).

Uses the same throwaway-container pattern as
test_migration_15feab823caf_squad_level.py: the shared session-scoped
container in conftest.py is already migrated straight to head, so there's
no way to seed pre-migration state against it.
"""
import os
import uuid
from contextlib import contextmanager
from datetime import date

from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import IntegrityError
from testcontainers.postgres import PostgresContainer

DOWN_REVISION = "<down_revision_from_step_1>"
REVISION = "<rev>"


@contextmanager
def _db_at_down_revision():
    from app.settings import get_settings

    saved_database_url = os.environ.get("DATABASE_URL")
    saved_db_admin_url = os.environ.get("DB_ADMIN_URL")

    with PostgresContainer(
        "postgres:16-alpine", username="db_admin", password="db_admin_pw", dbname="justice"
    ).with_command(
        "postgres -c fsync=off -c full_page_writes=off -c synchronous_commit=off"
    ) as pg:
        url = make_url(pg.get_connection_url()).set(drivername="postgresql+psycopg")
        db_url = url.render_as_string(hide_password=False)

        try:
            os.environ["DATABASE_URL"] = db_url
            os.environ["DB_ADMIN_URL"] = db_url
            get_settings.cache_clear()

            from alembic import command
            from alembic.config import Config

            cfg = Config("alembic.ini")
            cfg.set_main_option("script_location", "alembic")
            command.upgrade(cfg, DOWN_REVISION)

            engine = create_engine(db_url, future=True)
            try:
                yield engine, (lambda: command.upgrade(cfg, REVISION))
            finally:
                engine.dispose()
        finally:
            if saved_database_url is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = saved_database_url
            if saved_db_admin_url is None:
                os.environ.pop("DB_ADMIN_URL", None)
            else:
                os.environ["DB_ADMIN_URL"] = saved_db_admin_url
            get_settings.cache_clear()


def _insert_soldier(conn, *, personal_number):
    sid = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO soldiers (id, personal_number, full_name, password_hash, role) "
            "VALUES (:id, :pn, 'Test', 'x', 'soldier')"
        ),
        {"id": sid, "pn": personal_number},
    )
    return sid


def test_upgrade_creates_table_with_working_constraints():
    with _db_at_down_revision() as (engine, run_migration):
        run_migration()

        with engine.begin() as conn:
            principal_id = _insert_soldier(conn, personal_number="dep-test-1")
            deputy_id = _insert_soldier(conn, personal_number="dep-test-2")
            conn.execute(
                text(
                    "INSERT INTO role_deputies (id, principal_id, deputy_id, role, start_date, end_date) "
                    "VALUES (gen_random_uuid(), :p, :d, 'commander', :s, :e)"
                ),
                {"p": principal_id, "d": deputy_id, "s": date(2026, 1, 1), "e": date(2026, 1, 31)},
            )

        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT role, start_date, end_date FROM role_deputies WHERE principal_id = :p"),
                {"p": principal_id},
            ).mappings().one()
        assert row["role"] == "commander"
        assert row["start_date"] == date(2026, 1, 1)
        assert row["end_date"] == date(2026, 1, 31)


def test_end_date_before_start_date_is_rejected():
    with _db_at_down_revision() as (engine, run_migration):
        run_migration()

        with engine.begin() as conn:
            principal_id = _insert_soldier(conn, personal_number="dep-test-3")
            deputy_id = _insert_soldier(conn, personal_number="dep-test-4")

        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO role_deputies (id, principal_id, deputy_id, role, start_date, end_date) "
                        "VALUES (gen_random_uuid(), :p, :d, 'commander', :s, :e)"
                    ),
                    {"p": principal_id, "d": deputy_id, "s": date(2026, 2, 1), "e": date(2026, 1, 1)},
                )
            assert False, "expected IntegrityError from the date-range check constraint"
        except IntegrityError:
            pass


def test_duplicate_principal_deputy_role_is_rejected():
    with _db_at_down_revision() as (engine, run_migration):
        run_migration()

        with engine.begin() as conn:
            principal_id = _insert_soldier(conn, personal_number="dep-test-5")
            deputy_id = _insert_soldier(conn, personal_number="dep-test-6")
            conn.execute(
                text(
                    "INSERT INTO role_deputies (id, principal_id, deputy_id, role, start_date, end_date) "
                    "VALUES (gen_random_uuid(), :p, :d, 'commander', :s, :e)"
                ),
                {"p": principal_id, "d": deputy_id, "s": date(2026, 1, 1), "e": date(2026, 1, 31)},
            )

        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO role_deputies (id, principal_id, deputy_id, role, start_date, end_date) "
                        "VALUES (gen_random_uuid(), :p, :d, 'commander', :s2, :e2)"
                    ),
                    {"p": principal_id, "d": deputy_id, "s2": date(2026, 3, 1), "e2": date(2026, 3, 31)},
                )
            assert False, "expected IntegrityError from the unique constraint"
        except IntegrityError:
            pass


def test_downgrade_drops_the_table():
    from alembic import command
    from alembic.config import Config

    with _db_at_down_revision() as (engine, run_migration):
        run_migration()

        cfg = Config("alembic.ini")
        cfg.set_main_option("script_location", "alembic")
        command.downgrade(cfg, DOWN_REVISION)

        with engine.begin() as conn:
            exists = conn.execute(
                text("SELECT to_regclass('role_deputies')")
            ).scalar()
        assert exists is None
```

- [ ] **Step 5: Run the migration tests**

Run: `pytest tests/unit/test_migration_<rev>_role_deputies.py -q`
Expected: 4 passed.

- [ ] **Step 6: Run the full fast suite to catch any model-loading regression**

Run: `pytest -q`
Expected: all pass (this confirms the new model doesn't break SQLAlchemy metadata loading anywhere else).

- [ ] **Step 7: Commit**

```bash
git add backend/alembic/versions/<rev>_create_role_deputies.py backend/app/db/models.py backend/tests/unit/test_migration_<rev>_role_deputies.py
git commit -m "feat: add role_deputies table and RoleDeputy model"
```

---

## Task 2: Deputy-aware scope lookups in `authz.py`

**Files:**
- Modify: `backend/app/auth/authz.py`
- Test: `backend/app/services/tests/test_authz_deputies.py` (new)

**Interfaces:**
- Consumes: `RoleDeputy` (Task 1).
- Produces: `commanded_node_ids(session, soldier_id, *, today=None) -> set[uuid.UUID]`, `dm_scope_node_ids(session, soldier_id, *, today=None) -> set[uuid.UUID]`. `is_commander`, `is_duty_manager`, `scope_root_ids`, `can_view_medical_document` now route through these.

- [ ] **Step 1: Write the failing tests**

Create `backend/app/services/tests/test_authz_deputies.py`:

```python
from __future__ import annotations

import uuid
from datetime import date, timedelta

from app.auth.authz import commanded_node_ids, dm_scope_node_ids, is_commander, is_duty_manager
from app.db.models import DutyManagerScope, RoleDeputy
from tests.helpers import create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_commanded_node_ids_includes_own_commanded_node(admin_session):
    cmd = create_soldier(admin_session, personal_number=f"a_{_uid()}", role="commander")
    node = create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=cmd.id)
    assert commanded_node_ids(admin_session, cmd.id) == {node.id}


def test_commanded_node_ids_includes_active_deputy_grant(admin_session):
    principal = create_soldier(admin_session, personal_number=f"b_{_uid()}", role="commander")
    node = create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"c_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today() - timedelta(days=1), end_date=date.today() + timedelta(days=1),
    ))
    admin_session.commit()

    assert commanded_node_ids(admin_session, deputy.id) == {node.id}
    assert is_commander(admin_session, deputy.id) is True


def test_commanded_node_ids_excludes_expired_deputy_grant(admin_session):
    principal = create_soldier(admin_session, personal_number=f"d_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"e_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today() - timedelta(days=10), end_date=date.today() - timedelta(days=1),
    ))
    admin_session.commit()

    assert commanded_node_ids(admin_session, deputy.id) == set()
    assert is_commander(admin_session, deputy.id) is False


def test_commanded_node_ids_excludes_future_deputy_grant(admin_session):
    principal = create_soldier(admin_session, personal_number=f"f_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"g_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=10),
    ))
    admin_session.commit()

    assert commanded_node_ids(admin_session, deputy.id) == set()


def test_dm_scope_node_ids_includes_active_deputy_grant(admin_session):
    principal = create_soldier(admin_session, personal_number=f"h_{_uid()}", role="duty_manager")
    node = create_node(admin_session, level="team", name=f"n_{_uid()}")
    admin_session.add(DutyManagerScope(duty_manager_id=principal.id, hierarchy_node_id=node.id))
    deputy = create_soldier(admin_session, personal_number=f"i_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="duty_manager",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    assert dm_scope_node_ids(admin_session, deputy.id) == {node.id}
    assert is_duty_manager(admin_session, deputy.id) is True


def test_commander_deputy_grant_does_not_grant_duty_manager_scope(admin_session):
    """role='commander' grants must not leak into dm_scope_node_ids, and vice versa."""
    principal = create_soldier(admin_session, personal_number=f"j_{_uid()}", role="commander")
    node = create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"k_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    assert commanded_node_ids(admin_session, deputy.id) == {node.id}
    assert dm_scope_node_ids(admin_session, deputy.id) == set()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest app/services/tests/test_authz_deputies.py -q`
Expected: FAIL — `ImportError: cannot import name 'commanded_node_ids'`.

- [ ] **Step 3: Add the two functions and refactor `is_commander`/`is_duty_manager`/`scope_root_ids`**

In `backend/app/auth/authz.py`, add `from datetime import date` to the imports (currently just `import uuid`), and add `RoleDeputy` to the `from app.db.models import ...` line. Then replace the three existing functions (`is_commander`, `is_duty_manager`, `scope_root_ids` — currently at lines 15-34 and 123-142) with:

```python
def _active_principal_ids(
    session: Session, *, deputy_id: uuid.UUID, role: str, today: date | None = None
) -> set[uuid.UUID]:
    """Principals `deputy_id` is currently (today) an active deputy for, in `role`."""
    today = today or date.today()
    return set(
        session.execute(
            select(RoleDeputy.principal_id).where(
                RoleDeputy.deputy_id == deputy_id,
                RoleDeputy.role == role,
                RoleDeputy.start_date <= today,
                RoleDeputy.end_date >= today,
            )
        ).scalars().all()
    )


def commanded_node_ids(
    session: Session, soldier_id: uuid.UUID, *, today: date | None = None
) -> set[uuid.UUID]:
    """Node ids this soldier commands directly, plus — via any active
    commander-role deputy grant — the commanded node ids of every principal
    they're currently deputizing for. Single source of truth: every other
    place in the codebase that needs "which nodes does X command" should
    call this instead of querying HierarchyNode.commander_id directly."""
    direct = set(
        session.execute(
            select(HierarchyNode.id).where(HierarchyNode.commander_id == soldier_id)
        ).scalars().all()
    )
    principal_ids = _active_principal_ids(session, deputy_id=soldier_id, role="commander", today=today)
    if principal_ids:
        direct.update(
            session.execute(
                select(HierarchyNode.id).where(HierarchyNode.commander_id.in_(principal_ids))
            ).scalars().all()
        )
    return direct


def dm_scope_node_ids(
    session: Session, soldier_id: uuid.UUID, *, today: date | None = None
) -> set[uuid.UUID]:
    """Node ids in this soldier's own DutyManagerScope, plus — via any active
    duty_manager-role deputy grant — the DM-scope node ids of every principal
    they're currently deputizing for. Single source of truth, mirroring
    commanded_node_ids above."""
    direct = set(
        session.execute(
            select(DutyManagerScope.hierarchy_node_id).where(
                DutyManagerScope.duty_manager_id == soldier_id
            )
        ).scalars().all()
    )
    principal_ids = _active_principal_ids(session, deputy_id=soldier_id, role="duty_manager", today=today)
    if principal_ids:
        direct.update(
            session.execute(
                select(DutyManagerScope.hierarchy_node_id).where(
                    DutyManagerScope.duty_manager_id.in_(principal_ids)
                )
            ).scalars().all()
        )
    return direct


def is_commander(session: Session, soldier_id: uuid.UUID) -> bool:
    """True iff this soldier currently commands at least one hierarchy node,
    directly or via an active commander-role deputy grant."""
    return bool(commanded_node_ids(session, soldier_id))


def is_duty_manager(session: Session, soldier_id: uuid.UUID) -> bool:
    """True iff this soldier currently holds at least one DutyManagerScope
    row, directly or via an active duty_manager-role deputy grant."""
    return bool(dm_scope_node_ids(session, soldier_id))
```

(`is_commander`/`is_duty_manager` no longer use `.limit(1)` — they now do a full scope computation, matching the cost profile `scope_root_ids` already had. This is an intentional simplicity-over-micro-optimization trade-off, consistent with the rest of this file.)

Now replace `scope_root_ids` (previously lines 123-142) with:

```python
def scope_root_ids(session: Session, user: Soldier) -> set[uuid.UUID]:
    """The node ids whose subtrees this user governs — directly, or via an
    active deputy grant for someone who does."""
    return dm_scope_node_ids(session, user.id) | commanded_node_ids(session, user.id)
```

- [ ] **Step 4: Refactor `can_view_medical_document`**

In the same file, `can_view_medical_document` (around what was line 214-265) has two inline queries — replace them:

```python
    if is_commander(session, viewer.id):
        commander_roots = commanded_node_ids(session, viewer.id)
        required_level = _min_level("exemptions.medical_doc_min_commander_level", "מדור")
        if dm_scope_covers_target(
            session, scope_root_ids=commander_roots, target_node=node, required_level_key=required_level
        ):
            return True
    if is_duty_manager(session, viewer.id):
        dm_roots = dm_scope_node_ids(session, viewer.id)
        required_level = _min_level("exemptions.medical_doc_min_duty_manager_level", "מרכז")
        if dm_scope_covers_target(
            session, scope_root_ids=dm_roots, target_node=node, required_level_key=required_level
        ):
            return True
    return False
```

(This replaces the two `session.execute(select(HierarchyNode.id).where(HierarchyNode.commander_id == viewer.id))...` / `select(DutyManagerScope.hierarchy_node_id).where(DutyManagerScope.duty_manager_id == viewer.id))...` blocks with calls to the new functions — same logic, now deputy-aware.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest app/services/tests/test_authz_deputies.py -q`
Expected: 6 passed.

- [ ] **Step 6: Run the full fast suite**

Run: `pytest -q`
Expected: all pass — this is the highest-risk step in the whole plan, since `is_commander`/`is_duty_manager`/`scope_root_ids` are used everywhere. If anything fails, read the failure carefully before changing anything else; it likely means some caller depended on the old `.limit(1)` short-circuit behavior or an edge case in the query shape.

- [ ] **Step 7: Commit**

```bash
git add backend/app/auth/authz.py backend/app/services/tests/test_authz_deputies.py
git commit -m "feat: make is_commander/is_duty_manager/scope_root_ids deputy-aware"
```

---

## Task 3: Refactor `services/authority.py` onto the shared lookups

**Files:**
- Modify: `backend/app/services/authority.py`
- Test: `backend/app/services/tests/test_authority.py` (extend existing file)

**Interfaces:**
- Consumes: `commanded_node_ids`, `dm_scope_node_ids` (Task 2).
- Produces: `_commanded_nodes`, `_dm_scope_nodes` (unchanged signatures, now deputy-aware) — everything else in this file that calls them, or is refactored to call them, inherits deputy-awareness.

- [ ] **Step 1: Write the failing tests**

Add to the end of `backend/app/services/tests/test_authority.py` (it already imports `create_node`, `create_soldier` from `tests.helpers`, and the functions under test — add `RoleDeputy` to the `app.db.models` import line, and `from datetime import date, timedelta` alongside the existing `import uuid`):

```python
def test_rank_advancement_edit_authorized_extends_to_active_commander_deputy(admin_session):
    principal = create_soldier(admin_session, personal_number=f"ra1_{uuid.uuid4().hex[:8]}", role="commander")
    node = create_node(admin_session, level="group", name=f"n_{uuid.uuid4().hex[:8]}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"ra2_{uuid.uuid4().hex[:8]}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    assert rank_advancement_edit_authorized(admin_session, user=deputy, target_node=node) is True


def test_commander_can_grant_commander_exemption_extends_to_active_deputy(admin_session):
    from app.services.settings_loader import set_setting
    set_setting(admin_session, "exemptions.commander_exemption_min_level", "group", actor_id=None)
    admin_session.commit()
    principal = create_soldier(admin_session, personal_number=f"ce1_{uuid.uuid4().hex[:8]}", role="commander")
    create_node(admin_session, level="group", name=f"n_{uuid.uuid4().hex[:8]}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"ce2_{uuid.uuid4().hex[:8]}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    assert commander_can_grant_commander_exemption(admin_session, commander_id=deputy.id) is True


def test_commander_delete_soldier_authorized_extends_to_active_deputy(admin_session):
    from app.services.settings_loader import set_setting
    set_setting(admin_session, "soldiers.commander_delete_min_level", "group", actor_id=None)
    admin_session.commit()
    principal = create_soldier(admin_session, personal_number=f"cd1_{uuid.uuid4().hex[:8]}", role="commander")
    node = create_node(admin_session, level="group", name=f"n_{uuid.uuid4().hex[:8]}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"cd2_{uuid.uuid4().hex[:8]}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    assert commander_delete_soldier_authorized(admin_session, user=deputy, target_node=node) is True
    assert has_any_commander_delete_scope(admin_session, user=deputy) is True


def test_range_attendance_edit_authorized_extends_to_active_dm_deputy(admin_session):
    from app.services.settings_loader import set_setting
    set_setting(admin_session, "mitvachim.attendance_edit_min_level", "group", actor_id=None)
    admin_session.commit()
    principal = create_soldier(admin_session, personal_number=f"rae1_{uuid.uuid4().hex[:8]}", role="duty_manager")
    node = create_node(admin_session, level="group", name=f"n_{uuid.uuid4().hex[:8]}")
    admin_session.add(DutyManagerScope(duty_manager_id=principal.id, hierarchy_node_id=node.id))
    deputy = create_soldier(admin_session, personal_number=f"rae2_{uuid.uuid4().hex[:8]}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="duty_manager",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    assert range_attendance_edit_authorized(admin_session, user=deputy, target_node=node) is True


def test_can_view_soldier_scope_extends_to_active_commander_deputy(admin_session):
    principal = create_soldier(admin_session, personal_number=f"cv1_{uuid.uuid4().hex[:8]}", role="commander")
    node = create_node(admin_session, level="group", name=f"n_{uuid.uuid4().hex[:8]}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"cv2_{uuid.uuid4().hex[:8]}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    assert can_view_soldier_scope(admin_session, deputy, node) is True
    assert has_any_visibility(admin_session, deputy) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest app/services/tests/test_authority.py -k "extends_to_active" -q`
Expected: 5 FAIL (all currently return `False`, since deputy grants don't affect anything yet in this file).

- [ ] **Step 3: Refactor `_commanded_nodes` and `_dm_scope_nodes`**

In `backend/app/services/authority.py`, replace the two functions (around lines 324-340):

```python
def _commanded_nodes(session: Session, soldier_id: uuid.UUID) -> list[HierarchyNode]:
    from app.auth.authz import commanded_node_ids
    ids = commanded_node_ids(session, soldier_id)
    if not ids:
        return []
    return list(
        session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(ids))).scalars().all()
    )


def _dm_scope_nodes(session: Session, soldier_id: uuid.UUID) -> list[HierarchyNode]:
    from app.auth.authz import dm_scope_node_ids
    ids = dm_scope_node_ids(session, soldier_id)
    if not ids:
        return []
    return list(
        session.execute(select(HierarchyNode).where(HierarchyNode.id.in_(ids))).scalars().all()
    )
```

(`can_view_soldier_scope` and `has_any_visibility` already call `_commanded_nodes`/`_dm_scope_nodes`, so they're now deputy-aware with no further changes.)

- [ ] **Step 4: Refactor `rank_advancement_edit_authorized`**

Replace its body (the two inline `session.execute(select(...))` blocks, around lines 74-92):

```python
    commander_root_ids = _commanded_node_ids_only(session, user.id)
    if dm_scope_covers_target(
        session, scope_root_ids=commander_root_ids, target_node=target_node, required_level_key="מדור",
    ):
        return True
    duty_manager_root_ids = _dm_scope_node_ids_only(session, user.id)
    return dm_scope_covers_target(
        session, scope_root_ids=duty_manager_root_ids, target_node=target_node, required_level_key="מדור",
    )
```

Add these two tiny wrappers right above `rank_advancement_edit_authorized` (they exist purely so the rest of this file — which imports `authority` names, not `authz` names, in several places — reads consistently; they just forward to `authz`):

```python
def _commanded_node_ids_only(session: Session, soldier_id: uuid.UUID) -> set[uuid.UUID]:
    from app.auth.authz import commanded_node_ids
    return commanded_node_ids(session, soldier_id)


def _dm_scope_node_ids_only(session: Session, soldier_id: uuid.UUID) -> set[uuid.UUID]:
    from app.auth.authz import dm_scope_node_ids
    return dm_scope_node_ids(session, soldier_id)
```

- [ ] **Step 5: Refactor `RankAdvancementEditScope.__init__`**

Replace the two inline query blocks (around lines 121-132):

```python
        commander_root_ids = _commanded_node_ids_only(session, user.id)
        duty_manager_root_ids = _dm_scope_node_ids_only(session, user.id)
```

- [ ] **Step 6: Refactor `range_attendance_edit_authorized`**

Replace the inline query (around lines 174-177):

```python
    dm_root_ids = _dm_scope_node_ids_only(session, user.id)
```

(delete the now-unused `dm_scope_rows = session.execute(...)` line entirely.)

- [ ] **Step 7: Refactor `commander_can_grant_commander_exemption`**

Replace the inline query (around line 192-194):

```python
    commanded_nodes = _commanded_nodes(session, commander_id)
```

- [ ] **Step 8: Refactor `duty_manager_exemption_immediate_apply_authorized`**

Replace the inline query (around lines 228-233):

```python
    dm_root_ids = _dm_scope_node_ids_only(session, user.id)
```

- [ ] **Step 9: Refactor `commander_delete_soldier_authorized` and `has_any_commander_delete_scope`**

Replace the inline query in `commander_delete_soldier_authorized` (around lines 279-283):

```python
    commander_root_ids = _commanded_node_ids_only(session, user.id)
```

Replace the inline query in `has_any_commander_delete_scope` (around lines 300-302):

```python
    commanded_nodes = _commanded_nodes(session, user.id)
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `pytest app/services/tests/test_authority.py -q`
Expected: all pass, including the 5 new ones.

- [ ] **Step 11: Run the full fast suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 12: Commit**

```bash
git add backend/app/services/authority.py backend/app/services/tests/test_authority.py
git commit -m "feat: route authority.py's scope lookups through deputy-aware authz functions"
```

---

## Task 4: Refactor the remaining direct-query call sites

**Files:**
- Modify: `backend/app/routes/commander_dashboard.py`
- Modify: `backend/app/routes/range_qualification_visibility.py`
- Modify: `backend/app/routes/exemption_requests.py`
- Modify: `backend/app/services/hierarchy_transfers.py`
- Test: `backend/tests/integration/test_soldiers_api.py` (extend), `backend/app/services/tests/test_hierarchy_transfers.py` (extend if it exists, else create), `backend/tests/integration/test_range_qualification_visibility.py` (extend if it exists)

**Interfaces:**
- Consumes: `commanded_node_ids`, `dm_scope_node_ids` (Task 2).

- [ ] **Step 1: Refactor `commander_dashboard.py`'s `_commander_node`**

In `backend/app/routes/commander_dashboard.py`, replace `_commander_node` (around lines 113-116):

```python
def _commander_node(session: Session, user: Soldier) -> uuid.UUID | None:
    from app.auth.authz import commanded_node_ids
    ids = commanded_node_ids(session, user.id)
    # The dashboard is built around a single "my command post" view. A
    # soldier who both commands their own node and is an active deputy for
    # another commander could have more than one id here — pick
    # deterministically (smallest UUID) rather than by arbitrary set order.
    return min(ids) if ids else None
```

- [ ] **Step 2: Write a test proving a deputy can reach the commander dashboard**

Add this test to `backend/app/routes/tests/test_commander_dashboard.py` (it already has route-level tests using the `client`/`admin_session` fixtures with locally-scoped imports — e.g. `test_upcoming_route_includes_status_field_for_draft` — so match that existing style):

```python
def test_active_commander_deputy_can_reach_dashboard(client, admin_session):
    import uuid
    from datetime import date
    from app.db.models import RoleDeputy
    from tests.helpers import auth_headers, create_node, create_soldier

    principal = create_soldier(admin_session, personal_number=f"cdash1_{uuid.uuid4().hex[:8]}", role="commander")
    create_node(admin_session, level="group", name=f"n_{uuid.uuid4().hex[:8]}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"cdash2_{uuid.uuid4().hex[:8]}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    r = client.get("/api/command-dashboard/summary", headers=auth_headers(deputy))
    assert r.status_code == 200, r.text
```

- [ ] **Step 3: Refactor `range_qualification_visibility.py`'s `_resolve_roots`**

In `backend/app/routes/range_qualification_visibility.py`, replace `_resolve_roots` (around lines 100-123):

```python
def _resolve_roots(session: Session, *, user: Soldier, audience: Audience) -> set[uuid.UUID] | None:
    if user.role == "admin":
        return None

    from app.auth.authz import commanded_node_ids, dm_scope_node_ids

    if audience == "planning":
        if not is_duty_manager(session, user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        return dm_scope_node_ids(session, user.id)

    if not is_commander(session, user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return commanded_node_ids(session, user.id)
```

- [ ] **Step 4: Refactor `exemption_requests.py`'s inline DM-scope lookup**

In `backend/app/routes/exemption_requests.py`, replace the inline query (around lines 267-271):

```python
    from app.auth.authz import dm_scope_node_ids
    user_dm_node_ids = dm_scope_node_ids(session, user.id)
```

- [ ] **Step 5: Refactor `hierarchy_transfers.py`'s `list_pending_for_approver`**

In `backend/app/services/hierarchy_transfers.py`, replace the body (around lines 129-137):

```python
def list_pending_for_approver(session: Session, *, approver_id: uuid.UUID) -> list[HierarchyTransferRequest]:
    from app.auth.authz import commanded_node_ids, dm_scope_node_ids
    root_ids = commanded_node_ids(session, approver_id) | dm_scope_node_ids(session, approver_id)
    if not root_ids:
        return []
```

(the unused `from app.db.models import DutyManagerScope, HierarchyNode` import on the line above can be removed if nothing else in this function still needs those names — check the rest of the function body before deleting it.)

- [ ] **Step 6: Write a test proving a deputy sees pending transfer requests**

Add this test to `backend/tests/unit/test_hierarchy_transfers.py` (it already has `create_request`/`list_pending_for_approver`-style tests using `admin_session` with locally-scoped imports — match that style; note the real signature is `create_request(session, soldier_id=..., to_node_id=..., requested_by=...)`, confirmed from this file's existing `test_create_request_does_not_move_soldier_immediately`):

```python
def test_list_pending_for_approver_includes_active_deputy(admin_session):
    import uuid
    from datetime import date
    from app.db.models import RoleDeputy
    from app.services.hierarchy_transfers import create_request, list_pending_for_approver
    from tests.helpers import create_node, create_soldier

    dest = create_node(admin_session, level="group", name=f"dest_{uuid.uuid4().hex[:8]}")
    principal = create_soldier(admin_session, personal_number=f"ht1_{uuid.uuid4().hex[:8]}", role="commander")
    dest.commander_id = principal.id
    admin_session.commit()
    deputy = create_soldier(admin_session, personal_number=f"ht2_{uuid.uuid4().hex[:8]}")
    admin_session.add(RoleDeputy(
        principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(),
    ))
    soldier = create_soldier(admin_session, personal_number=f"ht3_{uuid.uuid4().hex[:8]}")
    admin_session.commit()

    create_request(admin_session, soldier_id=soldier.id, to_node_id=dest.id, requested_by=soldier.id)

    pending = list_pending_for_approver(admin_session, approver_id=deputy.id)
    assert len(pending) == 1
```

- [ ] **Step 7: Run the affected test files**

Run: `pytest tests/unit/test_hierarchy_transfers.py app/services/tests/test_authority.py app/routes/tests/test_commander_dashboard.py -q`
Expected: all pass.

- [ ] **Step 8: Run the full fast suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add backend/app/routes/commander_dashboard.py backend/app/routes/range_qualification_visibility.py backend/app/routes/exemption_requests.py backend/app/services/hierarchy_transfers.py backend/tests
git commit -m "feat: extend commander dashboard, range visibility, exemption, and transfer scope checks to active deputies"
```

---

## Task 5: `services/deputies.py` — create/list/revoke

**Files:**
- Create: `backend/app/services/deputies.py`
- Test: `backend/app/services/tests/test_deputies.py`

**Interfaces:**
- Consumes: `is_commander`, `is_duty_manager` (Task 2, already deputy-aware).
- Produces: `DeputyError(Exception)`; `create_deputy(session, *, principal_id, deputy_id, role, start_date, end_date, actor_id) -> RoleDeputy`; `list_deputies(session, *, principal_id) -> list[RoleDeputy]`; `list_active_deputies_for(session, *, deputy_id, today=None) -> list[RoleDeputy]`; `revoke_deputy(session, *, deputy_grant_id, actor_id) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `backend/app/services/tests/test_deputies.py`:

```python
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.db.models import RoleDeputy
from app.services.deputies import (
    DeputyError,
    create_deputy,
    list_active_deputies_for,
    list_deputies,
    revoke_deputy,
)
from tests.helpers import create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_create_deputy_for_a_real_commander_succeeds(admin_session):
    principal = create_soldier(admin_session, personal_number=f"a_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"b_{_uid()}")

    entry = create_deputy(
        admin_session, principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today() + timedelta(days=7), actor_id=principal.id,
    )
    admin_session.commit()

    assert entry.principal_id == principal.id
    assert entry.deputy_id == deputy.id
    assert entry.role == "commander"


def test_create_deputy_rejects_principal_who_lacks_the_role(admin_session):
    principal = create_soldier(admin_session, personal_number=f"c_{_uid()}")  # plain soldier
    deputy = create_soldier(admin_session, personal_number=f"d_{_uid()}")

    with pytest.raises(DeputyError, match="principal_lacks_role"):
        create_deputy(
            admin_session, principal_id=principal.id, deputy_id=deputy.id, role="commander",
            start_date=date.today(), end_date=date.today(), actor_id=principal.id,
        )


def test_create_deputy_rejects_end_before_start(admin_session):
    principal = create_soldier(admin_session, personal_number=f"e_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"f_{_uid()}")

    with pytest.raises(DeputyError, match="invalid_date_range"):
        create_deputy(
            admin_session, principal_id=principal.id, deputy_id=deputy.id, role="commander",
            start_date=date.today() + timedelta(days=1), end_date=date.today(), actor_id=principal.id,
        )


def test_create_deputy_rejects_self_deputizing(admin_session):
    principal = create_soldier(admin_session, personal_number=f"g_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)

    with pytest.raises(DeputyError, match="cannot_deputize_self"):
        create_deputy(
            admin_session, principal_id=principal.id, deputy_id=principal.id, role="commander",
            start_date=date.today(), end_date=date.today(), actor_id=principal.id,
        )


def test_create_deputy_rejects_recursion(admin_session):
    """A soldier who is themselves currently an active deputy for `role`
    cannot be named as a principal for a new deputy grant (no sub-deputies)."""
    grandparent = create_soldier(admin_session, personal_number=f"h_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=grandparent.id)
    parent = create_soldier(admin_session, personal_number=f"i_{_uid()}")
    create_deputy(
        admin_session, principal_id=grandparent.id, deputy_id=parent.id, role="commander",
        start_date=date.today(), end_date=date.today() + timedelta(days=10), actor_id=grandparent.id,
    )
    admin_session.commit()
    child = create_soldier(admin_session, personal_number=f"j_{_uid()}")

    with pytest.raises(DeputyError, match="cannot_deputize_a_deputy"):
        create_deputy(
            admin_session, principal_id=parent.id, deputy_id=child.id, role="commander",
            start_date=date.today(), end_date=date.today(), actor_id=grandparent.id,
        )


def test_create_deputy_allows_one_deputy_for_multiple_principals(admin_session):
    p1 = create_soldier(admin_session, personal_number=f"k_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n1_{_uid()}", commander_id=p1.id)
    p2 = create_soldier(admin_session, personal_number=f"l_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n2_{_uid()}", commander_id=p2.id)
    deputy = create_soldier(admin_session, personal_number=f"m_{_uid()}")

    create_deputy(
        admin_session, principal_id=p1.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(), actor_id=p1.id,
    )
    admin_session.commit()
    entry2 = create_deputy(
        admin_session, principal_id=p2.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(), actor_id=p2.id,
    )
    admin_session.commit()

    assert entry2.principal_id == p2.id


def test_list_deputies_returns_all_grants_for_a_principal(admin_session):
    principal = create_soldier(admin_session, personal_number=f"n_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    d1 = create_soldier(admin_session, personal_number=f"o_{_uid()}")
    d2 = create_soldier(admin_session, personal_number=f"p_{_uid()}")
    create_deputy(
        admin_session, principal_id=principal.id, deputy_id=d1.id, role="commander",
        start_date=date.today(), end_date=date.today(), actor_id=principal.id,
    )
    create_deputy(
        admin_session, principal_id=principal.id, deputy_id=d2.id, role="commander",
        start_date=date.today() + timedelta(days=30), end_date=date.today() + timedelta(days=37),
        actor_id=principal.id,
    )
    admin_session.commit()

    grants = list_deputies(admin_session, principal_id=principal.id)
    assert {g.deputy_id for g in grants} == {d1.id, d2.id}


def test_list_active_deputies_for_only_returns_currently_active_grants(admin_session):
    principal = create_soldier(admin_session, personal_number=f"q_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"r_{_uid()}")
    create_deputy(
        admin_session, principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=10),
        actor_id=principal.id,
    )
    admin_session.commit()

    assert list_active_deputies_for(admin_session, deputy_id=deputy.id) == []
    assert len(list_active_deputies_for(
        admin_session, deputy_id=deputy.id, today=date.today() + timedelta(days=7)
    )) == 1


def test_revoke_deputy_deletes_the_grant(admin_session):
    principal = create_soldier(admin_session, personal_number=f"s_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"t_{_uid()}")
    entry = create_deputy(
        admin_session, principal_id=principal.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(), actor_id=principal.id,
    )
    admin_session.commit()

    revoke_deputy(admin_session, deputy_grant_id=entry.id, actor_id=principal.id)
    admin_session.commit()

    assert admin_session.get(RoleDeputy, entry.id) is None


def test_revoke_deputy_raises_for_unknown_grant(admin_session):
    with pytest.raises(DeputyError, match="deputy_grant_not_found"):
        revoke_deputy(admin_session, deputy_grant_id=uuid.uuid4(), actor_id=None)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest app/services/tests/test_deputies.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.deputies'`.

- [ ] **Step 3: Write the service**

Create `backend/app/services/deputies.py`:

```python
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.auth.authz import is_commander, is_duty_manager
from app.db.models import RoleDeputy, Soldier


class DeputyError(Exception):
    pass


def _is_active_deputy(
    session: Session, *, soldier_id: uuid.UUID, role: str, window_start: date, window_end: date
) -> bool:
    """True iff `soldier_id` already has a RoleDeputy row (as the deputy) for
    `role` overlapping [window_start, window_end] — used to block naming a
    current deputy as someone else's principal (no recursion)."""
    return session.execute(
        select(RoleDeputy.id).where(
            RoleDeputy.deputy_id == soldier_id,
            RoleDeputy.role == role,
            RoleDeputy.start_date <= window_end,
            RoleDeputy.end_date >= window_start,
        ).limit(1)
    ).first() is not None


def create_deputy(
    session: Session,
    *,
    principal_id: uuid.UUID,
    deputy_id: uuid.UUID,
    role: str,
    start_date: date,
    end_date: date,
    actor_id: uuid.UUID | None,
) -> RoleDeputy:
    if role not in ("commander", "duty_manager"):
        raise DeputyError("invalid_role")
    if end_date < start_date:
        raise DeputyError("invalid_date_range")
    if principal_id == deputy_id:
        raise DeputyError("cannot_deputize_self")
    if session.get(Soldier, principal_id) is None:
        raise DeputyError("principal_not_found")
    if session.get(Soldier, deputy_id) is None:
        raise DeputyError("deputy_not_found")

    holds_role = is_commander(session, principal_id) if role == "commander" else is_duty_manager(session, principal_id)
    if not holds_role:
        raise DeputyError("principal_lacks_role")

    # No recursion: reject if the *principal* is themselves currently (for
    # any part of this window) someone else's active deputy for this role.
    if _is_active_deputy(session, soldier_id=principal_id, role=role, window_start=start_date, window_end=end_date):
        raise DeputyError("cannot_deputize_a_deputy")

    existing = session.execute(
        select(RoleDeputy).where(
            RoleDeputy.principal_id == principal_id,
            RoleDeputy.deputy_id == deputy_id,
            RoleDeputy.role == role,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise DeputyError("already_exists")

    entry = RoleDeputy(
        principal_id=principal_id, deputy_id=deputy_id, role=role,
        start_date=start_date, end_date=end_date, created_by=actor_id,
    )
    session.add(entry)
    session.flush()
    write_audit(
        session, actor_id=actor_id, action="deputy.create", entity_type="role_deputy",
        entity_id=entry.id,
        after={
            "principal_id": str(principal_id), "deputy_id": str(deputy_id), "role": role,
            "start_date": start_date.isoformat(), "end_date": end_date.isoformat(),
        },
    )
    return entry


def list_deputies(session: Session, *, principal_id: uuid.UUID) -> list[RoleDeputy]:
    return list(
        session.execute(
            select(RoleDeputy)
            .where(RoleDeputy.principal_id == principal_id)
            .order_by(RoleDeputy.start_date.desc())
        ).scalars().all()
    )


def list_active_deputies_for(
    session: Session, *, deputy_id: uuid.UUID, today: date | None = None
) -> list[RoleDeputy]:
    """Grants where `deputy_id` is currently acting as someone's deputy."""
    today = today or date.today()
    return list(
        session.execute(
            select(RoleDeputy).where(
                RoleDeputy.deputy_id == deputy_id,
                RoleDeputy.start_date <= today,
                RoleDeputy.end_date >= today,
            )
        ).scalars().all()
    )


def revoke_deputy(session: Session, *, deputy_grant_id: uuid.UUID, actor_id: uuid.UUID | None) -> None:
    entry = session.get(RoleDeputy, deputy_grant_id)
    if entry is None:
        raise DeputyError("deputy_grant_not_found")
    before = {
        "principal_id": str(entry.principal_id), "deputy_id": str(entry.deputy_id), "role": entry.role,
    }
    session.delete(entry)
    session.flush()
    write_audit(
        session, actor_id=actor_id, action="deputy.revoke", entity_type="role_deputy",
        entity_id=deputy_grant_id, before=before,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest app/services/tests/test_deputies.py -q`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/deputies.py backend/app/services/tests/test_deputies.py
git commit -m "feat: add deputies service (create/list/revoke deputy grants)"
```

---

## Task 6: `routes/deputies.py` — API endpoints

**Files:**
- Create: `backend/app/routes/deputies.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/integration/test_deputies_api.py`

**Interfaces:**
- Consumes: `svc.create_deputy`, `svc.list_deputies`, `svc.revoke_deputy`, `svc.DeputyError` (Task 5).
- Produces: `POST /api/deputies`, `GET /api/deputies?principal_id=...`, `DELETE /api/deputies/{id}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_deputies_api.py`:

```python
from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_principal_can_create_and_list_their_own_deputy(client: TestClient, admin_session: Session):
    principal = create_soldier(admin_session, personal_number=f"a_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"b_{_uid()}")
    admin_session.commit()

    r = client.post(
        "/api/deputies", headers=auth_headers(principal),
        json={
            "principal_id": str(principal.id), "deputy_id": str(deputy.id), "role": "commander",
            "start_date": str(date.today()), "end_date": str(date.today() + timedelta(days=7)),
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["deputy_id"] == str(deputy.id)
    assert body["deputy_name"] == deputy.full_name

    r2 = client.get(f"/api/deputies?principal_id={principal.id}", headers=auth_headers(principal))
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_other_soldier_cannot_create_a_deputy_for_someone_else(client: TestClient, admin_session: Session):
    principal = create_soldier(admin_session, personal_number=f"c_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"d_{_uid()}")
    other = create_soldier(admin_session, personal_number=f"e_{_uid()}")
    admin_session.commit()

    r = client.post(
        "/api/deputies", headers=auth_headers(other),
        json={
            "principal_id": str(principal.id), "deputy_id": str(deputy.id), "role": "commander",
            "start_date": str(date.today()), "end_date": str(date.today()),
        },
    )
    assert r.status_code == 403


def test_admin_can_create_a_deputy_for_someone_else(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number=f"f_{_uid()}", role="admin")
    principal = create_soldier(admin_session, personal_number=f"g_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"h_{_uid()}")
    admin_session.commit()

    r = client.post(
        "/api/deputies", headers=auth_headers(admin),
        json={
            "principal_id": str(principal.id), "deputy_id": str(deputy.id), "role": "commander",
            "start_date": str(date.today()), "end_date": str(date.today()),
        },
    )
    assert r.status_code == 201, r.text


def test_create_deputy_for_a_non_commander_returns_400(client: TestClient, admin_session: Session):
    principal = create_soldier(admin_session, personal_number=f"i_{_uid()}")  # plain soldier
    deputy = create_soldier(admin_session, personal_number=f"j_{_uid()}")
    admin_session.commit()

    r = client.post(
        "/api/deputies", headers=auth_headers(principal),
        json={
            "principal_id": str(principal.id), "deputy_id": str(deputy.id), "role": "commander",
            "start_date": str(date.today()), "end_date": str(date.today()),
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "principal_lacks_role"


def test_principal_can_revoke_their_own_deputy(client: TestClient, admin_session: Session):
    principal = create_soldier(admin_session, personal_number=f"k_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"l_{_uid()}")
    admin_session.commit()

    created = client.post(
        "/api/deputies", headers=auth_headers(principal),
        json={
            "principal_id": str(principal.id), "deputy_id": str(deputy.id), "role": "commander",
            "start_date": str(date.today()), "end_date": str(date.today()),
        },
    ).json()

    r = client.delete(f"/api/deputies/{created['id']}", headers=auth_headers(principal))
    assert r.status_code == 200

    r2 = client.get(f"/api/deputies?principal_id={principal.id}", headers=auth_headers(principal))
    assert r2.json() == []


def test_other_soldier_cannot_revoke_someone_elses_deputy(client: TestClient, admin_session: Session):
    principal = create_soldier(admin_session, personal_number=f"m_{_uid()}", role="commander")
    create_node(admin_session, level="team", name=f"n_{_uid()}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"n_{_uid()}")
    other = create_soldier(admin_session, personal_number=f"o_{_uid()}")
    admin_session.commit()

    created = client.post(
        "/api/deputies", headers=auth_headers(principal),
        json={
            "principal_id": str(principal.id), "deputy_id": str(deputy.id), "role": "commander",
            "start_date": str(date.today()), "end_date": str(date.today()),
        },
    ).json()

    r = client.delete(f"/api/deputies/{created['id']}", headers=auth_headers(other))
    assert r.status_code == 403
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/integration/test_deputies_api.py -q`
Expected: FAIL — 404s, since the route doesn't exist yet.

- [ ] **Step 3: Write the routes**

Create `backend/app/routes/deputies.py`:

```python
from __future__ import annotations

import uuid
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import require_password_changed
from app.db.models import RoleDeputy, Soldier
from app.db.session import get_session
from app.services import deputies as svc

router = APIRouter(prefix="/deputies", tags=["deputies"])


class CreateDeputyRequest(BaseModel):
    principal_id: uuid.UUID
    deputy_id: uuid.UUID
    role: str
    start_date: date_type
    end_date: date_type


class DeputyOut(BaseModel):
    id: uuid.UUID
    principal_id: uuid.UUID
    principal_name: str
    deputy_id: uuid.UUID
    deputy_name: str
    role: str
    start_date: date_type
    end_date: date_type


def _out(session: Session, entry: RoleDeputy) -> DeputyOut:
    principal = session.get(Soldier, entry.principal_id)
    deputy = session.get(Soldier, entry.deputy_id)
    return DeputyOut(
        id=entry.id,
        principal_id=entry.principal_id,
        principal_name=principal.full_name if principal else "",
        deputy_id=entry.deputy_id,
        deputy_name=deputy.full_name if deputy else "",
        role=entry.role,
        start_date=entry.start_date,
        end_date=entry.end_date,
    )


def _assert_self_or_admin(user: Soldier, principal_id: uuid.UUID) -> None:
    if user.role != "admin" and user.id != principal_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


@router.post("", response_model=DeputyOut, status_code=status.HTTP_201_CREATED)
def create_deputy(
    body: CreateDeputyRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> DeputyOut:
    _assert_self_or_admin(user, body.principal_id)
    try:
        entry = svc.create_deputy(
            session,
            principal_id=body.principal_id,
            deputy_id=body.deputy_id,
            role=body.role,
            start_date=body.start_date,
            end_date=body.end_date,
            actor_id=user.id,
        )
        session.commit()
        return _out(session, entry)
    except svc.DeputyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("", response_model=list[DeputyOut])
def list_deputies(
    principal_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[DeputyOut]:
    _assert_self_or_admin(user, principal_id)
    entries = svc.list_deputies(session, principal_id=principal_id)
    return [_out(session, e) for e in entries]


@router.delete("/{deputy_grant_id}", status_code=status.HTTP_200_OK)
def revoke_deputy(
    deputy_grant_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    entry = session.get(RoleDeputy, deputy_grant_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    _assert_self_or_admin(user, entry.principal_id)
    try:
        svc.revoke_deputy(session, deputy_grant_id=deputy_grant_id, actor_id=user.id)
        session.commit()
        return {"status": "ok"}
    except svc.DeputyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, add the import near the other route imports (find the line `from app.routes import dm_scope as dm_scope_routes` and add right after it):

```python
from app.routes import deputies as deputy_routes
```

Then add the registration line right after `app.include_router(dm_scope_routes.router, prefix="/api")`:

```python
    app.include_router(deputy_routes.router, prefix="/api")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/integration/test_deputies_api.py -q`
Expected: 6 passed.

- [ ] **Step 6: Run the full fast suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/deputies.py backend/app/main.py backend/tests/integration/test_deputies_api.py
git commit -m "feat: add deputy assignment API (create/list/revoke)"
```

---

## Task 7: Expose active deputy grants on `/me`

**Files:**
- Modify: `backend/app/routes/me.py`
- Test: `backend/tests/integration/test_me_api.py` (extend if it exists, else create as `backend/tests/integration/test_me_deputies.py`)

**Interfaces:**
- Consumes: `list_active_deputies_for` (Task 5).
- Produces: `MeResponse.active_deputy_grants: list[ActiveDeputyGrantOut]`, each with `principal_id, principal_name, role, end_date`.

- [ ] **Step 1: Write the failing test**

Check whether `backend/tests/integration/test_me_api.py` exists (`grep -rl "class.*MeResponse\|/api/me\b" backend/tests`); if it does, add this test there matching its existing import style, otherwise create `backend/tests/integration/test_me_deputies.py`:

```python
from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_me_includes_active_deputy_grants(client: TestClient, admin_session: Session):
    principal = create_soldier(admin_session, personal_number=f"a_{uuid.uuid4().hex[:8]}", role="commander")
    create_node(admin_session, level="team", name=f"n_{uuid.uuid4().hex[:8]}", commander_id=principal.id)
    deputy = create_soldier(admin_session, personal_number=f"b_{uuid.uuid4().hex[:8]}")
    admin_session.commit()

    client.post(
        "/api/deputies", headers=auth_headers(principal),
        json={
            "principal_id": str(principal.id), "deputy_id": str(deputy.id), "role": "commander",
            "start_date": str(date.today()), "end_date": str(date.today() + timedelta(days=3)),
        },
    )

    r = client.get("/api/me", headers=auth_headers(deputy))
    assert r.status_code == 200
    grants = r.json()["active_deputy_grants"]
    assert len(grants) == 1
    assert grants[0]["principal_id"] == str(principal.id)
    assert grants[0]["role"] == "commander"
    assert r.json()["is_commander"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/integration/test_me_deputies.py -q` (adjust path if you added to an existing file)
Expected: FAIL — `KeyError: 'active_deputy_grants'`.

- [ ] **Step 3: Extend `MeResponse` and the `me` handler**

In `backend/app/routes/me.py`, add the import (alongside the existing `from app.services.authority import (...)` block, add a new line):

```python
from app.services.deputies import list_active_deputies_for
```

Add a new response model right above `class MeResponse`:

```python
class ActiveDeputyGrantOut(BaseModel):
    principal_id: uuid.UUID
    principal_name: str
    role: str
    end_date: str
```

Add a field to `MeResponse` (right after `can_apply_commander_exemption_immediately: bool = False`):

```python
    active_deputy_grants: list[ActiveDeputyGrantOut] = []
```

In the `me()` handler, right before the `return MeResponse(...)` call, add:

```python
    active_grants = list_active_deputies_for(session, deputy_id=user.id)
    active_deputy_grants = []
    for g in active_grants:
        g_principal = session.get(Soldier, g.principal_id)
        active_deputy_grants.append(ActiveDeputyGrantOut(
            principal_id=g.principal_id,
            principal_name=g_principal.full_name if g_principal else "",
            role=g.role,
            end_date=str(g.end_date),
        ))
```

And add `active_deputy_grants=active_deputy_grants,` as a new keyword argument in the `MeResponse(...)` call (anywhere in the argument list — order doesn't matter for keyword arguments).

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/integration/test_me_deputies.py -q`
Expected: 1 passed.

- [ ] **Step 5: Run the full fast suite**

Run: `pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/me.py backend/tests/integration/test_me_deputies.py
git commit -m "feat: expose active deputy grants on GET /me"
```

---

## Task 8: Extend notification cascades to active deputies

**Files:**
- Modify: `backend/app/services/notifications.py`
- Test: `backend/app/services/tests/test_notifications_dm.py` (extend if it covers `notify_duty_managers_in_scope`/`cascade_to_commanders`, else create `backend/app/services/tests/test_notifications_deputies.py`)

**Interfaces:**
- Consumes: `RoleDeputy` (Task 1).
- Produces: `_active_deputy_ids(session, *, principal_id, role, today=None) -> set[uuid.UUID]` (private helper); `cascade_to_commanders`, `notify_duty_managers_in_scope`, `notify_duty_managers_of_request`, `notify_enrollment_received` now also notify active deputies.

- [ ] **Step 1: Write the failing tests**

Create `backend/app/services/tests/test_notifications_deputies.py`:

```python
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select

from app.db.models import (
    CommanderNotificationScope,
    DutyManagerScope,
    Notification,
    NotificationType,
    RoleDeputy,
)
from app.services.notifications import (
    cascade_to_commanders,
    notify_duty_managers_in_scope,
    notify_duty_managers_of_request,
)
from tests.helpers import create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _notif_recipient_ids(session, *, reference_id) -> set:
    rows = session.execute(
        select(Notification.soldier_id).where(Notification.reference_id == reference_id)
    ).scalars().all()
    return set(rows)


def test_cascade_to_commanders_also_notifies_active_deputy(admin_session):
    node = create_node(admin_session, level="team", name=f"n_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"a_{_uid()}", hierarchy_node_id=node.id)
    commander = create_soldier(admin_session, personal_number=f"b_{_uid()}", role="commander")
    admin_session.add(CommanderNotificationScope(commander_id=commander.id, hierarchy_node_id=node.id))
    deputy = create_soldier(admin_session, personal_number=f"c_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=commander.id, deputy_id=deputy.id, role="commander",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    ref_id = uuid.uuid4()
    cascade_to_commanders(
        admin_session, type=NotificationType.assignment_created, title="t", body=None,
        reference_type="duty_assignment", reference_id=ref_id, actor_id=None,
        original_soldier_id=soldier.id,
    )
    admin_session.commit()

    recipients = _notif_recipient_ids(admin_session, reference_id=ref_id)
    assert commander.id in recipients
    assert deputy.id in recipients


def test_notify_duty_managers_in_scope_also_notifies_active_deputy(admin_session):
    node = create_node(admin_session, level="team", name=f"n_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"d_{_uid()}", hierarchy_node_id=node.id)
    dm = create_soldier(admin_session, personal_number=f"e_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    deputy = create_soldier(admin_session, personal_number=f"f_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=dm.id, deputy_id=deputy.id, role="duty_manager",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    ref_id = uuid.uuid4()
    notify_duty_managers_in_scope(
        admin_session, soldier_id=soldier.id, type=NotificationType.swap_pending_approval,
        title="t", reference_type="swap_request", reference_id=ref_id,
    )
    admin_session.commit()

    recipients = _notif_recipient_ids(admin_session, reference_id=ref_id)
    assert dm.id in recipients
    assert deputy.id in recipients


def test_notify_duty_managers_of_request_also_notifies_active_deputy(admin_session):
    # REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY (the level notify_duty_managers_of_request
    # actually checks against — a fixed module constant, not a setting) defaults
    # to "מרכז", the level keyed "department" (rank 4) in the seeded level types.
    # The DM's scope node must be at that rank or shallower (numerically <=) for
    # dm_scope_covers_level to pass, so this node must be "department", not
    # something deeper like "group" (מדור, rank 6).
    node = create_node(admin_session, level="department", name=f"n_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"g_{_uid()}", hierarchy_node_id=node.id)
    dm = create_soldier(admin_session, personal_number=f"h_{_uid()}", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    deputy = create_soldier(admin_session, personal_number=f"i_{_uid()}")
    admin_session.add(RoleDeputy(
        principal_id=dm.id, deputy_id=deputy.id, role="duty_manager",
        start_date=date.today(), end_date=date.today(),
    ))
    admin_session.commit()

    ref_id = uuid.uuid4()
    notify_duty_managers_of_request(
        admin_session, soldier_id=soldier.id, type=NotificationType.exemption_request_pending,
        title="t", reference_type="exemption_request", reference_id=ref_id,
    )
    admin_session.commit()

    recipients = _notif_recipient_ids(admin_session, reference_id=ref_id)
    assert dm.id in recipients
    assert deputy.id in recipients
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest app/services/tests/test_notifications_deputies.py -q`
Expected: 3 FAIL (deputy not in recipients yet).

- [ ] **Step 3: Add the shared helper**

In `backend/app/services/notifications.py`, add this function near the top of the file, right after the imports (before `cascade_to_commanders`):

```python
def _active_deputy_ids(
    session: Session, *, principal_id: uuid.UUID, role: str, today: date | None = None
) -> set[uuid.UUID]:
    """Soldiers currently (today) an active deputy for `principal_id` in `role`."""
    from app.db.models import RoleDeputy
    today = today or date.today()
    return set(
        session.execute(
            select(RoleDeputy.deputy_id).where(
                RoleDeputy.principal_id == principal_id,
                RoleDeputy.role == role,
                RoleDeputy.start_date <= today,
                RoleDeputy.end_date >= today,
            )
        ).scalars().all()
    )
```

(`date` and `from __future__ import annotations` are already imported/enabled at the top of this file, so the plain `date | None` annotation above works as-is with no further changes needed.)

- [ ] **Step 4: Extend `cascade_to_commanders`**

Replace the body of the `for scope in scopes:` loop (the block from `if scope.commander_id in seen:` through the `_create_notif(...)` call):

```python
    for scope in scopes:
        if scope.commander_id in seen:
            continue
        # Depth filtering for pending approval types
        if type in _DEPTH_FILTERED_TYPES:
            max_depth = _commander_max_depth(session, scope.commander_id, type)
            if max_depth is not None:
                try:
                    scope_idx = soldier_node.path_ids.index(scope.hierarchy_node_id)
                except ValueError:
                    continue
                depth = len(soldier_node.path_ids) - 1 - scope_idx
                if depth > max_depth:
                    continue
        seen.add(scope.commander_id)
        recipients = {scope.commander_id} | _active_deputy_ids(
            session, principal_id=scope.commander_id, role="commander"
        )
        for recipient_id in recipients:
            _create_notif(
                session, soldier_id=recipient_id,
                type=type, title=f"{soldier.full_name}: {title}",
                body=body, reference_type=reference_type,
                reference_id=reference_id, actor_id=actor_id,
            )
```

- [ ] **Step 5: Extend `notify_duty_managers_in_scope`**

Replace the body of its `for dm_scope in dm_scopes:` loop:

```python
    for dm_scope in dm_scopes:
        if (
            dm_scope.duty_manager_id in seen
            or dm_scope.duty_manager_id == soldier.id
            or (exclude_soldier_ids is not None and dm_scope.duty_manager_id in exclude_soldier_ids)
        ):
            continue
        seen.add(dm_scope.duty_manager_id)
        recipients = {dm_scope.duty_manager_id} | _active_deputy_ids(
            session, principal_id=dm_scope.duty_manager_id, role="duty_manager"
        )
        recipients.discard(soldier.id)
        if exclude_soldier_ids is not None:
            recipients -= exclude_soldier_ids
        for recipient_id in recipients:
            _create_notif(
                session, soldier_id=recipient_id,
                type=type, title=f"{soldier.full_name}: {title}",
                body=body, reference_type=reference_type,
                reference_id=reference_id, actor_id=actor_id,
                metadata=metadata,
            )
```

(Check the exact trailing arguments of the existing `_create_notif(...)` call in this function before replacing — it may already include `metadata=metadata` since this function accepts a `metadata` parameter; keep whatever the original call already passed.)

- [ ] **Step 6: Extend `notify_duty_managers_of_request`**

Replace the body of its `for dm_id in dm_ids:` loop:

```python
    for dm_id in dm_ids:
        roots = set(
            session.execute(
                select(DutyManagerScope.hierarchy_node_id).where(
                    DutyManagerScope.duty_manager_id == dm_id
                )
            ).scalars().all()
        )
        if not dm_scope_covers_target(
            session, scope_root_ids=roots, target_node=target_node,
            required_level_key=REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY,
        ):
            continue
        recipients = {dm_id} | _active_deputy_ids(session, principal_id=dm_id, role="duty_manager")
        for recipient_id in recipients:
            _create_notif(
                session, soldier_id=recipient_id, type=type,
                title=f"{soldier.full_name}: {title}", body=body,
                reference_type=reference_type, reference_id=reference_id,
                actor_id=actor_id,
            )
```

- [ ] **Step 7: Extend `notify_enrollment_received`**

This function has two separate loops — one over `cmdr_scopes` (commanders) and one over `dm_scopes` (duty managers). Replace the commander loop's body:

```python
    for scope in cmdr_scopes:
        if scope.commander_id in seen or scope.commander_id == soldier.id:
            continue
        seen.add(scope.commander_id)
        recipients = {scope.commander_id} | _active_deputy_ids(
            session, principal_id=scope.commander_id, role="commander"
        )
        recipients.discard(soldier.id)
        for recipient_id in recipients:
            _create_notif(
                session, soldier_id=recipient_id,
                type=NotificationType.enrollment_request_received,
                title=title, body=None,
                reference_type="enrollment_request", reference_id=enrollment_req.id,
                actor_id=None,
            )
```

And the duty-manager loop's body:

```python
    for dm_scope in dm_scopes:
        if dm_scope.duty_manager_id in seen or dm_scope.duty_manager_id == soldier.id:
            continue
        scope_node = session.get(HierarchyNode, dm_scope.hierarchy_node_id)
        if not scope_node:
            continue
        lt = session.execute(
            select(HierarchyLevelType).where(HierarchyLevelType.key == scope_node.level)
        ).scalar_one_or_none()
        if lt is None or lt.rank < min_rank:
            continue
        seen.add(dm_scope.duty_manager_id)
        recipients = {dm_scope.duty_manager_id} | _active_deputy_ids(
            session, principal_id=dm_scope.duty_manager_id, role="duty_manager"
        )
        recipients.discard(soldier.id)
        for recipient_id in recipients:
            _create_notif(
                session, soldier_id=recipient_id,
                type=NotificationType.enrollment_request_received,
                title=title, body=None,
                reference_type="enrollment_request", reference_id=enrollment_req.id,
                actor_id=None,
            )
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `pytest app/services/tests/test_notifications_deputies.py -q`
Expected: 3 passed.

- [ ] **Step 9: Run the full fast suite**

Run: `pytest -q`
Expected: all pass — this touches heavily-tested notification paths, so read any failure carefully; it most likely means an existing test asserted an exact recipient *count* that a no-op `_active_deputy_ids` call (returning an empty set when there are no deputies) shouldn't have changed, in which case the fix is in this task's code, not the old test.

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/notifications.py backend/app/services/tests/test_notifications_deputies.py
git commit -m "feat: notify active deputies alongside commanders/duty-managers"
```

---

## Task 9: Frontend API wrapper

**Files:**
- Create: `frontend/src/api/deputies.ts`
- Modify: `frontend/src/api/auth.ts`

**Interfaces:**
- Produces: `DeputyDTO`, `listDeputies(principalId)`, `createDeputy(input)`, `revokeDeputy(id)`; `Me.active_deputy_grants: ActiveDeputyGrantDTO[]`.

- [ ] **Step 1: Add `active_deputy_grants` to the `Me` interface**

In `frontend/src/api/auth.ts`, find the `Me` interface (it has fields like `is_commander: boolean; is_duty_manager: boolean; ...`) and add:

```typescript
export interface ActiveDeputyGrantDTO {
  principal_id: string;
  principal_name: string;
  role: "commander" | "duty_manager";
  end_date: string;
}
```

right above the `Me` interface, then add this field inside `Me`:

```typescript
  active_deputy_grants: ActiveDeputyGrantDTO[];
```

- [ ] **Step 2: Write `api/deputies.ts`**

Create `frontend/src/api/deputies.ts`:

```typescript
import { api } from "./client";

export interface DeputyDTO {
  id: string;
  principal_id: string;
  principal_name: string;
  deputy_id: string;
  deputy_name: string;
  role: "commander" | "duty_manager";
  start_date: string;
  end_date: string;
}

export interface CreateDeputyInput {
  principal_id: string;
  deputy_id: string;
  role: "commander" | "duty_manager";
  start_date: string;
  end_date: string;
}

export async function listDeputies(principalId: string): Promise<DeputyDTO[]> {
  return (await api.get<DeputyDTO[]>("/deputies", { params: { principal_id: principalId } })).data;
}

export async function createDeputy(input: CreateDeputyInput): Promise<DeputyDTO> {
  return (await api.post<DeputyDTO>("/deputies", input)).data;
}

export async function revokeDeputy(id: string): Promise<void> {
  await api.delete(`/deputies/${id}`);
}
```

- [ ] **Step 3: Typecheck**

Run (from `frontend/`): `npx tsc --noEmit -p .`
Expected: no errors. (No test for this task — it's a thin, directly-mirrored API wrapper with no branching logic; Task 10's component tests exercise it through mocks.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/deputies.ts frontend/src/api/auth.ts
git commit -m "feat: add deputies API client and Me.active_deputy_grants"
```

---

## Task 10: `DeputiesPanel` component

**Files:**
- Create: `frontend/src/components/DeputiesPanel.tsx`
- Create: `frontend/src/components/DeputiesPanel.test.tsx`
- Modify: `frontend/src/i18n/he.json`

**Interfaces:**
- Consumes: `listDeputies`, `createDeputy`, `revokeDeputy` (Task 9), `listSoldiers` (existing, `frontend/src/api/soldiers.ts`), `DateInput` (existing, `frontend/src/components/DateInput.tsx`).
- Produces: `<DeputiesPanel principalId={string} principalRoles={{ isCommander: boolean; isDutyManager: boolean }} />` — a self-contained section with an add-deputy form and a list of existing grants (each revocable).

- [ ] **Step 1: Add translation keys**

In `frontend/src/i18n/he.json`, add a new `"deputies"` section (place it alphabetically near `"duty_config"` or `"dashboard"` — check the file's existing top-level key ordering and insert accordingly):

```json
  "deputies": {
    "title": "ממלאי מקום",
    "add": "הוסף ממלא מקום",
    "search_soldier_placeholder": "חיפוש חייל...",
    "role_commander": "מפקד",
    "role_duty_manager": "אחראי תורנויות",
    "start_date": "מתאריך",
    "end_date": "עד תאריך",
    "no_deputies": "אין ממלאי מקום מוגדרים",
    "revoke": "הסר",
    "revoke_confirm": "להסיר את ממלא המקום?",
    "active_badge": "פעיל",
    "future_badge": "עתידי",
    "expired_badge": "פג תוקף",
    "role_label": "תפקיד"
  },
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/components/DeputiesPanel.test.tsx`:

```typescript
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import DeputiesPanel from "./DeputiesPanel";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, fallback?: string) => fallback ?? key }),
}));

const mockListDeputies = vi.fn();
const mockCreateDeputy = vi.fn();
const mockRevokeDeputy = vi.fn();
vi.mock("../api/deputies", () => ({
  listDeputies: (...args: unknown[]) => mockListDeputies(...args),
  createDeputy: (...args: unknown[]) => mockCreateDeputy(...args),
  revokeDeputy: (...args: unknown[]) => mockRevokeDeputy(...args),
}));

vi.mock("../api/soldiers", () => ({
  listSoldiers: vi.fn(() =>
    Promise.resolve([
      { id: "s1", full_name: "יוסי כהן", personal_number: "1234567", role: "soldier" },
    ])
  ),
}));

const grant = {
  id: "g1", principal_id: "p1", principal_name: "מפקד", deputy_id: "s1", deputy_name: "יוסי כהן",
  role: "commander" as const, start_date: "2026-01-01", end_date: "2026-12-31",
};

beforeEach(() => {
  mockListDeputies.mockReset();
  mockCreateDeputy.mockReset();
  mockRevokeDeputy.mockReset();
  mockListDeputies.mockResolvedValue([grant]);
});

test("lists existing deputy grants", async () => {
  render(<DeputiesPanel principalId="p1" principalRoles={{ isCommander: true, isDutyManager: false }} />);
  expect(await screen.findByText("יוסי כהן")).toBeInTheDocument();
});

test("creates a new deputy grant", async () => {
  mockCreateDeputy.mockResolvedValue({ ...grant, id: "g2" });
  render(<DeputiesPanel principalId="p1" principalRoles={{ isCommander: true, isDutyManager: false }} />);
  await screen.findByText("יוסי כהן");

  fireEvent.change(screen.getByPlaceholderText("חיפוש חייל..."), { target: { value: "יוסי" } });
  fireEvent.click(await screen.findByText(/יוסי כהן/));
  fireEvent.change(screen.getByLabelText("מתאריך"), { target: { value: "2026-02-01" } });
  fireEvent.change(screen.getByLabelText("עד תאריך"), { target: { value: "2026-02-28" } });
  fireEvent.click(screen.getByText("הוסף ממלא מקום"));

  await waitFor(() =>
    expect(mockCreateDeputy).toHaveBeenCalledWith({
      principal_id: "p1", deputy_id: "s1", role: "commander",
      start_date: "2026-02-01", end_date: "2026-02-28",
    })
  );
});

test("revokes an existing grant", async () => {
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
  mockRevokeDeputy.mockResolvedValue(undefined);
  render(<DeputiesPanel principalId="p1" principalRoles={{ isCommander: true, isDutyManager: false }} />);
  await screen.findByText("יוסי כהן");

  fireEvent.click(screen.getByText("הסר"));

  await waitFor(() => expect(mockRevokeDeputy).toHaveBeenCalledWith("g1"));
  confirmSpy.mockRestore();
});

test("role select is hidden and fixed to commander when principal only holds that role", async () => {
  render(<DeputiesPanel principalId="p1" principalRoles={{ isCommander: true, isDutyManager: false }} />);
  await screen.findByText("יוסי כהן");
  expect(screen.queryByLabelText("תפקיד")).not.toBeInTheDocument();
});

test("role select is shown when principal holds both roles", async () => {
  render(<DeputiesPanel principalId="p1" principalRoles={{ isCommander: true, isDutyManager: true }} />);
  await screen.findByText("יוסי כהן");
  expect(screen.getByLabelText("תפקיד")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npx vitest run src/components/DeputiesPanel.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the component**

Create `frontend/src/components/DeputiesPanel.tsx`:

```tsx
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Fuse from "fuse.js";
import { DeputyDTO, createDeputy, listDeputies, revokeDeputy } from "../api/deputies";
import { SoldierDTO, listSoldiers } from "../api/soldiers";
import DateInput from "./DateInput";

interface Props {
  principalId: string;
  principalRoles: { isCommander: boolean; isDutyManager: boolean };
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function statusOf(g: DeputyDTO, today: string): "active" | "future" | "expired" {
  if (g.end_date < today) return "expired";
  if (g.start_date > today) return "future";
  return "active";
}

export default function DeputiesPanel({ principalId, principalRoles }: Props) {
  const { t } = useTranslation();
  const [grants, setGrants] = useState<DeputyDTO[]>([]);
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [selectedDeputyId, setSelectedDeputyId] = useState("");
  const [searchText, setSearchText] = useState("");
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState<"commander" | "duty_manager">(
    principalRoles.isCommander ? "commander" : "duty_manager"
  );
  const [startDate, setStartDate] = useState(todayIso());
  const [endDate, setEndDate] = useState(todayIso());
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const bothRoles = principalRoles.isCommander && principalRoles.isDutyManager;

  async function refresh() {
    setGrants(await listDeputies(principalId));
  }

  useEffect(() => {
    void refresh();
    void listSoldiers().then(setSoldiers);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [principalId]);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const fuse = useMemo(
    () => new Fuse(soldiers, { keys: ["full_name", "personal_number"], threshold: 0.4 }),
    [soldiers]
  );
  const filtered = searchText ? fuse.search(searchText).map((r) => r.item).slice(0, 20) : soldiers.slice(0, 20);

  async function handleAdd() {
    if (!selectedDeputyId) return;
    setError(null);
    try {
      await createDeputy({
        principal_id: principalId, deputy_id: selectedDeputyId, role,
        start_date: startDate, end_date: endDate,
      });
      setSelectedDeputyId("");
      setSearchText("");
      await refresh();
    } catch {
      setError(t("errors.generic", "שגיאה"));
    }
  }

  async function handleRevoke(id: string) {
    if (!window.confirm(t("deputies.revoke_confirm", "להסיר את ממלא המקום?"))) return;
    await revokeDeputy(id);
    await refresh();
  }

  const today = todayIso();

  return (
    <div className="space-y-3" dir="rtl">
      <h4 className="font-semibold text-sm">{t("deputies.title", "ממלאי מקום")}</h4>

      {grants.length === 0 ? (
        <p className="text-xs text-gray-500 dark:text-gray-400">{t("deputies.no_deputies", "אין ממלאי מקום מוגדרים")}</p>
      ) : (
        <ul className="space-y-1">
          {grants.map((g) => {
            const s = statusOf(g, today);
            const badgeKey = s === "active" ? "deputies.active_badge" : s === "future" ? "deputies.future_badge" : "deputies.expired_badge";
            const badgeText = s === "active" ? "פעיל" : s === "future" ? "עתידי" : "פג תוקף";
            return (
              <li key={g.id} className="flex items-center justify-between text-sm border-b dark:border-gray-600 py-1">
                <span>
                  {g.deputy_name}{" "}
                  <span className="text-xs text-gray-400">
                    ({g.role === "commander" ? t("deputies.role_commander", "מפקד") : t("deputies.role_duty_manager", "אחראי תורנויות")}, {g.start_date} — {g.end_date})
                  </span>{" "}
                  <span className="text-xs">{t(badgeKey, badgeText)}</span>
                </span>
                {s !== "expired" && (
                  <button type="button" onClick={() => void handleRevoke(g.id)} className="text-red-600 text-xs hover:underline">
                    {t("deputies.revoke", "הסר")}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <div className="flex flex-wrap gap-2 items-end pt-2 border-t dark:border-gray-600">
        <div ref={containerRef} className="relative">
          <label className="block text-xs text-gray-500 mb-1">{t("deputies.add", "הוסף ממלא מקום")}</label>
          <input
            className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            value={searchText}
            onChange={(e) => { setSearchText(e.target.value); setSelectedDeputyId(""); setOpen(true); }}
            onFocus={() => setOpen(true)}
            placeholder={t("deputies.search_soldier_placeholder", "חיפוש חייל...")}
            autoComplete="off"
          />
          {open && filtered.length > 0 && (
            <ul className="absolute z-10 w-full mt-1 bg-white dark:bg-gray-700 border dark:border-gray-600 rounded shadow-lg max-h-48 overflow-y-auto">
              {filtered.map((s) => (
                <li
                  key={s.id}
                  className="px-3 py-2 text-sm cursor-pointer hover:bg-indigo-50 dark:hover:bg-indigo-900 dark:text-gray-100"
                  onMouseDown={(e) => { e.preventDefault(); setSelectedDeputyId(s.id); setSearchText(`${s.full_name} (${s.personal_number})`); setOpen(false); }}
                >
                  {s.full_name} <span className="text-gray-400 text-xs">({s.personal_number})</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {bothRoles && (
          <div className="flex flex-col gap-1">
            <label className="text-xs text-gray-500" htmlFor="deputy-role-select">{t("deputies.role_label", "תפקיד")}</label>
            <select
              id="deputy-role-select"
              value={role}
              onChange={(e) => setRole(e.target.value as "commander" | "duty_manager")}
              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
            >
              <option value="commander">{t("deputies.role_commander", "מפקד")}</option>
              <option value="duty_manager">{t("deputies.role_duty_manager", "אחראי תורנויות")}</option>
            </select>
          </div>
        )}

        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500" htmlFor="deputy-start-date">{t("deputies.start_date", "מתאריך")}</label>
          <DateInput id="deputy-start-date" value={startDate} onChange={setStartDate} />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-gray-500" htmlFor="deputy-end-date">{t("deputies.end_date", "עד תאריך")}</label>
          <DateInput id="deputy-end-date" value={endDate} onChange={setEndDate} min={startDate} />
        </div>

        <button
          type="button"
          onClick={() => void handleAdd()}
          disabled={!selectedDeputyId}
          className="bg-indigo-600 text-white px-3 py-1.5 rounded text-sm hover:bg-indigo-700 disabled:opacity-50"
        >
          {t("deputies.add", "הוסף ממלא מקום")}
        </button>
      </div>
      {error && <p className="text-red-500 text-xs">{error}</p>}
    </div>
  );
}
```

Before finalizing, check `frontend/src/components/DateInput.tsx`'s exact prop names (`value`, `onChange`, `min`, `id` — confirmed present via `DateInputProps` around line 68) and `frontend/src/api/soldiers.ts`'s `SoldierDTO` fields (`id`, `full_name`, `personal_number`, `role` — confirmed via `AssignCommanderDialog.tsx`) to make sure this component compiles against their real shapes.

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run src/components/DeputiesPanel.test.tsx`
Expected: 5 passed.

- [ ] **Step 5: Typecheck and lint**

Run: `npx tsc --noEmit -p .` then `npm run lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DeputiesPanel.tsx frontend/src/components/DeputiesPanel.test.tsx frontend/src/i18n/he.json
git commit -m "feat: add DeputiesPanel component"
```

---

## Task 11: Wire `DeputiesPanel` into `ProfilePage` (self-service)

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx`

**Interfaces:**
- Consumes: `DeputiesPanel` (Task 10).

- [ ] **Step 1: Add the import**

In `frontend/src/pages/ProfilePage.tsx`, add near the other component imports:

```typescript
import DeputiesPanel from "../components/DeputiesPanel";
```

- [ ] **Step 2: Render it conditionally**

Find the closing `</section>` of the notification-preferences section (the one this session added `visiblePrefs`/`isCommanderLike` to earlier — search for `{t("notifications.preferences")}`), and add a new section right after that `</section>` closes, before the final `</Layout>`:

```tsx
      {isCommanderLike && user?.id && (
        <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 mt-4 space-y-3" dir="rtl">
          <DeputiesPanel
            principalId={user.id}
            principalRoles={{ isCommander: !!user?.is_commander, isDutyManager: !!user?.is_duty_manager }}
          />
        </section>
      )}
```

(`isCommanderLike` already exists in this file, defined as `!!(user?.role === "admin" || user?.is_commander || user?.is_duty_manager)` — reuse it as the gate rather than inventing a new condition. Note admins without their own commander/DM scope would see the panel but `principalId={user.id}` for a plain admin who isn't themselves a commander/DM would hit `principal_lacks_role` on any add attempt; that's acceptable since the panel is empty/harmless for them and this matches the existing `isCommanderLike` gate's behavior for the notification-preferences section above it.)

- [ ] **Step 3: Typecheck**

Run: `npx tsc --noEmit -p .`
Expected: no errors.

- [ ] **Step 4: Manual smoke check (no automated test — see Task 13 for the homepage banner test, and Task 10 for DeputiesPanel's own tests; this task is pure wiring)**

Start the dev stack and confirm, as a commander or duty-manager user, the deputies panel appears on `/profile`. (If you can't run the dev stack in this environment, skip this step — the wiring is a 5-line JSX addition with no new logic, fully covered by Task 10's component tests plus the typecheck in Step 3.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ProfilePage.tsx
git commit -m "feat: show DeputiesPanel on ProfilePage for commanders/duty managers"
```

---

## Task 12: Wire `DeputiesPanel` into `UnifiedSoldierModal` (admin)

**Files:**
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx`

**Interfaces:**
- Consumes: `DeputiesPanel` (Task 10).

- [ ] **Step 1: Add the import**

In `frontend/src/components/UnifiedSoldierModal.tsx`, add near the other component imports:

```typescript
import DeputiesPanel from "./DeputiesPanel";
```

- [ ] **Step 2: Render it conditionally, admin-only**

This modal already computes `isCommander`/`isDutyManager` for the *viewing* user (lines 59-60: `const isDutyManager = user?.is_duty_manager ?? false; const isCommander = user?.is_commander ?? false;`) — those describe the viewer, not the modal's target `soldierData`. Add a check for the target's role instead: find where `soldierData.role` is rendered (around line 301, `{t(`role.${soldierData.role}`)}`) and add a new section after the modal's existing content, gated on `user?.role === "admin"` (the *viewer* being an admin) and the *target* currently holding a deputizable role:

```tsx
      {user?.role === "admin" && (soldierData.role === "commander" || soldierData.role === "duty_manager") && (
        <div className="mt-4 pt-4 border-t dark:border-gray-600">
          <DeputiesPanel
            principalId={soldierData.id}
            principalRoles={{
              isCommander: soldierData.role === "commander",
              isDutyManager: soldierData.role === "duty_manager",
            }}
          />
        </div>
      )}
```

Place this block wherever the modal's other conditional admin-only sections live (search for an existing `user?.role === "admin"` check in this file to match the surrounding JSX structure/indentation, and confirm `soldierData.id` and `soldierData.role` are the correct field names by checking this file's existing `soldierData.*` usages — e.g. line 285's `SoldierAvatar url={soldierData.profile_picture_url} ...` and line 301's role display already establish `soldierData` has `id` and `role`).

Note: `soldierData.role` is the denormalized *display* label (see `recompute_role` in `backend/app/services/dm_scope.py`), not a live `is_commander`/`is_duty_manager` check — the backend's `POST /deputies` route independently re-validates via the live `is_commander`/`is_duty_manager` functions (Task 5's `create_deputy`), so a stale label here only affects whether the panel is *shown*, never whether an invalid grant can actually be created.

- [ ] **Step 3: Typecheck and lint**

Run: `npx tsc --noEmit -p .` then `npm run lint`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/UnifiedSoldierModal.tsx
git commit -m "feat: let admins manage a soldier's deputies from UnifiedSoldierModal"
```

---

## Task 13: Active-deputy banner on the homepage

**Files:**
- Create: `frontend/src/components/ActiveDeputyBanner.tsx`
- Create: `frontend/src/components/ActiveDeputyBanner.test.tsx`
- Modify: `frontend/src/pages/HomePage.tsx`

**Interfaces:**
- Consumes: `Me.active_deputy_grants` (Task 9).
- Produces: `<ActiveDeputyBanner grants={ActiveDeputyGrantDTO[]} />`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/ActiveDeputyBanner.test.tsx`:

```typescript
import { render, screen } from "@testing-library/react";
import ActiveDeputyBanner from "./ActiveDeputyBanner";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, opts?: Record<string, unknown>) => {
    if (key === "deputies.acting_as_banner") {
      return `פועל/ת כממלא/ת מקום עבור ${opts?.principal} (${opts?.role}) עד ${opts?.endDate}`;
    }
    return key;
  } }),
}));

test("renders nothing when there are no active grants", () => {
  const { container } = render(<ActiveDeputyBanner grants={[]} />);
  expect(container).toBeEmptyDOMElement();
});

test("renders one line per active grant", () => {
  render(
    <ActiveDeputyBanner
      grants={[
        { principal_id: "p1", principal_name: "דנה לוי", role: "commander", end_date: "2026-09-01" },
        { principal_id: "p2", principal_name: "רון כהן", role: "duty_manager", end_date: "2026-09-15" },
      ]}
    />
  );
  expect(screen.getByText(/דנה לוי/)).toBeInTheDocument();
  expect(screen.getByText(/רון כהן/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run src/components/ActiveDeputyBanner.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Add the translation key**

In `frontend/src/i18n/he.json`, add this key inside the `"deputies"` section added in Task 10:

```json
    "acting_as_banner": "פועל/ת כממלא/ת מקום עבור {{principal}} ({{role}}) עד {{endDate}}",
```

- [ ] **Step 4: Write the component**

Create `frontend/src/components/ActiveDeputyBanner.tsx`:

```tsx
import { useTranslation } from "react-i18next";
import { ActiveDeputyGrantDTO } from "../api/auth";

interface Props {
  grants: ActiveDeputyGrantDTO[];
}

export default function ActiveDeputyBanner({ grants }: Props) {
  const { t } = useTranslation();
  if (grants.length === 0) return null;

  return (
    <div className="bg-indigo-50 dark:bg-indigo-950 border border-indigo-200 dark:border-indigo-800 rounded-lg p-3 text-sm text-indigo-800 dark:text-indigo-200 space-y-1" dir="rtl">
      {grants.map((g) => (
        <p key={g.principal_id}>
          {t("deputies.acting_as_banner", {
            principal: g.principal_name,
            role: g.role === "commander" ? t("deputies.role_commander", "מפקד") : t("deputies.role_duty_manager", "אחראי תורנויות"),
            endDate: g.end_date,
          })}
        </p>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `npx vitest run src/components/ActiveDeputyBanner.test.tsx`
Expected: 2 passed.

- [ ] **Step 6: Wire it into `HomePage`**

In `frontend/src/pages/HomePage.tsx`, add the import near the other component imports:

```typescript
import ActiveDeputyBanner from "../components/ActiveDeputyBanner";
```

Find where `user` is destructured from `useAuth()` (already present in this file, from earlier work this session) and add, near the top of the rendered JSX (immediately after the opening of the main content container, before the first existing section/widget):

```tsx
        <ActiveDeputyBanner grants={user?.active_deputy_grants ?? []} />
```

- [ ] **Step 7: Typecheck and lint**

Run: `npx tsc --noEmit -p .` then `npm run lint`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/ActiveDeputyBanner.tsx frontend/src/components/ActiveDeputyBanner.test.tsx frontend/src/pages/HomePage.tsx frontend/src/i18n/he.json
git commit -m "feat: show an active-deputy banner on the homepage"
```

---

## Task 14: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend suite including slow tests**

Run (from `backend/`): `pytest --slow -q`
Expected: all pass. This is the first time the slow suite runs against this feature — it includes the large-scale CP-SAT algorithm tests, which don't touch deputies directly but do exercise `is_commander`/`scope_root_ids` at scale through the normal assignment/scoring pipeline, so this is the real confirmation that Task 2's refactor didn't regress performance or correctness under load.

- [ ] **Step 2: Run the full frontend suite**

Run (from `frontend/`): `npm test`
Expected: all pass.

- [ ] **Step 3: Run frontend lint and typecheck one more time**

Run: `npm run lint` then `npx tsc --noEmit -p .`
Expected: zero warnings, no errors.

- [ ] **Step 4: Commit if anything needed fixing**

If any of the above required a fix, commit it now with a message describing what broke and why. If everything already passed, there's nothing to commit — this task is verification-only.
