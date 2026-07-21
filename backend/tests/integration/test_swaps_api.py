from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyAssignment, DutyLocation, DutyType, SwapManagerApproval, SwapRequest
from app.services import swaps as svc
from app.services.settings_loader import set_setting
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


def test_swap_config_reports_duty_manager_setting(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number=f"api_cfg_adm_{_uid()}", role="admin")
    set_setting(admin_session, "swaps.require_duty_manager_approval", False, actor_id=None)
    admin_session.commit()

    r = client.get("/api/swaps/config", headers=auth_headers(admin))
    assert r.status_code == 200, r.text
    assert r.json() == {"require_manager_approval": True, "require_duty_manager_approval": False}


def test_manager_approvals_out_order_matches_nearest_first_chain(client: TestClient, admin_session: Session):
    """The requester's node sits under a two-level chain: mid commander (nearest)
    and root commander (further). All rows for this side are created in a single
    flush and share the same created_at, so only chain_order can guarantee that
    requester_manager_approvals[0] is genuinely the nearest commander — the
    thing DirectCommanderApproval.tsx on the frontend relies on. Checked via
    both the single-swap path (/api/me/swaps, _manager_approvals_out) and the
    bulk path (/api/swaps/pending, _manager_approvals_out_bulk)."""
    root_node = create_node(admin_session, level="division", name=f"api_root_{_uid()}")
    root_cmd = create_soldier(admin_session, personal_number=f"api_rootc_{_uid()}", role="commander")
    root_node.commander_id = root_cmd.id
    mid_node = create_node(admin_session, level="unit", name=f"api_mid_{_uid()}", parent=root_node)
    mid_cmd = create_soldier(admin_session, personal_number=f"api_midc_{_uid()}", role="commander")
    mid_node.commander_id = mid_cmd.id
    admin_session.commit()

    requester = create_soldier(admin_session, personal_number=f"api_chain_req_{_uid()}", hierarchy_node_id=mid_node.id)
    covering = create_soldier(admin_session, personal_number=f"api_chain_cov_{_uid()}")

    dt = DutyType(name=f"api_chain_dt_{_uid()}", score_per_day=1)
    loc = DutyLocation(name=f"api_chain_loc_{_uid()}")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    assignment = DutyAssignment(
        duty_type_id=dt.id, duty_location_id=loc.id, soldier_id=requester.id,
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=2),
        status="published",
    )
    admin_session.add(assignment)
    admin_session.flush()
    swap_req = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=assignment.start_date,
        requesting_soldier_id=requester.id, status="open",
    )
    admin_session.add(swap_req)
    admin_session.commit()

    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    # All rows for this side share one created_at (single flush inside
    # _create_manager_approval_rows) — assert that precondition still holds,
    # so this test would actually fail if chain_order were removed/ignored.
    rows = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == swap_req.id,
            SwapManagerApproval.side == "requester",
        )
    ).scalars().all()
    assert len({row.created_at for row in rows}) == 1
    assert len(rows) == 2

    r = client.get("/api/me/swaps", headers=auth_headers(requester))
    assert r.status_code == 200, r.text
    swap_out = next(s for s in r.json() if s["id"] == str(swap_req.id))
    approvals = swap_out["requester_manager_approvals"]
    assert len(approvals) == 2
    assert approvals[0]["commander_id"] == str(mid_cmd.id)
    assert approvals[1]["commander_id"] == str(root_cmd.id)

    admin = create_soldier(admin_session, personal_number=f"api_chain_adm_{_uid()}", role="admin")
    r = client.get("/api/swaps/pending", headers=auth_headers(admin))
    assert r.status_code == 200, r.text
    swap_out_bulk = next(s for s in r.json() if s["id"] == str(swap_req.id))
    approvals_bulk = swap_out_bulk["requester_manager_approvals"]
    assert len(approvals_bulk) == 2
    assert approvals_bulk[0]["commander_id"] == str(mid_cmd.id)
    assert approvals_bulk[1]["commander_id"] == str(root_cmd.id)


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


def test_claim_creates_commander_and_duty_manager_rows(client: TestClient, admin_session: Session):
    """Claiming a swap should create SwapManagerApproval rows for both the
    chain-commander requirement and the duty-manager requirement, on each
    side that has a soldier."""
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    create_soldier(admin_session, personal_number=f"api_dm_{_uid()}", role="duty_manager")
    admin_session.commit()

    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    rows = admin_session.execute(
        select(SwapManagerApproval).where(SwapManagerApproval.swap_request_id == swap_req.id)
    ).scalars().all()
    kinds_by_side = {(r.side, r.approver_kind) for r in rows}
    assert ("requester", "commander") in kinds_by_side
    assert ("requester", "duty_manager") in kinds_by_side
    assert ("covering", "commander") in kinds_by_side
    assert ("covering", "duty_manager") in kinds_by_side


def test_shared_commander_approval_cascades_to_other_side(admin_session: Session):
    """A commander shared by both sides (requester and covering both report to
    the same immediate commander) should only need to approve once — that
    approval cascades to their row on the other side. But the swap still
    isn't finalized until the duty manager (a separate, distinct required
    approver kind) has also approved."""
    shared_node = create_node(admin_session, level="unit", name=f"api_shared_{_uid()}")
    shared_cmd = create_soldier(admin_session, personal_number=f"api_shcmd_{_uid()}", role="commander")
    shared_node.commander_id = shared_cmd.id
    admin_session.commit()

    requester = create_soldier(admin_session, personal_number=f"api_shreq_{_uid()}", hierarchy_node_id=shared_node.id)
    covering = create_soldier(admin_session, personal_number=f"api_shcov_{_uid()}", hierarchy_node_id=shared_node.id)
    dm = create_soldier(admin_session, personal_number=f"api_shdm_{_uid()}", role="duty_manager")

    dt = DutyType(name=f"api_sh_dt_{_uid()}", score_per_day=1)
    loc = DutyLocation(name=f"api_sh_loc_{_uid()}")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    assignment = DutyAssignment(
        duty_type_id=dt.id, duty_location_id=loc.id, soldier_id=requester.id,
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=2),
        status="published",
    )
    admin_session.add(assignment)
    admin_session.flush()
    swap_req = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=assignment.start_date,
        requesting_soldier_id=requester.id, status="open",
    )
    admin_session.add(swap_req)
    admin_session.commit()

    svc.claim_request(admin_session, request_id=swap_req.id, covering_soldier_id=covering.id)

    svc.approve_soldier_side(admin_session, request_id=swap_req.id, soldier_id=requester.id)
    svc.approve_soldier_side(admin_session, request_id=swap_req.id, soldier_id=covering.id)
    svc.approve_manager_row(
        admin_session, request_id=swap_req.id, side="requester", commander_id=shared_cmd.id, actor_id=shared_cmd.id,
    )

    rows = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == swap_req.id,
            SwapManagerApproval.commander_id == shared_cmd.id,
        )
    ).scalars().all()
    assert len(rows) == 2  # requester side + covering side
    assert all(r.approved for r in rows)  # cascaded to both sides
    assert admin_session.get(SwapRequest, swap_req.id).status == "pending_approval"  # duty manager still required

    svc.approve_manager_row(
        admin_session, request_id=swap_req.id, side="requester", commander_id=dm.id, actor_id=dm.id,
    )
    dm_rows = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == swap_req.id,
            SwapManagerApproval.commander_id == dm.id,
        )
    ).scalars().all()
    assert len(dm_rows) == 2
    assert all(r.approved for r in dm_rows)
    assert admin_session.get(SwapRequest, swap_req.id).status == "applied"
