from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.db.models import DutyLocation, DutyType, SwapRequest
from app.services import assignments as assignments_svc
from app.services.commander_dashboard import summary_cards
from tests.helpers import create_node, create_soldier


def test_summary_cards_counts_pending_approval_swaps(admin_session):
    node = create_node(admin_session, level="unit", name="pending_swap_test")
    soldier = create_soldier(admin_session, personal_number="7930001", hierarchy_node_id=node.id)

    baseline = summary_cards(admin_session, subtree_ids=[node.id])

    dt = DutyType(name="dt_pending_swap_test", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_pending_swap_test")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    assignment = assignments_svc.create_assignment(
        admin_session, soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 2),
    )
    admin_session.flush()
    # minimal swap request in pending_approval status
    req = SwapRequest(
        duty_assignment_id=assignment.id,
        duty_date=date(2026, 8, 1),
        requesting_soldier_id=soldier.id,
        status="pending_approval",
    )
    admin_session.add(req)
    admin_session.commit()

    cards = summary_cards(admin_session, subtree_ids=[node.id])
    assert cards["approvals_pending"] == baseline["approvals_pending"] + 1
