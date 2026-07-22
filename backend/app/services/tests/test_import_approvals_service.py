from __future__ import annotations

import io
import uuid
from datetime import date as date_type
from decimal import Decimal

import openpyxl
import pytest

from app.db.models import (
    DutyAssignment, DutyLocation, DutyShift, ExemptionRequest, ExemptionType,
    PersonalConstraint, Soldier, SoldierEnrollmentRequest, SoldierExemption,
    SoldierFieldUpdate, SwapRequest,
)
from app.services.duty_config import create_duty_type
import app.services.import_parsers.v1_standard  # noqa: F401
from app.services.import_sessions import create_session
from tests.helpers import create_node, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _to_bytes(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _wb_with_sheet(sheet_name: str, header: list[str], rows: list[list]):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet(sheet_name)
    ws.append(header)
    for r in rows:
        ws.append(r)
    return wb


def _wb_with_personal_constraints(rows):
    return _wb_with_sheet(
        "personal_constraints",
        ["id", "soldier_personal_number", "start_date", "end_date", "reason",
         "status", "decided_by_personal_number", "decision_note"],
        rows,
    )


# ---------------------------------------------------------------------------
# personal_constraints
# ---------------------------------------------------------------------------

def test_personal_constraint_new_row_resolves(admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    admin_session.commit()

    wb = _wb_with_personal_constraints([
        ["", soldier.personal_number, "15.06.2024", "16.06.2024", "reason", "pending", "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    row = sess.parsed_state["personal_constraints"][0]
    assert row["action"] == "new"
    assert row["resolved_soldier_id"] == str(soldier.id)


def test_personal_constraint_existing_id_resolves_to_update(admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}")
    existing = PersonalConstraint(
        soldier_id=soldier.id, start_date=date_type(2024, 1, 1), end_date=date_type(2024, 1, 2),
        reason="old", status="pending",
    )
    admin_session.add(existing)
    admin_session.commit()

    wb = _wb_with_personal_constraints([
        [str(existing.id), soldier.personal_number, "15.06.2024", "16.06.2024", "new reason", "approved", decider.personal_number, "ok"],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm2_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    row = sess.parsed_state["personal_constraints"][0]
    assert row["action"] == "update"
    assert row["existing_id"] == str(existing.id)


# ---------------------------------------------------------------------------
# soldier_field_updates
# ---------------------------------------------------------------------------

def _wb_with_soldier_field_updates(rows):
    return _wb_with_sheet(
        "soldier_field_updates",
        ["id", "soldier_personal_number", "field_name", "new_value", "previous_value",
         "status", "decided_by_personal_number", "decision_note"],
        rows,
    )


def test_soldier_field_update_new_row_resolves(admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    admin_session.commit()

    wb = _wb_with_soldier_field_updates([
        ["", soldier.personal_number, "phone", "0501234567", "0509999999", "pending", "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    row = sess.parsed_state["soldier_field_updates"][0]
    assert row["action"] == "new"
    assert row["resolved_soldier_id"] == str(soldier.id)


def test_soldier_field_update_existing_id_resolves_to_update(admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}")
    existing = SoldierFieldUpdate(
        soldier_id=soldier.id, field_name="phone", new_value="0501111111",
        previous_value="0509999999", status="pending",
    )
    admin_session.add(existing)
    admin_session.commit()

    wb = _wb_with_soldier_field_updates([
        [str(existing.id), soldier.personal_number, "phone", "0501234567", "0509999999",
         "approved", decider.personal_number, "ok"],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm2_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    row = sess.parsed_state["soldier_field_updates"][0]
    assert row["action"] == "update"
    assert row["existing_id"] == str(existing.id)


# ---------------------------------------------------------------------------
# soldier_enrollment_requests
# ---------------------------------------------------------------------------

def _wb_with_soldier_enrollment_requests(rows):
    return _wb_with_sheet(
        "soldier_enrollment_requests",
        ["id", "soldier_personal_number", "requested_node_name", "status",
         "decided_by_personal_number", "decision_note"],
        rows,
    )


def test_soldier_enrollment_request_new_row_resolves(admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    node = create_node(admin_session, level="branch", name=f"node_{_uid()}")
    admin_session.commit()

    wb = _wb_with_soldier_enrollment_requests([
        ["", soldier.personal_number, node.name, "pending", "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    row = sess.parsed_state["soldier_enrollment_requests"][0]
    assert row["action"] == "new"
    assert row["resolved_soldier_id"] == str(soldier.id)
    assert row["resolved_node_id"] == str(node.id)


def test_soldier_enrollment_request_existing_id_resolves_to_update(admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}")
    node = create_node(admin_session, level="branch", name=f"node_{_uid()}")
    existing = SoldierEnrollmentRequest(soldier_id=soldier.id, requested_node_id=node.id, status="pending")
    admin_session.add(existing)
    admin_session.commit()

    wb = _wb_with_soldier_enrollment_requests([
        [str(existing.id), soldier.personal_number, node.name, "approved", decider.personal_number, "ok"],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm2_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    row = sess.parsed_state["soldier_enrollment_requests"][0]
    assert row["action"] == "update"
    assert row["existing_id"] == str(existing.id)


# ---------------------------------------------------------------------------
# soldier_exemptions
# ---------------------------------------------------------------------------

def _wb_with_soldier_exemptions(rows):
    return _wb_with_sheet(
        "soldier_exemptions",
        ["id", "soldier_personal_number", "exemption_type_name", "start_date", "end_date",
         "reason", "granted_by_personal_number", "revoked", "revoke_reason"],
        rows,
    )


def test_soldier_exemption_new_row_resolves(admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    et = ExemptionType(name=f"et_{_uid()}")
    admin_session.add(et)
    admin_session.commit()

    wb = _wb_with_soldier_exemptions([
        ["", soldier.personal_number, et.name, "15.06.2024", "16.06.2024", "reason", "", "false", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    row = sess.parsed_state["soldier_exemptions"][0]
    assert row["action"] == "new"
    assert row["resolved_soldier_id"] == str(soldier.id)
    assert row["resolved_exemption_type_id"] == str(et.id)


def test_soldier_exemption_existing_id_resolves_to_update(admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    granter = create_soldier(admin_session, personal_number=f"gr_{_uid()}")
    et = ExemptionType(name=f"et_{_uid()}")
    admin_session.add(et)
    admin_session.flush()
    existing = SoldierExemption(
        soldier_id=soldier.id, exemption_type_id=et.id,
        start_date=date_type(2024, 1, 1), end_date=date_type(2024, 1, 2), reason="old",
    )
    admin_session.add(existing)
    admin_session.commit()

    wb = _wb_with_soldier_exemptions([
        [str(existing.id), soldier.personal_number, et.name, "15.06.2024", "16.06.2024",
         "new reason", granter.personal_number, "true", "revoke reason"],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm2_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    row = sess.parsed_state["soldier_exemptions"][0]
    assert row["action"] == "update"
    assert row["existing_id"] == str(existing.id)


# ---------------------------------------------------------------------------
# exemption_requests
# ---------------------------------------------------------------------------

def _wb_with_exemption_requests(rows):
    return _wb_with_sheet(
        "exemption_requests",
        ["id", "soldier_personal_number", "exemption_type_name", "start_date", "end_date",
         "reason", "status", "commander_approved_by_personal_number",
         "decided_by_personal_number", "decision_note", "files"],
        rows,
    )


def test_exemption_request_new_row_resolves(admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    et = ExemptionType(name=f"et_{_uid()}")
    admin_session.add(et)
    admin_session.commit()

    wb = _wb_with_exemption_requests([
        ["", soldier.personal_number, et.name, "15.06.2024", "16.06.2024",
         "reason", "pending_commander", "", "", "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    row = sess.parsed_state["exemption_requests"][0]
    assert row["action"] == "new"
    assert row["resolved_soldier_id"] == str(soldier.id)
    assert row["resolved_exemption_type_id"] == str(et.id)


def test_exemption_request_existing_id_resolves_to_update(admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    commander_approver = create_soldier(admin_session, personal_number=f"cmd_{_uid()}")
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}")
    et = ExemptionType(name=f"et_{_uid()}")
    admin_session.add(et)
    admin_session.flush()
    existing = ExemptionRequest(
        soldier_id=soldier.id, exemption_type_id=et.id,
        start_date=date_type(2024, 1, 1), status="pending_commander",
    )
    admin_session.add(existing)
    admin_session.commit()

    wb = _wb_with_exemption_requests([
        [str(existing.id), soldier.personal_number, et.name, "15.06.2024", "16.06.2024",
         "new reason", "approved", commander_approver.personal_number, decider.personal_number, "ok", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm3_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    row = sess.parsed_state["exemption_requests"][0]
    assert row["action"] == "update"
    assert row["existing_id"] == str(existing.id)


# ---------------------------------------------------------------------------
# swap_requests (update-only by design — no "new" action path)
# ---------------------------------------------------------------------------

def _wb_with_swap_requests(rows):
    return _wb_with_sheet(
        "swap_requests",
        ["id", "requesting_personal_number", "target_personal_number", "covering_personal_number",
         "duty_date", "status", "reason", "requester_side_approved", "covering_side_approved",
         "rejected_by_personal_number", "decision_note", "approval_log"],
        rows,
    )


def _make_swap_request(session, *, requesting_soldier) -> SwapRequest:
    dt = create_duty_type(session, name=f"dt_{_uid()}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{_uid()}")
    session.add(loc)
    session.flush()
    shift = DutyShift(
        duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date_type(2024, 6, 15), end_date=date_type(2024, 6, 16),
        required_count=1,
    )
    session.add(shift)
    session.flush()
    assignment = DutyAssignment(
        soldier_id=requesting_soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        duty_shift_id=shift.id, start_date=shift.start_date, end_date=shift.end_date,
    )
    session.add(assignment)
    session.flush()
    swap = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=shift.start_date,
        requesting_soldier_id=requesting_soldier.id, status="open",
    )
    session.add(swap)
    session.flush()
    return swap


def test_swap_request_without_id_is_error_not_new(admin_session):
    requesting = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    admin_session.commit()

    wb = _wb_with_swap_requests([
        ["", requesting.personal_number, "", "", "15.06.2024", "open", "reason", "", "", "", "", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    row = sess.parsed_state["swap_requests"][0]
    assert row["action"] == "error"
    assert any("עדכון" in e for e in row["errors"])


def test_swap_request_existing_id_resolves_to_update(admin_session):
    requesting = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    existing = _make_swap_request(admin_session, requesting_soldier=requesting)
    admin_session.commit()

    wb = _wb_with_swap_requests([
        [str(existing.id), requesting.personal_number, "", "", "15.06.2024", "applied", "reason",
         "true", "true", "", "ok", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    row = sess.parsed_state["swap_requests"][0]
    assert row["action"] == "update"
    assert row["existing_id"] == str(existing.id)
