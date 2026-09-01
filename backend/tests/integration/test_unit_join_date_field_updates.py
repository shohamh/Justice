from __future__ import annotations

import uuid
from datetime import date

from app.db.models import AuditLog, DutyManagerScope, HierarchyNode, Notification, SoldierFieldUpdate
from tests.helpers import auth_headers, create_node, create_soldier


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _approval_tree(session):
    branch = create_node(session, level="branch", name=_uid("branch"))
    group = create_node(session, level="group", name=_uid("group"), parent=branch)
    team = create_node(session, level="team", name=_uid("team"), parent=group)
    commander = create_soldier(session, personal_number=_uid("cmd"), role="commander")
    group.commander_id = commander.id
    duty_manager = create_soldier(session, personal_number=_uid("dm"), role="duty_manager")
    session.add(DutyManagerScope(duty_manager_id=duty_manager.id, hierarchy_node_id=branch.id))
    soldier = create_soldier(session, personal_number=_uid("soldier"), hierarchy_node_id=team.id)
    soldier.enlistment_date = date(2020, 1, 1)
    soldier.unit_join_date = date(2026, 1, 1)
    soldier.enrolled_at = date(2026, 8, 31)
    session.commit()
    return soldier, commander, duty_manager


def _submit(client, actor, soldier, value: str = "2026-02-01"):
    return client.post(
        f"/api/soldiers/{soldier.id}/field-updates",
        json={"field_name": "unit_join_date", "new_value": value},
        headers=auth_headers(actor),
    )


def _approve(client, actor, soldier, update_id):
    return client.post(
        f"/api/soldiers/{soldier.id}/field-updates/{update_id}/approve",
        json={},
        headers=auth_headers(actor),
    )


def test_soldier_request_waits_for_commander_then_duty_manager(client, admin_session):
    soldier, commander, duty_manager = _approval_tree(admin_session)

    submitted = _submit(client, soldier, soldier)
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["status"] == "pending_commander"
    assert submitted.json()["waiting_on"]["kind"] == "commander"
    assert soldier.unit_join_date == date(2026, 1, 1)

    commander_step = _approve(client, commander, soldier, submitted.json()["id"])
    assert commander_step.status_code == 200, commander_step.text
    assert commander_step.json()["status"] == "pending_duty_manager"
    assert commander_step.json()["commander_approved_by"]["soldier_id"] == str(commander.id)
    assert soldier.unit_join_date == date(2026, 1, 1)

    duty_manager_step = _approve(client, duty_manager, soldier, submitted.json()["id"])
    assert duty_manager_step.status_code == 200, duty_manager_step.text
    assert duty_manager_step.json()["status"] == "approved"
    admin_session.refresh(soldier)
    assert soldier.unit_join_date == date(2026, 2, 1)


def test_commander_initiator_auto_approves_only_commander_stage(client, admin_session):
    soldier, commander, duty_manager = _approval_tree(admin_session)

    submitted = _submit(client, commander, soldier)
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["status"] == "pending_duty_manager"
    assert submitted.json()["commander_approved_by"]["soldier_id"] == str(commander.id)
    assert soldier.unit_join_date == date(2026, 1, 1)

    self_approval = _approve(client, commander, soldier, submitted.json()["id"])
    assert self_approval.status_code == 403

    approved = _approve(client, duty_manager, soldier, submitted.json()["id"])
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


def test_duty_manager_initiator_auto_approves_only_duty_manager_stage(client, admin_session):
    soldier, commander, duty_manager = _approval_tree(admin_session)

    submitted = _submit(client, duty_manager, soldier)
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["status"] == "pending_commander"
    assert submitted.json()["decided_by"]["soldier_id"] == str(duty_manager.id)
    assert soldier.unit_join_date == date(2026, 1, 1)

    self_approval = _approve(client, duty_manager, soldier, submitted.json()["id"])
    assert self_approval.status_code == 403

    approved = _approve(client, commander, soldier, submitted.json()["id"])
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"


def test_dual_authority_initiator_auto_approves_both_stages(client, admin_session):
    soldier, _commander, _duty_manager = _approval_tree(admin_session)
    dual_authority = create_soldier(admin_session, personal_number=_uid("dual"), role="commander")
    target_node = admin_session.get(HierarchyNode, soldier.hierarchy_node_id)
    group_node = admin_session.get(HierarchyNode, target_node.parent_id)
    group_node.commander_id = dual_authority.id
    admin_session.add(DutyManagerScope(duty_manager_id=dual_authority.id, hierarchy_node_id=group_node.parent_id))
    admin_session.commit()

    submitted = _submit(client, dual_authority, soldier)

    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["status"] == "approved"
    assert submitted.json()["commander_approved_by"]["soldier_id"] == str(dual_authority.id)
    assert submitted.json()["duty_manager_approved_by"]["soldier_id"] == str(dual_authority.id)
    admin_session.refresh(soldier)
    assert soldier.unit_join_date == date(2026, 2, 1)


def test_unit_join_date_requires_medor_commander_and_anaph_duty_manager_scope(client, admin_session):
    soldier, _commander, _duty_manager = _approval_tree(admin_session)
    submitted = _submit(client, soldier, soldier)
    update_id = submitted.json()["id"]

    target_node = admin_session.get(HierarchyNode, soldier.hierarchy_node_id)
    junior_commander = create_soldier(admin_session, personal_number=_uid("junior_cmd"), role="commander")
    target_node.commander_id = junior_commander.id

    junior_dm = create_soldier(admin_session, personal_number=_uid("junior_dm"), role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=junior_dm.id, hierarchy_node_id=target_node.id))
    admin_session.commit()

    assert _approve(client, junior_commander, soldier, update_id).status_code == 403
    assert _approve(client, junior_dm, soldier, update_id).status_code == 403


def test_duty_manager_stage_requires_anaph_or_higher_scope(client, admin_session):
    soldier, commander, _duty_manager = _approval_tree(admin_session)
    submitted = _submit(client, soldier, soldier)
    assert _approve(client, commander, soldier, submitted.json()["id"]).status_code == 200

    team_node = admin_session.get(HierarchyNode, soldier.hierarchy_node_id)
    medor_node = admin_session.get(HierarchyNode, team_node.parent_id)
    medor_dm = create_soldier(admin_session, personal_number=_uid("medor_dm"), role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=medor_dm.id, hierarchy_node_id=medor_node.id))
    admin_session.commit()

    assert _approve(client, medor_dm, soldier, submitted.json()["id"]).status_code == 403


def test_staged_unit_join_date_requests_are_visible_and_counted_for_current_approver(client, admin_session):
    soldier, commander, _duty_manager = _approval_tree(admin_session)
    submitted = _submit(client, soldier, soldier)
    assert submitted.status_code == 201, submitted.text

    rows = client.get("/api/soldiers/field-updates/pending", headers=auth_headers(commander))
    assert rows.status_code == 200
    assert [row["id"] for row in rows.json()] == [submitted.json()["id"]]
    assert rows.json()[0]["status"] == "pending_commander"
    assert rows.json()[0]["can_approve"] is True

    count = client.get("/api/soldiers/field-updates/pending/count", headers=auth_headers(commander))
    assert count.status_code == 200
    assert count.json() == {"count": 1}


def test_out_of_scope_initiator_gets_forbidden_status(client, admin_session):
    soldier, _commander, _duty_manager = _approval_tree(admin_session)
    other_group = create_node(admin_session, level="group", name=_uid("other_group"))
    outsider = create_soldier(
        admin_session, personal_number=_uid("outsider"), role="commander", hierarchy_node_id=other_group.id,
    )
    other_group.commander_id = outsider.id
    admin_session.commit()

    response = _submit(client, outsider, soldier)

    assert response.status_code == 403


def test_current_stage_approver_can_reject_unit_join_date_request(client, admin_session):
    soldier, commander, _duty_manager = _approval_tree(admin_session)
    submitted = _submit(client, soldier, soldier)

    rejected = client.post(
        f"/api/soldiers/{soldier.id}/field-updates/{submitted.json()['id']}/reject",
        json={"decision_note": "wrong"},
        headers=auth_headers(commander),
    )

    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    admin_session.refresh(soldier)
    assert soldier.unit_join_date == date(2026, 1, 1)


def test_new_request_supersedes_pending_same_field_and_keeps_history(client, admin_session):
    soldier, _commander, _duty_manager = _approval_tree(admin_session)
    first = _submit(client, soldier, soldier, "2026-02-01")
    second = _submit(client, soldier, soldier, "2026-03-01")
    assert second.status_code == 201, second.text

    first_row = admin_session.get(SoldierFieldUpdate, uuid.UUID(first.json()["id"]))
    assert first_row.status == "superseded"
    history = client.get(
        f"/api/soldiers/{soldier.id}/field-updates", headers=auth_headers(soldier),
    )
    assert history.status_code == 200
    assert {row["status"] for row in history.json()} == {"pending_commander", "superseded"}


def test_unit_join_date_is_revalidated_at_submission_and_each_approval(client, admin_session):
    soldier, commander, duty_manager = _approval_tree(admin_session)

    invalid = _submit(client, soldier, soldier, "2019-12-31")
    assert invalid.status_code == 400
    assert "unit_join_date_before_enlistment" in invalid.text

    submitted = _submit(client, soldier, soldier, "2026-02-01")
    soldier.enlistment_date = date(2026, 3, 1)
    admin_session.commit()
    stale_commander = _approve(client, commander, soldier, submitted.json()["id"])
    assert stale_commander.status_code == 400
    assert "unit_join_date_before_enlistment" in stale_commander.text

    soldier.enlistment_date = date(2020, 1, 1)
    admin_session.commit()
    assert _approve(client, commander, soldier, submitted.json()["id"]).status_code == 200
    soldier.discharge_date = date(2026, 1, 15)
    admin_session.commit()
    stale_final = _approve(client, duty_manager, soldier, submitted.json()["id"])
    assert stale_final.status_code == 400
    assert "unit_join_date_on_or_after_discharge" in stale_final.text
    admin_session.refresh(soldier)
    assert soldier.unit_join_date == date(2026, 1, 1)


def test_submission_and_auto_stage_write_audit_and_notify_current_approver(client, admin_session):
    soldier, commander, duty_manager = _approval_tree(admin_session)

    submitted = _submit(client, commander, soldier)
    assert submitted.status_code == 201, submitted.text
    update_id = uuid.UUID(submitted.json()["id"])

    actions = {
        row.action
        for row in admin_session.query(AuditLog).filter_by(
            entity_type="soldier_field_update", entity_id=update_id,
        )
    }
    assert "soldier.field_update.submit" in actions
    assert "soldier.field_update.commander_approve" in actions

    notifications = admin_session.query(Notification).filter_by(
        soldier_id=duty_manager.id, reference_type="soldier_field_update", reference_id=update_id,
    ).all()
    assert len(notifications) == 1


def test_final_approval_writes_audit_and_notifies_soldier(client, admin_session):
    soldier, commander, duty_manager = _approval_tree(admin_session)
    submitted = _submit(client, soldier, soldier)
    update_id = uuid.UUID(submitted.json()["id"])
    assert _approve(client, commander, soldier, update_id).status_code == 200

    final = _approve(client, duty_manager, soldier, update_id)

    assert final.status_code == 200, final.text
    actions = {
        row.action
        for row in admin_session.query(AuditLog).filter_by(
            entity_type="soldier_field_update", entity_id=update_id,
        )
    }
    assert "soldier.field_update.duty_manager_approve" in actions
    notifications = admin_session.query(Notification).filter_by(
        soldier_id=soldier.id, reference_type="soldier_field_update", reference_id=update_id,
    ).all()
    assert len(notifications) == 1
    assert notifications[0].type == "field_update_approved"
