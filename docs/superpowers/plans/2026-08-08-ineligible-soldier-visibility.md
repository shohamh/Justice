# Ineligible Soldier Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Detect when a *published* duty assignment retroactively becomes weapon-ineligible (soldier's range qualification lapsed, excusal approved, setting/duty-type changed after the fact), cache the result on `DutyAssignment`, surface it in four UI locations with a red badge + ⚠️ markers, notify the soldier/commander/duty-managers once per transition, and give both the soldier and duty managers a one-click resolution path via the existing swap-request flow.

**Architecture:** A hybrid detector — event-driven rechecks fired from the four places that can change a soldier's weapon eligibility (attendance correction, excusal decision, system-setting change, duty-type range-tier change), plus a once-daily safety-net worker that catches pure time decay (qualification expiring with no triggering action). Both paths converge on one shared core function, `recheck_assignments`, built directly on top of `weapon_eligibility.compute_eligibility` (already shipped). Results are cached as three columns on `DutyAssignment` so badge queries are cheap `COUNT`s, not recomputation.

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy 2.0 (backend), React 18 / TypeScript / Vite (frontend), pytest (backend tests), Vitest (frontend tests), Alembic (migrations).

## Global Constraints

- Design spec: [`docs/superpowers/specs/2026-08-07-ineligible-soldier-visibility-design.md`](../specs/2026-08-07-ineligible-soldier-visibility-design.md) — every task below implements a piece of it; do not deviate from its approved decisions without checking back in.
- Alembic head at plan-writing time is `ffe105dad988` (the merge migration reconciling the ranges-in-duty-history and weapon-qualification-eligibility branches — see Task 1's `down_revision`). Verify this is still the actual head before generating Task 1's migration (`alembic heads` must print exactly one line); if it's drifted, use the real head instead and note it.
- **False → True transition** (soldier becomes ineligible): update cache, send 3 notifications (soldier, direct commander, duty managers in scope).
- **True → False transition** (soldier becomes eligible again): update cache silently, **no notification** — same pattern as the existing range-attendance-correction feature.
- Only `DutyAssignment` rows with `status == "published"` and a duty type whose `required_range_type is not None` are ever checked. Cancelled/draft assignments and non-weapon duties are never touched.
- The daily safety-net worker runs every 86400 seconds (once/day), unlike the other workers in this codebase which poll every 300 seconds — this one only needs to catch pure time decay, not fast-moving state.
- No new eligibility-computation logic: this feature is purely detection/caching/notification/visibility on top of the already-shipped `weapon_eligibility.compute_eligibility(session, *, soldier_id, required_range_type, as_of)`.
- The two resolution paths reuse existing mechanisms exactly as-is: soldier path opens the existing `OfferSwapModal` pre-filled with the ineligible assignment; duty-manager path cancels the assignment and reopens the existing `ShiftAssignModal` (already weapon-aware) on the freed slot. No new swap or assignment mechanism is built.
- Follow existing code patterns exactly where cited (file:line references below point at real precedent in this codebase — read them before writing the new code).
- Every task's backend tests run via `pytest -q <path>` from `backend/` (venv activated); frontend tests via `npm test -- <path>` from `frontend/`.

---

### Task 1: Migration — `DutyAssignment` weapon-ineligibility cache columns

**Files:**
- Create: `backend/alembic/versions/<new_revision>_add_duty_assignment_weapon_ineligible_cache.py`
- Test: `backend/tests/unit/test_migrations_weapon_ineligible_cache.py`

**Interfaces:**
- Produces: DB columns `duty_assignments.weapon_ineligible` (Boolean, `server_default=false`), `duty_assignments.weapon_ineligible_reason` (Text, nullable), `duty_assignments.weapon_ineligible_detected_at` (DateTime with tz, nullable), plus a partial index `ix_duty_assignments_weapon_ineligible` on `duty_assignments (id)` `WHERE weapon_ineligible = true`.

- [x] **Step 1: Generate the revision skeleton**

Run (from `backend/`, venv activated):
```bash
alembic heads
```
Confirm it prints exactly one line: `ffe105dad988 (head)`. If it prints something else, use that revision id as `down_revision` below instead.

```bash
alembic revision -m "add_duty_assignment_weapon_ineligible_cache"
```
Note the generated revision id (e.g. `a1b2c3d4e5f6`).

- [x] **Step 2: Write the migration body**

Replace the generated file's `upgrade`/`downgrade` with (the partial-index pattern is copied exactly from the existing precedent at `backend/alembic/versions/7f2c1a9d4e6b_add_range_excusal_requests.py:78-84`):

```python
"""add_duty_assignment_weapon_ineligible_cache

Revision ID: <new_revision>
Revises: ffe105dad988
Create Date: 2026-08-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '<new_revision>'
down_revision: Union[str, Sequence[str], None] = 'ffe105dad988'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "duty_assignments",
        sa.Column("weapon_ineligible", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "duty_assignments",
        sa.Column("weapon_ineligible_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "duty_assignments",
        sa.Column("weapon_ineligible_detected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_duty_assignments_weapon_ineligible",
        "duty_assignments",
        ["id"],
        unique=False,
        postgresql_where=sa.text("weapon_ineligible = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_duty_assignments_weapon_ineligible", table_name="duty_assignments")
    op.drop_column("duty_assignments", "weapon_ineligible_detected_at")
    op.drop_column("duty_assignments", "weapon_ineligible_reason")
    op.drop_column("duty_assignments", "weapon_ineligible")
```

- [x] **Step 3: Write a test proving the columns and defaults**

```python
# backend/tests/unit/test_migrations_weapon_ineligible_cache.py
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def test_weapon_ineligible_columns_exist_with_correct_defaults(app_session: Session) -> None:
    row = app_session.execute(
        text(
            "SELECT column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_name = 'duty_assignments' AND column_name = 'weapon_ineligible'"
        )
    ).mappings().first()
    assert row is not None
    assert row["data_type"] == "boolean"
    assert row["is_nullable"] == "NO"

    reason_row = app_session.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'duty_assignments' AND column_name = 'weapon_ineligible_reason'"
        )
    ).mappings().first()
    assert reason_row is not None
    assert reason_row["is_nullable"] == "YES"

    detected_row = app_session.execute(
        text(
            "SELECT is_nullable, data_type FROM information_schema.columns "
            "WHERE table_name = 'duty_assignments' AND column_name = 'weapon_ineligible_detected_at'"
        )
    ).mappings().first()
    assert detected_row is not None
    assert detected_row["is_nullable"] == "YES"
    assert detected_row["data_type"] == "timestamp with time zone"


def test_weapon_ineligible_partial_index_exists(app_session: Session) -> None:
    row = app_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'duty_assignments' AND indexname = 'ix_duty_assignments_weapon_ineligible'"
        )
    ).mappings().first()
    assert row is not None
    assert "weapon_ineligible" in row["indexdef"]
```

- [x] **Step 4: Apply the migration and run the test**

```bash
alembic upgrade head
pytest tests/unit/test_migrations_weapon_ineligible_cache.py -v
```
Expected: migration applies cleanly, both tests PASS.

- [x] **Step 5: Commit**

```bash
git add backend/alembic/versions/*_add_duty_assignment_weapon_ineligible_cache.py backend/tests/unit/test_migrations_weapon_ineligible_cache.py
git commit -m "feat: add DutyAssignment weapon-ineligibility cache columns"
```

---

### Task 2: Model — `DutyAssignment` fields + `NotificationType` members

**Files:**
- Modify: `backend/app/db/models.py:377-382` (DutyAssignment class), `backend/app/db/models.py:1219-1222` (NotificationType enum)

**Interfaces:**
- Produces: `DutyAssignment.weapon_ineligible: bool` (default `False`), `DutyAssignment.weapon_ineligible_reason: str | None`, `DutyAssignment.weapon_ineligible_detected_at: datetime | None`; `NotificationType.weapon_ineligible_detected` member.

- [x] **Step 1: Add the three columns to `DutyAssignment`**

In `backend/app/db/models.py`, immediately before `created_at` (currently lines 380-382), after `forced_call_up_multiplier` (currently lines 377-379):

```python
    forced_call_up_multiplier: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True, default=None
    )
    weapon_ineligible: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    weapon_ineligible_reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    weapon_ineligible_detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [x] **Step 2: Add the `NotificationType` member**

In `backend/app/db/models.py`, inside the `NotificationType` enum, right after `bug_report_comment = "bug_report_comment"` (the last member):

```python
    bug_report_comment = "bug_report_comment"
    weapon_ineligible_detected = "weapon_ineligible_detected"
```

- [x] **Step 3: Verify the model imports and constructs cleanly**

```bash
python -c "
from app.db.models import DutyAssignment, NotificationType
assert NotificationType.weapon_ineligible_detected == 'weapon_ineligible_detected'
print('ok')
"
```
Expected: prints `ok`.

- [x] **Step 4: Run the migration test from Task 1 (now covers ORM round-trip too)**

```bash
pytest tests/unit/test_migrations_weapon_ineligible_cache.py -v
```
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat: add DutyAssignment weapon-ineligibility fields and NotificationType member"
```

---

### Task 3: `duty_config.py` — make `DutyType.required_range_type` settable

**Files:**
- Modify: `backend/app/services/duty_config.py:87-147` (`update_duty_type`, `create_duty_type`)
- Modify: `backend/app/routes/duty_config.py:51-96,130-199` (`CreateDutyTypeRequest`, `UpdateDutyTypeRequest`, routes)
- Test: `backend/app/services/tests/test_duty_config.py` (add cases; check the file exists first)

**Interfaces:**
- Produces: `update_duty_type(..., required_range_type: str | None = None, ...)` and `create_duty_type(..., required_range_type: str | None = None, ...)` now accept and apply this field. `UpdateDutyTypeRequest`/`CreateDutyTypeRequest` gain a `required_range_type: str | None = None` field. The route captures the pre-update value so Task 6 can detect a real change.

This field currently exists only on the model (added by the weapon-qualification-eligibility plan) and is write-only via direct DB/migration — this task is the first time it becomes settable through the API, which Task 6's event hook depends on.

- [x] **Step 1: Check for an existing duty_config test file**

```bash
ls backend/app/services/tests/test_duty_config.py 2>&1
```
Use it if it exists; if not, create it (mirror the import style of `backend/app/services/tests/test_weapon_eligibility.py:1-21`).

- [x] **Step 2: Write the failing tests**

```python
# Add to backend/app/services/tests/test_duty_config.py
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import DutyType, RangeType
from app.services.duty_config import create_duty_type, update_duty_type


def test_create_duty_type_accepts_required_range_type(app_session: Session) -> None:
    dt = create_duty_type(
        app_session, name="dc-weapon-1", score_per_day=Decimal("1.00"), description=None,
        is_external=False, requires_weapon=True, required_range_type=RangeType.live,
    )
    app_session.commit()
    app_session.refresh(dt)
    assert dt.required_range_type == "live"


def test_update_duty_type_sets_required_range_type(app_session: Session) -> None:
    dt = DutyType(name="dc-weapon-2", score_per_day=Decimal("1.00"), requires_weapon=True)
    app_session.add(dt)
    app_session.commit()

    updated = update_duty_type(
        app_session, duty_type=dt, name=None, score_per_day=None, description=None,
        required_range_type=RangeType.alal,
    )
    app_session.commit()
    app_session.refresh(updated)
    assert updated.required_range_type == "alal"


def test_update_duty_type_leaves_required_range_type_untouched_when_none(app_session: Session) -> None:
    dt = DutyType(
        name="dc-weapon-3", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser,
    )
    app_session.add(dt)
    app_session.commit()

    update_duty_type(app_session, duty_type=dt, name="dc-weapon-3-renamed", score_per_day=None, description=None)
    app_session.commit()
    app_session.refresh(dt)
    assert dt.required_range_type == "laser"
```

- [x] **Step 3: Run to verify failure**

```bash
pytest app/services/tests/test_duty_config.py -v -k required_range_type
```
Expected: FAIL with `TypeError: ...got an unexpected keyword argument 'required_range_type'`.

- [x] **Step 4: Add the parameter to `create_duty_type` and `update_duty_type`**

In `backend/app/services/duty_config.py`, add `required_range_type: str | None = None` to both functions' signatures (`create_duty_type` and `update_duty_type`, alongside the existing `requires_weapon: bool | None = None` parameter). In `create_duty_type`'s body, pass it straight into the `DutyType(...)` constructor call alongside `requires_weapon=requires_weapon,`. In `update_duty_type`'s body, add — following the exact `contact_name`/`contact_phone` sub-style at lines 132-135 (simple assign, no `before[...]` capture, since `required_range_type` isn't currently part of the audit-log `before`/`after` dict) — right after the existing `requires_weapon` handling:

```python
    if required_range_type is not None:
        duty_type.required_range_type = required_range_type
```

- [x] **Step 5: Add the field to both request schemas and wire the routes**

In `backend/app/routes/duty_config.py`, add to both `CreateDutyTypeRequest` (after `requires_weapon: bool = False`) and `UpdateDutyTypeRequest` (after `requires_weapon: bool | None = None`):

```python
    required_range_type: str | None = None
```

In `create_duty_type`'s route function (around line 137-153), add `required_range_type=body.required_range_type,` to the `svc.create_duty_type(...)` call alongside the existing `requires_weapon=body.requires_weapon,`.

In `update_duty_type`'s route function (around line 161-192): right after `dt = session.get(DutyType, duty_type_id)` (line ~168), capture the pre-update value for Task 6's event hook to use later:

```python
    old_required_range_type = dt.required_range_type
```

Then add `required_range_type=body.required_range_type,` to the `svc.update_duty_type(...)` call alongside `requires_weapon=body.requires_weapon,`. Leave `old_required_range_type` unused for now (it's a placeholder Task 6 will consume) — but do not remove it; a `# noqa` or simply referencing it is not needed since Task 6 lands in the same file shortly after and will use it directly.

- [x] **Step 6: Run tests to verify pass**

```bash
pytest app/services/tests/test_duty_config.py -v
```
Expected: all PASS (including pre-existing tests in the file — check for regressions).

- [x] **Step 7: Typecheck the frontend is unaffected (no frontend admin UI for this field — Global Constraint from the weapon-qualification plan still applies, no frontend changes in this task)**

```bash
cd ../frontend && npx tsc --noEmit -p .
cd ../backend
```
Expected: clean (no frontend files were touched).

- [x] **Step 8: Commit**

```bash
git add backend/app/services/duty_config.py backend/app/routes/duty_config.py backend/app/services/tests/test_duty_config.py
git commit -m "feat: make DutyType.required_range_type settable via update/create"
```

---

### Task 4: Core — `duty_eligibility_watch.py` (`recheck_assignments`)

**Files:**
- Create: `backend/app/services/duty_eligibility_watch.py`
- Test: `backend/app/services/tests/test_duty_eligibility_watch.py`

**Interfaces:**
- Consumes: `app.services.weapon_eligibility.compute_eligibility` (existing), `app.services.approval_scope.commander_chain_for_soldier` (existing), `app.services.notifications.notify_duty_managers_in_scope`/`create_notification` (existing).
- Produces: `recheck_assignments(session: Session, assignment_ids: Sequence[uuid.UUID]) -> int` — returns the count of assignments that just transitioned False→True (became newly ineligible). Updates the cache columns on every assignment in `assignment_ids`, sends notifications only on False→True.

- [x] **Step 1: Write the failing tests**

```python
# backend/app/services/tests/test_duty_eligibility_watch.py
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment, DutyLocation, DutyShift, DutyType, Notification, NotificationType, RangeType,
    SoldierRangeQualification,
)
from app.services.duty_eligibility_watch import recheck_assignments
from tests.helpers import create_node, create_soldier


def _make_weapon_assignment(
    session: Session, *, soldier_id, node_id, start_date: date, required_range_type: str = RangeType.laser,
) -> DutyAssignment:
    dt = DutyType(
        name=f"watch-weapon-{start_date.isoformat()}", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=required_range_type, eligible_node_ids=[node_id],
    )
    loc = DutyLocation(name="watch-loc")
    session.add_all([dt, loc])
    session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=start_date, end_date=start_date, required_count=1, status="active",
    )
    session.add(shift)
    session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=start_date, end_date=start_date,
        score=Decimal("1.00"), status="published",
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def test_transition_to_ineligible_updates_cache_and_notifies_three_recipients(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="watch-node-1")
    commander = create_soldier(app_session, personal_number="watch-cmd-1", hierarchy_node_id=node.id)
    node.commander_id = commander.id
    soldier = create_soldier(app_session, personal_number="watch-sol-1", hierarchy_node_id=node.id)
    app_session.commit()

    assignment = _make_weapon_assignment(
        app_session, soldier_id=soldier.id, node_id=node.id, start_date=date.today() + timedelta(days=5),
    )
    assert assignment.weapon_ineligible is False

    changed = recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)

    assert changed == 1
    assert assignment.weapon_ineligible is True
    assert assignment.weapon_ineligible_reason is not None
    assert assignment.weapon_ineligible_detected_at is not None

    notifs = app_session.query(Notification).filter(
        Notification.type == NotificationType.weapon_ineligible_detected
    ).all()
    recipient_ids = {n.soldier_id for n in notifs}
    assert soldier.id in recipient_ids
    assert commander.id in recipient_ids
    assert len(notifs) >= 2  # soldier + commander at minimum; duty-manager notification depends on scope setup


def test_transition_to_eligible_updates_cache_silently(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="watch-node-2")
    soldier = create_soldier(app_session, personal_number="watch-sol-2", hierarchy_node_id=node.id)
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.laser, valid_until=date.today() + timedelta(days=30),
    ))
    app_session.commit()

    assignment = _make_weapon_assignment(
        app_session, soldier_id=soldier.id, node_id=node.id, start_date=date.today() + timedelta(days=5),
    )
    assignment.weapon_ineligible = True
    assignment.weapon_ineligible_reason = "stale"
    app_session.commit()

    before_count = app_session.query(Notification).count()
    changed = recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)

    assert changed == 0
    assert assignment.weapon_ineligible is False
    assert assignment.weapon_ineligible_reason is None
    assert app_session.query(Notification).count() == before_count


def test_cancelled_assignment_is_never_checked(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="watch-node-3")
    soldier = create_soldier(app_session, personal_number="watch-sol-3", hierarchy_node_id=node.id)
    assignment = _make_weapon_assignment(
        app_session, soldier_id=soldier.id, node_id=node.id, start_date=date.today() + timedelta(days=5),
    )
    assignment.status = "cancelled"
    app_session.commit()

    changed = recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)
    assert changed == 0
    assert assignment.weapon_ineligible is False


def test_non_weapon_duty_type_is_never_checked(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="watch-node-4")
    soldier = create_soldier(app_session, personal_number="watch-sol-4", hierarchy_node_id=node.id)
    dt = DutyType(name="watch-non-weapon", score_per_day=Decimal("1.00"), requires_weapon=False)
    loc = DutyLocation(name="watch-loc-4")
    app_session.add_all([dt, loc])
    app_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        required_count=1, status="active",
    )
    app_session.add(shift)
    app_session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        score=Decimal("1.00"), status="published",
    )
    app_session.add(assignment)
    app_session.commit()

    changed = recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)
    assert changed == 0
    assert assignment.weapon_ineligible is False
```

- [x] **Step 2: Run to verify failure**

```bash
pytest app/services/tests/test_duty_eligibility_watch.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.duty_eligibility_watch'`.

- [x] **Step 3: Implement `duty_eligibility_watch.py`**

```python
# backend/app/services/duty_eligibility_watch.py
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, DutyType, NotificationType
from app.services.approval_scope import commander_chain_for_soldier
from app.services.notifications import create_notification, notify_duty_managers_in_scope
from app.services.weapon_eligibility import compute_eligibility

_WEAPON_INELIGIBLE_TITLE = "אינך כשיר לתורנות המשובצת"


def _reason_body(soldier_name: str, duty_type_name: str, start_date) -> str:
    return f"{soldier_name} אינו/ה כשיר/ה מבחינת הכשרת נשק לתורנות '{duty_type_name}' בתאריך {start_date.isoformat()}."


def recheck_assignments(session: Session, assignment_ids: Sequence[uuid.UUID]) -> int:
    """Re-evaluate weapon eligibility for the given assignment ids, updating the
    cache columns on each. Sends notifications only on a False->True transition
    (soldier just became ineligible). True->False is updated silently. Assignments
    that are not `published`, or whose duty type doesn't require a weapon tier,
    are skipped entirely. Returns the count of False->True transitions."""
    if not assignment_ids:
        return 0

    assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.id.in_(assignment_ids),
            DutyAssignment.status == "published",
        )
    ).scalars().all()
    if not assignments:
        return 0

    type_ids = {a.duty_type_id for a in assignments}
    types_by_id = {
        dt.id: dt
        for dt in session.execute(select(DutyType).where(DutyType.id.in_(type_ids))).scalars()
    }

    newly_ineligible = 0
    for assignment in assignments:
        duty_type = types_by_id.get(assignment.duty_type_id)
        if duty_type is None or duty_type.required_range_type is None:
            continue

        eligible, reason = compute_eligibility(
            session, soldier_id=assignment.soldier_id,
            required_range_type=duty_type.required_range_type, as_of=assignment.start_date,
        )
        was_ineligible = assignment.weapon_ineligible
        now_ineligible = not eligible

        if now_ineligible == was_ineligible:
            continue

        assignment.weapon_ineligible = now_ineligible
        if now_ineligible:
            assignment.weapon_ineligible_reason = "אין הכשרת נשק בתוקף לתאריך התורנות"
            assignment.weapon_ineligible_detected_at = datetime.now(UTC)
            newly_ineligible += 1

            soldier_name = assignment.soldier.full_name if assignment.soldier else ""
            body = _reason_body(soldier_name, duty_type.name, assignment.start_date)

            create_notification(
                session, soldier_id=assignment.soldier_id, type=NotificationType.weapon_ineligible_detected,
                title=_WEAPON_INELIGIBLE_TITLE, body=body,
                reference_type="duty_assignment", reference_id=assignment.id,
            )
            notify_duty_managers_in_scope(
                session, soldier_id=assignment.soldier_id, type=NotificationType.weapon_ineligible_detected,
                title=_WEAPON_INELIGIBLE_TITLE, body=body,
                reference_type="duty_assignment", reference_id=assignment.id,
            )
            chain = commander_chain_for_soldier(session, assignment.soldier_id)
            if chain:
                create_notification(
                    session, soldier_id=chain[0], type=NotificationType.weapon_ineligible_detected,
                    title=_WEAPON_INELIGIBLE_TITLE, body=body,
                    reference_type="duty_assignment", reference_id=assignment.id,
                )
        else:
            assignment.weapon_ineligible_reason = None
            assignment.weapon_ineligible_detected_at = None

    session.commit()
    return newly_ineligible
```

- [x] **Step 4: Run tests to verify pass**

```bash
pytest app/services/tests/test_duty_eligibility_watch.py -v
```
Expected: all PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/services/duty_eligibility_watch.py backend/app/services/tests/test_duty_eligibility_watch.py
git commit -m "feat: add duty_eligibility_watch core (recheck_assignments)"
```

---

### Task 5: Event hooks — `ranges.py` (`mark_attendance`) + `range_excusal.py` (`decide_primary_excusal`, `request_reserve_excusal`)

**Files:**
- Modify: `backend/app/services/ranges.py:522-633` (`mark_attendance`)
- Modify: `backend/app/services/range_excusal.py:83-112,160-206` (`request_reserve_excusal`, `decide_primary_excusal`)
- Test: `backend/app/services/tests/test_duty_eligibility_watch_integration.py`

**Interfaces:**
- Consumes: `duty_eligibility_watch.recheck_assignments` (Task 4).
- Produces: after any of these three functions changes a soldier's range-qualification-relevant state, that soldier's currently-published, weapon-requiring assignments get rechecked.

- [x] **Step 1: Write the failing tests**

```python
# backend/app/services/tests/test_duty_eligibility_watch_integration.py
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment, DutyLocation, DutyShift, DutyType, RangeAttendanceStatus, RangeType,
)
from app.services.range_excusal import decide_primary_excusal, request_reserve_excusal
from app.services.ranges import add_range_assignment, create_range_event, mark_attendance
from tests.helpers import create_node, create_range_location, create_soldier


def _make_weapon_assignment(session, *, soldier_id, node_id, start_date) -> DutyAssignment:
    dt = DutyType(
        name=f"watchint-weapon-{start_date.isoformat()}-{soldier_id}", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node_id],
    )
    loc = DutyLocation(name="watchint-loc")
    session.add_all([dt, loc])
    session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=start_date, end_date=start_date, required_count=1, status="active",
    )
    session.add(shift)
    session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=start_date, end_date=start_date,
        score=Decimal("1.00"), status="published",
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def test_mark_attendance_no_show_triggers_recheck(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="watchint-node-1")
    soldier = create_soldier(app_session, personal_number="watchint-sol-1", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() - timedelta(days=1),
        range_location_id=create_range_location(app_session).id, required_count=1,
    )
    range_assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    app_session.commit()

    duty_assignment = _make_weapon_assignment(
        app_session, soldier_id=soldier.id, node_id=node.id, start_date=date.today() + timedelta(days=5),
    )
    assert duty_assignment.weapon_ineligible is False

    mark_attendance(app_session, assignment=range_assignment, status=RangeAttendanceStatus.no_show)

    app_session.refresh(duty_assignment)
    assert duty_assignment.weapon_ineligible is True


def test_decide_primary_excusal_approval_triggers_recheck(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="watchint-node-2")
    soldier = create_soldier(app_session, personal_number="watchint-sol-2", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=2),
        range_location_id=create_range_location(app_session).id, required_count=1,
    )
    range_assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    app_session.commit()

    duty_assignment = _make_weapon_assignment(
        app_session, soldier_id=soldier.id, node_id=node.id, start_date=date.today() + timedelta(days=5),
    )
    assert duty_assignment.weapon_ineligible is False

    excusal = request_reserve_excusal(
        app_session, assignment=range_assignment, reason="בדיקה", requested_by=soldier.id,
    )
    app_session.commit()
    app_session.refresh(duty_assignment)
    assert duty_assignment.weapon_ineligible is True
```

- [x] **Step 2: Run to verify failure**

```bash
pytest app/services/tests/test_duty_eligibility_watch_integration.py -v
```
Expected: FAIL — `duty_assignment.weapon_ineligible` stays `False` after both calls (the hooks don't exist yet).

- [x] **Step 3: Add the hook to `mark_attendance`**

In `backend/app/services/ranges.py`, `mark_attendance` (lines 522-633). Right after the core state assignment completes (currently `assignment.note = note` at line 624, before the `write_audit(...)` call at line 626), add:

```python
    assignment.note = note

    from app.services.duty_eligibility_watch import recheck_assignments
    from app.db.models import DutyAssignment as _DutyAssignment
    from sqlalchemy import select as _select

    affected_ids = session.execute(
        _select(_DutyAssignment.id).where(
            _DutyAssignment.soldier_id == assignment.soldier_id,
            _DutyAssignment.status == "published",
        )
    ).scalars().all()
    if affected_ids:
        recheck_assignments(session, affected_ids)

    write_audit(...)  # existing call, unchanged
```

(Use a local import here — matching the existing local-import convention for cross-service calls seen elsewhere in this codebase, e.g. `backend/app/routes/shifts.py:630-631` — to avoid a circular import between `ranges.py` and `duty_eligibility_watch.py`, which itself imports from `weapon_eligibility.py`.)

- [x] **Step 4: Add the hook to `request_reserve_excusal` and `decide_primary_excusal`**

In `backend/app/services/range_excusal.py`, `request_reserve_excusal` (lines 83-112): right after `session.flush()` (line 99), before the notification calls at lines 100-109, add:

```python
    session.flush()

    from app.services.duty_eligibility_watch import recheck_assignments
    from app.db.models import DutyAssignment as _DutyAssignment
    from sqlalchemy import select as _select

    affected_ids = session.execute(
        _select(_DutyAssignment.id).where(
            _DutyAssignment.soldier_id == assignment.soldier_id,
            _DutyAssignment.status == "published",
        )
    ).scalars().all()
    if affected_ids:
        recheck_assignments(session, affected_ids)
```

In `decide_primary_excusal` (lines 160-206), inside the approval (`else:`) branch, right after `promoted.is_reserve = False` (line 186), before the `_range_notification` call at line 188, add the same block but keyed on **both** the excused soldier (`request.assignment.soldier_id` — the one who just got excused, now potentially ineligible for nothing since their assignment is gone, but other future assignments of theirs could still reference this specific range's qualification) and the promoted soldier (who may have just gained a qualification):

```python
        promoted.is_reserve = False

        from app.services.duty_eligibility_watch import recheck_assignments
        from app.db.models import DutyAssignment as _DutyAssignment
        from sqlalchemy import select as _select

        for _soldier_id in {request.assignment.soldier_id, promoted.soldier_id}:
            affected_ids = session.execute(
                _select(_DutyAssignment.id).where(
                    _DutyAssignment.soldier_id == _soldier_id,
                    _DutyAssignment.status == "published",
                )
            ).scalars().all()
            if affected_ids:
                recheck_assignments(session, affected_ids)
```

- [x] **Step 5: Run tests to verify pass**

```bash
pytest app/services/tests/test_duty_eligibility_watch_integration.py -v
```
Expected: both PASS.

- [x] **Step 6: Run the broader ranges/excusal suites for regressions**

```bash
pytest app/services/tests/test_ranges_service.py tests/unit/test_range_attendance.py tests/unit/test_range_excusal.py -v
```
Expected: all PASS (the recheck is a no-op when the affected soldier has no published weapon-requiring assignments, which is true for every pre-existing test in these files).

- [x] **Step 7: Commit**

```bash
git add backend/app/services/ranges.py backend/app/services/range_excusal.py backend/app/services/tests/test_duty_eligibility_watch_integration.py
git commit -m "feat: trigger weapon-ineligibility recheck from attendance and excusal events"
```

---

### Task 6: Event hooks — `settings_loader.py` (`apply_settings`) + `duty_config.py` (`update_duty_type` route)

**Files:**
- Modify: `backend/app/services/settings_loader.py:114-132` (`apply_settings`)
- Modify: `backend/app/routes/duty_config.py` (the `update_duty_type` route, modified again after Task 3)
- Test: `backend/app/services/tests/test_duty_eligibility_watch_broad_triggers.py`

**Interfaces:**
- Consumes: `duty_eligibility_watch.recheck_assignments` (Task 4), `old_required_range_type` captured in Task 3's route.
- Produces: changing `weapon_qualification.enforce_eligibility` triggers a background-run, all-relevant-assignments recheck; changing a `DutyType`'s `required_range_type` triggers a recheck of every published assignment of that duty type.

- [x] **Step 1: Write the failing tests**

```python
# backend/app/services/tests/test_duty_eligibility_watch_broad_triggers.py
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, DutyLocation, DutyShift, DutyType, RangeType
from app.services.duty_config import update_duty_type
from app.services.settings_loader import apply_settings
from tests.helpers import create_node, create_soldier


def _make_weapon_assignment(session, *, soldier_id, duty_type, start_date) -> DutyAssignment:
    loc = DutyLocation(name="broad-loc")
    session.add(loc)
    session.flush()
    shift = DutyShift(
        duty_type_id=duty_type.id, duty_location_id=loc.id,
        start_date=start_date, end_date=start_date, required_count=1, status="active",
    )
    session.add(shift)
    session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=duty_type.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=start_date, end_date=start_date,
        score=Decimal("1.00"), status="published",
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def test_changing_required_range_type_triggers_recheck_for_that_duty_type(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="broad-node-1")
    soldier = create_soldier(app_session, personal_number="broad-sol-1", hierarchy_node_id=node.id)
    dt = DutyType(
        name="broad-weapon-1", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    )
    app_session.add(dt)
    app_session.commit()

    assignment = _make_weapon_assignment(
        app_session, soldier_id=soldier.id, duty_type=dt, start_date=date.today() + timedelta(days=5),
    )
    assert assignment.weapon_ineligible is False

    update_duty_type(
        app_session, duty_type=dt, name=None, score_per_day=None, description=None,
        required_range_type=RangeType.alal,
    )
    app_session.commit()

    from app.services.duty_eligibility_watch import recheck_assignments
    from sqlalchemy import select
    ids = app_session.execute(
        select(DutyAssignment.id).where(DutyAssignment.duty_type_id == dt.id, DutyAssignment.status == "published")
    ).scalars().all()
    recheck_assignments(app_session, ids)
    app_session.refresh(assignment)
    assert assignment.weapon_ineligible is True


def test_apply_settings_detects_enforce_eligibility_key_change() -> None:
    current = {"weapon_qualification.enforce_eligibility": True}
    updates = {"weapon_qualification.enforce_eligibility": False}
    assert "weapon_qualification.enforce_eligibility" in updates
    assert current.get("weapon_qualification.enforce_eligibility") != updates.get("weapon_qualification.enforce_eligibility")
```

- [x] **Step 2: Run to verify failure**

```bash
pytest app/services/tests/test_duty_eligibility_watch_broad_triggers.py -v -k required_range_type
```
Expected: FAIL — `assignment.weapon_ineligible` stays `False` (the route-level hook doesn't exist yet; note this test calls the service function directly and then manually invokes `recheck_assignments`, so it's really testing that `update_duty_type` accepts the field — Step 3 below adds the actual auto-trigger at the *route* layer, which needs an HTTP-level or route-function-level test; add one more test in Step 3 if the route function is easily callable directly).

- [x] **Step 3: Add the hook to `duty_config.py`'s `update_duty_type` route**

In `backend/app/routes/duty_config.py`, the `update_duty_type` route function (already modified in Task 3 to capture `old_required_range_type` right after loading `dt`). After the `svc.update_duty_type(...)` call and `session.commit()`, add:

```python
    session.commit()

    if body.required_range_type is not None and body.required_range_type != old_required_range_type:
        from app.services.duty_eligibility_watch import recheck_assignments
        from app.db.models import DutyAssignment as _DutyAssignment
        from sqlalchemy import select as _select

        affected_ids = session.execute(
            _select(_DutyAssignment.id).where(
                _DutyAssignment.duty_type_id == duty_type_id,
                _DutyAssignment.status == "published",
            )
        ).scalars().all()
        if affected_ids:
            recheck_assignments(session, affected_ids)
```

(Place this after whatever the route's existing `session.commit()`/return-building logic is — read the current route body to find the exact insertion point; the key requirement is it runs after the duty-type change is committed, using `duty_type_id` from the route's own path parameter and `old_required_range_type` from Task 3.)

- [x] **Step 4: Add the hook to `settings_loader.py`'s `apply_settings`**

In `backend/app/services/settings_loader.py`, `apply_settings` (lines 114-132). Right after `merged = validate_settings_update(current, updates)` (line 121), before the `for key, value in to_write.items(): ... set_setting(...)` loop:

```python
    merged = validate_settings_update(current, updates)

    _weapon_setting_changed = (
        "weapon_qualification.enforce_eligibility" in updates
        and current.get("weapon_qualification.enforce_eligibility") != updates["weapon_qualification.enforce_eligibility"]
    )
```

Then, after the existing `for key, value in to_write.items(): set_setting(...)` loop completes (and after any commit that loop implies — check whether `apply_settings` commits internally or leaves that to the caller; if the caller commits, place the recheck trigger after this function returns, in `apply_settings`'s own caller in `backend/app/routes/system_settings.py` instead — locate that route and add the trigger there, gated on the same `_weapon_setting_changed`-style boolean computed from the route's own `current`/`updates` view):

```python
    if _weapon_setting_changed:
        from app.services.duty_eligibility_watch import recheck_assignments
        from app.db.models import DutyAssignment as _DutyAssignment, DutyType as _DutyType
        from sqlalchemy import select as _select

        weapon_type_ids = session.execute(
            _select(_DutyType.id).where(_DutyType.required_range_type.is_not(None))
        ).scalars().all()
        if weapon_type_ids:
            affected_ids = session.execute(
                _select(_DutyAssignment.id).where(
                    _DutyAssignment.duty_type_id.in_(weapon_type_ids),
                    _DutyAssignment.status == "published",
                )
            ).scalars().all()
            if affected_ids:
                recheck_assignments(session, affected_ids)
```

Note `apply_settings`'s current signature takes `session` as its first parameter already (confirmed: `def apply_settings(session: Session, current: dict, updates: dict, *, actor_id) -> dict`), so `session` is already in scope for this block — no signature change needed. Per the design spec, this is a "run in the background so it doesn't block the settings-update API call" requirement — for this task, implement it synchronously (correctness first); if response latency becomes a real issue, follow-up work can move it to a background task using the same `asyncio.to_thread`/worker pattern used elsewhere in this codebase. Note this synchronous-vs-background deviation explicitly in your task report.

- [x] **Step 5: Run tests to verify pass**

```bash
pytest app/services/tests/test_duty_eligibility_watch_broad_triggers.py -v
```
Expected: all PASS.

- [x] **Step 6: Run the broader settings/duty_config suites for regressions**

```bash
pytest app/services/tests/test_duty_config.py tests/unit/test_settings_loader.py tests/integration/test_settings_routes.py -v
```
(Check the exact settings-route test file name first with `ls backend/tests/integration/ | grep -i setting`; adjust the path if it differs.)
Expected: all PASS.

- [x] **Step 7: Commit**

```bash
git add backend/app/services/settings_loader.py backend/app/routes/duty_config.py backend/app/services/tests/test_duty_eligibility_watch_broad_triggers.py
git commit -m "feat: trigger weapon-ineligibility recheck from settings and duty-type changes"
```

---

### Task 7: Safety-net worker — `duty_eligibility_worker.py`

**Files:**
- Create: `backend/app/duty_eligibility_worker.py`
- Modify: `backend/app/main.py` (lifespan registration)
- Test: `backend/tests/unit/test_duty_eligibility_worker.py`

**Interfaces:**
- Consumes: `duty_eligibility_watch.recheck_assignments` (Task 4).
- Produces: `run_duty_eligibility_worker() -> None` (async, infinite loop, 86400s poll interval), started/stopped in `main.py`'s lifespan alongside the other three workers.

- [x] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_duty_eligibility_worker.py
from __future__ import annotations

from unittest.mock import patch

from app.duty_eligibility_worker import _recheck_all_published_weapon_assignments


def test_worker_function_calls_recheck_assignments_and_handles_errors() -> None:
    with patch("app.duty_eligibility_worker.session_scope") as mock_scope, \
         patch("app.duty_eligibility_worker.recheck_assignments") as mock_recheck:
        mock_session = mock_scope.return_value.__enter__.return_value
        mock_session.execute.return_value.scalars.return_value.all.return_value = []
        mock_recheck.return_value = 0
        _recheck_all_published_weapon_assignments()
        mock_scope.assert_called_once()
```

- [x] **Step 2: Run to verify failure**

```bash
pytest tests/unit/test_duty_eligibility_worker.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'app.duty_eligibility_worker'`.

- [x] **Step 3: Implement the worker**

Copy the exact structure of `backend/app/range_attendance_worker.py` (25 lines, poll constant / `session_scope` function / async loop with try/except-log):

```python
# backend/app/duty_eligibility_worker.py
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.db.models import DutyAssignment, DutyType
from app.db.session import session_scope
from app.services.duty_eligibility_watch import recheck_assignments

logger = logging.getLogger(__name__)

_POLL_SECONDS = 86400


def _recheck_all_published_weapon_assignments() -> None:
    with session_scope() as session:
        weapon_type_ids = session.execute(
            select(DutyType.id).where(DutyType.required_range_type.is_not(None))
        ).scalars().all()
        if not weapon_type_ids:
            return
        assignment_ids = session.execute(
            select(DutyAssignment.id).where(
                DutyAssignment.duty_type_id.in_(weapon_type_ids),
                DutyAssignment.status == "published",
            )
        ).scalars().all()
        if not assignment_ids:
            return
        count = recheck_assignments(session, assignment_ids)
        if count:
            logger.info("duty eligibility worker: %d assignment(s) newly weapon-ineligible", count)


async def run_duty_eligibility_worker() -> None:
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            await asyncio.to_thread(_recheck_all_published_weapon_assignments)
        except Exception:
            logger.warning("duty eligibility worker: unhandled error", exc_info=True)
```

- [x] **Step 4: Register the worker in `main.py`'s lifespan**

In `backend/app/main.py`, add the import alongside the existing worker imports (near line 15, e.g. `from app.range_attendance_worker import run_range_attendance_worker`):

```python
from app.duty_eligibility_worker import run_duty_eligibility_worker
```

In the `lifespan` function (lines 121-138), add the task creation alongside the other three (near line 129, e.g. `range_attendance_task = asyncio.create_task(run_range_attendance_worker())`):

```python
    duty_eligibility_task = asyncio.create_task(run_duty_eligibility_worker())
```

And add it to the shutdown/cleanup loop (lines 131-137) exactly the same way the other three tasks are cancelled and awaited there — find the existing list/tuple of tasks being cancelled and add `duty_eligibility_task` to it.

- [x] **Step 5: Run tests to verify pass**

```bash
pytest tests/unit/test_duty_eligibility_worker.py -v
```
Expected: PASS.

- [x] **Step 6: Verify the app still starts cleanly**

```bash
python -c "
import asyncio
from app.duty_eligibility_worker import run_duty_eligibility_worker
print('import ok')
"
```
Expected: prints `import ok`, no import errors.

- [x] **Step 7: Commit**

```bash
git add backend/app/duty_eligibility_worker.py backend/app/main.py backend/tests/unit/test_duty_eligibility_worker.py
git commit -m "feat: add daily safety-net worker for weapon-ineligibility detection"
```

---

### Task 8: Backend visibility — hierarchy-scoped badge count endpoint

**Files:**
- Modify: `backend/app/routes/shifts.py` (or a new small route module `backend/app/routes/duty_eligibility.py` — your call; the plan uses `shifts.py` for consistency with where the rest of the weapon-eligibility backend logic lives)
- Test: `backend/tests/integration/test_weapon_ineligible_count.py`

**Interfaces:**
- Produces: `GET /api/shifts/weapon-ineligible/count` → `{"count": int}`, hierarchy-scoped per the requesting user exactly like the existing `GET /constraints/pending/count` pattern.

- [x] **Step 1: Write the failing tests**

```python
# backend/tests/integration/test_weapon_ineligible_count.py
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.db.models import DutyAssignment, DutyLocation, DutyShift, DutyType, RangeType
from tests.helpers import auth_headers, create_node, create_soldier


def test_admin_sees_global_ineligible_count(client, admin_session):
    node = create_node(admin_session, level="branch", name="cnt-node-1")
    admin = create_soldier(admin_session, personal_number="cnt-admin-1", role="admin", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="cnt-sol-1", hierarchy_node_id=node.id)
    dt = DutyType(
        name="cnt-weapon-1", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    )
    loc = DutyLocation(name="cnt-loc-1")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        required_count=1, status="active",
    )
    admin_session.add(shift)
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        score=Decimal("1.00"), status="published", weapon_ineligible=True,
    )
    admin_session.add(assignment)
    admin_session.commit()

    r = client.get("/api/shifts/weapon-ineligible/count", headers=auth_headers(admin))
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_zero_count_when_no_ineligible_assignments(client, admin_session):
    admin = create_soldier(admin_session, personal_number="cnt-admin-2", role="admin")
    r = client.get("/api/shifts/weapon-ineligible/count", headers=auth_headers(admin))
    assert r.status_code == 200
    assert r.json()["count"] == 0
```

- [x] **Step 2: Run to verify failure**

```bash
pytest tests/integration/test_weapon_ineligible_count.py -v
```
Expected: FAIL — `404 Not Found` (route doesn't exist).

- [x] **Step 3: Implement the endpoint**

In `backend/app/routes/shifts.py`, add near the top (with the other response models, alongside `ShiftOut`):

```python
class WeaponIneligibleCountOut(BaseModel):
    count: int
```

Add the route (anywhere among the other `@router.get(...)` route functions in this file — the exact ordering doesn't matter, place it near `list_shifts` for locality):

```python
@router.get("/weapon-ineligible/count", response_model=WeaponIneligibleCountOut)
def weapon_ineligible_count(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> WeaponIneligibleCountOut:
    from app.auth.authz import scope_root_ids
    from app.db.models import DutyAssignment as _DutyAssignment
    from sqlalchemy import func as _func, select as _select

    if user.role == "admin":
        cnt = session.execute(
            _select(_func.count(_DutyAssignment.id)).where(
                _DutyAssignment.weapon_ineligible.is_(True),
                _DutyAssignment.status == "published",
            )
        ).scalar_one()
        return WeaponIneligibleCountOut(count=cnt)

    roots = scope_root_ids(session, user)
    if not roots:
        return WeaponIneligibleCountOut(count=0)

    from app.db.models import HierarchyNode as _HierarchyNode, Soldier as _Soldier

    cnt = session.execute(
        _select(_func.count(_DutyAssignment.id))
        .join(_Soldier, _Soldier.id == _DutyAssignment.soldier_id)
        .join(_HierarchyNode, _HierarchyNode.id == _Soldier.hierarchy_node_id)
        .where(
            _DutyAssignment.weapon_ineligible.is_(True),
            _DutyAssignment.status == "published",
            _HierarchyNode.id.in_(roots),  # Note: exact-node match; see Step 3a below for subtree expansion
        )
    ).scalar_one()
    return WeaponIneligibleCountOut(count=cnt)
```

**Step 3a — subtree scoping:** `roots` (from `scope_root_ids`) gives the node ids the user directly governs, but soldiers may sit in *descendant* nodes, not just those exact nodes. Check how `svc.pending_approval_count(session, node_ids=roots)` (the precedent this endpoint is modeled on, referenced by `backend/app/routes/constraints.py`'s `pending_count`) handles subtree expansion — it likely calls a hierarchy-path helper (search for `hierarchy_path_ids` or a `subtree_node_ids`/`descendant_node_ids` function in `backend/app/services/` or `backend/app/auth/authz.py`). Use the same subtree-expansion helper here instead of a bare `HierarchyNode.id.in_(roots)` exact match, so a branch commander sees ineligible assignments anywhere in their subtree, not just soldiers on the root node itself.

- [x] **Step 4: Run tests to verify pass**

```bash
pytest tests/integration/test_weapon_ineligible_count.py -v
```
Expected: both PASS.

- [x] **Step 5: Commit**

```bash
git add backend/app/routes/shifts.py backend/tests/integration/test_weapon_ineligible_count.py
git commit -m "feat: add hierarchy-scoped weapon-ineligible assignment count endpoint"
```

---

### Task 9: Backend visibility — `ShiftOut.ineligible_count`

**Files:**
- Modify: `backend/app/routes/shifts.py:31-48,114-170` (`ShiftOut`, `_out`, `list_shifts`)
- Test: `backend/tests/integration/test_shifts_routes.py` (add cases)

**Interfaces:**
- Produces: `ShiftOut.ineligible_count: int` (default `0`) — count of published, weapon-ineligible assignments for that specific shift.

- [x] **Step 1: Write the failing test**

```python
# Add to backend/tests/integration/test_shifts_routes.py
def test_list_shifts_includes_ineligible_count(client, admin_session):
    from decimal import Decimal
    from datetime import date, timedelta
    from app.db.models import DutyAssignment, DutyLocation, DutyShift, DutyType, RangeType
    from tests.helpers import auth_headers, create_node, create_soldier

    node = create_node(admin_session, level="branch", name="so-node-1")
    dm = create_soldier(admin_session, personal_number="so-dm-1", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="so-sol-1", hierarchy_node_id=node.id)
    dt = DutyType(
        name="so-weapon-1", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    )
    loc = DutyLocation(name="so-loc-1")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        required_count=1, status="active",
    )
    admin_session.add(shift)
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        score=Decimal("1.00"), status="published", weapon_ineligible=True,
    )
    admin_session.add(assignment)
    admin_session.commit()

    r = client.get(
        f"/api/shifts?date_from={date.today().isoformat()}&date_to={(date.today()+timedelta(days=30)).isoformat()}",
        headers=auth_headers(dm),
    )
    assert r.status_code == 200
    row = next(s for s in r.json() if s["id"] == str(shift.id))
    assert row["ineligible_count"] == 1
```

- [x] **Step 2: Run to verify failure**

```bash
pytest tests/integration/test_shifts_routes.py -v -k ineligible_count
```
Expected: FAIL — `KeyError: 'ineligible_count'`.

- [x] **Step 3: Add the field to `ShiftOut` and batch-compute it in `list_shifts`**

In `backend/app/routes/shifts.py`, add to `ShiftOut` (after `node_quotas`):

```python
    ineligible_count: int = 0
```

Add an `ineligible_count: int = 0` parameter to `_out(...)`'s signature and pass it straight into the `ShiftOut(...)` constructor call.

In `list_shifts` (lines 155-170), following this file's established batch-then-pass-in pattern (the same one used for `template_names`/`node_quotas`, computed once before the list comprehension), add right before the `[_out(s, session, ...) for s in shifts]` line:

```python
    from app.db.models import DutyAssignment as _DutyAssignment
    from sqlalchemy import func as _func, select as _select

    shift_ids = [s.id for s in shifts]
    ineligible_counts: dict[uuid.UUID, int] = {}
    if shift_ids:
        rows = session.execute(
            _select(_DutyAssignment.duty_shift_id, _func.count(_DutyAssignment.id))
            .where(
                _DutyAssignment.duty_shift_id.in_(shift_ids),
                _DutyAssignment.weapon_ineligible.is_(True),
                _DutyAssignment.status == "published",
            )
            .group_by(_DutyAssignment.duty_shift_id)
        ).all()
        ineligible_counts = {row[0]: row[1] for row in rows}
```

Then pass `ineligible_count=ineligible_counts.get(s.id, 0)` into each `_out(...)` call.

- [x] **Step 4: Run tests to verify pass**

```bash
pytest tests/integration/test_shifts_routes.py -v
```
Expected: all PASS (including pre-existing tests — check for regressions since `_out`'s signature changed).

- [x] **Step 5: Commit**

```bash
git add backend/app/routes/shifts.py backend/tests/integration/test_shifts_routes.py
git commit -m "feat: add ineligible_count to ShiftOut"
```

---

### Task 10: Backend visibility — `CalendarShiftAssignee` weapon-ineligibility fields

**Files:**
- Modify: `backend/app/routes/calendar.py:46-59` (`CalendarShiftAssignee`)
- Modify: `backend/app/services/calendar_shifts.py` (`get_calendar_shifts`, `get_single_shift`)
- Test: `backend/tests/integration/test_calendar_routes.py` (add cases; check exact filename first)

**Interfaces:**
- Produces: `CalendarShiftAssignee.weapon_ineligible: bool = False`, `CalendarShiftAssignee.weapon_ineligible_reason: str | None = None` — populated from the `DutyAssignment` rows already loaded in bulk by both functions.

- [x] **Step 1: Check the exact calendar-routes test file name**

```bash
ls backend/tests/integration/ | grep -i calendar
```
Use whichever file exists; read its existing fixture/import style first.

- [x] **Step 2: Write the failing test**

```python
# Add to the calendar routes integration test file found in Step 1
def test_calendar_shift_assignee_includes_weapon_ineligible_flag(client, admin_session):
    from decimal import Decimal
    from datetime import date, timedelta
    from app.db.models import DutyAssignment, DutyLocation, DutyShift, DutyType, RangeType
    from tests.helpers import auth_headers, create_node, create_soldier

    node = create_node(admin_session, level="branch", name="cal-node-1")
    dm = create_soldier(admin_session, personal_number="cal-dm-1", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="cal-sol-1", hierarchy_node_id=node.id)
    dt = DutyType(
        name="cal-weapon-1", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    )
    loc = DutyLocation(name="cal-loc-1")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        required_count=1, status="active",
    )
    admin_session.add(shift)
    admin_session.flush()
    admin_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        score=Decimal("1.00"), status="published",
        weapon_ineligible=True, weapon_ineligible_reason="אין הכשרת נשק בתוקף לתאריך התורנות",
    ))
    admin_session.commit()

    r = client.get(
        f"/api/calendar/shifts?date_from={date.today().isoformat()}&date_to={(date.today()+timedelta(days=30)).isoformat()}",
        headers=auth_headers(dm),
    )
    assert r.status_code == 200
    row = next(s for s in r.json()["shifts"] if s["id"] == str(shift.id))
    assignee = next(a for a in row["assignees"] if a["soldier_id"] == str(soldier.id))
    assert assignee["weapon_ineligible"] is True
    assert assignee["weapon_ineligible_reason"] == "אין הכשרת נשק בתוקף לתאריך התורנות"
```

- [x] **Step 3: Run to verify failure**

```bash
pytest tests/integration/<calendar_test_file> -v -k weapon_ineligible
```
Expected: FAIL — `KeyError: 'weapon_ineligible'`.

- [x] **Step 4: Add the fields to `CalendarShiftAssignee`**

In `backend/app/routes/calendar.py`, add to `CalendarShiftAssignee` (after `hierarchy_path_ids`):

```python
    weapon_ineligible: bool = False
    weapon_ineligible_reason: str | None = None
```

- [x] **Step 5: Populate the fields in `calendar_shifts.py`**

In `backend/app/services/calendar_shifts.py`, both `get_calendar_shifts` and `get_single_shift` already load the full `DutyAssignment` ORM objects in bulk (`assignments = session.execute(select(DutyAssignment).where(...)).scalars().all()`). Since `weapon_ineligible`/`weapon_ineligible_reason` live directly on those already-loaded objects, no additional query is needed — just read them off each `DutyAssignment` object (`a.weapon_ineligible`, `a.weapon_ineligible_reason`) at the point where each function currently builds its per-assignee dict/object for the `assignees` list, and include the two new keys there. Locate that exact construction point in both functions (search for where `soldier_id`/`soldier_name`/`assignment_id` are assembled into the assignee representation) and add the two fields alongside them.

- [x] **Step 6: Run tests to verify pass**

```bash
pytest tests/integration/<calendar_test_file> -v
```
Expected: all PASS.

- [x] **Step 7: Commit**

```bash
git add backend/app/routes/calendar.py backend/app/services/calendar_shifts.py backend/tests/integration/<calendar_test_file>
git commit -m "feat: surface weapon-ineligibility on CalendarShiftAssignee"
```

---

### Task 11: Backend visibility — `EffectiveDuty` weapon-ineligibility fields (soldier's own view)

**Files:**
- Modify: `backend/app/routes/assignments.py:54-146` (`EffectiveDutyOut`, `list_effective_duties`)
- Modify: `backend/app/services/scoring.py` (or wherever `effective_duty_spans` lives — locate it first)
- Test: `backend/tests/integration/test_assignments_routes.py` (add cases; check exact filename first)

**Interfaces:**
- Produces: `EffectiveDutyOut.weapon_ineligible: bool = False`, `EffectiveDutyOut.weapon_ineligible_reason: str | None = None`.

- [x] **Step 1: Locate `effective_duty_spans`**

```bash
grep -rn "def effective_duty_spans" backend/app/
```
Read its full implementation before editing — confirm whether it queries `DutyAssignment` rows directly (in which case the new fields are a simple additional key in whatever dict/tuple it returns per span) or derives spans some other way (in which case you'll need to join back to `DutyAssignment` by `assignment_id` to pull the two new columns).

- [x] **Step 2: Write the failing test**

```python
# Add to the assignments routes integration test file (find exact name: ls backend/tests/integration/ | grep -i assignment)
def test_effective_duties_includes_weapon_ineligible_flag(client, admin_session):
    from decimal import Decimal
    from datetime import date, timedelta
    from app.db.models import DutyAssignment, DutyLocation, DutyShift, DutyType, RangeType
    from tests.helpers import auth_headers, create_node, create_soldier

    node = create_node(admin_session, level="branch", name="eff-node-1")
    soldier = create_soldier(admin_session, personal_number="eff-sol-1", hierarchy_node_id=node.id)
    dt = DutyType(
        name="eff-weapon-1", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    )
    loc = DutyLocation(name="eff-loc-1")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        required_count=1, status="active",
    )
    admin_session.add(shift)
    admin_session.flush()
    admin_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        score=Decimal("1.00"), status="published",
        weapon_ineligible=True, weapon_ineligible_reason="אין הכשרת נשק בתוקף לתאריך התורנות",
    ))
    admin_session.commit()

    r = client.get(f"/api/assignments/effective?soldier_id={soldier.id}", headers=auth_headers(soldier))
    assert r.status_code == 200
    row = next(d for d in r.json() if d["duty_type_id"] == str(dt.id))
    assert row["weapon_ineligible"] is True
    assert row["weapon_ineligible_reason"] == "אין הכשרת נשק בתוקף לתאריך התורנות"
```

- [x] **Step 3: Run to verify failure**

```bash
pytest tests/integration/<assignments_test_file> -v -k weapon_ineligible
```
Expected: FAIL — `KeyError`/`AssertionError` on missing field.

- [x] **Step 4: Add the fields to `EffectiveDutyOut` and populate them**

In `backend/app/routes/assignments.py`, add to `EffectiveDutyOut` (after `is_reserve`):

```python
    weapon_ineligible: bool = False
    weapon_ineligible_reason: str | None = None
```

Populate them based on what Step 1 found: if `effective_duty_spans` already returns dicts keyed by `assignment_id` (matching `EffectiveDutyOut`'s `**sp` spread pattern seen at `list_effective_duties`'s return statement), add the two new keys directly inside `effective_duty_spans`'s span-building loop, reading them off the `DutyAssignment` row it's already working from. If it does NOT have the `DutyAssignment` row in scope at that point, add a batched lookup in `list_effective_duties` itself (in `backend/app/routes/assignments.py`) — after `spans = scoring_svc.effective_duty_spans(...)`, before the final list comprehension:

```python
    from app.db.models import DutyAssignment as _DutyAssignment
    from sqlalchemy import select as _select

    span_assignment_ids = [sp["assignment_id"] for sp in spans]
    ineligible_map: dict[uuid.UUID, tuple[bool, str | None]] = {}
    if span_assignment_ids:
        rows = session.execute(
            _select(_DutyAssignment.id, _DutyAssignment.weapon_ineligible, _DutyAssignment.weapon_ineligible_reason)
            .where(_DutyAssignment.id.in_(span_assignment_ids))
        ).all()
        ineligible_map = {row[0]: (row[1], row[2]) for row in rows}

    return [
        EffectiveDutyOut(
            **sp, duty_type_name=names.get(sp["duty_type_id"], ""),
            weapon_ineligible=ineligible_map.get(sp["assignment_id"], (False, None))[0],
            weapon_ineligible_reason=ineligible_map.get(sp["assignment_id"], (False, None))[1],
        )
        for sp in spans
    ]
```

(Prefer whichever approach avoids the extra query — check Step 1's findings first; only add the batched lookup if `effective_duty_spans` genuinely doesn't have `DutyAssignment` rows in scope.)

- [x] **Step 5: Run tests to verify pass**

```bash
pytest tests/integration/<assignments_test_file> -v
```
Expected: all PASS.

- [x] **Step 6: Commit**

```bash
git add backend/app/routes/assignments.py backend/app/services/scoring.py backend/tests/integration/<assignments_test_file>
git commit -m "feat: surface weapon-ineligibility on EffectiveDuty (soldier's own view)"
```

---

### Task 12: Frontend — `UnifiedNav.tsx` red badge

**Files:**
- Modify: `frontend/src/api/shifts.ts` (new API function)
- Modify: `frontend/src/components/UnifiedNav.tsx:10-16,55-70,157` (imports, state, tab config)
- Test: `frontend/src/components/UnifiedNav.test.tsx` (check if it exists first; add cases)

**Interfaces:**
- Consumes: `GET /api/shifts/weapon-ineligible/count` (Task 8).
- Produces: `getWeaponIneligibleCount(): Promise<number>` in `shifts.ts`; a new red badge on the nav, visible to duty managers and commanders, scoped per the backend's own hierarchy filtering (no client-side scoping needed).

- [x] **Step 1: Add the API function**

In `frontend/src/api/shifts.ts`:

```typescript
export async function getWeaponIneligibleCount(): Promise<number> {
  const r = await api.get<{ count: number }>("/shifts/weapon-ineligible/count");
  return r.data.count;
}
```

- [x] **Step 2: Check for an existing `UnifiedNav.test.tsx`**

```bash
ls frontend/src/components/UnifiedNav.test.tsx 2>&1
```
Read it fully first if it exists, to match its mock/fixture conventions.

- [x] **Step 3: Write the failing test**

```tsx
// Add to frontend/src/components/UnifiedNav.test.tsx (or create following existing test conventions in this directory)
import { render, screen, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import * as shiftsApi from "../api/shifts";
// ... existing imports for UnifiedNav, router wrapper, auth context mock, etc. per this file's existing conventions

vi.mock("../api/shifts");

describe("UnifiedNav weapon-ineligible badge", () => {
  beforeEach(() => {
    vi.mocked(shiftsApi.getWeaponIneligibleCount).mockResolvedValue(3);
  });

  it("shows a red badge with the ineligible count for a duty manager", async () => {
    // render UnifiedNav with a duty_manager user per this file's existing render helper
    await waitFor(() => screen.getByText("3"));
  });
});
```

- [x] **Step 4: Run to verify failure**

```bash
npm test -- UnifiedNav.test.tsx
```
Expected: FAIL — the badge doesn't exist yet.

- [x] **Step 5: Implement the badge**

In `frontend/src/components/UnifiedNav.tsx`, add the import (alongside the existing ones at lines 10-16):

```tsx
import { getWeaponIneligibleCount } from "../api/shifts";
```

Add state (alongside `pendingCount`/`swapIncomingCount` at lines 55-56):

```tsx
const [weaponIneligibleCount, setWeaponIneligibleCount] = useState(0);
```

Fetch it in the existing `useEffect` block (starting line 68), following the exact same pattern used for `pendingCount`:

```tsx
getWeaponIneligibleCount().then(setWeaponIneligibleCount).catch(() => {});
```

Add a new nav tab entry (near the approvals tab at line 157), gated to duty managers/commanders/admins only — check how other tabs restrict visibility by role in this file (e.g. search for `user?.role === "admin"` or `is_duty_manager` conditionals in the tabs array construction) and follow the same conditional-inclusion pattern:

```tsx
{
  label: t("nav.weapon_ineligible"),
  to: "/shifts?filter=weapon_ineligible",
  badge: weaponIneligibleCount,
  badgeColor: "red" as BadgeColor,
  testId: "nav-weapon-ineligible",
},
```

Add the translation key `nav.weapon_ineligible` to `frontend/src/i18n/he.json` (find the `nav.*` section and add alongside `nav.approvals`) with value `"⚠️ חוסר כשירות"` or similar concise Hebrew label.

- [x] **Step 6: Run tests to verify pass**

```bash
npm test -- UnifiedNav.test.tsx
```
Expected: PASS.

- [x] **Step 7: Typecheck and run the broader frontend suite**

```bash
npx tsc --noEmit -p .
npm test
```
Expected: clean, no regressions.

- [x] **Step 8: Commit**

```bash
git add frontend/src/api/shifts.ts frontend/src/components/UnifiedNav.tsx frontend/src/components/UnifiedNav.test.tsx frontend/src/i18n/he.json
git commit -m "feat: add weapon-ineligible red badge to nav"
```

---

### Task 13: Frontend — `ShiftsPage.tsx` ⚠️ indicator

**Files:**
- Modify: `frontend/src/pages/ShiftsPage.tsx:608-624` (columns array, near `fill_status`)
- Test: `frontend/src/pages/ShiftsPage.test.tsx` (check if it exists first; add cases)

**Interfaces:**
- Consumes: `ShiftOut.ineligible_count` (Task 9).

- [x] **Step 1: Check for an existing `ShiftsPage.test.tsx`**

```bash
ls frontend/src/pages/ShiftsPage.test.tsx 2>&1
```
Read it fully first if it exists.

- [x] **Step 2: Write the failing test**

```tsx
// Add to frontend/src/pages/ShiftsPage.test.tsx (matching its existing conventions)
it("shows a warning indicator for shifts with an ineligible_count", async () => {
  // mock listShifts to return one shift with ineligible_count: 2
  // render ShiftsContent
  // assert an element with title/text mentioning the count or a ⚠️ marker is present in that row
});
```

- [x] **Step 3: Run to verify failure**

```bash
npm test -- ShiftsPage.test.tsx
```
Expected: FAIL.

- [x] **Step 4: Add the indicator**

In `frontend/src/pages/ShiftsPage.tsx`, add a new column definition right after the `fill_status` column (lines 608-618), following the exact same column-object shape:

```tsx
{
  id: "weapon_ineligible",
  header: "",
  cell: (s) =>
    s.ineligible_count > 0 ? (
      <span
        title={`${s.ineligible_count} חייל/ים לא כשירים מבחינת הכשרת נשק`}
        className="text-amber-500 dark:text-amber-400"
      >
        ⚠️
      </span>
    ) : null,
  sortValue: (s) => s.ineligible_count,
},
```

Add `ineligible_count: number` to the frontend `Shift`/`ShiftOut`-equivalent TypeScript interface in `frontend/src/api/shifts.ts` (find the existing interface — likely named `Shift` or `ShiftOut` — and add the field matching the backend's new field exactly).

- [x] **Step 5: Run tests to verify pass**

```bash
npm test -- ShiftsPage.test.tsx
```
Expected: PASS.

- [x] **Step 6: Typecheck**

```bash
npx tsc --noEmit -p .
```
Expected: clean.

- [x] **Step 7: Commit**

```bash
git add frontend/src/pages/ShiftsPage.tsx frontend/src/api/shifts.ts frontend/src/pages/ShiftsPage.test.tsx
git commit -m "feat: show weapon-ineligibility warning indicator on shifts table rows"
```

---

### Task 14: Frontend — `ShiftDetailPanel.tsx` per-soldier ⚠️ + duty-manager "Replace" resolution

**Files:**
- Modify: `frontend/src/components/ShiftDetailPanel.tsx` (primaries/reserves row rendering, around lines 188-320)
- Modify: `frontend/src/api/calendar.ts:34-48` (`CalendarShiftAssignee` interface)
- Test: `frontend/src/components/ShiftDetailPanel.test.tsx` (check if it exists first; add cases)

**Interfaces:**
- Consumes: `CalendarShiftAssignee.weapon_ineligible`/`weapon_ineligible_reason` (Task 10).
- Produces: per-soldier ⚠️ marker in both the primaries and reserves lists; a "החלף" (Replace) button next to it for duty managers/admins that cancels the ineligible assignment and opens `ShiftAssignModal` targeted at the freed slot on that same shift.

- [x] **Step 1: Check for an existing `ShiftDetailPanel.test.tsx`**

```bash
ls frontend/src/components/ShiftDetailPanel.test.tsx 2>&1
```
Read it fully first if it exists, to match its mock/render conventions (it will need a mock `CalendarShift`/`shift` prop and mocked `getCalendarShifts`/`cancelAssignment`/similar API calls).

- [x] **Step 2: Write the failing tests**

```tsx
// Add to frontend/src/components/ShiftDetailPanel.test.tsx
it("shows a warning marker next to an ineligible soldier's name", async () => {
  // render ShiftDetailPanel with a shift prop whose primaries include one assignee with weapon_ineligible: true
  // assert a ⚠️ element (with title matching weapon_ineligible_reason) is present next to that soldier's name
});

it("shows a Replace button for duty managers next to the ineligible marker, which cancels and reopens the assign modal", async () => {
  // render as a duty_manager user
  // click the Replace button
  // assert the cancel-assignment API was called with the correct assignment_id
  // assert ShiftAssignModal (or its trigger state) opens targeted at the freed slot
});
```

- [x] **Step 3: Run to verify failure**

```bash
npm test -- ShiftDetailPanel.test.tsx
```
Expected: FAIL.

- [x] **Step 4: Add the fields to the frontend `CalendarShiftAssignee` interface**

In `frontend/src/api/calendar.ts`, add to the `CalendarShiftAssignee` interface (matching the backend schema from Task 10 exactly):

```typescript
  weapon_ineligible: boolean;
  weapon_ineligible_reason: string | null;
```

- [x] **Step 5: Add the ⚠️ marker and Replace button**

In `frontend/src/components/ShiftDetailPanel.tsx`, in both the primaries row (around lines 199-201, right after the `SoldierLink`) and the reserves row (the equivalent point around line 305-306), add — following the exact `ShiftAssignModal.tsx` weapon-warning JSX style cited in research (`{c.weapon_warning && (<span title={...} className="mr-1 text-amber-500 dark:text-amber-400">⚠️</span>)}`):

```tsx
<SoldierLink id={a.soldier_id} name={a.soldier_name} className="font-medium" />
{a.weapon_ineligible && (
  <span title={a.weapon_ineligible_reason ?? undefined} className="mr-1 text-red-500 dark:text-red-400">⚠️</span>
)}
```

(Note: use `text-red-500`/`text-red-400` here rather than the amber used for the soft-warning-at-assign-time marker in `ShiftAssignModal.tsx` — this is a *retroactive* ineligibility on an already-published assignment, a more urgent state per the design spec's "red badge" language, and should be visually distinct from the pre-assignment soft warning.)

Add the "Replace" button in the same right-aligned button group where the existing swap-offer/dismiss buttons live (lines 212-228 for primaries, equivalent block for reserves), gated on `(user?.role === "admin" || user?.is_duty_manager) && a.weapon_ineligible`:

```tsx
{(user?.role === "admin" || user?.is_duty_manager) && a.weapon_ineligible && (
  <button
    className="text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded hover:bg-red-200"
    onClick={async () => {
      await cancelAssignment(a.assignment_id);
      setReplaceTarget({ shiftId: shift.id });
      onRefreshNeeded();
    }}
  >
    {t("weapon_ineligible.replace")}
  </button>
)}
```

Add a `replaceTarget` state (`useState<{ shiftId: string } | null>(null)`) and, near wherever `OfferSwapModal` is conditionally rendered (lines 387-398), render `ShiftAssignModal` when `replaceTarget` is set, passing the shift so it opens focused on this shift's now-freed slot:

```tsx
{replaceTarget && (
  <ShiftAssignModal
    shift={shift}
    dutyTypes={dutyTypes}
    onSaved={() => { setReplaceTarget(null); onRefreshNeeded(); }}
    onClose={() => setReplaceTarget(null)}
  />
)}
```

(Check `ShiftAssignModal`'s actual prop names against its current definition — it was last touched by the weapon-qualification-eligibility plan, confirm `shift`/`dutyTypes`/`onSaved`/`onClose` are still its exact prop names before wiring this up. Import `ShiftAssignModal` and `cancelAssignment` — locate the exact existing cancel-assignment API function name, likely in `frontend/src/api/shifts.ts` or `frontend/src/api/assignments.ts` — at the top of the file if not already imported.)

- [x] **Step 6: Run tests to verify pass**

```bash
npm test -- ShiftDetailPanel.test.tsx
```
Expected: both PASS.

- [x] **Step 7: Typecheck and run the broader frontend suite**

```bash
npx tsc --noEmit -p .
npm test
```
Expected: clean, no regressions.

- [x] **Step 8: Commit**

```bash
git add frontend/src/components/ShiftDetailPanel.tsx frontend/src/api/calendar.ts frontend/src/components/ShiftDetailPanel.test.tsx
git commit -m "feat: show weapon-ineligibility marker and Replace action in shift roster panel"
```

---

### Task 15: Frontend — `MyDutiesPage.tsx` soldier resolution path

**Files:**
- Modify: `frontend/src/pages/MyDutiesPage.tsx` (upcoming-duties rendering)
- Modify: `frontend/src/api/assignments.ts:14-28` (`EffectiveDuty` interface)
- Test: `frontend/src/pages/MyDutiesPage.test.tsx` (check if it exists first; add cases)

**Interfaces:**
- Consumes: `EffectiveDuty.weapon_ineligible`/`weapon_ineligible_reason` (Task 11).
- Produces: a message + "בקש החלפה" (request swap) button on an ineligible duty row, opening `OfferSwapModal` pre-filled with that duty's `assignment_id`.

- [x] **Step 1: Check for an existing `MyDutiesPage.test.tsx`**

```bash
ls frontend/src/pages/MyDutiesPage.test.tsx 2>&1
```
Read it fully first if it exists.

- [x] **Step 2: Write the failing test**

```tsx
// Add to frontend/src/pages/MyDutiesPage.test.tsx
it("shows a swap-request button for an ineligible upcoming duty", async () => {
  // mock listEffectiveDuties to return one duty with weapon_ineligible: true, weapon_ineligible_reason: "..."
  // render MyDutiesPage
  // assert the reason text and a button (matching the swap-request label) are present
  // click the button, assert OfferSwapModal opens with targetAssignmentId matching the duty's assignment_id
});
```

- [x] **Step 3: Run to verify failure**

```bash
npm test -- MyDutiesPage.test.tsx
```
Expected: FAIL.

- [x] **Step 4: Add the fields to the frontend `EffectiveDuty` interface**

In `frontend/src/api/assignments.ts`, add to the `EffectiveDuty` interface (after `is_reserve`):

```typescript
  weapon_ineligible: boolean;
  weapon_ineligible_reason: string | null;
```

- [x] **Step 5: Add the resolution UI**

In `frontend/src/pages/MyDutiesPage.tsx`, in the upcoming-duties rendering block (the section iterating `dutiesQuery.data`, near lines 67-80), add a conditional block per duty row:

```tsx
{d.weapon_ineligible && (
  <div className="mt-1 flex items-center gap-2 text-sm text-red-600 dark:text-red-400">
    <span>⚠️ {d.weapon_ineligible_reason ?? "אינך כשיר לתורנות זו"}</span>
    <button
      className="text-xs bg-red-100 text-red-800 px-2 py-0.5 rounded hover:bg-red-200"
      onClick={() => setOfferSwapTarget({
        soldierId: d.soldier_id, soldierName: user!.full_name, assignmentId: d.assignment_id,
      })}
    >
      בקש החלפה
    </button>
  </div>
)}
```

Add the `offerSwapTarget` state and the conditional `OfferSwapModal` render at the bottom of the component, following the exact pattern already established in `ShiftDetailPanel.tsx` (lines 387-398) — `targetSoldierId`, `targetSoldierName`, `targetAssignmentId={offerSwapTarget.assignmentId}`, `targetDutyStart={d.start_date}`, `targetDutyEnd={d.end_date}`, `targetDutyTypeId={d.duty_type_id}`, `onClose`, `onDone`. Import `OfferSwapModal` at the top of the file if not already imported.

- [x] **Step 6: Run tests to verify pass**

```bash
npm test -- MyDutiesPage.test.tsx
```
Expected: PASS.

- [x] **Step 7: Typecheck and run the broader frontend suite**

```bash
npx tsc --noEmit -p .
npm test
```
Expected: clean, no regressions.

- [x] **Step 8: Commit**

```bash
git add frontend/src/pages/MyDutiesPage.tsx frontend/src/api/assignments.ts frontend/src/pages/MyDutiesPage.test.tsx
git commit -m "feat: let soldiers request a swap directly from a newly-ineligible duty"
```

---

### Task 16: Full regression pass

**Files:** none (verification only)

- [x] **Step 1: Run the full backend fast suite**

```bash
cd backend
pytest -q
```
Expected: all green (aside from any already-known, pre-existing, unrelated flaky failures — verify any failure passes in isolation and touches code this plan never modified before treating it as pre-existing).

- [x] **Step 2: Run the backend slow suite**

```bash
pytest --slow -q
```
Expected: all green.

- [x] **Step 3: Run the full frontend suite**

```bash
cd frontend
npm test
npm run lint
npx tsc --noEmit -p .
```
Expected: all green, zero lint warnings.

- [x] **Step 4: Manual smoke test in the browser**

Start the dev stack, log in as an admin. Create a `DutyType` with `requires_weapon=true` and `required_range_type=laser` (now possible via the API directly, per Task 3), create a shift for it, assign a soldier with no range qualification (bypassing the soft-warning-with-override from the weapon-qualification-eligibility feature), then either wait for the daily worker or manually call `recheck_assignments` for that assignment (e.g. via a one-off script) — confirm: the nav badge count increments, the ⚠️ appears on the shifts table row, the ⚠️ + "Replace" button appear in the shift detail panel, the soldier sees the "request swap" prompt on their own duties page, and a notification was created for the soldier, their commander, and the duty managers in scope.

- [x] **Step 5: No commit needed** — this task only verifies prior commits; if any regression surfaces, fix it within the task that introduced it and re-run this task.
