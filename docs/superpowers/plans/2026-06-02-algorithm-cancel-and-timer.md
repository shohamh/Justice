# Algorithm Job Cancellation and Timer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow a running algorithm job to be genuinely interrupted (stopping the CP-SAT solver mid-search via OR-Tools' `StopSearch()`), and show an elapsed timer + cancel button while the job runs in `AlgorithmPage`.

**Architecture:** A process-level `_cancel_events` dict in `algorithm_bridge.py` maps job IDs to `threading.Event` objects. The cancel endpoint sets the event and the DB status; a daemon watcher thread in `_solve_with_settings` calls `solver.StopSearch()` when the event fires, causing `solver.Solve()` to return with UNKNOWN status. `_infeasibility_relaxation_chain` checks for non-standard status and returns `SolverResult(status="CANCELLED")`. `run_algorithm_job` exits early on CANCELLED without post-processing. The frontend adds a cancel button and live elapsed timer to the right panel of `AlgorithmPage`.

**Tech Stack:** Python 3.13, OR-Tools CP-SAT (`CpSolver.StopSearch()`), `threading.Event`, FastAPI; React 18, TypeScript, Tailwind CSS

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `backend/app/algorithm/solver.py` | Add `cancel_event` param, watcher thread, UNKNOWN status guard |
| Modify | `backend/app/services/algorithm_bridge.py` | Add `_cancel_events` dict, register/signal/cleanup in `run_algorithm_job` |
| Modify | `backend/app/routes/algorithm.py` | Signal cancel event + add `finished_at` to `cancel_job` |
| Create | `backend/tests/integration/test_algorithm_cancel.py` | Test cancel endpoint behaviour |
| Modify | `frontend/src/api/algorithm.ts` | Add `cancelJob()` |
| Modify | `frontend/src/pages/AlgorithmPage.tsx` | Cancel button, elapsed timer, cancelled job display |
| Modify | `frontend/src/i18n/he.json` | Add `algorithm.cancel_btn` key |

---

## Task 1: Backend — solver cancellation support

**Files:**
- Modify: `backend/app/algorithm/solver.py`

- [ ] **Step 1: Rewrite solver.py with cancellation support**

Read `backend/app/algorithm/solver.py` first. Then replace its entire contents with:

```python
from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import TYPE_CHECKING

from ortools.sat.python.cp_model import CpSolver, IntVar

from app.algorithm.model import build_model
from app.algorithm.types import (
    Assignment,
    DutyBlock,
    ExistingAssignment,
    SoldierInput,
    SolverResult,
    SolverSettings,
)

if TYPE_CHECKING:
    pass


def _watch_cancel(solver: CpSolver, event: threading.Event) -> None:
    """Daemon thread: calls StopSearch when the cancel event fires."""
    event.wait()
    solver.StopSearch()


def solve(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = None,
    cancel_event: threading.Event | None = None,
) -> SolverResult:
    """Build the CP-SAT model and solve it. Returns assignments + metrics."""
    return _infeasibility_relaxation_chain(soldiers, duties, existing, settings, reserve_dist, cancel_event=cancel_event)


def _solve_with_settings(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[CpSolver, dict[tuple[int, int], IntVar], int]:
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


def _infeasibility_relaxation_chain(
    soldiers: Sequence[SoldierInput],
    duties: Sequence[DutyBlock],
    existing: Sequence[ExistingAssignment],
    settings: SolverSettings,
    reserve_dist: dict[tuple[int, int], int] | None = None,
    cancel_event: threading.Event | None = None,
) -> SolverResult:
    current = SolverSettings(
        K=settings.K, T=settings.T, W=settings.W,
        alpha=settings.alpha, beta=settings.beta,
        time_limit_seconds=settings.time_limit_seconds,
        seed=settings.seed,
        reserve_hierarchy_weight=settings.reserve_hierarchy_weight,
    )
    relaxed: list[str] = []

    for attempt in range(5):
        solver, x, status = _solve_with_settings(soldiers, duties, existing, current, reserve_dist, cancel_event=cancel_event)
        status_name = solver.StatusName(status)

        # UNKNOWN means StopSearch() fired before a solution was found — treat as cancelled
        if status_name not in ("OPTIMAL", "FEASIBLE", "INFEASIBLE"):
            return SolverResult(assignments=[], status="CANCELLED", seed=current.seed or 0, relaxed=relaxed)

        if status_name == "INFEASIBLE":
            if attempt < 3:
                current.K = current.K + 1
                relaxed.append(f"K→{current.K}")
                continue
            elif attempt < 4:
                current.T = current.T + 1
                relaxed.append(f"T→{current.T}")
                continue
            return SolverResult(
                assignments=[], status="INFEASIBLE",
                seed=current.seed or 0, relaxed=relaxed,
            )

        assignments: list[Assignment] = []
        for (di, si), var in x.items():
            if solver.Value(var):
                assignments.append(Assignment(
                    duty_id=duties[di].id,
                    soldier_id=soldiers[si].id,
                ))

        assignments.sort(key=lambda a: a.duty_id)

        return SolverResult(
            assignments=assignments,
            status=status_name,
            objective_value=solver.ObjectiveValue() if status_name in ("OPTIMAL", "FEASIBLE") else None,
            seed=current.seed or 0,
            solver_metrics={
                "wall_time": solver.WallTime(),
                "conflicts": solver.NumConflicts(),
                "branches": solver.NumBranches(),
            },
            relaxed=relaxed,
        )

    return SolverResult(
        assignments=[], status="INFEASIBLE",
        seed=current.seed or 0, relaxed=relaxed,
    )
```

- [ ] **Step 2: Run existing backend tests to verify no regressions**

```bash
cd C:\Users\Shoham\workspace\callofduty2\backend && uv run pytest tests/unit/test_algorithm_bridge_shifts.py tests/integration/test_algorithm_shifts.py -v 2>&1 | tail -15
```
Expected: all existing tests pass.

- [ ] **Step 3: Commit**

```bash
git -C C:\Users\Shoham\workspace\callofduty2 add backend/app/algorithm/solver.py
git -C C:\Users\Shoham\workspace\callofduty2 commit -m "feat: add cancel_event support to CP-SAT solver"
```

---

## Task 2: Backend — algorithm_bridge.py and cancel endpoint

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py`
- Modify: `backend/app/routes/algorithm.py`
- Create: `backend/tests/integration/test_algorithm_cancel.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_algorithm_cancel.py`:

```python
from __future__ import annotations

import time
from decimal import Decimal

from app.db.models import AlgorithmJob, DutyLocation, DutyShift, DutyType
from tests.helpers import auth_headers, create_node, create_soldier


def _setup(session, pn: str):
    node = create_node(session, level="branch", name=f"n_{pn}")
    dm = create_soldier(session, personal_number=pn, role="duty_manager", hierarchy_node_id=node.id)
    dt = DutyType(name=f"t_{pn}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"l_{pn}")
    session.add(dt); session.add(loc); session.flush()
    shift = DutyShift(
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date="2028-06-01",
        end_date="2028-06-01",
        required_count=1,
    )
    session.add(shift)
    session.commit()
    return dm, shift


def test_cancel_sets_failed_and_finished_at(client, admin_session):
    dm, shift = _setup(admin_session, "cancel_001")
    create_soldier(admin_session, personal_number="cancel_001s")
    admin_session.commit()

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"K": 8, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 60},
        },
        headers=auth_headers(dm),
    )
    assert create_resp.status_code == 202
    job_id = create_resp.json()["id"]

    # Give the job a moment to transition to "running"
    time.sleep(1)

    cancel_resp = client.delete(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
    assert cancel_resp.status_code == 204

    admin_session.expire_all()
    job = admin_session.get(AlgorithmJob, job_id)
    assert job is not None
    assert job.status == "failed"
    assert job.error_message == "cancelled_by_user"
    assert job.finished_at is not None


def test_cancel_returns_409_for_done_job(client, admin_session):
    dm, shift = _setup(admin_session, "cancel_002")
    create_soldier(admin_session, personal_number="cancel_002s")
    admin_session.commit()

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"K": 20, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 10},
        },
        headers=auth_headers(dm),
    )
    job_id = create_resp.json()["id"]

    # Wait for job to complete
    for _ in range(15):
        poll = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        if poll.json()["status"] in ("done", "failed"):
            break
        time.sleep(2)

    cancel_resp = client.delete(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
    assert cancel_resp.status_code == 409
    assert cancel_resp.json()["detail"] == "not_cancellable"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:\Users\Shoham\workspace\callofduty2\backend && uv run pytest tests/integration/test_algorithm_cancel.py::test_cancel_sets_failed_and_finished_at -v 2>&1 | tail -10
```
Expected: FAIL — `assert job.finished_at is not None` (finished_at not yet set by cancel endpoint)

- [ ] **Step 3: Update algorithm_bridge.py**

Read `backend/app/services/algorithm_bridge.py` to confirm exact line numbers. Then make these changes:

**3a.** Add `import threading` and the `_cancel_events` dict at the module level (near the top of the file, after existing imports):

```python
import threading

_cancel_events: dict[str, threading.Event] = {}
```

**3b.** Rewrite `run_algorithm_job` to add: event registration/cleanup, early-exit for pre-cancelled jobs, and passing `cancel_event` to `solve`. The new function body (keep all existing logic unchanged except where marked):

```python
def run_algorithm_job(job_id: uuid.UUID, actor_id: uuid.UUID | None) -> None:
    """Background task: load data, run solver, persist results."""
    from app.algorithm.explain import build_explanations
    from app.algorithm.reserve import compute_reserve_dist
    from app.algorithm.solver import solve
    from app.db.session import session_scope
    from app.services.settings_loader import get_setting

    cancel_event = threading.Event()
    _cancel_events[str(job_id)] = cancel_event

    try:
        with session_scope() as session:
            job = session.get(AlgorithmJob, job_id)
            if job is None:
                return

            # Job cancelled before background task started
            if job.status == "failed":
                return

            job.status = "running"
            job.started_at = datetime.now(tz=timezone.utc)
            session.commit()

            try:
                def _setting_decimal(key: str, default: str) -> Decimal:
                    try:
                        return Decimal(str(get_setting(session, key)))
                    except Exception:
                        return Decimal(default)

                settings = SolverSettings(
                    K=Decimal(str(job.settings_json.get("K", 8))),
                    T=int(job.settings_json.get("T", 7)),
                    W=int(job.settings_json.get("W", 14)),
                    alpha=Decimal(str(job.settings_json.get("alpha", 1.0))),
                    beta=Decimal(str(job.settings_json.get("beta", 2.0))),
                    time_limit_seconds=int(job.settings_json.get("time_limit_seconds", 30)),
                    reserve_hierarchy_weight=_setting_decimal("fairness.reserve_hierarchy_weight", "0.5"),
                )
                standby_multiplier = _setting_decimal("scoring.reserve_standby_multiplier", "0.2")

                shift_ids = [uuid.UUID(s) for s in job.shift_ids]
                duties, block_to_shift_map = load_duty_blocks_from_shifts(
                    session, shift_ids=shift_ids, standby_multiplier=standby_multiplier,
                )

                if not duties:
                    job.status = "failed"
                    job.error_message = "no_shifts_selected"
                    job.finished_at = datetime.now(tz=timezone.utc)
                    session.commit()
                    return

                planning_start = min(d.start_date for d in duties)
                planning_end = max(d.end_date for d in duties)

                soldiers = load_soldier_inputs(session, as_of=planning_start)
                existing = load_existing_assignments(
                    session,
                    planning_start=planning_start,
                    planning_end=planning_end,
                    W=settings.W,
                )

                if not soldiers:
                    job.status = "failed"
                    job.error_message = "no_soldiers_or_duties"
                    job.finished_at = datetime.now(tz=timezone.utc)
                    session.commit()
                    return

                hier_parent, hier_children, soldier_node, node_soldiers = build_hierarchy_maps(session)

                reserve_dist = compute_reserve_dist(
                    soldiers=soldiers, duties=duties, block_to_shift=block_to_shift_map,
                    hierarchy_parent=hier_parent, soldier_node=soldier_node,
                )

                result = solve(soldiers, duties, existing, settings, reserve_dist=reserve_dist, cancel_event=cancel_event)

                # Solver was interrupted by cancellation — DB already marked failed
                if result.status == "CANCELLED":
                    session.rollback()
                    return

                if result.status == "INFEASIBLE":
                    from app.algorithm.diagnose import diagnose_infeasibility
                    dt_names = {
                        dt.id: dt.name
                        for dt in session.execute(select(DutyType)).scalars().all()
                    }
                    reasons = diagnose_infeasibility(soldiers, duties, existing, dt_names)
                    job.status = "failed"
                    job.error_message = json.dumps({
                        "relaxed": result.relaxed,
                        "status": "INFEASIBLE",
                        "reasons": reasons,
                    })
                    job.finished_at = datetime.now(tz=timezone.utc)
                    session.commit()
                    return

                explanation_data = build_explanations(
                    soldiers=soldiers,
                    duties=duties,
                    assignments=result.assignments,
                    global_before={},
                    global_after={},
                    solver_seed=result.seed,
                )

                soldier_names = {
                    s.id: s.full_name
                    for s in session.execute(select(Soldier)).scalars().all()
                }

                persist_results(
                    session,
                    job=job,
                    result=result,
                    explanation_data=explanation_data,
                    duty_blocks=duties,
                    soldier_names=soldier_names,
                    actor_id=actor_id,
                    block_to_shift_map=block_to_shift_map,
                    hierarchy_parent=hier_parent,
                    hierarchy_children=hier_children,
                    soldier_node=soldier_node,
                )

                # Check if job was cancelled while the solver was running
                session.refresh(job)
                if job.status == "failed":
                    # Cancelled externally — don't overwrite the cancellation
                    session.rollback()
                    return

                job.status = "done"
                job.finished_at = datetime.now(tz=timezone.utc)

                if job.created_by:
                    from app.db.models import NotificationType
                    from app.services.notifications import create_notification
                    proposal_count = _count_proposals_for_job(session, job)
                    create_notification(
                        session,
                        soldier_id=job.created_by,
                        type=NotificationType.algorithm_job_done,
                        title=f"הרצת האלגוריתם הסתיימה — {proposal_count} הצעות ממתינות לאישור",
                        reference_type="algorithm_job",
                        reference_id=job.id,
                    )

                session.commit()

            except Exception as exc:  # noqa: BLE001
                session.rollback()
                with session_scope() as err_session:
                    err_job = err_session.get(AlgorithmJob, job_id)
                    if err_job is not None:
                        err_job.status = "failed"
                        err_job.error_message = str(exc)
                        err_job.finished_at = datetime.now(tz=timezone.utc)

                        if err_job.created_by:
                            from app.db.models import NotificationType
                            from app.services.notifications import create_notification
                            body = str(exc)[:200] if str(exc) else None
                            create_notification(
                                err_session,
                                soldier_id=err_job.created_by,
                                type=NotificationType.algorithm_job_failed,
                                title="הרצת האלגוריתם נכשלה",
                                body=body,
                                reference_type="algorithm_job",
                                reference_id=err_job.id,
                            )

                        err_session.commit()
    finally:
        _cancel_events.pop(str(job_id), None)
```

- [ ] **Step 4: Update the cancel_job endpoint in algorithm.py**

In `backend/app/routes/algorithm.py`, find the `cancel_job` function (around line 361). The `datetime` import is already at the top of the file. Replace the function body:

```python
@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def cancel_job(
    job_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    from datetime import datetime, timezone
    job = _load_job(session, job_id)
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    if job.status not in ("pending", "running"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_cancellable")
    job.status = "failed"
    job.error_message = "cancelled_by_user"
    job.finished_at = datetime.now(tz=timezone.utc)
    session.commit()

    from app.services.algorithm_bridge import _cancel_events
    event = _cancel_events.get(str(job_id))
    if event:
        event.set()
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd C:\Users\Shoham\workspace\callofduty2\backend && uv run pytest tests/integration/test_algorithm_cancel.py -v 2>&1 | tail -15
```
Expected: Both tests PASS (first test ~2–5s, second ~20s).

- [ ] **Step 6: Run the full existing backend test suite to check for regressions**

```bash
cd C:\Users\Shoham\workspace\callofduty2\backend && uv run pytest tests/integration/test_algorithm_jobs_list.py tests/integration/test_algorithm_notification.py tests/integration/test_algorithm_shifts.py -v 2>&1 | tail -15
```
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git -C C:\Users\Shoham\workspace\callofduty2 add backend/app/services/algorithm_bridge.py backend/app/routes/algorithm.py backend/tests/integration/test_algorithm_cancel.py
git -C C:\Users\Shoham\workspace\callofduty2 commit -m "feat: cancel algorithm job and interrupt CP-SAT solver via threading.Event"
```

---

## Task 3: Frontend — cancel button, elapsed timer, cancelled display

**Files:**
- Modify: `frontend/src/api/algorithm.ts`
- Modify: `frontend/src/pages/AlgorithmPage.tsx`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add cancelJob() to algorithm.ts**

In `frontend/src/api/algorithm.ts`, add at the end of the file:

```typescript
export async function cancelJob(id: string): Promise<void> {
  await api.delete(`/algorithm/jobs/${id}`);
}
```

- [ ] **Step 2: Add i18n key**

In `frontend/src/i18n/he.json`, inside the `"algorithm"` block (before the closing `}`), add:

```json
    "cancel_btn": "בטל הרצה",
    "cancelled": "ההרצה בוטלה"
```

- [ ] **Step 3: Update AlgorithmPage.tsx**

Read `frontend/src/pages/AlgorithmPage.tsx` first.

**3a.** Add `cancelJob` to the import from `../api/algorithm`:
```tsx
import { AlgorithmJob, JobSummaryOut, listJobs, pollJob, cancelJob } from "../api/algorithm";
```

**3b.** Add the `handleCancel` function after `handleJobSubmitted` (around line 92):
```tsx
  async function handleCancel() {
    if (!selectedJobId) return;
    try {
      await cancelJob(selectedJobId);
    } catch { /* 409 = already done, ignore */ }
  }
```

**3c.** Replace the running indicator in the right panel job header (currently lines 167-169):

Find this block:
```tsx
                {(selectedJob.status === "pending" || selectedJob.status === "running") && (
                  <p className="text-gray-600 animate-pulse">{t("algorithm.running")}</p>
                )}
```

Replace with:
```tsx
                {(selectedJob.status === "pending" || selectedJob.status === "running") && (
                  <div className="flex items-center gap-3">
                    <p className="text-gray-600 animate-pulse text-sm">
                      {selectedJob.started_at
                        ? `${t("algorithm.running")} (${Math.floor((Date.now() - new Date(selectedJob.started_at).getTime()) / 1000)}s)`
                        : t("algorithm.running")}
                    </p>
                    <button
                      onClick={handleCancel}
                      className="text-xs text-red-600 hover:text-red-800 border border-red-300 rounded px-2 py-0.5"
                    >
                      {t("algorithm.cancel_btn")}
                    </button>
                  </div>
                )}
```

**3d.** Update the failed state block to detect `cancelled_by_user` and display it neutrally. Find the failed state block (currently lines 173-190):

```tsx
              {/* Failed state */}
              {selectedJob.status === "failed" && (() => {
                let parsed: { reasons?: string[] } | null = null;
                try { parsed = JSON.parse(selectedJob.error_message ?? "{}"); } catch { /* plain string */ }
                const reasons = parsed?.reasons ?? [];
                return (
                  <div className="text-red-600 text-sm space-y-1">
                    <p className="font-medium">{t("algorithm.failed")}</p>
                    {reasons.length > 0 && (
                      <ul className="list-disc pr-5 space-y-0.5 text-xs">
                        {reasons.map((r, i) => <li key={i}>{r}</li>)}
                      </ul>
                    )}
                    {reasons.length === 0 && selectedJob.error_message && (
                      <p className="text-xs">{selectedJob.error_message}</p>
                    )}
                  </div>
                );
              })()}
```

Replace with:
```tsx
              {/* Failed state */}
              {selectedJob.status === "failed" && (() => {
                if (selectedJob.error_message === "cancelled_by_user") {
                  return <p className="text-sm text-gray-500">{t("algorithm.cancelled")}</p>;
                }
                let parsed: { reasons?: string[] } | null = null;
                try { parsed = JSON.parse(selectedJob.error_message ?? "{}"); } catch { /* plain string */ }
                const reasons = parsed?.reasons ?? [];
                return (
                  <div className="text-red-600 text-sm space-y-1">
                    <p className="font-medium">{t("algorithm.failed")}</p>
                    {reasons.length > 0 && (
                      <ul className="list-disc pr-5 space-y-0.5 text-xs">
                        {reasons.map((r, i) => <li key={i}>{r}</li>)}
                      </ul>
                    )}
                    {reasons.length === 0 && selectedJob.error_message && (
                      <p className="text-xs">{selectedJob.error_message}</p>
                    )}
                  </div>
                );
              })()}
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd C:\Users\Shoham\workspace\callofduty2\frontend && pnpm exec tsc --noEmit --skipLibCheck 2>&1 | head -20
```
Expected: no new errors.

- [ ] **Step 5: Run frontend tests**

```bash
cd C:\Users\Shoham\workspace\callofduty2\frontend && pnpm test 2>&1 | tail -10
```
Expected: 18/18 tests pass.

- [ ] **Step 6: Commit**

```bash
git -C C:\Users\Shoham\workspace\callofduty2 add frontend/src/api/algorithm.ts frontend/src/pages/AlgorithmPage.tsx frontend/src/i18n/he.json
git -C C:\Users\Shoham\workspace\callofduty2 commit -m "feat: add cancel button and elapsed timer to algorithm job panel"
```
