from __future__ import annotations

import uuid
from datetime import date as date_type

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ExemptionRequest, ExemptionType, HierarchyNode, PersonalConstraint,
    Soldier, SoldierEnrollmentRequest, SoldierExemption, SoldierFieldUpdate,
    SwapCandidate, SwapRequest,
)
from app.services.import_parsers.schema import ParsedImportData


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
        decided_by_pn = field("decided_by_personal_number", row.decided_by_personal_number)
        decision_note = field("decision_note", row.decision_note)

        soldier = soldiers_by_pn.get(soldier_pn) if soldier_pn else None
        if soldier is None:
            errors.append(f"חייל לא מזוהה '{soldier_pn}'")
        decided_by = soldiers_by_pn.get(decided_by_pn) if decided_by_pn else None
        if decided_by_pn and decided_by is None:
            errors.append(f"מחליט לא מזוהה '{decided_by_pn}'")
        if status not in ("pending", "approved", "rejected"):
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
            errors.append(f"מכסה לא מזוהה '{covering_pn}'")
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
