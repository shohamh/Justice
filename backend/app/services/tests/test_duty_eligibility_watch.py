# backend/app/services/tests/test_duty_eligibility_watch.py
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import (
    CommanderNotificationScope, DutyAssignment, DutyLocation, DutyShift, DutyType, Notification, NotificationType,
    RangeAssignment, RangeEvent, RangeType, SoldierRangeQualification,
)
from app.services.duty_eligibility_watch import recheck_assignments
from app.services.settings_loader import set_setting
from tests.helpers import create_duty_location, create_node, create_range_location, create_soldier

# Keep planned-range fixtures safely inside weapon_eligibility's real today-based
# future window (mirrors test_range_eligibility_projection.py's AS_OF convention).
AS_OF = date.today() + timedelta(days=6)


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
        status="published",
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def test_transition_to_ineligible_updates_cache_and_notifies_exact_audience(app_session: Session) -> None:
    # mitvachim.enabled defaults to False (weapon-eligibility enforcement off in
    # production until explicitly enabled) -- must opt in explicitly, matching
    # the convention in test_weapon_eligibility.py.
    set_setting(app_session, "mitvachim.enabled", True, actor_id=None)
    parent = create_node(app_session, level="division", name="watch-parent-1")
    node = create_node(app_session, level="branch", name="watch-node-1", parent=parent)
    higher_commander = create_soldier(
        app_session, personal_number="watch-cmd-parent-1", hierarchy_node_id=parent.id,
    )
    parent.commander_id = higher_commander.id
    commander = create_soldier(app_session, personal_number="watch-cmd-1", hierarchy_node_id=node.id)
    node.commander_id = commander.id
    duty_manager = create_soldier(
        app_session, personal_number="watch-dm-1", role="duty_manager", hierarchy_node_id=node.id,
    )
    soldier = create_soldier(app_session, personal_number="watch-sol-1", hierarchy_node_id=node.id)
    app_session.add_all([
        CommanderNotificationScope(commander_id=commander.id, hierarchy_node_id=node.id),
        CommanderNotificationScope(commander_id=higher_commander.id, hierarchy_node_id=parent.id),
    ])
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
        Notification.type == NotificationType.weapon_ineligible_detected,
        Notification.reference_id == assignment.id,
    ).all()
    assert len(notifs) == 3
    assert {n.soldier_id for n in notifs} == {soldier.id, commander.id, duty_manager.id}


def test_transition_to_eligible_updates_cache_silently(app_session: Session) -> None:
    set_setting(app_session, "mitvachim.enabled", True, actor_id=None)
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
        status="published",
    )
    app_session.add(assignment)
    app_session.commit()

    changed = recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)
    assert changed == 0
    assert assignment.weapon_ineligible is False


def _make_info_duty_assignment(
    session: Session, *, soldier_id, node_id, start_date: date = AS_OF, required_range_type: str = RangeType.laser,
) -> DutyAssignment:
    set_setting(session, "mitvachim.enabled", True, actor_id=None)
    dt = DutyType(
        name=f"watch-info-{soldier_id}-{start_date.isoformat()}", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=required_range_type,
    )
    session.add(dt)
    session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=dt.id, duty_location_id=create_duty_location(session).id,
        start_date=start_date, end_date=start_date, status="published",
    )
    session.add(assignment)
    session.commit()
    session.refresh(assignment)
    return assignment


def _add_planned_range(
    session: Session, *, soldier_id, node_id, range_type: str, event_date: date,
) -> RangeAssignment:
    event = RangeEvent(
        hierarchy_node_id=node_id, range_type=range_type, date=event_date,
        range_location_id=create_range_location(session).id, required_count=1,
    )
    session.add(event)
    session.flush()
    assignment = RangeAssignment(
        range_event_id=event.id, soldier_id=soldier_id, is_reserve=False, is_draft=False,
    )
    session.add(assignment)
    session.commit()
    return assignment


def test_recheck_assignments_detects_new_info_signal(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="watch-info-node-1")
    soldier = create_soldier(app_session, personal_number="watch-info-sol-1", hierarchy_node_id=node.id)
    assignment = _make_info_duty_assignment(app_session, soldier_id=soldier.id, node_id=node.id)
    _add_planned_range(
        app_session, soldier_id=soldier.id, node_id=node.id,
        range_type=RangeType.laser, event_date=AS_OF - timedelta(days=1),
    )

    recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)

    assert assignment.range_info_active is True
    assert assignment.range_info_covering_range_type is not None
    assert assignment.range_info_detected_at is not None

    notif_types = {
        n.type for n in app_session.query(Notification).filter_by(soldier_id=assignment.soldier_id)
    }
    assert NotificationType.range_covers_duty_info in notif_types


def test_recheck_assignments_does_not_renotify_when_covering_range_unchanged(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="watch-info-node-2")
    soldier = create_soldier(app_session, personal_number="watch-info-sol-2", hierarchy_node_id=node.id)
    assignment = _make_info_duty_assignment(app_session, soldier_id=soldier.id, node_id=node.id)
    _add_planned_range(
        app_session, soldier_id=soldier.id, node_id=node.id,
        range_type=RangeType.laser, event_date=AS_OF - timedelta(days=1),
    )

    recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)
    first_detected_at = assignment.range_info_detected_at
    notif_count_after_first = app_session.query(Notification).filter_by(
        soldier_id=assignment.soldier_id, type=NotificationType.range_covers_duty_info,
    ).count()

    recheck_assignments(app_session, [assignment.id])  # nothing changed
    app_session.refresh(assignment)

    assert assignment.range_info_detected_at == first_detected_at
    notif_count_after_second = app_session.query(Notification).filter_by(
        soldier_id=assignment.soldier_id, type=NotificationType.range_covers_duty_info,
    ).count()
    assert notif_count_after_second == notif_count_after_first


def test_recheck_assignments_renotifies_when_covering_range_changes(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="watch-info-node-3")
    soldier = create_soldier(app_session, personal_number="watch-info-sol-3", hierarchy_node_id=node.id)
    assignment = _make_info_duty_assignment(app_session, soldier_id=soldier.id, node_id=node.id)
    first_range = _add_planned_range(
        app_session, soldier_id=soldier.id, node_id=node.id,
        range_type=RangeType.laser, event_date=AS_OF - timedelta(days=1),
    )

    recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)
    first_detected_at = assignment.range_info_detected_at

    # Move the soldier off the first RangeEvent's roster and onto a second one
    # whose window also covers the duty's start_date, so the covering range changes.
    app_session.delete(first_range)
    app_session.commit()
    _add_planned_range(
        app_session, soldier_id=soldier.id, node_id=node.id,
        range_type=RangeType.laser, event_date=AS_OF - timedelta(days=2),
    )

    recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)

    assert assignment.range_info_detected_at != first_detected_at
    notif_count = app_session.query(Notification).filter_by(
        soldier_id=assignment.soldier_id, type=NotificationType.range_covers_duty_info,
    ).count()
    assert notif_count == 2


def test_recheck_assignments_clears_info_signal_silently_when_no_longer_covered(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="watch-info-node-4")
    soldier = create_soldier(app_session, personal_number="watch-info-sol-4", hierarchy_node_id=node.id)
    assignment = _make_info_duty_assignment(app_session, soldier_id=soldier.id, node_id=node.id)
    planned = _add_planned_range(
        app_session, soldier_id=soldier.id, node_id=node.id,
        range_type=RangeType.laser, event_date=AS_OF - timedelta(days=1),
    )

    recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)
    assert assignment.range_info_active is True

    # Remove the covering RangeAssignment entirely (soldier no longer has any
    # planned range covering the duty, and no current qualification either).
    app_session.delete(planned)
    app_session.commit()

    recheck_assignments(app_session, [assignment.id])
    app_session.refresh(assignment)

    assert assignment.range_info_active is False
    assert assignment.range_info_covered_by_date is None
    assert assignment.range_info_covering_range_type is None
    # No NEW info notification should have been created for the clearing --
    # count stays at 1 (from the initial detection only).
    notif_count = app_session.query(Notification).filter_by(
        soldier_id=assignment.soldier_id, type=NotificationType.range_covers_duty_info,
    ).count()
    assert notif_count == 1
