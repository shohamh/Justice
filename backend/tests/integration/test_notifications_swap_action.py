from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, DutyLocation, DutyType, SwapCandidate, SwapManagerApproval, SwapRequest
from app.services.action_tokens import create_token
from tests.helpers import auth_headers, create_node, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def _setup(session: Session):
    """Requester + covering soldier under their own commanders, with a
    pending_approval swap (mirrors tests/integration/test_swaps_api.py)."""
    req_node = create_node(session, level="unit", name=f"na_req_{_uid()}")
    cov_node = create_node(session, level="unit", name=f"na_cov_{_uid()}")
    req_cmd = create_soldier(session, personal_number=f"na_rc_{_uid()}", role="commander")
    cov_cmd = create_soldier(session, personal_number=f"na_cc_{_uid()}", role="commander")
    req_node.commander_id = req_cmd.id
    cov_node.commander_id = cov_cmd.id
    session.commit()

    requester = create_soldier(session, personal_number=f"na_req_s_{_uid()}", hierarchy_node_id=req_node.id)
    covering = create_soldier(session, personal_number=f"na_cov_s_{_uid()}", hierarchy_node_id=cov_node.id)

    dt = DutyType(name=f"na_dt_{_uid()}", score_per_day=1)
    loc = DutyLocation(name=f"na_loc_{_uid()}")
    session.add_all([dt, loc])
    session.flush()
    assignment = DutyAssignment(
        duty_type_id=dt.id, duty_location_id=loc.id, soldier_id=requester.id,
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=2),
        status="published",
    )
    session.add(assignment)
    session.flush()

    swap_req = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=assignment.start_date,
        requesting_soldier_id=requester.id, status="open",
    )
    session.add(swap_req)
    session.commit()

    return requester, covering, req_cmd, cov_cmd, assignment, swap_req


def test_dispatch_swap_approve_requester_by_required_commander(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    tok = create_token(admin_session, soldier_id=req_cmd.id, action="swap:approve_requester", resource_id=swap_req.id)
    admin_session.commit()

    resp = client.post("/api/action", headers=auth_headers(req_cmd), json={"token": tok})
    assert resp.status_code == 200, resp.text

    row = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == swap_req.id,
            SwapManagerApproval.side == "requester",
            SwapManagerApproval.commander_id == req_cmd.id,
        )
    ).scalar_one()
    assert row.approved is True
    assert row.approved_by == req_cmd.id


def test_dispatch_swap_approve_requester_admin_override(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})
    admin = create_soldier(admin_session, personal_number=f"na_adm_{_uid()}", role="admin")

    tok = create_token(admin_session, soldier_id=admin.id, action="swap:approve_requester", resource_id=swap_req.id)
    admin_session.commit()

    resp = client.post("/api/action", headers=auth_headers(admin), json={"token": tok})
    assert resp.status_code == 200, resp.text

    rows = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == swap_req.id,
            SwapManagerApproval.side == "requester",
        )
    ).scalars().all()
    assert all(row.approved for row in rows)
    assert all(row.approved_by == admin.id for row in rows)


def test_dispatch_swap_approve_requester_stranger_forbidden(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})
    stranger = create_soldier(admin_session, personal_number=f"na_str_{_uid()}")

    tok = create_token(admin_session, soldier_id=stranger.id, action="swap:approve_requester", resource_id=swap_req.id)
    admin_session.commit()

    resp = client.post("/api/action", headers=auth_headers(stranger), json={"token": tok})
    assert resp.status_code == 403


def test_dispatch_swap_reject_by_requester_kills_whole_request(client: TestClient, admin_session: Session):
    """swap:reject dispatched by the request's own requester must reject
    the whole SwapRequest (status becomes 'rejected')."""
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    candidate = SwapCandidate(swap_request_id=swap_req.id, soldier_id=covering.id, source="invited")
    admin_session.add(candidate)
    admin_session.commit()

    tok = create_token(admin_session, soldier_id=requester.id, action="swap:reject", resource_id=swap_req.id)
    admin_session.commit()

    resp = client.post("/api/action", headers=auth_headers(requester), json={"token": tok})
    assert resp.status_code == 200, resp.text

    admin_session.expire_all()
    refreshed_req = admin_session.get(SwapRequest, swap_req.id)
    refreshed_candidate = admin_session.get(SwapCandidate, candidate.id)
    assert refreshed_req.status == "rejected"
    assert refreshed_candidate.status == "cancelled"


def test_dispatch_swap_reject_by_candidate_declines_only_own_candidacy(client: TestClient, admin_session: Session):
    """swap:reject dispatched by a non-requester invited candidate must only
    decline that candidate's own row, leaving the parent SwapRequest and any
    other live candidates untouched. Regression test: this dispatch used to
    call reject_request unconditionally regardless of the acting soldier,
    destroying the entire request even when the actor was just one invited
    candidate declining their own invite."""
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    other_node = create_node(admin_session, level="unit", name=f"na_oth_{_uid()}")
    other_candidate_soldier = create_soldier(admin_session, personal_number=f"na_oth_s_{_uid()}", hierarchy_node_id=other_node.id)
    candidate = SwapCandidate(swap_request_id=swap_req.id, soldier_id=covering.id, source="invited")
    other_candidate = SwapCandidate(swap_request_id=swap_req.id, soldier_id=other_candidate_soldier.id, source="invited")
    admin_session.add_all([candidate, other_candidate])
    admin_session.commit()

    tok = create_token(admin_session, soldier_id=covering.id, action="swap:reject", resource_id=swap_req.id)
    admin_session.commit()

    resp = client.post("/api/action", headers=auth_headers(covering), json={"token": tok})
    assert resp.status_code == 200, resp.text

    admin_session.expire_all()
    refreshed_req = admin_session.get(SwapRequest, swap_req.id)
    refreshed_candidate = admin_session.get(SwapCandidate, candidate.id)
    refreshed_other = admin_session.get(SwapCandidate, other_candidate.id)
    assert refreshed_req.status == "open"
    assert refreshed_candidate.status == "declined"
    assert refreshed_other.status == "pending"
