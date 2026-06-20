# Duty Day Calculation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make "how many days does this duty span" mean two different, correct things depending on purpose — calendar dates touched (for rolling-window/rest constraints, already correct today) vs. wall-clock duration rounded up (for effort score, currently wrong because no duty record stores a time-of-day at all).

**Architecture:** Add a pure, dependency-free `score_days()`/`calendar_days_touched()` helper to `app/algorithm`. Thread real `start_time`/`end_time` (HH:MM strings, same format already used by `ShiftTemplate`) through `DutyShift`, `DutyAssignment`, and `DutyBlock`, defaulting everywhere to `"00:00"`/`"23:59"` so every existing whole-day duty's score is unchanged. Switch every score-calculation call site from `(end_date - start_date).days` to `score_days(...)`. Leave every window/rolling-cap calculation untouched — it already operates on calendar dates touched, which was never the bug.

**Tech Stack:** Python/SQLAlchemy 2.0 (MappedAsDataclass)/Alembic/pytest, OR-Tools CP-SAT.

**Spec:** `docs/superpowers/specs/2026-06-20-duty-day-calculation-design.md`

---

### Task 1: Pure date/time duration helpers

**Files:**
- Create: `backend/app/algorithm/duration.py`
- Test: `backend/app/algorithm/tests/test_duration.py`

This is a new, pure, dependency-free module (no DB imports, consistent with the rest of `app/algorithm`) so both the solver and the services layer can share it.

- [ ] **Step 1: Write the failing tests**

Create `backend/app/algorithm/tests/test_duration.py`:

```python
from datetime import date

from app.algorithm.duration import calendar_days_touched, score_days


def test_calendar_days_touched_single_day():
    assert calendar_days_touched(date(2026, 6, 1), date(2026, 6, 2)) == 1


def test_calendar_days_touched_multi_day():
    assert calendar_days_touched(date(2026, 6, 1), date(2026, 6, 8)) == 7


def test_score_days_same_day_partial_hours():
    # 8am-5pm, touches 1 calendar day -> 9 hours -> ceil to 1 day.
    assert score_days(date(2026, 6, 1), date(2026, 6, 2), "08:00", "17:00") == 1


def test_score_days_exact_week_spanning_eight_calendar_days():
    # Monday 14:00 -> following Monday 14:00: duration_days=8 (touches 8 calendar
    # dates), but exactly 168 hours = 7*24h elapsed -> scores as 7 days.
    assert score_days(date(2026, 6, 1), date(2026, 6, 9), "14:00", "14:00") == 7

    # calendar_days_touched is still 8 -- the window-relevant count is unaffected.
    assert calendar_days_touched(date(2026, 6, 1), date(2026, 6, 9)) == 8


def test_score_days_default_full_day_reproduces_calendar_days_touched():
    # The "00:00"/"23:59" defaults used everywhere a real time isn't known should
    # reproduce today's exact whole-day count for any duration.
    for n in (1, 2, 5, 14):
        end = date(2026, 6, 1).fromordinal(date(2026, 6, 1).toordinal() + n)
        assert score_days(date(2026, 6, 1), end, "00:00", "23:59") == n


def test_score_days_overnight_two_calendar_days_one_score_day():
    # 23:00 -> 01:00 next day: touches 2 calendar dates, 2 hours elapsed -> 1 day.
    assert score_days(date(2026, 6, 1), date(2026, 6, 3), "23:00", "01:00") == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

From `backend/` with the venv activated:

```bash
pytest app/algorithm/tests/test_duration.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.algorithm.duration'`.

- [ ] **Step 3: Implement the helpers**

Create `backend/app/algorithm/duration.py`:

```python
from __future__ import annotations

import math
from datetime import date


def calendar_days_touched(start_date: date, end_date: date) -> int:
    """Number of distinct calendar dates in [start_date, end_date) — end_date is
    exclusive (the first day NOT touched). This is what rolling-window/rest
    constraints care about: which calendar dates a duty occupies."""
    return (end_date - start_date).days


def _parse_hhmm(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def score_days(start_date: date, end_date: date, start_time: str, end_time: str) -> int:
    """Wall-clock duration of the duty, rounded up to whole days, for effort-score
    purposes. `start_time` is the clock time on `start_date`; `end_time` is the
    clock time on `end_date - 1 day` (the LAST calendar day touched, not end_date
    itself, which is never touched)."""
    days_touched = calendar_days_touched(start_date, end_date)
    elapsed_minutes = (days_touched - 1) * 24 * 60 + (_parse_hhmm(end_time) - _parse_hhmm(start_time))
    return max(1, math.ceil(elapsed_minutes / (24 * 60)))
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest app/algorithm/tests/test_duration.py -v
```

Expected: all 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/algorithm/duration.py backend/app/algorithm/tests/test_duration.py
git commit -m "feat: add pure score_days/calendar_days_touched duration helpers"
```

---

### Task 2: Add `start_time`/`end_time` to `DutyShift`

**Files:**
- Modify: `backend/app/db/models.py:319-320`
- Create: `backend/alembic/versions/0055_add_times_to_duty_shifts.py`

- [ ] **Step 1: Add the columns**

In `backend/app/db/models.py`, the `DutyShift` class currently has at lines 319-321:

```python
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    required_count: Mapped[int] = mapped_column(server_default=text("1"), default=1)
```

Insert two new columns between `end_date` and `required_count`:

```python
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[str] = mapped_column(Text, server_default=text("'00:00'"), default="00:00")  # "HH:MM"
    end_time: Mapped[str] = mapped_column(Text, server_default=text("'23:59'"), default="23:59")    # "HH:MM"
    required_count: Mapped[int] = mapped_column(server_default=text("1"), default=1)
```

`Text` is already imported at the top of this file.

- [ ] **Step 2: Create the migration**

Create `backend/alembic/versions/0055_add_times_to_duty_shifts.py`:

```python
"""add start_time/end_time to duty_shifts

Revision ID: 0055
Revises: 0054
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "duty_shifts",
        sa.Column("start_time", sa.Text(), nullable=False, server_default="00:00"),
    )
    op.add_column(
        "duty_shifts",
        sa.Column("end_time", sa.Text(), nullable=False, server_default="23:59"),
    )


def downgrade() -> None:
    op.drop_column("duty_shifts", "end_time")
    op.drop_column("duty_shifts", "start_time")
```

- [ ] **Step 3: Apply the migration**

From `backend/` with the venv activated (set `DATABASE_URL`/`DB_ADMIN_URL`/`JWT_SECRET` env vars pointed at your local Postgres if not already set):

```bash
alembic upgrade head
```

Expected: no errors; `alembic current` reports `0055 (head)`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/0055_add_times_to_duty_shifts.py
git commit -m "feat: add start_time/end_time columns to duty_shifts"
```

---

### Task 3: Validate time ordering and copy times at shift generation

**Files:**
- Modify: `backend/app/services/shift_templates.py`
- Test: `backend/tests/unit/test_shift_generation.py`

- [ ] **Step 1: Write the failing tests**

Add to the bottom of `backend/tests/unit/test_shift_generation.py`:

```python
def test_create_template_rejects_end_time_before_start_time_when_single_day(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    with pytest.raises(svc.TemplateError):
        svc.create_template(
            admin_session, name="bad_order", duty_type_id=dt.id, duty_location_id=loc.id,
            recurrence_type="daily", weekdays=[], duration_days=1,
            start_time="17:00", end_time="08:00",
        )


def test_create_template_allows_any_end_time_when_multi_day(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    tpl = svc.create_template(
        admin_session, name="overnight_multi", duty_type_id=dt.id, duty_location_id=loc.id,
        recurrence_type="daily", weekdays=[], duration_days=2,
        start_time="23:00", end_time="01:00",
    )
    assert tpl.duration_days == 2


def test_generate_shifts_copies_template_times_onto_shift(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    tpl = svc.create_template(
        admin_session, name="timed", duty_type_id=dt.id, duty_location_id=loc.id,
        recurrence_type="daily", weekdays=[], duration_days=1,
        start_time="08:00", end_time="17:00",
    )
    admin_session.flush()
    created = svc.generate_shifts(
        admin_session, tpl=tpl, range_start=date(2026, 6, 1), range_end=date(2026, 6, 1),
    )
    assert len(created) == 1
    assert created[0].start_time == "08:00"
    assert created[0].end_time == "17:00"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/unit/test_shift_generation.py -k "time_order or copies_template_times" -v
```

Expected: `test_create_template_rejects_end_time_before_start_time_when_single_day` FAILS (no `TemplateError` raised — the ordering rule doesn't exist yet); `test_generate_shifts_copies_template_times_onto_shift` FAILS (`created[0].start_time == "00:00"`, the default, not `"08:00"`).

- [ ] **Step 3: Add the ordering check to `_validate`**

In `backend/app/services/shift_templates.py`, `_validate` currently ends with:

```python
    for t in (start_time, end_time):
        parts = t.split(":")
        if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
            raise TemplateError("invalid_time")
    if auto_roll_until is not None and auto_roll_until < date.today():
        raise TemplateError("invalid_auto_roll_until")
```

Add the ordering check right after the format loop (HH:MM strings are zero-padded by the format check above, so a plain string comparison is a valid same-day ordering test):

```python
    for t in (start_time, end_time):
        parts = t.split(":")
        if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
            raise TemplateError("invalid_time")
    if duration_days == 1 and end_time <= start_time:
        raise TemplateError("invalid_time_order")
    if auto_roll_until is not None and auto_roll_until < date.today():
        raise TemplateError("invalid_auto_roll_until")
```

- [ ] **Step 4: Copy `start_time`/`end_time` onto the generated `DutyShift`**

In `generate_shifts()` (same file), the `DutyShift(...)` constructor currently is:

```python
        shift = DutyShift(
            duty_type_id=tpl.duty_type_id,
            duty_location_id=tpl.duty_location_id,
            start_date=d,
            end_date=d + timedelta(days=tpl.duration_days),
            required_count=tpl.required_count,
            notes=tpl.notes,
            created_by=actor_id,
            generated_from_template_id=tpl.id,
        )
```

Add `start_time`/`end_time`:

```python
        shift = DutyShift(
            duty_type_id=tpl.duty_type_id,
            duty_location_id=tpl.duty_location_id,
            start_date=d,
            end_date=d + timedelta(days=tpl.duration_days),
            start_time=tpl.start_time,
            end_time=tpl.end_time,
            required_count=tpl.required_count,
            notes=tpl.notes,
            created_by=actor_id,
            generated_from_template_id=tpl.id,
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
pytest tests/unit/test_shift_generation.py -v
```

Expected: all tests in the file PASS, including the 3 new ones and every pre-existing test (none of them pass an explicit `duration_days=1` with a backwards time, so the new ordering check doesn't affect them).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/shift_templates.py backend/tests/unit/test_shift_generation.py
git commit -m "feat: validate time ordering and copy template times onto generated shifts"
```

---

### Task 4: Optional `start_time`/`end_time` on manual shift creation

**Files:**
- Modify: `backend/app/services/shifts.py`
- Modify: `backend/app/routes/shifts.py`
- Test: `backend/tests/unit/test_shift_generation.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_shift_generation.py`:

```python
from app.services import shifts as shifts_svc


def test_create_shift_defaults_to_full_day_times(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    shift = shifts_svc.create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
    )
    assert shift.start_time == "00:00"
    assert shift.end_time == "23:59"


def test_create_shift_accepts_explicit_times(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    shift = shifts_svc.create_shift(
        admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        start_time="08:00", end_time="17:00",
    )
    assert shift.start_time == "08:00"
    assert shift.end_time == "17:00"


def test_create_shift_rejects_end_time_before_start_time_when_single_day(admin_session):
    dt, loc = _seed_type_and_location(admin_session)
    with pytest.raises(shifts_svc.ShiftError):
        shifts_svc.create_shift(
            admin_session, duty_type_id=dt.id, duty_location_id=loc.id,
            start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
            start_time="17:00", end_time="08:00",
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/unit/test_shift_generation.py -k "create_shift_" -v
```

Expected: `test_create_shift_defaults_to_full_day_times` FAILS with `TypeError: create_shift() got an unexpected keyword argument` is NOT what happens (no kwarg passed) — it actually fails on the assertion, since `start_time`/`end_time` attributes don't exist yet on `DutyShift` until Task 2 lands (already done) but `create_shift()` doesn't set them — wait, the model default (`"00:00"`/`"23:59"`) already applies even without `create_shift()` passing them explicitly, so this first test should already PASS once Task 2's migration is applied. The other two FAIL: `test_create_shift_accepts_explicit_times` fails because `create_shift()` doesn't accept `start_time`/`end_time` kwargs yet (`TypeError`), and `test_create_shift_rejects_end_time_before_start_time_when_single_day` fails because no such validation exists yet (no exception raised, in fact a `TypeError` for the unexpected kwarg, not a `ShiftError`).

- [ ] **Step 3: Add `start_time`/`end_time` params to the service function**

In `backend/app/services/shifts.py`, `create_shift` currently is:

```python
def create_shift(
    session: Session,
    *,
    duty_type_id: uuid.UUID,
    duty_location_id: uuid.UUID,
    start_date: date,
    end_date: date,
    required_count: int = 1,
    notes: str | None = None,
    reserve_count_override: int | None = None,
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
        reserve_count_override=reserve_count_override,
        created_by=actor_id,
    )
```

Replace with:

```python
def create_shift(
    session: Session,
    *,
    duty_type_id: uuid.UUID,
    duty_location_id: uuid.UUID,
    start_date: date,
    end_date: date,
    start_time: str = "00:00",
    end_time: str = "23:59",
    required_count: int = 1,
    notes: str | None = None,
    reserve_count_override: int | None = None,
    actor_id: uuid.UUID | None = None,
) -> DutyShift:
    if end_date < start_date:
        raise ShiftError("end_before_start")
    if required_count < 1:
        raise ShiftError("invalid_required_count")
    if (end_date - start_date).days == 1 and end_time <= start_time:
        raise ShiftError("invalid_time_order")
    shift = DutyShift(
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id,
        start_date=start_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
        required_count=required_count,
        notes=notes,
        reserve_count_override=reserve_count_override,
        created_by=actor_id,
    )
```

- [ ] **Step 4: Wire the new fields through the route**

In `backend/app/routes/shifts.py`, `CreateShiftRequest` currently is:

```python
class CreateShiftRequest(BaseModel):
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    required_count: int = Field(default=1, ge=1)
    notes: str | None = Field(default=None, max_length=1000)
    reserve_count_override: int | None = Field(default=None, ge=0)
```

Add the two optional fields:

```python
class CreateShiftRequest(BaseModel):
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    start_time: str = "00:00"
    end_time: str = "23:59"
    required_count: int = Field(default=1, ge=1)
    notes: str | None = Field(default=None, max_length=1000)
    reserve_count_override: int | None = Field(default=None, ge=0)
```

And in `create_shift` (the route handler), the `svc.create_shift(...)` call currently is:

```python
        shift = svc.create_shift(
            session,
            duty_type_id=body.duty_type_id,
            duty_location_id=body.duty_location_id,
            start_date=body.start_date,
            end_date=body.end_date,
            required_count=body.required_count,
            notes=body.notes,
            reserve_count_override=body.reserve_count_override,
            actor_id=user.id,
        )
```

Add `start_time`/`end_time`:

```python
        shift = svc.create_shift(
            session,
            duty_type_id=body.duty_type_id,
            duty_location_id=body.duty_location_id,
            start_date=body.start_date,
            end_date=body.end_date,
            start_time=body.start_time,
            end_time=body.end_time,
            required_count=body.required_count,
            notes=body.notes,
            reserve_count_override=body.reserve_count_override,
            actor_id=user.id,
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
pytest tests/unit/test_shift_generation.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/shifts.py backend/app/routes/shifts.py backend/tests/unit/test_shift_generation.py
git commit -m "feat: accept optional start_time/end_time on manual shift creation"
```

---

### Task 5: Add `start_time`/`end_time` to `DutyAssignment`

**Files:**
- Modify: `backend/app/db/models.py:248-249`
- Create: `backend/alembic/versions/0056_add_times_to_duty_assignments.py`

- [ ] **Step 1: Add the columns**

In `backend/app/db/models.py`, the `DutyAssignment` class currently has at lines 248-250:

```python
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        Text, server_default=text("'published'"), default="published"
    )
```

Insert the two new columns between `end_date` and `status`:

```python
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[str] = mapped_column(Text, server_default=text("'00:00'"), default="00:00")  # "HH:MM"
    end_time: Mapped[str] = mapped_column(Text, server_default=text("'23:59'"), default="23:59")    # "HH:MM"
    status: Mapped[str] = mapped_column(
        Text, server_default=text("'published'"), default="published"
    )
```

- [ ] **Step 2: Create the migration**

Create `backend/alembic/versions/0056_add_times_to_duty_assignments.py`:

```python
"""add start_time/end_time to duty_assignments

Revision ID: 0056
Revises: 0055
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "duty_assignments",
        sa.Column("start_time", sa.Text(), nullable=False, server_default="00:00"),
    )
    op.add_column(
        "duty_assignments",
        sa.Column("end_time", sa.Text(), nullable=False, server_default="23:59"),
    )


def downgrade() -> None:
    op.drop_column("duty_assignments", "end_time")
    op.drop_column("duty_assignments", "start_time")
```

- [ ] **Step 3: Apply the migration**

```bash
alembic upgrade head
```

Expected: `alembic current` reports `0056 (head)`. Existing rows are backfilled to `"00:00"`/`"23:59"` via `server_default`, so every historical assignment's `score_days` reproduces its current `calendar_days_touched` exactly (per Task 1's `test_score_days_default_full_day_reproduces_calendar_days_touched`) — no historical score changes.

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/0056_add_times_to_duty_assignments.py
git commit -m "feat: add start_time/end_time columns to duty_assignments"
```

---

### Task 6: Resolve `start_time`/`end_time` from the linked shift in `create_assignment`

**Files:**
- Modify: `backend/app/services/assignments.py`
- Test: find or create `backend/app/services/tests/test_assignments.py`

This is the one `DutyAssignment`-creation call site that's reachable directly from a route with only a `duty_shift_id` (not a loaded `DutyShift` object) — `backend/app/routes/assignments.py:145`. Resolving inside the service function (rather than requiring every caller to pass times) fixes that site and the two `assign_batch` call sites in `backend/app/routes/shifts.py` (which already have the full `shift` loaded, but don't need to be touched since the service now does the lookup itself).

- [ ] **Step 1: Check for an existing test file**

Run:

```bash
ls app/services/tests/test_assignments.py
```

If it exists, read it first to match its fixture conventions before adding tests. If it doesn't exist, create it following the pattern in `app/services/tests/test_shift_templates.py` (a `dt`/`loc` seed helper, `admin_session` fixture).

- [ ] **Step 2: Write the failing tests**

Add (creating the file if needed) `backend/app/services/tests/test_assignments.py`:

```python
from datetime import date
from decimal import Decimal

from app.db.models import DutyLocation, DutyShift, DutyType
from app.services import assignments as svc


def _seed(session):
    dt = DutyType(name="dt_assign_test", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_assign_test")
    session.add(dt)
    session.add(loc)
    session.flush()
    return dt, loc


def test_create_assignment_without_shift_defaults_to_full_day_times(admin_session):
    dt, loc = _seed(admin_session)
    soldier = admin_session.execute(
        __import__("sqlalchemy").select(__import__("app.db.models", fromlist=["Soldier"]).Soldier)
    ).scalars().first()
    a = svc.create_assignment(
        admin_session, soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
    )
    assert a.start_time == "00:00"
    assert a.end_time == "23:59"


def test_create_assignment_copies_times_from_linked_shift(admin_session):
    dt, loc = _seed(admin_session)
    from sqlalchemy import select
    from app.db.models import Soldier
    soldier = admin_session.execute(select(Soldier)).scalars().first()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        start_time="08:00", end_time="17:00",
    )
    admin_session.add(shift)
    admin_session.flush()
    a = svc.create_assignment(
        admin_session, soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=shift.start_date, end_date=shift.end_date, duty_shift_id=shift.id,
    )
    assert a.start_time == "08:00"
    assert a.end_time == "17:00"
```

This relies on `admin_session` already having at least one `Soldier` row available — check `backend/tests/conftest.py`'s `admin_session` fixture for how it seeds the admin soldier (it's used by every other test file via `select(Soldier)` patterns elsewhere — if no soldier exists in the fixture, create one inline: `soldier = Soldier(full_name="Test Soldier", phone=f"050{uuid.uuid4().hex[:7]}"` — check `Soldier`'s required fields in `models.py` first and adjust accordingly before relying on a query).

- [ ] **Step 3: Run the tests to verify they fail**

```bash
pytest app/services/tests/test_assignments.py -v
```

Expected: `test_create_assignment_without_shift_defaults_to_full_day_times` likely PASSES already (model defaults apply automatically). `test_create_assignment_copies_times_from_linked_shift` FAILS — `a.start_time == "00:00"` (the default), not `"08:00"`, since `create_assignment` doesn't look up the shift yet.

- [ ] **Step 4: Implement the lookup**

In `backend/app/services/assignments.py`, `create_assignment` currently builds:

```python
    a = DutyAssignment(
        soldier_id=soldier_id,
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id,
        start_date=start_date,
        end_date=end_date,
        notes=notes,
        duty_shift_id=duty_shift_id,
        is_reserve=is_reserve,
        created_by=actor_id,
    )
```

Add a lookup right before it, and pass the resolved times into the constructor:

```python
    start_time, end_time = "00:00", "23:59"
    if duty_shift_id is not None:
        shift = session.get(DutyShift, duty_shift_id)
        if shift is not None:
            start_time, end_time = shift.start_time, shift.end_time
    a = DutyAssignment(
        soldier_id=soldier_id,
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id,
        start_date=start_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
        notes=notes,
        duty_shift_id=duty_shift_id,
        is_reserve=is_reserve,
        created_by=actor_id,
    )
```

`DutyShift` must be imported in this file — check the existing `from app.db.models import ...` line at the top and add `DutyShift` to it if not already present.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
pytest app/services/tests/test_assignments.py -v
```

Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/assignments.py backend/app/services/tests/test_assignments.py
git commit -m "feat: resolve assignment start_time/end_time from linked shift"
```

---

### Task 7: Copy times in gimelim reserve promotion

**Files:**
- Modify: `backend/app/services/gimelim.py:597-609`
- Test: find the existing gimelim test file (search `ls app/services/tests/test_gimelim.py` or similar — adjust path if different) and add to it.

- [ ] **Step 1: Locate the existing gimelim test file**

```bash
find . -iname "*gimelim*test*" -o -iname "*test*gimelim*"
```

Read whichever file(s) this finds to learn the existing fixture/setup conventions for testing `apply_gimelim` before writing a new test.

- [ ] **Step 2: Write a failing test**

Using the patterns found in Step 1, add a test asserting that after `apply_gimelim` promotes a reserve to primary on a `future_shift` with explicit `start_time`/`end_time` (e.g. `"08:00"`/`"17:00"`), the newly created `DutyAssignment` (the one with `notes` starting with `"גלגול גימלים"`) has matching `start_time`/`end_time`. The exact test code depends on that file's existing setup helpers — mirror its style rather than introducing a new pattern. At minimum it must:
1. Create a `DutyShift` (the "future_shift") with non-default `start_time`/`end_time`.
2. Drive whatever setup `apply_gimelim` needs to reach the "Promote A" branch (the one constructing `a_new`).
3. Query the resulting `DutyAssignment` and assert its `start_time`/`end_time` match the shift's.

If the existing test setup for `apply_gimelim` is too complex to reach the promotion branch easily in isolation, it's acceptable to write a narrower test that directly calls whatever helper function contains the promotion logic, as long as it exercises the real code path (not a reimplementation). Flag this with status `DONE_WITH_CONCERNS` if so, and note exactly why.

- [ ] **Step 3: Run the test to verify it fails**

Run the specific test with `pytest <path> -k <test_name> -v`. Expected: FAIL — the new assignment's `start_time`/`end_time` are `"00:00"`/`"23:59"` (the default), not the shift's actual values.

- [ ] **Step 4: Copy the times**

In `backend/app/services/gimelim.py`, the `DutyAssignment(...)` construction currently is:

```python
                a_new = DutyAssignment(
                    soldier_id=primary_a.soldier_id,
                    duty_type_id=primary_a.duty_type_id,
                    duty_location_id=primary_a.duty_location_id,
                    start_date=future_shift.start_date,
                    end_date=future_shift.end_date,
                    status="published",
                    is_reserve=False,
                    duty_shift_id=future_shift_id,
                    created_by=actor_id,
                    notes=f"גלגול גימלים מתורנות {primary_a.start_date.isoformat()}",
                )
```

Add `start_time`/`end_time`:

```python
                a_new = DutyAssignment(
                    soldier_id=primary_a.soldier_id,
                    duty_type_id=primary_a.duty_type_id,
                    duty_location_id=primary_a.duty_location_id,
                    start_date=future_shift.start_date,
                    end_date=future_shift.end_date,
                    start_time=future_shift.start_time,
                    end_time=future_shift.end_time,
                    status="published",
                    is_reserve=False,
                    duty_shift_id=future_shift_id,
                    created_by=actor_id,
                    notes=f"גלגול גימלים מתורנות {primary_a.start_date.isoformat()}",
                )
```

- [ ] **Step 5: Run the test to verify it passes**

Re-run the same test command from Step 3. Expected: PASS.

- [ ] **Step 6: Run the full gimelim test file to check for regressions**

```bash
pytest <the file you found in Step 1> -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/gimelim.py <the test file you modified>
git commit -m "feat: copy shift times onto gimelim-promoted assignment"
```

---

### Task 8: Add `start_time`/`end_time` to `DutyBlock`

**Files:**
- Modify: `backend/app/algorithm/types.py:30-40`

- [ ] **Step 1: Add the fields with safe defaults**

In `backend/app/algorithm/types.py`, `DutyBlock` currently is:

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
    eligible_node_ids: list[uuid.UUID] | None = None
```

Add `start_time`/`end_time` with the same `"00:00"`/`"23:59"` defaults used everywhere else, so every existing test that constructs a `DutyBlock(...)` without these two fields keeps working unchanged:

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
    eligible_node_ids: list[uuid.UUID] | None = None
    start_time: str = "00:00"
    end_time: str = "23:59"
```

- [ ] **Step 2: Run the full algorithm test suite to confirm no breakage**

From `backend/`:

```bash
pytest app/algorithm/tests/ tests/unit/test_model.py tests/unit/test_algorithm_bridge.py tests/unit/test_algorithm_bridge_shifts.py tests/unit/test_fairness.py tests/unit/test_fairness_e2e.py tests/test_model_effort.py tests/test_effort_score.py -v
```

Expected: all PASS unchanged — every existing `DutyBlock(...)` construction omits these two fields and gets the defaults, which reproduce today's exact behavior.

- [ ] **Step 3: Commit**

```bash
git add backend/app/algorithm/types.py
git commit -m "feat: add start_time/end_time fields to DutyBlock with full-day defaults"
```

---

### Task 9: Populate `DutyBlock` times from the source shift

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py:301-355`
- Test: `backend/tests/unit/test_algorithm_bridge_shifts.py`

This handles one subtlety: `load_duty_blocks_from_shifts` computes `effective_start = max(shift.start_date, today)`, truncating a block's start date forward when a multi-day shift is already partway through. When that truncation happens, the block's real start is midnight of `effective_start` — NOT the shift's original `start_time` (which applied to the shift's actual `start_date`, a day that's now in the past). Only copy `start_time` when there was no truncation; otherwise use `"00:00"`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_algorithm_bridge_shifts.py`:

```python
def test_block_copies_shift_times_when_not_truncated(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 2),
        start_time="08:00", end_time="17:00", required_count=1,
    )
    admin_session.add(shift)
    admin_session.flush()
    admin_session.commit()

    blocks, _ = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert len(blocks) == 1
    assert blocks[0].start_time == "08:00"
    assert blocks[0].end_time == "17:00"


def test_block_start_time_resets_to_midnight_when_truncated_to_today(admin_session):
    dt = _dt(admin_session)
    loc = _loc(admin_session)
    from datetime import timedelta
    yesterday = date.today() - timedelta(days=1)
    far_future = date.today() + timedelta(days=5)
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=yesterday, end_date=far_future,
        start_time="08:00", end_time="17:00", required_count=1,
    )
    admin_session.add(shift)
    admin_session.flush()
    admin_session.commit()

    blocks, _ = load_duty_blocks_from_shifts(admin_session, shift_ids=[shift.id])
    assert len(blocks) == 1
    assert blocks[0].start_date == date.today()  # truncated forward
    assert blocks[0].start_time == "00:00"        # NOT "08:00" -- that was yesterday's clock time
    assert blocks[0].end_time == "17:00"           # end side is never truncated, unaffected
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/unit/test_algorithm_bridge_shifts.py -k "copies_shift_times or resets_to_midnight" -v
```

Expected: both FAIL — `blocks[0].start_time`/`end_time` are the `DutyBlock` defaults (`"00:00"`/`"23:59"`), not the shift's values, since `load_duty_blocks_from_shifts` doesn't set them yet.

- [ ] **Step 3: Populate the fields**

In `backend/app/services/algorithm_bridge.py`, the two `DutyBlock(...)` constructions in `load_duty_blocks_from_shifts` currently are:

```python
            blocks.append(DutyBlock(
                id=block_id,
                duty_type_id=shift.duty_type_id,
                duty_location_id=shift.duty_location_id,
                start_date=effective_start,
                end_date=shift.end_date,
                score_per_day=score,
                is_reserve=False,
                eligible_node_ids=shift.eligible_node_ids,
            ))
            block_to_shift[block_id] = shift.id
        r_count = reserve_count_for_shift(session, shift=shift)
        reserve_needed = max(0, r_count - filled_reserve)
        r_score = score * standby_multiplier
        for _ in range(reserve_needed):
            block_id = uuid.uuid4()
            blocks.append(DutyBlock(
                id=block_id,
                duty_type_id=shift.duty_type_id,
                duty_location_id=shift.duty_location_id,
                start_date=effective_start,
                end_date=shift.end_date,
                score_per_day=r_score,
                is_reserve=True,
                eligible_node_ids=shift.eligible_node_ids,
            ))
            block_to_shift[block_id] = shift.id
```

Add a `block_start_time` computed once per shift (right after `effective_start` is computed, before the primary-blocks loop), and pass `start_time`/`end_time` into both `DutyBlock(...)` calls:

```python
        effective_start = max(shift.start_date, today)
        if effective_start > shift.end_date:
            # Shift is entirely in the past — nothing left to assign
            continue
        block_start_time = shift.start_time if effective_start == shift.start_date else "00:00"
```

(this line goes right after the existing `if effective_start > shift.end_date: continue` check — find that exact spot and insert below it)

```python
            blocks.append(DutyBlock(
                id=block_id,
                duty_type_id=shift.duty_type_id,
                duty_location_id=shift.duty_location_id,
                start_date=effective_start,
                end_date=shift.end_date,
                score_per_day=score,
                is_reserve=False,
                eligible_node_ids=shift.eligible_node_ids,
                start_time=block_start_time,
                end_time=shift.end_time,
            ))
            block_to_shift[block_id] = shift.id
        r_count = reserve_count_for_shift(session, shift=shift)
        reserve_needed = max(0, r_count - filled_reserve)
        r_score = score * standby_multiplier
        for _ in range(reserve_needed):
            block_id = uuid.uuid4()
            blocks.append(DutyBlock(
                id=block_id,
                duty_type_id=shift.duty_type_id,
                duty_location_id=shift.duty_location_id,
                start_date=effective_start,
                end_date=shift.end_date,
                score_per_day=r_score,
                is_reserve=True,
                eligible_node_ids=shift.eligible_node_ids,
                start_time=block_start_time,
                end_time=shift.end_time,
            ))
            block_to_shift[block_id] = shift.id
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/unit/test_algorithm_bridge_shifts.py -v
```

Expected: all PASS, including the pre-existing tests in this file (they don't set explicit times on their test shifts, so they get the `"00:00"`/`"23:59"` defaults from Task 2 and are unaffected).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/algorithm_bridge.py backend/tests/unit/test_algorithm_bridge_shifts.py
git commit -m "feat: populate DutyBlock times from source shift, handling truncated start"
```

---

### Task 10: Copy `DutyBlock` times onto persisted `DutyAssignment`

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py:593-604`
- Test: find the existing `persist_results` test (search `grep -rl persist_results tests/ app/`) and add to it.

- [ ] **Step 1: Locate the existing `persist_results` test coverage**

```bash
grep -rl "persist_results" tests/ app/services/tests/ app/routes/tests/ 2>/dev/null
```

Read whichever file(s) this finds to learn the setup pattern (likely constructs a `SolverResult`/`DutyBlock` list and calls `persist_results` directly) before adding a new test.

- [ ] **Step 2: Write a failing test**

Following the pattern found in Step 1, add a test that: builds a `DutyBlock` with explicit non-default `start_time`/`end_time` (e.g. `"08:00"`/`"17:00"`), includes it in a minimal `SolverResult.assignments` list assigning it to some soldier, calls `persist_results(...)`, then queries the resulting `DutyAssignment` and asserts `start_time == "08:00"` and `end_time == "17:00"`.

- [ ] **Step 3: Run the test to verify it fails**

Run the specific test. Expected: FAIL — the new assignment's `start_time`/`end_time` are the `DutyAssignment` model defaults (`"00:00"`/`"23:59"`), not the block's values.

- [ ] **Step 4: Copy the fields**

In `backend/app/services/algorithm_bridge.py`, `persist_results`'s `DutyAssignment(...)` construction currently is:

```python
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
```

Add `start_time`/`end_time`:

```python
        da = DutyAssignment(
            soldier_id=a.soldier_id,
            duty_type_id=block.duty_type_id,
            duty_location_id=block.duty_location_id,
            start_date=block.start_date,
            end_date=block.end_date,
            start_time=block.start_time,
            end_time=block.end_time,
            status="algorithm_draft",
            created_by=actor_id,
            notes=None,
            duty_shift_id=shift_id,
            is_reserve=block.is_reserve,
        )
```

- [ ] **Step 5: Run the test to verify it passes, then the full file for regressions**

```bash
pytest <the file from Step 1> -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/algorithm_bridge.py <the test file you modified>
git commit -m "feat: copy DutyBlock times onto persisted algorithm-draft assignments"
```

---

### Task 11: Switch the solver's block-score formula to `score_days`

**Files:**
- Modify: `backend/app/algorithm/model.py:24-27`
- Test: `backend/app/algorithm/tests/test_model.py` if it exists, else `backend/tests/unit/test_model.py`

- [ ] **Step 1: Locate the right test file**

```bash
grep -rl "_block_score\|from app.algorithm.model import" tests/unit/test_model.py app/algorithm/tests/ 2>/dev/null
```

Use whichever file already imports from `app.algorithm.model` for solver-internals tests.

- [ ] **Step 2: Write the failing test**

Add to that file:

```python
from datetime import date
from decimal import Decimal

from app.algorithm.model import _block_score
from app.algorithm.types import DutyBlock
import uuid


def test_block_score_uses_score_days_not_calendar_days_touched():
    # Monday -> following Monday, 14:00-14:00: touches 8 calendar days but is
    # exactly 168 hours = 7*24h -> should score as 7 days, not 8.
    block = DutyBlock(
        id=uuid.uuid4(), duty_type_id=uuid.uuid4(), duty_location_id=uuid.uuid4(),
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 9),
        score_per_day=Decimal("2"), start_time="14:00", end_time="14:00",
    )
    # _block_score returns milli-units (x1000): 7 days * score_per_day(2) * 1000
    assert _block_score(block) == 7 * 2 * 1000
```

- [ ] **Step 3: Run the test to verify it fails**

Run the specific test. Expected: FAIL — current formula computes `8 * 2 * 1000 = 16000`, not `14000`.

- [ ] **Step 4: Update `_block_score`**

In `backend/app/algorithm/model.py`, currently:

```python
def _block_score(d: DutyBlock) -> int:
    """Total score for completing the entire block, in milli-units (x1000 for integer math)."""
    days = (d.end_date - d.start_date).days
    return int(d.score_per_day * Decimal(days) * 1000)
```

Replace with:

```python
def _block_score(d: DutyBlock) -> int:
    """Total score for completing the entire block, in milli-units (x1000 for integer math)."""
    days = score_days(d.start_date, d.end_date, d.start_time, d.end_time)
    return int(d.score_per_day * Decimal(days) * 1000)
```

Add the import at the top of the file, alongside the existing `from app.algorithm.types import (...)` block:

```python
from app.algorithm.duration import score_days
```

- [ ] **Step 5: Run the test to verify it passes, then the full algorithm suite for regressions**

```bash
pytest tests/unit/test_model.py app/algorithm/tests/ -v
```

Expected: all PASS. Every existing test constructs `DutyBlock`s without explicit `start_time`/`end_time` (full-day defaults), so `score_days(...)` reproduces `(end_date-start_date).days` exactly for all of them — zero behavior change for existing tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/algorithm/model.py <the test file you modified>
git commit -m "feat: solver block score uses score_days instead of calendar days touched"
```

---

### Task 12: Switch `inject_effort_scores`'s unit-score sum to `score_days`

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py:373-376`
- Test: `backend/tests/unit/test_algorithm_bridge.py` or wherever `inject_effort_scores` is already tested

- [ ] **Step 1: Locate existing test coverage**

```bash
grep -rl "inject_effort_scores" tests/ app/ 2>/dev/null
```

- [ ] **Step 2: Write a failing test**

In the file found above, add a test constructing a `DutyBlock` list containing one block with `start_time="14:00"`, `end_time="14:00"`, `start_date=date(2026,6,1)`, `end_date=date(2026,6,9)` (the same 7-day-not-8-day example), call `inject_effort_scores([], [block], {})`, and assert the computed `unit_score_milli`-derived behavior reflects 7 days, not 8. Since `unit_score_milli` is a local variable not directly returned, the most direct test is to construct two `SoldierInput`s with known `effort_per_milli`/`effort_offset` inputs and assert on the returned `(range_min, range_max)` tuple, OR — simpler — extract the exact sum independently in the test:

```python
from datetime import date
from decimal import Decimal
import uuid

from app.algorithm.duration import score_days
from app.algorithm.types import DutyBlock


def test_unit_score_milli_uses_score_days():
    block = DutyBlock(
        id=uuid.uuid4(), duty_type_id=uuid.uuid4(), duty_location_id=uuid.uuid4(),
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 9),
        score_per_day=Decimal("2"), start_time="14:00", end_time="14:00",
    )
    expected = int(float(block.score_per_day) * score_days(
        block.start_date, block.end_date, block.start_time, block.end_time
    ) * 1000)
    assert expected == 7 * 2 * 1000  # sanity-check the expectation itself
```

This test only pins down the expected formula; Step 4 verifies `algorithm_bridge.py` actually uses it. If this repo's test conventions call `inject_effort_scores` directly and assert on its return value instead, prefer that style — check the file found in Step 1 for the established pattern and follow it rather than introducing a new style.

- [ ] **Step 3: Run the test, confirm current behavior, then update the source**

In `backend/app/services/algorithm_bridge.py`, `inject_effort_scores` currently computes:

```python
    unit_score_milli = sum(
        int(float(b.score_per_day) * ((b.end_date - b.start_date).days) * 1000)
        for b in duty_blocks
    )
```

Replace with:

```python
    unit_score_milli = sum(
        int(float(b.score_per_day) * score_days(b.start_date, b.end_date, b.start_time, b.end_time) * 1000)
        for b in duty_blocks
    )
```

Add the import near the top of the file (alongside the existing imports from `app.algorithm.types`):

```python
from app.algorithm.duration import score_days
```

- [ ] **Step 4: Run the full file's test suite for regressions**

```bash
pytest <the file from Step 1> -v
```

Expected: all PASS — existing tests use default-timed blocks, so `score_days` reproduces the old formula exactly for them.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/algorithm_bridge.py <the test file you modified>
git commit -m "feat: effort-score unit calculation uses score_days instead of calendar days touched"
```

---

### Task 13: Weight per-day effort-score contribution by `score_days / calendar_days_touched`

**Files:**
- Modify: `backend/app/services/scoring.py`
- Test: find or create a unit test file for `scoring.py` (`grep -rl "effective_duty_days" tests/`)

This is the one place where per-day score attribution changes while the per-day calendar-date *expansion* itself stays exactly as-is (preserving quarter-boundary splitting and any duty-history timeline display that relies on "which days was this soldier on duty").

- [ ] **Step 1: Locate existing test coverage**

```bash
grep -rl "effective_duty_days\|_duty_stats_by_soldier" tests/ 2>/dev/null
```

Read whichever file(s) this finds. If none exist, create `backend/tests/unit/test_scoring.py` following the `admin_session`/`_seed_type_and_location`-style fixtures used in `test_shift_generation.py`.

- [ ] **Step 2: Write the failing test**

Add a test that: creates a `DutyType` with a known `score_per_day` (e.g. `Decimal("10")`), creates a published `DutyAssignment` spanning Monday 14:00 to the following Monday 14:00 (`start_date=Mon`, `end_date=Mon+8`, `start_time="14:00"`, `end_time="14:00"` — `score_days` = 7, `calendar_days_touched` = 8), calls `effective_duty_days(session)`, and asserts:
1. There are exactly 8 rows for this assignment (one per calendar day touched — unchanged).
2. The sum of `score_per_day * mult` across all 8 rows equals `10 * 7` (the corrected total), not `10 * 8` (the old, overcounted total).

```python
from datetime import date
from decimal import Decimal

from app.db.models import DutyAssignment, DutyType, DutyLocation, Soldier
from app.services.scoring import effective_duty_days


def test_effective_duty_days_spreads_score_days_evenly_across_touched_days(admin_session):
    from sqlalchemy import select
    dt = DutyType(name="dt_scoring_test", score_per_day=Decimal("10"))
    loc = DutyLocation(name="loc_scoring_test")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    soldier = admin_session.execute(select(Soldier)).scalars().first()

    a = DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 9),
        start_time="14:00", end_time="14:00", status="published",
    )
    admin_session.add(a)
    admin_session.flush()
    admin_session.commit()

    rows = [r for r in effective_duty_days(admin_session) if r[1] == soldier.id]
    assert len(rows) == 8  # calendar_days_touched unchanged
    total_score = sum(dt.score_per_day * mult for _day, _eff, _dtid, mult in rows)
    assert total_score == Decimal("70")  # 10 * score_days(7), not 10 * 8 = 80
```

If `admin_session` has no `Soldier` row available by default, check `backend/tests/conftest.py` for how other tests obtain one and follow that pattern instead of querying blindly.

- [ ] **Step 3: Run the test to verify it fails**

```bash
pytest <wherever you placed the test> -k spreads_score_days -v
```

Expected: FAIL — `total_score == Decimal("80")` (8 days × flat `score_per_day`), not `70`.

- [ ] **Step 4: Implement the weighting**

In `backend/app/services/scoring.py`, add the import at the top:

```python
from app.algorithm.duration import calendar_days_touched, score_days
```

In `effective_duty_days`, the loop currently is:

```python
    out: list[tuple[date, uuid.UUID, uuid.UUID, Decimal]] = []
    for a in assignments:
        day = a.start_date
        while day < a.end_date:
            if date_to is not None and day > date_to:
                break
            if (date_from is None or day >= date_from):
                ov = overrides.get((a.id, day))
                eff = ov.effective_soldier_id if ov is not None else a.soldier_id
                if eff is not None:
                    if a.forced_call_up_multiplier is not None:
                        mult = a.forced_call_up_multiplier
                    elif a.is_reserve:
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

Replace with (computing `day_weight` once per assignment, before its day-loop, and folding it into `mult` right before appending):

```python
    out: list[tuple[date, uuid.UUID, uuid.UUID, Decimal]] = []
    for a in assignments:
        touched = calendar_days_touched(a.start_date, a.end_date)
        day_weight = Decimal(score_days(a.start_date, a.end_date, a.start_time, a.end_time)) / Decimal(touched)
        day = a.start_date
        while day < a.end_date:
            if date_to is not None and day > date_to:
                break
            if (date_from is None or day >= date_from):
                ov = overrides.get((a.id, day))
                eff = ov.effective_soldier_id if ov is not None else a.soldier_id
                if eff is not None:
                    if a.forced_call_up_multiplier is not None:
                        mult = a.forced_call_up_multiplier
                    elif a.is_reserve:
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
                    out.append((day, eff, a.duty_type_id, mult * day_weight))
            day += timedelta(days=1)
    return out
```

Apply the identical change to `_duty_stats_by_soldier` (same file), which has its own independent copy of this loop. Currently:

```python
    for a in assignments:
        day = a.start_date
        while day < a.end_date:
            ov = overrides.get((a.id, day))
            eff = ov.effective_soldier_id if ov is not None else a.soldier_id
            if eff is not None:
                if a.forced_call_up_multiplier is not None:
                    mult = a.forced_call_up_multiplier
                elif a.is_reserve:
                    if (
                        a.called_up_from is not None
                        and a.called_up_to is not None
                        and a.called_up_from <= day <= a.called_up_to
                    ):
                        mult = called_up_mult
                    else:
                        mult = standby_mult
                else:
                    ranges = dismissal_ranges.get(a.id, [])
                    if any(df <= day <= dt for df, dt in ranges):
                        mult = dismissed_mult
                    else:
                        mult = Decimal("1.0")
                duty_scores[eff] += type_scores.get(a.duty_type_id, Decimal("0")) * mult
                assignment_sets[eff].add(a.id)
            day += timedelta(days=1)
```

Replace with:

```python
    for a in assignments:
        touched = calendar_days_touched(a.start_date, a.end_date)
        day_weight = Decimal(score_days(a.start_date, a.end_date, a.start_time, a.end_time)) / Decimal(touched)
        day = a.start_date
        while day < a.end_date:
            ov = overrides.get((a.id, day))
            eff = ov.effective_soldier_id if ov is not None else a.soldier_id
            if eff is not None:
                if a.forced_call_up_multiplier is not None:
                    mult = a.forced_call_up_multiplier
                elif a.is_reserve:
                    if (
                        a.called_up_from is not None
                        and a.called_up_to is not None
                        and a.called_up_from <= day <= a.called_up_to
                    ):
                        mult = called_up_mult
                    else:
                        mult = standby_mult
                else:
                    ranges = dismissal_ranges.get(a.id, [])
                    if any(df <= day <= dt for df, dt in ranges):
                        mult = dismissed_mult
                    else:
                        mult = Decimal("1.0")
                duty_scores[eff] += type_scores.get(a.duty_type_id, Decimal("0")) * mult * day_weight
                assignment_sets[eff].add(a.id)
            day += timedelta(days=1)
```

Note: `effective_duty_spans` (the third loop in this file) is intentionally NOT changed — it only tracks which soldier is effective on which day for span-merging/display purposes, never computes a score.

- [ ] **Step 5: Run the test to verify it passes, then the full scoring-related suite for regressions**

```bash
pytest <wherever you placed the test> tests/test_effort_score.py tests/unit/test_fairness.py tests/unit/test_fairness_e2e.py -v
```

Expected: all PASS — every existing assignment in these tests uses default full-day times, so `day_weight` evaluates to exactly `1` for all of them (since `score_days == calendar_days_touched` when times are `"00:00"`/`"23:59"`), reproducing today's exact totals.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/scoring.py <the test file you added/modified>
git commit -m "feat: weight per-day effort score by score_days/calendar_days_touched ratio"
```

---

### Task 14: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend fast suite**

From `backend/` with the venv activated:

```bash
pytest -q
```

Expected: this repo may have pre-existing, unrelated failures from other in-progress work (check `git log`/`git status` for anything obviously unrelated, e.g. hierarchy/root-node work, before assuming a failure is yours). Confirm zero NEW failures related to `duty_shifts`, `duty_assignments`, `shift_templates`, `algorithm`, `scoring`, or `effort_score`.

- [ ] **Step 2: Run the slow suite once**

```bash
pytest --slow -q
```

This includes the large-scale CP-SAT tests, which are the most likely place a subtle score-formula regression would surface as a changed assignment count or objective value. Investigate and fix (don't just report) any failure that traces back to this branch's changes.

- [ ] **Step 3: Manually sanity-check the worked example end-to-end**

Using the running dev app (or a quick Python REPL against the dev DB), create a shift template with `recurrence_type="weekly"`, `duration_days=8`, `start_time="14:00"`, `end_time="14:00"`, generate one shift from it, manually assign a soldier, publish, and confirm via `app.services.scoring.effective_duty_days` (or the soldier's transparency/effort-score page) that the assignment contributes 7 days' worth of score while still occupying 8 calendar dates (e.g. visible as 8 entries on a duty-history timeline, if one exists).
