from __future__ import annotations

import uuid

from app.db.models import DutyManagerScope
from tests.helpers import auth_headers, create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def test_assign_scope_as_admin(client, admin_session):
    """Admin can POST /duty-manager-scope to assign a soldier as DM."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    resp = client.post(
        "/api/duty-manager-scope",
        json={"soldier_id": str(soldier.id), "node_id": str(node.id)},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["duty_manager_id"] == str(soldier.id)
    assert data["hierarchy_node_id"] == str(node.id)
    admin_session.refresh(soldier)
    assert soldier.role == "duty_manager"


def test_assign_scope_commander_low_rank_forbidden(client, admin_session):
    """Commander with rank סרן (below רסן) cannot assign DM scope."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    cmd = create_soldier(admin_session, personal_number=f"cmd_{_uid()}", role="commander")
    cmd.rank = "סרן"
    node.commander_id = cmd.id
    cmd.hierarchy_node_id = node.id
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")

    resp = client.post(
        "/api/duty-manager-scope",
        json={"soldier_id": str(soldier.id), "node_id": str(node.id)},
        headers=auth_headers(cmd),
    )
    assert resp.status_code == 403


def test_assign_scope_commander_rasan_allowed(client, admin_session):
    """Commander with rank רסן can assign DM scope within their subtree."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    cmd = create_soldier(admin_session, personal_number=f"cmd_{_uid()}", role="commander")
    cmd.rank = "רסן"
    node.commander_id = cmd.id
    cmd.hierarchy_node_id = node.id
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")

    resp = client.post(
        "/api/duty-manager-scope",
        json={"soldier_id": str(soldier.id), "node_id": str(node.id)},
        headers=auth_headers(cmd),
    )
    assert resp.status_code == 201


def test_remove_scope_as_admin(client, admin_session):
    """Admin can DELETE /duty-manager-scope/{id}; role downgrades to soldier."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    entry = DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id)
    admin_session.add(entry)
    admin_session.commit()
    admin_session.refresh(entry)

    resp = client.delete(f"/api/duty-manager-scope/{entry.id}", headers=auth_headers(admin))
    assert resp.status_code == 200
    admin_session.refresh(dm)
    assert dm.role == "soldier"


def test_list_scope(client, admin_session):
    """GET /duty-manager-scope?soldier_id=... returns that soldier's scope entries."""
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager")
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    entry = DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id)
    admin_session.add(entry)
    admin_session.commit()

    resp = client.get(
        f"/api/duty-manager-scope?soldier_id={dm.id}",
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert any(d["hierarchy_node_id"] == str(node.id) for d in data)
