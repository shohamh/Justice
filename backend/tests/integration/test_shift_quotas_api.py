from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.db.models import DutyLocation, DutyType
from app.services.shifts import create_shift
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


def test_quota_split_preview_returns_entries_summing_to_required_count(client, admin_session):
    dm, dt, loc, parent = _setup(admin_session, "sp_001")
    child_a = create_node(admin_session, level="branch", name="sp_001_a", parent=parent)
    child_b = create_node(admin_session, level="branch", name="sp_001_b", parent=parent)
    create_soldier(admin_session, personal_number="sp_001_s1", hierarchy_node_id=child_a.id)
    create_soldier(admin_session, personal_number="sp_001_s2", hierarchy_node_id=child_b.id)
    admin_session.commit()

    resp = client.get(
        "/api/shifts/quota-split-preview",
        params={"parent_node_id": str(parent.id), "required_count": 5},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200, resp.text
    entries = resp.json()["entries"]
    assert sum(e["count"] for e in entries) == 5
    assert {e["node_name"] for e in entries} == {"sp_001_a", "sp_001_b"}


def test_quota_split_preview_unknown_parent_returns_404(client, admin_session):
    dm, dt, loc, _parent = _setup(admin_session, "sp_002")

    resp = client.get(
        "/api/shifts/quota-split-preview",
        params={"parent_node_id": "00000000-0000-0000-0000-000000000000", "required_count": 3},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 404


def test_quota_split_preview_no_children_returns_400(client, admin_session):
    dm, dt, loc, leaf = _setup(admin_session, "sp_003")

    resp = client.get(
        "/api/shifts/quota-split-preview",
        params={"parent_node_id": str(leaf.id), "required_count": 3},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 400


def test_quota_split_preview_forbidden_for_plain_soldier(client, admin_session):
    dm, dt, loc, parent = _setup(admin_session, "sp_004")
    create_node(admin_session, level="branch", name="sp_004_a", parent=parent)
    plain = create_soldier(admin_session, personal_number="sp_004_plain", role="soldier")
    admin_session.commit()

    resp = client.get(
        "/api/shifts/quota-split-preview",
        params={"parent_node_id": str(parent.id), "required_count": 3},
        headers=auth_headers(plain),
    )
    assert resp.status_code == 403


def test_two_level_split_preview_endpoint(client, admin_session):
    dm, dt, loc, unit = _setup(admin_session, "tl_001")
    child = create_node(admin_session, level="branch", name="tl_001_child", parent=unit)
    create_soldier(admin_session, personal_number="tl_001_s1", hierarchy_node_id=child.id)
    admin_session.commit()

    shift = create_shift(
        admin_session,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        required_count=3,
        eligible_node_ids=[unit.id],
    )
    admin_session.commit()

    resp = client.get(f"/api/shifts/{shift.id}/quota-split-preview-two-level", headers=auth_headers(dm))
    assert resp.status_code == 200, resp.text
    entries = resp.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["node_name"] == "tl_001_child"
    assert entries[0]["count"] == 3
    assert entries[0]["parent_responsible_node_id"] == str(unit.id)


def test_two_level_split_preview_requires_eligible_node_ids(client, admin_session):
    dm, dt, loc, _unit = _setup(admin_session, "tl_002")

    shift = create_shift(
        admin_session,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        required_count=3,
    )
    admin_session.commit()

    resp = client.get(f"/api/shifts/{shift.id}/quota-split-preview-two-level", headers=auth_headers(dm))
    assert resp.status_code == 400


def test_auto_assign_responsibility_preview_endpoint(client, admin_session):
    dm, dt, loc, parent = _setup(admin_session, "resp_api")
    strong = create_node(admin_session, level="branch", name="resp_api_strong", parent=parent)
    create_node(admin_session, level="branch", name="resp_api_weak", parent=parent)
    for i in range(4):
        create_soldier(admin_session, personal_number=f"resp_api_{i}", hierarchy_node_id=strong.id)
    admin_session.commit()

    shift = create_shift(
        admin_session,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 2),
        required_count=2,
        eligible_node_ids=[parent.id],
    )
    admin_session.commit()

    resp = client.post(
        "/api/shifts/auto-assign-responsibility/preview",
        json={"shift_ids": [str(shift.id)]},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200, resp.text
    assignments = resp.json()["assignments"]
    assert len(assignments) == 1
    assert assignments[0]["shift_id"] == str(shift.id)
    assert assignments[0]["node_name"] == "resp_api_strong"
