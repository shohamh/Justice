# Design: Commander Exemption Escalation + Requests-in-Tab

**Date:** 2026-07-05
**Status:** Approved

## Overview

The exemptions system already has two separate pieces: (1) commander-granted
informal exemptions (`is_commander_exemption=True` on `ExemptionType`, granted
via `grant_commander_exemption`, excluded from potential calculations), and
(2) a soldier-initiated official exemption request pipeline
(`ExemptionRequest`, commander → duty-manager approval, counted in potential
once approved). These currently don't talk to each other, and pending
requests only surface on a separate `/exemption-requests` Approvals page, not
inside a soldier's own profile.

This design adds:

1. A **request history section** inside the soldier's exemptions tab
   (`ExemptionsPanel`), showing all exemption requests for that soldier
   (pending/approved/rejected), with inline approve/reject for authorized
   viewers.
2. A **confirmation gate** on the existing commander-exemption grant form —
   a modal restating the "doesn't count toward potential, unit bears the
   burden, use sparingly" warning, requiring an explicit acknowledgment
   checkbox before the grant is submitted.
3. An **escalation path**: when granting a commander exemption, the
   commander can tick a box to also raise it to the duty manager for
   approval as an official exemption (which, once approved, does count
   toward potential). A second checkbox controls whether the informal
   commander exemption is applied immediately or only requested.

## Data Model

**`ExemptionRequest` — new column:**
```sql
ALTER TABLE exemption_requests
  ADD COLUMN linked_commander_exemption_id UUID NULL
  REFERENCES soldier_exemptions(id) ON DELETE SET NULL;
```
Set only when the request was created via commander escalation with
"apply immediately" checked — lets the DM approval UI show that an informal
exemption is already active covering (all or part of) this period. `NULL`
for ordinary soldier-submitted requests.

No other schema changes. `ExemptionRequest.status` already supports the
values this flow needs (`pending_duty_manager`); no new statuses required.

## Backend

### `services/exemption_requests.py` — new function

```python
def submit_commander_escalation(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    official_exemption_type_id: uuid.UUID,
    start_date: date,
    end_date: date | None,
    reason: str | None,
    apply_immediately: bool,
    actor_id: uuid.UUID,
) -> ExemptionRequest:
```

Behavior:
- Validates `official_exemption_type_id` refers to a **non**-commander
  `ExemptionType` (mirror of the existing check in `submit_request`, inverted
  — raise `ExemptionRequestError("official_exemption_type_required")` if the
  type has `is_commander_exemption=True`).
- If `apply_immediately`: calls existing `grant_commander_exemption(...)`
  (unchanged) using the soldier's chosen *commander* exemption type — this
  requires the caller to also pass the commander exemption type id, since
  it's distinct from the official one being requested. Capture the resulting
  `SoldierExemption.id`.
- Creates `ExemptionRequest` directly with:
  - `status="pending_duty_manager"` (skips `pending_commander` — a commander
    is already the one initiating this)
  - `commander_approved_by=actor_id`
  - `exemption_type_id=official_exemption_type_id`
  - `linked_commander_exemption_id` set if a commander exemption was granted
    above, else `NULL`
- Notifies duty managers directly (see Notifications below).
- Returns the request.

### `services/notifications.py` — new helper

`notify_duty_managers_of_request(session, *, soldier_id, request_id, ...)`,
modeled on the DM-notification half of `notify_enrollment_received`: walks
`DutyManagerScope` for nodes covering the soldier, filters by
`dm_scope_covers_target` / `REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY` (already
defined in `services/authority.py`), sends `NotificationType.exemption_request_pending`
to each qualifying DM. Reuses `_create_notif` internally like the rest of the
file.

This is a new path because `cascade_to_commanders` (used by
`notify_commanders_of_request`) targets commanders, not duty managers
specifically — since we've skipped the commander step, commanders aren't the
right audience here.

### `services/exemption_requests.py` — existing functions unchanged

`approve_duty_manager_step` and `reject_request` operate on any
`pending_duty_manager` request regardless of how it was created — no changes
needed. `approve_commander_step` is simply never called for escalated
requests (they start past that stage).

### `routes/exemptions.py` — new route

```python
@router.post("/commander-escalate", response_model=ExemptionRequestOut, status_code=201)
def escalate_commander_exemption_route(soldier_id, body, session, user): ...
```

Request body:
```python
class CommanderEscalateRequest(BaseModel):
    commander_exemption_type_id: uuid.UUID  # the informal type, required only if apply_immediately
    official_exemption_type_id: uuid.UUID   # the type being requested from the DM
    start_date: date
    end_date: date | None = None
    reason: str = Field(min_length=1, max_length=1000)
    apply_immediately: bool
```

Authorization: **identical block** to `grant_commander_exemption_route`
(admin, or in-scope duty manager, or in-scope commander with
`commander_can_grant_commander_exemption`) — escalating requires the same
authority as granting the informal exemption outright.

Returns `ExemptionRequestOut` (reuse the Pydantic model already defined in
`routes/exemption_requests.py` — move it to a shared location, e.g.
`app/routes/_exemption_shared.py`, or import from there; avoid duplicating
the schema).

### `routes/exemption_requests.py` — new route

```python
@router.get("/soldiers/{soldier_id}/exemption-requests", response_model=list[ExemptionRequestOut])
def get_soldier_exemption_requests(soldier_id, session, user): ...
```

Returns **full history** (all statuses, not just pending) for one soldier.
Authorization: same as the existing per-soldier exemptions list —
`Action.EXEMPTION_READ` on the soldier's node (skip the check if
`soldier_id == user.id`), with `include_sensitive` masking via
`can_see_private` exactly like `routes/exemptions.py::list_`.

### Notifications table

| Event | Recipients |
|---|---|
| Commander escalates (apply_immediately=True or False) | Duty managers in scope, rank-eligible (new `notify_duty_managers_of_request`) |
| DM approves escalated request | Soldier: existing `exemption_approved` (unchanged) |
| DM rejects escalated request | Soldier: existing `exemption_rejected` (unchanged); the informal exemption, if one was granted, is **not** auto-revoked — commander revokes manually if desired |

## Frontend

### `ExemptionsPanel.tsx`

New "בקשות פטור" section (below the existing active/expired exemption
lists), populated from the new `listExemptionRequestsForSoldier(soldierId)`
API call:
- Shows every request regardless of status: type name, dates, reason,
  status badge (ממתין לאישור מפקד / ממתין לאישור מפקד תורנויות / אושר /
  נדחה), decided-by when applicable.
- For rows with status `pending_commander` or `pending_duty_manager`, show
  inline **אשר** / **דחה** buttons when the viewer is authorized — reuse the
  existing `approveCommanderStep` / `approveDutyManagerStep` / `rejectRequest`
  API wrappers already used by the Approvals page. Authorization is
  enforced server-side (buttons can be shown optimistically; a 403 simply
  surfaces as an error toast).

### `CommanderExemptionGrantForm.tsx`

- Rename submit button to **"צור פטור פיקודי"**.
- Clicking it no longer grants directly — it opens a **confirmation modal**
  (new small component, e.g. `ConfirmCommanderExemptionModal`) that:
  - Restates the existing warning text.
  - Has a required checkbox, "אני מבין/ה", that gates the modal's own
    confirm button (disabled until checked).
  - On confirm, performs the actual grant (or escalation, see below) and
    closes.
- New checkbox on the base form: **"העלה לאישור מפקד תורנויות כפטור
  רשמי"** (escalate). When ticked, reveals:
  - A `Combobox` of official (non-commander) `ExemptionType`s — the type
    being requested from the DM. Required when escalate is ticked.
  - A second checkbox, **default unticked**: **"החל את הפטור הפיקודי
    מיידית"** (apply the informal exemption now, in addition to requesting
    official status).
- Submit logic in the confirmation modal:
  - Escalate off → existing `grantCommanderExemption(soldierId, {...})` call
    (unchanged).
  - Escalate on → new `escalateCommanderExemption(soldierId, {...})` call
    with `apply_immediately` reflecting the second checkbox.
- After either path succeeds, call `onGranted()` (existing prop) to refresh
  both the exemptions list and the new requests-history section.

### `frontend/src/api/exemptions.ts` — new wrappers

```ts
export function escalateCommanderExemption(soldierId: string, body: {
  commander_exemption_type_id?: string;
  official_exemption_type_id: string;
  start_date: string;
  end_date?: string | null;
  reason: string;
  apply_immediately: boolean;
}): Promise<ExemptionRequest>;

export function listExemptionRequestsForSoldier(soldierId: string): Promise<ExemptionRequest[]>;
```

## Alembic Migration

Single migration:
```sql
ALTER TABLE exemption_requests
  ADD COLUMN linked_commander_exemption_id UUID NULL
  REFERENCES soldier_exemptions(id) ON DELETE SET NULL;
```

## Unchanged

- `grant_exemption`, `grant_commander_exemption`, `revoke_exemption` — no
  changes.
- `approve_commander_step`, `approve_duty_manager_step`, `reject_request` —
  no changes; they already operate purely on `ExemptionRequest.status`.
- The separate Approvals page (`ApprovalsPage.tsx`) and `MyRequestsPage.tsx`
  — unchanged; the new soldier-scoped history is additive, not a
  replacement.
- Potential calculation (`services/potential.py`) — unchanged; it already
  only counts non-commander-exemption types, which is exactly what makes the
  escalated official exemption count once approved.
