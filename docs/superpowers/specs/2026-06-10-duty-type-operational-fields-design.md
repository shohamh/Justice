# Duty Type Operational Fields

**Date:** 2026-06-10
**Status:** Approved

## Summary

Add six operational fields to duty types: contact person (name + phone), fixed start/end hours, free-form instructions, and an internal/external flag. These fields are visible when creating/editing duty types in the config page, when clicking an assignment in the duty history panel, and when clicking a shift in the unit calendar.

## Database

Six new columns on the `duty_types` table:

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `contact_name` | `TEXT` | yes | |
| `contact_phone` | `TEXT` | yes | |
| `start_time` | `TIME` (no tz) | yes | |
| `end_time` | `TIME` (no tz) | yes | |
| `instructions` | `TEXT` | yes | ≤300 words |
| `is_external` | `BOOLEAN NOT NULL` | no | |

**Migration:** `ALTER TABLE duty_types ADD COLUMN is_external BOOLEAN NOT NULL DEFAULT false`, then `ALTER TABLE duty_types ALTER COLUMN is_external DROP DEFAULT` so future inserts require it explicitly. The other five columns are added as nullable with no default.

## Backend

### SQLAlchemy (`backend/app/db/models.py`)

Add to `DutyType`:
- `contact_name: Mapped[str | None]` — `Text`, nullable
- `contact_phone: Mapped[str | None]` — `Text`, nullable
- `start_time: Mapped[time | None]` — `Time`, nullable
- `end_time: Mapped[time | None]` — `Time`, nullable
- `instructions: Mapped[str | None]` — `Text`, nullable
- `is_external: Mapped[bool]` — `Boolean`, no Python default

### Pydantic schemas (`backend/app/routes/duty_config.py`)

**`DutyTypeOut`** — add all six fields; `start_time`/`end_time` typed as `datetime.time | None`, `is_external: bool`.

**`CreateDutyTypeRequest`** — add all six; `is_external` is required (no default); `instructions` has a word-count validator: `len(value.split()) <= 300`.

**`UpdateDutyTypeRequest`** — all six optional (consistent with existing PATCH pattern).

**`_dt_out` mapper** — pass the six new fields through from ORM object to `DutyTypeOut`.

### Service (`backend/app/services/duty_config.py`)

`create_duty_type` and `update_duty_type` receive the new kwargs and pass them to the model. No additional business logic.

## Frontend

### `frontend/src/api/dutyConfig.ts`

Extend `DutyType` interface:
```ts
contact_name: string | null;
contact_phone: string | null;
start_time: string | null;   // "HH:MM:SS" from API, display as HH:MM
end_time: string | null;
instructions: string | null;
is_external: boolean;
```
Extend `createDutyType` and `updateDutyType` input types to include the six fields.

### `DutyConfigPage.tsx` (create form)

Add to the new duty type form:
- `contact_name` — text input
- `contact_phone` — text input
- `start_time` / `end_time` — `<input type="time">`
- `instructions` — `<textarea>` with "עד 300 מילים" hint
- `is_external` — required `<select>` with no blank default; options: `false` → "פנימית", `true` → "חיצונית"

In the expanded duty type row in the list, show all new fields (same accordion pattern used for requirements).

### `ShiftDetailPanel.tsx`

The panel already resolves duty type names via `listDutyTypes()`. Extend to display below the shift header (when the duty type has the data set):
- Contact name + phone
- Hours (HH:MM – HH:MM)
- Internal/external badge
- Instructions

### `DutyHistoryPanel.tsx`

Assignment events expand on click. The panel already imports `listDutyTypes`. On expansion of an assignment event, show the same four info blocks (contact, hours, badge, instructions) using the duty type id from `e.metadata.duty_type_id`.

The duty type list is loaded once on mount — no extra API call per event.

## Out of scope

- Phone format validation (free text only)
- Per-shift override of hours (hours are fixed per duty type)
- Replacement approval flow for external duties (mentioned as future work)
