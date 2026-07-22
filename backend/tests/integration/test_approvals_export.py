from __future__ import annotations

import io
import uuid
from datetime import date

import openpyxl

from app.db.models import (
    ExemptionRequest,
    ExemptionType,
    PersonalConstraint,
    SoldierEnrollmentRequest,
    SoldierExemption,
    SoldierFieldUpdate,
)
from app.services.hierarchy import create_node as create_hierarchy_node
from tests.helpers import auth_headers, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _token(soldier) -> str:
    return auth_headers(soldier)["Authorization"].split(" ", 1)[1]


def test_export_personal_constraints_sheet(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"sld_{_uid()}")
    constraint = PersonalConstraint(
        soldier_id=soldier.id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 5),
        reason="חופשה",
        status="approved",
        decided_by=admin.id,
        decision_note="ok",
    )
    admin_session.add(constraint)
    admin_session.commit()

    resp = client.get(
        "/api/approvals/export?sheets=personal_constraints",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert wb.sheetnames == ["personal_constraints"]
    ws = wb["personal_constraints"]
    header = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    assert header == [
        "id", "soldier_personal_number", "soldier_name", "start_date", "end_date",
        "reason", "status", "decided_by_personal_number", "decision_note", "created_at",
    ]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    row = next(r for r in rows if r[0] == str(constraint.id))
    assert row[1] == soldier.personal_number
    assert row[2] == soldier.full_name
    assert row[3] == "2026-01-01"
    assert row[4] == "2026-01-05"
    assert row[5] == "חופשה"
    assert row[6] == "approved"
    assert row[7] == admin.personal_number
    assert row[8] == "ok"


def test_export_defaults_to_all_six_sheets(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    resp = client.get(
        "/api/approvals/export", headers={"Authorization": f"Bearer {_token(admin)}"}
    )
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert set(wb.sheetnames) == {
        "swap_requests", "exemption_requests", "soldier_field_updates",
        "soldier_enrollment_requests", "personal_constraints", "soldier_exemptions",
    }


def test_export_soldier_field_updates_sheet(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"sld_{_uid()}")
    update = SoldierFieldUpdate(
        soldier_id=soldier.id,
        field_name="phone",
        new_value="0501234567",
        previous_value="0500000000",
        status="pending",
    )
    admin_session.add(update)
    admin_session.commit()

    resp = client.get(
        "/api/approvals/export?sheets=soldier_field_updates",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    rows = list(wb["soldier_field_updates"].iter_rows(min_row=2, values_only=True))
    row = next(r for r in rows if r[0] == str(update.id))
    assert row[1] == soldier.personal_number
    assert row[3] == "phone"
    assert row[4] == "0501234567"
    assert row[5] == "0500000000"
    assert row[6] == "pending"


def test_export_soldier_enrollment_requests_sheet(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"sld_{_uid()}")
    node = create_hierarchy_node(admin_session, level="group", name=f"מדור_{_uid()}", parent_id=None)
    req = SoldierEnrollmentRequest(soldier_id=soldier.id, requested_node_id=node.id, status="pending")
    admin_session.add(req)
    admin_session.commit()

    resp = client.get(
        "/api/approvals/export?sheets=soldier_enrollment_requests",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    rows = list(wb["soldier_enrollment_requests"].iter_rows(min_row=2, values_only=True))
    row = next(r for r in rows if r[0] == str(req.id))
    assert row[1] == soldier.personal_number
    assert row[3] == node.name
    assert row[4] == "pending"


def test_export_soldier_exemptions_sheet(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"sld_{_uid()}")
    et = ExemptionType(name=f"et_{_uid()}", is_global=False, is_medical=False, is_commander_exemption=False)
    admin_session.add(et)
    admin_session.flush()
    exemption = SoldierExemption(
        soldier_id=soldier.id,
        exemption_type_id=et.id,
        start_date=date(2026, 2, 1),
        reason="פציעה",
        granted_by=admin.id,
    )
    admin_session.add(exemption)
    admin_session.commit()

    resp = client.get(
        "/api/approvals/export?sheets=soldier_exemptions",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    rows = list(wb["soldier_exemptions"].iter_rows(min_row=2, values_only=True))
    row = next(r for r in rows if r[0] == str(exemption.id))
    assert row[1] == soldier.personal_number
    assert row[3] == et.name
    assert row[4] == "2026-02-01"
    assert row[6] == "פציעה"
    assert row[7] == admin.personal_number


def test_export_exemption_requests_sheet(client, admin_session):
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"sld_{_uid()}")
    et = ExemptionType(name=f"et_{_uid()}", is_global=False, is_medical=False, is_commander_exemption=False)
    admin_session.add(et)
    admin_session.flush()
    req = ExemptionRequest(
        soldier_id=soldier.id,
        exemption_type_id=et.id,
        start_date=date(2026, 3, 1),
        reason="בדיקה רפואית",
        status="pending",
    )
    admin_session.add(req)
    admin_session.commit()

    resp = client.get(
        "/api/approvals/export?sheets=exemption_requests",
        headers={"Authorization": f"Bearer {_token(admin)}"},
    )
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    rows = list(wb["exemption_requests"].iter_rows(min_row=2, values_only=True))
    row = next(r for r in rows if r[0] == str(req.id))
    assert row[1] == soldier.personal_number
    assert row[3] == et.name
    assert row[6] == "בדיקה רפואית"
    assert row[7] == "pending"
