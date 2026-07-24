from __future__ import annotations

import uuid
from datetime import UTC, datetime
from datetime import date as date_type

from sqlalchemy import select

import app.services.import_parsers.v1_standard  # noqa: F401 -- registers the v1_standard parser
from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyManagerScope,
    DutyType,
    ExemptionRequest,
    ExemptionType,
    PersonalConstraint,
    Soldier,
    SoldierEnrollmentRequest,
    SoldierExemption,
    SoldierFieldUpdate,
    SwapManagerApproval,
    SwapRequest,
)
from app.services.hierarchy import create_node
from app.services.import_sessions import confirm_session, create_session
from tests.helpers import auth_headers, create_soldier


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _token(soldier: Soldier) -> str:
    return auth_headers(soldier)["Authorization"].split(" ", 1)[1]


def _admin_headers(soldier: Soldier) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(soldier)}"}


def _make_assignment(session, *, soldier: Soldier, node=None, start_date=date_type(2026, 4, 1)) -> DutyAssignment:
    dt = DutyType(name=f"dt_{_uid()}", score_per_day=1)
    loc = DutyLocation(name=f"loc_{_uid()}")
    session.add_all([dt, loc])
    session.flush()
    assignment = DutyAssignment(
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        soldier_id=soldier.id,
        start_date=start_date,
        end_date=start_date,
        status="published",
    )
    session.add(assignment)
    session.flush()
    return assignment


def _export(client, admin: Soldier, sheet: str):
    resp = client.get(
        f"/api/approvals/export?sheets={sheet}", headers=_admin_headers(admin)
    )
    assert resp.status_code == 200
    return resp.content


def test_personal_constraint_export_import_round_trip(admin_session, client):
    node = create_node(admin_session, level="group", name=f"n_{_uid()}", parent_id=None)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=node.id)
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}")
    original = PersonalConstraint(
        soldier_id=soldier.id, start_date=date_type(2024, 6, 15), end_date=date_type(2024, 6, 16),
        reason="round trip test", status="approved", decided_by=decider.id,
        decided_at=datetime.now(UTC), decision_note="ok",
    )
    admin_session.add(original)
    admin_session.commit()

    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    # Export applies the same reason-visibility redaction as the interactive
    # constraint endpoints (can_see_private): give the admin actor
    # duty-manager scope over the soldier's node so the reason round-trips
    # instead of being (correctly) redacted to None and then blanking the
    # existing DB value on re-import.
    admin_session.add(DutyManagerScope(duty_manager_id=admin.id, hierarchy_node_id=node.id))
    admin_session.commit()
    xlsx_bytes = _export(client, admin, "personal_constraints")

    sess = create_session(admin_session, filename="roundtrip.xlsx", content=xlsx_bytes, actor=admin, parser_id="v1_standard")
    row = sess.parsed_state["personal_constraints"][0]
    assert row["action"] == "update"
    assert row["existing_id"] == str(original.id)

    confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()
    admin_session.refresh(original)

    assert original.status == "approved"
    assert original.decided_by == decider.id
    assert original.decision_note == "ok"
    assert original.start_date == date_type(2024, 6, 15)
    assert original.end_date == date_type(2024, 6, 16)
    assert original.reason == "round trip test"

    # No duplicate row was created by the round trip.
    all_rows = admin_session.execute(select(PersonalConstraint)).scalars().all()
    assert len(all_rows) == 1


def test_soldier_field_update_export_import_round_trip(admin_session, client):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}")
    original = SoldierFieldUpdate(
        soldier_id=soldier.id, field_name="phone", new_value="0501234567",
        previous_value="0500000000", status="approved", decided_by=decider.id,
        decided_at=datetime.now(UTC), decision_note="ok",
    )
    admin_session.add(original)
    admin_session.commit()

    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    xlsx_bytes = _export(client, admin, "soldier_field_updates")

    sess = create_session(admin_session, filename="roundtrip.xlsx", content=xlsx_bytes, actor=admin, parser_id="v1_standard")
    row = sess.parsed_state["soldier_field_updates"][0]
    assert row["action"] == "update"
    assert row["existing_id"] == str(original.id)

    confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()
    admin_session.refresh(original)

    assert original.status == "approved"
    assert original.decided_by == decider.id
    assert original.decision_note == "ok"
    assert original.field_name == "phone"
    assert original.new_value == "0501234567"
    assert original.previous_value == "0500000000"

    all_rows = admin_session.execute(select(SoldierFieldUpdate)).scalars().all()
    assert len(all_rows) == 1


def test_soldier_enrollment_request_export_import_round_trip(admin_session, client):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}")
    node = create_node(admin_session, level="group", name=f"n_{_uid()}", parent_id=None)
    original = SoldierEnrollmentRequest(
        soldier_id=soldier.id, requested_node_id=node.id, status="approved",
        decided_by=decider.id, decided_at=datetime.now(UTC), decision_note="ok",
    )
    admin_session.add(original)
    admin_session.commit()

    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    xlsx_bytes = _export(client, admin, "soldier_enrollment_requests")

    sess = create_session(admin_session, filename="roundtrip.xlsx", content=xlsx_bytes, actor=admin, parser_id="v1_standard")
    row = sess.parsed_state["soldier_enrollment_requests"][0]
    assert row["action"] == "update"
    assert row["existing_id"] == str(original.id)

    confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()
    admin_session.refresh(original)

    assert original.status == "approved"
    assert original.decided_by == decider.id
    assert original.decision_note == "ok"
    assert original.requested_node_id == node.id

    all_rows = admin_session.execute(select(SoldierEnrollmentRequest)).scalars().all()
    assert len(all_rows) == 1


def test_soldier_exemption_export_import_round_trip(admin_session, client):
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}")
    granter = create_soldier(admin_session, personal_number=f"gr_{_uid()}")
    et = ExemptionType(name=f"et_{_uid()}", is_global=False, is_medical=False, is_commander_exemption=False)
    admin_session.add(et)
    admin_session.flush()
    original = SoldierExemption(
        soldier_id=soldier.id, exemption_type_id=et.id, start_date=date_type(2026, 2, 1),
        end_date=date_type(2026, 2, 10), reason="פציעה", granted_by=granter.id,
    )
    admin_session.add(original)
    admin_session.commit()

    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    xlsx_bytes = _export(client, admin, "soldier_exemptions")

    sess = create_session(admin_session, filename="roundtrip.xlsx", content=xlsx_bytes, actor=admin, parser_id="v1_standard")
    row = sess.parsed_state["soldier_exemptions"][0]
    assert row["action"] == "update"
    assert row["existing_id"] == str(original.id)

    confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()
    admin_session.refresh(original)

    assert original.reason == "פציעה"
    assert original.granted_by == granter.id
    assert original.start_date == date_type(2026, 2, 1)
    assert original.end_date == date_type(2026, 2, 10)
    assert original.revoked_at is None

    all_rows = admin_session.execute(select(SoldierExemption)).scalars().all()
    assert len(all_rows) == 1


def test_exemption_request_export_import_round_trip(admin_session, client):
    node = create_node(admin_session, level="group", name=f"n_{_uid()}", parent_id=None)
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=node.id)
    commander = create_soldier(admin_session, personal_number=f"cmd_{_uid()}")
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}")
    et = ExemptionType(name=f"et_{_uid()}", is_global=False, is_medical=True, is_commander_exemption=False)
    admin_session.add(et)
    admin_session.flush()
    original = ExemptionRequest(
        soldier_id=soldier.id, exemption_type_id=et.id, start_date=date_type(2026, 3, 1),
        end_date=date_type(2026, 3, 5), reason="בדיקה רפואית", status="approved",
        commander_approved_by=commander.id, decided_by=decider.id, decision_note="ok",
    )
    admin_session.add(original)
    admin_session.commit()

    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    # Same redaction policy as constraints (can_see_private) — grant scope so
    # the reason round-trips instead of being blanked on re-import.
    admin_session.add(DutyManagerScope(duty_manager_id=admin.id, hierarchy_node_id=node.id))
    admin_session.commit()
    xlsx_bytes = _export(client, admin, "exemption_requests")

    sess = create_session(admin_session, filename="roundtrip.xlsx", content=xlsx_bytes, actor=admin, parser_id="v1_standard")
    row = sess.parsed_state["exemption_requests"][0]
    assert row["action"] == "update"
    assert row["existing_id"] == str(original.id)

    confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()
    admin_session.refresh(original)

    assert original.status == "approved"
    assert original.commander_approved_by == commander.id
    assert original.decided_by == decider.id
    assert original.decision_note == "ok"
    assert original.reason == "בדיקה רפואית"

    all_rows = admin_session.execute(select(ExemptionRequest)).scalars().all()
    assert len(all_rows) == 1


def test_swap_request_export_import_round_trip_preserves_approval_log(admin_session, client):
    node = create_node(admin_session, level="unit", name=f"n_{_uid()}", parent_id=None)
    requester = create_soldier(admin_session, personal_number=f"r_{_uid()}", hierarchy_node_id=node.id)
    covering = create_soldier(admin_session, personal_number=f"c_{_uid()}", hierarchy_node_id=node.id)
    commander = create_soldier(admin_session, personal_number=f"cm_{_uid()}")
    node.commander_id = commander.id
    admin_session.flush()
    assignment = _make_assignment(admin_session, soldier=requester, node=node)
    original = SwapRequest(
        duty_assignment_id=assignment.id, duty_date=assignment.start_date,
        requesting_soldier_id=requester.id, covering_soldier_id=covering.id,
        status="pending_approval", requester_side_approved=True, covering_side_approved=True,
    )
    admin_session.add(original)
    admin_session.flush()
    decision = SwapManagerApproval(
        swap_request_id=original.id, side="requester", commander_id=commander.id,
        approver_kind="commander", approved=True, approved_by=commander.id, approved_at=datetime.now(UTC),
    )
    admin_session.add(decision)
    admin_session.commit()

    admin = create_soldier(admin_session, personal_number=f"adm_{_uid()}", role="admin")
    xlsx_bytes = _export(client, admin, "swap_requests")

    sess = create_session(admin_session, filename="roundtrip.xlsx", content=xlsx_bytes, actor=admin, parser_id="v1_standard")
    row = sess.parsed_state["swap_requests"][0]
    assert row["action"] == "update"
    assert len(row["approval_log"]) == 1
    assert row["approval_log"][0]["side"] == "requester"
    assert row["approval_log"][0]["outcome"] == "approved"

    confirm_session(admin_session, session_id=sess.id, actor=admin)
    admin_session.commit()

    rows = admin_session.execute(
        select(SwapManagerApproval).where(SwapManagerApproval.swap_request_id == original.id)
    ).scalars().all()
    assert len(rows) == 1  # idempotent -- re-confirming didn't duplicate the decision row
    assert rows[0].approved is True
    assert rows[0].commander_id == commander.id
    # Note carried forward from an earlier review: the swap_requests export's
    # approval_log column logs the decision-log row's commander_id (the actor who
    # made the decision) rather than a separately-named approved_by/rejected_by
    # field. commander_id and approved_by are always the same value for any given
    # decision row under the current codebase's design, so both survive the round
    # trip identically.
    assert rows[0].approved_by == commander.id

    admin_session.refresh(original)
    assert original.status == "pending_approval"
    assert original.requester_side_approved is True
    assert original.covering_side_approved is True
    assert original.covering_soldier_id == covering.id
