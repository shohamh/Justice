# Range Attendance Auto-Mark and Correction Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Once a range event's date passes, every soldier actually scheduled (non-reserve, non-draft) is automatically marked present; any retroactive correction of attendance — either direction — requires a written reason and notifies both the soldier and their direct (nearest-ancestor) commander.

**Architecture:** A new polling worker (mirroring the existing `range_reminder_worker.py` exactly) calls a new service function that reuses the existing `mark_attendance` side-effect logic (qualification grant/revoke, score adjustments) for auto-marking. `mark_attendance` itself gains a broader note-required rule and two new notification paths, reusing the existing `commander_chain_for_soldier` helper to find the soldier's nearest commander rather than inventing new hierarchy-walking logic.

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy 2.0 (backend), React 18 / TypeScript / Vite (frontend), pytest (backend tests), Alembic (migrations).

## Global Constraints

- Design spec: [`docs/superpowers/specs/2026-08-07-range-attendance-auto-mark-and-corrections-design.md`](../specs/2026-08-07-range-attendance-auto-mark-and-corrections-design.md).
- Everything here is gated by `mitvachim.enabled`, matching every other range feature (`ranges.py:37-39`'s `_mitvachim_enabled`, `range_reminders.py:54-56`).
- "Direct commander" = `commander_chain_for_soldier(session, soldier_id)[0]` (nearest, not the whole chain) — reuse `backend/app/services/approval_scope.py:11-46`, do not re-implement hierarchy walking.
- Note is required whenever `status == no_show` OR (`previous_status != pending` AND `status != previous_status`) — i.e. any real correction of an already-resolved attendance record, either direction.
- The renamed error code `note_required_for_attendance_change` replaces `note_required_for_no_show` everywhere it's raised (there is exactly one raise site).
- This plan **modifies an existing passing test** (`test_correcting_no_show_to_present_reverses_penalty_and_sets_qualification` in `backend/tests/unit/test_range_attendance.py:209-228`) which currently calls `mark_attendance(..., status=present, marked_by=soldier.id)` with no note — under the new rule this call would now raise. Task 3 updates it to pass a note.
- Backend tests run via `pytest -q <path>` from `backend/` (venv activated); frontend tests via `npm test -- <path>` from `frontend/`.

---

### Task 1: Migration — new `NotificationType` enum values

**Files:**
- Create: `backend/alembic/versions/<new_revision>_add_range_attendance_correction_notification_types.py`

**Interfaces:**
- Produces: two new Postgres enum values on `notification_type`: `range_absence_reported_to_commander`, `range_attendance_corrected_to_present`.

- [ ] **Step 1: Generate the revision skeleton**

```bash
cd backend
alembic revision -m "add_range_attendance_correction_notification_types"
```

- [ ] **Step 2: Write the migration body**

Follow the exact pattern of `backend/alembic/versions/f7a8b9c0d1e2_add_bug_report_comment_notification.py`:

```python
"""add_range_attendance_correction_notification_types

Revision ID: <new_revision>
Revises: <auto-filled head>
"""

from alembic import op


revision = "<new_revision>"
down_revision = "<auto-filled head>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'range_absence_reported_to_commander'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'range_attendance_corrected_to_present'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op.
    pass
```

- [ ] **Step 3: Apply the migration**

```bash
alembic upgrade head
```
Expected: applies cleanly.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/*_add_range_attendance_correction_notification_types.py
git commit -m "feat: add range attendance correction notification enum values"
```

---

### Task 2: Model — `NotificationType` new members

**Files:**
- Modify: `backend/app/db/models.py:1167-1210`

**Interfaces:**
- Produces: `NotificationType.range_absence_reported_to_commander`, `NotificationType.range_attendance_corrected_to_present`.

- [ ] **Step 1: Add the enum members**

In `backend/app/db/models.py`, after `range_excusal_no_backfill = "range_excusal_no_backfill"` (line 1209):

```python
    range_excusal_no_backfill = "range_excusal_no_backfill"
    range_absence_reported_to_commander = "range_absence_reported_to_commander"
    range_attendance_corrected_to_present = "range_attendance_corrected_to_present"
    bug_report_comment = "bug_report_comment"
```

(Insert before the existing `bug_report_comment` line to keep the range-related block together; exact position doesn't matter functionally.)

- [ ] **Step 2: Verify**

```bash
python -c "from app.db.models import NotificationType; print(NotificationType.range_absence_reported_to_commander, NotificationType.range_attendance_corrected_to_present)"
```
Expected: prints both values with no error.

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat: add range attendance correction NotificationType members"
```

---

### Task 3: `mark_attendance` — note rule, direct-commander notifications

**Files:**
- Modify: `backend/app/services/ranges.py:467-553`
- Modify: `backend/tests/unit/test_range_attendance.py` (fix one existing test, add new ones)

**Interfaces:**
- Consumes: `app.services.approval_scope.commander_chain_for_soldier` (`backend/app/services/approval_scope.py:11-46`).
- Produces: `mark_attendance(session, *, assignment, status, marked_by: uuid.UUID | None = None, note=None)` (widened `marked_by` type), raising `RangeValidationError("note_required_for_attendance_change")` under the widened rule.

- [ ] **Step 1: Fix the pre-existing test that the new rule breaks**

In `backend/tests/unit/test_range_attendance.py`, update `test_correcting_no_show_to_present_reverses_penalty_and_sets_qualification` (line 209-228) — add a note to the correction call:

```python
def test_correcting_no_show_to_present_reverses_penalty_and_sets_qualification(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.laser_validity_days": 180}, actor_id=None)
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)
    mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=soldier.id, note="סימון ראשוני",
    )

    corrected = mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.present,
        marked_by=soldier.id, note="התברר שהוא כן הגיע",
    )

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

- [ ] **Step 2: Write the new failing tests**

Append to `backend/tests/unit/test_range_attendance.py`:

```python
def test_correcting_no_show_to_present_without_note_raises(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)
    mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=soldier.id, note="סימון ראשוני",
    )

    with pytest.raises(RangeValidationError, match="note_required_for_attendance_change"):
        mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)


def test_pending_to_present_still_does_not_require_note(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)

    updated = mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)

    assert updated.attendance_status == RangeAttendanceStatus.present


def test_no_show_notifies_direct_commander(app_session: Session) -> None:
    from app.db.models import HierarchyNode

    apply_settings(app_session, {}, {"mitvachim.enabled": True}, actor_id=None)
    past_date = date.today() - timedelta(days=1)
    commander = create_soldier(app_session, personal_number="5900010", role="commander")
    node = create_node(app_session, level="פלוגה", name="פלוגה-מפקד", commander_id=commander.id)
    app_session.commit()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=past_date, range_location_id=create_range_location(app_session, name="מטווח מפקד").id,
        required_count=1,
    )
    soldier = create_soldier(app_session, personal_number="5900011", hierarchy_node_id=node.id)
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=commander.id, note="לא הגיע",
    )

    notif = app_session.execute(select(Notification).where(
        Notification.soldier_id == commander.id,
        Notification.type == NotificationType.range_absence_reported_to_commander,
    )).scalar_one()
    assert notif.body == "לא הגיע"


def test_correcting_to_present_notifies_soldier_and_commander(app_session: Session) -> None:
    from app.db.models import HierarchyNode

    apply_settings(app_session, {}, {"mitvachim.enabled": True}, actor_id=None)
    past_date = date.today() - timedelta(days=1)
    commander = create_soldier(app_session, personal_number="5900012", role="commander")
    node = create_node(app_session, level="פלוגה", name="פלוגה-מפקד-2", commander_id=commander.id)
    app_session.commit()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=past_date, range_location_id=create_range_location(app_session, name="מטווח מפקד 2").id,
        required_count=1,
    )
    soldier = create_soldier(app_session, personal_number="5900013", hierarchy_node_id=node.id)
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=commander.id, note="סימון ראשוני",
    )

    mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.present,
        marked_by=commander.id, note="התברר שכן הגיע",
    )

    for recipient_id in (soldier.id, commander.id):
        notif = app_session.execute(select(Notification).where(
            Notification.soldier_id == recipient_id,
            Notification.type == NotificationType.range_attendance_corrected_to_present,
        )).scalar_one()
        assert notif.body == "התברר שכן הגיע"


def test_no_direct_commander_does_not_raise(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    node = create_node(app_session, level="פלוגה", name="פלוגה-ללא-מפקד")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=past_date, range_location_id=create_range_location(app_session, name="מטווח ללא מפקד").id,
        required_count=1,
    )
    soldier = create_soldier(app_session, personal_number="5900014", hierarchy_node_id=node.id)
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    updated = mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=soldier.id, note="לא הגיע",
    )
    assert updated.attendance_status == RangeAttendanceStatus.no_show


def test_auto_mark_uses_none_marked_by(app_session: Session) -> None:
    past_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=past_date)

    updated = mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=None)

    assert updated.marked_by is None
    assert updated.attendance_status == RangeAttendanceStatus.present
```

- [ ] **Step 3: Run to verify failure**

```bash
pytest tests/unit/test_range_attendance.py -v -k "note_required_for_attendance_change or direct_commander or corrected_to_present or no_direct_commander or auto_mark_uses_none"
```
Expected: FAIL — `marked_by: uuid.UUID | None` not yet accepted with `None` (TypeError from the type system is not enforced at runtime by a plain dataclass-less function, so this specific call may not fail on `None`, but it WILL fail because `note_required_for_attendance_change` isn't the raised string yet, no commander notifications are sent yet, etc).

- [ ] **Step 4: Implement the changes to `mark_attendance`**

In `backend/app/services/ranges.py`, add the import at the top (near the existing `from app.services.range_exemption import is_range_exempt` line):

```python
from app.services.approval_scope import commander_chain_for_soldier
```

Add a small helper right before `mark_attendance` (after `_delete_qualification_from_this_assignment`, line 461-464):

```python
def _direct_commander_id(session: Session, soldier_id: uuid.UUID) -> uuid.UUID | None:
    chain = commander_chain_for_soldier(session, soldier_id)
    return chain[0] if chain else None
```

Replace the `mark_attendance` signature and body (lines 467-553) with:

```python
def mark_attendance(
    session: Session, *, assignment: RangeAssignment, status: RangeAttendanceStatus,
    marked_by: uuid.UUID | None = None, note: str | None = None,
) -> RangeAssignment:
    if assignment.is_draft:
        raise RangeValidationError("assignment_not_confirmed")
    event = session.get(RangeEvent, assignment.range_event_id)
    if event is None:
        raise RangeValidationError("event_not_found")
    if event.status == RangeEventStatus.cancelled:
        raise RangeValidationError("event_cancelled")
    if event.date > date.today():
        raise RangeValidationError("event_not_yet_occurred")

    previous_status = assignment.attendance_status
    note_required = status == RangeAttendanceStatus.no_show or (
        previous_status != RangeAttendanceStatus.pending and status != previous_status
    )
    if note_required and not note:
        raise RangeValidationError("note_required_for_attendance_change")

    if previous_status == status:
        if status == RangeAttendanceStatus.no_show and _mitvachim_enabled(session):
            latest_body = f"{_range_context(session, event, reason=note)} | assignment={assignment.id}"
            session.query(Notification).filter(
                Notification.type == NotificationType.range_no_show,
                Notification.reference_type == "range_event",
                Notification.reference_id == event.id,
            ).update({Notification.body: latest_body}, synchronize_session=False)
        session.commit()
        session.refresh(assignment)
        return assignment
    no_show_transition = previous_status != RangeAttendanceStatus.no_show and status == RangeAttendanceStatus.no_show
    present_correction = previous_status == RangeAttendanceStatus.no_show and status == RangeAttendanceStatus.present

    # Reverse the previous side effect, if any.
    if previous_status == RangeAttendanceStatus.no_show and assignment.score_adjustment_id is not None:
        original = session.get(ScoreAdjustment, assignment.score_adjustment_id)
        reversal_delta = -original.delta if original is not None else -_NO_SHOW_PENALTY
        create_adjustment(
            session, soldier_id=assignment.soldier_id, delta=reversal_delta,
            reason="range_no_show_reversed", actor_id=marked_by,
        )
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
        _record_qualification(
            session, soldier_id=assignment.soldier_id, range_type=event.range_type,
            valid_until=valid_until, source_range_assignment_id=assignment.id,
        )
        if present_correction:
            commander_id = _direct_commander_id(session, assignment.soldier_id)
            _range_notification(
                session, soldier_id=assignment.soldier_id, type=NotificationType.range_attendance_corrected_to_present,
                title="תיקון נוכחות במטווח", body=note, reference_type="range_assignment",
                reference_id=assignment.id, actor_id=marked_by,
            )
            if commander_id is not None:
                _range_notification(
                    session, soldier_id=commander_id, type=NotificationType.range_attendance_corrected_to_present,
                    title="תיקון נוכחות במטווח", body=note, reference_type="range_assignment",
                    reference_id=assignment.id, actor_id=marked_by,
                )
    elif status == RangeAttendanceStatus.no_show:
        adjustment = create_adjustment(
            session, soldier_id=assignment.soldier_id, delta=_NO_SHOW_PENALTY,
            reason="range_no_show", actor_id=marked_by,
        )
        assignment.score_adjustment_id = adjustment.id
        _range_notification(
            session, soldier_id=assignment.soldier_id, type=NotificationType.no_show_marked,
            title="נרשם היעדרות ממטווח", body=note, reference_type="range_assignment",
            reference_id=assignment.id, actor_id=marked_by,
        )
        if no_show_transition and _mitvachim_enabled(session):
            _range_notification(session, soldier_id=assignment.soldier_id, type=NotificationType.range_no_show, title="Range no-show recorded", body=f"{_range_context(session, event, reason=note)} | assignment={assignment.id}", reference_type="range_event", reference_id=event.id, actor_id=marked_by)
            notify_duty_managers_in_scope(
                session, soldier_id=assignment.soldier_id, type=NotificationType.range_no_show,
                title="Range no-show recorded",
                body=f"{_range_context(session, event, reason=note)} | assignment={assignment.id}",
                reference_type="range_event", reference_id=event.id, actor_id=marked_by,
            )
            commander_id = _direct_commander_id(session, assignment.soldier_id)
            if commander_id is not None:
                _range_notification(
                    session, soldier_id=commander_id, type=NotificationType.range_absence_reported_to_commander,
                    title="נרשמה היעדרות ממטווח", body=note, reference_type="range_assignment",
                    reference_id=assignment.id, actor_id=marked_by,
                )

    assignment.attendance_status = status
    assignment.marked_by = marked_by
    assignment.marked_at = datetime.now(UTC)
    assignment.note = note

    write_audit(
        session, actor_id=marked_by, action="range_attendance_marked", entity_type="range_assignment",
        entity_id=assignment.id, before={"attendance_status": previous_status}, after={"attendance_status": status},
    )

    session.commit()
    session.refresh(assignment)
    return assignment
```

- [ ] **Step 5: Run tests to verify pass**

```bash
pytest tests/unit/test_range_attendance.py -v
```
Expected: all PASS, including the pre-existing tests (now updated) and the six new ones.

- [ ] **Step 6: Run the broader ranges suite for regressions**

```bash
pytest tests/unit/test_range_attendance.py tests/unit/test_range_excusal.py tests/unit/test_ranges_service.py tests/integration/test_ranges_api.py -v
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/ranges.py backend/tests/unit/test_range_attendance.py
git commit -m "feat: notify direct commander on range attendance corrections, require reason both directions"
```

---

### Task 4: Auto-mark service

**Files:**
- Create: `backend/app/services/range_attendance_auto_mark.py`
- Test: `backend/app/services/tests/test_range_attendance_auto_mark.py`

**Interfaces:**
- Consumes: `app.services.ranges.mark_attendance`.
- Produces: `auto_mark_present_for_elapsed_events(session: Session, *, today: date | None = None) -> int`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/app/services/tests/test_range_attendance_auto_mark.py
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RangeAttendanceStatus, RangeEventStatus, RangeType, SoldierRangeQualification
from app.services.range_attendance_auto_mark import auto_mark_present_for_elapsed_events
from app.services.ranges import add_range_assignment, cancel_range_event, create_range_event
from app.services.settings_loader import apply_settings
from tests.helpers import create_node, create_range_location, create_soldier


def _event(session: Session, *, event_date: date, reserve_count: int = 1):
    node = create_node(session, level="branch", name=f"auto-mark-{event_date}")
    location = create_range_location(session, name="auto-mark-loc")
    event = create_range_event(
        session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, range_location_id=location.id,
        required_count=1, reserve_count=reserve_count,
    )
    return node, event


def test_auto_marks_non_reserve_non_draft_assignment_present(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.enabled": True}, actor_id=None)
    node, event = _event(app_session, event_date=date.today() - timedelta(days=1))
    soldier = create_soldier(app_session, personal_number="am-001", hierarchy_node_id=node.id)
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    count = auto_mark_present_for_elapsed_events(app_session)

    assert count == 1
    app_session.refresh(event)
    assignment = event.assignments[0] if hasattr(event, "assignments") else None
    qualification = app_session.execute(
        select(SoldierRangeQualification).where(SoldierRangeQualification.soldier_id == soldier.id)
    ).scalar_one()
    assert qualification.range_type == RangeType.laser


def test_reserve_assignment_not_auto_marked(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.enabled": True}, actor_id=None)
    node, event = _event(app_session, event_date=date.today() - timedelta(days=1))
    soldier = create_soldier(app_session, personal_number="am-002", hierarchy_node_id=node.id)
    reserve_assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=True)

    auto_mark_present_for_elapsed_events(app_session)

    app_session.refresh(reserve_assignment)
    assert reserve_assignment.attendance_status == RangeAttendanceStatus.pending


def test_future_event_not_touched(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.enabled": True}, actor_id=None)
    node, event = _event(app_session, event_date=date.today() + timedelta(days=1))
    soldier = create_soldier(app_session, personal_number="am-003", hierarchy_node_id=node.id)
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    count = auto_mark_present_for_elapsed_events(app_session)

    assert count == 0
    app_session.refresh(assignment)
    assert assignment.attendance_status == RangeAttendanceStatus.pending


def test_cancelled_event_not_touched(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.enabled": True}, actor_id=None)
    node, event = _event(app_session, event_date=date.today() + timedelta(days=1))
    soldier = create_soldier(app_session, personal_number="am-004", hierarchy_node_id=node.id)
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    cancel_range_event(app_session, event=event, reason="בוטל", actor_id=soldier.id)

    count = auto_mark_present_for_elapsed_events(app_session, today=date.today() + timedelta(days=2))

    assert count == 0
    app_session.refresh(assignment)
    assert assignment.attendance_status == RangeAttendanceStatus.pending


def test_already_marked_assignment_not_reprocessed(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.enabled": True}, actor_id=None)
    node, event = _event(app_session, event_date=date.today() - timedelta(days=1))
    soldier = create_soldier(app_session, personal_number="am-005", hierarchy_node_id=node.id)
    add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    first = auto_mark_present_for_elapsed_events(app_session)
    second = auto_mark_present_for_elapsed_events(app_session)

    assert first == 1
    assert second == 0
    qualification_count = app_session.execute(
        select(SoldierRangeQualification).where(SoldierRangeQualification.soldier_id == soldier.id)
    ).scalars().all()
    assert len(qualification_count) == 1


def test_disabled_setting_skips_entirely(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.enabled": False}, actor_id=None)
    node, event = _event(app_session, event_date=date.today() - timedelta(days=1))
    soldier = create_soldier(app_session, personal_number="am-006", hierarchy_node_id=node.id)
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    count = auto_mark_present_for_elapsed_events(app_session)

    assert count == 0
    app_session.refresh(assignment)
    assert assignment.attendance_status == RangeAttendanceStatus.pending
```

Check `cancel_range_event`'s actual signature first (`grep -n "^def cancel_range_event" backend/app/services/ranges.py`) and adjust the call in `test_cancelled_event_not_touched` to match if it differs from the guessed `(session, event=event, reason=..., actor_id=...)` shape above.

- [ ] **Step 2: Run to verify failure**

```bash
pytest app/services/tests/test_range_attendance_auto_mark.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.range_attendance_auto_mark'`.

- [ ] **Step 3: Implement the service**

```python
# backend/app/services/range_attendance_auto_mark.py
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RangeAssignment, RangeAttendanceStatus, RangeEvent, RangeEventStatus, SystemSetting
from app.services.ranges import mark_attendance


def _mitvachim_enabled(session: Session) -> bool:
    setting = session.get(SystemSetting, "mitvachim.enabled")
    return setting is None or setting.value is True


def auto_mark_present_for_elapsed_events(session: Session, *, today: date | None = None) -> int:
    """Auto-marks 'present' every still-pending, non-reserve, non-draft assignment
    on a RangeEvent whose date has already passed. Reuses mark_attendance so
    qualification granting stays consistent with manual marking. Idempotent —
    only ever touches assignments still in the 'pending' state."""
    if not _mitvachim_enabled(session):
        return 0
    today = today or date.today()
    events = session.execute(
        select(RangeEvent).where(
            RangeEvent.date < today,
            RangeEvent.status != RangeEventStatus.cancelled,
        )
    ).scalars().all()
    marked = 0
    for event in events:
        assignments = session.execute(
            select(RangeAssignment).where(
                RangeAssignment.range_event_id == event.id,
                RangeAssignment.attendance_status == RangeAttendanceStatus.pending,
                RangeAssignment.is_reserve.is_(False),
                RangeAssignment.is_draft.is_(False),
            )
        ).scalars().all()
        for assignment in assignments:
            mark_attendance(session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=None)
            marked += 1
    return marked
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest app/services/tests/test_range_attendance_auto_mark.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/range_attendance_auto_mark.py backend/app/services/tests/test_range_attendance_auto_mark.py
git commit -m "feat: add automatic range attendance marking for elapsed events"
```

---

### Task 5: Polling worker + startup wiring

**Files:**
- Create: `backend/app/range_attendance_worker.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `range_attendance_auto_mark.auto_mark_present_for_elapsed_events`.
- Produces: `run_range_attendance_worker()` coroutine, started/cancelled in `main.py`'s `lifespan`.

- [ ] **Step 1: Implement the worker**

Mirror `backend/app/range_reminder_worker.py` exactly:

```python
# backend/app/range_attendance_worker.py
from __future__ import annotations

import asyncio
import logging

from app.db.session import session_scope
from app.services.range_attendance_auto_mark import auto_mark_present_for_elapsed_events

logger = logging.getLogger(__name__)
_POLL_SECONDS = 300

def _auto_mark_present_for_elapsed_events() -> None:
    with session_scope() as session:
        count = auto_mark_present_for_elapsed_events(session)
        if count:
            logger.info("range attendance worker: auto-marked %d assignment(s) present", count)

async def run_range_attendance_worker() -> None:
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            await asyncio.to_thread(_auto_mark_present_for_elapsed_events)
        except Exception:
            logger.warning("range attendance worker: unhandled error", exc_info=True)
```

- [ ] **Step 2: Wire it into `main.py`**

Add the import (line 14, alongside `run_range_reminder_worker`):

```python
from app.range_reminder_worker import run_range_reminder_worker
from app.range_attendance_worker import run_range_attendance_worker
```

Update `lifespan` (lines 120-136):

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== STARTUP pid=%d ===", os.getpid())
    asyncio.get_running_loop().set_exception_handler(_handle_async_exception)
    _fail_orphaned_algorithm_jobs()
    email_task = asyncio.create_task(run_email_worker())
    swap_expiry_task = asyncio.create_task(run_swap_expiry_worker())
    range_reminder_task = asyncio.create_task(run_range_reminder_worker())
    range_attendance_task = asyncio.create_task(run_range_attendance_worker())
    yield
    for task in (email_task, swap_expiry_task, range_reminder_task, range_attendance_task):
        task.cancel()
    for task in (email_task, swap_expiry_task, range_reminder_task, range_attendance_task):
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("=== CLEAN SHUTDOWN ===")
```

- [ ] **Step 3: Verify the app still starts**

```bash
cd backend
python -c "from app.main import create_app; app = create_app(); print('ok')"
```
Expected: prints `ok`, no import errors.

- [ ] **Step 4: Commit**

```bash
git add backend/app/range_attendance_worker.py backend/app/main.py
git commit -m "feat: start range attendance auto-mark worker on app startup"
```

---

### Task 6: Frontend — `RangeAttendancePanel` note requirement for corrections

**Files:**
- Modify: `frontend/src/components/ranges/RangeAttendancePanel.tsx`
- Test: `frontend/src/components/ranges/RangeAttendancePanel.test.tsx` (check if it exists first)

**Interfaces:**
- Consumes: `RangeAssignment.attendance_status` (already on the type, `frontend/src/api/ranges.ts:5`).

- [ ] **Step 1: Check for an existing test file**

```bash
ls frontend/src/components/ranges/RangeAttendancePanel.test.tsx 2>&1
```
Read it fully first if it exists, to match existing render/mock conventions.

- [ ] **Step 2: Write the failing test**

```tsx
// frontend/src/components/ranges/RangeAttendancePanel.test.tsx (new, or append)
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import RangeAttendancePanel from "./RangeAttendancePanel";
import * as rangesApi from "../../api/ranges";

vi.mock("../../api/ranges", async () => {
  const actual = await vi.importActual<typeof rangesApi>("../../api/ranges");
  return { ...actual, markRangeAttendance: vi.fn().mockResolvedValue({}) };
});

describe("RangeAttendancePanel correction note requirement", () => {
  it("requires a note when correcting an already-present assignment to no_show (already true today)", () => {
    render(
      <RangeAttendancePanel
        eventId="e1"
        assignments={[{
          id: "a1", soldier_id: "s1", is_reserve: false, is_draft: false,
          attendance_status: "present", note: null,
          assignment_reason_code: null, assignment_reason_text: null,
        }]}
        onMarked={vi.fn()}
      />
    );
    fireEvent.click(screen.getByTestId("no-show-a1"));
    const submit = screen.getByTestId("submit-a1") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
  });

  it("requires a note when correcting an already no_show assignment back to present", () => {
    render(
      <RangeAttendancePanel
        eventId="e1"
        assignments={[{
          id: "a2", soldier_id: "s2", is_reserve: false, is_draft: false,
          attendance_status: "no_show", note: "לא הגיע",
          assignment_reason_code: null, assignment_reason_text: null,
        }]}
        onMarked={vi.fn()}
      />
    );
    fireEvent.click(screen.getByTestId("present-a2"));
    const submit = screen.getByTestId("submit-a2") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect(screen.getByTestId("note-a2")).toBeTruthy();
  });

  it("does not require a note for a fresh pending-to-present mark", () => {
    render(
      <RangeAttendancePanel
        eventId="e1"
        assignments={[{
          id: "a3", soldier_id: "s3", is_reserve: false, is_draft: false,
          attendance_status: "pending", note: null,
          assignment_reason_code: null, assignment_reason_text: null,
        }]}
        onMarked={vi.fn()}
      />
    );
    fireEvent.click(screen.getByTestId("present-a3"));
    const submit = screen.getByTestId("submit-a3") as HTMLButtonElement;
    expect(submit.disabled).toBe(false);
  });
});
```

- [ ] **Step 3: Run to verify failure**

```bash
npm test -- RangeAttendancePanel.test.tsx
```
Expected: FAIL on the second test — today, `present` never shows a note field or requires one, so `submit.disabled` would be `false` and `note-a2` wouldn't exist.

- [ ] **Step 4: Implement the panel changes**

In `frontend/src/components/ranges/RangeAttendancePanel.tsx`, replace the `canSubmit` computation and the note-field condition (lines 40-41 and 70-78):

```tsx
      {assignments.map((a) => {
        const status = pendingStatus[a.id];
        const isCorrection = a.attendance_status !== "pending" && status !== a.attendance_status;
        const noteRequired = status === "no_show" || isCorrection;
        const canSubmit = !!status && (!noteRequired || !!notes[a.id]);
        return (
```

and:

```tsx
            {noteRequired && (
              <input
                data-testid={`note-${a.id}`}
                value={notes[a.id] ?? ""}
                onChange={(e) => setNotes((prev) => ({ ...prev, [a.id]: e.target.value }))}
                placeholder="סיבה (חובה)"
                className="border rounded p-1 text-sm flex-1 min-w-40 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              />
            )}
```

(The rest of the component — buttons, submit call, error display — is unchanged.)

- [ ] **Step 5: Run tests to verify pass**

```bash
npm test -- RangeAttendancePanel.test.tsx
```
Expected: all PASS.

- [ ] **Step 6: Typecheck and run the broader frontend suite**

```bash
npx tsc --noEmit -p .
npm test
```
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ranges/RangeAttendancePanel.tsx frontend/src/components/ranges/RangeAttendancePanel.test.tsx
git commit -m "feat: require a reason for range attendance corrections in either direction"
```

---

### Task 7: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend fast suite**

```bash
cd backend
pytest -q
```
Expected: all green.

- [ ] **Step 2: Run the backend slow suite**

```bash
pytest --slow -q
```
Expected: all green.

- [ ] **Step 3: Run the full frontend suite**

```bash
cd frontend
npm test
npm run lint
npx tsc --noEmit -p .
```
Expected: all green, zero lint warnings.

- [ ] **Step 4: Manual smoke test**

Start `.\dev.ps1`, create a range event dated yesterday with a confirmed (non-draft, non-reserve) soldier assignment left `pending`, wait up to 5 minutes (or temporarily lower `_POLL_SECONDS` locally to verify faster), and confirm the assignment flips to `present` with a qualification row created. Then use the attendance panel to correct it to `no_show` with a reason, and confirm both the soldier and their direct commander (set one via `HierarchyNode.commander_id` in the DB/admin UI first) receive notifications.

- [ ] **Step 5: No commit needed** — verification only; fix regressions in the task that introduced them.
