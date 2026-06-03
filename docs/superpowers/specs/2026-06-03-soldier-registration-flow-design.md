# Soldier Registration Flow — Design Spec
**Date:** 2026-06-03

## Overview

Add a self-service registration flow so new soldiers can create their own accounts, submit optional exemption requests and personal constraints, link Telegram, and request assignment to a commander's node. The commander (and superiors / אחראי תורנויות above them) must approve the request before the soldier is placed in the real hierarchy. Rejected or pending soldiers sit in a system-wide holding node ("מסגרת ממתינים לקליטה"). An invite-code system gates who may register.

This spec also introduces scoped אחראי תורנויות (duty managers) — replacing the current single-node `hierarchy_node_id` scoping with a multi-node `DutyManagerScope` table — and defines how commanders of rank רסן and above can appoint them.

---

## 1. Data Models

### 1.1 `RegistrationInviteCode` (new table)
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | auto |
| `code` | Text unique | short random string, auto-generated |
| `uses_left` | int | set by admin at creation; decremented on each successful registration; registration rejected when 0 |
| `created_by` | UUID FK soldiers | admin who created it |
| `created_at` | timestamptz | auto |

### 1.2 `SoldierEnrollmentRequest` (new table)
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | auto |
| `soldier_id` | UUID FK soldiers | the registering soldier |
| `requested_node_id` | UUID FK hierarchy_nodes | node the soldier wants to join |
| `status` | Text | `pending` / `approved` / `rejected` |
| `decided_by` | UUID FK soldiers nullable | approver/rejecter |
| `decided_at` | timestamptz nullable | |
| `decision_note` | Text nullable | required on reject |
| `created_at` | timestamptz | auto |

Constraint: a soldier may have at most one `pending` request at a time.

### 1.3 `DutyManagerScope` (new table)
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | auto |
| `duty_manager_id` | UUID FK soldiers | soldier with `duty_manager` role |
| `hierarchy_node_id` | UUID FK hierarchy_nodes | root of the subtree they manage |

Unique constraint on `(duty_manager_id, hierarchy_node_id)`.

Replaces `Soldier.hierarchy_node_id` as the scoping mechanism for אחראי תורנויות. `Soldier.hierarchy_node_id` is retained as the soldier's personal assignment node and is unchanged by this feature.

**Migration:** each existing DM's current `hierarchy_node_id` is seeded as their initial `DutyManagerScope` entry.

### 1.4 `NotificationType` additions
- `enrollment_request_received` — sent to commander(s) + אחראי תורנויות when a soldier requests to join
- `enrollment_approved` — sent to soldier
- `enrollment_rejected` — sent to soldier

### 1.5 System settings (new keys)
| Key | Default | Description |
|---|---|---|
| `registration.telegram_required` | `true` | Whether Telegram linking must be completed before accessing the app |
| `system.holding_node_id` | set by bootstrap | UUID of the "מסגרת ממתינים לקליטה" holding node |

### 1.6 "מסגרת ממתינים לקליטה" holding node
- A single division-level hierarchy node created by `bootstrap.py` on first run.
- Its UUID is written to `system.holding_node_id` in `system_settings`.
- Protected from deletion (existing guard: cannot delete a node with soldiers assigned).
- All registering soldiers are placed here until their enrollment request is approved.

---

## 2. Backend API

### 2.1 Registration endpoints (unauthenticated)

**`POST /auth/register`**
- Body: `invite_code`, all mandatory soldier fields (personal_number, full_name, password, phone, gender, is_officer, rank, bahad1_graduate, enlistment_date, mandatory_end_date, discharge_date, last_mitvahim_date, last_alal_date), `requested_node_id`, optional `exemption_requests[]`, optional `personal_constraints[]`
- Validates invite code (`uses_left > 0`), decrements `uses_left`
- Creates `Soldier` with `hierarchy_node_id = system.holding_node_id`, `must_change_password = False`
- Creates any submitted exemption requests and personal constraints (status=pending)
- Creates `SoldierEnrollmentRequest` (status=pending)
- Sends `enrollment_request_received` notification to: commander of requested node, all commanders above in the path, all אחראי תורנויות whose scope contains the requested node
- Returns same `LoginResponse` as `/auth/login` plus `telegram_required: bool`

**`GET /auth/register/nodes`**
- Returns all hierarchy nodes with `id`, `name`, `level`, `path_ids`, `commander_name`
- Used by the wizard's commander-selection step (no auth required)

**`GET /auth/register/validate-code?code=...`**
- Returns `{ valid: bool }` — used for live validation in step 1 of the wizard

### 2.2 Enrollment request routes (`/enrollment-requests`)

**`GET /enrollment-requests/pending`**
- Returns pending requests scoped to the caller:
  - Commander: requests where `requested_node_id` is in their scope
  - אחראי תורנויות: requests where `requested_node_id` is in their `DutyManagerScope`
  - Admin: all

**`POST /enrollment-requests/{id}/approve`**
- Sets `soldier.hierarchy_node_id = request.requested_node_id`
- Sets request status=approved, `decided_by`, `decided_at`
- Sends `enrollment_approved` notification to soldier
- Auth: `Action.ENROLLMENT_APPROVE` — commander in scope, אחראי תורנויות in scope, or admin

**`POST /enrollment-requests/{id}/reject`**
- Body: `{ decision_note }` (required)
- Leaves soldier in holding node
- Sets request status=rejected
- Sends `enrollment_rejected` notification to soldier
- Auth: same as approve

### 2.3 Invite code routes (`/admin/invite-codes`, admin-only)

- `GET /admin/invite-codes` — list all codes with `uses_left`, `created_by`, `created_at`
- `POST /admin/invite-codes` — body: `{ uses_left }`; code auto-generated as a short random string
- `DELETE /admin/invite-codes/{id}` — revoke (delete) a code

### 2.4 DM scope management (`/duty-manager-scope`)

**`POST /duty-manager-scope`**
- Body: `{ soldier_id, node_id }`
- Adds a `DutyManagerScope` entry
- Implicitly sets `soldier.role = "duty_manager"` if not already
- Auth: admin, or commander with rank רסן or above (`Action.DM_SCOPE_MANAGE`) where `node_id` is in their scope

**`DELETE /duty-manager-scope/{id}`**
- Removes a scope entry
- If soldier has no remaining scope entries: role downgraded to `commander` if they command any node, else `soldier`
- Auth: same as POST

### 2.5 Authorization changes

New actions in `authz.py`:
- `Action.ENROLLMENT_APPROVE` — commander in scope, DM in scope, admin
- `Action.DM_SCOPE_MANAGE` — commander with rank רסן+ in scope, admin

Updated `scope_root_ids()` for DMs: queries `DutyManagerScope` instead of using `Soldier.hierarchy_node_id`.

Rank constant (from existing `OFFICER_RANKS` in `eligibility.py`):
```python
RANKS_RASAN_AND_ABOVE = OFFICER_RANKS[OFFICER_RANKS.index("רסן"):]
# ["רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף"]
```

---

## 3. Frontend

### 3.1 Login page
- "הרשמה" button below the existing form → navigates to `/register`

### 3.2 Registration wizard (`/register`)
Six steps, state held in React until final submission:

| Step | Content |
|---|---|
| 1. קוד הזמנה | Text input; validated against `GET /auth/register/validate-code` on blur/next |
| 2. פרטים אישיים | All mandatory fields: name, personal number, password (+ confirm), phone, gender, rank, is_officer, bahad1 graduate, enlistment date, mandatory end date, discharge date, last mitvahim date, last alal date |
| 3. בקשות פטור | Add/remove rows (exemption type, start date, end date, reason); "דלג" button |
| 4. אילוצים אישיים | Add/remove date-range rows with reason; "דלג" button |
| 5. בחירת מפקד | Fuzzy search with `fuse.js` over node names + commander names; collapsible hierarchy tree browser; selected node shows commander name |
| 6. סקירה ואישור | Read-only summary of all entered data; "הרשם" submits `POST /auth/register`; on success auto-login and redirect to `/setup/telegram` |

### 3.2a `/me` endpoint extension
`GET /me` gains two new fields:
- `telegram_linked: bool` — true if a verified `TelegramLink` exists for this soldier
- `telegram_required: bool` — value of `registration.telegram_required` system setting

`AuthContext` reads these on every login/refresh and stores them in context state.

### 3.3 Telegram setup page (`/setup/telegram`)
- Shows soldier's Telegram verification code and bot instructions
- "בדוק אימות" button polls `GET /me/telegram-link` for `is_verified`
- On verified: redirects to `/`
- `AuthContext` gains a `telegramVerified` flag derived from the `/me` response
- `ProtectedRoute` redirects to `/setup/telegram` when `registration.telegram_required` is true and `telegramVerified` is false

### 3.4 Approvals page — new "הצטרפות" tab
- New tab alongside constraints / exemptions / field_updates / swaps
- Shows pending `SoldierEnrollmentRequest` items scoped to the viewer
- Each row: soldier name + personal number, requested node name, commander name, date submitted
- Approve button; reject requires a decision note

### 3.5 Admin: Invite Codes page (`/admin/invite-codes`)
- Table: code, uses_left, created by, created at
- "צור קוד" button → dialog with `uses_left` input → creates code
- "בטל" (revoke) per row
- Linked from the admin/settings area of `UnifiedNav`

### 3.6 Commander panel — Assign אחראי תורנויות
- On `TeamHierarchyPage` or soldier profile, commanders ranked רסן+ see "מנה אחראי תורנויות" on soldiers within their scope
- Opens a dialog: multi-select nodes from their own subtree → submits `POST /duty-manager-scope`
- Existing DM scope entries shown with "הסר" buttons per entry

---

## 4. Edge Cases

| Case | Behaviour |
|---|---|
| Soldier submits a second enrollment request while one is pending | Rejected with `enrollment_request_pending` error |
| Soldier rejected — wants to re-request | "בקש שוב" button on profile page; allowed once previous request is decided |
| Invite code `uses_left = 0` | Registration returns `invite_code_exhausted` error; admin panel shows code greyed out |
| Commander has null rank | `DM_SCOPE_MANAGE` denied — rank check requires explicit value in `RANKS_RASAN_AND_ABOVE` |
| Last DM scope entry removed | Role downgraded: `commander` if they command any node, else `soldier` |
| `registration.telegram_required` toggled off mid-flow | Soldiers not yet verified gain app access immediately; already-verified unaffected |
| Holding node attempted deletion | Blocked by existing guard (node has soldiers assigned) |

---

## 5. Testing

- Unit tests for `scope_root_ids()` with multi-node DM scope
- Unit tests for rank guard on `DM_SCOPE_MANAGE`
- Unit test for enrollment request approval/rejection state transitions
- Unit test for invite code `uses_left` decrement and exhaustion
- Integration tests for `POST /auth/register` happy path and error cases
- Frontend: existing `ApprovalsPage` tests extended for the new "הצטרפות" tab
