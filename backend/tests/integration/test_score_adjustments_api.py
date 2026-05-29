from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_soldier


def test_admin_creates_and_lists(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5500001", role="admin")
    s = create_soldier(admin_session, personal_number="5500002", role="soldier")
    r = client.post("/api/score-adjustments", headers=auth_headers(admin),
                    json={"soldier_id": str(s.id), "delta": "-2.50", "reason": "תיקון"})
    assert r.status_code == 201, r.text
    r2 = client.get(f"/api/score-adjustments?soldier_id={s.id}", headers=auth_headers(admin))
    assert r2.status_code == 200
    assert r2.json()[0]["delta"] == "-2.50"


def test_zero_delta_rejected(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5500003", role="admin")
    s = create_soldier(admin_session, personal_number="5500004", role="soldier")
    r = client.post("/api/score-adjustments", headers=auth_headers(admin),
                    json={"soldier_id": str(s.id), "delta": "0", "reason": "x"})
    assert r.status_code == 400
    assert r.json()["detail"] == "zero_delta"


def test_plain_soldier_forbidden(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5500005", role="soldier")
    r = client.post("/api/score-adjustments", headers=auth_headers(s),
                    json={"soldier_id": str(s.id), "delta": "1", "reason": "x"})
    assert r.status_code == 403
