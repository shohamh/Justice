from __future__ import annotations

import uuid

from app.db.models import HierarchyNode, SoldierEnrollmentRequest, SystemSetting
from tests.helpers import auth_headers, create_node, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def _make_holding(session):
    node = HierarchyNode(level="division", name=f"holding_{_uid()}", parent_id=None, commander_id=None, path_ids=[])
    session.add(node)
    session.flush()
    node.path_ids = [node.id]
    if session.get(SystemSetting, "system.holding_node_id") is None:
        session.add(SystemSetting(key="system.holding_node_id", value=str(node.id), updated_by=None))
    session.commit()
    return node


def _make_req(session, soldier, node):
    req = SoldierEnrollmentRequest(soldier_id=soldier.id, requested_node_id=node.id, status="pending")
    session.add(req)
    session.commit()
    session.refresh(req)
    return req


def test_admin_can_list_pending(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    _make_req(admin_session, soldier, node)

    resp = client.get("/api/enrollment-requests/pending", headers=auth_headers(admin))
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_admin_can_approve(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)

    resp = client.post(f"/api/enrollment-requests/{req.id}/approve",
                       json={"decision_note": None}, headers=auth_headers(admin))
    assert resp.status_code == 200
    admin_session.refresh(soldier)
    assert soldier.hierarchy_node_id == node.id


def test_admin_can_reject(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)

    resp = client.post(f"/api/enrollment-requests/{req.id}/reject",
                       json={"decision_note": "not eligible"}, headers=auth_headers(admin))
    assert resp.status_code == 200
    admin_session.refresh(soldier)
    assert soldier.hierarchy_node_id == holding.id


def test_reject_without_note_fails(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)

    resp = client.post(f"/api/enrollment-requests/{req.id}/reject",
                       json={"decision_note": ""}, headers=auth_headers(admin))
    assert resp.status_code == 422


def test_plain_soldier_cannot_approve(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    other = create_soldier(admin_session, personal_number=f"o_{_uid()}", role="soldier")
    req = _make_req(admin_session, soldier, node)

    resp = client.post(f"/api/enrollment-requests/{req.id}/approve",
                       json={"decision_note": None}, headers=auth_headers(other))
    assert resp.status_code == 403
