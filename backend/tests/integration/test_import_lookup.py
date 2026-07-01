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
