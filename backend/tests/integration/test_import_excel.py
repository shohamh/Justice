from __future__ import annotations

import io
import uuid
from decimal import Decimal

import openpyxl
import pytest

from app.db.models import DutyAssignment, DutyLocation, DutyType
from app.services.duty_config import create_duty_type
from tests.helpers import auth_headers, create_node, create_soldier


def make_xlsx_bytes(soldiers=None, assignments=None) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    if soldiers:
        ws = wb.create_sheet("soldiers")
        ws.append(["personal_number", "full_name", "rank"])
        for row in soldiers:
            ws.append(row)
    if assignments:
        ws = wb.create_sheet("assignments")
        ws.append(["personal_number", "duty_type_name", "start_date", "end_date", "is_reserve"])
        for row in assignments:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload(client, xlsx: bytes, token: str):
    return client.post(
        "/api/import/preview",
        files={"file": ("import.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_preview_new_soldier(client, admin_session):
    node = create_node(admin_session, level="branch", name="ie_node_001")
    dm = create_soldier(admin_session, personal_number="ie_dm_001", role="duty_manager", hierarchy_node_id=node.id)
    xlsx = make_xlsx_bytes(soldiers=[["ie_new_001", "ישראל ישראלי", "רב"]])
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]
    resp = _upload(client, xlsx, token)
    assert resp.status_code == 200
    soldiers = resp.json()["soldiers"]
    assert len(soldiers) == 1
    assert soldiers[0]["action"] == "new"
    assert soldiers[0]["personal_number"] == "ie_new_001"


def test_preview_duplicate_soldier_is_update(client, admin_session):
    node = create_node(admin_session, level="branch", name="ie_node_002")
    dm = create_soldier(admin_session, personal_number="ie_dm_002", role="duty_manager", hierarchy_node_id=node.id)
    existing = create_soldier(admin_session, personal_number="ie_existing_002", hierarchy_node_id=node.id)
    xlsx = make_xlsx_bytes(soldiers=[[existing.personal_number, "שם חדש", None]])
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]
    resp = _upload(client, xlsx, token)
    assert resp.json()["soldiers"][0]["action"] == "update"


def test_apply_creates_soldier(client, admin_session):
    node = create_node(admin_session, level="branch", name="ie_node_003")
    dm = create_soldier(admin_session, personal_number="ie_dm_003", role="duty_manager", hierarchy_node_id=node.id)
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]
    resp = client.post(
        "/api/import/apply",
        json={
            "soldiers": [{
                "row": 2, "action": "new",
                "personal_number": "ie_apply_003", "full_name": "טסט יחידה",
                "rank": None, "gender": None, "is_officer": None,
                "hierarchy_node_id": str(node.id), "enrolled_at": None,
                "enlistment_date": None, "phone": None, "email": None, "existing_id": None,
            }],
            "assignments": [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["created"] == 1
    assert resp.json()["errors"] == []


def test_apply_creates_soldier_with_password_hash_and_does_not_force_change(client, admin_session):
    """A new soldier row that supplies a password_hash already has a real,
    working password -- unlike the placeholder path for soldiers created
    without one, it must not be forced to change it."""
    node = create_node(admin_session, level="branch", name="ie_node_pw_new")
    dm = create_soldier(admin_session, personal_number="ie_dm_pw_new", role="duty_manager", hierarchy_node_id=node.id)
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]
    fake_hash = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$c29tZWhhc2g"

    resp = client.post(
        "/api/import/apply",
        json={
            "soldiers": [{
                "row": 2, "action": "new",
                "personal_number": "ie_apply_pw_new", "full_name": "טסט סיסמה",
                "rank": None, "gender": None, "is_officer": None,
                "hierarchy_node_id": str(node.id), "enrolled_at": None,
                "enlistment_date": None, "phone": None, "email": None, "existing_id": None,
                "password_hash": fake_hash,
            }],
            "assignments": [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["created"] == 1

    from app.db.models import Soldier
    created = admin_session.query(Soldier).filter_by(personal_number="ie_apply_pw_new").one()
    assert created.password_hash == fake_hash
    assert created.must_change_password is False


def test_apply_creates_soldier_without_password_hash_gets_placeholder_and_forced_change(client, admin_session):
    """A new soldier row with no password_hash at all falls back to the same
    random-placeholder-plus-forced-change pattern already used for soldiers
    created without a password by HR sync (person_sync._apply_new_person)."""
    node = create_node(admin_session, level="branch", name="ie_node_pw_none")
    dm = create_soldier(admin_session, personal_number="ie_dm_pw_none", role="duty_manager", hierarchy_node_id=node.id)
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]

    resp = client.post(
        "/api/import/apply",
        json={
            "soldiers": [{
                "row": 2, "action": "new",
                "personal_number": "ie_apply_pw_none", "full_name": "טסט בלי סיסמה",
                "rank": None, "gender": None, "is_officer": None,
                "hierarchy_node_id": str(node.id), "enrolled_at": None,
                "enlistment_date": None, "phone": None, "email": None, "existing_id": None,
            }],
            "assignments": [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["created"] == 1

    from app.db.models import Soldier
    created = admin_session.query(Soldier).filter_by(personal_number="ie_apply_pw_none").one()
    assert created.password_hash
    assert created.must_change_password is True


def test_apply_update_without_password_hash_does_not_wipe_existing_password(client, admin_session):
    """An update row that omits password_hash (e.g. an unrelated phone edit)
    must not wipe the soldier's real password back to a random placeholder,
    nor flip must_change_password."""
    node = create_node(admin_session, level="branch", name="ie_node_pw_update_blank")
    dm = create_soldier(admin_session, personal_number="ie_dm_pw_update_blank", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="ie_soldier_pw_update_blank", hierarchy_node_id=node.id)
    original_hash = soldier.password_hash
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]

    resp = client.post(
        "/api/import/apply",
        json={
            "soldiers": [{
                "row": 2, "action": "update",
                "personal_number": soldier.personal_number, "full_name": soldier.full_name,
                "rank": None, "gender": None, "is_officer": None,
                "hierarchy_node_id": None, "enrolled_at": None,
                "enlistment_date": None, "phone": "050-1112233", "email": None,
                "existing_id": str(soldier.id),
            }],
            "assignments": [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["errors"] == []

    admin_session.expire_all()
    updated = admin_session.get(type(soldier), soldier.id)
    assert updated.password_hash == original_hash
    assert updated.must_change_password is False
    assert updated.phone == "050-1112233"


def test_apply_update_with_password_hash_overwrites_existing_hash(client, admin_session):
    """An update row that DOES supply a password_hash must overwrite the
    existing soldier's hash, without itself forcing a password change."""
    node = create_node(admin_session, level="branch", name="ie_node_pw_update_set")
    dm = create_soldier(admin_session, personal_number="ie_dm_pw_update_set", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="ie_soldier_pw_update_set", hierarchy_node_id=node.id, must_change_password=True)
    new_hash = "$argon2id$v=19$m=65536,t=3,p=4$YW5vdGhlcnNhbHQ$YW5vdGhlcmhhc2g"
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]

    resp = client.post(
        "/api/import/apply",
        json={
            "soldiers": [{
                "row": 2, "action": "update",
                "personal_number": soldier.personal_number, "full_name": soldier.full_name,
                "rank": None, "gender": None, "is_officer": None,
                "hierarchy_node_id": None, "enrolled_at": None,
                "enlistment_date": None, "phone": None, "email": None,
                "existing_id": str(soldier.id),
                "password_hash": new_hash,
            }],
            "assignments": [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["errors"] == []

    admin_session.expire_all()
    updated = admin_session.get(type(soldier), soldier.id)
    assert updated.password_hash == new_hash
    assert updated.must_change_password is True


def test_export_reimport_roundtrip_via_apply_preserves_password_hash(client, admin_session):
    """Genuine export -> re-parse -> apply round trip: an existing soldier's
    real password_hash must survive unchanged, and must_change_password must
    not be flipped, even though the export/apply cycle passes through the
    row-preview parsing used by this route."""
    import app.services.import_parsers.v1_standard  # noqa: F401
    from app.services.import_parsers.registry import get_parser

    node = create_node(admin_session, level="branch", name="ie_node_pw_roundtrip")
    dm = create_soldier(admin_session, personal_number="ie_dm_pw_roundtrip", role="duty_manager", hierarchy_node_id=node.id)
    admin = create_soldier(admin_session, personal_number="ie_admin_pw_roundtrip", role="admin")
    soldier = create_soldier(admin_session, personal_number="ie_soldier_pw_roundtrip", hierarchy_node_id=node.id)
    original_hash = soldier.password_hash
    admin_session.commit()

    admin_token = auth_headers(admin)["Authorization"].split(" ", 1)[1]
    export_resp = client.get("/api/import/export?sheets=soldiers", headers={"Authorization": f"Bearer {admin_token}"})
    assert export_resp.status_code == 200

    wb = openpyxl.load_workbook(io.BytesIO(export_resp.content), data_only=True)
    parsed = get_parser("v1_standard").parse(wb)
    row = next(r for r in parsed.soldiers if r.personal_number == soldier.personal_number)
    assert row.password_hash == original_hash

    dm_token = auth_headers(dm)["Authorization"].split(" ", 1)[1]
    resp = client.post(
        "/api/import/apply",
        json={
            "soldiers": [{
                "row": row.source_row, "action": "update",
                "personal_number": row.personal_number, "full_name": row.full_name,
                "rank": None, "gender": None, "is_officer": None,
                "hierarchy_node_id": None, "enrolled_at": None,
                "enlistment_date": None, "phone": None, "email": None,
                "existing_id": str(soldier.id),
                "password_hash": row.password_hash,
            }],
            "assignments": [],
        },
        headers={"Authorization": f"Bearer {dm_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["errors"] == []

    admin_session.expire_all()
    updated = admin_session.get(type(soldier), soldier.id)
    assert updated.password_hash == original_hash
    assert updated.must_change_password is False


def test_apply_rejects_out_of_scope_hierarchy_node(client, admin_session):
    """A duty manager scoped to unit A must not be able to import a soldier
    into unit B via /import/apply."""
    node_a = create_node(admin_session, level="branch", name="ie_node_scope_a")
    node_b = create_node(admin_session, level="branch", name="ie_node_scope_b")
    dm = create_soldier(admin_session, personal_number="ie_dm_scope", role="duty_manager", hierarchy_node_id=node_a.id)
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]

    resp = client.post(
        "/api/import/apply",
        json={
            "soldiers": [{
                "row": 2, "action": "new",
                "personal_number": "ie_apply_scope", "full_name": "טסט חריגה",
                "rank": None, "gender": None, "is_officer": None,
                "hierarchy_node_id": str(node_b.id), "enrolled_at": None,
                "enlistment_date": None, "phone": None, "email": None, "existing_id": None,
            }],
            "assignments": [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert "out_of_scope_rows" in resp.json()["detail"]


def test_apply_notifies_soldier_of_new_assignment(client, admin_session):
    from app.db.models import Notification, NotificationType

    node = create_node(admin_session, level="branch", name="ie_node_notif")
    dm = create_soldier(admin_session, personal_number="ie_dm_notif", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="ie_soldier_notif", hierarchy_node_id=node.id)
    dt = create_duty_type(admin_session, name=f"dt_notif_{uuid.uuid4().hex[:8]}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_notif_{uuid.uuid4().hex[:8]}")
    admin_session.add(loc)
    admin_session.commit()
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]

    resp = client.post(
        "/api/import/apply",
        json={
            "soldiers": [],
            "assignments": [{
                "row": 2, "action": "new",
                "resolved_soldier_id": str(soldier.id),
                "resolved_duty_type_id": str(dt.id),
                "start_date": "2024-06-15", "end_date": "2024-06-16",
                "is_reserve": False,
            }],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["created"] == 1

    admin_session.expire_all()
    notif = admin_session.query(Notification).filter_by(
        soldier_id=soldier.id, type=NotificationType.assignment_created,
    ).one_or_none()
    assert notif is not None


def test_apply_succeeds_even_if_notification_fails(client, admin_session, monkeypatch):
    """If sending the post-import notification raises, the import's own side
    effects (soldiers/assignments/audit row) already committed successfully,
    so the endpoint must still return 200 with the correct counts rather than
    an unhandled 500."""
    import app.routes.import_excel as import_excel_module

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated notification failure")

    monkeypatch.setattr(import_excel_module, "create_notification", _boom)

    node = create_node(admin_session, level="branch", name="ie_node_notif_fail")
    dm = create_soldier(admin_session, personal_number="ie_dm_notif_fail", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="ie_soldier_notif_fail", hierarchy_node_id=node.id)
    dt = create_duty_type(admin_session, name=f"dt_notif_fail_{uuid.uuid4().hex[:8]}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_notif_fail_{uuid.uuid4().hex[:8]}")
    admin_session.add(loc)
    admin_session.commit()
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]

    resp = client.post(
        "/api/import/apply",
        json={
            "soldiers": [],
            "assignments": [{
                "row": 2, "action": "new",
                "resolved_soldier_id": str(soldier.id),
                "resolved_duty_type_id": str(dt.id),
                "start_date": "2024-06-15", "end_date": "2024-06-16",
                "is_reserve": False,
            }],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["created"] == 1

    # The assignment itself was durably committed despite the notification failure.
    from app.db.models import DutyAssignment
    admin_session.expire_all()
    assignment = admin_session.query(DutyAssignment).filter_by(soldier_id=soldier.id).one_or_none()
    assert assignment is not None


def test_apply_notifies_remaining_assignments_when_one_notification_fails(client, admin_session, monkeypatch):
    """A notification failure for one assignment in a multi-assignment batch
    must not prevent the other assignments' notifications from being sent —
    only the failing item should be skipped, not everything after it."""
    from app.db.models import Notification, NotificationType
    import app.routes.import_excel as import_excel_module

    node = create_node(admin_session, level="branch", name="ie_node_notif_partial")
    dm = create_soldier(admin_session, personal_number="ie_dm_notif_partial", role="duty_manager", hierarchy_node_id=node.id)
    soldier_bad = create_soldier(admin_session, personal_number="ie_soldier_notif_bad", hierarchy_node_id=node.id)
    soldier_good = create_soldier(admin_session, personal_number="ie_soldier_notif_good", hierarchy_node_id=node.id)
    dt = create_duty_type(admin_session, name=f"dt_notif_partial_{uuid.uuid4().hex[:8]}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_notif_partial_{uuid.uuid4().hex[:8]}")
    admin_session.add(loc)
    admin_session.commit()
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]

    real_create_notification = import_excel_module.create_notification

    def _flaky(*args, **kwargs):
        if kwargs.get("soldier_id") == soldier_bad.id:
            raise RuntimeError("simulated notification failure for one assignment")
        return real_create_notification(*args, **kwargs)

    monkeypatch.setattr(import_excel_module, "create_notification", _flaky)

    resp = client.post(
        "/api/import/apply",
        json={
            "soldiers": [],
            "assignments": [
                {
                    "row": 2, "action": "new",
                    "resolved_soldier_id": str(soldier_bad.id),
                    "resolved_duty_type_id": str(dt.id),
                    "start_date": "2024-06-15", "end_date": "2024-06-16",
                    "is_reserve": False,
                },
                {
                    "row": 3, "action": "new",
                    "resolved_soldier_id": str(soldier_good.id),
                    "resolved_duty_type_id": str(dt.id),
                    "start_date": "2024-06-15", "end_date": "2024-06-16",
                    "is_reserve": False,
                },
            ],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["created"] == 2
    assert resp.json()["errors"] == []

    admin_session.expire_all()
    notif_bad = admin_session.query(Notification).filter_by(
        soldier_id=soldier_bad.id, type=NotificationType.assignment_created,
    ).one_or_none()
    assert notif_bad is None

    # The second assignment's notification must still have been attempted
    # and succeeded, even though the first one raised.
    notif_good = admin_session.query(Notification).filter_by(
        soldier_id=soldier_good.id, type=NotificationType.assignment_created,
    ).one_or_none()
    assert notif_good is not None


def test_template_download(client, admin_session):
    node = create_node(admin_session, level="branch", name="ie_node_004")
    dm = create_soldier(admin_session, personal_number="ie_dm_004", role="duty_manager", hierarchy_node_id=node.id)
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]
    resp = client.get("/api/import/template", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert set(wb.sheetnames) == {
        "חיילים", "משמרות", "שיבוצים",
        "מיקומי תורנויות", "היררכיה", "סוגי תפקידים", "סוגי פטורים", "תבניות משמרות",
        "מיקומי מטווח", "ימי מטווח", "שיבוצי מטווח",
        "כשירויות מטווח", "בקשות היעדרות",
    }
    headers = [c.value for c in next(wb["שיבוצים"].iter_rows(min_row=1, max_row=1))]
    assert headers == [
        "מספר אישי", "שם מלא", "סוג תפקיד", "מיקום",
        "תאריך התחלה", "תאריך סיום", "שעת התחלה", "שעת סיום", "מילואים", "הערות",
    ]


def test_template_download_includes_shift_templates_sheet(client, admin_session):
    node = create_node(admin_session, level="branch", name="ie_node_005")
    dm = create_soldier(admin_session, personal_number="ie_dm_005", role="duty_manager", hierarchy_node_id=node.id)
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]
    resp = client.get("/api/import/template", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert "תבניות משמרות" in wb.sheetnames
    headers = [c.value for c in next(wb["תבניות משמרות"].iter_rows(min_row=1, max_row=1))]
    assert headers == [
        "שם", "סוג תפקיד", "מיקום", "מחזוריות", "ימים בשבוע",
        "שעת התחלה", "שעת סיום", "נדרשים", "חידוש אוטומטי", "חידוש אוטומטי עד",
        "משך בימים", "הערות", "יחידות מותרות",
    ]


def test_export_current_data_includes_shift_templates(client, admin_session):
    from app.services.shift_templates import create_template
    from app.db.models import DutyLocation

    dt = create_duty_type(admin_session, name=f"dt_export_{uuid.uuid4().hex[:8]}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_export_{uuid.uuid4().hex[:8]}")
    admin_session.add(loc)
    admin_session.flush()
    tpl_name = f"tpl_export_{uuid.uuid4().hex[:8]}"
    create_template(
        admin_session, name=tpl_name, duty_type_id=dt.id, duty_location_id=loc.id,
        recurrence_type="weekdays", weekdays=[], required_count=1,
    )
    admin_session.commit()

    admin = create_soldier(admin_session, personal_number=f"adm_export_{uuid.uuid4().hex[:8]}", role="admin")
    token = auth_headers(admin)["Authorization"].split(" ", 1)[1]
    resp = client.get("/api/import/export", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert "תבניות משמרות" in wb.sheetnames
    rows = list(wb["תבניות משמרות"].iter_rows(min_row=2, values_only=True))
    names = [r[0] for r in rows]
    assert tpl_name in names


def test_preview_rejects_oversized_file(client, admin_session):
    node = create_node(admin_session, level="branch", name="ie_node_size_001")
    dm = create_soldier(admin_session, personal_number="ie_dm_size_001", role="duty_manager", hierarchy_node_id=node.id)
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]
    oversized = b"PK\x03\x04" + b"0" * (25 * 1024 * 1024)
    resp = client.post(
        "/api/import/preview",
        files={"file": ("import.xlsx", oversized, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "file_too_large"


def test_apply_sets_created_by_on_imported_assignments(client, admin_session):
    """Imported assignments must record the importing duty manager as creator
    so duty-history can show who assigned them."""
    node = create_node(admin_session, level="branch", name="ie_node_cb")
    dm = create_soldier(admin_session, personal_number="ie_dm_cb", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="ie_soldier_cb", hierarchy_node_id=node.id)
    dt = create_duty_type(admin_session, name=f"dt_cb_{uuid.uuid4().hex[:8]}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_cb_{uuid.uuid4().hex[:8]}")
    admin_session.add(loc)
    admin_session.commit()
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]

    resp = client.post(
        "/api/import/apply",
        json={
            "soldiers": [],
            "assignments": [{
                "row": 2, "action": "new",
                "resolved_soldier_id": str(soldier.id),
                "resolved_duty_type_id": str(dt.id),
                "start_date": "2024-06-15", "end_date": "2024-06-16",
                "is_reserve": False,
            }],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["created"] == 1

    admin_session.expire_all()
    assignment = admin_session.query(DutyAssignment).filter_by(soldier_id=soldier.id).one_or_none()
    assert assignment is not None
    assert assignment.created_by == dm.id


def test_apply_update_stamps_rank_last_set_by_manual(client, admin_session):
    """A bulk Excel update that changes `rank` is a deliberate human-controlled
    edit (someone prepared the Excel file and imported it) -- same category as
    update_soldier_profile's manual edit, so it must stamp
    rank_last_set_by="manual" just like that path does."""
    node = create_node(admin_session, level="branch", name="ie_node_rank_stamp")
    dm = create_soldier(admin_session, personal_number="ie_dm_rank_stamp", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="ie_soldier_rank_stamp", hierarchy_node_id=node.id)
    soldier.rank = "טוראי"
    soldier.rank_last_set_by = "hr_sync"
    admin_session.commit()
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]

    resp = client.post(
        "/api/import/apply",
        json={
            "soldiers": [{
                "row": 2, "action": "update",
                "personal_number": soldier.personal_number, "full_name": soldier.full_name,
                "rank": "רבט", "gender": None, "is_officer": None,
                "hierarchy_node_id": None, "enrolled_at": None,
                "enlistment_date": None, "phone": None, "email": None,
                "existing_id": str(soldier.id),
            }],
            "assignments": [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["errors"] == []

    admin_session.expire_all()
    updated = admin_session.get(type(soldier), soldier.id)
    assert updated.rank == "רבט"
    assert updated.rank_last_set_by == "manual"


def test_apply_update_does_not_stamp_rank_last_set_by_when_rank_unchanged(client, admin_session):
    """An Excel re-import that re-sends the same rank value (unrelated fields
    changed, e.g. phone) must not overwrite an existing "worker"/"hr_sync"
    provenance -- only an actual rank change is a manual override."""
    node = create_node(admin_session, level="branch", name="ie_node_rank_unchanged")
    dm = create_soldier(admin_session, personal_number="ie_dm_rank_unchanged", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="ie_soldier_rank_unchanged", hierarchy_node_id=node.id)
    soldier.rank = "טוראי"
    soldier.rank_last_set_by = "worker"
    admin_session.commit()
    token = auth_headers(dm)["Authorization"].split(" ", 1)[1]

    resp = client.post(
        "/api/import/apply",
        json={
            "soldiers": [{
                "row": 2, "action": "update",
                "personal_number": soldier.personal_number, "full_name": soldier.full_name,
                "rank": "טוראי", "gender": None, "is_officer": None,
                "hierarchy_node_id": None, "enrolled_at": None,
                "enlistment_date": None, "phone": "050-9998877", "email": None,
                "existing_id": str(soldier.id),
            }],
            "assignments": [],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["errors"] == []

    admin_session.expire_all()
    updated = admin_session.get(type(soldier), soldier.id)
    assert updated.rank == "טוראי"
    assert updated.rank_last_set_by == "worker"
