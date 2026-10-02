"""C16/R8 — range attendance auto-mark races (audit inventory R8).

``auto_mark_present_for_elapsed_events`` (run by every web worker process)
SELECTs the still-``pending`` primary assignments of elapsed events and calls
``mark_attendance`` on each loaded row. ``mark_attendance`` decides from the
row object it was handed (``previous_status``) and takes no lock, so:

* two workers that both loaded the row as ``pending`` both mark it present
  and both record a range qualification for it;
* a manual ``no_show`` committed after the worker's SELECT is overwritten
  with ``present`` without reversing its no-show penalty.

Schedules (two independent sessions), each meeting right after the worker's
SELECT of pending assignments.

Fixed (Task 4): ``mark_attendance`` starts with
``lock_assignment_for_attendance`` (soldier, then assignment, fresh read), and
the auto-mark worker re-checks ``pending`` on that locked row, skipping an
assignment someone else already decided.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.db.models import (
    DutyType,
    RangeAssignment,
    RangeAttendanceStatus,
    RangeEvent,
    RangeType,
    ScoreAdjustment,
    SoldierRangeQualification,
    SystemSetting,
)
from app.services import ranges as ranges_service
from app.services.range_attendance_auto_mark import auto_mark_present_for_elapsed_events
from tests.helpers import create_node, create_range_location, create_soldier


def _seed(session, tag):
    session.add(SystemSetting(key="mitvachim.enabled", value=True))
    node = create_node(session, level="branch", name=f"race-att-{tag}")
    session.add(DutyType(name=f"race-att-{tag} weapon", score_per_day=Decimal("1.00"),
                         requires_weapon=True, eligible_node_ids=[node.id]))
    soldier = create_soldier(session, personal_number=f"race-att-{tag}-s", hierarchy_node_id=node.id)
    manager = create_soldier(session, personal_number=f"race-att-{tag}-dm", role="admin")
    event = RangeEvent(
        hierarchy_node_id=node.id, range_type=RangeType.laser, date=date.today() - timedelta(days=1),
        range_location_id=create_range_location(session, name=f"race-att-{tag} range").id,
        required_count=1, reserve_count=0,
    )
    session.add(event)
    session.flush()
    assignment = RangeAssignment(range_event_id=event.id, soldier_id=soldier.id)
    session.add(assignment)
    session.commit()
    return assignment.id, soldier.id, manager.id


def _auto_mark(race, hook):
    s = race.session()
    race.pause_after_select(s, RangeAssignment, hook)
    return auto_mark_present_for_elapsed_events(s)


def _qualifications(session, soldier_id):
    return session.execute(
        select(func.count()).select_from(SoldierRangeQualification)
        .where(SoldierRangeQualification.soldier_id == soldier_id)
    ).scalar_one()


def test_concurrent_auto_mark_workers_record_one_qualification(race, admin_session):
    assignment_id, soldier_id, _manager_id = _seed(admin_session, "dup")
    after_select = race.rendezvous(2, "both workers loaded the pending assignment")

    outcomes = race.run(lambda: _auto_mark(race, after_select.wait), lambda: _auto_mark(race, after_select.wait))

    for outcome in outcomes:
        if not outcome.ok:
            raise RuntimeError(f"worker crashed: {outcome.error!r}") from outcome.error
    admin_session.expire_all()
    count = _qualifications(admin_session, soldier_id)
    assert count == 1, f"{count} qualifications recorded for one attended range; marked={[o.value for o in outcomes]}"
    assert sorted(o.value for o in outcomes) == [0, 1]


def test_auto_mark_does_not_overwrite_a_manual_no_show(race, admin_session):
    assignment_id, soldier_id, manager_id = _seed(admin_session, "noshow")

    def manual_no_show(s):
        return ranges_service.mark_attendance(
            s, assignment=s.get(RangeAssignment, assignment_id), status=RangeAttendanceStatus.no_show,
            marked_by=manager_id, note="לא הגיע",
        ).attendance_status

    worker_read = race.signal("worker loaded the pending assignment")
    manual_done = race.signal("manual no-show committed")

    def worker():
        def _after_select():
            worker_read.set()
            manual_done.wait()
        return _auto_mark(race, _after_select)

    def manual():
        worker_read.wait()
        try:
            return manual_no_show(race.session())
        finally:
            manual_done.set()

    worker_outcome, manual_outcome = race.run(worker, manual)

    for outcome in (worker_outcome, manual_outcome):
        if not outcome.ok:
            raise RuntimeError(f"racer crashed: {outcome.error!r}") from outcome.error
    admin_session.expire_all()
    assignment = admin_session.get(RangeAssignment, assignment_id)
    penalties = admin_session.execute(
        select(func.count()).select_from(ScoreAdjustment).where(ScoreAdjustment.soldier_id == soldier_id)
    ).scalar_one()
    assert assignment.attendance_status == RangeAttendanceStatus.no_show, (
        f"final status {assignment.attendance_status} with {penalties} no-show adjustment(s) and "
        f"{_qualifications(admin_session, soldier_id)} qualification(s)"
    )
    assert _qualifications(admin_session, soldier_id) == 0
    assert worker_outcome.value == 0
