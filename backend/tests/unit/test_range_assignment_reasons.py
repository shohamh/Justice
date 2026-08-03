from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import (
    DutyAssignment,
    DutyType,
    RangeType,
    SoldierRangeQualification,
)
from app.services.range_auto_assign import propose_range_assignments
from app.services.ranges import create_range_event
from tests.helpers import create_duty_location, create_node, create_soldier


def test_auto_assignment_reason_fields_are_persisted_as_nullable_contract(
    app_session: Session,
) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגת סיבת שיבוץ")
    app_session.add(DutyType(
        name="תורנות נשק סיבת שיבוץ",
        score_per_day=Decimal("1.00"),
        requires_weapon=True,
        eligible_node_ids=[node.id],
    ))
    soldier = create_soldier(app_session, personal_number="7010001", hierarchy_node_id=node.id)
    app_session.flush()
    event = create_range_event(
        app_session,
        hierarchy_node_id=node.id,
        range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        location="מטווח",
        required_count=1,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert shortfall == 0
    assert [assignment.soldier_id for assignment in created] == [soldier.id]
    assert created[0].assignment_reason_code == "available_and_balanced"
    assert created[0].assignment_reason_text is None


def test_auto_assignment_marks_qualified_candidate_with_qualification_reason(
    app_session: Session,
) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגת הכשרה")
    soldier = create_soldier(app_session, personal_number="7010003", hierarchy_node_id=node.id)
    event_date = date.today() + timedelta(days=5)
    app_session.add(DutyType(
        name="תורנות נשק הכשרה", score_per_day=Decimal("1.00"), requires_weapon=True,
        eligible_node_ids=[node.id],
    ))
    app_session.add(SoldierRangeQualification(
        soldier_id=soldier.id, range_type=RangeType.laser, valid_until=event_date,
    ))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=event_date, location="מטווח", required_count=1,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert shortfall == 0
    assert created[0].soldier_id == soldier.id
    assert created[0].assignment_reason_code == "qualified"


def test_auto_assignment_marks_future_weapon_duty_candidate_with_priority_reason(
    app_session: Session,
) -> None:
    node = create_node(app_session, level="פלוגה", name="פלוגת עדיפות נשק")
    soldier = create_soldier(app_session, personal_number="7010004", hierarchy_node_id=node.id)
    duty_type = DutyType(
        name="תורנות נשק עדיפות", score_per_day=Decimal("1.00"), requires_weapon=True,
        eligible_node_ids=[node.id],
    )
    app_session.add(duty_type)
    app_session.flush()
    location = create_duty_location(app_session)
    future_duty_date = date.today() + timedelta(days=2)
    app_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=duty_type.id, duty_location_id=location.id,
        start_date=future_duty_date, end_date=future_duty_date, status="published",
    ))
    app_session.flush()
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5), location="מטווח", required_count=1,
    )

    created, shortfall = propose_range_assignments(app_session, event=event)

    assert shortfall == 0
    assert created[0].soldier_id == soldier.id
    assert created[0].assignment_reason_code == "weapon_duty_priority"
