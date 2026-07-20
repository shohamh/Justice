from __future__ import annotations

import uuid

from sqlalchemy import select

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


from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import DutyAssignment, DutyLocation, DutyType, HierarchyNode, SwapManagerApproval, SwapRequest


def _make_assignment(session, *, soldier, node):
    dt = DutyType(name=f"dt_{_uid()}", score_per_day=Decimal("1.0"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    session.add_all([dt, loc])
    session.flush()
    a = DutyAssignment(
        duty_type_id=dt.id, duty_location_id=loc.id, soldier_id=soldier.id,
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=2),
        status="published",
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def test_commander_chain_walks_to_root(admin_session):
    from app.services.swaps import commander_chain_for_soldier

    root = create_node(admin_session, level="division", name=f"root_{_uid()}")
    root_cmd = create_soldier(admin_session, personal_number=f"rc_{_uid()}", role="commander")
    root.commander_id = root_cmd.id
    mid = create_node(admin_session, level="unit", name=f"mid_{_uid()}", parent=root)
    mid_cmd = create_soldier(admin_session, personal_number=f"mc_{_uid()}", role="commander")
    mid.commander_id = mid_cmd.id
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=mid.id)

    chain = commander_chain_for_soldier(admin_session, soldier.id)
    assert chain == [mid_cmd.id, root_cmd.id]


def test_commander_chain_orders_nearest_first(admin_session):
    """The soldier's own node has no commander; mid has commander B; root has
    commander A. The chain must come back nearest-first: [B, A] — not [A, B]
    and not merely the same set."""
    from app.services.swaps import commander_chain_for_soldier

    root = create_node(admin_session, level="division", name=f"root_{_uid()}")
    root_cmd = create_soldier(admin_session, personal_number=f"rc2_{_uid()}", role="commander")
    root.commander_id = root_cmd.id
    mid = create_node(admin_session, level="unit", name=f"mid2_{_uid()}", parent=root)
    mid_cmd = create_soldier(admin_session, personal_number=f"mc2_{_uid()}", role="commander")
    mid.commander_id = mid_cmd.id
    leaf = create_node(admin_session, level="team", name=f"leaf_{_uid()}", parent=mid)
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number=f"s2_{_uid()}", hierarchy_node_id=leaf.id)

    chain = commander_chain_for_soldier(admin_session, soldier.id)
    assert chain == [mid_cmd.id, root_cmd.id]


def test_commander_chain_excludes_soldier_commanding_own_node(admin_session):
    from app.services.swaps import commander_chain_for_soldier

    node = create_node(admin_session, level="unit", name=f"self_cmd_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=node.id, role="commander")
    node.commander_id = soldier.id
    admin_session.commit()

    chain = commander_chain_for_soldier(admin_session, soldier.id)
    assert soldier.id not in chain


def test_commander_chain_empty_when_no_commanders(admin_session):
    from app.services.swaps import commander_chain_for_soldier

    node = create_node(admin_session, level="unit", name=f"no_cmd_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=node.id)

    chain = commander_chain_for_soldier(admin_session, soldier.id)
    assert chain == []


def _setup_pending_swap(session, *, with_commanders: bool):
    node = create_node(session, level="unit", name=f"pend_{_uid()}")
    requester_cmd = create_soldier(session, personal_number=f"rcmd_{_uid()}", role="commander")
    covering_cmd = create_soldier(session, personal_number=f"ccmd_{_uid()}", role="commander")
    if with_commanders:
        node.commander_id = requester_cmd.id
    session.commit()
    requester = create_soldier(session, personal_number=f"req_{_uid()}", hierarchy_node_id=node.id)
    node2 = create_node(session, level="unit", name=f"pend2_{_uid()}")
    if with_commanders:
        node2.commander_id = covering_cmd.id
        session.commit()
    covering = create_soldier(session, personal_number=f"cov_{_uid()}", hierarchy_node_id=node2.id)
    assignment = _make_assignment(session, soldier=requester, node=node)

    from app.services.swaps import claim_request
    req = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=assignment.start_date,
        requesting_soldier_id=requester.id, status="open",
    )
    session.add(req)
    session.commit()
    req = claim_request(session, request_id=req.id, covering_soldier_id=covering.id)
    session.commit()
    return req, requester, covering, requester_cmd, covering_cmd


def test_claim_creates_manager_approval_rows_for_both_chains(admin_session):
    req, requester, covering, requester_cmd, covering_cmd = _setup_pending_swap(admin_session, with_commanders=True)

    rows = admin_session.execute(
        select(SwapManagerApproval).where(SwapManagerApproval.swap_request_id == req.id)
    ).scalars().all()
    by_side = {"requester": [], "covering": []}
    for r in rows:
        by_side[r.side].append(r.commander_id)
    assert by_side["requester"] == [requester_cmd.id]
    assert by_side["covering"] == [covering_cmd.id]


def test_finalize_requires_both_soldiers_and_all_managers(admin_session):
    from app.services.swaps import approve_soldier_side, approve_manager_row

    req, requester, covering, requester_cmd, covering_cmd = _setup_pending_swap(admin_session, with_commanders=True)

    approve_soldier_side(admin_session, request_id=req.id, soldier_id=requester.id)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.status == "pending_approval"

    approve_soldier_side(admin_session, request_id=req.id, soldier_id=covering.id)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.status == "pending_approval"  # managers haven't approved yet

    approve_manager_row(admin_session, request_id=req.id, side="requester", commander_id=requester_cmd.id, actor_id=requester_cmd.id)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.status == "pending_approval"  # covering-side manager still pending

    approve_manager_row(admin_session, request_id=req.id, side="covering", commander_id=covering_cmd.id, actor_id=covering_cmd.id)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.status == "applied"


def test_finalize_with_no_commanders_needs_only_soldiers(admin_session):
    from app.services.swaps import approve_soldier_side

    req, requester, covering, _, _ = _setup_pending_swap(admin_session, with_commanders=False)

    approve_soldier_side(admin_session, request_id=req.id, soldier_id=requester.id)
    admin_session.commit()
    approve_soldier_side(admin_session, request_id=req.id, soldier_id=covering.id)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.status == "applied"


def test_approve_soldier_side_rejects_non_party(admin_session):
    from app.services.swaps import approve_soldier_side, SwapError

    req, requester, covering, _, _ = _setup_pending_swap(admin_session, with_commanders=False)
    stranger = create_soldier(admin_session, personal_number=f"str_{_uid()}")

    with pytest.raises(SwapError, match="not_a_party"):
        approve_soldier_side(admin_session, request_id=req.id, soldier_id=stranger.id)


def test_approve_manager_row_rejects_wrong_commander(admin_session):
    from app.services.swaps import approve_manager_row, SwapError

    req, *_rest = _setup_pending_swap(admin_session, with_commanders=True)
    stranger = create_soldier(admin_session, personal_number=f"str2_{_uid()}")

    with pytest.raises(SwapError, match="not_required_approver"):
        approve_manager_row(admin_session, request_id=req.id, side="requester", commander_id=stranger.id, actor_id=stranger.id)


def _setup_pending_swap_with_chain(session):
    """Requester side has TWO chain commanders (mid + root); covering side has none."""
    root = create_node(session, level="division", name=f"root_{_uid()}")
    root_cmd = create_soldier(session, personal_number=f"rc_{_uid()}", role="commander")
    root.commander_id = root_cmd.id
    mid = create_node(session, level="unit", name=f"mid_{_uid()}", parent=root)
    mid_cmd = create_soldier(session, personal_number=f"mc_{_uid()}", role="commander")
    mid.commander_id = mid_cmd.id
    session.commit()
    requester = create_soldier(session, personal_number=f"req_{_uid()}", hierarchy_node_id=mid.id)
    cov_node = create_node(session, level="unit", name=f"covn_{_uid()}")
    covering = create_soldier(session, personal_number=f"cov_{_uid()}", hierarchy_node_id=cov_node.id)
    assignment = _make_assignment(session, soldier=requester, node=mid)

    from app.services.swaps import claim_request
    req = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=assignment.start_date,
        requesting_soldier_id=requester.id, status="open",
    )
    session.add(req)
    session.commit()
    req = claim_request(session, request_id=req.id, covering_soldier_id=covering.id)
    session.commit()
    return req, requester, covering, mid_cmd, root_cmd


def test_any_one_chain_commander_approval_suffices_for_side(admin_session):
    """Per the product clarification, only ONE commander anywhere in a side's
    chain needs to approve — not every one of them."""
    from app.services.swaps import approve_manager_row, approve_soldier_side

    req, requester, covering, mid_cmd, root_cmd = _setup_pending_swap_with_chain(admin_session)

    approve_soldier_side(admin_session, request_id=req.id, soldier_id=requester.id)
    approve_soldier_side(admin_session, request_id=req.id, soldier_id=covering.id)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.status == "pending_approval"  # no chain commander has approved yet

    # Only the mid-level commander approves — the root commander's row stays untouched.
    approve_manager_row(admin_session, request_id=req.id, side="requester", commander_id=mid_cmd.id, actor_id=mid_cmd.id)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.status == "applied"  # one approval on the side was enough

    root_row = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == req.id,
            SwapManagerApproval.side == "requester",
            SwapManagerApproval.commander_id == root_cmd.id,
        )
    ).scalar_one()
    assert root_row.approved is False  # left untouched, not cleared


def test_same_commander_reapproving_is_a_harmless_noop(admin_session):
    """A legitimate chain commander clicking approve a second time must be a
    no-op via the normal path — it must NOT reroute into the override path
    (which would incorrectly clear other pending rows on the OLD "require
    all" semantics, and is meant for people outside the chain regardless)."""
    from app.services.swaps import approve_manager_row, approve_soldier_side

    # Two-sided setup so the swap stays pending_approval after the requester
    # side's single commander approves (covering side's commander hasn't).
    req, requester, covering, requester_cmd, covering_cmd = _setup_pending_swap(admin_session, with_commanders=True)
    approve_soldier_side(admin_session, request_id=req.id, soldier_id=requester.id)
    approve_soldier_side(admin_session, request_id=req.id, soldier_id=covering.id)
    admin_session.commit()

    approve_manager_row(admin_session, request_id=req.id, side="requester", commander_id=requester_cmd.id, actor_id=requester_cmd.id)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.status == "pending_approval"  # covering side's commander still pending

    row = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == req.id,
            SwapManagerApproval.side == "requester",
            SwapManagerApproval.commander_id == requester_cmd.id,
        )
    ).scalar_one()
    first_approved_at = row.approved_at
    first_approved_by = row.approved_by

    # Second click by the same commander: no error, original approval record
    # untouched, swap still not finalized (covering side still pending).
    approve_manager_row(admin_session, request_id=req.id, side="requester", commander_id=requester_cmd.id, actor_id=requester_cmd.id)
    admin_session.commit()
    admin_session.refresh(row)
    admin_session.refresh(req)
    assert row.approved_at == first_approved_at
    assert row.approved_by == first_approved_by
    assert req.status == "pending_approval"


def test_is_chain_commander_for_side_true_regardless_of_approval_state(admin_session):
    from app.services.swaps import approve_manager_row, is_chain_commander_for_side

    req, requester, covering, mid_cmd, root_cmd = _setup_pending_swap_with_chain(admin_session)

    assert is_chain_commander_for_side(admin_session, request_id=req.id, side="requester", commander_id=mid_cmd.id)
    approve_manager_row(admin_session, request_id=req.id, side="requester", commander_id=mid_cmd.id, actor_id=mid_cmd.id)
    admin_session.commit()
    # Still True after approving — chain membership, not "still pending".
    assert is_chain_commander_for_side(admin_session, request_id=req.id, side="requester", commander_id=mid_cmd.id)


def test_stranger_is_not_a_chain_commander_and_cannot_approve(admin_session):
    from app.services.swaps import SwapError, approve_manager_side, is_chain_commander_for_side

    req, *_rest = _setup_pending_swap_with_chain(admin_session)
    stranger = create_soldier(admin_session, personal_number=f"str3_{_uid()}")

    assert not is_chain_commander_for_side(
        admin_session, request_id=req.id, side="requester", commander_id=stranger.id
    )
    with pytest.raises(SwapError, match="forbidden"):
        approve_manager_side(
            admin_session, request_id=req.id, side="requester", actor_id=stranger.id,
            is_authorized_override=False,
        )


def test_approve_manager_side_override_clears_all_rows_for_side(admin_session):
    from app.services.swaps import approve_manager_side_override, approve_soldier_side

    req, requester, covering, requester_cmd, covering_cmd = _setup_pending_swap(admin_session, with_commanders=True)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    approve_soldier_side(admin_session, request_id=req.id, soldier_id=requester.id)
    approve_soldier_side(admin_session, request_id=req.id, soldier_id=covering.id)
    admin_session.commit()

    approve_manager_side_override(admin_session, request_id=req.id, side="requester", actor_id=admin.id)
    admin_session.commit()
    row = admin_session.execute(
        select(SwapManagerApproval).where(
            SwapManagerApproval.swap_request_id == req.id, SwapManagerApproval.side == "requester"
        )
    ).scalar_one()
    assert row.approved is True
    assert row.approved_by == admin.id

    approve_manager_side_override(admin_session, request_id=req.id, side="covering", actor_id=admin.id)
    admin_session.commit()
    admin_session.refresh(req)
    assert req.status == "applied"
