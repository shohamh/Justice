# Duty Type Operational Fields — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add contact person (name + phone), fixed start/end hours, free-form instructions (≤300 words), and an internal/external flag to duty types, and surface these fields in the duty config form, duty history panel, and unit calendar shift detail panel.

**Architecture:** New columns on the `duty_types` table; backend Pydantic schemas and service updated to pass them through; frontend API types, DutyConfigPage, DutyHistoryPanel, and ShiftDetailPanel updated to show/edit them.

**Tech Stack:** Python/FastAPI/SQLAlchemy/Alembic (backend), React/TypeScript/Tailwind/i18next (frontend), PostgreSQL (TIME type for hours).

---

## Files

| File | Change |
|---|---|
| `backend/alembic/versions/0043_duty_type_operational_fields.py` | Create — migration adding 6 columns |
| `backend/app/db/models.py` | Modify — add 6 fields to `DutyType` |
| `backend/app/routes/duty_config.py` | Modify — schemas + `_dt_out` |
| `backend/app/services/duty_config.py` | Modify — `create_duty_type`, `update_duty_type` |
| `backend/tests/integration/test_duty_config_api.py` | Modify — add tests for new fields |
| `frontend/src/api/dutyConfig.ts` | Modify — extend `DutyType` interface + API functions |
| `frontend/src/i18n/he.json` | Modify — add Hebrew strings |
| `frontend/src/pages/DutyConfigPage.tsx` | Modify — create form + list display |
| `frontend/src/components/ShiftDetailPanel.tsx` | Modify — show new fields |
| `frontend/src/components/DutyHistoryPanel.tsx` | Modify — show new fields on expanded assignments |

---

## Task 1: Migration

**Files:**
- Create: `backend/alembic/versions/0043_duty_type_operational_fields.py`

- [ ] **Step 1: Create the migration file**

```python
# backend/alembic/versions/0043_duty_type_operational_fields.py
"""Add operational fields to duty_types

Revision ID: 0043
Revises: 0042
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("duty_types", sa.Column("contact_name", sa.Text, nullable=True))
    op.add_column("duty_types", sa.Column("contact_phone", sa.Text, nullable=True))
    op.add_column("duty_types", sa.Column("start_time", sa.Time, nullable=True))
    op.add_column("duty_types", sa.Column("end_time", sa.Time, nullable=True))
    op.add_column("duty_types", sa.Column("instructions", sa.Text, nullable=True))
    op.add_column(
        "duty_types",
        sa.Column("is_external", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.alter_column("duty_types", "is_external", server_default=None)


def downgrade() -> None:
    op.drop_column("duty_types", "is_external")
    op.drop_column("duty_types", "instructions")
    op.drop_column("duty_types", "end_time")
    op.drop_column("duty_types", "start_time")
    op.drop_column("duty_types", "contact_phone")
    op.drop_column("duty_types", "contact_name")
```

- [ ] **Step 2: Apply the migration**

Run from `backend/`:
```
uv run alembic upgrade head
```
Expected: `Running upgrade 0042 -> 0043, Add operational fields to duty_types`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/0043_duty_type_operational_fields.py
git commit -m "feat: add operational fields migration to duty_types"
```

---

## Task 2: SQLAlchemy Model

**Files:**
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Add imports and fields**

In `backend/app/db/models.py`, the `from sqlalchemy import` line currently reads:
```python
from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Numeric, Text, text
```
Add `Time` to that import:
```python
from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Numeric, Text, Time, text
```

Also add `time` to the `from datetime import` line (currently `from datetime import date, datetime`):
```python
from datetime import date, datetime, time
```

- [ ] **Step 2: Add fields to `DutyType`**

After the `reserve_minimum` field (line ~142) and before `created_at`, add:
```python
    contact_name: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    contact_phone: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True, default=None)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True, default=None)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    is_external: Mapped[bool] = mapped_column(Boolean)
```

- [ ] **Step 3: Verify the app starts**

Run from `backend/`:
```
uv run python -c "from app.db.models import DutyType; print('ok')"
```
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat: add operational fields to DutyType model"
```

---

## Task 3: Backend Schemas, Service, and Tests

**Files:**
- Modify: `backend/app/routes/duty_config.py`
- Modify: `backend/app/services/duty_config.py`
- Modify: `backend/tests/integration/test_duty_config_api.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/integration/test_duty_config_api.py`:

```python
def test_create_duty_type_with_operational_fields(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200001", role="admin")
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={
            "name": "שמירה-ב",
            "score_per_day": "1.00",
            "contact_name": "יוסי כהן",
            "contact_phone": "050-1234567",
            "start_time": "06:00:00",
            "end_time": "18:00:00",
            "instructions": "להגיע עם נשק",
            "is_external": False,
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["contact_name"] == "יוסי כהן"
    assert data["contact_phone"] == "050-1234567"
    assert data["start_time"] == "06:00:00"
    assert data["end_time"] == "18:00:00"
    assert data["instructions"] == "להגיע עם נשק"
    assert data["is_external"] is False


def test_create_duty_type_is_external_required(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200002", role="admin")
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "שמירה-ג", "score_per_day": "1.00"},
    )
    assert r.status_code == 422


def test_create_duty_type_instructions_too_long(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200003", role="admin")
    long_instructions = " ".join(["מילה"] * 301)
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "שמירה-ד", "score_per_day": "1.00", "is_external": False, "instructions": long_instructions},
    )
    assert r.status_code == 422


def test_update_duty_type_operational_fields(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5200004", role="admin")
    dt = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(admin),
        json={"name": "שמירה-ה", "score_per_day": "1.00", "is_external": False},
    ).json()
    r = client.patch(
        f"/api/duty-config/duty-types/{dt['id']}",
        headers=auth_headers(admin),
        json={"contact_name": "דני לוי", "is_external": True},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["contact_name"] == "דני לוי"
    assert data["is_external"] is True
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd backend && uv run pytest tests/integration/test_duty_config_api.py::test_create_duty_type_with_operational_fields -v
```
Expected: FAIL (422 or validation error — `is_external` not in schema yet)

- [ ] **Step 3: Update route schemas and mapper in `duty_config.py`**

In `backend/app/routes/duty_config.py`, add `from datetime import time` at the top (after existing imports).

Replace the `DutyTypeOut` class:
```python
class DutyTypeOut(BaseModel):
    id: uuid.UUID
    name: str
    score_per_day: Decimal
    description: str | None
    active: bool
    requirements: dict[str, Any] = {}
    reserve_ratio: Decimal = Decimal("0.000")
    reserve_minimum: int = 0
    contact_name: str | None = None
    contact_phone: str | None = None
    start_time: time | None = None
    end_time: time | None = None
    instructions: str | None = None
    is_external: bool = False
```

Replace `CreateDutyTypeRequest`:
```python
class CreateDutyTypeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    score_per_day: Decimal = Field(ge=0)
    description: str | None = Field(default=None, max_length=1000)
    reserve_ratio: Decimal = Field(default=Decimal("0.000"), ge=0, le=1)
    reserve_minimum: int = Field(default=0, ge=0)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=50)
    start_time: time | None = None
    end_time: time | None = None
    instructions: str | None = Field(default=None)
    is_external: bool  # required — no default

    @field_validator("instructions")
    @classmethod
    def validate_instructions_word_count(cls, v: str | None) -> str | None:
        if v is not None and len(v.split()) > 300:
            raise ValueError("instructions must be at most 300 words")
        return v
```

Add `from pydantic import BaseModel, Field, field_validator` (replace existing pydantic import line).

Replace `UpdateDutyTypeRequest`:
```python
class UpdateDutyTypeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    score_per_day: Decimal | None = Field(default=None, ge=0)
    description: str | None = Field(default=None, max_length=1000)
    active: bool | None = None
    requirements: dict[str, Any] | None = None
    reserve_ratio: Decimal | None = Field(default=None, ge=0, le=1)
    reserve_minimum: int | None = Field(default=None, ge=0)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=50)
    start_time: time | None = None
    end_time: time | None = None
    instructions: str | None = Field(default=None)
    is_external: bool | None = None

    @field_validator("instructions")
    @classmethod
    def validate_instructions_word_count(cls, v: str | None) -> str | None:
        if v is not None and len(v.split()) > 300:
            raise ValueError("instructions must be at most 300 words")
        return v
```

Replace the `_dt_out` function:
```python
def _dt_out(d: DutyType) -> DutyTypeOut:
    return DutyTypeOut(
        id=d.id,
        name=d.name,
        score_per_day=d.score_per_day,
        description=d.description,
        active=d.active,
        requirements=d.requirements or {},
        reserve_ratio=d.reserve_ratio or Decimal("0.000"),
        reserve_minimum=d.reserve_minimum or 0,
        contact_name=d.contact_name,
        contact_phone=d.contact_phone,
        start_time=d.start_time,
        end_time=d.end_time,
        instructions=d.instructions,
        is_external=d.is_external,
    )
```

Update the `create_duty_type` route call to pass new fields:
```python
dt = svc.create_duty_type(
    session,
    name=body.name,
    score_per_day=body.score_per_day,
    description=body.description,
    reserve_ratio=body.reserve_ratio,
    reserve_minimum=body.reserve_minimum,
    contact_name=body.contact_name,
    contact_phone=body.contact_phone,
    start_time=body.start_time,
    end_time=body.end_time,
    instructions=body.instructions,
    is_external=body.is_external,
    actor_id=user.id,
)
```

Update the `update_duty_type` route call:
```python
svc.update_duty_type(
    session,
    duty_type=dt,
    name=body.name,
    score_per_day=body.score_per_day,
    description=body.description,
    actor_id=user.id,
    requirements=body.requirements,
    reserve_ratio=body.reserve_ratio,
    reserve_minimum=body.reserve_minimum,
    contact_name=body.contact_name,
    contact_phone=body.contact_phone,
    start_time=body.start_time,
    end_time=body.end_time,
    instructions=body.instructions,
    is_external=body.is_external,
)
```

- [ ] **Step 4: Update service `create_duty_type` in `backend/app/services/duty_config.py`**

Add `from datetime import time` at the top.

Replace the `create_duty_type` signature and body:
```python
def create_duty_type(
    session: Session,
    *,
    name: str,
    score_per_day: Decimal,
    description: str | None = None,
    reserve_ratio: Decimal = Decimal("0.000"),
    reserve_minimum: int = 0,
    contact_name: str | None = None,
    contact_phone: str | None = None,
    start_time: time | None = None,
    end_time: time | None = None,
    instructions: str | None = None,
    is_external: bool,
    actor_id: uuid.UUID | None = None,
) -> DutyType:
    if score_per_day < 0:
        raise DutyConfigError("score_per_day must be >= 0")
    if session.execute(select(DutyType.id).where(DutyType.name == name)).first():
        raise DutyConfigError("name_taken")
    dt = DutyType(
        name=name,
        score_per_day=score_per_day,
        description=description,
        reserve_ratio=reserve_ratio,
        reserve_minimum=reserve_minimum,
        contact_name=contact_name,
        contact_phone=contact_phone,
        start_time=start_time,
        end_time=end_time,
        instructions=instructions,
        is_external=is_external,
    )
    session.add(dt)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="duty_type.create",
        entity_type="duty_type",
        entity_id=dt.id,
        after={
            "name": name,
            "score_per_day": str(score_per_day),
            "reserve_ratio": str(reserve_ratio),
            "reserve_minimum": reserve_minimum,
            "is_external": is_external,
        },
    )
    return dt
```

Replace `update_duty_type` signature (add new kwargs after `reserve_minimum`):
```python
def update_duty_type(
    session: Session,
    *,
    duty_type: DutyType,
    name: str | None,
    score_per_day: Decimal | None,
    description: str | None,
    actor_id: uuid.UUID | None = None,
    requirements: dict | None = None,
    reserve_ratio: Decimal | None = None,
    reserve_minimum: int | None = None,
    contact_name: str | None = None,
    contact_phone: str | None = None,
    start_time: time | None = None,
    end_time: time | None = None,
    instructions: str | None = None,
    is_external: bool | None = None,
) -> DutyType:
```

Inside the function body of `update_duty_type`, after the `reserve_minimum` block (before `write_audit`), add:
```python
    if contact_name is not None:
        duty_type.contact_name = contact_name
    if contact_phone is not None:
        duty_type.contact_phone = contact_phone
    if start_time is not None:
        duty_type.start_time = start_time
    if end_time is not None:
        duty_type.end_time = end_time
    if instructions is not None:
        duty_type.instructions = instructions
    if is_external is not None:
        duty_type.is_external = is_external
```

- [ ] **Step 5: Run the tests**

```
cd backend && uv run pytest tests/integration/test_duty_config_api.py -v
```
Expected: all pass including the four new tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/duty_config.py backend/app/services/duty_config.py backend/tests/integration/test_duty_config_api.py
git commit -m "feat: add operational fields to duty type API and service"
```

---

## Task 4: Frontend API Types

**Files:**
- Modify: `frontend/src/api/dutyConfig.ts`

- [ ] **Step 1: Update `DutyType` interface and API functions**

Replace the `DutyType` interface in `frontend/src/api/dutyConfig.ts`:
```ts
export interface DutyType {
  id: string;
  name: string;
  score_per_day: string;
  description: string | null;
  active: boolean;
  reserve_ratio?: string;
  reserve_minimum?: number;
  requirements?: {
    allowed_genders?: string[];
    requires_mitvahim?: boolean;
    requires_alal?: boolean;
    allowed_ranks?: string[];
    allowed_service_types?: string[];
    officers_allowed?: boolean;
    enlisted_allowed?: boolean;
    requires_bahad1?: boolean;
  };
  contact_name: string | null;
  contact_phone: string | null;
  start_time: string | null;   // "HH:MM:SS" from API
  end_time: string | null;     // "HH:MM:SS" from API
  instructions: string | null;
  is_external: boolean;
}
```

Replace the `createDutyType` function signature (the type in the `input` parameter):
```ts
export async function createDutyType(input: {
  name: string;
  score_per_day: string;
  description?: string | null;
  reserve_ratio?: string;
  reserve_minimum?: number;
  contact_name?: string | null;
  contact_phone?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  instructions?: string | null;
  is_external: boolean;
}): Promise<DutyType> {
  return (await api.post<DutyType>("/duty-config/duty-types", input)).data;
}
```

Replace the `updateDutyType` function signature:
```ts
export async function updateDutyType(
  id: string,
  input: Partial<{
    name: string;
    score_per_day: string;
    description: string | null;
    active: boolean;
    reserve_ratio: string;
    reserve_minimum: number;
    contact_name: string | null;
    contact_phone: string | null;
    start_time: string | null;
    end_time: string | null;
    instructions: string | null;
    is_external: boolean;
  }>
): Promise<DutyType> {
  return (await api.patch<DutyType>(`/duty-config/duty-types/${id}`, input)).data;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/dutyConfig.ts
git commit -m "feat: extend DutyType API types with operational fields"
```

---

## Task 5: i18n Strings

**Files:**
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add new keys to the `duty_config` section**

In `frontend/src/i18n/he.json`, inside the `"duty_config"` object (after `"delete": "מחק"`), add:
```json
    "contact_name": "איש קשר",
    "contact_phone": "טלפון איש קשר",
    "start_time": "שעת התחלה",
    "end_time": "שעת סיום",
    "instructions": "הנחיות",
    "instructions_hint": "עד 300 מילים",
    "is_external": "סוג תורנות",
    "is_external_internal": "פנימית",
    "is_external_external": "חיצונית",
    "is_external_placeholder": "בחר סוג..."
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/i18n/he.json
git commit -m "feat: add i18n keys for duty type operational fields"
```

---

## Task 6: DutyConfigPage — Create Form and List Display

**Files:**
- Modify: `frontend/src/pages/DutyConfigPage.tsx`

- [ ] **Step 1: Add state for new fields**

In the `DutyConfigContent` function, after the existing state declarations (`dtReserveMin`, etc.), add:
```tsx
  const [dtContactName, setDtContactName] = useState("");
  const [dtContactPhone, setDtContactPhone] = useState("");
  const [dtStartTime, setDtStartTime] = useState("");
  const [dtEndTime, setDtEndTime] = useState("");
  const [dtInstructions, setDtInstructions] = useState("");
  const [dtIsExternal, setDtIsExternal] = useState<"" | "true" | "false">("");
```

- [ ] **Step 2: Reset new fields in `addDutyType`**

In the `addDutyType` function, replace the current `createDutyType` call and state resets:
```tsx
  async function addDutyType(e: FormEvent) {
    e.preventDefault();
    await createDutyType({
      name: dtName,
      score_per_day: dtScore,
      reserve_ratio: dtReserveRatio,
      reserve_minimum: parseInt(dtReserveMin) || 0,
      contact_name: dtContactName || null,
      contact_phone: dtContactPhone || null,
      start_time: dtStartTime || null,
      end_time: dtEndTime || null,
      instructions: dtInstructions || null,
      is_external: dtIsExternal === "true",
    });
    setDtName(""); setDtScore("1.00"); setDtReserveRatio("0.000"); setDtReserveMin("0");
    setDtContactName(""); setDtContactPhone(""); setDtStartTime(""); setDtEndTime("");
    setDtInstructions(""); setDtIsExternal("");
    await refresh();
  }
```

- [ ] **Step 3: Add new fields to the create form**

The create form currently ends with the `dt-reserve-min` input and submit button. Add new rows below `dt-reserve-min`, before the submit button:

```tsx
          <label className="block"><span className="text-xs">{t("duty_config.contact_name")}</span>
            <input className="block border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={dtContactName} onChange={(e) => setDtContactName(e.target.value)} data-testid="dt-contact-name" /></label>
          <label className="block"><span className="text-xs">{t("duty_config.contact_phone")}</span>
            <input className="block border rounded p-1 w-32 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={dtContactPhone} onChange={(e) => setDtContactPhone(e.target.value)} data-testid="dt-contact-phone" /></label>
          <label className="block"><span className="text-xs">{t("duty_config.start_time")}</span>
            <input type="time" className="block border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={dtStartTime} onChange={(e) => setDtStartTime(e.target.value)} data-testid="dt-start-time" /></label>
          <label className="block"><span className="text-xs">{t("duty_config.end_time")}</span>
            <input type="time" className="block border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={dtEndTime} onChange={(e) => setDtEndTime(e.target.value)} data-testid="dt-end-time" /></label>
          <label className="block"><span className="text-xs">{t("duty_config.is_external")} *</span>
            <select required className="block border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" value={dtIsExternal} onChange={(e) => setDtIsExternal(e.target.value as "" | "true" | "false")} data-testid="dt-is-external">
              <option value="" disabled>{t("duty_config.is_external_placeholder")}</option>
              <option value="false">{t("duty_config.is_external_internal")}</option>
              <option value="true">{t("duty_config.is_external_external")}</option>
            </select></label>
```

The instructions textarea goes outside the `flex` form row, as a block below the form row (still inside the `<form>`, before the submit button). Restructure the form to have a `<div className="flex items-end gap-2 flex-wrap mb-2">` wrapping the compact inputs and a separate block for instructions:

```tsx
        <form onSubmit={addDutyType} className="space-y-2 mb-2" data-testid="duty-type-form">
          <div className="flex items-end gap-2 flex-wrap">
            {/* existing fields: name, score, reserve_ratio, reserve_min */}
            {/* new fields: contact_name, contact_phone, start_time, end_time, is_external */}
            {/* all inputs as above */}
          </div>
          <label className="block">
            <span className="text-xs">{t("duty_config.instructions")} <span className="text-gray-400">({t("duty_config.instructions_hint")})</span></span>
            <textarea
              className="block border rounded p-1 w-full dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
              rows={3}
              value={dtInstructions}
              onChange={(e) => setDtInstructions(e.target.value)}
              data-testid="dt-instructions"
            />
          </label>
          <button type="submit" className="bg-indigo-600 text-white px-3 py-1 rounded" data-testid="dt-submit">{t("duty_config.add")}</button>
        </form>
```

- [ ] **Step 4: Show new fields in the duty type list row**

Currently, the duty type list row shows name, score, reserve info, active toggle, and the requirements expand button. Extend the expanded section (the `expandedDtId === d.id` block) to also show the new operational fields above the requirements editor. Add a new `showDetails` expanded section — you can reuse `expandedDtId` or add a separate state. The simplest approach: show the new fields as read-only text below the row's main line, always visible (not behind an expand toggle), since they are operational info users frequently need to see:

In the `dt-row` div, after the first `<div className="flex items-center gap-2">...</div>`, add:

```tsx
              {(d.contact_name || d.contact_phone || d.start_time || d.end_time || d.instructions) && (
                <div className="text-xs text-gray-500 dark:text-gray-400 space-y-0.5 mt-1">
                  {(d.contact_name || d.contact_phone) && (
                    <p>{t("duty_config.contact_name")}: {d.contact_name ?? "—"}{d.contact_phone ? ` | ${d.contact_phone}` : ""}</p>
                  )}
                  {(d.start_time || d.end_time) && (
                    <p>{t("duty_config.start_time")}: {d.start_time?.slice(0, 5) ?? "—"} — {d.end_time?.slice(0, 5) ?? "—"}</p>
                  )}
                  {d.instructions && <p>{t("duty_config.instructions")}: {d.instructions}</p>}
                </div>
              )}
              <span className={`text-xs px-1.5 py-0.5 rounded ${d.is_external ? "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200" : "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"}`}>
                {d.is_external ? t("duty_config.is_external_external") : t("duty_config.is_external_internal")}
              </span>
```

Add that badge inside the existing `<div className="flex items-center gap-2">` after the reserve ratio span.

- [ ] **Step 5: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/DutyConfigPage.tsx
git commit -m "feat: show and create duty type operational fields in config page"
```

---

## Task 7: ShiftDetailPanel — Show Operational Fields

**Files:**
- Modify: `frontend/src/components/ShiftDetailPanel.tsx`

The panel already loads duty type names via `listDutyTypes()` into `dutyTypeNames: Record<string, string>`. We need the full `DutyType` objects instead.

- [ ] **Step 1: Change `dutyTypeNames` state to full objects**

Replace the state declaration:
```tsx
  const [dutyTypeNames, setDutyTypeNames] = useState<Record<string, string>>({});
```
with:
```tsx
  const [dutyTypeById, setDutyTypeById] = useState<Record<string, import("../api/dutyConfig").DutyType>>({});
```

Update `handleOpenCoverModal` where `dutyTypeNames` is set:
```tsx
  async function handleOpenCoverModal(swap: SwapRequest) {
    setCoverSwap(swap);
    if (user) {
      const [duties, dts] = await Promise.all([
        listEffectiveDuties(user.id).catch(() => [] as EffectiveDuty[]),
        listDutyTypes().catch(() => []),
      ]);
      setMyDuties(duties);
      setDutyTypeById(Object.fromEntries(dts.map((d) => [d.id, d])));
    }
  }
```

Find the places in the JSX where `dutyTypeNames` was used (it was passed to `CoverOfferModal` and `OfferSwapModal`). Those modals use `dutyTypeNames` to resolve names — replace with:
```tsx
dutyTypeNames={Object.fromEntries(Object.entries(dutyTypeById).map(([id, dt]) => [id, dt.name]))}
```

- [ ] **Step 2: Load duty types for the current shift**

Add a `useEffect` that loads duty types whenever `shift` changes, so we can look up the duty type for the current shift's info block:

```tsx
  const [shiftDutyTypes, setShiftDutyTypes] = useState<Record<string, import("../api/dutyConfig").DutyType>>({});

  useEffect(() => {
    listDutyTypes().catch(() => []).then((dts) => {
      setShiftDutyTypes(Object.fromEntries(dts.map((d) => [d.id, d])));
    });
  }, []);
```

Note: `shift.duty_type_id` is available on `CalendarShift`. Check the `CalendarShift` type in `frontend/src/api/calendar.ts` — if `duty_type_id` is not present, add it. Look up how to get the duty type id from the shift.

- [ ] **Step 3: Check `CalendarShift` for `duty_type_id`**

Read `frontend/src/api/calendar.ts` and check if `CalendarShift` has `duty_type_id`. If not, add it:
```ts
duty_type_id: string;
```
And ensure the backend route `GET /calendar/shifts` returns it. Check `backend/app/routes/calendar.py` — if `CalendarShiftOut` doesn't include `duty_type_id`, add it to the Pydantic schema and mapper.

- [ ] **Step 4: Add operational info block to the panel**

In the JSX of `ShiftDetailPanel`, after the header block (the `<div className="flex justify-between items-center mb-4">` containing shift title and close button), add:

```tsx
        {(() => {
          const dt = shiftDutyTypes[shift.duty_type_id];
          if (!dt) return null;
          const hasInfo = dt.contact_name || dt.contact_phone || dt.start_time || dt.end_time || dt.instructions;
          return (
            <div className="mb-4 p-3 bg-gray-50 dark:bg-gray-700 rounded text-sm space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-xs px-1.5 py-0.5 rounded ${dt.is_external ? "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200" : "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"}`}>
                  {dt.is_external ? t("duty_config.is_external_external") : t("duty_config.is_external_internal")}
                </span>
                {dt.start_time && dt.end_time && (
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {dt.start_time.slice(0, 5)} – {dt.end_time.slice(0, 5)}
                  </span>
                )}
              </div>
              {hasInfo && (
                <>
                  {(dt.contact_name || dt.contact_phone) && (
                    <p className="text-xs text-gray-600 dark:text-gray-300">
                      {t("duty_config.contact_name")}: {dt.contact_name ?? "—"}
                      {dt.contact_phone && <> | <a href={`tel:${dt.contact_phone}`} className="text-indigo-600 dark:text-indigo-400">{dt.contact_phone}</a></>}
                    </p>
                  )}
                  {dt.instructions && (
                    <p className="text-xs text-gray-600 dark:text-gray-300 whitespace-pre-wrap">{dt.instructions}</p>
                  )}
                </>
              )}
            </div>
          );
        })()}
```

- [ ] **Step 5: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```
Expected: no errors. If `duty_type_id` is missing from `CalendarShift`, fix it now and rerun.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ShiftDetailPanel.tsx frontend/src/api/calendar.ts
git commit -m "feat: show duty type operational fields in shift detail panel"
```

---

## Task 8: DutyHistoryPanel — Show Operational Fields on Expanded Assignments

**Files:**
- Modify: `frontend/src/components/DutyHistoryPanel.tsx`

The panel already imports `listDutyTypes`. We need to load the list on mount and pass the matching `DutyType` to each `EventCard`.

- [ ] **Step 1: Add duty types state to the parent component**

Find the main component function in `DutyHistoryPanel.tsx` (search for `export default function` or the function that renders the `Timeline`). Add state and a load effect:

```tsx
  const [dutyTypeById, setDutyTypeById] = useState<Record<string, import("../api/dutyConfig").DutyType>>({});

  useEffect(() => {
    listDutyTypes().catch(() => []).then((dts) => {
      setDutyTypeById(Object.fromEntries(dts.map((d) => [d.id, d])));
    });
  }, []);
```

Pass `dutyTypeById` down to the `Timeline` component (or wherever `EventCard` is rendered), then pass the matching duty type to each `EventCard`:
```tsx
dutyType={e.event_type === "assignment" ? dutyTypeById[e.metadata.duty_type_id ?? ""] ?? null : null}
```

- [ ] **Step 2: Update `EventCard` props**

Add `dutyType` to the `EventCard` props interface:
```tsx
  dutyType?: import("../api/dutyConfig").DutyType | null;
```

- [ ] **Step 3: Render the duty type info block inside `isExpanded`**

Inside the `{isExpanded && (` block in `EventCard`, after the existing `e.description` paragraph and before the `score_total` line, add:

```tsx
            {dutyType && e.event_type === "assignment" && (
              <div className="bg-gray-50 dark:bg-gray-700 rounded p-2 space-y-1 mt-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`text-xs px-1.5 py-0.5 rounded ${dutyType.is_external ? "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200" : "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"}`}>
                    {dutyType.is_external ? t("duty_config.is_external_external") : t("duty_config.is_external_internal")}
                  </span>
                  {dutyType.start_time && dutyType.end_time && (
                    <span className="text-xs text-gray-500 dark:text-gray-400">
                      {dutyType.start_time.slice(0, 5)} – {dutyType.end_time.slice(0, 5)}
                    </span>
                  )}
                </div>
                {(dutyType.contact_name || dutyType.contact_phone) && (
                  <p className="text-xs text-gray-600 dark:text-gray-300">
                    {t("duty_config.contact_name")}: {dutyType.contact_name ?? "—"}
                    {dutyType.contact_phone && <> | <a href={`tel:${dutyType.contact_phone}`} className="text-indigo-600 dark:text-indigo-400">{dutyType.contact_phone}</a></>}
                  </p>
                )}
                {dutyType.instructions && (
                  <p className="text-xs text-gray-600 dark:text-gray-300 whitespace-pre-wrap">{dutyType.instructions}</p>
                )}
              </div>
            )}
```

- [ ] **Step 4: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 5: Run frontend linter**

```
cd frontend && pnpm lint
```
Expected: no warnings (zero warnings enforced).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DutyHistoryPanel.tsx
git commit -m "feat: show duty type operational fields in duty history panel"
```

---

## Task 9: Full Test Run

- [ ] **Step 1: Run all backend tests**

```
cd backend && uv run pytest -q
```
Expected: all pass, no failures.

- [ ] **Step 2: Run frontend tests**

```
cd frontend && pnpm test --run
```
Expected: all pass.

- [ ] **Step 3: Run the dev stack and smoke-test manually**

```
cd .. && .\dev.ps1 -NoBot
```

Open http://localhost:5173, navigate to duty config, create a duty type with all fields filled (contact, hours, instructions, "חיצונית"). Verify it appears in the list with the badge and details. Open the unit calendar, click a shift — verify the operational info block shows. Open a soldier's duty history, click an assignment — verify the info block appears when expanded.
