# מטווחים (Ranges) — Phase 2: automatic assignment design spec

## Goal

Let a DM auto-fill a planned `RangeEvent`'s remaining primary/reserve slots
by a strict priority ordering, instead of picking soldiers manually one by
one (Phase 1). Builds directly on the
[Phase 1 spec](2026-07-31-mitvachim-phase1-design.md) — same tables, same
permission model, adds one new action and one new field.

## Current state (relevant existing patterns)

- Phase 1 already defines `RangeEvent`, `RangeAssignment`,
  `SoldierRangeQualification`, `RangeType` (laser < live < alal), the
  exemption rule, and `Action.RANGE_MANAGE`.
- The existing duty auto-assigner (`backend/app/algorithm/`, entry point
  `run_algorithm_job` in `backend/app/services/algorithm_bridge.py:1062`)
  is a CP-SAT solver whose objective is multi-tier *fairness dispersion*
  (`build_fairness_objective`, `algorithm/model.py:77`) — built for
  balancing load across an entire soldier pool over a schedule with
  overlapping rest/quota constraints. It writes `DutyAssignment` rows with
  `status="algorithm_draft"` (`algorithm_bridge.py:661`) which a DM then
  accepts/rejects individually via `POST
  /algorithm/jobs/{id}/proposals/{id}/accept|reject`
  (`routes/algorithm.py:892-1091`) before soldiers see them.
- No deterministic (non-solver) assignment path exists anywhere in the
  codebase today — this feature introduces the first one.
- `PersonalConstraint` (`backend/app/db/models.py:638`) — `status ==
  "approved"` rows with `start_date`/`end_date` are the "אילוץ אישי"
  soldiers can be excused from scheduling on; `get_approved_constraint_dates()`
  (`backend/app/services/constraints.py:413`) is the existing helper that
  loads them per soldier, already used to feed the duty algorithm.
- `DutyType.requires_weapon` and the exemption rule
  (`ExemptionType.forbids_weapons`/`is_global`) are already defined in
  Phase 1's data model.

## Rejected approaches

- **Routing range auto-assignment through the existing CP-SAT solver**:
  rejected — confirmed by design discussion. The range criteria are a
  strict lexicographic ordering with no fairness trade-off and no shared
  combinatorial constraints (no rest-hour windows, no per-day multi-duty
  overlap accounting, no rolling quotas) — exactly what a plain
  `sorted()` + fill-to-quota loop solves. Reusing the solver would mean
  encoding a rank-ordering as objective weights, which is more code, more
  fragile (weight tuning to *force* strict lexicographic behavior instead
  of a genuine trade-off), and harder to explain to a DM than "here's the
  sorted list, here's why."
- **Immediately creating live `RangeAssignment` rows on auto-assign (no
  review step)**: rejected — the DM wants to see and adjust the proposed
  list before soldiers are notified. A draft/confirm step was chosen
  instead.
- **A full `AlgorithmJob`-style table for range auto-assign runs**:
  rejected as overkill — since there's no solver run to track (no
  diagnostics, no timeout, no batch status), a boolean flag directly on
  `RangeAssignment` is sufficient to represent "still a draft."

## Design

**Trigger**: a new button on a `planned` `RangeEvent`'s roster —
"שבץ אוטומטית" — fills *only the currently-empty* primary/reserve slots
(`required_count`/`reserve_count` minus existing `RangeAssignment` rows);
it does not touch already-assigned soldiers (manual or previously
confirmed) whether draft or confirmed.

**Candidate pool** (soldiers considered at all): every soldier whose
`hierarchy_node_id` path is inside `event.hierarchy_node_id`'s subtree,
**minus**:
- Already assigned to this event (any status).
- Range-exempt per the Phase 1 rule (global/`forbids_weapons`
  exemption covering `event.date`, or structurally ineligible for any
  `requires_weapon=true` duty type).
- Has an `approved` `PersonalConstraint` covering `event.date`
  (via `get_approved_constraint_dates()`).
- Already has a `DutyAssignment` (any duty type) whose `start_date..end_date`
  covers `event.date` — i.e. already on duty that day.
- Already has a `RangeAssignment` (any status, any event) whose
  `RangeEvent.date == event.date` — i.e. already booked at another range
  that day.

**Priority ordering** (strict lexicographic, computed once per
auto-assign call over the filtered candidate pool):
1. **Tier A** — no valid `SoldierRangeQualification` at `event.range_type`
   or higher (per the laser < live < alal hierarchy) **and** currently
   holds a future `DutyAssignment` (`status="published"`,
   `start_date >= today`) for a `DutyType` with `requires_weapon=true`.
   Ordered by that duty's `start_date` ascending (soonest first). If a
   soldier has multiple such duties, use the earliest.
2. **Tier B** — no valid qualification at `event.range_type` or higher,
   not in Tier A. Ordered by `soldier_id` (stable, arbitrary — no
   criterion given for this tier's internal order).
3. **Tier C** — has a valid qualification at `event.range_type` or higher.
   Ordered by `valid_until` ascending (soonest-expiring first, across
   whichever qualifying `range_type` row is the most permissive one still
   valid).

**Fill**: take the sorted list; the first `remaining_primary` candidates
become primary (`is_reserve=False`), the next `remaining_reserve` become
reserve (`is_reserve=True`). If the pool is smaller than the total needed,
fill as many as available and report the shortfall to the DM (no error —
partial fill is expected and normal).

**Draft/review step**: every row created by auto-assign gets
`RangeAssignment.is_draft = True` (new column, default `False`). Draft
rows:
- Are visible to the DM in the planning page's roster, visually marked
  ("טיוטה" badge).
- Do **not** trigger the soldier-facing assignment notification.
- Do **not** appear on the soldier's own homepage/calendar as confirmed
  (visible only in the DM's planning view) — from the soldier's
  perspective, nothing has happened yet.
- Can be removed individually by the DM (same `remove_range_assignment`
  used in Phase 1 for manual rows — draft or not, it's still just a
  `RangeAssignment` row).
- Can be confirmed individually (`is_draft → False`, fires the assignment
  notification, becomes indistinguishable from a manually-created row)
  or in bulk ("confirm all drafts for this event").

**No new algorithm-provenance tracking** (no equivalent of
`algorithm_job_id`/`AssignmentExplanation`) — per the rejected-approaches
note, there's no solver run to explain; the sort criteria above *are* the
explanation, and the DM can already see each candidate's tier by
inspecting their qualification/duty state directly.

## Data model changes

**`RangeAssignment`** (extends Phase 1 table) — add:
```python
is_draft: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
```

No other schema changes — everything else (candidate filtering,
qualification lookups, duty-type weapon flag) reuses Phase 1 tables plus
the existing `PersonalConstraint`/`DutyAssignment` tables.

## Backend

**New action**: `Action.RANGE_MANAGE` (already defined in Phase 1)
covers auto-assign and draft confirm/reject too — same scope as manual
assignment, no new permission tier needed.

**New service `backend/app/services/range_auto_assign.py`**:
- `propose_range_assignments(event) -> list[RangeAssignment]`:
  builds the candidate pool (filters above), computes the three-tier sort
  key per candidate, fills remaining slots, inserts `RangeAssignment`
  rows with `is_draft=True`, returns them (plus a `shortfall` count if
  the pool ran out).
- `confirm_draft_assignment(assignment)` / `confirm_all_drafts(event)`:
  flips `is_draft → False`, fires the assignment notification (reusing
  the Phase 1 notification call, which was previously invoked
  unconditionally at creation — now conditional on `is_draft=False`,
  either at creation time for manual rows or here for confirmed drafts).
- `reject_draft_assignment(assignment)`: deletes the row (equivalent to
  `remove_range_assignment`, just named for the draft-review context).

**New routes** (`backend/app/routes/ranges.py`, extends Phase 1):
- `POST /ranges/{id}/auto-assign` (`RANGE_MANAGE`) — runs
  `propose_range_assignments`, returns the created drafts + shortfall.
- `POST /ranges/{id}/assignments/{id}/confirm` (`RANGE_MANAGE`).
- `POST /ranges/{id}/assignments/confirm-all` (`RANGE_MANAGE`).
- (Draft rejection reuses the existing Phase 1
  `DELETE /ranges/{id}/assignments/{id}`.)

**Phase 1 creation-notification adjustment**: `add_range_assignment`
(manual path) still notifies immediately, since manual rows are never
drafts (`is_draft` defaults `False` for that path) — no behavior change
for Phase 1 users, this is purely additive.

## Frontend

- **"שבץ אוטומטית" button** on the planning page's roster panel for a
  `planned` event, enabled only when slots remain open. Calls the
  auto-assign endpoint, shows the returned drafts inline with a "טיוטה"
  badge, and a shortfall banner if fewer candidates were found than
  slots needed.
- **Per-row confirm/reject controls** on draft rows, plus a "אשר הכל"
  bulk action.
- **Tier visibility (optional nice-to-have, not required for v1)**: since
  there's no formal "explanation" record, the roster row for a draft can
  simply show the soldier's current qualification status
  (valid-until per level) so the DM can sanity-check the ordering by eye
  without needing a dedicated explanation UI.

## Testing

Backend (pytest):
- Candidate filtering excludes: already-assigned-this-event,
  range-exempt (both exemption paths), approved personal constraint
  covering the date, existing duty assignment covering the date,
  existing range assignment (any event) on the same date.
- Tier ordering: a soldier in Tier A with an earlier weapon-duty
  `start_date` sorts before one with a later one; Tier A sorts before
  Tier B sorts before Tier C; Tier C sorts by `valid_until` ascending.
- Fill respects `remaining_primary`/`remaining_reserve` counts exactly;
  partial fill when pool is smaller than needed, with correct shortfall
  count, no error raised.
- `is_draft=True` rows don't trigger a notification at creation;
  `confirm_draft_assignment` does.
- `confirm_all_drafts` flips every draft for the event and fires one
  notification per soldier.
- Rejecting a draft deletes the row and leaves the slot open for a
  subsequent auto-assign or manual add.
- Manual `add_range_assignment` (Phase 1 path) still notifies
  immediately, unaffected by `is_draft`.

Frontend (vitest):
- Auto-assign button disabled when no slots remain; calling it renders
  returned drafts with the draft badge.
- Confirm/reject per-row and bulk-confirm call the right endpoints and
  update the roster view.
- Shortfall banner renders when the response reports a shortfall.
