from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import DutyManagerScope, DutyType, Soldier
from app.services.settings_loader import apply_settings
from tests.helpers import auth_headers, create_node, create_range_location, create_soldier


def _enable_mitvachim(session: Session) -> None:
    apply_settings(session, {}, {"mitvachim.enabled": True}, actor_id=None)
    session.commit()


def _scoped_dm(session: Session, *, node, personal_number: str) -> Soldier:
    dm = create_soldier(session, personal_number=personal_number, role="duty_manager", hierarchy_node_id=None)
    session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=node.id))
    session.commit()
    return dm


def test_clear_assignments_endpoint_via_http(client: TestClient, admin_session: Session) -> None:
    _enable_mitvachim(admin_session)
    node = create_node(admin_session, level="branch", name="api-clear-scratch")
    dm = _scoped_dm(admin_session, node=node, personal_number="api-clear-scratch-dm")
    s1 = create_soldier(admin_session, personal_number="api-clear-scratch-1", hierarchy_node_id=node.id)
    s2 = create_soldier(admin_session, personal_number="api-clear-scratch-2", hierarchy_node_id=node.id)
    admin_session.add(DutyType(name="api-clear-scratch weapon", score_per_day=Decimal("1.00"), requires_weapon=True, eligible_node_ids=[node.id]))
    loc = create_range_location(admin_session, name="api-clear-scratch loc")
    admin_session.commit()

    create = client.post(
        "/api/ranges",
        json={
            "hierarchy_node_id": str(node.id), "range_type": "laser",
            "date": (date.today() + timedelta(days=5)).isoformat(),
            "range_location_id": str(loc.id), "required_count": 2,
        },
        headers=auth_headers(dm),
    )
    assert create.status_code == 201, create.text
    event_id = create.json()["id"]

    batch = client.post(
        f"/api/ranges/{event_id}/assignments/batch",
        json={"primaries": [str(s1.id), str(s2.id)], "reserves": []},
        headers=auth_headers(dm),
    )
    assert batch.status_code == 200, batch.text

    clear = client.request(
        "DELETE", f"/api/ranges/{event_id}/assignments",
        json={"reason": "test cleanup"}, headers=auth_headers(dm),
    )
    assert clear.status_code == 200, clear.text
    assert clear.json() == {"cleared_assignments": 2}

    get = client.get(f"/api/ranges/{event_id}", headers=auth_headers(dm))
    assert get.json()["assignments"] == []
