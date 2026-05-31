# v2: Shift Templates + Duty Swaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add (A) reusable weekly recurring shift templates that auto-generate empty `duty_shifts` over a rolling horizon, and (B) duty swap/cover so a soldier can hand a duty to a peer (direct request or open board) with configurable, two-sided manager approval.

**Architecture:** Backend follows the existing service/route split — services own business logic + `write_audit` calls and never commit; routes own `authorize(...)` + `session.commit()`. Two new tables (`shift_templates`, `swap_requests`) via additive Alembic migrations 0023/0024. Feature A generation is a pure-ish service that materialises `DutyShift` rows idempotently from a template's weekly rule; an auto-roll entry point reuses it. Feature B reuses the `duty_day_overrides.effective_soldier_id` layer (via `assignments.set_day_override`) so an approved cover credits the covering soldier automatically in scoring. Frontend mirrors the existing `api/*.ts` + `pages/*.tsx` + TanStack Query patterns, Hebrew RTL.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x (MappedAsDataclass), Alembic, Pydantic v2, Postgres 16, pytest + testcontainers, React 18 + Vite + TS, react-i18next, axios, TanStack Query. Same toolchain as slices 1–10.

---

## Spec coverage

Implements [the v2 re-scope brainstorm](../specs/2026-05-30-v2-rescope-brainstorm.md):

- **Feature A** (templates + recurrence + hybrid auto-roll generation): Tasks 1–9.
- **Feature B** (direct + open-board cover, one-way primary, configurable two-sided approval): Tasks 10–19.
- **Wiring + docs + memory:** Task 20.

Deferred per spec (NOT in this plan): greedy online mode, punishment duties, compensation workflow, notifications, two-way trade UI (schema supports it; no UI), per-unit template ownership.

## File structure

**Feature A — backend**
- Create `backend/alembic/versions/0023_shift_templates.py` — `shift_templates` table.
- Modify `backend/app/db/models.py` — add `ShiftTemplate`, add `generated_from_template_id` + `dm_locked` to `DutyShift`.
- Create `backend/app/services/shift_templates.py` — CRUD + recurrence expansion + idempotent generation + auto-roll.
- Create `backend/app/routes/shift_templates.py` — REST + preview + generate endpoints.
- Create `backend/app/services/tests/test_shift_templates.py` — recurrence + idempotency tests (pure, no DB where possible).

**Feature A — frontend**
- Create `frontend/src/api/shiftTemplates.ts`
- Create `frontend/src/pages/ShiftTemplatesPage.tsx`
- Create `frontend/src/components/ShiftTemplateFormModal.tsx`
- Create `frontend/src/components/GenerateShiftsModal.tsx`

**Feature B — backend**
- Create `backend/alembic/versions/0024_swap_requests.py` — `swap_requests` table.
- Modify `backend/app/db/models.py` — add `SwapRequest`.
- Modify `backend/app/auth/authz.py` — add `SWAP_APPROVE` action.
- Create `backend/app/services/swaps.py` — create/offer/accept/approve/reject/apply→override.
- Create `backend/app/routes/swaps.py` — REST.
- Create `backend/app/services/tests/test_swaps.py`

**Feature B — frontend**
- Create `frontend/src/api/swaps.ts`
- Create `frontend/src/pages/SwapsPage.tsx` (board + my requests)
- Modify `frontend/src/pages/ApprovalsPage.tsx` — add swaps approval tab.

**Wiring**
- Modify `backend/app/main.py` — include the two new routers.
- Modify `frontend/src/App.tsx` + `frontend/src/components/Layout.tsx` — routes + nav.
- Modify `frontend/src/i18n/index.ts` — Hebrew keys.

## Conventions to follow (verified against current code)

- Models use `MappedAsDataclass`; every column needs `default=`/`default_factory=`/`init=False`. PK pattern: `mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)`. Timestamps: `server_default=text("now()"), init=False`.
- Services import `from app.audit.writer import write_audit` and call it for every state change; services call `session.flush()` (never `commit()`).
- Routes call `authorize(session, user, Action.X, target_node=...)` then `session.commit()`. DM-global actions (`ASSIGNMENT_MANAGE`, `ALGORITHM_RUN`) pass `target_node=None`.
- Settings read via `get_setting` / fallback helper, mirroring `_get_setting_with_default` in `services/constraints.py`.
- A cover is applied through `assignments.set_day_override(...)` with `reason="replacement"` (already in `_OVERRIDE_REASONS`), which already enforces overlap + blocking-exemption checks and credits the effective soldier in scoring.
- Migrations: `revision`/`down_revision` string ids, reversible `upgrade`/`downgrade`. Latest is `0022`.

---

## Task 1: ShiftTemplate model + DutyShift generation columns

**Files:**
- Modify: `backend/app/db/models.py` (after `DutyShift`, ends line ~299)
- Modify: `backend/app/db/models.py:289` (`DutyShift` body — add two columns)

- [ ] **Step 1: Add generation-tracking columns to `DutyShift`**

In `backend/app/db/models.py`, inside `class DutyShift`, immediately after the `notes` column (line ~290) add:

```python
    generated_from_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shift_templates.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    dm_locked: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
```

- [ ] **Step 2: Add the `ShiftTemplate` model**

In `backend/app/db/models.py`, add after `class DutyShift` (after line ~299):

```python
class ShiftTemplate(Base):
    __tablename__ = "shift_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    name: Mapped[str] = mapped_column(Text)
    duty_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_types.id", ondelete="RESTRICT")
    )
    duty_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_locations.id", ondelete="RESTRICT")
    )
    # ISO weekday numbers the shift recurs on: 1=Mon … 7=Sun
    weekdays: Mapped[list[Any]] = mapped_column(JSONB, default_factory=list)
    start_time: Mapped[str] = mapped_column(Text, default="00:00")  # "HH:MM"
    end_time: Mapped[str] = mapped_column(Text, default="23:59")    # "HH:MM"
    required_count: Mapped[int] = mapped_column(server_default=text("1"), default=1)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    auto_roll: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
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

- [ ] **Step 3: Verify import still works**

Run: `cd backend && .venv/Scripts/python.exe -c "import app.db.models; print('OK')"`
Expected: `OK` (no "already defined" or NameError).

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat(v2): ShiftTemplate model + DutyShift generation columns"
```

---

## Task 2: Migration 0023 — shift_templates

**Files:**
- Create: `backend/alembic/versions/0023_shift_templates.py`

- [ ] **Step 1: Write the migration**

```python
"""shift_templates table + duty_shifts generation columns

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shift_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("duty_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("duty_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("duty_location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("duty_locations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("weekdays", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("start_time", sa.Text(), server_default=sa.text("'00:00'"), nullable=False),
        sa.Column("end_time", sa.Text(), server_default=sa.text("'23:59'"), nullable=False),
        sa.Column("required_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("auto_roll", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.add_column(
        "duty_shifts",
        sa.Column("generated_from_template_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("shift_templates.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "duty_shifts",
        sa.Column("dm_locked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("duty_shifts", "dm_locked")
    op.drop_column("duty_shifts", "generated_from_template_id")
    op.drop_table("shift_templates")
```

- [ ] **Step 2: Apply the migration**

Run: `cd backend && .venv/Scripts/alembic upgrade head`
Expected: ends at `0023`, no error.

- [ ] **Step 3: Verify reversibility**

Run: `cd backend && .venv/Scripts/alembic downgrade -1 && .venv/Scripts/alembic upgrade head`
Expected: clean down then up, ends at `0023`.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/0023_shift_templates.py
git commit -m "feat(v2): migration 0023 shift_templates"
```

---

## Task 3: Recurrence expansion (pure function) — failing test

**Files:**
- Create: `backend/app/services/tests/__init__.py` (if absent)
- Create: `backend/app/services/tests/test_shift_templates.py`
- Create (next task): `backend/app/services/shift_templates.py`

- [ ] **Step 1: Ensure the tests package exists**

If `backend/app/services/tests/__init__.py` does not exist, create it empty.

- [ ] **Step 2: Write the failing test for `expand_dates`**

Create `backend/app/services/tests/test_shift_templates.py`:

```python
from datetime import date

from app.services.shift_templates import expand_dates


def test_expand_dates_weekly_filters_to_selected_weekdays():
    # 2026-06-01 is a Monday. Select Mon(1), Wed(3), Fri(5).
    out = expand_dates(
        weekdays=[1, 3, 5],
        range_start=date(2026, 6, 1),
        range_end=date(2026, 6, 7),
    )
    assert out == [date(2026, 6, 1), date(2026, 6, 3), date(2026, 6, 5)]


def test_expand_dates_empty_weekdays_returns_nothing():
    out = expand_dates(weekdays=[], range_start=date(2026, 6, 1), range_end=date(2026, 6, 7))
    assert out == []


def test_expand_dates_inclusive_bounds():
    # Sunday is ISO 7. 2026-06-07 is a Sunday.
    out = expand_dates(weekdays=[7], range_start=date(2026, 6, 1), range_end=date(2026, 6, 7))
    assert out == [date(2026, 6, 7)]
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/services/tests/test_shift_templates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.shift_templates'`.

---

## Task 4: Recurrence expansion — implement

**Files:**
- Create: `backend/app/services/shift_templates.py`

- [ ] **Step 1: Create the module with `expand_dates`**

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyShift, ShiftTemplate


class TemplateError(Exception):
    """Raised on invalid template operations."""


def expand_dates(*, weekdays: list[int], range_start: date, range_end: date) -> list[date]:
    """Return every date in [range_start, range_end] whose ISO weekday is in `weekdays`.

    ISO weekday: Mon=1 … Sun=7. Order preserved (ascending by date).
    """
    selected = set(weekdays)
    out: list[date] = []
    if not selected or range_end < range_start:
        return out
    day = range_start
    while day <= range_end:
        if day.isoweekday() in selected:
            out.append(day)
        day += timedelta(days=1)
    return out
```

- [ ] **Step 2: Run to verify pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/services/tests/test_shift_templates.py -v`
Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/shift_templates.py backend/app/services/tests/__init__.py backend/app/services/tests/test_shift_templates.py
git commit -m "feat(v2): shift template recurrence expansion"
```

---

## Task 5: Template CRUD service

**Files:**
- Modify: `backend/app/services/shift_templates.py`

- [ ] **Step 1: Add a dataclass + CRUD functions**

Append to `backend/app/services/shift_templates.py`:

```python
_VALID_WEEKDAYS = {1, 2, 3, 4, 5, 6, 7}


def _validate(weekdays: list[int], required_count: int, start_time: str, end_time: str) -> None:
    if not weekdays or not set(weekdays) <= _VALID_WEEKDAYS:
        raise TemplateError("invalid_weekdays")
    if required_count < 1:
        raise TemplateError("invalid_required_count")
    for t in (start_time, end_time):
        parts = t.split(":")
        if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
            raise TemplateError("invalid_time")


def create_template(
    session: Session,
    *,
    name: str,
    duty_type_id: uuid.UUID,
    duty_location_id: uuid.UUID,
    weekdays: list[int],
    start_time: str = "00:00",
    end_time: str = "23:59",
    required_count: int = 1,
    auto_roll: bool = False,
    notes: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> ShiftTemplate:
    _validate(weekdays, required_count, start_time, end_time)
    tpl = ShiftTemplate(
        name=name,
        duty_type_id=duty_type_id,
        duty_location_id=duty_location_id,
        weekdays=sorted(set(weekdays)),
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
        after={"name": name, "weekdays": tpl.weekdays, "auto_roll": auto_roll},
    )
    return tpl


def list_templates(session: Session, *, include_inactive: bool = False) -> list[ShiftTemplate]:
    q = select(ShiftTemplate)
    if not include_inactive:
        q = q.where(ShiftTemplate.active.is_(True))
    return list(session.execute(q.order_by(ShiftTemplate.name)).scalars().all())


def update_template(
    session: Session,
    *,
    tpl: ShiftTemplate,
    name: str | None = None,
    weekdays: list[int] | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    required_count: int | None = None,
    auto_roll: bool | None = None,
    active: bool | None = None,
    notes: object = ...,
    actor_id: uuid.UUID | None = None,
) -> ShiftTemplate:
    before = {"name": tpl.name, "weekdays": tpl.weekdays, "active": tpl.active, "auto_roll": tpl.auto_roll}
    if name is not None:
        tpl.name = name
    if weekdays is not None:
        tpl.weekdays = sorted(set(weekdays))
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
    _validate(tpl.weekdays, tpl.required_count, tpl.start_time, tpl.end_time)
    write_audit(
        session,
        actor_id=actor_id,
        action="shift_template.update",
        entity_type="shift_template",
        entity_id=tpl.id,
        before=before,
        after={"name": tpl.name, "weekdays": tpl.weekdays, "active": tpl.active, "auto_roll": tpl.auto_roll},
    )
    return tpl


def delete_template(session: Session, *, tpl: ShiftTemplate, actor_id: uuid.UUID | None = None) -> None:
    write_audit(
        session,
        actor_id=actor_id,
        action="shift_template.delete",
        entity_type="shift_template",
        entity_id=tpl.id,
        before={"name": tpl.name},
    )
    session.delete(tpl)
```

- [ ] **Step 2: Verify import**

Run: `cd backend && .venv/Scripts/python.exe -c "from app.services import shift_templates; print('OK')"`
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/shift_templates.py
git commit -m "feat(v2): shift template CRUD service"
```

---

## Task 6: Idempotent generation — failing test

**Files:**
- Modify: `backend/app/services/tests/test_shift_templates.py`

- [ ] **Step 1: Add generation tests (DB-backed, use existing conftest session fixture)**

First confirm the integration fixture name. Run: `cd backend && grep -rn "def session" app/routes/tests/conftest.py` — expect a `session` fixture yielding a `Session`. Use the same fixture by importing the conftest path; integration tests live alongside routes. Create these in `backend/app/routes/tests/test_shift_generation.py` instead so they pick up the DB `session` fixture:

Create `backend/app/routes/tests/test_shift_generation.py`:

```python
from datetime import date

from app.db.models import DutyShift, DutyLocation, DutyType
from app.services import shift_templates as svc


def _seed_type_and_location(session):
    dt = DutyType(name="שמירה-gen", score_per_day=1)
    loc = DutyLocation(name="עמדה-gen")
    session.add(dt)
    session.add(loc)
    session.flush()
    return dt, loc


def test_generate_creates_one_shift_per_matching_day(session):
    dt, loc = _seed_type_and_location(session)
    tpl = svc.create_template(
        session, name="t1", duty_type_id=dt.id, duty_location_id=loc.id,
        weekdays=[1, 3, 5], required_count=2,
    )
    session.flush()
    created = svc.generate_shifts(
        session, tpl=tpl, range_start=date(2026, 6, 1), range_end=date(2026, 6, 7),
    )
    assert len(created) == 3  # Mon, Wed, Fri
    assert all(s.required_count == 2 for s in created)
    assert all(s.generated_from_template_id == tpl.id for s in created)


def test_generate_is_idempotent(session):
    dt, loc = _seed_type_and_location(session)
    tpl = svc.create_template(
        session, name="t2", duty_type_id=dt.id, duty_location_id=loc.id, weekdays=[1],
    )
    session.flush()
    first = svc.generate_shifts(session, tpl=tpl, range_start=date(2026, 6, 1), range_end=date(2026, 6, 14))
    session.flush()
    second = svc.generate_shifts(session, tpl=tpl, range_start=date(2026, 6, 1), range_end=date(2026, 6, 14))
    assert len(first) == 2   # two Mondays
    assert len(second) == 0  # already present → no duplicates


def test_preview_reports_existing_vs_new(session):
    dt, loc = _seed_type_and_location(session)
    tpl = svc.create_template(
        session, name="t3", duty_type_id=dt.id, duty_location_id=loc.id, weekdays=[1],
    )
    session.flush()
    svc.generate_shifts(session, tpl=tpl, range_start=date(2026, 6, 1), range_end=date(2026, 6, 1))
    session.flush()
    preview = svc.preview_generation(session, tpl=tpl, range_start=date(2026, 6, 1), range_end=date(2026, 6, 8))
    new_dates = [p["date"] for p in preview if not p["exists"]]
    existing_dates = [p["date"] for p in preview if p["exists"]]
    assert date(2026, 6, 8) in new_dates
    assert date(2026, 6, 1) in existing_dates
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/routes/tests/test_shift_generation.py -v`
Expected: FAIL — `AttributeError: module 'app.services.shift_templates' has no attribute 'generate_shifts'`.

---

## Task 7: Idempotent generation + preview — implement

**Files:**
- Modify: `backend/app/services/shift_templates.py`

- [ ] **Step 1: Add `preview_generation` and `generate_shifts`**

Append to `backend/app/services/shift_templates.py`:

```python
def _existing_dates(
    session: Session, *, template_id: uuid.UUID, dates: list[date]
) -> set[date]:
    """Dates in `dates` that already have a shift generated from this template
    (single-day shift, start_date == end_date == d)."""
    if not dates:
        return set()
    rows = session.execute(
        select(DutyShift.start_date).where(
            DutyShift.generated_from_template_id == template_id,
            DutyShift.start_date.in_(dates),
        )
    ).scalars().all()
    return set(rows)


def preview_generation(
    session: Session, *, tpl: ShiftTemplate, range_start: date, range_end: date
) -> list[dict]:
    """Return [{date, exists}] for each recurring date in the range. No mutation."""
    dates = expand_dates(weekdays=tpl.weekdays, range_start=range_start, range_end=range_end)
    existing = _existing_dates(session, template_id=tpl.id, dates=dates)
    return [{"date": d, "exists": d in existing} for d in dates]


def generate_shifts(
    session: Session,
    *,
    tpl: ShiftTemplate,
    range_start: date,
    range_end: date,
    actor_id: uuid.UUID | None = None,
) -> list[DutyShift]:
    """Idempotently create one single-day DutyShift per recurring date that does not
    already have one from this template. Returns the newly created shifts."""
    dates = expand_dates(weekdays=tpl.weekdays, range_start=range_start, range_end=range_end)
    existing = _existing_dates(session, template_id=tpl.id, dates=dates)
    created: list[DutyShift] = []
    for d in dates:
        if d in existing:
            continue
        shift = DutyShift(
            duty_type_id=tpl.duty_type_id,
            duty_location_id=tpl.duty_location_id,
            start_date=d,
            end_date=d,
            required_count=tpl.required_count,
            notes=tpl.notes,
            created_by=actor_id,
            generated_from_template_id=tpl.id,
        )
        session.add(shift)
        created.append(shift)
    session.flush()
    if created:
        write_audit(
            session,
            actor_id=actor_id,
            action="shift_template.generate",
            entity_type="shift_template",
            entity_id=tpl.id,
            after={"created_count": len(created), "range_start": range_start.isoformat(), "range_end": range_end.isoformat()},
        )
    return created
```

- [ ] **Step 2: Run to verify pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/routes/tests/test_shift_generation.py -v`
Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/shift_templates.py backend/app/routes/tests/test_shift_generation.py
git commit -m "feat(v2): idempotent shift generation + preview"
```

---

## Task 8: Auto-roll horizon entry point

**Files:**
- Modify: `backend/app/services/shift_templates.py`
- Modify: `backend/app/routes/tests/test_shift_generation.py`

- [ ] **Step 1: Add failing test for `roll_horizon`**

Append to `backend/app/routes/tests/test_shift_generation.py`:

```python
def test_roll_horizon_generates_only_for_auto_roll_templates(session):
    dt, loc = _seed_type_and_location(session)
    rolling = svc.create_template(
        session, name="auto", duty_type_id=dt.id, duty_location_id=loc.id, weekdays=[1,2,3,4,5,6,7], auto_roll=True,
    )
    manual = svc.create_template(
        session, name="manual", duty_type_id=dt.id, duty_location_id=loc.id, weekdays=[1,2,3,4,5,6,7], auto_roll=False,
    )
    session.flush()
    total = svc.roll_horizon(session, horizon_days=10, today=date(2026, 6, 1))
    assert total == 10  # 10 days, every weekday, only the auto_roll template
    rolled = session.query(DutyShift).filter(DutyShift.generated_from_template_id == rolling.id).count()
    not_rolled = session.query(DutyShift).filter(DutyShift.generated_from_template_id == manual.id).count()
    assert rolled == 10
    assert not_rolled == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/routes/tests/test_shift_generation.py::test_roll_horizon_generates_only_for_auto_roll_templates -v`
Expected: FAIL — no attribute `roll_horizon`.

- [ ] **Step 3: Implement `roll_horizon`**

Append to `backend/app/services/shift_templates.py`:

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

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/routes/tests/test_shift_generation.py -v`
Expected: all passed (4).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/shift_templates.py backend/app/routes/tests/test_shift_generation.py
git commit -m "feat(v2): auto-roll horizon for shift templates"
```

---

## Task 9: Shift template routes (CRUD + preview + generate + roll)

**Files:**
- Create: `backend/app/routes/shift_templates.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create the router**

```python
from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import ShiftTemplate, Soldier
from app.db.session import get_session
from app.services import shift_templates as svc

router = APIRouter(prefix="/shift-templates", tags=["shift-templates"])


class TemplateOut(BaseModel):
    id: uuid.UUID
    name: str
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    weekdays: list[int]
    start_time: str
    end_time: str
    required_count: int
    active: bool
    auto_roll: bool
    notes: str | None


class CreateTemplateRequest(BaseModel):
    name: str = Field(max_length=200)
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    weekdays: list[int]
    start_time: str = "00:00"
    end_time: str = "23:59"
    required_count: int = Field(default=1, ge=1)
    auto_roll: bool = False
    notes: str | None = Field(default=None, max_length=1000)


class UpdateTemplateRequest(BaseModel):
    name: str | None = None
    weekdays: list[int] | None = None
    start_time: str | None = None
    end_time: str | None = None
    required_count: int | None = Field(default=None, ge=1)
    auto_roll: bool | None = None
    active: bool | None = None
    notes: str | None = None


class GenerateRequest(BaseModel):
    range_start: date
    range_end: date


class PreviewRow(BaseModel):
    date: date
    exists: bool


class GenerateResult(BaseModel):
    created_count: int


def _out(t: ShiftTemplate) -> TemplateOut:
    return TemplateOut(
        id=t.id, name=t.name, duty_type_id=t.duty_type_id, duty_location_id=t.duty_location_id,
        weekdays=t.weekdays, start_time=t.start_time, end_time=t.end_time,
        required_count=t.required_count, active=t.active, auto_roll=t.auto_roll, notes=t.notes,
    )


def _load(session: Session, template_id: uuid.UUID) -> ShiftTemplate:
    t = session.get(ShiftTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return t


@router.get("", response_model=list[TemplateOut])
def list_templates(
    include_inactive: bool = False,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[TemplateOut]:
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    return [_out(t) for t in svc.list_templates(session, include_inactive=include_inactive)]


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
            duty_location_id=body.duty_location_id, weekdays=body.weekdays,
            start_time=body.start_time, end_time=body.end_time,
            required_count=body.required_count, auto_roll=body.auto_roll,
            notes=body.notes, actor_id=user.id,
        )
    except svc.TemplateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(t)
    return _out(t)


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
    try:
        svc.update_template(
            session, tpl=t, name=body.name, weekdays=body.weekdays,
            start_time=body.start_time, end_time=body.end_time,
            required_count=body.required_count, auto_roll=body.auto_roll,
            active=body.active, actor_id=user.id, **extra,
        )
    except svc.TemplateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(t)
    return _out(t)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    t = _load(session, template_id)
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    svc.delete_template(session, tpl=t, actor_id=user.id)
    session.commit()


@router.post("/{template_id}/preview", response_model=list[PreviewRow])
def preview(
    template_id: uuid.UUID,
    body: GenerateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[PreviewRow]:
    t = _load(session, template_id)
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    rows = svc.preview_generation(session, tpl=t, range_start=body.range_start, range_end=body.range_end)
    return [PreviewRow(date=r["date"], exists=r["exists"]) for r in rows]


@router.post("/{template_id}/generate", response_model=GenerateResult)
def generate(
    template_id: uuid.UUID,
    body: GenerateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> GenerateResult:
    t = _load(session, template_id)
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
    created = svc.generate_shifts(
        session, tpl=t, range_start=body.range_start, range_end=body.range_end, actor_id=user.id
    )
    session.commit()
    return GenerateResult(created_count=len(created))
```

- [ ] **Step 2: Register the router in `main.py`**

In `backend/app/main.py`, add the import after `from app.routes import shifts as shift_routes` (line 21):

```python
from app.routes import shift_templates as shift_template_routes
```

And the include after `app.include_router(shift_routes.router, prefix="/api")` (line 53):

```python
    app.include_router(shift_template_routes.router, prefix="/api")
```

- [ ] **Step 3: Smoke-test app import**

Run: `cd backend && .venv/Scripts/python.exe -c "from app.main import app; print('routes', len(app.routes))"`
Expected: prints a route count, no error.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/shift_templates.py backend/app/main.py
git commit -m "feat(v2): shift template REST routes"
```

---

## Task 10: SwapRequest model

**Files:**
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Add the `SwapRequest` model**

Append after `class ShiftTemplate` in `backend/app/db/models.py`:

```python
class SwapRequest(Base):
    __tablename__ = "swap_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    # The assignment + specific day being handed off.
    duty_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_assignments.id", ondelete="CASCADE")
    )
    duty_date: Mapped[date] = mapped_column(Date)
    requesting_soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    # NULL = open board posting; set = direct request to a specific peer.
    target_soldier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    # Soldier who agreed to cover (set when an offer is accepted/claimed).
    covering_soldier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    # open → claimed (peer agreed) → pending_approval → applied | rejected | cancelled
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"), default="open")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Two-sided approval flags (NULL = not yet decided / not required).
    requester_side_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    covering_side_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    resulting_override_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_day_overrides.id", ondelete="SET NULL"), nullable=True, default=None
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 2: Verify import**

Run: `cd backend && .venv/Scripts/python.exe -c "import app.db.models; print('OK')"`
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat(v2): SwapRequest model"
```

---

## Task 11: Migration 0024 — swap_requests

**Files:**
- Create: `backend/alembic/versions/0024_swap_requests.py`

- [ ] **Step 1: Write the migration**

```python
"""swap_requests table

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "swap_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("duty_assignment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("duty_assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("duty_date", sa.Date(), nullable=False),
        sa.Column("requesting_soldier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_soldier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("covering_soldier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("requester_side_approved", sa.Boolean(), nullable=True),
        sa.Column("covering_side_approved", sa.Boolean(), nullable=True),
        sa.Column("resulting_override_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("duty_day_overrides.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_swap_requests_status", "swap_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_swap_requests_status", table_name="swap_requests")
    op.drop_table("swap_requests")
```

- [ ] **Step 2: Apply + verify reversibility**

Run: `cd backend && .venv/Scripts/alembic upgrade head && .venv/Scripts/alembic downgrade -1 && .venv/Scripts/alembic upgrade head`
Expected: ends at `0024`, no error.

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/0024_swap_requests.py
git commit -m "feat(v2): migration 0024 swap_requests"
```

---

## Task 12: SWAP_APPROVE authz action

**Files:**
- Modify: `backend/app/auth/authz.py`

- [ ] **Step 1: Add the action constant + grant to DM/commander**

In `backend/app/auth/authz.py`, add to `class Action` after `ALGORITHM_RUN = "algorithm.run"` (line 28):

```python
    SWAP_APPROVE = "swap.approve"
```

Add `Action.SWAP_APPROVE,` to `_DM_ACTIONS` (after `Action.CONSTRAINT_APPROVE,`) and to `_COMMANDER_ACTIONS` (after `Action.CONSTRAINT_APPROVE,`).

- [ ] **Step 2: Verify import**

Run: `cd backend && .venv/Scripts/python.exe -c "from app.auth.authz import Action; print(Action.SWAP_APPROVE)"`
Expected: `swap.approve`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/auth/authz.py
git commit -m "feat(v2): swap.approve authz action"
```

---

## Task 13: Swap service — create + list (failing test)

**Files:**
- Create: `backend/app/routes/tests/test_swaps.py`

- [ ] **Step 1: Write failing tests for create/list**

Create `backend/app/routes/tests/test_swaps.py`:

```python
from datetime import date

from app.db.models import DutyAssignment, DutyLocation, DutyType, Soldier
from app.services import swaps as svc


def _seed(session):
    dt = DutyType(name="שמירה-swap", score_per_day=1)
    loc = DutyLocation(name="עמדה-swap")
    a = Soldier(personal_number="swapA", full_name="A", password_hash="x", role="soldier",
                enrolled_at=date(2026, 1, 1), must_change_password=False)
    b = Soldier(personal_number="swapB", full_name="B", password_hash="x", role="soldier",
                enrolled_at=date(2026, 1, 1), must_change_password=False)
    session.add_all([dt, loc, a, b])
    session.flush()
    assignment = DutyAssignment(
        soldier_id=a.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 10), end_date=date(2026, 6, 10), status="published",
    )
    session.add(assignment)
    session.flush()
    return a, b, assignment


def test_create_open_request(session):
    a, b, assignment = _seed(session)
    req = svc.create_request(
        session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        duty_date=date(2026, 6, 10), target_soldier_id=None, reason="busy", actor_id=a.id,
    )
    assert req.status == "open"
    assert req.target_soldier_id is None


def test_create_direct_request(session):
    a, b, assignment = _seed(session)
    req = svc.create_request(
        session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        duty_date=date(2026, 6, 10), target_soldier_id=b.id, reason="cover me", actor_id=a.id,
    )
    assert req.status == "open"
    assert req.target_soldier_id == b.id


def test_cannot_request_others_duty(session):
    a, b, assignment = _seed(session)
    try:
        svc.create_request(
            session, requesting_soldier_id=b.id, duty_assignment_id=assignment.id,
            duty_date=date(2026, 6, 10), target_soldier_id=None, reason="x", actor_id=b.id,
        )
        assert False, "expected SwapError"
    except svc.SwapError as exc:
        assert str(exc) == "not_your_duty"
```

Note: confirm the `Soldier` constructor field for the forced-password-change flag by checking `app/db/models.py` `class Soldier`; if the field is named differently than `must_change_password`, use the actual name. Run: `cd backend && grep -n "change_password\|must_change" app/db/models.py`.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/routes/tests/test_swaps.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.swaps'`.

---

## Task 14: Swap service — create + list (implement)

**Files:**
- Create: `backend/app/services/swaps.py`

- [ ] **Step 1: Create the module**

```python
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyAssignment, SwapRequest


class SwapError(Exception):
    """Raised on an invalid swap operation."""


def create_request(
    session: Session,
    *,
    requesting_soldier_id: uuid.UUID,
    duty_assignment_id: uuid.UUID,
    duty_date: date,
    target_soldier_id: uuid.UUID | None,
    reason: str | None,
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    assignment = session.get(DutyAssignment, duty_assignment_id)
    if assignment is None:
        raise SwapError("assignment_not_found")
    if assignment.soldier_id != requesting_soldier_id:
        raise SwapError("not_your_duty")
    if not (assignment.start_date <= duty_date <= assignment.end_date):
        raise SwapError("date_out_of_range")
    if assignment.status != "published":
        raise SwapError("not_published")
    if target_soldier_id is not None and target_soldier_id == requesting_soldier_id:
        raise SwapError("cannot_target_self")
    req = SwapRequest(
        duty_assignment_id=duty_assignment_id,
        duty_date=duty_date,
        requesting_soldier_id=requesting_soldier_id,
        target_soldier_id=target_soldier_id,
        reason=reason,
        status="open",
    )
    session.add(req)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="swap.create",
        entity_type="swap_request",
        entity_id=req.id,
        after={
            "duty_assignment_id": str(duty_assignment_id),
            "duty_date": duty_date.isoformat(),
            "target_soldier_id": str(target_soldier_id) if target_soldier_id else None,
            "status": "open",
        },
    )
    return req


def list_open_board(session: Session, *, for_soldier_id: uuid.UUID) -> list[SwapRequest]:
    """Open postings visible to a soldier: open-to-anyone OR directed at this soldier,
    excluding their own requests."""
    return list(
        session.execute(
            select(SwapRequest)
            .where(
                SwapRequest.status == "open",
                SwapRequest.requesting_soldier_id != for_soldier_id,
                or_(
                    SwapRequest.target_soldier_id.is_(None),
                    SwapRequest.target_soldier_id == for_soldier_id,
                ),
            )
            .order_by(SwapRequest.duty_date.asc())
        )
        .scalars()
        .all()
    )


def list_own(session: Session, *, soldier_id: uuid.UUID) -> list[SwapRequest]:
    return list(
        session.execute(
            select(SwapRequest)
            .where(SwapRequest.requesting_soldier_id == soldier_id)
            .order_by(SwapRequest.created_at.desc())
        )
        .scalars()
        .all()
    )
```

- [ ] **Step 2: Run to verify pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/routes/tests/test_swaps.py -v`
Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/swaps.py backend/app/routes/tests/test_swaps.py
git commit -m "feat(v2): swap request create + list service"
```

---

## Task 15: Swap claim + apply-or-queue (failing test)

**Files:**
- Modify: `backend/app/routes/tests/test_swaps.py`

- [ ] **Step 1: Add tests for claim → auto-apply (approval off) and queue (approval on)**

Append to `backend/app/routes/tests/test_swaps.py`:

```python
from app.db.models import DutyDayOverride, SwapRequest
from app.services.settings_loader import set_setting


def test_claim_auto_applies_when_approval_off(session):
    a, b, assignment = _seed(session)
    set_setting(session, "swaps.require_manager_approval", False, actor_id=None)
    req = svc.create_request(
        session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        duty_date=date(2026, 6, 10), target_soldier_id=None, reason="x", actor_id=a.id,
    )
    session.flush()
    out = svc.claim_request(session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
    assert out.status == "applied"
    assert out.covering_soldier_id == b.id
    ov = session.get(DutyDayOverride, out.resulting_override_id)
    assert ov is not None
    assert ov.effective_soldier_id == b.id
    assert ov.reason == "replacement"


def test_claim_queues_when_approval_on(session):
    a, b, assignment = _seed(session)
    set_setting(session, "swaps.require_manager_approval", True, actor_id=None)
    req = svc.create_request(
        session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        duty_date=date(2026, 6, 10), target_soldier_id=None, reason="x", actor_id=a.id,
    )
    session.flush()
    out = svc.claim_request(session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
    assert out.status == "pending_approval"
    assert out.resulting_override_id is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/routes/tests/test_swaps.py -k claim -v`
Expected: FAIL — no attribute `claim_request`.

---

## Task 16: Swap claim + apply-or-queue (implement)

**Files:**
- Modify: `backend/app/services/swaps.py`

- [ ] **Step 1: Add `_require_approval`, `_apply_cover`, and `claim_request`**

Append to `backend/app/services/swaps.py` (add the imports at the top first):

```python
# add to the imports at the top of the file:
from app.db.models import Soldier
from app.services import assignments as assignments_svc
from app.services.settings_loader import SettingNotFound, get_setting
```

```python
def _require_approval(session: Session) -> bool:
    try:
        return bool(get_setting(session, "swaps.require_manager_approval"))
    except SettingNotFound:
        return True  # safe default: require approval


def _apply_cover(
    session: Session, *, req: SwapRequest, actor_id: uuid.UUID | None
) -> None:
    """Translate an agreed swap into a duty_day_override crediting the covering soldier.
    Relies on assignments.set_day_override for eligibility + overlap enforcement."""
    assignment = session.get(DutyAssignment, req.duty_assignment_id)
    if assignment is None:
        raise SwapError("assignment_not_found")
    try:
        ov = assignments_svc.set_day_override(
            session,
            assignment=assignment,
            date=req.duty_date,
            effective_soldier_id=req.covering_soldier_id,
            reason="replacement",
            actor_id=actor_id,
        )
    except assignments_svc.AssignmentError as exc:
        # surface eligibility/overlap failures to the caller
        raise SwapError(f"cover_blocked:{exc}") from exc
    req.resulting_override_id = ov.id
    req.status = "applied"


def claim_request(
    session: Session,
    *,
    request_id: uuid.UUID,
    covering_soldier_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "open":
        raise SwapError("not_open")
    if covering_soldier_id == req.requesting_soldier_id:
        raise SwapError("cannot_cover_own")
    if req.target_soldier_id is not None and req.target_soldier_id != covering_soldier_id:
        raise SwapError("not_targeted_at_you")
    if session.get(Soldier, covering_soldier_id) is None:
        raise SwapError("soldier_not_found")
    req.covering_soldier_id = covering_soldier_id
    before_status = req.status
    if _require_approval(session):
        req.status = "pending_approval"
        req.requester_side_approved = None
        req.covering_side_approved = None
        write_audit(
            session, actor_id=actor_id, action="swap.claim", entity_type="swap_request",
            entity_id=req.id, before={"status": before_status},
            after={"status": "pending_approval", "covering_soldier_id": str(covering_soldier_id)},
        )
    else:
        _apply_cover(session, req=req, actor_id=actor_id)
        write_audit(
            session, actor_id=actor_id, action="swap.claim", entity_type="swap_request",
            entity_id=req.id, before={"status": before_status},
            after={"status": "applied", "covering_soldier_id": str(covering_soldier_id)},
        )
    session.flush()
    return req
```

- [ ] **Step 2: Run to verify pass**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/routes/tests/test_swaps.py -v`
Expected: all passed (5).

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/swaps.py backend/app/routes/tests/test_swaps.py
git commit -m "feat(v2): swap claim with apply-or-queue"
```

---

## Task 17: Two-sided approval + reject + cancel (test + implement)

**Files:**
- Modify: `backend/app/routes/tests/test_swaps.py`
- Modify: `backend/app/services/swaps.py`

- [ ] **Step 1: Add tests for two-sided approval and reject**

Append to `backend/app/routes/tests/test_swaps.py`:

```python
def test_two_sided_approval_applies_only_after_both(session):
    a, b, assignment = _seed(session)
    set_setting(session, "swaps.require_manager_approval", True, actor_id=None)
    req = svc.create_request(
        session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        duty_date=date(2026, 6, 10), target_soldier_id=None, reason="x", actor_id=a.id,
    )
    session.flush()
    svc.claim_request(session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
    session.flush()

    svc.approve_side(session, request_id=req.id, side="requester", actor_id=None)
    assert session.get(SwapRequest, req.id).status == "pending_approval"  # still waiting

    out = svc.approve_side(session, request_id=req.id, side="covering", actor_id=None)
    assert out.status == "applied"
    assert out.resulting_override_id is not None


def test_reject_sets_status_and_no_override(session):
    a, b, assignment = _seed(session)
    set_setting(session, "swaps.require_manager_approval", True, actor_id=None)
    req = svc.create_request(
        session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        duty_date=date(2026, 6, 10), target_soldier_id=None, reason="x", actor_id=a.id,
    )
    session.flush()
    svc.claim_request(session, request_id=req.id, covering_soldier_id=b.id, actor_id=b.id)
    session.flush()
    out = svc.reject_request(session, request_id=req.id, decision_note="no", actor_id=None)
    assert out.status == "rejected"
    assert out.resulting_override_id is None


def test_cancel_open_request(session):
    a, b, assignment = _seed(session)
    req = svc.create_request(
        session, requesting_soldier_id=a.id, duty_assignment_id=assignment.id,
        duty_date=date(2026, 6, 10), target_soldier_id=None, reason="x", actor_id=a.id,
    )
    session.flush()
    svc.cancel_request(session, request_id=req.id, actor_id=a.id)
    assert session.get(SwapRequest, req.id).status == "cancelled"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/routes/tests/test_swaps.py -k "approval or reject or cancel" -v`
Expected: FAIL — no attribute `approve_side`.

- [ ] **Step 3: Implement approval/reject/cancel + pending list**

Append to `backend/app/services/swaps.py`:

```python
def approve_side(
    session: Session,
    *,
    request_id: uuid.UUID,
    side: str,  # "requester" | "covering"
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status != "pending_approval":
        raise SwapError("not_pending")
    if side == "requester":
        req.requester_side_approved = True
    elif side == "covering":
        req.covering_side_approved = True
    else:
        raise SwapError("bad_side")
    write_audit(
        session, actor_id=actor_id, action="swap.approve_side", entity_type="swap_request",
        entity_id=req.id, after={"side": side},
    )
    if req.requester_side_approved and req.covering_side_approved:
        _apply_cover(session, req=req, actor_id=actor_id)
        write_audit(
            session, actor_id=actor_id, action="swap.apply", entity_type="swap_request",
            entity_id=req.id, after={"status": "applied"},
        )
    session.flush()
    return req


def reject_request(
    session: Session,
    *,
    request_id: uuid.UUID,
    decision_note: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status not in ("open", "pending_approval"):
        raise SwapError("not_rejectable")
    before = {"status": req.status}
    req.status = "rejected"
    req.decision_note = decision_note
    write_audit(
        session, actor_id=actor_id, action="swap.reject", entity_type="swap_request",
        entity_id=req.id, before=before, after={"status": "rejected", "decision_note": decision_note},
    )
    session.flush()
    return req


def cancel_request(
    session: Session,
    *,
    request_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> SwapRequest:
    req = session.get(SwapRequest, request_id)
    if req is None:
        raise SwapError("request_not_found")
    if req.status not in ("open", "pending_approval"):
        raise SwapError("not_cancellable")
    before = {"status": req.status}
    req.status = "cancelled"
    write_audit(
        session, actor_id=actor_id, action="swap.cancel", entity_type="swap_request",
        entity_id=req.id, before=before, after={"status": "cancelled"},
    )
    session.flush()
    return req


def list_pending_approval(session: Session) -> list[SwapRequest]:
    return list(
        session.execute(
            select(SwapRequest)
            .where(SwapRequest.status == "pending_approval")
            .order_by(SwapRequest.duty_date.asc())
        )
        .scalars()
        .all()
    )
```

- [ ] **Step 4: Run full swap suite**

Run: `cd backend && .venv/Scripts/python.exe -m pytest app/routes/tests/test_swaps.py -v`
Expected: all passed (8).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/swaps.py backend/app/routes/tests/test_swaps.py
git commit -m "feat(v2): two-sided swap approval, reject, cancel"
```

---

## Task 18: Swap routes

**Files:**
- Create: `backend/app/routes/swaps.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create the router**

```python
from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize, scope_root_ids
from app.auth.deps import require_password_changed
from app.db.models import SwapRequest, Soldier
from app.db.session import get_session
from app.services import swaps as svc

router = APIRouter(tags=["swaps"])


class SwapOut(BaseModel):
    id: uuid.UUID
    duty_assignment_id: uuid.UUID
    duty_date: date
    requesting_soldier_id: uuid.UUID
    target_soldier_id: uuid.UUID | None
    covering_soldier_id: uuid.UUID | None
    status: str
    reason: str | None
    requester_side_approved: bool | None
    covering_side_approved: bool | None
    decision_note: str | None
    created_at: datetime


class CreateSwapRequest(BaseModel):
    duty_assignment_id: uuid.UUID
    duty_date: date
    target_soldier_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=1000)


class ClaimRequest(BaseModel):
    pass


class ApproveSideRequest(BaseModel):
    side: str  # "requester" | "covering"


class RejectRequest(BaseModel):
    decision_note: str | None = Field(default=None, max_length=1000)


def _out(r: SwapRequest) -> SwapOut:
    return SwapOut(
        id=r.id, duty_assignment_id=r.duty_assignment_id, duty_date=r.duty_date,
        requesting_soldier_id=r.requesting_soldier_id, target_soldier_id=r.target_soldier_id,
        covering_soldier_id=r.covering_soldier_id, status=r.status, reason=r.reason,
        requester_side_approved=r.requester_side_approved,
        covering_side_approved=r.covering_side_approved,
        decision_note=r.decision_note, created_at=r.created_at,
    )


def _err(exc: svc.SwapError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/me/swaps", response_model=list[SwapOut])
def my_swaps(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SwapOut]:
    return [_out(r) for r in svc.list_own(session, soldier_id=user.id)]


@router.get("/swaps/board", response_model=list[SwapOut])
def board(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SwapOut]:
    return [_out(r) for r in svc.list_open_board(session, for_soldier_id=user.id)]


@router.post("/me/swaps", response_model=SwapOut, status_code=status.HTTP_201_CREATED)
def create(
    body: CreateSwapRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    try:
        r = svc.create_request(
            session, requesting_soldier_id=user.id, duty_assignment_id=body.duty_assignment_id,
            duty_date=body.duty_date, target_soldier_id=body.target_soldier_id,
            reason=body.reason, actor_id=user.id,
        )
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r)


@router.post("/swaps/{request_id}/claim", response_model=SwapOut)
def claim(
    request_id: uuid.UUID,
    _body: ClaimRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    try:
        r = svc.claim_request(session, request_id=request_id, covering_soldier_id=user.id, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r)


@router.delete("/me/swaps/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel(
    request_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    r = session.get(SwapRequest, request_id)
    if r is None or r.requesting_soldier_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    try:
        svc.cancel_request(session, request_id=request_id, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()


@router.get("/swaps/pending", response_model=list[SwapOut])
def pending(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[SwapOut]:
    roots = scope_root_ids(session, user)
    if user.role != "admin" and not roots:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return [_out(r) for r in svc.list_pending_approval(session)]


@router.post("/swaps/{request_id}/approve", response_model=SwapOut)
def approve(
    request_id: uuid.UUID,
    body: ApproveSideRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    authorize(session, user, Action.SWAP_APPROVE, target_node=None)
    try:
        r = svc.approve_side(session, request_id=request_id, side=body.side, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r)


@router.post("/swaps/{request_id}/reject", response_model=SwapOut)
def reject(
    request_id: uuid.UUID,
    body: RejectRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> SwapOut:
    authorize(session, user, Action.SWAP_APPROVE, target_node=None)
    try:
        r = svc.reject_request(session, request_id=request_id, decision_note=body.decision_note, actor_id=user.id)
    except svc.SwapError as exc:
        raise _err(exc) from exc
    session.commit()
    session.refresh(r)
    return _out(r)
```

> **Note on approval authz:** for the pilot, `SWAP_APPROVE` is treated as a DM-global action (`target_node=None`), matching how `ASSIGNMENT_MANAGE` is handled. The two-sided model is captured in data (`requester_side_approved` / `covering_side_approved`) and surfaced in the UI; tightening each side's approval to that soldier's own subtree is a follow-up once multi-DM scoping is needed (recorded in spec open questions).

- [ ] **Step 2: Register router in `main.py`**

In `backend/app/main.py`, add import after the shift-templates import from Task 9:

```python
from app.routes import swaps as swap_routes
```

And include after the shift-templates include:

```python
    app.include_router(swap_routes.router, prefix="/api")
```

- [ ] **Step 3: Smoke-test + full backend suite**

Run: `cd backend && .venv/Scripts/python.exe -c "from app.main import app; print('OK')" && .venv/Scripts/python.exe -m pytest -q`
Expected: `OK`, then the full suite passes (no regressions).

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/swaps.py backend/app/main.py
git commit -m "feat(v2): swap REST routes"
```

---

## Task 19: Frontend — API clients

**Files:**
- Create: `frontend/src/api/shiftTemplates.ts`
- Create: `frontend/src/api/swaps.ts`

- [ ] **Step 1: Create `shiftTemplates.ts`**

```typescript
import { api } from "./client";

export interface ShiftTemplate {
  id: string;
  name: string;
  duty_type_id: string;
  duty_location_id: string;
  weekdays: number[];
  start_time: string;
  end_time: string;
  required_count: number;
  active: boolean;
  auto_roll: boolean;
  notes: string | null;
}

export interface CreateTemplateInput {
  name: string;
  duty_type_id: string;
  duty_location_id: string;
  weekdays: number[];
  start_time?: string;
  end_time?: string;
  required_count?: number;
  auto_roll?: boolean;
  notes?: string | null;
}

export type UpdateTemplateInput = Partial<
  Omit<CreateTemplateInput, "duty_type_id" | "duty_location_id"> & { active: boolean }
>;

export interface PreviewRow {
  date: string;
  exists: boolean;
}

export async function listTemplates(includeInactive = false): Promise<ShiftTemplate[]> {
  return (await api.get<ShiftTemplate[]>("/shift-templates", { params: { include_inactive: includeInactive } })).data;
}

export async function createTemplate(input: CreateTemplateInput): Promise<ShiftTemplate> {
  return (await api.post<ShiftTemplate>("/shift-templates", input)).data;
}

export async function updateTemplate(id: string, input: UpdateTemplateInput): Promise<ShiftTemplate> {
  return (await api.patch<ShiftTemplate>(`/shift-templates/${id}`, input)).data;
}

export async function deleteTemplate(id: string): Promise<void> {
  await api.delete(`/shift-templates/${id}`);
}

export async function previewGeneration(
  id: string,
  range_start: string,
  range_end: string,
): Promise<PreviewRow[]> {
  return (await api.post<PreviewRow[]>(`/shift-templates/${id}/preview`, { range_start, range_end })).data;
}

export async function generateShifts(
  id: string,
  range_start: string,
  range_end: string,
): Promise<{ created_count: number }> {
  return (await api.post<{ created_count: number }>(`/shift-templates/${id}/generate`, { range_start, range_end })).data;
}
```

- [ ] **Step 2: Create `swaps.ts`**

```typescript
import { api } from "./client";

export interface SwapRequest {
  id: string;
  duty_assignment_id: string;
  duty_date: string;
  requesting_soldier_id: string;
  target_soldier_id: string | null;
  covering_soldier_id: string | null;
  status: "open" | "pending_approval" | "applied" | "rejected" | "cancelled";
  reason: string | null;
  requester_side_approved: boolean | null;
  covering_side_approved: boolean | null;
  decision_note: string | null;
  created_at: string;
}

export interface CreateSwapInput {
  duty_assignment_id: string;
  duty_date: string;
  target_soldier_id?: string | null;
  reason?: string | null;
}

export async function listMySwaps(): Promise<SwapRequest[]> {
  return (await api.get<SwapRequest[]>("/me/swaps")).data;
}

export async function listBoard(): Promise<SwapRequest[]> {
  return (await api.get<SwapRequest[]>("/swaps/board")).data;
}

export async function createSwap(input: CreateSwapInput): Promise<SwapRequest> {
  return (await api.post<SwapRequest>("/me/swaps", input)).data;
}

export async function claimSwap(id: string): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/swaps/${id}/claim`, {})).data;
}

export async function cancelSwap(id: string): Promise<void> {
  await api.delete(`/me/swaps/${id}`);
}

export async function listPendingSwaps(): Promise<SwapRequest[]> {
  return (await api.get<SwapRequest[]>("/swaps/pending")).data;
}

export async function approveSwapSide(id: string, side: "requester" | "covering"): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/swaps/${id}/approve`, { side })).data;
}

export async function rejectSwap(id: string, decision_note?: string): Promise<SwapRequest> {
  return (await api.post<SwapRequest>(`/swaps/${id}/reject`, { decision_note })).data;
}
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && pnpm exec tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/shiftTemplates.ts frontend/src/api/swaps.ts
git commit -m "feat(v2): frontend api clients for templates + swaps"
```

---

## Task 20: Frontend pages, nav, i18n, docs, memory

This task wires the UI surfaces and finishes the slice. Follow the existing page conventions in `frontend/src/pages/ShiftsPage.tsx` (TanStack Query: `useQuery`/`useMutation` + `queryClient.invalidateQueries`) and `frontend/src/pages/ApprovalsPage.tsx` (tabbed approvals).

- [ ] **Step 1: Create `frontend/src/pages/ShiftTemplatesPage.tsx`**

A DM page listing templates (table: name, duty type, weekday chips, required_count, auto_roll badge), with buttons to open `ShiftTemplateFormModal` (create/edit), delete (with confirm), and "צור משמרות" (open `GenerateShiftsModal`). Use `useQuery(["shiftTemplates"], () => listTemplates())`, mutations call `createTemplate`/`updateTemplate`/`deleteTemplate` and `invalidateQueries(["shiftTemplates"])`. Render weekday numbers via the i18n keys from Step 6. Mirror the loading/error/empty-state markup used in `ShiftsPage.tsx`.

- [ ] **Step 2: Create `frontend/src/components/ShiftTemplateFormModal.tsx`**

A modal form with: name (text), duty type (select from `listDutyTypes` in `api/dutyConfig.ts`), location (select from `listDutyLocations`), weekday multi-toggle (7 buttons, ISO 1–7), start_time/end_time (time inputs), required_count (number ≥1), auto_roll (checkbox), notes (textarea). On submit call the `onSubmit` prop with `CreateTemplateInput`/`UpdateTemplateInput`. Match the prop/close pattern of `frontend/src/components/ShiftFormModal.tsx`.

- [ ] **Step 3: Create `frontend/src/components/GenerateShiftsModal.tsx`**

Given a `templateId`, two date inputs (range_start, range_end) defaulting to today … today+30d. A "תצוגה מקדימה" button calls `previewGeneration` and renders the returned rows, marking each date as חדש (new) or קיים (exists). A "צור" button calls `generateShifts` then shows `created_count` and calls `onGenerated()` (which invalidates `["shifts"]` and `["shiftTemplates"]`). Disable "צור" when preview shows zero new dates.

- [ ] **Step 4: Create `frontend/src/pages/SwapsPage.tsx`**

Two sections: **"הבקשות שלי"** (`listMySwaps`) with a create button (modal: pick one of the soldier's own upcoming published duty-days via `listAssignments({soldier_id: me})` expanded per day, optional target soldier via `SoldierSearchAutocomplete`, reason) and a cancel button for `open`/`pending_approval` rows; and **"לוח מחליפים"** (`listBoard`) listing claimable postings with a "אני מכסה" button calling `claimSwap`. Status rendered with the app palette (green=applied, amber=pending_approval/open, red=rejected, grey=cancelled). Use `useMutation` + `invalidateQueries(["mySwaps"])` / `(["swapBoard"])`.

- [ ] **Step 5: Add a swaps approval tab to `frontend/src/pages/ApprovalsPage.tsx`**

Add a tab "החלפות" alongside the existing constraints/field-update tabs. Load `listPendingSwaps`; each row shows requester, covering soldier, duty date, and two approve buttons ("אשר צד מבקש" → `approveSwapSide(id,"requester")`, "אשר צד מכסה" → `approveSwapSide(id,"covering")`) plus reject. Show per-side approved state from `requester_side_approved`/`covering_side_approved`. Invalidate `["pendingSwaps"]` after each action. Follow the existing tab/badge-count structure already in this file.

- [ ] **Step 6: Routes, nav, and i18n**

In `frontend/src/App.tsx`, add routes `/shift-templates` → `ShiftTemplatesPage` (DM-gated like the shifts route) and `/swaps` → `SwapsPage` (all authenticated users). In `frontend/src/components/Layout.tsx`, add nav entries: "תבניות משמרת" (DM section, near ניהול תורנויות) and "החלפות" (soldier section). In `frontend/src/i18n/index.ts`, add Hebrew keys used above, including weekday short labels:

```
swaps.title = "החלפות"
swaps.board = "לוח מחליפים"
swaps.mine = "הבקשות שלי"
swaps.cover = "אני מכסה"
swaps.status.open = "פתוח"
swaps.status.pending_approval = "ממתין לאישור"
swaps.status.applied = "בוצע"
swaps.status.rejected = "נדחה"
swaps.status.cancelled = "בוטל"
shiftTemplates.title = "תבניות משמרת"
shiftTemplates.generate = "צור משמרות"
shiftTemplates.autoRoll = "יצירה אוטומטית"
shiftTemplates.preview = "תצוגה מקדימה"
weekday.1 = "ב׳"
weekday.2 = "ג׳"
weekday.3 = "ד׳"
weekday.4 = "ה׳"
weekday.5 = "ו׳"
weekday.6 = "ש׳"
weekday.7 = "א׳"
```

- [ ] **Step 7: Type-check, build, and frontend tests**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm build && pnpm test`
Expected: tsc clean, build succeeds, existing tests pass.

- [ ] **Step 8: Update docs + memory**

- In `backend/app/scripts/seed.py`, optionally add one demo `ShiftTemplate` (active, auto_roll=False) and set `swaps.require_manager_approval` so the dev DB exercises both features. (Match the existing seed style; if seed is large, add minimally.)
- Update the project memory `project_callofduty2.md`: record v2 (shift templates + swaps), migrations now at **0024**, and the new tables/routes.

- [ ] **Step 9: Commit**

```bash
git add frontend/src docs backend/app/scripts/seed.py
git commit -m "feat(v2): shift templates + swaps UI, nav, i18n, seed"
```

---

## Self-review notes (addressed)

- **Spec coverage:** weekly recurrence (T3–4), org-wide DM library (T5, routes gate on `ASSIGNMENT_MANAGE`), hybrid auto-roll + preview/edit/cancel (T7–8 generation/idempotency + `dm_locked` column for protecting DM edits; T20 preview UI), generated shifts start empty and feed the existing algorithm (no assignment created at generation), direct + open-board cover (T13–14), one-way cover primary via `set_day_override` (T16), configurable approval with two sides (T15–17), eligibility respected (delegated to `set_day_override`'s existing checks). Two-way trade is supported by the schema but intentionally has no UI (deferred).
- **`dm_locked` usage:** the column is added now so the auto-roll job can later skip DM-cancelled/edited generated shifts; wiring the roll job to honor it (and a periodic trigger) is part of operationalizing auto-roll. For this plan, generation is idempotent by `(template, date)` which already prevents duplicates; a follow-up can make `roll_horizon` skip `dm_locked` shifts and add a scheduler. Flagged as the one deliberate partial.
- **Placeholder scan:** none — every code step has full code; UI steps (T20) describe concrete components but reference real existing files to mirror.
- **Type consistency:** service signatures (`create_request`, `claim_request`, `approve_side`, `generate_shifts`, `expand_dates`, `roll_horizon`) match across tests, services, and routes; `SwapOut`/`TemplateOut` fields match model columns.
- **Open follow-ups (recorded, not blockers):** per-side approval scoping to each soldier's own subtree; auto-roll scheduler + `dm_locked` honoring; match-quality ranking for the board.
