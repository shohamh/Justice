from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_soldier


def test_admin_creates_and_lists_duty_type(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5100001", role="admin")
    r = client.post("/api/duty-config/duty-types", headers=auth_headers(admin),
                    json={"name": "שמירה-א", "score_per_day": "1.50"})
    assert r.status_code == 201, r.text
    dt_id = r.json()["id"]
    r2 = client.get("/api/duty-config/duty-types", headers=auth_headers(admin))
    assert r2.status_code == 200
    assert any(d["id"] == dt_id for d in r2.json())


def test_duty_manager_allowed(client: TestClient, admin_session: Session):
    dm = create_soldier(admin_session, personal_number="5100002", role="duty_manager")
    r = client.post("/api/duty-config/duty-types", headers=auth_headers(dm),
                    json={"name": "ניקיון-א", "score_per_day": "1.00"})
    assert r.status_code == 201


def test_plain_soldier_forbidden(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5100003", role="soldier")
    r = client.post("/api/duty-config/duty-types", headers=auth_headers(s),
                    json={"name": "x", "score_per_day": "1.00"})
    assert r.status_code == 403


def test_commander_forbidden(client: TestClient, admin_session: Session):
    c = create_soldier(admin_session, personal_number="5100004", role="commander")
    r = client.get("/api/duty-config/duty-types", headers=auth_headers(c))
    assert r.status_code == 403


def test_commander_can_list_exemption_types(client: TestClient, admin_session: Session):
    # Reference data is readable by any authenticated user (needed to fill the grant form).
    c = create_soldier(admin_session, personal_number="5100041", role="commander")
    assert client.get("/api/duty-config/exemption-types", headers=auth_headers(c)).status_code == 200


def test_duplicate_name_rejected(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5100005", role="admin")
    client.post("/api/duty-config/duty-types", headers=auth_headers(admin),
                json={"name": "כפול-א", "score_per_day": "1.00"})
    r = client.post("/api/duty-config/duty-types", headers=auth_headers(admin),
                    json={"name": "כפול-א", "score_per_day": "2.00"})
    assert r.status_code == 400
    assert r.json()["detail"] == "name_taken"


def test_set_exemption_duty_types(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5100006", role="admin")
    et = client.post("/api/duty-config/exemption-types", headers=auth_headers(admin),
                     json={"name": "פטור-א"}).json()
    dt = client.post("/api/duty-config/duty-types", headers=auth_headers(admin),
                     json={"name": "מטבח-א", "score_per_day": "1.00"}).json()
    r = client.put(f"/api/duty-config/exemption-types/{et['id']}/duty-types",
                   headers=auth_headers(admin), json={"duty_type_ids": [dt["id"]]})
    assert r.status_code == 200
    r2 = client.get(f"/api/duty-config/exemption-types/{et['id']}/duty-types", headers=auth_headers(admin))
    assert r2.json() == [dt["id"]]
