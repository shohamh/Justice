from __future__ import annotations

import io
from datetime import date
from decimal import Decimal

import openpyxl
import pytest

from sqlalchemy import select

from app.db.models import DutyAssignment, DutyLocation, DutyShift, DutyShiftNodeQuota, RangeAssignment, RangeEvent
from app.services.duty_config import create_duty_type
from app.services.import_sessions import confirm_session, create_session
from tests.helpers import (
    auth_headers,
    create_node,
    create_range_assignment,
    create_range_event,
    create_range_location,
    create_soldier,
)


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
    assert set(wb.sheetnames) == {
        "חיילים", "משמרות", "שיבוצים", "תבניות משמרות",
        "ימי מטווח", "שיבוצי מטווח",
    }

    soldier_rows = list(wb["חיילים"].iter_rows(min_row=2, values_only=True))
    assert any(r[0] == soldier.personal_number for r in soldier_rows)

    shift_rows = list(wb["משמרות"].iter_rows(min_row=2, values_only=True))
    matching_shift = next(r for r in shift_rows if r[0] == dt.name and r[1] == loc.name)
    assert matching_shift[6] == 2  # required_count
    assert node.name in matching_shift[7]  # node_quotas string

    assignment_rows = list(wb["שיבוצים"].iter_rows(min_row=2, values_only=True))
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
    assignment_rows = list(wb["שיבוצים"].iter_rows(min_row=2, values_only=True))
    assert not any(r[0] == soldier.personal_number for r in assignment_rows)


def test_import_export_includes_range_events_and_assignments(client, admin_session):
    node = create_node(admin_session, level="branch", name=f"node_{_uid()}")
    loc = create_range_location(admin_session, name=f"מטווח_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"sol_{_uid()}", hierarchy_node_id=node.id)
    event = create_range_event(
        admin_session, hierarchy_node=node, range_location=loc,
        range_type="live", event_date=date(2024, 6, 20),
    )
    create_range_assignment(admin_session, range_event=event, soldier=soldier)
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    admin_session.commit()

    token = auth_headers(admin)["Authorization"].split(" ", 1)[1]
    resp = client.get(
        "/api/import/export?sheets=range_events,range_assignments",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(resp.content))
    assert set(wb.sheetnames) == {"ימי מטווח", "שיבוצי מטווח"}

    event_rows = list(wb["ימי מטווח"].iter_rows(min_row=2, values_only=True))
    assert any(r[0] == node.name and r[3] == loc.name for r in event_rows)

    assignment_rows = list(wb["שיבוצי מטווח"].iter_rows(min_row=2, values_only=True))
    assert any(r[0] == soldier.personal_number for r in assignment_rows)


def test_range_events_and_assignments_export_import_round_trip(client, admin_session):
    """Genuine export -> re-upload -> confirm -> verify-DB round trip for
    import_export's range_events/range_assignments sheets (Task 10), per
    Finding 4. This is the regression guard that would have caught the
    Enum-serialization bug already fixed in Task 10 (RangeType/
    RangeEventStatus/RangeAttendanceStatus round-tripping through the xlsx
    cell as their real string value, not a Python repr like
    "RangeType.live") — a bad serialization would surface here as either an
    exception during export, or an "invalid range_type/status" row error on
    re-import."""
    node = create_node(admin_session, level="branch", name=f"node_{_uid()}")
    loc = create_range_location(admin_session, name=f"מטווח_{_uid()}")
    soldier = create_soldier(admin_session, personal_number=f"sol_{_uid()}", hierarchy_node_id=node.id)
    event = create_range_event(
        admin_session, hierarchy_node=node, range_location=loc,
        range_type="live", event_date=date(2024, 6, 20), required_count=3,
    )
    create_range_assignment(admin_session, range_event=event, soldier=soldier, attendance_status="present")
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    admin_session.commit()

    token = auth_headers(admin)["Authorization"].split(" ", 1)[1]
    resp = client.get(
        "/api/import/export?sheets=range_events,range_assignments",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    sess = create_session(
        admin_session, filename="roundtrip.xlsx", content=resp.content, actor=admin, parser_id="v1_standard",
    )
    # The export contains every range_event/range_assignment in the DB (not
    # just this test's), so match on this test's unique node/location/soldier
    # names rather than assuming index 0 — other tests sharing this worker's
    # DB may have already created their own rows.
    event_row = next(
        r for r in sess.parsed_state["ימי מטווח"]
        if r["hierarchy_node_name"] == node.name and r["range_location_name"] == loc.name
    )
    assignment_row = next(
        r for r in sess.parsed_state["שיבוצי מטווח"] if r["personal_number"] == soldier.personal_number
    )
    # No "update" path exists for range_events (a fresh import always proposes
    # "new" — see _resolve_range_events), but the re-parsed enum/date/location
    # fields must be valid and error-free; the assignment row must resolve
    # against the *existing* DB event (not the about-to-be-recreated one) and
    # therefore detect it's already assigned.
    assert event_row["errors"] == []
    assert event_row["action"] == "new"
    assert event_row["range_type"] == "live"
    assert event_row["status"] == "planned"
    assert assignment_row["errors"] == []
    assert assignment_row["resolved_range_event_id"] == str(event.id)
    assert assignment_row["action"] == "skip"  # soldier already assigned to this exact event

    confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    events = admin_session.execute(
        select(RangeEvent).where(RangeEvent.hierarchy_node_id == node.id, RangeEvent.range_location_id == loc.id)
    ).scalars().all()
    assert len(events) == 2  # the original + the re-imported "new" row
    assert any(e.required_count == 3 and e.range_type == "live" for e in events)

    assignments = admin_session.execute(
        select(RangeAssignment).where(RangeAssignment.soldier_id == soldier.id)
    ).scalars().all()
    assert len(assignments) == 1  # the "skip" action prevented a duplicate assignment
    assert assignments[0].attendance_status.value == "present"
