from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.db.models import AuditLog, DutyLocation, DutyType, Soldier
from app.services.duty_config import create_duty_type
from app.services.shift_quotas import (
    ShiftQuotaError,
    compute_potential_split,
    compute_potential_split_multi,
    compute_two_level_split,
    get_shift_quotas,
    set_shift_quotas,
)
from app.services.shifts import create_shift
from tests.helpers import create_node, create_soldier

import pytest
from datetime import date


def _make_shift(session, name_suffix: str, required_count: int):
    dt = create_duty_type(session, name=f"dt_quota_{name_suffix}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_quota_{name_suffix}")
    session.add(loc)
    session.flush()
    shift = create_shift(
        session, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 1), end_date=date(2026, 6, 2),
        required_count=required_count,
    )
    session.flush()
    return shift


def test_set_quotas_within_required_count(admin_session):
    shift = _make_shift(admin_session, "1", required_count=5)
    node_a = create_node(admin_session, level="branch", name="ענף פוקוס")
    node_b = create_node(admin_session, level="branch", name="ענף אלומות")

    set_shift_quotas(admin_session, shift_id=shift.id, quotas=[
        (node_a.id, 2), (node_b.id, 3),
    ])
    admin_session.flush()

    result = get_shift_quotas(admin_session, shift_id=shift.id)
    assert {(q.hierarchy_node_id, q.count) for q in result} == {(node_a.id, 2), (node_b.id, 3)}


def test_set_quotas_over_required_count_raises(admin_session):
    shift = _make_shift(admin_session, "2", required_count=3)
    node_a = create_node(admin_session, level="branch", name="ענף פוקוס")
    node_b = create_node(admin_session, level="branch", name="ענף אלומות")

    with pytest.raises(ShiftQuotaError, match="quota_sum_exceeds_required_count"):
        set_shift_quotas(admin_session, shift_id=shift.id, quotas=[(node_a.id, 2), (node_b.id, 2)])


def test_set_quotas_unknown_node_raises(admin_session):
    shift = _make_shift(admin_session, "3", required_count=3)
    with pytest.raises(ShiftQuotaError, match="hierarchy_node_not_found"):
        set_shift_quotas(admin_session, shift_id=shift.id, quotas=[(uuid.uuid4(), 1)])


def test_set_quotas_replaces_existing(admin_session):
    shift = _make_shift(admin_session, "4", required_count=5)
    node_a = create_node(admin_session, level="branch", name="ענף פוקוס")
    node_b = create_node(admin_session, level="branch", name="ענף אלומות")

    set_shift_quotas(admin_session, shift_id=shift.id, quotas=[(node_a.id, 2)])
    admin_session.flush()
    set_shift_quotas(admin_session, shift_id=shift.id, quotas=[(node_b.id, 3)])
    admin_session.flush()

    result = get_shift_quotas(admin_session, shift_id=shift.id)
    assert {(q.hierarchy_node_id, q.count) for q in result} == {(node_b.id, 3)}


def test_set_quotas_writes_audit_log(admin_session):
    shift = _make_shift(admin_session, "5", required_count=5)
    node_a = create_node(admin_session, level="branch", name="ענף פוקוס")
    actor_id = uuid.uuid4()

    set_shift_quotas(
        admin_session, shift_id=shift.id, quotas=[(node_a.id, 2)], actor_id=actor_id,
    )
    admin_session.flush()

    audit_entry = admin_session.execute(
        select(AuditLog).where(
            AuditLog.action == "shift.set_node_quotas",
            AuditLog.entity_id == shift.id,
        )
    ).scalar_one()
    assert audit_entry.actor_id == actor_id
    assert audit_entry.before == []
    assert audit_entry.after == [{"node_id": str(node_a.id), "count": 2}]


def _make_permissive_duty_type(session, name: str):
    dt = DutyType(name=name, score_per_day=Decimal("1.00"), requirements={})
    session.add(dt)
    session.flush()
    return dt


def test_compute_potential_split_even_weights(admin_session):
    _make_permissive_duty_type(admin_session, "dt_pot_even")
    parent = create_node(admin_session, level="unit", name="pot_even_parent")
    child_a = create_node(admin_session, level="branch", name="pot_even_a", parent=parent)
    child_b = create_node(admin_session, level="branch", name="pot_even_b", parent=parent)
    create_soldier(admin_session, personal_number="pe_a1", hierarchy_node_id=child_a.id)
    create_soldier(admin_session, personal_number="pe_a2", hierarchy_node_id=child_a.id)
    create_soldier(admin_session, personal_number="pe_b1", hierarchy_node_id=child_b.id)
    create_soldier(admin_session, personal_number="pe_b2", hierarchy_node_id=child_b.id)

    result = compute_potential_split(admin_session, parent_node_id=parent.id, required_count=10)

    by_name = {r["node_name"]: r for r in result}
    assert by_name["pot_even_a"]["count"] == 5
    assert by_name["pot_even_b"]["count"] == 5
    assert by_name["pot_even_a"]["weight"] == 2
    assert by_name["pot_even_b"]["weight"] == 2
    assert sum(r["count"] for r in result) == 10


def test_compute_potential_split_uneven_weights_sums_exactly(admin_session):
    _make_permissive_duty_type(admin_session, "dt_pot_uneven")
    parent = create_node(admin_session, level="unit", name="pot_uneven_parent")
    child_a = create_node(admin_session, level="branch", name="pot_uneven_a", parent=parent)
    child_b = create_node(admin_session, level="branch", name="pot_uneven_b", parent=parent)
    child_c = create_node(admin_session, level="branch", name="pot_uneven_c", parent=parent)
    for i in range(3):
        create_soldier(admin_session, personal_number=f"pu_a{i}", hierarchy_node_id=child_a.id)
    for i in range(2):
        create_soldier(admin_session, personal_number=f"pu_b{i}", hierarchy_node_id=child_b.id)
    create_soldier(admin_session, personal_number="pu_c0", hierarchy_node_id=child_c.id)

    # weights 3:2:1 (total 6), required_count=10 -> raw shares 5.0:3.33:1.67
    result = compute_potential_split(admin_session, parent_node_id=parent.id, required_count=10)

    assert sum(r["count"] for r in result) == 10
    by_name = {r["node_name"]: r["count"] for r in result}
    assert by_name["pot_uneven_a"] == 5
    assert by_name["pot_uneven_b"] == 3
    assert by_name["pot_uneven_c"] == 2


def test_compute_potential_split_zero_weight_child_gets_zero_count(admin_session):
    _make_permissive_duty_type(admin_session, "dt_pot_zero")
    parent = create_node(admin_session, level="unit", name="pot_zero_parent")
    child_a = create_node(admin_session, level="branch", name="pot_zero_a", parent=parent)
    child_b = create_node(admin_session, level="branch", name="pot_zero_b", parent=parent)
    create_soldier(admin_session, personal_number="pz_a1", hierarchy_node_id=child_a.id)

    result = compute_potential_split(admin_session, parent_node_id=parent.id, required_count=4)

    by_name = {r["node_name"]: r for r in result}
    assert by_name["pot_zero_a"]["count"] == 4
    assert by_name["pot_zero_b"]["count"] == 0
    assert by_name["pot_zero_b"]["weight"] == 0


def test_compute_potential_split_all_zero_weight_falls_back_to_even_split(admin_session):
    # No DutyType created at all -> every child has final_potential == 0.
    parent = create_node(admin_session, level="unit", name="pot_allzero_parent")
    create_node(admin_session, level="branch", name="pot_allzero_a", parent=parent)
    create_node(admin_session, level="branch", name="pot_allzero_b", parent=parent)
    create_node(admin_session, level="branch", name="pot_allzero_c", parent=parent)

    result = compute_potential_split(admin_session, parent_node_id=parent.id, required_count=10)

    assert sum(r["count"] for r in result) == 10
    counts = sorted(r["count"] for r in result)
    assert counts == [3, 3, 4]


def test_compute_potential_split_no_children_raises(admin_session):
    leaf = create_node(admin_session, level="team", name="pot_leaf")

    with pytest.raises(ShiftQuotaError, match="parent_node_no_children"):
        compute_potential_split(admin_session, parent_node_id=leaf.id, required_count=5)


def test_compute_potential_split_invalid_required_count_raises(admin_session):
    parent = create_node(admin_session, level="unit", name="pot_invalid_parent")
    create_node(admin_session, level="branch", name="pot_invalid_a", parent=parent)

    with pytest.raises(ShiftQuotaError, match="required_count_must_be_positive"):
        compute_potential_split(admin_session, parent_node_id=parent.id, required_count=0)


def test_compute_potential_split_multi_arbitrary_nodes(admin_session):
    _make_permissive_duty_type(admin_session, "dt_multi")
    unrelated_parent_a = create_node(admin_session, level="unit", name="multi_parent_a")
    unrelated_parent_b = create_node(admin_session, level="unit", name="multi_parent_b")
    node_a = create_node(admin_session, level="branch", name="multi_a", parent=unrelated_parent_a)
    node_b = create_node(admin_session, level="branch", name="multi_b", parent=unrelated_parent_b)
    for i in range(3):
        create_soldier(admin_session, personal_number=f"multi_a{i}", hierarchy_node_id=node_a.id)
    create_soldier(admin_session, personal_number="multi_b0", hierarchy_node_id=node_b.id)

    result = compute_potential_split_multi(
        admin_session, node_ids=[node_a.id, node_b.id], required_count=8
    )

    by_name = {r["node_name"]: r["count"] for r in result}
    assert by_name["multi_a"] == 6
    assert by_name["multi_b"] == 2
    assert sum(r["count"] for r in result) == 8


def test_compute_two_level_split_splits_across_units_then_children(admin_session):
    _make_permissive_duty_type(admin_session, "dt_two_level")
    unit_a = create_node(admin_session, level="unit", name="two_level_unit_a")
    unit_b = create_node(admin_session, level="unit", name="two_level_unit_b")
    child_a1 = create_node(admin_session, level="branch", name="two_level_a1", parent=unit_a)
    child_a2 = create_node(admin_session, level="branch", name="two_level_a2", parent=unit_a)
    child_b1 = create_node(admin_session, level="branch", name="two_level_b1", parent=unit_b)
    # unit_a: 2 soldiers each under a1/a2 (potential 4 total); unit_b: 4 soldiers under b1 (potential 4 total)
    for i in range(2):
        create_soldier(admin_session, personal_number=f"tl_a1_{i}", hierarchy_node_id=child_a1.id)
        create_soldier(admin_session, personal_number=f"tl_a2_{i}", hierarchy_node_id=child_a2.id)
    for i in range(4):
        create_soldier(admin_session, personal_number=f"tl_b1_{i}", hierarchy_node_id=child_b1.id)

    result = compute_two_level_split(
        admin_session, responsible_node_ids=[unit_a.id, unit_b.id], required_count=8
    )

    # Step A: unit_a and unit_b each get 4 (equal potential 4:4).
    # Step B: unit_a's 4 split evenly 2:2 across a1/a2; unit_b's 4 all go to its only child b1.
    by_name = {r["node_name"]: r["count"] for r in result}
    assert by_name["two_level_a1"] == 2
    assert by_name["two_level_a2"] == 2
    assert by_name["two_level_b1"] == 4
    assert sum(r["count"] for r in result) == 8
    parent_map = {r["node_name"]: r["parent_responsible_node_id"] for r in result}
    assert parent_map["two_level_a1"] == unit_a.id
    assert parent_map["two_level_b1"] == unit_b.id


def test_compute_two_level_split_leaf_responsible_unit_with_no_children(admin_session):
    _make_permissive_duty_type(admin_session, "dt_two_level_leaf")
    leaf_unit = create_node(admin_session, level="branch", name="two_level_leaf")
    create_soldier(admin_session, personal_number="tl_leaf_0", hierarchy_node_id=leaf_unit.id)

    result = compute_two_level_split(
        admin_session, responsible_node_ids=[leaf_unit.id], required_count=3
    )

    # No children under leaf_unit -> its whole step-A share stays on itself.
    assert len(result) == 1
    assert result[0]["node_name"] == "two_level_leaf"
    assert result[0]["count"] == 3
    assert result[0]["parent_responsible_node_id"] == leaf_unit.id
