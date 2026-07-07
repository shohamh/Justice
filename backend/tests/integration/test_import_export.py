from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import openpyxl
import pytest

from app.db.models import DutyAssignment, DutyLocation, DutyShift, DutyShiftNodeQuota
from app.services.duty_config import create_duty_type
from tests.helpers import auth_headers, create_node, create_soldier


def _uid() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


def test_export_round_trips_soldiers_duty_shifts_and_assignments(client, admin_session):
    node = create_node(admin_session, level="branch", name=f"node_{_uid()}")
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    soldier = create_soldier(admin_session, personal_number=f"sol_{_uid()}", hierarchy_node_id=node.id)
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2024, 6, 15), end_date=date(2024, 6, 16),
        required_count=2,
    )
    admin_session.add(shift)
    admin_session.flush()
    admin_session.add(DutyShiftNodeQuota(duty_shift_id=shift.id, hierarchy_node_id=node.id, count=1))
    admin_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=shift.start_date, end_date=shift.end_date,
    ))
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    admin_session.commit()

    token = auth_headers(admin)["Authorization"].split(" ", 1)[1]
    resp = client.get("/api/import/export", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert "spreadsheetml" in resp.headers["content-type"]

    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert set(wb.sheetnames) == {"soldiers", "duty_shifts", "assignments"}

    soldier_rows = list(wb["soldiers"].iter_rows(min_row=2, values_only=True))
    assert any(r[0] == soldier.personal_number for r in soldier_rows)

    shift_rows = list(wb["duty_shifts"].iter_rows(min_row=2, values_only=True))
    matching_shift = next(r for r in shift_rows if r[0] == dt.name and r[1] == loc.name)
    assert matching_shift[6] == 2  # required_count
    assert node.name in matching_shift[7]  # node_quotas string

    assignment_rows = list(wb["assignments"].iter_rows(min_row=2, values_only=True))
    assert len(assignment_rows) == 1
    a = assignment_rows[0]
    assert a[0] == soldier.personal_number
    assert a[1] == soldier.full_name
    assert a[2] == dt.name
    assert a[3] == loc.name


def test_export_omits_assignments_without_linked_shift(client, admin_session):
    dt = create_duty_type(admin_session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    admin_session.add(loc)
    admin_session.flush()
    soldier = create_soldier(admin_session, personal_number=f"sol_{_uid()}")
    admin_session.add(DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2024, 6, 15), end_date=date(2024, 6, 16),
    ))  # no duty_shift_id
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    admin_session.commit()

    token = auth_headers(admin)["Authorization"].split(" ", 1)[1]
    resp = client.get("/api/import/export", headers={"Authorization": f"Bearer {token}"})
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assignment_rows = list(wb["assignments"].iter_rows(min_row=2, values_only=True))
    assert not any(r[0] == soldier.personal_number for r in assignment_rows)
