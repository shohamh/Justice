import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import DutyAssignment, SwapCandidate, SwapRequest
from app.services import swaps as svc
from app.services.swaps import SwapError
from tests.helpers import create_node, create_soldier


def _published_assignment(session, *, soldier_id, node_id):
    from app.db.models import DutyType, DutyLocation
    dt = DutyType(name=f"dt_svc_{soldier_id}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_svc_{soldier_id}")
    session.add_all([dt, loc])
    session.flush()
    a = DutyAssignment(
        soldier_id=soldier_id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=10), end_date=date.today() + timedelta(days=11),
        status="published",
    )
    session.add(a)
    session.flush()
    return a


def test_create_request_combining_targets_and_marketplace(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-1")
    requester = create_soldier(admin_session, personal_number="7710001", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="7710002", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[target.id], reason=None,
        open_to_marketplace=True,
    )
    admin_session.flush()

    assert isinstance(req, SwapRequest)
    assert req.open_to_marketplace is True
    candidates = admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id).all()
    assert len(candidates) == 1
    assert candidates[0].soldier_id == target.id
    assert candidates[0].source == "invited"
    assert candidates[0].status == "pending"


def test_create_request_rejects_second_open_request_for_same_duty(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-2")
    requester = create_soldier(admin_session, personal_number="7710003", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
    )
    admin_session.flush()

    with pytest.raises(SwapError, match="already_pending"):
        svc.create_request(
            admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
            target_soldier_id=None, target_soldier_ids=None, reason=None, open_to_marketplace=True,
        )


def test_claim_request_creates_marketplace_candidate_without_cancelling_invited(admin_session):
    node = create_node(admin_session, level="unit", name="swap-svc-unit-3")
    requester = create_soldier(admin_session, personal_number="7710004", hierarchy_node_id=node.id)
    invited = create_soldier(admin_session, personal_number="7710005", hierarchy_node_id=node.id)
    claimant = create_soldier(admin_session, personal_number="7710006", hierarchy_node_id=node.id)
    assignment = _published_assignment(admin_session, soldier_id=requester.id, node_id=node.id)

    req = svc.create_request(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id,
        target_soldier_id=None, target_soldier_ids=[invited.id], reason=None, open_to_marketplace=True,
    )
    admin_session.flush()

    svc.claim_request(admin_session, request_id=req.id, covering_soldier_id=claimant.id, actor_id=claimant.id)
    admin_session.flush()

    candidates = {c.soldier_id: c for c in admin_session.query(SwapCandidate).filter_by(swap_request_id=req.id).all()}
    assert len(candidates) == 2
    assert candidates[invited.id].status == "pending"  # untouched — no more cancel-on-claim
    assert candidates[claimant.id].source == "marketplace"
    assert candidates[claimant.id].soldier_side_approved is True
