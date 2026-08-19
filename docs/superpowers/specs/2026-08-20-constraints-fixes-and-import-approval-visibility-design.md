# Personal-constraint fixes, partial import, and approval visibility

Date: 2026-08-20

Five independent, small-to-medium changes to the personal-constraints workflow,
the Excel import wizard, and approval-status visibility. Each is scoped to be
implemented and tested independently.

## 1. Double-approve on the manager Approvals queue

**Problem:** Clicking "approve" sometimes appears to require a second click.

**Root causes (both real, both fixed):**
- The approve button in `ApprovalsPage.tsx` has no in-flight/disabled state,
  so a fast double-click (or a click while a slow request is still pending)
  can fire the mutation twice.
- Personal constraints (and exemption requests) can require a genuine
  two-step approval (commander, then duty manager). When the same person
  holds both roles for a soldier, the item reappears in the queue needing a
  second, distinct approval — easy to mistake for "the first click didn't
  work."

**Fix:**
- Track in-flight row IDs locally in `ApprovalsPage.tsx` (e.g. a
  `Set<string>` of ids currently being approved/rejected) and disable the
  relevant button while the id is in that set, for constraints, exemption
  requests, field updates, and transfer requests (same button pattern is
  reused across all of them).
- Add a small step indicator ("1/2" or "2/2") next to constraint and
  exemption-request rows whose flow requires both commander and duty-manager
  approval, derived from existing status + the
  `constraints.require_commander_approval` /
  `constraints.require_duty_manager_approval` settings (already fetched
  elsewhere in the app) — no new backend field required for constraints
  since `status` already distinguishes `pending_commander` from
  `pending_duty_manager`.

## 2. Privacy leak: personal-constraint reason exposed via duty history

**Problem:** `get_duty_history()` in `backend/app/services/duty_history.py`
builds `personal_constraint` timeline events with `description=c.reason`
unconditionally, ignoring the `include_sensitive` flag that
`get_soldier_duty_history()` in `backend/app/routes/soldiers.py` already
computes correctly via `can_see_private()`. Any viewer with general
duty-history visibility for a soldier (broader than "can see private info")
currently sees the private reason text.

**Fix:** Gate `description` (and any other reason-derived field) on
`personal_constraint` events behind `include_sensitive`, matching the
existing pattern used for `SoldierExemption` events a few lines above in the
same function. When not sensitive, keep the event (soldiers, dates, status
are not private) but null out the reason text.

## 3. Quarterly quota not enforced across a quarter boundary

**Problem:** `submit_constraint()` calls `remaining_days()` to check the cap,
but `remaining_days()` computes the period window from *today's date*, not
from the submitted request's own date range. A request submitted before a
quarter boundary for dates entirely after that boundary has zero overlap
with "today's" quarter, so the cap check computes `requested_in_period = 0`
and passes trivially — regardless of the actual cap.

**Fix:** Give `remaining_days()` an explicit period-anchor date, separate
from "today" used for display purposes:
- Keep the existing default behavior (anchor = today) for the two
  *display* call sites (`GET /me/constraints/remaining`).
- In `submit_constraint()`'s cap check specifically, anchor the period to
  the request's own `start_date` instead of today. A request spanning two
  quarters still gets clipped/split correctly by the existing overlap math
  — only the anchor changes.
- Add a regression test: submit a request before a quarter boundary for
  dates after it, confirm the cap is enforced against the target quarter.

**Retraction:** Widen `cancel_constraint()` (currently `pending_commander`
only) to also allow cancellation while `status == "pending_duty_manager"`,
per user decision. Once `approved`, a constraint stays final — no widening
there. Update the matching frontend condition and stale comment in
`MyRequestsPage.tsx` (the comment there currently asserts only the first
step is cancelable, which becomes false).

## 4. Partial Excel import (import only selected sections)

**Current architecture:** the parser (`v1_standard.py`) already produces
discrete per-section rows (`soldiers`, `duty_shifts`, `personal_constraints`,
`exemption_requests`, etc.) inside one `ParsedImportData`/`parsed_state`
object. `confirm_session()` in `import_sessions.py` processes each section in
its own loop, and every loop already checks
`effective = _effective_action(selections, group, row)` and skips the row
when `effective == "skip"`. `user_selections` is a plain dict keyed by group
name, so no DB schema change is needed to add a new kind of entry to it.

**Fix:**
- Reserve a key `"__excluded_groups__"` in the `user_selections` dict,
  holding a list of group names the user has opted out of entirely.
- `_effective_action()` returns `"skip"` for any row whose group is in that
  list, before falling through to the existing per-row/default logic — this
  makes every existing per-group loop in `confirm_session()` respect the
  exclusion automatically, with no changes needed inside those ~20 loops.
- Frontend: on `ImportSessionReviewPage.tsx`, above the existing tab bar,
  add a checklist of the sections actually detected in this file (only show
  sections that have at least one parsed row), each togglable. Toggling
  calls the existing `set_selections` API to persist
  `__excluded_groups__`. An excluded section's tab shows a visually
  distinct "excluded" state and its rows are not counted in the confirm
  summary's created/updated totals.
- Preview/summary counts (created/updated/skipped) already flow through
  `confirm_session`'s per-row skip path, so excluded sections show up as
  "skipped" — no separate counting logic needed.

## 5. "Waiting on X" visibility for the requester

**Current state:** the manager-facing Approvals queue already shows grouped
commander/duty-manager approver badges for constraints, exemption requests,
and swap manager chains (`ApprovalsPage.tsx`), and the constraint API
(`ConstraintOut`) already returns `nearest_commander` / `nearest_duty_manager`
identity. This is not yet surfaced to the soldier who submitted the request.

**Fix:**
- In `MyRequestsPage.tsx`, add a "Waiting on: <name>" line to each pending
  personal-constraint row, picking `nearest_commander` when
  `status == "pending_commander"` and `nearest_duty_manager` when
  `status == "pending_duty_manager"`.
- Check whether `ExemptionRequestOut` (backend) already returns the same
  `nearest_commander`/`nearest_duty_manager` fields (route code suggests it
  does — confirm during implementation) and add the same badge to the
  exemption-request list in the same page. If the fields aren't already
  exposed on that schema, add them following the existing constraints
  pattern (`_nearest_approvers()` helper already exists and is reusable).
- No change to the manager Approvals queue (already covers "who's waiting").

## Testing

Each of the five items gets its own test coverage, added test-first per the
project's usual pytest/vitest conventions:
- Backend: `backend/app/services/tests/` for the duty-history privacy fix
  and the quota-anchor fix; `backend/tests/` (integration) for the
  cancel-widening and import-exclusion changes.
- Frontend: existing `*.test.tsx` files for `ApprovalsPage`,
  `MyRequestsPage`, and `ImportSessionReviewPage` get new cases for the
  disabled-button race, the step indicator, the "waiting on" badge, and the
  section-exclusion checklist.

## Out of scope

- No change to how many approval steps exist, or who can approve — only to
  how state/identity already computed is surfaced or checked.
- No change to the Excel file format or parser detection logic — only to
  which already-parsed sections get applied.
- No admin UI for configuring which sections are importable by default —
  the checklist is per-session, not a saved preference.
