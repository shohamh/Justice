# Searchable combobox for select boxes — design

## Problem

Native `<select>` elements are hard to use for long lists (soldiers, duty
types, locations, hierarchy nodes, exemption types, ranks) — no search, and
on some browsers the native picker is clunky. The codebase already has three
separate ad-hoc implementations of a searchable dropdown:

- `ShiftTemplateFormModal.tsx` — private `Combobox` sub-component, Fuse.js
  fuzzy search, portal-rendered dropdown.
- `RegisterPage.tsx` — inline Fuse.js search list for the requested-node
  picker (not a `<select>` replacement, but same underlying need).
- `UnitCalendarPage.tsx` — `NodeSearchDropdown`, substring filter, manual
  open/close + click-outside handling, tree-depth indentation with `└`
  markers.

This duplicates ~60-100 lines of logic three times with diverging behavior
(fuzzy vs. substring search, no indentation support in the first one, no
disabled-item support in any of them).

## Goal

One shared `Combobox` component, used everywhere a `<select>` is backed by a
dynamic or long option list. Fixed small enums (2-6 static options) keep
native `<select>` — search adds nothing there, and native select has fuller
keyboard/accessibility support for free.

## Component: `frontend/src/components/Combobox.tsx`

Extracted and generalized from `ShiftTemplateFormModal`'s version:

```ts
interface ComboboxItem {
  id: string;
  name: string;
  disabled?: boolean;
}

interface ComboboxProps {
  label?: string;
  items: ComboboxItem[];
  value: string;
  onChange: (id: string) => void;
  getDepth?: (item: ComboboxItem) => number; // tree indentation, └ marker
  placeholder?: string;                      // empty-option text, e.g. "—"
  allowEmpty?: boolean;                      // shows placeholder as a selectable "clear" row
}
```

Behavior carried over unchanged from the existing implementation:
- Fuse.js fuzzy search (`keys: ["name"]`, `threshold: 0.4`) over `items`,
  full list shown when query is empty.
- Dropdown rendered via `createPortal` into `document.body`, positioned with
  `getBoundingClientRect`, so it escapes `overflow-y-auto` modal containers.
- Input shows the selected item's name; clicking a result sets value + closes;
  blur closes after a short delay (so `onPointerDown` selection isn't lost).

New behavior added to absorb the other two implementations:
- `getDepth`: when provided, each row is indented (`paddingRight` step) and
  prefixed with a `└` marker for depth > 0 — replaces
  `UnitCalendarPage.NodeSearchDropdown`'s indentation and the
  `sortNodesByTree` + `indentedNodeLabel` pattern used for hierarchy-node
  selects elsewhere.
- `disabled` items render non-interactively (grayed, no `onPointerDown`) —
  needed by `ReserveDismissalModal`'s called-up assignments.
- `placeholder` / `allowEmpty`: renders a selectable "—" / "כל הסוגים" style
  row that calls `onChange("")` — needed by selects that allow clearing or
  have an "all" option.

`ShiftTemplateFormModal.tsx` drops its private `Combobox` and imports the
shared one (no behavior change there).

## Files converted to `Combobox`

| File | Select(s) replaced |
|---|---|
| `ShiftFormModal.tsx` | duty type, location |
| `ShiftTemplateFormModal.tsx` | (already Combobox — import shared component) |
| `DutyManagementPage.tsx` | soldier |
| `AlgorithmProposalTable.tsx` | batch filter |
| `AlgorithmRunForm.tsx` | duty type filter |
| `ProfilePage.tsx` | rank, hierarchy node |
| `MyRequestsPage.tsx` | exemption type |
| `TeamHierarchyPage.tsx` | onboarding node |
| `RegisterPage.tsx` | rank |
| `SwapsPage.tsx` | duty type, node |
| `DismissalModal.tsx` | assignment |
| `EntriesExitsPanel.tsx` | exemption type, node |
| `ExemptionsPanel.tsx` | exemption type |
| `SoldierEditModal.tsx` | hierarchy node |
| `ReserveDismissalModal.tsx` | assignment (disabled rows for called-up) |
| `UnifiedSoldierModal.tsx` | hierarchy node, rank |
| `UnitCalendarPage.tsx` | node selector — `NodeSearchDropdown` removed, replaced with shared `Combobox` using `getDepth` |

Each conversion preserves existing `value`/`onChange` wiring, required-field
validation, and any "add new" affordances (e.g. `ShiftFormModal`'s inline
add-location form stays as-is, just swapping the `<select>` for `Combobox`).

## Selects left as native `<select>`

Fixed 2-6 option enums where search has no value:

- `AddChildNodeDialog.tsx`, `AddRootNodeDialog.tsx` — hierarchy level picker
- `ImportPage.tsx` — row action (update/new/skip)
- Gender selects (`ProfilePage.tsx`, `RegisterPage.tsx`, `UnifiedSoldierModal.tsx`)
- `ProfilePage.tsx` — depth-levels filter (-1, 1-5)
- `SystemSettingsPage.tsx` — 2-option settings dropdowns
- `DutyTypeFormModal.tsx` — internal/external toggle

## Testing

- Existing frontend unit tests (`npm test`) must keep passing; update any
  test that queries a converted field via `getByRole("combobox")` /
  `<select>` semantics to instead interact with the new text-input-based
  control.
- Manual smoke check (via preview tools) on `ShiftFormModal` and one
  hierarchy-node conversion (e.g. `SoldierEditModal`) to confirm search,
  selection, and portal positioning work inside a scrolling modal.

## Out of scope

- No change to native selects with fixed small option sets (see above).
- No change to `RegisterPage.tsx`'s unauthenticated node-picker UI beyond
  the rank select — it's a different UX (always-visible list, no
  open/closed toggle) for a pre-login flow and isn't a `<select>` replacement.
