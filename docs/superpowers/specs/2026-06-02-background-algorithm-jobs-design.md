# Background Algorithm Jobs Design

**Date:** 2026-06-02  
**Status:** Approved

## Goal

Allow algorithm runs to execute in the background so users can navigate freely while a job runs, receive an in-app notification when it completes, and review job history and results from a dedicated page.

## Background

The algorithm already runs asynchronously via FastAPI `BackgroundTasks` — the `POST /algorithm/jobs` endpoint returns a job ID immediately (HTTP 202) and the job runs in a thread. The blocking part is purely the frontend: `AlgorithmPlanningWindow` polls every second and the user must stay on `DutyManagementPage` to see results. This design removes that constraint.

`AlgorithmJob.created_by` (UUID FK to soldiers) already links jobs to users. `NotificationType` is a DB enum that requires a migration to extend.

---

## Data Model & API

### Migration

Add two new values to the `NotificationType` PostgreSQL enum:
- `algorithm_job_done`
- `algorithm_job_failed`

### New endpoint: `GET /algorithm/jobs`

Returns paginated job history for the authenticated user (`created_by = current_soldier.id`).

Response shape per item (`JobSummaryOut`):
```python
class JobSummaryOut(BaseModel):
    id: uuid.UUID
    status: str              # pending | running | done | failed
    mode: str
    planning_start: date
    planning_end: date
    shift_count: int         # len(shift_ids)
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
```

Query params: `limit` (default 20), `offset` (default 0). Ordered by `created_at DESC`.

Access: `canManageDuties` roles only (duty_manager, admin).

Existing `GET /algorithm/jobs/{job_id}` returns full `JobOut` with proposals — unchanged.

### Notification trigger

In `backend/app/services/algorithm_bridge.py`, inside `run_algorithm_job()`:

**On success** (after setting status = "done"):
```python
create_notification(
    session=session,
    soldier_id=job.created_by,
    title=f"הרצת האלגוריתם הסתיימה — {len(proposals)} הצעות ממתינות לאישור",
    type=NotificationType.algorithm_job_done,
    reference_type="algorithm_job",
    reference_id=job.id,
)
```

**On failure** (after setting status = "failed"):
```python
create_notification(
    session=session,
    soldier_id=job.created_by,
    title="הרצת האלגוריתם נכשלה",
    body=job.error_message[:200] if job.error_message else None,
    type=NotificationType.algorithm_job_failed,
    reference_type="algorithm_job",
    reference_id=job.id,
)
```

No commander cascade (`cascade=False`). No Telegram push by default (users can opt in via preferences).

---

## Notification Routing (Frontend)

In `NotificationBell` (or wherever notifications render links): when `notification.reference_type === "algorithm_job"`, the link navigates to `/algorithm?jobId=<reference_id>`.

---

## Frontend Architecture

### New files

| File | Responsibility |
|------|----------------|
| `frontend/src/pages/AlgorithmPage.tsx` | Full `/algorithm` page — two-panel layout, wires form + table |
| `frontend/src/components/AlgorithmRunForm.tsx` | Planning form extracted from old window (date range, shifts, mode, settings) |
| `frontend/src/components/AlgorithmProposalTable.tsx` | Proposal review table extracted from old window (accept/reject/bulk) |

### Modified files

| File | Change |
|------|--------|
| `frontend/src/App.tsx` | Add `/algorithm` route, guard to canManageDuties |
| `frontend/src/components/ManageSheet.tsx` | Add "ניהול אלגוריתם" link under Planning section |
| `frontend/src/components/ManageSheet.test.tsx` | Update planning section test to include algorithm link |
| `frontend/src/i18n/he.json` | Add `nav.algorithm: "ניהול אלגוריתם"` |
| `frontend/src/api/algorithm.ts` (or existing) | Add `listJobs()` function |
| `frontend/src/pages/DutyManagementPage.tsx` | Remove `AlgorithmPlanningWindow` |

### Deleted files

| File | Reason |
|------|--------|
| `frontend/src/components/AlgorithmPlanningWindow.tsx` | Replaced by AlgorithmPage + AlgorithmRunForm + AlgorithmProposalTable |

---

## AlgorithmPage Layout

```
┌─────────────────────────────────────────────────────┐
│  Left panel (~280px)    │  Right panel (flex-1)      │
│  ─────────────────────  │  ─────────────────────    │
│  [+ הרצה חדשה]         │  <empty state or job>      │
│                         │                            │
│  ⏳ הרצה — 01/06-30/06  │  job header:               │
│  ✓  הרצה — 25/05-31/05  │    status, times, shifts   │
│  ✗  הרצה — 20/05-24/05  │                            │
│                         │  proposal table:           │
│                         │    accept/reject/bulk      │
└─────────────────────────┴────────────────────────────┘
```

### Left panel (job list)

- Fetches `GET /algorithm/jobs` on mount
- Auto-refreshes every 3 seconds while any job is `pending` or `running`
- Each row: status icon, date range, shift count, elapsed time (for done jobs) or spinner (for running)
- "הרצה חדשה +" button opens `AlgorithmRunForm` in a modal/drawer
- On job submitted: prepend to list, auto-select it
- URL param `?jobId=<id>` pre-selects a job on load (used by notification links)

### Right panel (job results)

- Empty state ("בחר הרצה מהרשימה") until a job is selected
- When `pending`/`running`: spinner + "מריץ אלגוריתם..." + polls `GET /algorithm/jobs/{id}` every 1s; on done/failed, loads proposals and stops polling
- When `done`: job header + `AlgorithmProposalTable`
- When `failed`: job header + red error message panel

### AlgorithmRunForm (drawer/modal)

Contains all inputs from the old `AlgorithmPlanningWindow`:
- Planning date range (start, end)
- Shift selector (multi-select from available shifts in range)
- Mode selector (shadow / dm_reviewed)
- Solver settings (K, T, W, alpha, beta, time_limit_seconds) in a collapsible "הגדרות מתקדמות" section
- Submit → calls `POST /algorithm/jobs` → closes drawer → new job appears selected in list

### AlgorithmProposalTable

All proposal review logic from old `AlgorithmPlanningWindow`:
- Table columns: date, type, soldier (clickable), reserve, scores, rank, actions
- Per-row accept/reject toggle (algorithm_draft ↔ published / algorithm_rejected)
- Bulk approve selected button
- Explanation modal per proposal
- Relaxed constraints banner (if any)
- Reset draft / reset published bulk ops

---

## Navigation

Add `nav.algorithm: "ניהול אלגוריתם"` to `he.json`.

Add to `ManageSheet.tsx` under the Planning section (canManageDuties):
```tsx
<Link to="/algorithm" onClick={onClose} className={linkClass}>{t("nav.algorithm")}</Link>
```

Add to `App.tsx` inside the existing `<Route element={<ProtectedRoute />}>` block:
```tsx
<Route path="/algorithm" element={<ForcedPasswordGate><AlgorithmPage /></ForcedPasswordGate>} />
```

`AlgorithmPage` itself redirects to `/` if the user lacks `canManageDuties` (same pattern as other role-gated pages).

---

## Out of Scope

- Real-time WebSocket progress (polling is sufficient given job duration)
- Admin view of other users' jobs
- Job cancellation
- Telegram push notifications for algorithm jobs (can be opted in via existing preferences UI)
