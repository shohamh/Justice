from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_me_exposes_dual_capabilities(client: TestClient, admin_session: Session):
    from app.db.models import DutyManagerScope

    a = create_node(admin_session, level="department", name="me-cap-a")
    b = create_node(admin_session, level="department", name="me-cap-b")
    dual = create_soldier(admin_session, personal_number="me-cap-001", role="commander")
    a.commander_id = dual.id
    admin_session.add(DutyManagerScope(duty_manager_id=dual.id, hierarchy_node_id=b.id))
    admin_session.commit()

    r = client.get("/api/me", headers=auth_headers(dual))
    assert r.status_code == 200
    body = r.json()
    assert body["is_commander"] is True
    assert body["is_duty_manager"] is True


def test_me_plain_soldier_has_no_capabilities(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="me-cap-002", role="soldier")
    r = client.get("/api/me", headers=auth_headers(s))
    assert r.status_code == 200
    body = r.json()
    assert body["is_commander"] is False
    assert body["is_duty_manager"] is False
