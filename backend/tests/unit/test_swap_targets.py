from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.db.models import DutyAssignment, DutyLocation, DutyType, ExemptionType, SoldierExemption
from app.services import swap_targets
from tests.helpers import create_node, create_soldier


def _setup_assignment(session, pn: str):
    dt = DutyType(name=f"dt_st_{pn}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_st_{pn}")
    session.add(dt)
    session.add(loc)
    session.flush()
    requester_node = create_node(session, level="branch", name=f"n_st_req_{pn}")
    requester = create_soldier(
        session, personal_number=f"st_req_{pn}", hierarchy_node_id=requester_node.id
    )
    assignment = DutyAssignment(
        soldier_id=requester.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2030, 2, 10),
        end_date=date(2030, 2, 10),
        status="published",
    )
    session.add(assignment)
    session.flush()
    session.commit()
    return requester, requester_node, dt, assignment


def test_list_eligible_targets_sorted_by_distance_and_excludes_ineligible(admin_session):
    requester, requester_node, dt, assignment = _setup_assignment(admin_session, "001")

    # Sibling node under the same parent as requester_node -> close candidate.
    root = create_node(admin_session, level="department", name="n_st_root_001", parent=None)
    admin_session.commit()

    # Re-parent requester's node under root so distance math is well-defined
    # (requester_node currently has no parent, i.e. it IS a root itself).
    sibling_node = create_node(admin_session, level="branch", name="n_st_sib_001", parent=root)
    far_root = create_node(admin_session, level="department", name="n_st_far_root_001", parent=None)
    far_branch = create_node(admin_session, level="branch", name="n_st_far_branch_001", parent=far_root)
    far_group = create_node(admin_session, level="group", name="n_st_far_group_001", parent=far_branch)
    admin_session.commit()

    close = create_soldier(admin_session, personal_number="st_close_001", hierarchy_node_id=sibling_node.id)
    far = create_soldier(admin_session, personal_number="st_far_001", hierarchy_node_id=far_group.id)

    # Exempt candidate: eligible node-wise but has a global exemption -> excluded.
    exempt_node = create_node(admin_session, level="branch", name="n_st_exempt_001", parent=root)
    exempt = create_soldier(admin_session, personal_number="st_exempt_001", hierarchy_node_id=exempt_node.id)
    et = ExemptionType(name="global_et_st_001", is_global=True)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(
        SoldierExemption(soldier_id=exempt.id, exemption_type_id=et.id, start_date="2025-01-01", end_date=None)
    )
    admin_session.commit()

    results = swap_targets.list_eligible_targets(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id
    )
    ids_in_order = [r["soldier_id"] for r in results]
    assert close.id in ids_in_order
    assert far.id in ids_in_order
    assert exempt.id not in ids_in_order
    assert ids_in_order.index(close.id) < ids_in_order.index(far.id)


def test_list_eligible_targets_excludes_requester(admin_session):
    requester, requester_node, dt, assignment = _setup_assignment(admin_session, "002")
    results = swap_targets.list_eligible_targets(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=assignment.id
    )
    assert requester.id not in [r["soldier_id"] for r in results]


def test_list_eligible_targets_missing_assignment_returns_empty(admin_session):
    requester, _requester_node, _dt, _assignment = _setup_assignment(admin_session, "003")
    import uuid

    results = swap_targets.list_eligible_targets(
        admin_session, requesting_soldier_id=requester.id, duty_assignment_id=uuid.uuid4()
    )
    assert results == []
