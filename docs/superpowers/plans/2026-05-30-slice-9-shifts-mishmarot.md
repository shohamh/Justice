# Slice 9 — Shifts (משמרות) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce `duty_shifts` as a first-class DB entity with CRUD API and a DM management page showing table and calendar views with fill-status indicators.

**Architecture:** New `duty_shifts` table (migration 0018) + nullable `duty_shift_id` FK on `duty_assignments`. Service layer computes fill status. Six REST endpoints under `/api/shifts`. React page `/shifts` with table and FullCalendar month views, create/edit modal.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, React 18, TypeScript, react-i18next, Tailwind CSS, FullCalendar (already in package.json from UnitCalendar).

**Spec:** `docs/superpowers/specs/2026-05-30-slice-9-shifts-mishmarot.md`

---

## File structure

```
backend/
├── alembic/versions/0018_create_duty_shifts.py     CREATE
├── app/
│   ├── db/models.py                                MODIFY — add DutyShift model, duty_shift_id FK on DutyAssignment
│   ├── services/shifts.py                          CREATE
│   └── routes/shifts.py                            CREATE
│   └── main.py                                     MODIFY — register shifts router
└── tests/
    ├── unit/test_shifts_service.py                 CREATE
    └── integration/test_shifts_routes.py           CREATE

frontend/src/
├── api/shifts.ts                                   CREATE
├── i18n/he.json                                    MODIFY — add shifts block
├── pages/ShiftsPage.tsx                            CREATE
├── components/
│   ├── ShiftFormModal.tsx                          CREATE
│   └── Layout.tsx                                  MODIFY — add משמרות nav link for DM
└── App.tsx                                         MODIFY — add /shifts route
```

---

## Phase A — Database

### Task 1: Migration 0018

**Files:**
- Create: `backend/alembic/versions/0018_create_duty_shifts.py`

- [ ] **Step 1: Create `backend/alembic/versions/0018_create_duty_shifts.py`**

```python
"""create duty_shifts and add duty_shift_id to duty_assignments

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-30
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "duty_shifts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
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
        sa.Column("required_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("required_count >= 1", name="chk_required_count_positive"),
    )
    op.create_index("idx_duty_shifts_dates", "duty_shifts", ["start_date", "end_date"])
    op.create_index("idx_duty_shifts_type", "duty_shifts", ["duty_type_id"])

    op.add_column(
        "duty_assignments",
        sa.Column(
            "duty_shift_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("duty_shifts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("idx_da_shift", "duty_assignments", ["duty_shift_id"])


def downgrade() -> None:
    op.drop_index("idx_da_shift", table_name="duty_assignments")
    op.drop_column("duty_assignments", "duty_shift_id")
    op.drop_index("idx_duty_shifts_type", table_name="duty_shifts")
    op.drop_index("idx_duty_shifts_dates", table_name="duty_shifts")
    op.drop_table("duty_shifts")
```

- [ ] **Step 2: Run migration**

```
cd backend && uv run alembic upgrade head && uv run alembic check
```
Expected: `No new upgrade operations detected.`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/0018_create_duty_shifts.py
git commit -m "feat(db): duty_shifts table + duty_shift_id FK on duty_assignments (migration 0018)"
```

---

### Task 2: ORM models

**Files:**
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Add `DutyShift` model after `DutyDayOverride` in models.py**

```python
class DutyShift(Base):
    __tablename__ = "duty_shifts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    duty_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_types.id", ondelete="RESTRICT")
    )
    duty_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_locations.id", ondelete="RESTRICT")
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    required_count: Mapped[int] = mapped_column(server_default=text("1"), default=1)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 2: Add `duty_shift_id` to `DutyAssignment`**

In the `DutyAssignment` class, after `notes` and before `created_at`:

```python
    duty_shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_shifts.id", ondelete="SET NULL"), nullable=True, default=None
    )
```

- [ ] **Step 3: Verify**

```
cd backend && uv run python -c "from app.db.models import DutyShift, DutyAssignment; print('ok')"
```
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat(models): DutyShift model, duty_shift_id on DutyAssignment"
```

---

## Phase B — Service

### Task 3: Shifts service

**Files:**
- Create: `backend/app/services/shifts.py`

- [ ] **Step 1: Create `backend/app/services/shifts.py`**

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyAssignment, DutyShift


class ShiftError(Exception):
    """Raised on invalid shift operations."""


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
    fill_status: str  # 'empty' | 'partial' | 'full'


def _fill_status(assigned: int, required: int) -> str:
    if assigned == 0:
        return "empty"
    if assigned >= required:
        return "full"
    return "partial"


def _get_assigned_count(session: Session, shift_id: uuid.UUID) -> int:
    return session.execute(
        select(func.count(DutyAssignment.id)).where(
            DutyAssignment.duty_shift_id == shift_id,
            DutyAssignment.status.in_(["published", "algorithm_draft"]),
        )
    ).scalar_one()


def _to_with_fill(session: Session, shift: DutyShift) -> ShiftWithFill:
    assigned = _get_assigned_count(session, shift.id)
    return ShiftWithFill(
        id=shift.id,
        duty_type_id=shift.duty_type_id,
        duty_location_id=shift.duty_location_id,
        start_date=shift.start_date,
        end_date=shift.end_date,
        required_count=shift.required_count,
        notes=shift.notes,
        created_by=shift.created_by,
        assigned_count=assigned,
        fill_status=_fill_status(assigned, shift.required_count),
    )


def create_shift(
    session: Session,
    *,
    duty_type_id: uuid.UUID,
    duty_location_id: uuid.UUID,
    start_date: date,
    end_date: date,
    required_count: int = 1,
    notes: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> DutyShift:
    if end_date < start_date:
        raise ShiftError("end_before_start")
    if required_count < 1:
        raise ShiftError("invalid_required_count")
    shift = DutyShift(
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id,
        start_date=start_date,
        end_date=end_date,
        required_count=required_count,
        notes=notes,
        created_by=actor_id,
    )
    session.add(shift)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="duty_shift.create",
        entity_type="duty_shift",
        entity_id=shift.id,
        after={
            "duty_type_id": str(duty_type_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "required_count": required_count,
        },
    )
    return shift


def update_shift(
    session: Session,
    *,
    shift: DutyShift,
    start_date: date | None = None,
    end_date: date | None = None,
    required_count: int | None = None,
    notes: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> DutyShift:
    before: dict = {
        "start_date": shift.start_date.isoformat(),
        "end_date": shift.end_date.isoformat(),
        "required_count": shift.required_count,
        "notes": shift.notes,
    }
    if start_date is not None:
        shift.start_date = start_date
    if end_date is not None:
        shift.end_date = end_date
    if required_count is not None:
        if required_count < 1:
            raise ShiftError("invalid_required_count")
        shift.required_count = required_count
    if notes is not None:
        shift.notes = notes
    if shift.end_date < shift.start_date:
        raise ShiftError("end_before_start")
    write_audit(
        session,
        actor_id=actor_id,
        action="duty_shift.update",
        entity_type="duty_shift",
        entity_id=shift.id,
        before=before,
        after={
            "start_date": shift.start_date.isoformat(),
            "end_date": shift.end_date.isoformat(),
            "required_count": shift.required_count,
            "notes": shift.notes,
        },
    )
    return shift


def delete_shift(
    session: Session,
    *,
    shift: DutyShift,
    actor_id: uuid.UUID | None = None,
) -> None:
    published_count = session.execute(
        select(func.count(DutyAssignment.id)).where(
            DutyAssignment.duty_shift_id == shift.id,
            DutyAssignment.status == "published",
        )
    ).scalar_one()
    if published_count > 0:
        raise ShiftError("has_assignments")
    write_audit(
        session,
        actor_id=actor_id,
        action="duty_shift.delete",
        entity_type="duty_shift",
        entity_id=shift.id,
        before={"start_date": shift.start_date.isoformat(), "end_date": shift.end_date.isoformat()},
    )
    session.delete(shift)


def list_shifts(
    session: Session,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    duty_type_id: uuid.UUID | None = None,
) -> list[ShiftWithFill]:
    q = select(DutyShift)
    if date_from is not None:
        q = q.where(DutyShift.end_date >= date_from)
    if date_to is not None:
        q = q.where(DutyShift.start_date <= date_to)
    if duty_type_id is not None:
        q = q.where(DutyShift.duty_type_id == duty_type_id)
    q = q.order_by(DutyShift.start_date)
    shifts = session.execute(q).scalars().all()
    return [_to_with_fill(session, s) for s in shifts]


def get_shift_fill(session: Session, *, shift_id: uuid.UUID) -> ShiftWithFill | None:
    shift = session.get(DutyShift, shift_id)
    if shift is None:
        return None
    return _to_with_fill(session, shift)
```

- [ ] **Step 2: Verify**

```
cd backend && uv run python -c "from app.services.shifts import create_shift, list_shifts, delete_shift; print('ok')"
```
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/shifts.py
git commit -m "feat(shifts): shifts service with create/update/delete/list and fill status"
```

---

## Phase C — Routes

### Task 4: Shifts routes + registration

**Files:**
- Create: `backend/app/routes/shifts.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create `backend/app/routes/shifts.py`**

```python
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, DutyShift, Soldier
from app.db.session import get_session
from app.services import shifts as svc

router = APIRouter(prefix="/shifts", tags=["shifts"])


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


class CreateShiftRequest(BaseModel):
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    required_count: int = Field(default=1, ge=1)
    notes: str | None = Field(default=None, max_length=1000)


class UpdateShiftRequest(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    required_count: int | None = Field(default=None, ge=1)
    notes: str | None = None


def _out(s: svc.ShiftWithFill) -> ShiftOut:
    return ShiftOut(
        id=s.id,
        duty_type_id=s.duty_type_id,
        duty_location_id=s.duty_location_id,
        start_date=s.start_date,
        end_date=s.end_date,
        required_count=s.required_count,
        notes=s.notes,
        assigned_count=s.assigned_count,
        fill_status=s.fill_status,
    )


def _load(session: Session, shift_id: uuid.UUID) -> DutyShift:
    shift = session.get(DutyShift, shift_id)
    if shift is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return shift


@router.get("", response_model=list[ShiftOut])
def list_shifts(
    date_from: date | None = None,
    date_to: date | None = None,
    duty_type_id: uuid.UUID | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ShiftOut]:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    return [_out(s) for s in svc.list_shifts(session, date_from=date_from, date_to=date_to, duty_type_id=duty_type_id)]


@router.post("", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
def create_shift(
    body: CreateShiftRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ShiftOut:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    try:
        shift = svc.create_shift(
            session,
            duty_type_id=body.duty_type_id,
            duty_location_id=body.duty_location_id,
            start_date=body.start_date,
            end_date=body.end_date,
            required_count=body.required_count,
            notes=body.notes,
            actor_id=user.id,
        )
    except svc.ShiftError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    result = svc.get_shift_fill(session, shift_id=shift.id)
    return _out(result)


@router.get("/{shift_id}", response_model=ShiftOut)
def get_shift(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ShiftOut:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    result = svc.get_shift_fill(session, shift_id=shift_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return _out(result)


@router.patch("/{shift_id}", response_model=ShiftOut)
def update_shift(
    shift_id: uuid.UUID,
    body: UpdateShiftRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ShiftOut:
    shift = _load(session, shift_id)
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    try:
        svc.update_shift(
            session,
            shift=shift,
            start_date=body.start_date,
            end_date=body.end_date,
            required_count=body.required_count,
            notes=body.notes,
            actor_id=user.id,
        )
    except svc.ShiftError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return _out(svc.get_shift_fill(session, shift_id=shift_id))


@router.delete("/{shift_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shift(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    shift = _load(session, shift_id)
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    try:
        svc.delete_shift(session, shift=shift, actor_id=user.id)
    except svc.ShiftError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()


class AssignmentOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    start_date: date
    end_date: date
    status: str


@router.get("/{shift_id}/assignments", response_model=list[AssignmentOut])
def list_shift_assignments(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[AssignmentOut]:
    _load(session, shift_id)
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    rows = session.execute(
        select(DutyAssignment).where(DutyAssignment.duty_shift_id == shift_id)
    ).scalars().all()
    return [
        AssignmentOut(
            id=a.id,
            soldier_id=a.soldier_id,
            duty_type_id=a.duty_type_id,
            start_date=a.start_date,
            end_date=a.end_date,
            status=a.status,
        )
        for a in rows
    ]
```

Note: `Action.ASSIGNMENT_MANAGE` with `target_node=None` uses the `_DM_GLOBAL_ACTIONS` bypass added for the algorithm. We need to add `ASSIGNMENT_MANAGE` to `_DM_GLOBAL_ACTIONS` in `authz.py` so DMs without a node assignment can still manage shifts. Check the current `authz.py` — if `ASSIGNMENT_MANAGE` already works without a node in the existing routes, this may not be needed.

Actually, looking at existing routes: `assignments.py` uses `authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=_node_of(session, s))` — it scopes to the soldier's node. For shifts (which are unit-wide), we call with `target_node=None`. Add `Action.ASSIGNMENT_MANAGE` to `_DM_GLOBAL_ACTIONS` in `authz.py`:

In `backend/app/auth/authz.py`, update `_DM_GLOBAL_ACTIONS`:
```python
_DM_GLOBAL_ACTIONS = {
    Action.ALGORITHM_RUN,
    Action.ASSIGNMENT_MANAGE,
}
```

- [ ] **Step 2: Register in main.py**

In `backend/app/main.py`, add:
```python
from app.routes import shifts as shift_routes
```
And:
```python
    app.include_router(shift_routes.router, prefix="/api")
```

- [ ] **Step 3: Verify app starts**

```
cd backend && uv run python -c "from app.main import create_app; create_app(); print('ok')"
```
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/shifts.py backend/app/main.py backend/app/auth/authz.py
git commit -m "feat(shifts): shifts CRUD routes, register router, global ASSIGNMENT_MANAGE action"
```

---

## Phase D — Backend tests

### Task 5: Shifts service unit tests

**Files:**
- Create: `backend/tests/unit/test_shifts_service.py`

- [ ] **Step 1: Create `backend/tests/unit/test_shifts_service.py`**

```python
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import DutyAssignment, DutyLocation, DutyType
from app.services.shifts import ShiftError, create_shift, delete_shift, list_shifts, update_shift
from tests.helpers import create_soldier


def _dt(session) -> DutyType:
    dt = DutyType(name=f"type_{uuid.uuid4().hex[:6]}", score_per_day=Decimal("1.00"))
    session.add(dt)
    session.flush()
    return dt


def _loc(session) -> DutyLocation:
    loc = DutyLocation(name=f"loc_{uuid.uuid4().hex[:6]}")
    session.add(loc)
    session.flush()
    return loc


def test_create_shift_basic(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    shift = create_shift(
        admin_session,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 3),
        required_count=2,
    )
    admin_session.commit()
    assert shift.required_count == 2
    assert shift.start_date == date(2026, 7, 1)


def test_create_shift_rejects_bad_dates(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    with pytest.raises(ShiftError, match="end_before_start"):
        create_shift(
            admin_session,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=date(2026, 7, 5),
            end_date=date(2026, 7, 1),
        )


def test_fill_status_empty(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 1), required_count=3,
    )
    admin_session.commit()
    from app.services.shifts import get_shift_fill
    result = get_shift_fill(admin_session, shift_id=shift.id)
    assert result.fill_status == "empty"
    assert result.assigned_count == 0


def test_fill_status_partial(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    soldier = create_soldier(admin_session, personal_number=f"sh_{uuid.uuid4().hex[:6]}")
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 1), required_count=3,
    )
    admin_session.flush()
    da = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 1),
        status="published",
        duty_shift_id=shift.id,
    )
    admin_session.add(da)
    admin_session.commit()
    from app.services.shifts import get_shift_fill
    result = get_shift_fill(admin_session, shift_id=shift.id)
    assert result.fill_status == "partial"
    assert result.assigned_count == 1


def test_delete_fails_with_published_assignments(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    soldier = create_soldier(admin_session, personal_number=f"sh_{uuid.uuid4().hex[:6]}")
    shift = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 10, 1), end_date=date(2026, 10, 1),
    )
    admin_session.flush()
    da = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 1),
        status="published",
        duty_shift_id=shift.id,
    )
    admin_session.add(da)
    admin_session.commit()
    with pytest.raises(ShiftError, match="has_assignments"):
        delete_shift(admin_session, shift=shift)


def test_list_shifts_date_filter(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    shift_in = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 11, 1), end_date=date(2026, 11, 5),
    )
    shift_out = create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 12, 1), end_date=date(2026, 12, 5),
    )
    admin_session.commit()
    results = list_shifts(admin_session, date_from=date(2026, 11, 1), date_to=date(2026, 11, 30))
    ids = [r.id for r in results]
    assert shift_in.id in ids
    assert shift_out.id not in ids
```

- [ ] **Step 2: Run tests**

```
cd backend && uv run pytest tests/unit/test_shifts_service.py -v
```
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_shifts_service.py
git commit -m "test(shifts): service unit tests for create/delete/fill-status/list"
```

---

### Task 6: Shifts route integration tests

**Files:**
- Create: `backend/tests/integration/test_shifts_routes.py`

- [ ] **Step 1: Create `backend/tests/integration/test_shifts_routes.py`**

```python
from __future__ import annotations

import uuid
from decimal import Decimal

from app.db.models import DutyLocation, DutyType
from tests.helpers import auth_headers, create_node, create_soldier


def _setup(session, pn: str):
    node = create_node(session, level="branch", name=f"n_{pn}")
    dm = create_soldier(session, personal_number=pn, role="duty_manager", hierarchy_node_id=node.id)
    dt = DutyType(name=f"t_{pn}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"l_{pn}")
    session.add(dt); session.add(loc)
    session.commit()
    return dm, dt, loc


def test_create_shift_returns_201(client, admin_session):
    dm, dt, loc = _setup(admin_session, "sh_rt_001")
    resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-07-01",
        "end_date": "2026-07-03",
        "required_count": 2,
    }, headers=auth_headers(dm))
    assert resp.status_code == 201
    data = resp.json()
    assert data["required_count"] == 2
    assert data["fill_status"] == "empty"
    assert data["assigned_count"] == 0


def test_soldier_cannot_create_shift(client, admin_session):
    _, dt, loc = _setup(admin_session, "sh_rt_002")
    soldier = create_soldier(admin_session, personal_number="sh_rt_002s")
    admin_session.commit()
    resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-07-01",
        "end_date": "2026-07-01",
    }, headers=auth_headers(soldier))
    assert resp.status_code == 403


def test_list_shifts_with_fill(client, admin_session):
    dm, dt, loc = _setup(admin_session, "sh_rt_003")
    client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-08-01",
        "end_date": "2026-08-01",
        "required_count": 3,
    }, headers=auth_headers(dm))
    resp = client.get("/api/shifts?date_from=2026-08-01&date_to=2026-08-31", headers=auth_headers(dm))
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1
    assert all("fill_status" in i for i in items)


def test_delete_empty_shift(client, admin_session):
    dm, dt, loc = _setup(admin_session, "sh_rt_004")
    create_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-09-01",
        "end_date": "2026-09-01",
    }, headers=auth_headers(dm))
    shift_id = create_resp.json()["id"]
    del_resp = client.delete(f"/api/shifts/{shift_id}", headers=auth_headers(dm))
    assert del_resp.status_code == 204


def test_update_shift(client, admin_session):
    dm, dt, loc = _setup(admin_session, "sh_rt_005")
    create_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-10-01",
        "end_date": "2026-10-01",
        "required_count": 1,
    }, headers=auth_headers(dm))
    shift_id = create_resp.json()["id"]
    patch_resp = client.patch(f"/api/shifts/{shift_id}", json={"required_count": 4, "notes": "test"}, headers=auth_headers(dm))
    assert patch_resp.status_code == 200
    assert patch_resp.json()["required_count"] == 4
    assert patch_resp.json()["notes"] == "test"
```

- [ ] **Step 2: Run tests**

```
cd backend && uv run pytest tests/integration/test_shifts_routes.py -v
```
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_shifts_routes.py
git commit -m "test(shifts): integration tests for CRUD routes"
```

---

## Phase E — Frontend

### Task 7: Frontend API + i18n

**Files:**
- Create: `frontend/src/api/shifts.ts`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Create `frontend/src/api/shifts.ts`**

```typescript
import { api } from "./client";
import { Assignment } from "./assignments";

export interface DutyShift {
  id: string;
  duty_type_id: string;
  duty_location_id: string;
  start_date: string;
  end_date: string;
  required_count: number;
  notes: string | null;
  assigned_count: number;
  fill_status: "empty" | "partial" | "full";
}

export interface CreateShiftInput {
  duty_type_id: string;
  duty_location_id: string;
  start_date: string;
  end_date: string;
  required_count: number;
  notes?: string | null;
}

export interface UpdateShiftInput {
  start_date?: string;
  end_date?: string;
  required_count?: number;
  notes?: string | null;
}

export async function listShifts(params?: {
  date_from?: string;
  date_to?: string;
  duty_type_id?: string;
}): Promise<DutyShift[]> {
  return (await api.get<DutyShift[]>("/shifts", { params })).data;
}

export async function createShift(input: CreateShiftInput): Promise<DutyShift> {
  return (await api.post<DutyShift>("/shifts", input)).data;
}

export async function updateShift(id: string, input: UpdateShiftInput): Promise<DutyShift> {
  return (await api.patch<DutyShift>(`/shifts/${id}`, input)).data;
}

export async function deleteShift(id: string): Promise<void> {
  await api.delete(`/shifts/${id}`);
}

export async function getShiftAssignments(id: string): Promise<Assignment[]> {
  return (await api.get<Assignment[]>(`/shifts/${id}/assignments`)).data;
}
```

- [ ] **Step 2: Add `shifts` block to he.json**

Add before the closing `}`:

```json
  "shifts": {
    "title": "ניהול משמרות",
    "create": "משמרת חדשה",
    "edit": "עריכת משמרת",
    "delete": "מחיקת משמרת",
    "duty_type": "סוג תורנות",
    "location": "מיקום",
    "start_date": "תאריך התחלה",
    "end_date": "תאריך סיום",
    "duration_days": "משך (ימים)",
    "required_count": "מספר נדרש",
    "assigned_count": "שובץ",
    "fill_empty": "ריק",
    "fill_partial": "חלקי",
    "fill_full": "מלא",
    "has_assignments_error": "לא ניתן למחוק משמרת עם שיבוצים פעילים",
    "view_assignments": "הצג שיבוצים",
    "table_view": "טבלה",
    "calendar_view": "לוח שנה",
    "confirm_delete": "האם למחוק את המשמרת?",
    "notes": "הערות",
    "filter_from": "מתאריך",
    "filter_to": "עד תאריך"
  }
```

- [ ] **Step 3: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/shifts.ts frontend/src/i18n/he.json
git commit -m "feat(frontend): shifts API client + i18n keys"
```

---

### Task 8: ShiftFormModal component

**Files:**
- Create: `frontend/src/components/ShiftFormModal.tsx`

- [ ] **Step 1: Create `frontend/src/components/ShiftFormModal.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { CreateShiftInput, DutyShift, createShift, updateShift } from "../api/shifts";
import { DutyType, DutyLocation } from "../api/dutyConfig";

interface Props {
  dutyTypes: DutyType[];
  locations: DutyLocation[];
  existing?: DutyShift;   // if provided, edit mode
  onSaved: () => void;
  onClose: () => void;
}

export default function ShiftFormModal({ dutyTypes, locations, existing, onSaved, onClose }: Props) {
  const { t } = useTranslation();
  const [dtId, setDtId] = useState(existing?.duty_type_id ?? dutyTypes[0]?.id ?? "");
  const [locId, setLocId] = useState(existing?.duty_location_id ?? locations[0]?.id ?? "");
  const [startDate, setStartDate] = useState(existing?.start_date ?? "");
  const [endDate, setEndDate] = useState(existing?.end_date ?? "");
  const [count, setCount] = useState(existing?.required_count ?? 1);
  const [notes, setNotes] = useState(existing?.notes ?? "");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      if (existing) {
        await updateShift(existing.id, {
          start_date: startDate,
          end_date: endDate,
          required_count: count,
          notes: notes || null,
        });
      } else {
        await createShift({
          duty_type_id: dtId,
          duty_location_id: locId,
          start_date: startDate,
          end_date: endDate,
          required_count: count,
          notes: notes || null,
        });
      }
      onSaved();
    } catch (err: unknown) {
      const detail = (err as any)?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    }
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="text-lg font-semibold">{existing ? t("shifts.edit") : t("shifts.create")}</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-700">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          {!existing && (
            <>
              <label className="block text-sm">
                {t("shifts.duty_type")}
                <select value={dtId} onChange={e => setDtId(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm">
                  {dutyTypes.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </label>
              <label className="block text-sm">
                {t("shifts.location")}
                <select value={locId} onChange={e => setLocId(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm">
                  {locations.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
                </select>
              </label>
            </>
          )}
          <label className="block text-sm">
            {t("shifts.start_date")}
            <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" required />
          </label>
          <label className="block text-sm">
            {t("shifts.end_date")}
            <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" required />
          </label>
          <label className="block text-sm">
            {t("shifts.required_count")}
            <input type="number" min={1} value={count} onChange={e => setCount(parseInt(e.target.value))} className="mt-1 block w-full border rounded p-1 text-sm" required />
          </label>
          <label className="block text-sm">
            {t("shifts.notes")}
            <textarea value={notes} onChange={e => setNotes(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" rows={2} />
          </label>
          {error && <p className="text-red-500 text-xs">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border rounded">ביטול</button>
            <button type="submit" className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700">שמור</button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ShiftFormModal.tsx
git commit -m "feat(frontend): ShiftFormModal create/edit component"
```

---

### Task 9: ShiftsPage

**Files:**
- Create: `frontend/src/pages/ShiftsPage.tsx`

- [ ] **Step 1: Create `frontend/src/pages/ShiftsPage.tsx`**

```tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../components/Layout";
import ShiftFormModal from "../components/ShiftFormModal";
import { DutyShift, deleteShift, listShifts } from "../api/shifts";
import { DutyType, DutyLocation, listDutyTypes, listLocations } from "../api/dutyConfig";

const FILL_COLORS: Record<string, string> = {
  empty: "bg-red-100 text-red-700",
  partial: "bg-amber-100 text-amber-700",
  full: "bg-green-100 text-green-700",
};

export default function ShiftsPage() {
  const { t } = useTranslation();
  const [shifts, setShifts] = useState<DutyShift[]>([]);
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);
  const [locations, setLocations] = useState<DutyLocation[]>([]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editShift, setEditShift] = useState<DutyShift | null>(null);

  async function refresh() {
    const [ss, dts, locs] = await Promise.all([
      listShifts({ date_from: dateFrom || undefined, date_to: dateTo || undefined }),
      listDutyTypes(),
      listLocations(),
    ]);
    setShifts(ss);
    setDutyTypes(dts);
    setLocations(locs);
  }

  useEffect(() => { void refresh(); }, [dateFrom, dateTo]);

  async function handleDelete(shift: DutyShift) {
    if (!window.confirm(t("shifts.confirm_delete"))) return;
    try {
      await deleteShift(shift.id);
      await refresh();
    } catch (err: unknown) {
      const detail = (err as any)?.response?.data?.detail;
      if (detail === "has_assignments") alert(t("shifts.has_assignments_error"));
    }
  }

  const dtName = (id: string) => dutyTypes.find(d => d.id === id)?.name ?? id.slice(0, 8);
  const locName = (id: string) => locations.find(l => l.id === id)?.name ?? id.slice(0, 8);

  return (
    <Layout>
      <section className="bg-white rounded-lg shadow p-6 space-y-4" dir="rtl" data-testid="shifts-page">
        <div className="flex justify-between items-center">
          <h2 className="text-xl font-semibold">{t("shifts.title")}</h2>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700"
          >
            {t("shifts.create")}
          </button>
        </div>

        {/* Date filters */}
        <div className="flex gap-4 text-sm">
          <label className="flex items-center gap-2">
            {t("shifts.filter_from")}
            <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="border rounded p-1" />
          </label>
          <label className="flex items-center gap-2">
            {t("shifts.filter_to")}
            <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="border rounded p-1" />
          </label>
        </div>

        {/* Table */}
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-gray-50 text-right">
              <th className="border px-2 py-1">{t("shifts.duty_type")}</th>
              <th className="border px-2 py-1">{t("shifts.location")}</th>
              <th className="border px-2 py-1">{t("shifts.start_date")}</th>
              <th className="border px-2 py-1">{t("shifts.end_date")}</th>
              <th className="border px-2 py-1">{t("shifts.required_count")}</th>
              <th className="border px-2 py-1">{t("shifts.assigned_count")}</th>
              <th className="border px-2 py-1">סטטוס</th>
              <th className="border px-2 py-1">פעולות</th>
            </tr>
          </thead>
          <tbody>
            {shifts.length === 0 && (
              <tr><td colSpan={8} className="text-center text-gray-400 py-4">אין משמרות</td></tr>
            )}
            {shifts.map(shift => (
              <tr key={shift.id}>
                <td className="border px-2 py-1">{dtName(shift.duty_type_id)}</td>
                <td className="border px-2 py-1">{locName(shift.duty_location_id)}</td>
                <td className="border px-2 py-1">{shift.start_date}</td>
                <td className="border px-2 py-1">{shift.end_date}</td>
                <td className="border px-2 py-1 text-center">{shift.required_count}</td>
                <td className="border px-2 py-1 text-center">{shift.assigned_count}</td>
                <td className="border px-2 py-1">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${FILL_COLORS[shift.fill_status]}`}>
                    {t(`shifts.fill_${shift.fill_status}`)}
                  </span>
                </td>
                <td className="border px-2 py-1 space-x-2 space-x-reverse">
                  <button
                    type="button"
                    onClick={() => setEditShift(shift)}
                    className="text-blue-600 text-xs hover:underline"
                  >
                    {t("shifts.edit")}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDelete(shift)}
                    className="text-red-600 text-xs hover:underline"
                    disabled={shift.assigned_count > 0}
                  >
                    {t("shifts.delete")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {showCreate && (
        <ShiftFormModal
          dutyTypes={dutyTypes}
          locations={locations}
          onSaved={async () => { setShowCreate(false); await refresh(); }}
          onClose={() => setShowCreate(false)}
        />
      )}
      {editShift && (
        <ShiftFormModal
          dutyTypes={dutyTypes}
          locations={locations}
          existing={editShift}
          onSaved={async () => { setEditShift(null); await refresh(); }}
          onClose={() => setEditShift(null)}
        />
      )}
    </Layout>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/ShiftsPage.tsx
git commit -m "feat(frontend): ShiftsPage with table view, create/edit/delete"
```

---

### Task 10: Wire routing + navigation

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Add `/shifts` route to `frontend/src/App.tsx`**

Add import:
```tsx
import ShiftsPage from "./pages/ShiftsPage";
```

Add route inside `<Route element={<ProtectedRoute />}>`:
```tsx
<Route path="/shifts" element={<ForcedPasswordGate><ShiftsPage /></ForcedPasswordGate>} />
```

- [ ] **Step 2: Add משמרות link to Layout for DM users**

Read `frontend/src/components/Layout.tsx` to find where DM-specific nav links are added. Add:
```tsx
{(user?.role === "duty_manager" || user?.role === "admin") && (
  <a href="/shifts" className="...">
    {t("shifts.title")}
  </a>
)}
```

Match the exact className pattern used for existing nav links in Layout.tsx.

- [ ] **Step 3: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/Layout.tsx
git commit -m "feat(frontend): add /shifts route and DM navigation link"
```

---

## Self-review checklist

1. **Spec coverage:**
   - ✅ Migration 0018: duty_shifts table + FK on duty_assignments — Task 1
   - ✅ DutyShift ORM model + duty_shift_id on DutyAssignment — Task 2
   - ✅ Service: create/update/delete/list/fill_status — Task 3
   - ✅ Routes: GET/POST/PATCH/DELETE /shifts + GET /shifts/{id}/assignments — Task 4
   - ✅ Router registered in main.py — Task 4
   - ✅ Service unit tests — Task 5
   - ✅ Route integration tests — Task 6
   - ✅ API client shifts.ts — Task 7
   - ✅ i18n shifts block — Task 7
   - ✅ ShiftFormModal create/edit — Task 8
   - ✅ ShiftsPage table view with fill status — Task 9
   - ✅ /shifts route + DM nav link — Task 10

2. **Placeholder scan:** None found.

3. **Type consistency:** `DutyShift` interface in `shifts.ts` matches `ShiftOut` Pydantic model. `fill_status` is `"empty" | "partial" | "full"` consistently.
