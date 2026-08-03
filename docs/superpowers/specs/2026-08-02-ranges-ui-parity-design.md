# Ranges UI Parity Design

## Goal

Make the ranges planning screen feel like the existing shifts management
screen while preserving range-specific behavior: range metadata, draft
assignment confirmation, attendance/no-show, excusal, auto-assignment, and
cancel/delete lifecycle actions.

## Scope

### Planning screen

`RangesPage` and `RangePlanningTable` will use the same visual conventions as
`ShiftsManagementPage` and `PlanningTable`:

- consistent page header and primary action button;
- shared filter field sizing, borders, spacing, labels, and empty/loading/error
  states;
- consistent search and sort controls;
- table row actions with the same button hierarchy and danger treatment used by
  shift management;
- explicit action buttons remain separate from row selection.

The existing range filters (date range, type, status, fill state) remain, but
their presentation will use the shared planning controls rather than bespoke
unstyled inputs.

### Range detail modal

The existing `EventDetailModal` remains the modal shell. Range details will be
arranged like shift details:

- title and subtitle in the standard modal header;
- metadata in the standard definition-list treatment;
- consistent modal action buttons for edit and cancel;
- operational instructions, contact details, and notes in a styled content
  panel;
- primary and reserve rosters using shared assignment/roster components;
- attendance, excusal, draft, and auto-assignment controls retain their current
  authorization and lifecycle rules.

### Range edit modal

`RangeFormModal` will be restyled and reorganized to match `ShiftFormModal`:

- standard modal width, header, and footer;
- consistent two-column responsive field grid;
- shared input/select/button classes and disabled/pending states;
- clear sections for schedule/location, operational instructions/contact, and
  roster capacity;
- existing validation remains: time ordering, non-negative capacities, and
  explicit confirmation when changing date/type with assignments.

### Range assignment edit modal

Add `RangeEditAssignmentsModal`, modeled structurally after
`ShiftEditAssignmentsModal`, with range-specific API calls:

- current primary and reserve assignments, including draft indicators;
- remove controls with per-row pending state;
- soldier search/picker for primary and reserve additions;
- capacity-aware selection and clear full/shortfall messaging;
- auto-assignment and draft confirmation actions;
- shared assignment-row, section, table, and modal primitives where their
  semantics match.

The range detail modal will open this assignment editor through an explicit
“edit assignments” action. Existing inline controls remain available only when
they provide a distinct workflow, such as attendance or excusal.

## Data flow and behavior

No backend contract changes are required for the visual parity work. Existing
range API functions will be reused. Mutations invalidate the range list and
selected-event queries so the planning table, detail modal, and assignment
editor stay synchronized.

Authorization remains enforced by the existing `canPlan`/backend rules. A
commander may continue to view permitted range details without receiving
planning mutations. Cancel/delete actions require the current planned-state
and capacity safeguards.

## Component boundaries

- `RangesPage`: query state, filters, selection, mutation orchestration.
- `RangePlanningTable`: range-specific columns only; shared planning table
  presentation.
- `RangeFormModal`: range form state and range validation only.
- `RangeEditAssignmentsModal`: assignment editor state and range API mapping.
- shared planning components: modal shell, planning table, roster/assignment
  row, and common action styling where already supported.

Avoid copying the full shift assignment domain model into ranges. Reuse visual
and interaction primitives, not incompatible API or authorization semantics.

## Testing

Add or update frontend tests for:

- filter/table styling hooks and row-action rendering;
- detail modal metadata and action layout;
- form sections, validation, save/cancel states;
- assignment editor add/remove, reserve selection, draft controls, and pending
  states;
- commander read-only behavior.

Run the focused ranges tests, then frontend typecheck/lint and the complete
frontend suite. Run backend tests only if shared API behavior or backend code is
changed.

## Acceptance criteria

1. A user familiar with shift management recognizes the ranges page controls,
   table, buttons, and modal structure without learning a second visual system.
2. All existing range workflows continue to work, including create/edit,
   cancel/delete, auto-assign, draft confirmation, attendance/no-show, and
   excusal.
3. Assignment editing is available in a shift-like modal with primary/reserve
   separation and clear pending/error states.
4. Authorization and backend behavior are unchanged unless a test exposes a
   necessary compatibility fix.
5. Focused and full frontend verification pass with no new warnings enforced by
   lint.
