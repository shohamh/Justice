from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyManagerScope, DutyType, RangeAssignment
from app.services.settings_loader import apply_settings
from tests.helpers import auth_headers, create_node, create_range_location, create_soldier


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
    #  3. Task 15 made `node_id` a required query param on the list route,
    #     so a node_id must be supplied here too (any value works — the
    #     enabled-check runs before the node lookup in the handler body).
    soldier = create_soldier(admin_session, personal_number="6000000")
    node = create_node(admin_session, level="פלוגה", name="פלוגה תת0")
    response = client.get(f"/api/ranges?node_id={node.id}", headers=auth_headers(soldier))
    assert response.status_code == 404


def test_create_range_event_success(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה א")
    dm = create_soldier(
        admin_session, personal_number="6000001", role="duty_manager", hierarchy_node_id=node.id
    )
    loc = create_range_location(admin_session, name="מטווח דרום")
    admin_session.commit()

    response = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-09-01",
            "range_location_id": str(loc.id),
            "required_count": 4,
            "reserve_count": 1,
        },
        headers=auth_headers(dm),
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "planned"
    assert response.json()["responsible_duty_manager_id"] == str(dm.id)


def test_create_range_event_respects_explicit_responsible_duty_manager(
    client: TestClient, admin_session: Session
) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה אחראי-נבחר")
    dm = create_soldier(
        admin_session, personal_number="6000010", role="duty_manager", hierarchy_node_id=node.id
    )
    other_dm = create_soldier(
        admin_session, personal_number="6000011", role="duty_manager", hierarchy_node_id=node.id
    )
    loc = create_range_location(admin_session, name="מטווח")
    admin_session.commit()

    response = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-09-01",
            "range_location_id": str(loc.id),
            "required_count": 2,
            "responsible_duty_manager_id": str(other_dm.id),
        },
        headers=auth_headers(dm),
    )

    assert response.status_code == 201, response.text
    assert response.json()["responsible_duty_manager_id"] == str(other_dm.id)


def test_update_range_event_changes_responsible_duty_manager(
    client: TestClient, admin_session: Session
) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה אחראי-עדכון")
    dm = create_soldier(
        admin_session, personal_number="6000012", role="duty_manager", hierarchy_node_id=node.id
    )
    new_manager = create_soldier(
        admin_session, personal_number="6000013", role="duty_manager", hierarchy_node_id=node.id
    )
    loc = create_range_location(admin_session, name="מטווח")
    admin_session.commit()

    created = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-09-01",
            "range_location_id": str(loc.id),
            "required_count": 2,
        },
        headers=auth_headers(dm),
    ).json()

    response = client.patch(
        f"/api/ranges/{created['id']}",
        json={"responsible_duty_manager_id": str(new_manager.id)},
        headers=auth_headers(dm),
    )

    assert response.status_code == 200, response.text
    assert response.json()["responsible_duty_manager_id"] == str(new_manager.id)


def test_create_range_event_forbidden_outside_dm_scope(
    client: TestClient, admin_session: Session
) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה ב")
    other_node = create_node(admin_session, level="פלוגה", name="פלוגה ג")
    dm = create_soldier(
        admin_session,
        personal_number="6000002",
        role="duty_manager",
        hierarchy_node_id=other_node.id,
    )
    loc = create_range_location(admin_session, name="מטווח")
    admin_session.commit()

    response = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-09-01",
            "range_location_id": str(loc.id),
            "required_count": 2,
        },
        headers=auth_headers(dm),
    )

    assert response.status_code == 403


def test_add_and_remove_assignment(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה ד")
    dm = create_soldier(
        admin_session, personal_number="6000003", role="duty_manager", hierarchy_node_id=node.id
    )
    weapon_duty = DutyType(
        name="שמירה עם נשק ד",
        score_per_day=Decimal("1.00"),
        requires_weapon=True,
        eligible_node_ids=[node.id],
    )
    admin_session.add(weapon_duty)
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number="6000004", hierarchy_node_id=node.id)
    loc = create_range_location(admin_session, name="מטווח")
    admin_session.commit()

    create_resp = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "live",
            "date": "2026-09-05",
            "range_location_id": str(loc.id),
            "required_count": 3,
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

    remove_resp = client.request(
        "DELETE",
        f"/api/ranges/{event_id}/assignments/{assignment_id}",
        json={"reason": "חייל שוחרר"},
        headers=auth_headers(dm),
    )
    assert remove_resp.status_code == 204


def test_remove_assignment_requires_reason_in_body(client, admin_session):
    from app.db.models import RangeType
    from app.services.ranges import add_range_assignment, create_range_event

    node = create_node(admin_session, level="branch", name="rra-api-1")
    dm = create_soldier(admin_session, personal_number="rra-api-dm1", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="rra-api-s1", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name="שמירה עם נשק rra-api",
        score_per_day=Decimal("1.00"),
        requires_weapon=True,
        eligible_node_ids=[node.id],
    )
    admin_session.add(weapon_duty)
    admin_session.commit()
    _enable_mitvachim(admin_session)
    event = create_range_event(
        admin_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(admin_session).id, required_count=1,
    )
    assignment = add_range_assignment(admin_session, event=event, soldier_id=soldier.id, is_reserve=False)

    resp = client.request(
        "DELETE", f"/api/ranges/{event.id}/assignments/{assignment.id}",
        json={"reason": "חייל שוחרר"}, headers=auth_headers(dm),
    )
    assert resp.status_code == 204


def test_remove_assignment_missing_reason_rejected(client, admin_session):
    from app.db.models import RangeType
    from app.services.ranges import add_range_assignment, create_range_event

    node = create_node(admin_session, level="branch", name="rra-api-2")
    dm = create_soldier(admin_session, personal_number="rra-api-dm2", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="rra-api-s2", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name="שמירה עם נשק rra-api-2",
        score_per_day=Decimal("1.00"),
        requires_weapon=True,
        eligible_node_ids=[node.id],
    )
    admin_session.add(weapon_duty)
    admin_session.commit()
    _enable_mitvachim(admin_session)
    event = create_range_event(
        admin_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(admin_session).id, required_count=1,
    )
    assignment = add_range_assignment(admin_session, event=event, soldier_id=soldier.id, is_reserve=False)

    resp = client.request(
        "DELETE", f"/api/ranges/{event.id}/assignments/{assignment.id}",
        json={}, headers=auth_headers(dm),
    )
    assert resp.status_code == 422


def test_remove_assignment_whitespace_reason_rejected(client, admin_session):
    from app.db.models import RangeType
    from app.services.ranges import add_range_assignment, create_range_event

    node = create_node(admin_session, level="branch", name="rra-api-3")
    dm = create_soldier(admin_session, personal_number="rra-api-dm3", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="rra-api-s3", hierarchy_node_id=node.id)
    weapon_duty = DutyType(
        name="שמירה עם נשק rra-api-3",
        score_per_day=Decimal("1.00"),
        requires_weapon=True,
        eligible_node_ids=[node.id],
    )
    admin_session.add(weapon_duty)
    admin_session.commit()
    _enable_mitvachim(admin_session)
    event = create_range_event(
        admin_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(admin_session).id, required_count=1,
    )
    assignment = add_range_assignment(admin_session, event=event, soldier_id=soldier.id, is_reserve=False)

    resp = client.request(
        "DELETE", f"/api/ranges/{event.id}/assignments/{assignment.id}",
        json={"reason": "   "}, headers=auth_headers(dm),
    )
    assert resp.status_code == 422


def test_get_range_event_returns_roster(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה ה")
    dm = create_soldier(
        admin_session, personal_number="6000005", role="duty_manager", hierarchy_node_id=node.id
    )
    loc = create_range_location(admin_session, name="מטווח")
    admin_session.commit()

    create_resp = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "alal",
            "date": "2026-09-10",
            "range_location_id": str(loc.id),
            "required_count": 2,
        },
        headers=auth_headers(dm),
    )
    event_id = create_resp.json()["id"]

    get_resp = client.get(f"/api/ranges/{event_id}", headers=auth_headers(dm))
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == event_id
    assert get_resp.json()["assignments"] == []


def test_get_range_event_returns_food_summary_to_duty_manager(
    client: TestClient, admin_session: Session
) -> None:
    from app.db.models import RangeType
    from app.services.ranges import add_range_assignment, create_range_event

    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="branch", name="food-summary-node")
    dm = create_soldier(admin_session, personal_number="food-summary-dm", role="duty_manager", hierarchy_node_id=node.id)
    primary = create_soldier(admin_session, personal_number="food-summary-p", hierarchy_node_id=node.id)
    primary.food_type = "vegetarian"
    primary.food_constraints = "Peanut allergy"
    reserve = create_soldier(admin_session, personal_number="food-summary-r", hierarchy_node_id=node.id)
    reserve.food_type = "vegan"
    reserve.food_constraints = "No soy"
    admin_session.add(DutyType(
        name="food-summary-weapon-duty", score_per_day=Decimal("1.00"),
        requires_weapon=True, eligible_node_ids=[node.id],
    ))
    admin_session.commit()
    event = create_range_event(
        admin_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(admin_session).id, required_count=1, reserve_count=1,
    )
    add_range_assignment(admin_session, event=event, soldier_id=primary.id, is_reserve=False)
    add_range_assignment(admin_session, event=event, soldier_id=reserve.id, is_reserve=True)

    response = client.get(f"/api/ranges/{event.id}", headers=auth_headers(dm))

    assert response.status_code == 200, response.text
    summary = response.json()["food_summary"]
    assert summary["primary"]["counts"]["vegetarian"] == 1
    assert summary["reserve"]["counts"]["vegan"] == 1
    assert summary["primary"]["special_constraints"][0]["constraint"] == "Peanut allergy"
    assert summary["reserve"]["special_constraints"][0]["constraint"] == "No soy"


def test_get_range_event_hides_drafts_from_commander_but_not_range_managers(
    client: TestClient, admin_session: Session
) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה תת-מפקד-בתחום")
    dm = create_soldier(
        admin_session, personal_number="6300001", role="duty_manager", hierarchy_node_id=node.id
    )
    commander = create_soldier(
        admin_session, personal_number="6300002", role="commander", hierarchy_node_id=node.id
    )
    admin = create_soldier(
        admin_session, personal_number="6300005", role="admin", hierarchy_node_id=node.id
    )
    confirmed_soldier = create_soldier(
        admin_session, personal_number="6300006", hierarchy_node_id=node.id
    )
    draft_soldier = create_soldier(
        admin_session, personal_number="6300007", hierarchy_node_id=node.id
    )
    node.commander_id = commander.id
    loc = create_range_location(admin_session, name="מטווח")
    admin_session.commit()

    create_resp = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-09-10",
            "range_location_id": str(loc.id),
            "required_count": 2,
        },
        headers=auth_headers(dm),
    )
    event_id = create_resp.json()["id"]
    confirmed = RangeAssignment(
        range_event_id=event_id,
        soldier_id=confirmed_soldier.id,
        is_reserve=False,
        is_draft=False,
    )
    draft = RangeAssignment(
        range_event_id=event_id,
        soldier_id=draft_soldier.id,
        is_reserve=False,
        is_draft=True,
    )
    admin_session.add_all([confirmed, draft])
    admin_session.commit()

    dm_response = client.get(f"/api/ranges/{event_id}", headers=auth_headers(dm))
    admin_response = client.get(f"/api/ranges/{event_id}", headers=auth_headers(admin))
    assert dm_response.status_code == 200
    assert admin_response.status_code == 200
    assert {row["id"] for row in dm_response.json()["assignments"]} == {
        str(confirmed.id), str(draft.id)
    }
    assert {row["id"] for row in admin_response.json()["assignments"]} == {
        str(confirmed.id), str(draft.id)
    }

    get_resp = client.get(f"/api/ranges/{event_id}", headers=auth_headers(commander))
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == event_id
    assert [row["id"] for row in get_resp.json()["assignments"]] == [str(confirmed.id)]


def test_get_range_event_forbidden_for_commander_outside_scope(
    client: TestClient, admin_session: Session
) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה תת-מחוץ-לתחום")
    other_node = create_node(admin_session, level="פלוגה", name="פלוגה תת-אחרת")
    dm = create_soldier(
        admin_session, personal_number="6300003", role="duty_manager", hierarchy_node_id=node.id
    )
    commander = create_soldier(
        admin_session, personal_number="6300004", role="commander", hierarchy_node_id=other_node.id
    )
    other_node.commander_id = commander.id
    loc = create_range_location(admin_session, name="מטווח")
    admin_session.commit()

    create_resp = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-09-10",
            "range_location_id": str(loc.id),
            "required_count": 2,
        },
        headers=auth_headers(dm),
    )
    event_id = create_resp.json()["id"]

    get_resp = client.get(f"/api/ranges/{event_id}", headers=auth_headers(commander))
    assert get_resp.status_code == 403


def test_mark_attendance_requires_elevated_dm_scope(
    client: TestClient, admin_session: Session
) -> None:
    _enable_mitvachim(admin_session)
    apply_settings(
        admin_session, {}, {"mitvachim.attendance_edit_min_level": "branch"}, actor_id=None
    )
    battalion = create_node(admin_session, level="unit", name="גדוד ט1")
    company = create_node(admin_session, level="branch", name="ענף ט1", parent=battalion)
    platoon = create_node(admin_session, level="group", name="פלוגה ט1", parent=company)
    low_dm = create_soldier(
        admin_session, personal_number="6100001", role="duty_manager", hierarchy_node_id=platoon.id
    )
    high_dm = create_soldier(
        admin_session, personal_number="6100002", role="duty_manager", hierarchy_node_id=company.id
    )
    weapon_duty = DutyType(
        name="שמירה עם נשק ט1",
        score_per_day=Decimal("1.00"),
        requires_weapon=True,
        eligible_node_ids=[platoon.id],
    )
    admin_session.add(weapon_duty)
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number="6100003", hierarchy_node_id=platoon.id)
    loc = create_range_location(admin_session, name="מטווח")
    admin_session.commit()

    past_date = date.today() - timedelta(days=1)
    create_resp = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(platoon.id),
            "range_type": "laser",
            "date": past_date.isoformat(),
            "range_location_id": str(loc.id),
            "required_count": 1,
        },
        headers=auth_headers(high_dm),
    )
    event_id = create_resp.json()["id"]
    add_resp = client.post(
        f"/api/ranges/{event_id}/assignments",
        json={"soldier_id": str(soldier.id), "is_reserve": False},
        headers=auth_headers(high_dm),
    )
    assignment_id = add_resp.json()["id"]

    denied_resp = client.patch(
        f"/api/ranges/{event_id}/assignments/{assignment_id}/attendance",
        json={"status": "present"},
        headers=auth_headers(low_dm),
    )
    assert denied_resp.status_code == 403

    allowed_resp = client.patch(
        f"/api/ranges/{event_id}/assignments/{assignment_id}/attendance",
        json={"status": "present"},
        headers=auth_headers(high_dm),
    )
    assert allowed_resp.status_code == 200, allowed_resp.text
    assert allowed_resp.json()["attendance_status"] == "present"


def test_list_range_events_requires_node_id(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה תת1")
    dm = create_soldier(
        admin_session, personal_number="6200001", role="duty_manager", hierarchy_node_id=node.id
    )

    response = client.get("/api/ranges", headers=auth_headers(dm))
    assert response.status_code == 422


def test_list_range_events_filters_by_node_and_date(
    client: TestClient, admin_session: Session
) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה תת2")
    other_node = create_node(admin_session, level="פלוגה", name="פלוגה תת3")
    dm = create_soldier(
        admin_session, personal_number="6200002", role="duty_manager", hierarchy_node_id=node.id
    )
    loc_in = create_range_location(admin_session, name="מטווח בתוך")
    admin_session.commit()
    client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-09-01",
            "range_location_id": str(loc_in.id),
            "required_count": 1,
        },
        headers=auth_headers(dm),
    )
    other_dm = create_soldier(
        admin_session,
        personal_number="6200003",
        role="duty_manager",
        hierarchy_node_id=other_node.id,
    )
    loc_out = create_range_location(admin_session, name="מטווח מחוץ")
    admin_session.commit()
    client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(other_node.id),
            "range_type": "laser",
            "date": "2026-09-01",
            "range_location_id": str(loc_out.id),
            "required_count": 1,
        },
        headers=auth_headers(other_dm),
    )

    response = client.get(f"/api/ranges?node_id={node.id}", headers=auth_headers(dm))
    assert response.status_code == 200
    locations = [e["location"] for e in response.json()]
    assert locations == ["מטווח בתוך"]


def test_list_range_events_filters_by_date_range(
    client: TestClient, admin_session: Session
) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה תת4")
    dm = create_soldier(
        admin_session, personal_number="6200004", role="duty_manager", hierarchy_node_id=node.id
    )
    loc_sept = create_range_location(admin_session, name="מטווח ספטמבר")
    admin_session.commit()
    client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-09-01",
            "range_location_id": str(loc_sept.id),
            "required_count": 1,
        },
        headers=auth_headers(dm),
    )
    loc_oct = create_range_location(admin_session, name="מטווח אוקטובר")
    admin_session.commit()
    client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-10-01",
            "range_location_id": str(loc_oct.id),
            "required_count": 1,
        },
        headers=auth_headers(dm),
    )

    response = client.get(
        f"/api/ranges?node_id={node.id}&date_from=2026-09-15&date_to=2026-10-15",
        headers=auth_headers(dm),
    )
    assert response.status_code == 200
    locations = [e["location"] for e in response.json()]
    assert locations == ["מטווח אוקטובר"]


def test_get_range_candidates_forbidden_for_non_manager(
    client: TestClient, admin_session: Session
) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה תת-מועמדים1")
    dm = create_soldier(
        admin_session, personal_number="6400001", role="duty_manager", hierarchy_node_id=node.id
    )
    soldier = create_soldier(admin_session, personal_number="6400002", hierarchy_node_id=node.id)
    loc = create_range_location(admin_session, name="מטווח")
    admin_session.commit()

    create_resp = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-09-01",
            "range_location_id": str(loc.id),
            "required_count": 2,
        },
        headers=auth_headers(dm),
    )
    event_id = create_resp.json()["id"]

    response = client.get(
        f"/api/ranges/{event_id}/candidates", headers=auth_headers(soldier)
    )
    assert response.status_code == 403


def test_get_range_candidates_404_when_disabled(
    client: TestClient, admin_session: Session
) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה תת-מועמדים2")
    dm = create_soldier(
        admin_session, personal_number="6400003", role="duty_manager", hierarchy_node_id=node.id
    )
    loc = create_range_location(admin_session, name="מטווח")
    admin_session.commit()
    create_resp = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-09-01",
            "range_location_id": str(loc.id),
            "required_count": 2,
        },
        headers=auth_headers(dm),
    )
    event_id = create_resp.json()["id"]

    apply_settings(admin_session, {}, {"mitvachim.enabled": False}, actor_id=None)
    admin_session.commit()

    response = client.get(
        f"/api/ranges/{event_id}/candidates", headers=auth_headers(dm)
    )
    assert response.status_code == 404


def test_batch_assign_forbidden_for_non_manager(
    client: TestClient, admin_session: Session
) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה תת-באצ1")
    dm = create_soldier(
        admin_session, personal_number="6400004", role="duty_manager", hierarchy_node_id=node.id
    )
    soldier = create_soldier(admin_session, personal_number="6400005", hierarchy_node_id=node.id)
    loc = create_range_location(admin_session, name="מטווח")
    admin_session.commit()

    create_resp = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-09-01",
            "range_location_id": str(loc.id),
            "required_count": 2,
        },
        headers=auth_headers(dm),
    )
    event_id = create_resp.json()["id"]

    response = client.post(
        f"/api/ranges/{event_id}/assignments/batch",
        json={"primaries": [str(soldier.id)], "reserves": []},
        headers=auth_headers(soldier),
    )
    assert response.status_code == 403


def _scoped_dm(session: Session, *, node, personal_number: str) -> "Soldier":
    """A duty manager scoped to `node` via DutyManagerScope but not itself a
    soldier inside `node`'s subtree — so they never show up as a range candidate
    and don't skew reconciliation's refill/shortage outcome."""
    from app.db.models import Soldier

    dm = create_soldier(session, personal_number=personal_number, role="duty_manager", hierarchy_node_id=None)
    session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    session.commit()
    return dm


def _weapon_duty_type_for(session: Session, *, node, name: str) -> DutyType:
    duty_type = DutyType(
        name=name, score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id],
    )
    session.add(duty_type)
    session.commit()
    return duty_type


def test_add_assignment_reconciles_and_refills_later_duplicate_via_api(
    client: TestClient, admin_session: Session
) -> None:
    """POSTing a single assignment that gives a soldier guaranteed future coverage
    (a planned primary slot) must reconcile away their now-redundant later duplicate
    and refill that vacated slot from the later event's own subtree, preserving the
    slot kind (primary stays primary) — exercised through the real HTTP endpoints,
    not the service layer directly."""
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="branch", name="api-reconcile-1")
    dm = _scoped_dm(admin_session, node=node, personal_number="api-recon-dm1")
    covered = create_soldier(admin_session, personal_number="api-recon-s1", hierarchy_node_id=node.id)
    replacement = create_soldier(admin_session, personal_number="api-recon-s2", hierarchy_node_id=node.id)
    _weapon_duty_type_for(admin_session, node=node, name="api-reconcile-1 weapon")
    loc = create_range_location(admin_session, name="api-reconcile-1 loc")
    admin_session.commit()

    later_create = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id), "range_type": "laser",
            "date": (date.today() + timedelta(days=10)).isoformat(),
            "range_location_id": str(loc.id), "required_count": 1,
        },
        headers=auth_headers(dm),
    )
    assert later_create.status_code == 201, later_create.text
    later_event_id = later_create.json()["id"]
    later_add = client.post(
        f"/api/ranges/{later_event_id}/assignments",
        json={"soldier_id": str(covered.id), "is_reserve": False},
        headers=auth_headers(dm),
    )
    assert later_add.status_code == 201, later_add.text
    later_assignment_id = later_add.json()["id"]

    source_create = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id), "range_type": "live",
            "date": (date.today() + timedelta(days=5)).isoformat(),
            "range_location_id": str(loc.id), "required_count": 1,
        },
        headers=auth_headers(dm),
    )
    assert source_create.status_code == 201, source_create.text
    source_event_id = source_create.json()["id"]

    add_resp = client.post(
        f"/api/ranges/{source_event_id}/assignments",
        json={"soldier_id": str(covered.id), "is_reserve": False},
        headers=auth_headers(dm),
    )

    assert add_resp.status_code == 201, add_resp.text
    assert add_resp.json()["soldier_id"] == str(covered.id)

    later_get = client.get(f"/api/ranges/{later_event_id}", headers=auth_headers(dm))
    assert later_get.status_code == 200
    assignments = later_get.json()["assignments"]
    assert later_assignment_id not in {a["id"] for a in assignments}
    assert len(assignments) == 1
    refilled = assignments[0]
    assert refilled["soldier_id"] == str(replacement.id)
    assert refilled["is_reserve"] is False


def test_batch_assign_reconciles_and_refills_via_api(
    client: TestClient, admin_session: Session
) -> None:
    """A batch assignment call reconciles for every soldier it creates a row for,
    regardless of whether the vacated later slot was primary or reserve — the
    refill always preserves the vacated slot's own kind."""
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="branch", name="api-reconcile-batch")
    dm = _scoped_dm(admin_session, node=node, personal_number="api-recon-batch-dm")
    covered_primary = create_soldier(admin_session, personal_number="api-recon-batch-p", hierarchy_node_id=node.id)
    covered_reserve = create_soldier(admin_session, personal_number="api-recon-batch-r", hierarchy_node_id=node.id)
    create_soldier(admin_session, personal_number="api-recon-batch-x1", hierarchy_node_id=node.id)
    create_soldier(admin_session, personal_number="api-recon-batch-x2", hierarchy_node_id=node.id)
    _weapon_duty_type_for(admin_session, node=node, name="api-reconcile-batch weapon")
    loc = create_range_location(admin_session, name="api-reconcile-batch loc")
    admin_session.commit()

    later_create = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id), "range_type": "laser",
            "date": (date.today() + timedelta(days=10)).isoformat(),
            "range_location_id": str(loc.id), "required_count": 1, "reserve_count": 1,
        },
        headers=auth_headers(dm),
    )
    later_event_id = later_create.json()["id"]
    later_primary = client.post(
        f"/api/ranges/{later_event_id}/assignments",
        json={"soldier_id": str(covered_primary.id), "is_reserve": False},
        headers=auth_headers(dm),
    )
    later_reserve = client.post(
        f"/api/ranges/{later_event_id}/assignments",
        json={"soldier_id": str(covered_reserve.id), "is_reserve": True},
        headers=auth_headers(dm),
    )
    assert later_primary.status_code == 201, later_primary.text
    assert later_reserve.status_code == 201, later_reserve.text
    later_primary_id = later_primary.json()["id"]
    later_reserve_id = later_reserve.json()["id"]

    source_create = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id), "range_type": "live",
            "date": (date.today() + timedelta(days=5)).isoformat(),
            "range_location_id": str(loc.id), "required_count": 2,
        },
        headers=auth_headers(dm),
    )
    source_event_id = source_create.json()["id"]

    batch_resp = client.post(
        f"/api/ranges/{source_event_id}/assignments/batch",
        json={"primaries": [str(covered_primary.id), str(covered_reserve.id)], "reserves": []},
        headers=auth_headers(dm),
    )
    assert batch_resp.status_code == 200, batch_resp.text
    assert {row["soldier_id"] for row in batch_resp.json()} == {str(covered_primary.id), str(covered_reserve.id)}

    later_get = client.get(f"/api/ranges/{later_event_id}", headers=auth_headers(dm))
    assert later_get.status_code == 200
    assignments = later_get.json()["assignments"]
    ids = {a["id"] for a in assignments}
    assert later_primary_id not in ids
    assert later_reserve_id not in ids
    assert len(assignments) == 2
    primary_row = next(a for a in assignments if not a["is_reserve"])
    reserve_row = next(a for a in assignments if a["is_reserve"])
    assert primary_row["soldier_id"] not in {str(covered_primary.id), str(covered_reserve.id)}
    assert reserve_row["soldier_id"] not in {str(covered_primary.id), str(covered_reserve.id)}


def test_add_assignment_reconciliation_shortage_visible_via_api(
    client: TestClient, admin_session: Session
) -> None:
    """When reconciliation removes a later duplicate but no valid replacement
    exists anywhere in that later event's hierarchy subtree, the API request that
    triggered it must still succeed (the source assignment is created), and the
    shortfall must be visible through the later event's existing data — the
    already-returned primary_filled/required_count pair — with no new response
    field required."""
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="branch", name="api-reconcile-shortage")
    dm = _scoped_dm(admin_session, node=node, personal_number="api-recon-short-dm")
    covered = create_soldier(admin_session, personal_number="api-recon-short-s1", hierarchy_node_id=node.id)
    # No other soldier exists in the node's subtree, so reconciliation's refill
    # step will find nobody to take the vacated slot.
    _weapon_duty_type_for(admin_session, node=node, name="api-reconcile-shortage weapon")
    loc = create_range_location(admin_session, name="api-reconcile-shortage loc")
    admin_session.commit()

    later_create = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id), "range_type": "laser",
            "date": (date.today() + timedelta(days=10)).isoformat(),
            "range_location_id": str(loc.id), "required_count": 1,
        },
        headers=auth_headers(dm),
    )
    later_event_id = later_create.json()["id"]
    later_add = client.post(
        f"/api/ranges/{later_event_id}/assignments",
        json={"soldier_id": str(covered.id), "is_reserve": False},
        headers=auth_headers(dm),
    )
    assert later_add.status_code == 201, later_add.text

    source_create = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id), "range_type": "live",
            "date": (date.today() + timedelta(days=5)).isoformat(),
            "range_location_id": str(loc.id), "required_count": 1,
        },
        headers=auth_headers(dm),
    )
    source_event_id = source_create.json()["id"]

    add_resp = client.post(
        f"/api/ranges/{source_event_id}/assignments",
        json={"soldier_id": str(covered.id), "is_reserve": False},
        headers=auth_headers(dm),
    )
    assert add_resp.status_code == 201, add_resp.text

    later_get = client.get(f"/api/ranges/{later_event_id}", headers=auth_headers(dm))
    assert later_get.status_code == 200
    body = later_get.json()
    assert body["assignments"] == []
    # The shortfall is fully visible from data the API already returns: 0 filled
    # against a required_count of 1, with no new field needed to express it.
    assert body["primary_filled"] == 0
    assert body["required_count"] == 1


def test_batch_assign_stale_candidate_rejected_with_no_partial_writes(
    client: TestClient, admin_session: Session
) -> None:
    """A regression check on pre-existing all-or-nothing validation: if a candidate
    from a previously-fetched list gets assigned elsewhere on a conflicting date
    before the batch is submitted, assign_batch must still reject the whole batch
    (soldier_already_assigned_on_date) and write nothing — reconciliation's wiring
    must not have weakened this pre-existing guarantee."""
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="branch", name="api-stale-race")
    dm = create_soldier(
        admin_session, personal_number="api-stale-race-dm", role="duty_manager", hierarchy_node_id=node.id
    )
    soldier_a = create_soldier(admin_session, personal_number="api-stale-race-a", hierarchy_node_id=node.id)
    soldier_b = create_soldier(admin_session, personal_number="api-stale-race-b", hierarchy_node_id=node.id)
    _weapon_duty_type_for(admin_session, node=node, name="api-stale-race weapon")
    loc = create_range_location(admin_session, name="api-stale-race loc")
    admin_session.commit()

    event_date = (date.today() + timedelta(days=5)).isoformat()
    create_resp = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id), "range_type": "laser",
            "date": event_date, "range_location_id": str(loc.id), "required_count": 2,
        },
        headers=auth_headers(dm),
    )
    event_id = create_resp.json()["id"]

    candidates_resp = client.get(f"/api/ranges/{event_id}/candidates", headers=auth_headers(dm))
    assert candidates_resp.status_code == 200
    candidate_ids = {c["soldier_id"] for c in candidates_resp.json()["candidates"]}
    assert {str(soldier_a.id), str(soldier_b.id)}.issubset(candidate_ids)

    # A prior/concurrent operation assigns soldier_a elsewhere on the same date,
    # making them no longer a valid candidate for the batch below.
    conflicting_create = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id), "range_type": "laser",
            "date": event_date, "range_location_id": str(loc.id), "required_count": 1,
        },
        headers=auth_headers(dm),
    )
    conflicting_event_id = conflicting_create.json()["id"]
    conflict_add = client.post(
        f"/api/ranges/{conflicting_event_id}/assignments",
        json={"soldier_id": str(soldier_a.id), "is_reserve": False},
        headers=auth_headers(dm),
    )
    assert conflict_add.status_code == 201, conflict_add.text

    # Submit the original (now-stale) batch built from the earlier candidate list.
    batch_resp = client.post(
        f"/api/ranges/{event_id}/assignments/batch",
        json={"primaries": [str(soldier_a.id), str(soldier_b.id)], "reserves": []},
        headers=auth_headers(dm),
    )

    assert batch_resp.status_code == 400
    assert batch_resp.json()["detail"] == "soldier_already_assigned_on_date"

    get_resp = client.get(f"/api/ranges/{event_id}", headers=auth_headers(dm))
    assert get_resp.status_code == 200
    assert get_resp.json()["assignments"] == []
    assert admin_session.query(RangeAssignment).filter(
        RangeAssignment.range_event_id == event_id,
    ).count() == 0


def test_batch_assign_404_when_disabled(
    client: TestClient, admin_session: Session
) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="פלוגה", name="פלוגה תת-באצ2")
    dm = create_soldier(
        admin_session, personal_number="6400006", role="duty_manager", hierarchy_node_id=node.id
    )
    soldier = create_soldier(admin_session, personal_number="6400007", hierarchy_node_id=node.id)
    loc = create_range_location(admin_session, name="מטווח")
    admin_session.commit()
    create_resp = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id),
            "range_type": "laser",
            "date": "2026-09-01",
            "range_location_id": str(loc.id),
            "required_count": 2,
        },
        headers=auth_headers(dm),
    )
    event_id = create_resp.json()["id"]

    apply_settings(admin_session, {}, {"mitvachim.enabled": False}, actor_id=None)
    admin_session.commit()

    response = client.post(
        f"/api/ranges/{event_id}/assignments/batch",
        json={"primaries": [str(soldier.id)], "reserves": []},
        headers=auth_headers(dm),
    )
    assert response.status_code == 404
