# Import/Export: Assignments Sheet

**Date:** 2026-07-06

## Problem

The Excel import/export flow (session-based: `import_sessions.py` / `ImportSessionReviewPage`) supports `soldiers` and `duty_shifts` sheets, but there is no way to import or export actual soldier-to-shift assignments (which soldier is assigned to which specific duty shift instance). There is also no way to export current DB state as an xlsx workbook at all today — export only exists client-side for unrelated pages (potential, transparency) and server-side for the potential table.

## Goal

Add a third `assignments` sheet to the import template, parser, review UI, and confirm flow, so a workbook can carry `personal_number` + `full_name` soldiers assigned to specific `duty_shifts` rows. Add a new backend export endpoint that dumps current DB state (soldiers, duty_shifts, assignments) into the same 3-sheet format, enabling a full export → edit → re-import round trip.

---

## 1. Template (`GET /import/template`, `import_excel.py`)

Add a third sheet, **`assignments`**, with headers:

| Column | Notes |
|---|---|
| `personal_number` | Primary soldier lookup key |
| `full_name` | Cross-check when `personal_number` matches; fallback lookup key when it doesn't (see §3) |
| `duty_type_name` | Part of the shift composite key |
| `duty_location_name` | Part of the shift composite key |
| `start_date`, `end_date` | `dd.mm.yyyy`, same format as `duty_shifts` |
| `start_time`, `end_time` | `HH:MM`, same format/defaults as `duty_shifts` (`00:00`/`23:59`) |
| `is_reserve` | `true`/`false`, same parsing as existing `is_reserve` fields |
| `notes` | Optional, free text |

This replaces the current legacy fallback behavior in `v1_standard.py` (lines ~113-128) where an `assignments` sheet — only read when `duty_shifts` is absent — is silently converted into synthetic single-slot `duty_shifts` rows. That fallback is removed; `assignments` becomes a first-class sheet parsed independently and always available alongside `duty_shifts`.

## 2. Parser (`import_parsers/v1_standard.py`, `schema.py`)

Add `ImportAssignmentRow` to `schema.py` with fields mirroring the columns above, plus `source_row` (as the other row types have).

`V1StandardParser` gains an `assignments` sheet reader producing a list of `ImportAssignmentRow`, attached to `ParsedImportData.assignments` (new attribute, alongside `.soldiers` / `.duty_shifts`).

## 3. Resolution (`services/import_sessions.py`)

### Soldier lookup fallback (applies to both `soldiers` sheet and new `assignments` sheet)

When resolving a row's soldier by `personal_number`:

1. **`personal_number` matches an existing soldier** → use it.
   - *Soldiers sheet:* proceed as a normal update; `full_name` in the row is simply one of the fields being written (no separate cross-check — a name change is just an update).
   - *Assignments sheet:* cross-check the row's `full_name` against the matched soldier's actual `full_name`. Mismatch → row `action="error"`.
2. **`personal_number` does not match any soldier** → fall back to looking up by `full_name` (exact match) against existing soldiers:
   - **Exactly one match** →
     - *Soldiers sheet:* treat the row as an **update** to that soldier (this row's `personal_number` replaces theirs). Row gets a `warning`: `"matched by name, personal_number changed from X to Y"`.
     - *Assignments sheet:* use that soldier to resolve the assignment. Row gets a `warning`: `"matched by name (personal_number '<value>' not found)"`.
   - **More than one match** → `action="error"` (ambiguous full_name).
   - **No match at all** →
     - *Soldiers sheet:* `action="new"`, as today.
     - *Assignments sheet:* `action="error"` (soldier cannot be resolved).

This requires `_resolve_soldiers()` to build a `by_full_name` lookup (in addition to the existing `by_personal_number` lookup) over current DB soldiers, and `_resolve_assignments()` to reuse that same combined lookup (extended with any soldiers newly created earlier in the same session's `soldiers` sheet — a soldier created in this import must be resolvable by an assignments row in the same file).

### Shift lookup (new `_resolve_assignments()`)

Each assignment row resolves its target shift via the composite key `(duty_type_name, duty_location_name, start_date, end_date, start_time, end_time)`, matched (in this order) against:

1. `DutyShift` rows resolved from this session's own `duty_shifts` sheet (including ones not yet persisted — matched by their resolved field values, not DB id, since they don't have one yet).
2. Existing `DutyShift` rows already in the DB.

No match in either → `action="error"`.

### Duplicate handling

If the resolved soldier is already assigned (existing `DutyAssignment` with the same `soldier_id` + resolved `duty_shift_id`) → `action="skip"` (no-op; re-importing the same export is idempotent).

### Capacity check

If applying this row would bring the shift's assigned-soldier count above its `required_count` → row stays `action="new"` (not blocked) but gets a `warning`: `"shift already has N/required_count soldiers assigned"`.

### Actor scope

Same scope-check pattern as `_resolve_soldiers()` / `_resolve_duty_shifts()`: a non-admin actor can only create assignments for soldiers within their hierarchy scope; out-of-scope rows get `action="out_of_scope"`.

`_resolve_and_score()` calls `_resolve_assignments()` after `_resolve_soldiers()` and `_resolve_duty_shifts()`, passing through the resolved (not-yet-persisted) duty_shifts list so composite-key matching against in-session shifts is possible.

## 4. Review UI (`ImportSessionReviewPage.tsx`)

Add an `assignments` tab alongside the existing `soldiers` / `duty_shifts` tabs, showing per row: `personal_number`, `full_name`, resolved shift summary (duty type / location / dates), `action`, and any `warning`/`error` text. Same row-action-override affordance (e.g. new → skip) as the other tabs. No new fuzzy-matching combobox is introduced for this sheet — soldier/shift resolution ambiguity is a hard error, not a pick-a-candidate flow (per §3).

## 5. Commit (`confirm_session()`, `services/import_sessions.py`)

After creating `duty_shifts` (existing logic), iterate resolved `assignments`:

- For each row with `action in ("new",)`, create a `DutyAssignment` with `soldier_id`, `duty_shift_id` (from the just-created shift or the pre-existing one), and denormalized `duty_type_id`/`duty_location_id`/`start_date`/`end_date`/`start_time`/`end_time` copied from the matched shift, plus `is_reserve`, `notes`, `status="published"`.
- Use a savepoint per row (same pattern as `duty_shifts`) so one bad row doesn't roll back the whole import.
- `skip` / `out_of_scope` rows are no-ops. `error` rows are excluded from confirm entirely (as with the other sheets).

Response payload (`created`/`updated`/`skipped`/`errors`) gains assignment counts alongside soldier/duty_shift counts.

## 6. Export (new `GET /import/export`, `import_excel.py`)

New endpoint producing a 3-sheet workbook (`soldiers`, `duty_shifts`, `assignments`) in exactly the template's column layout, populated from current DB state:

- **`soldiers`**: all soldiers, one row each.
- **`duty_shifts`**: all duty shifts; `node_quotas` serialized back to `"unit:count;unit:count"` (inverse of the existing parse).
- **`assignments`**: all `DutyAssignment` rows with a non-null `duty_shift_id`, with `duty_type_name`/`duty_location_name`/dates/times taken from the linked `DutyShift`, plus the assignment's own `full_name` (via soldier), `is_reserve`, `notes`. Assignments with no linked `duty_shift_id` (legacy/manual assignments not tied to a shift instance) are omitted — they have no composite key to export.

This is a straight DB dump, not tied to any particular import session. Combined with the template/parser changes, this gives a full round trip: export current state → edit in Excel → re-import (unchanged rows resolve as `skip`, added rows as `new`).

## 7. Testing

- `test_import_parser_v1.py`: parsing the new `assignments` sheet into `ImportAssignmentRow`s; removal of the old fallback-to-duty_shifts behavior.
- `test_import_sessions_service.py`: `_resolve_assignments()` cases — shift match against in-session and existing shifts, personal_number match, full_name fallback (single/ambiguous/none) for both soldiers and assignments sheets, duplicate skip, over-capacity warning, actor scope.
- `test_import_sessions_api.py`: end-to-end session flow including an `assignments` sheet, confirm creating `DutyAssignment` rows.
- New test file (or extend `test_import_excel.py`) for `GET /import/export`: round-trip — export, then re-import the exported file, assert everything resolves as `skip`/no changes.

## Out of scope

- Exporting or importing `shift_templates` (unrelated to this feature; still UI-only as today).
- A fuzzy-match/combobox picker for ambiguous soldier names (ambiguity is a hard error here, unlike duty_type/hierarchy_node name mapping).
- Any change to the legacy `/import/preview` + `/import/apply` endpoints in `import_excel.py` (left as-is; not used by the current frontend).
