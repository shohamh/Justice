# Algorithm Run Load Performance — Design

Date: 2026-06-23

## Problem

`GET /algorithm/jobs/{job_id}` is slow for large jobs (hundreds–thousands of proposals) because `_proposals_for_job` does two expensive things:

1. **Audit log full scan** — finds assignment IDs by scanning `audit_log` on `context->>'job_id'` with no index.
2. **Explanation payload flood** — loads all `AssignmentExplanation` rows (1–2 KB each) just to extract 4 scalar values per row.

## Solution: Denormalize onto `DutyAssignment` (Option B)

Add a job FK and 4 score columns directly to `duty_assignments`. Populate them during `persist_results`. The proposals query then becomes a single indexed `WHERE algorithm_job_id = ?` — no audit log scan, no explanation load.

## Schema Changes

New migration adds to `duty_assignments`:

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `algorithm_job_id` | `UUID FK → algorithm_jobs(id) ON DELETE SET NULL` | yes | Links assignment to its job |
| `norm_score_before` | `FLOAT` | yes | Assigned soldier's score before assignment |
| `norm_score_after` | `FLOAT` | yes | Assigned soldier's score after assignment |
| `candidate_rank` | `INTEGER` | yes | 1-based rank among eligible candidates |
| `candidate_pool_size` | `INTEGER` | yes | Total unblocked candidate count |

Index: `CREATE INDEX idx_duty_assignments_job_id ON duty_assignments(algorithm_job_id)`.

No backfill. Old records have `NULL` for all new columns.

## Backend Changes

### `DutyAssignment` model (`backend/app/db/models.py`)
Add 5 nullable mapped columns matching the schema above.

### `persist_results` (`backend/app/services/algorithm_bridge.py`)
- **Pass 1**: Set `algorithm_job_id = job.id` on every new `DutyAssignment`.
- **Pass 2**: After computing `_explanation_payload`, write the 4 scalars back onto the already-flushed `DutyAssignment`:
  - `norm_score_before` / `norm_score_after` — look up the assigned soldier in the (pre-truncation) candidates
  - `candidate_rank` / `candidate_pool_size` — already computed as `assigned_rank` / `pool_size` inside `_explanation_payload`

### `_proposals_for_job` (`backend/app/routes/algorithm.py`)
New fast path: if the job has assignments with `algorithm_job_id` set, query directly:

```python
rows = session.execute(
    select(DutyAssignment).where(DutyAssignment.algorithm_job_id == job.id)
).scalars().all()
```

Score/rank fields come from the assignment columns. Reserve links still loaded via one `IN` query.

Old audit-log path is the fallback when the direct query returns no rows (pre-migration jobs).

### What is NOT changing
- Explanation modal (`GET /algorithm/jobs/{job_id}/explanations/{assignment_id}`) — still loads one full payload on demand, which is fine.
- `_maybe_publish_job`, accept/reject endpoints — still use audit log, no change.
- Frontend — `ProposalRow` already has these fields, no changes needed.

## Test Impact
- Unit tests that test `_proposals_for_job` or `persist_results` need the new columns populated.
- No frontend tests affected.
