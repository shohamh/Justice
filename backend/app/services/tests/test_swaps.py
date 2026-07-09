from __future__ import annotations

import uuid

from tests.helpers import create_node, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def test_swap_manager_approval_row_can_be_created(admin_session):
    from decimal import Decimal
    from datetime import date, timedelta

    from app.db.models import DutyAssignment, DutyLocation, DutyType, SwapManagerApproval, SwapRequest

    node = create_node(admin_session, level="unit", name=f"smoke_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"sm_{_uid()}", hierarchy_node_id=node.id)
    commander = create_soldier(admin_session, personal_number=f"cm_{_uid()}")
    dt = DutyType(name=f"dt_{_uid()}", score_per_day=Decimal("1.0"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    assignment = DutyAssignment(
        duty_type_id=dt.id, duty_location_id=loc.id, soldier_id=soldier.id,
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=2),
        status="published",
    )
    admin_session.add(assignment)
    admin_session.flush()
    req = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=assignment.start_date,
        requesting_soldier_id=soldier.id, status="open",
    )
    admin_session.add(req)
    admin_session.flush()

    row = SwapManagerApproval(swap_request_id=req.id, side="requester", commander_id=commander.id)
    admin_session.add(row)
    admin_session.commit()
    admin_session.refresh(row)

    assert row.approved is False
    assert row.approved_by is None
