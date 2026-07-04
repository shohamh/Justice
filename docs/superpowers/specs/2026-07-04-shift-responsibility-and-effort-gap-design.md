# Shift Unit-Responsibility Actions + Effort-vs-Potential Gap Columns

Date: 2026-07-04
Status: Approved for planning

## Context

Two related but independent features, both building on existing infrastructure:

- The Shift Schedule page (`ShiftsPage.tsx`) already supports multi-selecting
  shifts and has a `BulkActionBar` (clear/cancel/delete/auto-assign soldiers).
  Shifts already have `eligible_node_ids` (which hierarchy nodes may be
  assigned) and a `DutyShiftNodeQuota` table + `quota-split-preview` /
  `setShiftQuotas` API for splitting a shift's `required_count` across
  subunits — but there's no UI for it yet, and no concept of "who is
  responsible" for a shift beyond eligibility.
- The Transparency page shows per-subunit `avg_effort` (client-side
  aggregation); the Potential page shows per-node `final_potential`. Neither
  page currently compares the two.

## Feature 1: Bulk unit-responsibility actions on the Shift Schedule page

### Concept

A shift's "responsible units" are simply its `eligible_node_ids` — no new DB
field. A shift can have one or several responsible units at once.

Three new buttons appear in the shift schedule's bulk-action area, operating
on the currently multi-selected shifts. All three show a preview modal before
applying (consistent with each other, distinct from the plain-toast pattern
used by the pre-existing clear/cancel/delete actions).

### 1. Set responsible unit(s)

- Modal with a **multi-select** hierarchy tree picker (reuses the existing
  tree-picker UI pattern from `ShiftFormModal.tsx`).
- Applying **replaces** `eligible_node_ids` with the chosen set, for every
  selected shift.
- Preview: "N shifts will be set to eligible_node_ids = [X, Y, ...]".

### 2. Split in unit (two-level quota split)

For each selected shift, using its current `eligible_node_ids` as the set of
responsible units:

1. **Step A** — split the shift's `required_count` across the responsible
   units themselves, weighted by each unit's `final_potential`, using the
   largest-remainder method (counts sum exactly to `required_count`).
2. **Step B** — split each responsible unit's share further across *its own*
   direct children, again weighted by `final_potential` (largest-remainder).

Resulting quotas (`DutyShiftNodeQuota` rows) are set on the grandchildren —
the leaf subunits that actually do the work.

**Backend changes required** (`backend/app/services/shift_quotas.py`):
- `compute_potential_split` currently weights by raw active-soldier headcount
  per child of a single parent. Change its weighting to use `final_potential`
  (from `app/services/potential.py`) instead of headcount, so the name
  matches the behavior.
- Add a new helper for Step A: split a `required_count` across an arbitrary
  **list** of nodes (not necessarily siblings under one parent), weighted by
  `final_potential`, same largest-remainder method.
- Compose both helpers for the two-level split; expose via a
  route (reusing/extending `quota-split-preview`) that accepts a shift ID and
  returns the full two-level breakdown.

Preview modal shows the two-level breakdown per shift → confirm calls
`setShiftQuotas()` per shift with the computed grandchild-level quotas.

### 3. Auto assign unit responsibility

- Candidate units for a given shift = union of the direct children of that
  shift's current `eligible_node_ids`.
- Picks exactly **one** best unit per shift (auto-assign never produces
  multiple responsible units — that remains a manual capability via button 1).
- Scoring: `final_potential(candidate) − (past_effort(candidate) +
  running_batch_load(candidate))`, or equivalent ordering. Shifts in the
  batch are processed in a fixed order (e.g. by date); each time a unit is
  chosen, its assumed load (e.g. the shift's `required_count`) is added to
  `running_batch_load` for that unit, so later shifts in the same batch favor
  units that haven't been picked yet (fair-share behavior within the batch).
- `past_effort` per candidate comes from the same effort data used in
  Feature 2 (`total_effort` per node, see below).
- Preview modal: "shift → assigned unit" per selected shift → confirm
  **replaces** `eligible_node_ids` with `[chosen_unit]` (single-element) for
  each shift.

### Layout

The existing general "שיבוץ אוטומטי" button (assigns soldiers to shifts,
already in `BulkActionBar`) becomes the large, prominent button at the top of
the bulk-action bar. The three new buttons form a secondary row below it.

## Feature 2: Effort-vs-Potential comparison columns

### New shared backend endpoint

Returns, per hierarchy node (respecting whatever date-range/quarter filter
the Transparency page already applies):

- `final_potential` — existing calculation, unchanged.
- `total_effort` — **new**: sum of `effort_score` across all soldiers in the
  node's subtree (a capacity-like total, comparable to `final_potential`,
  distinct from the existing `avg_effort` which stays as a per-soldier
  average for its existing purpose).
- `sibling_potential_share` / `sibling_effort_share` — node's value ÷ sum
  across its direct siblings (children of the same parent).
- `sibling_gap` — `sibling_effort_share ÷ sibling_potential_share` (ratio;
  1.0 = proportionate to peers).
- `global_potential_share` / `global_effort_share` — node's value ÷
  organization-wide total.
- `global_gap` — same ratio, computed globally instead of among siblings.

This centralizes the calculation in one tested backend service instead of
duplicating it client-side in two pages.

### Page changes

Both Transparency and Potential pages call this endpoint and add:

- A **sibling gap** column — color-coded (e.g. red if ratio > ~1.3,
  overloaded relative to peers; blue if < ~0.7, underloaded), sortable.
- A **global gap** column — same treatment, computed globally.
- Existing `avg_effort` and `final_potential` columns are unchanged
  (additive, not replaced).

No separate "biggest differences" ranking column is needed: sorting by
either gap column surfaces the largest deviations at the top/bottom.

## Out of scope

- No new DB field for "responsible unit" — it's `eligible_node_ids` reused.
- No changes to how `effort_score` itself is computed per soldier
  (`app/services/effort_score.py`) — only new aggregations on top of it.
- No UI for editing the exact color thresholds (1.3 / 0.7) — hardcoded
  constants for now.
