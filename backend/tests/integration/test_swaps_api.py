from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, DutyLocation, DutyType, SwapManagerApproval, SwapRequest
from tests.helpers import auth_headers, create_node, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def _setup(session: Session):
    """Build a requester + covering soldier, each under their own commander,
    and a pending_approval swap between them (via claim)."""
    req_node = create_node(session, level="unit", name=f"api_req_{_uid()}")
    cov_node = create_node(session, level="unit", name=f"api_cov_{_uid()}")
    req_cmd = create_soldier(session, personal_number=f"api_rc_{_uid()}", role="commander")
    cov_cmd = create_soldier(session, personal_number=f"api_cc_{_uid()}", role="commander")
    req_node.commander_id = req_cmd.id
    cov_node.commander_id = cov_cmd.id
    session.commit()

    requester = create_soldier(session, personal_number=f"api_req_s_{_uid()}", hierarchy_node_id=req_node.id)
    covering = create_soldier(session, personal_number=f"api_cov_s_{_uid()}", hierarchy_node_id=cov_node.id)

    dt = DutyType(name=f"api_dt_{_uid()}", score_per_day=1)
    loc = DutyLocation(name=f"api_loc_{_uid()}")
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


def test_soldier_can_approve_own_side(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.post(f"/api/me/swaps/{swap_req.id}/approve", headers=auth_headers(requester))
    assert r.status_code == 200, r.text
    assert r.json()["requester_side_approved"] is True
    assert r.json()["status"] == "pending_approval"


def test_non_party_soldier_cannot_approve(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})
    stranger = create_soldier(admin_session, personal_number=f"api_str_{_uid()}")

    r = client.post(f"/api/me/swaps/{swap_req.id}/approve", headers=auth_headers(stranger))
    assert r.status_code == 400


def test_full_approval_chain_applies_swap(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    client.post(f"/api/me/swaps/{swap_req.id}/approve", headers=auth_headers(requester))
    client.post(f"/api/me/swaps/{swap_req.id}/approve", headers=auth_headers(covering))
    client.post(f"/api/swaps/{swap_req.id}/manager-approve", headers=auth_headers(req_cmd), json={"side": "requester"})
    r = client.post(f"/api/swaps/{swap_req.id}/manager-approve", headers=auth_headers(cov_cmd), json={"side": "covering"})

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "applied"


def test_wrong_commander_cannot_manager_approve(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.post(f"/api/swaps/{swap_req.id}/manager-approve", headers=auth_headers(cov_cmd), json={"side": "requester"})
    assert r.status_code == 403


def test_manager_reapprove_is_noop_not_override(client: TestClient, admin_session: Session):
    """A chain commander clicking approve a second time should be a harmless
    no-op through the normal (idempotent) path, not silently reroute through
    the broader-authority override path."""
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    client.post(f"/api/me/swaps/{swap_req.id}/approve", headers=auth_headers(requester))
    client.post(f"/api/me/swaps/{swap_req.id}/approve", headers=auth_headers(covering))
    r1 = client.post(f"/api/swaps/{swap_req.id}/manager-approve", headers=auth_headers(req_cmd), json={"side": "requester"})
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "pending_approval"  # covering side's commander hasn't approved yet

    row = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == swap_req.id, SwapManagerApproval.side == "requester"
        )
    ).scalar_one()
    first_approved_at = row.approved_at

    r2 = client.post(f"/api/swaps/{swap_req.id}/manager-approve", headers=auth_headers(req_cmd), json={"side": "requester"})
    assert r2.status_code == 200, r2.text
    admin_session.refresh(row)
    assert row.approved_by == req_cmd.id
    assert row.approved_at == first_approved_at


def test_admin_override_clears_manager_side(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})
    admin = create_soldier(admin_session, personal_number=f"api_adm_{_uid()}", role="admin")

    r = client.post(f"/api/swaps/{swap_req.id}/manager-approve", headers=auth_headers(admin), json={"side": "requester"})
    assert r.status_code == 200, r.text
    rows = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == swap_req.id, SwapManagerApproval.side == "requester"
        )
    ).scalars().all()
    assert all(row.approved for row in rows)
    assert all(row.approved_by == admin.id for row in rows)


def test_swap_out_includes_manager_approvals(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.get("/api/me/swaps", headers=auth_headers(requester))
    assert r.status_code == 200
    swap_out = next(s for s in r.json() if s["id"] == str(swap_req.id))
    assert len(swap_out["requester_manager_approvals"]) == 1
    assert swap_out["requester_manager_approvals"][0]["commander_id"] == str(req_cmd.id)
    assert swap_out["requester_manager_approvals"][0]["approved"] is False
    assert len(swap_out["covering_manager_approvals"]) == 1


def test_soldier_reject_kills_swap(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.post(f"/api/me/swaps/{swap_req.id}/reject", headers=auth_headers(covering), json={"decision_note": "no thanks"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"


def test_manager_reject_kills_swap(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.post(f"/api/swaps/{swap_req.id}/manager-reject", headers=auth_headers(req_cmd), json={"decision_note": "denied"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"
