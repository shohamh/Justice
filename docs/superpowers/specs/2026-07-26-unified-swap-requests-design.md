# Unified swap requests — design spec

## Goal

A soldier can have at most one outstanding "swap this duty out" request per
duty assignment, no matter how many people they invite or whether they also
post it to the open marketplace. That single request can attract multiple
candidate covering soldiers in parallel — each independently accepted and
run through their own commander/duty-manager approval chain — and whichever
candidate finishes approval first actually performs the cover; the rest are
cancelled at that point. Both `SwapsPage` (the requester's own view) and
`ApprovalsPage` (the commander/duty-manager approval queue) show this as one
request with a visible list of candidates and each one's approval progress.

## Current state (what's changing and why)

Today, `backend/app/db/models.py`'s `SwapRequest` is one row per
`(duty_assignment_id, target_soldier_id)`. Asking N specific people calls
`create_request()` (`backend/app/services/swaps.py:60`), which fans out into
N separate rows via `_create_single_request()`. Posting to the open
marketplace is a *different*, mutually exclusive path: a single row with
`target_soldier_id = NULL`. The moment any one row is claimed
(`claim_request()`, `swaps.py:542`), its "siblings" — other rows for the
same `(duty_assignment_id, requesting_soldier_id)` — are cancelled
immediately, *before* any manager approval happens (`swaps.py:604-632`).
Manager approval (`SwapManagerApproval`, keyed by
`(swap_request_id, side, commander_id, approver_kind)`) only ever applies to
the single row that got claimed, since only one row per duty ever reaches
`pending_approval`.

This produces exactly the symptom reported: `SwapsPage`'s "mine" tab
(`frontend/src/pages/SwapsPage.tsx:659-662`, `renderMySwapCard` at :487)
renders `mySwaps.map(renderMySwapCard)` — one full card per row — so asking
3 people shows 3 separate cards for what is conceptually one outstanding
ask, each with its own cancel button and status badge.

The new design:
- Collapses request identity to one row per `(requesting_soldier_id, duty_assignment_id)`.
- Splits "who might cover this" into a new child table, so a request can have zero, one, or many candidates from either source (invited or marketplace-claimed) at once.
- Lets candidates run their approval chains in parallel — first fully-approved candidate wins, per your explicit choice over the simpler "first acceptance locks in" alternative.

## Data model

### `SwapRequest` (modified)

Remove `target_soldier_id`, `covering_soldier_id`, `requester_side_approved`,
`covering_side_approved` (these move to `SwapCandidate`, one instance per
candidate rather than one shared pair of flags on the parent). Add:

- `open_to_marketplace: bool` (`server_default=false`) — true if this
  request is visible on the open board for any eligible soldier to claim,
  independent of whether specific soldiers were also invited.

Keep: `id`, `duty_assignment_id`, `duty_date`, `requesting_soldier_id`,
`status` (`open` → `applied` | `rejected` | `cancelled` — no more
`pending_approval` on the *parent*; that state now lives per-candidate),
`reason`, `resulting_override_id`, `decision_note`, `rejected_by`,
`offered_assignment_ids` (moves to `SwapCandidate` — a counter-offer is a
property of a specific candidate's proposal, not the parent), `created_at`.

A DB-level partial unique index enforces the "no duplicate request for the
same duty" rule directly: `UNIQUE (requesting_soldier_id, duty_assignment_id) WHERE status = 'open'`
— exactly the "don't allow multiple swap requests for the same duty by the
same user" requirement, enforced as a real constraint, not just app-level
validation (defense in depth: `_create_single_request`'s existing
`existing = session.execute(...)` pre-check pattern stays as the
friendly-error path; the index is the backstop).

### `SwapCandidate` (new table, `swap_candidates`)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `swap_request_id` | UUID FK → `swap_requests.id`, `ondelete=CASCADE` | |
| `soldier_id` | UUID FK → `soldiers.id`, `ondelete=CASCADE` | the candidate covering soldier |
| `source` | Text | `"invited"` \| `"marketplace"` |
| `status` | Text | `"pending"` (invited, awaiting response) → `"declined"` \| `"accepted"` → `"pending_approval"` implicit via manager-approval rows' state → `"applied"` \| `"cancelled"` |
| `offered_assignment_ids` | JSONB, `server_default='[]'` | this candidate's own counter-offer, if any (moved from the parent — was `submitCoverOffer`) |
| `soldier_side_approved` | Boolean, nullable | this candidate's own "I agree to cover" confirmation (was `covering_side_approved` on the parent) |
| `created_at` | timestamptz | |
| `decided_at` | timestamptz, nullable | when accepted/declined/finalized |

Unique constraint: `(swap_request_id, soldier_id)` — a soldier can only be
one candidate per request, even if somehow both invited and self-claiming
from the marketplace (the invite row is reused, `source` doesn't change).

Marketplace claims (`claim_request`) create a `SwapCandidate` row with
`source="marketplace"` on demand, gated on `open_to_marketplace = true` and
the request having no existing candidate row for that soldier. Invited
targets get their `SwapCandidate` rows created at request-creation time
(`source="invited"`, `status="pending"`), same as today's fan-out — just
into the child table instead of duplicate parent rows.

### `SwapManagerApproval` (modified)

Add `swap_candidate_id: UUID | None` (FK → `swap_candidates.id`,
`ondelete=CASCADE`). Requester-side approval rows (`side="requester"`) keep
referencing `swap_request_id` directly with `swap_candidate_id = NULL` —
there's exactly one requester regardless of how many candidates exist, so
that chain is shared and only needs to run once. Covering-side rows
(`side="covering"`) now require `swap_candidate_id` — each candidate has
their own commander/duty-manager chain, since they're different soldiers.
The existing unique constraint
(`swap_request_id, side, commander_id, approver_kind`) becomes
`(swap_request_id, swap_candidate_id, side, commander_id, approver_kind)` to
allow the same commander to appear once per candidate they're responsible
for (e.g. commander of soldier A on candidate 1, and separately of soldier B
on candidate 2, if A and B share a commander that's a coincidence, not a
conflict).

### Migration for existing data

Existing `open`/`pending_approval` rows get converted in place: each
existing `SwapRequest` row becomes both a parent row (stripped of the
moved columns) and exactly one `SwapCandidate` row carrying
`target_soldier_id`/`covering_soldier_id` → `soldier_id`,
`covering_side_approved` → `soldier_side_approved`,
`offered_assignment_ids` → the candidate's own column, and
`source = "marketplace" if target_soldier_id was NULL else "invited"`.
Existing `SwapManagerApproval` rows for `side="covering"` get backfilled
with the new candidate's id; `side="requester"` rows keep
`swap_candidate_id = NULL`. Since today's sibling-cancellation means at most
one row per `(requester, duty)` is ever non-terminal at a time, this
migration has no real multi-row-merge case to handle for live data — it's a
reshape, not a merge. `applied`/`rejected`/`cancelled` rows also get
reshaped the same way for historical consistency (list-mine / audit trails
keep working), even though they're not part of any "in-flight" grouping
concern anymore.

## Service-layer behavior (`backend/app/services/swaps.py`)

- `create_request()` / `_create_single_request()`: creates one `SwapRequest`
  parent, then one `SwapCandidate` row per invited target (`source="invited"`,
  `status="pending"`), and sets `open_to_marketplace=True` if the caller
  chose the open-board mode. Since both modes can now combine, the
  frontend's mutually-exclusive radio buttons become a checkbox-style
  choice (see UI section) — a single call can pass both target soldier ids
  and the marketplace flag. The DB partial unique index is the enforcement
  point for "no second open request for this duty"; catch its violation and
  translate to the existing `SwapError("already_pending")`.
- `claim_request()` (marketplace claim): instead of setting
  `covering_soldier_id` on the parent, creates or reuses a `SwapCandidate`
  row (`source="marketplace"`) and sets its `soldier_side_approved = True`
  (claiming implies consent, as today). No more "cancel siblings on claim"
  — parallel candidates are now the intended, supported state. The request
  parent's `status` does not change to `pending_approval` any more (that
  concept moves to the candidate); the parent stays `open` until one
  candidate fully finalizes.
- Soldier-side approve/reject (`approve_soldier_side` equivalent): operates
  on a `swap_candidate_id`, not the request id — sets that candidate's
  `soldier_side_approved`, or on reject, sets that candidate's `status =
  "declined"` (does **not** kill the whole request — other candidates, and
  the open invite/marketplace slots, continue unaffected). The **requester's**
  own approval (`requester_side_approved` today) becomes a once-per-request
  action tied to the parent, satisfied independently of which candidate
  ends up winning (semantically: "I still want to swap this out," not tied
  to a specific candidate) — call it out explicitly as new behavior: today
  requester approval is auto-set to `True` at claim time; keep that
  auto-set-on-first-candidate-acceptance behavior, but store it on the
  parent (shared), not duplicated per candidate.
- Manager approve/reject (`approve_manager_row`, `approve_manager_side`,
  `approve_manager_side_override`, `reject_manager_row`): every call now
  takes a `swap_candidate_id` for the covering side (requester side stays
  request-scoped). `_qualifying_rows_for_actor` and `is_chain_commander_for_side`
  resolve against the specific candidate's `soldier_id` for `side="covering"`.
  A manager rejecting a candidate sets that candidate's `status =
  "cancelled"` and notifies just that candidate + the requester — it does
  **not** reject the whole parent request (other candidates keep going).
- `_all_approved` / `_try_finalize` becomes per-candidate: a candidate is
  "approved" once its own `soldier_side_approved` is true, the shared
  requester-side approval is true, and its own commander/duty-manager chain
  (if any) is fully approved. **Finalization is now a race**: the first
  candidate to become fully approved triggers `_apply_cover()` (using that
  candidate's `soldier_id` and `offered_assignment_ids`), sets the parent's
  `status = "applied"`, sets that candidate's `status = "applied"`, and
  cancels every other still-live candidate (`pending`/`accepted`, with
  in-flight manager-approval rows left as historical record) — same
  notification pattern as today's sibling-cancel, just moved to finalize
  time instead of claim time.
- `reject_request()` (requester rejects the whole thing) and
  `cancel_request()` (requester cancels): unchanged in spirit — operate on
  the parent, cascade-cancel every live candidate, notify each one that had
  progressed past "pending".
- `take_free()`: unaffected in spirit — it's a proactive, no-approval
  bypass unrelated to the invite/marketplace flow. Under the new schema it
  creates a parent row plus one `SwapCandidate` (`source="marketplace"`,
  immediately `status="applied"`) so it fits the same read shape everywhere
  else, without going through the multi-candidate machinery at all.
- `cover_offer()` / `submitCoverOffer`: becomes an action on a specific
  candidate (sets that candidate's `offered_assignment_ids`), not the
  parent.

## API changes

- `GET /me/swaps`, `GET /swaps/board`, `GET /swaps/incoming`,
  `GET /swaps/pending`, `GET /swaps/for-assignment/{id}`: response shape
  changes from a flat `SwapRequest` (with `covering_soldier_id`,
  `covering_manager_approvals`, etc.) to a `SwapRequest` with a nested
  `candidates: SwapCandidateOut[]` list, each carrying its own
  `soldier_id`, `soldier_name`, `source`, `status`,
  `soldier_side_approved`, `offered_assignment_ids`, and
  `manager_approvals: SwapManagerApproval[]` (the existing shape, now
  per-candidate instead of per-request-side).
- `POST /me/swaps`: body gains `open_to_marketplace: bool` alongside the
  existing `target_soldier_id(s)`; both may be set. Still returns a single
  `SwapRequest` (never a list — no more client-visible fan-out).
- `POST /swaps/{id}/claim`: unchanged signature; internally creates/reuses a
  candidate instead of mutating the parent.
- `POST /me/swaps/{id}/approve`, `/reject`: signature unchanged (no new
  body field). The route resolves "the candidate row for this request
  where `soldier_id` = current user" server-side — the
  `(swap_request_id, soldier_id)` unique constraint guarantees at most one
  match, so the client never needs to know or pass a candidate id for its
  own actions.
- `POST /swaps/{id}/manager-approve`, `/manager-reject`: gain a required
  `candidate_id` for `side="covering"` (a manager may have multiple
  candidates to judge on one request); `side="requester"` calls don't need
  one.
- `POST /swaps/{id}/offer`: becomes `POST /swaps/{id}/candidates/{candidate_id}/offer`.

## Frontend changes

### `AskSwapModal` (`frontend/src/pages/SwapsPage.tsx:207`)

Radio buttons (`mode: "open" | "soldier"`) become independent controls: a
checkbox "post to open marketplace" plus the existing target-soldier
picker, either or both usable together. Submit always calls one endpoint
with both `target_soldier_ids` (possibly empty) and `open_to_marketplace`.

### "Mine" tab (`renderMySwapCard`, `SwapsPage.tsx:487`)

One card per `SwapRequest` (already true at the data level now — no
grouping logic needed in the frontend, since the backend no longer fans
out). The card body changes from a flat status view to a collapsible
"parties" section listing each `candidate`: soldier name, source badge
(invited vs. marketplace), status (pending / declined / accepted →
manager-approval progress via the existing `SwapManagerApproval` rendering,
reused per-candidate instead of once for the whole card). The requester's
own cancel/approve/reject actions stay at the card level (they're
parent-scoped); a per-candidate "remove this candidate" action is not
needed for v1 — declining is soldier-initiated, not requester-initiated.

### "Board"/"Incoming" tabs

Unaffected in shape (`renderBoardCard`, `renderIncomingCard` already render
one request at a time from the requester's perspective) — claiming still
works the same from the claimant's point of view; they just don't see the
other candidates (only the requester and managers see the full party list).

### `ApprovalsPage` swap tab

Currently one row per pending-approval `SwapRequest` (already collapsed to
one live row per duty today, since only the claimed row ever reached
`pending_approval`). Now a request can have **multiple** candidates
simultaneously mid-approval — the row expands to show one
approval-progress block per live candidate (reusing the existing
`DirectCommanderApproval`/manager-approval rendering, once per candidate),
so a commander approving soldier B's candidacy doesn't have to guess
whether soldier A's parallel candidacy already won.

## Out of scope

- `take_free` behavior/UX is unchanged — only its internal row shape adapts.
- No change to hierarchy-level restrictions, reserve-cap checks, or
  eligibility checks (`check_soldier_for_assignment`) — those still gate
  candidate creation exactly as they gate today's fan-out rows.
- No change to the Telegram bot's swap-approval action-token flow beyond
  passing through the new `candidate_id` parameter where it already passes
  `side` — detailed wiring is a planning-time concern, not a design
  decision.
