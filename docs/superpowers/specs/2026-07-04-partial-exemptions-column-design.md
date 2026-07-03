# Partial exemptions column + exemption-type view/edit modal

## Goal

On the potential page, show how many soldiers in each subunit are exempt from
one or more (but not all) of their eligible duty types. These soldiers still
count toward their subunit's potential — this column exists purely for
visibility. Clicking an exemption name shown in the soldier detail table
opens a modal describing that exemption type, with an edit option for users
who manage duty config.

## Backend changes

`backend/app/services/potential.py`:

- `SoldierPotentialDetail` gains `partial_exemption_names: list[str] = field(default_factory=list)`.
  Populated only when `counted=True` and the soldier has at least one active
  (non-commander) exemption whose mapped duty types intersect `base_eligible`
  but do not cover all of it (i.e. `remaining` non-empty and `excluded &
  base_eligible` non-empty).
- `PotentialResult` gains `partial_exemption_count: int` — count of soldiers
  in the subtree with non-empty `partial_exemption_names`.
- `compute_potential` computes both while building `details`, reusing the
  existing `active_exemptions` / `etid_to_dtids` / `base_eligible` /
  `excluded` values already computed per soldier — no new queries.

`backend/app/routes/potential.py`:

- Extend the response schema(s) for `SoldierPotentialDetail`/`PotentialResult`
  equivalents to include the two new fields.

## Frontend changes

`frontend/src/api/potential.ts`:

- Add `partial_exemption_names: string[]` to `SoldierPotentialDetail`.
- Add `partial_exemption_count: number` to `PotentialResult`.

`frontend/src/pages/planning/PotentialPage.tsx`:

- New column `partial_exemptions`, header "פטורים חלקיים", placed
  immediately after `eligible`. Uses `headerTooltip` (existing "?" → modal
  mechanism in `DataTable`) explaining these soldiers still count toward
  their subunit's potential.
- `wholeOrgResult` synthetic aggregate sums `partial_exemption_count` across
  top-level roots, same pattern as other summed fields.
- `soldierCols` "reason" column: when `s.counted && s.partial_exemption_names.length > 0`,
  render each name as a clickable chip (button) instead of "—". Clicking a
  chip opens `ExemptionTypeViewModal` for that exemption type.
- On mount, `PotentialPage` loads `listExemptionTypes()` and
  `getAllExemptionDutyTypeMaps()` once (small admin-config-sized lists) to
  resolve a clicked exemption name to its full `ExemptionType` record + its
  duty-type mapping, passed into the modal.

New `frontend/src/components/ExemptionTypeViewModal.tsx`:

- Props: `exemptionType: ExemptionType`, `mappedDutyTypeIds: string[]`,
  `dutyTypes: DutyType[]`, `onClose`, `onSaved` (refetch callback).
- View mode: name as title, badges for global/medical/commander (same style
  as `DutyConfigPage`'s exemption-type list), and either "פוטר מכל סוגי
  התורנות" (if global) or the list of mapped duty type names.
- Pencil icon shown only if `user.role === "admin" || user.is_duty_manager`
  (mirrors backend's `require_config_manager` gate — admin or any duty-manager
  scope). Clicking it switches to an inline edit form: name input, global/
  medical/commander checkboxes, duty-type mapping checkboxes — reusing
  `updateExemptionType` and `setExemptionDutyTypes` from `api/dutyConfig.ts`.
  On save, calls `onSaved` and returns to view mode.

## i18n

Add to `frontend/src/i18n/he.json` under `potential`:
- `partial_exemptions`: "פטורים חלקיים"
- `partial_exemptions_tooltip`: explains these soldiers still count toward
  the subunit's potential despite having an active partial exemption.

Add new keys for the exemption-type modal (reusing existing `duty_config.*`
strings like `global`, `medical`, `exempts_from` where possible).

## Tests

- Extend `backend/app/services/tests/test_potential.py` with cases for a
  soldier who has one exemption covering one of two eligible duty types
  (partial — counted, `partial_exemption_names` populated) vs. a soldier
  exempt from all eligible duty types (existing fully-exempt path,
  unaffected).
- Extend `backend/app/services/tests/test_potential_routes.py` to assert the
  new fields serialize correctly.
- No frontend test file exists for `PotentialPage` today; not adding one,
  consistent with current coverage.

## Out of scope

- No change to how potential is *calculated* (`final_potential`,
  `raw_eligible_count`) — partial exemptions never reduce potential, only
  full exemptions (existing `reason == "exempted"` path) do.
- No new backend endpoint — reuses existing `listExemptionTypes` /
  `getAllExemptionDutyTypeMaps` / `updateExemptionType` /
  `setExemptionDutyTypes`.
