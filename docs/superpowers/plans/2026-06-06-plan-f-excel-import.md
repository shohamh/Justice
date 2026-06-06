# Plan F — Excel Import Mechanism

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 3-step Excel import wizard (upload → review → confirm) for soldiers, historical duty assignments, and shift templates.

**Architecture:** Two new backend endpoints (`POST /import/preview`, `POST /import/apply`) plus a template download (`GET /import/template`). New frontend page at `/import` with a 3-tab review step. Backend parsing uses `openpyxl` (already a dependency). Per-row action choices (new/update/skip) are decided in the review step and sent back in the apply request.

**Tech Stack:** React, Tailwind, FastAPI, openpyxl, SQLAlchemy

---

### Task 1: Backend — import schemas and preview endpoint

**Files:**
- Create: `backend/app/routes/import_excel.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create `import_excel.py` with schemas**

Create `backend/app/routes/import_excel.py`:
```python
from __future__ import annotations

import io
import uuid
from datetime import date
from typing import Any, Literal

import openpyxl
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import (
    DutyAssignment, DutyShift, DutyType, HierarchyNode, Soldier,
)
from app.db.session import get_session

router = APIRouter(prefix="/import", tags=["import"])


# ── Row models ────────────────────────────────────────────────────────────────

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
    existing_id: uuid.UUID | None  # set if action=="update"
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


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_date(val: Any) -> str | None:
    """Accept dd.mm.yyyy or yyyy-mm-dd strings, or date objects."""
    if val is None:
        return None
    if isinstance(val, date):
        return val.isoformat()
    s = str(val).strip()
    if len(s) == 10 and s[2] == "." and s[5] == ".":
        d, m, y = s.split(".")
        return f"{y}-{m}-{d}"
    return s  # assume ISO


def _parse_bool(val: Any) -> bool | None:
    if val is None:
        return None
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "כן", "נכון")


# ── Preview endpoint ───────────────────────────────────────────────────────────

@router.post("/preview", response_model=PreviewResult)
async def preview(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
):
    authorize(actor, Action.CREATE, "import")

    content = await file.read()
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_xlsx")

    # Build lookup maps
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
            errors.append("days_of_week must be comma-separated integers (0-6)")
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
```

- [ ] **Step 2: Register router**

In `backend/app/main.py`:
```python
from app.routes.import_excel import router as import_router
app.include_router(import_router)
```

- [ ] **Step 3: Write preview test**

In `backend/tests/integration/test_import_excel.py` (create):
```python
import io
import openpyxl

def make_xlsx_bytes(soldiers=None, assignments=None, templates=None) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    if soldiers:
        ws = wb.create_sheet("soldiers")
        ws.append(["personal_number", "full_name", "rank"])
        for row in soldiers:
            ws.append(row)
    if assignments:
        ws = wb.create_sheet("assignments")
        ws.append(["personal_number", "duty_type_name", "start_date", "end_date"])
        for row in assignments:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

def test_preview_new_soldier(client, duty_manager_token):
    xlsx = make_xlsx_bytes(soldiers=[["12345", "ישראל ישראלי", "רב"]])
    resp = client.post(
        "/import/preview",
        files={"file": ("import.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"Authorization": f"Bearer {duty_manager_token}"},
    )
    assert resp.status_code == 200
    soldiers = resp.json()["soldiers"]
    assert len(soldiers) == 1
    assert soldiers[0]["action"] == "new"
    assert soldiers[0]["personal_number"] == "12345"

def test_preview_duplicate_soldier_is_update(client, duty_manager_token, existing_soldier_pn):
    xlsx = make_xlsx_bytes(soldiers=[[existing_soldier_pn, "שם חדש", None]])
    resp = client.post(
        "/import/preview",
        files={"file": ("import.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers={"Authorization": f"Bearer {duty_manager_token}"},
    )
    assert resp.json()["soldiers"][0]["action"] == "update"
```

Run: `cd backend && uv run pytest tests/integration/test_import_excel.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/import_excel.py backend/app/main.py backend/tests/integration/test_import_excel.py
git commit -m "feat: POST /import/preview parses xlsx and returns per-row preview with actions"
```

---

### Task 2: Backend — apply endpoint + template download

**Files:**
- Modify: `backend/app/routes/import_excel.py`

- [ ] **Step 1: Add apply endpoint**

Append to `backend/app/routes/import_excel.py`:
```python
from app.db.models import ShiftTemplate  # import if exists; if not, skip templates apply


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


@router.post("/apply", response_model=ApplyResult)
def apply(
    req: ApplyRequest,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_password_changed),
):
    authorize(actor, Action.CREATE, "import")

    created = updated = skipped = 0
    errors: list[str] = []

    try:
        # Soldiers
        for row in req.soldiers:
            if row.action == "skip":
                skipped += 1
                continue
            if row.action == "new":
                import secrets
                from app.auth.password import hash_password
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
                    from datetime import date as date_type
                    new_soldier.enrolled_at = date_type.fromisoformat(row.enrolled_at)
                if row.enlistment_date:
                    new_soldier.enlistment_date = date_type.fromisoformat(row.enlistment_date)
                session.add(new_soldier)
                created += 1
            elif row.action == "update" and row.existing_id:
                s = session.get(Soldier, row.existing_id)
                if s:
                    s.full_name = row.full_name
                    if row.rank is not None: s.rank = row.rank
                    if row.gender is not None: s.gender = row.gender
                    if row.is_officer is not None: s.is_officer = row.is_officer
                    if row.hierarchy_node_id is not None: s.hierarchy_node_id = row.hierarchy_node_id
                    if row.phone is not None: s.phone = row.phone
                    if row.email is not None: s.email = row.email
                    if row.enrolled_at: s.enrolled_at = date_type.fromisoformat(row.enrolled_at)
                    if row.enlistment_date: s.enlistment_date = date_type.fromisoformat(row.enlistment_date)
                    updated += 1

        session.flush()

        # Re-fetch soldiers for assignment resolution
        soldiers_by_pn = {s.personal_number: s for s in session.execute(select(Soldier)).scalars().all()}

        # Assignments
        for row in req.assignments:
            if row.action == "skip":
                skipped += 1
                continue
            # Find a shift or create a bare assignment
            from app.db.models import DutyLocation
            loc = session.execute(select(DutyLocation).limit(1)).scalar_one_or_none()
            if loc is None:
                errors.append(f"Row {row.row}: no duty location exists — cannot import assignment")
                continue
            from datetime import date as date_type
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

        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc))

    return ApplyResult(created=created, updated=updated, skipped=skipped, errors=errors)
```

- [ ] **Step 2: Add template download endpoint**

```python
from fastapi.responses import StreamingResponse

@router.get("/template")
def download_template():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # soldiers sheet
    ws_s = wb.create_sheet("soldiers")
    ws_s.append(["personal_number", "full_name", "rank", "gender", "is_officer",
                  "hierarchy_node_name", "enrolled_at", "enlistment_date", "phone", "email"])
    ws_s.append(["12345", "ישראל ישראלי", "רב", "m", "false", "מדור א", "01.01.2022", "01.03.2020", "", ""])

    # assignments sheet
    ws_a = wb.create_sheet("assignments")
    ws_a.append(["personal_number", "duty_type_name", "start_date", "end_date", "is_reserve"])
    ws_a.append(["12345", "שמירה", "15.06.2024", "16.06.2024", "false"])

    # templates sheet
    ws_t = wb.create_sheet("shift_templates")
    ws_t.append(["name", "duty_type_name", "days_of_week", "required_primary", "required_reserve"])
    ws_t.append(["שמירת שישי", "שמירה", "5", "2", "1"])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="import_template.xlsx"'},
    )
```

- [ ] **Step 3: Write apply test**

In `backend/tests/integration/test_import_excel.py`, add:
```python
def test_apply_creates_soldier(client, duty_manager_token):
    resp = client.post(
        "/import/apply",
        json={
            "soldiers": [{
                "row": 2, "action": "new",
                "personal_number": "99999", "full_name": "טסט יחידה",
                "rank": None, "gender": None, "is_officer": None,
                "hierarchy_node_id": None, "enrolled_at": None,
                "enlistment_date": None, "phone": None, "email": None, "existing_id": None,
            }],
            "assignments": [],
            "shift_templates": [],
        },
        headers={"Authorization": f"Bearer {duty_manager_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["created"] == 1
    assert resp.json()["errors"] == []
```

Run: `cd backend && uv run pytest tests/integration/test_import_excel.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/import_excel.py
git commit -m "feat: POST /import/apply and GET /import/template endpoints"
```

---

### Task 3: Frontend — import wizard page

**Files:**
- Create: `frontend/src/pages/ImportPage.tsx`
- Create: `frontend/src/api/importExcel.ts`
- Modify: `frontend/src/App.tsx` (add route)
- Modify: `frontend/src/components/NavSheet.tsx` (add link under תכנון)

- [ ] **Step 1: Create API client**

Create `frontend/src/api/importExcel.ts`:
```ts
import { api } from "./client";

export interface SoldierRowPreview {
  row: number;
  action: "new" | "update" | "error";
  personal_number: string;
  full_name: string;
  rank: string | null;
  gender: string | null;
  is_officer: boolean | null;
  hierarchy_node_id: string | null;
  hierarchy_node_name: string | null;
  enrolled_at: string | null;
  enlistment_date: string | null;
  phone: string | null;
  email: string | null;
  existing_id: string | null;
  errors: string[];
}

export interface AssignmentRowPreview {
  row: number;
  action: "new" | "error";
  personal_number: string;
  duty_type_name: string;
  start_date: string;
  end_date: string;
  is_reserve: boolean;
  resolved_soldier_id: string | null;
  resolved_duty_type_id: string | null;
  errors: string[];
}

export interface TemplateRowPreview {
  row: number;
  action: "new" | "error";
  name: string;
  duty_type_name: string;
  days_of_week: number[];
  required_primary: number;
  required_reserve: number;
  resolved_duty_type_id: string | null;
  errors: string[];
}

export interface PreviewResult {
  soldiers: SoldierRowPreview[];
  assignments: AssignmentRowPreview[];
  shift_templates: TemplateRowPreview[];
}

export interface ApplySoldierRow extends Omit<SoldierRowPreview, "errors"> {
  action: "new" | "update" | "skip";
}

export interface ApplyAssignmentRow {
  row: number;
  action: "new" | "skip";
  resolved_soldier_id: string;
  resolved_duty_type_id: string;
  start_date: string;
  end_date: string;
  is_reserve: boolean;
}

export interface ApplyRequest {
  soldiers: ApplySoldierRow[];
  assignments: ApplyAssignmentRow[];
  shift_templates: Array<{ row: number; action: "new" | "skip"; name: string; resolved_duty_type_id: string; days_of_week: number[]; required_primary: number; required_reserve: number }>;
}

export interface ApplyResult {
  created: number;
  updated: number;
  skipped: number;
  errors: string[];
}

export async function previewImport(file: File): Promise<PreviewResult> {
  const form = new FormData();
  form.append("file", file);
  return (await api.post<PreviewResult>("/import/preview", form, {
    headers: { "Content-Type": "multipart/form-data" },
  })).data;
}

export async function applyImport(req: ApplyRequest): Promise<ApplyResult> {
  return (await api.post<ApplyResult>("/import/apply", req)).data;
}

export function templateDownloadUrl(): string {
  return "/api/import/template";
}
```

- [ ] **Step 2: Create `ImportPage.tsx`**

Create `frontend/src/pages/ImportPage.tsx`:
```tsx
import { useRef, useState } from "react";
import Layout from "../components/Layout";
import {
  ApplyRequest, ApplySoldierRow, PreviewResult, SoldierRowPreview,
  applyImport, previewImport,
} from "../api/importExcel";

type Step = "upload" | "review" | "done";

const ACTION_CHIP: Record<string, string> = {
  new: "bg-green-100 text-green-700",
  update: "bg-blue-100 text-blue-700",
  error: "bg-red-100 text-red-700",
  skip: "bg-gray-100 text-gray-500",
};
const ACTION_LABEL: Record<string, string> = {
  new: "חדש", update: "עדכון", error: "שגיאה", skip: "דלג",
};

export default function ImportPage() {
  const [step, setStep] = useState<Step>("upload");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [soldierActions, setSoldierActions] = useState<Record<number, "new" | "update" | "skip">>({});
  const [tab, setTab] = useState<"soldiers" | "assignments" | "templates">("soldiers");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ created: number; updated: number; skipped: number } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleUpload(file: File) {
    setLoading(true);
    setError(null);
    try {
      const p = await previewImport(file);
      setPreview(p);
      // default actions
      const defaults: Record<number, "new" | "update" | "skip"> = {};
      for (const row of p.soldiers) {
        if (row.action !== "error") defaults[row.row] = row.action as "new" | "update";
      }
      setSoldierActions(defaults);
      setStep("review");
    } catch {
      setError("שגיאה בפענוח הקובץ — ודא שהוא xlsx תקין עם גיליונות בשמות הנכונים");
    } finally {
      setLoading(false);
    }
  }

  async function handleApply() {
    if (!preview) return;
    setLoading(true);
    const req: ApplyRequest = {
      soldiers: preview.soldiers
        .filter((r) => r.action !== "error")
        .map((r): ApplySoldierRow => ({
          ...r,
          action: soldierActions[r.row] ?? "skip",
        })),
      assignments: preview.assignments
        .filter((r) => r.action === "new" && r.resolved_soldier_id && r.resolved_duty_type_id)
        .map((r) => ({
          row: r.row,
          action: "new" as const,
          resolved_soldier_id: r.resolved_soldier_id!,
          resolved_duty_type_id: r.resolved_duty_type_id!,
          start_date: r.start_date,
          end_date: r.end_date,
          is_reserve: r.is_reserve,
        })),
      shift_templates: preview.shift_templates
        .filter((r) => r.action === "new" && r.resolved_duty_type_id)
        .map((r) => ({
          row: r.row,
          action: "new" as const,
          name: r.name,
          resolved_duty_type_id: r.resolved_duty_type_id!,
          days_of_week: r.days_of_week,
          required_primary: r.required_primary,
          required_reserve: r.required_reserve,
        })),
    };
    try {
      const res = await applyImport(req);
      setResult(res);
      setStep("done");
    } catch {
      setError("שגיאה בייבוא — אין שינויים שנשמרו");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Layout>
      <div className="max-w-3xl mx-auto space-y-4 p-4" dir="rtl">
        <h1 className="text-xl font-semibold">ייבוא מ-Excel</h1>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">{error}</div>
        )}

        {/* Step 1: Upload */}
        {step === "upload" && (
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4 text-center">
            <p className="text-gray-600 dark:text-gray-400 text-sm">
              העלה קובץ Excel עם גיליונות: <code>soldiers</code>, <code>assignments</code>, <code>shift_templates</code>
            </p>
            <a href="/api/import/template" className="text-indigo-600 hover:underline text-sm">
              הורד תבנית לדוגמה ›
            </a>
            <div>
              <input
                ref={fileRef}
                type="file"
                accept=".xlsx"
                className="hidden"
                onChange={(e) => { if (e.target.files?.[0]) void handleUpload(e.target.files[0]); }}
              />
              <button
                className="bg-indigo-600 text-white px-6 py-2 rounded font-medium hover:bg-indigo-700"
                disabled={loading}
                onClick={() => fileRef.current?.click()}
              >
                {loading ? "טוען..." : "בחר קובץ"}
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Review */}
        {step === "review" && preview && (
          <div className="space-y-4">
            {/* Tabs */}
            <div className="flex gap-1 border-b dark:border-gray-700">
              {(["soldiers", "assignments", "templates"] as const).map((t) => (
                <button
                  key={t}
                  className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${tab === t ? "border-indigo-600 text-indigo-600" : "border-transparent text-gray-500 hover:text-gray-700"}`}
                  onClick={() => setTab(t)}
                >
                  {t === "soldiers" ? `חיילים (${preview.soldiers.length})` : t === "assignments" ? `שיבוצים (${preview.assignments.length})` : `תבניות (${preview.shift_templates.length})`}
                </button>
              ))}
            </div>

            {tab === "soldiers" && (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-gray-500 border-b">
                    <th className="text-right pb-1">שם</th>
                    <th className="text-right pb-1">מ"א</th>
                    <th className="text-right pb-1">סטטוס</th>
                    <th className="text-right pb-1">פעולה</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.soldiers.map((row) => (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="py-1">{row.full_name}</td>
                      <td className="py-1">{row.personal_number}</td>
                      <td className="py-1">
                        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${ACTION_CHIP[row.action]}`}>
                          {ACTION_LABEL[row.action]}
                        </span>
                        {row.errors.length > 0 && (
                          <span className="text-red-500 text-xs mr-1">{row.errors.join("; ")}</span>
                        )}
                      </td>
                      <td className="py-1">
                        {row.action !== "error" && (
                          <select
                            className="border rounded text-xs p-0.5 dark:bg-gray-700"
                            value={soldierActions[row.row] ?? row.action}
                            onChange={(e) => setSoldierActions((prev) => ({
                              ...prev,
                              [row.row]: e.target.value as "new" | "update" | "skip",
                            }))}
                          >
                            {row.action === "update" && <option value="update">עדכן</option>}
                            {row.action === "new" && <option value="new">צור</option>}
                            <option value="skip">דלג</option>
                          </select>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {tab === "assignments" && (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-gray-500 border-b">
                    <th className="text-right pb-1">מ"א</th>
                    <th className="text-right pb-1">סוג תורנות</th>
                    <th className="text-right pb-1">תאריכים</th>
                    <th className="text-right pb-1">סטטוס</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.assignments.map((row) => (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="py-1">{row.personal_number}</td>
                      <td className="py-1">{row.duty_type_name}</td>
                      <td className="py-1">{row.start_date} – {row.end_date}</td>
                      <td className="py-1">
                        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${ACTION_CHIP[row.action]}`}>
                          {ACTION_LABEL[row.action]}
                        </span>
                        {row.errors.map((e, i) => <span key={i} className="text-red-500 text-xs mr-1">{e}</span>)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {tab === "templates" && (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-gray-500 border-b">
                    <th className="text-right pb-1">שם</th>
                    <th className="text-right pb-1">סוג</th>
                    <th className="text-right pb-1">ימים</th>
                    <th className="text-right pb-1">נדרש</th>
                    <th className="text-right pb-1">סטטוס</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.shift_templates.map((row) => (
                    <tr key={row.row} className="border-b dark:border-gray-700">
                      <td className="py-1">{row.name}</td>
                      <td className="py-1">{row.duty_type_name}</td>
                      <td className="py-1">{row.days_of_week.join(",")}</td>
                      <td className="py-1">{row.required_primary}+{row.required_reserve}</td>
                      <td className="py-1">
                        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${ACTION_CHIP[row.action]}`}>
                          {ACTION_LABEL[row.action]}
                        </span>
                        {row.errors.map((e, i) => <span key={i} className="text-red-500 text-xs mr-1">{e}</span>)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div className="flex gap-3 justify-end pt-2">
              <button
                className="border border-gray-300 px-4 py-2 rounded text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
                onClick={() => setStep("upload")}
              >
                חזור
              </button>
              <button
                className="bg-indigo-600 text-white px-4 py-2 rounded text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
                disabled={loading}
                onClick={() => void handleApply()}
              >
                {loading ? "מייבא..." : "אשר וייבא"}
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Done */}
        {step === "done" && result && (
          <div className="bg-green-50 dark:bg-green-950 border border-green-200 dark:border-green-800 rounded-lg p-6 text-center space-y-3">
            <p className="text-green-700 dark:text-green-300 font-semibold text-lg">ייבוא הושלם בהצלחה</p>
            <p className="text-sm text-gray-600 dark:text-gray-400">
              נוצרו: {result.created} · עודכנו: {result.updated} · דולגו: {result.skipped}
            </p>
            <button
              className="border border-gray-300 px-4 py-2 rounded text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
              onClick={() => { setStep("upload"); setPreview(null); setResult(null); }}
            >
              ייבוא נוסף
            </button>
          </div>
        )}
      </div>
    </Layout>
  );
}
```

- [ ] **Step 3: Add route in `App.tsx`**

In `frontend/src/App.tsx`, import `ImportPage` and add:
```tsx
import ImportPage from "./pages/ImportPage";
// In the router:
<Route path="/import" element={<ImportPage />} />
```

- [ ] **Step 4: Add link in תכנון nav sheet**

In `frontend/src/components/NavSheet.tsx`, find the planning (תכנון) section links and add:
```tsx
{ label: "ייבוא מ-Excel", to: "/import" }
```

- [ ] **Step 5: Verify end-to-end**

1. Download template from `/api/import/template`.
2. Fill in a soldier row.
3. Upload via the UI → review step shows the row as "חדש".
4. Click "אשר וייבא" → done screen shows `created: 1`.
5. Verify soldier appears in the system.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ImportPage.tsx frontend/src/api/importExcel.ts frontend/src/App.tsx frontend/src/components/NavSheet.tsx
git commit -m "feat: Excel import wizard page (upload → review → confirm)"
```
