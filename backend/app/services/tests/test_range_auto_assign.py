from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import DutyType, RangeType
from app.services.range_auto_assign import propose_range_assignments
from app.services.ranges import create_range_event
from tests.helpers import create_node, create_soldier


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
    soldier = create_soldier(
        app_session, personal_number="7010001", hierarchy_node_id=node.id
    )
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
    assert created[0].assignment_reason_code is None
    assert created[0].assignment_reason_text is None
