from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.settings_loader import apply_settings
from tests.helpers import auth_headers, create_node, create_range_location, create_soldier


def _enable_mitvachim(session: Session) -> None:
    apply_settings(session, {}, {"mitvachim.enabled": True}, actor_id=None)
    session.commit()


def test_scoped_duty_manager_can_submit_pending_assignment_request(
    client: TestClient, admin_session: Session,
) -> None:
    _enable_mitvachim(admin_session)
    owner_node = create_node(admin_session, level="×¤×œ×•×’×”", name="owner")
    proposer_node = create_node(admin_session, level="×¤×œ×•×’×”", name="proposer")
    owner = create_soldier(
        admin_session, personal_number="7000001", role="duty_manager", hierarchy_node_id=owner_node.id,
    )
    proposer = create_soldier(
        admin_session, personal_number="7000002", role="duty_manager", hierarchy_node_id=proposer_node.id,
    )
    soldier = create_soldier(
        admin_session, personal_number="7000003", hierarchy_node_id=proposer_node.id,
    )
    location = create_range_location(admin_session, name="test range")
    admin_session.commit()

    response = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(owner_node.id),
            "range_type": "live",
            "date": "2026-09-15",
            "range_location_id": str(location.id),
            "required_count": 1,
            "reserve_count": 1,
            "responsible_duty_manager_id": str(owner.id),
        },
        headers=auth_headers(owner),
    )
    assert response.status_code == 201, response.text
    event_id = response.json()["id"]
    assert response.json()["responsible_duty_manager_id"] == str(owner.id)

    request_response = client.post(
        f"/api/ranges/{event_id}/assignment-requests",
        json={"soldier_id": str(soldier.id), "reason": "needs qualification before next duty"},
        headers=auth_headers(proposer),
    )

    assert request_response.status_code == 201, request_response.text
    body = request_response.json()
    assert body["status"] == "pending"
    assert body["soldier_id"] == str(soldier.id)
    assert body["reason"] == "needs qualification before next duty"


def test_assignment_request_rejects_soldier_outside_proposers_scope(
    client: TestClient, admin_session: Session,
) -> None:
    _enable_mitvachim(admin_session)
    owner_node = create_node(admin_session, level="×¤×œ×•×’×”", name="owner-2")
    proposer_node = create_node(admin_session, level="×¤×œ×•×’×”", name="proposer-2")
    target_node = create_node(admin_session, level="×¤×œ×•×’×”", name="target-2")
    owner = create_soldier(
        admin_session, personal_number="7000011", role="duty_manager", hierarchy_node_id=owner_node.id,
    )
    proposer = create_soldier(
        admin_session, personal_number="7000012", role="duty_manager", hierarchy_node_id=proposer_node.id,
    )
    target = create_soldier(
        admin_session, personal_number="7000013", hierarchy_node_id=target_node.id,
    )
    location = create_range_location(admin_session, name="test range 2")
    admin_session.commit()
    response = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(owner_node.id),
            "range_type": "live",
            "date": "2026-09-16",
            "range_location_id": str(location.id),
            "required_count": 1,
            "responsible_duty_manager_id": str(owner.id),
        },
        headers=auth_headers(owner),
    )
    event_id = response.json()["id"]

    request_response = client.post(
        f"/api/ranges/{event_id}/assignment-requests",
        json={"soldier_id": str(target.id), "reason": "out of scope"},
        headers=auth_headers(proposer),
    )

    assert request_response.status_code == 403
