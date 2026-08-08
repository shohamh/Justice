from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyType, RangeAssignment
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
