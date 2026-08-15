from __future__ import annotations

from datetime import date

from app.db.models import HierarchyLevelType
from tests.helpers import auth_headers, create_node, create_soldier


def _setup_dm(session, pn: str):
    node = _mador_root(session, name=f"mador_{pn}")
    dm = create_soldier(session, personal_number=pn, role="duty_manager", hierarchy_node_id=node.id)
    return dm, node


def _mador_root(session, *, name: str, commander_id=None):
    level = session.query(HierarchyLevelType).filter_by(key="group").one()
    level.key = "מדור"
    level.label = "מדור"
    session.flush()
    return create_node(session, level="מדור", name=name, commander_id=commander_id)


def test_senior_commander_can_override_rank_date_and_receives_capability(client, admin_session):
    commander = create_soldier(admin_session, personal_number="rank_cmd_001", role="commander")
    root = _mador_root(admin_session, name="rank_cmd_root", commander_id=commander.id)
    target_node = create_node(admin_session, level="team", name="rank_cmd_target", parent=root)
    soldier = create_soldier(admin_session, personal_number="rank_cmd_target_s", hierarchy_node_id=target_node.id)
    soldier.enlistment_date = date(2021, 1, 15)
    admin_session.commit()

    response = client.patch(
        f"/api/soldiers/{soldier.id}/profile",
        json={"rank": "סמר", "next_rank_date": "2030-02-03"},
        headers=auth_headers(commander),
    )

    assert response.status_code == 200, response.text
    assert response.json()["next_rank_date"] == "2030-02-03"
    assert response.json()["next_rank_date_overridden"] is True
    assert response.json()["can_edit_rank_advancement"] is True


def test_senior_duty_manager_can_correct_rank(client, admin_session):
    root = _mador_root(admin_session, name="rank_dm_root")
    duty_manager = create_soldier(
        admin_session, personal_number="rank_dm_001", role="duty_manager", hierarchy_node_id=root.id,
    )
    target_node = create_node(admin_session, level="team", name="rank_dm_target", parent=root)
    soldier = create_soldier(admin_session, personal_number="rank_dm_target_s", hierarchy_node_id=target_node.id)

    response = client.patch(
        f"/api/soldiers/{soldier.id}/profile",
        json={"rank": "סמר"},
        headers=auth_headers(duty_manager),
    )

    assert response.status_code == 200, response.text
    assert response.json()["rank"] == "סמר"
    assert response.json()["can_edit_rank_advancement"] is True


def test_lower_level_commander_cannot_correct_rank_or_edit_ordinary_profile(client, admin_session):
    commander = create_soldier(admin_session, personal_number="rank_junior_cmd", role="commander")
    root = create_node(admin_session, level="branch", name="rank_junior_root", commander_id=commander.id)
    soldier = create_soldier(admin_session, personal_number="rank_junior_target", hierarchy_node_id=root.id)
    admin_session.commit()

    rank_response = client.patch(
        f"/api/soldiers/{soldier.id}/profile", json={"rank": "סמר"}, headers=auth_headers(commander),
    )
    ordinary_response = client.patch(
        f"/api/soldiers/{soldier.id}/profile", json={"gender": "male"}, headers=auth_headers(commander),
    )
    profile_response = client.get(f"/api/soldiers/{soldier.id}", headers=auth_headers(commander))

    assert rank_response.status_code == 403
    assert ordinary_response.status_code == 403
    assert profile_response.json()["can_edit_rank_advancement"] is False


def test_lower_level_duty_manager_cannot_correct_rank(client, admin_session):
    root = create_node(admin_session, level="branch", name="rank_junior_dm_root")
    duty_manager = create_soldier(
        admin_session, personal_number="rank_junior_dm", role="duty_manager", hierarchy_node_id=root.id,
    )
    soldier = create_soldier(admin_session, personal_number="rank_junior_dm_target", hierarchy_node_id=root.id)

    response = client.patch(
        f"/api/soldiers/{soldier.id}/profile", json={"rank_track": "enlisted"}, headers=auth_headers(duty_manager),
    )

    assert response.status_code == 403


def test_senior_commander_cannot_correct_rank_outside_their_scope(client, admin_session):
    commander = create_soldier(admin_session, personal_number="rank_out_scope_cmd", role="commander")
    _mador_root(admin_session, name="rank_out_scope_root", commander_id=commander.id)
    other_node = create_node(admin_session, level="team", name="rank_out_scope_target")
    soldier = create_soldier(admin_session, personal_number="rank_out_scope_s", hierarchy_node_id=other_node.id)
    admin_session.commit()

    response = client.patch(
        f"/api/soldiers/{soldier.id}/profile", json={"is_officer": False}, headers=auth_headers(commander),
    )

    assert response.status_code == 403


def test_admin_can_correct_rank_without_hierarchy_node(client, admin_session):
    admin = create_soldier(admin_session, personal_number="rank_admin_001", role="admin")
    soldier = create_soldier(admin_session, personal_number="rank_admin_target")

    response = client.patch(
        f"/api/soldiers/{soldier.id}/profile", json={"rank": "סמר"}, headers=auth_headers(admin),
    )

    assert response.status_code == 200, response.text


def test_explicit_null_next_rank_date_restores_automatic_schedule(client, admin_session):
    admin = create_soldier(admin_session, personal_number="rank_reset_admin", role="admin")
    soldier = create_soldier(admin_session, personal_number="rank_reset_target")
    soldier.enlistment_date = date(2021, 1, 15)
    admin_session.commit()

    override_response = client.patch(
        f"/api/soldiers/{soldier.id}/profile",
        json={"rank": "סמר", "next_rank_date": "2030-02-03"},
        headers=auth_headers(admin),
    )
    reset_response = client.patch(
        f"/api/soldiers/{soldier.id}/profile", json={"next_rank_date": None}, headers=auth_headers(admin),
    )

    assert override_response.json()["next_rank_date_overridden"] is True
    assert reset_response.status_code == 200, reset_response.text
    assert reset_response.json()["next_rank_date"] == "2025-09-15"
    assert reset_response.json()["next_rank_date_overridden"] is False


def test_dm_can_patch_profile(client, admin_session):
    dm, node = _setup_dm(admin_session, "prof_dm_001")
    s = create_soldier(admin_session, personal_number="prof_s_001", hierarchy_node_id=node.id)
    s.enlistment_date = date(2021, 1, 15)
    admin_session.commit()

    resp = client.patch(
        f"/api/soldiers/{s.id}/profile",
        json={"rank": "סמר", "is_officer": False, "gender": "male"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rank"] == "סמר"
    assert data["is_officer"] is False
    assert data["gender"] == "male"  # DM can see gender
    admin_session.refresh(s)
    assert s.current_rank_since == date(2021, 1, 15)
    assert s.next_rank_date == date(2025, 9, 15)


def test_profile_update_rank_track_incompatible_returns_400(client, admin_session):
    dm, node = _setup_dm(admin_session, "prof_dm_incompat")
    s = create_soldier(admin_session, personal_number="prof_s_incompat", hierarchy_node_id=node.id)
    # No mandatory_end_date set -> is_career derives False ("חובה" track).
    # "רסן" is a קבע-only rank, so this combination is structurally incompatible.
    resp = client.patch(
        f"/api/soldiers/{s.id}/profile",
        json={"rank": "רסן"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 400, resp.text
    assert "rank_track_incompatible" in resp.json()["detail"]


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
