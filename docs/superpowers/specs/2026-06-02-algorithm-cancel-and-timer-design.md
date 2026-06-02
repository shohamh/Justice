# Algorithm Job Cancellation and Timer Design

**Date:** 2026-06-02  
**Status:** Approved

## Goal

Allow a running algorithm job to be genuinely interrupted (stopping the CP-SAT solver mid-search), and show an elapsed timer while the job runs.

## Background

The backend already has `DELETE /algorithm/jobs/{job_id}` which marks the DB as failed, and `run_algorithm_job` discards results if the DB status is already "failed" — but the OR-Tools CP-SAT solver continues running until its `time_limit_seconds` expires. `CpSolver.StopSearch()` can be called from another thread to interrupt the search immediately.

**Edge case:** When `StopSearch()` fires before any feasible solution is found, `solver.Solve()` returns status `UNKNOWN`. Accessing `solver.Value(var)` with UNKNOWN status crashes. The relaxation chain in `_infeasibility_relaxation_chain` must handle UNKNOWN status without crashing.

---

## Backend Changes

### `backend/app/algorithm/solver.py`

**`_solve_with_settings`** gains `cancel_event: threading.Event | None = None`. If provided, a daemon thread is started that calls `solver.StopSearch()` when the event fires:

```python
import threading

def _watch_cancel(solver: CpSolver, event: threading.Event) -> None:
    event.wait()
    solver.StopSearch()

def _solve_with_settings(
    soldiers, duties, existing, settings, reserve_dist=None,
    cancel_event: threading.Event | None = None,
) -> tuple[CpSolver, dict, int]:
    model, x = build_model(soldiers, duties, existing, settings, reserve_dist)
    solver = CpSolver()
    solver.parameters.max_time_in_seconds = settings.time_limit_seconds
    if settings.seed is not None:
        solver.parameters.random_seed = settings.seed
    solver.parameters.num_search_workers = 8
    if cancel_event is not None:
        threading.Thread(target=_watch_cancel, args=(solver, cancel_event), daemon=True).start()
    status = solver.Solve(model)
    return solver, x, status
```

**`_infeasibility_relaxation_chain`** gains `cancel_event` param. After each `_solve_with_settings` call, checks for cancellation before accessing `solver.Value()`:

```python
def _infeasibility_relaxation_chain(
    soldiers, duties, existing, settings, reserve_dist=None,
    cancel_event: threading.Event | None = None,
) -> SolverResult:
    ...
    for attempt in range(5):
        solver, x, status = _solve_with_settings(
            soldiers, duties, existing, current, reserve_dist,
            cancel_event=cancel_event
        )
        status_name = solver.StatusName(status)

        # Treat UNKNOWN (solver stopped early) as cancelled
        if status_name not in ("OPTIMAL", "FEASIBLE", "INFEASIBLE"):
            return SolverResult(assignments=[], status="CANCELLED", seed=current.seed or 0, relaxed=relaxed)

        if status_name == "INFEASIBLE":
            ...  # existing relaxation logic unchanged
```

**`solve`** gains `cancel_event` param and passes it through:

```python
def solve(..., cancel_event: threading.Event | None = None) -> SolverResult:
    return _infeasibility_relaxation_chain(
        soldiers, duties, existing, settings, reserve_dist,
        cancel_event=cancel_event
    )
```

### `backend/app/services/algorithm_bridge.py`

**Module-level dict:**
```python
import threading
_cancel_events: dict[str, threading.Event] = {}
```

**`run_algorithm_job` changes:**

1. Add early-exit at the very top of `run_algorithm_job` (right after loading the job) to handle jobs cancelled while still "pending":
```python
if job is None:
    return
# If job was cancelled before the background task started, exit without running
if job.status == "failed":
    return
```

2. Register the cancel event and wrap the entire job body in a `try/finally` for cleanup:
```python
cancel_event = threading.Event()
_cancel_events[str(job_id)] = cancel_event
try:
    # ... all existing job logic (status=running commit, solve, persist, done commit, exception handler)
finally:
    _cancel_events.pop(str(job_id), None)
```

3. Pass event to `solve`:
```python
result = solve(soldiers, duties, existing, settings, reserve_dist=reserve_dist, cancel_event=cancel_event)
```

4. Early-exit check right after `solve` returns (before `build_explanations`):
```python
if result.status == "CANCELLED":
    # DB already marked failed by cancel_job endpoint; nothing to persist
    session.rollback()
    return

session.refresh(job)
if job.status == "failed":
    session.rollback()
    return
```

### `backend/app/routes/algorithm.py`

**`cancel_job` endpoint** — after marking DB, signal the event:

```python
from datetime import datetime, timezone

@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def cancel_job(job_id, session, user):
    job = _load_job(session, job_id)
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    if job.status not in ("pending", "running"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_cancellable")
    job.status = "failed"
    job.error_message = "cancelled_by_user"
    job.finished_at = datetime.now(tz=timezone.utc)  # was missing before
    session.commit()

    from app.services.algorithm_bridge import _cancel_events
    event = _cancel_events.get(str(job_id))
    if event:
        event.set()
```

---

## Frontend Changes

### `frontend/src/api/algorithm.ts`

Add:
```typescript
export async function cancelJob(id: string): Promise<void> {
  await api.delete(`/algorithm/jobs/${id}`);
}
```

### `frontend/src/pages/AlgorithmPage.tsx`

**Elapsed timer:** Replace the static "האלגוריתם רץ..." line in the right panel with:

```tsx
{(selectedJob.status === "pending" || selectedJob.status === "running") && (
  <div className="flex items-center gap-3">
    <p className="text-gray-600 animate-pulse">
      {selectedJob.started_at
        ? `${t("algorithm.running")} (${Math.floor((Date.now() - new Date(selectedJob.started_at).getTime()) / 1000)}s)`
        : t("algorithm.running")}
    </p>
    <button
      onClick={handleCancel}
      className="text-xs text-red-600 hover:text-red-800 border border-red-300 rounded px-2 py-0.5"
    >
      בטל הרצה
    </button>
  </div>
)}
```

Since the right panel polls every 1s and re-renders, the elapsed time updates automatically with no extra interval.

**Cancel handler:**
```tsx
async function handleCancel() {
  if (!selectedJobId) return;
  try {
    await cancelJob(selectedJobId);
  } catch { /* 409 = already done, ignore */ }
}
```

**Cancelled job display:** Detect `error_message === "cancelled_by_user"` in the failed state block and show neutral styling:

```tsx
{selectedJob.status === "failed" && (() => {
  if (selectedJob.error_message === "cancelled_by_user") {
    return <p className="text-sm text-gray-500">ההרצה בוטלה</p>;
  }
  // ... existing red error display
})()}
```

**Import:** Add `cancelJob` to the `import { ..., cancelJob } from "../api/algorithm"` line.

---

## No notification for cancels

The `cancel_job` endpoint sets DB status directly. `run_algorithm_job` exits via the `result.status === "CANCELLED"` early return — this path does not hit the `except Exception` handler, so no `algorithm_job_failed` notification is created for intentional cancellations.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/algorithm/solver.py` | Add `cancel_event` param + watcher thread + UNKNOWN status guard |
| `backend/app/services/algorithm_bridge.py` | Add `_cancel_events` dict, register/signal/cleanup pattern |
| `backend/app/routes/algorithm.py` | Signal cancel event + add `finished_at` to cancel endpoint |
| `frontend/src/api/algorithm.ts` | Add `cancelJob()` |
| `frontend/src/pages/AlgorithmPage.tsx` | Cancel button + elapsed timer + cancelled display |
