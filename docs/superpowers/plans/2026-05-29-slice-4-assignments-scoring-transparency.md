# Slice 4: Duty Assignments, Scoring & Transparency — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add manual duty assignments (contiguous blocks), the per-day override layer (replacement/cancellation), manual score adjustments, on-demand cumulative + normalised scoring, and the four Hebrew/RTL UI surfaces (DM duty management, שקיפות transparency, personal duty list, unit calendar) — every mutation audited and behind the role + scope authorization layer.

**Architecture:** Three scoped domain service modules (`assignments.py`, `adjustments.py`, `scoring.py`) mirror the Slice 2–3 grain: pure functions mutate + `write_audit` in one transaction and raise domain errors; thin routes parse → load → `authorize(...)` → call service → return Pydantic. `scoring.py` is read-only and computes in Python (expanding date ranges + applying overrides) for clarity and unit-testability at pilot scale. Two new `Action`s (`ASSIGNMENT_MANAGE`, `SCORE_ADJUST`) go to duty_manager + admin; the transparency table is the one read open to every authenticated user.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x (MappedAsDataclass), Alembic, Pydantic v2, Postgres 16, pytest + testcontainers, React 18 + Vite + TS, react-i18next, axios, Playwright. Same toolchain as Slices 1–3.

---

## Spec coverage

Implements `docs/superpowers/specs/2026-05-29-slice-4-assignments-scoring-transparency-design.md`: design-doc §4.1 tables `duty_assignments`, `duty_day_overrides`, `score_adjustments`; §4.4 cumulative/active-days/normalised scoring; §5.2 rows "Create / edit duty assignments", "Override an assignment", "Adjust soldier scores manually", "View calendar of soldiers in subtree", "View each subtree soldier's score and history", "View transparency table"; page surfaces §7 #5/#6/#7 + a personal duty list. Out of scope: `personal_constraints`, the CP-SAT algorithm, `assignment_explanations`, `reserve_assignments`, the full month-grid calendar + "?למה קיבלתי" modal, the marketplace, `system_settings` editing UI.

## Conventions

- Backend commands run from `backend/` with `uv`. **Use `git -C ..` for commits** so the shell stays in `backend/`.
- Frontend commands run from `frontend/` with `pnpm`.
- "Run X. Expected: Y." — actually run it and confirm before continuing.
- TDD: write the failing test, see it fail, implement, see it pass, commit. One small commit per task.
- Branch `slice-4-assignments-scoring-transparency` off `master`. Migrations continue at `0012`.
- MappedAsDataclass ordering: fields **without** a default precede fields **with** a default; `init=False` columns (PK, timestamps) are excluded from `__init__`, so their position is free. Constructors are called with keyword args, so field order does not affect callers.
- Enum-like columns are `text` + a CHECK constraint (portable; adding values later needs no type migration).

## File structure

```
backend/
├── alembic/versions/
│   ├── 0012_create_duty_assignments.py
│   ├── 0013_create_duty_day_overrides.py
│   └── 0014_create_score_adjustments.py
├── app/
│   ├── db/models.py                    # +DutyAssignment, DutyDayOverride, ScoreAdjustment
│   ├── auth/authz.py                   # +ASSIGNMENT_MANAGE, SCORE_ADJUST
│   ├── services/{assignments,adjustments,scoring}.py
│   ├── routes/{assignments,score_adjustments,scoring,calendar}.py
│   └── main.py                         # wire four routers
└── tests/
    ├── unit/{test_assignments_service,test_adjustments_service,test_scoring_service}.py
    └── integration/{test_assignments_api,test_score_adjustments_api,test_scoring_api,test_calendar_api}.py

frontend/
├── src/
│   ├── api/{assignments,scoreAdjustments,scoring,calendar}.ts
│   ├── pages/{DutyManagementPage,TransparencyPage,MyDutiesPage,UnitCalendarPage}.tsx
│   ├── components/Layout.tsx           # +sidebar entries
│   ├── App.tsx                         # +routes
│   └── i18n/he.json                    # +strings
└── tests/e2e/assignments.spec.ts
```

---

## Phase A — Schema (migrations 0012–0014)

### Task 1: Create the three migrations

**Files:**
- Create: `backend/alembic/versions/0012_create_duty_assignments.py`
- Create: `backend/alembic/versions/0013_create_duty_day_overrides.py`
- Create: `backend/alembic/versions/0014_create_score_adjustments.py`

- [ ] **Step 1: Create `0012_create_duty_assignments.py`**

```python
"""create duty_assignments

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "duty_assignments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "soldier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "duty_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("duty_types.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "duty_location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("duty_locations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'published'"), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'published', 'cancelled')",
            name="ck_duty_assignments_status",
        ),
    )
    op.create_index(
        "ix_duty_assignments_soldier_start", "duty_assignments", ["soldier_id", "start_date"]
    )
    op.create_index("ix_duty_assignments_dates", "duty_assignments", ["start_date", "end_date"])


def downgrade() -> None:
    op.drop_table("duty_assignments")
```

- [ ] **Step 2: Create `0013_create_duty_day_overrides.py`** (`revision="0013"`, `down_revision="0012"`)

```python
"""create duty_day_overrides

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "duty_day_overrides",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "duty_assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("duty_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "effective_soldier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("duty_assignment_id", "date", name="uq_duty_day_overrides_assignment_date"),
        sa.CheckConstraint(
            "reason IN ('replacement', 'no_show_covered', 'cancelled', 'manual_edit')",
            name="ck_duty_day_overrides_reason",
        ),
    )


def downgrade() -> None:
    op.drop_table("duty_day_overrides")
```

- [ ] **Step 3: Create `0014_create_score_adjustments.py`** (`revision="0014"`, `down_revision="0013"`)

```python
"""create score_adjustments

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "score_adjustments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "soldier_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("delta", sa.Numeric(8, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "duty_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("duty_types.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_score_adjustments_soldier", "score_adjustments", ["soldier_id"])


def downgrade() -> None:
    op.drop_table("score_adjustments")
```

- [ ] **Step 4: Apply via the suite bootstrap**

Run (from `backend/`): `uv run pytest tests/integration/test_audit_append_only.py -q`
Expected: `3 passed` (proves `alembic upgrade head` including 0012–0014 applies cleanly).

- [ ] **Step 5: Verify migrations are reversible**

Run: `uv run alembic check`
Expected: no error (exit 0).

- [ ] **Step 6: Commit**

```bash
git -C .. add backend/alembic/versions/0012_create_duty_assignments.py backend/alembic/versions/0013_create_duty_day_overrides.py backend/alembic/versions/0014_create_score_adjustments.py
git -C .. commit -m "feat(db): duty_assignments, duty_day_overrides, score_adjustments migrations"
```

---

## Phase B — ORM models

### Task 2: Add three ORM models to `models.py`

**Files:**
- Modify: `backend/app/db/models.py` (append at end; imports already include `Boolean, Date, DateTime, Enum, ForeignKey, Numeric, Text, text`, `Decimal`, `UUID`)

- [ ] **Step 1: Append the models** to the end of `backend/app/db/models.py`

```python
class DutyAssignment(Base):
    __tablename__ = "duty_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    duty_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_types.id", ondelete="RESTRICT")
    )
    duty_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_locations.id", ondelete="RESTRICT")
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, server_default=text("'published'"), default="published")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class DutyDayOverride(Base):
    __tablename__ = "duty_day_overrides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    duty_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_assignments.id", ondelete="CASCADE")
    )
    date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    effective_soldier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class ScoreAdjustment(Base):
    __tablename__ = "score_adjustments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    delta: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    reason: Mapped[str] = mapped_column(Text)
    duty_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_types.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 2: Verify the import graph**

Run: `uv run python -c "from app.db.models import DutyAssignment, DutyDayOverride, ScoreAdjustment; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git -C .. add backend/app/db/models.py
git -C .. commit -m "feat(db): ORM models for assignments, overrides, score adjustments"
```

---

## Phase C — Authorization extension

### Task 3: Add assignment + score actions to the authz engine

**Files:**
- Modify: `backend/app/auth/authz.py`
- Modify: `backend/tests/unit/test_authz.py`

- [ ] **Step 1: Add failing tests** — append to `backend/tests/unit/test_authz.py` (mirror the existing helper usage `create_node`, `create_soldier`, `_roots` already imported in that file):

```python
def test_duty_manager_can_manage_assignments_and_scores_in_scope(admin_session):
    d = create_node(admin_session, level="department", name="d-s4")
    b = create_node(admin_session, level="branch", name="b-s4", parent=d)
    other = create_node(admin_session, level="department", name="other-s4")
    dm = create_soldier(admin_session, personal_number="7400001", role="duty_manager", hierarchy_node_id=b.id)
    roots = _roots(admin_session, dm)
    assert authz.can(dm, authz.Action.ASSIGNMENT_MANAGE, target_node=b, roots=roots)
    assert authz.can(dm, authz.Action.SCORE_ADJUST, target_node=b, roots=roots)
    assert not authz.can(dm, authz.Action.ASSIGNMENT_MANAGE, target_node=other, roots=roots)


def test_commander_cannot_manage_assignments(admin_session):
    d = create_node(admin_session, level="department", name="d-s4b")
    b = create_node(admin_session, level="branch", name="b-s4b", parent=d)
    cmd = create_soldier(admin_session, personal_number="7400002", role="commander")
    b.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    assert not authz.can(cmd, authz.Action.ASSIGNMENT_MANAGE, target_node=b, roots=roots)
    assert not authz.can(cmd, authz.Action.SCORE_ADJUST, target_node=b, roots=roots)


def test_plain_soldier_cannot_manage_assignments(admin_session):
    d = create_node(admin_session, level="department", name="d-s4c")
    s = create_soldier(admin_session, personal_number="7400003", role="soldier", hierarchy_node_id=d.id)
    roots = _roots(admin_session, s)
    assert not authz.can(s, authz.Action.ASSIGNMENT_MANAGE, target_node=d, roots=roots)
```

> If `test_authz.py` does not already import `authz`, `create_node`, `create_soldier`, and a `_roots` helper, copy the import block from the top of that file's existing tests (added in Slice 2/3). Do not invent new helpers.

- [ ] **Step 2: Run — expect FAIL** (`AttributeError: ASSIGNMENT_MANAGE`).

Run: `uv run pytest tests/unit/test_authz.py -q`

- [ ] **Step 3: Edit `backend/app/auth/authz.py`**

Add two attributes to `class Action` (after `EXEMPTION_READ`):

```python
    ASSIGNMENT_MANAGE = "assignment.manage"
    SCORE_ADJUST = "score.adjust"
```

Add both to `_DM_ACTIONS` only (commanders may view but not manage — they are intentionally left out of `_COMMANDER_ACTIONS`):

```python
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
    Action.ASSIGNMENT_MANAGE,
    Action.SCORE_ADJUST,
}
```

> Admin already returns `True` for every action via the `role == "admin"` short-circuit — no change needed there.

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/unit/test_authz.py -q`
Expected: all pass (pre-existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/app/auth/authz.py backend/tests/unit/test_authz.py
git -C .. commit -m "feat(authz): ASSIGNMENT_MANAGE + SCORE_ADJUST actions for duty_manager"
```

---

## Phase D — Assignments service (TDD)

### Task 4: create / cancel assignment with overlap + exemption guards

**Files:**
- Create: `backend/app/services/assignments.py`
- Create: `backend/tests/unit/test_assignments_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_assignments_service.py
from datetime import date

import pytest

from app.db.models import DutyAssignment, DutyLocation, DutyType, ExemptionType, SoldierExemption
from app.services.assignments import AssignmentError, cancel_assignment, create_assignment
from app.services.duty_config import map_exemption_to_duty_type
from tests.helpers import create_soldier


def _dt(session, name="dt", score="1.00"):
    from decimal import Decimal
    dt = DutyType(name=name, score_per_day=Decimal(score))
    session.add(dt)
    session.flush()
    return dt


def _loc(session, name="loc"):
    loc = DutyLocation(name=name)
    session.add(loc)
    session.flush()
    return loc


def test_create_assignment(admin_session):
    s = create_soldier(admin_session, personal_number="8100001")
    dt = _dt(admin_session, "שמירה-a1")
    loc = _loc(admin_session, "מוצב-a1")
    a = create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 6, 1), end_date=date(2026, 6, 3), notes="ok", actor_id=None)
    admin_session.commit()
    assert a.status == "published"
    assert a.start_date == date(2026, 6, 1)


def test_create_rejects_bad_date_range(admin_session):
    s = create_soldier(admin_session, personal_number="8100002")
    dt = _dt(admin_session, "שמירה-a2")
    loc = _loc(admin_session, "מוצב-a2")
    with pytest.raises(AssignmentError):
        create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 6, 5), end_date=date(2026, 6, 1), notes=None, actor_id=None)


def test_create_rejects_overlap(admin_session):
    s = create_soldier(admin_session, personal_number="8100003")
    dt = _dt(admin_session, "שמירה-a3")
    loc = _loc(admin_session, "מוצב-a3")
    create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date(2026, 6, 1), end_date=date(2026, 6, 5), notes=None, actor_id=None)
    admin_session.flush()
    with pytest.raises(AssignmentError) as exc:
        create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 6, 4), end_date=date(2026, 6, 7), notes=None, actor_id=None)
    assert "overlap" in str(exc.value)


def test_create_rejects_exempted_soldier(admin_session):
    s = create_soldier(admin_session, personal_number="8100004")
    dt = _dt(admin_session, "שמירה-a4")
    loc = _loc(admin_session, "מוצב-a4")
    et = ExemptionType(name="פטור-a4")
    admin_session.add(et)
    admin_session.flush()
    map_exemption_to_duty_type(admin_session, exemption_type_id=et.id, duty_type_id=dt.id, actor_id=None)
    admin_session.add(SoldierExemption(soldier_id=s.id, exemption_type_id=et.id,
                                       start_date=date(2026, 6, 1), end_date=None))
    admin_session.flush()
    with pytest.raises(AssignmentError) as exc:
        create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 6, 2), end_date=date(2026, 6, 4), notes=None, actor_id=None)
    assert "exempted" in str(exc.value)


def test_cancel_assignment(admin_session):
    s = create_soldier(admin_session, personal_number="8100005")
    dt = _dt(admin_session, "שמירה-a5")
    loc = _loc(admin_session, "מוצב-a5")
    a = create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 6, 1), end_date=date(2026, 6, 2), notes=None, actor_id=None)
    admin_session.flush()
    cancel_assignment(admin_session, assignment=a, reason="בוטל", actor_id=None)
    admin_session.commit()
    assert a.status == "cancelled"
    # a cancelled block no longer blocks a new overlapping one
    create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date(2026, 6, 1), end_date=date(2026, 6, 2), notes=None, actor_id=None)
    admin_session.commit()


def test_cancel_requires_reason(admin_session):
    s = create_soldier(admin_session, personal_number="8100006")
    dt = _dt(admin_session, "שמירה-a6")
    loc = _loc(admin_session, "מוצב-a6")
    a = create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 6, 1), end_date=date(2026, 6, 2), notes=None, actor_id=None)
    admin_session.flush()
    with pytest.raises(AssignmentError):
        cancel_assignment(admin_session, assignment=a, reason="  ", actor_id=None)
```

- [ ] **Step 2: Run — expect FAIL** (module missing).

Run: `uv run pytest tests/unit/test_assignments_service.py -q`

- [ ] **Step 3: Create `backend/app/services/assignments.py`**

```python
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import (
    DutyAssignment,
    DutyDayOverride,
    DutyLocation,
    DutyType,
    ExemptionDutyTypeMap,
    Soldier,
    SoldierExemption,
)

_OVERRIDE_REASONS = {"replacement", "no_show_covered", "cancelled", "manual_edit"}


class AssignmentError(Exception):
    """Raised on an invalid assignment operation."""


def _has_overlap(
    session: Session, *, soldier_id: uuid.UUID, start_date: date, end_date: date,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    q = select(DutyAssignment.id).where(
        DutyAssignment.soldier_id == soldier_id,
        DutyAssignment.status != "cancelled",
        DutyAssignment.start_date <= end_date,
        DutyAssignment.end_date >= start_date,
    )
    if exclude_id is not None:
        q = q.where(DutyAssignment.id != exclude_id)
    return session.execute(q).first() is not None


def _has_blocking_exemption(
    session: Session, *, soldier_id: uuid.UUID, duty_type_id: uuid.UUID, start_date: date, end_date: date
) -> bool:
    covering = select(ExemptionDutyTypeMap.exemption_type_id).where(
        ExemptionDutyTypeMap.duty_type_id == duty_type_id
    )
    q = select(SoldierExemption.id).where(
        SoldierExemption.soldier_id == soldier_id,
        SoldierExemption.exemption_type_id.in_(covering),
        SoldierExemption.start_date <= end_date,
        or_(SoldierExemption.end_date.is_(None), SoldierExemption.end_date >= start_date),
    )
    return session.execute(q).first() is not None


def create_assignment(
    session: Session, *, soldier_id: uuid.UUID, duty_type_id: uuid.UUID, duty_location_id: uuid.UUID,
    start_date: date, end_date: date, notes: str | None = None, actor_id: uuid.UUID | None = None,
) -> DutyAssignment:
    if end_date < start_date:
        raise AssignmentError("bad_date_range")
    if session.get(Soldier, soldier_id) is None:
        raise AssignmentError("soldier_not_found")
    if session.get(DutyType, duty_type_id) is None:
        raise AssignmentError("duty_type_not_found")
    if session.get(DutyLocation, duty_location_id) is None:
        raise AssignmentError("location_not_found")
    if _has_overlap(session, soldier_id=soldier_id, start_date=start_date, end_date=end_date):
        raise AssignmentError("overlap")
    if _has_blocking_exemption(session, soldier_id=soldier_id, duty_type_id=duty_type_id,
                               start_date=start_date, end_date=end_date):
        raise AssignmentError("exempted")
    a = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=duty_type_id, duty_location_id=duty_location_id,
        start_date=start_date, end_date=end_date, notes=notes, created_by=actor_id,
    )
    session.add(a)
    session.flush()
    write_audit(session, actor_id=actor_id, action="assignment.create", entity_type="duty_assignment",
                entity_id=a.id, after={"soldier_id": str(soldier_id), "duty_type_id": str(duty_type_id),
                                       "start_date": start_date.isoformat(), "end_date": end_date.isoformat()})
    return a


def cancel_assignment(
    session: Session, *, assignment: DutyAssignment, reason: str, actor_id: uuid.UUID | None = None
) -> DutyAssignment:
    if not reason or not reason.strip():
        raise AssignmentError("reason_required")
    before = {"status": assignment.status}
    assignment.status = "cancelled"
    write_audit(session, actor_id=actor_id, action="assignment.cancel", entity_type="duty_assignment",
                entity_id=assignment.id, before=before, after={"status": "cancelled"},
                context={"reason": reason})
    return assignment
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/unit/test_assignments_service.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/app/services/assignments.py backend/tests/unit/test_assignments_service.py
git -C .. commit -m "feat(assignments): create + cancel with overlap and exemption guards"
```

---

### Task 5: per-day overrides + list helpers

**Files:**
- Modify: `backend/app/services/assignments.py`
- Modify: `backend/tests/unit/test_assignments_service.py`

- [ ] **Step 1: Add failing tests** — append:

```python
from app.db.models import DutyDayOverride
from app.services.assignments import (
    clear_day_override,
    list_assignments,
    list_assignments_for_soldiers,
    set_day_override,
)


def test_set_and_clear_day_override(admin_session):
    s = create_soldier(admin_session, personal_number="8200001")
    repl = create_soldier(admin_session, personal_number="8200002")
    dt = _dt(admin_session, "שמירה-o1")
    loc = _loc(admin_session, "מוצב-o1")
    a = create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 7, 1), end_date=date(2026, 7, 5), notes=None, actor_id=None)
    admin_session.flush()
    ov = set_day_override(admin_session, assignment=a, date=date(2026, 7, 3),
                          effective_soldier_id=repl.id, reason="replacement", actor_id=None)
    admin_session.flush()
    assert ov.effective_soldier_id == repl.id
    clear_day_override(admin_session, assignment=a, date=date(2026, 7, 3), actor_id=None)
    admin_session.flush()
    assert admin_session.execute(
        select(DutyDayOverride).where(DutyDayOverride.duty_assignment_id == a.id)
    ).first() is None


def test_override_cancel_day_with_null_effective(admin_session):
    s = create_soldier(admin_session, personal_number="8200003")
    dt = _dt(admin_session, "שמירה-o2")
    loc = _loc(admin_session, "מוצב-o2")
    a = create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 7, 1), end_date=date(2026, 7, 2), notes=None, actor_id=None)
    admin_session.flush()
    ov = set_day_override(admin_session, assignment=a, date=date(2026, 7, 1),
                          effective_soldier_id=None, reason="cancelled", actor_id=None)
    admin_session.flush()
    assert ov.effective_soldier_id is None


def test_override_rejects_date_out_of_range(admin_session):
    s = create_soldier(admin_session, personal_number="8200004")
    dt = _dt(admin_session, "שמירה-o3")
    loc = _loc(admin_session, "מוצב-o3")
    a = create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 7, 1), end_date=date(2026, 7, 2), notes=None, actor_id=None)
    admin_session.flush()
    with pytest.raises(AssignmentError):
        set_day_override(admin_session, assignment=a, date=date(2026, 7, 9),
                         effective_soldier_id=None, reason="cancelled", actor_id=None)


def test_set_override_is_idempotent_upsert(admin_session):
    s = create_soldier(admin_session, personal_number="8200005")
    r1 = create_soldier(admin_session, personal_number="8200006")
    r2 = create_soldier(admin_session, personal_number="8200007")
    dt = _dt(admin_session, "שמירה-o4")
    loc = _loc(admin_session, "מוצב-o4")
    a = create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 7, 1), end_date=date(2026, 7, 2), notes=None, actor_id=None)
    admin_session.flush()
    set_day_override(admin_session, assignment=a, date=date(2026, 7, 1),
                     effective_soldier_id=r1.id, reason="replacement", actor_id=None)
    set_day_override(admin_session, assignment=a, date=date(2026, 7, 1),
                     effective_soldier_id=r2.id, reason="replacement", actor_id=None)
    admin_session.flush()
    rows = admin_session.execute(
        select(DutyDayOverride).where(DutyDayOverride.duty_assignment_id == a.id)
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].effective_soldier_id == r2.id


def test_list_assignments_by_soldier_and_range(admin_session):
    s = create_soldier(admin_session, personal_number="8200008")
    dt = _dt(admin_session, "שמירה-o5")
    loc = _loc(admin_session, "מוצב-o5")
    create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date(2026, 7, 1), end_date=date(2026, 7, 2), notes=None, actor_id=None)
    create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date(2026, 8, 1), end_date=date(2026, 8, 2), notes=None, actor_id=None)
    admin_session.flush()
    july = list_assignments(admin_session, soldier_id=s.id, date_from=date(2026, 7, 1), date_to=date(2026, 7, 31))
    assert len(july) == 1
    both = list_assignments_for_soldiers(admin_session, soldier_ids=[s.id])
    assert len(both) == 2
```

- [ ] **Step 2: Run — expect FAIL** (functions missing).

- [ ] **Step 3: Append to `backend/app/services/assignments.py`**

```python
def _day_busy(
    session: Session, *, soldier_id: uuid.UUID, on_date: date, exclude_assignment_id: uuid.UUID | None = None
) -> bool:
    q = select(DutyAssignment.id).where(
        DutyAssignment.soldier_id == soldier_id,
        DutyAssignment.status != "cancelled",
        DutyAssignment.start_date <= on_date,
        DutyAssignment.end_date >= on_date,
    )
    if exclude_assignment_id is not None:
        q = q.where(DutyAssignment.id != exclude_assignment_id)
    return session.execute(q).first() is not None


def set_day_override(
    session: Session, *, assignment: DutyAssignment, date: date, effective_soldier_id: uuid.UUID | None,
    reason: str, actor_id: uuid.UUID | None = None,
) -> DutyDayOverride:
    if not (assignment.start_date <= date <= assignment.end_date):
        raise AssignmentError("date_out_of_range")
    if reason not in _OVERRIDE_REASONS:
        raise AssignmentError("bad_reason")
    if effective_soldier_id is not None:
        if session.get(Soldier, effective_soldier_id) is None:
            raise AssignmentError("soldier_not_found")
        if _day_busy(session, soldier_id=effective_soldier_id, on_date=date,
                     exclude_assignment_id=assignment.id):
            raise AssignmentError("overlap")
        if _has_blocking_exemption(session, soldier_id=effective_soldier_id,
                                   duty_type_id=assignment.duty_type_id, start_date=date, end_date=date):
            raise AssignmentError("exempted")
    existing = session.execute(
        select(DutyDayOverride).where(
            DutyDayOverride.duty_assignment_id == assignment.id, DutyDayOverride.date == date
        )
    ).scalar_one_or_none()
    after = {"effective_soldier_id": str(effective_soldier_id) if effective_soldier_id else None,
             "reason": reason}
    if existing is not None:
        before = {"effective_soldier_id": str(existing.effective_soldier_id)
                  if existing.effective_soldier_id else None, "reason": existing.reason}
        existing.effective_soldier_id = effective_soldier_id
        existing.reason = reason
        write_audit(session, actor_id=actor_id, action="assignment.override",
                    entity_type="duty_day_override", entity_id=existing.id, before=before, after=after)
        return existing
    ov = DutyDayOverride(duty_assignment_id=assignment.id, date=date,
                         effective_soldier_id=effective_soldier_id, reason=reason, created_by=actor_id)
    session.add(ov)
    session.flush()
    write_audit(session, actor_id=actor_id, action="assignment.override",
                entity_type="duty_day_override", entity_id=ov.id, after=after)
    return ov


def clear_day_override(
    session: Session, *, assignment: DutyAssignment, date: date, actor_id: uuid.UUID | None = None
) -> None:
    ov = session.execute(
        select(DutyDayOverride).where(
            DutyDayOverride.duty_assignment_id == assignment.id, DutyDayOverride.date == date
        )
    ).scalar_one_or_none()
    if ov is None:
        return  # idempotent
    write_audit(session, actor_id=actor_id, action="assignment.override_clear",
                entity_type="duty_day_override", entity_id=ov.id,
                before={"effective_soldier_id": str(ov.effective_soldier_id) if ov.effective_soldier_id else None})
    session.delete(ov)


def list_assignments(
    session: Session, *, soldier_id: uuid.UUID | None = None, date_from: date | None = None,
    date_to: date | None = None,
) -> list[DutyAssignment]:
    q = select(DutyAssignment).where(DutyAssignment.status != "cancelled")
    if soldier_id is not None:
        q = q.where(DutyAssignment.soldier_id == soldier_id)
    if date_from is not None:
        q = q.where(DutyAssignment.end_date >= date_from)
    if date_to is not None:
        q = q.where(DutyAssignment.start_date <= date_to)
    return list(session.execute(q.order_by(DutyAssignment.start_date)).scalars().all())


def list_assignments_for_soldiers(
    session: Session, *, soldier_ids: list[uuid.UUID], date_from: date | None = None,
    date_to: date | None = None,
) -> list[DutyAssignment]:
    if not soldier_ids:
        return []
    q = select(DutyAssignment).where(
        DutyAssignment.status != "cancelled", DutyAssignment.soldier_id.in_(soldier_ids)
    )
    if date_from is not None:
        q = q.where(DutyAssignment.end_date >= date_from)
    if date_to is not None:
        q = q.where(DutyAssignment.start_date <= date_to)
    return list(session.execute(q.order_by(DutyAssignment.start_date)).scalars().all())
```

> Note: `set_day_override`'s parameter `date` shadows the imported `date` type within that function body; this is intentional and harmless (no `date(...)` construction happens inside). Keep the module-level `from datetime import date` import.

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/unit/test_assignments_service.py -q`
Expected: `11 passed`.

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/app/services/assignments.py backend/tests/unit/test_assignments_service.py
git -C .. commit -m "feat(assignments): per-day overrides + list helpers"
```

---

## Phase E — Adjustments service (TDD)

### Task 6: score adjustments create / list

**Files:**
- Create: `backend/app/services/adjustments.py`
- Create: `backend/tests/unit/test_adjustments_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_adjustments_service.py
from decimal import Decimal

import pytest

from app.services.adjustments import AdjustmentError, create_adjustment, list_adjustments
from tests.helpers import create_soldier


def test_create_positive_and_negative(admin_session):
    s = create_soldier(admin_session, personal_number="8300001")
    create_adjustment(admin_session, soldier_id=s.id, delta=Decimal("2.5"), reason="פיצוי", actor_id=None)
    create_adjustment(admin_session, soldier_id=s.id, delta=Decimal("-1.0"), reason="תיקון", actor_id=None)
    admin_session.commit()
    rows = list_adjustments(admin_session, soldier_id=s.id)
    assert {r.delta for r in rows} == {Decimal("2.50"), Decimal("-1.00")}


def test_zero_delta_rejected(admin_session):
    s = create_soldier(admin_session, personal_number="8300002")
    with pytest.raises(AdjustmentError):
        create_adjustment(admin_session, soldier_id=s.id, delta=Decimal("0"), reason="x", actor_id=None)


def test_empty_reason_rejected(admin_session):
    s = create_soldier(admin_session, personal_number="8300003")
    with pytest.raises(AdjustmentError):
        create_adjustment(admin_session, soldier_id=s.id, delta=Decimal("1"), reason="  ", actor_id=None)


def test_unknown_soldier_rejected(admin_session):
    import uuid
    with pytest.raises(AdjustmentError):
        create_adjustment(admin_session, soldier_id=uuid.uuid4(), delta=Decimal("1"), reason="x", actor_id=None)
```

- [ ] **Step 2: Run — expect FAIL** (module missing).

- [ ] **Step 3: Create `backend/app/services/adjustments.py`**

```python
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import ScoreAdjustment, Soldier


class AdjustmentError(Exception):
    """Raised on an invalid score-adjustment operation."""


def create_adjustment(
    session: Session, *, soldier_id: uuid.UUID, delta: Decimal, reason: str,
    duty_type_id: uuid.UUID | None = None, actor_id: uuid.UUID | None = None,
) -> ScoreAdjustment:
    if session.get(Soldier, soldier_id) is None:
        raise AdjustmentError("soldier_not_found")
    if delta == 0:
        raise AdjustmentError("zero_delta")
    if not reason or not reason.strip():
        raise AdjustmentError("reason_required")
    adj = ScoreAdjustment(soldier_id=soldier_id, delta=delta, reason=reason,
                          duty_type_id=duty_type_id, created_by=actor_id)
    session.add(adj)
    session.flush()
    write_audit(session, actor_id=actor_id, action="score_adjustment.create",
                entity_type="score_adjustment", entity_id=adj.id,
                after={"soldier_id": str(soldier_id), "delta": str(delta)}, context={"reason": reason})
    return adj


def list_adjustments(session: Session, *, soldier_id: uuid.UUID) -> list[ScoreAdjustment]:
    return list(session.execute(
        select(ScoreAdjustment).where(ScoreAdjustment.soldier_id == soldier_id)
        .order_by(ScoreAdjustment.created_at)
    ).scalars().all())
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/unit/test_adjustments_service.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/app/services/adjustments.py backend/tests/unit/test_adjustments_service.py
git -C .. commit -m "feat(adjustments): score-adjustment create/list service"
```

---

## Phase F — Scoring service (TDD)

### Task 7: effective duty-days + cumulative score

**Files:**
- Create: `backend/app/services/scoring.py`
- Create: `backend/tests/unit/test_scoring_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_scoring_service.py
from datetime import date
from decimal import Decimal

from app.db.models import DutyLocation, DutyType
from app.services.adjustments import create_adjustment
from app.services.assignments import cancel_assignment, create_assignment, set_day_override
from app.services.scoring import cumulative_score, effective_duty_days
from tests.helpers import create_soldier


def _dt(session, name, score):
    dt = DutyType(name=name, score_per_day=Decimal(score))
    session.add(dt)
    session.flush()
    return dt


def _loc(session, name):
    loc = DutyLocation(name=name)
    session.add(loc)
    session.flush()
    return loc


def test_effective_days_basic_block(admin_session):
    s = create_soldier(admin_session, personal_number="8400001")
    dt = _dt(admin_session, "שמירה-sc1", "1.00")
    loc = _loc(admin_session, "מוצב-sc1")
    create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date(2026, 9, 1), end_date=date(2026, 9, 3), notes=None, actor_id=None)
    admin_session.flush()
    days = [d for d in effective_duty_days(admin_session) if d[1] == s.id]
    assert len(days) == 3


def test_cumulative_with_override_and_adjustment(admin_session):
    s = create_soldier(admin_session, personal_number="8400002")
    repl = create_soldier(admin_session, personal_number="8400003")
    dt = _dt(admin_session, "שמירה-sc2", "2.00")
    loc = _loc(admin_session, "מוצב-sc2")
    a = create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 9, 1), end_date=date(2026, 9, 3), notes=None, actor_id=None)
    admin_session.flush()
    # day 2 reassigned to repl, day 3 cancelled
    set_day_override(admin_session, assignment=a, date=date(2026, 9, 2),
                     effective_soldier_id=repl.id, reason="replacement", actor_id=None)
    set_day_override(admin_session, assignment=a, date=date(2026, 9, 3),
                     effective_soldier_id=None, reason="cancelled", actor_id=None)
    create_adjustment(admin_session, soldier_id=s.id, delta=Decimal("5.00"), reason="פיצוי", actor_id=None)
    admin_session.flush()
    # s keeps day 1 only: 1*2.00 + 5.00 adjustment = 7.00
    assert cumulative_score(admin_session, soldier_id=s.id) == Decimal("7.00")
    # repl earns day 2 only: 1*2.00
    assert cumulative_score(admin_session, soldier_id=repl.id) == Decimal("2.00")


def test_cancelled_assignment_excluded(admin_session):
    s = create_soldier(admin_session, personal_number="8400004")
    dt = _dt(admin_session, "שמירה-sc3", "3.00")
    loc = _loc(admin_session, "מוצב-sc3")
    a = create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                          start_date=date(2026, 9, 1), end_date=date(2026, 9, 2), notes=None, actor_id=None)
    admin_session.flush()
    cancel_assignment(admin_session, assignment=a, reason="בוטל", actor_id=None)
    admin_session.flush()
    assert cumulative_score(admin_session, soldier_id=s.id) == Decimal("0")
```

- [ ] **Step 2: Run — expect FAIL** (module missing).

- [ ] **Step 3: Create `backend/app/services/scoring.py`**

```python
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyDayOverride,
    DutyType,
    ExemptionDutyTypeMap,
    HierarchyNode,
    ScoreAdjustment,
    Soldier,
    SoldierExemption,
)


def _duty_type_scores(session: Session) -> dict[uuid.UUID, Decimal]:
    return {dt.id: dt.score_per_day for dt in session.execute(select(DutyType)).scalars().all()}


def effective_duty_days(
    session: Session, *, date_from: date | None = None, date_to: date | None = None
) -> list[tuple[date, uuid.UUID, uuid.UUID]]:
    """Expand every published assignment to (date, effective_soldier_id, duty_type_id) tuples,
    applying overrides (replacement reassigns; NULL effective drops the day)."""
    assignments = session.execute(
        select(DutyAssignment).where(DutyAssignment.status == "published")
    ).scalars().all()
    overrides = {
        (o.duty_assignment_id, o.date): o
        for o in session.execute(select(DutyDayOverride)).scalars().all()
    }
    out: list[tuple[date, uuid.UUID, uuid.UUID]] = []
    for a in assignments:
        day = a.start_date
        while day <= a.end_date:
            if (date_from is None or day >= date_from) and (date_to is None or day <= date_to):
                ov = overrides.get((a.id, day))
                eff = ov.effective_soldier_id if ov is not None else a.soldier_id
                if eff is not None:
                    out.append((day, eff, a.duty_type_id))
            day += timedelta(days=1)
    return out


def duty_score_by_soldier(session: Session) -> dict[uuid.UUID, Decimal]:
    scores = _duty_type_scores(session)
    out: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0"))
    for _day, eff, dtid in effective_duty_days(session):
        out[eff] += scores.get(dtid, Decimal("0"))
    return out


def adjustments_by_soldier(session: Session) -> dict[uuid.UUID, Decimal]:
    rows = session.execute(
        select(ScoreAdjustment.soldier_id, func.sum(ScoreAdjustment.delta))
        .group_by(ScoreAdjustment.soldier_id)
    ).all()
    return {sid: Decimal(total) for sid, total in rows}


def cumulative_score(session: Session, *, soldier_id: uuid.UUID) -> Decimal:
    duty = duty_score_by_soldier(session).get(soldier_id, Decimal("0"))
    adj = adjustments_by_soldier(session).get(soldier_id, Decimal("0"))
    return duty + adj
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/unit/test_scoring_service.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/app/services/scoring.py backend/tests/unit/test_scoring_service.py
git -C .. commit -m "feat(scoring): effective duty-days + cumulative score"
```

---

### Task 8: active days (full-coverage exemption), normalised, transparency, breakdown

**Files:**
- Modify: `backend/app/services/scoring.py`
- Modify: `backend/tests/unit/test_scoring_service.py`

- [ ] **Step 1: Add failing tests** — append:

```python
from datetime import timedelta

from app.db.models import ExemptionType, SoldierExemption
from app.services.duty_config import map_exemption_to_duty_type
from app.services.scoring import (
    active_days,
    normalised_score,
    soldier_score_breakdown,
    transparency_rows,
)


def test_active_days_subtracts_full_coverage_exemption(admin_session):
    s = create_soldier(admin_session, personal_number="8500001")
    s.enrolled_at = date.today() - timedelta(days=10)
    admin_session.flush()
    # one active duty type; exemption mapped to it = full coverage
    dt = _dt(admin_session, "שמירה-ad1", "1.00")
    et = ExemptionType(name="פטור-מלא-ad1")
    admin_session.add(et)
    admin_session.flush()
    map_exemption_to_duty_type(admin_session, exemption_type_id=et.id, duty_type_id=dt.id, actor_id=None)
    admin_session.add(SoldierExemption(soldier_id=s.id, exemption_type_id=et.id,
                                       start_date=date.today() - timedelta(days=4), end_date=date.today()))
    admin_session.flush()
    # raw 10 days minus 5 exempt dates (today-4 .. today inclusive) = 5
    assert active_days(admin_session, soldier=s) == 5


def test_active_days_floor_is_one(admin_session):
    s = create_soldier(admin_session, personal_number="8500002")
    s.enrolled_at = date.today()
    admin_session.flush()
    assert active_days(admin_session, soldier=s) == 1


def test_partial_coverage_does_not_reduce_active_days(admin_session):
    s = create_soldier(admin_session, personal_number="8500003")
    s.enrolled_at = date.today() - timedelta(days=10)
    admin_session.flush()
    d1 = _dt(admin_session, "שמירה-ad3a", "1.00")
    _dt(admin_session, "ניקיון-ad3b", "1.00")  # second active duty type, not covered
    et = ExemptionType(name="פטור-חלקי-ad3")
    admin_session.add(et)
    admin_session.flush()
    map_exemption_to_duty_type(admin_session, exemption_type_id=et.id, duty_type_id=d1.id, actor_id=None)
    admin_session.add(SoldierExemption(soldier_id=s.id, exemption_type_id=et.id,
                                       start_date=date.today() - timedelta(days=4), end_date=date.today()))
    admin_session.flush()
    # exemption covers only 1 of 2 active duty types -> not full coverage -> no subtraction
    assert active_days(admin_session, soldier=s) == 10


def test_normalised_and_transparency(admin_session):
    s = create_soldier(admin_session, personal_number="8500004")
    s.enrolled_at = date.today() - timedelta(days=10)
    admin_session.flush()
    dt = _dt(admin_session, "שמירה-tr", "2.00")
    loc = _loc(admin_session, "מוצב-tr")
    create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date.today() - timedelta(days=3), end_date=date.today() - timedelta(days=2),
                      notes=None, actor_id=None)
    admin_session.flush()
    # 2 days * 2.00 = 4.00 cumulative; 10 active days -> 0.40 normalised
    assert normalised_score(admin_session, soldier=s) == Decimal("4.00") / Decimal("10")
    rows = transparency_rows(admin_session)
    mine = next(r for r in rows if r["soldier_id"] == s.id)
    assert mine["cumulative_score"] == Decimal("4.00")
    assert mine["active_days"] == 10
    # sorted by normalised score descending
    norms = [r["normalised_score"] for r in rows]
    assert norms == sorted(norms, reverse=True)


def test_breakdown(admin_session):
    s = create_soldier(admin_session, personal_number="8500005")
    dt = _dt(admin_session, "שמירה-bd", "1.50")
    loc = _loc(admin_session, "מוצב-bd")
    create_assignment(admin_session, soldier_id=s.id, duty_type_id=dt.id, duty_location_id=loc.id,
                      start_date=date(2026, 9, 1), end_date=date(2026, 9, 2), notes=None, actor_id=None)
    create_adjustment(admin_session, soldier_id=s.id, delta=Decimal("3.00"), reason="פיצוי", actor_id=None)
    admin_session.flush()
    bd = soldier_score_breakdown(admin_session, soldier_id=s.id)
    assert any(pt["days"] == 2 and pt["score"] == Decimal("3.00") for pt in bd["per_type"])
    assert len(bd["adjustments"]) == 1
```

- [ ] **Step 2: Run — expect FAIL** (functions missing).

- [ ] **Step 3: Append to `backend/app/services/scoring.py`**

```python
def _active_duty_type_ids(session: Session) -> set[uuid.UUID]:
    return set(session.execute(
        select(DutyType.id).where(DutyType.active.is_(True))
    ).scalars().all())


def _full_coverage_exempt_dates(
    session: Session, *, soldier_id: uuid.UUID, start: date, end: date
) -> set[date]:
    active_dts = _active_duty_type_ids(session)
    if not active_dts:
        return set()  # no active duty types => "full coverage" is undefined; subtract nothing
    covered: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for etid, dtid in session.execute(
        select(ExemptionDutyTypeMap.exemption_type_id, ExemptionDutyTypeMap.duty_type_id)
    ).all():
        covered[etid].add(dtid)
    full_types = {etid for etid, dts in covered.items() if active_dts <= dts}
    if not full_types:
        return set()
    result: set[date] = set()
    exemptions = session.execute(
        select(SoldierExemption).where(
            SoldierExemption.soldier_id == soldier_id,
            SoldierExemption.exemption_type_id.in_(full_types),
        )
    ).scalars().all()
    for ex in exemptions:
        lo = max(ex.start_date, start)
        hi = min(ex.end_date, end) if ex.end_date is not None else end
        day = lo
        while day <= hi:
            result.add(day)
            day += timedelta(days=1)
    return result


def active_days(session: Session, *, soldier: Soldier) -> int:
    today = date.today()
    raw = (today - soldier.enrolled_at).days
    if raw < 1:
        raw = 1  # why: avoid divide-by-zero for same-day enrolment
    exempt = _full_coverage_exempt_dates(
        session, soldier_id=soldier.id, start=soldier.enrolled_at, end=today
    )
    return max(1, raw - len(exempt))


def normalised_score(session: Session, *, soldier: Soldier) -> Decimal:
    return cumulative_score(session, soldier_id=soldier.id) / Decimal(active_days(session, soldier=soldier))


def transparency_rows(session: Session) -> list[dict]:
    soldiers = session.execute(select(Soldier).where(Soldier.left_at.is_(None))).scalars().all()
    duty_scores = duty_score_by_soldier(session)
    adj_scores = adjustments_by_soldier(session)
    nodes = {n.id: n for n in session.execute(select(HierarchyNode)).scalars().all()}
    rows: list[dict] = []
    for s in soldiers:
        cum = duty_scores.get(s.id, Decimal("0")) + adj_scores.get(s.id, Decimal("0"))
        ad = active_days(session, soldier=s)
        node = nodes.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
        rows.append({
            "soldier_id": s.id,
            "full_name": s.full_name,
            "node_name": node.name if node is not None else None,
            "enrolled_at": s.enrolled_at,
            "active_days": ad,
            "cumulative_score": cum,
            "normalised_score": cum / Decimal(ad),
        })
    rows.sort(key=lambda r: r["normalised_score"], reverse=True)
    return rows


def soldier_score_breakdown(session: Session, *, soldier_id: uuid.UUID) -> dict:
    scores = _duty_type_scores(session)
    dt_names = {dt.id: dt.name for dt in session.execute(select(DutyType)).scalars().all()}
    by_type_days: dict[uuid.UUID, int] = defaultdict(int)
    for _day, eff, dtid in effective_duty_days(session):
        if eff == soldier_id:
            by_type_days[dtid] += 1
    per_type = [
        {"duty_type_id": dtid, "duty_type_name": dt_names.get(dtid), "days": days,
         "score": scores.get(dtid, Decimal("0")) * days}
        for dtid, days in by_type_days.items()
    ]
    adjustments = session.execute(
        select(ScoreAdjustment).where(ScoreAdjustment.soldier_id == soldier_id)
        .order_by(ScoreAdjustment.created_at)
    ).scalars().all()
    return {"per_type": per_type, "adjustments": list(adjustments)}
```

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/unit/test_scoring_service.py -q`
Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
git -C .. add backend/app/services/scoring.py backend/tests/unit/test_scoring_service.py
git -C .. commit -m "feat(scoring): active-days, normalised score, transparency, breakdown"
```

---

## Phase G — API routes (TDD)

### Task 9: assignments routes

**Files:**
- Create: `backend/app/routes/assignments.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_assignments_api.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_assignments_api.py
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyLocation, DutyType
from tests.helpers import auth_headers, create_soldier


def _dt_loc(session: Session, tag: str):
    dt = DutyType(name=f"שמירה-{tag}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"מוצב-{tag}")
    session.add_all([dt, loc])
    session.commit()
    return dt, loc


def test_admin_creates_and_lists(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5400001", role="admin")
    target = create_soldier(admin_session, personal_number="5400002", role="soldier")
    dt, loc = _dt_loc(admin_session, "api1")
    r = client.post("/api/assignments", headers=auth_headers(admin), json={
        "soldier_id": str(target.id), "duty_type_id": str(dt.id), "duty_location_id": str(loc.id),
        "start_date": "2026-10-01", "end_date": "2026-10-03"})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    r2 = client.get(f"/api/assignments?soldier_id={target.id}", headers=auth_headers(admin))
    assert r2.status_code == 200
    assert any(a["id"] == aid for a in r2.json())


def test_overlap_returns_409(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5400003", role="admin")
    target = create_soldier(admin_session, personal_number="5400004", role="soldier")
    dt, loc = _dt_loc(admin_session, "api2")
    body = {"soldier_id": str(target.id), "duty_type_id": str(dt.id), "duty_location_id": str(loc.id),
            "start_date": "2026-10-01", "end_date": "2026-10-05"}
    assert client.post("/api/assignments", headers=auth_headers(admin), json=body).status_code == 201
    r = client.post("/api/assignments", headers=auth_headers(admin), json={**body, "start_date": "2026-10-04"})
    assert r.status_code == 409
    assert r.json()["detail"] == "overlap"


def test_plain_soldier_forbidden_to_create(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5400005", role="soldier")
    dt, loc = _dt_loc(admin_session, "api3")
    r = client.post("/api/assignments", headers=auth_headers(s), json={
        "soldier_id": str(s.id), "duty_type_id": str(dt.id), "duty_location_id": str(loc.id),
        "start_date": "2026-10-01", "end_date": "2026-10-02"})
    assert r.status_code == 403


def test_soldier_can_list_own(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5400006", role="admin")
    s = create_soldier(admin_session, personal_number="5400007", role="soldier")
    dt, loc = _dt_loc(admin_session, "api4")
    client.post("/api/assignments", headers=auth_headers(admin), json={
        "soldier_id": str(s.id), "duty_type_id": str(dt.id), "duty_location_id": str(loc.id),
        "start_date": "2026-10-01", "end_date": "2026-10-02"})
    r = client.get(f"/api/assignments?soldier_id={s.id}", headers=auth_headers(s))
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_cancel_and_override(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5400008", role="admin")
    s = create_soldier(admin_session, personal_number="5400009", role="soldier")
    repl = create_soldier(admin_session, personal_number="5400010", role="soldier")
    dt, loc = _dt_loc(admin_session, "api5")
    aid = client.post("/api/assignments", headers=auth_headers(admin), json={
        "soldier_id": str(s.id), "duty_type_id": str(dt.id), "duty_location_id": str(loc.id),
        "start_date": "2026-10-01", "end_date": "2026-10-03"}).json()["id"]
    ro = client.put(f"/api/assignments/{aid}/overrides/2026-10-02", headers=auth_headers(admin),
                    json={"effective_soldier_id": str(repl.id), "reason": "replacement"})
    assert ro.status_code == 200, ro.text
    rc = client.post(f"/api/assignments/{aid}/cancel", headers=auth_headers(admin), json={"reason": "בוטל"})
    assert rc.status_code == 200
    assert rc.json()["status"] == "cancelled"
```

- [ ] **Step 2: Run — expect FAIL** (404 / no route).

- [ ] **Step 3: Create `backend/app/routes/assignments.py`**

```python
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, HierarchyNode, Soldier
from app.db.session import get_session
from app.services import assignments as svc

router = APIRouter(prefix="/assignments", tags=["assignments"])

_CONFLICT = {"overlap", "exempted"}


class AssignmentOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    status: str
    notes: str | None


class CreateAssignmentRequest(BaseModel):
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    notes: str | None = Field(default=None, max_length=1000)


class CancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class OverrideRequest(BaseModel):
    effective_soldier_id: uuid.UUID | None = None
    reason: str = Field(min_length=1, max_length=50)


def _out(a: DutyAssignment) -> AssignmentOut:
    return AssignmentOut(id=a.id, soldier_id=a.soldier_id, duty_type_id=a.duty_type_id,
                         duty_location_id=a.duty_location_id, start_date=a.start_date,
                         end_date=a.end_date, status=a.status, notes=a.notes)


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


def _load_soldier(session: Session, soldier_id: uuid.UUID) -> Soldier:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return s


def _load_assignment(session: Session, assignment_id: uuid.UUID) -> DutyAssignment:
    a = session.get(DutyAssignment, assignment_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return a


def _err(exc: svc.AssignmentError) -> HTTPException:
    detail = str(exc)
    code = status.HTTP_409_CONFLICT if detail in _CONFLICT else status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=detail)


@router.get("", response_model=list[AssignmentOut])
def list_assignments(
    soldier_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[AssignmentOut]:
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    rows = svc.list_assignments(session, soldier_id=soldier_id, date_from=date_from, date_to=date_to)
    return [_out(a) for a in rows]


@router.post("", response_model=AssignmentOut, status_code=status.HTTP_201_CREATED)
def create_assignment(
    body: CreateAssignmentRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> AssignmentOut:
    s = _load_soldier(session, body.soldier_id)
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=_node_of(session, s))
    try:
        a = svc.create_assignment(
            session, soldier_id=body.soldier_id, duty_type_id=body.duty_type_id,
            duty_location_id=body.duty_location_id, start_date=body.start_date,
            end_date=body.end_date, notes=body.notes, actor_id=user.id,
        )
    except svc.AssignmentError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(a)
    return _out(a)


@router.post("/{assignment_id}/cancel", response_model=AssignmentOut)
def cancel_assignment(
    assignment_id: uuid.UUID,
    body: CancelRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> AssignmentOut:
    a = _load_assignment(session, assignment_id)
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=_node_of(session, _load_soldier(session, a.soldier_id)))
    try:
        svc.cancel_assignment(session, assignment=a, reason=body.reason, actor_id=user.id)
    except svc.AssignmentError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(a)
    return _out(a)


@router.put("/{assignment_id}/overrides/{day}", status_code=status.HTTP_200_OK)
def set_override(
    assignment_id: uuid.UUID,
    day: date,
    body: OverrideRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, str]:
    a = _load_assignment(session, assignment_id)
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=_node_of(session, _load_soldier(session, a.soldier_id)))
    try:
        svc.set_day_override(session, assignment=a, date=day,
                             effective_soldier_id=body.effective_soldier_id, reason=body.reason,
                             actor_id=user.id)
    except svc.AssignmentError as exc:
        raise _err(exc) from exc
    session.commit()
    return {"status": "ok"}


@router.delete("/{assignment_id}/overrides/{day}", status_code=status.HTTP_204_NO_CONTENT)
def clear_override(
    assignment_id: uuid.UUID,
    day: date,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    a = _load_assignment(session, assignment_id)
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=_node_of(session, _load_soldier(session, a.soldier_id)))
    svc.clear_day_override(session, assignment=a, date=day, actor_id=user.id)
    session.commit()
```

- [ ] **Step 4: Wire the router in `backend/app/main.py`**

Add the import alongside the others:

```python
from app.routes import assignments as assignment_routes
```

Add the include after `soldier_routes`:

```python
    app.include_router(assignment_routes.router, prefix="/api")
```

- [ ] **Step 5: Run — expect PASS**

Run: `uv run pytest tests/integration/test_assignments_api.py -q`
Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git -C .. add backend/app/routes/assignments.py backend/app/main.py backend/tests/integration/test_assignments_api.py
git -C .. commit -m "feat(api): assignment create/list/cancel/override routes"
```

---

### Task 10: score-adjustments routes

**Files:**
- Create: `backend/app/routes/score_adjustments.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_score_adjustments_api.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_score_adjustments_api.py
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_soldier


def test_admin_creates_and_lists(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5500001", role="admin")
    s = create_soldier(admin_session, personal_number="5500002", role="soldier")
    r = client.post("/api/score-adjustments", headers=auth_headers(admin),
                    json={"soldier_id": str(s.id), "delta": "-2.50", "reason": "תיקון"})
    assert r.status_code == 201, r.text
    r2 = client.get(f"/api/score-adjustments?soldier_id={s.id}", headers=auth_headers(admin))
    assert r2.status_code == 200
    assert r2.json()[0]["delta"] == "-2.50"


def test_zero_delta_rejected(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5500003", role="admin")
    s = create_soldier(admin_session, personal_number="5500004", role="soldier")
    r = client.post("/api/score-adjustments", headers=auth_headers(admin),
                    json={"soldier_id": str(s.id), "delta": "0", "reason": "x"})
    assert r.status_code == 400
    assert r.json()["detail"] == "zero_delta"


def test_plain_soldier_forbidden(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5500005", role="soldier")
    r = client.post("/api/score-adjustments", headers=auth_headers(s),
                    json={"soldier_id": str(s.id), "delta": "1", "reason": "x"})
    assert r.status_code == 403
```

- [ ] **Step 2: Run — expect FAIL** (404).

- [ ] **Step 3: Create `backend/app/routes/score_adjustments.py`**

```python
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, ScoreAdjustment, Soldier
from app.db.session import get_session
from app.services import adjustments as svc

router = APIRouter(prefix="/score-adjustments", tags=["score-adjustments"])


class AdjustmentOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    delta: Decimal
    reason: str
    duty_type_id: uuid.UUID | None
    created_at: datetime


class CreateAdjustmentRequest(BaseModel):
    soldier_id: uuid.UUID
    delta: Decimal
    reason: str = Field(min_length=1, max_length=1000)
    duty_type_id: uuid.UUID | None = None


def _out(a: ScoreAdjustment) -> AdjustmentOut:
    return AdjustmentOut(id=a.id, soldier_id=a.soldier_id, delta=a.delta, reason=a.reason,
                         duty_type_id=a.duty_type_id, created_at=a.created_at)


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


def _load_soldier(session: Session, soldier_id: uuid.UUID) -> Soldier:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return s


@router.get("", response_model=list[AdjustmentOut])
def list_adjustments(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[AdjustmentOut]:
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    return [_out(a) for a in svc.list_adjustments(session, soldier_id=soldier_id)]


@router.post("", response_model=AdjustmentOut, status_code=status.HTTP_201_CREATED)
def create_adjustment(
    body: CreateAdjustmentRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> AdjustmentOut:
    s = _load_soldier(session, body.soldier_id)
    authorize(session, user, Action.SCORE_ADJUST, target_node=_node_of(session, s))
    try:
        adj = svc.create_adjustment(session, soldier_id=body.soldier_id, delta=body.delta,
                                    reason=body.reason, duty_type_id=body.duty_type_id, actor_id=user.id)
    except svc.AdjustmentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(adj)
    return _out(adj)
```

- [ ] **Step 4: Wire the router in `backend/app/main.py`**

```python
from app.routes import score_adjustments as score_adjustment_routes
```
```python
    app.include_router(score_adjustment_routes.router, prefix="/api")
```

- [ ] **Step 5: Run — expect PASS**

Run: `uv run pytest tests/integration/test_score_adjustments_api.py -q`
Expected: `3 passed`.

- [ ] **Step 6: Commit**

```bash
git -C .. add backend/app/routes/score_adjustments.py backend/app/main.py backend/tests/integration/test_score_adjustments_api.py
git -C .. commit -m "feat(api): score-adjustment routes"
```

---

### Task 11: scoring + calendar routes

**Files:**
- Create: `backend/app/routes/scoring.py`
- Create: `backend/app/routes/calendar.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_scoring_api.py`
- Create: `backend/tests/integration/test_calendar_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/integration/test_scoring_api.py
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyLocation, DutyType
from tests.helpers import auth_headers, create_soldier


def test_transparency_open_to_any_authed_user(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5600001", role="soldier")
    r = client.get("/api/scoring/transparency", headers=auth_headers(s))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_transparency_reflects_assignment(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5600002", role="admin")
    s = create_soldier(admin_session, personal_number="5600003", role="soldier")
    dt = DutyType(name="שמירה-sca", score_per_day=Decimal("2.00"))
    loc = DutyLocation(name="מוצב-sca")
    admin_session.add_all([dt, loc])
    admin_session.commit()
    client.post("/api/assignments", headers=auth_headers(admin), json={
        "soldier_id": str(s.id), "duty_type_id": str(dt.id), "duty_location_id": str(loc.id),
        "start_date": "2026-10-01", "end_date": "2026-10-02"})
    r = client.get("/api/scoring/transparency", headers=auth_headers(admin))
    row = next(x for x in r.json() if x["soldier_id"] == str(s.id))
    assert Decimal(row["cumulative_score"]) == Decimal("4.00")


def test_soldier_can_read_own_breakdown(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5600004", role="soldier")
    r = client.get(f"/api/scoring/soldiers/{s.id}", headers=auth_headers(s))
    assert r.status_code == 200
    assert "per_type" in r.json()


def test_soldier_cannot_read_other_breakdown(client: TestClient, admin_session: Session):
    a = create_soldier(admin_session, personal_number="5600005", role="soldier")
    b = create_soldier(admin_session, personal_number="5600006", role="soldier")
    r = client.get(f"/api/scoring/soldiers/{b.id}", headers=auth_headers(a))
    assert r.status_code == 403
```

```python
# backend/tests/integration/test_calendar_api.py
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyLocation, DutyType
from tests.helpers import auth_headers, create_soldier
from tests.helpers import create_node


def test_commander_sees_subtree_calendar(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5700001", role="admin")
    dept = create_node(admin_session, level="department", name="dep-cal")
    branch = create_node(admin_session, level="branch", name="br-cal", parent=dept)
    cmd = create_soldier(admin_session, personal_number="5700002", role="commander")
    branch.commander_id = cmd.id
    member = create_soldier(admin_session, personal_number="5700003", role="soldier",
                            hierarchy_node_id=branch.id)
    admin_session.commit()
    dt = DutyType(name="שמירה-cal", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="מוצב-cal")
    admin_session.add_all([dt, loc])
    admin_session.commit()
    client.post("/api/assignments", headers=auth_headers(admin), json={
        "soldier_id": str(member.id), "duty_type_id": str(dt.id), "duty_location_id": str(loc.id),
        "start_date": "2026-10-01", "end_date": "2026-10-02"})
    r = client.get(f"/api/calendar/unit?node_id={branch.id}", headers=auth_headers(cmd))
    assert r.status_code == 200, r.text
    rows = r.json()
    assert any(row["soldier_id"] == str(member.id) and len(row["assignments"]) == 1 for row in rows)


def test_plain_soldier_forbidden_calendar(client: TestClient, admin_session: Session):
    dept = create_node(admin_session, level="department", name="dep-cal2")
    s = create_soldier(admin_session, personal_number="5700004", role="soldier",
                       hierarchy_node_id=dept.id)
    admin_session.commit()
    r = client.get(f"/api/calendar/unit?node_id={dept.id}", headers=auth_headers(s))
    assert r.status_code == 403
```

- [ ] **Step 2: Run — expect FAIL** (404).

- [ ] **Step 3: Create `backend/app/routes/scoring.py`**

```python
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, Soldier
from app.db.session import get_session
from app.services import scoring as svc

router = APIRouter(prefix="/scoring", tags=["scoring"])


class TransparencyRow(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    node_name: str | None
    enrolled_at: date
    active_days: int
    cumulative_score: Decimal
    normalised_score: Decimal


class PerTypeRow(BaseModel):
    duty_type_id: uuid.UUID
    duty_type_name: str | None
    days: int
    score: Decimal


class AdjustmentRow(BaseModel):
    id: uuid.UUID
    delta: Decimal
    reason: str
    created_at: datetime


class BreakdownOut(BaseModel):
    per_type: list[PerTypeRow]
    adjustments: list[AdjustmentRow]


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


@router.get("/transparency", response_model=list[TransparencyRow])
def transparency(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[TransparencyRow]:
    return [TransparencyRow(**row) for row in svc.transparency_rows(session)]


@router.get("/soldiers/{soldier_id}", response_model=BreakdownOut)
def breakdown(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> BreakdownOut:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if s.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))
    data = svc.soldier_score_breakdown(session, soldier_id=soldier_id)
    return BreakdownOut(
        per_type=[PerTypeRow(**pt) for pt in data["per_type"]],
        adjustments=[AdjustmentRow(id=a.id, delta=a.delta, reason=a.reason, created_at=a.created_at)
                     for a in data["adjustments"]],
    )
```

- [ ] **Step 4: Create `backend/app/routes/calendar.py`**

```python
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, Soldier
from app.db.session import get_session
from app.services import assignments as svc

router = APIRouter(prefix="/calendar", tags=["calendar"])


class CalAssignment(BaseModel):
    id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date


class CalRow(BaseModel):
    soldier_id: uuid.UUID
    full_name: str
    assignments: list[CalAssignment]


@router.get("/unit", response_model=list[CalRow])
def unit_calendar(
    node_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[CalRow]:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    authorize(session, user, Action.HIERARCHY_READ, target_node=node)
    # nodes whose materialized path includes node_id == the subtree rooted at node
    subtree_node_ids = session.execute(
        select(HierarchyNode.id).where(HierarchyNode.path_ids.any(node_id))  # type: ignore[arg-type]
    ).scalars().all()
    soldiers = session.execute(
        select(Soldier).where(Soldier.hierarchy_node_id.in_(subtree_node_ids), Soldier.left_at.is_(None))
    ).scalars().all()
    soldier_ids = [s.id for s in soldiers]
    rows = svc.list_assignments_for_soldiers(session, soldier_ids=soldier_ids,
                                             date_from=date_from, date_to=date_to)
    by_soldier: dict[uuid.UUID, list[CalAssignment]] = {sid: [] for sid in soldier_ids}
    for a in rows:
        by_soldier[a.soldier_id].append(CalAssignment(
            id=a.id, duty_type_id=a.duty_type_id, duty_location_id=a.duty_location_id,
            start_date=a.start_date, end_date=a.end_date))
    return [CalRow(soldier_id=s.id, full_name=s.full_name, assignments=by_soldier[s.id]) for s in soldiers]
```

- [ ] **Step 5: Wire both routers in `backend/app/main.py`**

```python
from app.routes import calendar as calendar_routes
from app.routes import scoring as scoring_routes
```
```python
    app.include_router(scoring_routes.router, prefix="/api")
    app.include_router(calendar_routes.router, prefix="/api")
```

- [ ] **Step 6: Run — expect PASS**

Run: `uv run pytest tests/integration/test_scoring_api.py tests/integration/test_calendar_api.py -q`
Expected: `6 passed`.

- [ ] **Step 7: Commit**

```bash
git -C .. add backend/app/routes/scoring.py backend/app/routes/calendar.py backend/app/main.py backend/tests/integration/test_scoring_api.py backend/tests/integration/test_calendar_api.py
git -C .. commit -m "feat(api): scoring transparency/breakdown + unit calendar routes"
```

---

### Task 12: full backend gate — lint, type, whole suite

**Files:** none (verification only)

- [ ] **Step 1: Run ruff + mypy**

Run (from `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run mypy app`
Expected: no errors. Fix any reported issues (common: unused imports, line length) and re-run until clean.

- [ ] **Step 2: Run the entire backend test suite**

Run: `uv run pytest -q`
Expected: all tests pass (Slices 1–3 + the new Slice 4 unit + integration tests).

- [ ] **Step 3: Commit any lint/type fixes**

```bash
git -C .. add -A
git -C .. commit -m "chore(slice-4): lint + type fixes across new backend modules" || echo "nothing to commit"
```

---

## Phase H — Frontend

### Task 13: API clients

**Files:**
- Create: `frontend/src/api/assignments.ts`
- Create: `frontend/src/api/scoreAdjustments.ts`
- Create: `frontend/src/api/scoring.ts`
- Create: `frontend/src/api/calendar.ts`

- [ ] **Step 1: Create `frontend/src/api/assignments.ts`**

```typescript
import { api } from "./client";

export interface Assignment {
  id: string;
  soldier_id: string;
  duty_type_id: string;
  duty_location_id: string;
  start_date: string;
  end_date: string;
  status: string;
  notes: string | null;
}

export async function listAssignments(soldierId: string, params?: { date_from?: string; date_to?: string }): Promise<Assignment[]> {
  return (await api.get<Assignment[]>(`/assignments`, { params: { soldier_id: soldierId, ...params } })).data;
}
export async function createAssignment(input: {
  soldier_id: string; duty_type_id: string; duty_location_id: string; start_date: string; end_date: string; notes?: string | null;
}): Promise<Assignment> {
  return (await api.post<Assignment>(`/assignments`, input)).data;
}
export async function cancelAssignment(id: string, reason: string): Promise<Assignment> {
  return (await api.post<Assignment>(`/assignments/${id}/cancel`, { reason })).data;
}
export async function setOverride(id: string, day: string, input: { effective_soldier_id: string | null; reason: string }): Promise<void> {
  await api.put(`/assignments/${id}/overrides/${day}`, input);
}
export async function clearOverride(id: string, day: string): Promise<void> {
  await api.delete(`/assignments/${id}/overrides/${day}`);
}
```

- [ ] **Step 2: Create `frontend/src/api/scoreAdjustments.ts`**

```typescript
import { api } from "./client";

export interface ScoreAdjustment {
  id: string;
  soldier_id: string;
  delta: string;
  reason: string;
  duty_type_id: string | null;
  created_at: string;
}

export async function listAdjustments(soldierId: string): Promise<ScoreAdjustment[]> {
  return (await api.get<ScoreAdjustment[]>(`/score-adjustments`, { params: { soldier_id: soldierId } })).data;
}
export async function createAdjustment(input: { soldier_id: string; delta: string; reason: string; duty_type_id?: string | null }): Promise<ScoreAdjustment> {
  return (await api.post<ScoreAdjustment>(`/score-adjustments`, input)).data;
}
```

- [ ] **Step 3: Create `frontend/src/api/scoring.ts`**

```typescript
import { api } from "./client";

export interface TransparencyRow {
  soldier_id: string;
  full_name: string;
  node_name: string | null;
  enrolled_at: string;
  active_days: number;
  cumulative_score: string;
  normalised_score: string;
}

export interface Breakdown {
  per_type: { duty_type_id: string; duty_type_name: string | null; days: number; score: string }[];
  adjustments: { id: string; delta: string; reason: string; created_at: string }[];
}

export async function getTransparency(): Promise<TransparencyRow[]> {
  return (await api.get<TransparencyRow[]>(`/scoring/transparency`)).data;
}
export async function getBreakdown(soldierId: string): Promise<Breakdown> {
  return (await api.get<Breakdown>(`/scoring/soldiers/${soldierId}`)).data;
}
```

- [ ] **Step 4: Create `frontend/src/api/calendar.ts`**

```typescript
import { api } from "./client";

export interface CalRow {
  soldier_id: string;
  full_name: string;
  assignments: { id: string; duty_type_id: string; duty_location_id: string; start_date: string; end_date: string }[];
}

export async function getUnitCalendar(nodeId: string, params?: { date_from?: string; date_to?: string }): Promise<CalRow[]> {
  return (await api.get<CalRow[]>(`/calendar/unit`, { params: { node_id: nodeId, ...params } })).data;
}
```

- [ ] **Step 5: Type-check**

Run (from `frontend/`): `pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git -C .. add frontend/src/api/assignments.ts frontend/src/api/scoreAdjustments.ts frontend/src/api/scoring.ts frontend/src/api/calendar.ts
git -C .. commit -m "feat(frontend): api clients for assignments, adjustments, scoring, calendar"
```

---

### Task 14: i18n strings + sidebar + routes

**Files:**
- Modify: `frontend/src/i18n/he.json`
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Add strings to `frontend/src/i18n/he.json`**

Add these keys to the `nav` object (after `"duty_config"`):

```json
    "duty_management": "ניהול תורנויות",
    "transparency": "שקיפות",
    "my_duties": "היומן שלי",
    "unit_calendar": "היומן של היחידה",
```

Add these new top-level sections (after the `"duty_config"` block, before `"exemptions"`):

```json
  "duty_management": {
    "title": "ניהול תורנויות",
    "soldier": "חייל",
    "duty_type": "סוג תורנות",
    "location": "מיקום",
    "start_date": "מתאריך",
    "end_date": "עד תאריך",
    "notes": "הערות",
    "create": "צור תורנות",
    "cancel": "בטל תורנות",
    "cancel_reason": "סיבת ביטול",
    "override": "החלפה ליום",
    "override_day": "תאריך",
    "replacement": "מחליף",
    "score_adjustment": "תיקון ניקוד",
    "delta": "שינוי ניקוד",
    "reason": "סיבה",
    "apply": "החל",
    "none": "אין תורנויות"
  },
  "transparency": {
    "title": "שקיפות",
    "name": "שם",
    "unit": "יחידה",
    "enrolled_at": "תאריך הצטרפות",
    "active_days": "ימים פעילים",
    "cumulative": "ניקוד מצטבר",
    "normalised": "ניקוד מנורמל",
    "my_breakdown": "הפירוט שלי",
    "days": "ימים",
    "adjustments": "תיקוני ניקוד"
  },
  "my_duties": {
    "title": "היומן שלי",
    "duty_type": "סוג תורנות",
    "location": "מיקום",
    "from": "מתאריך",
    "to": "עד תאריך",
    "none": "אין תורנויות"
  },
  "unit_calendar": {
    "title": "היומן של היחידה",
    "soldier": "חייל",
    "duties": "תורנויות",
    "none": "אין תורנויות ביחידה"
  },
```

- [ ] **Step 2: Add sidebar entries in `frontend/src/components/Layout.tsx`**

After the existing `canManageDuties` derivation, the sidebar already computes `canManageTeam` (commander+) and `canManageDuties` (DM/admin). Add the transparency + my-duties links (all users) and the unit-calendar link (commander+) and the duty-management link (DM/admin). Replace the sidebar `<aside>` children with:

```tsx
        <Link to="/" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-home">{t("nav.home")}</Link>
        <Link to="/my-duties" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-my-duties">{t("nav.my_duties")}</Link>
        <Link to="/transparency" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-transparency">{t("nav.transparency")}</Link>
        {canManageTeam && (
          <Link to="/team" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-team">{t("nav.team_hierarchy")}</Link>
        )}
        {canManageTeam && (
          <Link to="/unit-calendar" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-unit-calendar">{t("nav.unit_calendar")}</Link>
        )}
        {canManageDuties && (
          <Link to="/duty-config" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-duty-config">{t("nav.duty_config")}</Link>
        )}
        {canManageDuties && (
          <Link to="/duty-management" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-duty-management">{t("nav.duty_management")}</Link>
        )}
        <Link to="/profile" className="block px-2 py-1 rounded hover:bg-gray-100" data-testid="nav-profile">{t("nav.profile")}</Link>
```

- [ ] **Step 3: Register routes in `frontend/src/App.tsx`**

Add the imports:

```tsx
import DutyManagementPage from "./pages/DutyManagementPage";
import MyDutiesPage from "./pages/MyDutiesPage";
import TransparencyPage from "./pages/TransparencyPage";
import UnitCalendarPage from "./pages/UnitCalendarPage";
```

Add the routes inside the `ProtectedRoute` block (after the `/duty-config` route):

```tsx
          <Route path="/duty-management" element={<ForcedPasswordGate><DutyManagementPage /></ForcedPasswordGate>} />
          <Route path="/transparency" element={<ForcedPasswordGate><TransparencyPage /></ForcedPasswordGate>} />
          <Route path="/my-duties" element={<ForcedPasswordGate><MyDutiesPage /></ForcedPasswordGate>} />
          <Route path="/unit-calendar" element={<ForcedPasswordGate><UnitCalendarPage /></ForcedPasswordGate>} />
```

> The page components don't exist yet — `pnpm tsc --noEmit` will fail until Tasks 15–18 create them. That's expected; commit this task together with Task 15's page or after all pages exist. To keep commits green, create the four pages (Tasks 15–18) before running tsc, then commit.

- [ ] **Step 4: Commit** (after pages exist — see Task 18 Step for the combined green commit; if committing now, expect tsc to fail until pages land)

```bash
git -C .. add frontend/src/i18n/he.json frontend/src/components/Layout.tsx frontend/src/App.tsx
git -C .. commit -m "feat(frontend): slice-4 i18n strings, sidebar entries, routes"
```

---

### Task 15: Transparency page

**Files:**
- Create: `frontend/src/pages/TransparencyPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/TransparencyPage.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { useAuth } from "../auth/AuthContext";
import { Breakdown, TransparencyRow, getBreakdown, getTransparency } from "../api/scoring";

export default function TransparencyPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [rows, setRows] = useState<TransparencyRow[]>([]);
  const [breakdown, setBreakdown] = useState<Breakdown | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => { void getTransparency().then(setRows); }, []);

  async function toggleOwn() {
    if (!expanded && user) setBreakdown(await getBreakdown(user.id));
    setExpanded(!expanded);
  }

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4" data-testid="transparency-page">
        <h2 className="text-xl font-semibold">{t("transparency.title")}</h2>
        <table className="w-full text-sm text-right" data-testid="transparency-table">
          <thead>
            <tr className="border-b">
              <th className="p-1">{t("transparency.name")}</th>
              <th className="p-1">{t("transparency.unit")}</th>
              <th className="p-1">{t("transparency.enrolled_at")}</th>
              <th className="p-1">{t("transparency.active_days")}</th>
              <th className="p-1">{t("transparency.cumulative")}</th>
              <th className="p-1">{t("transparency.normalised")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.soldier_id} data-testid={`transparency-row-${r.soldier_id}`}
                  className={r.soldier_id === user?.id ? "bg-indigo-50" : ""}>
                <td className="p-1">
                  {r.soldier_id === user?.id ? (
                    <button className="text-indigo-600" onClick={toggleOwn} data-testid="own-row-toggle">{r.full_name}</button>
                  ) : r.full_name}
                </td>
                <td className="p-1">{r.node_name ?? "—"}</td>
                <td className="p-1">{r.enrolled_at}</td>
                <td className="p-1">{r.active_days}</td>
                <td className="p-1">{r.cumulative_score}</td>
                <td className="p-1">{r.normalised_score}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {expanded && breakdown && (
          <div data-testid="own-breakdown" className="border-t pt-3 text-sm">
            <h3 className="font-medium">{t("transparency.my_breakdown")}</h3>
            <ul>
              {breakdown.per_type.map((pt) => (
                <li key={pt.duty_type_id}>{pt.duty_type_name ?? pt.duty_type_id}: {pt.days} {t("transparency.days")} — {pt.score}</li>
              ))}
            </ul>
            <h4 className="font-medium mt-2">{t("transparency.adjustments")}</h4>
            <ul>
              {breakdown.adjustments.map((a) => <li key={a.id}>{a.delta} — {a.reason}</li>)}
            </ul>
          </div>
        )}
      </section>
    </Layout>
  );
}
```

> Confirmed: `useAuth()` returns `user: Me | null` where `Me` (from `src/api/auth.ts`) includes `id`, `full_name`, `role`, and `hierarchy_node_id`. `user.id` is the signed-in soldier's id.

- [ ] **Step 2: Commit** (deferred green commit — see Task 18). For now:

```bash
git -C .. add frontend/src/pages/TransparencyPage.tsx
git -C .. commit -m "feat(frontend): transparency page"
```

---

### Task 16: My duties page

**Files:**
- Create: `frontend/src/pages/MyDutiesPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/MyDutiesPage.tsx`**

> Uses `user.id` from `useAuth()` (confirmed available via `Me`). Duty-type/location names come from the `dutyConfig` API (DM/admin only — see the note after the code).

```tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { useAuth } from "../auth/AuthContext";
import { Assignment, listAssignments } from "../api/assignments";
import { DutyLocation, DutyType, listDutyTypes, listLocations } from "../api/dutyConfig";

export default function MyDutiesPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [rows, setRows] = useState<Assignment[]>([]);
  const [types, setTypes] = useState<Record<string, string>>({});
  const [locs, setLocs] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!user) return;
    void (async () => {
      const [as, dts, ls]: [Assignment[], DutyType[], DutyLocation[]] = await Promise.all([
        listAssignments(user.id),
        listDutyTypes().catch(() => [] as DutyType[]),
        listLocations().catch(() => [] as DutyLocation[]),
      ]);
      setRows(as);
      setTypes(Object.fromEntries(dts.map((d) => [d.id, d.name])));
      setLocs(Object.fromEntries(ls.map((l) => [l.id, l.name])));
    })();
  }, [user]);

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4" data-testid="my-duties-page">
        <h2 className="text-xl font-semibold">{t("my_duties.title")}</h2>
        {rows.length === 0 ? (
          <p data-testid="my-duties-empty">{t("my_duties.none")}</p>
        ) : (
          <table className="w-full text-sm text-right" data-testid="my-duties-table">
            <thead>
              <tr className="border-b">
                <th className="p-1">{t("my_duties.duty_type")}</th>
                <th className="p-1">{t("my_duties.location")}</th>
                <th className="p-1">{t("my_duties.from")}</th>
                <th className="p-1">{t("my_duties.to")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id} data-testid={`my-duty-row-${a.id}`}>
                  <td className="p-1">{types[a.duty_type_id] ?? a.duty_type_id}</td>
                  <td className="p-1">{locs[a.duty_location_id] ?? a.duty_location_id}</td>
                  <td className="p-1">{a.start_date}</td>
                  <td className="p-1">{a.end_date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </Layout>
  );
}
```

> Note: `listDutyTypes`/`listLocations` require DM/admin role server-side; the `.catch(() => [])` keeps the page working for plain soldiers (who then see raw ids rather than names). This is acceptable for the slice; a public name-lookup endpoint is a later refinement.

- [ ] **Step 2: Commit**

```bash
git -C .. add frontend/src/pages/MyDutiesPage.tsx
git -C .. commit -m "feat(frontend): personal duties page"
```

---

### Task 17: Unit calendar page

**Files:**
- Create: `frontend/src/pages/UnitCalendarPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/UnitCalendarPage.tsx`**

The page lets a commander/DM pick a node and see each subtree soldier's duties. Reuse the hierarchy API to list nodes the user can see.

```tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { CalRow, getUnitCalendar } from "../api/calendar";
import { NodeDTO, fetchTree } from "../api/hierarchy";

export default function UnitCalendarPage() {
  const { t } = useTranslation();
  const [nodes, setNodes] = useState<NodeDTO[]>([]);
  const [nodeId, setNodeId] = useState<string>("");
  const [rows, setRows] = useState<CalRow[]>([]);

  useEffect(() => { void fetchTree().then((ns) => { setNodes(ns); if (ns[0]) setNodeId(ns[0].id); }); }, []);
  useEffect(() => { if (nodeId) void getUnitCalendar(nodeId).then(setRows); }, [nodeId]);

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4" data-testid="unit-calendar-page">
        <h2 className="text-xl font-semibold">{t("unit_calendar.title")}</h2>
        <select className="border rounded p-1" value={nodeId} onChange={(e) => setNodeId(e.target.value)} data-testid="unit-node-select">
          {nodes.map((n) => <option key={n.id} value={n.id}>{n.name}</option>)}
        </select>
        {rows.length === 0 ? (
          <p data-testid="unit-calendar-empty">{t("unit_calendar.none")}</p>
        ) : (
          <table className="w-full text-sm text-right" data-testid="unit-calendar-table">
            <thead>
              <tr className="border-b">
                <th className="p-1">{t("unit_calendar.soldier")}</th>
                <th className="p-1">{t("unit_calendar.duties")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.soldier_id} data-testid={`unit-row-${r.soldier_id}`}>
                  <td className="p-1">{r.full_name}</td>
                  <td className="p-1">
                    {r.assignments.map((a) => `${a.start_date}→${a.end_date}`).join(", ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </Layout>
  );
}
```

> Confirmed: `frontend/src/api/hierarchy.ts` exports `fetchTree(): Promise<NodeDTO[]>` where `NodeDTO` has `id` and `name` (Slice 2). The select lists all nodes the user can see; the backend `/calendar/unit` still authorizes the chosen `node_id` via `HIERARCHY_READ`.

- [ ] **Step 2: Commit** (deferred green commit — see Task 18). For now:

```bash
git -C .. add frontend/src/pages/UnitCalendarPage.tsx
git -C .. commit -m "feat(frontend): unit calendar page"
```

---

### Task 18: Duty management page + type-check gate

**Files:**
- Create: `frontend/src/pages/DutyManagementPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/DutyManagementPage.tsx`**

DM-facing page: pick a soldier, create an assignment, then list/cancel/override that soldier's assignments, and make a score adjustment. Reuse the soldier list + duty-config APIs.

```tsx
import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import Layout from "../components/Layout";
import { Assignment, cancelAssignment, createAssignment, listAssignments, setOverride } from "../api/assignments";
import { createAdjustment } from "../api/scoreAdjustments";
import { DutyLocation, DutyType, listDutyTypes, listLocations } from "../api/dutyConfig";
import { SoldierDTO, listSoldiers } from "../api/soldiers";

export default function DutyManagementPage() {
  const { t } = useTranslation();
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [types, setTypes] = useState<DutyType[]>([]);
  const [locs, setLocs] = useState<DutyLocation[]>([]);
  const [soldierId, setSoldierId] = useState("");
  const [typeId, setTypeId] = useState("");
  const [locId, setLocId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [rows, setRows] = useState<Assignment[]>([]);
  const [error, setError] = useState("");
  const [adjDelta, setAdjDelta] = useState("");
  const [adjReason, setAdjReason] = useState("");

  useEffect(() => {
    void (async () => {
      const [ss, dts, ls] = await Promise.all([listSoldiers(), listDutyTypes(), listLocations()]);
      setSoldiers(ss); setTypes(dts); setLocs(ls);
      if (ss[0]) setSoldierId(ss[0].id);
      if (dts[0]) setTypeId(dts[0].id);
      if (ls[0]) setLocId(ls[0].id);
    })();
  }, []);

  async function refresh(sid: string) {
    if (sid) setRows(await listAssignments(sid));
  }
  useEffect(() => { void refresh(soldierId); }, [soldierId]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await createAssignment({ soldier_id: soldierId, duty_type_id: typeId, duty_location_id: locId, start_date: start, end_date: end });
      setStart(""); setEnd("");
      await refresh(soldierId);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } }).response?.data?.detail;
      setError(detail ?? "error");
    }
  }

  async function doCancel(id: string) {
    const reason = window.prompt(t("duty_management.cancel_reason"));
    if (!reason) return;
    await cancelAssignment(id, reason);
    await refresh(soldierId);
  }

  async function doOverride(id: string) {
    const day = window.prompt(t("duty_management.override_day"));
    if (!day) return;
    const repl = window.prompt(t("duty_management.replacement"));
    await setOverride(id, day, { effective_soldier_id: repl || null, reason: repl ? "replacement" : "cancelled" });
    await refresh(soldierId);
  }

  async function submitAdj(e: FormEvent) {
    e.preventDefault();
    await createAdjustment({ soldier_id: soldierId, delta: adjDelta, reason: adjReason });
    setAdjDelta(""); setAdjReason("");
  }

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-6" data-testid="duty-management-page">
        <h2 className="text-xl font-semibold">{t("duty_management.title")}</h2>

        <label className="block text-sm">{t("duty_management.soldier")}
          <select className="block border rounded p-1" value={soldierId} onChange={(e) => setSoldierId(e.target.value)} data-testid="dm-soldier">
            {soldiers.map((s) => <option key={s.id} value={s.id}>{s.full_name}</option>)}
          </select>
        </label>

        <form onSubmit={submit} className="flex flex-wrap items-end gap-2" data-testid="assignment-form">
          <select className="border rounded p-1" value={typeId} onChange={(e) => setTypeId(e.target.value)} data-testid="dm-type">
            {types.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <select className="border rounded p-1" value={locId} onChange={(e) => setLocId(e.target.value)} data-testid="dm-loc">
            {locs.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
          <input type="date" className="border rounded p-1" value={start} onChange={(e) => setStart(e.target.value)} required data-testid="dm-start" />
          <input type="date" className="border rounded p-1" value={end} onChange={(e) => setEnd(e.target.value)} required data-testid="dm-end" />
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="dm-create">{t("duty_management.create")}</button>
        </form>
        {error && <p className="text-red-600 text-sm" data-testid="dm-error">{error}</p>}

        <ul className="text-sm space-y-1" data-testid="assignment-list">
          {rows.length === 0 && <li data-testid="dm-empty">{t("duty_management.none")}</li>}
          {rows.map((a) => (
            <li key={a.id} data-testid={`assignment-row-${a.id}`} className="flex items-center gap-2">
              <span>{a.start_date} → {a.end_date}</span>
              <button className="text-xs text-indigo-600" onClick={() => doOverride(a.id)} data-testid={`override-${a.id}`}>{t("duty_management.override")}</button>
              <button className="text-xs text-red-600" onClick={() => doCancel(a.id)} data-testid={`cancel-${a.id}`}>{t("duty_management.cancel")}</button>
            </li>
          ))}
        </ul>

        <form onSubmit={submitAdj} className="flex items-end gap-2 border-t pt-4" data-testid="adjustment-form">
          <h3 className="font-medium">{t("duty_management.score_adjustment")}</h3>
          <input className="border rounded p-1 w-24" value={adjDelta} onChange={(e) => setAdjDelta(e.target.value)} placeholder={t("duty_management.delta")} required data-testid="adj-delta" />
          <input className="border rounded p-1" value={adjReason} onChange={(e) => setAdjReason(e.target.value)} placeholder={t("duty_management.reason")} required data-testid="adj-reason" />
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="adj-submit">{t("duty_management.apply")}</button>
        </form>
      </section>
    </Layout>
  );
}
```

> Confirmed: `frontend/src/api/soldiers.ts` exports `listSoldiers(): Promise<SoldierDTO[]>` with `id` and `full_name` (Slice 2).

- [ ] **Step 2: Type-check the whole frontend**

Run (from `frontend/`): `pnpm tsc --noEmit`
Expected: no errors. Fix any mismatches against the actual `AuthContext`/`hierarchy`/`soldiers` API exports surfaced here.

- [ ] **Step 3: Lint**

Run: `pnpm eslint src`
Expected: no errors. Fix and re-run until clean.

- [ ] **Step 4: Commit**

```bash
git -C .. add frontend/src/pages/DutyManagementPage.tsx
git -C .. commit -m "feat(frontend): duty management page (assignments + overrides + adjustments)"
```

---

## Phase I — End-to-end + final verification

### Task 19: Playwright e2e

**Files:**
- Create: `frontend/tests/e2e/assignments.spec.ts`

- [ ] **Step 1: Create `frontend/tests/e2e/assignments.spec.ts`** (reuse the admin-login helper pattern from `duty_config.spec.ts`)

```typescript
import { test, expect } from "@playwright/test";

async function loginAsAdmin(page) {
  await page.goto("/login");
  await page.getByTestId("personal-number-input").fill("1000001");
  await page.getByTestId("password-input").fill("ChangeMeOnFirstLogin!");
  await page.getByTestId("login-submit").click();
  try {
    await page.waitForURL(/\/change-password$/, { timeout: 4000 });
    await page.getByTestId("current-password").fill("ChangeMeOnFirstLogin!");
    await page.getByTestId("new-password").fill("AdminNewPassw0rd");
    await page.getByTestId("change-password-submit").click();
  } catch {
    await page.getByTestId("password-input").fill("AdminNewPassw0rd");
    await page.getByTestId("login-submit").click();
  }
  await expect(page).toHaveURL("/");
}

test("admin creates a duty type, location, assignment; transparency reflects it", async ({ page }) => {
  await loginAsAdmin(page);
  const suffix = `${Date.now() % 100000}`;

  // Need a duty type + location first.
  await page.getByTestId("nav-duty-config").click();
  await page.getByTestId("dt-name").fill(`שמירה-${suffix}`);
  await page.getByTestId("dt-score").fill("2.00");
  await page.getByTestId("dt-submit").click();
  await expect(page.getByTestId(`dt-row-שמירה-${suffix}`)).toBeVisible();
  await page.getByTestId("loc-name").fill(`מוצב-${suffix}`);
  await page.getByTestId("loc-submit").click();
  await expect(page.getByTestId(`loc-row-מוצב-${suffix}`)).toBeVisible();

  // Create an assignment for the admin themselves (admin is in the soldier list).
  await page.getByTestId("nav-duty-management").click();
  await expect(page).toHaveURL(/\/duty-management$/);
  await page.getByTestId("dm-start").fill("2026-11-01");
  await page.getByTestId("dm-end").fill("2026-11-02");
  await page.getByTestId("dm-create").click();
  await expect(page.getByTestId("assignment-list").locator("li")).not.toHaveText(/^$/);

  // Transparency page renders.
  await page.getByTestId("nav-transparency").click();
  await expect(page.getByTestId("transparency-table")).toBeVisible();
});
```

> The DM page's soldier dropdown defaults to the first soldier returned by `listSoldiers()`; for the bootstrap admin that includes themselves. If the suite seeds differently, target a known soldier via the dropdown (`page.getByTestId("dm-soldier").selectOption({ label: ... })`) before creating.

- [ ] **Step 2: Run the e2e suite**

Run (from `frontend/`): `pnpm test:e2e assignments.spec.ts` (or the project's configured e2e command — check `package.json` scripts; Slice 3 used the same runner).
Expected: the new spec passes. If the runner needs the backend + frontend up, follow the same harness the existing specs use (check `playwright.config.ts` `webServer`).

- [ ] **Step 3: Commit**

```bash
git -C .. add frontend/tests/e2e/assignments.spec.ts
git -C .. commit -m "test(e2e): assignment creation + transparency render"
```

---

### Task 20: Final full verification

**Files:** none (verification + optional merge)

- [ ] **Step 1: Backend — full gate**

Run (from `backend/`): `uv run ruff check . && uv run mypy app && uv run alembic check && uv run pytest -q`
Expected: all green.

- [ ] **Step 2: Frontend — full gate**

Run (from `frontend/`): `pnpm tsc --noEmit && pnpm eslint src && pnpm test:e2e`
Expected: all green.

- [ ] **Step 3: Confirm the OpenAPI client is in sync (if the repo generates one)**

Check whether the repo has an OpenAPI-client generation step (Slices 1–3 mention a generated TS client in the design). If a generation script exists (e.g. `pnpm gen:api`), run it and commit any diff. If the FE hand-writes its clients (as in `src/api/*.ts` here), skip.

- [ ] **Step 4: Merge to master** (per the project's no-PR-by-default workflow)

```bash
git -C .. checkout master
git -C .. merge --no-ff slice-4-assignments-scoring-transparency -m "Merge slice 4: duty assignments, scoring & transparency"
```

> Confirm with the user before pushing.

---

## Self-review notes

- **Spec coverage:** tables (Task 1–2), authz (Task 3), assignments + overlap/exemption (Task 4), overrides (Task 5), adjustments (Task 6), scoring incl. active-days full-coverage + transparency + breakdown (Tasks 7–8), all API routes (Tasks 9–11), RBAC asserted in integration tests (Tasks 9–11), four frontend surfaces (Tasks 14–18), e2e (Task 19). All spec sections map to a task.
- **Status model:** `published` default, `proposed` reserved, `cancelled` excluded from scoring/overlap — consistent across migration CHECK, model default, `effective_duty_days` filter, and `_has_overlap`.
- **Naming consistency:** service functions (`create_assignment`, `cancel_assignment`, `set_day_override`, `clear_day_override`, `list_assignments`, `list_assignments_for_soldiers`, `create_adjustment`, `cumulative_score`, `active_days`, `normalised_score`, `transparency_rows`, `soldier_score_breakdown`) match between their defining task and their callers in routes.
- **Integration touch-points confirmed against real exports** (during plan authoring): `useAuth().user` is `Me` with `id` (`src/api/auth.ts`); `api/hierarchy.ts` exports `fetchTree(): NodeDTO[]`; `api/soldiers.ts` exports `listSoldiers(): SoldierDTO[]`; `test_authz.py` already imports `authz`, `create_node`, `create_soldier`, and defines `_roots`. The only item to confirm at execution time is the frontend e2e runner command (check `frontend/package.json` scripts + `playwright.config.ts`), since Slice 3's e2e harness command was not re-read here.
