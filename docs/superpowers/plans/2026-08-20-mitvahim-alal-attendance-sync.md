# מטווחים/אל"ל attendance sync + expiry notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep `Soldier.last_mitvahim_date` / `Soldier.last_alal_date` in sync with
real range attendance recorded through the מטווחים subsystem, and add a proactive
notification (to the soldier and their commander chain) as those qualifications
approach or pass expiry.

**Architecture:** Two independent changes, each a self-contained task. (1) Hook
`mark_attendance()` in `backend/app/services/ranges.py` so a `present` attendance
record advances the relevant profile date field, and a reversal recomputes it from
remaining present attendances. (2) A new daily background worker
(`backend/app/qualification_expiry_worker.py`), following the exact pattern of the
existing `rank_advancement_worker.py`, that checks each soldier's profile date
against configurable validity/warn-day settings and fires a notification via two
new `NotificationType` values per qualification (mitvahim, alal) — one for
"expiring soon", one for "expired".

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, pytest, existing `session_scope()` /
`create_notification()` / `get_setting_int()` helpers.

## Global Constraints

- Both existing eligibility mechanisms (the legacy date-based check in
  `eligibility.py` and the newer qualification-based `weapon_eligibility.py`)
  stay as-is and independent — this work only keeps the legacy profile date
  fields honest, it does not consolidate the two systems.
- The profile date field only ever moves **forward** on a `present` mark
  (`max(current, event.date)`), and on reversal is recomputed from remaining
  present attendances — never cleared to `None` if no attendances remain (a
  manually-entered value may still be valid and must not be erased).
- Deleting a `RangeAssignment` entirely (via `remove_range_assignment`) does
  **not** trigger a recompute. The `SoldierRangeQualification.source_range_assignment_id`
  column is `ON DELETE SET NULL`, and `get_effective_range_qualification()`
  treats a qualification with a null source as still valid — so the
  qualification subsystem itself does not revoke on assignment deletion.
  Recomputing the profile date on deletion would make the profile field
  stricter than the subsystem it's supposed to mirror. Only an explicit
  attendance-status transition away from `present` triggers a recompute.
- Notification titles are plain hardcoded Hebrew strings built server-side
  (see `notify_rank_advanced` / `notify_rank_advancement_soon` in
  `backend/app/services/notifications.py`) — there is **no** i18n/`he.json`
  involvement for notification titles; the frontend renders `notification.title`
  verbatim (`frontend/src/pages/NotificationsPage.tsx`,
  `frontend/src/components/NotificationBell.tsx`).
- Reuse the existing settings keys already driving the home-page banner
  (`home.mitvahim_validity_days` default 180, `home.mitvahim_warn_days` default
  30, `home.alal_validity_days` default 90, `home.alal_warn_days` default 30) —
  do not introduce new setting keys.
- אל"ל checks are scoped to `is_alal_relevant(session, soldier)` from
  `backend/app/services/alal_relevance.py`, matching `AlertBanners.tsx`'s own
  `user.alal_relevant` gate.

---

### Task 1: Sync range attendance into `last_mitvahim_date` / `last_alal_date`

**Files:**
- Modify: `backend/app/services/ranges.py:506-666` (add two helpers, wire into `mark_attendance`)
- Test: `backend/tests/unit/test_range_attendance.py`

**Interfaces:**
- Consumes: existing `RangeType`, `RangeAttendanceStatus`, `RangeEvent`, `RangeAssignment`, `Soldier` (all already imported in `ranges.py`); existing `_setup_event_and_assignment(session, *, event_date, range_type=RangeType.laser)` test helper in `test_range_attendance.py`.
- Produces: no new public functions — `mark_attendance()`'s existing signature and return value are unchanged. Later tasks do not depend on anything from this task.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_range_attendance.py` (append to end of file):

```python
def test_mark_present_advances_last_mitvahim_date(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.laser_validity_days": 180}, actor_id=None)
    event_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=event_date)
    soldier.last_mitvahim_date = event_date - timedelta(days=200)
    app_session.flush()

    mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)

    app_session.refresh(soldier)
    assert soldier.last_mitvahim_date == event_date


def test_mark_present_does_not_move_last_mitvahim_date_backward(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.laser_validity_days": 180}, actor_id=None)
    event_date = date.today() - timedelta(days=30)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=event_date)
    newer_manual_date = date.today() - timedelta(days=1)
    soldier.last_mitvahim_date = newer_manual_date
    app_session.flush()

    mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)

    app_session.refresh(soldier)
    assert soldier.last_mitvahim_date == newer_manual_date


def test_mark_present_advances_last_alal_date_for_alal_range_type(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.alal_validity_days": 365}, actor_id=None)
    event_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=event_date, range_type=RangeType.alal)

    mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)

    app_session.refresh(soldier)
    assert soldier.last_alal_date == event_date
    assert soldier.last_mitvahim_date is None


def test_reversal_recomputes_last_mitvahim_date_from_remaining_present_attendance(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.laser_validity_days": 180}, actor_id=None)
    earlier_date = date.today() - timedelta(days=30)
    later_date = date.today() - timedelta(days=1)
    node = create_node(app_session, level="פלוגה", name="פלוגה-reversal")
    soldier = create_soldier(app_session, personal_number="5900010", hierarchy_node_id=node.id)
    location = create_range_location(app_session, name="מטווח reversal")
    earlier_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=earlier_date, range_location_id=location.id, required_count=1,
    )
    later_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=later_date, range_location_id=location.id, required_count=1,
    )
    earlier_assignment = add_range_assignment(app_session, event=earlier_event, soldier_id=soldier.id, is_reserve=False)
    later_assignment = add_range_assignment(app_session, event=later_event, soldier_id=soldier.id, is_reserve=False)
    mark_attendance(app_session, assignment=earlier_assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)
    mark_attendance(app_session, assignment=later_assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)
    app_session.refresh(soldier)
    assert soldier.last_mitvahim_date == later_date

    mark_attendance(
        app_session, assignment=later_assignment, status=RangeAttendanceStatus.no_show,
        marked_by=soldier.id, note="תיקון",
    )

    app_session.refresh(soldier)
    assert soldier.last_mitvahim_date == earlier_date


def test_reversal_leaves_date_untouched_when_no_present_attendance_remains(app_session: Session) -> None:
    apply_settings(app_session, {}, {"mitvachim.laser_validity_days": 180}, actor_id=None)
    event_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=event_date)
    manual_date = date.today() - timedelta(days=500)
    soldier.last_mitvahim_date = manual_date
    app_session.flush()
    mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)
    app_session.refresh(soldier)
    assert soldier.last_mitvahim_date == event_date  # advanced past the manual value

    mark_attendance(
        app_session, assignment=assignment, status=RangeAttendanceStatus.no_show,
        marked_by=soldier.id, note="תיקון",
    )

    app_session.refresh(soldier)
    assert soldier.last_mitvahim_date == event_date  # no remaining present attendance -> left untouched


def test_synced_mitvahim_date_satisfies_legacy_eligibility_check(app_session: Session) -> None:
    """Regression test for the actual point of this feature: a date synced from
    real range attendance must be read by the existing legacy eligibility check
    exactly like a manually-entered date would be."""
    from app.services.eligibility import DutyTypeRequirements, _is_eligible

    apply_settings(app_session, {}, {"mitvachim.laser_validity_days": 180}, actor_id=None)
    event_date = date.today() - timedelta(days=1)
    event, soldier, assignment = _setup_event_and_assignment(app_session, event_date=event_date)
    reqs = DutyTypeRequirements(requires_mitvahim=True)

    assert _is_eligible(soldier, reqs, mitvahim_months=6, alal_months=3, today=date.today()) is False

    mark_attendance(app_session, assignment=assignment, status=RangeAttendanceStatus.present, marked_by=soldier.id)
    app_session.refresh(soldier)

    assert _is_eligible(soldier, reqs, mitvahim_months=6, alal_months=3, today=date.today()) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest backend/tests/unit/test_range_attendance.py -k "advances_last or move_last_mitvahim_backward or advances_last_alal or reversal_recomputes or reversal_leaves or synced_mitvahim_date" -v`
Expected: FAIL — `soldier.last_mitvahim_date`/`last_alal_date` stay unset because `mark_attendance` doesn't sync them yet.

- [ ] **Step 3: Implement the sync helpers and wire them into `mark_attendance`**

In `backend/app/services/ranges.py`, add these two helpers directly above `def mark_attendance(` (i.e. right after `_direct_commander_id`, before line 543):

```python
_MITVAHIM_RANGE_TYPES = (RangeType.laser, RangeType.live)


def _profile_date_field_for_range_type(range_type: str) -> str:
    return "last_alal_date" if range_type == RangeType.alal else "last_mitvahim_date"


def _sync_profile_date_on_present(soldier: Soldier, *, range_type: str, event_date: date) -> None:
    field = _profile_date_field_for_range_type(range_type)
    current = getattr(soldier, field)
    if current is None or event_date > current:
        setattr(soldier, field, event_date)


def _resync_profile_date_on_reversal(session: Session, *, soldier: Soldier, range_type: str) -> None:
    field = _profile_date_field_for_range_type(range_type)
    types = (RangeType.alal,) if range_type == RangeType.alal else _MITVAHIM_RANGE_TYPES
    latest = session.execute(
        select(func.max(RangeEvent.date))
        .join(RangeAssignment, RangeAssignment.range_event_id == RangeEvent.id)
        .where(
            RangeAssignment.soldier_id == soldier.id,
            RangeAssignment.attendance_status == RangeAttendanceStatus.present,
            RangeEvent.range_type.in_(types),
        )
    ).scalar_one_or_none()
    if latest is not None:
        setattr(soldier, field, latest)
```

Then modify `mark_attendance` itself. First, fetch the soldier right after the
event is validated — change:

```python
    if event.date > date.today():
        raise RangeValidationError("event_not_yet_occurred")

    previous_status = assignment.attendance_status
```

to:

```python
    if event.date > date.today():
        raise RangeValidationError("event_not_yet_occurred")

    soldier = session.get(Soldier, assignment.soldier_id)
    previous_status = assignment.attendance_status
```

Then wire the reversal hook — change:

```python
    if previous_status == RangeAttendanceStatus.present:
        _delete_qualification_from_this_assignment(session, assignment=assignment)

    # Apply the new side effect.
    if status == RangeAttendanceStatus.present:
        valid_until = event.date + timedelta(days=_validity_days(session, event.range_type))
        _record_qualification(
            session, soldier_id=assignment.soldier_id, range_type=event.range_type,
            valid_until=valid_until, source_range_assignment_id=assignment.id,
        )
```

to:

```python
    if previous_status == RangeAttendanceStatus.present:
        _delete_qualification_from_this_assignment(session, assignment=assignment)
        _resync_profile_date_on_reversal(session, soldier=soldier, range_type=event.range_type)

    # Apply the new side effect.
    if status == RangeAttendanceStatus.present:
        valid_until = event.date + timedelta(days=_validity_days(session, event.range_type))
        _record_qualification(
            session, soldier_id=assignment.soldier_id, range_type=event.range_type,
            valid_until=valid_until, source_range_assignment_id=assignment.id,
        )
        _sync_profile_date_on_present(soldier, range_type=event.range_type, event_date=event.date)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest backend/tests/unit/test_range_attendance.py -v`
Expected: PASS (all tests in the file, including the pre-existing ones — confirms no regression).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ranges.py backend/tests/unit/test_range_attendance.py
git commit -m "feat: sync last_mitvahim_date/last_alal_date from real range attendance"
```

---

### Task 2: Proactive expiry notification worker

**Files:**
- Modify: `backend/app/db/models.py` (add 4 `NotificationType` values, ~line 1259)
- Create: `backend/alembic/versions/b7c8d9e0f1a2_add_qualification_expiry_notification_types.py`
- Modify: `backend/app/services/notifications.py` (add 4 wrapper functions, after `notify_rank_advancement_soon`)
- Create: `backend/app/qualification_expiry_worker.py`
- Modify: `backend/app/main.py` (register the new worker task)
- Test: `backend/tests/unit/test_qualification_expiry_worker.py`

**Interfaces:**
- Consumes: `Soldier.last_mitvahim_date` / `Soldier.last_alal_date` (kept in sync by Task 1, but this task's tests set them directly — no runtime dependency on Task 1), `is_alal_relevant(session, soldier) -> bool` (`app/services/alal_relevance.py`), `get_setting_int(session, key, default) -> int` (`app/services/settings_loader.py`), `create_notification(...)` (`app/services/notifications.py`), `session_scope()` (`app/db/session.py`).
- Produces: `run_qualification_expiry_worker() -> Awaitable[None]` (registered as an `asyncio.create_task` in `main.py`, mirroring the other workers there) — nothing else depends on this task's output.

- [ ] **Step 1: Add the new `NotificationType` values**

In `backend/app/db/models.py`, change:

```python
    rank_advanced = "rank_advanced"
    rank_advancement_soon = "rank_advancement_soon"


class Notification(Base):
```

to:

```python
    rank_advanced = "rank_advanced"
    rank_advancement_soon = "rank_advancement_soon"
    mitvahim_expiring_soon = "mitvahim_expiring_soon"
    mitvahim_expired = "mitvahim_expired"
    alal_expiring_soon = "alal_expiring_soon"
    alal_expired = "alal_expired"


class Notification(Base):
```

- [ ] **Step 2: Add the Alembic migration for the enum values**

Create `backend/alembic/versions/b7c8d9e0f1a2_add_qualification_expiry_notification_types.py`:

```python
"""add qualification expiry notification types

Revision ID: b7c8d9e0f1a2
Revises: c7e8f9a0b1c2
Create Date: 2026-08-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = 'c7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'mitvahim_expiring_soon'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'mitvahim_expired'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'alal_expiring_soon'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'alal_expired'")


def downgrade() -> None:
    # Postgres cannot drop enum values; matches the existing repo convention
    # (see db05bb8f7744_add_rank_advancement.py) of not reversing
    # ALTER TYPE ... ADD VALUE in downgrade.
    pass
```

Run: `cd backend && alembic upgrade head`
Expected: migration applies with no errors; `alembic current` now shows `b7c8d9e0f1a2 (head)`.

- [ ] **Step 3: Add the notification wrapper functions**

In `backend/app/services/notifications.py`, immediately after `notify_rank_advancement_soon` (end of file), add:

```python
def notify_mitvahim_expiring_soon(
    session: Session, *, soldier_id: uuid.UUID, expiry_date: date, actor_id: uuid.UUID | None = None
) -> None:
    create_notification(
        session,
        soldier_id=soldier_id,
        type=NotificationType.mitvahim_expiring_soon,
        title=f"תוקף המטווחים פג בתאריך {expiry_date.strftime('%d.%m.%Y')}",
        actor_id=actor_id,
    )


def notify_mitvahim_expired(
    session: Session, *, soldier_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    create_notification(
        session,
        soldier_id=soldier_id,
        type=NotificationType.mitvahim_expired,
        title="תוקף המטווחים פג",
        actor_id=actor_id,
    )


def notify_alal_expiring_soon(
    session: Session, *, soldier_id: uuid.UUID, expiry_date: date, actor_id: uuid.UUID | None = None
) -> None:
    create_notification(
        session,
        soldier_id=soldier_id,
        type=NotificationType.alal_expiring_soon,
        title=f'תוקף האל"ל פג בתאריך {expiry_date.strftime("%d.%m.%Y")}',
        actor_id=actor_id,
    )


def notify_alal_expired(
    session: Session, *, soldier_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    create_notification(
        session,
        soldier_id=soldier_id,
        type=NotificationType.alal_expired,
        title='תוקף האל"ל פג',
        actor_id=actor_id,
    )
```

- [ ] **Step 4: Write the failing worker tests**

Create `backend/tests/unit/test_qualification_expiry_worker.py`:

```python
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy.orm import sessionmaker

from app.db.models import Notification, NotificationType, Soldier
from app.qualification_expiry_worker import (
    _check_alal_expiry,
    _check_mitvahim_expiry,
    run_qualification_expiry_worker,
)
from app.services.settings_loader import set_setting
from tests.helpers import create_soldier


def test_worker_calls_both_checks_each_cycle() -> None:
    with patch("app.qualification_expiry_worker._check_mitvahim_expiry") as mock_mitvahim, \
         patch("app.qualification_expiry_worker._check_alal_expiry") as mock_alal, \
         patch("app.qualification_expiry_worker.asyncio.sleep", side_effect=[None, asyncio.CancelledError]):
        try:
            asyncio.run(run_qualification_expiry_worker())
        except asyncio.CancelledError:
            pass
    mock_mitvahim.assert_called_once()
    mock_alal.assert_called_once()


def test_check_mitvahim_expiry_notifies_at_exact_warn_day(app_session) -> None:
    set_setting(app_session, "home.mitvahim_validity_days", 180, actor_id=None)
    set_setting(app_session, "home.mitvahim_warn_days", 30, actor_id=None)
    s = create_soldier(app_session, personal_number="1000101")
    s.last_mitvahim_date = date(2026, 1, 1)  # expiry = 2026-06-30; today+30 = 2026-06-30
    app_session.commit()

    with patch("app.qualification_expiry_worker.session_scope") as mock_scope, \
         patch("app.qualification_expiry_worker.date") as mock_date:
        mock_scope.return_value.__enter__.return_value = app_session
        mock_date.today.return_value = date(2026, 5, 31)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        _check_mitvahim_expiry()

    notif = app_session.query(Notification).filter(
        Notification.soldier_id == s.id,
        Notification.type == NotificationType.mitvahim_expiring_soon,
    ).one_or_none()
    assert notif is not None


def test_check_mitvahim_expiry_notifies_expired_on_exact_expiry_day(app_session) -> None:
    set_setting(app_session, "home.mitvahim_validity_days", 180, actor_id=None)
    set_setting(app_session, "home.mitvahim_warn_days", 30, actor_id=None)
    s = create_soldier(app_session, personal_number="1000102")
    s.last_mitvahim_date = date(2026, 1, 1)  # expiry = 2026-06-30
    app_session.commit()

    with patch("app.qualification_expiry_worker.session_scope") as mock_scope, \
         patch("app.qualification_expiry_worker.date") as mock_date:
        mock_scope.return_value.__enter__.return_value = app_session
        mock_date.today.return_value = date(2026, 6, 30)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        _check_mitvahim_expiry()

    notif = app_session.query(Notification).filter(
        Notification.soldier_id == s.id,
        Notification.type == NotificationType.mitvahim_expired,
    ).one_or_none()
    assert notif is not None


def test_check_mitvahim_expiry_does_not_notify_outside_exact_days(app_session) -> None:
    set_setting(app_session, "home.mitvahim_validity_days", 180, actor_id=None)
    set_setting(app_session, "home.mitvahim_warn_days", 30, actor_id=None)
    s = create_soldier(app_session, personal_number="1000103")
    s.last_mitvahim_date = date(2026, 1, 1)  # expiry = 2026-06-30
    app_session.commit()

    with patch("app.qualification_expiry_worker.session_scope") as mock_scope, \
         patch("app.qualification_expiry_worker.date") as mock_date:
        mock_scope.return_value.__enter__.return_value = app_session
        mock_date.today.return_value = date(2026, 5, 1)  # neither warn-day nor expiry-day
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        _check_mitvahim_expiry()

    count = app_session.query(Notification).filter(
        Notification.soldier_id == s.id,
        Notification.type.in_([NotificationType.mitvahim_expiring_soon, NotificationType.mitvahim_expired]),
    ).count()
    assert count == 0


def test_check_mitvahim_expiry_skips_departed_soldiers(app_session) -> None:
    set_setting(app_session, "home.mitvahim_validity_days", 180, actor_id=None)
    set_setting(app_session, "home.mitvahim_warn_days", 30, actor_id=None)
    s = create_soldier(app_session, personal_number="1000104")
    s.last_mitvahim_date = date(2026, 1, 1)
    s.left_at = date(2026, 2, 1)
    app_session.commit()

    with patch("app.qualification_expiry_worker.session_scope") as mock_scope, \
         patch("app.qualification_expiry_worker.date") as mock_date:
        mock_scope.return_value.__enter__.return_value = app_session
        mock_date.today.return_value = date(2026, 6, 30)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        _check_mitvahim_expiry()

    count = app_session.query(Notification).filter(Notification.soldier_id == s.id).count()
    assert count == 0


def test_check_alal_expiry_skips_soldiers_who_are_not_alal_relevant(app_session) -> None:
    set_setting(app_session, "home.alal_validity_days", 90, actor_id=None)
    set_setting(app_session, "home.alal_warn_days", 30, actor_id=None)
    s = create_soldier(app_session, personal_number="1000105")
    s.last_alal_date = date(2026, 1, 1)  # expiry = 2026-04-01
    app_session.commit()

    with patch("app.qualification_expiry_worker.session_scope") as mock_scope, \
         patch("app.qualification_expiry_worker.date") as mock_date, \
         patch("app.qualification_expiry_worker.is_alal_relevant", return_value=False):
        mock_scope.return_value.__enter__.return_value = app_session
        mock_date.today.return_value = date(2026, 4, 1)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        _check_alal_expiry()

    notif = app_session.query(Notification).filter(
        Notification.soldier_id == s.id,
        Notification.type == NotificationType.alal_expired,
    ).one_or_none()
    assert notif is None


def test_check_alal_expiry_notifies_relevant_soldier_on_expiry_day(app_session) -> None:
    set_setting(app_session, "home.alal_validity_days", 90, actor_id=None)
    set_setting(app_session, "home.alal_warn_days", 30, actor_id=None)
    s = create_soldier(app_session, personal_number="1000106")
    s.last_alal_date = date(2026, 1, 1)  # expiry = 2026-04-01
    app_session.commit()

    with patch("app.qualification_expiry_worker.session_scope") as mock_scope, \
         patch("app.qualification_expiry_worker.date") as mock_date, \
         patch("app.qualification_expiry_worker.is_alal_relevant", return_value=True):
        mock_scope.return_value.__enter__.return_value = app_session
        mock_date.today.return_value = date(2026, 4, 1)
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        _check_alal_expiry()

    notif = app_session.query(Notification).filter(
        Notification.soldier_id == s.id,
        Notification.type == NotificationType.alal_expired,
    ).one_or_none()
    assert notif is not None


def test_check_mitvahim_expiry_commits_and_persists_after_session_close(app_session, app_engine) -> None:
    """Regression coverage for a missing session.commit(), mirroring the
    equivalent rank_advancement_worker test: calls the REAL (unmocked)
    _check_mitvahim_expiry, which opens its own session via the real
    session_scope() and must commit before returning."""
    s = create_soldier(app_session, personal_number="1000107")
    s.last_mitvahim_date = date.today() - timedelta(days=180)  # expires today with default 180-day validity
    app_session.commit()
    soldier_id = s.id

    _check_mitvahim_expiry()  # real session_scope() -- not mocked/patched

    FreshSession = sessionmaker(bind=app_engine, expire_on_commit=False)
    with FreshSession() as fresh:
        notif = fresh.query(Notification).filter(
            Notification.soldier_id == soldier_id,
            Notification.type == NotificationType.mitvahim_expired,
        ).one_or_none()
        assert notif is not None
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `pytest backend/tests/unit/test_qualification_expiry_worker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.qualification_expiry_worker'`.

- [ ] **Step 6: Implement the worker**

Create `backend/app/qualification_expiry_worker.py`:

```python
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from sqlalchemy import select

from app.db.models import Soldier
from app.db.session import session_scope
from app.services.alal_relevance import is_alal_relevant
from app.services.notifications import (
    notify_alal_expired,
    notify_alal_expiring_soon,
    notify_mitvahim_expired,
    notify_mitvahim_expiring_soon,
)
from app.services.settings_loader import get_setting_int

logger = logging.getLogger(__name__)

_POLL_SECONDS = 86400


def _active_soldiers_with_date(session, *, date_column, today: date):
    return session.execute(
        select(Soldier).where(
            date_column.is_not(None),
            Soldier.discharge_date.is_(None) | (Soldier.discharge_date > today),
            Soldier.left_at.is_(None) | (Soldier.left_at > today),
        )
    ).scalars().all()


def _check_mitvahim_expiry() -> None:
    today = date.today()
    with session_scope() as session:
        validity_days = get_setting_int(session, "home.mitvahim_validity_days", 180)
        warn_days = get_setting_int(session, "home.mitvahim_warn_days", 30)
        soldiers = _active_soldiers_with_date(session, date_column=Soldier.last_mitvahim_date, today=today)
        for s in soldiers:
            expiry = s.last_mitvahim_date + timedelta(days=validity_days)
            if expiry == today + timedelta(days=warn_days):
                notify_mitvahim_expiring_soon(session, soldier_id=s.id, expiry_date=expiry)
            elif expiry == today:
                notify_mitvahim_expired(session, soldier_id=s.id)
        session.commit()


def _check_alal_expiry() -> None:
    today = date.today()
    with session_scope() as session:
        validity_days = get_setting_int(session, "home.alal_validity_days", 90)
        warn_days = get_setting_int(session, "home.alal_warn_days", 30)
        soldiers = _active_soldiers_with_date(session, date_column=Soldier.last_alal_date, today=today)
        for s in soldiers:
            if not is_alal_relevant(session, s):
                continue
            expiry = s.last_alal_date + timedelta(days=validity_days)
            if expiry == today + timedelta(days=warn_days):
                notify_alal_expiring_soon(session, soldier_id=s.id, expiry_date=expiry)
            elif expiry == today:
                notify_alal_expired(session, soldier_id=s.id)
        session.commit()


async def run_qualification_expiry_worker() -> None:
    while True:
        await asyncio.sleep(_POLL_SECONDS)
        try:
            await asyncio.to_thread(_check_mitvahim_expiry)
            await asyncio.to_thread(_check_alal_expiry)
        except Exception:
            logger.warning("qualification expiry worker: unhandled error", exc_info=True)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest backend/tests/unit/test_qualification_expiry_worker.py -v`
Expected: PASS (all 8 tests).

- [ ] **Step 8: Register the worker in `main.py`**

In `backend/app/main.py`, add the import alongside the other worker imports:

```python
from app.rank_advancement_worker import run_rank_advancement_worker
from app.range_reminder_worker import run_range_reminder_worker
```

becomes:

```python
from app.qualification_expiry_worker import run_qualification_expiry_worker
from app.rank_advancement_worker import run_rank_advancement_worker
from app.range_reminder_worker import run_range_reminder_worker
```

Then in the `lifespan` function, change:

```python
    rank_advancement_task = asyncio.create_task(run_rank_advancement_worker())
    yield
    for task in (email_task, swap_expiry_task, range_reminder_task, range_attendance_task, duty_eligibility_task, rank_advancement_task):
        task.cancel()
    for task in (email_task, swap_expiry_task, range_reminder_task, range_attendance_task, duty_eligibility_task, rank_advancement_task):
```

to:

```python
    rank_advancement_task = asyncio.create_task(run_rank_advancement_worker())
    qualification_expiry_task = asyncio.create_task(run_qualification_expiry_worker())
    yield
    for task in (email_task, swap_expiry_task, range_reminder_task, range_attendance_task, duty_eligibility_task, rank_advancement_task, qualification_expiry_task):
        task.cancel()
    for task in (email_task, swap_expiry_task, range_reminder_task, range_attendance_task, duty_eligibility_task, rank_advancement_task, qualification_expiry_task):
```

- [ ] **Step 9: Run the full backend suite**

Run: `pytest -q`
Expected: PASS, no regressions (existing count plus the 6 new Task 1 tests and 8 new Task 2 tests).

- [ ] **Step 10: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/b7c8d9e0f1a2_add_qualification_expiry_notification_types.py backend/app/services/notifications.py backend/app/qualification_expiry_worker.py backend/app/main.py backend/tests/unit/test_qualification_expiry_worker.py
git commit -m "feat: notify soldiers and commanders as מטווחים/אל\"ל qualifications approach or pass expiry"
```
