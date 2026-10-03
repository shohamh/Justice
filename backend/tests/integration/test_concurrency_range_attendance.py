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


def test_attendance_correction_and_duty_dismissal_of_one_soldier_do_not_deadlock(race, admin_session):
    """I1 — ``mark_attendance`` locks the soldier and the range assignment,
    refreshes the score projection (``create_adjustment`` for a no-show) and
    only then lets ``recheck_assignments`` UPDATE the soldier's published duty
    assignments. ``dismiss_primary`` on one of those duties locks the duty row
    first and then refreshes the projection: the reverse order.

    Schedule: the attendance mark holds the projection rows; the dismissal
    holds the duty row; each then waits for the other's lock.

    Fixed: ``mark_attendance`` locks the soldier's published duty assignments
    (id order, ``FOR NO KEY UPDATE``) right after the range assignment, before
    any projection lock (soldier -> range assignment -> duty assignments ->
    projection)."""
    from app.db.models import (
        DutyAssignment,
        DutyDismissal,
        DutyLocation,
        ScoreProjectionQuarterTotal,
    )
    from app.services import reserves as reserves_service

    assignment_id, soldier_id, manager_id = _seed(admin_session, "i1")
    dt = DutyType(name="race-att-i1 plain", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="race-att-i1 loc")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    start = date.today() + timedelta(days=30)
    duty = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=dt.id, duty_location_id=loc.id, start_date=start,
        end_date=start + timedelta(days=5), status="published", is_reserve=False,
        # A stale cached warning: recheck_assignments clears it, so it UPDATEs this row.
        weapon_ineligible=True,
    )
    admin_session.add(duty)
    admin_session.commit()
    duty_id = duty.id

    attendance_holds_projection = race.signal("attendance mark holds the projection rows")
    dismissal_holds_duty = race.signal("dismissal holds the duty row")

    def mark_no_show():
        s = race.session()

        def _after_total_lock():
            attendance_holds_projection.set()
            dismissal_holds_duty.wait()

        race.pause_after_select(s, ScoreProjectionQuarterTotal, _after_total_lock)
        return ranges_service.mark_attendance(
            s, assignment=s.get(RangeAssignment, assignment_id), status=RangeAttendanceStatus.no_show,
            marked_by=manager_id, note="לא הגיע",
        ).attendance_status

    def dismiss():
        attendance_holds_projection.wait()
        s = race.session()
        d = s.get(DutyAssignment, duty_id)
        race.pause_after_select(s, DutyDismissal, dismissal_holds_duty.set)
        reserves_service.dismiss_primary(
            s, assignment=d, from_date=start + timedelta(days=1), to_date=start + timedelta(days=2),
            reason=None, actor_id=manager_id,
        )
        s.commit()

    outcomes = race.run(mark_no_show, dismiss)

    assert all(o.ok for o in outcomes), f"outcomes={outcomes}"
    admin_session.expire_all()
    assert admin_session.get(RangeAssignment, assignment_id).attendance_status == RangeAttendanceStatus.no_show
    assert admin_session.get(DutyAssignment, duty_id).weapon_ineligible is False


def test_auto_mark_releases_locks_after_a_validation_error(race, admin_session, monkeypatch):
    """Auto-mark residual — after ``lock_assignment_for_attendance`` the worker
    calls ``mark_attendance``; on ``RangeValidationError`` it logged and
    ``continue``d without a rollback, so the soldier and range-assignment locks
    of the skipped row stayed held while the sweep went on with the next row.

    Fixed: the worker rolls back before ``continue``. The probe (an independent
    session, ``FOR UPDATE NOWAIT``) runs while the worker handles the second
    assignment and checks the first soldier's row is free again."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    from app.services import range_attendance_auto_mark as auto_mark_module

    first_id, first_soldier_id, _manager_id = _seed(admin_session, "rollback")
    first = admin_session.get(RangeAssignment, first_id)
    other = create_soldier(admin_session, personal_number="race-att-rollback-s2")
    admin_session.add(RangeAssignment(range_event_id=first.range_event_id, soldier_id=other.id))
    admin_session.commit()

    real_mark = auto_mark_module.mark_attendance
    calls: list = []
    probe: dict[str, str] = {}

    def mark(session, *, assignment, **kwargs):
        calls.append(assignment.soldier_id)
        if len(calls) == 1:
            raise ranges_service.RangeValidationError("injected")
        s = race.session()
        try:
            s.execute(text("SELECT id FROM soldiers WHERE id = :id FOR UPDATE NOWAIT"), {"id": calls[0]})
            probe["first_soldier"] = "free"
        except OperationalError:
            probe["first_soldier"] = "held"
        finally:
            s.rollback()
        return real_mark(session, assignment=assignment, **kwargs)

    monkeypatch.setattr(auto_mark_module, "mark_attendance", mark)

    s = race.session()
    marked = auto_mark_present_for_elapsed_events(s)

    assert marked == 1
    assert len(calls) == 2
    assert probe["first_soldier"] == "free", "the skipped assignment's soldier lock was still held"
    admin_session.expire_all()
    statuses = sorted(
        admin_session.execute(
            select(RangeAssignment.attendance_status).where(RangeAssignment.range_event_id == first.range_event_id)
        ).scalars().all()
    )
    assert statuses == sorted([RangeAttendanceStatus.pending, RangeAttendanceStatus.present])
