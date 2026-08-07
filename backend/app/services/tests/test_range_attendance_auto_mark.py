from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyType, RangeAttendanceStatus, RangeEventStatus, RangeType, SoldierRangeQualification
from app.services.range_attendance_auto_mark import auto_mark_present_for_elapsed_events
from app.services.ranges import add_range_assignment, cancel_range_event, create_range_event
from app.services.settings_loader import apply_settings
from tests.helpers import create_node, create_range_location, create_soldier


def _event(session: Session, *, event_date: date, reserve_count: int = 1):
    node = create_node(session, level="branch", name=f"auto-mark-{event_date}")
    location = create_range_location(session, name="auto-mark-loc")
    # Create a weapon duty type to make soldiers eligible for range events
    weapon_duty = DutyType(
        name=f"weapon-duty-{event_date}", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    session.add(weapon_duty)
    session.commit()
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
