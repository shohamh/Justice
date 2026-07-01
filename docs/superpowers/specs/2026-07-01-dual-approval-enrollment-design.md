# Design: Dual-Approval Enrollment + Bug Fixes

**Date:** 2026-07-01  
**Status:** Approved

## Overview

Two parallel tracks:

1. **Dual-approval enrollment** — soldier enters the system only after both commander and an eligible duty manager approve. Commander approves basic registration; duty managers approve exemption requests linked to the enrollment.
2. **Bug fixes** — exemption type dropdown in registration, edit soldier in hierarchy (single click), dismiss-from-duty permission guard, ALAL alert shown only to relevant soldiers.

---

## Part 1: Dual-Approval Enrollment

### Data Model

**`ExemptionRequest` — new column:**
```sql
enrollment_request_id UUID NULL REFERENCES soldier_enrollment_requests(id)
```
Exemption requests created during registration are linked to the enrollment. Existing standalone exemption requests keep `NULL`.

**`Soldier` — new column:**
```sql
is_career BOOLEAN NOT NULL DEFAULT FALSE
```
Career soldiers (קבע). Used for ALAL eligibility and alert filtering.

**`SoldierEnrollmentRequest` — no new columns**, but the `status` field gains a new value:
- `pending` → waiting for commander
- `commander_approved` → commander approved, waiting for exemptions to resolve
- `approved` → soldier activated (moved to requested node)
- `rejected` → commander rejected

**System setting (new):**
```
enrollment.min_dm_level_rank  (int, default = rank of "מרכז" level type)
```
DMs must have scope over a node whose level rank ≥ this value to see and approve enrollment-linked exemption requests.

### Backend: `services/registration.py`

Changes:
- Accept `is_career: bool` in the registration payload; store it on the `Soldier`.
- Create each `ExemptionRequest` with `enrollment_request_id` set to the new `SoldierEnrollmentRequest.id`.
- After flushing, send notifications to:
  - Commander of the requested node (existing pattern).
  - All duty managers whose scope covers the requested node **and** whose scope root is at level rank ≥ `enrollment.min_dm_level_rank`.

### Backend: `services/enrollment.py`

**`approve_enrollment`** — changed behavior:
1. Set `req.status = "commander_approved"` (not `"approved"`).
2. Set `req.decided_by`, `req.decided_at`, `req.decision_note`.
3. Call `try_activate(session, req.id)`.

**New function `try_activate(session, enrollment_request_id)`:**
```python
def try_activate(session, enrollment_request_id):
    req = session.get(SoldierEnrollmentRequest, enrollment_request_id)
    if req is None or req.status != "commander_approved":
        return
    pending = session.execute(
        select(ExemptionRequest).where(
            ExemptionRequest.enrollment_request_id == enrollment_request_id,
            ExemptionRequest.status == "pending",
        )
    ).scalars().all()
    if pending:
        return
    soldier = session.get(Soldier, req.soldier_id)
    soldier.hierarchy_node_id = req.requested_node_id
    req.status = "approved"
    session.flush()
    # send notification to soldier: enrollment approved, welcome
    write_audit(...)
```

### Backend: `services/exemption_requests.py`

**`approve_request` and `reject_request`** — after setting status and flushing, add:
```python
if req.enrollment_request_id:
    from app.services.enrollment import try_activate
    try_activate(session, req.enrollment_request_id)
```

### Backend: New/Modified Routes

**`GET /auth/exemption-types`** (public, no auth):
- Returns `[{id, name, description}]`.
- Same DB query as `/duty-config/exemption-types`.
- Placed in `routes/auth.py` or a new `routes/public.py`.

**`PATCH /enrollment-requests/{id}`** (commander edits before approving):
- Editable fields: `full_name`, `personal_number`, `requested_node_id`, `phone`, `email`, `rank`, `is_officer`, `is_career`, `enlistment_date`, `mandatory_end_date`, `discharge_date`, `last_mitvahim_date`, `last_alal_date`, plus `personal_constraints` (add/remove).
- Auth: same `ENROLLMENT_APPROVE` action check.
- Applies edits directly to the `Soldier` record.

**`PATCH /exemption-requests/{id}`** (DM edits before approving):
- Editable fields: `exemption_type_id`, `start_date`, `end_date`, `reason`.
- Auth: same scope check as approve/reject.
- Only allowed while `status == "pending"`.

**`GET /exemption-requests/pending`** — adds filtering:
- For exemption requests where `enrollment_request_id IS NOT NULL`, only include them for DMs whose scope root level rank ≥ `enrollment.min_dm_level_rank`.
- Regular (non-enrollment) exemptions continue to be visible as before.

**`GET /enrollment-requests/pending`** — add full soldier data to response:
- Include all soldier profile fields so the commander approval UI can pre-populate the edit form.

### Notifications

| Event | Recipients |
|---|---|
| Soldier registers (with exemptions) | Commander of requested node + eligible DMs |
| Soldier registers (no exemptions) | Commander of requested node only |
| Commander approves (exemptions pending) | No new notification (DMs already notified at registration) |
| Commander approves (no exemptions) | Soldier: "enrollment approved" |
| All exemptions resolved + commander already approved | Soldier: "enrollment approved, you can now access the system" |
| Commander rejects | Soldier: "enrollment rejected" + decision_note |
| DM approves/rejects exemption | Soldier: existing exemption_approved/rejected notification |

---

## Part 2: Bug Fixes

### Fix 1: Exemption type Combobox in RegisterPage

**File:** `frontend/src/pages/RegisterPage.tsx`  
**Change:** Step 3 replaces the raw UUID `<input>` with `<Combobox>` populated from `GET /auth/exemption-types`. Fetch once on entering step 3 (or on component mount after invite code is validated). If fetch fails, fall back to a text input with a helper message.

### Fix 2: Edit soldier in HierarchyTree — single click

**File:** `frontend/src/components/HierarchyTree.tsx`  
**Change:** The button text `t("team.view_profile")` is misleading; rename the i18n key usage to `t("team.edit")` on this button. Verify that `UnifiedSoldierModal` with `initialEditing={true}` actually opens in edit mode on the "details" tab — investigate and fix if not (likely the tab starts on "details" but the edit form is not active by default in that tab).

### Fix 3: Dismiss-from-duty shown to all users

**File:** `frontend/src/components/ShiftDetailPanel.tsx`  
**Change:** Wrap both dismiss buttons (primary soldiers, line ~228; reserve soldiers, line ~347) in:
```tsx
{(user?.role === "admin" || user?.is_duty_manager) && (
  <button ...>{t("dismiss_action")}</button>
)}
```

### Fix 4: ALAL alert for irrelevant soldiers

**Files:**
- `backend/app/db/models.py` — add `is_career` column to `Soldier`
- `backend/app/routes/me.py` — expose `is_career` in `/me` response
- `frontend/src/api/auth.ts` — add `is_career?: boolean` to `Me` type
- `frontend/src/pages/RegisterPage.tsx` — send `is_career` in registration payload
- `frontend/src/components/dashboard/AlertBanners.tsx` — wrap alal alert:
  ```tsx
  const shouldShowAlal = user?.is_officer || user?.is_career;
  const alalMsg = shouldShowAlal ? alertMessage(lastAlalDate, ...) : null;
  ```

---

## Alembic Migration

Single migration covering:
1. `ALTER TABLE exemption_requests ADD COLUMN enrollment_request_id UUID REFERENCES soldier_enrollment_requests(id)`
2. `ALTER TABLE soldiers ADD COLUMN is_career BOOLEAN NOT NULL DEFAULT FALSE`

---

## Unchanged

- `services/exemption_requests.py` submit/list/count logic — unchanged
- `GET /exemption-requests/pending` base logic — only add the level-rank filter layer
- File upload/download for exemption requests — unchanged
- Existing notifications for exemption approve/reject — unchanged, just add `try_activate` call alongside
