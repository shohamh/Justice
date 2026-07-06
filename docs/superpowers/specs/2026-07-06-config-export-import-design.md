# Export/Import: Duty Types, Duty Locations, Hierarchy, Exemption Types

**Date:** 2026-07-06

## Problem

The Excel export/import system supports `soldiers` and `duty_shifts` (session-based flow: `import_sessions.py` / `ImportSessionReviewPage`), but core configuration — duty types, duty locations, the organizational hierarchy (including which soldier is commander/duty manager of each unit), and exemption types — can only be edited one row at a time through the `DutyConfigPage` / hierarchy UI. There's also no export of this configuration at all today.

## Goal

Add four new sheets — `duty_types`, `duty_locations`, `hierarchy`, `exemption_types` — to the same session-based import pipeline (parser → resolve → review tab → confirm), each independently optional (a workbook may contain any subset). Add a new backend export endpoint producing these sheets from current DB state. Extend the existing `/planning/export` page with one unified checkbox panel covering both this new config export and the two existing report exports (transparency, sub-units), producing a single merged workbook.

**Note:** branch `import-export-assignments` (not yet merged to `dev`) touches the same files (`v1_standard.py`, `schema.py`, `import_sessions.py`, `ImportSessionReviewPage.tsx`) to add a first-class `assignments` sheet. That work is independent of this feature; whichever lands second reconciles the overlap at merge time. This design does not depend on it landing first.

---

## 1. Schema (`import_parsers/schema.py`)

New row models, following the existing `ImportSoldierRow` / `ImportDutyShiftRow` pattern (`source_row` first field, plain strings for anything requiring later resolution):

```python
class ImportDutyLocationRow(BaseModel):
    source_row: int
    name: str
    base: str | None = None
    active: bool | None = None  # None -> defaults to True on create, unchanged on update


class ImportHierarchyNodeRow(BaseModel):
    source_row: int
    name: str
    level: str  # HierarchyLevelType.key, e.g. "corps"
    parent_name: str | None = None
    commander_personal_number: str | None = None
    commander_name: str | None = None
    duty_manager_refs: list[str] = []  # each "personal_number:full_name" pair, split from the cell


class ImportDutyTypeRow(BaseModel):
    source_row: int
    name: str
    score_per_day: str  # parsed to Decimal at resolve time
    description: str | None = None
    active: bool | None = None
    reserve_ratio: str | None = None
    reserve_minimum: int | None = None
    is_external: bool | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    instructions: str | None = None
    eligible_unit_names: list[str] = []
    requirements_json: str | None = None  # raw cell text, parsed+validated at resolve time


class ImportExemptionTypeRow(BaseModel):
    source_row: int
    name: str
    description: str | None = None
    is_global: bool | None = None
    is_medical: bool | None = None
    is_commander_exemption: bool | None = None
    applies_to_duty_type_names: list[str] = []
```

`ParsedImportData` gains `duty_locations`, `hierarchy`, `duty_types`, `exemption_types` fields (each defaulting to `[]`), alongside `soldiers` / `duty_shifts`.

## 2. Parser (`import_parsers/v1_standard.py`)

`KNOWN_SHEETS` gains `"duty_locations"`, `"hierarchy"`, `"duty_types"`, `"exemption_types"` (each sheet, if absent, simply yields `[]` — same `_sheet_rows()` helper already used for `soldiers`/`duty_shifts`).

Column layout per sheet (headers lowercased on read, same convention as existing sheets):

| Sheet | Columns |
|---|---|
| `duty_locations` | `name`, `base`, `active` |
| `hierarchy` | `name`, `level`, `parent_name`, `commander_personal_number`, `commander_name`, `duty_managers` (semicolon-separated `personal_number:full_name` pairs, e.g. `12345:ישראל ישראלי;23456:משה כהן`) |
| `duty_types` | `name`, `score_per_day`, `description`, `active`, `reserve_ratio`, `reserve_minimum`, `is_external`, `contact_name`, `contact_phone`, `start_time`, `end_time`, `instructions`, `eligible_units` (comma-separated unit names), `requirements_json` |
| `exemption_types` | `name`, `description`, `is_global`, `is_medical`, `is_commander_exemption`, `applies_to_duty_types` (comma-separated duty type names) |

`duty_managers` cell parsing reuses the same `;`-split-then-`:`-split convention as the existing `node_quotas` column (`_parse_node_quotas` in the same file) — malformed entries produce a row-tagged parser warning and are skipped individually, not fatal to the row.

## 3. Resolution (`services/import_sessions.py`)

New resolver functions, added in dependency order (each may reference names resolved by an earlier one in the same workbook):

**`_resolve_duty_locations()`** — match existing `DutyLocation` by `name`; `action` = `update` if matched, else `new`. No cross-references.

**`_resolve_hierarchy()`** — match existing `HierarchyNode` by `name`; `action` = `update`/`new`.
- `level`: validated against existing `HierarchyLevelType.key` values; unmatched → row error.
- `parent_name`: resolved by name **within the same resolution pass**, two passes over `data.hierarchy` so a child row can precede its parent row in the sheet — first pass builds `name -> resolved-or-new` records, second pass links `parent_id`. A parent name that resolves to neither an existing node nor another row in this sheet → row error. Root nodes (no parent) leave `parent_name` blank.
- `commander_personal_number` / `commander_name`: resolved against existing soldiers — **personal number first; if it doesn't match any soldier, fall back to matching by `commander_name`** (exact, case-sensitive-off match). No match on either → row error (a hierarchy row cannot silently drop its commander). Ambiguous name match (multiple soldiers, same full name) → row error.
- `duty_manager_refs`: same personal-number-then-name resolution per entry, independently; unresolvable individual entries are **per-entry errors** appended to the row's `errors` list (not necessarily failing the whole row) — mirrors the existing pattern of node-quota entries in `_resolve_duty_shifts()` where quota resolution failures are per-entry, but here an unresolved duty-manager entry blocks the row (a partially-applied duty manager list is worse than an explicit error) — action becomes `error` if any entry is unresolved.
- Like `_resolve_soldiers()` / `_resolve_duty_shifts()`, honors the existing `_name_mappings` by-row/by-name override mechanism (`nm.get("hierarchy_node", ...)`) for manual disambiguation via the review UI's existing "pick a match" picker — reused as-is for `parent_name` resolution; commander/duty-manager soldier lookups use the existing pattern from `_resolve_soldiers()`.
- Actor scope: same `is_node_in_actor_scope()` check as `_resolve_soldiers()` — a non-admin actor can only create/update nodes within their scope; out-of-scope rows get `action="out_of_scope"`.

**`_resolve_duty_types()`** — match existing `DutyType` by `name`.
- `eligible_unit_names`: each resolved by name against `HierarchyNode` (existing + this-sheet's `hierarchy` rows, using the same combined lookup pattern as `_resolve_duty_shifts()`'s node-quota resolution); unresolved names are per-entry errors on the row (row action becomes `error` if any name is unresolved — an eligibility list can't silently drop a unit).
- `requirements_json`: if present, parsed with `json.loads`; invalid JSON → row error with the parse exception message. Blank cell → leave existing `requirements` untouched on update, or default `{}` on create (matches the DB column's own default).
- `score_per_day` / `reserve_ratio`: parsed as `Decimal`; non-numeric → row error.

**`_resolve_exemption_types()`** — match existing `ExemptionType` by `name`.
- `applies_to_duty_type_names`: resolved by name against `DutyType` (existing + this-sheet's `duty_types` rows); unresolved → per-entry error, same treatment as `duty_types.eligible_unit_names`.

`_resolve_and_score()` calls these four in order (`duty_locations`, `hierarchy`, `duty_types`, `exemption_types`) after the existing `soldiers` / `duty_shifts` / `shift_templates` resolvers, passing the same `_name_mappings` structure through.

## 4. Review UI (`ImportSessionReviewPage.tsx`)

`TabKey` gains `"duty_locations" | "hierarchy" | "duty_types" | "exemption_types"`. Each gets a tab following the exact same table/row-action/pending-pick pattern as `soldiers`/`duty_shifts`:

- **Duty Locations**: name, base, active, action.
- **Hierarchy**: name, level, resolved parent (with picker on mismatch, reusing the existing node-picker affordance), commander (resolved name or error), duty managers (resolved list or per-entry errors), action.
- **Duty Types**: name, score/day, active, eligible units (resolved list with picker for unresolved names), requirements JSON validity indicator, action.
- **Exemption Types**: name, flags (global/medical/commander), applies-to list (resolved with picker), action.

Same row-action-override select (new → skip, etc.) as existing tabs.

## 5. Commit (`confirm_session()`, `services/import_sessions.py`)

Applied in the same dependency order as resolution (locations → hierarchy → duty types → exemption types), each wrapped in a per-row `session.begin_nested()` savepoint (same pattern as `duty_shifts`) so one bad row doesn't roll back the whole import:

- **Duty Locations**: create or update matched fields.
- **Hierarchy**: create or update `HierarchyNode` (`name`, `level`, `parent_id`, `commander_id`); `path_ids` recomputed via the existing hierarchy service helper used by the manual hierarchy-edit routes (not reimplemented here). Duty managers: existing `DutyManagerScope` rows for this node are replaced with the resolved set from `duty_manager_refs` (diffed: remove rows not in the new set, add rows not already present) — this is an update to the row's own field, not the earlier-established "no deletes across rows" rule (which concerns whether an *absent sheet row* deletes an entity, not what an *present row's own list field* overwrites).
- **Duty Types**: create or update all scalar fields plus `eligible_node_ids` (from resolved `eligible_unit_names`) and `requirements` (from parsed JSON, when the cell was non-blank).
- **Exemption Types**: create or update scalar fields; `ExemptionDutyTypeMap` rows diffed against resolved `applies_to_duty_type_names` the same way as `DutyManagerScope` above.

`skip` / `out_of_scope` rows are no-ops; `error` rows are excluded from confirm, same as existing sheets. Response payload's `created`/`updated`/`skipped` counts extend to include these four groups.

## 6. Export (new `GET /config/export`, new route file `app/routes/config_export.py`)

Separate from the (in-progress, unmerged) `GET /import/export` endpoint in the sibling assignments design, to avoid a merge collision — this endpoint is scoped to config data only and can be folded together later if useful.

```
GET /config/export?sheets=duty_types,duty_locations,hierarchy,exemption_types
```

`sheets` query param: comma-separated subset of the four sheet names; defaults to all four if omitted. Returns a `StreamingResponse` xlsx (same `openpyxl.Workbook()` + `StreamingResponse` pattern as `download_template()` in `import_excel.py`), containing only the requested sheets, each with the exact column layout from §2, populated from current DB state:

- **`duty_locations`**: all rows, straight field dump.
- **`hierarchy`**: all nodes; `parent_name` resolved via `parent_id`; `commander_personal_number`/`commander_name` from the linked `Soldier` (blank if no commander); `duty_managers` cell built by joining `DutyManagerScope` rows for that node as `personal_number:full_name` pairs.
- **`duty_types`**: all fields dumped as-is; `eligible_units` built from `eligible_node_ids` resolved to names; `requirements_json` is `json.dumps(requirements)` (empty dict serializes to `"{}"`, matching what a blank-cell import treats as "no change").
- **`exemption_types`**: all fields; `applies_to_duty_types` built from `ExemptionDutyTypeMap` rows resolved to duty type names.

Requires `require_duty_manager_or_admin` (same dependency as the rest of the import/export system).

## 7. Frontend export UI (`pages/planning/ExportPage.tsx`)

Replace the current two separate cards with a single panel: a checkbox list with all 6 export options —

- Transparency (existing, client-built)
- Sub-units (existing, client-built)
- Duty Types (new)
- Duty Locations (new)
- Hierarchy (new)
- Exemption Types (new)

— and one "ייצוא" button. On click:

1. For checked client-built sheets (transparency/sub-units), build worksheets exactly as `ExcelExportButton` does today (`XLSX.utils.aoa_to_sheet`), but append to a single shared `XLSX.utils.book_new()` workbook instead of writing immediately.
2. If any config checkboxes are checked, `fetch` `GET /config/export?sheets=...` with the checked subset, get the response as an `ArrayBuffer`, `XLSX.read()` it, and `XLSX.utils.book_append_sheet()` each of its sheets into the same shared workbook.
3. `XLSX.writeFile(workbook, "export.xlsx")` once, after both steps — single file, single download, containing only the checked sheets.

`ExcelExportButton` itself is not reused directly (it writes-and-downloads in one step); its per-column-to-row logic (`exportValueOf`) is extracted into a small shared helper so both the existing inline usage and this new combined flow share it, rather than duplicating the column-to-cell-value logic.

## 8. Template download (`GET /import/template`, `import_excel.py`)

Extend `download_template()` with the four new example sheets (small illustrative rows, same style as the existing `soldiers`/`duty_shifts` examples), so a user starting from scratch has a working starting point for all six sheets.

## 9. Testing

- `test_import_parser_v1.py`: parsing each of the 4 new sheets into their row models; absent-sheet handling (defaults to `[]`); malformed `duty_managers`/`node`-list cell handling (warnings, not fatal).
- `test_import_sessions_service.py`: each new `_resolve_*()` — name matching (create/update), parent-by-name two-pass resolution (including forward references), commander/duty-manager personal-number-then-name fallback (single match, ambiguous, no match), eligible-units/applies-to cross-sheet-and-DB resolution, `requirements_json` validation, actor scope for hierarchy rows.
- `test_import_sessions_api.py`: end-to-end session flow including all 4 new sheets; confirm creating/updating each entity type, including `DutyManagerScope`/`ExemptionDutyTypeMap` diffing (add + remove).
- New test file for `GET /config/export`: per-sheet content correctness; round-trip — export, then create a new session from the exported file, assert everything resolves as `update` with no diffs (idempotent re-import).
- Frontend: `ExportPage.test.tsx` — checkbox selection producing a merged workbook with exactly the checked sheets (mock the `/config/export` fetch).

## Out of scope

- Deleting entities absent from an imported sheet (explicitly decided: import only creates/updates, never deletes rows missing from the sheet).
- Any interaction with the not-yet-merged `import-export-assignments` branch's `assignments` sheet or its `GET /import/export` endpoint — reconciled at merge time, not designed against here.
- Editing `HierarchyLevelType` definitions themselves (the `level` column only *references* existing level-type keys; creating new level types remains UI-only).
- A full sync/delete mode — only additive create/update, per the earlier decision in this design's brainstorming.
