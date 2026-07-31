from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyType
from app.services.settings_loader import apply_settings
from tests.helpers import auth_headers, create_node, create_soldier


def _enable_mitvachim(session: Session) -> None:
    apply_settings(session, {}, {"mitvachim.enabled": True}, actor_id=None)
    session.commit()


def test_ranges_routes_404_when_disabled(client: TestClient, admin_session: Session) -> None:
    # mitvachim.enabled is off by default (no _enable_mitvachim call here).
    # Two adjustments from the brief's literal test here:
    #  1. FastAPI's dependency chain runs auth (require_password_changed)
    #     before the enabled-check in the handler body — matching the
    #     existing convention in gimelim.py/hakpaza.py, where every
    #     settings-gated route also requires auth first — so an
    #     authenticated request is needed to actually reach the check.
    #  2. `POST /ranges` with an empty body fails pydantic body validation
    #     (422) before the handler body ever runs, since FastAPI validates
    #     the request body as part of dependency resolution. `GET /ranges`
    #     (list endpoint, no request body) exercises the same
    #     _require_enabled() 404 path without that unrelated 422 noise.
    soldier = create_soldier(admin_session, personal_number="6000000")
    response = client.get("/api/ranges", headers=auth_headers(soldier))
    assert response.status_code == 404


def test_create_range_event_success(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה א")
    dm = create_soldier(admin_session, personal_number="6000001", role="duty_manager", hierarchy_node_id=node.id)

    response = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-09-01",
            "location": "מטווח דרום",
            "required_count": 4,
            "reserve_count": 1,
        },
        headers=auth_headers(dm),
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "planned"


def test_create_range_event_forbidden_outside_dm_scope(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה ב")
    other_node = create_node(admin_session, level="פלוגה", name="פלוגה ג")
    dm = create_soldier(admin_session, personal_number="6000002", role="duty_manager", hierarchy_node_id=other_node.id)

    response = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-09-01",
            "location": "מטווח",
            "required_count": 2,
        },
        headers=auth_headers(dm),
    )

    assert response.status_code == 403


def test_add_and_remove_assignment(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה ד")
    dm = create_soldier(admin_session, personal_number="6000003", role="duty_manager", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name="שמירה עם נשק ד", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    )
    admin_session.add(weapon_duty)
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number="6000004", hierarchy_node_id=node.id)

    create_resp = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id), "range_type": "live", "date": "2026-09-05",
            "location": "מטווח", "required_count": 3,
        },
        headers=auth_headers(dm),
    )
    event_id = create_resp.json()["id"]

    add_resp = client.post(
        f"/api/ranges/{event_id}/assignments",
        json={"soldier_id": str(soldier.id), "is_reserve": False},
        headers=auth_headers(dm),
    )
    assert add_resp.status_code == 201, add_resp.text
    assignment_id = add_resp.json()["id"]

    remove_resp = client.delete(f"/api/ranges/{event_id}/assignments/{assignment_id}", headers=auth_headers(dm))
    assert remove_resp.status_code == 204


def test_get_range_event_returns_roster(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה ה")
    dm = create_soldier(admin_session, personal_number="6000005", role="duty_manager", hierarchy_node_id=node.id)

    create_resp = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id), "range_type": "alal", "date": "2026-09-10",
            "location": "מטווח", "required_count": 2,
        },
        headers=auth_headers(dm),
    )
    event_id = create_resp.json()["id"]

    get_resp = client.get(f"/api/ranges/{event_id}", headers=auth_headers(dm))
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == event_id
    assert get_resp.json()["assignments"] == []
