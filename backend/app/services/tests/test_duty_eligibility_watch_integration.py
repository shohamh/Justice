# backend/app/services/tests/test_duty_eligibility_watch_integration.py
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment, DutyLocation, DutyShift, DutyType, RangeAttendanceStatus, RangeType,
)
from app.services.range_excusal import decide_primary_excusal, request_primary_excusal, request_reserve_excusal
from app.services.ranges import add_range_assignment, create_range_event, mark_attendance
from app.services.settings_loader import set_setting
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
        status="published",
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def test_mark_attendance_no_show_triggers_recheck(app_session: Session) -> None:
    # mitvachim.enabled defaults to False (weapon-eligibility enforcement off in
    # production until explicitly enabled) -- must opt in explicitly, matching
    # the convention in test_duty_eligibility_watch.py / test_weapon_eligibility.py.
    set_setting(app_session, "mitvachim.enabled", True, actor_id=None)
    node = create_node(app_session, level="branch", name="watchint-node-1")
    soldier = create_soldier(app_session, personal_number="watchint-sol-1", hierarchy_node_id=node.id)

    # The weapon-requiring duty type must exist before add_range_assignment is
    # called: is_range_exempt() treats a soldier as structurally exempt from
    # ranges entirely when no weapon-requiring duty type is eligible for their
    # node yet, which would otherwise make the range assignment below fail
    # with "soldier_range_exempt".
    duty_assignment = _make_weapon_assignment(
        app_session, soldier_id=soldier.id, node_id=node.id, start_date=date.today() + timedelta(days=5),
    )
    assert duty_assignment.weapon_ineligible is False

    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() - timedelta(days=1),
        range_location_id=create_range_location(app_session).id, required_count=1,
    )
    range_assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    app_session.commit()

    mark_attendance(
        app_session, assignment=range_assignment, status=RangeAttendanceStatus.no_show, note="בדיקה",
    )

    app_session.refresh(duty_assignment)
    assert duty_assignment.weapon_ineligible is True


def test_request_reserve_excusal_triggers_recheck(app_session: Session) -> None:
    set_setting(app_session, "mitvachim.enabled", True, actor_id=None)
    node = create_node(app_session, level="branch", name="watchint-node-2")
    soldier = create_soldier(app_session, personal_number="watchint-sol-2", hierarchy_node_id=node.id)

    # Same ordering requirement as above: the weapon-requiring duty type must
    # exist before add_range_assignment, or the soldier is structurally
    # range-exempt and the assignment creation itself fails.
    duty_assignment = _make_weapon_assignment(
        app_session, soldier_id=soldier.id, node_id=node.id, start_date=date.today() + timedelta(days=5),
    )
    assert duty_assignment.weapon_ineligible is False

    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=2),
        range_location_id=create_range_location(app_session).id, required_count=1, reserve_count=1,
    )
    # request_reserve_excusal is the reserve soldier's self-service excusal path
    # (RangeValidationError("assignment_is_primary") if the assignment isn't a
    # reserve slot), so the assignment must be created with is_reserve=True.
    range_assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=True)
    app_session.commit()

    request_reserve_excusal(
        app_session, assignment=range_assignment, reason="בדיקה", requested_by=soldier.id,
    )
    app_session.commit()
    app_session.refresh(duty_assignment)
    assert duty_assignment.weapon_ineligible is True


def test_decide_primary_excusal_approval_rechecks_excused_and_promoted_soldiers(app_session: Session) -> None:
    set_setting(app_session, "mitvachim.enabled", True, actor_id=None)
    node = create_node(app_session, level="branch", name="watchint-node-3")
    excused_soldier = create_soldier(app_session, personal_number="watchint-sol-3", hierarchy_node_id=node.id)
    promoted_soldier = create_soldier(app_session, personal_number="watchint-sol-4", hierarchy_node_id=node.id)

    excused_duty = _make_weapon_assignment(
        app_session, soldier_id=excused_soldier.id, node_id=node.id, start_date=date.today() + timedelta(days=5),
    )
    assert excused_duty.weapon_ineligible is False

    promoted_duty = _make_weapon_assignment(
        app_session, soldier_id=promoted_soldier.id, node_id=node.id, start_date=date.today() + timedelta(days=5),
    )
    # Simulate a stale cached ineligibility for the reserve soldier, so the
    # promotion's recheck has something to actually flip -- proving the hook
    # rechecks the promoted soldier, not just the excused one.
    promoted_duty.weapon_ineligible = True
    promoted_duty.weapon_ineligible_reason = "stale"
    app_session.commit()

    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=2),
        range_location_id=create_range_location(app_session).id, required_count=1, reserve_count=1,
    )
    primary_assignment = add_range_assignment(
        app_session, event=event, soldier_id=excused_soldier.id, is_reserve=False,
    )
    reserve_assignment = add_range_assignment(
        app_session, event=event, soldier_id=promoted_soldier.id, is_reserve=True,
    )
    app_session.commit()

    request = request_primary_excusal(
        app_session, assignment=primary_assignment, reason="בדיקה", requested_by=excused_soldier.id,
    )
    app_session.commit()

    decide_primary_excusal(app_session, request=request, approve=True, decided_by=excused_soldier.id)

    # The excused soldier's only source of weapon eligibility (their own future
    # range assignment) was just removed -> now ineligible.
    app_session.refresh(excused_duty)
    assert excused_duty.weapon_ineligible is True

    # The promoted reserve now holds the primary slot for that same future
    # event -> the stale ineligibility cache gets cleared.
    app_session.refresh(promoted_duty)
    assert promoted_duty.weapon_ineligible is False
