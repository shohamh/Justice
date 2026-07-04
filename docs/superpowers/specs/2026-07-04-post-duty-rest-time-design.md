# Post-duty rest time

## Goal

Introduce a minimum rest period a soldier must have after finishing a duty before
starting another one. Default 12 hours, configurable globally and per duty type.
If a soldier is dismissed early mid-duty, rest counts from the dismissal moment,
not the duty's originally scheduled end.

## Rest calculation rules

**Base rest**: every duty assignment, once it truly ends, requires a rest period
(default 12h) before the same soldier can start another duty. Configurable via:
- A global `SystemSetting` key `duty.default_rest_hours` (default `12`).
- An optional per-`DutyType` override: a `rest_hours` key inside the existing
  `requirements` JSONB field. Falls back to the global default when absent.

**Effective end moment** for a duty assignment, used as the start of the rest window:
- Normally: `end_date` combined with the assignment's `end_time`.
- If a `DutyDismissal` exists for the assignment where `dismissed_to >= end_date`
  (the soldier never returns to finish the duty): effective end becomes
  `dismissed_from` combined with the assignment's `start_time`. This is a
  conservative assumption — since `dismissed_from` only has date precision, we
  assume the dismissal happened at the start of that day's shift, which
  guarantees at least the configured rest period regardless of when during the
  day the dismissal actually happened.
- If a `DutyDismissal` exists but `dismissed_to < end_date` (temporary leave —
  the soldier resumes the same assignment before its scheduled end): this does
  **not** shorten the duty. Effective end stays at the original
  `end_date`/`end_time`. A short mid-duty pause with return is not an early
  exit from the duty.

**Gimelim (reserve) stacking**: for dismissals flagged `is_gimelim=true`, an
additional configurable buffer stacks on top of the base rest_hours. This
reuses the existing `gimalim.default_rest_days` system setting (default
unchanged at `7`), reinterpreted as "extra rest days added on top of base
rest" rather than a standalone rule. Total gimelim rest = base rest_hours +
`gimalim.default_rest_days`, both counted from the same effective-end moment
defined above. This replaces the current flat "N days from end_date" logic in
`backend/app/services/gimelim.py`.

**Which duty type's rest_hours applies**: when two duties of different types
are adjacent for the same soldier, the rest requirement is determined by the
**outgoing** (just-finished) duty's type — i.e., "how much recovery this type
of duty demands" — regardless of the incoming duty's type.

## Algorithm enforcement (CP-SAT)

A new **hard constraint** in `backend/app/algorithm/model.py`, alongside the
existing per-day no-overlap constraint (~lines 388-403): for each soldier, no
candidate assignment may start before `effective_end + rest_hours` of any
prior assignment (existing or newly placed by the solver in the same run).

Since the solver operates on whole days, hour-precision rest is translated
into a **per-duty-type-pair blocked-day matrix**, precomputed once per
algorithm run: for each ordered pair (outgoing duty type, incoming duty type),
compute how many extra calendar days must be blocked after the outgoing
type's normal end_time before the incoming type's normal start_time satisfies
the outgoing type's rest_hours.

Example: a duty ending at 17:00 and rest_hours=12 — the next duty's normal
08:00 start the following day is a 15h gap, which already satisfies the rule,
so zero *extra* blocked days beyond the existing same-day exclusion. A
type-pair with a tighter time window might require blocking the following day
too. This keeps the existing boolean-per-soldier-per-day model structure
rather than introducing continuous time variables into the CP-SAT model.

`ExistingAssignment` (`backend/app/algorithm/types.py`) needs to carry each
assignment's effective end (dismissal adjustment already applied) so the
solver itself stays dismissal-agnostic — that computation happens once in a
shared helper before assignments are loaded into the solver.

## Manual assignment path

`backend/app/services/assignments.py` already validates overlaps
(`AssignmentError` → `"overlap"` → HTTP 409, see `backend/app/routes/assignments.py:20`).
Add an analogous rest check there (e.g. a new `"insufficient_rest"` conflict
code) so manually creating/editing an assignment through the UI is validated
the same way as the auto-scheduler, using the same effective-end/rest_hours
calculation.

## Data & settings changes

No new DB columns are needed:
- `DutyDismissal.dismissed_from`/`dismissed_to` (`backend/app/db/models.py:735-736`)
  already provide what the rest calculation needs.
- `DutyType.requirements` JSONB (`backend/app/db/models.py:152-154`) already
  supports arbitrary override keys; add `rest_hours` as a recognized key.

New `SystemSetting`:
- `duty.default_rest_hours` (default `12`), read via the existing
  `get_setting()` pattern (see `backend/app/services/gimelim.py:29`).

Existing setting reinterpreted:
- `gimalim.default_rest_days` (`backend/app/routes/public_settings.py:16`)
  keeps its key and default value, but its meaning changes from "days after
  end_date before re-callup eligible" to "extra days stacked on top of base
  rest_hours for gimelim dismissals."

## Frontend surfaces

- Duty type edit dialog: optional "rest hours override" field.
- System settings page: new "default rest hours" field; relabel the existing
  gimelim rest-days field to reflect the new stacking semantics.
- Out of scope for this design: any new visual "resting" indicator on the
  calendar (candidate fast-follow, not required here).

## Testing

- Extend `pytest -m algorithm` tests for the new CP-SAT constraint, including
  the explicit 8am–5pm-duty / 8am-next-day-ok scenario.
- Extend `pytest -m duty` / assignments service tests for the manual-path
  validation (`insufficient_rest` conflict).
- Update/extend gimelim tests (`backend/app/services/tests/test_duty_history.py`
  and gimelim-specific tests) for the stacked rest calculation and the
  "`dismissed_to < end_date` → no early rest" case.

## Out of scope

- Per-soldier rest overrides (only global + per-duty-type).
- Calendar UI visualization of rest/blocked periods.
- Any change to the existing per-day no-overlap constraint itself — rest is
  additive to it, not a replacement.
