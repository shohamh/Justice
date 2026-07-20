from __future__ import annotations

import uuid
from decimal import Decimal

from app.db.models import DutyLocation, DutyType
from tests.helpers import auth_headers, create_node, create_soldier


def _setup(session, pn: str):
    node = create_node(session, level="branch", name=f"n_{pn}")
    dm = create_soldier(session, personal_number=pn, role="duty_manager", hierarchy_node_id=node.id)
    dt = DutyType(name=f"t_{pn}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"l_{pn}")
    session.add(dt); session.add(loc)
    session.commit()
    return dm, dt, loc


def test_create_shift_returns_201(client, admin_session):
    dm, dt, loc = _setup(admin_session, "sh_rt_001")
    resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-07-01",
        "end_date": "2026-07-03",
        "required_count": 2,
    }, headers=auth_headers(dm))
    assert resp.status_code == 201
    data = resp.json()
    assert data["required_count"] == 2
    assert data["fill_status"] == "empty"
    assert data["assigned_count"] == 0


def test_soldier_cannot_create_shift(client, admin_session):
    _, dt, loc = _setup(admin_session, "sh_rt_002")
    soldier = create_soldier(admin_session, personal_number="sh_rt_002s")
    admin_session.commit()
    resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-07-01",
        "end_date": "2026-07-01",
    }, headers=auth_headers(soldier))
    assert resp.status_code == 403


def test_list_shifts_with_fill(client, admin_session):
    dm, dt, loc = _setup(admin_session, "sh_rt_003")
    client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-08-01",
        "end_date": "2026-08-02",
        "required_count": 3,
    }, headers=auth_headers(dm))
    resp = client.get("/api/shifts?date_from=2026-08-01&date_to=2026-08-31", headers=auth_headers(dm))
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1
    assert all("fill_status" in i for i in items)


def test_delete_empty_shift(client, admin_session):
    dm, dt, loc = _setup(admin_session, "sh_rt_004")
    create_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-09-01",
        "end_date": "2026-09-02",
    }, headers=auth_headers(dm))
    shift_id = create_resp.json()["id"]
    del_resp = client.delete(f"/api/shifts/{shift_id}", headers=auth_headers(dm))
    assert del_resp.status_code == 204


def test_remove_shift_assignment_notifies_soldier(client, admin_session):
    from app.db.models import Notification, NotificationType

    dm, dt, loc = _setup(admin_session, "sh_rt_006")
    soldier = create_soldier(admin_session, personal_number="sh_rt_006s", hierarchy_node_id=dm.hierarchy_node_id)
    admin_session.commit()
    create_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-11-01",
        "end_date": "2026-11-02",
        "required_count": 1,
    }, headers=auth_headers(dm))
    shift_id = create_resp.json()["id"]
    assign_resp = client.post(f"/api/shifts/{shift_id}/assign-batch", json={
        "primaries": [str(soldier.id)],
        "reserves": [],
    }, headers=auth_headers(dm))
    assert assign_resp.status_code == 201, assign_resp.text
    assignment_id = assign_resp.json()["primary_assignment_ids"][0]

    resp = client.delete(f"/api/shifts/{shift_id}/assignments/{assignment_id}", headers=auth_headers(dm))
    assert resp.status_code == 204

    notif = admin_session.query(Notification).filter_by(
        soldier_id=soldier.id, type=NotificationType.assignment_removed,
    ).one_or_none()
    assert notif is not None


def test_bulk_delete_shifts_notifies_all_affected_soldiers(client, admin_session):
    from app.db.models import Notification, NotificationType

    dm, dt, loc = _setup(admin_session, "sh_rt_007")
    soldier1 = create_soldier(admin_session, personal_number="sh_rt_007a", hierarchy_node_id=dm.hierarchy_node_id)
    soldier2 = create_soldier(admin_session, personal_number="sh_rt_007b", hierarchy_node_id=dm.hierarchy_node_id)
    admin_session.commit()

    shift1_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-12-01",
        "end_date": "2026-12-02",
        "required_count": 1,
    }, headers=auth_headers(dm))
    shift2_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-12-05",
        "end_date": "2026-12-06",
        "required_count": 1,
    }, headers=auth_headers(dm))
    shift1_id = shift1_resp.json()["id"]
    shift2_id = shift2_resp.json()["id"]

    assert client.post(f"/api/shifts/{shift1_id}/assign-batch", json={
        "primaries": [str(soldier1.id)], "reserves": [],
    }, headers=auth_headers(dm)).status_code == 201
    assert client.post(f"/api/shifts/{shift2_id}/assign-batch", json={
        "primaries": [str(soldier2.id)], "reserves": [],
    }, headers=auth_headers(dm)).status_code == 201

    resp = client.delete(
        "/api/shifts/bulk-delete",
        params={"date_from": "2026-12-01", "date_to": "2026-12-31"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted_assignments"] == 2

    for soldier_id in (soldier1.id, soldier2.id):
        notif = admin_session.query(Notification).filter_by(
            soldier_id=soldier_id, type=NotificationType.assignment_removed,
        ).one_or_none()
        assert notif is not None


def test_update_shift(client, admin_session):
    dm, dt, loc = _setup(admin_session, "sh_rt_005")
    create_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-10-01",
        "end_date": "2026-10-02",
        "required_count": 1,
    }, headers=auth_headers(dm))
    shift_id = create_resp.json()["id"]
    patch_resp = client.patch(f"/api/shifts/{shift_id}", json={"required_count": 4, "notes": "test"}, headers=auth_headers(dm))
    assert patch_resp.status_code == 200
    assert patch_resp.json()["required_count"] == 4
    assert patch_resp.json()["notes"] == "test"
