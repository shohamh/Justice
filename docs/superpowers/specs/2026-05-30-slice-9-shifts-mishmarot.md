# Slice 9 — Shifts (משמרות): Entity, Management Page, Calendar View

**Date:** 2026-05-30
**Status:** Approved (brainstorm 2026-05-30).
**Depends on:** Slice 8 (soldier profile + eligibility).
**Followed by:** Slice 10 (algorithm integration with shifts).

## Goal

Introduce `duty_shifts` as a first-class DB entity representing a scheduled duty slot that requires N soldiers. Duty managers create and manage shifts; the algorithm in Slice 10 assigns soldiers to them. Shifts remain alive after assignment and display fill status (assigned/required) on a management page and calendar.

---

## 1. Data model (migration 0018)

### 1.1 New table `duty_shifts`

```sql
duty_shifts (
  id               uuid PK DEFAULT gen_random_uuid()
  duty_type_id     uuid FK duty_types ON DELETE RESTRICT NOT NULL
  duty_location_id uuid FK duty_locations ON DELETE RESTRICT NOT NULL
  start_date       date NOT NULL
  end_date         date NOT NULL
  required_count   int NOT NULL DEFAULT 1 CHECK (required_count >= 1)
  notes            text NULL
  created_by       uuid FK soldiers ON DELETE SET NULL, nullable
  created_at       timestamptz NOT NULL DEFAULT now()
  updated_at       timestamptz NOT NULL DEFAULT now()
)
```

Indexes: `(start_date, end_date)`, `(duty_type_id)`.

### 1.2 FK on `duty_assignments`

```sql
ALTER TABLE duty_assignments ADD COLUMN duty_shift_id uuid
  REFERENCES duty_shifts(id) ON DELETE SET NULL;
```

Nullable — manually-created assignments (no shift) remain valid.

### 1.3 Fill status (computed, not stored)

`assigned_count` = `COUNT(duty_assignments WHERE duty_shift_id = X AND status IN ('published', 'algorithm_draft'))`

`fill_status`:
- `empty`: assigned_count = 0
- `partial`: 0 < assigned_count < required_count
- `full`: assigned_count = required_count

---

## 2. Backend

### 2.1 ORM model `DutyShift`

Standard SQLAlchemy `MappedAsDataclass` model matching 1.1.

### 2.2 Service `app/services/shifts.py`

```python
def create_shift(session, *, duty_type_id, duty_location_id, start_date, end_date,
                 required_count, notes, actor_id) -> DutyShift
def update_shift(session, *, shift, **kwargs, actor_id) -> DutyShift
def delete_shift(session, *, shift, actor_id) -> None   # only if no published assignments
def list_shifts(session, *, date_from, date_to, duty_type_id=None) -> list[ShiftWithFill]
def get_shift_fill(session, *, shift_id) -> ShiftWithFill
```

`ShiftWithFill` is a dataclass/dict combining `DutyShift` fields with `assigned_count` and `fill_status`.

Deleting a shift with published assignments raises `ShiftError("has_assignments")`.

### 2.3 Routes `app/routes/shifts.py`

```
GET    /api/shifts                 duty_manager  — list with date_from/date_to + duty_type_id filters
POST   /api/shifts                 duty_manager  — create
GET    /api/shifts/{id}            duty_manager  — get single shift with fill status
PATCH  /api/shifts/{id}            duty_manager  — update (notes, required_count, dates)
DELETE /api/shifts/{id}            duty_manager  — delete (fails if has published assignments)
GET    /api/shifts/{id}/assignments duty_manager — list assignments for this shift
```

All routes require `Action.ASSIGNMENT_MANAGE` (existing action — DM already has it).

All mutations write to `audit_log`.

### 2.4 Register router in `main.py`

```python
from app.routes import shifts as shift_routes
app.include_router(shift_routes.router, prefix="/api")
```

---

## 3. Frontend

### 3.1 New page — ניהול משמרות (`/shifts`)

DM-only. Two views toggled by a button:

#### Table view (default)

Columns: סוג תורנות, מיקום, תאריך התחלה, תאריך סיום, משך (ימים), נדרש, שובץ, סטטוס.

Status badge:
- 🔴 ריק — 0 assigned
- 🟡 חלקי — assigned < required
- 🟢 מלא — assigned = required

Row actions: עריכה (edit modal), מחיקה (confirm modal, disabled if has published assignments), לחצן "הצג שיבוצים" → expands to show assigned soldiers.

#### Calendar view

Month grid (same RTL calendar component pattern as UnitCalendar). Each shift appears as a horizontal bar spanning its date range. Bar color = fill status (red/amber/green). Clicking a bar opens a side panel: shift details + list of assigned soldiers + empty slot indicators.

#### Create/edit shift modal

Fields: duty type select, location select, start date, end date, required count (number input ≥ 1), notes (optional textarea). Validation: end ≥ start, required_count ≥ 1.

### 3.2 Navigation

Add "משמרות" link to the DM sidebar in `Layout.tsx`.

### 3.3 New API file `frontend/src/api/shifts.ts`

```typescript
export interface DutyShift { id, duty_type_id, duty_location_id, start_date, end_date, required_count, notes, assigned_count, fill_status }
export async function listShifts(params): Promise<DutyShift[]>
export async function createShift(input): Promise<DutyShift>
export async function updateShift(id, input): Promise<DutyShift>
export async function deleteShift(id): Promise<void>
export async function getShiftAssignments(id): Promise<Assignment[]>
```

### 3.4 i18n additions

```json
"shifts": {
  "title": "ניהול משמרות",
  "create": "משמרת חדשה",
  "edit": "עריכת משמרת",
  "delete": "מחיקת משמרת",
  "duty_type": "סוג תורנות",
  "location": "מיקום",
  "start_date": "תאריך התחלה",
  "end_date": "תאריך סיום",
  "duration_days": "משך (ימים)",
  "required_count": "מספר נדרש",
  "assigned_count": "שובץ",
  "fill_status_empty": "ריק",
  "fill_status_partial": "חלקי",
  "fill_status_full": "מלא",
  "has_assignments_error": "לא ניתן למחוק משמרת עם שיבוצים פעילים",
  "view_assignments": "הצג שיבוצים",
  "table_view": "טבלה",
  "calendar_view": "לוח שנה"
}
```

---

## 4. Testing

- **Unit** (`test_shifts_service.py`): create/update/delete happy paths, delete-with-assignments error, fill status computation.
- **Integration** (`test_shifts_routes.py`): CRUD endpoints, auth (soldiers cannot create), fill status in list response, delete blocked when assignments exist.
- **Frontend**: `ShiftsPage.test.tsx` — table/calendar toggle, create modal, delete confirmation.
