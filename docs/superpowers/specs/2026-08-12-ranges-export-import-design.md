# Ranges export/import — design

## Goal

Extend the existing bulk import-session pipeline and the existing round-trip
export/template mechanism to cover the ranges domain, so range data can be
bulk-exported, edited in Excel, and re-imported with the same review/confirm
workflow already used for soldiers, duty shifts, and assignments.

## Scope

Five new importable/exportable sheets, covering the full ranges domain:

| Sheet | Backing model(s) | Mirrors existing sheet |
|---|---|---|
| `range_locations` | `RangeLocation` | `duty_locations` |
| `range_events` | `RangeEvent` | `duty_shifts` |
| `range_assignments` | `RangeAssignment` | `assignments` |
| `soldier_range_qualifications` | `SoldierRangeQualification` | `soldier_exemptions` |
| `range_excusal_requests` | `RangeExcusalRequest` | `exemption_requests` / `personal_constraints` |

### Column layout

**`range_locations`** (update-by-`name`, like `duty_locations`):
`name`, `active`

**`range_events`** (always "new" on import — no dedup, same convention as
`duty_shifts`):
`hierarchy_node_name`, `range_type`, `date`, `range_location_name`,
`required_count`, `reserve_count`, `start_time`, `end_time`,
`arrival_instructions`, `contact_name`, `contact_phone`, `notes`, `status`

**`range_assignments`** (always "new"; resolves to a `range_events` row —
either one created earlier in the same import session or an existing one —
via the composite key `hierarchy_node_name` + `range_type` + `date` +
`range_location_name`, the same way `assignments` resolves against
`duty_shifts`):
`personal_number`, `full_name`, `hierarchy_node_name`, `range_type`, `date`,
`range_location_name`, `is_reserve`, `is_draft`, `attendance_status`, `note`

**`soldier_range_qualifications`** (update-by-`id`, like `soldier_exemptions`):
`id`, `soldier_personal_number`, `range_type`, `valid_until`, `revoked`,
`revoke_reason`

**`range_excusal_requests`** (update-by-`id`, status-validated workflow row,
like `exemption_requests`/`personal_constraints`):
`id`, `soldier_personal_number`, `hierarchy_node_name`, `range_type`, `date`,
`range_location_name`, `reason`, `status` (`pending`/`approved`/`rejected`),
`decided_by_personal_number`, `decision_note`

### Explicitly out of scope

- No new DB models or migrations — all five sheets map onto existing tables.
- No dedup/update matching for `range_events`/`range_assignments` beyond what
  `duty_shifts`/`assignments` already do (i.e. none) — re-importing an
  already-imported export will create duplicates. This is the existing house
  convention, not something this feature changes.

## Backend architecture

- **`app/services/import_parsers/schema.py`** — add five `Import*Row`
  dataclasses (`ImportRangeLocationRow`, `ImportRangeEventRow`,
  `ImportRangeAssignmentRow`, `ImportSoldierRangeQualificationRow`,
  `ImportRangeExcusalRequestRow`) and add the corresponding fields to
  `ParsedImportData`.
- **`app/services/import_parsers/v1_standard.py`** — add the five sheet names
  to `KNOWN_SHEETS`; add a `_sheet_rows`-based parse block per sheet,
  following the existing per-sheet blocks in `V1StandardParser.parse`.
- **`app/services/import_sessions.py`**:
  - `_resolve_range_locations`, `_resolve_range_events`,
    `_resolve_range_assignments` — new resolver functions, added to the
    orchestrator that builds `parsed_state` (~line 949). `_resolve_range_events`
    follows `_resolve_duty_shifts`'s shape (resolve `hierarchy_node_name` →
    `HierarchyNode`, `range_location_name` → `RangeLocation`, scope-check via
    `is_node_in_actor_scope`). `_resolve_range_assignments` follows
    `_resolve_assignments`'s shape, including the session-row-to-created-id
    matching for range_events created earlier in the same import.
  - `confirm_session` — three new apply blocks, each following the
    `duty_shifts`/`assignments` nested-`SAVEPOINT` pattern (isolate each row's
    write so one row's flush failure doesn't poison the outer transaction).
  - Row summary counts.
- **`app/services/import_approvals.py`**:
  - `resolve_soldier_range_qualifications`, `resolve_range_excusal_requests`
    — new resolver functions, id-keyed, status-validated, following
    `resolve_soldier_exemptions`/`resolve_personal_constraints`'s shape.
  - Approving a `range_excusal_request` through import must produce the same
    side effects as the live excusal-approval endpoint (flipping the linked
    `RangeAssignment`'s status) — implementation will check
    `app/services/range_excusal.py` for that logic and reuse it rather than
    duplicating it.
- **`app/routes/import_sessions.py`** — extend `_session_summary`'s
  `row_summary` dict with the five new counts.
- **`app/routes/import_excel.py`** — add the five sheets to
  `EXPORT_DATA_SHEETS` (round-trip export) and to `/import/template`'s example
  workbook.

## Frontend

- **`frontend/src/pages/ImportSessionReviewPage.tsx`** — five new tabs with
  editable row tables, following the `duty_shifts`/`assignments` tab pattern
  (per-field overrides, existing-match picker where relevant, inline error
  display).
- **`frontend/src/pages/planning/ExportPage.tsx`** — new "מטווחים" checkbox
  group for the five sheets, wired to `/import/export?sheets=...`.
- **`frontend/src/pages/ImportUploadPage.tsx`** — update the sheet-name hint
  text to mention the new sheets.
- **`frontend/src/pages/RangesPage.tsx`** — add "ייצוא"/"ייבוא" links to the
  existing unified `/planning/export` and `/import` pages (no new
  ranges-specific pages).

## Authorization

Reuses `require_duty_manager_or_admin` and `is_node_in_actor_scope`
throughout, consistent with how `duty_shifts`/`assignments` are scoped today.

## Testing

- Backend: unit tests per new resolver function and per new apply block
  (small, focused, mirroring the style of existing service tests); one
  integration test driving a full upload → confirm session with a small
  ranges-only workbook covering all five sheets.
- Frontend: component tests for the five new `ImportSessionReviewPage` tabs
  and for the new `ExportPage` checkboxes.
