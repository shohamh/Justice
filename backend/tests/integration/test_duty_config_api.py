from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_soldier


def test_admin_creates_and_lists_duty_type(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5100001", role="admin")
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "שמירה-א", "score_per_day": "1.50", "is_external": False},
    )
    assert r.status_code == 201, r.text
    dt_id = r.json()["id"]
    r2 = client.get("/api/duty-config/duty-types", headers=auth_headers(admin))
    assert r2.status_code == 200
    assert any(d["id"] == dt_id for d in r2.json())


def test_duty_manager_allowed(client: TestClient, admin_session: Session):
    dm = create_soldier(admin_session, personal_number="5100002", role="duty_manager")
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(dm),
        json={"name": "ניקיון-א", "score_per_day": "1.00", "is_external": False},
    )
    assert r.status_code == 201


def test_plain_soldier_forbidden(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5100003", role="soldier")
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(s),
        json={"name": "x", "score_per_day": "1.00"},
    )
    assert r.status_code == 403


def test_commander_forbidden(client: TestClient, admin_session: Session):
    c = create_soldier(admin_session, personal_number="5100004", role="commander")
    r = client.get("/api/duty-config/duty-types", headers=auth_headers(c))
    assert r.status_code == 403


def test_commander_can_list_exemption_types(client: TestClient, admin_session: Session):
    # Reference data is readable by any authenticated user (needed to fill the grant form).
    c = create_soldier(admin_session, personal_number="5100041", role="commander")
    assert (
        client.get("/api/duty-config/exemption-types", headers=auth_headers(c)).status_code == 200
    )


def test_duplicate_name_rejected(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5100005", role="admin")
    client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "כפול-א", "score_per_day": "1.00", "is_external": False},
    )
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "כפול-א", "score_per_day": "2.00", "is_external": False},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "name_taken"


def test_set_exemption_duty_types(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5100006", role="admin")
    et = client.post(
        "/api/duty-config/exemption-types", headers=auth_headers(admin), json={"name": "פטור-א"}
    ).json()
    dt = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "מטבח-א", "score_per_day": "1.00", "is_external": False},
    ).json()
    r = client.put(
        f"/api/duty-config/exemption-types/{et['id']}/duty-types",
        headers=auth_headers(admin),
        json={"duty_type_ids": [dt["id"]]},
    )
    assert r.status_code == 200
    r2 = client.get(
        f"/api/duty-config/exemption-types/{et['id']}/duty-types", headers=auth_headers(admin)
    )
    assert r2.json() == [dt["id"]]


def test_create_duty_type_with_operational_fields(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200001", role="admin")
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={
            "name": "שמירה-ב",
            "score_per_day": "1.00",
            "contact_name": "יוסי כהן",
            "contact_phone": "050-1234567",
            "start_time": "06:00:00",
            "end_time": "18:00:00",
            "instructions": "להגיע עם נשק",
            "is_external": False,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["contact_name"] == "יוסי כהן"
    assert data["contact_phone"] == "050-1234567"
    assert data["start_time"] == "06:00:00"
    assert data["end_time"] == "18:00:00"
    assert data["instructions"] == "להגיע עם נשק"
    assert data["is_external"] is False


def test_create_duty_type_is_external_required(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200002", role="admin")
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "שמירה-ג", "score_per_day": "1.00"},
    )
    assert r.status_code == 422


def test_create_duty_type_instructions_too_long(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200003", role="admin")
    long_instructions = " ".join(["מילה"] * 301)
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "שמירה-ד", "score_per_day": "1.00", "is_external": False, "instructions": long_instructions},
    )
    assert r.status_code == 422


def test_update_duty_type_operational_fields(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200004", role="admin")
    dt = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "שמירה-ה", "score_per_day": "1.00", "is_external": False},
    ).json()
    r = client.patch(
        f"/api/duty-config/duty-types/{dt['id']}",
        headers=auth_headers(admin),
        json={"contact_name": "דני לוי", "is_external": True},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["contact_name"] == "דני לוי"
    assert data["is_external"] is True
