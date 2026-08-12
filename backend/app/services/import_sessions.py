from __future__ import annotations

import io
import json
import secrets
import uuid
from datetime import UTC, date as date_type, datetime
from decimal import Decimal

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.password import hash_password
from app.db.models import (
    BugReport,
    DutyAssignment,
    DutyLocation,
    DutyManagerScope,
    DutyShift,
    DutyType,
    ExemptionRequest,
    ExemptionType,
    HierarchyLevelType,
    HierarchyNode,
    ImportSession,
    PersonalConstraint,
    RangeAssignment,
    RangeAttendanceStatus,
    RangeEvent,
    RangeEventStatus,
    RangeLocation,
    RangeType,
    ShiftTemplate,
    Soldier,
    SoldierEnrollmentRequest,
    SoldierExemption,
    SoldierFieldUpdate,
    SwapCandidate,
    SwapManagerApproval,
    SwapRequest,
    SystemSetting,
)
from app.services.dm_scope import assign_dm_scope, remove_dm_scope
from app.services.duty_config import (
    create_duty_type,
    create_exemption_type,
    create_location,
    set_exemption_duty_types,
    update_duty_type,
    update_exemption_type,
    update_location,
)
from app.services.hierarchy import change_node_level, create_node, move_node, set_commander
from app.services.import_approvals import (
    resolve_bug_reports, resolve_exemption_requests, resolve_personal_constraints,
    resolve_soldier_enrollment_requests, resolve_soldier_exemptions, resolve_soldier_field_updates,
    resolve_swap_requests, resolve_system_settings,
)
from app.services.import_parsers.registry import auto_detect_parser, get_parser
from app.services.import_parsers.schema import ParsedImportData
from app.services.import_scope import is_node_in_actor_scope
from app.services.settings_loader import set_setting
from app.services.shift_quotas import set_shift_quotas
from app.services.shift_templates import create_template, update_template


class ImportSessionError(Exception):
    pass


def _resolve_soldiers(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    node_by_name: dict[str, str] | None = None,
    node_by_row: dict[str, str] | None = None,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    node_by_name = node_by_name or {}
    node_by_row = node_by_row or {}
    overrides = overrides or {}
    existing_by_pn = {
        s.personal_number: s for s in session.execute(select(Soldier)).scalars()
    }
    existing_by_full_name: dict[str, list[Soldier]] = {}
    for s in existing_by_pn.values():
        existing_by_full_name.setdefault(s.full_name, []).append(s)
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}

    out = []
    for row in data.soldiers:
        errors: list[str] = []
        warnings: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        personal_number = field("personal_number", row.personal_number)
        full_name = field("full_name", row.full_name)
        rank = field("rank", row.rank)
        gender = field("gender", row.gender)
        is_officer = field("is_officer", row.is_officer)
        hierarchy_node_name = field("hierarchy_node_name", row.hierarchy_node_name)
        enrolled_at = field("enrolled_at", row.enrolled_at)
        enlistment_date = field("enlistment_date", row.enlistment_date)
        phone = field("phone", row.phone)
        email = field("email", row.email)
        is_career = field("is_career", row.is_career)
        next_rank_date = field("next_rank_date", row.next_rank_date)
        bahad1_graduate = field("bahad1_graduate", row.bahad1_graduate)
        has_military_driving_license = field("has_military_driving_license", row.has_military_driving_license)
        military_driving_license_expiry = field("military_driving_license_expiry", row.military_driving_license_expiry)
        mandatory_end_date = field("mandatory_end_date", row.mandatory_end_date)
        discharge_date = field("discharge_date", row.discharge_date)
        last_mitvahim_date = field("last_mitvahim_date", row.last_mitvahim_date)
        last_alal_date = field("last_alal_date", row.last_alal_date)
        left_at = field("left_at", row.left_at)

        if not personal_number:
            errors.append("חסר מספר אישי")
        if not full_name:
            errors.append("חסר שם מלא")

        node = None
        if hierarchy_node_name:
            row_key = f"soldiers:{row.source_row}"
            mapped_id = node_by_row.get(row_key) or node_by_name.get(hierarchy_node_name)
            if mapped_id:
                try:
                    node = session.get(HierarchyNode, uuid.UUID(mapped_id))
                except ValueError:
                    pass
            if node is None:
                node = nodes_by_name.get(hierarchy_node_name)
            if node is None:
                errors.append(f"יחידה לא מזוהה '{hierarchy_node_name}'")

        existing = existing_by_pn.get(personal_number) if personal_number else None
        if existing is None and personal_number and full_name:
            candidates = existing_by_full_name.get(full_name, [])
            if len(candidates) == 1:
                existing = candidates[0]
                warnings.append(
                    f"נמצא לפי שם — מספר אישי עודכן מ-'{existing.personal_number}' ל-'{personal_number}'"
                )
            elif len(candidates) > 1:
                errors.append(
                    f"שם '{full_name}' אינו חד משמעי (מספר אישי '{personal_number}' לא נמצא)"
                )

        if errors:
            action = "error"
        elif existing is not None:
            action = "update"
        else:
            action = "new"

        if action != "error" and node is not None:
            if actor.role != "admin" and not is_node_in_actor_scope(
                session=session, actor=actor, node_id=node.id
            ):
                action = "out_of_scope"

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "warnings": warnings,
            "personal_number": personal_number,
            "full_name": full_name,
            "rank": rank,
            "gender": gender,
            "is_officer": is_officer,
            "hierarchy_node_id": str(node.id) if node is not None else None,
            "hierarchy_node_name": hierarchy_node_name,
            "enrolled_at": enrolled_at,
            "enlistment_date": enlistment_date,
            "phone": phone,
            "email": email,
            "is_career": is_career,
            "next_rank_date": next_rank_date,
            "bahad1_graduate": bahad1_graduate,
            "has_military_driving_license": has_military_driving_license,
            "military_driving_license_expiry": military_driving_license_expiry,
            "mandatory_end_date": mandatory_end_date,
            "discharge_date": discharge_date,
            "last_mitvahim_date": last_mitvahim_date,
            "last_alal_date": last_alal_date,
            "left_at": left_at,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def _resolve_duty_locations(
    session: Session,
    data: ParsedImportData,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    overrides = overrides or {}
    existing_by_name = {
        loc.name: loc for loc in session.execute(select(DutyLocation)).scalars()
    }
    out = []
    for row in data.duty_locations:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        name = field("name", row.name)
        base = field("base", row.base)
        active = field("active", row.active)

        if not name:
            errors.append("חסר שם מיקום")
        existing = existing_by_name.get(name) if name else None
        action = "error" if errors else ("update" if existing else "new")
        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": name,
            "base": base,
            "active": active,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def _resolve_range_locations(
    session: Session,
    data: ParsedImportData,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    overrides = overrides or {}
    existing_by_name = {
        loc.name: loc for loc in session.execute(select(RangeLocation)).scalars()
    }
    out = []
    for row in data.range_locations:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        name = field("name", row.name)
        active = field("active", row.active)

        if not name:
            errors.append("חסר שם מיקום מטווח")
        existing = existing_by_name.get(name) if name else None
        action = "error" if errors else ("update" if existing else "new")
        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": name,
            "active": active,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def _resolve_range_events(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    node_by_name: dict[str, str] | None = None,
    node_by_row: dict[str, str] | None = None,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    node_by_name = node_by_name or {}
    node_by_row = node_by_row or {}
    overrides = overrides or {}
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}
    locations_by_name = {loc.name: loc for loc in session.execute(select(RangeLocation)).scalars()}

    out = []
    for row in data.range_events:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        hierarchy_node_name = field("hierarchy_node_name", row.hierarchy_node_name)
        range_type = field("range_type", row.range_type)
        event_date = field("date", row.date)
        range_location_name = field("range_location_name", row.range_location_name)
        required_count = field("required_count", row.required_count)
        reserve_count = field("reserve_count", row.reserve_count)
        start_time = field("start_time", row.start_time)
        end_time = field("end_time", row.end_time)
        arrival_instructions = field("arrival_instructions", row.arrival_instructions)
        contact_name = field("contact_name", row.contact_name)
        contact_phone = field("contact_phone", row.contact_phone)
        notes = field("notes", row.notes)
        status = field("status", row.status) or RangeEventStatus.planned.value

        node = None
        if hierarchy_node_name:
            row_key = f"range_events:{row.source_row}"
            mapped_id = node_by_row.get(row_key) or node_by_name.get(hierarchy_node_name)
            if mapped_id:
                try:
                    node = session.get(HierarchyNode, uuid.UUID(mapped_id))
                except ValueError:
                    pass
            if node is None:
                node = nodes_by_name.get(hierarchy_node_name)
        if node is None:
            errors.append(f"יחידה לא מזוהה '{hierarchy_node_name}'")

        location = locations_by_name.get(range_location_name) if range_location_name else None
        if location is None:
            errors.append(f"מיקום מטווח לא מזוהה '{range_location_name}'")

        if range_type not in (rt.value for rt in RangeType):
            errors.append(f"סוג מטווח לא תקין '{range_type}'")
        if not event_date:
            errors.append("חסר תאריך")
        if status not in (s.value for s in RangeEventStatus):
            errors.append(f"סטטוס לא תקין '{status}'")

        action = "error" if errors else "new"

        if action == "new" and node is not None and actor.role != "admin":
            if not is_node_in_actor_scope(session=session, actor=actor, node_id=node.id):
                action = "out_of_scope"

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "hierarchy_node_name": hierarchy_node_name,
            "resolved_hierarchy_node_id": str(node.id) if node is not None else None,
            "range_type": range_type,
            "date": event_date,
            "range_location_name": range_location_name,
            "resolved_range_location_id": str(location.id) if location is not None else None,
            "required_count": required_count,
            "reserve_count": reserve_count,
            "start_time": start_time,
            "end_time": end_time,
            "arrival_instructions": arrival_instructions,
            "contact_name": contact_name,
            "contact_phone": contact_phone,
            "notes": notes,
            "status": status,
        })
    return out


def _resolve_range_assignments(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    resolved_range_events: list[dict],
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    overrides = overrides or {}

    soldiers_by_pn = {s.personal_number: s for s in session.execute(select(Soldier)).scalars()}
    soldiers_by_full_name: dict[str, list[Soldier]] = {}
    for s in soldiers_by_pn.values():
        soldiers_by_full_name.setdefault(s.full_name, []).append(s)

    existing_events = session.execute(select(RangeEvent)).scalars().all()
    existing_event_by_key: dict[tuple, RangeEvent] = {}
    for ev in existing_events:
        key = (ev.hierarchy_node_id, ev.range_type, ev.date.isoformat(), ev.range_location_id)
        existing_event_by_key[key] = ev

    session_event_by_key: dict[tuple, dict] = {}
    for ev_row in resolved_range_events:
        if (
            ev_row["action"] != "new"
            or not ev_row.get("resolved_hierarchy_node_id")
            or not ev_row.get("resolved_range_location_id")
        ):
            continue
        key = (
            uuid.UUID(ev_row["resolved_hierarchy_node_id"]), ev_row["range_type"],
            ev_row["date"], uuid.UUID(ev_row["resolved_range_location_id"]),
        )
        session_event_by_key[key] = ev_row

    existing_assignment_pairs = {
        (a.soldier_id, a.range_event_id) for a in session.execute(select(RangeAssignment)).scalars()
    }

    out = []
    for row in data.range_assignments:
        errors: list[str] = []
        warnings: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        personal_number = field("personal_number", row.personal_number)
        full_name = field("full_name", row.full_name)
        hierarchy_node_name = field("hierarchy_node_name", row.hierarchy_node_name)
        range_type = field("range_type", row.range_type)
        event_date = field("date", row.date)
        range_location_name = field("range_location_name", row.range_location_name)
        is_reserve = field("is_reserve", row.is_reserve)
        is_draft = field("is_draft", row.is_draft)
        attendance_status = field("attendance_status", row.attendance_status) or RangeAttendanceStatus.pending.value
        note = field("note", row.note)

        soldier = soldiers_by_pn.get(personal_number) if personal_number else None
        if soldier is not None:
            if soldier.full_name != full_name:
                errors.append(
                    f"שם מלא '{full_name}' אינו תואם לחייל עם מספר אישי '{personal_number}' ('{soldier.full_name}')"
                )
        else:
            candidates = soldiers_by_full_name.get(full_name, []) if full_name else []
            if len(candidates) == 1:
                soldier = candidates[0]
                warnings.append(f"נמצא לפי שם — מספר אישי '{personal_number}' לא נמצא")
            elif len(candidates) > 1:
                errors.append(f"מספר אישי '{personal_number}' לא נמצא ושם '{full_name}' אינו חד משמעי")
            else:
                errors.append(f"לא נמצא חייל עם מספר אישי '{personal_number}' או שם '{full_name}'")

        resolved_node = None
        if hierarchy_node_name:
            resolved_node = session.execute(
                select(HierarchyNode).where(HierarchyNode.name == hierarchy_node_name)
            ).scalar_one_or_none()
            if resolved_node is None:
                errors.append(f"יחידה לא מזוהה '{hierarchy_node_name}'")

        location = session.execute(
            select(RangeLocation).where(RangeLocation.name == range_location_name)
        ).scalar_one_or_none() if range_location_name else None
        if location is None:
            errors.append(f"מיקום מטווח לא מזוהה '{range_location_name}'")

        if range_type not in (rt.value for rt in RangeType):
            errors.append(f"סוג מטווח לא תקין '{range_type}'")

        resolved_range_event_id: str | None = None
        matched_session_row: int | None = None
        if resolved_node is not None and location is not None and event_date and range_type in (rt.value for rt in RangeType):
            key = (resolved_node.id, range_type, event_date, location.id)
            existing_match = existing_event_by_key.get(key)
            session_match = session_event_by_key.get(key)
            if existing_match is not None:
                resolved_range_event_id = str(existing_match.id)
            elif session_match is not None:
                matched_session_row = session_match["row"]
            else:
                errors.append("לא נמצא מטווח תואם (יחידה, סוג, תאריך ומיקום)")

        action = "error" if errors else "new"

        if action == "new" and soldier is not None and actor.role != "admin":
            if soldier.hierarchy_node_id is None or not is_node_in_actor_scope(
                session=session, actor=actor, node_id=soldier.hierarchy_node_id
            ):
                action = "out_of_scope"

        if (
            action == "new"
            and soldier is not None
            and resolved_range_event_id is not None
            and (soldier.id, uuid.UUID(resolved_range_event_id)) in existing_assignment_pairs
        ):
            action = "skip"

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "warnings": warnings,
            "personal_number": personal_number,
            "full_name": full_name,
            "range_type": range_type,
            "date": event_date,
            "range_location_name": range_location_name,
            "is_reserve": is_reserve,
            "is_draft": is_draft,
            "attendance_status": attendance_status,
            "note": note,
            "resolved_soldier_id": str(soldier.id) if soldier is not None else None,
            "resolved_range_event_id": resolved_range_event_id,
            "matched_session_row": matched_session_row,
        })
    return out


def _resolve_soldier_ref(
    personal_number: str | None,
    full_name: str | None,
    by_pn: dict[str, Soldier],
    by_name: dict[str, list[Soldier]],
) -> tuple[Soldier | None, str | None]:
    """personal-number-first, name-fallback soldier lookup shared by commander
    and duty-manager-ref resolution. Returns (soldier_or_None, error_or_None)."""
    if personal_number and personal_number in by_pn:
        return by_pn[personal_number], None
    if full_name:
        matches = by_name.get(full_name, [])
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, f"שם '{full_name}' מתאים ליותר מחייל אחד"
    return None, f"לא נמצא חייל (מספר אישי '{personal_number or ''}', שם '{full_name or ''}')"


def _resolve_hierarchy(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    node_by_name: dict[str, str] | None = None,
    node_by_row: dict[str, str] | None = None,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    node_by_name = node_by_name or {}
    node_by_row = node_by_row or {}
    overrides = overrides or {}
    existing_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}
    valid_levels = {
        lt.key for lt in session.execute(select(HierarchyLevelType)).scalars()
    }
    by_pn = {s.personal_number: s for s in session.execute(select(Soldier)).scalars()}
    by_name: dict[str, list[Soldier]] = {}
    for s in by_pn.values():
        by_name.setdefault(s.full_name, []).append(s)

    row_by_name = {row.name: row for row in data.hierarchy}

    out = []
    for row in data.hierarchy:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        name = field("name", row.name)
        level = field("level", row.level)
        parent_name = field("parent_name", row.parent_name)
        commander_personal_number = field("commander_personal_number", row.commander_personal_number)
        commander_name = field("commander_name", row.commander_name)

        if level not in valid_levels:
            errors.append(f"סוג יחידה לא מוכר '{level}'")

        existing = existing_by_name.get(name)

        resolved_parent_id = None
        if parent_name:
            row_key = f"hierarchy:{row.source_row}"
            mapped_id = node_by_row.get(row_key) or node_by_name.get(parent_name)
            if mapped_id:
                resolved_parent_id = mapped_id
            elif parent_name in existing_by_name:
                resolved_parent_id = str(existing_by_name[parent_name].id)
            elif parent_name in row_by_name:
                resolved_parent_id = None
            else:
                errors.append(f"יחידת אב לא מזוהה '{parent_name}'")

        resolved_commander_id = None
        if commander_personal_number or commander_name:
            soldier, err = _resolve_soldier_ref(
                commander_personal_number, commander_name, by_pn, by_name
            )
            if soldier is not None:
                resolved_commander_id = str(soldier.id)
            else:
                errors.append(f"מפקד לא מזוהה: {err}")

        dm_results = []
        for ref in row.duty_manager_refs:
            pn, _, ref_name = ref.partition(":")
            soldier, err = _resolve_soldier_ref(pn.strip(), ref_name.strip(), by_pn, by_name)
            dm_results.append({
                "ref": ref,
                "resolved_soldier_id": str(soldier.id) if soldier is not None else None,
            })
            if soldier is None:
                errors.append(f"אחראי תורנות לא מזוהה: {err}")

        action: str
        if errors:
            action = "error"
        elif existing is not None:
            action = "update"
        else:
            action = "new"

        if action != "error" and existing is not None and actor.role != "admin":
            if not is_node_in_actor_scope(session=session, actor=actor, node_id=existing.id):
                action = "out_of_scope"
        elif action == "new" and actor.role != "admin" and resolved_parent_id:
            try:
                if not is_node_in_actor_scope(
                    session=session, actor=actor, node_id=uuid.UUID(resolved_parent_id)
                ):
                    action = "out_of_scope"
            except ValueError:
                pass
        elif action == "new" and actor.role != "admin" and not resolved_parent_id:
            action = "out_of_scope"

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": name,
            "level": level,
            "parent_name": parent_name,
            "resolved_parent_id": resolved_parent_id,
            "commander_personal_number": commander_personal_number,
            "commander_name": commander_name,
            "resolved_commander_id": resolved_commander_id,
            "duty_manager_refs": dm_results,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def _resolve_duty_types(
    session: Session,
    data: ParsedImportData,
    node_by_name: dict[str, str] | None = None,
    node_by_row: dict[str, str] | None = None,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    node_by_name = node_by_name or {}
    node_by_row = node_by_row or {}
    overrides = overrides or {}
    existing_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}

    out = []
    for row in data.duty_types:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        name = field("name", row.name)
        raw_score = field("score_per_day", row.score_per_day)
        raw_reserve_ratio = field("reserve_ratio", row.reserve_ratio)
        raw_requirements_json = field("requirements_json", row.requirements_json)
        eligible_unit_names = field("eligible_unit_names", row.eligible_unit_names)

        score_per_day: Decimal | None = None
        try:
            score_per_day = Decimal(raw_score) if raw_score else None
            if score_per_day is None:
                errors.append("חסר ניקוד ליום")
        except Exception:
            errors.append(f"ניקוד ליום לא תקין '{raw_score}'")

        reserve_ratio: Decimal | None = None
        if raw_reserve_ratio is not None and raw_reserve_ratio != "":
            try:
                reserve_ratio = Decimal(raw_reserve_ratio)
            except Exception:
                errors.append(f"יחס רזרבה לא תקין '{raw_reserve_ratio}'")

        requirements: dict | None = field("requirements", None)
        if requirements is None and raw_requirements_json:
            try:
                requirements = json.loads(raw_requirements_json)
            except Exception as exc:
                errors.append(f"JSON לא תקין בעמודת requirements_json: {exc}")

        resolved_eligible_node_ids: list[str] = field("resolved_eligible_node_ids", None) or []
        if "resolved_eligible_node_ids" not in override:
            resolved_eligible_node_ids = []
            for unit_name in eligible_unit_names:
                row_key = f"duty_types:{row.source_row}:{unit_name}"
                mapped_id = node_by_row.get(row_key) or node_by_name.get(unit_name)
                node = None
                if mapped_id:
                    try:
                        node = session.get(HierarchyNode, uuid.UUID(mapped_id))
                    except ValueError:
                        pass
                if node is None:
                    node = nodes_by_name.get(unit_name)
                if node is None:
                    errors.append(f"יחידה זכאית לא מזוהה '{unit_name}'")
                else:
                    resolved_eligible_node_ids.append(str(node.id))

        existing = existing_by_name.get(name) if name else None
        action = "error" if errors else ("update" if existing else "new")

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": name,
            "score_per_day": str(score_per_day) if score_per_day is not None else None,
            "description": field("description", row.description),
            "active": field("active", row.active),
            "reserve_ratio": str(reserve_ratio) if reserve_ratio is not None else None,
            "reserve_minimum": field("reserve_minimum", row.reserve_minimum),
            "is_external": field("is_external", row.is_external),
            "contact_name": field("contact_name", row.contact_name),
            "contact_phone": field("contact_phone", row.contact_phone),
            "start_time": field("start_time", row.start_time),
            "end_time": field("end_time", row.end_time),
            "instructions": field("instructions", row.instructions),
            "resolved_eligible_node_ids": resolved_eligible_node_ids,
            "requirements": requirements,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def _resolve_exemption_types(
    session: Session,
    data: ParsedImportData,
    dt_by_name: dict[str, str] | None = None,
    dt_by_row: dict[str, str] | None = None,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    """Resolve exemption types from import data.

    Matches by name (unique constraint on exemption_types.name).
    Resolves applies_to_duty_type_names to duty type IDs from both DB and import sheet.
    """
    dt_by_name = dt_by_name or {}
    dt_by_row = dt_by_row or {}
    overrides = overrides or {}
    existing_by_name = {et.name: et for et in session.execute(select(ExemptionType)).scalars()}
    duty_types_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}

    out = []
    for row in data.exemption_types:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        name = field("name", row.name)
        applies_to_duty_type_names = field("applies_to_duty_type_names", row.applies_to_duty_type_names)

        resolved_duty_type_ids: list[str] = field("resolved_duty_type_ids", None) or []
        if "resolved_duty_type_ids" not in override:
            resolved_duty_type_ids = []
            for duty_type_name in applies_to_duty_type_names:
                row_key = f"exemption_types:{row.source_row}:{duty_type_name}"
                mapped_id = dt_by_row.get(row_key) or dt_by_name.get(duty_type_name)
                duty_type = None
                if mapped_id:
                    try:
                        duty_type = session.get(DutyType, uuid.UUID(mapped_id))
                    except ValueError:
                        pass
                if duty_type is None:
                    duty_type = duty_types_by_name.get(duty_type_name)
                if duty_type is None:
                    errors.append(f"סוג חובה לא מזוהה '{duty_type_name}' (applies_to)")
                else:
                    resolved_duty_type_ids.append(str(duty_type.id))

        is_global_raw = field("is_global", row.is_global)
        is_medical_raw = field("is_medical", row.is_medical)
        is_commander_exemption_raw = field("is_commander_exemption", row.is_commander_exemption)
        is_global = is_global_raw if is_global_raw is not None else False
        is_medical = is_medical_raw if is_medical_raw is not None else False
        is_commander_exemption = is_commander_exemption_raw if is_commander_exemption_raw is not None else False

        existing = existing_by_name.get(name) if name else None
        action = "error" if errors else ("update" if existing else "new")

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": name,
            "description": field("description", row.description),
            "is_global": is_global,
            "is_medical": is_medical,
            "is_commander_exemption": is_commander_exemption,
            "resolved_duty_type_ids": resolved_duty_type_ids,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def _resolve_duty_shifts(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    dt_by_name: dict[str, str] | None = None,
    dt_by_row: dict[str, str] | None = None,
    node_by_name: dict[str, str] | None = None,
    node_by_row: dict[str, str] | None = None,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    dt_by_name = dt_by_name or {}
    dt_by_row = dt_by_row or {}
    node_by_name = node_by_name or {}
    node_by_row = node_by_row or {}
    overrides = overrides or {}
    duty_types_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}
    locations_by_name = {loc.name: loc for loc in session.execute(select(DutyLocation)).scalars()}
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}

    out = []
    for row in data.duty_shifts:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        duty_type_name = field("duty_type_name", row.duty_type_name)
        duty_location_name = field("duty_location_name", row.duty_location_name)
        start_date = field("start_date", row.start_date)
        end_date = field("end_date", row.end_date)
        start_time = field("start_time", row.start_time)
        end_time = field("end_time", row.end_time)
        required_count = field("required_count", row.required_count)
        notes = field("notes", row.notes)

        duty_type = None
        if duty_type_name:
            row_key = f"duty_shifts:{row.source_row}"
            mapped_id = dt_by_row.get(row_key) or dt_by_name.get(duty_type_name)
            if mapped_id:
                try:
                    duty_type = session.get(DutyType, uuid.UUID(mapped_id))
                except ValueError:
                    pass
            if duty_type is None:
                duty_type = duty_types_by_name.get(duty_type_name)
        if duty_type is None:
            errors.append(f"סוג תורנות לא מזוהה '{duty_type_name}'")

        location = locations_by_name.get(duty_location_name) if duty_location_name else None
        if location is None:
            errors.append(f"מיקום תורנות לא מזוהה '{duty_location_name}'")

        if not start_date:
            errors.append("חסר תאריך התחלה")
        if not end_date:
            errors.append("חסר תאריך סיום")

        quota_dicts = []
        quota_total = 0
        for q in row.node_quotas:
            quota_key = f"duty_shifts:{row.source_row}:{q.node_name}"
            mapped_node_id = node_by_row.get(quota_key) or node_by_name.get(q.node_name)
            node = None
            if mapped_node_id:
                try:
                    node = session.get(HierarchyNode, uuid.UUID(mapped_node_id))
                except ValueError:
                    pass
            if node is None:
                node = nodes_by_name.get(q.node_name)
            quota_dicts.append({
                "node_name": q.node_name,
                "node_id": str(node.id) if node is not None else None,
                "count": q.count,
                "resolved": node is not None,
            })
            quota_total += q.count

        if quota_total > required_count:
            errors.append(
                f"סה\"כ מכסות ({quota_total}) גדול מהכמות הנדרשת ({required_count})"
            )

        action = "error" if errors else "new"

        if action == "new" and actor.role != "admin":
            resolved_node_ids = [
                uuid.UUID(qd["node_id"]) for qd in quota_dicts if qd["resolved"]
            ]
            for node_id in resolved_node_ids:
                # Same per-row trade-off as in _resolve_soldiers above: this calls
                # is_node_in_actor_scope (and thus scope_root_ids) per node_id rather
                # than hoisting scope_root_ids(session, actor) out of the loop.
                # Acceptable for typical import volumes; revisit if row counts grow.
                if not is_node_in_actor_scope(session=session, actor=actor, node_id=node_id):
                    action = "out_of_scope"
                    break

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "duty_type_name": duty_type_name,
            "resolved_duty_type_id": str(duty_type.id) if duty_type is not None else None,
            "duty_location_name": duty_location_name,
            "resolved_duty_location_id": str(location.id) if location is not None else None,
            "start_date": start_date,
            "end_date": end_date,
            "start_time": start_time,
            "end_time": end_time,
            "required_count": required_count,
            "node_quotas": quota_dicts,
            "notes": notes,
        })
    return out


def _resolve_shift_templates(
    session: Session,
    data: ParsedImportData,
    dt_by_name: dict[str, str] | None = None,
    dt_by_row: dict[str, str] | None = None,
    node_by_name: dict[str, str] | None = None,
    node_by_row: dict[str, str] | None = None,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    dt_by_name = dt_by_name or {}
    dt_by_row = dt_by_row or {}
    node_by_name = node_by_name or {}
    node_by_row = node_by_row or {}
    overrides = overrides or {}
    duty_types_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}
    locations_by_name = {loc.name: loc for loc in session.execute(select(DutyLocation)).scalars()}
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}
    existing_by_name = {tpl.name: tpl for tpl in session.execute(select(ShiftTemplate)).scalars()}

    out = []
    for row in data.shift_templates:
        errors: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        name = field("name", row.name)
        duty_type_name = field("duty_type_name", row.duty_type_name)
        duty_location_name = field("duty_location_name", row.duty_location_name)
        recurrence_type = field("recurrence_type", row.recurrence_type)
        eligible_unit_names = field("eligible_unit_names", row.eligible_unit_names)

        duty_type = None
        if duty_type_name:
            row_key = f"shift_templates:{row.source_row}"
            mapped_id = dt_by_row.get(row_key) or dt_by_name.get(duty_type_name)
            if mapped_id:
                try:
                    duty_type = session.get(DutyType, uuid.UUID(mapped_id))
                except ValueError:
                    pass
            if duty_type is None:
                duty_type = duty_types_by_name.get(duty_type_name)
        if duty_type is None:
            errors.append(f"סוג תורנות לא מזוהה '{duty_type_name}'")

        location = locations_by_name.get(duty_location_name) if duty_location_name else None
        if location is None:
            errors.append(f"מיקום תורנות לא מזוהה '{duty_location_name}'")

        if recurrence_type is not None and recurrence_type not in ("daily", "weekdays", "weekly"):
            # A blank cell (None) means "leave unchanged" on an update row, or
            # "apply the create-time default" on a new row (both handled where
            # the resolved row is consumed) — only an explicit-but-invalid
            # value is an error here.
            errors.append(f"סוג חזרתיות לא תקין '{recurrence_type}'")

        resolved_eligible_node_ids: list[str] = field("resolved_eligible_node_ids", None) or []
        if "resolved_eligible_node_ids" not in override:
            resolved_eligible_node_ids = []
            for unit_name in eligible_unit_names:
                row_key = f"shift_templates:{row.source_row}:{unit_name}"
                mapped_id = node_by_row.get(row_key) or node_by_name.get(unit_name)
                node = None
                if mapped_id:
                    try:
                        node = session.get(HierarchyNode, uuid.UUID(mapped_id))
                    except ValueError:
                        pass
                if node is None:
                    node = nodes_by_name.get(unit_name)
                if node is None:
                    errors.append(f"יחידה זכאית לא מזוהה '{unit_name}'")
                else:
                    resolved_eligible_node_ids.append(str(node.id))

        existing = existing_by_name.get(name) if name else None
        action = "error" if errors else ("update" if existing else "new")

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": name,
            "duty_type_name": duty_type_name,
            "resolved_duty_type_id": str(duty_type.id) if duty_type is not None else None,
            "duty_location_name": duty_location_name,
            "resolved_duty_location_id": str(location.id) if location is not None else None,
            "recurrence_type": recurrence_type,
            "weekdays": field("weekdays", row.weekdays),
            "start_time": field("start_time", row.start_time),
            "end_time": field("end_time", row.end_time),
            "required_count": field("required_count", row.required_count),
            "auto_roll": field("auto_roll", row.auto_roll),
            "auto_roll_until": field("auto_roll_until", row.auto_roll_until),
            "duration_days": field("duration_days", row.duration_days),
            "notes": field("notes", row.notes),
            "resolved_eligible_node_ids": resolved_eligible_node_ids,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def _resolve_assignments(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    resolved_duty_shifts: list[dict],
    dt_by_name: dict[str, str] | None = None,
    dt_by_row: dict[str, str] | None = None,
    overrides: dict[str, dict] | None = None,
) -> list[dict]:
    dt_by_name = dt_by_name or {}
    dt_by_row = dt_by_row or {}
    overrides = overrides or {}

    def _default_time(value: str | None, default: str) -> str:
        return value if value else default

    soldiers_by_pn = {s.personal_number: s for s in session.execute(select(Soldier)).scalars()}
    soldiers_by_full_name: dict[str, list[Soldier]] = {}
    for s in soldiers_by_pn.values():
        soldiers_by_full_name.setdefault(s.full_name, []).append(s)
    duty_types_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}
    locations_by_name = {loc.name: loc for loc in session.execute(select(DutyLocation)).scalars()}

    existing_shifts = session.execute(select(DutyShift)).scalars().all()
    existing_shift_by_key: dict[tuple, DutyShift] = {}
    for shift in existing_shifts:
        key = (
            shift.duty_type_id, shift.duty_location_id,
            shift.start_date.isoformat(), shift.end_date.isoformat(),
            shift.start_time, shift.end_time,
        )
        existing_shift_by_key[key] = shift

    session_shift_by_key: dict[tuple, dict] = {}
    for shift_row in resolved_duty_shifts:
        if (
            shift_row["action"] != "new"
            or not shift_row.get("resolved_duty_type_id")
            or not shift_row.get("resolved_duty_location_id")
        ):
            continue
        key = (
            uuid.UUID(shift_row["resolved_duty_type_id"]),
            uuid.UUID(shift_row["resolved_duty_location_id"]),
            shift_row["start_date"], shift_row["end_date"],
            _default_time(shift_row.get("start_time"), "00:00"),
            _default_time(shift_row.get("end_time"), "23:59"),
        )
        session_shift_by_key[key] = shift_row

    existing_assignment_pairs = {
        (a.soldier_id, a.duty_shift_id)
        for a in session.execute(select(DutyAssignment)).scalars()
        if a.duty_shift_id is not None
    }
    running_count: dict[str, int] = {}
    for (_, shift_id) in existing_assignment_pairs:
        key = f"existing:{shift_id}"
        running_count[key] = running_count.get(key, 0) + 1

    out = []
    for row in data.assignments:
        errors: list[str] = []
        warnings: list[str] = []
        override = overrides.get(str(row.source_row), {})

        def field(name: str, default):
            return override[name] if name in override else default

        personal_number = field("personal_number", row.personal_number)
        full_name = field("full_name", row.full_name)
        duty_type_name = field("duty_type_name", row.duty_type_name)
        duty_location_name = field("duty_location_name", row.duty_location_name)
        start_date = field("start_date", row.start_date)
        end_date = field("end_date", row.end_date)
        start_time = field("start_time", row.start_time)
        end_time = field("end_time", row.end_time)
        is_reserve = field("is_reserve", row.is_reserve)
        notes = field("notes", row.notes)

        soldier = soldiers_by_pn.get(personal_number) if personal_number else None
        if soldier is not None:
            if soldier.full_name != full_name:
                errors.append(
                    f"שם מלא '{full_name}' אינו תואם לחייל עם מספר אישי "
                    f"'{personal_number}' ('{soldier.full_name}')"
                )
        else:
            candidates = soldiers_by_full_name.get(full_name, []) if full_name else []
            if len(candidates) == 1:
                soldier = candidates[0]
                warnings.append(f"נמצא לפי שם — מספר אישי '{personal_number}' לא נמצא")
            elif len(candidates) > 1:
                errors.append(
                    f"מספר אישי '{personal_number}' לא נמצא ושם '{full_name}' אינו חד משמעי"
                )
            else:
                errors.append(
                    f"לא נמצא חייל עם מספר אישי '{personal_number}' או שם '{full_name}'"
                )

        duty_type = None
        if duty_type_name:
            row_key = f"assignments:{row.source_row}"
            mapped_id = dt_by_row.get(row_key) or dt_by_name.get(duty_type_name)
            if mapped_id:
                try:
                    duty_type = session.get(DutyType, uuid.UUID(mapped_id))
                except ValueError:
                    pass
            if duty_type is None:
                duty_type = duty_types_by_name.get(duty_type_name)
        if duty_type is None:
            errors.append(f"סוג תורנות לא מזוהה '{duty_type_name}'")

        location = locations_by_name.get(duty_location_name) if duty_location_name else None
        if location is None:
            errors.append(f"מיקום תורנות לא מזוהה '{duty_location_name}'")

        resolved_duty_shift_id: str | None = None
        matched_session_row: int | None = None
        shift_key_str: str | None = None
        required_count: int | None = None
        if duty_type is not None and location is not None and start_date and end_date:
            key = (
                duty_type.id, location.id, start_date, end_date,
                _default_time(start_time, "00:00"),
                _default_time(end_time, "23:59"),
            )
            existing_match = existing_shift_by_key.get(key)
            session_match = session_shift_by_key.get(key)
            if existing_match is not None:
                resolved_duty_shift_id = str(existing_match.id)
                shift_key_str = f"existing:{existing_match.id}"
                required_count = existing_match.required_count
            elif session_match is not None:
                matched_session_row = session_match["row"]
                shift_key_str = f"session_row:{matched_session_row}"
                required_count = session_match["required_count"]
            else:
                errors.append("לא נמצאה משמרת תואמת (סוג תורנות, מיקום, תאריכים ושעות)")

        action = "error" if errors else "new"

        if action == "new" and soldier is not None and actor.role != "admin":
            if soldier.hierarchy_node_id is None or not is_node_in_actor_scope(
                session=session, actor=actor, node_id=soldier.hierarchy_node_id
            ):
                action = "out_of_scope"

        if (
            action == "new"
            and soldier is not None
            and resolved_duty_shift_id is not None
            and (soldier.id, uuid.UUID(resolved_duty_shift_id)) in existing_assignment_pairs
        ):
            action = "skip"

        if action == "new" and shift_key_str is not None and required_count is not None:
            current = running_count.get(shift_key_str, 0)
            if current >= required_count:
                warnings.append(f"למשמרת כבר משויכים {current}/{required_count} חיילים")
            running_count[shift_key_str] = current + 1

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "warnings": warnings,
            "personal_number": personal_number,
            "full_name": full_name,
            "duty_type_name": duty_type_name,
            "duty_location_name": duty_location_name,
            "start_date": start_date,
            "end_date": end_date,
            "start_time": start_time,
            "end_time": end_time,
            "is_reserve": is_reserve,
            "notes": notes,
            "resolved_soldier_id": str(soldier.id) if soldier is not None else None,
            "resolved_duty_shift_id": resolved_duty_shift_id,
            "matched_session_row": matched_session_row,
        })
    return out


def _resolve_and_score(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    selections: dict | None = None,
) -> dict:
    nm = (selections or {}).get("_name_mappings", {})
    fo = (selections or {}).get("_field_overrides", {})
    dt_by_name  = nm.get("duty_type", {}).get("by_name", {})
    dt_by_row   = nm.get("duty_type", {}).get("by_row", {})
    node_by_name = nm.get("hierarchy_node", {}).get("by_name", {})
    node_by_row  = nm.get("hierarchy_node", {}).get("by_row", {})
    duty_shifts = _resolve_duty_shifts(session, data, actor, dt_by_name, dt_by_row, node_by_name, node_by_row, fo.get("duty_shifts", {}))
    range_events = _resolve_range_events(session, data, actor, node_by_name, node_by_row, fo.get("range_events", {}))
    return {
        "soldiers": _resolve_soldiers(session, data, actor, node_by_name, node_by_row, fo.get("soldiers", {})),
        "duty_shifts": duty_shifts,
        "shift_templates": _resolve_shift_templates(
            session, data, dt_by_name, dt_by_row, node_by_name, node_by_row, fo.get("shift_templates", {})
        ),
        "assignments": _resolve_assignments(session, data, actor, duty_shifts, dt_by_name, dt_by_row, fo.get("assignments", {})),
        "duty_locations": _resolve_duty_locations(session, data, fo.get("duty_locations", {})),
        "hierarchy": _resolve_hierarchy(session, data, actor, node_by_name, node_by_row, fo.get("hierarchy", {})),
        "duty_types": _resolve_duty_types(session, data, node_by_name, node_by_row, fo.get("duty_types", {})),
        "exemption_types": _resolve_exemption_types(session, data, dt_by_name, dt_by_row, fo.get("exemption_types", {})),
        "system_settings": resolve_system_settings(session, data, actor, fo.get("system_settings", {})),
        "bug_reports": resolve_bug_reports(session, data, actor, fo.get("bug_reports", {})),
        "personal_constraints": resolve_personal_constraints(session, data, fo.get("personal_constraints", {})),
        "soldier_field_updates": resolve_soldier_field_updates(session, data, fo.get("soldier_field_updates", {})),
        "soldier_enrollment_requests": resolve_soldier_enrollment_requests(session, data, fo.get("soldier_enrollment_requests", {})),
        "soldier_exemptions": resolve_soldier_exemptions(session, data, fo.get("soldier_exemptions", {})),
        "exemption_requests": resolve_exemption_requests(session, data, fo.get("exemption_requests", {})),
        "swap_requests": resolve_swap_requests(session, data, fo.get("swap_requests", {})),
        "range_locations": _resolve_range_locations(session, data, fo.get("range_locations", {})),
        "range_events": range_events,
        "range_assignments": _resolve_range_assignments(session, data, actor, range_events, fo.get("range_assignments", {})),
        "parser_id": data.parser_id,
        "parser_warnings": data.parser_warnings,
    }


def create_session(
    session: Session,
    *,
    filename: str,
    content: bytes,
    actor: Soldier,
    parser_id: str | None = None,
) -> ImportSession:
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    parser = get_parser(parser_id) if parser_id else auto_detect_parser(wb)
    data = parser.parse(wb)
    parsed_state = _resolve_and_score(session, data, actor)

    import_session = ImportSession(
        status="draft",
        filename=filename,
        raw_excel=content,
        parsed_state=parsed_state,
        user_selections={},
        created_links={},
        created_by=actor.id,
    )
    session.add(import_session)
    session.flush()
    return import_session


def reparse_session(session: Session, *, session_id: uuid.UUID, actor: Soldier) -> ImportSession:
    import_session = session.get(ImportSession, session_id)
    if import_session is None:
        raise ImportSessionError("session_not_found")
    if import_session.status != "draft":
        raise ImportSessionError("only_draft_sessions_can_be_reparsed")

    wb = openpyxl.load_workbook(io.BytesIO(import_session.raw_excel), data_only=True)
    parser = get_parser(import_session.parsed_state["parser_id"])
    data = parser.parse(wb)
    parsed_state = _resolve_and_score(session, data, actor, selections=import_session.user_selections)

    import_session.parsed_state = parsed_state
    session.flush()
    return import_session


def set_selections(
    session: Session, *, session_id: uuid.UUID, selections: dict
) -> ImportSession:
    import_session = session.get(ImportSession, session_id)
    if import_session is None:
        raise ImportSessionError("session_not_found")

    import_session.user_selections = selections
    session.flush()
    return import_session


def _effective_action(selections: dict, group: str, row: dict) -> str:
    return selections.get(group, {}).get(str(row["row"]), row["action"])


def confirm_session(
    session: Session, *, session_id: uuid.UUID, actor: Soldier
) -> dict:
    import_session = session.get(ImportSession, session_id)
    if import_session is None:
        raise ImportSessionError("session_not_found")
    if import_session.status != "draft":
        raise ImportSessionError("only_draft_sessions_can_be_confirmed")

    selections = import_session.user_selections or {}
    state = import_session.parsed_state

    created = 0
    updated = 0
    skipped = 0
    errors: list[dict] = []
    created_soldiers: list[str] = []
    created_duty_shifts: list[str] = []
    created_assignments: list[str] = []
    created_shift_templates: list[str] = []
    shift_row_to_id: dict[int, uuid.UUID] = {}

    # ── Soldiers ────────────────────────────────────────────────────────
    for row in state.get("soldiers", []):
        effective = _effective_action(selections, "soldiers", row)
        if row["action"] in ("error", "out_of_scope") or effective == "skip":
            skipped += 1
            continue
        try:
            if effective == "new":
                new_soldier = Soldier(
                    personal_number=row["personal_number"],
                    full_name=row["full_name"],
                    password_hash=hash_password(secrets.token_hex(16)),
                    must_change_password=True,
                    rank=row.get("rank"),
                    gender=row.get("gender"),
                    is_officer=row.get("is_officer"),
                    hierarchy_node_id=(
                        uuid.UUID(row["hierarchy_node_id"])
                        if row.get("hierarchy_node_id")
                        else None
                    ),
                    phone=row.get("phone"),
                    email=row.get("email"),
                    is_career=row.get("is_career") or False,
                    bahad1_graduate=row.get("bahad1_graduate") or False,
                    has_military_driving_license=row.get("has_military_driving_license"),
                )
                if row.get("enrolled_at"):
                    new_soldier.enrolled_at = date_type.fromisoformat(row["enrolled_at"])
                if row.get("enlistment_date"):
                    new_soldier.enlistment_date = date_type.fromisoformat(row["enlistment_date"])
                if row.get("next_rank_date"):
                    new_soldier.next_rank_date = date_type.fromisoformat(row["next_rank_date"])
                if row.get("military_driving_license_expiry"):
                    new_soldier.military_driving_license_expiry = date_type.fromisoformat(
                        row["military_driving_license_expiry"]
                    )
                if row.get("mandatory_end_date"):
                    new_soldier.mandatory_end_date = date_type.fromisoformat(row["mandatory_end_date"])
                if row.get("discharge_date"):
                    new_soldier.discharge_date = date_type.fromisoformat(row["discharge_date"])
                if row.get("last_mitvahim_date"):
                    new_soldier.last_mitvahim_date = date_type.fromisoformat(row["last_mitvahim_date"])
                if row.get("last_alal_date"):
                    new_soldier.last_alal_date = date_type.fromisoformat(row["last_alal_date"])
                if row.get("left_at"):
                    new_soldier.left_at = date_type.fromisoformat(row["left_at"])
                session.add(new_soldier)
                session.flush()
                created += 1
                created_soldiers.append(str(new_soldier.id))
            elif effective == "update" and row.get("existing_id"):
                s = session.get(Soldier, uuid.UUID(row["existing_id"]))
                if s is not None:
                    s.personal_number = row["personal_number"]
                    s.full_name = row["full_name"]
                    if row.get("rank") is not None:
                        s.rank = row["rank"]
                    if row.get("gender") is not None:
                        s.gender = row["gender"]
                    if row.get("is_officer") is not None:
                        s.is_officer = row["is_officer"]
                    if row.get("hierarchy_node_id") is not None:
                        s.hierarchy_node_id = uuid.UUID(row["hierarchy_node_id"])
                    if row.get("phone") is not None:
                        s.phone = row["phone"]
                    if row.get("email") is not None:
                        s.email = row["email"]
                    if row.get("is_career") is not None:
                        s.is_career = row["is_career"]
                    if row.get("bahad1_graduate") is not None:
                        s.bahad1_graduate = row["bahad1_graduate"]
                    if row.get("has_military_driving_license") is not None:
                        s.has_military_driving_license = row["has_military_driving_license"]
                    if row.get("enrolled_at"):
                        s.enrolled_at = date_type.fromisoformat(row["enrolled_at"])
                    if row.get("enlistment_date"):
                        s.enlistment_date = date_type.fromisoformat(row["enlistment_date"])
                    if row.get("next_rank_date"):
                        s.next_rank_date = date_type.fromisoformat(row["next_rank_date"])
                    if row.get("military_driving_license_expiry"):
                        s.military_driving_license_expiry = date_type.fromisoformat(
                            row["military_driving_license_expiry"]
                        )
                    if row.get("mandatory_end_date"):
                        s.mandatory_end_date = date_type.fromisoformat(row["mandatory_end_date"])
                    if row.get("discharge_date"):
                        s.discharge_date = date_type.fromisoformat(row["discharge_date"])
                    if row.get("last_mitvahim_date"):
                        s.last_mitvahim_date = date_type.fromisoformat(row["last_mitvahim_date"])
                    if row.get("last_alal_date"):
                        s.last_alal_date = date_type.fromisoformat(row["last_alal_date"])
                    if row.get("left_at"):
                        s.left_at = date_type.fromisoformat(row["left_at"])
                    session.flush()
                    updated += 1
                    created_soldiers.append(str(s.id))
                else:
                    skipped += 1
            else:
                skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "soldiers", "error": str(exc)})

    # ── Duty shifts ─────────────────────────────────────────────────────
    for row in state.get("duty_shifts", []):
        effective = _effective_action(selections, "duty_shifts", row)
        if row["action"] in ("error", "out_of_scope") or effective == "skip":
            skipped += 1
            continue
        if effective != "new":
            skipped += 1
            continue
        try:
            # Nested transaction (SAVEPOINT): shift creation and quota
            # application are two separate writes. If the quota write fails
            # after the shift has already been flushed, we must not leave a
            # partially-created DutyShift (without its quotas) in the
            # session for the caller's eventual outer commit. Wrapping both
            # steps in begin_nested() means any exception rolls back only
            # this row's SAVEPOINT, leaving previously-successful rows and
            # the outer session/transaction untouched.
            with session.begin_nested():
                shift = DutyShift(
                    duty_type_id=uuid.UUID(row["resolved_duty_type_id"]),
                    duty_location_id=uuid.UUID(row["resolved_duty_location_id"]),
                    start_date=date_type.fromisoformat(row["start_date"]),
                    end_date=date_type.fromisoformat(row["end_date"]),
                    required_count=row["required_count"],
                    notes=row.get("notes"),
                )
                if row.get("start_time"):
                    shift.start_time = row["start_time"]
                if row.get("end_time"):
                    shift.end_time = row["end_time"]
                session.add(shift)
                session.flush()

                resolved_quotas = [
                    (uuid.UUID(q["node_id"]), q["count"])
                    for q in row.get("node_quotas", [])
                    if q.get("resolved")
                ]
                if resolved_quotas:
                    set_shift_quotas(
                        session, shift_id=shift.id, quotas=resolved_quotas, actor_id=actor.id
                    )

            created += 1
            created_duty_shifts.append(str(shift.id))
            shift_row_to_id[row["row"]] = shift.id
        except Exception as exc:
            errors.append({"row": row["row"], "type": "duty_shifts", "error": str(exc)})

    # ── Assignments ─────────────────────────────────────────────────────
    for row in state.get("assignments", []):
        effective = _effective_action(selections, "assignments", row)
        if row["action"] in ("error", "out_of_scope") or effective == "skip":
            skipped += 1
            continue
        if effective != "new":
            skipped += 1
            continue
        try:
            if row.get("resolved_duty_shift_id"):
                duty_shift_id = uuid.UUID(row["resolved_duty_shift_id"])
            elif row.get("matched_session_row") is not None:
                mapped = shift_row_to_id.get(row["matched_session_row"])
                if mapped is None:
                    errors.append({
                        "row": row["row"], "type": "assignments",
                        "error": "המשמרת המתאימה לא נוצרה (דולגה או נכשלה)",
                    })
                    continue
                duty_shift_id = mapped
            else:
                errors.append({
                    "row": row["row"], "type": "assignments", "error": "לא נמצאה משמרת תואמת",
                })
                continue

            # Nested transaction (SAVEPOINT), same rationale as the duty_shifts
            # loop above: isolates this row's write so a flush-time failure
            # can't poison the outer session/transaction for subsequent rows.
            with session.begin_nested():
                shift = session.get(DutyShift, duty_shift_id)
                assignment = DutyAssignment(
                    soldier_id=uuid.UUID(row["resolved_soldier_id"]),
                    duty_type_id=shift.duty_type_id,
                    duty_location_id=shift.duty_location_id,
                    duty_shift_id=duty_shift_id,
                    start_date=shift.start_date,
                    end_date=shift.end_date,
                    is_reserve=row.get("is_reserve") or False,
                    notes=row.get("notes"),
                )
                if shift.start_time:
                    assignment.start_time = shift.start_time
                if shift.end_time:
                    assignment.end_time = shift.end_time
                session.add(assignment)
                session.flush()

            created += 1
            created_assignments.append(str(assignment.id))
        except Exception as exc:
            errors.append({"row": row["row"], "type": "assignments", "error": str(exc)})

    # ── Duty locations ─────────────────────────────────────────────────
    for row in state.get("duty_locations", []):
        effective = _effective_action(selections, "duty_locations", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                if effective == "new":
                    new_loc = create_location(
                        session, name=row["name"], base=row.get("base"), actor_id=actor.id,
                    )
                    if row.get("active") is not None:
                        new_loc.active = row["active"]
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    loc = session.get(DutyLocation, uuid.UUID(row["existing_id"]))
                    if loc is not None:
                        update_location(
                            session, location=loc, name=None, base=row.get("base"), actor_id=actor.id,
                        )
                        if row.get("active") is not None:
                            loc.active = row["active"]
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "duty_locations", "error": str(exc)})

    # ── Duty types ──────────────────────────────────────────────────────
    for row in state.get("duty_types", []):
        effective = _effective_action(selections, "duty_types", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                eligible_ids = [uuid.UUID(nid) for nid in row.get("resolved_eligible_node_ids", [])] or None
                start_time = (
                    datetime.strptime(row["start_time"], "%H:%M").time() if row.get("start_time") else None
                )
                end_time = (
                    datetime.strptime(row["end_time"], "%H:%M").time() if row.get("end_time") else None
                )
                if effective == "new":
                    new_dt = create_duty_type(
                        session,
                        name=row["name"],
                        score_per_day=Decimal(row["score_per_day"]),
                        description=row.get("description"),
                        reserve_ratio=Decimal(row["reserve_ratio"]) if row.get("reserve_ratio") else Decimal("0.000"),
                        reserve_minimum=row.get("reserve_minimum") or 0,
                        contact_name=row.get("contact_name"),
                        contact_phone=row.get("contact_phone"),
                        start_time=start_time,
                        end_time=end_time,
                        instructions=row.get("instructions"),
                        is_external=bool(row.get("is_external")),
                        eligible_node_ids=eligible_ids,
                        requirements=row.get("requirements"),
                        actor_id=actor.id,
                    )
                    if row.get("active") is not None:
                        new_dt.active = row["active"]
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    dt = session.get(DutyType, uuid.UUID(row["existing_id"]))
                    if dt is not None:
                        update_duty_type(
                            session,
                            duty_type=dt,
                            name=None,
                            score_per_day=Decimal(row["score_per_day"]) if row.get("score_per_day") else None,
                            description=row.get("description"),
                            reserve_ratio=Decimal(row["reserve_ratio"]) if row.get("reserve_ratio") else None,
                            reserve_minimum=row.get("reserve_minimum"),
                            contact_name=row.get("contact_name"),
                            contact_phone=row.get("contact_phone"),
                            start_time=start_time,
                            end_time=end_time,
                            instructions=row.get("instructions"),
                            is_external=row.get("is_external"),
                            eligible_node_ids=eligible_ids if row.get("resolved_eligible_node_ids") else ...,
                            requirements=row.get("requirements"),
                            actor_id=actor.id,
                        )
                        if row.get("active") is not None:
                            dt.active = row["active"]
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "duty_types", "error": str(exc)})

    # ── Shift templates ─────────────────────────────────────────────────
    for row in state.get("shift_templates", []):
        effective = _effective_action(selections, "shift_templates", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                eligible_ids = [uuid.UUID(nid) for nid in row.get("resolved_eligible_node_ids", [])] or None
                if effective == "new":
                    tpl = create_template(
                        session,
                        name=row["name"],
                        duty_type_id=uuid.UUID(row["resolved_duty_type_id"]),
                        duty_location_id=uuid.UUID(row["resolved_duty_location_id"]),
                        recurrence_type=row.get("recurrence_type") or "weekdays",
                        weekdays=row.get("weekdays") or [],
                        duration_days=row.get("duration_days") or 1,
                        start_time=row.get("start_time") or "00:00",
                        end_time=row.get("end_time") or "23:59",
                        required_count=row.get("required_count") or 1,
                        auto_roll=bool(row.get("auto_roll")),
                        auto_roll_until=(
                            date_type.fromisoformat(row["auto_roll_until"])
                            if row.get("auto_roll_until") else None
                        ),
                        notes=row.get("notes"),
                        eligible_node_ids=eligible_ids,
                        actor_id=actor.id,
                    )
                    created += 1
                    created_shift_templates.append(str(tpl.id))
                elif effective == "update" and row.get("existing_id"):
                    tpl = session.get(ShiftTemplate, uuid.UUID(row["existing_id"]))
                    if tpl is not None:
                        update_template(
                            session,
                            tpl=tpl,
                            recurrence_type=row.get("recurrence_type"),
                            weekdays=row.get("weekdays"),
                            duration_days=row.get("duration_days"),
                            start_time=row.get("start_time"),
                            end_time=row.get("end_time"),
                            required_count=row.get("required_count"),
                            auto_roll=row.get("auto_roll"),
                            auto_roll_until=(
                                date_type.fromisoformat(row["auto_roll_until"])
                                if row.get("auto_roll_until") else ...
                            ),
                            notes=row.get("notes") if row.get("notes") else ...,
                            eligible_node_ids=eligible_ids if row.get("resolved_eligible_node_ids") else ...,
                            actor_id=actor.id,
                        )
                        updated += 1
                        created_shift_templates.append(str(tpl.id))
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "shift_templates", "error": str(exc)})

    # ── Hierarchy ───────────────────────────────────────────────────────
    name_to_new_node_id: dict[str, uuid.UUID] = {}
    for row in state.get("hierarchy", []):
        effective = _effective_action(selections, "hierarchy", row)
        if row["action"] in ("error", "out_of_scope") or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                if effective == "new":
                    parent_id = (
                        uuid.UUID(row["resolved_parent_id"]) if row.get("resolved_parent_id") else None
                    )
                    node = create_node(
                        session,
                        level=row["level"],
                        name=row["name"],
                        parent_id=parent_id,
                        actor_id=actor.id,
                    )
                    name_to_new_node_id[row["name"]] = node.id
                    if row.get("resolved_commander_id") is not None:
                        # Route through set_commander (not create_node's own
                        # commander_id param) so the reciprocal bookkeeping
                        # (soldier.hierarchy_node_id, role recompute) that the
                        # update branch already gets for free also applies here.
                        set_commander(
                            session, node_id=node.id,
                            commander_id=uuid.UUID(row["resolved_commander_id"]), actor_id=actor.id,
                        )
                    for dm in row.get("duty_manager_refs", []):
                        if dm.get("resolved_soldier_id"):
                            assign_dm_scope(
                                session, soldier_id=uuid.UUID(dm["resolved_soldier_id"]),
                                node_id=node.id, actor_id=actor.id,
                            )
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    node = session.get(HierarchyNode, uuid.UUID(row["existing_id"]))
                    if node is not None:
                        if row.get("level") and row["level"] != node.level:
                            change_node_level(session, node_id=node.id, level=row["level"], actor_id=actor.id)
                        if row.get("resolved_parent_id") and uuid.UUID(row["resolved_parent_id"]) != node.parent_id:
                            move_node(session, node_id=node.id, new_parent_id=uuid.UUID(row["resolved_parent_id"]), actor_id=actor.id)
                        if row.get("resolved_commander_id") is not None:
                            set_commander(
                                session, node_id=node.id,
                                commander_id=uuid.UUID(row["resolved_commander_id"]), actor_id=actor.id,
                            )
                        existing_scopes = {
                            s.duty_manager_id: s.id
                            for s in session.execute(
                                select(DutyManagerScope).where(DutyManagerScope.hierarchy_node_id == node.id)
                            ).scalars()
                        }
                        desired_ids = {
                            uuid.UUID(dm["resolved_soldier_id"])
                            for dm in row.get("duty_manager_refs", [])
                            if dm.get("resolved_soldier_id")
                        }
                        for soldier_id in desired_ids - set(existing_scopes.keys()):
                            assign_dm_scope(session, soldier_id=soldier_id, node_id=node.id, actor_id=actor.id)
                        for soldier_id, scope_id in existing_scopes.items():
                            if soldier_id not in desired_ids:
                                remove_dm_scope(session, entry_id=scope_id, actor_id=actor.id)
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "hierarchy", "error": str(exc)})

    # Second sub-pass: link any node whose parent_name pointed at another
    # *new* row in this same sheet (unresolvable during the resolve phase,
    # since that row had no id yet).
    for row in state.get("hierarchy", []):
        effective = _effective_action(selections, "hierarchy", row)
        if row["action"] in ("error", "out_of_scope") or effective != "new":
            continue
        if row.get("parent_name") and not row.get("resolved_parent_id") and row["parent_name"] in name_to_new_node_id:
            node_id = name_to_new_node_id.get(row["name"])
            parent_id = name_to_new_node_id[row["parent_name"]]
            if node_id is not None:
                try:
                    with session.begin_nested():
                        move_node(session, node_id=node_id, new_parent_id=parent_id, actor_id=actor.id)
                except Exception as exc:
                    errors.append({"row": row["row"], "type": "hierarchy", "error": str(exc)})

    # ── Exemption types ─────────────────────────────────────────────────
    for row in state.get("exemption_types", []):
        effective = _effective_action(selections, "exemption_types", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                duty_type_ids = [uuid.UUID(i) for i in row.get("resolved_duty_type_ids", [])]
                if effective == "new":
                    et = create_exemption_type(
                        session,
                        name=row["name"],
                        description=row.get("description"),
                        is_global=bool(row.get("is_global")),
                        is_medical=bool(row.get("is_medical")),
                        is_commander_exemption=bool(row.get("is_commander_exemption")),
                        actor_id=actor.id,
                    )
                    if duty_type_ids:
                        set_exemption_duty_types(
                            session, exemption_type_id=et.id, duty_type_ids=duty_type_ids, actor_id=actor.id,
                        )
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    et = session.get(ExemptionType, uuid.UUID(row["existing_id"]))
                    if et is not None:
                        update_exemption_type(
                            session,
                            exemption_type=et,
                            name=None,
                            description=row.get("description"),
                            is_global=row.get("is_global"),
                            is_medical=row.get("is_medical"),
                            is_commander_exemption=row.get("is_commander_exemption"),
                            actor_id=actor.id,
                        )
                        set_exemption_duty_types(
                            session, exemption_type_id=et.id, duty_type_ids=duty_type_ids, actor_id=actor.id,
                        )
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "exemption_types", "error": str(exc)})

    # ── System settings ────────────────────────────────────────────────
    for row in state.get("system_settings", []):
        effective = _effective_action(selections, "system_settings", row)
        if row["action"] in ("error", "out_of_scope") or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                set_setting(session, key=row["key"], value=row["parsed_value"], actor_id=actor.id)
                if effective == "new":
                    created += 1
                else:
                    updated += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "system_settings", "error": str(exc)})

    # ── Bug reports ─────────────────────────────────────────────────────
    for row in state.get("bug_reports", []):
        effective = _effective_action(selections, "bug_reports", row)
        if row["action"] in ("error", "out_of_scope") or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                if effective == "new":
                    br = BugReport(
                        reporter_id=uuid.UUID(row["resolved_reporter_id"]),
                        description=row["description"],
                        severity=row["severity"],
                        route=row["route"],
                        status=row["status"],
                        nav_history=row.get("nav_history"),
                        audit_snapshot=row.get("audit_snapshot"),
                        user_snapshot=row.get("user_snapshot"),
                    )
                    session.add(br)
                    session.flush()
                    if row.get("created_at"):
                        br.created_at = datetime.fromisoformat(row["created_at"])
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    br = session.get(BugReport, uuid.UUID(row["existing_id"]))
                    if br is not None:
                        br.description = row["description"]
                        br.severity = row["severity"]
                        br.route = row["route"]
                        br.status = row["status"]
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "bug_reports", "error": str(exc)})

    # ── Personal constraints ────────────────────────────────────────────
    for row in state.get("personal_constraints", []):
        effective = _effective_action(selections, "personal_constraints", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                if effective == "new":
                    pc = PersonalConstraint(
                        soldier_id=uuid.UUID(row["resolved_soldier_id"]),
                        start_date=date_type.fromisoformat(row["start_date"]),
                        end_date=date_type.fromisoformat(row["end_date"]),
                        reason=row["reason"] or "",
                        status=row["status"],
                    )
                    if row.get("resolved_decided_by_id"):
                        pc.decided_by = uuid.UUID(row["resolved_decided_by_id"])
                        pc.decided_at = datetime.now(UTC)
                    pc.decision_note = row.get("decision_note")
                    session.add(pc)
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    pc = session.get(PersonalConstraint, uuid.UUID(row["existing_id"]))
                    if pc is not None:
                        pc.start_date = date_type.fromisoformat(row["start_date"])
                        pc.end_date = date_type.fromisoformat(row["end_date"])
                        if row.get("reason") is not None:
                            pc.reason = row["reason"]
                        pc.status = row["status"]
                        if row.get("resolved_decided_by_id"):
                            pc.decided_by = uuid.UUID(row["resolved_decided_by_id"])
                        pc.decision_note = row.get("decision_note")
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "personal_constraints", "error": str(exc)})

    # ── Soldier field updates ───────────────────────────────────────────
    for row in state.get("soldier_field_updates", []):
        effective = _effective_action(selections, "soldier_field_updates", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                if effective == "new":
                    sfu = SoldierFieldUpdate(
                        soldier_id=uuid.UUID(row["resolved_soldier_id"]),
                        field_name=row["field_name"],
                        new_value=row["new_value"],
                        previous_value=row.get("previous_value"),
                        status=row["status"],
                    )
                    if row.get("resolved_decided_by_id"):
                        sfu.decided_by = uuid.UUID(row["resolved_decided_by_id"])
                        sfu.decided_at = datetime.now(UTC)
                    sfu.decision_note = row.get("decision_note")
                    session.add(sfu)
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    sfu = session.get(SoldierFieldUpdate, uuid.UUID(row["existing_id"]))
                    if sfu is not None:
                        sfu.field_name = row["field_name"]
                        sfu.new_value = row["new_value"]
                        sfu.previous_value = row.get("previous_value")
                        sfu.status = row["status"]
                        if row.get("resolved_decided_by_id"):
                            sfu.decided_by = uuid.UUID(row["resolved_decided_by_id"])
                        sfu.decision_note = row.get("decision_note")
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "soldier_field_updates", "error": str(exc)})

    # ── Soldier enrollment requests ──────────────────────────────────────
    for row in state.get("soldier_enrollment_requests", []):
        effective = _effective_action(selections, "soldier_enrollment_requests", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                if effective == "new":
                    ser = SoldierEnrollmentRequest(
                        soldier_id=uuid.UUID(row["resolved_soldier_id"]),
                        requested_node_id=uuid.UUID(row["resolved_node_id"]),
                        status=row["status"],
                    )
                    if row.get("resolved_decided_by_id"):
                        ser.decided_by = uuid.UUID(row["resolved_decided_by_id"])
                        ser.decided_at = datetime.now(UTC)
                    ser.decision_note = row.get("decision_note")
                    session.add(ser)
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    ser = session.get(SoldierEnrollmentRequest, uuid.UUID(row["existing_id"]))
                    if ser is not None:
                        ser.requested_node_id = uuid.UUID(row["resolved_node_id"])
                        ser.status = row["status"]
                        if row.get("resolved_decided_by_id"):
                            ser.decided_by = uuid.UUID(row["resolved_decided_by_id"])
                        ser.decision_note = row.get("decision_note")
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "soldier_enrollment_requests", "error": str(exc)})

    # ── Soldier exemptions ───────────────────────────────────────────────
    for row in state.get("soldier_exemptions", []):
        effective = _effective_action(selections, "soldier_exemptions", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                if effective == "new":
                    se = SoldierExemption(
                        soldier_id=uuid.UUID(row["resolved_soldier_id"]),
                        exemption_type_id=uuid.UUID(row["resolved_exemption_type_id"]),
                        start_date=date_type.fromisoformat(row["start_date"]),
                        end_date=(
                            date_type.fromisoformat(row["end_date"]) if row.get("end_date") else None
                        ),
                        reason=row.get("reason"),
                    )
                    if row.get("resolved_granted_by_id"):
                        se.granted_by = uuid.UUID(row["resolved_granted_by_id"])
                    if row.get("revoked"):
                        se.revoked_at = datetime.now(UTC)
                        se.revoke_reason = row.get("revoke_reason")
                    session.add(se)
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    se = session.get(SoldierExemption, uuid.UUID(row["existing_id"]))
                    if se is not None:
                        se.start_date = date_type.fromisoformat(row["start_date"])
                        se.end_date = (
                            date_type.fromisoformat(row["end_date"]) if row.get("end_date") else None
                        )
                        se.reason = row.get("reason")
                        if row.get("resolved_granted_by_id"):
                            se.granted_by = uuid.UUID(row["resolved_granted_by_id"])
                        if row.get("revoked"):
                            if se.revoked_at is None:
                                se.revoked_at = datetime.now(UTC)
                            se.revoke_reason = row.get("revoke_reason")
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "soldier_exemptions", "error": str(exc)})

    # ── Exemption requests ───────────────────────────────────────────────
    for row in state.get("exemption_requests", []):
        effective = _effective_action(selections, "exemption_requests", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                if effective == "new":
                    er = ExemptionRequest(
                        soldier_id=uuid.UUID(row["resolved_soldier_id"]),
                        exemption_type_id=uuid.UUID(row["resolved_exemption_type_id"]),
                        start_date=date_type.fromisoformat(row["start_date"]),
                        end_date=(
                            date_type.fromisoformat(row["end_date"]) if row.get("end_date") else None
                        ),
                        reason=row.get("reason"),
                        status=row["status"],
                    )
                    if row.get("resolved_commander_approved_by_id"):
                        er.commander_approved_by = uuid.UUID(row["resolved_commander_approved_by_id"])
                    if row.get("resolved_decided_by_id"):
                        er.decided_by = uuid.UUID(row["resolved_decided_by_id"])
                    er.decision_note = row.get("decision_note")
                    session.add(er)
                    created += 1
                elif effective == "update" and row.get("existing_id"):
                    er = session.get(ExemptionRequest, uuid.UUID(row["existing_id"]))
                    if er is not None:
                        er.start_date = date_type.fromisoformat(row["start_date"])
                        er.end_date = (
                            date_type.fromisoformat(row["end_date"]) if row.get("end_date") else None
                        )
                        if row.get("reason") is not None:
                            er.reason = row.get("reason")
                        er.status = row["status"]
                        if row.get("resolved_commander_approved_by_id"):
                            er.commander_approved_by = uuid.UUID(row["resolved_commander_approved_by_id"])
                        if row.get("resolved_decided_by_id"):
                            er.decided_by = uuid.UUID(row["resolved_decided_by_id"])
                        er.decision_note = row.get("decision_note")
                        updated += 1
                    else:
                        skipped += 1
                else:
                    skipped += 1
        except Exception as exc:
            errors.append({"row": row["row"], "type": "exemption_requests", "error": str(exc)})

    # ── Swap requests ───────────────────────────────────────────────────
    # Each row restores the parent SwapRequest plus, at most, the one
    # SwapCandidate it identifies via target/covering personal number (see
    # resolve_swap_requests in import_approvals.py and
    # approvals_export._write_swap_requests — a request with several
    # candidates round-trips as several rows sharing the same "id").
    for row in state.get("swap_requests", []):
        effective = _effective_action(selections, "swap_requests", row)
        if row["action"] == "error" or effective == "skip":
            skipped += 1
            continue
        try:
            with session.begin_nested():
                # update-only (see resolve_swap_requests in Task 3) — action is
                # always "update" for a non-error, non-skipped row; "existing_id"
                # is always present since resolution requires it.
                if effective != "update" or not row.get("existing_id"):
                    skipped += 1
                    continue
                swap = session.get(SwapRequest, uuid.UUID(row["existing_id"]))
                if swap is None:
                    skipped += 1
                    continue
                swap.status = row["status"]
                swap.reason = row.get("reason")
                swap.requester_side_approved = row.get("requester_side_approved")
                swap.decision_note = row.get("decision_note")
                if row.get("resolved_rejected_by_id"):
                    swap.rejected_by = uuid.UUID(row["resolved_rejected_by_id"])

                # Restore this row's candidate, if it names one — update the
                # existing SwapCandidate matched by (swap_request, soldier),
                # or create it if the export had one that no longer exists
                # here (e.g. re-importing into a fresh DB).
                candidate = None
                if row.get("resolved_candidate_soldier_id"):
                    if row.get("existing_candidate_id"):
                        candidate = session.get(SwapCandidate, uuid.UUID(row["existing_candidate_id"]))
                    if candidate is None:
                        candidate = SwapCandidate(
                            swap_request_id=swap.id,
                            soldier_id=uuid.UUID(row["resolved_candidate_soldier_id"]),
                            source=row.get("candidate_source") or "invited",
                        )
                        session.add(candidate)
                        session.flush()
                    candidate.soldier_side_approved = row.get("covering_side_approved")
                    if swap.status == "applied":
                        candidate.status = "applied"
                    elif swap.status in ("rejected", "cancelled"):
                        candidate.status = "cancelled"
                    elif row.get("covering_side_approved"):
                        candidate.status = "accepted"
                    else:
                        candidate.status = "pending"

                updated += 1

                # Restore the approval_log's decision-log rows — one insert
                # per segment, exactly as recorded (not re-derived from the
                # live hierarchy), skipping any (side, kind, person) already
                # present for this swap (idempotent re-confirm). Covering-side
                # entries attach to this row's candidate; requester-side
                # entries are shared across every row for the request.
                for entry in row.get("approval_log", []):
                    row_candidate_id = candidate.id if (entry["side"] == "covering" and candidate is not None) else None
                    existing_decision = session.execute(
                        select(SwapManagerApproval).where(
                            SwapManagerApproval.swap_request_id == swap.id,
                            SwapManagerApproval.swap_candidate_id == row_candidate_id,
                            SwapManagerApproval.side == entry["side"],
                            SwapManagerApproval.approver_kind == entry["kind"],
                            SwapManagerApproval.commander_id == uuid.UUID(entry["resolved_person_id"]),
                        )
                    ).scalar_one_or_none()
                    if existing_decision is None:
                        existing_decision = SwapManagerApproval(
                            swap_request_id=swap.id, swap_candidate_id=row_candidate_id,
                            side=entry["side"], approver_kind=entry["kind"],
                            commander_id=uuid.UUID(entry["resolved_person_id"]),
                        )
                        session.add(existing_decision)
                    at = datetime.fromisoformat(entry["at"]) if entry.get("at") else datetime.now(UTC)
                    if entry["outcome"] == "approved":
                        existing_decision.approved = True
                        existing_decision.approved_by = uuid.UUID(entry["resolved_person_id"])
                        existing_decision.approved_at = at
                    else:
                        existing_decision.rejected = True
                        existing_decision.rejected_by = uuid.UUID(entry["resolved_person_id"])
                        existing_decision.rejected_at = at
        except Exception as exc:
            errors.append({"row": row["row"], "type": "swap_requests", "error": str(exc)})

    import_session.created_links = {
        "soldiers": created_soldiers,
        "duty_shifts": created_duty_shifts,
        "assignments": created_assignments,
        "shift_templates": created_shift_templates,
    }
    import_session.status = "confirmed"
    import_session.confirmed_at = datetime.now(tz=UTC)
    session.flush()

    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}


def cancel_session(
    session: Session, *, session_id: uuid.UUID, actor: Soldier
) -> ImportSession:
    import_session = session.get(ImportSession, session_id)
    if import_session is None:
        raise ImportSessionError("session_not_found")
    if import_session.status != "draft":
        raise ImportSessionError("only_draft_sessions_can_be_cancelled")

    import_session.status = "cancelled"
    import_session.cancelled_at = datetime.now(tz=UTC)
    session.flush()
    return import_session


def mark_done(
    session: Session, *, session_id: uuid.UUID, actor: Soldier
) -> ImportSession:
    import_session = session.get(ImportSession, session_id)
    if import_session is None:
        raise ImportSessionError("session_not_found")
    if import_session.status != "confirmed":
        raise ImportSessionError("only_confirmed_sessions_can_be_marked_done")

    import_session.status = "done"
    session.flush()
    return import_session
