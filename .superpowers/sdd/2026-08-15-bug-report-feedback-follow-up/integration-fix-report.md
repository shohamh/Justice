# Integration fix report

## Regression

`RangeFormModal` initialized a new event's controlled `range_type` to `laser`, which changed the pre-existing create-form payload contract from `live` to `laser` after Task 3 replaced the native selector with the shared `Combobox`.

## Fix

Preserved `live` as the default both in the initial form state and when opening a new form. Existing event values still take precedence. The shared `Combobox`, readable Hebrew labels, exact test IDs, and selector-only location behavior were unchanged. Added a focused component regression asserting the submitted default payload.

## Verification

- Focused: `RangeFormModal.test.tsx`, `Combobox.test.tsx`, and `RangesPage.test.tsx` — 59 tests passed.
- Integrated frontend list from the plan — 9 files, 90 tests passed.
- `npm run typecheck` — passed.
- Non-failing existing warnings remain: React Router future-flag, react-i18next setup, and `act(...)` warnings in `ShiftDetailPanel` tests.
