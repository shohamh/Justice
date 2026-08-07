from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import DutyType, RangeAssignment, RangeExcusalStatus, RangeType
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
