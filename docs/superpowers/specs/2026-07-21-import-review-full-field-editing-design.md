# Import Review: Complete Inline Field-Editing, Inspection & Assignment Remap

**Date:** 2026-07-21

## Problem

The per-field inline-edit mechanism (`_field_overrides` + `setFieldOverride`, added in
the 2026-07-08 import-review design) only covers 3 of 8 import tabs: `duty_types`,
`exemption_types`, `shift_templates`. The other five — `soldiers`, `duty_shifts`,
`assignments`, `duty_locations`, `hierarchy` — still only offer a status chip and an
approve/skip action select; none of their fields can be corrected pre-confirm, and none
of the rows can be inspected in full (some fields aren't rendered as table columns at
all, e.g. a soldier's `phone`/`email`/`enlistment_date`).

Separately, `assignments` has no error-recovery path: an unmatched `duty_type_name`,
`duty_location_name`, or shift-matching key just renders a red error, with no combobox
remap like soldiers/duty_shifts already have for their own unresolved names.

Finally, the soldier import schema only captures a subset of the `Soldier` model's
profile fields (personal_number, full_name, rank, gender, is_officer, hierarchy_node,
enrolled_at, enlistment_date, phone, email) — missing `is_career`, `next_rank_date`,
`bahad1_graduate`, `has_military_driving_license`, `military_driving_license_expiry`,
`mandatory_end_date`, `discharge_date`, `last_mitvahim_date`, `last_alal_date`, `left_at`.

## Goal

- Every one of the 8 import tabs gets: (a) scalar fields inline-editable via
  `_field_overrides` (same mechanism as duty_types today), (b) relational/lookup fields
  kept on the existing combobox/remap flow, (c) a "details" modal that shows every field
  for a row in one place, editable where applicable.
- `assignments` gains the same combobox/remap UX that soldiers/duty_shifts already have,
  for its unresolved `duty_type_name`/`duty_location_name`.
- Soldier import round-trips the full set of profile fields the `Soldier` model
  actually has (minus system/security/derived fields and `profile_picture_url`, which
  needs file upload rather than a text column).

Out of scope: multi-select/JSON editors for duty_types/exemption_types/shift_templates
(already exist via `ImportRowFieldsModal`, unchanged). Export/import of requests,
exemptions, and standalone personal constraints (separate specs).

---

## 1. Backend: extend `_field_overrides` to all resolvers

`backend/app/services/import_sessions.py` — each of the five resolvers gains an
`overrides: dict[str, dict] | None = None` parameter, applied with the exact pattern
already used in `_resolve_duty_types` (`override = overrides.get(str(row.source_row),
{})`, then a local `field(name, default)` helper reading from `override` first, else the
parsed value):

- `_resolve_soldiers(session, data, actor, node_by_name, node_by_row, overrides=None)`
- `_resolve_duty_locations(session, data, overrides=None)`
- `_resolve_hierarchy(session, data, actor, node_by_name, node_by_row, overrides=None)`
- `_resolve_duty_shifts(session, data, actor, dt_by_name, dt_by_row, node_by_name, node_by_row, overrides=None)`
- `_resolve_assignments(session, data, actor, duty_shifts, dt_by_name, dt_by_row, overrides=None)`
  (also gains the `dt_by_name`/`dt_by_row` duty-type mapping params it currently lacks —
  see §3; no hierarchy-node params, since assignments have no direct node reference)

`_resolve_and_score` passes `fo.get("<group>", {})` into each, same as the three
existing calls. No changes to `set_selections`, `confirm_session`, or the
`_field_overrides` schema itself — it already stores per-group/per-row dicts generically.

## 2. Frontend: scalar inline edit for the five remaining tabs

`ImportSessionReviewPage.tsx` — each tab's table cells switch from plain text to the
existing `readOnly ? <span> : <input onBlur={setFieldOverride(...)}>` pattern (copied
verbatim from the duty_types/shift_templates cells). `setFieldOverride`'s `group`
parameter type widens from the current 3-value union to a plain `string` (it's only
ever used as a dict key).

| Tab | Inline-editable scalars (new) | Stays combobox/remap (unchanged) |
|---|---|---|
| soldiers | full_name, rank, gender, is_officer, enlistment_date, phone, email, is_career, next_rank_date, bahad1_graduate, has_military_driving_license, military_driving_license_expiry, mandatory_end_date, discharge_date, last_mitvahim_date, last_alal_date, left_at | hierarchy_node |
| duty_shifts | start_date, end_date, start_time, end_time, required_count, notes | duty_type, node_quotas |
| assignments | start_date, end_date, start_time, end_time, is_reserve, notes | duty_type_name, duty_location_name (now via combobox — see §3) |
| duty_locations | name, base, active | — (no relational fields) |
| hierarchy | name, level | parent, commander, duty_manager_refs |

Booleans render as checkboxes, dates as `type="date"` inputs, everything else as text
inputs — matching the existing duty_types cell conventions exactly.

## 3. Assignments: combobox remap for unresolved names

Today `_resolve_assignments` takes no name-mapping args and assignments rows have no
fix-up UI. Bring it in line with `_resolve_duty_shifts`: accept `dt_by_name`, `dt_by_row`
and apply them the same way `_resolve_duty_shifts` does before matching
`duty_type_name` against existing duty types.

Frontend: the assignments tab's `duty_type_name`/`duty_location_name` cells get the same
red-name + `Combobox` + `PendingPickBanner` treatment already used in the soldiers
(hierarchy_node) and duty_shifts (duty_type) tabs, reusing `handlePick`/`applyMapping`
unmodified (they're already generic over `"duty_type"` / `"hierarchy_node"` kinds) with
row keys namespaced `assignments:<row>`.

Note: `duty_location_name` has no existing "kind" in `handlePick`/`_name_mappings`
(today only `duty_type` and `hierarchy_node` are mapped kinds; duty_locations have never
needed remapping since duty_shifts/assignments treat an unresolved location as a hard
error, and duty_locations themselves are always creatable inline via the `duty_locations`
tab rather than remapped). This spec does **not** add a third mapping kind for duty
locations — an unresolved `duty_location_name` on an assignment row remains a hard error,
consistent with how duty_shifts already treats it. Only `duty_type_name` gets the new
combobox on the assignments tab.

## 4. Row detail / inspect modal

New `ImportRowDetailModal` component, generic over a `fields: { key: string; label:
string; value: unknown; editable?: { type: "text" | "number" | "date" | "checkbox" |
"textarea"; onChange: (v: unknown) => void } }[]` prop. Every tab gets a new "פרטים"
button per row (all 8 tabs, including the 3 that already have partial per-row modals —
`dutyTypeFieldsRow`/`exemptionTypeFieldsRow`/`shiftTemplateFieldsRow` keep their existing
multi-select modals unchanged; the new detail modal is additive, opened from a separate
button) that opens this modal populated with every field on that row, including ones
not shown as table columns (`existing_id`, full `errors`/`warnings` list, etc.).
Read-only fields render as plain text; editable scalar fields render the same input
type as their inline-cell counterpart and call the same `setFieldOverride`, so the modal
and the inline cell are two views over identical state (editing in one updates the
other on next render, same resync-by-`row.row` pattern already used for
`dutyTypeFieldsRow`/etc.).

## 5. Soldier profile field parity

Four layers, all additive (no renames, no removals of existing fields):

1. **`backend/app/services/import_parsers/schema.py`** — `ImportSoldierRow` gains:
   `is_career: bool | None`, `next_rank_date: str | None`, `bahad1_graduate: bool | None`,
   `has_military_driving_license: bool | None`,
   `military_driving_license_expiry: str | None`, `mandatory_end_date: str | None`,
   `discharge_date: str | None`, `last_mitvahim_date: str | None`,
   `last_alal_date: str | None`, `left_at: str | None`.
2. **`backend/app/services/import_parsers/v1_standard.py`** — the soldiers sheet reader
   gains one `r.get("<field_name>")` line per new field (same snake_case-matches-column-
   header convention as every existing field), using the existing `_parse_bool`/
   `_parse_date` helpers for the typed ones.
3. **`_resolve_soldiers`** — copies each new field straight through into the output row
   dict (no validation beyond the existing `_parse_bool`/`_parse_date` at parse time —
   consistent with how e.g. `phone`/`email` are handled today, no format validation).
4. **`confirm_session`**'s soldiers block — both the `new` (constructor kwargs) and
   `update` (`if row.get(field) is not None: s.field = ...`) branches gain one line per
   new field, following the exact existing pattern for `rank`/`gender`/`is_officer`.

Frontend: `SoldierRow` TS interface gains the 10 new fields; the soldiers tab table
gains inline-edit cells for all of them (dates as `type="date"`, booleans as checkboxes,
`is_career`/`bahad1_graduate`/`has_military_driving_license` as checkboxes) — likely
via the new row-detail modal (§4) rather than 10 more table columns, to keep the table
scannable; the table itself keeps showing only name/personal_number/hierarchy/status as
today, with the modal being the primary place all profile fields are visible and edited.

**Excluded:** `profile_picture_url` (needs file upload, not a spreadsheet column),
`password_hash`/`role`/`email_verified`/`must_change_password`/`token_version`/
`failed_login_count`/`locked_until`/`created_at`/`updated_at` (system/security/derived,
never user-editable via import).

## Testing

- Backend: extend `test_import_sessions_service.py` with cases per resolver — override
  applied, override absent falls back to parsed value, override re-validated (e.g. bad
  date string in an override still produces an error same as a bad parsed value would).
- Backend: assignments combobox remap — unresolved duty_type_name resolved via
  `_name_mappings.duty_type.by_row`/`by_name`, mirrors existing duty_shifts test cases.
- Backend: soldier new-field round-trip — parse → resolve → confirm → assert all 10
  new fields land on the created/updated `Soldier` row.
- Frontend: no new test framework needed; existing patterns for inline-edit cells and
  combobox remap are copied, not reinvented.
