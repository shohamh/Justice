from __future__ import annotations

from datetime import date

from tests.helpers import auth_headers, create_node, create_soldier


def _setup_dm(session, pn: str):
    node = create_node(session, level="branch", name=f"branch_{pn}")
    dm = create_soldier(session, personal_number=pn, role="duty_manager", hierarchy_node_id=node.id)
    return dm, node


def test_dm_can_patch_profile(client, admin_session):
    dm, node = _setup_dm(admin_session, "prof_dm_001")
    s = create_soldier(admin_session, personal_number="prof_s_001", hierarchy_node_id=node.id)

    resp = client.patch(
        f"/api/soldiers/{s.id}/profile",
        json={"rank": "סמל", "is_officer": False, "gender": "male"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rank"] == "סמל"
    assert data["is_officer"] is False
    assert data["gender"] == "male"  # DM can see gender


def test_gender_hidden_from_peer(client, admin_session):
    dm, node = _setup_dm(admin_session, "prof_dm_002")
    node2 = create_node(admin_session, level="branch", name="branch_peer_002")
    s1 = create_soldier(admin_session, personal_number="prof_s_002a", hierarchy_node_id=node.id)
    s2 = create_soldier(admin_session, personal_number="prof_s_002b", hierarchy_node_id=node2.id)

    # DM patches s1's gender
    client.patch(
        f"/api/soldiers/{s1.id}/profile",
        json={"gender": "female"},
        headers=auth_headers(dm),
    )

    # s2 tries to fetch s1 — either 403 or gender=null
    resp = client.get(f"/api/soldiers/{s1.id}", headers=auth_headers(s2))
    if resp.status_code == 200:
        assert resp.json()["gender"] is None


def test_soldier_submits_field_update(client, admin_session):
    dm, node = _setup_dm(admin_session, "prof_dm_003")
    s = create_soldier(admin_session, personal_number="prof_s_003", hierarchy_node_id=node.id)

    resp = client.post(
        f"/api/soldiers/{s.id}/field-updates",
        json={"field_name": "last_mitvahim_date", "new_value": "2026-05-01"},
        headers=auth_headers(s),
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"
    update_id = resp.json()["id"]

    # DM approves
    resp2 = client.post(
        f"/api/soldiers/{s.id}/field-updates/{update_id}/approve",
        json={},
        headers=auth_headers(dm),
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "approved"

    # Soldier profile now has the date
    profile = client.get(f"/api/soldiers/{s.id}", headers=auth_headers(dm))
    assert profile.json()["last_mitvahim_date"] == "2026-05-01"


def test_field_update_includes_nearest_commander_and_duty_manager(client, admin_session):
    d = create_node(admin_session, level="department", name="d-nearest-fu")
    b = create_node(admin_session, level="branch", name="b-nearest-fu", parent=d)
    cmd = create_soldier(admin_session, personal_number="prof_cmd_004", role="commander")
    b.commander_id = cmd.id
    admin_session.commit()
    dm = create_soldier(admin_session, personal_number="prof_dm_004", role="duty_manager", hierarchy_node_id=d.id)
    s = create_soldier(admin_session, personal_number="prof_s_004", hierarchy_node_id=b.id)

    resp = client.post(
        f"/api/soldiers/{s.id}/field-updates",
        json={"field_name": "last_mitvahim_date", "new_value": "2026-05-01"},
        headers=auth_headers(s),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["nearest_commander"]["id"] == str(cmd.id)
    assert body["nearest_commander"]["name"] == cmd.full_name
    assert body["nearest_duty_manager"]["id"] == str(dm.id)
    assert body["nearest_duty_manager"]["name"] == dm.full_name

    resp2 = client.get(f"/api/soldiers/{s.id}/field-updates", headers=auth_headers(s))
    items = resp2.json()
    assert len(items) == 1
    assert items[0]["nearest_commander"]["id"] == str(cmd.id)
    assert items[0]["nearest_duty_manager"]["id"] == str(dm.id)


def test_soldier_cannot_update_is_officer_directly(client, admin_session):
    _, node = _setup_dm(admin_session, "prof_dm_004")
    s = create_soldier(admin_session, personal_number="prof_s_004", hierarchy_node_id=node.id)

    resp = client.post(
        f"/api/soldiers/{s.id}/field-updates",
        json={"field_name": "is_officer", "new_value": "true"},
        headers=auth_headers(s),
    )
    assert resp.status_code == 400


def test_ranks_endpoint(client, admin_session):
    s = create_soldier(admin_session, personal_number="prof_ranks_001")
    resp = client.get("/api/soldiers/ranks", headers=auth_headers(s))
    assert resp.status_code == 200
    data = resp.json()
    assert "enlisted" in data and "officers" in data
    assert "סמל" in data["enlisted"]
    assert "סרן" in data["officers"]


import json


def test_soldier_submits_military_license_dm_approves(client, admin_session):
    dm, node = _setup_dm(admin_session, "prof_dm_005")
    s = create_soldier(admin_session, personal_number="prof_s_005", hierarchy_node_id=node.id)

    resp = client.post(
        f"/api/soldiers/{s.id}/field-updates",
        json={
            "field_name": "military_driving_license",
            "new_value": json.dumps({"has_license": True, "expiry_date": "2028-01-01"}),
        },
        headers=auth_headers(s),
    )
    assert resp.status_code == 201
    update_id = resp.json()["id"]

    resp2 = client.post(
        f"/api/soldiers/{s.id}/field-updates/{update_id}/approve",
        json={},
        headers=auth_headers(dm),
    )
    assert resp2.status_code == 200

    profile = client.get(f"/api/soldiers/{s.id}", headers=auth_headers(dm))
    assert profile.json()["has_military_driving_license"] is True
    assert profile.json()["military_driving_license_expiry"] == "2028-01-01"


def test_commander_below_rasan_cannot_approve_military_license(client, admin_session):
    node = create_node(admin_session, level="branch", name="branch_prof_006")
    cmd = create_soldier(admin_session, personal_number="prof_cmd_006", role="commander")
    cmd.rank = "סרן"
    node.commander_id = cmd.id
    admin_session.commit()
    s = create_soldier(admin_session, personal_number="prof_s_006", hierarchy_node_id=node.id)

    resp = client.post(
        f"/api/soldiers/{s.id}/field-updates",
        json={
            "field_name": "military_driving_license",
            "new_value": json.dumps({"has_license": True, "expiry_date": None}),
        },
        headers=auth_headers(s),
    )
    update_id = resp.json()["id"]

    resp2 = client.post(
        f"/api/soldiers/{s.id}/field-updates/{update_id}/approve",
        json={},
        headers=auth_headers(cmd),
    )
    assert resp2.status_code == 403


def test_commander_rasan_and_above_can_approve_military_license(client, admin_session):
    node = create_node(admin_session, level="branch", name="branch_prof_007")
    cmd = create_soldier(admin_session, personal_number="prof_cmd_007", role="commander")
    cmd.rank = "רסן"
    node.commander_id = cmd.id
    admin_session.commit()
    s = create_soldier(admin_session, personal_number="prof_s_007", hierarchy_node_id=node.id)

    resp = client.post(
        f"/api/soldiers/{s.id}/field-updates",
        json={
            "field_name": "military_driving_license",
            "new_value": json.dumps({"has_license": True, "expiry_date": None}),
        },
        headers=auth_headers(s),
    )
    update_id = resp.json()["id"]

    resp2 = client.post(
        f"/api/soldiers/{s.id}/field-updates/{update_id}/approve",
        json={},
        headers=auth_headers(cmd),
    )
    assert resp2.status_code == 200, resp2.text
