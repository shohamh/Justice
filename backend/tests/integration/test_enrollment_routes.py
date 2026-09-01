from __future__ import annotations

import uuid
from datetime import date, timedelta

from app.db.models import (
    ExemptionRequest,
    ExemptionType,
    DutyManagerScope,
    HierarchyNode,
    Notification,
    NotificationType,
    SoldierEnrollmentRequest,
    SystemSetting,
)
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


def test_pending_list_survives_permanent_exemption_request(client, admin_session):
    """Regression test: a permanent exemption request (start_date=None) attached
    to a pending enrollment used to crash EnrollmentExemptionOut serialization
    (er.start_date.isoformat() with no None guard), 500ing GET /pending for
    every commander/duty manager as long as the row existed."""
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)
    et = ExemptionType(name=f"et_{_uid()}", is_commander_exemption=False)
    admin_session.add(et)
    admin_session.flush()
    admin_session.add(
        ExemptionRequest(
            soldier_id=soldier.id,
            exemption_type_id=et.id,
            enrollment_request_id=req.id,
            start_date=None,
            reason="פטור קבוע",
            status="pending",
        )
    )
    admin_session.commit()

    resp = client.get("/api/enrollment-requests/pending", headers=auth_headers(admin))
    assert resp.status_code == 200
    matching = next(r for r in resp.json() if r["id"] == str(req.id))
    assert matching["exemption_requests"][0]["start_date"] is None

    patched = client.patch(
        f"/api/enrollment-requests/{req.id}",
        headers=auth_headers(admin),
        json={"full_name": soldier.full_name},
    )
    assert patched.status_code == 200
    assert patched.json()["exemption_requests"][0]["start_date"] is None


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


def test_junior_commander_cannot_change_rank_on_in_scope_enrollment(client, admin_session):
    holding = _make_holding(admin_session)
    commander = create_soldier(admin_session, personal_number=f"cmd_{_uid()}", role="commander")
    requested_node = create_node(
        admin_session, level="team", name=f"junior_{_uid()}", parent=holding, commander_id=commander.id,
    )
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, requested_node)

    response = client.patch(
        f"/api/enrollment-requests/{req.id}", json={"rank": "סמר"}, headers=auth_headers(commander),
    )

    assert response.status_code == 403


def test_junior_commander_can_approve_own_node_without_changing_rank(client, admin_session):
    """Regression test: the "save and approve" UI flow always resubmits
    rank/rank_track/is_officer (defaulting to None/None/False) even when the
    reviewer never touched them. A commander with full ENROLLMENT_APPROVE
    scope over the exact node the soldier is enrolling into — but who sits
    below the "מדור"-or-above bar rank_advancement_edit_authorized requires —
    must still be able to approve as long as the resubmitted values match the
    soldier's current (unset) rank data."""
    holding = _make_holding(admin_session)
    commander = create_soldier(admin_session, personal_number=f"cmd_{_uid()}", role="commander")
    requested_node = create_node(
        admin_session, level="team", name=f"junior_{_uid()}", parent=holding, commander_id=commander.id,
    )
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, requested_node)

    response = client.patch(
        f"/api/enrollment-requests/{req.id}",
        json={"rank": None, "rank_track": None, "is_officer": False},
        headers=auth_headers(commander),
    )
    assert response.status_code == 200, response.text

    approve_resp = client.post(
        f"/api/enrollment-requests/{req.id}/approve",
        json={"decision_note": None}, headers=auth_headers(commander),
    )
    assert approve_resp.status_code == 200, approve_resp.text
    admin_session.refresh(soldier)
    assert soldier.hierarchy_node_id == requested_node.id


def test_rank_change_requires_authority_over_enrollment_destination(client, admin_session):
    holding = _make_holding(admin_session)
    senior_root = create_node(admin_session, level="group", name=f"senior_{_uid()}", parent=holding)
    junior_destination = create_node(admin_session, level="team", name=f"junior_{_uid()}", parent=holding)
    duty_manager = create_soldier(
        admin_session, personal_number=f"dm_{_uid()}", role="duty_manager", hierarchy_node_id=senior_root.id,
    )
    admin_session.add(
        DutyManagerScope(duty_manager_id=duty_manager.id, hierarchy_node_id=junior_destination.id)
    )
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    request = _make_req(admin_session, soldier, senior_root)

    response = client.patch(
        f"/api/enrollment-requests/{request.id}",
        json={"rank": "סמר", "requested_node_id": str(junior_destination.id)},
        headers=auth_headers(duty_manager),
    )

    assert response.status_code == 403


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


def test_admin_reject_notifies_soldier(client, admin_session):
    from app.db.models import Notification, NotificationType
    from sqlalchemy import select

    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)

    resp = client.post(f"/api/enrollment-requests/{req.id}/reject",
                       json={"decision_note": "not eligible"}, headers=auth_headers(admin))
    assert resp.status_code == 200

    notif = admin_session.execute(
        select(Notification).where(
            Notification.soldier_id == soldier.id,
            Notification.type == NotificationType.enrollment_rejected,
        )
    ).scalar_one_or_none()
    assert notif is not None


def test_patch_rejects_invalid_phone(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)

    resp = client.patch(f"/api/enrollment-requests/{req.id}",
                        json={"phone": "not-a-phone-number"}, headers=auth_headers(admin))
    assert resp.status_code == 422


def test_patch_accepts_valid_phone(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)

    resp = client.patch(f"/api/enrollment-requests/{req.id}",
                        json={"phone": "050-1234567"}, headers=auth_headers(admin))
    assert resp.status_code == 200
    admin_session.refresh(soldier)
    assert soldier.phone == "050-1234567"


def test_enrollment_reviewer_can_correct_unit_join_date_before_activation(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    soldier.enlistment_date = date.today() - timedelta(days=30)
    soldier.discharge_date = date.today() + timedelta(days=30)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)
    admin_session.commit()

    resp = client.patch(
        f"/api/enrollment-requests/{req.id}",
        json={"unit_join_date": soldier.enlistment_date.isoformat()},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["unit_join_date"] == soldier.enlistment_date.isoformat()
    admin_session.refresh(soldier)
    assert soldier.unit_join_date == soldier.enlistment_date


def test_enrollment_reviewer_cannot_set_unit_join_date_before_enlistment(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    soldier.enlistment_date = date.today() - timedelta(days=30)
    soldier.discharge_date = date.today() + timedelta(days=30)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)
    admin_session.commit()

    resp = client.patch(
        f"/api/enrollment-requests/{req.id}",
        json={"unit_join_date": (soldier.enlistment_date - timedelta(days=1)).isoformat()},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "unit_join_date_before_enlistment"


def test_patch_notifies_soldier_when_fields_actually_changed(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)

    resp = client.patch(f"/api/enrollment-requests/{req.id}",
                        json={"phone": "050-1234567", "rank": "רבט"}, headers=auth_headers(admin))
    assert resp.status_code == 200

    notif = admin_session.query(Notification).filter_by(
        soldier_id=soldier.id, type=NotificationType.enrollment_fields_edited,
    ).one()
    assert "טלפון" in notif.body
    assert "דרגה" in notif.body
    assert notif.reference_type == "soldier_enrollment_request"
    assert notif.reference_id == req.id


def test_enrollment_rank_change_uses_cumulative_enlistment_schedule(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    soldier.enlistment_date = date(2021, 1, 15)
    admin_session.commit()
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)

    resp = client.patch(
        f"/api/enrollment-requests/{req.id}",
        json={"rank": "סמר"},
        headers=auth_headers(admin),
    )

    assert resp.status_code == 200, resp.text
    admin_session.refresh(soldier)
    assert soldier.current_rank_since == date(2021, 1, 15)
    assert soldier.next_rank_date == date(2025, 9, 15)


def test_patch_does_not_notify_when_nothing_actually_changed(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    soldier.phone = "050-1234567"
    admin_session.commit()
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)

    # Re-submitting the soldier's own current phone value is not an edit.
    resp = client.patch(f"/api/enrollment-requests/{req.id}",
                        json={"phone": soldier.phone}, headers=auth_headers(admin))
    assert resp.status_code == 200

    count = admin_session.query(Notification).filter_by(
        soldier_id=soldier.id, type=NotificationType.enrollment_fields_edited,
    ).count()
    assert count == 0


def test_reject_without_note_fails(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    req = _make_req(admin_session, soldier, node)

    resp = client.post(f"/api/enrollment-requests/{req.id}/reject",
                       json={"decision_note": ""}, headers=auth_headers(admin))
    assert resp.status_code == 422


def test_pending_list_includes_nearest_commander_and_duty_manager(client, admin_session):
    holding = _make_holding(admin_session)
    dept = create_node(admin_session, level="division", name=f"dept_{_uid()}", parent=holding)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=dept)
    cmd = create_soldier(admin_session, personal_number=f"cmd_{_uid()}", role="commander")
    node.commander_id = cmd.id
    admin_session.commit()
    dm = create_soldier(admin_session, personal_number=f"dm_{_uid()}", role="duty_manager", hierarchy_node_id=dept.id)
    # The requesting soldier has NOT been placed into `node` yet — hierarchy_node_id
    # still points at the holding node until the request is approved. The nearest
    # commander/duty-manager must therefore be resolved from `requested_node_id`.
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    _make_req(admin_session, soldier, node)

    resp = client.get("/api/enrollment-requests/pending", headers=auth_headers(admin))
    assert resp.status_code == 200
    items = [i for i in resp.json() if i["soldier_id"] == str(soldier.id)]
    assert len(items) == 1
    assert items[0]["nearest_commander"]["id"] == str(cmd.id)
    assert items[0]["nearest_commander"]["name"] == cmd.full_name
    assert items[0]["nearest_duty_manager"]["id"] == str(dm.id)
    assert items[0]["nearest_duty_manager"]["name"] == dm.full_name


def test_plain_soldier_cannot_approve(client, admin_session):
    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"u_{_uid()}", parent=holding)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    other = create_soldier(admin_session, personal_number=f"o_{_uid()}", role="soldier")
    req = _make_req(admin_session, soldier, node)

    resp = client.post(f"/api/enrollment-requests/{req.id}/approve",
                       json={"decision_note": None}, headers=auth_headers(other))
    assert resp.status_code == 403


def test_below_mador_commander_can_approve_without_editing_rank(client, admin_session):
    from app.db.models import SoldierEnrollmentRequest
    node = create_node(admin_session, level="team", name=f"enroll_low_{_uid()}")
    cmd = create_soldier(admin_session, personal_number=f"cmd_{_uid()}", role="commander")
    node.commander_id = cmd.id
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    req = SoldierEnrollmentRequest(soldier_id=soldier.id, requested_node_id=node.id, status="pending")
    admin_session.add(req)
    admin_session.commit()

    list_resp = client.get("/api/enrollment-requests/pending", headers=auth_headers(cmd))
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["can_edit_rank_advancement"] is False

    approve_resp = client.post(
        f"/api/enrollment-requests/{req.id}/approve", headers=auth_headers(cmd), json={},
    )
    assert approve_resp.status_code == 200, approve_resp.text


def test_mador_plus_commander_sees_rank_edit_flag_true(client, admin_session):
    from app.db.models import SoldierEnrollmentRequest
    node = create_node(admin_session, level="group", name=f"enroll_high_{_uid()}")
    cmd = create_soldier(admin_session, personal_number=f"cmd_{_uid()}", role="commander")
    node.commander_id = cmd.id
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    req = SoldierEnrollmentRequest(soldier_id=soldier.id, requested_node_id=node.id, status="pending")
    admin_session.add(req)
    admin_session.commit()

    list_resp = client.get("/api/enrollment-requests/pending", headers=auth_headers(cmd))
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["can_edit_rank_advancement"] is True


def test_pending_list_computes_rank_edit_flag_per_row_with_shared_scope(client, admin_session):
    """Regression test for the RankAdvancementEditScope refactor in _load_reqs:
    several pending requests spanning both an in-authority (מדור+) node and a
    too-junior node must each get their OWN correct can_edit_rank_advancement
    value from the single scope built once for the request, not a value bled
    over from another row."""
    from app.db.models import SoldierEnrollmentRequest
    cmd = create_soldier(admin_session, personal_number=f"cmd_{_uid()}", role="commander")
    high_node = create_node(admin_session, level="group", name=f"enroll_shared_high_{_uid()}")
    high_node.commander_id = cmd.id
    low_node = create_node(admin_session, level="team", name=f"enroll_shared_low_{_uid()}")
    low_node.commander_id = cmd.id
    admin_session.commit()

    high_soldier_1 = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    high_soldier_2 = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    low_soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    high_req_1 = SoldierEnrollmentRequest(soldier_id=high_soldier_1.id, requested_node_id=high_node.id, status="pending")
    high_req_2 = SoldierEnrollmentRequest(soldier_id=high_soldier_2.id, requested_node_id=high_node.id, status="pending")
    low_req = SoldierEnrollmentRequest(soldier_id=low_soldier.id, requested_node_id=low_node.id, status="pending")
    admin_session.add_all([high_req_1, high_req_2, low_req])
    admin_session.commit()

    list_resp = client.get("/api/enrollment-requests/pending", headers=auth_headers(cmd))
    assert list_resp.status_code == 200
    by_soldier = {i["soldier_id"]: i["can_edit_rank_advancement"] for i in list_resp.json()}
    assert len(by_soldier) == 3
    assert by_soldier[str(high_soldier_1.id)] is True
    assert by_soldier[str(high_soldier_2.id)] is True
    assert by_soldier[str(low_soldier.id)] is False
