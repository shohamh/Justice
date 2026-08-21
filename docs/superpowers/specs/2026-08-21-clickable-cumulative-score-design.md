# Clickable cumulative score → filtered duty history

## Problem

On the transparency page, each soldier's row shows a "ניקוד מצטבר" (cumulative
score) number. There's no way to verify that number against the underlying
events without manually opening the soldier's profile, switching to the duty
history tab, and figuring out which of the ten event-type filters are
score-relevant.

## Goal

Clicking the cumulative-score number opens that soldier's duty history,
pre-filtered to just the event types that carry a `score_total`
(`assignment`, `cancellation`, `call_up`, `dismissal` — per
`backend/app/services/duty_history.py`), so the score can be verified by eye.

## Changes

### 1. Multiselect event-type filter in `DutyHistoryPanel`

Replace the current single-select filter chips (`filter: FilterType`) with a
multiselect, using the existing generic `CheckboxListDropdown` component
(already used for the duty-type filter on the unit calendar page).

- State becomes `types: string[] | null` (`null` means "all", matching the
  `dutyTypeFilter` pattern in `UnitCalendar.tsx`).
- Items = the same 9 entries currently in `FILTER_KEYS` minus `"all"`
  (`assignment`, `algorithm_draft`, `cancellation`, `call_up`, `dismissal`,
  `exemption`, `exemption_request`, `personal_constraint`, `range`), same
  Hebrew labels.
- Matching logic is preserved as-is, generalized from "equals the selected
  filter" to "included in the selected types":
  - `range` continues to match both `range_assignment` and `range_removed`
    event types.
  - `algorithm_draft` continues to match on `status === "algorithm_draft"`
    rather than `event_type`.
- The separate status filter row (published/draft/reserve/cancelled) is
  unchanged.
- Effective selection for filtering purposes is
  `types ?? allItemIds` (mirroring `UnitCalendar`'s
  `effectiveDutyTypeFilter`), so the unset default behaves as "show
  everything."

### 2. Opening the modal on a specific tab with a preset filter

- `UnifiedSoldierModal` gains an optional `initialTab?: TabKey` prop
  (default `"details"`, same pattern as the existing `initialEditing` prop),
  used only to seed the `tab` state on mount.
- `DutyHistoryPanel` gains an optional `initialTypes?: string[]` prop, used
  only to seed the new `types` state on mount.
- `SoldierModalContext`'s `openSoldierModal` signature grows two new
  optional trailing parameters:
  `openSoldierModal(soldierId, onRefresh?, initialTab?, initialHistoryTypes?)`.
  Both are threaded down to `UnifiedSoldierModal`. Existing call sites
  (`SoldierLink`, etc.) are unaffected since the new parameters are optional.

### 3. The clickable score cell

In `TransparencyPage.tsx`, the `cumulative` column's `cell` renderer changes
from plain text to a button, styled identically to the existing
`effort_score` column's button (indigo text, underline on hover, a
`title` tooltip: "לחץ לצפייה באירועים שמשפיעים על הניקוד").

`onClick` calls:

```ts
openSoldierModal(r.soldier_id, undefined, "duty_history", SCORE_AFFECTING_TYPES)
```

where `SCORE_AFFECTING_TYPES = ["assignment", "cancellation", "call_up", "dismissal"]`
is a module-level constant in `TransparencyPage.tsx`.

## Testing

- `DutyHistoryPanel.test.tsx`: update the one test that currently clicks
  `getByTestId("history-filter-range")` to instead interact with the
  checkbox dropdown (open it, check/uncheck the "מטווחים" item). Add a test
  that `initialTypes` seeds the filter correctly on mount.
- `UnifiedSoldierModal.test.tsx`: add a test that `initialTab` opens the
  modal on the given tab.
- `TransparencyPage.test.tsx`: add a test that clicking the cumulative-score
  button calls through to open the soldier modal with the expected
  arguments (event types + tab).

## Out of scope

- No change to the status filter row.
- No change to what counts toward `cumulative_score` on the backend — this
  is purely a frontend navigation/filtering affordance.
- No change to `SoldierLink` or other existing `openSoldierModal` call
  sites.
