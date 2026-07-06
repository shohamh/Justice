# Exemption Revocation Reason + Exemption-Type Disable/Bulk-Cancel

Date: 2026-07-06
Status: Approved for planning

## Context

**Bug report:** Canceling an exemption from the soldier edit modal "doesn't work."

**Root cause (confirmed via direct API testing):** the revoke call actually
succeeds — `backend/app/services/exemptions.py::revoke_exemption` correctly
truncates `end_date` to today. But:

- The frontend gives zero feedback: `ExemptionsPanel.tsx::onRevoke` uses a
  bare `window.confirm()`, no success/error message.
- The "active" list filter (`ex.end_date >= today`, inclusive) is consistent
  with how the backend itself defines "currently in effect"
  (`scoring.py::globally_exempted_soldier_ids` uses the same inclusive
  bound) — so a just-revoked exemption correctly stays visible in the active
  section until tomorrow, with its revoke button still sitting there,
  unchanged. This reads as "nothing happened."

Fixing this properly means replacing the silent `confirm()` with an explicit
modal that requires a reason and gives clear before/after feedback — which
is also exactly what the user separately asked for: a required reason on
cancellation, recorded on the soldier's duty history, visible only to the
soldier, commanders in scope, and duty managers with scope over their
hierarchy node.

**Related bug, folded into this spec because it reuses the same revoke
pipeline:** deleting an exemption type "doesn't work." Root cause: there is
no delete button anywhere in the frontend (`ExemptionTypeViewModal.tsx` has
none) — the backend `DELETE /exemption-types/{id}` endpoint exists and
correctly 409s when the type is in use, but nothing calls it. `DutyType`
already has a proven "disable instead of delete when in use" pattern
(`DutyType.active`, `DutyConfigPage.tsx`'s delete-with-usage-check modal) —
`ExemptionType` has no equivalent flag.

## Part 1: Exemption cancellation with required reason

### Data model

Add three nullable columns to `SoldierExemption`
(`backend/app/db/models.py`):

- `revoked_at: Mapped[datetime | None]`
- `revoked_by: Mapped[uuid.UUID | None]` (FK to `soldiers.id`, `ON DELETE SET NULL`)
- `revoke_reason: Mapped[str | None]` (text)

These three are the single source of truth for "was this exemption actively
cancelled" — set together, always, whenever `revoke_exemption` runs (except
the already-expired no-op case, see below).

### `revoke_exemption` behavior changes

`backend/app/services/exemptions.py::revoke_exemption` gains a required
`reason: str` parameter and `actor_id: uuid.UUID` (who revoked it, for
`revoked_by`). New behavior per case:

- **Already expired** (`end_date < today`): unchanged — true no-op, no
  fields touched, no notification sent. (The UI will no longer offer this
  action for expired exemptions — see UI section.)
- **Already started** (`start_date <= today`): `end_date` is still
  truncated to `today` (unchanged — preserves "still in effect through
  today" scoring semantics). Additionally sets `revoked_at = now()`,
  `revoked_by = actor_id`, `revoke_reason = reason`.
- **Not yet started** (`start_date > today`): no longer hard-deleted. The
  row is kept with its original `start_date`/`end_date` untouched (historical
  accuracy — "this was granted for X→Y but revoked before it took effect").
  Sets `revoked_at`/`revoked_by`/`revoke_reason` as above. Because
  `end_date` isn't touched here, this case relies entirely on the new
  `revoked_at IS NOT NULL` guard (below) to be excluded from "currently in
  effect" everywhere.

### "Currently in effect" guard — one added condition, four call sites

Every place that currently checks "is this exemption in effect right now"
gets `revoked_at IS NULL` added to its existing date-range condition:

1. `backend/app/services/potential.py::compute_potential`'s active-exemption
   scan.
2. `backend/app/services/scoring.py::globally_exempted_soldier_ids`.
3. `backend/app/services/scoring.py::_active_exemptions_by_soldier`.
4. `backend/app/services/duty_history.py`'s active-exemption timeline
   builder.
5. Frontend `ExemptionsPanel.tsx`'s `activeItems`/`expiredItems` split: an
   item with `revoked_at` set is never "active," regardless of `end_date`.

This directly fixes the reported bug: a revoked exemption disappears from
"active" immediately, not tomorrow.

### API surface

- `DELETE /soldiers/{soldier_id}/exemptions/{exemption_id}` gains a required
  JSON body `{"reason": string}` (previously bodyless).
- `revoke_reason` and `revoked_by` (resolved to a name) are included in the
  `Exemption` response **only** when `can_see_private(session, viewer,
  soldier)` is true (existing function, unchanged) — mirrors how grant
  `reason` visibility already works elsewhere in this codebase. Other
  viewers get `null` for both fields, same pattern as existing
  exemption-name redaction.

### Frontend UI

- New `RevokeExemptionModal` (or extend `ExemptionsPanel.tsx` inline)
  replacing the `window.confirm()` call: opens on clicking "בטל", shows the
  exemption's type/dates, a required reason textarea, cancel/confirm
  buttons. On confirm: calls the updated `revokeExemption(soldierId,
  exemptionId, reason)`, shows a success toast/inline message, refreshes the
  list — the exemption now visibly leaves the active section (per the
  filter fix above), giving the clear feedback the original bug lacked.
- Already-expired exemptions (in the "past" section) lose their revoke
  button entirely — the action is a permanent no-op for them, so offering it
  (with a now-mandatory reason prompt) would be worse than today's silent
  no-op.

### Duty history

The existing exemption entry in `duty_history.py`'s timeline (per soldier)
is annotated in place — not a new separate event — with the revocation
fact: who revoked it, when, and the reason. Visible under the same
`can_see_private` gate as the reason field itself (soldier + commanders/DMs
in scope; hidden from others, same as today's exemption-name redaction for
out-of-scope viewers).

### Notifications

On successful revoke (not on the expired no-op), using the existing
`create_notification`/cascade infrastructure in
`backend/app/services/notifications.py`:

- The soldier is notified directly (new `NotificationType.exemption_revoked`),
  including the reason.
- Commanders with scope over the soldier's node are notified via the
  existing `cascade_to_commanders`-style mechanism.
- Duty managers with scope over the soldier's node are notified via the
  existing duty-manager cascade mechanism used elsewhere for
  scope-based routing (mirrors how enrollment-request notifications already
  reach both audiences separately).

## Part 2: Exemption-type delete/disable + bulk-cancel

### Data model

Add `ExemptionType.active: Mapped[bool]` (`server_default=text("true")`,
`default=True`) — identical shape to `DutyType.active`.

### Delete/disable flow (mirrors `DutyType`'s existing pattern)

Frontend gains a delete action in `ExemptionTypeViewModal.tsx` (currently
has none), following `DutyConfigPage.tsx`'s established
`DutyType`-delete-with-usage-check flow:

1. Click delete → check usage (any `SoldierExemption` row referencing this
   type, same query `delete_exemption_type` already runs).
2. **Not in use:** hard-delete proceeds exactly as today's backend logic
   already supports (`DutyConfigError("exemption_type_in_use")` simply
   won't fire) — no behavior change needed here, just wiring up the missing
   UI button.
3. **In use:** hard-delete is blocked (as today); instead offer "disable,"
   which opens the same required-reason modal from Part 1 (one shared
   reason for this action, not per-soldier). On confirm:
   - Sets `ExemptionType.active = False`.
   - Finds every soldier with a currently-active (not already revoked, not
     expired) `SoldierExemption` of this type, and revokes each one through
     the *same* `revoke_exemption` function from Part 1, passing the shared
     reason and the acting admin as `revoked_by` — so every affected soldier
     gets the same notification, duty-history annotation, and visibility
     rules as an individual cancellation.
4. Disabled types are excluded from the grant-form's type picker (new
   grants can't reference them) but remain listed (toggle-able back to
   active) in exemption-type management — same as `DutyType.active`, not a
   one-way action.

## Out of scope

- No change to the already-expired no-op semantics for individual
  cancellation — still a true no-op, just no longer reachable via the UI.
- No bulk UI to select *which* soldiers get cancelled when disabling a type
  — it's always "everyone currently holding it," matching the "type no
  longer exists" framing.
- No change to `ExemptionDutyTypeMap`'s existing `ON DELETE CASCADE` — that
  cleanup path is untouched; it only matters for the (now rarer, since
  disable is preferred) hard-delete-when-unused path.
- `ExemptionRequest` (commander self-exemption request flow) usage-checking
  before delete is not added in this pass — flagged by the earlier
  investigation as a possible gap, but no evidence it's part of the reported
  bug; can be a follow-up if it surfaces separately.
