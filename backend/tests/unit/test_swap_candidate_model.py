import uuid
from datetime import date, timedelta

from app.db.models import DutyAssignment, DutyLocation, DutyType, Soldier, SwapCandidate, SwapRequest
from tests.helpers import create_node, create_soldier


def test_swap_request_no_longer_has_target_or_covering_columns():
    assert not hasattr(SwapRequest, "target_soldier_id")
    assert not hasattr(SwapRequest, "covering_soldier_id")
    assert not hasattr(SwapRequest, "covering_side_approved")
    assert not hasattr(SwapRequest, "offered_assignment_ids")
    # requester_side_approved is intentionally KEPT on SwapRequest — it's
    # shared across every candidate (there's one requester), unlike
    # covering-side approval which becomes per-candidate.
    assert hasattr(SwapRequest, "requester_side_approved")


def test_swap_request_has_open_to_marketplace_column(admin_session):
    node = create_node(admin_session, level="unit", name="swap-model-unit")
    soldier = create_soldier(admin_session, personal_number="7700001", hierarchy_node_id=node.id)
    req = SwapRequest(
        duty_assignment_id=uuid.uuid4(), duty_date=date(2026, 8, 1),
        requesting_soldier_id=soldier.id, status="open",
    )
    assert req.open_to_marketplace is False


def test_swap_candidate_defaults(admin_session):
    node = create_node(admin_session, level="unit", name="swap-model-unit-2")
    requester = create_soldier(admin_session, personal_number="7700002", hierarchy_node_id=node.id)
    candidate_soldier = create_soldier(admin_session, personal_number="7700003", hierarchy_node_id=node.id)
    dt = DutyType(name="swap-model-dt", score_per_day=1)
    loc = DutyLocation(name="swap-model-loc")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    assignment = DutyAssignment(
        duty_type_id=dt.id, duty_location_id=loc.id, soldier_id=requester.id,
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 1), status="published",
    )
    admin_session.add(assignment)
    admin_session.flush()
    req = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=date(2026, 8, 1),
        requesting_soldier_id=requester.id, status="open",
    )
    admin_session.add(req)
    admin_session.flush()
    cand = SwapCandidate(
        swap_request_id=req.id, soldier_id=candidate_soldier.id, source="invited",
    )
    admin_session.add(cand)
    admin_session.flush()
    assert cand.status == "pending"
    assert cand.offered_assignment_ids == []
    assert cand.soldier_side_approved is None
