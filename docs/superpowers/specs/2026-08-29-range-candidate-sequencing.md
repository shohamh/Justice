# Range candidate sequencing — as-built behavioral contract

Recorded 2026-08-29 from the implemented code, after Tasks 1-6 of the
range-candidate-sequencing plan landed. This document describes what the
system actually does, not the original plan proposal — see notes below on
where the implementation narrowed or clarified the plan.

## Definitions

- **Primary range** — a `RangeAssignment` with `is_reserve=False` on a
  `RangeEvent`. It is a *projection*: as long as the event stays
  `planned` and the assignment carries no `pending` `RangeExcusalRequest`,
  it counts as guaranteed future qualification even though the event
  hasn't happened yet (`range_coverage.py::_primary_assignment_rows`).
- **Reserve range** — a `RangeAssignment` with `is_reserve=True`. Unlike
  primary, it only counts as coverage once attendance is *recorded*:
  `attendance_status == present` and the event is not `cancelled`
  (`range_coverage.py::_completed_reserve_assignment_rows`,
  `range_reconciliation.py::_source_provides_guaranteed_coverage`). A
  reserve assignment on a still-`planned` future event provides no
  coverage at all — only actual attendance does.
- **Pending excusal** — a `RangeExcusalRequest` with
  `status=pending`, tied 1:1 to a primary `RangeAssignment` (`request_primary_excusal`
  in `range_excusal.py`). While pending, the assignment stops counting as
  guaranteed coverage (`_primary_assignment_rows`'s `disqualify_pending`
  and `_source_provides_guaranteed_coverage`'s planned-status check
  implicitly excluding it via the caller flow — see coverage table).
- **Approved excusal** — a decided `RangeExcusalRequest` with
  `status=approved`. For a primary assignment (`decide_primary_excusal`),
  approval deletes the assignment outright and, if an eligible reserve
  exists on the same event, promotes that reserve to primary
  (`assignment.is_reserve = False`) and records
  `promoted_assignment_id`. For a reserve assignment
  (`request_reserve_excusal`), the request is auto-approved at creation
  time (self-service, no manager decision) and the assignment is deleted
  immediately.
- **Called-up / confirmed attendance** — `RangeAssignment.attendance_status
  == RangeAttendanceStatus.present`, the only attendance value the coverage
  seam treats as recorded presence for reserve coverage purposes.
- **Planned event** — a `RangeEvent` with `status == RangeEventStatus.planned`.
  Only planned events can source or receive reconciliation, and only
  planned primary assignments project future coverage.
- **Draft assignment / draft event** — a `RangeAssignment` with
  `is_draft=True` (or an event still in draft form). Drafts are inert for
  every purpose covered here: never a coverage source, never a
  reconciliation trigger, never a reconciliation target, and excluded from
  the `primary_filled`/`reserve_filled` counts (`ranges.py::_notify_roster_change`
  filters `not a.is_draft`).

## The coverage truth table

Basis: `range_coverage.py` (`get_range_coverages`, `_primary_assignment_rows`,
`_completed_reserve_assignment_rows`) and
`range_reconciliation.py::_source_provides_guaranteed_coverage`, which is the
authority used specifically to decide whether a *new* assignment/event-state
change should trigger reconciliation (a slightly narrower question than "is
this coverage classified as guaranteed" in general — see notes after the
table).

| Kind | State | Timing vs. duty/event date | Counts as guaranteed coverage? |
|---|---|---|---|
| Primary | planned event, no pending excusal | any (future window is what matters) | **Yes** — a projection, does not require the event to have happened |
| Primary | planned event, pending excusal | any | **No** — `disqualify_pending=True` is the default for candidate ranking; reconciliation's `_source_provides_guaranteed_coverage` never even reaches this state as a *source* because it's called right after the pending request is flushed, so the primary already fails the `event.status == planned` + `not pending_excusal` check |
| Primary | approved-excused (assignment deleted) | n/a | **No** — the assignment no longer exists; coverage comes only from whatever record (e.g. the promoted reserve) replaces it |
| Primary | draft | any | **No** — `is_draft=True` is unconditionally excluded from `_primary_assignment_rows` and from `_source_provides_guaranteed_coverage` |
| Primary | non-planned event (completed/cancelled) | any | **No** — `_primary_assignment_rows` filters `RangeEvent.status == planned`; a completed or cancelled event's primary assignment is not a coverage source (a soldier's *qualification* from actually attending is recorded separately via `SoldierRangeQualification`, not through this primary-assignment path) |
| Reserve | attendance recorded present, event not cancelled | before `as_of`/duty date (event already happened) | **Yes** — the only reserve path that counts |
| Reserve | planned event, attendance not yet recorded | before or after `as_of` | **No** — reserve coverage never projects forward; only recorded presence counts |
| Reserve | attendance present, event date after `as_of` | after `as_of` | **No** — `_completed_reserve_assignment_rows`/`get_range_coverages` bound reserve rows with `event_date_through=as_of`; an event after the point being evaluated can never qualify an earlier date, even if attendance somehow already shows present |
| Reserve | draft | any | **No** — excluded like primary drafts |
| Reserve | approved-excused (assignment deleted) | n/a | **No** — record no longer exists |

Notes on where the implementation narrowed/clarified the plan:

- **Reserve-coverage rule.** The plan's original framing treated reserve
  attendance more loosely; the as-built rule is strict on two axes at once:
  attendance must be `present` (not merely "assigned"), and the event date
  must be `<= as_of` — a future dated reserve event can never supply
  coverage no matter what its (would-be) attendance value is. This is
  enforced both in `get_range_coverages` (via `event_date_through=as_of`
  passed to `_completed_reserve_assignment_rows`) and independently in
  `_source_provides_guaranteed_coverage`, which relies on the *caller*
  only ever invoking reconciliation with a `source_event` that has already
  been established as the trigger (see Reconciliation behavior below) —
  it does not itself re-check the event's date against "today," it checks
  `attendance_status == present and event.status != cancelled`, trusting
  that a `present` reserve assignment only exists after the event date.
- **`user=None` candidate-pool semantics (Task 5B).** `_soldier_pool` in
  `range_auto_assign.py` treats `user=None` as "no caller context" (used
  exclusively by reconciliation's automatic refill), which resolves the
  candidate pool to *exactly* the target event's own hierarchy subtree —
  not the wider union of commanded/duty-manager subtrees a real user would
  get. This was an explicit decision so automatic refill never silently
  reaches across organizational boundaries a human caller would have been
  authorized to but the system has no standing consent to act on.
- **Same-date tie-break.** `_earliest_coverage` treats qualification as
  winning over primary and reserve coverage only on an exact
  `source_event_date` tie (see `kind_tiebreaker`); otherwise the source
  with the numerically earliest date wins regardless of kind.

## Reconciliation behavior

**What triggers it** (`reconcile_future_range_assignments` call sites):
1. `ranges.py::add_range_assignment` — every single assignment creation,
   after the new row is flushed (line ~482).
2. `ranges.py::assign_batch` — once per soldier in the batch, after all
   rows in the batch are validated and flushed (line ~550).
3. `range_excusal.py::request_primary_excusal` — called defensively right
   after the pending excusal request is flushed; documented in-code as a
   no-op today because the just-flushed pending request already makes the
   source assignment fail `_source_provides_guaranteed_coverage`, but kept
   so the call site stays correct if that predicate's rules ever change.
4. `range_excusal.py::decide_primary_excusal` — only when a primary
   excusal is approved **and** an eligible reserve was found to promote;
   the promoted soldier becomes the new coverage source for the *original*
   event. If no reserve is available to promote, there is nothing to
   reconcile (nobody just gained coverage) and reconciliation is skipped
   entirely — duty managers are notified of the no-backfill state instead.

**What it does**: for the `(soldier_id, source_event)` pair, if the source
assignment provides guaranteed coverage, it finds every other
non-draft assignment for that same soldier on a `planned` event dated
strictly after the source event and on/before the source's projected
`valid_until`, whose `range_type` is at the same tier or *lower* rank than
the source's (i.e. the source already covers that requirement). Each such
assignment is removed via `_remove_range_assignment_in_transaction` (audit
row written, roster-change notification sent), and its now-vacant slot is
immediately offered to the best-ranked replacement from the *target*
event's own hierarchy subtree only (`rank_candidates(..., user=None)`),
strictly preserving whether the vacated slot was primary or reserve
(`_refill_slot`'s `is_reserve` parameter is threaded straight through from
the removed assignment). All of this happens inside the same open
transaction as the original assignment/promotion — nothing is committed
mid-reconciliation; the caller (`add_range_assignment`, `assign_batch`,
`decide_primary_excusal`) commits once at the end.

**What it explicitly does NOT do**:
- Never touches draft assignments or draft events, in either direction —
  the target-discovery query filters `RangeAssignment.is_draft.is_(False)`
  and `RangeEvent.status == RangeEventStatus.planned` (which excludes any
  event still in a non-planned/draft-like state), and
  `_source_provides_guaranteed_coverage` returns `False` immediately for
  `assignment.is_draft`.
- Never touches cancelled or completed events — the target query requires
  `RangeEvent.status == RangeEventStatus.planned` (excludes both), and a
  reserve source additionally requires `event.status != cancelled`; a
  primary source requires `event.status == planned` outright (a completed
  or cancelled event can never be a reconciliation source).
- Never commits mid-transaction — `reconcile_future_range_assignments` and
  everything it calls (`_remove_range_assignment_in_transaction`,
  `_refill_slot`) only `session.flush()`; every call site commits once,
  after reconciliation returns.
- Never crosses primary/reserve — the vacated slot's `is_reserve` is
  captured before removal and passed straight into `_refill_slot`'s
  `is_reserve` parameter, so a primary vacancy is only ever refilled by a
  primary candidate and a reserve vacancy only by a reserve candidate.
- Never invents new response fields for shortages — see next section.

## How a shortage surfaces

`ReconciliationResult.unfilled_primary_count` / `unfilled_reserve_count`
are computed and incremented internally (`reconcile_future_range_assignments`,
when `_refill_slot` returns `None`), but neither field is serialized into
any API response. The caller (`add_range_assignment`, `assign_batch`,
`decide_primary_excusal`) reads `refilled_primary_assignment_ids` /
`refilled_reserve_assignment_ids` only to send "you've been assigned"
notifications to whoever got refilled in — it never reports the unfilled
counters anywhere.

The shortfall is instead visible purely through the *affected event's*
existing, pre-existing response fields — `required_count`, `reserve_count`,
and the derived `primary_filled`/`reserve_filled` counts computed in
`routes/ranges.py` from the event's current (non-draft) assignments. A
soldier removed by reconciliation with no replacement simply lowers
`primary_filled`/`reserve_filled` below `required_count`/`reserve_count`
the next time that event is fetched. The client discovers it needs to
refetch via the existing `range_roster_changed` notification, which
`_notify_roster_change` already fires whenever an assignment is removed
(including a reconciliation-driven removal) — no new notification type or
payload field was added for this.

This is confirmed end-to-end by
`backend/tests/integration/test_ranges_api.py::test_add_assignment_reconciliation_shortage_visible_via_api`,
which creates a shortage with no possible replacement in the target
event's subtree, then asserts the API call that triggered reconciliation
still succeeds (201) and that a subsequent GET on the affected event shows
`primary_filled == 0` against `required_count == 1` with no other new
field involved.

## Duplicate-authority-path review

Read `range_coverage.py`, `range_auto_assign.py`, `range_reconciliation.py`,
and `weapon_eligibility.py` end to end. Finding: **clean — no duplicate
authority path found.**

- `range_auto_assign.py::_bulk_rank` and `_rank_candidate` both call
  `get_range_coverages`/`get_range_coverage` from `range_coverage.py` for
  primary/reserve/qualification classification; neither re-implements the
  planned/pending/draft/date predicates itself.
- `range_reconciliation.py::_source_provides_guaranteed_coverage` does not
  call into `range_coverage.py` directly, but it does not re-derive the
  primary/reserve/draft/date classification rules either — it applies a
  narrower, single-assignment predicate (is *this specific* assignment
  usable as a trigger right now) built from the same underlying model
  fields (`is_draft`, `is_reserve`, `attendance_status`, `event.status`,
  and a fresh pending-excusal existence check) rather than importing and
  reusing `range_coverage.py`'s bulk classification, which is intentional
  since reconciliation needs a single yes/no on one already-known
  assignment (not a "search across all coverage sources for this soldier"
  query) and the two are next to each other in the same commit for review.
  It is worth naming as a soft duplication risk rather than a bug: the
  pending-excusal predicate (`RangeExcusalRequest.status == pending`) is
  written out independently in `_source_provides_guaranteed_coverage`
  (`range_reconciliation.py:49-54`) and in
  `range_coverage.py::_primary_assignment_rows` (`range_coverage.py:54-59`
  and `:71-72`). Both express the same "pending excusal exists" check
  against the same columns, just inlined twice rather than sharing one
  helper. Not a behavioral divergence today — flagged for awareness, not
  fixed in this task.
- `range_reconciliation.py::_refill_slot` calls `rank_candidates` from
  `range_auto_assign.py`, which itself uses `range_coverage.py` — so the
  refill path's ranking is the same seam as manual candidate ranking, not
  a separate implementation.
- `weapon_eligibility.py` calls `get_projected_range_windows` from
  `range_coverage.py` (via `_future_windows_by_soldier_and_required_type`)
  for its future-window computation, and layers only its own qualification
  `valid_until` lookups (`SoldierRangeQualification`, which is a distinct
  concern from assignment-based coverage) and system-setting gates on top.
  It does not reimplement primary/reserve/draft/date classification.

**Concern to note** (not a defect, but worth flagging per the brief): the
pending-excusal-exists subquery is written twice
(`range_reconciliation.py:49-54` and `range_coverage.py:54-59`,`71-72`)
instead of sharing one helper. Left as-is per task scope (no implementation
changes in this task).

## Automatic-behavior boundary confirmations

- **Cancelled and completed events are excluded from both the
  removal-target query and from ever acting as a guaranteed-coverage
  source.** Target query: `range_reconciliation.py:133`
  (`RangeEvent.status == RangeEventStatus.planned`) excludes both
  cancelled and completed targets. Source: `range_reconciliation.py:47-48`
  (`if event.status != RangeEventStatus.planned: return False`) excludes
  both for a primary source; `range_reconciliation.py:45`
  (`event.status != RangeEventStatus.cancelled`) excludes cancelled
  specifically for a reserve source (a reserve source additionally
  requires recorded `present` attendance, which in practice only exists
  once an event has run its course).
- **Draft assignments and draft events are excluded from both directions
  (never a trigger, never a target).** Trigger: `range_reconciliation.py:41-42`
  (`if assignment.is_draft: return False`) inside
  `_source_provides_guaranteed_coverage`. Target:
  `range_reconciliation.py:132` (`RangeAssignment.is_draft.is_(False)`) in
  the target-discovery query's `where` clause.
- **Primary and reserve counts are never merged.** The vacated slot's kind
  is captured before removal at `range_reconciliation.py:145`
  (`removed_id, is_reserve = assignment.id, assignment.is_reserve`) and
  threaded straight into the refill call at `range_reconciliation.py:154-157`
  (`_refill_slot(..., is_reserve=is_reserve, ...)`), which itself passes
  `is_reserve` unchanged into `_validate_and_build_assignment` at
  `range_reconciliation.py:73-76`. The result is recorded into the
  distinct `refilled_primary_assignment_ids`/`refilled_reserve_assignment_ids`
  (and `unfilled_primary_count`/`unfilled_reserve_count`) fields at
  `range_reconciliation.py:158-166` based on that same captured
  `is_reserve` flag, so a primary vacancy can never be counted or filled as
  reserve or vice versa.
