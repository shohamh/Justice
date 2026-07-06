from __future__ import annotations

import io
import secrets
import uuid
from datetime import UTC, date as date_type, datetime

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.password import hash_password
from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyShift,
    DutyType,
    HierarchyNode,
    ImportSession,
    Soldier,
)
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
    existing_by_full_name: dict[str, list[Soldier]] = {}
    for s in existing_by_pn.values():
        existing_by_full_name.setdefault(s.full_name, []).append(s)
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}

    out = []
    for row in data.soldiers:
        errors: list[str] = []
        warnings: list[str] = []
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
        if existing is None and row.personal_number and row.full_name:
            candidates = existing_by_full_name.get(row.full_name, [])
            if len(candidates) == 1:
                existing = candidates[0]
                warnings.append(
                    f"נמצא לפי שם — מספר אישי עודכן מ-'{existing.personal_number}' ל-'{row.personal_number}'"
                )
            elif len(candidates) > 1:
                errors.append(
                    f"שם '{row.full_name}' אינו חד משמעי (מספר אישי '{row.personal_number}' לא נמצא)"
                )

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
            "warnings": warnings,
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


def _resolve_assignments(
    session: Session,
    data: ParsedImportData,
    actor: Soldier,
    resolved_duty_shifts: list[dict],
) -> list[dict]:
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

        soldier = soldiers_by_pn.get(row.personal_number) if row.personal_number else None
        if soldier is not None:
            if soldier.full_name != row.full_name:
                errors.append(
                    f"שם מלא '{row.full_name}' אינו תואם לחייל עם מספר אישי "
                    f"'{row.personal_number}' ('{soldier.full_name}')"
                )
        else:
            candidates = soldiers_by_full_name.get(row.full_name, []) if row.full_name else []
            if len(candidates) == 1:
                soldier = candidates[0]
                warnings.append(f"נמצא לפי שם — מספר אישי '{row.personal_number}' לא נמצא")
            elif len(candidates) > 1:
                errors.append(
                    f"מספר אישי '{row.personal_number}' לא נמצא ושם '{row.full_name}' אינו חד משמעי"
                )
            else:
                errors.append(
                    f"לא נמצא חייל עם מספר אישי '{row.personal_number}' או שם '{row.full_name}'"
                )

        duty_type = duty_types_by_name.get(row.duty_type_name) if row.duty_type_name else None
        if duty_type is None:
            errors.append(f"סוג תורנות לא מזוהה '{row.duty_type_name}'")
        location = locations_by_name.get(row.duty_location_name) if row.duty_location_name else None
        if location is None:
            errors.append(f"מיקום תורנות לא מזוהה '{row.duty_location_name}'")

        resolved_duty_shift_id: str | None = None
        matched_session_row: int | None = None
        shift_key_str: str | None = None
        required_count: int | None = None
        if duty_type is not None and location is not None and row.start_date and row.end_date:
            key = (
                duty_type.id, location.id, row.start_date, row.end_date,
                _default_time(row.start_time, "00:00"),
                _default_time(row.end_time, "23:59"),
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
            "personal_number": row.personal_number,
            "full_name": row.full_name,
            "duty_type_name": row.duty_type_name,
            "duty_location_name": row.duty_location_name,
            "start_date": row.start_date,
            "end_date": row.end_date,
            "start_time": row.start_time,
            "end_time": row.end_time,
            "is_reserve": row.is_reserve,
            "notes": row.notes,
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
    dt_by_name  = nm.get("duty_type", {}).get("by_name", {})
    dt_by_row   = nm.get("duty_type", {}).get("by_row", {})
    node_by_name = nm.get("hierarchy_node", {}).get("by_name", {})
    node_by_row  = nm.get("hierarchy_node", {}).get("by_row", {})
    duty_shifts = _resolve_duty_shifts(session, data, actor, dt_by_name, dt_by_row, node_by_name, node_by_row)
    return {
        "soldiers": _resolve_soldiers(session, data, actor, node_by_name, node_by_row),
        "duty_shifts": duty_shifts,
        "shift_templates": _resolve_shift_templates(session, data, dt_by_name, dt_by_row),
        "assignments": _resolve_assignments(session, data, actor, duty_shifts),
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
    created_assignments: list[str] = []
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

    import_session.created_links = {
        "soldiers": created_soldiers,
        "duty_shifts": created_duty_shifts,
        "assignments": created_assignments,
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
