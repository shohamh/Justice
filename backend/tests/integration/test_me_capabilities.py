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


def test_me_reports_enrollment_pending(client, admin_session):
    from app.db.models import SoldierEnrollmentRequest
    from tests.helpers import create_node, create_soldier, auth_headers

    node = create_node(admin_session, level="unit", name="me_enrollment_pending_unit")
    s = create_soldier(admin_session, personal_number="7600020", hierarchy_node_id=node.id)
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id, status="pending"))
    admin_session.commit()

    r = client.get("/api/me", headers=auth_headers(s))
    assert r.status_code == 200
    assert r.json()["enrollment_pending"] is True


def test_me_reports_not_pending_when_no_enrollment_request(client, admin_session):
    from tests.helpers import create_soldier, auth_headers

    s = create_soldier(admin_session, personal_number="7600021")
    r = client.get("/api/me", headers=auth_headers(s))
    assert r.status_code == 200
    assert r.json()["enrollment_pending"] is False


def test_me_defaults_theme_preference_to_system(client, admin_session):
    from tests.helpers import create_soldier, auth_headers

    s = create_soldier(admin_session, personal_number="7600022")
    r = client.get("/api/me", headers=auth_headers(s))
    assert r.status_code == 200
    assert r.json()["theme_preference"] == "system"


def test_me_includes_can_view_transparency(client, admin_session):
    from tests.helpers import create_soldier, auth_headers

    s = create_soldier(admin_session, personal_number="7600023")
    r = client.get("/api/me", headers=auth_headers(s))
    assert r.status_code == 200
    assert r.json()["can_view_transparency"] is False


def test_me_includes_alal_relevant_flag(client, admin_session) -> None:
    from app.db.models import DutyType, RangeType

    node = create_node(admin_session, level="team", name="me-alal-team")
    soldier = create_soldier(admin_session, personal_number="me-alal-001", hierarchy_node_id=node.id)
    admin_session.add(DutyType(
        name="me-alal-duty", score_per_day=1, requires_weapon=True,
        required_range_type=RangeType.alal, eligible_node_ids=[node.id],
    ))
    admin_session.commit()

    response = client.get("/api/me", headers=auth_headers(soldier))

    assert response.status_code == 200, response.text
    assert response.json()["alal_relevant"] is True
