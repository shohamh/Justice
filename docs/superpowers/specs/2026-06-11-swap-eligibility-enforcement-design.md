# Swap Eligibility & Availability Enforcement

**Date:** 2026-06-11
**Branch:** feat/duty-type-operational-fields

## Problem

Swap write operations (`create_request`, `claim_request`, `cover_offer`, `take_free`) currently perform no eligibility or availability checks on the covering soldier. A soldier can accept or be targeted for a swap even if they are exempt from the duty type, ineligible due to expired qualifications, have an approved personal constraint on those dates, or already have another duty scheduled.

The existing `GET /swaps/eligible-duties` endpoint provides a preview check but is not enforced at write time and does not check for scheduling conflicts.

## Goals

1. Hard-block ineligible/unavailable soldiers at the backend on all four swap write operations.
2. Provide a pre-flight endpoint so the frontend can grey out confirm buttons before the user submits.
3. Eliminate the inline duplication between `routes/swaps_eligibility.py` and the new service logic.

## Four Eligibility Checks (in order)

1. **Duty type eligibility** — mitvahim/alal recency, gender, rank, service type, bahad1, officers/enlisted restrictions (via existing `_is_eligible()` in `services/eligibility.py`).
2. **Active exemption** — soldier has a `SoldierExemption` whose date range overlaps the duty and covers this duty type (or is a global exemption).
3. **Approved personal constraint** — soldier has a `PersonalConstraint` with `status=approved` whose date range overlaps the duty dates.
4. **Scheduling conflict** — soldier already has a published `DutyAssignment` whose date range overlaps the duty dates (excluding the assignment being swapped itself).

First failing check short-circuits and returns a Hebrew reason string.

## Architecture — Option A (chosen)

### `services/eligibility.py` — new function

```python
def check_soldier_for_assignment(
    session: Session,
    soldier_id: uuid.UUID,
    assignment_id: uuid.UUID,
    *,
    exclude_assignment_id: uuid.UUID | None = None,
) -> tuple[bool, str | None]:
    """Return (True, None) if eligible+available, or (False, Hebrew reason) on first failure."""
```

This replaces the inline logic in `routes/swaps_eligibility.py` (refactored to call this helper) and is the single source of truth for all eligibility enforcement.

### `services/swaps.py` — guard calls

Each write operation calls `check_soldier_for_assignment` before any mutations:

| Operation | Soldier checked | Assignment |
|---|---|---|
| `create_request(target_soldier_id=X)` | target X | requester's `duty_assignment_id` |
| `claim_request` | `covering_soldier_id` | request's assignment |
| `cover_offer` | `covering_soldier_id` | request's assignment |
| `take_free` | `covering_soldier_id` | `assignment_id` arg |

On failure: `raise SwapError(f"cover_not_eligible:{reason}")`

### `routes/swaps.py` — new pre-flight endpoint

```
GET /swaps/{assignment_id}/cover-eligibility
→ { eligible: bool, reason: str | null }
```

Checks the authenticated user (`current_user.id`) against the assignment. Returns 200 in both eligible and ineligible cases; 404 if assignment not found.

### `routes/swaps_eligibility.py` — refactor

Replace inline per-assignment logic with a call to `check_soldier_for_assignment`. This also adds the scheduling-conflict check to the existing `eligible-duties` endpoint as a side-effect improvement.

## Frontend Changes

### `api/swaps.ts`

```ts
export async function checkCoverEligibility(
  assignmentId: string,
): Promise<{ eligible: boolean; reason: string | null }>;
```

Calls `GET /swaps/{assignmentId}/cover-eligibility`.

### `CoverOfferModal.tsx`

- On mount: call `checkCoverEligibility(swap.duty_assignment_id)`.
- While loading: show a spinner or disable the submit button.
- If ineligible: grey out the submit button (`disabled`, `opacity-50`) and show the Hebrew reason in amber text beneath it (same style as `freeBlocked` message in `OfferSwapModal`).

### `OfferSwapModal.tsx`

- For "take free" mode: call `checkCoverEligibility(targetAssignmentId)` alongside the existing local scheduling-conflict check (`freeBlocked`).
- The "take free" radio is disabled and the reason shown if either check fails.
- "Swap" mode: no extra frontend work — `getEligibleDuties` already greys out rows; the refactored backend now also returns scheduling conflicts via that endpoint.

## Error Handling

- Backend raises `SwapError(f"cover_not_eligible:{reason}")` where `reason` is a Hebrew string.
- Frontend: if the 400 detail starts with `cover_not_eligible:`, extract and display the suffix as the error message.
- Pre-flight endpoint eliminates most cases where the raw backend error is seen.

## What Is Not Changing

- Approval flow (`approve_side`, `reject_request`, `cancel_request`) — no eligibility re-check needed at approval time.
- Commander-side manager approval (`/swaps/pending`) — commanders see the reason in the swap history if a soldier somehow bypassed the UI; they can reject.
- Swap mode eligibility preview in `OfferSwapModal` — already works via `getEligibleDuties`; only refactored to add scheduling-conflict check.
