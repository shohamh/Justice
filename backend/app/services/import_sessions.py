from __future__ import annotations

import io
import uuid

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DutyLocation, DutyType, HierarchyNode, ImportSession, Soldier
from app.services.import_parsers.registry import auto_detect_parser, get_parser
from app.services.import_parsers.schema import ParsedImportData
from app.services.import_scope import is_node_in_actor_scope


class ImportSessionError(Exception):
    pass


def _resolve_soldiers(session: Session, data: ParsedImportData, actor: Soldier) -> list[dict]:
    existing_by_pn = {
        s.personal_number: s for s in session.execute(select(Soldier)).scalars()
    }
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}

    out = []
    for row in data.soldiers:
        errors: list[str] = []
        if not row.personal_number:
            errors.append("missing personal_number")
        if not row.full_name:
            errors.append("missing full_name")

        node = None
        if row.hierarchy_node_name:
            node = nodes_by_name.get(row.hierarchy_node_name)
            if node is None:
                errors.append(f"unresolved hierarchy_node_name '{row.hierarchy_node_name}'")

        existing = existing_by_pn.get(row.personal_number) if row.personal_number else None

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


def _resolve_duty_shifts(session: Session, data: ParsedImportData, actor: Soldier) -> list[dict]:
    duty_types_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}
    locations_by_name = {loc.name: loc for loc in session.execute(select(DutyLocation)).scalars()}
    nodes_by_name = {n.name: n for n in session.execute(select(HierarchyNode)).scalars()}

    out = []
    for row in data.duty_shifts:
        errors: list[str] = []

        duty_type = duty_types_by_name.get(row.duty_type_name) if row.duty_type_name else None
        if duty_type is None:
            errors.append(f"unresolved duty_type_name '{row.duty_type_name}'")

        location = locations_by_name.get(row.duty_location_name) if row.duty_location_name else None
        if location is None:
            errors.append(f"unresolved duty_location_name '{row.duty_location_name}'")

        if not row.start_date:
            errors.append("missing start_date")
        if not row.end_date:
            errors.append("missing end_date")

        quota_dicts = []
        quota_total = 0
        for q in row.node_quotas:
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
                f"node_quotas total ({quota_total}) exceeds required_count ({row.required_count})"
            )

        action = "error" if errors else "new"

        if action == "new" and actor.role != "admin":
            resolved_node_ids = [
                uuid.UUID(qd["node_id"]) for qd in quota_dicts if qd["resolved"]
            ]
            for node_id in resolved_node_ids:
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


def _resolve_shift_templates(session: Session, data: ParsedImportData) -> list[dict]:
    duty_types_by_name = {dt.name: dt for dt in session.execute(select(DutyType)).scalars()}

    out = []
    for row in data.shift_templates:
        errors: list[str] = []
        duty_type = duty_types_by_name.get(row.duty_type_name) if row.duty_type_name else None
        if duty_type is None:
            errors.append(f"unresolved duty_type_name '{row.duty_type_name}'")

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


def _resolve_and_score(session: Session, data: ParsedImportData, actor: Soldier) -> dict:
    return {
        "soldiers": _resolve_soldiers(session, data, actor),
        "duty_shifts": _resolve_duty_shifts(session, data, actor),
        "shift_templates": _resolve_shift_templates(session, data),
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
    parsed_state = _resolve_and_score(session, data, actor)

    import_session.parsed_state = parsed_state
    session.flush()
    return import_session
