# Shift Template Auto-Roll "Until Date" — Design

## Problem

Shift templates have an `auto_roll` checkbox ("יצירה אוטומטית"). When checked, a
recurring `roll_horizon` job materialises shifts on a rolling N-day horizon
forever — there's no way to give an auto-rolling template a defined end date.
Commanders want to cap it: pick a date after which the template stops
generating new shifts, and see an estimate of how many shifts that will
produce.

## Data model

Add `auto_roll_until: Date | None` column to `ShiftTemplate`
(`backend/app/db/models.py`), nullable, no server default. `None` preserves
today's behavior (roll forever). New Alembic migration.

## Backend behavior

- `create_template` / `update_template` (`backend/app/services/shift_templates.py`)
  accept and persist `auto_roll_until`.
- Validation (in `_validate` or inline): if `auto_roll_until` is set, it must
  be `>= today`. Reject with the existing 400 validation-error pattern
  otherwise.
- `roll_horizon`: for each active auto-roll template, clamp the generation
  window's end to `min(range_end, tpl.auto_roll_until)` when
  `tpl.auto_roll_until` is set. If `tpl.auto_roll_until < base` (the date
  roll_horizon is running for), skip the template entirely — it has already
  expired. The `auto_roll` flag itself is left untouched; this is purely a
  generation-window clamp, not a state change.
- The manual one-off `generate_shifts` / `preview_generation` endpoints are
  unaffected — the commander picks an explicit range there, so
  `auto_roll_until` doesn't apply.

## API

`routes/shift_templates.py`: `CreateTemplateInput`, `UpdateTemplateInput`, and
the response schema gain `auto_roll_until: date | None = None`.

## Frontend

- `frontend/src/api/shiftTemplates.ts`: `ShiftTemplate`, `CreateTemplateInput`,
  `UpdateTemplateInput` gain `auto_roll_until: string | null`.
- `frontend/src/components/ShiftTemplateFormModal.tsx`:
  - When the `auto_roll` checkbox is checked, reveal a date input directly
    below it, labeled "עד איזה תאריך לייצר" (optional — `min` is today, no
    default value).
  - Unchecking the box hides the field but does not clear its stored value,
    so re-checking restores whatever date was previously entered.
  - Directly under the date field, show a live count when a date is chosen:
    "ייוצרו כ-N מופעים עד התאריך הזה". Computed entirely client-side (no
    backend round-trip, since the template may not exist yet on create) by
    counting matching weekdays between today and the chosen date, mirroring
    the backend's `_effective_weekdays` rule: `daily` → every day; `weekdays`
    → Sun–Thu; `weekly` → the selected start weekday only. `duration_days`
    does not affect the count (each instance is one start date; duration
    only extends that single shift's length).
  - If no date is chosen, no count is shown.
  - Submit payload includes `auto_roll_until` (the date string, or `null` if
    cleared/auto_roll is off).

## Out of scope

- No change to the existing manual "generate shifts in range" flow
  (`GenerateShiftsModal.tsx` / `/generate` / `/preview` endpoints).
- No auto-disabling of the `auto_roll` flag when the until-date passes —
  roll_horizon just stops generating; the checkbox and date stay as-is for
  the commander to edit/extend later.
