# מטווחים (Ranges) — Phase 3: advance excusal & reserve promotion design spec

## Goal

Let a soldier declare in advance that they won't be able to attend an
upcoming range event, with a mandatory reason. For a **primary**, this
requires DM or commander approval before anything changes on the roster;
once approved, the best eligible currently-assigned reserve is
automatically promoted to primary. For a **reserve**, no approval is
needed — they can drop out immediately. Builds directly on the
[Phase 1](2026-07-31-mitvachim-phase1-design.md) and
[Phase 2](2026-07-31-mitvachim-phase2-auto-assign-design.md) specs — same
tables, same candidate-filtering/tier-sort logic, no new schema beyond one
small table.

## Current state (relevant existing patterns)

- Phase 1/2 already define `RangeEvent`, `RangeAssignment` (with
  `is_draft`), the candidate-filter + three-tier sort used by
  auto-assign, and `Action.RANGE_MANAGE` (subunit-scoped, no elevation).
- `backend/app/services/authority.py` (`dm_scope_covers_level`,
  `get_level_rank`, `COMMANDER_EXEMPTION_MIN_LEVEL_KEY = "מדור"`) is the
  existing pattern for "commander whose commanded node is at level X or
  higher" checks — reused here for the commander side of excusal
  approval, with a new setting defaulting to the same `"מדור"` level.
- The existing duty swap system (`backend/app/services/swaps.py`) was
  investigated as a possible template but is **not** reused: it's built
  around a marketplace/named-target negotiation with multi-step
  soldier+manager approval chains, for a problem (arbitrary duty-to-duty
  swaps) that doesn't apply here — a range event already has its own
  pre-assigned, tier-ordered reserve pool, so "who replaces the primary"
  never needs negotiation, only an approval gate on the request itself.
- `backend/app/services/reserves.py`'s `dismiss_primary` (duty side)
  notably does **not** auto-promote a reserve today (that's manual
  DM follow-up) — this phase intentionally builds the auto-promotion
  behavior for ranges that doesn't yet exist for duty, per your explicit
  request.

## Rejected approaches

- **Reusing the duty swap marketplace/candidate system**: rejected —
  wrong shape for this problem (see above); would add named-target
  invites, marketplace board, and multi-step approval-chain machinery
  that ranges don't need, since the reserve pool and its priority order
  already exist on the event.
- **Auto-promoting immediately on the soldier's request, before
  approval**: rejected per your correction — a primary's excusal must be
  approved first; only reserves get to self-remove without a gate.
- **Requiring approval for reserve excusal too**: rejected — a reserve
  dropping out doesn't change who's on primary duty, so there's nothing
  for a DM/commander to approve; only the DM being informed matters.

## Design

**`RangeExcusalRequest`** (new table) — created when a **primary**
submits "לא אוכל להגיע":
- `range_assignment_id` (FK, the primary's row — stays intact and
  unchanged while the request is `pending`)
- `reason` (Text, required)
- `requested_at`
- `status`: `pending` | `approved` | `rejected`
- `decided_by`, `decided_at`, `decision_note` (nullable)
- `promoted_assignment_id` (nullable FK → the reserve's `RangeAssignment`
  row, set only on approval if a promotion happened)

One open (`pending`) request per `range_assignment_id` at a time
(partial unique index, mirroring `SwapRequest`'s one-open-request
constraint).

**Primary excusal flow**:
1. Soldier submits → `RangeExcusalRequest(status="pending")` created.
   The original `RangeAssignment` is untouched — soldier still shows as
   assigned, still expected to attend, until a decision is made.
2. DM (subunit scope, regular `RANGE_MANAGE`, no elevation) or commander
   at `מדור`-rank-or-higher over that subunit (new setting
   `mitvachim.excusal_approve_min_commander_level`, default `"מדור"`,
   checked via `dm_scope_covers_level` against the commander's own
   commanded node) reviews the request:
   - **Reject**: `status="rejected"`, `decision_note` optional, soldier
     stays assigned, notified of the rejection.
   - **Approve**: `status="approved"`; the original primary's
     `RangeAssignment` row is deleted; the same Phase 2 candidate-filter
     + three-tier sort runs, restricted to the event's *currently
     assigned reserves* (`is_reserve=True`, not already excused/removed,
     re-checked against the same conflict filters since time may have
     passed); the top-ranked eligible reserve is promoted
     (`is_reserve → False`), `promoted_assignment_id` set on the
     request, promoted soldier notified. If no reserve is eligible, the
     primary slot is left open and the DM is notified that a manual
     backfill is needed.
3. **Backfill tooling**: after approval (with or without a successful
   promotion), the DM can freely add a replacement reserve manually
   (Phase 1 `add_range_assignment`) or re-run "שבץ אוטומטית" (Phase 2) to
   top up the now-short reserve count — no new mechanism, this is just
   the existing tooling operating on the event's now-smaller roster.

**Reserve excusal flow** (no approval): soldier submits reason →
service immediately deletes their `RangeAssignment` row and writes a
lightweight audit record (reuse `RangeExcusalRequest` with
`status="approved"` set immediately, `decided_by = null` to mark it as
self-service/no-approval-needed — avoids a second table for what's
structurally the same audit shape). DM notified their reserve pool
shrank by one; no promotion logic runs (nothing to promote into).

## Data model changes

**New table `RangeExcusalRequest`** as above. No changes to
`RangeAssignment`, `RangeEvent`, or any Phase 1/2 table.

## Backend

**New action**: `Action.RANGE_EXCUSAL_DECIDE` — bucketed into both
`_DM_ACTIONS` (subunit scope, no elevation, same scope check as
`RANGE_MANAGE`) and `_COMMANDER_ACTIONS` (gated by
`dm_scope_covers_level` against `mitvachim.excusal_approve_min_commander_level`,
mirroring `commander_can_grant_commander_exemption`'s shape in
`authority.py`).

**New service functions** (`backend/app/services/range_excusal.py`):
- `request_primary_excusal(assignment, reason, requested_by)` — guards:
  assignment must be `is_reserve=False`, `event.date` in the future, no
  existing `pending` request for this assignment.
- `decide_primary_excusal(request, approve: bool, decided_by, note=None)`
  — on reject: sets status, notifies soldier. On approve: deletes the
  primary's `RangeAssignment`, runs the restricted tier-sort over
  current reserves (reusing Phase 2's filter/sort function, parameterized
  to the reserve subset instead of the full candidate pool), promotes the
  winner or notifies the DM of no eligible reserve, sets
  `promoted_assignment_id`, notifies the promoted soldier.
- `request_reserve_excusal(assignment, reason, requested_by)` — guards:
  `is_reserve=True`, `event.date` in the future; deletes the assignment,
  writes the self-approved audit record, notifies the DM.

**New routes** (`backend/app/routes/ranges.py`, extends Phase 1/2):
- `POST /ranges/{id}/assignments/{id}/excuse` — body `{reason}`; branches
  internally on `is_reserve` to call the primary (creates pending
  request) or reserve (immediate) path. Authorized as "any assigned
  soldier acting on their own assignment" (ownership check, not a scope
  action).
- `POST /ranges/{id}/excusal-requests/{id}/decide`
  (`RANGE_EXCUSAL_DECIDE`) — body `{approve: bool, note?}`.
- `GET /ranges/{id}/excusal-requests` (`RANGE_MANAGE` or
  `RANGE_EXCUSAL_DECIDE` scope) — pending requests for the DM/commander's
  review queue.

## Frontend

- **"לא אוכל להגיע" button** on a soldier's own upcoming range
  assignment (homepage widget or a personal "my assignments" view) — free
  text reason required to submit.
- **Review queue** (new section on the planning/commander page): lists
  pending `RangeExcusalRequest`s in scope, with approve/reject controls
  and the reason shown; approving shows the resulting promotion (or "no
  eligible reserve" warning) inline.
- **Reserve self-drop**: same button, but submits immediately with no
  review-queue entry — a toast confirms removal.

## Testing

Backend (pytest):
- Primary excusal creates a `pending` request; original assignment
  unchanged until decided.
- Reject: request closed, assignment untouched, soldier notified.
- Approve with an eligible reserve: original assignment deleted, correct
  reserve promoted (tier-sort verified same as Phase 2's ordering tests,
  scoped to reserves only), `promoted_assignment_id` set, notifications
  fired.
- Approve with no eligible reserve (all reserves excluded by conflicts,
  or zero reserves assigned): slot left open, DM notified, no promotion
  row created.
- Reserve excusal: immediate deletion, no approval step, DM notified,
  no promotion logic invoked.
- One-open-request-per-assignment constraint enforced.
- `RANGE_EXCUSAL_DECIDE` authorization: DM in subunit scope (any level)
  → allowed; commander at `מדור` rank or higher over the subunit →
  allowed; commander below that rank → denied.

Frontend (vitest):
- "לא אוכל להגיע" requires non-empty reason before submit is enabled.
- Review queue renders pending requests; approve/reject call the right
  endpoint; approved-with-promotion vs approved-without-eligible-reserve
  render distinct outcomes.
- Reserve self-drop shows immediate confirmation, no queue entry.
