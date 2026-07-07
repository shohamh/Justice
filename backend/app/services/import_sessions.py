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
    DutyLocation,
    DutyManagerScope,
    DutyShift,
    DutyType,
    ExemptionType,
    HierarchyLevelType,
    HierarchyNode,
    ImportSession,
    Soldier,
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
from app.services.import_parsers.registry import auto_detect_parser, get_parser
from app.services.import_parsers.schema import ParsedImportData
from app.services.import_scope import is_node_in_actor_scope
from app.services.shift_quotas import set_shift_quotas


class ImportSessionError(Exception):
    pass


def _resolve_soldiers(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    node_by_name: dict[str, str] | None = None,
    node_by_row: dict[str, str] | None = None,
) -> list[dict]:
    node_by_name = node_by_name or {}
    node_by_row = node_by_row or {}
    existing_by_pn = {
        s.personal_number: s for s in session.execute(select(Soldier)).scalars()
    }
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}

    out = []
    for row in data.soldiers:
        errors: list[str] = []
        if not row.personal_number:
            errors.append("חסר מספר אישי")
        if not row.full_name:
            errors.append("חסר שם מלא")

        node = None
        if row.hierarchy_node_name:
            row_key = f"soldiers:{row.source_row}"
            mapped_id = node_by_row.get(row_key) or node_by_name.get(row.hierarchy_node_name)
            if mapped_id:
                try:
                    node = session.get(HierarchyNode, uuid.UUID(mapped_id))
                except ValueError:
                    pass
            if node is None:
                node = nodes_by_name.get(row.hierarchy_node_name)
            if node is None:
                errors.append(f"יחידה לא מזוהה '{row.hierarchy_node_name}'")

        existing = existing_by_pn.get(row.personal_number) if row.personal_number else None

        if errors:
            action = "error"
        elif existing is not None:
            action = "update"
        else:
            action = "new"

        if action != "error" and node is not None:
            # Per-row scope check: re-runs scope_root_ids(session, actor) on every
            # iteration instead of hoisting it out of the loop. Fine for typical
            # single-Excel-import row counts; if import volumes grow significantly,
            # this is the first place to optimize (precompute scope_root_ids once
            # and inline the subtree check).
            if actor.role != "admin" and not is_node_in_actor_scope(
                session=session, actor=actor, node_id=node.id
            ):
                action = "out_of_scope"

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "personal_number": row.personal_number,
            "full_name": row.full_name,
            "rank": row.rank,
            "gender": row.gender,
            "is_officer": row.is_officer,
            "hierarchy_node_id": str(node.id) if node is not None else None,
            "hierarchy_node_name": row.hierarchy_node_name,
            "enrolled_at": row.enrolled_at,
            "enlistment_date": row.enlistment_date,
            "phone": row.phone,
            "email": row.email,
            "existing_id": str(existing.id) if existing is not None else None,
        })
    return out


def _resolve_duty_locations(session: Session, data: ParsedImportData) -> list[dict]:
    existing_by_name = {
        loc.name: loc for loc in session.execute(select(DutyLocation)).scalars()
    }
    out = []
    for row in data.duty_locations:
        errors: list[str] = []
        if not row.name:
            errors.append("חסר שם מיקום")
        existing = existing_by_name.get(row.name) if row.name else None
        action = "error" if errors else ("update" if existing else "new")
        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": row.name,
            "base": row.base,
            "active": row.active,
            "existing_id": str(existing.id) if existing is not None else None,
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
) -> list[dict]:
    node_by_name = node_by_name or {}
    node_by_row = node_by_row or {}
    existing_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}
    valid_levels = {
        lt.key for lt in session.execute(select(HierarchyLevelType)).scalars()
    }
    by_pn = {s.personal_number: s for s in session.execute(select(Soldier)).scalars()}
    by_name: dict[str, list[Soldier]] = {}
    for s in by_pn.values():
        by_name.setdefault(s.full_name, []).append(s)

    # Pass 1: figure out each row's own resolved-or-new identity (name -> row index),
    # so pass 2 can resolve forward-referenced parents regardless of sheet order.
    row_by_name = {row.name: row for row in data.hierarchy}

    out = []
    for row in data.hierarchy:
        errors: list[str] = []

        if row.level not in valid_levels:
            errors.append(f"סוג יחידה לא מוכר '{row.level}'")

        existing = existing_by_name.get(row.name)

        resolved_parent_id = None
        if row.parent_name:
            row_key = f"hierarchy:{row.source_row}"
            mapped_id = node_by_row.get(row_key) or node_by_name.get(row.parent_name)
            if mapped_id:
                resolved_parent_id = mapped_id
            elif row.parent_name in existing_by_name:
                resolved_parent_id = str(existing_by_name[row.parent_name].id)
            elif row.parent_name in row_by_name:
                resolved_parent_id = None  # resolved to another *new* row by name at commit time
            else:
                errors.append(f"יחידת אב לא מזוהה '{row.parent_name}'")

        resolved_commander_id = None
        if row.commander_personal_number or row.commander_name:
            soldier, err = _resolve_soldier_ref(
                row.commander_personal_number, row.commander_name, by_pn, by_name
            )
            if soldier is not None:
                resolved_commander_id = str(soldier.id)
            else:
                errors.append(f"מפקד לא מזוהה: {err}")

        dm_results = []
        for ref in row.duty_manager_refs:
            pn, _, name = ref.partition(":")
            soldier, err = _resolve_soldier_ref(pn.strip(), name.strip(), by_pn, by_name)
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
            # Either a brand-new root node, or a parent that only resolves to
            # another *new* row later in this same sheet (forward reference,
            # not yet a real node id) — in both cases scope cannot be verified
            # against a real parent node at this point, so treat as out of
            # scope for non-admins. Matches is_node_in_actor_scope's contract
            # that a None node_id is never in scope for a non-admin actor.
            action = "out_of_scope"

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": row.name,
            "level": row.level,
            "parent_name": row.parent_name,
            "resolved_parent_id": resolved_parent_id,
            "commander_personal_number": row.commander_personal_number,
            "commander_name": row.commander_name,
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
) -> list[dict]:
    node_by_name = node_by_name or {}
    node_by_row = node_by_row or {}
    existing_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}

    out = []
    for row in data.duty_types:
        errors: list[str] = []

        score_per_day: Decimal | None = None
        try:
            score_per_day = Decimal(row.score_per_day) if row.score_per_day else None
            if score_per_day is None:
                errors.append("חסר ניקוד ליום")
        except Exception:
            errors.append(f"ניקוד ליום לא תקין '{row.score_per_day}'")

        reserve_ratio: Decimal | None = None
        if row.reserve_ratio is not None and row.reserve_ratio != "":
            try:
                reserve_ratio = Decimal(row.reserve_ratio)
            except Exception:
                errors.append(f"יחס רזרבה לא תקין '{row.reserve_ratio}'")

        requirements: dict | None = None
        if row.requirements_json:
            try:
                requirements = json.loads(row.requirements_json)
            except Exception as exc:
                errors.append(f"JSON לא תקין בעמודת requirements_json: {exc}")

        resolved_eligible_node_ids: list[str] = []
        for unit_name in row.eligible_unit_names:
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

        existing = existing_by_name.get(row.name) if row.name else None
        action = "error" if errors else ("update" if existing else "new")

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": row.name,
            "score_per_day": str(score_per_day) if score_per_day is not None else None,
            "description": row.description,
            "active": row.active,
            "reserve_ratio": str(reserve_ratio) if reserve_ratio is not None else None,
            "reserve_minimum": row.reserve_minimum,
            "is_external": row.is_external,
            "contact_name": row.contact_name,
            "contact_phone": row.contact_phone,
            "start_time": row.start_time,
            "end_time": row.end_time,
            "instructions": row.instructions,
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
) -> list[dict]:
    """Resolve exemption types from import data.

    Matches by name (unique constraint on exemption_types.name).
    Resolves applies_to_duty_type_names to duty type IDs from both DB and import sheet.
    """
    dt_by_name = dt_by_name or {}
    dt_by_row = dt_by_row or {}
    existing_by_name = {et.name: et for et in session.execute(select(ExemptionType)).scalars()}
    duty_types_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}

    out = []
    for row in data.exemption_types:
        errors: list[str] = []

        # Resolve applies_to_duty_type_names to duty type IDs
        resolved_duty_type_ids: list[str] = []
        for duty_type_name in row.applies_to_duty_type_names:
            # Try name mappings first (from import sheet), then DB
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

        # Handle boolean fields - must check explicitly for None, not use truthiness
        is_global = row.is_global if row.is_global is not None else False
        is_medical = row.is_medical if row.is_medical is not None else False
        is_commander_exemption = row.is_commander_exemption if row.is_commander_exemption is not None else False

        existing = existing_by_name.get(row.name) if row.name else None
        action = "error" if errors else ("update" if existing else "new")

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": row.name,
            "description": row.description,
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
) -> list[dict]:
    dt_by_name = dt_by_name or {}
    dt_by_row = dt_by_row or {}
    node_by_name = node_by_name or {}
    node_by_row = node_by_row or {}
    duty_types_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}
    locations_by_name = {loc.name: loc for loc in session.execute(select(DutyLocation)).scalars()}
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}

    out = []
    for row in data.duty_shifts:
        errors: list[str] = []

        duty_type = None
        if row.duty_type_name:
            row_key = f"duty_shifts:{row.source_row}"
            mapped_id = dt_by_row.get(row_key) or dt_by_name.get(row.duty_type_name)
            if mapped_id:
                try:
                    duty_type = session.get(DutyType, uuid.UUID(mapped_id))
                except ValueError:
                    pass
            if duty_type is None:
                duty_type = duty_types_by_name.get(row.duty_type_name)
        if duty_type is None:
            errors.append(f"סוג תורנות לא מזוהה '{row.duty_type_name}'")

        location = locations_by_name.get(row.duty_location_name) if row.duty_location_name else None
        if location is None:
            errors.append(f"מיקום תורנות לא מזוהה '{row.duty_location_name}'")

        if not row.start_date:
            errors.append("חסר תאריך התחלה")
        if not row.end_date:
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

        if quota_total > row.required_count:
            errors.append(
                f"סה\"כ מכסות ({quota_total}) גדול מהכמות הנדרשת ({row.required_count})"
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
            "duty_type_name": row.duty_type_name,
            "resolved_duty_type_id": str(duty_type.id) if duty_type is not None else None,
            "duty_location_name": row.duty_location_name,
            "resolved_duty_location_id": str(location.id) if location is not None else None,
            "start_date": row.start_date,
            "end_date": row.end_date,
            "start_time": row.start_time,
            "end_time": row.end_time,
            "required_count": row.required_count,
            "node_quotas": quota_dicts,
            "notes": row.notes,
        })
    return out


def _resolve_shift_templates(
    session: Session,
    data: ParsedImportData,
    dt_by_name: dict[str, str] | None = None,
    dt_by_row: dict[str, str] | None = None,
) -> list[dict]:
    dt_by_name = dt_by_name or {}
    dt_by_row = dt_by_row or {}
    duty_types_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}

    out = []
    for row in getattr(data, "shift_templates", []):
        errors: list[str] = []
        duty_type = None
        if row.duty_type_name:
            row_key = f"shift_templates:{row.source_row}"
            mapped_id = dt_by_row.get(row_key) or dt_by_name.get(row.duty_type_name)
            if mapped_id:
                try:
                    duty_type = session.get(DutyType, uuid.UUID(mapped_id))
                except ValueError:
                    pass
            if duty_type is None:
                duty_type = duty_types_by_name.get(row.duty_type_name)
        if duty_type is None:
            errors.append(f"סוג תורנות לא מזוהה '{row.duty_type_name}'")

        action = "error" if errors else "new"

        out.append({
            "row": row.source_row,
            "action": action,
            "errors": errors,
            "name": row.name,
            "duty_type_name": row.duty_type_name,
            "resolved_duty_type_id": str(duty_type.id) if duty_type is not None else None,
            "days_of_week": row.days_of_week,
            "required_primary": row.required_primary,
            "required_reserve": row.required_reserve,
        })
    return out


def _resolve_and_score(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    selections: dict | None = None,
) -> dict:
    nm = (selections or {}).get("_name_mappings", {})
    dt_by_name  = nm.get("duty_type", {}).get("by_name", {})
    dt_by_row   = nm.get("duty_type", {}).get("by_row", {})
    node_by_name = nm.get("hierarchy_node", {}).get("by_name", {})
    node_by_row  = nm.get("hierarchy_node", {}).get("by_row", {})
    return {
        "soldiers": _resolve_soldiers(session, data, actor, node_by_name, node_by_row),
        "duty_shifts": _resolve_duty_shifts(session, data, actor, dt_by_name, dt_by_row, node_by_name, node_by_row),
        "shift_templates": _resolve_shift_templates(session, data, dt_by_name, dt_by_row),
        "duty_locations": _resolve_duty_locations(session, data),
        "hierarchy": _resolve_hierarchy(session, data, actor, node_by_name, node_by_row),
        "duty_types": _resolve_duty_types(session, data, node_by_name, node_by_row),
        "exemption_types": _resolve_exemption_types(session, data, dt_by_name, dt_by_row),
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
        raise ImportSessionError("session not found")
    if import_session.status != "draft":
        raise ImportSessionError("only draft sessions can be reparsed")

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
        raise ImportSessionError("session not found")

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
        raise ImportSessionError("session not found")
    if import_session.status != "draft":
        raise ImportSessionError("only draft sessions can be confirmed")

    selections = import_session.user_selections or {}
    state = import_session.parsed_state

    created = 0
    updated = 0
    skipped = 0
    errors: list[dict] = []
    created_soldiers: list[str] = []
    created_duty_shifts: list[str] = []

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
                )
                if row.get("enrolled_at"):
                    new_soldier.enrolled_at = date_type.fromisoformat(row["enrolled_at"])
                if row.get("enlistment_date"):
                    new_soldier.enlistment_date = date_type.fromisoformat(row["enlistment_date"])
                session.add(new_soldier)
                session.flush()
                created += 1
                created_soldiers.append(str(new_soldier.id))
            elif effective == "update" and row.get("existing_id"):
                s = session.get(Soldier, uuid.UUID(row["existing_id"]))
                if s is not None:
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
                    if row.get("enrolled_at"):
                        s.enrolled_at = date_type.fromisoformat(row["enrolled_at"])
                    if row.get("enlistment_date"):
                        s.enlistment_date = date_type.fromisoformat(row["enlistment_date"])
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
        except Exception as exc:
            errors.append({"row": row["row"], "type": "duty_shifts", "error": str(exc)})

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
                        instructions=row.get("instructions"),
                        is_external=bool(row.get("is_external")),
                        eligible_node_ids=eligible_ids,
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

    import_session.created_links = {
        "soldiers": created_soldiers,
        "duty_shifts": created_duty_shifts,
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
        raise ImportSessionError("session not found")
    if import_session.status != "draft":
        raise ImportSessionError("only draft sessions can be cancelled")

    import_session.status = "cancelled"
    import_session.cancelled_at = datetime.now(tz=UTC)
    session.flush()
    return import_session


def mark_done(
    session: Session, *, session_id: uuid.UUID, actor: Soldier
) -> ImportSession:
    import_session = session.get(ImportSession, session_id)
    if import_session is None:
        raise ImportSessionError("session not found")
    if import_session.status != "confirmed":
        raise ImportSessionError("only confirmed sessions can be marked done")

    import_session.status = "done"
    session.flush()
    return import_session
