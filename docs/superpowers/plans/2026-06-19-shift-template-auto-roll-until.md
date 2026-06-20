# Shift Template Auto-Roll "Until Date" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a shift template's `auto_roll` (recurring generation) have an optional end date, after which `roll_horizon` stops generating new shifts for it, and show a live "how many instances" estimate next to the date picker in the template form.

**Architecture:** Add a nullable `auto_roll_until` Date column to `ShiftTemplate`. The service layer validates it (must be `>= today` when set) and `roll_horizon` clamps its per-template generation window to it (or skips the template entirely once expired). The frontend form reveals a date input when `auto_roll` is checked and computes the instance count purely client-side by re-implementing the same weekday-matching rule the backend uses, since the template may not exist yet on create.

**Tech Stack:** Python/FastAPI/SQLAlchemy 2.0 (MappedAsDataclass) + Alembic on the backend; React/TypeScript + vitest on the frontend.

**Spec:** `docs/superpowers/specs/2026-06-19-shift-template-auto-roll-until-design.md`

---

### Task 1: Add `auto_roll_until` column to the `ShiftTemplate` model

**Files:**
- Modify: `backend/app/db/models.py:371`

- [ ] **Step 1: Add the column**

In `backend/app/db/models.py`, the `ShiftTemplate` class currently has at line 371:

```python
    auto_roll: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
```

Add a new line directly after it:

```python
    auto_roll: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    auto_roll_until: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
```

`Date` is already imported at the top of this file (`from sqlalchemy import Boolean, Date, DateTime, ...`), so no import changes are needed.

- [ ] **Step 2: Create the Alembic migration**

Create `backend/alembic/versions/0054_add_auto_roll_until_to_shift_templates.py`. This repo's recent shift-template migrations use short numeric revision ids (see `0049_shift_template_duration_days.py`, `0051_grant_shift_templates_to_app.py`); the current head is `0053` (`alembic heads` from `backend/`, run with the venv activated, prints `0053 (head)`).

```python
"""add auto_roll_until to shift_templates

Revision ID: 0054
Revises: 0053
Create Date: 2026-06-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shift_templates",
        sa.Column("auto_roll_until", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("shift_templates", "auto_roll_until")
```

- [ ] **Step 3: Apply the migration**

From `backend/` with the venv activated:

```bash
alembic upgrade head
```

Expected: no errors; `alembic current` reports `0054 (head)`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/0054_add_auto_roll_until_to_shift_templates.py
git commit -m "feat: add auto_roll_until column to shift_templates"
```

---

### Task 2: Service layer — accept, validate, and apply `auto_roll_until`

**Files:**
- Modify: `backend/app/services/shift_templates.py`
- Test: `backend/tests/unit/test_shift_generation.py`

- [ ] **Step 1: Write the failing validation test**

Add to the bottom of `backend/tests/unit/test_shift_generation.py`:

```python
def test_create_template_rejects_past_auto_roll_until(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    with pytest.raises(svc.TemplateError):
        svc.create_template(
            admin_session, name="bad", duty_type_id=dt.id, duty_location_id=loc.id,
            weekdays=[1], auto_roll=True, auto_roll_until=date(2020, 1, 1),
        )


def test_create_template_stores_auto_roll_until(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    tpl = svc.create_template(
        admin_session, name="future", duty_type_id=dt.id, duty_location_id=loc.id,
        weekdays=[1], auto_roll=True, auto_roll_until=date(2099, 1, 1),
    )
    assert tpl.auto_roll_until == date(2099, 1, 1)


def test_update_template_can_clear_auto_roll_until(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    tpl = svc.create_template(
        admin_session, name="clearme", duty_type_id=dt.id, duty_location_id=loc.id,
        weekdays=[1], auto_roll=True, auto_roll_until=date(2099, 1, 1),
    )
    admin_session.flush()
    svc.update_template(admin_session, tpl=tpl, auto_roll_until=None)
    assert tpl.auto_roll_until is None
```

This file doesn't import `pytest` yet — add it to the top-of-file imports:

```python
from datetime import date

import pytest

from app.db.models import DutyLocation, DutyShift, DutyType
from app.services import shift_templates as svc
```

- [ ] **Step 2: Run the tests to verify they fail**

From `backend/` with the venv activated:

```bash
pytest tests/unit/test_shift_generation.py -k auto_roll_until -v
```

Expected: `test_create_template_rejects_past_auto_roll_until` FAILS because no `TemplateError` is raised (the kwarg is currently rejected with a `TypeError` for an unexpected keyword argument, since `create_template`/`update_template` don't accept `auto_roll_until` yet) — confirm the failure is about the missing parameter, not an unrelated error.

- [ ] **Step 3: Add `auto_roll_until` to `_validate`**

In `backend/app/services/shift_templates.py`, the `_validate` function currently is:

```python
def _validate(
    recurrence_type: str,
    weekdays: list[int],
    duration_days: int,
    required_count: int,
    start_time: str,
    end_time: str,
) -> None:
    if recurrence_type not in _VALID_RECURRENCE:
        raise TemplateError("invalid_recurrence_type")
    if recurrence_type == "weekly" and (not weekdays or not set(weekdays) <= _VALID_WEEKDAYS):
        raise TemplateError("invalid_weekdays")
    if not (1 <= duration_days <= 14):
        raise TemplateError("invalid_duration_days")
    if required_count < 1:
        raise TemplateError("invalid_required_count")
    for t in (start_time, end_time):
        parts = t.split(":")
        if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
            raise TemplateError("invalid_time")
```

Replace it with:

```python
def _validate(
    recurrence_type: str,
    weekdays: list[int],
    duration_days: int,
    required_count: int,
    start_time: str,
    end_time: str,
    auto_roll_until: date | None = None,
) -> None:
    if recurrence_type not in _VALID_RECURRENCE:
        raise TemplateError("invalid_recurrence_type")
    if recurrence_type == "weekly" and (not weekdays or not set(weekdays) <= _VALID_WEEKDAYS):
        raise TemplateError("invalid_weekdays")
    if not (1 <= duration_days <= 14):
        raise TemplateError("invalid_duration_days")
    if required_count < 1:
        raise TemplateError("invalid_required_count")
    for t in (start_time, end_time):
        parts = t.split(":")
        if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
            raise TemplateError("invalid_time")
    if auto_roll_until is not None and auto_roll_until < date.today():
        raise TemplateError("invalid_auto_roll_until")
```

- [ ] **Step 4: Thread `auto_roll_until` through `create_template`**

Current signature and body (lines ~76–117):

```python
def create_template(
    session: Session,
    *,
    name: str,
    duty_type_id: uuid.UUID,
    duty_location_id: uuid.UUID,
    recurrence_type: str = "weekly",
    weekdays: list[int],
    duration_days: int = 1,
    start_time: str = "00:00",
    end_time: str = "23:59",
    required_count: int = 1,
    auto_roll: bool = False,
    notes: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> ShiftTemplate:
    _validate(recurrence_type, weekdays, duration_days, required_count, start_time, end_time)
    tpl = ShiftTemplate(
        name=name,
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id,
        recurrence_type=recurrence_type,
        weekdays=sorted(set(weekdays)) if recurrence_type == "weekly" else [],
        duration_days=duration_days,
        start_time=start_time,
        end_time=end_time,
        required_count=required_count,
        auto_roll=auto_roll,
        notes=notes,
        created_by=actor_id,
    )
    session.add(tpl)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="shift_template.create",
        entity_type="shift_template",
        entity_id=tpl.id,
        after={"name": name, "recurrence_type": recurrence_type, "weekdays": tpl.weekdays, "duration_days": duration_days, "auto_roll": auto_roll},
    )
    return tpl
```

Replace with:

```python
def create_template(
    session: Session,
    *,
    name: str,
    duty_type_id: uuid.UUID,
    duty_location_id: uuid.UUID,
    recurrence_type: str = "weekly",
    weekdays: list[int],
    duration_days: int = 1,
    start_time: str = "00:00",
    end_time: str = "23:59",
    required_count: int = 1,
    auto_roll: bool = False,
    auto_roll_until: date | None = None,
    notes: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> ShiftTemplate:
    _validate(recurrence_type, weekdays, duration_days, required_count, start_time, end_time, auto_roll_until)
    tpl = ShiftTemplate(
        name=name,
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id,
        recurrence_type=recurrence_type,
        weekdays=sorted(set(weekdays)) if recurrence_type == "weekly" else [],
        duration_days=duration_days,
        start_time=start_time,
        end_time=end_time,
        required_count=required_count,
        auto_roll=auto_roll,
        auto_roll_until=auto_roll_until,
        notes=notes,
        created_by=actor_id,
    )
    session.add(tpl)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="shift_template.create",
        entity_type="shift_template",
        entity_id=tpl.id,
        after={"name": name, "recurrence_type": recurrence_type, "weekdays": tpl.weekdays, "duration_days": duration_days, "auto_roll": auto_roll, "auto_roll_until": auto_roll_until.isoformat() if auto_roll_until else None},
    )
    return tpl
```

- [ ] **Step 5: Thread `auto_roll_until` through `update_template`**

Current signature and body (lines ~129–177):

```python
def update_template(
    session: Session,
    *,
    tpl: ShiftTemplate,
    name: str | None = None,
    recurrence_type: str | None = None,
    weekdays: list[int] | None = None,
    duration_days: int | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    required_count: int | None = None,
    auto_roll: bool | None = None,
    active: bool | None = None,
    notes: object = ...,
    actor_id: uuid.UUID | None = None,
) -> ShiftTemplate:
    before = {"name": tpl.name, "recurrence_type": tpl.recurrence_type, "weekdays": tpl.weekdays, "duration_days": tpl.duration_days, "active": tpl.active, "auto_roll": tpl.auto_roll}
    if name is not None:
        tpl.name = name
    if recurrence_type is not None:
        tpl.recurrence_type = recurrence_type
    if weekdays is not None:
        tpl.weekdays = sorted(set(weekdays))
    if duration_days is not None:
        tpl.duration_days = duration_days
    if start_time is not None:
        tpl.start_time = start_time
    if end_time is not None:
        tpl.end_time = end_time
    if required_count is not None:
        tpl.required_count = required_count
    if auto_roll is not None:
        tpl.auto_roll = auto_roll
    if active is not None:
        tpl.active = active
    if notes is not ...:
        tpl.notes = notes  # type: ignore[assignment]
    if tpl.recurrence_type != "weekly":
        tpl.weekdays = []
        tpl.duration_days = 1
    _validate(tpl.recurrence_type, tpl.weekdays, tpl.duration_days, tpl.required_count, tpl.start_time, tpl.end_time)
    write_audit(
        session,
        actor_id=actor_id,
        action="shift_template.update",
        entity_type="shift_template",
        entity_id=tpl.id,
        before=before,
        after={"name": tpl.name, "recurrence_type": tpl.recurrence_type, "weekdays": tpl.weekdays, "active": tpl.active, "auto_roll": tpl.auto_roll},
    )
    return tpl
```

Replace with (new `auto_roll_until` param uses the same `object = ...` sentinel pattern as `notes`, so an explicit `None` clears it while omitting the kwarg leaves it untouched):

```python
def update_template(
    session: Session,
    *,
    tpl: ShiftTemplate,
    name: str | None = None,
    recurrence_type: str | None = None,
    weekdays: list[int] | None = None,
    duration_days: int | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    required_count: int | None = None,
    auto_roll: bool | None = None,
    auto_roll_until: object = ...,
    active: bool | None = None,
    notes: object = ...,
    actor_id: uuid.UUID | None = None,
) -> ShiftTemplate:
    before = {"name": tpl.name, "recurrence_type": tpl.recurrence_type, "weekdays": tpl.weekdays, "duration_days": tpl.duration_days, "active": tpl.active, "auto_roll": tpl.auto_roll}
    if name is not None:
        tpl.name = name
    if recurrence_type is not None:
        tpl.recurrence_type = recurrence_type
    if weekdays is not None:
        tpl.weekdays = sorted(set(weekdays))
    if duration_days is not None:
        tpl.duration_days = duration_days
    if start_time is not None:
        tpl.start_time = start_time
    if end_time is not None:
        tpl.end_time = end_time
    if required_count is not None:
        tpl.required_count = required_count
    if auto_roll is not None:
        tpl.auto_roll = auto_roll
    if auto_roll_until is not ...:
        tpl.auto_roll_until = auto_roll_until  # type: ignore[assignment]
    if active is not None:
        tpl.active = active
    if notes is not ...:
        tpl.notes = notes  # type: ignore[assignment]
    if tpl.recurrence_type != "weekly":
        tpl.weekdays = []
        tpl.duration_days = 1
    _validate(tpl.recurrence_type, tpl.weekdays, tpl.duration_days, tpl.required_count, tpl.start_time, tpl.end_time, tpl.auto_roll_until)
    write_audit(
        session,
        actor_id=actor_id,
        action="shift_template.update",
        entity_type="shift_template",
        entity_id=tpl.id,
        before=before,
        after={"name": tpl.name, "recurrence_type": tpl.recurrence_type, "weekdays": tpl.weekdays, "active": tpl.active, "auto_roll": tpl.auto_roll},
    )
    return tpl
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
pytest tests/unit/test_shift_generation.py -k auto_roll_until -v
```

Expected: all 3 PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/shift_templates.py backend/tests/unit/test_shift_generation.py
git commit -m "feat: validate and persist auto_roll_until on shift templates"
```

---

### Task 3: Clamp `roll_horizon` to `auto_roll_until`

**Files:**
- Modify: `backend/app/services/shift_templates.py:257-279`
- Test: `backend/tests/unit/test_shift_generation.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_shift_generation.py`:

```python
def test_roll_horizon_clamps_to_auto_roll_until(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    tpl = svc.create_template(
        admin_session, name="clamped", duty_type_id=dt.id, duty_location_id=loc.id,
        weekdays=[1, 2, 3, 4, 5, 6, 7], auto_roll=True,
    )
    tpl.auto_roll_until = date(2026, 6, 5)
    admin_session.flush()
    total = svc.roll_horizon(admin_session, horizon_days=10, today=date(2026, 6, 1))
    assert total == 5  # Jun 1..5 inclusive, clamped well before the 10-day horizon end (Jun 10)
    rolled = admin_session.query(DutyShift).filter(DutyShift.generated_from_template_id == tpl.id).count()
    assert rolled == 5


def test_roll_horizon_skips_template_past_auto_roll_until(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    tpl = svc.create_template(
        admin_session, name="expired", duty_type_id=dt.id, duty_location_id=loc.id,
        weekdays=[1, 2, 3, 4, 5, 6, 7], auto_roll=True,
    )
    tpl.auto_roll_until = date(2026, 5, 1)
    admin_session.flush()
    total = svc.roll_horizon(admin_session, horizon_days=10, today=date(2026, 6, 1))
    assert total == 0
    rolled = admin_session.query(DutyShift).filter(DutyShift.generated_from_template_id == tpl.id).count()
    assert rolled == 0
```

(These set `auto_roll_until` directly on the ORM object rather than through `create_template`/`update_template`, deliberately bypassing the `>= today` validation added in Task 2 — the point here is to exercise `roll_horizon`'s clamping logic against a date that's already in the past relative to the simulated `today=date(2026, 6, 1)`, not to test validation again.)

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/unit/test_shift_generation.py -k auto_roll_until -v
```

Expected: the two new `roll_horizon` tests FAIL — `test_roll_horizon_clamps_to_auto_roll_until` gets `total == 10` instead of `5`, and `test_roll_horizon_skips_template_past_auto_roll_until` gets `total == 10` instead of `0` (since `roll_horizon` doesn't look at `auto_roll_until` yet).

- [ ] **Step 3: Update `roll_horizon`**

Current body (lines 257–279):

```python
def roll_horizon(
    session: Session,
    *,
    horizon_days: int = 30,
    today: date | None = None,
    actor_id: uuid.UUID | None = None,
) -> int:
    """Materialise the next `horizon_days` days of shifts for every active auto_roll
    template. Idempotent (relies on generate_shifts). Returns total shifts created."""
    base = today or date.today()
    range_end = base + timedelta(days=horizon_days - 1)
    templates = session.execute(
        select(ShiftTemplate).where(
            ShiftTemplate.active.is_(True), ShiftTemplate.auto_roll.is_(True)
        )
    ).scalars().all()
    total = 0
    for tpl in templates:
        created = generate_shifts(
            session, tpl=tpl, range_start=base, range_end=range_end, actor_id=actor_id
        )
        total += len(created)
    return total
```

Replace with:

```python
def roll_horizon(
    session: Session,
    *,
    horizon_days: int = 30,
    today: date | None = None,
    actor_id: uuid.UUID | None = None,
) -> int:
    """Materialise the next `horizon_days` days of shifts for every active auto_roll
    template. Idempotent (relies on generate_shifts). Returns total shifts created.

    Templates with `auto_roll_until` set have their generation window clamped to that
    date; templates whose `auto_roll_until` has already passed are skipped entirely.
    """
    base = today or date.today()
    range_end = base + timedelta(days=horizon_days - 1)
    templates = session.execute(
        select(ShiftTemplate).where(
            ShiftTemplate.active.is_(True), ShiftTemplate.auto_roll.is_(True)
        )
    ).scalars().all()
    total = 0
    for tpl in templates:
        if tpl.auto_roll_until is not None and tpl.auto_roll_until < base:
            continue
        tpl_range_end = range_end
        if tpl.auto_roll_until is not None and tpl.auto_roll_until < tpl_range_end:
            tpl_range_end = tpl.auto_roll_until
        created = generate_shifts(
            session, tpl=tpl, range_start=base, range_end=tpl_range_end, actor_id=actor_id
        )
        total += len(created)
    return total
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/unit/test_shift_generation.py -v
```

Expected: all tests in the file PASS (including the pre-existing `test_roll_horizon_generates_only_for_auto_roll_templates`, which has no `auto_roll_until` set and so is unaffected).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/shift_templates.py backend/tests/unit/test_shift_generation.py
git commit -m "feat: clamp roll_horizon generation window to auto_roll_until"
```

---

### Task 4: Wire `auto_roll_until` through the API

**Files:**
- Modify: `backend/app/routes/shift_templates.py`

- [ ] **Step 1: Add the field to `TemplateOut`, `CreateTemplateRequest`, `UpdateTemplateRequest`**

In `backend/app/routes/shift_templates.py`, update the three schemas:

```python
class TemplateOut(BaseModel):
    id: uuid.UUID
    name: str
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    recurrence_type: str
    weekdays: list[int]
    duration_days: int
    start_time: str
    end_time: str
    required_count: int
    active: bool
    auto_roll: bool
    auto_roll_until: date | None
    notes: str | None


class CreateTemplateRequest(BaseModel):
    name: str = Field(max_length=200)
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    recurrence_type: str = "weekly"
    weekdays: list[int] = Field(default_factory=list)
    duration_days: int = Field(default=1, ge=1, le=14)
    start_time: str = "00:00"
    end_time: str = "23:59"
    required_count: int = Field(default=1, ge=1)
    auto_roll: bool = False
    auto_roll_until: date | None = None
    notes: str | None = Field(default=None, max_length=1000)


class UpdateTemplateRequest(BaseModel):
    name: str | None = None
    recurrence_type: str | None = None
    weekdays: list[int] | None = None
    duration_days: int | None = Field(default=None, ge=1, le=14)
    start_time: str | None = None
    end_time: str | None = None
    required_count: int | None = Field(default=None, ge=1)
    auto_roll: bool | None = None
    auto_roll_until: date | None = None
    active: bool | None = None
    notes: str | None = None
```

- [ ] **Step 2: Include it in `_out`**

```python
def _out(t: ShiftTemplate) -> TemplateOut:
    return TemplateOut(
        id=t.id, name=t.name, duty_type_id=t.duty_type_id, duty_location_id=t.duty_location_id,
        recurrence_type=t.recurrence_type, weekdays=t.weekdays, duration_days=t.duration_days,
        start_time=t.start_time, end_time=t.end_time, required_count=t.required_count,
        active=t.active, auto_roll=t.auto_roll, auto_roll_until=t.auto_roll_until, notes=t.notes,
    )
```

- [ ] **Step 3: Pass it through `create_template`**

```python
@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    body: CreateTemplateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TemplateOut:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    try:
        t = svc.create_template(
            session, name=body.name, duty_type_id=body.duty_type_id,
            duty_location_id=body.duty_location_id, recurrence_type=body.recurrence_type,
            weekdays=body.weekdays, duration_days=body.duration_days,
            start_time=body.start_time, end_time=body.end_time,
            required_count=body.required_count, auto_roll=body.auto_roll,
            auto_roll_until=body.auto_roll_until,
            notes=body.notes, actor_id=user.id,
        )
    except svc.TemplateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(t)
    return _out(t)
```

- [ ] **Step 4: Pass it through `update_template`, respecting explicit-null-vs-absent**

```python
@router.patch("/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: uuid.UUID,
    body: UpdateTemplateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TemplateOut:
    t = _load(session, template_id)
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    extra: dict = {}
    if "notes" in body.model_fields_set:
        extra["notes"] = body.notes
    if "auto_roll_until" in body.model_fields_set:
        extra["auto_roll_until"] = body.auto_roll_until
    try:
        svc.update_template(
            session, tpl=t, name=body.name, recurrence_type=body.recurrence_type,
            weekdays=body.weekdays, duration_days=body.duration_days,
            start_time=body.start_time, end_time=body.end_time,
            required_count=body.required_count, auto_roll=body.auto_roll,
            active=body.active, actor_id=user.id, **extra,
        )
    except svc.TemplateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(t)
    return _out(t)
```

- [ ] **Step 5: Run the full backend fast suite**

From `backend/` with the venv activated:

```bash
pytest -q
```

Expected: all tests PASS (excludes `@pytest.mark.slow`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/shift_templates.py
git commit -m "feat: expose auto_roll_until in shift template API"
```

---

### Task 5: Frontend types and i18n keys

**Files:**
- Modify: `frontend/src/api/shiftTemplates.ts`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add `auto_roll_until` to the frontend types**

In `frontend/src/api/shiftTemplates.ts`:

```typescript
export interface ShiftTemplate {
  id: string;
  name: string;
  duty_type_id: string;
  duty_location_id: string;
  recurrence_type: RecurrenceType;
  weekdays: number[];
  duration_days: number;
  start_time: string;
  end_time: string;
  required_count: number;
  active: boolean;
  auto_roll: boolean;
  auto_roll_until: string | null;
  notes: string | null;
}

export interface CreateTemplateInput {
  name: string;
  duty_type_id: string;
  duty_location_id: string;
  recurrence_type: RecurrenceType;
  weekdays: number[];
  duration_days?: number;
  start_time?: string;
  end_time?: string;
  required_count?: number;
  auto_roll?: boolean;
  auto_roll_until?: string | null;
  notes?: string | null;
}
```

(`UpdateTemplateInput` is `Partial<Omit<CreateTemplateInput, ...>>`, so it picks up `auto_roll_until` automatically — no change needed there.)

- [ ] **Step 2: Add Hebrew translation keys**

In `frontend/src/i18n/he.json`, inside the `shift_templates` object, add two keys right after `"auto_roll": "יצירה אוטומטית",` (line 529):

```json
    "auto_roll": "יצירה אוטומטית",
    "auto_roll_until": "עד איזה תאריך לייצר",
    "auto_roll_until_count": "ייוצרו כ-{{count}} מופעים עד התאריך הזה",
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/shiftTemplates.ts frontend/src/i18n/he.json
git commit -m "feat: add auto_roll_until type and translation keys"
```

---

### Task 6: Form modal — date picker and live instance count

**Files:**
- Modify: `frontend/src/components/ShiftTemplateFormModal.tsx`
- Test: `frontend/src/components/ShiftTemplateFormModal.test.tsx` (new)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/ShiftTemplateFormModal.test.tsx`:

```typescript
import { render, screen, fireEvent } from "@testing-library/react";
import ShiftTemplateFormModal from "./ShiftTemplateFormModal";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { count?: number }) =>
      key === "shift_templates.auto_roll_until_count" ? `count:${opts?.count}` : key,
  }),
}));

vi.mock("../api/shiftTemplates", () => ({
  createTemplate: vi.fn(() => Promise.resolve({})),
  updateTemplate: vi.fn(() => Promise.resolve({})),
}));

const dutyTypes = [{ id: "d1", name: "duty1" }];
const locations = [{ id: "l1", name: "loc1" }];

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-06-19T12:00:00Z")); // Friday
});

afterEach(() => {
  vi.useRealTimers();
});

test("checking auto_roll reveals the until-date picker", () => {
  render(
    <ShiftTemplateFormModal dutyTypes={dutyTypes} locations={locations} onSubmit={() => {}} onClose={() => {}} />
  );
  expect(screen.queryByTestId("auto-roll-until-date")).not.toBeInTheDocument();
  fireEvent.click(screen.getByTestId("auto-roll-checkbox"));
  expect(screen.getByTestId("auto-roll-until-date")).toBeInTheDocument();
});

test("picking an until-date shows the computed instance count for the default weekdays recurrence", () => {
  render(
    <ShiftTemplateFormModal dutyTypes={dutyTypes} locations={locations} onSubmit={() => {}} onClose={() => {}} />
  );
  fireEvent.click(screen.getByTestId("auto-roll-checkbox"));
  fireEvent.change(screen.getByTestId("auto-roll-until-date"), { target: { value: "2026-06-26" } });
  // Default recurrence is "weekdays" (Sun-Thu). Today=2026-06-19 (Fri) .. 2026-06-26 (Fri):
  // matching days are Sun 6/21, Mon 6/22, Tue 6/23, Wed 6/24, Thu 6/25 = 5.
  expect(screen.getByTestId("auto-roll-until-count")).toHaveTextContent("count:5");
});
```

- [ ] **Step 2: Run the test to verify it fails**

From `frontend/`:

```bash
npm test -- ShiftTemplateFormModal
```

Expected: FAIL — `auto-roll-checkbox`, `auto-roll-until-date`, and `auto-roll-until-count` test ids don't exist yet.

- [ ] **Step 3: Add the count-calculation helper**

In `frontend/src/components/ShiftTemplateFormModal.tsx`, add a new helper near the other module-level helpers (after `isoToDow`, before `parseTimeFraction`, around line 36):

```typescript
function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

// Mirrors the backend's _effective_weekdays rule in shift_templates.py.
function countAutoRollInstances(
  recurrenceType: RecurrenceType,
  startDow: number | null,
  fromDateStr: string,
  untilDateStr: string,
): number {
  if (!untilDateStr) return 0;
  let selected: Set<number>;
  if (recurrenceType === "daily") {
    selected = new Set([1, 2, 3, 4, 5, 6, 7]);
  } else if (recurrenceType === "weekdays") {
    selected = new Set([7, 1, 2, 3, 4]); // Israeli work week: Sun-Thu
  } else {
    if (startDow === null) return 0;
    selected = new Set([dowToIso(startDow)]);
  }
  const from = new Date(`${fromDateStr}T00:00:00`);
  const until = new Date(`${untilDateStr}T00:00:00`);
  if (until < from) return 0;
  let count = 0;
  const cur = new Date(from);
  while (cur <= until) {
    if (selected.has(dowToIso(cur.getDay()))) count++;
    cur.setDate(cur.getDate() + 1);
  }
  return count;
}
```

- [ ] **Step 4: Add state and the computed count**

In the main component, near the other `auto_roll`-related state (around line 206, `const [autoRoll, setAutoRoll] = useState(...)`), add:

```typescript
  const [autoRoll, setAutoRoll] = useState(initial?.auto_roll ?? false);
  const [autoRollUntil, setAutoRollUntil] = useState(initial?.auto_roll_until ?? "");
```

Below the existing state declarations (after `showAddLoc`), add the derived count:

```typescript
  const autoRollCount = autoRoll && autoRollUntil
    ? countAutoRollInstances(recurrenceType, startDow, todayStr(), autoRollUntil)
    : 0;
```

- [ ] **Step 5: Render the date picker and count**

Replace the existing auto-roll checkbox block:

```jsx
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={autoRoll} onChange={e => setAutoRoll(e.target.checked)} />
              {t("shift_templates.auto_roll")}
            </label>
```

with:

```jsx
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={autoRoll}
                onChange={e => setAutoRoll(e.target.checked)}
                data-testid="auto-roll-checkbox"
              />
              {t("shift_templates.auto_roll")}
            </label>

            {autoRoll && (
              <div className="pl-6 space-y-1">
                <label className="block text-sm">
                  {t("shift_templates.auto_roll_until")}
                  <input
                    type="date"
                    value={autoRollUntil}
                    min={todayStr()}
                    onChange={e => setAutoRollUntil(e.target.value)}
                    data-testid="auto-roll-until-date"
                    dir="ltr"
                    className="mt-1 block w-full border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                  />
                </label>
                {autoRollUntil && (
                  <p data-testid="auto-roll-until-count" className="text-xs text-gray-500 dark:text-gray-400">
                    {t("shift_templates.auto_roll_until_count", { count: autoRollCount })}
                  </p>
                )}
              </div>
            )}
```

- [ ] **Step 6: Include `auto_roll_until` in the submit payload**

In `handleSubmit`, the `UpdateTemplateInput` and `CreateTemplateInput` objects are built as:

```typescript
        const input: UpdateTemplateInput = {
          name, recurrence_type: recurrenceType, weekdays, duration_days,
          start_time: startTime, end_time: endTime,
          required_count: count, auto_roll: autoRoll, notes: notes || null,
        };
```

and

```typescript
        const input: CreateTemplateInput = {
          name, duty_type_id: dtId, duty_location_id: locId,
          recurrence_type: recurrenceType, weekdays, duration_days,
          start_time: startTime, end_time: endTime,
          required_count: count, auto_roll: autoRoll, notes: notes || null,
        };
```

Add `auto_roll_until: autoRollUntil || null` to both:

```typescript
        const input: UpdateTemplateInput = {
          name, recurrence_type: recurrenceType, weekdays, duration_days,
          start_time: startTime, end_time: endTime,
          required_count: count, auto_roll: autoRoll, auto_roll_until: autoRollUntil || null,
          notes: notes || null,
        };
```

```typescript
        const input: CreateTemplateInput = {
          name, duty_type_id: dtId, duty_location_id: locId,
          recurrence_type: recurrenceType, weekdays, duration_days,
          start_time: startTime, end_time: endTime,
          required_count: count, auto_roll: autoRoll, auto_roll_until: autoRollUntil || null,
          notes: notes || null,
        };
```

- [ ] **Step 7: Run the test to verify it passes**

```bash
npm test -- ShiftTemplateFormModal
```

Expected: both tests PASS.

- [ ] **Step 8: Run the full frontend test suite and lint**

```bash
npm test
npm run lint
```

Expected: all PASS, zero lint warnings.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/ShiftTemplateFormModal.tsx frontend/src/components/ShiftTemplateFormModal.test.tsx
git commit -m "feat: add auto-roll until-date picker with live instance count"
```

---

### Task 7: Manual verification in the running app

- [ ] **Step 1: Open the shift templates page**

With `.\dev.ps1` running, open http://localhost:5173 and navigate to the shift templates page (the one rendering `ShiftTemplateFormModal`).

- [ ] **Step 2: Create a template with auto-roll and an until-date**

Click "הוסף תבנית", fill in name/duty type/location, check "יצירה אוטומטית", confirm a date input labeled "עד איזה תאריך לייצר" appears with `min` set to today, pick a date a couple of weeks out, and confirm the instance-count text appears and updates as you change the recurrence type (daily / weekdays / weekly) and the date.

- [ ] **Step 3: Save and re-open**

Save the template, re-open it for editing, and confirm the until-date and checkbox state round-tripped correctly (check via the Network tab or by re-opening the edit modal).

- [ ] **Step 4: Uncheck and re-check**

In the edit modal, uncheck "יצירה אוטומטית" (date field disappears), then re-check it — confirm the previously-entered date reappears (per spec: unchecking doesn't clear the local field value).
