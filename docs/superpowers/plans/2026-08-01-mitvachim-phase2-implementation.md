# מטווחים (Ranges) Phase 2: automatic assignment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a DM auto-fill a planned `RangeEvent`'s remaining primary/reserve slots by a strict three-tier priority ordering (soldiers currently on a future weapon-duty first, then unqualified soldiers, then soonest-expiring-qualification soldiers), with a draft/confirm review step before soldiers are notified.

**Architecture:** One new boolean column (`RangeAssignment.is_draft`) plus a new service module `backend/app/services/range_auto_assign.py` that computes the candidate pool, ranks it, and creates draft `RangeAssignment` rows. Confirm/reject reuse `RangeAssignment` rows — confirm flips `is_draft` and fires a notification; reject reuses Phase 1's `remove_range_assignment`. Three new routes on the existing `backend/app/routes/ranges.py` router, gated by the same `mitvachim.enabled` flag and `Action.RANGE_MANAGE` authorization already used by every other ranges route. Frontend adds an "שבץ אוטומטית" button, draft badges, and confirm/reject controls to the existing `RangesPage.tsx` roster view.

**Tech Stack:** Python/FastAPI, SQLAlchemy 2.0 (dataclass-style models), Alembic, pytest (testcontainers Postgres), React/TypeScript, vitest, `@tanstack/react-query`.

## Global Constraints

- Hebrew UI strings, English code (identifiers, comments, commit messages) — per CLAUDE.md.
- Backend tests: `pytest -q` (parallel via `-n 4`, baked into `addopts`); this plan's new test file must be added to `_AREA_MARKERS` in `backend/tests/conftest.py`; the `range_assignments` table is already in `_ALL_DATA_TABLES` (Phase 1), no change needed there.
- Frontend: `npm run lint` (zero warnings enforced), `npm run typecheck` must stay clean.
- No behavior is user-visible until `mitvachim.enabled` is true — every new route checks the flag via the existing `_require_enabled(session)` helper and 404s otherwise.
- No new `Action` is introduced — auto-assign, confirm, and confirm-all all use the existing `Action.RANGE_MANAGE` (already bucketed into `_DM_ACTIONS` in `backend/app/auth/authz.py`), same as every other mutating ranges route.
- Manual `add_range_assignment` (Phase 1 path) is unaffected — it never sets `is_draft` (column defaults `False`), so it keeps behaving exactly as it does on `dev` today (no notification on manual add, unchanged).
- Follow the spec exactly: [docs/superpowers/specs/2026-07-31-mitvachim-phase2-auto-assign-design.md](../specs/2026-07-31-mitvachim-phase2-auto-assign-design.md). One deviation from the spec's prose, noted here because it affects what to build: the spec assumes manual `add_range_assignment` "was previously invoked unconditionally" with a notification — that's not what's on `dev`; `add_range_assignment` currently sends **no** notification at all (confirmed by reading `backend/app/services/ranges.py`). This plan does not change that path. Only `confirm_draft_assignment`/`confirm_all_drafts` (new, Task 3) send a notification, which fully satisfies the spec's actual intent ("draft rows don't notify, confirming one does").

---

## Task 1: `is_draft` column, model, and output schema

**Files:**
- Modify: `backend/app/db/models.py` (`RangeAssignment` class, ~line 855-886) — add `is_draft` column.
- Modify: `backend/app/db/models.py` (`NotificationType` enum, ~line 1094-1124) — add `range_assignment_confirmed`.
- Create: `backend/alembic/versions/7a13f6c9b8e2_add_range_assignment_is_draft.py`
- Modify: `backend/app/routes/ranges.py` (`RangeAssignmentOut`, `_assignment_out`, ~line 75-99) — expose `is_draft`.
- Test: `backend/app/db/tests/test_range_models.py` (existing file from Phase 1 — append one test).

**Interfaces:**
- Consumes: nothing new.
- Produces: `RangeAssignment.is_draft: bool` (default `False`), `NotificationType.range_assignment_confirmed` — both consumed by Task 2/3's service functions and Task 4's routes.

- [ ] **Step 1: Add the column to the model**

In `backend/app/db/models.py`, inside the `RangeAssignment` class (find `class RangeAssignment(Base):`), add this field after `is_reserve`:

```python
    is_draft: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
```

- [ ] **Step 2: Add the new notification type**

In the same file, inside `class NotificationType(str, _enum.Enum):`, add this line after `no_show_marked = "no_show_marked"`:

```python
    range_assignment_confirmed = "range_assignment_confirmed"
```

- [ ] **Step 3: Find the current Alembic head and create the migration**

Run: `cd backend && .venv/Scripts/python -m alembic heads`
Expected: `619962785231 (head)` — if a different id is printed, use that as `down_revision` below instead.

Create `backend/alembic/versions/7a13f6c9b8e2_add_range_assignment_is_draft.py`:

```python
"""add_range_assignment_is_draft

Revision ID: 7a13f6c9b8e2
Revises: 619962785231
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7a13f6c9b8e2'
down_revision: Union[str, Sequence[str], None] = '619962785231'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "range_assignments",
        sa.Column("is_draft", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("range_assignments", "is_draft")
```

- [ ] **Step 4: Expose `is_draft` on the API output schema**

In `backend/app/routes/ranges.py`, modify `RangeAssignmentOut` (currently at line 75-80):

```python
class RangeAssignmentOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    is_reserve: bool
    is_draft: bool
    attendance_status: str
    note: str | None
```

And `_assignment_out` (currently at line 95-99):

```python
def _assignment_out(a: RangeAssignment) -> RangeAssignmentOut:
    return RangeAssignmentOut(
        id=a.id, soldier_id=a.soldier_id, is_reserve=a.is_reserve, is_draft=a.is_draft,
        attendance_status=a.attendance_status, note=a.note,
    )
```

- [ ] **Step 5: Write a model round-trip test**

Append to `backend/app/db/tests/test_range_models.py`:

```python
def test_range_assignment_is_draft_defaults_false(app_session: Session) -> None:
    from app.db.models import RangeAssignment

    node = create_node(app_session, level="פלוגה", name="פלוגה is_draft")
    soldier = create_soldier(app_session, personal_number="9000001", hierarchy_node_id=node.id)
    event = RangeEvent(
        hierarchy_node_id=node.id, range_type=RangeType.laser,
        date=date(2026, 8, 25), location="מטווח", required_count=1,
    )
    app_session.add(event)
    app_session.flush()

    assignment = RangeAssignment(range_event_id=event.id, soldier_id=soldier.id, is_reserve=False)
    app_session.add(assignment)
    app_session.commit()
    app_session.refresh(assignment)

    assert assignment.is_draft is False
```

(This file already imports `date`, `RangeEvent`, `RangeType`, `create_node`, `create_soldier`, `Session` at module scope from Phase 1 — no new imports needed.)

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest app/db/tests/test_range_models.py -v`
Expected: all tests pass (the new one plus Phase 1's existing ones).

- [ ] **Step 7: Commit**

```bash
cd backend
git add app/db/models.py app/routes/ranges.py alembic/versions/7a13f6c9b8e2_add_range_assignment_is_draft.py app/db/tests/test_range_models.py
git commit -m "feat: add RangeAssignment.is_draft column and range_assignment_confirmed notification type"
```

---

## Task 2: Candidate pool and tier ranking

**Files:**
- Create: `backend/app/services/range_auto_assign.py`
- Test: `backend/app/services/tests/test_range_auto_assign.py`

**Interfaces:**
- Consumes: `RangeEvent`, `RangeAssignment`, `RangeEventStatus`, `RangeType`, `RANGE_TYPE_RANK`, `SoldierRangeQualification`, `DutyAssignment`, `DutyType`, `HierarchyNode`, `Soldier` (`app.db.models`); `is_range_exempt` (`app.services.range_exemption`); `get_approved_constraint_dates` (`app.services.constraints`); `RangeValidationError` (`app.services.ranges`).
- Produces: `propose_range_assignments(session: Session, *, event: RangeEvent) -> tuple[list[RangeAssignment], int]` (returns `(created_drafts, shortfall_count)`) in `app.services.range_auto_assign` — used by Task 4's route.

- [ ] **Step 1: Write the failing tests**

Create `backend/app/services/tests/test_range_auto_assign.py`:

```python
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyType,
    PersonalConstraint,
    RangeEventStatus,
    RangeType,
    SoldierRangeQualification,
)
from app.services.ranges import RangeValidationError, add_range_assignment, create_range_event
from app.services.range_auto_assign import propose_range_assignments
from tests.helpers import create_node, create_soldier


def _weapon_duty_type(session: Session, *, node, name: str) -> DutyType:
    dt = DutyType(name=name, score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id])
    session.add(dt)
    session.flush()
    return dt


def test_candidate_pool_excludes_soldier_outside_subtree(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה א-outside")
    other_node = create_node(app_session, level="פלוגה", name="פלוגה ב-outside")
    _weapon_duty_type(app_session, node=node, name="weapon-a-outside")
    outsider = create_soldier(app_session, personal_number="6000001", hierarchy_node_id=other_node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert outsider.id not in {a.soldier_id for a in created}
    assert shortfall == 1


def test_candidate_pool_excludes_already_assigned(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה כבר-משובץ")
    _weapon_duty_type(app_session, node=node, name="weapon-already-assigned")
    soldier = create_soldier(app_session, personal_number="6000002", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert created == []
    assert shortfall == 0


def test_candidate_pool_excludes_range_exempt_soldier(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה פטור")
    # No requires_weapon duty type eligible for this node -> soldier is structurally exempt.
    soldier = create_soldier(app_session, personal_number="6000003", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert soldier.id not in {a.soldier_id for a in created}


def test_candidate_pool_excludes_approved_personal_constraint(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה אילוץ")
    _weapon_duty_type(app_session, node=node, name="weapon-constraint")
    soldier = create_soldier(app_session, personal_number="6000004", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=1,
    )
    app_session.add(PersonalConstraint(
        soldier_id=soldier.id, start_date=event_date - timedelta(days=1),
        end_date=event_date + timedelta(days=1), reason="חופשה", status="approved",
    ))
    app_session.flush()

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert soldier.id not in {a.soldier_id for a in created}
    assert shortfall == 1


def test_candidate_pool_excludes_soldier_on_duty_that_day(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה בתורנות")
    location = None
    from tests.helpers import create_duty_location
    location = create_duty_location(app_session, hierarchy_node_id=node.id)
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-on-duty")
    soldier = create_soldier(app_session, personal_number="6000005", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=1,
    )
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=event_date, end_date=event_date, status="published",
    ))
    app_session.flush()

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert soldier.id not in {a.soldier_id for a in created}


def test_candidate_pool_excludes_soldier_at_another_range_same_day(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה מטווח-אחר")
    _weapon_duty_type(app_session, node=node, name="weapon-other-range")
    soldier = create_soldier(app_session, personal_number="6000006", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    other_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=event_date, location="מטווח אחר", required_count=1,
    )
    add_range_assignment(app_session, event=other_event, soldier_id=soldier.id, is_reserve=False)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=1,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert soldier.id not in {a.soldier_id for a in created}


def test_tier_a_sorts_before_tier_b_before_tier_c(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה שכבות")
    location = None
    from tests.helpers import create_duty_location
    location = create_duty_location(app_session, hierarchy_node_id=node.id)
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-tiers")
    event_date = date.today() + timedelta(days=5)

    tier_c_soldier = create_soldier(app_session, personal_number="6100001", hierarchy_node_id=node.id)
    app_session.add(SoldierRangeQualification(
        soldier_id=tier_c_soldier.id, range_type=RangeType.laser, valid_until=event_date + timedelta(days=30),
    ))
    tier_b_soldier = create_soldier(app_session, personal_number="6100002", hierarchy_node_id=node.id)
    tier_a_soldier = create_soldier(app_session, personal_number="6100003", hierarchy_node_id=node.id)
    app_session.add(DutyAssignment(
        soldier_id=tier_a_soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=1), status="published",
    ))
    app_session.flush()

    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=3,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    order = [a.soldier_id for a in created]
    assert order == [tier_a_soldier.id, tier_b_soldier.id, tier_c_soldier.id]
    assert shortfall == 0


def test_tier_a_orders_by_earliest_duty_start(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה טייר-א")
    location = None
    from tests.helpers import create_duty_location
    location = create_duty_location(app_session, hierarchy_node_id=node.id)
    weapon_dt = _weapon_duty_type(app_session, node=node, name="weapon-tier-a-order")
    event_date = date.today() + timedelta(days=5)

    later_soldier = create_soldier(app_session, personal_number="6200001", hierarchy_node_id=node.id)
    app_session.add(DutyAssignment(
        soldier_id=later_soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=date.today() + timedelta(days=10), end_date=date.today() + timedelta(days=10), status="published",
    ))
    sooner_soldier = create_soldier(app_session, personal_number="6200002", hierarchy_node_id=node.id)
    app_session.add(DutyAssignment(
        soldier_id=sooner_soldier.id, duty_type_id=weapon_dt.id, duty_location_id=location.id,
        start_date=date.today() + timedelta(days=2), end_date=date.today() + timedelta(days=2), status="published",
    ))
    app_session.flush()

    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=2,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert [a.soldier_id for a in created] == [sooner_soldier.id, later_soldier.id]


def test_tier_c_orders_by_soonest_expiring_qualification(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה טייר-ג")
    _weapon_duty_type(app_session, node=node, name="weapon-tier-c-order")
    event_date = date.today() + timedelta(days=5)

    expires_later = create_soldier(app_session, personal_number="6300001", hierarchy_node_id=node.id)
    app_session.add(SoldierRangeQualification(
        soldier_id=expires_later.id, range_type=RangeType.laser, valid_until=event_date + timedelta(days=100),
    ))
    expires_sooner = create_soldier(app_session, personal_number="6300002", hierarchy_node_id=node.id)
    app_session.add(SoldierRangeQualification(
        soldier_id=expires_sooner.id, range_type=RangeType.laser, valid_until=event_date + timedelta(days=10),
    ))
    app_session.flush()

    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=2,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert [a.soldier_id for a in created] == [expires_sooner.id, expires_later.id]


def test_qualification_at_higher_range_type_counts_as_tier_c(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה איכות-גבוהה")
    _weapon_duty_type(app_session, node=node, name="weapon-higher-qual")
    event_date = date.today() + timedelta(days=5)

    soldier = create_soldier(app_session, personal_number="6400001", hierarchy_node_id=node.id)
    # Qualified at "live" (higher than the event's "laser") -> still Tier C for a laser event.
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.live, valid_until=event_date + timedelta(days=10),
    ))
    app_session.flush()

    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=1,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert [a.soldier_id for a in created] == [soldier.id]


def test_fill_respects_primary_then_reserve_counts(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה מילוי")
    _weapon_duty_type(app_session, node=node, name="weapon-fill")
    event_date = date.today() + timedelta(days=5)
    soldiers = [
        create_soldier(app_session, personal_number=f"650000{i}", hierarchy_node_id=node.id)
        for i in range(3)
    ]
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=2, reserve_count=1,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert shortfall == 0
    assert sum(1 for a in created if not a.is_reserve) == 2
    assert sum(1 for a in created if a.is_reserve) == 1


def test_partial_fill_reports_shortfall(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה מחסור")
    _weapon_duty_type(app_session, node=node, name="weapon-shortfall")
    event_date = date.today() + timedelta(days=5)
    create_soldier(app_session, personal_number="6600001", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=3,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert len(created) == 1
    assert shortfall == 2


def test_created_drafts_have_is_draft_true(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה טיוטה")
    _weapon_duty_type(app_session, node=node, name="weapon-draft")
    soldier = create_soldier(app_session, personal_number="6700001", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert all(a.is_draft for a in created)


def test_auto_assign_only_fills_remaining_slots(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה חלקי-כבר-משובץ")
    _weapon_duty_type(app_session, node=node, name="weapon-partial-existing")
    already = create_soldier(app_session, personal_number="6800001", hierarchy_node_id=node.id)
    candidate = create_soldier(app_session, personal_number="6800002", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=2,
    )
    add_range_assignment(app_session, event=event, soldier_id=already.id, is_reserve=False)

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert [a.soldier_id for a in created] == [candidate.id]
    assert shortfall == 0


def test_propose_rejects_non_planned_event(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה בוטל")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )
    from app.services.ranges import cancel_range_event
    cancel_range_event(app_session, event=event)

    with pytest.raises(RangeValidationError):
        propose_range_assignments(app_session, event=event)
```

Note: this test file relies on a `create_duty_location` test helper. Check `backend/tests/helpers.py` for it before running — if it doesn't exist yet, add it there first:

```python
def create_duty_location(session: Session, *, hierarchy_node_id: uuid.UUID, name: str = "מיקום בדיקה") -> DutyLocation:
    location = DutyLocation(name=name, hierarchy_node_id=hierarchy_node_id)
    session.add(location)
    session.flush()
    return location
```

(Import `DutyLocation` from `app.db.models` at the top of `helpers.py` alongside its other model imports if not already imported.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest app/services/tests/test_range_auto_assign.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.range_auto_assign'`

- [ ] **Step 3: Implement the service**

Create `backend/app/services/range_auto_assign.py`:

```python
from __future__ import annotations

import uuid
from datetime import date
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyType,
    HierarchyNode,
    RANGE_TYPE_RANK,
    RangeAssignment,
    RangeEvent,
    RangeEventStatus,
    Soldier,
    SoldierRangeQualification,
)
from app.services.constraints import get_approved_constraint_dates
from app.services.range_exemption import is_range_exempt
from app.services.ranges import RangeValidationError


def _qualification_types_at_or_above(range_type: str) -> list[str]:
    min_rank = RANGE_TYPE_RANK[range_type]
    return [rt for rt, rank in RANGE_TYPE_RANK.items() if rank >= min_rank]


def _best_qualification_valid_until(
    session: Session, *, soldier_id: uuid.UUID, range_type: str, as_of: date,
) -> date | None:
    """Among the soldier's still-valid (valid_until >= as_of) qualification rows at
    range_type or higher, returns the valid_until of the most permissive (highest-rank)
    one, or None if the soldier has no such row."""
    candidate_types = _qualification_types_at_or_above(range_type)
    rows = session.execute(
        select(SoldierRangeQualification).where(
            SoldierRangeQualification.soldier_id == soldier_id,
            SoldierRangeQualification.range_type.in_(candidate_types),
            SoldierRangeQualification.valid_until >= as_of,
        )
    ).scalars().all()
    if not rows:
        return None
    best = max(rows, key=lambda r: RANGE_TYPE_RANK[r.range_type])
    return best.valid_until


def _earliest_future_weapon_duty_start(session: Session, *, soldier_id: uuid.UUID) -> date | None:
    return session.execute(
        select(func.min(DutyAssignment.start_date))
        .join(DutyType, DutyAssignment.duty_type_id == DutyType.id)
        .where(
            DutyAssignment.soldier_id == soldier_id,
            DutyAssignment.status == "published",
            DutyAssignment.start_date >= date.today(),
            DutyType.requires_weapon.is_(True),
        )
    ).scalar_one_or_none()


def _has_approved_constraint_on_date(session: Session, *, soldier_id: uuid.UUID, event_date: date) -> bool:
    for start, end in get_approved_constraint_dates(session, soldier_id=soldier_id):
        if start <= event_date <= end:
            return True
    return False


def _has_duty_assignment_on_date(session: Session, *, soldier_id: uuid.UUID, event_date: date) -> bool:
    return session.execute(
        select(DutyAssignment.id).where(
            DutyAssignment.soldier_id == soldier_id,
            DutyAssignment.start_date <= event_date,
            DutyAssignment.end_date >= event_date,
        ).limit(1)
    ).scalar_one_or_none() is not None


def _has_range_assignment_on_date(session: Session, *, soldier_id: uuid.UUID, event_date: date) -> bool:
    return session.execute(
        select(RangeAssignment.id)
        .join(RangeEvent, RangeAssignment.range_event_id == RangeEvent.id)
        .where(RangeAssignment.soldier_id == soldier_id, RangeEvent.date == event_date)
        .limit(1)
    ).scalar_one_or_none() is not None


def _sort_key(session: Session, *, soldier: Soldier, event: RangeEvent) -> tuple:
    qualified_until = _best_qualification_valid_until(
        session, soldier_id=soldier.id, range_type=event.range_type, as_of=event.date,
    )
    if qualified_until is not None:
        return (2, qualified_until, str(soldier.id))
    duty_start = _earliest_future_weapon_duty_start(session, soldier_id=soldier.id)
    if duty_start is not None:
        return (0, duty_start, str(soldier.id))
    return (1, str(soldier.id))


def _candidate_pool(session: Session, *, event: RangeEvent, exclude_soldier_ids: set[uuid.UUID]) -> list[Soldier]:
    subtree_node_ids = list(
        session.execute(
            select(HierarchyNode.id).where(HierarchyNode.path_ids.any(event.hierarchy_node_id))  # type: ignore[arg-type]
        ).scalars().all()
    )
    soldiers = session.execute(
        select(Soldier).where(Soldier.hierarchy_node_id.in_(subtree_node_ids))
    ).scalars().all()

    pool: list[Soldier] = []
    for soldier in soldiers:
        if soldier.id in exclude_soldier_ids:
            continue
        if is_range_exempt(session, soldier=soldier, event_date=event.date):
            continue
        if _has_approved_constraint_on_date(session, soldier_id=soldier.id, event_date=event.date):
            continue
        if _has_duty_assignment_on_date(session, soldier_id=soldier.id, event_date=event.date):
            continue
        if _has_range_assignment_on_date(session, soldier_id=soldier.id, event_date=event.date):
            continue
        pool.append(soldier)
    return pool


def propose_range_assignments(
    session: Session, *, event: RangeEvent,
) -> tuple[list[RangeAssignment], int]:
    """Fills the event's currently-empty primary/reserve slots with draft
    RangeAssignment rows (is_draft=True), ranked by the Phase 2 tier ordering.
    Returns (created_drafts, shortfall) where shortfall is how many slots
    could not be filled because the candidate pool ran out."""
    if event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")

    existing = session.execute(
        select(RangeAssignment).where(RangeAssignment.range_event_id == event.id)
    ).scalars().all()
    existing_soldier_ids = {a.soldier_id for a in existing}
    remaining_primary = max(event.required_count - sum(1 for a in existing if not a.is_reserve), 0)
    remaining_reserve = max(event.reserve_count - sum(1 for a in existing if a.is_reserve), 0)
    total_needed = remaining_primary + remaining_reserve
    if total_needed == 0:
        return [], 0

    pool = _candidate_pool(session, event=event, exclude_soldier_ids=existing_soldier_ids)
    ranked = sorted(pool, key=lambda s: _sort_key(session, soldier=s, event=event))

    chosen = ranked[:total_needed]
    shortfall = total_needed - len(chosen)

    created: list[RangeAssignment] = []
    for index, soldier in enumerate(chosen):
        assignment = RangeAssignment(
            range_event_id=event.id, soldier_id=soldier.id,
            is_reserve=index >= remaining_primary, is_draft=True,
        )
        session.add(assignment)
        created.append(assignment)

    session.commit()
    for assignment in created:
        session.refresh(assignment)
    return created, shortfall
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest app/services/tests/test_range_auto_assign.py -v`
Expected: `15 passed`

- [ ] **Step 5: Add the new test file to `_AREA_MARKERS`**

In `backend/tests/conftest.py`, find `_AREA_MARKERS: dict[str, str]` (it already has `"test_range_models": "duty"`, `"test_range_exemption": "duty"`, etc. from Phase 1) and add:

```python
    "test_range_auto_assign": "duty",
```

- [ ] **Step 6: Run the fast suite to confirm nothing broke**

Run: `cd backend && .venv/Scripts/python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
cd backend
git add app/services/range_auto_assign.py app/services/tests/test_range_auto_assign.py tests/conftest.py tests/helpers.py
git commit -m "feat: add range auto-assign candidate pool and three-tier priority ranking"
```

---

## Task 3: Confirm / reject draft assignments

**Files:**
- Modify: `backend/app/services/range_auto_assign.py` (append functions)
- Modify: `backend/app/services/tests/test_range_auto_assign.py` (append tests)

**Interfaces:**
- Consumes: `write_audit` (`app.audit.writer`), `create_notification` (`app.services.notifications`), `NotificationType.range_assignment_confirmed` (Task 1), `remove_range_assignment` (`app.services.ranges`, Phase 1, already handles the "reject" case — no new function needed for it).
- Produces: `confirm_draft_assignment(session: Session, *, assignment: RangeAssignment, actor_id: uuid.UUID | None = None) -> RangeAssignment`, `confirm_all_drafts(session: Session, *, event: RangeEvent, actor_id: uuid.UUID | None = None) -> list[RangeAssignment]` in `app.services.range_auto_assign` — used by Task 4's routes.

- [ ] **Step 1: Write the failing tests**

Append to `backend/app/services/tests/test_range_auto_assign.py`:

```python
from app.db.models import NotificationType, Notification
from app.services.range_auto_assign import confirm_all_drafts, confirm_draft_assignment


def test_confirm_draft_assignment_flips_is_draft_and_notifies(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה אישור")
    _weapon_duty_type(app_session, node=node, name="weapon-confirm")
    soldier = create_soldier(app_session, personal_number="6900001", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )
    created, _ = propose_range_assignments(app_session, event=event)
    draft = created[0]

    confirmed = confirm_draft_assignment(app_session, assignment=draft, actor_id=soldier.id)

    assert confirmed.is_draft is False
    notification = app_session.query(Notification).filter(
        Notification.soldier_id == confirmed.soldier_id,
        Notification.type == NotificationType.range_assignment_confirmed,
    ).one_or_none()
    assert notification is not None


def test_confirm_draft_assignment_rejects_non_draft(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה לא-טיוטה")
    _weapon_duty_type(app_session, node=node, name="weapon-not-draft")
    soldier = create_soldier(app_session, personal_number="6900002", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )
    manual = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    with pytest.raises(RangeValidationError):
        confirm_draft_assignment(app_session, assignment=manual, actor_id=soldier.id)


def test_confirm_all_drafts_confirms_every_draft_for_the_event(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה אישור-הכל")
    _weapon_duty_type(app_session, node=node, name="weapon-confirm-all")
    create_soldier(app_session, personal_number="6900003", hierarchy_node_id=node.id)
    create_soldier(app_session, personal_number="6900004", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=2,
    )
    propose_range_assignments(app_session, event=event)

    confirmed = confirm_all_drafts(app_session, event=event, actor_id=None)

    assert len(confirmed) == 2
    assert all(a.is_draft is False for a in confirmed)


def test_confirm_all_drafts_leaves_non_draft_assignments_untouched(app_session: Session) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגה מעורב")
    _weapon_duty_type(app_session, node=node, name="weapon-mixed")
    manual_soldier = create_soldier(app_session, personal_number="6900005", hierarchy_node_id=node.id)
    create_soldier(app_session, personal_number="6900006", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=2,
    )
    manual = add_range_assignment(app_session, event=event, soldier_id=manual_soldier.id, is_reserve=False)
    propose_range_assignments(app_session, event=event)

    confirm_all_drafts(app_session, event=event, actor_id=None)

    app_session.refresh(manual)
    assert manual.is_draft is False  # was already False, untouched


def test_rejecting_a_draft_deletes_the_row_and_reopens_the_slot(app_session: Session) -> None:
    from app.services.ranges import remove_range_assignment

    node = create_node(app_session, level="פלוגה", name="פלוגה דחייה")
    _weapon_duty_type(app_session, node=node, name="weapon-reject")
    create_soldier(app_session, personal_number="6900007", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )
    created, _ = propose_range_assignments(app_session, event=event)
    draft = created[0]

    remove_range_assignment(app_session, assignment=draft)

    created_again, shortfall = propose_range_assignments(app_session, event=event)
    assert len(created_again) == 1
    assert shortfall == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest app/services/tests/test_range_auto_assign.py -v`
Expected: FAIL — `ImportError: cannot import name 'confirm_draft_assignment'`

- [ ] **Step 3: Implement confirm/reject**

Append to `backend/app/services/range_auto_assign.py`:

```python
from app.audit.writer import write_audit
from app.db.models import NotificationType
from app.services.notifications import create_notification


def confirm_draft_assignment(
    session: Session, *, assignment: RangeAssignment, actor_id: uuid.UUID | None = None,
) -> RangeAssignment:
    if not assignment.is_draft:
        raise RangeValidationError("assignment_not_draft")

    assignment.is_draft = False
    write_audit(
        session, actor_id=actor_id, action="range_assignment_confirm", entity_type="range_assignment",
        entity_id=assignment.id, before={"is_draft": True}, after={"is_draft": False},
    )
    create_notification(
        session, soldier_id=assignment.soldier_id, type=NotificationType.range_assignment_confirmed,
        title="שובצת למטווח", reference_type="range_assignment", reference_id=assignment.id, actor_id=actor_id,
    )
    session.commit()
    session.refresh(assignment)
    return assignment


def confirm_all_drafts(
    session: Session, *, event: RangeEvent, actor_id: uuid.UUID | None = None,
) -> list[RangeAssignment]:
    drafts = session.execute(
        select(RangeAssignment).where(
            RangeAssignment.range_event_id == event.id, RangeAssignment.is_draft.is_(True),
        )
    ).scalars().all()
    return [confirm_draft_assignment(session, assignment=d, actor_id=actor_id) for d in drafts]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest app/services/tests/test_range_auto_assign.py -v`
Expected: `19 passed`

- [ ] **Step 5: Run the fast suite**

Run: `cd backend && .venv/Scripts/python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/services/range_auto_assign.py app/services/tests/test_range_auto_assign.py
git commit -m "feat: add confirm/confirm-all for draft range assignments with notification"
```

---

## Task 4: Routes — auto-assign, confirm, confirm-all

**Files:**
- Modify: `backend/app/routes/ranges.py`
- Test: `backend/app/routes/tests/test_ranges_api.py` (existing file from Phase 1 — check its exact name/location first with `Glob backend/app/routes/tests/test_range*` or `Glob backend/tests/**/test_ranges*`; append new tests there. If no such file exists yet, create `backend/app/routes/tests/test_ranges_api.py` following the same FastAPI `TestClient` pattern used by sibling route test files, e.g. `backend/app/routes/tests/test_swaps_api.py`.)

**Interfaces:**
- Consumes: `propose_range_assignments`, `confirm_draft_assignment`, `confirm_all_drafts` (Task 2/3, `app.services.range_auto_assign`); existing `_require_enabled`, `_load_event`, `_event_node`, `_assignment_out`, `Action.RANGE_MANAGE`, `authorize` (already in `backend/app/routes/ranges.py`).
- Produces: `POST /ranges/{event_id}/auto-assign`, `POST /ranges/{event_id}/assignments/{assignment_id}/confirm`, `POST /ranges/{event_id}/assignments/confirm-all` — consumed by Task 5's frontend API wrapper.

- [ ] **Step 1: Locate the existing route test file and its fixtures**

Run: `cd backend && .venv/Scripts/python -m pytest --collect-only -q -k ranges_api 2>&1 | head -30` (or on Windows, drop the `head`) to find the exact test file path and see what client/auth fixtures (`client`, `dm_headers` or similar) sibling tests use. Read that file before writing Step 2's tests so the new tests match its existing helper functions/fixtures exactly (e.g. how a DM user + JWT header is created, how `mitvachim.enabled` is turned on for a test).

- [ ] **Step 2: Write the failing route tests**

Using whatever pattern Step 1 found (a `client: TestClient` fixture, a helper to create an authenticated DM and get its auth header, a helper to enable `mitvachim.enabled`), append tests that:
- `test_auto_assign_creates_drafts`: POST `/ranges/{event_id}/auto-assign` as an in-scope DM on a planned event with open slots and at least one eligible soldier in the DB → 200, response body has a `created` list with `is_draft: true` entries and a `shortfall` integer.
- `test_auto_assign_requires_range_manage`: POST as a soldier (not DM) → 403.
- `test_auto_assign_404_when_flag_disabled`: with `mitvachim.enabled` false → 404.
- `test_confirm_draft_flips_is_draft`: POST `/ranges/{event_id}/assignments/{assignment_id}/confirm` on a previously-created draft as an in-scope DM → 200, `is_draft: false` in response.
- `test_confirm_all_drafts_confirms_every_draft`: POST `/ranges/{event_id}/assignments/confirm-all` → 200, list response, all `is_draft: false`.
- `test_confirm_nonexistent_assignment_404s`: POST confirm with a random UUID assignment id → 404.

Write these using the exact request/response shapes from Step 3's implementation below (the route paths, HTTP methods, and JSON field names must match exactly — `created`, `shortfall`, and a plain `list[RangeAssignmentOut]` for confirm-all).

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest app/routes/tests/test_ranges_api.py -v -k "auto_assign or confirm"`
Expected: FAIL — 404 (route doesn't exist) on every new test.

- [ ] **Step 4: Implement the routes**

In `backend/app/routes/ranges.py`, add this import near the top (alongside the existing `from app.services import ranges as svc`):

```python
from app.services import range_auto_assign as auto_assign_svc
```

Then append these route handlers and response models at the end of the file:

```python
class AutoAssignResponse(BaseModel):
    created: list[RangeAssignmentOut]
    shortfall: int


@router.post("/{event_id}/auto-assign", response_model=AutoAssignResponse)
def auto_assign(
    event_id: uuid.UUID, session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> AutoAssignResponse:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    try:
        created, shortfall = auto_assign_svc.propose_range_assignments(session, event=event)
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return AutoAssignResponse(created=[_assignment_out(a) for a in created], shortfall=shortfall)


@router.post("/{event_id}/assignments/{assignment_id}/confirm", response_model=RangeAssignmentOut)
def confirm_assignment(
    event_id: uuid.UUID, assignment_id: uuid.UUID, session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> RangeAssignmentOut:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    assignment = session.get(RangeAssignment, assignment_id)
    if assignment is None or assignment.range_event_id != event_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    try:
        confirmed = auto_assign_svc.confirm_draft_assignment(session, assignment=assignment, actor_id=user.id)
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _assignment_out(confirmed)


@router.post("/{event_id}/assignments/confirm-all", response_model=list[RangeAssignmentOut])
def confirm_all_assignments(
    event_id: uuid.UUID, session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[RangeAssignmentOut]:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    confirmed = auto_assign_svc.confirm_all_drafts(session, event=event, actor_id=user.id)
    return [_assignment_out(a) for a in confirmed]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest app/routes/tests/test_ranges_api.py -v`
Expected: all pass, including Phase 1's existing route tests (unaffected).

- [ ] **Step 6: Run the fast suite**

Run: `cd backend && .venv/Scripts/python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
cd backend
git add app/routes/ranges.py app/routes/tests/test_ranges_api.py
git commit -m "feat: add auto-assign, confirm, and confirm-all routes for range assignments"
```

---

## Task 5: Frontend API wrapper

**Files:**
- Modify: `frontend/src/api/ranges.ts`
- Modify: `frontend/src/api/ranges.test.ts`

**Interfaces:**
- Consumes: existing `api` client (`./client`), existing `RangeAssignment`/`RangeType` types in the same file.
- Produces: `RangeAssignment.is_draft: boolean` (extends existing interface), `autoAssignRange(eventId: string): Promise<{ created: RangeAssignment[]; shortfall: number }>`, `confirmDraftAssignment(eventId: string, assignmentId: string): Promise<RangeAssignment>`, `confirmAllDrafts(eventId: string): Promise<RangeAssignment[]>` — used by Task 6's `RangesPage.tsx`.

- [ ] **Step 1: Write the failing tests**

Read `frontend/src/api/ranges.test.ts` first to match its existing mock pattern for `api.get`/`api.post`/`api.delete` (Phase 1's tests already mock `./client`). Append:

```ts
describe("autoAssignRange", () => {
  it("posts to the auto-assign endpoint and returns created + shortfall", async () => {
    const mockResponse = { created: [{ id: "a1", soldier_id: "s1", is_reserve: false, is_draft: true, attendance_status: "pending", note: null }], shortfall: 1 };
    (api.post as jest.Mock).mockResolvedValueOnce({ data: mockResponse });

    const result = await autoAssignRange("event-1");

    expect(api.post).toHaveBeenCalledWith("/ranges/event-1/auto-assign");
    expect(result).toEqual(mockResponse);
  });
});

describe("confirmDraftAssignment", () => {
  it("posts to the confirm endpoint", async () => {
    const mockAssignment = { id: "a1", soldier_id: "s1", is_reserve: false, is_draft: false, attendance_status: "pending", note: null };
    (api.post as jest.Mock).mockResolvedValueOnce({ data: mockAssignment });

    const result = await confirmDraftAssignment("event-1", "a1");

    expect(api.post).toHaveBeenCalledWith("/ranges/event-1/assignments/a1/confirm");
    expect(result).toEqual(mockAssignment);
  });
});

describe("confirmAllDrafts", () => {
  it("posts to the confirm-all endpoint", async () => {
    const mockAssignments = [{ id: "a1", soldier_id: "s1", is_reserve: false, is_draft: false, attendance_status: "pending", note: null }];
    (api.post as jest.Mock).mockResolvedValueOnce({ data: mockAssignments });

    const result = await confirmAllDrafts("event-1");

    expect(api.post).toHaveBeenCalledWith("/ranges/event-1/assignments/confirm-all");
    expect(result).toEqual(mockAssignments);
  });
});
```

Adjust the mock setup (`vi.mock`/`jest.mock`, whichever this repo's vitest config uses — check the top of the existing `ranges.test.ts` file) and the import line at the top of the test file to include `autoAssignRange, confirmDraftAssignment, confirmAllDrafts` from `./ranges`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- ranges.test.ts`
Expected: FAIL — `autoAssignRange is not a function` (or TS compile error naming the missing export).

- [ ] **Step 3: Implement the wrapper functions**

In `frontend/src/api/ranges.ts`, modify the `RangeAssignment` interface (currently lines 7-13) to add `is_draft`:

```ts
export interface RangeAssignment {
  id: string;
  soldier_id: string;
  is_reserve: boolean;
  is_draft: boolean;
  attendance_status: RangeAttendanceStatus;
  note: string | null;
}
```

Add these exports at the end of the file:

```ts
export interface AutoAssignResult {
  created: RangeAssignment[];
  shortfall: number;
}

export function autoAssignRange(eventId: string): Promise<AutoAssignResult> {
  return api.post(`/ranges/${eventId}/auto-assign`).then((r) => r.data);
}

export function confirmDraftAssignment(eventId: string, assignmentId: string): Promise<RangeAssignment> {
  return api.post(`/ranges/${eventId}/assignments/${assignmentId}/confirm`).then((r) => r.data);
}

export function confirmAllDrafts(eventId: string): Promise<RangeAssignment[]> {
  return api.post(`/ranges/${eventId}/assignments/confirm-all`).then((r) => r.data);
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- ranges.test.ts`
Expected: all pass.

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
cd frontend
git add src/api/ranges.ts src/api/ranges.test.ts
git commit -m "feat: add auto-assign/confirm API wrapper functions and is_draft field"
```

---

## Task 6: Frontend UI — auto-assign button, draft badges, confirm/reject

**Files:**
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/pages/RangesPage.test.tsx`

**Interfaces:**
- Consumes: `autoAssignRange`, `confirmDraftAssignment`, `confirmAllDrafts` (Task 5, `../api/ranges`); existing `removeRangeAssignment`, `queryKeys.rangeEvent`.
- Produces: nothing new for other tasks — this is the final UI-facing task of the plan.

- [ ] **Step 1: Write the failing tests**

Read `frontend/src/pages/RangesPage.test.tsx` first to match its existing render/mock/query-client setup pattern (Phase 1's tests already mock `../api/ranges` and render with a `QueryClientProvider`). Append tests that:
- `test_auto_assign_button_visible_when_slots_remain`: with a selected `planned` event whose `assignments.length < required_count + reserve_count`, the "שבץ אוטומטית" button (`data-testid="auto-assign-button"`) renders; clicking it calls `autoAssignRange` with the event id and, after the mocked response resolves, the roster shows a draft row with a "טיוטה" badge (`data-testid="draft-badge"`).
- `test_auto_assign_button_hidden_when_slots_full`: with `assignments.length === required_count + reserve_count`, the button is absent.
- `test_confirm_draft_button_calls_confirm`: a draft row (`is_draft: true` in `selectedEvent.assignments`) renders a confirm button (`data-testid="confirm-draft-button"`); clicking it calls `confirmDraftAssignment(eventId, assignmentId)` and invalidates the `rangeEvent` query.
- `test_confirm_all_button_calls_confirm_all`: when at least one draft row exists, a "אשר הכל" button (`data-testid="confirm-all-button"`) renders; clicking it calls `confirmAllDrafts(eventId)`.
- `test_shortfall_banner_renders`: after `autoAssignRange` resolves with `shortfall: 2`, a banner (`data-testid="shortfall-banner"`) renders showing the shortfall count.
- `test_reject_draft_uses_existing_remove_button`: a draft row's existing "הסר" button still calls `removeRangeAssignment` (no behavior change — drafts are removed the same way as any other row, confirming Task 3's design choice to reuse the Phase 1 remove path).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- RangesPage.test.tsx`
Expected: FAIL — `auto-assign-button` / `draft-badge` / etc. not found.

- [ ] **Step 3: Implement the UI**

In `frontend/src/pages/RangesPage.tsx`, update the import block (currently lines 4-19) to add the three new API functions:

```tsx
import {
  getRanges,
  getRangeEvent,
  addRangeAssignment,
  removeRangeAssignment,
  createRangeEvent,
  autoAssignRange,
  confirmDraftAssignment,
  confirmAllDrafts,
  RangeEvent,
  RangeType,
} from "../api/ranges";
```

Add local state for the shortfall banner near the other `useState` declarations (after `const [newReserveCount, setNewReserveCount] = useState(0);`):

```tsx
  const [autoAssignShortfall, setAutoAssignShortfall] = useState<number | null>(null);
```

Add handler functions near `handleAddSoldier`:

```tsx
  async function handleAutoAssign() {
    if (!selectedEventId) return;
    const { shortfall } = await autoAssignRange(selectedEventId);
    setAutoAssignShortfall(shortfall > 0 ? shortfall : null);
    queryClient.invalidateQueries({ queryKey: queryKeys.rangeEvent(selectedEventId) });
  }

  async function handleConfirmDraft(assignmentId: string) {
    if (!selectedEventId) return;
    await confirmDraftAssignment(selectedEventId, assignmentId);
    queryClient.invalidateQueries({ queryKey: queryKeys.rangeEvent(selectedEventId) });
  }

  async function handleConfirmAll() {
    if (!selectedEventId) return;
    await confirmAllDrafts(selectedEventId);
    queryClient.invalidateQueries({ queryKey: queryKeys.rangeEvent(selectedEventId) });
  }
```

Replace the roster `<ul>` block (currently lines 185-194) plus the button above it (lines 166-170) with:

```tsx
          {canManage && (() => {
            const filled = selectedEvent.assignments.length;
            const capacity = selectedEvent.required_count + selectedEvent.reserve_count;
            const hasDrafts = selectedEvent.assignments.some((a) => a.is_draft);
            return (
              <>
                <button data-testid="add-soldier-button" onClick={() => setShowPicker(true)}>
                  הוסף חייל
                </button>
                {selectedEvent.status === "planned" && filled < capacity && (
                  <button data-testid="auto-assign-button" onClick={handleAutoAssign}>
                    שבץ אוטומטית
                  </button>
                )}
                {hasDrafts && (
                  <button data-testid="confirm-all-button" onClick={handleConfirmAll}>
                    אשר הכל
                  </button>
                )}
              </>
            );
          })()}
          {autoAssignShortfall !== null && (
            <div data-testid="shortfall-banner">
              לא נמצאו מספיק מועמדים — חסרים {autoAssignShortfall} משבצים
            </div>
          )}
          {showPicker && canManage && (
            <>
              <label>
                <input
                  type="checkbox"
                  data-testid="reserve-toggle"
                  checked={isReserveToggle}
                  onChange={(e) => setIsReserveToggle(e.target.checked)}
                />
                שבץ כרזרבה
              </label>
              <SoldierSearchAutocomplete onSelect={handleAddSoldier} />
            </>
          )}
          <ul>
            {selectedEvent.assignments.map((a) => (
              <li key={a.id}>
                {a.soldier_id} {a.is_reserve ? "(רזרבה)" : ""}
                {a.is_draft && <span data-testid="draft-badge">טיוטה</span>}
                {canManage && a.is_draft && (
                  <button data-testid="confirm-draft-button" onClick={() => handleConfirmDraft(a.id)}>
                    אשר
                  </button>
                )}
                {canManage && (
                  <button onClick={() => handleRemoveAssignment(a.id)}>הסר</button>
                )}
              </li>
            ))}
          </ul>
```

Note: the original file had `{showPicker && ( ... )}` without a `canManage` guard because the "הוסף חייל" button (which sets `showPicker`) was already inside a `canManage` block, making it unreachable otherwise — the replacement above keeps the same effective behavior (`showPicker` can only become true via a `canManage`-gated button) but the explicit `canManage` guard on the picker block itself is now redundant-but-harmless; keep it for defense-in-depth since the block is no longer textually nested inside the button's `canManage` check.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- RangesPage.test.tsx`
Expected: all pass.

- [ ] **Step 5: Lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: zero warnings, no type errors.

- [ ] **Step 6: Manual verification in the browser**

Start the dev stack (`.\dev.ps1` from the repo root per CLAUDE.md), navigate to the ranges page as a DM with `mitvachim.enabled=true`, create a planned event with open slots and at least one eligible soldier seeded in the DB, click "שבץ אוטומטית", confirm a draft row, and confirm the roster updates without a full page reload.

- [ ] **Step 7: Commit**

```bash
cd frontend
git add src/pages/RangesPage.tsx src/pages/RangesPage.test.tsx
git commit -m "feat: add auto-assign button, draft badges, and confirm/confirm-all controls to RangesPage"
```

---

## Task 7: Full verification pass

**Files:** none (verification only).

- [ ] **Step 1: Backend full suite**

Run: `cd backend && .venv/Scripts/python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 2: Frontend full suite**

Run: `cd frontend && npm test`
Expected: all tests pass.

- [ ] **Step 3: Frontend lint + typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: zero warnings, no errors.

- [ ] **Step 4: Alembic head sanity check**

Run: `cd backend && .venv/Scripts/python -m alembic heads`
Expected: exactly one head, `7a13f6c9b8e2 (head)`.
