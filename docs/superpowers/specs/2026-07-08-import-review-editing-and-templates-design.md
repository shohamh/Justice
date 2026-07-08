# Import Review: Inline Editing + Shift Templates + Export Reconciliation

**Date:** 2026-07-08

## Problem

Three gaps in the session-based import/export system (`import_sessions.py` / `ImportSessionReviewPage.tsx`):

1. **Two disconnected export endpoints.** `GET /api/config/export` (duty_types, duty_locations, hierarchy, exemption_types + client-built transparency/sub_units — see `2026-07-06-config-export-import-design.md`) and `GET /api/import/export` (soldiers, duty_shifts, assignments) were never reconciled, as that earlier design explicitly deferred. The `/planning/export` page only calls the former. A user exporting from that page and re-importing the result sees soldiers/duty_shifts/assignments as 0 — not a parsing bug, the sheets were never in the file.
2. **duty_types/exemption_types review tabs show almost nothing.** The backend resolvers (`_resolve_duty_types`, `_resolve_exemption_types`) already compute every field (description, active, reserve_ratio, contact info, times, instructions, requirements, eligible units, applies-to list), but the frontend types and table only expose `name` + `score_per_day` (duty_types) or `name` alone (exemption_types), and nothing is editable before confirming.
3. **`shift_templates` is dead scaffolding.** `_resolve_shift_templates()` exists but always operates on `getattr(data, "shift_templates", [])`, which is permanently `[]` — `ParsedImportData` has no such field, no parser reads a `shift_templates` sheet, and `confirm_session()` has no branch that creates `ShiftTemplate` rows. It's UI-only today.

## Goal

- Reconcile exports: `/planning/export` gains a second checkbox group ("נתוני מערכת": soldiers, duty shifts, assignments, shift templates) that merges in sheets from `/api/import/export`, so the page produces a genuine full round-trip export.
- duty_types and exemption_types review tabs show every field, and every field is editable pre-confirm via a new generic "field override" mechanism.
- `shift_templates` becomes a real, first-class sheet: parsed, validated, resolved, shown with full detail + inline edit, and created/updated on confirm — matching the real `ShiftTemplate` model (not the stale `required_primary`/`required_reserve` fields in the dead scaffold).

---

## 1. Export reconciliation (`ExportPage.tsx`)

Add a second `CONFIG_SHEET_OPTIONS`-style list, `DATA_SHEET_OPTIONS`, with one combined checkbox ("ייצוא נתוני מערכת (חיילים, משמרות, שיבוצים, תבניות)" — since `/api/import/export` returns all four sheets together as one workbook, not selectable individually, unlike `/config/export`'s per-sheet query param). When checked, `handleExport()` additionally `fetch`es `/api/import/export`, reads it with `XLSX.read`, and merges its sheets into the shared workbook — same pattern already used for the config-sheets fetch (§7 of the referenced design). No changes to `/api/import/export` itself beyond adding the `shift_templates` sheet (see §5).

## 2. Generic field-override mechanism (`import_sessions.py`, `ImportSessionReviewPage.tsx`)

New `selections` namespace, sibling to the existing `_name_mappings`:

```python
selections["_field_overrides"] = {
    "duty_types": {"<row>": {"<field>": <value>, ...}, ...},
    "exemption_types": {"<row>": {...}, ...},
    "shift_templates": {"<row>": {...}, ...},
}
```

`_resolve_and_score()` extracts `fo = (selections or {}).get("_field_overrides", {})` and passes `fo.get("duty_types", {})` / `fo.get("exemption_types", {})` / `fo.get("shift_templates", {})` into the corresponding resolver. Each resolver applies overrides to its row **before** running its existing validation for that row (so an edited `score_per_day` is re-validated as a Decimal, an edited `requirements_json`-equivalent re-parsed as JSON, etc. — reusing 100% of the existing per-field validation, none of it duplicated). Concretely: build a plain dict of the row's fields first (from the parsed `row.*` attributes), shallow-merge `overrides.get(str(row.source_row), {})` on top, then run the rest of the resolver body against that merged dict instead of `row.<field>` directly.

Frontend: extending `applyMapping`'s existing pattern (`setSelections` → debounced `saveSelections` → `reparseSession`), a new `setFieldOverride(group, row, field, value)` helper does the same: update `selections._field_overrides[group][row][field]`, debounce-save (reuse the existing `saveTimer` 500ms pattern), and trigger `handleReparse()` on blur (not on every keystroke, to avoid a reparse round-trip per character — text inputs update local `selections` state immediately for display, and reparse fires on blur/debounce-settle same as the existing save timer). `confirm_session()` requires **no changes**: it reads `import_session.parsed_state`, which already reflects the last reparse.

## 3. duty_types / exemption_types: full detail + inline edit (`ImportSessionReviewPage.tsx`, `api/importSessions.ts`)

Extend TS interfaces to match what the backend already returns (no backend change needed here — see current `_resolve_duty_types`/`_resolve_exemption_types` output dicts):

```ts
export interface DutyTypeImportRow extends RowBase {
  name: string;
  score_per_day: string | null;
  description: string | null;
  active: boolean | null;
  reserve_ratio: string | null;
  reserve_minimum: number | null;
  is_external: boolean | null;
  contact_name: string | null;
  contact_phone: string | null;
  start_time: string | null;
  end_time: string | null;
  instructions: string | null;
  resolved_eligible_node_ids: string[];
  requirements: Record<string, unknown> | null;
  existing_id: string | null;
}

export interface ExemptionTypeImportRow extends RowBase {
  name: string;
  description: string | null;
  is_global: boolean;
  is_medical: boolean;
  is_commander_exemption: boolean;
  resolved_duty_type_ids: string[];
  existing_id: string | null;
}
```

Table columns, editable via `setFieldOverride` (disabled when `readOnly`):

- **duty_types**: name, score_per_day, description, active (checkbox), reserve_ratio, reserve_minimum, is_external (checkbox), contact_name, contact_phone, start_time, end_time, instructions — all plain inline `<input>`/`<textarea>`/`<checkbox>`. Eligible units and requirements open a modal (below).
- **exemption_types**: name, description, is_global/is_medical/is_commander_exemption (checkboxes) — inline. Applies-to-duty-types opens a modal (below).

**Modal for complex fields** — one new component, `ImportRowFieldsModal`, parameterized by which sub-editors it shows:
- Eligible units (duty_types) / applies-to duty types (exemption_types): reuse `SubHierarchySelector` (for units) and a multi-select built on the existing `Combobox` (for duty types) — both already used elsewhere in the codebase for equivalent pickers.
- Requirements (duty_types only): reuse `DutyTypeRequirementsEditor`'s field markup. That component currently always calls `updateDutyTypeRequirements()` directly on save — add an optional controlled mode: `{ value, onChange }` props alongside its existing `{ dutyType, onSaved }` API-writing mode. When `value`/`onChange` are provided, render the same checkboxes bound to `value`/`onChange` instead of local state + API call. Existing callers (`DutyConfigPage`) are unaffected; the modal is the only new caller of the controlled mode.

The modal writes back to `selections._field_overrides` the same way inline fields do, via the same `setFieldOverride` helper (fields `resolved_eligible_node_ids` / `requirements` / `resolved_duty_type_ids` become override keys directly — the resolver already accepts these as row fields, since it currently sets them; overriding them pre-empties the resolver's own name-based resolution for that row).

## 4. Shift templates: real import/export pipeline

**Schema (`import_parsers/schema.py`):**

```python
class ImportShiftTemplateRow(BaseModel):
    source_row: int
    name: str
    duty_type_name: str
    duty_location_name: str
    recurrence_type: str = "weekdays"  # "weekdays" | "daily" | "weekly"
    weekdays: list[int] = []  # ISO 1=Mon..7=Sun; only meaningful for "weekly"
    start_time: str | None = None
    end_time: str | None = None
    required_count: int = 1
    auto_roll: bool = False
    auto_roll_until: str | None = None  # ISO date
    duration_days: int = 1
    notes: str | None = None
    eligible_unit_names: list[str] = []
```

`ParsedImportData.shift_templates: list[ImportShiftTemplateRow] = []` (replaces the `getattr(..., [])` fallback).

**Parser (`v1_standard.py`):** `KNOWN_SHEETS` gains `"shift_templates"`. Columns: `name, duty_type_name, duty_location_name, recurrence_type, weekdays, start_time, end_time, required_count, auto_roll, auto_roll_until, duration_days, notes, eligible_units` — `weekdays` and `eligible_units` are comma-separated, same convention as `duty_types.eligible_units`.

**Resolver (`_resolve_shift_templates`, rewritten):** match existing `ShiftTemplate` by `name` (`update` vs `new`, same convention as duty_types/exemption_types — no uniqueness constraint exists on the column today, so this matches "first found by name" like the others). Resolve `duty_type_name`/`duty_location_name` (row error if unmatched, honoring `_name_mappings` the same way `_resolve_duty_shifts` does for duty types). Resolve `eligible_unit_names` the same way `_resolve_duty_types` resolves its eligible units (per-entry error, row becomes `error` if any unresolved). Validate `recurrence_type` is one of the three known values. Actor scope check via `is_node_in_actor_scope` against the duty type's/location's... — no natural single "owner" node for a shift template beyond its eligible units; scope check mirrors `_resolve_duty_types`' treatment (no scope restriction on create, since duty types themselves aren't scope-restricted either).

**Confirm (`confirm_session`):** new loop placed after the duty_types and duty_locations loops (it depends on their resolved IDs) and before assignments, same per-row `session.begin_nested()` pattern as the others, creating/updating `ShiftTemplate` rows. `created_links["shift_templates"]` added.

**Template download (`/import/template`) + export (`/import/export`):** add a `shift_templates` sheet to both, matching the columns above; export writes all existing `ShiftTemplate` rows with `eligible_units` resolved back to names.

**Review UI:** new `shift_templates` tab replacing the current dead one, following the exact table/inline-edit pattern from §3 — name, duty_type, duty_location, recurrence_type (inline select), weekdays (7 inline day-toggle buttons, shown only when `recurrence_type === "weekly"`), start/end time, required_count, auto_roll (checkbox) + auto_roll_until (date, shown when auto_roll checked), duration_days, notes — all inline. Eligible units open the same `ImportRowFieldsModal` from §3.

## Out of scope

- Any change to the live `ShiftTemplateFormModal` / `DutyConfigPage` editing flows — those remain the primary UI for one-off edits; this adds a bulk Excel path alongside them.
- Deleting entities absent from an imported sheet (consistent with the existing rule across all sheets: import only creates/updates).
- `recurrence_type: "weekly"` with more than one weekday (the model technically allows a `weekdays` array, but no existing UI or business logic supports multi-day weekly recurrence — the sheet format allows a comma list for forward-compatibility, but validation doesn't need to special-case more than one entry beyond passing it through).

## Testing

- `test_import_parser_v1.py`: `shift_templates` sheet parsing, absent-sheet default `[]`.
- `test_import_sessions_service.py`: `_resolve_shift_templates` (name matching, duty_type/location resolution, eligible units, recurrence_type validation), `_field_overrides` applied before validation for duty_types/exemption_types/shift_templates (each: override changes the row's resolved output, and an invalid override value produces the same error as an invalid Excel cell would).
- `test_import_sessions_api.py`: end-to-end shift_templates upload → confirm → `ShiftTemplate` row created; end-to-end field-override upload → set override via `saveSelections` → reparse → confirm creates the overridden values, not the original sheet values.
- `test_import_excel.py`: `/import/template` and `/import/export` include `shift_templates`.
- Frontend: `ImportSessionReviewPage.test.tsx` — duty_types/exemption_types/shift_templates tabs render full fields; inline edit updates selections and triggers reparse; `ImportRowFieldsModal` round-trips eligible units / requirements / applies-to.
- `DutyTypeRequirementsEditor.test.tsx` (existing file) — new controlled-mode props don't break existing API-writing mode tests.
- `ExportPage.test.tsx` — new data-sheets checkbox merges `/api/import/export` sheets into the combined workbook.
