# Draft Duties in Soldier History Panel

**Date:** 2026-06-11  
**Branch:** feat/duty-type-operational-fields (will be its own task branch)  
**Status:** Approved

## Problem

When the algorithm runs in `dm_reviewed` mode it creates `DutyAssignment` records with `status = "algorithm_draft"`. Commanders currently review these only via the algorithm proposals table. There is no way to see a soldier's draft duties in context alongside their published history, and commanders cannot quickly accept or reject a single draft from the soldier profile view.

## Goal

Commanders and duty managers can see draft duties in a soldier's duty-history panel, with a clear visual badge, and can accept or reject them inline without leaving the profile.

Soldiers are **not** shown their own drafts until a draft is published.

## Scope (what is NOT in this design)

- No change to soldier-facing views (MyDutiesPage, MyRequestsPage)
- No notification to the soldier when a draft is created
- No bulk accept/reject in the history panel (that remains in the algorithm proposals table)
- Existing job-scoped endpoints (`/algorithm/jobs/{job_id}/proposals/{id}/accept|reject`) are unchanged

---

## Backend

### 1. `get_duty_history` service

File: `backend/app/services/duty_history.py`

Add `include_drafts: bool = False` parameter. When `False` (default), the query keeps `status.not_in(["algorithm_draft", "algorithm_rejected"])` — no behavior change. When `True`, the filter becomes `status.not_in(["algorithm_rejected"])`, letting draft assignments through.

For each `algorithm_draft` assignment, do a single AuditLog lookup to find the `job_id`:

```python
audit_row = session.execute(
    select(AuditLog.context["job_id"].astext).where(
        AuditLog.action == "algorithm.proposal.create",
        AuditLog.entity_id == a.id,
    ).limit(1)
).scalar_one_or_none()
```

Store the result as `metadata["job_id"]` (or `None` if not found). The event's `status` field is already `"algorithm_draft"`, which the frontend uses to identify draft cards.

### 2. History route

File: `backend/app/routes/assignments.py` (or wherever `GET /soldiers/{id}/duty-history` lives)

Add `include_drafts: bool = Query(False)`. When `True`, verify `user.role in ("duty_manager", "admin")` — raise HTTP 403 otherwise. Pass the flag through to `get_duty_history`.

### 3. New accept/reject endpoints (no job_id required)

File: `backend/app/routes/algorithm.py`

```
POST /algorithm/proposals/{assignment_id}/accept
POST /algorithm/proposals/{assignment_id}/reject
```

Both:
1. Load the assignment (404 if missing).
2. Authorize `Action.ALGORITHM_RUN`.
3. Check `status == "algorithm_draft"` — raise HTTP 409 `"not_draft"` if not.
4. Set status to `"published"` / `"algorithm_rejected"` and write audit (context omits job_id or includes it if found via AuditLog lookup).
5. Commit and return `{"status": <new_status>}`.

The existing job-scoped endpoints remain untouched.

---

## Frontend

### 1. `api/dutyHistory.ts`

`getSoldierDutyHistory(soldierId: string, includeDrafts?: boolean)` appends `?include_drafts=true` when the flag is truthy.

### 2. `api/algorithm.ts`

Two new typed wrappers:

```ts
acceptProposalDirect(assignmentId: string): Promise<void>
rejectProposalDirect(assignmentId: string): Promise<void>
```

Both call `POST /algorithm/proposals/{assignmentId}/accept|reject`.

### 3. `DutyHistoryPanel.tsx`

**Data fetching:** `getSoldierDutyHistory(soldierId, canManage)`. When `canManage` is false the flag is omitted — behavior is identical to today for soldiers.

**Filter chips:** Add `"algorithm_draft"` to `FilterType` and a new entry in `FILTER_KEYS`:

```ts
{ type: "algorithm_draft", i18nKey: "duty_history.filter_drafts" }
```

**Visual treatment in `EventCard`:**  
Draft events already receive the blue `STATUS_BADGE["algorithm_draft"]` chip from the existing status badge map. Add a second prominent amber badge labeled `"טיוטה"` rendered unconditionally when `e.status === "algorithm_draft"`, so it stands out from regular status chips.

**Inline actions (expanded view):**  
When `canManage && e.status === "algorithm_draft"`:

```tsx
<button onClick={() => handleAcceptDraft(e.id)}>אשר</button>
<button onClick={() => handleRejectDraft(e.id)}>דחה</button>
```

`handleAcceptDraft` / `handleRejectDraft` call the new API wrappers, then call `load()` to refresh. A 409 response (already decided elsewhere) also triggers a refresh without showing an error.

**No swap / cover buttons on draft cards** — these are suppressed since the draft isn't published yet (`onOfferSwap` and `openSwaps` are not passed for draft events).

---

## Data Flow

```
Commander opens soldier profile
  → DutyHistoryPanel (canManage=true)
    → GET /soldiers/{id}/duty-history?include_drafts=true
      → backend role check (DM/admin only)
      → get_duty_history(..., include_drafts=True)
        → includes algorithm_draft assignments
        → per-draft AuditLog lookup → job_id in metadata
      → response includes draft TimelineEvents
    → draft EventCards in upcoming section with amber "טיוטה" badge
    → commander expands card → Accept / Reject buttons
      → POST /algorithm/proposals/{id}/accept|reject
        → status updated in DB
        → audit written
      → history refreshes → draft card replaced by published/rejected event
```

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Soldier requests `include_drafts=true` | 403 |
| Draft already accepted/rejected (409) | Silently refresh — no error alert |
| Network error on accept/reject | Show `"שגיאה בביצוע הפעולה"` alert (matches existing pattern) |
| AuditLog row missing for a draft | `job_id = null` in metadata; accept/reject still works via new job-agnostic endpoints |

---

## i18n Keys (Hebrew)

| Key | Value |
|---|---|
| `duty_history.filter_drafts` | `טיוטות` |
| `duty_history.draft_badge` | `טיוטה` |

---

## Testing

- **Backend unit test** (`test_duty_history.py`): `get_duty_history` with `include_drafts=True` returns draft assignments; with `False` does not.
- **Backend unit test** (`test_algorithm_routes.py` or similar): new accept/reject endpoints return correct status, reject non-draft with 409.
- **Frontend**: no new Vitest tests required — existing EventCard rendering patterns cover the badge; manual verification sufficient for the inline buttons.
