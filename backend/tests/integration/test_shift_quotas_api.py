from __future__ import annotations

from decimal import Decimal

from app.db.models import DutyLocation, DutyType
from tests.helpers import auth_headers, create_node, create_soldier


def _setup(session, pn: str):
    node = create_node(session, level="branch", name=f"n_{pn}")
    dm = create_soldier(session, personal_number=pn, role="duty_manager", hierarchy_node_id=node.id)
    dt = DutyType(name=f"t_{pn}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"l_{pn}")
    session.add(dt)
    session.add(loc)
    session.commit()
    return dm, dt, loc, node


def _create_shift(client, dm, dt, loc, required_count=3, pn="x"):
    resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-07-01",
        "end_date": "2026-07-02",
        "required_count": required_count,
    }, headers=auth_headers(dm))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_put_quotas_valid_returns_200_with_node_name(client, admin_session):
    dm, dt, loc, node = _setup(admin_session, "sq_001")
    shift_id = _create_shift(client, dm, dt, loc, required_count=3, pn="sq_001")

    resp = client.put(f"/api/shifts/{shift_id}/quotas", json={
        "quotas": [{"hierarchy_node_id": str(node.id), "count": 2}],
    }, headers=auth_headers(dm))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["quotas"] == [{
        "hierarchy_node_id": str(node.id),
        "node_name": node.name,
        "count": 2,
    }]


def test_put_quotas_exceeding_required_count_returns_400(admin_session, client):
    dm, dt, loc, node = _setup(admin_session, "sq_002")
    shift_id = _create_shift(client, dm, dt, loc, required_count=2, pn="sq_002")

    resp = client.put(f"/api/shifts/{shift_id}/quotas", json={
        "quotas": [{"hierarchy_node_id": str(node.id), "count": 5}],
    }, headers=auth_headers(dm))
    assert resp.status_code == 400


def test_get_shift_includes_node_quotas(client, admin_session):
    dm, dt, loc, node = _setup(admin_session, "sq_003")
    shift_id = _create_shift(client, dm, dt, loc, required_count=4, pn="sq_003")

    put_resp = client.put(f"/api/shifts/{shift_id}/quotas", json={
        "quotas": [{"hierarchy_node_id": str(node.id), "count": 1}],
    }, headers=auth_headers(dm))
    assert put_resp.status_code == 200, put_resp.text

    get_resp = client.get(f"/api/shifts/{shift_id}", headers=auth_headers(dm))
    assert get_resp.status_code == 200, get_resp.text
    data = get_resp.json()
    assert data["node_quotas"] == [{
        "hierarchy_node_id": str(node.id),
        "node_name": node.name,
        "count": 1,
    }]
