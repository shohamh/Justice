# Extend an open swap request with more invites / marketplace — design spec

## Goal

Today, inviting specific people and/or publishing to the marketplace only
happens once, at `SwapRequest` creation time (`create_request()`,
`backend/app/services/swaps.py:61`). Once a request is open, the requester
has no way to reach additional people who weren't invited yet, or to push to
the marketplace if they didn't opt into it at creation time. This spec adds
that: a requester can extend an already-open `SwapRequest` with more invited
targets and/or publish it to the marketplace later, without creating a
second request for the same duty (the existing partial unique index on
`(requesting_soldier_id, duty_assignment_id) WHERE status = 'open'` already
forbids that, and this feature works within it rather than around it).

Re-inviting someone who already has a `SwapCandidate` row, or re-publishing
an already-published request, must be prevented — not silently, but visibly:
the UI shows those options greyed out with an explanation, rather than
letting the requester attempt and fail.

## Data model

No schema changes. This feature is pure service/route/UI work on top of the
existing `SwapRequest`/`SwapCandidate` shape (see
`2026-07-26-unified-swap-requests-design.md`):

- `SwapRequest.open_to_marketplace: bool` — the flag being set on an
  existing row instead of only at creation.
- `SwapCandidate` unique constraint `(swap_request_id, soldier_id)` — the
  backstop that guarantees a soldier can't end up with two candidate rows on
  the same request; the new "add targets" path relies on this exactly like
  creation does.
- Setting `swaps.max_specific_targets` (existing system setting, currently
  read only at creation via `_max_specific_targets()`,
  `backend/app/services/swaps.py:57`) now also governs the running total of
  invited candidates on a request across its whole lifetime — invites added
  later count against the same cap as invites made at creation, not a
  separate per-call allowance.

## Service-layer behavior (`backend/app/services/swaps.py`)

Two new functions alongside `create_request()`:

- **`add_targets(swap_request_id, soldier_id, target_ids: list[int]) -> SwapRequest`**
  - Loads the `SwapRequest`, 404s if missing, 403s if `soldier_id` isn't the
    requester, `SwapError("not_open")` (409) if `status != "open"`.
  - Recomputes the current candidate count for this request and checks
    `current_count + len(target_ids) <= max_specific_targets` (reusing
    `_max_specific_targets()`); over-cap → `SwapError("target_limit_reached")`.
  - For each target id already present as a `SwapCandidate` on this request
    → `SwapError("already_invited")` naming the soldier, so the caller gets
    a clear reason rather than a generic constraint violation. This check
    happens before insert; the existing DB unique constraint remains the
    final backstop against a race between two concurrent calls.
  - For each remaining target, calls the existing
    `_add_invited_candidate()` (`swaps.py:145`) unchanged — same self-invite
    guard, `check_soldier_for_assignment` eligibility check, hierarchy-level
    restriction, and notification send as at creation time.
  - Returns the updated `SwapRequest` (with its refreshed `candidates` list)
    for the route to serialize the same way `create_request` does.

- **`publish_to_marketplace(swap_request_id, soldier_id) -> SwapRequest`**
  - Same load/ownership/`status == "open"` checks as `add_targets`.
  - `SwapError("already_on_marketplace")` (409) if `open_to_marketplace` is
    already `True`.
  - Otherwise sets `open_to_marketplace = True` and returns the updated
    request. No candidate rows are created by this call — the marketplace
    is a passive "anyone eligible can claim" flag, exactly as it behaves at
    creation time (claims still go through `claim_request()`, unaffected by
    this spec).

Both functions operate only on requests owned by the caller (enforced
server-side, not just hidden in the UI) and both re-validate everything
they check, since the frontend's greyed-out state is a UX convenience, not
the source of truth.

## API changes

- `POST /me/swaps/{id}/targets` — body `{ target_ids: number[] }`, calls
  `add_targets`, returns the updated `SwapRequest` (same shape as
  `POST /me/swaps`'s response). 409 with the specific `SwapError` code
  (`not_open` / `target_limit_reached` / `already_invited`) on failure.
- `POST /me/swaps/{id}/publish` — no body, calls `publish_to_marketplace`,
  returns the updated `SwapRequest`. 409 (`not_open` /
  `already_on_marketplace`) on failure.

Both routes live in `backend/app/routes/swaps.py` next to the existing
`POST /me/swaps` (`swaps.py:460`), same auth dependency (current soldier),
same error-translation pattern already used for `SwapError` today.

## Frontend changes

### `AskSwapModal` (`frontend/src/components/AskSwapModal.tsx`)

Gains an edit mode: when opened for an existing open `SwapRequest` (as
opposed to creating a new one), it receives that request's id,
`open_to_marketplace`, and current `candidates` list as props.

- **Eligible-targets checklist**: unchanged data source
  (`listEligibleTargets`), but every person who already has a
  `SwapCandidate` row on this request (any status — pending, declined,
  accepted, applied, or cancelled; matches the DB unique constraint, so
  "already has a row" is the one rule, not a subset of statuses) renders
  disabled with a trailing note: "כבר הוזמן" ("already invited"). They stay
  visible rather than being filtered out, so the requester can see at a
  glance who they've already reached.
- **Cap enforcement in the UI**: once `existing candidate count + currently
  checked new people == max_specific_targets`, remaining not-yet-invited,
  not-yet-checked people in the list also grey out with "הגעת למגבלת
  ההזמנות" ("invite limit reached"), mirroring the creation-time cap
  behavior.
- **Marketplace checkbox**: if `open_to_marketplace` is already `true`,
  render it checked and disabled with "כבר פורסם בשוק ההחלפות" ("already
  published to marketplace"). Otherwise behaves as today (an open
  checkbox the requester can opt into).
- **Submit**: in edit mode, only calls the endpoints for what actually
  changed — `addSwapTargets` if any new people were checked,
  `publishSwapToMarketplace` if the marketplace checkbox was newly checked.
  If neither changed, submit is disabled (nothing to do).

### "Mine" tab (`renderMySwapCard`, `frontend/src/pages/SwapsPage.tsx:325`)

Open requests (`status === "open"`) gain a "נהל" / "Manage" button that
opens `AskSwapModal` in edit mode for that request. Non-open requests don't
show it — there's nothing left to extend once a request has resolved.

### `api/swaps.ts`

Add `addSwapTargets(swapId: string, targetIds: number[]): Promise<SwapRequest>`
and `publishSwapToMarketplace(swapId: string): Promise<SwapRequest>`,
mirroring the existing `createSwap` wrapper's error handling.

### i18n

New keys in `frontend/src/i18n/he.json` for: "Manage" button label, "already
invited" note, "invite limit reached" note, "already published to
marketplace" note, and any new toast/error text for the 409 cases above.

## Error handling & edge cases

- Race between two browser tabs adding the same person: the pre-check in
  `add_targets` catches the common case; the DB unique constraint catches
  the rest, surfaced as a generic "already invited, please refresh" toast
  rather than a raw constraint error.
- Request transitions out of `open` (e.g. a candidate finishes approval)
  while the modal is open: submit re-validates server-side and returns
  `not_open`; the frontend shows a toast and closes the modal, prompting a
  refresh, rather than silently failing.
- Self-invite and hierarchy-eligibility rules are not duplicated — both new
  targets and the existing creation path share `_add_invited_candidate()`,
  so any future change to eligibility rules applies to both automatically.

## Testing

- Backend unit tests (alongside existing `swaps.py` service tests):
  `add_targets` — cap enforcement (including cap counting pre-existing
  candidates), duplicate-target rejection, non-owner rejection, non-open
  rejection, and the happy path (reuses `_add_invited_candidate` behavior
  correctly). `publish_to_marketplace` — already-published rejection,
  non-owner rejection, non-open rejection, happy path.
- Backend integration tests for the two new routes (auth, 404, 409 cases,
  200 happy path) in `test_swaps_api.py` or equivalent.
- Frontend: extend `AskSwapModal` tests for edit mode — greyed-out
  already-invited rows with correct label, greyed marketplace checkbox with
  correct label when already published, cap-reached greying once the
  running total hits the limit, and submit calling only the endpoints for
  what changed.

## Out of scope

- No way to *unpublish* from the marketplace or *remove* an already-invited
  candidate via this feature — those are separate concerns (cancellation of
  individual candidates already has its own flow via manager/soldier
  reject, unaffected by this spec).
- No change to `max_specific_targets` itself or to how it's configured in
  system settings — it's read the same way, just enforced across more call
  sites (creation + add-targets) against the same running total.
- No change to marketplace claim (`claim_request`) or approval-chain
  behavior — this spec only adds ways to *reach* more candidates, not new
  ways to resolve a request.
