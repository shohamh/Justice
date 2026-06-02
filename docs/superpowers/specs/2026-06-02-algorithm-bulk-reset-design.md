# Algorithm Page: Bulk Reset Buttons

**Date:** 2026-06-02  
**Branch:** feature/soldier-duty-history (to be continued or new branch)

## Summary

Add two buttons to `AlgorithmPlanningWindow` that let a duty manager bulk-reset future assignments beyond a configurable number of days:

1. **Reset Published** — soft-cancels `published` assignments (notifies soldiers, writes audit)
2. **Reset Drafts** — bulk-rejects `algorithm_draft` assignments (no notification, writes audit)

## Backend

### Endpoints

Both on the existing `/algorithm` router (`backend/app/routes/algorithm.py`). Both require `ALGORITHM_RUN` authorization.

**`POST /algorithm/reset-published`**

Query param: `days_ahead: int` (≥ 1, validated via `Field(ge=1)`)

- Cutoff date: `date.today() + timedelta(days=days_ahead)`
- Queries `DutyAssignment` where `status == "published"` and `start_date > cutoff`
- Calls existing `cancel_assignment(session, assignment=a, reason="bulk_reset", actor_id=user.id)` for each — triggers notification + audit per assignment
- Commits once after all cancellations
- Returns `{"cancelled": N}`

**`POST /algorithm/reset-drafts`**

Query param: `days_ahead: int` (≥ 1)

- Same cutoff logic
- Queries `DutyAssignment` where `status == "algorithm_draft"` and `start_date > cutoff`
- Sets each to `status = "algorithm_rejected"`, writes one `write_audit` call per assignment (action: `"algorithm.proposal.bulk_reject"`)
- Commits once
- Returns `{"rejected": N}`

### Edge cases

- 0 matches → returns `{"cancelled": 0}` / `{"rejected": 0}` (not an error)
- `days_ahead < 1` → FastAPI 422

## Frontend

### API client (`frontend/src/api/algorithm.ts`)

Two new functions:

```ts
export async function resetPublished(daysAhead: number): Promise<{ cancelled: number }>
export async function resetDrafts(daysAhead: number): Promise<{ rejected: number }>
```

### Component (`frontend/src/components/AlgorithmPlanningWindow.tsx`)

New "danger zone" section below the Run button, always visible when the panel is open. Contains two independent sub-rows, each with:

- A number input for `days_ahead` (default 30, min 1)
- A button that:
  1. Shows `window.confirm()` with the computed cutoff date
  2. POSTs to the endpoint
  3. Displays success message with the returned count, or error string on failure
  4. Is disabled while the request is in-flight

Layout (RTL):
```
[ ביטול שיבוצים מפורסמים מעבר ל- [30] ימים ]  [בטל שיבוצים]
[ דחיית טיוטות אלגוריתם מעבר ל-  [30] ימים ]  [דחה טיוטות]
```

### i18n (`frontend/src/i18n/he.json`, `algorithm` section)

New keys:
- `reset_published_label` — "ביטול שיבוצים מפורסמים מעבר ל-"
- `reset_published_btn` — "בטל שיבוצים"
- `reset_drafts_label` — "דחיית טיוטות אלגוריתם מעבר ל-"
- `reset_drafts_btn` — "דחה טיוטות"
- `reset_days_suffix` — "ימים"
- `reset_confirm_published` — "לבטל את כל השיבוצים המפורסמים החל מ-{{date}}?"
- `reset_confirm_drafts` — "לדחות את כל טיוטות האלגוריתם החל מ-{{date}}?"
- `reset_result_cancelled` — "בוטלו {{count}} שיבוצים"
- `reset_result_rejected` — "נדחו {{count}} טיוטות"
- `reset_none` — "לא נמצאו שיבוצים לביטול"

## Error handling

- Buttons disabled while request in-flight
- On API error: display error string below the button (same pattern as existing `error` state)
- Zero count: show `reset_none` message
- `days_ahead < 1`: prevented by `min={1}` on the input; backend also validates
