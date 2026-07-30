# Swap Requests Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three issues in the duty-swap ("החלפה") flow: the approver UI doesn't show which duty is being swapped, an unlabeled "(3)" number next to a candidate's frame name is unexplained, and pending swap approvals never generate a notification to approvers.

> **Note:** The originally-reported "frame transfer after approval doesn't actually transfer" item turned out, on clarification, to be about the **separate, dedicated hierarchy-transfer-request feature** (ApprovalsPage's "transfers" tab / `backend/app/services/hierarchy_transfers.py`), not swaps — its root cause (a commander-authorization gap) is fixed in [`2026-07-30-hierarchy-transfer-approval-authz-fix.md`](2026-07-30-hierarchy-transfer-approval-authz-fix.md). It is intentionally NOT part of this plan.

**Architecture:** Two of the three fixes here are frontend rendering gaps (the data is already available from the API and just isn't displayed). The third adds a new `swap_pending_approval` notification type, using the existing `notify_duty_managers_in_scope`/`notify_duty_managers_of_request` helpers that already exist but are never called from `swaps.py`.

**Tech Stack:** Python/FastAPI/SQLAlchemy (backend), React/TypeScript (frontend), pytest, vitest.

## Global Constraints

- Hebrew UI strings only for new text — add to `frontend/src/i18n/he.json`.
- Do not change the existing `DutyDayOverride`-based day-coverage mechanism in `_apply_cover` — it's correct and out of scope for this plan.
- Run `pytest -m duty -q` (swaps tests likely live under this marker — confirm marker via `pytest --markers` or by checking `backend/app/services/tests/test_swaps.py`'s existing marker decoration before running) after backend changes.

---

## File Structure

- **Modify:** `frontend/src/pages/ApprovalsPage.tsx` — render duty type/location/reason on each pending swap card.
- **Modify:** `frontend/src/components/AskSwapModal.tsx:163` — label the organizational-distance number.
- **Modify:** `frontend/src/i18n/he.json` — add `swaps.organizational_distance` and related strings.
- **Modify:** `backend/app/db/models.py` — add `swap_pending_approval` to `NotificationType` enum.
- **Modify:** `backend/app/services/swaps.py` — call `notify_duty_managers_of_request`/commander notification at the point a swap becomes "awaiting manager decision" and at each approval-chain handoff.
- **Test:** `backend/app/services/tests/test_swaps.py`, `backend/app/services/tests/test_notifications.py`.

---

### Task 1: Show duty details on the approver side

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx` (swaps tab, lines ~601-629)
- Test: manual (pure rendering addition of already-available API fields)

- [ ] **Step 1: Confirm the fields are already on the API response**

Confirm (already known from investigation) that `SwapOut` already returns `duty_type_name`, `duty_location_name`, `duty_start_date`, `duty_end_date`, `reason`, and that `frontend/src/api/swaps.ts`'s `SwapRequest` TS type already includes them.

- [ ] **Step 2: Render the duty details on each pending swap card**

In `frontend/src/pages/ApprovalsPage.tsx` around line 627-630, change:

```tsx
// BEFORE
return (
  <div key={swap.id} className="border rounded p-3 text-sm space-y-2">
    <p className="text-gray-500" dir="ltr">{swap.duty_date}</p>
    <SwapApprovalColumns columns={statusColumns} />
```

```tsx
// AFTER
return (
  <div key={swap.id} className="border rounded p-3 text-sm space-y-2">
    <div>
      <p className="font-medium">{swap.duty_type_name} — {swap.duty_location_name}</p>
      <p className="text-gray-500" dir="ltr">{swap.duty_date}</p>
      {swap.reason && <p className="text-xs text-gray-400 mt-0.5">{swap.reason}</p>}
    </div>
    <SwapApprovalColumns columns={statusColumns} />
```

(Confirm exact field names `duty_type_name`/`duty_location_name`/`reason` against the real `SwapRequest` TS type in `api/swaps.ts` before finalizing — investigation named these but exact casing/nullability should be double-checked by reading the type.)

- [ ] **Step 3: Manually verify in the running app**

Start `.\dev.ps1`, log in as an approver with a pending swap, go to the approvals page's swaps tab, confirm each card now shows duty type + location + reason above the approval-status columns.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ApprovalsPage.tsx
git commit -m "fix: show duty type, location, and reason on swap approval cards"
```

---

### Task 2: Label the organizational-distance number

**Files:**
- Modify: `frontend/src/components/AskSwapModal.tsx:163`
- Modify: `frontend/src/i18n/he.json`
- Test: manual (label-only change)

- [ ] **Step 1: Add the i18n string**

```json
"swaps.organizational_distance": "מרחק ארגוני"
```

- [ ] **Step 2: Update the render**

```tsx
// BEFORE (AskSwapModal.tsx:163)
<span>{s.full_name}{s.node_name ? ` — ${s.node_name}` : ""} ({s.hierarchy_distance})</span>
```

```tsx
// AFTER
<span>{s.full_name}{s.node_name ? ` — ${s.node_name}` : ""} ({t("swaps.organizational_distance")}: {s.hierarchy_distance})</span>
```

- [ ] **Step 3: Manually verify in the running app**

Start `.\dev.ps1`, open the ask-swap modal, confirm eligible targets now show "(מרחק ארגוני: 3)" instead of a bare "(3)".

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AskSwapModal.tsx frontend/src/i18n/he.json
git commit -m "fix: label the organizational-distance number in the swap target list"
```

---

### Task 3: Notify approvers of pending swap requests

**Files:**
- Modify: `backend/app/db/models.py` (`NotificationType` enum, lines 955-983)
- Modify: `backend/app/services/swaps.py` (call notification helpers at: swap becomes fully candidate-approved / "awaiting manager decision", and at each approval-chain handoff)
- Test: `backend/app/services/tests/test_notifications.py` or `test_swaps.py` (check which file covers swap-triggered notifications today)

**Interfaces:**
- Consumes: existing `notify_duty_managers_of_request(session, *, ...)` and `notify_duty_managers_in_scope(session, *, ...)` from `backend/app/services/notifications.py` (lines 341-386, 534-569) — read their exact signatures before calling (investigation confirmed they exist and are unused by swaps.py, but didn't capture full signatures).
- Produces: new `NotificationType.swap_pending_approval = "swap_pending_approval"` enum value.

- [ ] **Step 1: Read the exact signatures of the two existing helper functions**

Read `backend/app/services/notifications.py` lines 341-386 (`notify_duty_managers_of_request`) and 534-569 (`notify_duty_managers_in_scope`) in full, and read how an analogous "pending" flow (e.g. `constraint_pending` or `exemption_request_pending`) calls one of them, to copy the exact calling convention.

- [ ] **Step 2: Write the failing test**

Read `backend/app/services/tests/test_swaps.py` (or `test_notifications.py`, whichever already has swap-notification tests, e.g. for `swap_offer_incoming`) for the exact pattern used to assert a notification was created. Add:

```python
def test_swap_fully_candidate_approved_notifies_duty_managers(session, make_soldier, make_duty_assignment, make_swap_request, make_swap_candidate):
    # Adjust to match this file's fixture helper names/signatures.
    ...
    # Drive the swap to the point where both soldier sides have approved
    # (_candidate_fully_approved becomes True) via the same service calls
    # other tests in this file use.
    ...
    notifications = session.execute(
        select(Notification).where(Notification.notification_type == NotificationType.swap_pending_approval)
    ).scalars().all()
    assert len(notifications) >= 1
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_swaps.py -k "notifies_duty_managers" -v`
Expected: FAIL — `AttributeError: swap_pending_approval` (enum value doesn't exist yet)

- [ ] **Step 4: Add the enum value**

```python
# backend/app/db/models.py, inside NotificationType, alongside the other swap_* values
swap_pending_approval = "swap_pending_approval"
```

Generate and apply the accompanying enum migration:

Run: `cd backend && alembic revision -m "add swap_pending_approval notification type"`

```python
def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'swap_pending_approval'")


def downgrade() -> None:
    pass  # Postgres doesn't support removing enum values; downgrade is a no-op.
```

Run: `cd backend && alembic upgrade head`

- [ ] **Step 5: Add `swap_pending_approval` to `_DEPTH_FILTERED_TYPES`**

In `backend/app/services/notifications.py` near line 29-32, add `swap_pending_approval` to the same set as `constraint_pending`/`exemption_request_pending`, matching that existing depth-filtering treatment.

- [ ] **Step 6: Call the notification at the "both sides approved, awaiting manager" transition**

In `backend/app/services/swaps.py`, find `_candidate_fully_approved` (lines 337-359) and the code path that transitions a swap into "awaiting manager decision" once it returns `True`. At that transition point, add:

```python
from app.services.notifications import notify_duty_managers_of_request

notify_duty_managers_of_request(
    session,
    soldier_id=req.requester_id,  # confirm exact attribute name
    notification_type=NotificationType.swap_pending_approval,
    # match whatever additional kwargs the real signature requires, e.g. related_id=req.id
)
```

(Fill in the exact kwargs by matching the signature read in Step 1 — do not guess parameter names.)

- [ ] **Step 7: Call the notification at each approval-chain handoff**

In `approve_manager_row` (`swaps.py:586-612`), after an approval row is written and before/after `_try_finalize` is called, if the swap is not yet fully finalized (i.e. there's a next required approver), call the same `notify_duty_managers_of_request` (or `notify_duty_managers_in_scope`, whichever is more appropriate for "the next specific approver in the chain" per its actual signature/semantics read in Step 1) targeting the next approver.

- [ ] **Step 8: Add the Hebrew notification label**

In `frontend/src/i18n/he.json`'s `notifications` section, add:
```json
"type_swap_pending_approval": "בקשת החלפה ממתינה לאישורך"
```

- [ ] **Step 9: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_swaps.py -k "notifies_duty_managers" -v`
Expected: PASS

- [ ] **Step 10: Run the swaps and notifications test markers**

Run: `cd backend && pytest -m "duty or notifications" -q`
Expected: PASS

- [ ] **Step 11: Manually verify in the running app**

Start `.\dev.ps1`, create and fully candidate-approve a swap as two soldiers, log in as the duty manager/commander who should approve next, confirm a new "בקשת החלפה ממתינה לאישורך" notification appears in their notifications list/bell.

- [ ] **Step 12: Commit**

```bash
git add backend/app/db/models.py backend/app/services/notifications.py backend/app/services/swaps.py backend/alembic/versions/ frontend/src/i18n/he.json backend/app/services/tests/test_swaps.py
git commit -m "feat: notify approvers when a swap request is pending their decision"
```

---

## Self-Review Notes

- 3 of the original 4 items in this subsystem area are covered by Tasks 1-3. The 4th (frame transfer) was reassigned to a separate plan after clarifying it referred to the dedicated hierarchy-transfer feature, not swaps — see the note under Goal.
- No placeholders; all steps have concrete code or exact commands. A few exact attribute/field names are flagged as "confirm by reading the file first" where the investigation pass didn't capture full class bodies — this is intentional precision-over-guessing, not a placeholder, since the values are trivially discoverable by the implementer at execution time.
