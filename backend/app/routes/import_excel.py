from __future__ import annotations

import io
import secrets
import uuid
from datetime import date as date_type
from typing import Any, Literal

import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_duty_manager_or_admin, require_password_changed
from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyType,
    HierarchyNode,
    ShiftTemplate,
    Soldier,
)
from app.db.session import get_session
from app.services.import_parsers._shared_parsing import parse_bool as _parse_bool
from app.services.import_parsers._shared_parsing import parse_date as _parse_date

router = APIRouter(prefix="/import", tags=["import"])


# ── Row models ─────────────────────────────────────────────────────────────────

class SoldierRowPreview(BaseModel):
    row: int
    action: Literal["new", "update", "error"]
    personal_number: str
    full_name: str
    rank: str | None
    gender: str | None
    is_officer: bool | None
    hierarchy_node_id: uuid.UUID | None
    hierarchy_node_name: str | None
    enrolled_at: str | None
    enlistment_date: str | None
    phone: str | None
    email: str | None
    existing_id: uuid.UUID | None
    errors: list[str]


class AssignmentRowPreview(BaseModel):
    row: int
    action: Literal["new", "error"]
    personal_number: str
    duty_type_name: str
    start_date: str
    end_date: str
    is_reserve: bool
    resolved_soldier_id: uuid.UUID | None
    resolved_duty_type_id: uuid.UUID | None
    errors: list[str]


class TemplateRowPreview(BaseModel):
    row: int
    action: Literal["new", "error"]
    name: str
    duty_type_name: str
    days_of_week: list[int]
    required_primary: int
    required_reserve: int
    resolved_duty_type_id: uuid.UUID | None
    errors: list[str]


class PreviewResult(BaseModel):
    soldiers: list[SoldierRowPreview]
    assignments: list[AssignmentRowPreview]
    shift_templates: list[TemplateRowPreview]


# ── Apply models ───────────────────────────────────────────────────────────────

class ApplySoldierRow(BaseModel):
    row: int
    action: Literal["new", "update", "skip"]
    personal_number: str
    full_name: str
    rank: str | None
    gender: str | None
    is_officer: bool | None
    hierarchy_node_id: uuid.UUID | None
    enrolled_at: str | None
    enlistment_date: str | None
    phone: str | None
    email: str | None
    existing_id: uuid.UUID | None


class ApplyAssignmentRow(BaseModel):
    row: int
    action: Literal["new", "skip"]
    resolved_soldier_id: uuid.UUID
    resolved_duty_type_id: uuid.UUID
    start_date: str
    end_date: str
    is_reserve: bool


class ApplyTemplateRow(BaseModel):
    row: int
    action: Literal["new", "skip"]
    name: str
    resolved_duty_type_id: uuid.UUID
    days_of_week: list[int]
    required_primary: int
    required_reserve: int


class ApplyRequest(BaseModel):
    soldiers: list[ApplySoldierRow]
    assignments: list[ApplyAssignmentRow]
    shift_templates: list[ApplyTemplateRow]


class ApplyResult(BaseModel):
    created: int
    updated: int
    skipped: int
    errors: list[str]


# ── Preview endpoint ───────────────────────────────────────────────────────────

@router.post("/preview", response_model=PreviewResult)
async def preview(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    content = await file.read()
    # Validate XLSX magic bytes (PK signature for ZIP format)
    if content[:4] != b"PK\x03\x04":
        raise HTTPException(status_code=400, detail="invalid_file_type")
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_xlsx")

    soldiers_by_pn: dict[str, Soldier] = {
        s.personal_number: s
        for s in session.execute(select(Soldier)).scalars().all()
    }
    nodes_by_name: dict[str, HierarchyNode] = {
        n.name: n
        for n in session.execute(select(HierarchyNode)).scalars().all()
    }
    duty_types_by_name: dict[str, DutyType] = {
        dt.name: dt
        for dt in session.execute(select(DutyType)).scalars().all()
    }

    soldiers = _parse_soldiers_sheet(wb, soldiers_by_pn, nodes_by_name)
    assignments = _parse_assignments_sheet(wb, soldiers_by_pn, duty_types_by_name)
    shift_templates = _parse_templates_sheet(wb, duty_types_by_name)

    return PreviewResult(soldiers=soldiers, assignments=assignments, shift_templates=shift_templates)


def _parse_soldiers_sheet(wb, soldiers_by_pn, nodes_by_name) -> list[SoldierRowPreview]:
    if "soldiers" not in wb.sheetnames:
        return []
    ws = wb["soldiers"]
    headers = [str(c.value).strip().lower() if c.value else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
    results = []
    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if all(v is None for v in row):
            continue
        data = dict(zip(headers, row))
        errors: list[str] = []
        pn = str(data.get("personal_number") or "").strip()
        full_name = str(data.get("full_name") or "").strip()
        if not pn:
            errors.append("personal_number is required")
        if not full_name:
            errors.append("full_name is required")

        node_name = str(data.get("hierarchy_node_name") or "").strip() or None
        node = nodes_by_name.get(node_name) if node_name else None
        if node_name and not node:
            errors.append(f"hierarchy_node_name '{node_name}' not found")

        existing = soldiers_by_pn.get(pn)
        action: Literal["new", "update", "error"] = "error" if errors else ("update" if existing else "new")

        results.append(SoldierRowPreview(
            row=i,
            action=action,
            personal_number=pn,
            full_name=full_name,
            rank=str(data.get("rank") or "").strip() or None,
            gender=str(data.get("gender") or "").strip() or None,
            is_officer=_parse_bool(data.get("is_officer")),
            hierarchy_node_id=node.id if node else None,
            hierarchy_node_name=node_name,
            enrolled_at=_parse_date(data.get("enrolled_at")),
            enlistment_date=_parse_date(data.get("enlistment_date")),
            phone=str(data.get("phone") or "").strip() or None,
            email=str(data.get("email") or "").strip() or None,
            existing_id=existing.id if existing else None,
            errors=errors,
        ))
    return results


def _parse_assignments_sheet(wb, soldiers_by_pn, duty_types_by_name) -> list[AssignmentRowPreview]:
    if "assignments" not in wb.sheetnames:
        return []
    ws = wb["assignments"]
    headers = [str(c.value).strip().lower() if c.value else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
    results = []
    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if all(v is None for v in row):
            continue
        data = dict(zip(headers, row))
        errors: list[str] = []
        pn = str(data.get("personal_number") or "").strip()
        dt_name = str(data.get("duty_type_name") or "").strip()
        start = _parse_date(data.get("start_date"))
        end = _parse_date(data.get("end_date"))

        soldier = soldiers_by_pn.get(pn)
        if not pn or not soldier:
            errors.append(f"personal_number '{pn}' not found")
        dt = duty_types_by_name.get(dt_name)
        if not dt_name or not dt:
            errors.append(f"duty_type_name '{dt_name}' not found")
        if not start:
            errors.append("start_date is required (dd.mm.yyyy)")
        if not end:
            errors.append("end_date is required (dd.mm.yyyy)")

        results.append(AssignmentRowPreview(
            row=i,
            action="error" if errors else "new",
            personal_number=pn,
            duty_type_name=dt_name,
            start_date=start or "",
            end_date=end or "",
            is_reserve=_parse_bool(data.get("is_reserve")) or False,
            resolved_soldier_id=soldier.id if soldier else None,
            resolved_duty_type_id=dt.id if dt else None,
            errors=errors,
        ))
    return results


def _parse_templates_sheet(wb, duty_types_by_name) -> list[TemplateRowPreview]:
    if "shift_templates" not in wb.sheetnames:
        return []
    ws = wb["shift_templates"]
    headers = [str(c.value).strip().lower() if c.value else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
    results = []
    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if all(v is None for v in row):
            continue
        data = dict(zip(headers, row))
        errors: list[str] = []
        name = str(data.get("name") or "").strip()
        dt_name = str(data.get("duty_type_name") or "").strip()
        if not name:
            errors.append("name is required")
        dt = duty_types_by_name.get(dt_name)
        if not dt:
            errors.append(f"duty_type_name '{dt_name}' not found")
        days_raw = str(data.get("days_of_week") or "").strip()
        try:
            days = [int(d.strip()) for d in days_raw.split(",") if d.strip()]
        except ValueError:
            days = []
            errors.append("days_of_week must be comma-separated integers (1-7)")
        required_primary = int(data.get("required_primary") or 1)
        required_reserve = int(data.get("required_reserve") or 0)

        results.append(TemplateRowPreview(
            row=i,
            action="error" if errors else "new",
            name=name,
            duty_type_name=dt_name,
            days_of_week=days,
            required_primary=required_primary,
            required_reserve=required_reserve,
            resolved_duty_type_id=dt.id if dt else None,
            errors=errors,
        ))
    return results


# ── Apply endpoint ─────────────────────────────────────────────────────────────

@router.post("/apply", response_model=ApplyResult)
def apply(
    req: ApplyRequest,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    from app.auth.password import hash_password

    created = updated = skipped = 0
    errors: list[str] = []

    try:
        for row in req.soldiers:
            if row.action == "skip":
                skipped += 1
                continue
            if row.action == "new":
                new_soldier = Soldier(
                    personal_number=row.personal_number,
                    full_name=row.full_name,
                    password_hash=hash_password(secrets.token_hex(16)),
                    must_change_password=True,
                    rank=row.rank,
                    gender=row.gender,
                    is_officer=row.is_officer,
                    hierarchy_node_id=row.hierarchy_node_id,
                    phone=row.phone,
                    email=row.email,
                )
                if row.enrolled_at:
                    new_soldier.enrolled_at = date_type.fromisoformat(row.enrolled_at)
                if row.enlistment_date:
                    new_soldier.enlistment_date = date_type.fromisoformat(row.enlistment_date)
                session.add(new_soldier)
                created += 1
            elif row.action == "update" and row.existing_id:
                s = session.get(Soldier, row.existing_id)
                if s:
                    s.full_name = row.full_name
                    if row.rank is not None:
                        s.rank = row.rank
                    if row.gender is not None:
                        s.gender = row.gender
                    if row.is_officer is not None:
                        s.is_officer = row.is_officer
                    if row.hierarchy_node_id is not None:
                        s.hierarchy_node_id = row.hierarchy_node_id
                    if row.phone is not None:
                        s.phone = row.phone
                    if row.email is not None:
                        s.email = row.email
                    if row.enrolled_at:
                        s.enrolled_at = date_type.fromisoformat(row.enrolled_at)
                    if row.enlistment_date:
                        s.enlistment_date = date_type.fromisoformat(row.enlistment_date)
                    updated += 1

        session.flush()

        # Assignments
        for row in req.assignments:
            if row.action == "skip":
                skipped += 1
                continue
            loc = session.execute(select(DutyLocation).limit(1)).scalar_one_or_none()
            if loc is None:
                errors.append(f"Row {row.row}: no duty location exists — cannot import assignment")
                continue
            assignment = DutyAssignment(
                soldier_id=row.resolved_soldier_id,
                duty_type_id=row.resolved_duty_type_id,
                duty_location_id=loc.id,
                start_date=date_type.fromisoformat(row.start_date),
                end_date=date_type.fromisoformat(row.end_date),
                status="published",
                is_reserve=row.is_reserve,
            )
            session.add(assignment)
            created += 1

        # Shift templates
        for row in req.shift_templates:
            if row.action == "skip":
                skipped += 1
                continue
            loc = session.execute(select(DutyLocation).limit(1)).scalar_one_or_none()
            if loc is None:
                errors.append(f"Row {row.row}: no duty location exists — cannot import template")
                continue
            template = ShiftTemplate(
                name=row.name,
                duty_type_id=row.resolved_duty_type_id,
                duty_location_id=loc.id,
                weekdays=row.days_of_week,
                required_count=row.required_primary + row.required_reserve,
            )
            session.add(template)
            created += 1

        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc))

    return ApplyResult(created=created, updated=updated, skipped=skipped, errors=errors)


# ── Template download ──────────────────────────────────────────────────────────

@router.get("/template")
def download_template():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    ws_s = wb.create_sheet("soldiers")
    ws_s.append(["personal_number", "full_name", "rank", "gender", "is_officer",
                  "hierarchy_node_name", "enrolled_at", "enlistment_date", "phone", "email"])
    ws_s.append(["12345", "ישראל ישראלי", "רב", "m", "false", "מדור א", "01.01.2022", "01.03.2020", "", ""])

    ws_a = wb.create_sheet("assignments")
    ws_a.append(["personal_number", "duty_type_name", "start_date", "end_date", "is_reserve"])
    ws_a.append(["12345", "שמירה", "15.06.2024", "16.06.2024", "false"])

    ws_t = wb.create_sheet("shift_templates")
    ws_t.append(["name", "duty_type_name", "days_of_week", "required_primary", "required_reserve"])
    ws_t.append(["שמירת שישי", "שמירה", "6", "2", "1"])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="import_template.xlsx"'},
    )
