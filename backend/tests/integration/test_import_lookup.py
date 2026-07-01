from __future__ import annotations

from decimal import Decimal

from app.db.models import DutyType
from tests.helpers import auth_headers, create_node, create_soldier


def test_duty_types_requires_duty_manager_or_admin(client, admin_session):
    soldier = create_soldier(admin_session, personal_number="il_soldier_001")
    resp = client.get("/api/import-lookup/duty-types", headers=auth_headers(soldier))
    assert resp.status_code == 403


def test_duty_types_returns_active_and_inactive(client, admin_session):
    node = create_node(admin_session, level="branch", name="il_node_001")
    dm = create_soldier(admin_session, personal_number="il_dm_001", role="duty_manager", hierarchy_node_id=node.id)
    active = DutyType(name="il_active_type", score_per_day=Decimal("1.00"))
    inactive = DutyType(name="il_inactive_type", score_per_day=Decimal("1.00"), active=False)
    admin_session.add_all([active, inactive])
    admin_session.commit()

    resp = client.get("/api/import-lookup/duty-types", headers=auth_headers(dm))
    assert resp.status_code == 200
    names = {row["name"] for row in resp.json()}
    assert "il_active_type" in names
    assert "il_inactive_type" in names


def test_hierarchy_requires_duty_manager_or_admin(client, admin_session):
    soldier = create_soldier(admin_session, personal_number="il_soldier_002")
    resp = client.get("/api/import-lookup/hierarchy", headers=auth_headers(soldier))
    assert resp.status_code == 403


def test_hierarchy_returns_full_tree_regardless_of_dm_scope(client, admin_session):
    root = create_node(admin_session, level="branch", name="il_root_001")
    other = create_node(admin_session, level="branch", name="il_other_001")
    dm = create_soldier(admin_session, personal_number="il_dm_002", role="duty_manager", hierarchy_node_id=root.id)

    resp = client.get("/api/import-lookup/hierarchy", headers=auth_headers(dm))
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()}
    assert str(root.id) in ids
    assert str(other.id) in ids


def test_soldiers_requires_at_least_one_filter(client, admin_session):
    node = create_node(admin_session, level="branch", name="il_node_003")
    dm = create_soldier(admin_session, personal_number="il_dm_003", role="duty_manager", hierarchy_node_id=node.id)
    resp = client.get("/api/import-lookup/soldiers", headers=auth_headers(dm))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "no_filter_provided"


def test_soldiers_lookup_by_personal_number(client, admin_session):
    node = create_node(admin_session, level="branch", name="il_node_004")
    dm = create_soldier(admin_session, personal_number="il_dm_004", role="duty_manager", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="il_target_004", hierarchy_node_id=node.id)

    resp = client.get(
        "/api/import-lookup/soldiers",
        params={"personal_number": "il_target_004"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["personal_number"] == "il_target_004"
    assert rows[0]["full_name"] == target.full_name
    assert rows[0]["hierarchy_node_name"] == "il_node_004"


def test_soldiers_lookup_by_partial_name_case_insensitive(client, admin_session):
    node = create_node(admin_session, level="branch", name="il_node_005")
    dm = create_soldier(admin_session, personal_number="il_dm_005", role="duty_manager", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="il_target_005", hierarchy_node_id=node.id)
    target.full_name = "Israel Israeli"
    admin_session.commit()

    resp = client.get(
        "/api/import-lookup/soldiers",
        params={"name": "israel isr"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["personal_number"] == "il_target_005"


def test_soldiers_lookup_by_hierarchy_includes_descendants(client, admin_session):
    top = create_node(admin_session, level="branch", name="il_top_006")
    mid = create_node(admin_session, level="unit", name="il_mid_006", parent=top)
    leaf = create_node(admin_session, level="squad", name="il_leaf_006", parent=mid)
    dm = create_soldier(admin_session, personal_number="il_dm_006", role="duty_manager", hierarchy_node_id=top.id)
    create_soldier(admin_session, personal_number="il_direct_006", hierarchy_node_id=top.id)
    create_soldier(admin_session, personal_number="il_grandchild_006", hierarchy_node_id=leaf.id)
    elsewhere_node = create_node(admin_session, level="branch", name="il_elsewhere_006")
    create_soldier(admin_session, personal_number="il_outside_006", hierarchy_node_id=elsewhere_node.id)

    resp = client.get(
        "/api/import-lookup/soldiers",
        params={"hierarchy_node_id": str(top.id)},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    numbers = {row["personal_number"] for row in resp.json()}
    assert numbers == {"il_direct_006", "il_grandchild_006"}
    assert "il_outside_006" not in numbers


def test_soldiers_lookup_combines_filters_with_and(client, admin_session):
    node = create_node(admin_session, level="branch", name="il_node_007")
    other_node = create_node(admin_session, level="branch", name="il_other_007")
    dm = create_soldier(admin_session, personal_number="il_dm_007", role="duty_manager", hierarchy_node_id=node.id)
    inside = create_soldier(admin_session, personal_number="il_inside_007", hierarchy_node_id=node.id)
    inside.full_name = "Shared Name"
    outside = create_soldier(admin_session, personal_number="il_outside_007", hierarchy_node_id=other_node.id)
    outside.full_name = "Shared Name"
    admin_session.commit()

    resp = client.get(
        "/api/import-lookup/soldiers",
        params={"name": "Shared Name", "hierarchy_node_id": str(node.id)},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    numbers = {row["personal_number"] for row in resp.json()}
    assert numbers == {"il_inside_007"}


def test_soldiers_lookup_no_matches_returns_empty_list(client, admin_session):
    node = create_node(admin_session, level="branch", name="il_node_008")
    dm = create_soldier(admin_session, personal_number="il_dm_008", role="duty_manager", hierarchy_node_id=node.id)
    resp = client.get(
        "/api/import-lookup/soldiers",
        params={"personal_number": "does_not_exist"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert resp.json() == []
