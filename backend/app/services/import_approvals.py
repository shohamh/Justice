from __future__ import annotations

import json
import uuid
from datetime import date as date_type

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    BugReport, ExemptionRequest, ExemptionType, HierarchyNode, PersonalConstraint,
    RangeAssignment, RangeEvent, RangeExcusalRequest, RangeExcusalStatus, RangeLocation,
    RangeType, Soldier, SoldierEnrollmentRequest, SoldierExemption, SoldierFieldUpdate,
    SoldierRangeQualification, SwapCandidate, SwapRequest, SystemSetting,
)
from app.services import settings_loader
from app.services.import_parsers.schema import ParsedImportData
from app.services.settings_loader import SettingsValidationError, _HIDDEN_KEYS

# The four settings whose combined values are cross-validated as a batch by
# validate_settings_update (t/r density ordering + relax-ceiling ordering).
_DENSITY_KEYS = {
    "algorithm.max_duties_per_window",
    "algorithm.max_total_duties_per_window",
    "algorithm.relax_t_ceiling",
    "algorithm.relax_r_ceiling",
}


def _soldiers_by_pn(session: Session) -> dict[str, Soldier]:
    return {s.personal_number: s for s in session.execute(select(Soldier)).scalars()}


def resolve_personal_constraints(session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None) -> list[dict]:
    overrides = overrides or {}
    soldiers_by_pn = _soldiers_by_pn(session)
    out = []
    for row in data.personal_constraints:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        soldier_pn = field("soldier_personal_number", row.soldier_personal_number)
        start_date = field("start_date", row.start_date)
        end_date = field("end_date", row.end_date)
        reason = field("reason", row.reason)
        status = field("status", row.status)
        # Legacy pre-Task-9 exports still carry the old single-state literal
        # "pending" for personal_constraints (before the commander/duty-manager
        # two-step split introduced "pending_commander"/"pending_duty_manager").
        # Coerce it to the new first-step value before validating, so older
        # exported workbooks can still be re-imported instead of hard-rejecting.
        if status == "pending":
            status = "pending_commander"
        decided_by_pn = field("decided_by_personal_number", row.decided_by_personal_number)
        decision_note = field("decision_note", row.decision_note)

        soldier = soldiers_by_pn.get(soldier_pn) if soldier_pn else None
        if soldier is None:
            errors.append(f"חייל לא מזוהה '{soldier_pn}'")
        decided_by = soldiers_by_pn.get(decided_by_pn) if decided_by_pn else None
        if decided_by_pn and decided_by is None:
            errors.append(f"מחליט לא מזוהה '{decided_by_pn}'")
        if status not in ("pending_commander", "pending_duty_manager", "approved", "rejected"):
            errors.append(f"סטטוס לא תקין '{status}'")

        existing = None
        if row.id:
            try:
                existing = session.get(PersonalConstraint, uuid.UUID(row.id))
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        action = "error" if errors else ("update" if existing is not None else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id, "soldier_personal_number": soldier_pn,
            "resolved_soldier_id": str(soldier.id) if soldier else None,
            "start_date": start_date, "end_date": end_date, "reason": reason, "status": status,
            "decided_by_personal_number": decided_by_pn,
            "resolved_decided_by_id": str(decided_by.id) if decided_by else None,
            "decision_note": decision_note,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def resolve_soldier_field_updates(session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None) -> list[dict]:
    overrides = overrides or {}
    soldiers_by_pn = _soldiers_by_pn(session)
    out = []
    for row in data.soldier_field_updates:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        soldier_pn = field("soldier_personal_number", row.soldier_personal_number)
        field_name = field("field_name", row.field_name)
        new_value = field("new_value", row.new_value)
        previous_value = field("previous_value", row.previous_value)
        status = field("status", row.status)
        decided_by_pn = field("decided_by_personal_number", row.decided_by_personal_number)
        decision_note = field("decision_note", row.decision_note)

        soldier = soldiers_by_pn.get(soldier_pn) if soldier_pn else None
        if soldier is None:
            errors.append(f"חייל לא מזוהה '{soldier_pn}'")
        decided_by = soldiers_by_pn.get(decided_by_pn) if decided_by_pn else None
        if decided_by_pn and decided_by is None:
            errors.append(f"מחליט לא מזוהה '{decided_by_pn}'")
        if not field_name:
            errors.append("חסר שם שדה")
        if status not in ("pending", "approved", "rejected"):
            errors.append(f"סטטוס לא תקין '{status}'")

        existing = None
        if row.id:
            try:
                existing = session.get(SoldierFieldUpdate, uuid.UUID(row.id))
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        action = "error" if errors else ("update" if existing is not None else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id, "soldier_personal_number": soldier_pn,
            "resolved_soldier_id": str(soldier.id) if soldier else None,
            "field_name": field_name, "new_value": new_value, "previous_value": previous_value,
            "status": status, "decided_by_personal_number": decided_by_pn,
            "resolved_decided_by_id": str(decided_by.id) if decided_by else None,
            "decision_note": decision_note,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def resolve_soldier_enrollment_requests(session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None) -> list[dict]:
    overrides = overrides or {}
    soldiers_by_pn = _soldiers_by_pn(session)
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}
    out = []
    for row in data.soldier_enrollment_requests:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        soldier_pn = field("soldier_personal_number", row.soldier_personal_number)
        requested_node_name = field("requested_node_name", row.requested_node_name)
        status = field("status", row.status)
        decided_by_pn = field("decided_by_personal_number", row.decided_by_personal_number)
        decision_note = field("decision_note", row.decision_note)

        soldier = soldiers_by_pn.get(soldier_pn) if soldier_pn else None
        if soldier is None:
            errors.append(f"חייל לא מזוהה '{soldier_pn}'")
        node = nodes_by_name.get(requested_node_name) if requested_node_name else None
        if node is None:
            errors.append(f"יחידה לא מזוהה '{requested_node_name}'")
        decided_by = soldiers_by_pn.get(decided_by_pn) if decided_by_pn else None
        if decided_by_pn and decided_by is None:
            errors.append(f"מחליט לא מזוהה '{decided_by_pn}'")
        if status not in ("pending", "commander_approved", "approved", "rejected"):
            errors.append(f"סטטוס לא תקין '{status}'")

        existing = None
        if row.id:
            try:
                existing = session.get(SoldierEnrollmentRequest, uuid.UUID(row.id))
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        action = "error" if errors else ("update" if existing is not None else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id, "soldier_personal_number": soldier_pn,
            "resolved_soldier_id": str(soldier.id) if soldier else None,
            "requested_node_name": requested_node_name,
            "resolved_node_id": str(node.id) if node else None,
            "status": status, "decided_by_personal_number": decided_by_pn,
            "resolved_decided_by_id": str(decided_by.id) if decided_by else None,
            "decision_note": decision_note,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def resolve_soldier_exemptions(session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None) -> list[dict]:
    overrides = overrides or {}
    soldiers_by_pn = _soldiers_by_pn(session)
    exemption_types_by_name = {et.name: et for et in session.execute(select(ExemptionType)).scalars()}
    out = []
    for row in data.soldier_exemptions:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        soldier_pn = field("soldier_personal_number", row.soldier_personal_number)
        exemption_type_name = field("exemption_type_name", row.exemption_type_name)
        start_date = field("start_date", row.start_date)
        end_date = field("end_date", row.end_date)
        reason = field("reason", row.reason)
        granted_by_pn = field("granted_by_personal_number", row.granted_by_personal_number)
        revoked = field("revoked", row.revoked)
        revoke_reason = field("revoke_reason", row.revoke_reason)

        soldier = soldiers_by_pn.get(soldier_pn) if soldier_pn else None
        if soldier is None:
            errors.append(f"חייל לא מזוהה '{soldier_pn}'")
        exemption_type = exemption_types_by_name.get(exemption_type_name) if exemption_type_name else None
        if exemption_type is None:
            errors.append(f"סוג פטור לא מזוהה '{exemption_type_name}'")
        granted_by = soldiers_by_pn.get(granted_by_pn) if granted_by_pn else None
        if granted_by_pn and granted_by is None:
            errors.append(f"מעניק לא מזוהה '{granted_by_pn}'")

        existing = None
        if row.id:
            try:
                existing = session.get(SoldierExemption, uuid.UUID(row.id))
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        action = "error" if errors else ("update" if existing is not None else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id, "soldier_personal_number": soldier_pn,
            "resolved_soldier_id": str(soldier.id) if soldier else None,
            "exemption_type_name": exemption_type_name,
            "resolved_exemption_type_id": str(exemption_type.id) if exemption_type else None,
            "start_date": start_date, "end_date": end_date, "reason": reason,
            "granted_by_personal_number": granted_by_pn,
            "resolved_granted_by_id": str(granted_by.id) if granted_by else None,
            "revoked": revoked, "revoke_reason": revoke_reason,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def resolve_soldier_range_qualifications(session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None) -> list[dict]:
    overrides = overrides or {}
    soldiers_by_pn = _soldiers_by_pn(session)
    out = []
    for row in data.soldier_range_qualifications:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        soldier_pn = field("soldier_personal_number", row.soldier_personal_number)
        range_type = field("range_type", row.range_type)
        valid_until = field("valid_until", row.valid_until)

        soldier = soldiers_by_pn.get(soldier_pn) if soldier_pn else None
        if soldier is None:
            errors.append(f"חייל לא מזוהה '{soldier_pn}'")
        if range_type not in (rt.value for rt in RangeType):
            errors.append(f"סוג מטווח לא תקין '{range_type}'")
        if not valid_until:
            errors.append("חסר תאריך תוקף")

        existing = None
        if row.id:
            try:
                existing = session.get(SoldierRangeQualification, uuid.UUID(row.id))
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        action = "error" if errors else ("update" if existing is not None else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id, "soldier_personal_number": soldier_pn,
            "resolved_soldier_id": str(soldier.id) if soldier else None,
            "range_type": range_type, "valid_until": valid_until,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def resolve_range_excusal_requests(session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None) -> list[dict]:
    overrides = overrides or {}
    soldiers_by_pn = _soldiers_by_pn(session)
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}
    locations_by_name = {loc.name: loc for loc in session.execute(select(RangeLocation)).scalars()}
    events = session.execute(select(RangeEvent)).scalars().all()
    events_by_key = {
        (ev.hierarchy_node_id, ev.range_type, ev.date.isoformat(), ev.range_location_id): ev
        for ev in events
    }
    assignments_by_event_and_soldier = {
        (a.range_event_id, a.soldier_id): a for a in session.execute(select(RangeAssignment)).scalars()
    }

    out = []
    for row in data.range_excusal_requests:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        soldier_pn = field("soldier_personal_number", row.soldier_personal_number)
        requested_by_pn = field("requested_by_personal_number", row.requested_by_personal_number)
        hierarchy_node_name = field("hierarchy_node_name", row.hierarchy_node_name)
        range_type = field("range_type", row.range_type)
        event_date = field("date", row.date)
        range_location_name = field("range_location_name", row.range_location_name)
        reason = field("reason", row.reason)
        status = field("status", row.status)
        decided_by_pn = field("decided_by_personal_number", row.decided_by_personal_number)
        decision_note = field("decision_note", row.decision_note)

        existing = None
        if row.id:
            try:
                existing = session.get(RangeExcusalRequest, uuid.UUID(row.id))
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        soldier = soldiers_by_pn.get(soldier_pn) if soldier_pn else None
        # An approved excusal's linked RangeAssignment is deleted on approval
        # (range_assignment_id is SET NULL), so re-exporting it has no way to
        # recover soldier_personal_number. Only error on a missing soldier
        # when the sheet actually provided a (now-unresolvable) personal
        # number, or when this is a genuinely new row (no existing match by
        # id) that needs a soldier to create — an update to an already-known
        # row with an empty soldier_pn is a legitimate round-trip, not an error.
        if soldier is None and (soldier_pn or existing is None):
            errors.append(f"חייל לא מזוהה '{soldier_pn}'")
        requested_by = soldiers_by_pn.get(requested_by_pn) if requested_by_pn else None
        if requested_by_pn and requested_by is None:
            errors.append(f"מבקש לא מזוהה '{requested_by_pn}'")
        decided_by = soldiers_by_pn.get(decided_by_pn) if decided_by_pn else None
        if decided_by_pn and decided_by is None:
            errors.append(f"מחליט לא מזוהה '{decided_by_pn}'")
        if status not in (s.value for s in RangeExcusalStatus):
            errors.append(f"סטטוס לא תקין '{status}'")

        node = nodes_by_name.get(hierarchy_node_name) if hierarchy_node_name else None
        location = locations_by_name.get(range_location_name) if range_location_name else None
        event = None
        assignment = None
        if node is not None and location is not None and event_date and range_type in (rt.value for rt in RangeType):
            event = events_by_key.get((node.id, range_type, event_date, location.id))
        if event is not None and soldier is not None:
            assignment = assignments_by_event_and_soldier.get((event.id, soldier.id))

        action = "error" if errors else ("update" if existing is not None else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id, "soldier_personal_number": soldier_pn,
            "resolved_soldier_id": str(soldier.id) if soldier else None,
            "requested_by_personal_number": requested_by_pn,
            "resolved_requested_by_id": str(requested_by.id) if requested_by else None,
            "hierarchy_node_name": hierarchy_node_name, "range_type": range_type, "date": event_date,
            "range_location_name": range_location_name,
            "resolved_range_event_id": str(event.id) if event else None,
            "resolved_range_assignment_id": str(assignment.id) if assignment else None,
            "reason": reason, "status": status,
            "decided_by_personal_number": decided_by_pn,
            "resolved_decided_by_id": str(decided_by.id) if decided_by else None,
            "decision_note": decision_note,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def resolve_exemption_requests(session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None) -> list[dict]:
    overrides = overrides or {}
    soldiers_by_pn = _soldiers_by_pn(session)
    exemption_types_by_name = {et.name: et for et in session.execute(select(ExemptionType)).scalars()}
    out = []
    for row in data.exemption_requests:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        soldier_pn = field("soldier_personal_number", row.soldier_personal_number)
        exemption_type_name = field("exemption_type_name", row.exemption_type_name)
        start_date = field("start_date", row.start_date)
        end_date = field("end_date", row.end_date)
        reason = field("reason", row.reason)
        status = field("status", row.status)
        commander_approved_by_pn = field("commander_approved_by_personal_number", row.commander_approved_by_personal_number)
        decided_by_pn = field("decided_by_personal_number", row.decided_by_personal_number)
        decision_note = field("decision_note", row.decision_note)
        files = field("files", row.files)

        soldier = soldiers_by_pn.get(soldier_pn) if soldier_pn else None
        if soldier is None:
            errors.append(f"חייל לא מזוהה '{soldier_pn}'")
        exemption_type = exemption_types_by_name.get(exemption_type_name) if exemption_type_name else None
        if exemption_type is None:
            errors.append(f"סוג פטור לא מזוהה '{exemption_type_name}'")
        commander_approved_by = soldiers_by_pn.get(commander_approved_by_pn) if commander_approved_by_pn else None
        if commander_approved_by_pn and commander_approved_by is None:
            errors.append(f"מפקד מאשר לא מזוהה '{commander_approved_by_pn}'")
        decided_by = soldiers_by_pn.get(decided_by_pn) if decided_by_pn else None
        if decided_by_pn and decided_by is None:
            errors.append(f"מחליט לא מזוהה '{decided_by_pn}'")
        if status not in ("pending_commander", "pending_duty_manager", "approved", "rejected"):
            errors.append(f"סטטוס לא תקין '{status}'")

        existing = None
        if row.id:
            try:
                existing = session.get(ExemptionRequest, uuid.UUID(row.id))
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        action = "error" if errors else ("update" if existing is not None else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id, "soldier_personal_number": soldier_pn,
            "resolved_soldier_id": str(soldier.id) if soldier else None,
            "exemption_type_name": exemption_type_name,
            "resolved_exemption_type_id": str(exemption_type.id) if exemption_type else None,
            "start_date": start_date, "end_date": end_date, "reason": reason, "status": status,
            "commander_approved_by_personal_number": commander_approved_by_pn,
            "resolved_commander_approved_by_id": str(commander_approved_by.id) if commander_approved_by else None,
            "decided_by_personal_number": decided_by_pn,
            "resolved_decided_by_id": str(decided_by.id) if decided_by else None,
            "decision_note": decision_note, "files": files,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def _parse_approval_log(raw: str | None) -> list[dict]:
    """Parse 'side:kind:person_pn:approved|rejected:iso_datetime;...' into
    dicts. Malformed segments are skipped individually (mirrors
    _parse_node_quotas' per-segment tolerance in v1_standard.py) rather than
    failing the whole row."""
    if not raw:
        return []
    out = []
    for segment in raw.split(";"):
        segment = segment.strip()
        if not segment:
            continue
        # maxsplit=4: the "at" field is an ISO datetime and always contains
        # its own colons (HH:MM:SS[+TZ]) — an unbounded split(":") would
        # fragment it and every real entry would silently fail the length
        # check below, so only the first 4 delimiters are split on.
        parts = segment.split(":", 4)
        if len(parts) != 5:
            continue
        side, kind, person_pn, outcome, at = parts
        if side not in ("requester", "covering") or kind not in ("commander", "duty_manager") or outcome not in ("approved", "rejected"):
            continue
        out.append({"side": side, "kind": kind, "person_pn": person_pn, "outcome": outcome, "at": at})
    return out


def resolve_swap_requests(session: Session, data: ParsedImportData, overrides: dict[str, dict] | None = None) -> list[dict]:
    overrides = overrides or {}
    soldiers_by_pn = _soldiers_by_pn(session)
    out = []
    for row in data.swap_requests:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        requesting_pn = field("requesting_personal_number", row.requesting_personal_number)
        target_pn = field("target_personal_number", row.target_personal_number)
        covering_pn = field("covering_personal_number", row.covering_personal_number)
        duty_date = field("duty_date", row.duty_date)
        status = field("status", row.status)
        reason = field("reason", row.reason)
        requester_side_approved = field("requester_side_approved", row.requester_side_approved)
        covering_side_approved = field("covering_side_approved", row.covering_side_approved)
        rejected_by_pn = field("rejected_by_personal_number", row.rejected_by_personal_number)
        decision_note = field("decision_note", row.decision_note)
        approval_log_raw = field("approval_log", row.approval_log)

        requesting = soldiers_by_pn.get(requesting_pn) if requesting_pn else None
        if requesting is None:
            errors.append(f"מבקש לא מזוהה '{requesting_pn}'")
        target = soldiers_by_pn.get(target_pn) if target_pn else None
        if target_pn and target is None:
            errors.append(f"חייל יעד לא מזוהה '{target_pn}'")
        covering = soldiers_by_pn.get(covering_pn) if covering_pn else None
        if covering_pn and covering is None:
            errors.append(f"מחליף לא מזוהה '{covering_pn}'")
        rejected_by = soldiers_by_pn.get(rejected_by_pn) if rejected_by_pn else None
        if rejected_by_pn and rejected_by is None:
            errors.append(f"דוחה לא מזוהה '{rejected_by_pn}'")
        # "pending_approval" was removed as a SwapRequest.status value by the
        # unified-swap-requests schema change — that in-progress state now
        # lives on SwapCandidate.status instead (see resolved_candidate_status
        # below), so it's no longer a valid value on this sheet.
        if status not in ("open", "applied", "rejected", "cancelled"):
            errors.append(f"סטטוס לא תקין '{status}'")

        approval_log_parsed = _parse_approval_log(approval_log_raw)
        resolved_log = []
        for entry in approval_log_parsed:
            person = soldiers_by_pn.get(entry["person_pn"])
            if person is None:
                errors.append(f"מאשר/דוחה לא מזוהה בלוג האישורים '{entry['person_pn']}'")
                continue
            resolved_log.append({**entry, "resolved_person_id": str(person.id)})

        # target_personal_number (still-unanswered invite) and
        # covering_personal_number (accepted/applied/self-claimed) are two
        # mutually-exclusive views of the same underlying SwapCandidate row
        # — see approvals_export._write_swap_requests. Whichever is present
        # identifies the one candidate this row's approval state applies to.
        candidate_soldier = covering or target
        candidate_source = "invited" if target_pn else ("marketplace" if covering_pn else None)

        existing = None
        existing_candidate = None
        if not row.id:
            errors.append("ייבוא בקשות החלפה נתמך רק לעדכון — נדרש מזהה (id)")
        else:
            try:
                existing = session.get(SwapRequest, uuid.UUID(row.id))
                if existing is None:
                    errors.append(f"בקשת החלפה לא נמצאה עבור מזהה '{row.id}'")
                elif candidate_soldier is not None:
                    existing_candidate = session.execute(
                        select(SwapCandidate).where(
                            SwapCandidate.swap_request_id == existing.id,
                            SwapCandidate.soldier_id == candidate_soldier.id,
                        )
                    ).scalar_one_or_none()
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        # Swap-request import is update-only by design: SwapRequest.duty_assignment_id
        # is a required FK with no natural round-trip column on this sheet (no stable
        # business key like duty_type_name+duty_location_name+date exists for an
        # arbitrary historical assignment), so creating a brand-new swap request via
        # spreadsheet is out of scope — only restoring/updating an existing one's
        # decided/rejected state, its (at most one) candidate per row, and
        # approval_log is supported.
        action = "error" if errors else "update"
        out.append({
            "row": row.source_row, "action": action, "errors": errors,
            "id": row.id,
            "requesting_personal_number": requesting_pn,
            "resolved_requesting_soldier_id": str(requesting.id) if requesting else None,
            "target_personal_number": target_pn,
            "resolved_target_soldier_id": str(target.id) if target else None,
            "covering_personal_number": covering_pn,
            "resolved_covering_soldier_id": str(covering.id) if covering else None,
            "resolved_candidate_soldier_id": str(candidate_soldier.id) if candidate_soldier else None,
            "candidate_source": candidate_source,
            "existing_candidate_id": str(existing_candidate.id) if existing_candidate is not None else None,
            "duty_date": duty_date, "status": status, "reason": reason,
            "requester_side_approved": requester_side_approved,
            "covering_side_approved": covering_side_approved,
            "rejected_by_personal_number": rejected_by_pn,
            "resolved_rejected_by_id": str(rejected_by.id) if rejected_by else None,
            "decision_note": decision_note,
            "approval_log": resolved_log,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def resolve_system_settings(
    session: Session, data: ParsedImportData, actor: Soldier, overrides: dict[str, dict] | None = None
) -> list[dict]:
    overrides = overrides or {}

    # Admin-only end to end (Critical Fix 1): a non-admin actor can't touch
    # system_settings via Excel import at all, so every row is short-circuited
    # to out_of_scope without computing lookups/validation.
    if actor.role != "admin":
        out = []
        for row in data.system_settings:
            override = overrides.get(str(row.source_row), {})

            def field(name: str, default):
                return override[name] if name in override else default

            out.append({
                "row": row.source_row, "action": "out_of_scope", "errors": [],
                "key": field("key", row.key), "value_json": field("value_json", row.value_json),
                "parsed_value": None,
            })
        return out

    existing_keys = {
        row[0] for row in session.execute(select(SystemSetting.key)).all()
    }

    # First pass: per-row resolution (key/value_json/parsed_value + JSON
    # validity), same as before. Action/hidden-key checks are deferred to the
    # second pass below so the batch density check below can see every row
    # that parsed cleanly, regardless of what it ends up flipped to.
    prelim = []
    for row in data.system_settings:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        key = field("key", row.key)
        value_json = field("value_json", row.value_json)

        if not key:
            errors.append("חסר מפתח")

        parsed_value = None
        if not errors:
            try:
                parsed_value = json.loads(value_json) if value_json != "" else None
            except Exception as exc:
                errors.append(f"JSON לא תקין בעמודת value_json: {exc}")

        prelim.append({
            "row": row.source_row, "errors": errors,
            "key": key, "value_json": value_json, "parsed_value": parsed_value,
        })

    # Batch-level density validation (Critical Fix 2 extension): only rows
    # that parsed cleanly and have a key participate — a row with a JSON
    # error shouldn't feed into the cross-field check.
    current = {r.key: r.value for r in session.execute(select(SystemSetting)).scalars().all()}
    proposed = {r["key"]: r["parsed_value"] for r in prelim if not r["errors"] and r["key"]}
    try:
        settings_loader.validate_settings_update(current, proposed)
    except SettingsValidationError as exc:
        density_keys_in_proposed = _DENSITY_KEYS & proposed.keys()
        # Defensive: the violation must have come from a change to one of the
        # four density keys, but if none of them are actually in this
        # import's proposed changes, don't crash — just skip attaching
        # per-row errors (nothing in this batch to blame).
        if density_keys_in_proposed:
            for r in prelim:
                if r["key"] in density_keys_in_proposed:
                    r["errors"].append(f"קונפליקט בערכי הצפיפות (t/r): {exc.code}")

    # Second pass: hidden-key filter (Critical Fix 3) + final action.
    out = []
    for r in prelim:
        errors = r["errors"]
        key = r["key"]
        if not errors and key in _HIDDEN_KEYS:
            errors.append("מפתח זה אינו ניתן לעריכה")
        action = "error" if errors else ("update" if key in existing_keys else "new")
        out.append({
            "row": r["row"], "action": action, "errors": errors,
            "key": key, "value_json": r["value_json"], "parsed_value": r["parsed_value"],
        })
    return out


def resolve_bug_reports(
    session: Session, data: ParsedImportData, actor: Soldier, overrides: dict[str, dict] | None = None
) -> list[dict]:
    soldiers_by_pn = _soldiers_by_pn(session)
    overrides = overrides or {}
    out = []
    for row in data.bug_reports:
        errors: list[str] = []
        warnings: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        reporter_pn = field("reporter_personal_number", row.reporter_personal_number)
        description = field("description", row.description)
        severity = field("severity", row.severity)
        route = field("route", row.route)
        status = field("status", row.status)
        created_at = field("created_at", row.created_at)

        # Admin-only end to end (Critical Fix 1): non-admin actors can't
        # touch bug_reports via Excel import — includes audit/user snapshots
        # and reporters' personal numbers — so short-circuit without
        # computing reporter lookups or JSON decoding.
        if actor.role != "admin":
            out.append({
                "row": row.source_row, "action": "out_of_scope", "errors": [], "warnings": [],
                "id": row.id,
                "reporter_personal_number": reporter_pn,
                "resolved_reporter_id": None,
                "description": description, "severity": severity, "route": route, "status": status,
                "created_at": created_at,
                "nav_history": None, "audit_snapshot": None, "user_snapshot": None,
                "existing_id": None,
            })
            continue

        reporter = soldiers_by_pn.get(reporter_pn) if reporter_pn else None
        if reporter is None:
            errors.append(f"מדווח לא מזוהה '{reporter_pn}'")
        if severity not in ("low", "medium", "high"):
            errors.append(f"חומרה לא תקינה '{severity}'")
        if status not in ("open", "in_progress", "resolved"):
            errors.append(f"סטטוס לא תקין '{status}'")
        if not description:
            errors.append("חסר תיאור")
        if not route:
            errors.append("חסר route")

        def _decode(raw: str | None, label: str):
            if not raw:
                return None
            try:
                return json.loads(raw)
            except Exception as exc:
                errors.append(f"JSON לא תקין בעמודת {label}: {exc}")
                return None

        nav_history = _decode(field("nav_history_json", row.nav_history_json), "nav_history_json")
        audit_snapshot = _decode(field("audit_snapshot_json", row.audit_snapshot_json), "audit_snapshot_json")
        user_snapshot = _decode(field("user_snapshot_json", row.user_snapshot_json), "user_snapshot_json")

        existing = None
        if row.id:
            try:
                existing = session.get(BugReport, uuid.UUID(row.id))
                if existing is None:
                    # Important Fix 6: a well-formed but nonexistent id must
                    # be a row error, not a silent fall-through to "new"
                    # (which would create an unrelated report).
                    errors.append(f"מזהה תקלה לא נמצא '{row.id}'")
            except ValueError:
                errors.append(f"מזהה לא תקין '{row.id}'")

        if existing is not None:
            # Important Fix 4: warn (not error — reporter_id never changes on
            # update) when the sheet's reporter doesn't match the report's
            # actual current reporter.
            existing_reporter = session.get(Soldier, existing.reporter_id)
            existing_reporter_pn = existing_reporter.personal_number if existing_reporter else None
            if reporter_pn != existing_reporter_pn:
                warnings.append(
                    f"שים לב: מספר אישי '{reporter_pn}' אינו תואם למדווח הקיים — הוא לא ישונה"
                )

        action = "error" if errors else ("update" if existing is not None else "new")
        out.append({
            "row": row.source_row, "action": action, "errors": errors, "warnings": warnings,
            "id": row.id,
            "reporter_personal_number": reporter_pn,
            "resolved_reporter_id": str(reporter.id) if reporter is not None else None,
            "description": description, "severity": severity, "route": route, "status": status,
            "created_at": created_at,
            "nav_history": nav_history, "audit_snapshot": audit_snapshot, "user_snapshot": user_snapshot,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out
