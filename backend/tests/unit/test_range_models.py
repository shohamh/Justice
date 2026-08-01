from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    RangeAssignment,
    RangeAttendanceStatus,
    RangeExcusalRequest,
    RangeExcusalStatus,
    RangeEvent,
    RangeEventStatus,
    RangeType,
    SoldierRangeQualification,
)
from tests.helpers import create_node, create_soldier


def test_range_event_round_trip(app_session: Session) -> None:
    node = create_node(app_session, level="×¤×œ×•×’×”", name="×¤×œ×•×’×” ×")
    event = RangeEvent(
        hierarchy_node_id=node.id,
        range_type=RangeType.laser,
        date=date(2026, 8, 15),
        location="×ž×˜×•×•×— ×“×¨×•×",
        required_count=5,
        reserve_count=2,
    )
    app_session.add(event)
    app_session.commit()
    app_session.refresh(event)

    assert event.status == RangeEventStatus.planned
    assert event.reserve_count == 2


def test_range_assignment_and_qualification_round_trip(app_session: Session) -> None:
    node = create_node(app_session, level="×¤×œ×•×’×”", name="×¤×œ×•×’×” ×‘")
    soldier = create_soldier(app_session, personal_number="1111111", hierarchy_node_id=node.id)
    event = RangeEvent(
        hierarchy_node_id=node.id,
        range_type=RangeType.live,
        date=date(2026, 9, 1),
        location="×ž×˜×•×•×— ×¦×¤×•×Ÿ",
        required_count=3,
    )
    app_session.add(event)
    app_session.flush()

    assignment = RangeAssignment(range_event_id=event.id, soldier_id=soldier.id, is_reserve=False)
    app_session.add(assignment)
    app_session.commit()
    app_session.refresh(assignment)

    assert assignment.attendance_status == RangeAttendanceStatus.pending

    qualification = SoldierRangeQualification(
        soldier_id=soldier.id,
        range_type=RangeType.live,
        valid_until=date(2027, 9, 1),
        source_range_assignment_id=assignment.id,
    )
    app_session.add(qualification)
    app_session.commit()
    app_session.refresh(qualification)

    assert qualification.valid_until == date(2027, 9, 1)


def test_duty_type_requires_weapon_defaults_false(app_session: Session) -> None:
    from app.db.models import DutyType
    from decimal import Decimal

    dt = DutyType(name="×©×ž×™×¨×” ×¨×’×™×œ×”", score_per_day=Decimal("1.00"))
    app_session.add(dt)
    app_session.commit()
    app_session.refresh(dt)
    assert dt.requires_weapon is False


def test_exemption_type_forbids_weapons_defaults_false(app_session: Session) -> None:
    from app.db.models import ExemptionType

    et = ExemptionType(name="×¤×˜×•×¨ ×¨×¤×•××™ ×›×œ×œ×™")
    app_session.add(et)
    app_session.commit()
    app_session.refresh(et)
    assert et.forbids_weapons is False


def test_range_assignment_is_draft_defaults_false(app_session: Session) -> None:
    node = create_node(app_session, level="×¤×œ×•×’×”", name="×¤×œ×•×’×” is_draft")
    soldier = create_soldier(app_session, personal_number="9000001", hierarchy_node_id=node.id)
    event = RangeEvent(
        hierarchy_node_id=node.id, range_type=RangeType.laser,
        date=date(2026, 8, 25), location="×ž×˜×•×•×—", required_count=1,
    )
    app_session.add(event)
    app_session.flush()

    assignment = RangeAssignment(range_event_id=event.id, soldier_id=soldier.id, is_reserve=False)
    app_session.add(assignment)
    app_session.commit()
    app_session.refresh(assignment)

    assert assignment.is_draft is False


def test_range_excusal_request_allows_only_one_pending_request_per_assignment(app_session: Session) -> None:
    """Dropping the partial pending index would permit duplicate active requests."""
    node = create_node(app_session, level="×¤×œ×•×’×”", name="×¤×œ×•×’×” ×‘×§×©×•×ª ×¤×˜×•×¨")
    soldier = create_soldier(app_session, personal_number="9000002", hierarchy_node_id=node.id)
    event = RangeEvent(
        hierarchy_node_id=node.id,
        range_type=RangeType.laser,
        date=date(2026, 8, 26),
        location="×ž×˜×•×•×—",
        required_count=1,
    )
    app_session.add(event)
    app_session.flush()
    assignment = RangeAssignment(range_event_id=event.id, soldier_id=soldier.id, is_reserve=False)
    app_session.add(assignment)
    app_session.flush()

    app_session.add(
        RangeExcusalRequest(
            range_assignment_id=assignment.id,
            requested_by=soldier.id,
            reason="×¡×™×‘×” ×¨××©×•× ×”",
        )
    )
    app_session.flush()
    app_session.add(
        RangeExcusalRequest(
            range_assignment_id=assignment.id,
            requested_by=soldier.id,
            reason="×¡×™×‘×” ×›×¤×•×œ×”",
        )
    )

    with pytest.raises(IntegrityError):
        app_session.flush()
    app_session.rollback()


def test_range_excusal_request_starts_pending_without_a_decision(app_session: Session) -> None:
    """A newly submitted request must not look decided before a reviewer acts."""
    node = create_node(app_session, level="×¤×œ×•×’×”", name="×¤×œ×•×’×” ×”×—×œ×˜×ª ×¤×˜×•×¨")
    soldier = create_soldier(app_session, personal_number="9000003", hierarchy_node_id=node.id)
    event = RangeEvent(
        hierarchy_node_id=node.id,
        range_type=RangeType.live,
        date=date(2026, 8, 27),
        location="×ž×˜×•×•×—",
        required_count=1,
    )
    app_session.add(event)
    app_session.flush()
    assignment = RangeAssignment(range_event_id=event.id, soldier_id=soldier.id, is_reserve=False)
    app_session.add(assignment)
    app_session.flush()

    request = RangeExcusalRequest(
        range_assignment_id=assignment.id,
        requested_by=soldier.id,
        reason="×‘×“×™×§×” ×¨×¤×•××™×ª",
    )
    app_session.add(request)
    app_session.commit()
    app_session.refresh(request)

    assert request.status == RangeExcusalStatus.pending
    assert request.decided_by is None
    assert request.decided_at is None
    assert request.decision_note is None
