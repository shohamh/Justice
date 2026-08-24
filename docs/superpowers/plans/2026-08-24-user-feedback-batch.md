# User Feedback Batch: 13 Items Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address 13 user-reported issues spanning approvals UX, profile fields, duty locations, hierarchy transfers, notification preferences, range eligibility, and public soldier profiles.

**Architecture:** Multi-stream plan organized by subsystem. Each stream is independently shippable. Streams A (approvals), B (profile), C (locations/shift modal), D (transfers/notifications), E (ranges/public profile) can run in parallel.

**Tech Stack:** FastAPI + SQLAlchemy + PostgreSQL (backend), React + TypeScript + Tailwind + TanStack Query (frontend), openpyxl (Excel), Alembic (migrations).

## Global Constraints

- All backend changes require tests; frontend changes require typecheck + lint + tests
- Migrations follow convention: `op.add_column` / `op.drop_column` with timestamp-slug revision IDs
- Hebrew i18n keys go in `frontend/src/i18n/he.json`
- Auth roles: `soldier`, `commander`, `duty_manager`, `admin`; hierarchy levels: `corps > division > unit > department > branch > group > team`
- Two-step approval flow: step 1 = commander (`pending_commander`), step 2 = duty manager (`pending_duty_manager`)
- `end_date` is EXCLUSIVE on all duty/range date ranges
- SQLAlchemy JSONB persists Python `None` as JSON value `null` (not SQL NULL) — always use `sqlalchemy.null()` for JSONB "clear" writes

---

## Stream A: Approvals & Permissions (Items 1, 8, 9)

### Investigation Findings

**Item 1 (no success feedback):** `UnifiedSoldierModal.tsx:171-195` — after creating a transfer request, only `setEditing(false); onRefresh()`. No modal. Transfer requests ARE excluded from the ApprovalsPage "waiting" tab (they have their own tab at lines 930-970).

**Item 8 (double-approve bug):** `constraints.py:355-382` — sole gate is `authorize(CONSTRAINT_APPROVE)` which is in BOTH `_COMMANDER_ACTIONS` AND `_DM_ACTIONS`. Service `approve_constraint()` dispatches by current status only — no identity check that the step-2 actor is a duty manager. `_can_approve_constraint` (lines 128-137) same issue. Frontend `ApprovalsPage.tsx:566-604` shows enabled Approve button for stage 2/2 to any scoped commander.

**Item 9 (nearest approver):** Rank field updates use `rank_advancement` authority system. The pending-for-others view shows "ממתין לאישור מוסמך להזנת דרגות" without naming the person. Need to resolve the nearest-upward authorized rank editor.

---

### Task A1: Two-step approval — block commanders from approving duty-manager step

**Files:**
- Modify: `backend/app/services/constraints.py` — `approve_constraint()` and `_approve_duty_manager_step()`
- Modify: `backend/app/routes/constraints.py` — `POST /{id}/approve` and `POST /{id}/reject`
- Modify: `backend/app/services/constraints.py` — `_can_approve_constraint()`
- Test: `backend/tests/integration/test_constraints_api.py` or new file

**Interfaces:**
- Produces: `_is_duty_manager(session, user, target_node_id) -> bool` — checks `DutyManagerScope` or `role == "duty_manager"` or `role == "admin"`

- [ ] **Step 1: Write failing test**

```python
def test_commander_cannot_approve_duty_manager_step(admin_session, client):
    # Create commander scoped to node, soldier under node, constraint in pending_duty_manager state
    # POST approve → should return 403
```

- [ ] **Step 2: Implement check in service**

In `approve_constraint()`, when `status == "pending_duty_manager"`, verify the caller is a duty manager or admin before proceeding. Return `SoldierError("dm_approval_required")` otherwise.

- [ ] **Step 3: Same check in `_can_approve_constraint`** so the frontend disables the button.

- [ ] **Step 4: Run tests, commit**

---

### Task A2: Success modal after two-step submission on people page

**Files:**
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx` — `handleSave()` lines 171-195
- Create or reuse: success modal component

- [ ] **Step 1:** After `createTransferRequest(...)` succeeds, show a success modal: "הבקשה נשלחה בהצלחה וממתינה לאישור" with a link to the approvals page.

- [ ] **Step 2:** Same for `CommanderExemptionGrantForm.tsx` after `escalateCommanderExemption(...)`.

- [ ] **Step 3:** Ensure transfer requests appear in the ApprovalsPage "waiting" tab (currently they only have their own tab — add them to `waitingCount` and the waiting list).

- [ ] **Step 4:** Run frontend tests, commit.

---

### Task A3: Show nearest authorized approver for rank updates

**Files:**
- Modify: `backend/app/routes/soldiers.py` — pending field-updates endpoint (lines 418-491)
- Modify: `frontend/src/pages/ApprovalsPage.tsx` — waiting cards for field updates

- [ ] **Step 1:** Backend: for each pending rank field-update, resolve the nearest-upward soldier with `rank_advancement` edit authority. Add `pending_approver_name` and `pending_approver_id` to the response.

- [ ] **Step 2:** Frontend: render the approver name as a link on the waiting card.

- [ ] **Step 3:** Run tests, commit.

---

## Stream B: Profile Enhancements (Items 2, 3, 10)

### Task B1: Duty history — show who assigned and when

**Files:**
- Modify: `backend/app/services/duty_history.py` — add `assigned_by_name` to assignment event metadata
- Modify: `backend/app/routes/soldiers.py` — `TimelineEventOut` add optional `assigned_by_name`
- Modify: `frontend/src/components/DutyHistoryPanel.tsx` — EventCard renders assigned_by + created_at for assignment events
- Modify: `frontend/src/api/dutyHistory.ts` — TimelineEvent interface

- [ ] **Step 1: Backend** — In the assignment/call_up/dismissal event builders, resolve `DutyAssignment.created_by` → `Soldier.full_name` and add `assigned_by_name` to metadata. Handle null (hakpaza/import legacy rows).

- [ ] **Step 2: Backend** — Add `assigned_by_name: str | None = None` to `TimelineEventOut`.

- [ ] **Step 3: Frontend** — In `EventCard`, for assignment-type events render "שובץ על ידי {assigned_by_name} בתאריך {created_at}".

- [ ] **Step 4:** Fix hakpaza.py and import_excel.py to set `created_by` on assignment creation.

- [ ] **Step 5:** Run tests, commit.

---

### Task B2: Food type + food constraints fields

**Files:**
- Create: Alembic migration (add `food_type` enum column + `food_constraints` text column to `soldiers`)
- Modify: `backend/app/db/models.py` — Soldier model
- Modify: `backend/app/routes/auth.py` — `RegisterRequest` + registration handler
- Modify: `backend/app/services/registration.py` — `register()` signature + Soldier construction
- Modify: `backend/app/routes/soldiers.py` — `SoldierOut`, `UpdateProfileRequest`, `_out()` serializer
- Modify: `backend/app/services/soldiers.py` — `PROFILE_FIELDS`, `update_soldier_profile`
- Modify: `frontend/src/pages/ProfilePage.tsx` — display + field-update controls
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx` — admin edit form
- Modify: `frontend/src/pages/RegisterPage.tsx` — registration step 2
- Modify: `frontend/src/api/auth.ts` — RegisterRequest payload
- Modify: `frontend/src/api/soldiers.ts` — SoldierDTO, UpdateProfilePayload
- Modify: `frontend/src/i18n/he.json` — labels

- [ ] **Step 1: Migration** — `op.add_column("soldiers", sa.Column("food_type", sa.Enum("regular","vegetarian","vegan","gluten_free","kosher_le_mehadrin", name="food_type"), nullable=True))` + `op.add_column("soldiers", sa.Column("food_constraints", sa.Text, nullable=True))`

- [ ] **Step 2: Backend model + registration + profile update** — add fields to Soldier model, register(), SoldierOut, UpdateProfileRequest, PROFILE_FIELDS.

- [ ] **Step 3: Frontend profile + registration** — add select dropdown (food_type) and text input (food_constraints) with question-mark tooltip (pattern from AlgorithmInlinePanel.tsx:92-98). Add to registration step 2.

- [ ] **Step 4:** Run tests, commit.

---

### Task B3: Unify service details with pending-edit fields

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx` — merge read-only display (lines 282-329) with editable controls (lines 326-449)
- Modify: `backend/app/services/soldiers.py` — `submit_field_update` add equality check
- Modify: `backend/app/routes/soldiers.py` — field-update route error handling

- [ ] **Step 1: Backend equality check** — In `submit_field_update`, compare normalized `new_value` against `_get_current_value(soldier, field_name)` using a per-field normalization helper (rank: parse JSON `{rank, rank_track}` and compare both; license: parse `{has_license, expiry_date}`; dates: ISO string comparison; strings: strip). Raise `SoldierError("same_value")` if equal.

- [ ] **Step 2: Frontend effective value overlay** — Compute effective current per field by overlaying latest pending `new_value` onto `/me` data. Show only the editable control (remove duplicate read-only display). Disable submit when selected == effective current.

- [ ] **Step 3:** Remove the duplicate read-only section (lines 282-329) since the same data now appears in the editable controls.

- [ ] **Step 4:** Run tests, commit.

---

## Stream C: Duty Locations & Shift Modal UX (Items 5, 6, 7)

### Task C1: Delete/deactivate duty locations

**Files:**
- Modify: `backend/app/routes/duty_config.py` — add `DELETE /locations/{id}`
- Modify: `backend/app/services/duty_config.py` — `delete_location()` with FK checks
- Modify: `frontend/src/api/dutyConfig.ts` — `deleteLocation(id)`
- Modify: `frontend/src/pages/DutyConfigPage.tsx` — locations list: add delete button + toggle active
- Modify: `frontend/src/api/dutyConfig.ts` — `updateLocation(id, {active})` already exists but is unused

- [ ] **Step 1: Backend** — `DELETE /duty-config/locations/{id}`: check FK references (duty_shifts.duty_location_id, duty_types.duty_location_id, duty_assignments.duty_location_id); if any exist → 400 with detail `location_in_use`; else delete + audit. Add `PATCH` for `{active: bool}` toggle (already exists at line 364-379).

- [ ] **Step 2: Frontend** — locations list: add delete button (disabled if in use, showing tooltip) + active toggle checkbox.

- [ ] **Step 3:** Run tests, commit.

---

### Task C2: Duty config active checkbox + grey disabled rows

**Files:**
- Modify: `frontend/src/pages/DutyConfigPage.tsx` — replace text link with checkbox toggle; add `rowClassName` for grey background

- [ ] **Step 1:** Replace the text `<button>` in the active column with a `<input type="checkbox">` that calls `updateDutyType(d.id, {active: !d.active}).then(refresh)`.
- [ ] **Step 2:** Add `rowClassName={(d) => !d.active ? "opacity-60 bg-gray-100 dark:bg-gray-700/50" : ""}` to the DataTable.
- [ ] **Step 3:** Run frontend tests, commit.

---

### Task C3: Fix nested modal close (location modal closes shift modal)

**Files:**
- Modify: `frontend/src/hooks/useModalBackClose.ts` — `handlePopState` must verify the popped entry belongs to THIS modal

- [ ] **Step 1:** In `handlePopState` (line 92-95), check `window.history.state?.__modalId !== entryIdRef.current` before calling `onClose()`. When another stacked modal's entry above was consumed, skip closing this one.
- [ ] **Step 2:** Test manually: open shift modal → open location modal → close location modal → shift modal stays open.
- [ ] **Step 3:** Commit.

---

## Stream D: Hierarchy Transfers & Notification Preferences (Items 4, 11)

### Task D1: Informative hierarchy transfer errors

**Files:**
- Modify: `backend/app/services/hierarchy_transfers.py` — add descriptive error messages
- Modify: `frontend/src/pages/` (hierarchy tree) — surface the `detail` field from the 400 response

- [ ] **Step 1: Investigate** — Attempt the transfer of צוות אקסודוס under צוות נילוס via the API and capture the exact error detail. The route already maps `HierarchyError` to `HTTPException(400, detail=str(exc))` — the frontend just needs to display it.

- [ ] **Step 2: Frontend** — In the hierarchy tree component's error handler, show `err.response.data.detail` in a toast/alert instead of a generic message.

- [ ] **Step 3:** If the error is a legitimate constraint (e.g. cycle, level mismatch), add a descriptive Hebrew message to the service's raise site. If it's a bug preventing valid transfers, fix the validation logic.

- [ ] **Step 4:** Run tests, commit.

---

### Task D2: Filter notification preferences by relevance

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx` — refine `MANAGER_ONLY_NOTIFICATION_TYPES` into a role→types mapping

- [ ] **Step 1:** Derive the role→notification-type mapping from the `notify_*` call sites in `backend/app/services/notifications.py`. Group into: soldier-relevant, commander-relevant, duty-manager-relevant, admin-only.
- [ ] **Step 2:** Replace the binary blocklist with a per-role allowlist in `visiblePrefs`.
- [ ] **Step 3:** Run frontend tests, commit.

---

## Stream E: Range Eligibility & Public Profile (Items 12, 13)

### Task E1: Range eligibility fallback to profile dates

**Files:**
- Modify: `backend/app/services/weapon_eligibility.py` — `compute_eligibility()`

- [ ] **Step 1: Write failing test** — Soldier with NO `SoldierRangeQualification` row but with `last_mitvahim_date` within validity window → `compute_eligibility` returns True.

- [ ] **Step 2: Implement** — In `compute_eligibility()`, when no `SoldierRangeQualification` row exists, fall back to `soldier.last_mitvahim_date` (for laser) or `soldier.last_alal_date` (for alal), checking `+ validity_days >= today` using the same `_VALIDITY_SETTING_KEYS`/`_FALLBACK_VALIDITY_DAYS` from ranges.py.

- [ ] **Step 3:** Run tests, commit.

---

### Task E2: Fix public soldier profile access for out-of-scope commanders

**Files:**
- Modify: `backend/app/routes/soldiers.py` — `get_soldier()` extend the public-bypass to commanders/DMs

- [ ] **Step 1: Write failing test** — Group-level commander requests a soldier outside their scope → currently 403, should return redacted public profile.

- [ ] **Step 2: Implement** — In `get_soldier()`, extend the `role == "soldier"` bypass to include `role == "commander"` and `role == "duty_manager"` when `include_private` would be False anyway. The redaction logic (`_contact_visibility`) already handles field-level privacy.

- [ ] **Step 3:** Run tests, commit.

---

## Execution Order

Streams A–E are independent. Recommended order by user impact:
1. Stream A (approvals bug fix = highest priority)
2. Stream B (profile UX improvements)
3. Stream E (range eligibility + public profile)
4. Stream C (location/shift modal UX)
5. Stream D (transfers/notifications)
