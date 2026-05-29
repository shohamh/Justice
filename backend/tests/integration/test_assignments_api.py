from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyLocation, DutyType
from tests.helpers import auth_headers, create_soldier


def _dt_loc(session: Session, tag: str):
    dt = DutyType(name=f"שמירה-{tag}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"מוצב-{tag}")
    session.add_all([dt, loc])
    session.commit()
    return dt, loc


def test_admin_creates_and_lists(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5400001", role="admin")
    target = create_soldier(admin_session, personal_number="5400002", role="soldier")
    dt, loc = _dt_loc(admin_session, "api1")
    r = client.post(
        "/api/assignments",
        headers=auth_headers(admin),
        json={
            "soldier_id": str(target.id),
            "duty_type_id": str(dt.id),
            "duty_location_id": str(loc.id),
            "start_date": "2026-10-01",
            "end_date": "2026-10-03",
        },
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    r2 = client.get(f"/api/assignments?soldier_id={target.id}", headers=auth_headers(admin))
    assert r2.status_code == 200
    assert any(a["id"] == aid for a in r2.json())


def test_overlap_returns_409(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5400003", role="admin")
    target = create_soldier(admin_session, personal_number="5400004", role="soldier")
    dt, loc = _dt_loc(admin_session, "api2")
    body = {
        "soldier_id": str(target.id),
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-10-01",
        "end_date": "2026-10-05",
    }
    assert (
        client.post("/api/assignments", headers=auth_headers(admin), json=body).status_code == 201
    )
    r = client.post(
        "/api/assignments", headers=auth_headers(admin), json={**body, "start_date": "2026-10-04"}
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "overlap"


def test_plain_soldier_forbidden_to_create(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="5400005", role="soldier")
    dt, loc = _dt_loc(admin_session, "api3")
    r = client.post(
        "/api/assignments",
        headers=auth_headers(s),
        json={
            "soldier_id": str(s.id),
            "duty_type_id": str(dt.id),
            "duty_location_id": str(loc.id),
            "start_date": "2026-10-01",
            "end_date": "2026-10-02",
        },
    )
    assert r.status_code == 403


def test_soldier_can_list_own(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5400006", role="admin")
    s = create_soldier(admin_session, personal_number="5400007", role="soldier")
    dt, loc = _dt_loc(admin_session, "api4")
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
    r = client.get(f"/api/assignments?soldier_id={s.id}", headers=auth_headers(s))
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_cancel_and_override(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5400008", role="admin")
    s = create_soldier(admin_session, personal_number="5400009", role="soldier")
    repl = create_soldier(admin_session, personal_number="5400010", role="soldier")
    dt, loc = _dt_loc(admin_session, "api5")
    aid = client.post(
        "/api/assignments",
        headers=auth_headers(admin),
        json={
            "soldier_id": str(s.id),
            "duty_type_id": str(dt.id),
            "duty_location_id": str(loc.id),
            "start_date": "2026-10-01",
            "end_date": "2026-10-03",
        },
    ).json()["id"]
    ro = client.put(
        f"/api/assignments/{aid}/overrides/2026-10-02",
        headers=auth_headers(admin),
        json={"effective_soldier_id": str(repl.id), "reason": "replacement"},
    )
    assert ro.status_code == 200, ro.text
    rc = client.post(
        f"/api/assignments/{aid}/cancel", headers=auth_headers(admin), json={"reason": "בוטל"}
    )
    assert rc.status_code == 200
    assert rc.json()["status"] == "cancelled"
