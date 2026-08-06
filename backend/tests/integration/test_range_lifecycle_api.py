from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.settings_loader import apply_settings
from tests.helpers import auth_headers, create_node, create_range_location, create_soldier


def test_planned_range_can_be_edited_cancelled_and_deleted_with_guards(
    client: TestClient, admin_session: Session
) -> None:
    apply_settings(admin_session, {}, {"mitvachim.enabled": True}, actor_id=None)
    admin_session.commit()
    node = create_node(admin_session, level="?????", name="??????-API-2")
    dm = create_soldier(
        admin_session, personal_number="6990001", role="duty_manager", hierarchy_node_id=node.id
    )

    loc = create_range_location(admin_session, name="????")
    admin_session.commit()
    response = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id), "range_type": "laser", "date": "2026-10-01",
            "range_location_id": str(loc.id), "required_count": 2,
        },
        headers=auth_headers(dm),
    )
    assert response.status_code == 201, response.text
    event_id = response.json()["id"]

    response = client.patch(
        f"/api/ranges/{event_id}",
        json={"range_type": "live", "date": "2026-10-02", "start_time": "08:00", "end_time": "12:00"},
        headers=auth_headers(dm),
    )
    assert response.status_code == 200, response.text
    assert response.json()["range_type"] == "live"
    assert response.json()["start_time"] == "08:00"

    response = client.patch(
        f"/api/ranges/{event_id}", json={"cancel": True}, headers=auth_headers(dm)
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "reason_required"

    response = client.patch(
        f"/api/ranges/{event_id}",
        json={"cancel": True, "cancellation_reason": "??? ?????"},
        headers=auth_headers(dm),
    )
    assert response.status_code == 200
    assert response.json()["cancellation_reason"] == "??? ?????"

    other_loc = create_range_location(admin_session, name="????")
    admin_session.commit()
    response = client.patch(
        f"/api/ranges/{event_id}", json={"range_location_id": str(other_loc.id)}, headers=auth_headers(dm)
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "event_not_planned"

    response = client.delete(f"/api/ranges/{event_id}", headers=auth_headers(dm))
    assert response.status_code == 400
    assert response.json()["detail"] == "event_not_planned"
