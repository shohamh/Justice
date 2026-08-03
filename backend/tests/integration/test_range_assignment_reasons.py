from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyType, RangeAssignment
from app.services.settings_loader import apply_settings
from tests.helpers import auth_headers, create_node, create_soldier


def _enable_mitvachim(session: Session) -> None:
    apply_settings(session, {}, {"mitvachim.enabled": True}, actor_id=None)
    session.commit()


def test_manual_assignment_defaults_reason_fields_and_event_capabilities(
    client: TestClient, admin_session: Session,
) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="ענף", name="ענף חוזה מטווח")
    planner = create_soldier(
        admin_session, personal_number="7010002", role="admin", hierarchy_node_id=node.id
    )
    admin_session.add(DutyType(
        name="תורנות נשק חוזה מטווח",
        score_per_day=Decimal("1.00"),
        requires_weapon=True,
        eligible_node_ids=[node.id],
    ))
    admin_session.commit()
    event_response = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-10-01",
            "location": "מטווח",
            "required_count": 1,
        },
        headers=auth_headers(planner),
    )
    assert event_response.status_code == 201, event_response.text
    event_id = event_response.json()["id"]

    assignment_response = client.post(
        f"/api/ranges/{event_id}/assignments",
        json={"soldier_id": str(planner.id)},
        headers=auth_headers(planner),
    )
    assert assignment_response.status_code == 201, assignment_response.text
    assignment = assignment_response.json()
    assert assignment["assignment_reason_code"] == "manual"
    assert assignment["assignment_reason_text"] == "שיבוץ ידני"

    updated_reason = client.patch(
        f"/api/ranges/{event_id}/assignments/{assignment['id']}/reason",
        json={"assignment_reason_code": "custom", "assignment_reason_text": " צורך מבצעי "},
        headers=auth_headers(planner),
    )
    assert updated_reason.status_code == 200, updated_reason.text
    assert updated_reason.json()["assignment_reason_text"] == "צורך מבצעי"

    blank_custom_reason = client.patch(
        f"/api/ranges/{event_id}/assignments/{assignment['id']}/reason",
        json={"assignment_reason_code": "custom", "assignment_reason_text": "   "},
        headers=auth_headers(planner),
    )
    assert blank_custom_reason.status_code == 400
    assert blank_custom_reason.json()["detail"] == "custom_reason_text_required"

    other_event = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id), "range_type": "live", "date": "2026-10-02",
            "location": "מטווח אחר", "required_count": 1,
        },
        headers=auth_headers(planner),
    )
    assert other_event.status_code == 201, other_event.text
    other_event_reason = client.patch(
        f"/api/ranges/{other_event.json()['id']}/assignments/{assignment['id']}/reason",
        json={"assignment_reason_code": "custom", "assignment_reason_text": "צורך מבצעי"},
        headers=auth_headers(planner),
    )
    assert other_event_reason.status_code == 404
    assert other_event_reason.json()["detail"] == "assignment_not_found"

    planner_detail = client.get(f"/api/ranges/{event_id}", headers=auth_headers(planner))
    assert planner_detail.status_code == 200, planner_detail.text
    assert planner_detail.json()["assigned_to_me"] is True
    assert planner_detail.json()["can_edit_attendance"] is True
    assert planner_detail.json()["assignments"][0]["assignment_reason_code"] == "custom"

    listing = client.get(f"/api/ranges?node_id={node.id}", headers=auth_headers(planner))
    assert listing.status_code == 200, listing.text
    assert listing.json()[0]["assigned_to_me"] is True
    assert listing.json()[0]["can_edit_attendance"] is True


def test_read_only_commander_cannot_see_own_draft_assignment_or_mutate_its_reason(
    client: TestClient, admin_session: Session,
) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגת טיוטה נסתרת")
    planner = create_soldier(
        admin_session, personal_number="7010010", role="duty_manager", hierarchy_node_id=node.id
    )
    commander = create_soldier(
        admin_session, personal_number="7010011", role="commander", hierarchy_node_id=node.id
    )
    node.commander_id = commander.id
    admin_session.commit()
    event_response = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id), "range_type": "laser", "date": "2026-10-03",
            "location": "מטווח", "required_count": 1,
        },
        headers=auth_headers(planner),
    )
    assert event_response.status_code == 201, event_response.text
    event_id = event_response.json()["id"]
    draft = RangeAssignment(
        range_event_id=event_id, soldier_id=commander.id, is_reserve=False, is_draft=True,
    )
    admin_session.add(draft)
    admin_session.commit()

    response = client.get(f"/api/ranges/{event_id}", headers=auth_headers(commander))

    assert response.status_code == 200, response.text
    assert response.json()["assignments"] == []
    assert response.json()["assigned_to_me"] is False
    assert response.json()["can_edit_attendance"] is False

    list_response = client.get(
        f"/api/ranges?node_id={node.id}", headers=auth_headers(commander)
    )
    assert list_response.status_code == 200, list_response.text
    assert list_response.json()[0]["assigned_to_me"] is False
    assert list_response.json()[0]["can_edit_attendance"] is False

    mutation = client.patch(
        f"/api/ranges/{event_id}/assignments/{draft.id}/reason",
        json={"assignment_reason_code": "custom", "assignment_reason_text": "צורך מבצעי"},
        headers=auth_headers(commander),
    )
    assert mutation.status_code == 403

    planner_response = client.get(f"/api/ranges/{event_id}", headers=auth_headers(planner))
    assert planner_response.status_code == 200, planner_response.text
    assert [row["id"] for row in planner_response.json()["assignments"]] == [str(draft.id)]
