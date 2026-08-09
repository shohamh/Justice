# backend/app/services/tests/test_duty_eligibility_watch.py
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import (
    CommanderNotificationScope, DutyAssignment, DutyLocation, DutyShift, DutyType, Notification, NotificationType, RangeType,
    SoldierRangeQualification,
)
from app.services.duty_eligibility_watch import recheck_assignments
from app.services.settings_loader import set_setting
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
