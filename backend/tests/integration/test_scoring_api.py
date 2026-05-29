from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyLocation, DutyType
from tests.helpers import auth_headers, create_soldier


def test_transparency_open_to_any_authed_user(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5600001", role="soldier")
    r = client.get("/api/scoring/transparency", headers=auth_headers(s))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_transparency_reflects_assignment(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5600002", role="admin")
    s = create_soldier(admin_session, personal_number="5600003", role="soldier")
    dt = DutyType(name="שמירה-sca", score_per_day=Decimal("2.00"))
    loc = DutyLocation(name="מוצב-sca")
    admin_session.add_all([dt, loc])
    admin_session.commit()
    client.post(
        "/api/assignments",
        headers=auth_headers(admin),
        json={
            "soldier_id": str(s.id),
            "duty_type_id": str(dt.id),
            "duty_location_id": str(loc.id),
            "start_date": "2026-10-01",
            "end_date": "2026-10-02",
        },
    )
    r = client.get("/api/scoring/transparency", headers=auth_headers(admin))
    row = next(x for x in r.json() if x["soldier_id"] == str(s.id))
    assert Decimal(row["cumulative_score"]) == Decimal("4.00")


def test_soldier_can_read_own_breakdown(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5600004", role="soldier")
    r = client.get(f"/api/scoring/soldiers/{s.id}", headers=auth_headers(s))
    assert r.status_code == 200
    assert "per_type" in r.json()


def test_soldier_cannot_read_other_breakdown(client: TestClient, admin_session: Session):
    a = create_soldier(admin_session, personal_number="5600005", role="soldier")
    b = create_soldier(admin_session, personal_number="5600006", role="soldier")
    r = client.get(f"/api/scoring/soldiers/{b.id}", headers=auth_headers(a))
    assert r.status_code == 403
