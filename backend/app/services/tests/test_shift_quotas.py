from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.db.models import AuditLog, DutyLocation, Soldier
from app.services.duty_config import create_duty_type
from app.services.shift_quotas import (
    ShiftQuotaError,
    compute_potential_split,
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

    with pytest.raises(ShiftQuotaError, match="exceeds required_count"):
        set_shift_quotas(admin_session, shift_id=shift.id, quotas=[(node_a.id, 2), (node_b.id, 2)])


def test_set_quotas_unknown_node_raises(admin_session):
    shift = _make_shift(admin_session, "3", required_count=3)
    with pytest.raises(ShiftQuotaError, match="not found"):
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


def test_compute_potential_split_even_weights(admin_session):
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

    with pytest.raises(ShiftQuotaError, match="no direct children"):
        compute_potential_split(admin_session, parent_node_id=leaf.id, required_count=5)


def test_compute_potential_split_invalid_required_count_raises(admin_session):
    parent = create_node(admin_session, level="unit", name="pot_invalid_parent")
    create_node(admin_session, level="branch", name="pot_invalid_a", parent=parent)

    with pytest.raises(ShiftQuotaError, match="required_count must be"):
        compute_potential_split(admin_session, parent_node_id=parent.id, required_count=0)
