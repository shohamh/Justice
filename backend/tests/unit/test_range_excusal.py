from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DutyType,
    Notification,
    NotificationType,
    RangeAssignment,
    RangeAttendanceStatus,
    RangeExcusalStatus,
    RangeType,
)
from app.services.range_excusal import request_primary_excusal, request_reserve_excusal
from app.services.ranges import add_range_assignment, create_range_event
from tests.helpers import create_node, create_range_location, create_soldier


def _assignment(session: Session, *, is_reserve: bool):
    node = create_node(session, level="branch", name=f"excusal {is_reserve}")
    session.add(DutyType(name=f"weapon {is_reserve}", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    session.flush()
    soldier = create_soldier(session, personal_number=f"excusal-{is_reserve}", hierarchy_node_id=node.id)
    event = create_range_event(
        session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(session, name="range").id, required_count=1,
        reserve_count=1 if is_reserve else 0,
    )
    return event, add_range_assignment(session, event=event, soldier_id=soldier.id, is_reserve=is_reserve)


def test_primary_excusal_creates_pending_request_and_keeps_assignment(app_session: Session) -> None:
    _, assignment = _assignment(app_session, is_reserve=False)
    request = request_primary_excusal(
        app_session, assignment=assignment, reason="medical appointment", requested_by=assignment.soldier_id
    )
    assert request.status == RangeExcusalStatus.pending
    assert app_session.get(RangeAssignment, assignment.id) is not None


def test_reserve_excusal_deletes_assignment_and_records_approved_request(app_session: Session) -> None:
    _, assignment = _assignment(app_session, is_reserve=True)
    request = request_reserve_excusal(
        app_session, assignment=assignment, reason="family matter", requested_by=assignment.soldier_id
    )
    assert request.status == RangeExcusalStatus.approved
    assert app_session.get(RangeAssignment, assignment.id) is None


def test_approving_primary_excusal_promotes_assigned_reserve(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="promotion")
    app_session.add(DutyType(name="weapon promotion", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    app_session.flush()
    primary = create_soldier(app_session, personal_number="excusal-primary", hierarchy_node_id=node.id)
    reserve = create_soldier(app_session, personal_number="excusal-reserve", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session, name="promotion range").id, required_count=1,
        reserve_count=1,
    )
    primary_assignment = add_range_assignment(app_session, event=event, soldier_id=primary.id, is_reserve=False)
    reserve_assignment = add_range_assignment(app_session, event=event, soldier_id=reserve.id, is_reserve=True)
    request = request_primary_excusal(
        app_session, assignment=primary_assignment, reason="medical appointment", requested_by=primary.id
    )

    from app.services.range_excusal import decide_primary_excusal
    decided = decide_primary_excusal(app_session, request=request, approve=True, decided_by=reserve.id)

    assert decided.status == RangeExcusalStatus.approved
    assert app_session.get(RangeAssignment, primary_assignment.id) is None
    promoted = app_session.get(RangeAssignment, reserve_assignment.id)
    assert promoted is not None and promoted.is_reserve is False
    assert decided.promoted_assignment_id == reserve_assignment.id


def test_primary_excusal_request_stores_range_event_id(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="rex-node-1")
    app_session.add(DutyType(name="rex-weapon-1", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    app_session.flush()
    soldier = create_soldier(app_session, personal_number="rex-001", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id, required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    request = request_primary_excusal(app_session, assignment=assignment, reason="בדיקה", requested_by=soldier.id)

    assert request.range_event_id == event.id


def test_reserve_excusal_request_stores_range_event_id(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="rex-node-2")
    app_session.add(DutyType(name="rex-weapon-2", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    app_session.flush()
    soldier = create_soldier(app_session, personal_number="rex-002", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id, required_count=1, reserve_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=True)

    request = request_reserve_excusal(app_session, assignment=assignment, reason="בדיקה", requested_by=soldier.id)

    assert request.range_event_id == event.id
    # The assignment is deleted synchronously by request_reserve_excusal — confirm
    # range_event_id survives that even within the same request/response cycle.
    assert request.range_assignment_id is None


def test_primary_excusal_notifies_duty_managers_with_event_id(app_session: Session) -> None:
    node = create_node(app_session, level="branch", name="excusal dm")
    dm = create_soldier(app_session, personal_number="excusal-dm", role="duty_manager", hierarchy_node_id=node.id)
    app_session.add(DutyType(name="weapon dm", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    app_session.flush()
    soldier = create_soldier(app_session, personal_number="excusal-soldier", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id, required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    request = request_primary_excusal(app_session, assignment=assignment, reason="בדיקה", requested_by=soldier.id)

    dm_notif = app_session.execute(
        select(Notification).where(
            Notification.soldier_id == dm.id,
            Notification.type == NotificationType.range_excusal_pending,
            Notification.reference_id == request.id,
        )
    ).scalar_one()
    assert dm_notif.metadata_json == {"event_id": str(assignment.range_event_id)}


def test_pending_primary_excusal_does_not_remove_later_primary_assignment(app_session: Session) -> None:
    from app.services.range_reconciliation import reconcile_future_range_assignments

    node = create_node(app_session, level="branch", name="reconciliation pending excusal")
    soldier = create_soldier(app_session, personal_number="reconciliation-excusal-001", hierarchy_node_id=node.id)
    app_session.add(DutyType(name="reconciliation pending excusal weapon", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    app_session.flush()
    location = create_range_location(app_session, name="reconciliation pending excusal range")
    source_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id, required_count=1,
    )
    target_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id, required_count=1,
    )
    source = add_range_assignment(app_session, event=source_event, soldier_id=soldier.id, is_reserve=False)
    target = add_range_assignment(app_session, event=target_event, soldier_id=soldier.id, is_reserve=False)
    request_primary_excusal(app_session, assignment=source, reason="medical appointment", requested_by=soldier.id)

    result = reconcile_future_range_assignments(
        app_session, soldier_id=soldier.id, source_event=source_event, actor_id=None,
    )

    assert result.removed_assignment_ids == []
    assert app_session.get(RangeAssignment, target.id) is not None


def test_reconciliation_requires_persisted_reserve_attendance_before_removal(app_session: Session) -> None:
    from app.services.range_reconciliation import reconcile_future_range_assignments

    node = create_node(app_session, level="branch", name="reconciliation reserve attendance")
    soldier = create_soldier(app_session, personal_number="reconciliation-excusal-002", hierarchy_node_id=node.id)
    app_session.add(DutyType(name="reconciliation reserve attendance weapon", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    app_session.flush()
    location = create_range_location(app_session, name="reconciliation reserve attendance range")
    source_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id, required_count=0,
        reserve_count=1,
    )
    target_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id, required_count=1,
    )
    source = add_range_assignment(app_session, event=source_event, soldier_id=soldier.id, is_reserve=True)
    target = add_range_assignment(app_session, event=target_event, soldier_id=soldier.id, is_reserve=False)

    pending_result = reconcile_future_range_assignments(
        app_session, soldier_id=soldier.id, source_event=source_event, actor_id=None,
    )
    source.attendance_status = RangeAttendanceStatus.present
    app_session.commit()
    confirmed_result = reconcile_future_range_assignments(
        app_session, soldier_id=soldier.id, source_event=source_event, actor_id=None,
    )

    assert pending_result.removed_assignment_ids == []
    assert confirmed_result.removed_assignment_ids == [target.id]
    assert app_session.get(RangeAssignment, target.id) is None


def test_draft_source_assignment_does_not_remove_later_assignment(app_session: Session) -> None:
    from app.services.range_reconciliation import reconcile_future_range_assignments

    node = create_node(app_session, level="branch", name="reconciliation draft source")
    soldier = create_soldier(app_session, personal_number="reconciliation-excusal-003", hierarchy_node_id=node.id)
    app_session.add(DutyType(name="reconciliation draft source weapon", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    app_session.flush()
    location = create_range_location(app_session, name="reconciliation draft source range")
    source_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id, required_count=1,
    )
    target_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id, required_count=1,
    )
    source = RangeAssignment(range_event_id=source_event.id, soldier_id=soldier.id, is_draft=True)
    app_session.add(source)
    app_session.commit()
    target = add_range_assignment(app_session, event=target_event, soldier_id=soldier.id, is_reserve=False)

    result = reconcile_future_range_assignments(
        app_session, soldier_id=soldier.id, source_event=source_event, actor_id=None,
    )

    assert result.removed_assignment_ids == []
    assert app_session.get(RangeAssignment, target.id) is not None


def _reconciliation_node(session: Session, *, name: str):
    node = create_node(session, level="branch", name=name)
    session.add(DutyType(
        name=f"{name} weapon", score_per_day=Decimal("1.00"), requires_weapon=True,
        eligible_node_ids=[node.id],
    ))
    session.flush()
    return node


def test_request_primary_excusal_leaves_later_assignment_intact(app_session: Session) -> None:
    """The pending request makes the source stop being guaranteed coverage, so the
    reconciliation the request triggers is a deliberate no-op."""
    node = _reconciliation_node(app_session, name="wire excusal request")
    soldier = create_soldier(app_session, personal_number="wire-excusal-001", hierarchy_node_id=node.id)
    create_soldier(app_session, personal_number="wire-excusal-002", hierarchy_node_id=node.id)
    location = create_range_location(app_session, name="wire excusal request range")
    source_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id, required_count=1,
    )
    later_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id, required_count=1,
    )
    source = add_range_assignment(app_session, event=source_event, soldier_id=soldier.id, is_reserve=False)
    later = add_range_assignment(app_session, event=later_event, soldier_id=soldier.id, is_reserve=False)

    request = request_primary_excusal(
        app_session, assignment=source, reason="medical appointment", requested_by=soldier.id,
    )

    assert request.status == RangeExcusalStatus.pending
    assert app_session.get(RangeAssignment, source.id) is not None
    assert app_session.execute(select(RangeAssignment).where(
        RangeAssignment.range_event_id == later_event.id,
    )).scalars().one().id == later.id


def test_approved_primary_excusal_reconciles_for_the_promoted_reserve(app_session: Session) -> None:
    from app.services.range_excusal import decide_primary_excusal

    node = _reconciliation_node(app_session, name="wire excusal promote")
    primary = create_soldier(app_session, personal_number="wire-excusal-003", hierarchy_node_id=node.id)
    reserve = create_soldier(app_session, personal_number="wire-excusal-004", hierarchy_node_id=node.id)
    create_soldier(app_session, personal_number="wire-excusal-005", hierarchy_node_id=node.id)
    location = create_range_location(app_session, name="wire excusal promote range")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id,
        required_count=1, reserve_count=1,
    )
    later_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id, required_count=1,
    )
    primary_assignment = add_range_assignment(app_session, event=event, soldier_id=primary.id, is_reserve=False)
    reserve_assignment = add_range_assignment(app_session, event=event, soldier_id=reserve.id, is_reserve=True)
    later = add_range_assignment(app_session, event=later_event, soldier_id=reserve.id, is_reserve=False)
    request = request_primary_excusal(
        app_session, assignment=primary_assignment, reason="medical appointment", requested_by=primary.id,
    )

    decided = decide_primary_excusal(app_session, request=request, approve=True, decided_by=primary.id)

    assert decided.promoted_assignment_id == reserve_assignment.id
    # The promotion made the reserve a guaranteed primary source, so their later
    # duplicate is now redundant and its slot goes to the next-best candidate.
    assert app_session.get(RangeAssignment, later.id) is None
    refilled = app_session.execute(select(RangeAssignment).where(
        RangeAssignment.range_event_id == later_event.id,
    )).scalars().one()
    assert refilled.soldier_id != reserve.id
    assert refilled.is_reserve is False


def test_approved_primary_excusal_without_promotion_touches_nothing_later(app_session: Session) -> None:
    from app.services.range_excusal import decide_primary_excusal

    node = _reconciliation_node(app_session, name="wire excusal no promote")
    soldier = create_soldier(app_session, personal_number="wire-excusal-006", hierarchy_node_id=node.id)
    create_soldier(app_session, personal_number="wire-excusal-007", hierarchy_node_id=node.id)
    location = create_range_location(app_session, name="wire excusal no promote range")
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), range_location_id=location.id, required_count=1,
    )
    later_event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=10), range_location_id=location.id, required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    later = add_range_assignment(app_session, event=later_event, soldier_id=soldier.id, is_reserve=False)
    request = request_primary_excusal(
        app_session, assignment=assignment, reason="medical appointment", requested_by=soldier.id,
    )

    decided = decide_primary_excusal(app_session, request=request, approve=True, decided_by=soldier.id)

    assert decided.promoted_assignment_id is None
    assert app_session.get(RangeAssignment, assignment.id) is None
    assert app_session.execute(select(RangeAssignment).where(
        RangeAssignment.range_event_id == later_event.id,
    )).scalars().one().id == later.id
