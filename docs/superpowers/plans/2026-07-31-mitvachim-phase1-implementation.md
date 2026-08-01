# מטווחים (Ranges) Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the data model, calendar/homepage display, manual assignment, attendance confirmation (with retroactive correction), qualification-expiry tracking, and exemptions for the new "מטווחים" (ranges) subsystem, entirely behind a `mitvachim.enabled` feature flag.

**Architecture:** Three new tables (`range_events`, `range_assignments`, `soldier_range_qualifications`) plus two new boolean columns on existing tables (`duty_types.requires_weapon`, `exemption_types.forbids_weapons`). A new `backend/app/services/ranges.py` service handles event/assignment CRUD and attendance marking, reusing the existing score-adjustment/audit/notification helpers exactly as `mark_no_show()` does today. A new `backend/app/services/range_exemption.py` computes the exemption rule. Authorization reuses the existing `Action`/`can()` scheme for regular DM actions, plus one new elevated helper (mirroring `commander_can_grant_commander_exemption`) for the attendance-correction gate. Frontend adds a settings-gated planning page, a roster/attendance UI, and hooks into the existing calendar/homepage widgets.

**Tech Stack:** Python/FastAPI, SQLAlchemy 2.0 (dataclass-style models), Alembic, pytest (testcontainers Postgres), React/TypeScript, vitest, `@tanstack/react-query`.

## Global Constraints

- Hebrew UI strings, English code (identifiers, comments, commit messages) — per CLAUDE.md.
- Backend tests: `pytest -q` (parallel via `-n 4`, baked into `addopts`); this plan's new test files must be added to `_AREA_MARKERS` in `backend/tests/conftest.py` and any new tables added to `_ALL_DATA_TABLES` so per-test truncation covers them.
- Frontend: `npm run lint` (zero warnings enforced), `npm run typecheck` must stay clean.
- No behavior is user-visible until `mitvachim.enabled` is true — every route in this plan checks the flag and 404s otherwise, mirroring the existing `forced_callup.enabled` gate.
- Follow the spec exactly: [docs/superpowers/specs/2026-07-31-mitvachim-phase1-design.md](../specs/2026-07-31-mitvachim-phase1-design.md).

---

## Task 1: Database models, enums, and migration

**Files:**
- Modify: `backend/app/db/models.py` (append new enums/classes; add two columns to existing classes)
- Create: `backend/alembic/versions/de2742d45fa3_add_ranges_tables.py`
- Test: `backend/app/db/tests/test_range_models.py` (new file — verify create + read/write for the migration to prove itself, run against the real test-container DB via existing fixtures)

**Interfaces:**
- Produces: `RangeType` (str enum: `laser`, `live`, `alal`), `RANGE_TYPE_RANK: dict[str, int]` (`{"laser": 1, "live": 2, "alal": 3}`), `RangeEventStatus` (str enum: `planned`, `completed`, `cancelled`), `RangeAttendanceStatus` (str enum: `pending`, `present`, `no_show`), `RangeEvent`, `RangeAssignment`, `SoldierRangeQualification` model classes, `DutyType.requires_weapon: bool`, `ExemptionType.forbids_weapons: bool` — all in `app.db.models`, importable as `from app.db.models import RangeType, RANGE_TYPE_RANK, RangeEventStatus, RangeAttendanceStatus, RangeEvent, RangeAssignment, SoldierRangeQualification`.

- [ ] **Step 1: Add the new enums and model classes to `backend/app/db/models.py`**

Append this block after the `DutyNoShow` class (or any existing class — placement doesn't matter for SQLAlchemy, keep it near other duty/exemption-adjacent models for readability):

```python
class RangeType(str, _enum.Enum):
    laser = "laser"
    live = "live"
    alal = "alal"


RANGE_TYPE_RANK: dict[str, int] = {"laser": 1, "live": 2, "alal": 3}


class RangeEventStatus(str, _enum.Enum):
    planned = "planned"
    completed = "completed"
    cancelled = "cancelled"


class RangeAttendanceStatus(str, _enum.Enum):
    pending = "pending"
    present = "present"
    no_show = "no_show"


class RangeEvent(Base):
    __tablename__ = "range_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id", ondelete="RESTRICT")
    )
    range_type: Mapped[str] = mapped_column(Enum(RangeType, name="range_type"))
    date: Mapped[date] = mapped_column(Date)
    location: Mapped[str] = mapped_column(Text)
    required_count: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    end_time: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    arrival_instructions: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    contact_name: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    contact_phone: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    reserve_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    status: Mapped[str] = mapped_column(
        Enum(RangeEventStatus, name="range_event_status"),
        server_default=text("'planned'"),
        default=RangeEventStatus.planned,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class RangeAssignment(Base):
    __tablename__ = "range_assignments"
    __table_args__ = (
        sa.UniqueConstraint("range_event_id", "soldier_id", name="uq_range_assignment_event_soldier"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    range_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("range_events.id", ondelete="CASCADE")
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    is_reserve: Mapped[bool] = mapped_column(Boolean, default=False)
    attendance_status: Mapped[str] = mapped_column(
        Enum(RangeAttendanceStatus, name="range_attendance_status"),
        server_default=text("'pending'"),
        default=RangeAttendanceStatus.pending,
    )
    marked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    score_adjustment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("score_adjustments.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class SoldierRangeQualification(Base):
    __tablename__ = "soldier_range_qualifications"
    __table_args__ = (
        sa.UniqueConstraint("soldier_id", "range_type", name="uq_soldier_range_qualification"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    range_type: Mapped[str] = mapped_column(Enum(RangeType, name="range_type"))
    valid_until: Mapped[date] = mapped_column(Date)
    source_range_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("range_assignments.id", ondelete="SET NULL"), nullable=True, default=None
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

Then add one column to the end of the existing `DutyType` class body (after `eligible_node_ids`):

```python
    requires_weapon: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
```

And one column to the end of the existing `ExemptionType` class body (after `active`):

```python
    forbids_weapons: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
```

- [ ] **Step 2: Create the Alembic migration**

Create `backend/alembic/versions/de2742d45fa3_add_ranges_tables.py`:

```python
"""add_ranges_tables

Revision ID: de2742d45fa3
Revises: d18bea0e6cbb
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'de2742d45fa3'
down_revision: Union[str, Sequence[str], None] = 'd18bea0e6cbb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    range_type_enum = postgresql.ENUM("laser", "live", "alal", name="range_type")
    range_type_enum.create(op.get_bind(), checkfirst=True)
    range_event_status_enum = postgresql.ENUM("planned", "completed", "cancelled", name="range_event_status")
    range_event_status_enum.create(op.get_bind(), checkfirst=True)
    range_attendance_status_enum = postgresql.ENUM("pending", "present", "no_show", name="range_attendance_status")
    range_attendance_status_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "duty_types",
        sa.Column("requires_weapon", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "exemption_types",
        sa.Column("forbids_weapons", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "range_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("hierarchy_node_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hierarchy_nodes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("range_type", postgresql.ENUM("laser", "live", "alal", name="range_type", create_type=False), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Text(), nullable=True),
        sa.Column("end_time", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("arrival_instructions", sa.Text(), nullable=True),
        sa.Column("contact_name", sa.Text(), nullable=True),
        sa.Column("contact_phone", sa.Text(), nullable=True),
        sa.Column("required_count", sa.Integer(), nullable=False),
        sa.Column("reserve_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "status",
            postgresql.ENUM("planned", "completed", "cancelled", name="range_event_status", create_type=False),
            nullable=False,
            server_default=sa.text("'planned'"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "range_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("range_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("range_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_reserve", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "attendance_status",
            postgresql.ENUM("pending", "present", "no_show", name="range_attendance_status", create_type=False),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("marked_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("marked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("score_adjustment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("score_adjustments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("range_event_id", "soldier_id", name="uq_range_assignment_event_soldier"),
    )

    op.create_table(
        "soldier_range_qualifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("range_type", postgresql.ENUM("laser", "live", "alal", name="range_type", create_type=False), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("source_range_assignment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("range_assignments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("soldier_id", "range_type", name="uq_soldier_range_qualification"),
    )

    op.execute(
        """
        INSERT INTO system_settings (key, value) VALUES
            ('mitvachim.enabled', 'false'),
            ('mitvachim.laser_validity_days', '180'),
            ('mitvachim.live_validity_days', '365'),
            ('mitvachim.alal_validity_days', '365'),
            ('mitvachim.attendance_edit_min_level', '"ענף"')
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM system_settings WHERE key IN ("
        "'mitvachim.enabled', 'mitvachim.laser_validity_days', 'mitvachim.live_validity_days', "
        "'mitvachim.alal_validity_days', 'mitvachim.attendance_edit_min_level')"
    )
    op.drop_table("soldier_range_qualifications")
    op.drop_table("range_assignments")
    op.drop_table("range_events")
    op.drop_column("exemption_types", "forbids_weapons")
    op.drop_column("duty_types", "requires_weapon")
    postgresql.ENUM(name="range_attendance_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="range_event_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="range_type").drop(op.get_bind(), checkfirst=True)
```

- [ ] **Step 3: Verify the migration head chain**

Run: `cd backend && .venv/Scripts/python -m alembic heads`
Expected: `de2742d45fa3 (head)` — if it prints a different id or shows multiple heads, someone else added a migration since `d18bea0e6cbb`; update `down_revision` to whatever `alembic heads` reports as the prior head before continuing.

- [ ] **Step 4: Write a model round-trip test**

Create `backend/app/db/tests/test_range_models.py`:

```python
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import (
    RangeAssignment,
    RangeAttendanceStatus,
    RangeEvent,
    RangeEventStatus,
    RangeType,
    SoldierRangeQualification,
)
from tests.helpers import create_node, create_soldier


def test_range_event_round_trip(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה א")
    event = RangeEvent(
        hierarchy_node_id=node.id,
        range_type=RangeType.laser,
        date=date(2026, 8, 15),
        location="מטווח דרום",
        required_count=5,
        reserve_count=2,
    )
    app_session.add(event)
    app_session.commit()
    app_session.refresh(event)

    assert event.status == RangeEventStatus.planned
    assert event.reserve_count == 2


def test_range_assignment_and_qualification_round_trip(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ב")
    soldier = create_soldier(app_session, personal_number="1111111", hierarchy_node_id=node.id)
    event = RangeEvent(
        hierarchy_node_id=node.id,
        range_type=RangeType.live,
        date=date(2026, 9, 1),
        location="מטווח צפון",
        required_count=3,
    )
    app_session.add(event)
    app_session.flush()

    assignment = RangeAssignment(range_event_id=event.id, soldier_id=soldier.id, is_reserve=False)
    app_session.add(assignment)
    app_session.commit()
    app_session.refresh(assignment)

    assert assignment.attendance_status == RangeAttendanceStatus.pending

    qualification = SoldierRangeQualification(
        soldier_id=soldier.id,
        range_type=RangeType.live,
        valid_until=date(2027, 9, 1),
        source_range_assignment_id=assignment.id,
    )
    app_session.add(qualification)
    app_session.commit()
    app_session.refresh(qualification)

    assert qualification.valid_until == date(2027, 9, 1)


def test_duty_type_requires_weapon_defaults_false(app_session: Session) -> None:
    from app.db.models import DutyType
    from decimal import Decimal

    dt = DutyType(name="שמירה רגילה", score_per_day=Decimal("1.00"))
    app_session.add(dt)
    app_session.commit()
    app_session.refresh(dt)
    assert dt.requires_weapon is False


def test_exemption_type_forbids_weapons_defaults_false(app_session: Session) -> None:
    from app.db.models import ExemptionType

    et = ExemptionType(name="פטור רפואי כללי")
    app_session.add(et)
    app_session.commit()
    app_session.refresh(et)
    assert et.forbids_weapons is False
```

- [ ] **Step 5: Run the test to verify it fails (table doesn't exist yet against a stale schema, or passes if `_apply_schema` already ran the new migration)**

Run: `cd backend && .venv/Scripts/python -m pytest app/db/tests/test_range_models.py -v`
Expected: since `_apply_schema` in `backend/tests/conftest.py` runs `alembic upgrade head` against a fresh test container for the whole session, this test will actually PASS once the migration file exists and models are added — there's no separate "red" state here beyond "the migration file doesn't exist yet." If you write this test before Step 1/2 are saved, it fails with `ImportError: cannot import name 'RangeEvent'`. Since Steps 1-2 are already done by this point in the task, just confirm it passes.

- [ ] **Step 6: Run and confirm pass**

Run: `cd backend && .venv/Scripts/python -m pytest app/db/tests/test_range_models.py -v`
Expected: `5 passed`

- [ ] **Step 7: Commit**

```bash
cd backend
git add app/db/models.py alembic/versions/de2742d45fa3_add_ranges_tables.py app/db/tests/test_range_models.py
git commit -m "feat: add ranges data model (RangeEvent, RangeAssignment, SoldierRangeQualification)"
```

---

## Task 2: Wire new tables into shared test fixtures

**Files:**
- Modify: `backend/tests/conftest.py` (`_ALL_DATA_TABLES`, `_AREA_MARKERS`)

**Interfaces:**
- Consumes: table names `range_events`, `range_assignments`, `soldier_range_qualifications` (from Task 1); no new production code.
- Produces: nothing new for other tasks to consume — this just makes later tests' fixtures behave correctly (per-test truncation, marker slicing).

- [ ] **Step 1: Add the three new table names to `_ALL_DATA_TABLES`**

Open `backend/tests/conftest.py`, find the `_ALL_DATA_TABLES` list (used by the autouse `_truncate_tables` fixture), and add:

```python
    "range_events",
    "range_assignments",
    "soldier_range_qualifications",
```

to the list (alongside the other table names — exact insertion point doesn't matter, list order is not semantically significant since it's used for a single `TRUNCATE ... CASCADE`-style reset).

- [ ] **Step 2: Add ranges test files to `_AREA_MARKERS`**

In the same file, find `_AREA_MARKERS: dict[str, str]` and add entries mapping the test-file stems this plan will create to the `"duty"` area (ranges is duty-adjacent and there's no dedicated marker for it yet):

```python
    "test_range_models": "duty",
    "test_range_exemption": "duty",
    "test_ranges_service": "duty",
    "test_ranges_api": "duty",
```

- [ ] **Step 3: Run the full fast suite to confirm nothing broke**

Run: `cd backend && .venv/Scripts/python -m pytest -q`
Expected: all existing tests still pass (this task only touches shared fixture config, no behavior change yet — Task 1's model test already exercises the fixtures).

- [ ] **Step 4: Commit**

```bash
cd backend
git add tests/conftest.py
git commit -m "test: wire ranges tables into shared test fixtures"
```

---

## Task 3: Range exemption rule

**Files:**
- Create: `backend/app/services/range_exemption.py`
- Test: `backend/app/services/tests/test_range_exemption.py`

**Interfaces:**
- Consumes: `SoldierExemption`, `ExemptionType`, `DutyType`, `HierarchyNode` (from `app.db.models`).
- Produces: `is_range_exempt(session: Session, *, soldier: Soldier, event_date: date) -> bool` — used by Task 5 (`add_range_assignment`).

- [ ] **Step 1: Write the failing tests**

Create `backend/app/services/tests/test_range_exemption.py`:

```python
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import DutyType, ExemptionType, SoldierExemption
from app.services.range_exemption import is_range_exempt
from tests.helpers import create_node, create_soldier


def _grant_exemption(session: Session, soldier_id, *, is_global=False, forbids_weapons=False,
                      start_date=None, end_date=None) -> SoldierExemption:
    et = ExemptionType(name=f"type-{soldier_id}-{is_global}-{forbids_weapons}",
                        is_global=is_global, forbids_weapons=forbids_weapons)
    session.add(et)
    session.flush()
    se = SoldierExemption(
        soldier_id=soldier_id, exemption_type_id=et.id,
        start_date=start_date or date(2020, 1, 1), end_date=end_date,
    )
    session.add(se)
    session.flush()
    return se


def test_global_exemption_covering_event_date_exempts(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה א")
    soldier = create_soldier(app_session, personal_number="2000001", hierarchy_node_id=node.id)
    _grant_exemption(app_session, soldier.id, is_global=True, end_date=None)

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 10, 1)) is True


def test_time_limited_forbids_weapons_exemption_covering_event_date_exempts(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ב")
    soldier = create_soldier(app_session, personal_number="2000002", hierarchy_node_id=node.id)
    _grant_exemption(
        app_session, soldier.id, forbids_weapons=True,
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
    )

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1)) is True


def test_expired_forbids_weapons_exemption_does_not_exempt(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ג")
    soldier = create_soldier(app_session, personal_number="2000003", hierarchy_node_id=node.id)
    _grant_exemption(
        app_session, soldier.id, forbids_weapons=True,
        start_date=date(2025, 1, 1), end_date=date(2025, 12, 31),
    )

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1)) is False


def test_plain_exemption_not_global_not_forbids_weapons_does_not_exempt(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ד")
    soldier = create_soldier(app_session, personal_number="2000004", hierarchy_node_id=node.id)
    _grant_exemption(app_session, soldier.id, is_global=False, forbids_weapons=False, end_date=None)

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1)) is False


def test_structurally_ineligible_for_any_weapon_duty_type_exempts(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ה")
    other_node = create_node(app_session, level="פלוגה", name="פלוגה ו")
    soldier = create_soldier(app_session, personal_number="2000005", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name="שמירה עם נשק", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[other_node.id],
    )
    app_session.add(weapon_duty)
    app_session.flush()

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1)) is True


def test_eligible_for_a_weapon_duty_type_does_not_exempt(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ז")
    soldier = create_soldier(app_session, personal_number="2000006", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name="שמירה עם נשק 2", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    app_session.add(weapon_duty)
    app_session.flush()

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1)) is False


def test_no_weapon_duty_types_exist_at_all_exempts(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ח")
    soldier = create_soldier(app_session, personal_number="2000007", hierarchy_node_id=node.id)

    assert is_range_exempt(app_session, soldier=soldier, event_date=date(2026, 6, 1)) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest app/services/tests/test_range_exemption.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.range_exemption'`

- [ ] **Step 3: Implement `is_range_exempt`**

Create `backend/app/services/range_exemption.py`:

```python
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyType, ExemptionType, HierarchyNode, Soldier, SoldierExemption


def _has_covering_weapon_exemption(session: Session, *, soldier_id, event_date: date) -> bool:
    rows = session.execute(
        select(SoldierExemption, ExemptionType)
        .join(ExemptionType, SoldierExemption.exemption_type_id == ExemptionType.id)
        .where(
            SoldierExemption.soldier_id == soldier_id,
            SoldierExemption.revoked_at.is_(None),
            SoldierExemption.start_date <= event_date,
        )
    ).all()
    for exemption, exemption_type in rows:
        if exemption.end_date is not None and exemption.end_date < event_date:
            continue
        if exemption_type.is_global or exemption_type.forbids_weapons:
            return True
    return False


def _has_any_eligible_weapon_duty_type(session: Session, *, soldier: Soldier) -> bool:
    if soldier.hierarchy_node_id is None:
        return False
    node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if node is None:
        return False
    weapon_duty_types = session.execute(
        select(DutyType).where(DutyType.requires_weapon.is_(True), DutyType.active.is_(True))
    ).scalars().all()
    for duty_type in weapon_duty_types:
        if duty_type.eligible_node_ids and node.id in duty_type.eligible_node_ids:
            return True
    return False


def is_range_exempt(session: Session, *, soldier: Soldier, event_date: date) -> bool:
    """True iff the soldier is exempt from a range event on event_date, per either:
    (1) an active global or weapons-forbidding exemption covering that date, or
    (2) structural ineligibility for any weapon-requiring duty type."""
    if _has_covering_weapon_exemption(session, soldier_id=soldier.id, event_date=event_date):
        return True
    return not _has_any_eligible_weapon_duty_type(session, soldier=soldier)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest app/services/tests/test_range_exemption.py -v`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/services/range_exemption.py app/services/tests/test_range_exemption.py
git commit -m "feat: add range exemption rule (global/forbids_weapons exemptions + structural weapon-duty ineligibility)"
```

---

## Task 4: Authorization — RANGE_MANAGE and RANGE_ATTENDANCE_EDIT

**Files:**
- Modify: `backend/app/auth/authz.py` (add `Action.RANGE_MANAGE`, bucket into `_DM_ACTIONS`)
- Modify: `backend/app/services/authority.py` (add `range_attendance_edit_authorized`)
- Test: `backend/app/services/tests/test_range_authorization.py`

**Interfaces:**
- Consumes: `Action`, `can()`, `scope_root_ids()`, `_node_in_scope()` (existing, `app.auth.authz`); `dm_scope_covers_target()`, `get_level_rank()` (existing, `app.services.authority`); `DutyManagerScope` (existing, `app.db.models`).
- Produces: `Action.RANGE_MANAGE` (usable with the existing `can()`/`authorize()` for regular subunit-scoped checks), `range_attendance_edit_authorized(session: Session, *, user: Soldier, target_node: HierarchyNode) -> bool` in `app.services.authority` — used by Task 9's attendance route.

- [ ] **Step 1: Write the failing tests**

Create `backend/app/services/tests/test_range_authorization.py`:

```python
from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth.authz import Action, can
from app.db.models import DutyManagerScope
from app.services.authority import range_attendance_edit_authorized
from app.services.settings_loader import apply_settings
from tests.helpers import create_node, create_soldier


def test_range_manage_allowed_for_dm_in_scope(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה א")
    dm = create_soldier(app_session, personal_number="3000001", role="duty_manager", hierarchy_node_id=node.id)

    assert can(app_session, dm, Action.RANGE_MANAGE, target_node=node) is True


def test_range_manage_denied_for_dm_out_of_scope(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ב")
    other_node = create_node(app_session, level="פלוגה", name="פלוגה ג")
    dm = create_soldier(app_session, personal_number="3000002", role="duty_manager", hierarchy_node_id=node.id)

    assert can(app_session, dm, Action.RANGE_MANAGE, target_node=other_node) is False


def test_range_attendance_edit_authorized_for_dm_at_required_level(app_session: Session) -> None:
    battalion = create_node(app_session, level="גדוד", name="גדוד 1")
    company = create_node(app_session, level="ענף", name="ענף 1", parent=battalion)
    apply_settings(app_session, {}, {"mitvachim.attendance_edit_min_level": "ענף"}, actor_id=None)
    dm = create_soldier(app_session, personal_number="3000003", role="duty_manager", hierarchy_node_id=company.id)
    app_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=company.id))
    app_session.flush()

    assert range_attendance_edit_authorized(app_session, user=dm, target_node=company) is True


def test_range_attendance_edit_denied_for_dm_below_required_level(app_session: Session) -> None:
    battalion = create_node(app_session, level="גדוד", name="גדוד 2")
    company = create_node(app_session, level="ענף", name="ענף 2", parent=battalion)
    platoon = create_node(app_session, level="פלוגה", name="פלוגה 2", parent=company)
    apply_settings(app_session, {}, {"mitvachim.attendance_edit_min_level": "ענף"}, actor_id=None)
    dm = create_soldier(app_session, personal_number="3000004", role="duty_manager", hierarchy_node_id=platoon.id)
    app_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=platoon.id))
    app_session.flush()

    assert range_attendance_edit_authorized(app_session, user=dm, target_node=platoon) is False


def test_range_attendance_edit_denied_for_commander_regardless_of_level(app_session: Session) -> None:
    battalion = create_node(app_session, level="גדוד", name="גדוד 3")
    company = create_node(app_session, level="ענף", name="ענף 3", parent=battalion)
    apply_settings(app_session, {}, {"mitvachim.attendance_edit_min_level": "ענף"}, actor_id=None)
    commander = create_soldier(app_session, personal_number="3000005", role="commander", hierarchy_node_id=company.id)
    company.commander_id = commander.id
    app_session.flush()

    assert range_attendance_edit_authorized(app_session, user=commander, target_node=company) is False
```

Note: this test file assumes `apply_settings(session, existing, updates, *, actor_id)` and hierarchy levels `"גדוד"`/`"ענף"`/`"פלוגה"` are already registered as valid `HierarchyLevelType` rows by the seed data `_truncate_tables` reloads before each test (per the conftest research: seed reseeds `hierarchy_level_types` defaults). If `"ענף"` isn't one of the seeded level keys, use whatever seeded level key sits at the correct rank instead — check `backend/app/scripts/seed.py` or the `HierarchyLevelType` seed rows for the exact available level keys before running this step.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest app/services/tests/test_range_authorization.py -v`
Expected: FAIL — `Action.RANGE_MANAGE` doesn't exist / `range_attendance_edit_authorized` import error.

- [ ] **Step 3: Add `Action.RANGE_MANAGE` and bucket it**

In `backend/app/auth/authz.py`, add to the `Action` class:

```python
    RANGE_MANAGE = "range.manage"
```

Add `Action.RANGE_MANAGE` to the `_DM_ACTIONS` set (alongside `Action.ASSIGNMENT_MANAGE`, etc.) — do **not** add it to `_COMMANDER_ACTIONS` for now (Phase 1 doesn't grant commanders event/roster management; only Phase 3 gives commanders a narrowly-scoped excusal-decision action, which is out of scope here).

- [ ] **Step 4: Add `range_attendance_edit_authorized` to `backend/app/services/authority.py`**

```python
from sqlalchemy import select

from app.db.models import DutyManagerScope, HierarchyNode, Soldier
from app.services.settings_loader import SettingNotFound, get_setting

RANGE_ATTENDANCE_EDIT_MIN_LEVEL_KEY = "ענף"  # fallback default if no setting is configured


def _range_attendance_edit_min_level(session: Session) -> str:
    try:
        value = get_setting(session, "mitvachim.attendance_edit_min_level")
        if value:
            return str(value)
    except SettingNotFound:
        pass
    return RANGE_ATTENDANCE_EDIT_MIN_LEVEL_KEY


def range_attendance_edit_authorized(session: Session, *, user: Soldier, target_node: HierarchyNode) -> bool:
    """True iff `user` is a duty manager (not a commander) whose own DM-scope node
    is at `mitvachim.attendance_edit_min_level` rank or higher, and that scope
    covers target_node. Commanders never qualify, regardless of rank."""
    if user.role == "admin":
        return True
    dm_scope_rows = session.execute(
        select(DutyManagerScope).where(DutyManagerScope.duty_manager_id == user.id)
    ).scalars().all()
    dm_root_ids = {row.hierarchy_node_id for row in dm_scope_rows}
    required_level = _range_attendance_edit_min_level(session)
    return dm_scope_covers_target(
        session, scope_root_ids=dm_root_ids, target_node=target_node, required_level_key=required_level,
    )
```

(Add this below the existing `dm_scope_covers_target` function in the same file — it's already imported/defined there, so no new import is needed beyond `DutyManagerScope`, `HierarchyNode`, `Soldier`, `SettingNotFound`, `get_setting` at the top of `authority.py`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest app/services/tests/test_range_authorization.py -v`
Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/auth/authz.py app/services/authority.py app/services/tests/test_range_authorization.py
git commit -m "feat: add RANGE_MANAGE action and elevated-scope attendance-edit authorization"
```

---

## Task 5: RangeEvent CRUD service

**Files:**
- Create: `backend/app/services/ranges.py`
- Test: `backend/app/services/tests/test_ranges_service.py`

**Interfaces:**
- Consumes: `RangeEvent`, `RangeEventStatus`, `RangeType`, `HierarchyNode` (from Task 1).
- Produces: `class RangeValidationError(Exception)`, `create_range_event(session, *, hierarchy_node_id, range_type, event_date, location, required_count, reserve_count=0, start_time=None, end_time=None, arrival_instructions=None, contact_name=None, contact_phone=None, notes=None, created_by=None) -> RangeEvent`, `update_range_event(session, *, event, location=None, arrival_instructions=None, contact_name=None, contact_phone=None, required_count=None, reserve_count=None, notes=None) -> RangeEvent`, `cancel_range_event(session, *, event) -> RangeEvent` — all in `app.services.ranges`, used by Task 7's routes and Task 6/8 (roster/attendance functions added to the same module).

- [ ] **Step 1: Write the failing tests**

Create `backend/app/services/tests/test_ranges_service.py`:

```python
from __future__ import annotations

from datetime import date

import pytest

from app.db.models import RangeEventStatus, RangeType
from app.services.ranges import (
    RangeValidationError,
    cancel_range_event,
    create_range_event,
    update_range_event,
)
from tests.helpers import create_node


def test_create_range_event_success(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה א")

    event = create_range_event(
        app_session,
        hierarchy_node_id=node.id,
        range_type=RangeType.laser,
        event_date=date(2026, 8, 20),
        location="מטווח דרום",
        required_count=4,
        reserve_count=1,
    )

    assert event.id is not None
    assert event.status == RangeEventStatus.planned


def test_create_range_event_rejects_unknown_node(app_session: Session) -> None:
    import uuid

    with pytest.raises(RangeValidationError):
        create_range_event(
            app_session,
            hierarchy_node_id=uuid.uuid4(),
            range_type=RangeType.live,
            event_date=date(2026, 8, 20),
            location="מטווח",
            required_count=2,
        )


def test_create_range_event_rejects_negative_counts(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ב")

    with pytest.raises(RangeValidationError):
        create_range_event(
            app_session,
            hierarchy_node_id=node.id,
            range_type=RangeType.alal,
            event_date=date(2026, 8, 20),
            location="מטווח",
            required_count=-1,
        )


def test_update_range_event_changes_fields(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ג")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date(2026, 8, 20), location="מטווח ישן", required_count=3,
    )

    updated = update_range_event(app_session, event=event, location="מטווח חדש", required_count=5)

    assert updated.location == "מטווח חדש"
    assert updated.required_count == 5


def test_cancel_range_event_sets_status(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ד")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), location="מטווח", required_count=2,
    )

    cancelled = cancel_range_event(app_session, event=event)

    assert cancelled.status == RangeEventStatus.cancelled
```

Add `from sqlalchemy.orm import Session` to the top imports of this test file alongside the rest.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest app/services/tests/test_ranges_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.ranges'`

- [ ] **Step 3: Implement the service**

Create `backend/app/services/ranges.py`:

```python
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.db.models import HierarchyNode, RangeEvent, RangeEventStatus, RangeType


class RangeValidationError(Exception):
    pass


def create_range_event(
    session: Session,
    *,
    hierarchy_node_id: uuid.UUID,
    range_type: RangeType,
    event_date: date,
    location: str,
    required_count: int,
    reserve_count: int = 0,
    start_time: str | None = None,
    end_time: str | None = None,
    arrival_instructions: str | None = None,
    contact_name: str | None = None,
    contact_phone: str | None = None,
    notes: str | None = None,
    created_by: uuid.UUID | None = None,
) -> RangeEvent:
    if session.get(HierarchyNode, hierarchy_node_id) is None:
        raise RangeValidationError("hierarchy_node_not_found")
    if required_count < 0 or reserve_count < 0:
        raise RangeValidationError("counts_must_be_non_negative")

    event = RangeEvent(
        hierarchy_node_id=hierarchy_node_id,
        range_type=range_type,
        date=event_date,
        location=location,
        required_count=required_count,
        reserve_count=reserve_count,
        start_time=start_time,
        end_time=end_time,
        arrival_instructions=arrival_instructions,
        contact_name=contact_name,
        contact_phone=contact_phone,
        notes=notes,
        created_by=created_by,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def update_range_event(
    session: Session,
    *,
    event: RangeEvent,
    location: str | None = None,
    arrival_instructions: str | None = None,
    contact_name: str | None = None,
    contact_phone: str | None = None,
    required_count: int | None = None,
    reserve_count: int | None = None,
    notes: str | None = None,
) -> RangeEvent:
    if required_count is not None:
        if required_count < 0:
            raise RangeValidationError("counts_must_be_non_negative")
        event.required_count = required_count
    if reserve_count is not None:
        if reserve_count < 0:
            raise RangeValidationError("counts_must_be_non_negative")
        event.reserve_count = reserve_count
    if location is not None:
        event.location = location
    if arrival_instructions is not None:
        event.arrival_instructions = arrival_instructions
    if contact_name is not None:
        event.contact_name = contact_name
    if contact_phone is not None:
        event.contact_phone = contact_phone
    if notes is not None:
        event.notes = notes
    session.commit()
    session.refresh(event)
    return event


def cancel_range_event(session: Session, *, event: RangeEvent) -> RangeEvent:
    event.status = RangeEventStatus.cancelled
    session.commit()
    session.refresh(event)
    return event
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest app/services/tests/test_ranges_service.py -v`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/services/ranges.py app/services/tests/test_ranges_service.py
git commit -m "feat: add RangeEvent create/update/cancel service"
```

---

## Task 6: Roster management (add/remove RangeAssignment)

**Files:**
- Modify: `backend/app/services/ranges.py` (append functions)
- Modify: `backend/app/services/tests/test_ranges_service.py` (append tests)

**Interfaces:**
- Consumes: `is_range_exempt()` (Task 3), `RangeEvent`, `RangeAssignment`, `RangeEventStatus`, `HierarchyNode`, `Soldier` (Task 1/existing).
- Produces: `add_range_assignment(session, *, event, soldier_id, is_reserve) -> RangeAssignment`, `remove_range_assignment(session, *, assignment) -> None` in `app.services.ranges` — used by Task 7's routes.

- [ ] **Step 1: Write the failing tests**

Append to `backend/app/services/tests/test_ranges_service.py`:

```python
from app.db.models import RangeAssignment
from app.services.ranges import add_range_assignment, remove_range_assignment
from tests.helpers import create_soldier


def test_add_range_assignment_success(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ה")
    soldier = create_soldier(app_session, personal_number="4000001", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), location="מטווח", required_count=3,
    )

    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    assert assignment.range_event_id == event.id
    assert assignment.is_reserve is False


def test_add_range_assignment_rejects_soldier_outside_subunit(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ו")
    other_node = create_node(app_session, level="פלוגה", name="פלוגה ז")
    soldier = create_soldier(app_session, personal_number="4000002", hierarchy_node_id=other_node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), location="מטווח", required_count=3,
    )

    with pytest.raises(RangeValidationError):
        add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)


def test_add_range_assignment_rejects_exempt_soldier(app_session: Session) -> None:
    from app.db.models import DutyType

    node = create_node(app_session, level="פלוגה", name="פלוגה ח")
    soldier = create_soldier(app_session, personal_number="4000003", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), location="מטווח", required_count=3,
    )
    # No requires_weapon=True duty type is eligible for this node -> structurally exempt.

    with pytest.raises(RangeValidationError):
        add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)


def test_remove_range_assignment_deletes_row(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה ט")
    soldier = create_soldier(app_session, personal_number="4000004", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date(2026, 8, 20), location="מטווח", required_count=3,
    )
    from app.db.models import DutyType
    from decimal import Decimal
    weapon_duty = DutyType(name="שמירה עם נשק ט", score_per_day=Decimal("1.00"),
                            requires_weapon=True, eligible_node_ids=[node.id])
    app_session.add(weapon_duty)
    app_session.flush()
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    assignment_id = assignment.id

    remove_range_assignment(app_session, assignment=assignment)

    assert app_session.get(RangeAssignment, assignment_id) is None
```

Note: `test_add_range_assignment_success` and `test_add_range_assignment_rejects_soldier_outside_subunit` will need a `requires_weapon=True` `DutyType` eligible for `node` too, since without one the soldier is structurally exempt per Task 3's rule — add the same `DutyType` creation block used in `test_remove_range_assignment_deletes_row` to those two tests before calling `add_range_assignment`, so the "success" tests aren't accidentally blocked by the exemption rule. Adjust `test_add_range_assignment_rejects_soldier_outside_subunit` to add the weapon duty type for `other_node` (the soldier's actual node) so exemption isn't the reason it's rejected — the subtree check must be what's tested.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest app/services/tests/test_ranges_service.py -v`
Expected: FAIL — `ImportError: cannot import name 'add_range_assignment'`

- [ ] **Step 3: Implement roster management**

Append to `backend/app/services/ranges.py`:

```python
from app.db.models import RangeAssignment, Soldier
from app.services.range_exemption import is_range_exempt


def add_range_assignment(
    session: Session, *, event: RangeEvent, soldier_id: uuid.UUID, is_reserve: bool,
) -> RangeAssignment:
    soldier = session.get(Soldier, soldier_id)
    if soldier is None:
        raise RangeValidationError("soldier_not_found")
    node = session.get(HierarchyNode, soldier.hierarchy_node_id) if soldier.hierarchy_node_id else None
    event_node = session.get(HierarchyNode, event.hierarchy_node_id)
    if node is None or event_node is None or event.hierarchy_node_id not in node.path_ids:
        raise RangeValidationError("soldier_outside_event_subunit")
    if is_range_exempt(session, soldier=soldier, event_date=event.date):
        raise RangeValidationError("soldier_range_exempt")

    assignment = RangeAssignment(range_event_id=event.id, soldier_id=soldier_id, is_reserve=is_reserve)
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def remove_range_assignment(session: Session, *, assignment: RangeAssignment) -> None:
    session.delete(assignment)
    session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest app/services/tests/test_ranges_service.py -v`
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/services/ranges.py app/services/tests/test_ranges_service.py
git commit -m "feat: add range roster management (add/remove assignment) with subtree and exemption checks"
```

---

## Task 7: Attendance marking with qualification update, score penalty, and correction

**Files:**
- Modify: `backend/app/services/ranges.py` (append `mark_attendance`)
- Create: `backend/app/services/tests/test_range_attendance.py`

**Interfaces:**
- Consumes: `create_adjustment()` (`app.services.adjustments`), `write_audit()` (`app.audit.writer`), `create_notification()` (`app.services.notifications`), `get_setting()` (`app.services.settings_loader`), `RangeAssignment`, `RangeAttendanceStatus`, `RangeEventStatus`, `RANGE_TYPE_RANK`, `SoldierRangeQualification` (Task 1/3/5).
- Produces: `mark_attendance(session, *, assignment, status, marked_by, note=None) -> RangeAssignment` in `app.services.ranges` — used by Task 9's attendance route.

- [ ] **Step 1: Write the failing tests**

Create `backend/app/services/tests/test_range_attendance.py`:

```python
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyType,
    RangeAttendanceStatus,
    RangeEventStatus,
    RangeType,
    SoldierRangeQualification,
)
from app.services.ranges import (
    RangeValidationError,
    add_range_assignment,
    cancel_range_event,
    create_range_event,
    mark_attendance,
)
from app.services.settings_loader import apply_settings
from tests.helpers import create_node, create_soldier


def _setup_event_and_assignment(session: Session, *, event_date: date, range_type: RangeType = RangeType.laser):
    node = create_node(session, level="פלוגה", name=f"פלוגה-{event_date}")
    weapon_duty = DutyType(
        name=f"שמירה עם נשק {event_date}", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    session.add(weapon_duty)
    session.flush()
    soldier = create_soldier(session, personal_number=f"5{event_date.toordinal()}"[:10], hierarchy_node_id=node.id)
    event = create_range_event(
        session, hierarchy_node_id=node.id, range_type=range_type,
        event_date=event_date, location="מטווח", required_count=1,
    )
    assignment = add_range_assignment(session, event=event, soldier_id=soldier.id, is_reserve=False)
    return event, soldier, assignment


def test_mark_present_updates_qualification(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.laser_validity_days": 180}, actor_id=None)
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)

    updated = mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)

    assert updated.attendance_status == RangeAttendanceStatus.present
    qualification = app_session.execute(
        select(SoldierRangeQualification).where(
            SoldierRangeQualification.soldier_id == soldier.id,
            SoldierRangeQualification.range_type == RangeType.laser,
        )
    ).scalar_one()
    assert qualification.valid_until == past_date + timedelta(days=180)


def test_mark_no_show_requires_note(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)

    with pytest.raises(RangeValidationError):
        mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.no_show, marked_by=soldier.id)


def test_mark_no_show_creates_score_adjustment_and_audit(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)

    updated = mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=soldier.id, note="לא הגיע ללא הודעה מוקדמת",
    )

    assert updated.attendance_status == RangeAttendanceStatus.no_show
    assert updated.score_adjustment_id is not None


def test_mark_attendance_rejects_future_event(app_session: Session) -> None:
    future_date = date.today() + timedelta(days=10)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=future_date)

    with pytest.raises(RangeValidationError):
        mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)


def test_mark_attendance_rejects_cancelled_event(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)
    cancel_range_event(app_session, event=event)

    with pytest.raises(RangeValidationError):
        mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)


def test_correcting_present_to_no_show_reverses_qualification_and_applies_penalty(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)
    mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)

    corrected = mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=soldier.id, note="תיקון בדיעבד - לא היה נוכח",
    )

    assert corrected.attendance_status == RangeAttendanceStatus.no_show
    assert corrected.score_adjustment_id is not None
    remaining_qualification = app_session.execute(
        select(SoldierRangeQualification).where(
            SoldierRangeQualification.soldier_id == soldier.id,
            SoldierRangeQualification.range_type == RangeType.laser,
        )
    ).scalar_one_or_none()
    assert remaining_qualification is None


def test_correcting_no_show_to_present_reverses_penalty_and_sets_qualification(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.laser_validity_days": 180}, actor_id=None)
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)
    mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=soldier.id, note="סימון ראשוני",
    )

    corrected = mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)

    assert corrected.attendance_status == RangeAttendanceStatus.present
    assert corrected.score_adjustment_id is None
    qualification = app_session.execute(
        select(SoldierRangeQualification).where(
            SoldierRangeQualification.soldier_id == soldier.id,
            SoldierRangeQualification.range_type == RangeType.laser,
        )
    ).scalar_one()
    assert qualification.valid_until == past_date + timedelta(days=180)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest app/services/tests/test_range_attendance.py -v`
Expected: FAIL — `ImportError: cannot import name 'mark_attendance'`

- [ ] **Step 3: Implement `mark_attendance`**

Append to `backend/app/services/ranges.py`:

```python
from datetime import date as _date, timedelta

from app.db.models import RangeAttendanceStatus, RangeEventStatus, RangeType, SoldierRangeQualification
from app.services.adjustments import create_adjustment
from app.audit.writer import write_audit
from app.services.notifications import create_notification
from app.db.models import NotificationType
from app.services.settings_loader import SettingNotFound, get_setting

_VALIDITY_SETTING_KEYS: dict[str, str] = {
    RangeType.laser: "mitvachim.laser_validity_days",
    RangeType.live: "mitvachim.live_validity_days",
    RangeType.alal: "mitvachim.alal_validity_days",
}
_NO_SHOW_PENALTY = Decimal("-1")


def _validity_days(session: Session, range_type: str) -> int:
    key = _VALIDITY_SETTING_KEYS[range_type]
    try:
        value = get_setting(session, key)
    except SettingNotFound:
        return 180
    return int(value)


def _upsert_qualification(session: Session, *, soldier_id: uuid.UUID, range_type: str, valid_until: _date,
                           source_range_assignment_id: uuid.UUID) -> None:
    existing = session.execute(
        select(SoldierRangeQualification).where(
            SoldierRangeQualification.soldier_id == soldier_id,
            SoldierRangeQualification.range_type == range_type,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.valid_until = valid_until
        existing.source_range_assignment_id = source_range_assignment_id
    else:
        session.add(SoldierRangeQualification(
            soldier_id=soldier_id, range_type=range_type, valid_until=valid_until,
            source_range_assignment_id=source_range_assignment_id,
        ))


def _delete_qualification_from_this_assignment(session: Session, *, assignment: RangeAssignment) -> None:
    existing = session.execute(
        select(SoldierRangeQualification).where(
            SoldierRangeQualification.source_range_assignment_id == assignment.id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        session.delete(existing)


def mark_attendance(
    session: Session, *, assignment: RangeAssignment, status: RangeAttendanceStatus,
    marked_by: uuid.UUID, note: str | None = None,
) -> RangeAssignment:
    event = session.get(RangeEvent, assignment.range_event_id)
    if event is None:
        raise RangeValidationError("event_not_found")
    if event.status == RangeEventStatus.cancelled:
        raise RangeValidationError("event_cancelled")
    if event.date > _date.today():
        raise RangeValidationError("event_not_yet_occurred")
    if status == RangeAttendanceStatus.no_show and not note:
        raise RangeValidationError("note_required_for_no_show")

    previous_status = assignment.attendance_status

    # Reverse the previous side effect, if any.
    if previous_status == RangeAttendanceStatus.no_show and assignment.score_adjustment_id is not None:
        write_audit(
            session, actor_id=marked_by, action="range_attendance_correction_reverse_no_show",
            entity_type="range_assignment", entity_id=assignment.id,
            before={"attendance_status": previous_status}, after=None,
        )
        assignment.score_adjustment_id = None
    if previous_status == RangeAttendanceStatus.present:
        _delete_qualification_from_this_assignment(session, assignment=assignment)

    # Apply the new side effect.
    if status == RangeAttendanceStatus.present:
        valid_until = event.date + timedelta(days=_validity_days(session, event.range_type))
        _upsert_qualification(
            session, soldier_id=assignment.soldier_id, range_type=event.range_type,
            valid_until=valid_until, source_range_assignment_id=assignment.id,
        )
    elif status == RangeAttendanceStatus.no_show:
        adjustment = create_adjustment(
            session, soldier_id=assignment.soldier_id, delta=_NO_SHOW_PENALTY,
            reason="range_no_show", actor_id=marked_by,
        )
        assignment.score_adjustment_id = adjustment.id
        create_notification(
            session, soldier_id=assignment.soldier_id, type=NotificationType.no_show_marked,
            title="נרשם היעדרות ממטווח", body=note, reference_type="range_assignment",
            reference_id=assignment.id, actor_id=marked_by,
        )

    assignment.attendance_status = status
    assignment.marked_by = marked_by
    assignment.marked_at = datetime.now(timezone.utc)
    assignment.note = note

    write_audit(
        session, actor_id=marked_by, action="range_attendance_marked", entity_type="range_assignment",
        entity_id=assignment.id, before={"attendance_status": previous_status}, after={"attendance_status": status},
    )

    session.commit()
    session.refresh(assignment)
    return assignment
```

Add `import uuid`, `from datetime import datetime, timezone`, `from decimal import Decimal`, `from sqlalchemy import select` to the top of `backend/app/services/ranges.py` if not already present from earlier tasks (Task 5/6 already added some of these — reconcile duplicate imports into one block at the top of the file).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest app/services/tests/test_range_attendance.py -v`
Expected: `7 passed`

- [ ] **Step 5: Run the full ranges test suite together to catch cross-file regressions**

Run: `cd backend && .venv/Scripts/python -m pytest app/services/tests/test_range_exemption.py app/services/tests/test_range_authorization.py app/services/tests/test_ranges_service.py app/services/tests/test_range_attendance.py app/db/tests/test_range_models.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/services/ranges.py app/services/tests/test_range_attendance.py
git commit -m "feat: add range attendance marking with qualification update, score penalty, and correction"
```

---

## Task 8: Register `mitvachim` system settings

**Files:**
- Modify: `backend/app/routes/public_settings.py` (`_PUBLIC_KEYS`)
- Test: `backend/app/routes/tests/test_public_settings_ranges.py`

**Interfaces:**
- Consumes: `_PUBLIC_KEYS` (existing set in `public_settings.py`).
- Produces: `"mitvachim.enabled"` visible via `GET /settings/public` — consumed by Task 11's `App.tsx` gating.

- [ ] **Step 1: Write the failing test**

Create `backend/app/routes/tests/test_public_settings_ranges.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient


def test_mitvachim_enabled_appears_in_public_settings(client: TestClient) -> None:
    response = client.get("/settings/public")
    assert response.status_code == 200
    assert "mitvachim.enabled" in response.json()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest app/routes/tests/test_public_settings_ranges.py -v`
Expected: FAIL — `assert "mitvachim.enabled" in {...}` is False since the key isn't in `_PUBLIC_KEYS` yet (it does exist as a row from Task 1's migration seed, but isn't exposed).

- [ ] **Step 3: Add the key**

In `backend/app/routes/public_settings.py`, add `"mitvachim.enabled"` to the `_PUBLIC_KEYS` set literal.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest app/routes/tests/test_public_settings_ranges.py -v`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/routes/public_settings.py app/routes/tests/test_public_settings_ranges.py
git commit -m "feat: expose mitvachim.enabled via public settings"
```

---

## Task 9: RangeEvent and roster routes

**Files:**
- Create: `backend/app/routes/ranges.py`
- Modify: `backend/app/main.py` (or wherever routers are registered — locate the existing `app.include_router(...)` calls and add one for `ranges`)
- Test: `backend/app/routes/tests/test_ranges_api.py`

**Interfaces:**
- Consumes: everything from Task 5/6 (`create_range_event`, `update_range_event`, `cancel_range_event`, `add_range_assignment`, `remove_range_assignment`, `RangeValidationError`), Task 4 (`Action.RANGE_MANAGE`), existing `authorize()`/`can()`, `get_session`, `require_password_changed`, `get_setting`.
- Produces: `POST /ranges`, `PATCH /ranges/{id}`, `POST /ranges/{id}/assignments`, `DELETE /ranges/{id}/assignments/{assignment_id}`, `GET /ranges`, `GET /ranges/{id}` — consumed by Task 12/13's frontend `api/ranges.ts`.

- [ ] **Step 1: Write the failing integration tests**

Create `backend/app/routes/tests/test_ranges_api.py`:

```python
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyType
from app.services.settings_loader import apply_settings
from tests.helpers import auth_headers, create_node, create_soldier


def _enable_mitvachim(session: Session) -> None:
    apply_settings(session, {}, {"mitvachim.enabled": True}, actor_id=None)
    session.commit()


def test_ranges_routes_404_when_disabled(client: TestClient) -> None:
    response = client.post("/ranges", json={})
    assert response.status_code == 404


def test_create_range_event_success(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה א")
    dm = create_soldier(admin_session, personal_number="6000001", role="duty_manager", hierarchy_node_id=node.id)

    response = client.post(
        "/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-09-01",
            "location": "מטווח דרום",
            "required_count": 4,
            "reserve_count": 1,
        },
        headers=auth_headers(dm),
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "planned"


def test_create_range_event_forbidden_outside_dm_scope(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה ב")
    other_node = create_node(admin_session, level="פלוגה", name="פלוגה ג")
    dm = create_soldier(admin_session, personal_number="6000002", role="duty_manager", hierarchy_node_id=other_node.id)

    response = client.post(
        "/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-09-01",
            "location": "מטווח",
            "required_count": 2,
        },
        headers=auth_headers(dm),
    )

    assert response.status_code == 403


def test_add_and_remove_assignment(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה ד")
    dm = create_soldier(admin_session, personal_number="6000003", role="duty_manager", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name="שמירה עם נשק ד", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    admin_session.add(weapon_duty)
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number="6000004", hierarchy_node_id=node.id)

    create_resp = client.post(
        "/ranges",
        json={
            "hierarchy_node_id": str(node.id), "range_type": "live", "date": "2026-09-05",
            "location": "מטווח", "required_count": 3,
        },
        headers=auth_headers(dm),
    )
    event_id = create_resp.json()["id"]

    add_resp = client.post(
        f"/ranges/{event_id}/assignments",
        json={"soldier_id": str(soldier.id), "is_reserve": False},
        headers=auth_headers(dm),
    )
    assert add_resp.status_code == 201, add_resp.text
    assignment_id = add_resp.json()["id"]

    remove_resp = client.delete(f"/ranges/{event_id}/assignments/{assignment_id}", headers=auth_headers(dm))
    assert remove_resp.status_code == 204


def test_get_range_event_returns_roster(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה ה")
    dm = create_soldier(admin_session, personal_number="6000005", role="duty_manager", hierarchy_node_id=node.id)

    create_resp = client.post(
        "/ranges",
        json={
            "hierarchy_node_id": str(node.id), "range_type": "alal", "date": "2026-09-10",
            "location": "מטווח", "required_count": 2,
        },
        headers=auth_headers(dm),
    )
    event_id = create_resp.json()["id"]

    get_resp = client.get(f"/ranges/{event_id}", headers=auth_headers(dm))
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == event_id
    assert get_resp.json()["assignments"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest app/routes/tests/test_ranges_api.py -v`
Expected: FAIL — `404` for the whole router since it isn't registered/doesn't exist (connection error or 404 from FastAPI's default catch-all).

- [ ] **Step 3: Implement the routes**

Create `backend/app/routes/ranges.py`:

```python
from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import HierarchyNode, RangeAssignment, RangeEvent, RangeType, Soldier
from app.db.session import get_session
from app.services import ranges as svc
from app.services.settings_loader import SettingNotFound, get_setting

router = APIRouter(prefix="/ranges", tags=["ranges"])


def _mitvachim_enabled(session: Session) -> bool:
    try:
        return bool(get_setting(session, "mitvachim.enabled"))
    except SettingNotFound:
        return False


def _require_enabled(session: Session) -> None:
    if not _mitvachim_enabled(session):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


def _event_node(session: Session, event: RangeEvent) -> HierarchyNode | None:
    return session.get(HierarchyNode, event.hierarchy_node_id)


def _load_event(session: Session, event_id: uuid.UUID) -> RangeEvent:
    event = session.get(RangeEvent, event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="range_event_not_found")
    return event


class CreateRangeEventBody(BaseModel):
    hierarchy_node_id: uuid.UUID
    range_type: RangeType
    date: date
    location: str = Field(min_length=1)
    required_count: int = Field(ge=0)
    reserve_count: int = Field(default=0, ge=0)
    start_time: str | None = None
    end_time: str | None = None
    arrival_instructions: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    notes: str | None = None


class UpdateRangeEventBody(BaseModel):
    location: str | None = None
    required_count: int | None = Field(default=None, ge=0)
    reserve_count: int | None = Field(default=None, ge=0)
    arrival_instructions: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    notes: str | None = None
    cancel: bool = False


class AddAssignmentBody(BaseModel):
    soldier_id: uuid.UUID
    is_reserve: bool = False


class RangeAssignmentOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    is_reserve: bool
    attendance_status: str
    note: str | None


class RangeEventOut(BaseModel):
    id: uuid.UUID
    hierarchy_node_id: uuid.UUID
    range_type: str
    date: date
    location: str
    required_count: int
    reserve_count: int
    status: str
    assignments: list[RangeAssignmentOut] = []


def _assignment_out(a: RangeAssignment) -> RangeAssignmentOut:
    return RangeAssignmentOut(
        id=a.id, soldier_id=a.soldier_id, is_reserve=a.is_reserve,
        attendance_status=a.attendance_status, note=a.note,
    )


def _event_out(session: Session, event: RangeEvent, *, include_assignments: bool = False) -> RangeEventOut:
    assignments: list[RangeAssignmentOut] = []
    if include_assignments:
        rows = session.query(RangeAssignment).filter(RangeAssignment.range_event_id == event.id).all()
        assignments = [_assignment_out(a) for a in rows]
    return RangeEventOut(
        id=event.id, hierarchy_node_id=event.hierarchy_node_id, range_type=event.range_type,
        date=event.date, location=event.location, required_count=event.required_count,
        reserve_count=event.reserve_count, status=event.status, assignments=assignments,
    )


@router.post("", response_model=RangeEventOut, status_code=status.HTTP_201_CREATED)
def create_range_event(
    body: CreateRangeEventBody, session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeEventOut:
    _require_enabled(session)
    target_node = session.get(HierarchyNode, body.hierarchy_node_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=target_node)
    try:
        event = svc.create_range_event(
            session, hierarchy_node_id=body.hierarchy_node_id, range_type=body.range_type,
            event_date=body.date, location=body.location, required_count=body.required_count,
            reserve_count=body.reserve_count, start_time=body.start_time, end_time=body.end_time,
            arrival_instructions=body.arrival_instructions, contact_name=body.contact_name,
            contact_phone=body.contact_phone, notes=body.notes, created_by=user.id,
        )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _event_out(session, event)


@router.patch("/{event_id}", response_model=RangeEventOut)
def update_range_event(
    event_id: uuid.UUID, body: UpdateRangeEventBody, session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeEventOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    try:
        if body.cancel:
            event = svc.cancel_range_event(session, event=event)
        else:
            event = svc.update_range_event(
                session, event=event, location=body.location, required_count=body.required_count,
                reserve_count=body.reserve_count, arrival_instructions=body.arrival_instructions,
                contact_name=body.contact_name, contact_phone=body.contact_phone, notes=body.notes,
            )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _event_out(session, event)


@router.post("/{event_id}/assignments", response_model=RangeAssignmentOut, status_code=status.HTTP_201_CREATED)
def add_assignment(
    event_id: uuid.UUID, body: AddAssignmentBody, session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeAssignmentOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    try:
        assignment = svc.add_range_assignment(
            session, event=event, soldier_id=body.soldier_id, is_reserve=body.is_reserve,
        )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _assignment_out(assignment)


@router.delete("/{event_id}/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_assignment(
    event_id: uuid.UUID, assignment_id: uuid.UUID, session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    assignment = session.get(RangeAssignment, assignment_id)
    if assignment is None or assignment.range_event_id != event_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    svc.remove_range_assignment(session, assignment=assignment)


@router.get("/{event_id}", response_model=RangeEventOut)
def get_range_event(
    event_id: uuid.UUID, session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeEventOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    return _event_out(session, event, include_assignments=True)


@router.get("", response_model=list[RangeEventOut])
def list_range_events(
    session: Session = Depends(get_session), user: Soldier = Depends(require_password_changed),
) -> list[RangeEventOut]:
    _require_enabled(session)
    events = session.query(RangeEvent).order_by(RangeEvent.date).all()
    return [_event_out(session, e) for e in events]
```

Note: `list_range_events` returns all events unfiltered by scope for now — Phase 1's spec doesn't call out list-scoping explicitly beyond "scoped list, filterable by node/date range — same shape as existing duty list endpoints." Check `backend/app/routes/duty_shifts.py` (or equivalent) for the exact existing list-scoping pattern and mirror it here rather than returning everything — adjust before merging if the existing duty list endpoint filters by `scope_root_ids()`.

- [ ] **Step 4: Register the router**

Find the file where existing routers are included (search for `app.include_router(no_show` or similar in `backend/app/main.py`), and add:

```python
from app.routes import ranges as ranges_routes
...
app.include_router(ranges_routes.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest app/routes/tests/test_ranges_api.py -v`
Expected: `5 passed`

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && .venv/Scripts/python -m pytest -q`
Expected: all tests pass, no regressions.

- [ ] **Step 7: Commit**

```bash
cd backend
git add app/routes/ranges.py app/routes/tests/test_ranges_api.py app/main.py
git commit -m "feat: add range event and roster management routes"
```

---

## Task 10: Attendance route with elevated-scope authorization

**Files:**
- Modify: `backend/app/routes/ranges.py` (append attendance endpoint)
- Modify: `backend/app/routes/tests/test_ranges_api.py` (append tests)

**Interfaces:**
- Consumes: `mark_attendance()` (Task 7), `range_attendance_edit_authorized()` (Task 4).
- Produces: `PATCH /ranges/{event_id}/assignments/{assignment_id}/attendance` — consumed by Task 14's frontend attendance UI.

- [ ] **Step 1: Write the failing tests**

Append to `backend/app/routes/tests/test_ranges_api.py`:

```python
from datetime import timedelta

from app.db.models import DutyManagerScope


def test_mark_attendance_requires_elevated_dm_scope(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    apply_settings(admin_session, {}, {"mitvachim.attendance_edit_min_level": "ענף"}, actor_id=None)
    battalion = create_node(admin_session, level="גדוד", name="גדוד ט1")
    company = create_node(admin_session, level="ענף", name="ענף ט1", parent=battalion)
    platoon = create_node(admin_session, level="פלוגה", name="פלוגה ט1", parent=company)
    low_dm = create_soldier(admin_session, personal_number="6100001", role="duty_manager", hierarchy_node_id=platoon.id)
    admin_session.add(DutyManagerScope(duty_manager_id=low_dm.id, hierarchy_node_id=platoon.id))
    high_dm = create_soldier(admin_session, personal_number="6100002", role="duty_manager", hierarchy_node_id=company.id)
    admin_session.add(DutyManagerScope(duty_manager_id=high_dm.id, hierarchy_node_id=company.id))
    weapon_duty = DutyType(name="שמירה עם נשק ט1", score_per_day=Decimal("1.00"),
                            requires_weapon=True, eligible_node_ids=[platoon.id])
    admin_session.add(weapon_duty)
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number="6100003", hierarchy_node_id=platoon.id)

    past_date = date.today() - timedelta(days=1)
    create_resp = client.post(
        "/ranges",
        json={"hierarchy_node_id": str(platoon.id), "range_type": "laser", "date": past_date.isoformat(),
              "location": "מטווח", "required_count": 1},
        headers=auth_headers(high_dm),
    )
    event_id = create_resp.json()["id"]
    add_resp = client.post(
        f"/ranges/{event_id}/assignments",
        json={"soldier_id": str(soldier.id), "is_reserve": False},
        headers=auth_headers(high_dm),
    )
    assignment_id = add_resp.json()["id"]

    denied_resp = client.patch(
        f"/ranges/{event_id}/assignments/{assignment_id}/attendance",
        json={"status": "present"},
        headers=auth_headers(low_dm),
    )
    assert denied_resp.status_code == 403

    allowed_resp = client.patch(
        f"/ranges/{event_id}/assignments/{assignment_id}/attendance",
        json={"status": "present"},
        headers=auth_headers(high_dm),
    )
    assert allowed_resp.status_code == 200, allowed_resp.text
    assert allowed_resp.json()["attendance_status"] == "present"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest app/routes/tests/test_ranges_api.py -v -k attendance`
Expected: FAIL — `404 Not Found` (no such route yet).

- [ ] **Step 3: Implement the route**

Append to `backend/app/routes/ranges.py`:

```python
from app.db.models import RangeAttendanceStatus
from app.services.authority import range_attendance_edit_authorized


class MarkAttendanceBody(BaseModel):
    status: RangeAttendanceStatus
    note: str | None = Field(default=None, max_length=1000)


@router.patch("/{event_id}/assignments/{assignment_id}/attendance", response_model=RangeAssignmentOut)
def mark_attendance_route(
    event_id: uuid.UUID, assignment_id: uuid.UUID, body: MarkAttendanceBody,
    session: Session = Depends(get_session), user: Soldier = Depends(require_password_changed),
) -> RangeAssignmentOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    assignment = session.get(RangeAssignment, assignment_id)
    if assignment is None or assignment.range_event_id != event_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    node = _event_node(session, event)
    if user.role != "admin" and not range_attendance_edit_authorized(session, user=user, target_node=node):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    try:
        updated = svc.mark_attendance(
            session, assignment=assignment, status=body.status, marked_by=user.id, note=body.note,
        )
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _assignment_out(updated)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest app/routes/tests/test_ranges_api.py -v`
Expected: `6 passed`

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && .venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/routes/ranges.py app/routes/tests/test_ranges_api.py
git commit -m "feat: add range attendance-marking route with elevated-scope authorization"
```

---

## Task 11: Frontend feature flag, settings entries, and API wrapper

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`
- Create: `frontend/src/api/ranges.ts`
- Test: `frontend/src/api/ranges.test.ts`

**Interfaces:**
- Consumes: `usePublicSettings()` (existing), `api` client (existing, `./client`).
- Produces: `mitvachimEnabled: boolean` gating in `App.tsx`; `getRanges`, `getRangeEvent`, `createRangeEvent`, `updateRangeEvent`, `addRangeAssignment`, `removeRangeAssignment`, `markRangeAttendance` in `frontend/src/api/ranges.ts` — consumed by Task 12/13/14's page components.

- [ ] **Step 1: Write the failing API wrapper test**

Create `frontend/src/api/ranges.test.ts`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { api } from "./client";
import { getRanges, createRangeEvent } from "./ranges";

vi.mock("./client", () => ({
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

describe("ranges api", () => {
  it("getRanges calls GET /ranges", async () => {
    (api.get as any).mockResolvedValue({ data: [] });
    const result = await getRanges();
    expect(api.get).toHaveBeenCalledWith("/ranges");
    expect(result).toEqual([]);
  });

  it("createRangeEvent calls POST /ranges with body", async () => {
    const body = {
      hierarchy_node_id: "node-1",
      range_type: "laser" as const,
      date: "2026-09-01",
      location: "מטווח",
      required_count: 3,
      reserve_count: 1,
    };
    (api.post as any).mockResolvedValue({ data: { id: "event-1", ...body, status: "planned", assignments: [] } });
    const result = await createRangeEvent(body);
    expect(api.post).toHaveBeenCalledWith("/ranges", body);
    expect(result.id).toBe("event-1");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- ranges.test.ts`
Expected: FAIL — `Cannot find module './ranges'`

- [ ] **Step 3: Implement `frontend/src/api/ranges.ts`**

```typescript
import { api } from "./client";

export type RangeType = "laser" | "live" | "alal";
export type RangeEventStatus = "planned" | "completed" | "cancelled";
export type RangeAttendanceStatus = "pending" | "present" | "no_show";

export interface RangeAssignment {
  id: string;
  soldier_id: string;
  is_reserve: boolean;
  attendance_status: RangeAttendanceStatus;
  note: string | null;
}

export interface RangeEvent {
  id: string;
  hierarchy_node_id: string;
  range_type: RangeType;
  date: string;
  location: string;
  required_count: number;
  reserve_count: number;
  status: RangeEventStatus;
  assignments: RangeAssignment[];
}

export interface CreateRangeEventBody {
  hierarchy_node_id: string;
  range_type: RangeType;
  date: string;
  location: string;
  required_count: number;
  reserve_count?: number;
  start_time?: string | null;
  end_time?: string | null;
  arrival_instructions?: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  notes?: string | null;
}

export interface UpdateRangeEventBody {
  location?: string;
  required_count?: number;
  reserve_count?: number;
  arrival_instructions?: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  notes?: string | null;
  cancel?: boolean;
}

export function getRanges(): Promise<RangeEvent[]> {
  return api.get("/ranges").then((r) => r.data);
}

export function getRangeEvent(id: string): Promise<RangeEvent> {
  return api.get(`/ranges/${id}`).then((r) => r.data);
}

export function createRangeEvent(body: CreateRangeEventBody): Promise<RangeEvent> {
  return api.post("/ranges", body).then((r) => r.data);
}

export function updateRangeEvent(id: string, body: UpdateRangeEventBody): Promise<RangeEvent> {
  return api.patch(`/ranges/${id}`, body).then((r) => r.data);
}

export function addRangeAssignment(
  eventId: string, soldierId: string, isReserve: boolean,
): Promise<RangeAssignment> {
  return api.post(`/ranges/${eventId}/assignments`, { soldier_id: soldierId, is_reserve: isReserve }).then((r) => r.data);
}

export function removeRangeAssignment(eventId: string, assignmentId: string): Promise<void> {
  return api.delete(`/ranges/${eventId}/assignments/${assignmentId}`).then(() => undefined);
}

export function markRangeAttendance(
  eventId: string, assignmentId: string, status: RangeAttendanceStatus, note?: string,
): Promise<RangeAssignment> {
  return api.patch(`/ranges/${eventId}/assignments/${assignmentId}/attendance`, { status, note }).then((r) => r.data);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- ranges.test.ts`
Expected: `2 passed`

- [ ] **Step 5: Add the feature flag gate to `App.tsx`**

Near the existing `hakpazaEnabled` line, add:

```tsx
const mitvachimEnabled = settings?.["mitvachim.enabled"] === true;
```

And near the `hakpazaEnabled` route block, add a placeholder route wired to Task 13's planning page (create the page component in Task 13 — for now, import a not-yet-existing `RangesPage` so this compiles once Task 13 lands; if Task 13 hasn't landed yet in your working tree, stub it minimally in this task to avoid a broken build — see Step 6):

```tsx
{mitvachimEnabled && (
  <Route path="/ranges" element={<AppGate><RangesPage /></AppGate>} />
)}
```

- [ ] **Step 6: Add a minimal `RangesPage` stub so the app still compiles**

Create `frontend/src/pages/RangesPage.tsx` with a minimal placeholder (Task 13 will replace this with the real planning page):

```tsx
export default function RangesPage() {
  return <div>מטווחים</div>;
}
```

Import it in `App.tsx`: `import RangesPage from "./pages/RangesPage";`

- [ ] **Step 7: Add settings entries to `SystemSettingsPage.tsx`**

Add a new group to `SETTING_GROUPS`:

```tsx
  {
    label: "מטווחים",
    settings: [
      {
        key: "mitvachim.enabled",
        label: "הפעלת תת-מערכת מטווחים",
        description: "מפעיל/מכבה את כל תת-המערכת הניסיונית של מטווחים ואל\"ל.",
        type: "boolean" as const,
        defaultValue: false,
      },
      {
        key: "mitvachim.laser_validity_days",
        label: "תוקף מטווח לייזר (ימים)",
        type: "number" as const,
        defaultValue: 180,
      },
      {
        key: "mitvachim.live_validity_days",
        label: "תוקף מטווח חי (ימים)",
        type: "number" as const,
        defaultValue: 365,
      },
      {
        key: "mitvachim.alal_validity_days",
        label: "תוקף אלל (ימים)",
        type: "number" as const,
        defaultValue: 365,
      },
      {
        key: "mitvachim.attendance_edit_min_level",
        label: "רמת היררכיה מינימלית לעריכת נוכחות",
        description: "אחראי תורנויות ברמה זו ומעלה בלבד יכולים לערוך/לתקן רישומי נוכחות במטווח.",
        type: "text" as const,
        defaultValue: "ענף",
      },
    ],
  },
```

- [ ] **Step 8: Run typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
cd frontend
git add src/App.tsx src/pages/RangesPage.tsx src/pages/SystemSettingsPage.tsx src/api/ranges.ts src/api/ranges.test.ts
git commit -m "feat: add mitvachim feature flag, settings entries, and ranges API wrapper"
```

---

## Task 12: Planning page — create/edit event and manage roster

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx` (replace stub with real implementation)
- Test: `frontend/src/pages/RangesPage.test.tsx`

**Interfaces:**
- Consumes: `getRanges`, `getRangeEvent`, `createRangeEvent`, `updateRangeEvent`, `addRangeAssignment`, `removeRangeAssignment` (Task 11).
- Produces: the planning page UI — no new exports consumed by later tasks (Task 13/14 are separate pages/widgets).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/pages/RangesPage.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import RangesPage from "./RangesPage";
import * as rangesApi from "../api/ranges";

vi.mock("../api/ranges");

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("RangesPage", () => {
  it("renders the list of range events", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      {
        id: "event-1", hierarchy_node_id: "node-1", range_type: "laser",
        date: "2026-09-01", location: "מטווח דרום", required_count: 4,
        reserve_count: 1, status: "planned", assignments: [],
      },
    ]);

    renderWithQuery(<RangesPage />);

    await waitFor(() => expect(screen.getByText("מטווח דרום")).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- RangesPage.test.tsx`
Expected: FAIL — stub component renders `"מטווחים"` only, no event list, `getByText("מטווח דרום")` not found.

- [ ] **Step 3: Implement the planning page**

Replace `frontend/src/pages/RangesPage.tsx`:

```tsx
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getRanges,
  getRangeEvent,
  addRangeAssignment,
  removeRangeAssignment,
  RangeEvent,
} from "../api/ranges";

export default function RangesPage() {
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: events } = useQuery({ queryKey: ["ranges"], queryFn: getRanges });
  const { data: selectedEvent } = useQuery({
    queryKey: ["ranges", selectedEventId],
    queryFn: () => getRangeEvent(selectedEventId as string),
    enabled: selectedEventId !== null,
  });

  async function handleRemoveAssignment(assignmentId: string) {
    if (!selectedEventId) return;
    await removeRangeAssignment(selectedEventId, assignmentId);
    queryClient.invalidateQueries({ queryKey: ["ranges", selectedEventId] });
  }

  return (
    <div dir="rtl">
      <h1>מטווחים</h1>
      <table>
        <thead>
          <tr>
            <th>תאריך</th>
            <th>סוג</th>
            <th>מיקום</th>
            <th>סטטוס</th>
          </tr>
        </thead>
        <tbody>
          {(events ?? []).map((event: RangeEvent) => (
            <tr key={event.id} onClick={() => setSelectedEventId(event.id)}>
              <td>{event.date}</td>
              <td>{event.range_type}</td>
              <td>{event.location}</td>
              <td>{event.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {selectedEvent && (
        <div>
          <h2>{selectedEvent.location}</h2>
          <ul>
            {selectedEvent.assignments.map((a) => (
              <li key={a.id}>
                {a.soldier_id} {a.is_reserve ? "(רזרבה)" : ""}
                <button onClick={() => handleRemoveAssignment(a.id)}>הסר</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
```

Note: this is an MVP roster view (list + select + remove) matching the spec's "create/edit range events, add/remove roster" requirement at a functional level. Adding-a-soldier requires a soldier picker component — reuse whatever existing soldier-search/picker component the duty planning page (`DutyManagementPage.tsx`) already uses; wire `addRangeAssignment` into it the same way `handleRemoveAssignment` is wired above. Check `DutyManagementPage.tsx` for the exact picker component name/props before implementing this piece, since it's a reusable existing component whose exact interface isn't captured in this plan.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- RangesPage.test.tsx`
Expected: `1 passed`

- [ ] **Step 5: Run lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd frontend
git add src/pages/RangesPage.tsx src/pages/RangesPage.test.tsx
git commit -m "feat: add ranges planning page with event list and roster view"
```

---

## Task 13: Attendance confirmation UI

**Files:**
- Create: `frontend/src/components/ranges/RangeAttendancePanel.tsx`
- Test: `frontend/src/components/ranges/RangeAttendancePanel.test.tsx`

**Interfaces:**
- Consumes: `markRangeAttendance`, `RangeAssignment`, `RangeAttendanceStatus` (Task 11).
- Produces: `<RangeAttendancePanel assignments={...} onMarked={...} />` component — to be embedded into `RangesPage.tsx` for past events (wiring left to a follow-up integration step, since Task 12 already covers the base planning page and this is an additive panel).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/ranges/RangeAttendancePanel.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import RangeAttendancePanel from "./RangeAttendancePanel";
import * as rangesApi from "../../api/ranges";

vi.mock("../../api/ranges");

const assignment = {
  id: "a1", soldier_id: "s1", is_reserve: false,
  attendance_status: "pending" as const, note: null,
};

describe("RangeAttendancePanel", () => {
  it("requires a note before submitting a no-show", () => {
    render(<RangeAttendancePanel eventId="e1" assignments={[assignment]} onMarked={() => {}} />);

    fireEvent.click(screen.getByTestId("no-show-a1"));
    const submitButton = screen.getByTestId("submit-a1");
    expect(submitButton).toBeDisabled();
  });

  it("calls markRangeAttendance with present and no note required", async () => {
    vi.mocked(rangesApi.markRangeAttendance).mockResolvedValue({ ...assignment, attendance_status: "present" });
    const onMarked = vi.fn();
    render(<RangeAttendancePanel eventId="e1" assignments={[assignment]} onMarked={onMarked} />);

    fireEvent.click(screen.getByTestId("present-a1"));
    fireEvent.click(screen.getByTestId("submit-a1"));

    await waitFor(() => expect(rangesApi.markRangeAttendance).toHaveBeenCalledWith("e1", "a1", "present", undefined));
    await waitFor(() => expect(onMarked).toHaveBeenCalled());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- RangeAttendancePanel.test.tsx`
Expected: FAIL — `Cannot find module './RangeAttendancePanel'`

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/ranges/RangeAttendancePanel.tsx`:

```tsx
import { useState } from "react";
import { markRangeAttendance, RangeAssignment, RangeAttendanceStatus } from "../../api/ranges";

interface Props {
  eventId: string;
  assignments: RangeAssignment[];
  onMarked: () => void;
}

export default function RangeAttendancePanel({ eventId, assignments, onMarked }: Props) {
  const [pendingStatus, setPendingStatus] = useState<Record<string, RangeAttendanceStatus>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});

  function setStatus(assignmentId: string, status: RangeAttendanceStatus) {
    setPendingStatus((prev) => ({ ...prev, [assignmentId]: status }));
  }

  async function submit(assignmentId: string) {
    const status = pendingStatus[assignmentId];
    if (!status) return;
    await markRangeAttendance(eventId, assignmentId, status, notes[assignmentId]);
    onMarked();
  }

  return (
    <div dir="rtl">
      {assignments.map((a) => {
        const status = pendingStatus[a.id];
        const canSubmit = status === "present" || (status === "no_show" && !!notes[a.id]);
        return (
          <div key={a.id}>
            <span>{a.soldier_id}</span>
            <button data-testid={`present-${a.id}`} onClick={() => setStatus(a.id, "present")}>
              נכח
            </button>
            <button data-testid={`no-show-${a.id}`} onClick={() => setStatus(a.id, "no_show")}>
              לא נכח
            </button>
            {status === "no_show" && (
              <input
                data-testid={`note-${a.id}`}
                value={notes[a.id] ?? ""}
                onChange={(e) => setNotes((prev) => ({ ...prev, [a.id]: e.target.value }))}
                placeholder="סיבה (חובה)"
              />
            )}
            <button data-testid={`submit-${a.id}`} disabled={!canSubmit} onClick={() => submit(a.id)}>
              אשר
            </button>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- RangeAttendancePanel.test.tsx`
Expected: `2 passed`

- [ ] **Step 5: Run lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd frontend
git add src/components/ranges/RangeAttendancePanel.tsx src/components/ranges/RangeAttendancePanel.test.tsx
git commit -m "feat: add range attendance confirmation panel with mandatory no-show note"
```

---

## Task 14: Homepage and calendar widget integration

**Files:**
- Modify: `frontend/src/components/dashboard/UpcomingDutiesWidget.tsx` (or create sibling `UpcomingRangesWidget.tsx` — see Step 1 decision)
- Test: `frontend/src/components/dashboard/UpcomingRangesWidget.test.tsx`

**Interfaces:**
- Consumes: `getRanges`, `RangeEvent` (Task 11).
- Produces: `<UpcomingRangesWidget ranges={...} onOpenRange={...} />` — to be placed on the homepage alongside `UpcomingDutiesWidget` (exact homepage wiring is a small addition to `HomePage.tsx`, included in Step 4 below).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/dashboard/UpcomingRangesWidget.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import UpcomingRangesWidget from "./UpcomingRangesWidget";
import { RangeEvent } from "../../api/ranges";

describe("UpcomingRangesWidget", () => {
  it("renders only future range events, sorted by date", () => {
    const today = new Date();
    const future1 = new Date(today);
    future1.setDate(future1.getDate() + 5);
    const future2 = new Date(today);
    future2.setDate(future2.getDate() + 2);
    const past = new Date(today);
    past.setDate(past.getDate() - 1);

    const ranges: RangeEvent[] = [
      { id: "1", hierarchy_node_id: "n1", range_type: "laser", date: future1.toISOString().slice(0, 10), location: "מטווח א", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
      { id: "2", hierarchy_node_id: "n1", range_type: "live", date: future2.toISOString().slice(0, 10), location: "מטווח ב", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
      { id: "3", hierarchy_node_id: "n1", range_type: "alal", date: past.toISOString().slice(0, 10), location: "מטווח ג", required_count: 1, reserve_count: 0, status: "planned", assignments: [] },
    ];

    render(<UpcomingRangesWidget ranges={ranges} onOpenRange={() => {}} />);

    expect(screen.queryByText("מטווח ג")).not.toBeInTheDocument();
    const rows = screen.getAllByRole("row").slice(1); // skip header row
    expect(rows[0]).toHaveTextContent("מטווח ב");
    expect(rows[1]).toHaveTextContent("מטווח א");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- UpcomingRangesWidget.test.tsx`
Expected: FAIL — `Cannot find module './UpcomingRangesWidget'`

- [ ] **Step 3: Implement the widget**

Create `frontend/src/components/dashboard/UpcomingRangesWidget.tsx`:

```tsx
import { RangeEvent } from "../../api/ranges";

interface Props {
  ranges: RangeEvent[];
  onOpenRange: (range: RangeEvent) => void;
}

export default function UpcomingRangesWidget({ ranges, onOpenRange }: Props) {
  const today = new Date().toISOString().slice(0, 10);
  const upcoming = ranges
    .filter((r) => r.date > today && r.status === "planned")
    .sort((a, b) => a.date.localeCompare(b.date));

  return (
    <div dir="rtl">
      <h2>מטווחים קרובים</h2>
      <table>
        <thead>
          <tr>
            <th>תאריך</th>
            <th>סוג</th>
            <th>מיקום</th>
          </tr>
        </thead>
        <tbody>
          {upcoming.map((range) => (
            <tr key={range.id} onClick={() => onOpenRange(range)}>
              <td>{range.date}</td>
              <td>{range.range_type}</td>
              <td>{range.location}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- UpcomingRangesWidget.test.tsx`
Expected: `1 passed`

- [ ] **Step 5: Wire the widget into the homepage**

Open `frontend/src/pages/HomePage.tsx`. Find where `UpcomingDutiesWidget` is rendered and add, immediately after it, gated by the feature flag (reuse `usePublicSettings()` the same way `App.tsx` does):

```tsx
{settings?.["mitvachim.enabled"] === true && (
  <UpcomingRangesWidget ranges={ranges ?? []} onOpenRange={(range) => navigate(`/ranges?event=${range.id}`)} />
)}
```

Add a `useQuery({ queryKey: ["ranges"], queryFn: getRanges })` call near the top of `HomePage.tsx` alongside wherever duties are fetched, to populate `ranges`. Check the exact existing data-fetching pattern in `HomePage.tsx` (react-query vs a custom hook) before wiring this in, and match it exactly rather than introducing a second pattern.

- [ ] **Step 6: Run typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
cd frontend
git add src/components/dashboard/UpcomingRangesWidget.tsx src/components/dashboard/UpcomingRangesWidget.test.tsx src/pages/HomePage.tsx
git commit -m "feat: add upcoming ranges widget to homepage"
```

---

## Task 15: Scope the `GET /ranges` list endpoint

**Files:**
- Modify: `backend/app/routes/ranges.py` (`list_range_events`)
- Modify: `backend/app/routes/tests/test_ranges_api.py` (append tests)

**Interfaces:**
- Consumes: `scope_root_ids()` (existing, `app.auth.authz`), the existing `GET /calendar/shifts` pattern (`backend/app/routes/calendar.py:211-230`) as the mirrored precedent — required `node_id` query param, optional `date_from`/`date_to`.
- Produces: `GET /ranges?node_id=...&date_from=...&date_to=...` scoped the same way `GET /calendar/shifts` is — consumed by Task 12's `RangesPage` and Task 14's homepage widget (both must now pass `node_id`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/app/routes/tests/test_ranges_api.py`:

```python
def test_list_range_events_requires_node_id(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה תת1")
    dm = create_soldier(admin_session, personal_number="6200001", role="duty_manager", hierarchy_node_id=node.id)

    response = client.get("/ranges", headers=auth_headers(dm))
    assert response.status_code == 422


def test_list_range_events_filters_by_node_and_date(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה תת2")
    other_node = create_node(admin_session, level="פלוגה", name="פלוגה תת3")
    dm = create_soldier(admin_session, personal_number="6200002", role="duty_manager", hierarchy_node_id=node.id)
    client.post(
        "/ranges",
        json={"hierarchy_node_id": str(node.id), "range_type": "laser", "date": "2026-09-01",
              "location": "מטווח בתוך", "required_count": 1},
        headers=auth_headers(dm),
    )
    other_dm = create_soldier(admin_session, personal_number="6200003", role="duty_manager", hierarchy_node_id=other_node.id)
    client.post(
        "/ranges",
        json={"hierarchy_node_id": str(other_node.id), "range_type": "laser", "date": "2026-09-01",
              "location": "מטווח מחוץ", "required_count": 1},
        headers=auth_headers(other_dm),
    )

    response = client.get(f"/ranges?node_id={node.id}", headers=auth_headers(dm))
    assert response.status_code == 200
    locations = [e["location"] for e in response.json()]
    assert locations == ["מטווח בתוך"]


def test_list_range_events_filters_by_date_range(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה תת4")
    dm = create_soldier(admin_session, personal_number="6200004", role="duty_manager", hierarchy_node_id=node.id)
    client.post(
        "/ranges",
        json={"hierarchy_node_id": str(node.id), "range_type": "laser", "date": "2026-09-01",
              "location": "מטווח ספטמבר", "required_count": 1},
        headers=auth_headers(dm),
    )
    client.post(
        "/ranges",
        json={"hierarchy_node_id": str(node.id), "range_type": "laser", "date": "2026-10-01",
              "location": "מטווח אוקטובר", "required_count": 1},
        headers=auth_headers(dm),
    )

    response = client.get(
        f"/ranges?node_id={node.id}&date_from=2026-09-15&date_to=2026-10-15", headers=auth_headers(dm),
    )
    assert response.status_code == 200
    locations = [e["location"] for e in response.json()]
    assert locations == ["מטווח אוקטובר"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest app/routes/tests/test_ranges_api.py -v -k list_range_events`
Expected: FAIL — current `list_range_events` takes no query params, so the "requires node_id" test gets 200 instead of 422, and the filter tests get all events back instead of the scoped subset.

- [ ] **Step 3: Implement node/date scoping**

Replace the existing `list_range_events` in `backend/app/routes/ranges.py`:

```python
@router.get("", response_model=list[RangeEventOut])
def list_range_events(
    node_id: uuid.UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[RangeEventOut]:
    _require_enabled(session)
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    query = session.query(RangeEvent).filter(RangeEvent.hierarchy_node_id == node_id)
    if date_from is not None:
        query = query.filter(RangeEvent.date >= date_from)
    if date_to is not None:
        query = query.filter(RangeEvent.date <= date_to)
    events = query.order_by(RangeEvent.date).all()
    return [_event_out(session, e) for e in events]
```

(This mirrors `calendar_shifts`'s exact-node filtering — it does not walk the subtree, matching the precedent function's behavior of filtering by the single `node_id` passed in, since the calendar view already lets the caller pick which node to view.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest app/routes/tests/test_ranges_api.py -v`
Expected: all pass.

- [ ] **Step 5: Update the frontend API wrapper and callers to pass `node_id`**

In `frontend/src/api/ranges.ts`, change `getRanges`:

```typescript
export function getRanges(nodeId: string, dateFrom?: string, dateTo?: string): Promise<RangeEvent[]> {
  const params = new URLSearchParams({ node_id: nodeId });
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  return api.get(`/ranges?${params.toString()}`).then((r) => r.data);
}
```

Update `frontend/src/api/ranges.test.ts`'s `getRanges` test to pass a `nodeId` argument and assert the call includes `node_id=`. Update `frontend/src/pages/RangesPage.tsx` and `frontend/src/pages/HomePage.tsx` (from Task 12/14) to pass the current user's `hierarchy_node_id` (from `useAuth().user`) as `nodeId` into `getRanges`.

- [ ] **Step 6: Run the frontend test suite and typecheck**

Run: `cd frontend && npm test && npm run typecheck`
Expected: all pass, no type errors.

- [ ] **Step 7: Commit**

```bash
cd backend
git add app/routes/ranges.py app/routes/tests/test_ranges_api.py
git commit -m "feat: scope GET /ranges by node_id and optional date range"
cd ../frontend
git add src/api/ranges.ts src/api/ranges.test.ts src/pages/RangesPage.tsx src/pages/HomePage.tsx
git commit -m "feat: pass node_id/date range to scoped ranges list endpoint"
```

---

## Task 16: Soldier picker in the planning page roster

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/pages/RangesPage.test.tsx` (append test)

**Interfaces:**
- Consumes: `SoldierSearchAutocomplete` (existing, `frontend/src/components/SoldierSearchAutocomplete.tsx`, props `{ onSelect: (soldier: SoldierDTO | null) => void; onCreateNew?: (personalNumber: string, fullName: string) => void }`), `SoldierDTO` (existing, `frontend/src/api/soldiers.ts`), `addRangeAssignment` (Task 11).
- Produces: nothing new for later tasks — completes Task 12's roster UI.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/pages/RangesPage.test.tsx`:

```tsx
import { fireEvent } from "@testing-library/react";

describe("RangesPage roster add", () => {
  it("adds a soldier to the roster via the picker", async () => {
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [] },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [],
    });
    vi.mocked(rangesApi.addRangeAssignment).mockResolvedValue({
      id: "assignment-1", soldier_id: "soldier-1", is_reserve: false, attendance_status: "pending", note: null,
    });

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח דרום"));
    fireEvent.click(await screen.findByTestId("add-soldier-button"));

    expect(await screen.findByTestId("soldier-picker")).toBeInTheDocument();
  });
});
```

Add `vi.mock("../components/SoldierSearchAutocomplete", () => ({ default: (props: any) => <div data-testid="soldier-picker" /> }));` near the top of `RangesPage.test.tsx`, alongside the existing `vi.mock("../api/ranges")`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- RangesPage.test.tsx`
Expected: FAIL — no `data-testid="add-soldier-button"` exists yet.

- [ ] **Step 3: Wire the picker into `RangesPage.tsx`**

In `frontend/src/pages/RangesPage.tsx`, add the import and state, and render the picker conditionally:

```tsx
import { useState } from "react";
import SoldierSearchAutocomplete from "../components/SoldierSearchAutocomplete";
import { SoldierDTO } from "../api/soldiers";
```

Add state alongside the existing `selectedEventId` state:

```tsx
const [showPicker, setShowPicker] = useState(false);
```

Add a handler:

```tsx
async function handleAddSoldier(soldier: SoldierDTO | null) {
  if (!soldier || !selectedEventId) return;
  await addRangeAssignment(selectedEventId, soldier.id, false);
  queryClient.invalidateQueries({ queryKey: ["ranges", selectedEventId] });
  setShowPicker(false);
}
```

In the `selectedEvent` block, add the button and conditional picker right after the `<h2>`:

```tsx
<button data-testid="add-soldier-button" onClick={() => setShowPicker(true)}>
  הוסף חייל
</button>
{showPicker && <SoldierSearchAutocomplete onSelect={handleAddSoldier} />}
```

Import `addRangeAssignment` alongside the other `../api/ranges` imports already at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- RangesPage.test.tsx`
Expected: all pass.

- [ ] **Step 5: Run lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd frontend
git add src/pages/RangesPage.tsx src/pages/RangesPage.test.tsx
git commit -m "feat: wire soldier picker into the ranges roster panel"
```

---

## Task 17: Calendar widget integration

**Files:**
- Modify: `frontend/src/components/dashboard/DutyCalendarWidget.tsx`
- Modify: `frontend/src/components/dashboard/DutyCalendarWidget.test.tsx` (append test)

**Interfaces:**
- Consumes: `RangeEvent` (Task 11).
- Produces: `DutyCalendarWidget` accepts an optional `ranges` prop and an optional `onOpenRange` callback — no other task consumes this further (it's the calendar's terminal integration point).

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/dashboard/DutyCalendarWidget.test.tsx`:

```tsx
it("renders range events distinctly from duty events", () => {
  const ranges = [
    { id: "r1", hierarchy_node_id: "n1", range_type: "laser" as const, date: "2026-09-01",
      location: "מטווח דרום", required_count: 3, reserve_count: 1, status: "planned" as const, assignments: [] },
  ];

  const { container } = render(
    <DutyCalendarWidget duties={[]} typeNames={{}} onOpenDuty={() => {}} ranges={ranges} onOpenRange={() => {}} />,
  );

  expect(container.textContent).toContain("מטווח דרום");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- DutyCalendarWidget.test.tsx`
Expected: FAIL — the `ranges`/`onOpenRange` props don't exist yet, TypeScript error or the range title never renders.

- [ ] **Step 3: Add the `ranges` prop**

In `frontend/src/components/dashboard/DutyCalendarWidget.tsx`, update the `Props` interface and component signature:

```tsx
import { RangeEvent } from "../../api/ranges";

interface Props {
  duties: EffectiveDuty[];
  typeNames: Record<string, string>;
  onOpenDuty: (duty: EffectiveDuty) => void;
  ranges?: RangeEvent[];
  onOpenRange?: (range: RangeEvent) => void;
}

export default function DutyCalendarWidget({ duties, typeNames, onOpenDuty, ranges = [], onOpenRange }: Props) {
```

Add a memoized events array for ranges, mirroring `dutyEvents`:

```tsx
const rangeEvents = useMemo(() =>
  ranges.map((r) => ({
    id: `range-${r.id}`,
    title: r.location,
    start: r.date,
    allDay: true,
    backgroundColor: "#7c3aed",
    borderColor: "#7c3aed",
    extendedProps: { range: r },
  })),
[ranges]);
```

Find where `dutyEvents` and `holidayEvents` are combined into the `<FullCalendar events={...} />` prop, and add `...rangeEvents` to that combined array. Find the calendar's `eventClick` handler (which currently calls `onOpenDuty` using `extendedProps.duty`) and extend it to check for `extendedProps.range` first, calling `onOpenRange?.(range)` when present instead of `onOpenDuty`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- DutyCalendarWidget.test.tsx`
Expected: all pass.

- [ ] **Step 5: Wire `ranges`/`onOpenRange` from the calendar's parent page**

Find wherever `DutyCalendarWidget` is rendered (likely `UnitCalendarPage.tsx`), pass the same `ranges` data already fetched for Task 14's homepage widget (reuse the same `useQuery(["ranges", ...])` call, scoped to whatever node the calendar page is currently viewing), and `onOpenRange={(range) => navigate(`/ranges?event=${range.id}`)}`.

- [ ] **Step 6: Run lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
cd frontend
git add src/components/dashboard/DutyCalendarWidget.tsx src/components/dashboard/DutyCalendarWidget.test.tsx src/pages/UnitCalendarPage.tsx
git commit -m "feat: render range events on the duty calendar widget"
```

---

## Task 18: Commander read-only roster view

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/pages/RangesPage.test.tsx` (append test)

**Interfaces:**
- Consumes: `useAuth()` (existing, `frontend/src/auth/AuthContext.tsx`, returns `{ user: Me | null, ... }` where `Me.is_duty_manager: boolean`, `Me.role: "soldier" | "commander" | "duty_manager" | "admin"`).
- Produces: nothing new for later tasks — this is Phase 1's final UI gap closure.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/pages/RangesPage.test.tsx`:

```tsx
vi.mock("../auth/AuthContext", () => ({
  useAuth: vi.fn(),
}));

import { useAuth } from "../auth/AuthContext";

describe("RangesPage read-only mode for commanders", () => {
  it("hides add/remove controls for a commander (not a duty manager)", async () => {
    vi.mocked(useAuth).mockReturnValue({
      user: { id: "u1", role: "commander", is_commander: true, is_duty_manager: false } as any,
    } as any);
    vi.mocked(rangesApi.getRanges).mockResolvedValue([
      { id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
        location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned", assignments: [] },
    ]);
    vi.mocked(rangesApi.getRangeEvent).mockResolvedValue({
      id: "event-1", hierarchy_node_id: "node-1", range_type: "laser", date: "2026-09-01",
      location: "מטווח דרום", required_count: 4, reserve_count: 1, status: "planned",
      assignments: [{ id: "a1", soldier_id: "s1", is_reserve: false, attendance_status: "pending", note: null }],
    });

    renderWithQuery(<RangesPage />);
    fireEvent.click(await screen.findByText("מטווח דרום"));

    expect(screen.queryByTestId("add-soldier-button")).not.toBeInTheDocument();
    expect(screen.queryByText("הסר")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- RangesPage.test.tsx`
Expected: FAIL — controls currently render unconditionally regardless of role.

- [ ] **Step 3: Gate the edit controls by role**

In `frontend/src/pages/RangesPage.tsx`, import and use `useAuth`:

```tsx
import { useAuth } from "../auth/AuthContext";
```

Inside the component body:

```tsx
const { user } = useAuth();
const canManage = user?.role === "admin" || user?.is_duty_manager === true;
```

Wrap the "הוסף חייל" button and each roster row's "הסר" button in `{canManage && (...)}`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- RangesPage.test.tsx`
Expected: all pass.

- [ ] **Step 5: Run lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd frontend
git add src/pages/RangesPage.tsx src/pages/RangesPage.test.tsx
git commit -m "feat: restrict range roster edit controls to duty managers and admins"
```

---

## Task 19: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend fast suite**

Run: `cd backend && .venv/Scripts/python -m pytest -q`
Expected: all tests pass (no `--slow` needed for this phase, per project convention — CI skips slow tests too).

- [ ] **Step 2: Run backend duty-marker slice to confirm no cross-area breakage**

Run: `cd backend && .venv/Scripts/python -m pytest -m duty -q`
Expected: all pass, including every new ranges test file (mapped to `"duty"` in Task 2).

- [ ] **Step 3: Run frontend unit tests**

Run: `cd frontend && npm test`
Expected: all pass.

- [ ] **Step 4: Run frontend lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: zero warnings, zero type errors.

- [ ] **Step 5: Manual smoke test via the dev stack**

Run: `.\dev.ps1` from the repo root, log in as an admin, enable `mitvachim.enabled` on `/admin/settings`, create a duty manager with a `requires_weapon=true` duty type eligible for some node, create a range event for that node via `/ranges`, add a soldier to it, confirm it appears on the homepage `UpcomingRangesWidget`, back-date the event via direct DB edit or wait, mark attendance, and confirm a `SoldierRangeQualification` row appears with the right `valid_until`. This step has no fixed pass/fail assertion — it's a final human sanity check before considering Phase 1 complete.

No commit for this task — it's pure verification.

---

## Self-Review Notes

**Spec coverage check:**
- Feature flag (`mitvachim.enabled`) — Task 8, Task 11. ✓
- `RangeEvent`/`RangeAssignment`/`SoldierRangeQualification` tables — Task 1. ✓
- `DutyType.requires_weapon`, `ExemptionType.forbids_weapons` — Task 1. ✓
- Exemption rule (global/forbids_weapons + structural) — Task 3. ✓
- Validity-duration settings per range type — Task 1 (migration seed), Task 7 (`_validity_days`), Task 11 (settings UI). ✓
- `RANGE_MANAGE` scoped DM action — Task 4, Task 9. ✓
- `RANGE_ATTENDANCE_EDIT`-equivalent elevated-scope check (`range_attendance_edit_authorized`), commanders excluded — Task 4, Task 10. ✓
- Manual roster add/remove with subtree + exemption validation — Task 6, Task 9. ✓
- Attendance marking with mandatory no-show note, score penalty, audit, notification — Task 7, Task 10. ✓
- Retroactive correction (flip present ↔ no_show) reversing prior side effect — Task 7. ✓
- Calendar/homepage display — Task 14 (homepage widget implemented; calendar-widget integration into `DutyCalendarWidget.tsx`/`UnitCalendarPage.tsx` is noted as a follow-up — see gap below). Planning page — Task 12. Commander read-only view — noted as a gap below (not included in this plan; see note).
- Cancellation blocking further attendance marking — Task 7 (`event.status == cancelled` check). ✓
- Calendar widget integration — Task 17 (`DutyCalendarWidget.tsx` renders `RangeEvent`s alongside duty shifts). ✓
- Commander read-only roster view — Task 18 (edit controls gated to DM/admin; commanders get a read-only roster). ✓
- `GET /ranges` scoping — Task 15 (mirrors `GET /calendar/shifts`'s `node_id`/`date_from`/`date_to` shape). ✓
- Soldier picker wiring — Task 16 (`SoldierSearchAutocomplete` wired into the roster panel). ✓

**Placeholder scan:** no TBD/TODO markers.

**Type consistency check:** `RangeType`, `RangeEventStatus`, `RangeAttendanceStatus` (Task 1) are used identically in Task 5/6/7 (service), Task 9/10 (routes/schemas), and Task 11 (frontend types) — verified same string values (`laser`/`live`/`alal`, `planned`/`completed`/`cancelled`, `pending`/`present`/`no_show`) throughout. Function names (`create_range_event`, `update_range_event`, `cancel_range_event`, `add_range_assignment`, `remove_range_assignment`, `mark_attendance`) match between their defining task and every consuming task.
