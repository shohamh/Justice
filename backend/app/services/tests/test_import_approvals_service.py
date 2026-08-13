from __future__ import annotations

import io
import uuid
from datetime import date
from datetime import date as date_type
from decimal import Decimal

import openpyxl
import pytest
from sqlalchemy import select

from app.db.models import (
    DutyAssignment, DutyLocation, DutyShift, ExemptionRequest, ExemptionType,
    PersonalConstraint, RangeAssignment, RangeExcusalRequest, RangeType, Soldier,
    SoldierEnrollmentRequest, SoldierExemption, SoldierFieldUpdate,
    SoldierRangeQualification, SwapCandidate, SwapManagerApproval, SwapRequest,
)
from app.services.duty_config import create_duty_type
import app.services.import_parsers.v1_standard  # noqa: F401
from app.services.import_approvals import resolve_range_excusal_requests, resolve_soldier_range_qualifications
from app.services.import_parsers.schema import ImportRangeExcusalRequestRow, ImportSoldierRangeQualificationRow, ParsedImportData
from app.services.import_sessions import confirm_session, create_session
from tests.helpers import (
    create_node, create_range_assignment, create_range_event, create_range_location, create_soldier,
)


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
        reason="old", status="pending_commander",
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


# ---------------------------------------------------------------------------
# confirm_session — restores decided status onto real DB records
# ---------------------------------------------------------------------------

def test_personal_constraint_confirm_restores_decided_status(admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}")
    existing = PersonalConstraint(
        soldier_id=soldier.id, start_date=date_type(2024, 1, 1), end_date=date_type(2024, 1, 2),
        reason="old", status="pending_commander",
    )
    admin_session.add(existing)
    admin_session.commit()

    wb = _wb_with_personal_constraints([
        [str(existing.id), soldier.personal_number, "15.06.2024", "16.06.2024", "new reason",
         "approved", decider.personal_number, "ok"],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert result["updated"] == 1
    assert result["errors"] == []
    updated = admin_session.get(PersonalConstraint, existing.id)
    assert updated.status == "approved"
    assert updated.reason == "new reason"
    assert updated.start_date == date_type(2024, 6, 15)
    assert updated.end_date == date_type(2024, 6, 16)
    assert updated.decided_by == decider.id
    assert updated.decision_note == "ok"


def test_soldier_field_update_confirm_restores_decided_status(admin_session):
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
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert result["updated"] == 1
    assert result["errors"] == []
    updated = admin_session.get(SoldierFieldUpdate, existing.id)
    assert updated.status == "approved"
    assert updated.new_value == "0501234567"
    assert updated.decided_by == decider.id
    assert updated.decision_note == "ok"


def test_soldier_enrollment_request_confirm_restores_decided_status(admin_session):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}")
    node = create_node(admin_session, level="branch", name=f"node_{_uid()}")
    existing = SoldierEnrollmentRequest(soldier_id=soldier.id, requested_node_id=node.id, status="pending")
    admin_session.add(existing)
    admin_session.commit()

    wb = _wb_with_soldier_enrollment_requests([
        [str(existing.id), soldier.personal_number, node.name, "approved", decider.personal_number, "ok"],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert result["updated"] == 1
    assert result["errors"] == []
    updated = admin_session.get(SoldierEnrollmentRequest, existing.id)
    assert updated.status == "approved"
    assert updated.decided_by == decider.id
    assert updated.decision_note == "ok"


def test_soldier_exemption_confirm_restores_revoked_status(admin_session):
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
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert result["updated"] == 1
    assert result["errors"] == []
    updated = admin_session.get(SoldierExemption, existing.id)
    assert updated.reason == "new reason"
    assert updated.granted_by == granter.id
    assert updated.revoked_at is not None
    assert updated.revoke_reason == "revoke reason"


def test_exemption_request_confirm_restores_decided_status(admin_session):
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
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert result["updated"] == 1
    assert result["errors"] == []
    updated = admin_session.get(ExemptionRequest, existing.id)
    assert updated.status == "approved"
    assert updated.reason == "new reason"
    assert updated.commander_approved_by == commander_approver.id
    assert updated.decided_by == decider.id
    assert updated.decision_note == "ok"


def test_personal_constraint_confirm_with_redacted_reason_preserves_existing(admin_session):
    """A row simulating a privacy-redacted export (reason blank, but id matching an
    existing record) must NOT null out the real reason already stored in the DB.

    This is the exact re-import-of-a-redacted-export scenario: reason=None means
    "I couldn't see this value," not "clear it."
    """
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}")
    existing = PersonalConstraint(
        soldier_id=soldier.id, start_date=date_type(2024, 1, 1), end_date=date_type(2024, 1, 2),
        reason="real sensitive reason", status="pending_commander",
    )
    admin_session.add(existing)
    admin_session.commit()

    # blank "reason" cell == redacted export value
    wb = _wb_with_personal_constraints([
        [str(existing.id), soldier.personal_number, "15.06.2024", "16.06.2024", "",
         "approved", decider.personal_number, "ok"],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert result["updated"] == 1
    assert result["errors"] == []
    updated = admin_session.get(PersonalConstraint, existing.id)
    assert updated.reason == "real sensitive reason"
    assert updated.status == "approved"
    assert updated.start_date == date_type(2024, 6, 15)
    assert updated.end_date == date_type(2024, 6, 16)


def test_exemption_request_confirm_with_redacted_reason_preserves_existing(admin_session):
    """Same redacted-export-reimport scenario for exemption_requests."""
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    commander_approver = create_soldier(admin_session, personal_number=f"cmd_{_uid()}")
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}")
    et = ExemptionType(name=f"et_{_uid()}")
    admin_session.add(et)
    admin_session.flush()
    existing = ExemptionRequest(
        soldier_id=soldier.id, exemption_type_id=et.id,
        start_date=date_type(2024, 1, 1), status="pending_commander",
        reason="real sensitive reason",
    )
    admin_session.add(existing)
    admin_session.commit()

    # blank "reason" cell == redacted export value
    wb = _wb_with_exemption_requests([
        [str(existing.id), soldier.personal_number, et.name, "15.06.2024", "16.06.2024",
         "", "approved", commander_approver.personal_number, decider.personal_number, "ok", ""],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert result["updated"] == 1
    assert result["errors"] == []
    updated = admin_session.get(ExemptionRequest, existing.id)
    assert updated.reason == "real sensitive reason"
    assert updated.status == "approved"
    assert updated.commander_approved_by == commander_approver.id
    assert updated.decided_by == decider.id
    assert updated.decision_note == "ok"


def test_swap_request_confirm_restores_status_and_approval_log(admin_session):
    requesting = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    covering = create_soldier(admin_session, personal_number=f"cov_{_uid()}")
    commander = create_soldier(admin_session, personal_number=f"cmd_{_uid()}")
    existing = _make_swap_request(admin_session, requesting_soldier=requesting)
    admin_session.commit()

    approval_log = f"requester:commander:{commander.personal_number}:approved:2024-06-15T10:00:00+00:00"
    wb = _wb_with_swap_requests([
        [str(existing.id), requesting.personal_number, "", covering.personal_number, "15.06.2024",
         "applied", "reason", "true", "true", "", "ok", approval_log],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    sess = create_session(admin_session, filename="f.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")

    result = confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    assert result["updated"] == 1
    assert result["errors"] == []
    updated = admin_session.get(SwapRequest, existing.id)
    assert updated.status == "applied"
    assert updated.requester_side_approved is True
    assert updated.decision_note == "ok"

    candidate = admin_session.execute(
        select(SwapCandidate).where(
            SwapCandidate.swap_request_id == existing.id,
            SwapCandidate.soldier_id == covering.id,
        )
    ).scalar_one()
    assert candidate.soldier_side_approved is True
    assert candidate.status == "applied"

    approvals = admin_session.execute(
        select(SwapManagerApproval).where(SwapManagerApproval.swap_request_id == existing.id)
    ).scalars().all()
    assert len(approvals) == 1
    approval = approvals[0]
    assert approval.side == "requester"
    assert approval.approver_kind == "commander"
    assert approval.commander_id == commander.id
    assert approval.approved is True
    assert approval.approved_by == commander.id
    assert approval.approved_at is not None


def test_swap_request_confirm_reconfirm_is_idempotent_no_duplicate_approval_rows(admin_session):
    """Re-running confirm_session against the same decided rows must not
    create duplicate SwapManagerApproval rows for the same (side, kind,
    person) — verifies the idempotent re-confirm behavior described in the
    task brief."""
    requesting = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    commander = create_soldier(admin_session, personal_number=f"cmd_{_uid()}")
    existing = _make_swap_request(admin_session, requesting_soldier=requesting)
    admin_session.commit()

    approval_log = f"requester:commander:{commander.personal_number}:approved:2024-06-15T10:00:00+00:00"
    wb = _wb_with_swap_requests([
        [str(existing.id), requesting.personal_number, "", "", "15.06.2024",
         "applied", "reason", "true", "", "", "ok", approval_log],
    ])
    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")

    sess1 = create_session(admin_session, filename="f1.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")
    confirm_session(admin_session, session_id=sess1.id, actor=admin)
    admin_session.commit()

    sess2 = create_session(admin_session, filename="f2.xlsx", content=_to_bytes(wb), actor=admin, parser_id="v1_standard")
    result2 = confirm_session(admin_session, session_id=sess2.id, actor=admin)
    admin_session.commit()

    assert result2["updated"] == 1
    assert result2["errors"] == []
    approvals = admin_session.execute(
        select(SwapManagerApproval).where(SwapManagerApproval.swap_request_id == existing.id)
    ).scalars().all()
    assert len(approvals) == 1


# ---------------------------------------------------------------------------
# soldier_range_qualifications / range_excusal_requests
# ---------------------------------------------------------------------------

def test_resolve_soldier_range_qualifications_new_and_update(app_session):
    soldier = create_soldier(app_session, personal_number="12345", full_name="ישראל ישראלי")
    existing = SoldierRangeQualification(soldier_id=soldier.id, range_type="live", valid_until=date(2024, 1, 1))
    app_session.add(existing)
    app_session.flush()

    data = ParsedImportData(
        parser_id="v1_standard",
        soldier_range_qualifications=[
            ImportSoldierRangeQualificationRow(source_row=2, id=str(existing.id), soldier_personal_number="12345", range_type="live", valid_until="2025-01-01"),
            ImportSoldierRangeQualificationRow(source_row=3, soldier_personal_number="12345", range_type="alal", valid_until="2025-06-01"),
        ],
    )
    result = resolve_soldier_range_qualifications(app_session, data)
    assert result[0]["action"] == "update"
    assert result[0]["existing_id"] == str(existing.id)
    assert result[1]["action"] == "new"


def test_resolve_soldier_range_qualifications_invalid_range_type_error(app_session):
    create_soldier(app_session, personal_number="12345", full_name="ישראל ישראלי")
    data = ParsedImportData(
        parser_id="v1_standard",
        soldier_range_qualifications=[
            ImportSoldierRangeQualificationRow(source_row=2, soldier_personal_number="12345", range_type="bogus", valid_until="2025-01-01"),
        ],
    )
    result = resolve_soldier_range_qualifications(app_session, data)
    assert result[0]["action"] == "error"


def test_resolve_range_excusal_requests_matches_existing_assignment(app_session):
    node = create_node(app_session, name="מדור א", level="group")
    loc = create_range_location(app_session, name="מטווח דרומי")
    soldier = create_soldier(app_session, personal_number="12345", full_name="ישראל ישראלי", hierarchy_node_id=node.id)
    event = create_range_event(app_session, hierarchy_node=node, range_location=loc)
    assignment = create_range_assignment(app_session, range_event=event, soldier=soldier)

    data = ParsedImportData(
        parser_id="v1_standard",
        range_excusal_requests=[
            ImportRangeExcusalRequestRow(
                source_row=2, soldier_personal_number="12345", requested_by_personal_number="12345",
                hierarchy_node_name="מדור א", range_type="live", date="2024-06-15",
                range_location_name="מטווח דרומי", reason="חופשה", status="pending",
            )
        ],
    )
    result = resolve_range_excusal_requests(app_session, data)
    row = result[0]
    assert row["action"] == "new"
    assert row["resolved_range_event_id"] == str(event.id)
    assert row["resolved_range_assignment_id"] == str(assignment.id)


def test_resolve_range_excusal_requests_invalid_status_error(app_session):
    create_soldier(app_session, personal_number="12345", full_name="ישראל ישראלי")
    data = ParsedImportData(
        parser_id="v1_standard",
        range_excusal_requests=[
            ImportRangeExcusalRequestRow(
                source_row=2, soldier_personal_number="12345", range_type="live",
                date="2024-06-15", range_location_name="מטווח דרומי", status="not_a_status",
            )
        ],
    )
    result = resolve_range_excusal_requests(app_session, data)
    assert result[0]["action"] == "error"


def test_resolve_range_excusal_requests_approved_update_with_no_soldier_pn_no_error(app_session):
    """Regression guard: an approved excusal's linked RangeAssignment is
    deleted on approval (range_assignment_id SET NULL), so re-exporting it
    has no way to recover soldier_personal_number — the export writer emits
    an empty cell for that row. Re-importing an unmodified export of an
    already-known (id-matched) approved excusal must resolve as a clean
    update, not error out on "soldier not found", or every approved excusal
    would fail to round-trip."""
    existing = RangeExcusalRequest(
        range_assignment_id=None,
        range_event_id=None,
        requested_by=None,
        reason="חופשה",
        status="approved",
    )
    app_session.add(existing)
    app_session.flush()

    data = ParsedImportData(
        parser_id="v1_standard",
        range_excusal_requests=[
            ImportRangeExcusalRequestRow(
                source_row=2, id=str(existing.id), soldier_personal_number="",
                range_type="live", date="2024-06-15",
                range_location_name="מטווח דרומי", reason="חופשה", status="approved",
            )
        ],
    )
    result = resolve_range_excusal_requests(app_session, data)
    row = result[0]
    assert row["errors"] == []
    assert row["action"] == "update"
    assert row["existing_id"] == str(existing.id)
