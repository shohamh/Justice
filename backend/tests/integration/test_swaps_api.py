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
    and an open swap between them (via claim)."""
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
        requesting_soldier_id=requester.id, status="open", open_to_marketplace=True,
    )
    session.add(swap_req)
    session.commit()

    return requester, covering, req_cmd, cov_cmd, assignment, swap_req


def _candidate_id_for(body: dict, soldier_id) -> str:
    """Pull the candidate id for a given soldier out of a SwapOut body's
    `candidates` list."""
    cand = next(c for c in body["candidates"] if c["soldier_id"] == str(soldier_id))
    return cand["id"]


def test_soldier_can_approve_own_side(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.post(f"/api/me/swaps/{swap_req.id}/approve", headers=auth_headers(requester))
    assert r.status_code == 200, r.text
    assert r.json()["requester_side_approved"] is True
    assert r.json()["status"] == "open"


def test_non_party_soldier_cannot_approve(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})
    stranger = create_soldier(admin_session, personal_number=f"api_str_{_uid()}")

    r = client.post(f"/api/me/swaps/{swap_req.id}/approve", headers=auth_headers(stranger))
    assert r.status_code == 400


def test_full_approval_chain_applies_swap(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    claim_body = client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={}).json()
    candidate_id = _candidate_id_for(claim_body, covering.id)

    client.post(f"/api/me/swaps/{swap_req.id}/approve", headers=auth_headers(requester))
    client.post(f"/api/me/swaps/{swap_req.id}/approve", headers=auth_headers(covering))
    client.post(f"/api/swaps/{swap_req.id}/manager-approve", headers=auth_headers(req_cmd), json={"side": "requester"})
    r = client.post(
        f"/api/swaps/{swap_req.id}/manager-approve", headers=auth_headers(cov_cmd),
        json={"side": "covering", "candidate_id": candidate_id},
    )

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "applied"


def test_wrong_commander_cannot_manager_approve(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.post(f"/api/swaps/{swap_req.id}/manager-approve", headers=auth_headers(cov_cmd), json={"side": "requester"})
    assert r.status_code == 403


def test_manager_approve_requires_candidate_id_for_covering_side(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    claim_body = client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={}).json()
    candidate_id = _candidate_id_for(claim_body, covering.id)

    r_missing = client.post(
        f"/api/swaps/{swap_req.id}/manager-approve", headers=auth_headers(cov_cmd), json={"side": "covering"},
    )
    assert r_missing.status_code == 400

    r_ok = client.post(
        f"/api/swaps/{swap_req.id}/manager-approve", headers=auth_headers(cov_cmd),
        json={"side": "covering", "candidate_id": candidate_id},
    )
    assert r_ok.status_code == 200, r_ok.text


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
    assert r1.json()["status"] == "open"  # covering side's commander hasn't approved yet

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


def test_admin_override_approval_visible_in_manager_approvals(client: TestClient, admin_session: Session):
    """After an admin/duty-manager uses the override path to clear one side,
    the roster returned by the API must show that decision — not just leave
    every chain commander looking 'pending' with no visibility into what
    happened. The override decision row's commander_id is the override
    actor's own id (not any chain member's), so _manager_approvals_out must
    surface it as an extra entry alongside the live chain rows."""
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})
    admin = create_soldier(admin_session, personal_number=f"api_ovadm_{_uid()}", role="admin")

    r = client.post(f"/api/swaps/{swap_req.id}/manager-approve", headers=auth_headers(admin), json={"side": "requester"})
    assert r.status_code == 200, r.text
    body = r.json()
    # The swap isn't fully finalized yet — covering side's commander hasn't approved.
    assert body["status"] == "open"
    assert body["requester_side_approved"] is True

    requester_approvals = body["requester_manager_approvals"]
    # The live chain member (req_cmd) still shows as not personally approved...
    chain_row = next(a for a in requester_approvals if a["commander_id"] == str(req_cmd.id))
    assert chain_row["approved"] is False
    # ...but the override decision by the admin is surfaced as its own entry,
    # proving the roster reflects what actually happened rather than hiding it.
    override_row = next(a for a in requester_approvals if a["commander_id"] == str(admin.id))
    assert override_row["approved"] is True
    assert override_row["approved_by"] == str(admin.id)
    assert override_row["approver_kind"] == "commander"

    # Covering side (the candidate) is untouched by the override and still shows as pending.
    candidate = next(c for c in body["candidates"] if c["soldier_id"] == str(covering.id))
    assert all(a["commander_id"] != str(admin.id) for a in candidate["manager_approvals"])

    # Fetching the swap again (a fresh GET, not just the mutation response)
    # shows the same override decision — proving it's not a one-off artifact
    # of the approve response but genuinely persisted/live-computed.
    r2 = client.get("/api/swaps/pending", headers=auth_headers(cov_cmd))
    pending_swap = next((s for s in r2.json() if s["id"] == str(swap_req.id)), None)
    assert pending_swap is not None
    override_row_2 = next(
        a for a in pending_swap["requester_manager_approvals"] if a["commander_id"] == str(admin.id)
    )
    assert override_row_2["approved"] is True


def test_swap_out_includes_manager_approvals(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.get("/api/me/swaps", headers=auth_headers(requester))
    assert r.status_code == 200
    swap_out = next(s for s in r.json() if s["id"] == str(swap_req.id))
    assert len(swap_out["requester_manager_approvals"]) == 1
    assert swap_out["requester_manager_approvals"][0]["commander_id"] == str(req_cmd.id)
    assert swap_out["requester_manager_approvals"][0]["approved"] is False
    assert len(swap_out["candidates"]) == 1
    assert len(swap_out["candidates"][0]["manager_approvals"]) == 1


def test_swap_config_reports_duty_manager_setting(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number=f"api_cfg_adm_{_uid()}", role="admin")
    set_setting(admin_session, "swaps.require_duty_manager_approval", False, actor_id=None)
    admin_session.commit()

    r = client.get("/api/swaps/config", headers=auth_headers(admin))
    assert r.status_code == 200, r.text
    assert r.json() == {
        "require_manager_approval": True,
        "require_duty_manager_approval": False,
        "max_specific_targets": 5,
    }


def test_manager_approvals_out_order_matches_nearest_first_chain(client: TestClient, admin_session: Session):
    """The requester's node sits under a two-level chain: mid commander (nearest)
    and root commander (further). requester_manager_approvals is live-computed
    from commander_chain_for_soldier (nearest-first) rather than read from
    persisted rows ordered by chain_order — no SwapManagerApproval rows exist
    yet at this point (they're created lazily only once someone actually
    approves/rejects), so this asserts ordering purely from the live chain.
    Checked via both the single-swap path (/api/me/swaps) and the pending-list
    path (/api/swaps/pending), both of which now go through the same _out."""
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
        requesting_soldier_id=requester.id, status="open", open_to_marketplace=True,
    )
    admin_session.add(swap_req)
    admin_session.commit()

    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    # No SwapManagerApproval rows exist yet — they're created lazily, only
    # once someone actually approves/rejects a row. The ordering guarantee
    # this test cares about now comes entirely from the live chain
    # (commander_chain_for_soldier), not from persisted rows/chain_order.
    rows = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == swap_req.id,
            SwapManagerApproval.side == "requester",
        )
    ).scalars().all()
    assert len(rows) == 0

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
    swap_out_2 = next(s for s in r.json() if s["id"] == str(swap_req.id))
    approvals_2 = swap_out_2["requester_manager_approvals"]
    assert len(approvals_2) == 2
    assert approvals_2[0]["commander_id"] == str(mid_cmd.id)
    assert approvals_2[1]["commander_id"] == str(root_cmd.id)


def test_requester_reject_kills_whole_swap(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.post(f"/api/me/swaps/{swap_req.id}/reject", headers=auth_headers(requester), json={"decision_note": "changed my mind"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"


def test_candidate_reject_only_declines_own_candidacy(client: TestClient, admin_session: Session):
    """A candidate rejecting via /me/swaps/{id}/reject only declines their own
    candidacy (svc.decline_candidate) — it does not kill the whole parent
    request, unlike a requester-initiated reject."""
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.post(f"/api/me/swaps/{swap_req.id}/reject", headers=auth_headers(covering), json={"decision_note": "no thanks"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "open"
    candidate = next(c for c in body["candidates"] if c["soldier_id"] == str(covering.id))
    assert candidate["status"] == "declined"


def test_soldier_reject_ignores_stray_candidate_id(client: TestClient, admin_session: Session):
    """Regression check for the RejectRequest/ManagerRejectRequest schema
    split: /me/swaps/{id}/reject only accepts decision_note now, but extra
    unknown fields (like a stray candidate_id) are simply ignored by
    pydantic/FastAPI's default behavior, not rejected — the route still
    resolves the caller's own candidate server-side."""
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.post(
        f"/api/me/swaps/{swap_req.id}/reject",
        headers=auth_headers(requester),
        json={"decision_note": "changed my mind", "candidate_id": str(uuid.uuid4())},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"


def test_manager_reject_kills_swap(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.post(f"/api/swaps/{swap_req.id}/manager-reject", headers=auth_headers(req_cmd), json={"decision_note": "denied"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"


def test_manager_reject_records_rejecting_commander_on_row(client: TestClient, admin_session: Session):
    """A chain commander rejecting via manager-reject should route through
    reject_manager_row: their row on the live-computed roster should show
    rejected=True with rejected_by_name attributing them, and the top-level
    SwapOut should surface who rejected via rejected_by_name."""
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    claim_body = client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={}).json()
    candidate_id = _candidate_id_for(claim_body, covering.id)

    r = client.post(
        f"/api/swaps/{swap_req.id}/manager-reject", headers=auth_headers(req_cmd), json={"decision_note": "denied"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "rejected"
    assert body["rejected_by_name"] == req_cmd.full_name

    row = next(
        a for a in body["requester_manager_approvals"] if a["commander_id"] == str(req_cmd.id)
    )
    assert row["rejected"] is True
    assert row["rejected_by"] == str(req_cmd.id)
    assert row["rejected_by_name"] == req_cmd.full_name
    assert row["rejected_at"] is not None
    # The covering side's candidate/chain commander never acted — their row stays clean.
    candidate = next(c for c in body["candidates"] if str(c["id"]) == candidate_id)
    cov_row = next(
        a for a in candidate["manager_approvals"] if a["commander_id"] == str(cov_cmd.id)
    )
    assert cov_row["rejected"] is False
    assert cov_row["rejected_by"] is None


def test_manager_reject_covering_candidate_only(client: TestClient, admin_session: Session):
    """A covering-side commander rejecting a specific candidate via
    manager-reject with candidate_id only cancels that candidate — the parent
    request stays open (e.g. for other candidates or the marketplace)."""
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    claim_body = client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={}).json()
    candidate_id = _candidate_id_for(claim_body, covering.id)

    r = client.post(
        f"/api/swaps/{swap_req.id}/manager-reject", headers=auth_headers(cov_cmd),
        json={"decision_note": "denied", "candidate_id": candidate_id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "open"
    candidate = next(c for c in body["candidates"] if c["id"] == candidate_id)
    assert candidate["status"] == "cancelled"


def test_manager_reject_covering_without_candidate_id_requires_candidate_id(
    client: TestClient, admin_session: Session
):
    """A covering-side commander must supply candidate_id to be recognized as
    a qualifying approver on this request. Without it — and since they don't
    qualify via the requester side either — the route should surface a 400
    candidate_id_required, not a generic 403 forbidden (mirrors
    manager_approve's up-front check for the covering side)."""
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.post(
        f"/api/swaps/{swap_req.id}/manager-reject", headers=auth_headers(cov_cmd), json={"decision_note": "denied"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "candidate_id_required"


def test_manager_reject_candidate_scoped_when_actor_also_covers_requester_side(
    client: TestClient, admin_session: Session
):
    """Regression: a per-candidate manager reject must NOT escalate into a
    whole-request rejection just because the acting manager also happens to
    qualify on the requester's side.

    The existing covering-candidate test uses two disjoint hierarchy branches,
    so its covering-side commander never qualifies on the requester side — the
    realistic topology is the opposite: a commander (or a duty manager scoped
    over the whole unit) sits in BOTH the requester's chain and the candidate's
    chain. Before the fix, `_qualifying_rows_for_actor` returned the requester
    side too and reject_manager_row escalated to reject_request, killing the
    parent request and cancelling every sibling candidate."""
    shared_node = create_node(admin_session, level="unit", name=f"api_shrej_{_uid()}")
    shared_cmd = create_soldier(admin_session, personal_number=f"api_shrejc_{_uid()}", role="commander")
    shared_node.commander_id = shared_cmd.id
    admin_session.commit()

    requester = create_soldier(admin_session, personal_number=f"api_shrejr_{_uid()}", hierarchy_node_id=shared_node.id)
    cand_a = create_soldier(admin_session, personal_number=f"api_shreja_{_uid()}", hierarchy_node_id=shared_node.id)
    cand_b = create_soldier(admin_session, personal_number=f"api_shrejb_{_uid()}", hierarchy_node_id=shared_node.id)
    # Unit-wide duty manager: in the requester's chain AND both candidates'.
    create_soldier(
        admin_session, personal_number=f"api_shrejdm_{_uid()}", role="duty_manager",
        hierarchy_node_id=shared_node.id,
    )

    dt = DutyType(name=f"api_shrej_dt_{_uid()}", score_per_day=1)
    loc = DutyLocation(name=f"api_shrej_loc_{_uid()}")
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
        requesting_soldier_id=requester.id, status="open", open_to_marketplace=True,
    )
    admin_session.add(swap_req)
    admin_session.commit()

    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(cand_a), json={})
    body = client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(cand_b), json={}).json()
    cand_a_id = _candidate_id_for(body, cand_a.id)
    cand_b_id = _candidate_id_for(body, cand_b.id)

    # shared_cmd qualifies on BOTH sides — this is the topology that used to
    # escalate. Rejecting candidate A must stay scoped to candidate A.
    r = client.post(
        f"/api/swaps/{swap_req.id}/manager-reject", headers=auth_headers(shared_cmd),
        json={"decision_note": "not A", "candidate_id": cand_a_id},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "open", "per-candidate reject must not kill the parent request"
    assert next(c for c in out["candidates"] if c["id"] == cand_a_id)["status"] == "cancelled"
    assert next(c for c in out["candidates"] if c["id"] == cand_b_id)["status"] == "accepted"

    # The requester-side chain row is untouched: shared_cmd never said no to
    # the requester's ask, only to this one candidate.
    req_row = next(a for a in out["requester_manager_approvals"] if a["commander_id"] == str(shared_cmd.id))
    assert req_row["rejected"] is False
    assert req_row["rejected_by"] is None
    assert out["rejected_by_name"] is None

    persisted = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == swap_req.id,
            SwapManagerApproval.side == "requester",
        )
    ).scalars().all()
    assert persisted == [], "no requester-side decision row should have been stamped"


def test_admin_can_manager_reject_without_a_chain_row(client: TestClient, admin_session: Session):
    """Regression: an override-authorized actor (admin — no hierarchy node, no
    DutyManagerScope, so no qualifying chain row anywhere) must still be able
    to reject. Their approve counterpart already goes through
    approve_manager_side_override; reject briefly regressed to raising
    not_required_approver, which surfaced as a 400 for an action the route had
    already authorized."""
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})
    admin = create_soldier(admin_session, personal_number=f"api_rejadm_{_uid()}", role="admin")

    r = client.post(
        f"/api/swaps/{swap_req.id}/manager-reject", headers=auth_headers(admin),
        json={"decision_note": "denied by admin"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"


def test_manager_reject_with_mismatched_candidate_id_returns_400(
    client: TestClient, admin_session: Session
):
    """A candidate_id belonging to a DIFFERENT swap request must surface as a
    400 candidate_mismatch, not a 500: _side_node raises SwapError and that
    call used to sit outside manager_reject's try/except."""
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    # A second, unrelated swap request with its own candidate.
    other_requester, other_covering, *_rest, other_swap_req = _setup(admin_session)
    other_body = client.post(
        f"/api/swaps/{other_swap_req.id}/claim", headers=auth_headers(other_covering), json={}
    ).json()
    other_candidate_id = _candidate_id_for(other_body, other_covering.id)

    admin = create_soldier(admin_session, personal_number=f"api_mismadm_{_uid()}", role="admin")
    r = client.post(
        f"/api/swaps/{swap_req.id}/manager-reject", headers=auth_headers(admin),
        json={"decision_note": "denied", "candidate_id": other_candidate_id},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == "candidate_mismatch"


def test_claim_creates_commander_and_duty_manager_rows(client: TestClient, admin_session: Session):
    """Claiming a swap should surface both the chain-commander requirement and
    the duty-manager requirement in the API response's live-computed approval
    roster, on each side that has a soldier. SwapManagerApproval rows are no
    longer pre-populated on claim — they're created lazily only once someone
    actually approves/rejects — so this asserts against the live-computed
    requester_manager_approvals/candidate manager_approvals instead of
    persisted rows."""
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    # duty_manager_chain_for_soldier is scope-based (DutyManagerScope), not a
    # blanket "every duty_manager role" lookup — scope each DM to the
    # respective side's node so both sides have a live duty-manager requirement.
    create_soldier(
        admin_session, personal_number=f"api_dm_req_{_uid()}", role="duty_manager",
        hierarchy_node_id=requester.hierarchy_node_id,
    )
    create_soldier(
        admin_session, personal_number=f"api_dm_cov_{_uid()}", role="duty_manager",
        hierarchy_node_id=covering.hierarchy_node_id,
    )
    admin_session.commit()

    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    # No rows are persisted yet — the roster is live-computed.
    rows = admin_session.execute(
        select(SwapManagerApproval).where(SwapManagerApproval.swap_request_id == swap_req.id)
    ).scalars().all()
    assert len(rows) == 0

    r = client.get("/api/me/swaps", headers=auth_headers(requester))
    assert r.status_code == 200, r.text
    swap_out = next(s for s in r.json() if s["id"] == str(swap_req.id))
    candidate = next(c for c in swap_out["candidates"] if c["soldier_id"] == str(covering.id))
    requester_kinds = {a["approver_kind"] for a in swap_out["requester_manager_approvals"]}
    covering_kinds = {a["approver_kind"] for a in candidate["manager_approvals"]}
    assert "commander" in requester_kinds
    assert "duty_manager" in requester_kinds
    assert "commander" in covering_kinds
    assert "duty_manager" in covering_kinds
    assert all(not a["approved"] for a in swap_out["requester_manager_approvals"])
    assert all(not a["approved"] for a in candidate["manager_approvals"])


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
    # Scoped to shared_node, which both requester and covering sit under directly
    # — duty_manager_chain_for_soldier is DutyManagerScope-based, so this single
    # scope entry covers both sides.
    dm = create_soldier(
        admin_session, personal_number=f"api_shdm_{_uid()}", role="duty_manager",
        hierarchy_node_id=shared_node.id,
    )

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
        requesting_soldier_id=requester.id, status="open", open_to_marketplace=True,
    )
    admin_session.add(swap_req)
    admin_session.commit()

    svc.claim_request(admin_session, request_id=swap_req.id, covering_soldier_id=covering.id)
    from app.db.models import SwapCandidate
    candidate = admin_session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == swap_req.id, SwapCandidate.soldier_id == covering.id,
        )
    ).scalar_one()

    svc.approve_soldier_side(admin_session, request_id=swap_req.id, soldier_id=requester.id)
    svc.approve_soldier_side(admin_session, request_id=swap_req.id, soldier_id=covering.id)
    # approve_manager_row resolves every (side, kind) the actor currently
    # qualifies for in one call. The requester side is always checked; the
    # covering side is only resolved for a specific candidate_id (each
    # candidate is a distinct soldier with their own chain), so the caller
    # must identify which live candidate they're acting on — here the one
    # (and only) candidate on this swap. Since shared_cmd commands both
    # requester's and this candidate's node, one call cascades to both rows.
    svc.approve_manager_row(admin_session, request_id=swap_req.id, actor_id=shared_cmd.id, candidate_id=candidate.id)

    rows = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == swap_req.id,
            SwapManagerApproval.commander_id == shared_cmd.id,
        )
    ).scalars().all()
    assert len(rows) == 2  # requester side + covering side
    assert all(r.approved for r in rows)  # cascaded to both sides
    assert admin_session.get(SwapRequest, swap_req.id).status == "open"  # duty manager still required

    # Same for the duty manager: their single scope over shared_node covers
    # both sides, so one call (with the candidate_id) cascades to both sides'
    # duty_manager row.
    svc.approve_manager_row(admin_session, request_id=swap_req.id, actor_id=dm.id, candidate_id=candidate.id)
    dm_rows = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == swap_req.id,
            SwapManagerApproval.commander_id == dm.id,
        )
    ).scalars().all()
    assert len(dm_rows) == 2
    assert all(r.approved for r in dm_rows)
    assert admin_session.get(SwapRequest, swap_req.id).status == "applied"


def test_create_swap_with_both_targets_and_marketplace(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="unit", name=f"api_create_{_uid()}")
    requester = create_soldier(admin_session, personal_number=f"api_create_req_{_uid()}", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number=f"api_create_tgt_{_uid()}", hierarchy_node_id=node.id)
    dt = DutyType(name=f"api_create_dt_{_uid()}", score_per_day=1)
    loc = DutyLocation(name=f"api_create_loc_{_uid()}")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    assignment = DutyAssignment(
        duty_type_id=dt.id, duty_location_id=loc.id, soldier_id=requester.id,
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=2),
        status="published",
    )
    admin_session.add(assignment)
    admin_session.commit()

    r = client.post(
        "/api/me/swaps", headers=auth_headers(requester),
        json={
            "duty_assignment_id": str(assignment.id),
            "target_soldier_ids": [str(target.id)],
            "open_to_marketplace": True,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # A single object, not a list — create_request never fans out anymore.
    assert isinstance(body, dict)
    assert "id" in body
    assert body["open_to_marketplace"] is True
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["soldier_id"] == str(target.id)
    assert body["candidates"][0]["source"] == "invited"
    assert body["candidates"][0]["status"] == "pending"


def test_swap_out_shape_has_candidates_list_not_flat_covering_fields(client: TestClient, admin_session: Session):
    requester, covering, req_cmd, cov_cmd, assignment, swap_req = _setup(admin_session)
    client.post(f"/api/swaps/{swap_req.id}/claim", headers=auth_headers(covering), json={})

    r = client.get("/api/me/swaps", headers=auth_headers(requester))
    assert r.status_code == 200
    swap_out = next(s for s in r.json() if s["id"] == str(swap_req.id))
    assert isinstance(swap_out["candidates"], list)
    assert "covering_soldier_id" not in swap_out
    assert "target_soldier_id" not in swap_out
    assert "covering_side_approved" not in swap_out
    assert "covering_manager_approvals" not in swap_out
