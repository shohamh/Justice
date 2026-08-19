from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.db.models import DutyLocation, DutyType, SwapCandidate, SwapRequest
from app.services import assignments as assignments_svc
from app.services.commander_dashboard import summary_cards, upcoming_duties
from tests.helpers import create_node, create_soldier


def test_summary_cards_counts_pending_approval_swaps(admin_session):
    node = create_node(admin_session, level="unit", name="pending_swap_test")
    soldier = create_soldier(admin_session, personal_number="7930001", hierarchy_node_id=node.id)
    covering = create_soldier(admin_session, personal_number="7930003")

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
    # Open swap request with one live (accepted) candidate — the current
    # equivalent of the old "pending_approval" status, now that manager
    # approval is tracked per-candidate rather than on the parent request.
    req = SwapRequest(
        duty_assignment_id=assignment.id,
        duty_date=date(2026, 8, 1),
        requesting_soldier_id=soldier.id,
        status="open",
    )
    admin_session.add(req)
    admin_session.flush()
    candidate = SwapCandidate(
        swap_request_id=req.id,
        soldier_id=covering.id,
        source="invited",
        status="accepted",
        soldier_side_approved=True,
    )
    admin_session.add(candidate)
    admin_session.commit()

    cards = summary_cards(admin_session, subtree_ids=[node.id])
    assert cards["approvals_pending"] == baseline["approvals_pending"] + 1


def test_upcoming_duties_includes_algorithm_draft(admin_session):
    from datetime import date as _date

    from app.db.models import DutyAssignment

    node = create_node(admin_session, level="unit", name="upcoming_draft_test")
    soldier = create_soldier(admin_session, personal_number="7940001", hierarchy_node_id=node.id)
    dt = DutyType(name="dt_upcoming_draft_test", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_upcoming_draft_test")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    admin_session.add(
        DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=_date.today(),
            end_date=_date.today() + timedelta(days=1),
            status="algorithm_draft",
        )
    )
    admin_session.commit()

    days = upcoming_duties(admin_session, subtree_ids=[node.id], days=7)
    all_assignments = [a for day in days for a in day["assignments"]]
    assert len(all_assignments) == 1
    assert all_assignments[0]["status"] == "algorithm_draft"


def test_summary_cards_upcoming_count_includes_algorithm_draft(admin_session):
    from datetime import date as _date

    from app.db.models import DutyAssignment

    node = create_node(admin_session, level="unit", name="summary_draft_test")
    soldier = create_soldier(admin_session, personal_number="7940002", hierarchy_node_id=node.id)
    baseline = summary_cards(admin_session, subtree_ids=[node.id])

    dt = DutyType(name="dt_summary_draft_test", score_per_day=Decimal("1"))
    loc = DutyLocation(name="loc_summary_draft_test")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    admin_session.add(
        DutyAssignment(
            soldier_id=soldier.id,
            duty_type_id=dt.id,
            duty_location_id=loc.id,
            start_date=_date.today(),
            end_date=_date.today() + timedelta(days=1),
            status="algorithm_draft",
        )
    )
    admin_session.commit()

    cards = summary_cards(admin_session, subtree_ids=[node.id])
    assert cards["upcoming_duties_7d"] == baseline["upcoming_duties_7d"] + 1
