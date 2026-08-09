from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.db.models import DutyAssignment, DutyLocation, DutyShift, DutyType, RangeType
from tests.helpers import auth_headers, create_node, create_soldier


def test_admin_sees_global_ineligible_count(client, admin_session):
    node = create_node(admin_session, level="branch", name="cnt-node-1")
    admin = create_soldier(admin_session, personal_number="cnt-admin-1", role="admin", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="cnt-sol-1", hierarchy_node_id=node.id)
    dt = DutyType(
        name="cnt-weapon-1", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    )
    loc = DutyLocation(name="cnt-loc-1")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        required_count=1, status="active",
    )
    admin_session.add(shift)
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        status="published", weapon_ineligible=True,
    )
    admin_session.add(assignment)
    admin_session.commit()

    r = client.get("/api/shifts/weapon-ineligible/count", headers=auth_headers(admin))
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_zero_count_when_no_ineligible_assignments(client, admin_session):
    admin = create_soldier(admin_session, personal_number="cnt-admin-2", role="admin")
    r = client.get("/api/shifts/weapon-ineligible/count", headers=auth_headers(admin))
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_duty_manager_sees_count_scoped_to_subtree(client, admin_session):
    """A duty manager scoped to a parent node must see ineligible assignments for
    soldiers in *descendant* nodes, not just soldiers on the exact scoped node
    (subtree expansion, not a bare exact-node match)."""
    parent = create_node(admin_session, level="brigade", name="cnt-parent-1")
    child = create_node(admin_session, level="battalion", name="cnt-child-1", parent=parent)
    other_branch = create_node(admin_session, level="brigade", name="cnt-other-1")

    dm = create_soldier(admin_session, personal_number="cnt-dm-1", role="duty_manager", hierarchy_node_id=parent.id)
    soldier_in_subtree = create_soldier(admin_session, personal_number="cnt-sol-2", hierarchy_node_id=child.id)
    soldier_out_of_scope = create_soldier(admin_session, personal_number="cnt-sol-3", hierarchy_node_id=other_branch.id)

    dt = DutyType(
        name="cnt-weapon-2", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser,
        eligible_node_ids=[parent.id, other_branch.id],
    )
    loc = DutyLocation(name="cnt-loc-2")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        required_count=2, status="active",
    )
    admin_session.add(shift)
    admin_session.flush()
    in_scope_assignment = DutyAssignment(
        soldier_id=soldier_in_subtree.id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        status="published", weapon_ineligible=True,
    )
    out_of_scope_assignment = DutyAssignment(
        soldier_id=soldier_out_of_scope.id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        status="published", weapon_ineligible=True,
    )
    admin_session.add_all([in_scope_assignment, out_of_scope_assignment])
    admin_session.commit()

    r = client.get("/api/shifts/weapon-ineligible/count", headers=auth_headers(dm))
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_user_with_no_scope_sees_zero_not_error(client, admin_session):
    node = create_node(admin_session, level="branch", name="cnt-node-3")
    soldier = create_soldier(admin_session, personal_number="cnt-sol-4", hierarchy_node_id=node.id)
    r = client.get("/api/shifts/weapon-ineligible/count", headers=auth_headers(soldier))
    assert r.status_code == 200
    assert r.json()["count"] == 0
