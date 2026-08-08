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


def test_bulk_delete_notifies_remaining_soldiers_when_one_notification_fails(client, admin_session, monkeypatch):
    """A notification failure for one assignment in a bulk-delete batch must
    not prevent the other assignments' notifications from being sent — only
    the failing item should be skipped, not everything after it, and the
    delete itself (already committed) must not be rolled back."""
    from app.db.models import Notification, NotificationType
    import app.routes.shifts as shifts_module

    dm, dt, loc = _setup(admin_session, "sh_rt_008")
    soldier_bad = create_soldier(admin_session, personal_number="sh_rt_008a", hierarchy_node_id=dm.hierarchy_node_id)
    soldier_good = create_soldier(admin_session, personal_number="sh_rt_008b", hierarchy_node_id=dm.hierarchy_node_id)
    admin_session.commit()

    shift1_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2027-01-01",
        "end_date": "2027-01-02",
        "required_count": 1,
    }, headers=auth_headers(dm))
    shift2_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2027-01-05",
        "end_date": "2027-01-06",
        "required_count": 1,
    }, headers=auth_headers(dm))
    shift1_id = shift1_resp.json()["id"]
    shift2_id = shift2_resp.json()["id"]

    assert client.post(f"/api/shifts/{shift1_id}/assign-batch", json={
        "primaries": [str(soldier_bad.id)], "reserves": [],
    }, headers=auth_headers(dm)).status_code == 201
    assert client.post(f"/api/shifts/{shift2_id}/assign-batch", json={
        "primaries": [str(soldier_good.id)], "reserves": [],
    }, headers=auth_headers(dm)).status_code == 201

    real_create_notification = shifts_module.create_notification

    def _flaky(*args, **kwargs):
        if kwargs.get("soldier_id") == soldier_bad.id:
            raise RuntimeError("simulated notification failure for one assignment")
        return real_create_notification(*args, **kwargs)

    monkeypatch.setattr(shifts_module, "create_notification", _flaky)

    resp = client.delete(
        "/api/shifts/bulk-delete",
        params={"date_from": "2027-01-01", "date_to": "2027-01-31"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted_assignments"] == 2

    admin_session.expire_all()
    notif_bad = admin_session.query(Notification).filter_by(
        soldier_id=soldier_bad.id, type=NotificationType.assignment_removed,
    ).one_or_none()
    assert notif_bad is None

    notif_good = admin_session.query(Notification).filter_by(
        soldier_id=soldier_good.id, type=NotificationType.assignment_removed,
    ).one_or_none()
    assert notif_good is not None


def test_bulk_clear_notifies_remaining_soldiers_when_one_notification_fails(client, admin_session, monkeypatch):
    """Same per-item isolation guarantee as bulk-delete, but for
    bulk-clear-assignments (which keeps the shifts, only clears assignments)."""
    from app.db.models import Notification, NotificationType
    import app.routes.shifts as shifts_module

    dm, dt, loc = _setup(admin_session, "sh_rt_009")
    soldier_bad = create_soldier(admin_session, personal_number="sh_rt_009a", hierarchy_node_id=dm.hierarchy_node_id)
    soldier_good = create_soldier(admin_session, personal_number="sh_rt_009b", hierarchy_node_id=dm.hierarchy_node_id)
    admin_session.commit()

    shift1_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2027-02-01",
        "end_date": "2027-02-02",
        "required_count": 1,
    }, headers=auth_headers(dm))
    shift2_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2027-02-05",
        "end_date": "2027-02-06",
        "required_count": 1,
    }, headers=auth_headers(dm))
    shift1_id = shift1_resp.json()["id"]
    shift2_id = shift2_resp.json()["id"]

    assert client.post(f"/api/shifts/{shift1_id}/assign-batch", json={
        "primaries": [str(soldier_bad.id)], "reserves": [],
    }, headers=auth_headers(dm)).status_code == 201
    assert client.post(f"/api/shifts/{shift2_id}/assign-batch", json={
        "primaries": [str(soldier_good.id)], "reserves": [],
    }, headers=auth_headers(dm)).status_code == 201

    real_create_notification = shifts_module.create_notification

    def _flaky(*args, **kwargs):
        if kwargs.get("soldier_id") == soldier_bad.id:
            raise RuntimeError("simulated notification failure for one assignment")
        return real_create_notification(*args, **kwargs)

    monkeypatch.setattr(shifts_module, "create_notification", _flaky)

    resp = client.delete(
        "/api/shifts/bulk-clear-assignments",
        params={"date_from": "2027-02-01", "date_to": "2027-02-28"},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["cleared_assignments"] == 2

    admin_session.expire_all()
    notif_bad = admin_session.query(Notification).filter_by(
        soldier_id=soldier_bad.id, type=NotificationType.assignment_removed,
    ).one_or_none()
    assert notif_bad is None

    notif_good = admin_session.query(Notification).filter_by(
        soldier_id=soldier_good.id, type=NotificationType.assignment_removed,
    ).one_or_none()
    assert notif_good is not None


def test_clear_shift_assignments_audit_captures_real_prior_status(client, admin_session):
    """The audit row for each cancelled assignment must record the
    assignment's actual prior status, not a hardcoded 'published' value."""
    from app.db.models import AuditLog, DutyAssignment

    dm, dt, loc = _setup(admin_session, "sh_rt_010")
    soldier = create_soldier(admin_session, personal_number="sh_rt_010s", hierarchy_node_id=dm.hierarchy_node_id)
    admin_session.commit()

    create_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2027-03-01",
        "end_date": "2027-03-02",
        "required_count": 1,
    }, headers=auth_headers(dm))
    shift_id = create_resp.json()["id"]
    assign_resp = client.post(f"/api/shifts/{shift_id}/assign-batch", json={
        "primaries": [str(soldier.id)], "reserves": [],
    }, headers=auth_headers(dm))
    assert assign_resp.status_code == 201, assign_resp.text
    assignment_id = assign_resp.json()["primary_assignment_ids"][0]

    # Force the assignment into a non-"published" status before clearing, to
    # prove the audit "before" value reflects reality rather than a hardcoded
    # "published" default.
    assignment = admin_session.get(DutyAssignment, uuid.UUID(assignment_id))
    assignment.status = "algorithm_draft"
    admin_session.commit()

    resp = client.delete(f"/api/shifts/{shift_id}/assignments", headers=auth_headers(dm))
    assert resp.status_code == 204

    admin_session.expire_all()
    audit_row = admin_session.query(AuditLog).filter_by(
        action="assignment.cancel", entity_id=uuid.UUID(assignment_id),
    ).order_by(AuditLog.created_at.desc()).first()
    assert audit_row is not None
    assert audit_row.before == {"status": "algorithm_draft"}


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


def test_assign_batch_rejects_primaries_beyond_required_count(client, admin_session):
    dm, dt, loc = _setup(admin_session, "sh_rt_007")
    first = create_soldier(admin_session, personal_number="sh_rt_007a", hierarchy_node_id=dm.hierarchy_node_id)
    second = create_soldier(admin_session, personal_number="sh_rt_007b", hierarchy_node_id=dm.hierarchy_node_id)
    admin_session.commit()
    create_resp = client.post("/api/shifts", json={
        "duty_type_id": str(dt.id),
        "duty_location_id": str(loc.id),
        "start_date": "2026-12-01",
        "end_date": "2026-12-02",
        "required_count": 1,
    }, headers=auth_headers(dm))
    shift_id = create_resp.json()["id"]
    ok_resp = client.post(f"/api/shifts/{shift_id}/assign-batch", json={
        "primaries": [str(first.id)],
        "reserves": [],
    }, headers=auth_headers(dm))
    assert ok_resp.status_code == 201, ok_resp.text

    over_resp = client.post(f"/api/shifts/{shift_id}/assign-batch", json={
        "primaries": [str(second.id)],
        "reserves": [],
    }, headers=auth_headers(dm))
    assert over_resp.status_code == 409
    assert over_resp.json()["detail"] == "primary_capacity_exceeded"


def test_list_shifts_includes_ineligible_count(client, admin_session):
    from datetime import date, timedelta

    from app.db.models import DutyAssignment, DutyShift, RangeType

    node = create_node(admin_session, level="branch", name="so-node-1")
    dm = create_soldier(admin_session, personal_number="so-dm-1", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="so-sol-1", hierarchy_node_id=node.id)
    dt = DutyType(
        name="so-weapon-1", score_per_day=Decimal("1.00"),
        requires_weapon=True, required_range_type=RangeType.laser, eligible_node_ids=[node.id],
    )
    loc = DutyLocation(name="so-loc-1")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        required_count=1, status="active",
    )
    admin_session.add(shift)
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=5),
        status="published", weapon_ineligible=True,
    )
    admin_session.add(assignment)
    admin_session.commit()

    r = client.get(
        f"/api/shifts?date_from={date.today().isoformat()}&date_to={(date.today()+timedelta(days=30)).isoformat()}",
        headers=auth_headers(dm),
    )
    assert r.status_code == 200
    row = next(s for s in r.json() if s["id"] == str(shift.id))
    assert row["ineligible_count"] == 1
