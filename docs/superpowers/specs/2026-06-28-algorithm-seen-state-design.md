# Algorithm Job Seen State

**Date:** 2026-06-28

## Problem

The תכנון nav button badge and the per-section chips inside `/planning/shifts` show counts for failed and done algorithm runs even after the user has clicked on them. The badge only clears on the next 30-second poll or navigation event, not immediately on click. Seen state is stored only in `localStorage`, so it is not shared across devices or browsers.

## Goal

- Clicking a done or failed job marks it as seen immediately, clearing its contribution to the nav badge and the section chips.
- "Mark all as seen" button clears all at once.
- Seen state is persisted per user in the database.
- `localStorage` is removed as the source of truth for seen state.

---

## Backend

### New table: `algorithm_job_seen`

```sql
CREATE TABLE algorithm_job_seen (
    job_id   UUID NOT NULL REFERENCES algorithm_jobs(id) ON DELETE CASCADE,
    user_id  UUID NOT NULL REFERENCES soldiers(id) ON DELETE CASCADE,
    seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, user_id)
);
```

Migration file: `backend/alembic/versions/0061_algorithm_job_seen.py`

### SQLAlchemy model

Add `AlgorithmJobSeen` dataclass to `backend/app/db/models.py`:

```python
class AlgorithmJobSeen(Base):
    __tablename__ = "algorithm_job_seen"
    job_id:  Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("algorithm_jobs.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id",       ondelete="CASCADE"), primary_key=True)
    seen_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)
```

### Updated `JobSummaryOut`

Add `seen: bool = False` to `backend/app/routes/algorithm.py`.

### Updated `list_jobs` endpoint

`GET /algorithm/jobs` already accepts a `limit` param. Extend the query to left-join `algorithm_job_seen` on `(job_id, current_user.id)` and populate `seen` on each `JobSummaryOut`. Only non-cancelled, non-pending/running jobs can be "seen" (pending/running always return `seen=False`).

### New endpoints (in `backend/app/routes/algorithm.py`)

```
POST /algorithm/jobs/{job_id}/seen
    Body: none
    Auth: any duty manager / admin
    Effect: INSERT INTO algorithm_job_seen (job_id, user_id) VALUES (...) ON CONFLICT DO NOTHING
    Returns: 204

POST /algorithm/jobs/mark-all-seen
    Body: none
    Auth: any duty manager / admin
    Effect: INSERT INTO algorithm_job_seen (job_id, user_id)
              SELECT id, :user_id FROM algorithm_jobs
              WHERE status NOT IN ('pending', 'running')
                AND NOT (status = 'failed' AND error_message = 'cancelled_by_user')
              ON CONFLICT DO NOTHING
    Returns: 204
```

---

## Frontend

### Remove `localStorage` dependency

`frontend/src/utils/seenAlgorithmJobs.ts` — delete the file entirely once context is in place. The `STORAGE_KEY` localStorage key can be ignored; old entries are harmless.

### New context: `frontend/src/contexts/AlgorithmSeenContext.tsx`

```ts
interface AlgorithmSeenContextValue {
  seenIds: ReadonlySet<string>;
  markJobSeen: (jobId: string) => Promise<void>;
  markAllSeen: () => Promise<void>;
}
```

- Initialized from the `seen` field on each `JobSummaryOut` item returned by the jobs list.
- The context does NOT fetch jobs itself — it is seeded by consumers that already fetch jobs (UnifiedNav, ShiftsManagementPage, AlgorithmPage).
- `markJobSeen(id)` calls `POST /algorithm/jobs/{id}/seen`, then adds `id` to local `seenIds` state.
- `markAllSeen()` calls `POST /algorithm/jobs/mark-all-seen`, then replaces `seenIds` with the full set of currently known job IDs (all non-running/non-pending).
- Provider is placed in `frontend/src/main.tsx` wrapping the router.

### `frontend/src/api/algorithm.ts`

Add two new fetch helpers:
```ts
export async function markJobSeen(jobId: string): Promise<void>
export async function markAllJobsSeen(): Promise<void>
```

### `frontend/src/components/UnifiedNav.tsx`

- Call `useSeenJobs()` to get `seenIds`.
- Seed the context with seen state from the job list response: after `listJobs()`, call a context method `seedSeenIds(items)` that merges any `seen: true` items into `seenIds` without overwriting locally-optimistic updates.
- Pass `seenIds` to `computeRunBadgeCounts` (replacing the old `getSeenJobIds()` call).
- Badge re-renders immediately when `seenIds` changes (React state), no 30s wait needed for the dismiss action.

### `frontend/src/pages/AlgorithmPage.tsx`

- Replace `import { markJobSeen } from "../utils/seenAlgorithmJobs"` with `useSeenJobs().markJobSeen`.
- The existing `useEffect` that fires on `selectedJob` change stays; it now calls the context's async `markJobSeen`.
- Add "סמן הכל כנראה" (Mark all as seen) button in the job list header, visible when `algorithmBadgeCount > 0`. Calls `markAllSeen()`.

### `frontend/src/pages/planning/ShiftsManagementPage.tsx`

- Use `useSeenJobs()` to get `seenIds`.
- Pass `seenIds` to `computeRunBadgeCounts(result.items, seenIds)`.
- Seed context with seen state after each jobs fetch (same `seedSeenIds` pattern as UnifiedNav).
- Add "סמן הכל כנראה" button next to the section chevron, same visibility rule.

### `frontend/src/utils/algorithmRunBadges.ts`

No changes needed — already accepts `seenIds`.

---

## Context seeding pattern

Since multiple components independently fetch the jobs list, we need a shared "seed" method so they all converge on the same `seenIds` state without redundant API calls:

```ts
// Called by any component after a jobs list fetch
seedSeenIds(items: JobSummaryOut[]): void
  → merges { id | item.seen } into seenIds (union, never removes)
```

Optimistic local updates (`markJobSeen`, `markAllSeen`) always win over seed data.

---

## Auth

Both new endpoints require `canPlan` permission (admin or `is_duty_manager`), same as the existing algorithm endpoints. Use the existing `current_user` dependency.

---

## Testing

### Backend
- Unit: `markJobSeen` is idempotent (double-call returns 204, no duplicate row).
- Unit: `markAllSeen` inserts rows for all non-pending/non-running/non-cancelled-by-user jobs.
- Unit: `list_jobs` returns `seen: true` only for jobs the current user has seen.
- Unit: seen rows cascade-delete when the job is deleted.

### Frontend
- Update `algorithmRunBadges.test.ts` to ensure seenIds from context (not localStorage) are used.
- Update `UnifiedNav.test.tsx` to mock context and verify badge drops to 0 after markJobSeen.
- Remove any tests that reference the old `localStorage` key.
