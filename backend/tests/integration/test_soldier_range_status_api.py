from __future__ import annotations

from datetime import date, timedelta

from app.db.models import DutyManagerScope, DutyType, RangeType
from app.services.settings_loader import set_setting
from tests.helpers import auth_headers, create_node, create_soldier


def _enable_mitvachim(session) -> None:
    set_setting(session, "mitvachim.enabled", True, actor_id=None)


def test_self_can_view_own_range_status(client, admin_session) -> None:
    node = create_node(admin_session, level="team", name="rs-api-team-1")
    soldier = create_soldier(admin_session, personal_number="rs-api-001", hierarchy_node_id=node.id)
    _enable_mitvachim(admin_session)
    admin_session.add(DutyType(
        name="rs-api-duty-1", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    admin_session.commit()

    response = client.get(f"/api/soldiers/{soldier.id}/range-status", headers=auth_headers(soldier))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["soldier_id"] == str(soldier.id)
    assert body["statuses"][0]["required_range_type"] == "alal"
    assert body["statuses"][0]["eligible"] is False


def test_out_of_scope_soldier_gets_403(client, admin_session) -> None:
    node = create_node(admin_session, level="team", name="rs-api-team-2")
    other_node = create_node(admin_session, level="team", name="rs-api-team-3")
    target = create_soldier(admin_session, personal_number="rs-api-002", hierarchy_node_id=node.id)
    other_soldier = create_soldier(admin_session, personal_number="rs-api-003", hierarchy_node_id=other_node.id)
    admin_session.commit()

    response = client.get(f"/api/soldiers/{target.id}/range-status", headers=auth_headers(other_soldier))

    assert response.status_code == 403


def test_duty_manager_in_scope_can_view(client, admin_session) -> None:
    node = create_node(admin_session, level="team", name="rs-api-team-4")
    target = create_soldier(admin_session, personal_number="rs-api-004", hierarchy_node_id=node.id)
    duty_manager = create_soldier(admin_session, personal_number="rs-api-005", role="duty_manager")
    admin_session.add(DutyManagerScope(duty_manager_id=duty_manager.id, hierarchy_node_id=node.id))
    admin_session.commit()

    response = client.get(f"/api/soldiers/{target.id}/range-status", headers=auth_headers(duty_manager))

    assert response.status_code == 200, response.text
