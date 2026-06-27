# Algorithm Job Seen State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist per-user "seen" state for algorithm jobs to the database, clear the תכנון nav badge immediately when a job is clicked, and add a "mark all as seen" button.

**Architecture:** A new `algorithm_job_seen` junction table tracks which jobs each user has seen. The backend exposes two new endpoints (`POST /algorithm/jobs/{id}/seen` and `POST /algorithm/jobs/mark-all-seen`) and enriches the jobs list with a `seen` boolean per job. On the frontend, a React context (`AlgorithmSeenContext`) holds `seenIds` as state seeded from the API response; consuming components (`UnifiedNav`, `AlgorithmPage`, `ShiftsManagementPage`) subscribe to it so the badge re-renders immediately on any seen-state change without waiting for the next poll.

**Tech Stack:** Python/FastAPI/SQLAlchemy/Alembic (backend), React/TypeScript/Axios (frontend), Vitest (frontend tests), pytest (backend tests)

---

## File Map

**Create:**
- `backend/alembic/versions/0061_algorithm_job_seen.py` — migration
- `backend/tests/integration/test_algorithm_seen.py` — backend integration tests
- `frontend/src/contexts/AlgorithmSeenContext.tsx` — React context + hook

**Modify:**
- `backend/app/db/models.py` — add `AlgorithmJobSeen` model
- `backend/app/routes/algorithm.py` — add `seen` field to `JobSummaryOut`, update `list_jobs`, add two new endpoints
- `frontend/src/api/algorithm.ts` — add `seen` to `JobSummaryOut`, add `markJobSeen` and `markAllJobsSeen` helpers
- `frontend/src/main.tsx` — wrap app in `AlgorithmSeenProvider`
- `frontend/src/components/UnifiedNav.tsx` — use context `seenIds`, store jobs in state for reactive recompute
- `frontend/src/pages/AlgorithmPage.tsx` — call context `markJobSeen`, add "סמן הכל כנראה" button
- `frontend/src/pages/planning/ShiftsManagementPage.tsx` — use context `seenIds` + `markAllSeen`, add button
- `frontend/src/components/UnifiedNav.test.tsx` — mock `AlgorithmSeenContext`, update badge tests

**Delete:**
- `frontend/src/utils/seenAlgorithmJobs.ts` — replaced by context

---

## Task 1: Migration — create `algorithm_job_seen` table

**Files:**
- Create: `backend/alembic/versions/0061_algorithm_job_seen.py`

- [ ] **Step 1: Write the migration file**

```python
# backend/alembic/versions/0061_algorithm_job_seen.py
"""create algorithm_job_seen table

Revision ID: 0061
Revises: 0060
Create Date: 2026-06-28
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0061'
down_revision: Union[str, Sequence[str], None] = '0060'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "algorithm_job_seen",
        sa.Column("job_id", sa.UUID(as_uuid=True), sa.ForeignKey("algorithm_jobs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("algorithm_job_seen")
```

- [ ] **Step 2: Apply migration**

```powershell
cd backend
.\.venv\Scripts\activate
alembic upgrade head
```

Expected: `Running upgrade 0060 -> 0061, create algorithm_job_seen table`

- [ ] **Step 3: Commit**

```bash
git add backend/alembic/versions/0061_algorithm_job_seen.py
git commit -m "feat: add algorithm_job_seen migration"
```

---

## Task 2: Backend model + `list_jobs` with `seen`

**Files:**
- Modify: `backend/app/db/models.py` (after the `AlgorithmJob` class, around line 630)
- Modify: `backend/app/routes/algorithm.py:113-130` (JobSummaryOut), `571-612` (list_jobs)

- [ ] **Step 1: Write the failing integration test**

Create `backend/tests/integration/test_algorithm_seen.py`:

```python
from __future__ import annotations

from decimal import Decimal

from app.db.models import DutyLocation, DutyShift, DutyType
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
        start_date="2027-03-01",
        end_date="2027-03-01",
        required_count=1,
    )
    session.add(shift)
    session.commit()
    return dm, shift


def _create_job(client, dm, shift):
    resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"T": 7, "W": 14, "alpha": 1.0, "time_limit_seconds": 5},
        },
        headers=auth_headers(dm),
    )
    assert resp.status_code == 202
    return resp.json()["id"]


def test_list_jobs_seen_false_by_default(client, admin_session):
    dm, shift = _setup(admin_session, "seen_001")
    job_id = _create_job(client, dm, shift)
    resp = client.get("/api/algorithm/jobs", headers=auth_headers(dm))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == job_id
    assert items[0]["seen"] is False


def test_mark_job_seen_returns_204(client, admin_session):
    dm, shift = _setup(admin_session, "seen_002")
    job_id = _create_job(client, dm, shift)
    resp = client.post(f"/api/algorithm/jobs/{job_id}/seen", headers=auth_headers(dm))
    assert resp.status_code == 204


def test_mark_job_seen_idempotent(client, admin_session):
    dm, shift = _setup(admin_session, "seen_003")
    job_id = _create_job(client, dm, shift)
    client.post(f"/api/algorithm/jobs/{job_id}/seen", headers=auth_headers(dm))
    resp = client.post(f"/api/algorithm/jobs/{job_id}/seen", headers=auth_headers(dm))
    assert resp.status_code == 204


def test_mark_job_seen_reflected_in_list(client, admin_session):
    dm, shift = _setup(admin_session, "seen_004")
    job_id = _create_job(client, dm, shift)
    client.post(f"/api/algorithm/jobs/{job_id}/seen", headers=auth_headers(dm))
    resp = client.get("/api/algorithm/jobs", headers=auth_headers(dm))
    items = resp.json()["items"]
    assert items[0]["seen"] is True


def test_mark_all_seen_returns_204(client, admin_session):
    dm, shift = _setup(admin_session, "seen_005")
    _create_job(client, dm, shift)
    resp = client.post("/api/algorithm/jobs/mark-all-seen", headers=auth_headers(dm))
    assert resp.status_code == 204


def test_seen_is_per_user(client, admin_session):
    """One user marking a job seen does not affect another user's view."""
    node = create_node(admin_session, level="branch", name="n_seen_006")
    dm1 = create_soldier(admin_session, personal_number="seen_006a", role="duty_manager", hierarchy_node_id=node.id)
    dm2 = create_soldier(admin_session, personal_number="seen_006b", role="duty_manager", hierarchy_node_id=node.id)
    dt = DutyType(name="t_seen_006", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="l_seen_006")
    admin_session.add(dt); admin_session.add(loc); admin_session.flush()
    shift = DutyShift(duty_type_id=dt.id, duty_location_id=loc.id, start_date="2027-04-01", end_date="2027-04-01", required_count=1)
    admin_session.add(shift); admin_session.commit()

    # dm1 creates a job and marks it seen
    job_id = _create_job(client, dm1, shift)
    client.post(f"/api/algorithm/jobs/{job_id}/seen", headers=auth_headers(dm1))

    # dm1 sees it as seen=True; dm2 has no jobs of their own so list is empty
    items1 = client.get("/api/algorithm/jobs", headers=auth_headers(dm1)).json()["items"]
    assert items1[0]["seen"] is True

    # dm2 creates their own job — it is not seen
    job_id2 = _create_job(client, dm2, shift)
    items2 = client.get("/api/algorithm/jobs", headers=auth_headers(dm2)).json()["items"]
    assert items2[0]["id"] == job_id2
    assert items2[0]["seen"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
cd backend
.\.venv\Scripts\activate
pytest tests/integration/test_algorithm_seen.py -v
```

Expected: FAIL with `KeyError: 'seen'` or similar (field not present yet)

- [ ] **Step 3: Add `AlgorithmJobSeen` model to `models.py`**

Add after the `AlgorithmJob` class (after line 629), before `class DutyDismissal`:

```python
class AlgorithmJobSeen(Base):
    __tablename__ = "algorithm_job_seen"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("algorithm_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE"), primary_key=True
    )
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 4: Update `JobSummaryOut` in `routes/algorithm.py`**

Change (line 113-126):
```python
class JobSummaryOut(BaseModel):
    id: uuid.UUID
    status: str
    mode: str
    planning_start: date
    planning_end: date
    shift_count: int
    created_at: Any
    started_at: Any
    finished_at: Any
    error_message: str | None
    total_duties: int = 0
    assigned_duties: int = 0
    seen: bool = False
```

- [ ] **Step 5: Import `AlgorithmJobSeen` in `routes/algorithm.py` and update `list_jobs`**

At the top of the file, add `AlgorithmJobSeen` to the models import (line 14-23):

```python
from app.db.models import (
    AlgorithmJob,
    AlgorithmJobSeen,
    AssignmentExplanation,
    AuditLog,
    DutyAssignment,
    DutyReserveLink,
    DutyShift,
    DutyType,
    Soldier,
)
```

Replace `list_jobs` (lines 570-612):

```python
@router.get("/jobs", response_model=JobListOut)
def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> JobListOut:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)

    from sqlalchemy import func

    total = session.execute(
        select(func.count()).select_from(AlgorithmJob).where(AlgorithmJob.created_by == user.id)
    ).scalar_one()

    seen_subq = (
        select(AlgorithmJobSeen.job_id)
        .where(
            AlgorithmJobSeen.job_id == AlgorithmJob.id,
            AlgorithmJobSeen.user_id == user.id,
        )
        .exists()
    )

    rows = session.execute(
        select(AlgorithmJob, seen_subq.label("seen"))
        .where(AlgorithmJob.created_by == user.id)
        .order_by(AlgorithmJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return JobListOut(
        items=[
            JobSummaryOut(
                id=j.id,
                status=j.status,
                mode=j.mode,
                planning_start=j.planning_start,
                planning_end=j.planning_end,
                shift_count=len(j.shift_ids),
                created_at=j.created_at,
                started_at=j.started_at,
                finished_at=j.finished_at,
                error_message=j.error_message,
                total_duties=j.total_duties,
                assigned_duties=j.assigned_duties,
                seen=bool(seen),
            )
            for j, seen in rows
        ],
        total=total,
    )
```

- [ ] **Step 6: Run tests — expect still failing (endpoints not added yet)**

```powershell
pytest tests/integration/test_algorithm_seen.py::test_list_jobs_seen_false_by_default -v
```

Expected: PASS (seen field now present)

```powershell
pytest tests/integration/test_algorithm_seen.py::test_mark_job_seen_returns_204 -v
```

Expected: FAIL with 404 or 405 (endpoint not yet defined)

- [ ] **Step 7: Commit progress**

```bash
git add backend/app/db/models.py backend/app/routes/algorithm.py backend/tests/integration/test_algorithm_seen.py
git commit -m "feat: add seen field to JobSummaryOut and list_jobs query"
```

---

## Task 3: Backend — mark-seen endpoints

**Files:**
- Modify: `backend/app/routes/algorithm.py` (add two endpoints after `list_jobs`)

- [ ] **Step 1: Add `mark_job_seen` endpoint**

Add after the `list_jobs` function (before `get_job`):

```python
@router.post("/jobs/{job_id}/seen", status_code=204)
def mark_job_seen(
    job_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    job = session.get(AlgorithmJob, job_id)
    if job is None or job.created_by != user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    session.execute(
        insert(AlgorithmJobSeen)
        .values(job_id=job_id, user_id=user.id)
        .on_conflict_do_nothing()
    )
    session.commit()


@router.post("/jobs/mark-all-seen", status_code=204)
def mark_all_jobs_seen(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    job_ids = session.execute(
        select(AlgorithmJob.id).where(
            AlgorithmJob.created_by == user.id,
            AlgorithmJob.status.notin_(["pending", "running"]),
            ~(
                (AlgorithmJob.status == "failed")
                & (AlgorithmJob.error_message == "cancelled_by_user")
            ),
        )
    ).scalars().all()
    if job_ids:
        session.execute(
            insert(AlgorithmJobSeen)
            .values([{"job_id": jid, "user_id": user.id} for jid in job_ids])
            .on_conflict_do_nothing()
        )
        session.commit()
```

Note: `insert` is already imported at line 8. `HTTPException` is already imported at line 6.

Also verify that `mark_all_jobs_seen` is registered **before** `get_job` in the file. FastAPI matches routes in registration order; since `mark-all-seen` is a literal path and `{job_id}` expects a UUID, there is no actual conflict, but placing it first is cleaner.

- [ ] **Step 2: Run all seen tests**

```powershell
cd backend
pytest tests/integration/test_algorithm_seen.py -v
```

Expected: All 6 tests PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/routes/algorithm.py
git commit -m "feat: add mark_job_seen and mark_all_jobs_seen endpoints"
```

---

## Task 4: Frontend API layer

**Files:**
- Modify: `frontend/src/api/algorithm.ts`

- [ ] **Step 1: Add `seen` to `JobSummaryOut` interface**

In `frontend/src/api/algorithm.ts`, update the `JobSummaryOut` interface (around line 124):

```typescript
export interface JobSummaryOut {
  id: string;
  status: "pending" | "running" | "done" | "failed";
  mode: string;
  planning_start: string;
  planning_end: string;
  shift_count: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  total_duties: number;
  assigned_duties: number;
  seen: boolean;
}
```

- [ ] **Step 2: Add the two new API helper functions**

At the end of `frontend/src/api/algorithm.ts` (after `listJobs`), add:

```typescript
export async function markJobSeen(jobId: string): Promise<void> {
  await api.post(`/algorithm/jobs/${jobId}/seen`);
}

export async function markAllJobsSeen(): Promise<void> {
  await api.post("/algorithm/jobs/mark-all-seen");
}
```

- [ ] **Step 3: Run typecheck**

```powershell
cd frontend
npm run typecheck
```

Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/algorithm.ts
git commit -m "feat: add seen field to JobSummaryOut interface and API helpers"
```

---

## Task 5: Create `AlgorithmSeenContext`

**Files:**
- Create: `frontend/src/contexts/AlgorithmSeenContext.tsx`

- [ ] **Step 1: Create the context file**

```tsx
// frontend/src/contexts/AlgorithmSeenContext.tsx
import { createContext, useCallback, useContext, useState } from "react";
import { markJobSeen as apiMarkJobSeen, markAllJobsSeen as apiMarkAllJobsSeen, JobSummaryOut } from "../api/algorithm";

interface AlgorithmSeenContextValue {
  seenIds: ReadonlySet<string>;
  /** Call after any jobs list fetch to merge server-side seen state into local state. */
  seedSeenIds: (items: Pick<JobSummaryOut, "id" | "seen">[]) => void;
  /** Mark a single job seen — calls the backend and updates local state immediately. */
  markJobSeen: (jobId: string) => Promise<void>;
  /** Mark all known non-running/non-pending jobs as seen. Pass the full job ID list. */
  markAllSeen: (allJobIds: string[]) => Promise<void>;
}

const AlgorithmSeenContext = createContext<AlgorithmSeenContextValue | null>(null);

export function AlgorithmSeenProvider({ children }: { children: React.ReactNode }) {
  const [seenIds, setSeenIds] = useState<ReadonlySet<string>>(new Set());

  const seedSeenIds = useCallback((items: Pick<JobSummaryOut, "id" | "seen">[]) => {
    const newIds = items.filter((i) => i.seen).map((i) => i.id);
    if (newIds.length === 0) return;
    setSeenIds((prev) => {
      const merged = new Set(prev);
      for (const id of newIds) merged.add(id);
      return merged;
    });
  }, []);

  const markJobSeen = useCallback(async (jobId: string) => {
    await apiMarkJobSeen(jobId);
    setSeenIds((prev) => {
      if (prev.has(jobId)) return prev;
      const next = new Set(prev);
      next.add(jobId);
      return next;
    });
  }, []);

  const markAllSeen = useCallback(async (allJobIds: string[]) => {
    await apiMarkAllJobsSeen();
    setSeenIds((prev) => {
      const next = new Set(prev);
      for (const id of allJobIds) next.add(id);
      return next;
    });
  }, []);

  return (
    <AlgorithmSeenContext.Provider value={{ seenIds, seedSeenIds, markJobSeen, markAllSeen }}>
      {children}
    </AlgorithmSeenContext.Provider>
  );
}

export function useSeenJobs(): AlgorithmSeenContextValue {
  const ctx = useContext(AlgorithmSeenContext);
  if (!ctx) throw new Error("useSeenJobs must be used inside AlgorithmSeenProvider");
  return ctx;
}
```

- [ ] **Step 2: Run typecheck**

```powershell
cd frontend
npm run typecheck
```

Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/contexts/AlgorithmSeenContext.tsx
git commit -m "feat: add AlgorithmSeenContext with seedSeenIds, markJobSeen, markAllSeen"
```

---

## Task 6: Wire provider in `main.tsx`

**Files:**
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: Add the provider**

Replace the contents of `frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import "./i18n";
import "./styles/globals.css";
import "katex/dist/katex.min.css";
import { AlgorithmSeenProvider } from "./contexts/AlgorithmSeenContext";

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AlgorithmSeenProvider>
          <App />
        </AlgorithmSeenProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 2: Run typecheck**

```powershell
cd frontend
npm run typecheck
```

Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/main.tsx
git commit -m "feat: wrap app in AlgorithmSeenProvider"
```

---

## Task 7: Update `UnifiedNav` to use context

**Files:**
- Modify: `frontend/src/components/UnifiedNav.tsx`
- Modify: `frontend/src/components/UnifiedNav.test.tsx`

- [ ] **Step 1: Update `UnifiedNav.tsx`**

Replace the algorithm badge `useEffect` and related state in `UnifiedNav.tsx`.

Remove the import:
```typescript
import { getSeenJobIds } from "../utils/seenAlgorithmJobs";
```

Add the import:
```typescript
import { useSeenJobs } from "../contexts/AlgorithmSeenContext";
```

Inside the component, after the existing state declarations, add:

```typescript
const { seenIds, seedSeenIds } = useSeenJobs();
const [algorithmJobs, setAlgorithmJobs] = useState<import("../utils/algorithmRunBadges").RunBadgeJob[]>([]);
```

And add the `RunBadgeJob` import at the top:
```typescript
import { computeRunBadgeCounts, RunBadgeCounts, RunBadgeJob } from "../utils/algorithmRunBadges";
```

Replace the entire algorithm badge `useEffect` (lines 79-97):

```typescript
useEffect(() => {
  if (!canPlan) return;

  async function fetchAlgorithmBadge() {
    try {
      const result = await listJobs(50);
      setAlgorithmJobs(result.items);
      seedSeenIds(result.items);
    } catch {
      // ignore
    }
  }

  void fetchAlgorithmBadge();

  const interval = setInterval(() => void fetchAlgorithmBadge(), 30_000);
  return () => clearInterval(interval);
}, [canPlan, location.pathname, seedSeenIds]);
```

Replace the two `useState` declarations for `algorithmBadgeCount` and `algorithmBadgeColor` with derived values computed from `algorithmJobs` and `seenIds`. Remove:

```typescript
const [algorithmBadgeCount, setAlgorithmBadgeCount] = useState(0);
const [algorithmBadgeColor, setAlgorithmBadgeColor] = useState<BadgeColor>("red");
```

Add (just after the `seenIds` / `algorithmJobs` declarations):

```typescript
const algorithmCounts = computeRunBadgeCounts(algorithmJobs, seenIds);
const algorithmBadgeCount = algorithmCounts.running + algorithmCounts.draft + algorithmCounts.done + algorithmCounts.failed;
const algorithmBadgeColor = pickBadgeColor(algorithmCounts);
```

The full resulting state/derived block near the top of the component body should look like:

```typescript
const [pendingCount, setPendingCount] = useState(0);
const [swapIncomingCount, setSwapIncomingCount] = useState(0);
const [commanderSheetOpen, setCommanderSheetOpen] = useState(false);
const [planningSheetOpen, setPlanningSheetOpen] = useState(false);
const { seenIds, seedSeenIds } = useSeenJobs();
const [algorithmJobs, setAlgorithmJobs] = useState<RunBadgeJob[]>([]);
const algorithmCounts = computeRunBadgeCounts(algorithmJobs, seenIds);
const algorithmBadgeCount = algorithmCounts.running + algorithmCounts.draft + algorithmCounts.done + algorithmCounts.failed;
const algorithmBadgeColor = pickBadgeColor(algorithmCounts);
```

- [ ] **Step 2: Update `UnifiedNav.test.tsx` to mock the context**

The tests currently mock `listJobs` via `vi.mock("../api/algorithm", ...)` and the component computes badge counts from the returned items. With the new code, the component still calls `listJobs` and stores jobs, then passes `seenIds` from context to `computeRunBadgeCounts`. We need to mock the context so tests can control `seenIds`.

Add a mock for the context at the top of the test file, after the existing mocks:

```typescript
import { vi } from "vitest";

// Mock the seen context — most tests just want seenIds = empty set
const mockSeedSeenIds = vi.fn();
vi.mock("../contexts/AlgorithmSeenContext", () => ({
  useSeenJobs: () => ({
    seenIds: new Set<string>(),
    seedSeenIds: mockSeedSeenIds,
    markJobSeen: vi.fn(),
    markAllSeen: vi.fn(),
  }),
}));
```

Add `beforeEach(() => { mockSeedSeenIds.mockReset(); });` inside the existing `beforeEach` or alongside it.

Also add a new test for the "seen job excluded from badge" behaviour in the algorithm badge color describe block:

```typescript
test("excludes a seen done job from the badge count", async () => {
  // Re-mock context with a non-empty seenIds for this one test
  const { useSeenJobs } = await import("../contexts/AlgorithmSeenContext");
  vi.mocked(useSeenJobs).mockReturnValueOnce({
    seenIds: new Set(["job-seen"]),
    seedSeenIds: vi.fn(),
    markJobSeen: vi.fn(),
    markAllSeen: vi.fn(),
  });
  mockListJobs.mockResolvedValue({
    items: [{ ...job("done", "shadow"), id: "job-seen", seen: true, total_duties: 0, assigned_duties: 0, created_at: "", started_at: null, finished_at: null, shift_count: 0 }],
    total: 1,
  });
  render(<UnifiedNav />);
  await waitFor(() => expect(mockListJobs).toHaveBeenCalled());
  expect(screen.queryByTestId("pending-badge")).not.toBeInTheDocument();
});
```

Note: the existing badge-color tests pass items without `seen` field; that's fine because `JobSummaryOut` has `seen: boolean` but the tests use a simplified `job()` helper. Update the `job()` helper in the test file to include `seen: false` and the required fields:

```typescript
function job(status: string, mode: string, error_message: string | null = null, id = "job-1") {
  return {
    id,
    status,
    mode,
    error_message,
    seen: false,
    total_duties: 0,
    assigned_duties: 0,
    created_at: "",
    started_at: null,
    finished_at: null,
    planning_start: "2027-01-01",
    planning_end: "2027-01-07",
    shift_count: 0,
  };
}
```

- [ ] **Step 3: Run typecheck and tests**

```powershell
cd frontend
npm run typecheck
npm test -- UnifiedNav
```

Expected: All `UnifiedNav` tests pass, no type errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/UnifiedNav.tsx frontend/src/components/UnifiedNav.test.tsx
git commit -m "feat: UnifiedNav reads seenIds from context for reactive badge updates"
```

---

## Task 8: Update `AlgorithmPage` to use context

**Files:**
- Modify: `frontend/src/pages/AlgorithmPage.tsx`

- [ ] **Step 1: Replace `markJobSeen` import and usage**

In `frontend/src/pages/AlgorithmPage.tsx`:

Remove:
```typescript
import { markJobSeen } from "../utils/seenAlgorithmJobs";
```

Add:
```typescript
import { useSeenJobs } from "../contexts/AlgorithmSeenContext";
```

Inside `AlgorithmContent`, destructure from context (add near the top of the function body, after the existing state declarations):

```typescript
const { markJobSeen, markAllSeen, seenIds } = useSeenJobs();
```

The existing `useEffect` that calls `markJobSeen` stays as-is (it now calls the async context version):

```typescript
useEffect(() => {
  if (!selectedJob) return;
  if (selectedJob.status === "pending" || selectedJob.status === "running") return;
  void markJobSeen(selectedJob.id);
}, [selectedJob, markJobSeen]);
```

Note: add `markJobSeen` to the dependency array.

- [ ] **Step 2: Seed context when jobs are loaded**

In `AlgorithmContent`, the `loadJobs` callback already sets `jobs` state. After `setJobs(result.items)`, also call `seedSeenIds`:

First add `seedSeenIds` to the destructure:
```typescript
const { markJobSeen, markAllSeen, seenIds, seedSeenIds } = useSeenJobs();
```

Update `loadJobs`:
```typescript
const loadJobs = useCallback(async () => {
  try {
    const result = await listJobs();
    setJobs(result.items);
    seedSeenIds(result.items);
  } catch { /* ignore */ }
}, [seedSeenIds]);
```

- [ ] **Step 3: Add "סמן הכל כנראה" button**

The job list header (around line 157 in the file) has:
```tsx
<div className="flex justify-between items-center p-3 border-b dark:border-gray-600">
  <h2 className="font-semibold text-sm">{t("algorithm.runs_title")}</h2>
  <Link
    to="/planning/shifts?autoAssign=1"
    className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
  >
    ריצה חדשה ←
  </Link>
</div>
```

Replace with:

```tsx
<div className="flex justify-between items-center p-3 border-b dark:border-gray-600">
  <h2 className="font-semibold text-sm">{t("algorithm.runs_title")}</h2>
  <div className="flex items-center gap-2">
    {jobs.some(j => (j.status === "done" || j.status === "failed") && j.error_message !== "cancelled_by_user" && !seenIds.has(j.id)) && (
      <button
        onClick={() => void markAllSeen(jobs.filter(j => (j.status === "done" || j.status === "failed") && j.error_message !== "cancelled_by_user").map(j => j.id))}
        className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
      >
        סמן הכל כנראה
      </button>
    )}
    <Link
      to="/planning/shifts?autoAssign=1"
      className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline"
    >
      ריצה חדשה ←
    </Link>
  </div>
</div>
```

- [ ] **Step 4: Run typecheck**

```powershell
cd frontend
npm run typecheck
```

Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AlgorithmPage.tsx
git commit -m "feat: AlgorithmPage uses context markJobSeen + mark-all-seen button"
```

---

## Task 9: Update `ShiftsManagementPage` to use context

**Files:**
- Modify: `frontend/src/pages/planning/ShiftsManagementPage.tsx`

- [ ] **Step 1: Replace `computeRunBadgeCounts` call with context-aware version**

In `frontend/src/pages/planning/ShiftsManagementPage.tsx`:

Add import:
```typescript
import { useSeenJobs } from "../../contexts/AlgorithmSeenContext";
```

Inside the component, destructure:
```typescript
const { seenIds, seedSeenIds, markAllSeen } = useSeenJobs();
```

Update `fetchRunBadgeCounts` to seed the context and pass `seenIds`:

```typescript
useEffect(() => {
  async function fetchRunBadgeCounts() {
    try {
      const result = await listJobs(50);
      seedSeenIds(result.items);
      setRunBadgeCounts(computeRunBadgeCounts(result.items, seenIds));
    } catch {
      // ignore — leave last known counts in place
    }
  }

  void fetchRunBadgeCounts();
  const interval = setInterval(() => void fetchRunBadgeCounts(), 30_000);
  return () => clearInterval(interval);
}, [latestJobId, seedSeenIds]);
```

Note: `seenIds` is intentionally NOT in the dependency array here — the effect's purpose is to fetch fresh data from the server; `seenIds` reactivity is handled by the useMemo below.

- [ ] **Step 2: Make the section badges reactive to `seenIds`**

Replace the `runBadgeCounts` state with a separate raw jobs state plus a derived value:

Remove:
```typescript
const [runBadgeCounts, setRunBadgeCounts] = useState<RunBadgeCounts>({ running: 0, draft: 0, done: 0, failed: 0 });
```

Add:
```typescript
import { useMemo } from "react";
// (add useMemo to the existing react import)

const [rawJobs, setRawJobs] = useState<import("../../utils/algorithmRunBadges").RunBadgeJob[]>([]);
const runBadgeCounts = useMemo(() => computeRunBadgeCounts(rawJobs, seenIds), [rawJobs, seenIds]);
```

Update `fetchRunBadgeCounts` to set `rawJobs` instead of `runBadgeCounts`:

```typescript
useEffect(() => {
  async function fetchRawJobs() {
    try {
      const result = await listJobs(50);
      setRawJobs(result.items);
      seedSeenIds(result.items);
    } catch {
      // ignore
    }
  }

  void fetchRawJobs();
  const interval = setInterval(() => void fetchRawJobs(), 30_000);
  return () => clearInterval(interval);
}, [latestJobId, seedSeenIds]);
```

- [ ] **Step 3: Add "סמן הכל כנראה" button to section header**

In the section header (around the chevron button area):

```tsx
<div className="flex items-center gap-2">
  {(runBadgeCounts.done > 0 || runBadgeCounts.failed > 0 || runBadgeCounts.draft > 0) && (
    <button
      type="button"
      onClick={() => void markAllSeen(
        rawJobs
          .filter(j => (j.status === "done" || j.status === "failed") && j.error_message !== "cancelled_by_user")
          .map(j => j.id)
      )}
      className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
    >
      סמן הכל כנראה
    </button>
  )}
  {runBadgeCounts.running > 0 && (
    <span data-testid="algo-badge-running" ...>...</span>
  )}
  {/* rest of existing badges */}
  <span className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-sm px-2 py-1">
    {runsOpen ? "▲" : "▼"}
  </span>
</div>
```

(Keep all existing badge spans; just add the button before them and change the outer div to flex.)

The existing outer `<div className="flex items-center gap-2">` is already wrapping the badges (lines 69-105 of the original file), so just add the button inside it before the first badge span.

Full replacement of the button's inner `<div className="flex items-center gap-2">` block:

```tsx
<div className="flex items-center gap-2">
  {(runBadgeCounts.done > 0 || runBadgeCounts.failed > 0 || runBadgeCounts.draft > 0) && (
    <button
      type="button"
      onClick={() => void markAllSeen(
        rawJobs
          .filter(j => (j.status === "done" || j.status === "failed") && j.error_message !== "cancelled_by_user")
          .map(j => j.id)
      )}
      className="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
    >
      סמן הכל כנראה
    </button>
  )}
  {runBadgeCounts.running > 0 && (
    <span
      data-testid="algo-badge-running"
      className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200"
    >
      {runBadgeCounts.running}
    </span>
  )}
  {runBadgeCounts.draft > 0 && (
    <span
      data-testid="algo-badge-draft"
      className="px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200"
    >
      {runBadgeCounts.draft}
    </span>
  )}
  {runBadgeCounts.done > 0 && (
    <span
      data-testid="algo-badge-done"
      className="px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
    >
      {runBadgeCounts.done}
    </span>
  )}
  {runBadgeCounts.failed > 0 && (
    <span
      data-testid="algo-badge-failed"
      className="px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
    >
      {runBadgeCounts.failed}
    </span>
  )}
  <span className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-sm px-2 py-1">
    {runsOpen ? "▲" : "▼"}
  </span>
</div>
```

- [ ] **Step 4: Run typecheck**

```powershell
cd frontend
npm run typecheck
```

Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/planning/ShiftsManagementPage.tsx
git commit -m "feat: ShiftsManagementPage uses context seenIds + mark-all-seen button"
```

---

## Task 10: Delete `seenAlgorithmJobs.ts` and run full test suite

**Files:**
- Delete: `frontend/src/utils/seenAlgorithmJobs.ts`

- [ ] **Step 1: Delete the file**

```powershell
Remove-Item frontend/src/utils/seenAlgorithmJobs.ts
```

- [ ] **Step 2: Run typecheck to confirm no remaining imports**

```powershell
cd frontend
npm run typecheck
```

Expected: No errors. If any file still imports from `seenAlgorithmJobs`, the error will name it — fix by removing the import.

- [ ] **Step 3: Run the full frontend test suite**

```powershell
npm test
```

Expected: All tests pass

- [ ] **Step 4: Run the backend integration tests for the seen feature**

```powershell
cd backend
pytest tests/integration/test_algorithm_seen.py -v
```

Expected: All 6 tests pass

- [ ] **Step 5: Run the broader backend algorithm tests**

```powershell
pytest -m algorithm -q
```

Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: remove seenAlgorithmJobs localStorage utility (replaced by AlgorithmSeenContext)"
```

---

## Self-Review Checklist

- [x] **Migration** creates the junction table with correct FKs and cascade deletes — Task 1
- [x] **`AlgorithmJobSeen` model** follows `MappedAsDataclass` pattern — Task 2
- [x] **`list_jobs`** enriches every item with `seen: bool` via correlated subquery — Task 2
- [x] **`mark_job_seen`** is idempotent via `ON CONFLICT DO NOTHING` — Task 3
- [x] **`mark_all_jobs_seen`** excludes pending/running and cancelled-by-user jobs — Task 3
- [x] **Seen state is per-user** — the subquery and inserts both filter by `user.id` — Tasks 2–3
- [x] **`JobSummaryOut`** interface updated in both backend (`routes/algorithm.py`) and frontend (`api/algorithm.ts`) — Tasks 2, 4
- [x] **`AlgorithmSeenContext`** initializes empty, seeds from API responses, never removes IDs (union only) — Task 5
- [x] **`markAllSeen`** in context adds ALL provided IDs to state after API call — Task 5
- [x] **Provider wraps the app** so all consumers share the same instance — Task 6
- [x] **`UnifiedNav`** badge re-renders immediately when `seenIds` changes (derived value, not polled) — Task 7
- [x] **`AlgorithmPage`** seeds context on jobs load and calls `markJobSeen` on non-running job select — Task 8
- [x] **`ShiftsManagementPage`** uses `useMemo` so section badges also re-render on `seenIds` change — Task 9
- [x] **"סמן הכל כנראה" button** visible in both `AlgorithmPage` and `ShiftsManagementPage` — Tasks 8–9
- [x] **`seenAlgorithmJobs.ts`** deleted — Task 10
- [x] **`UnifiedNav.test.tsx`** mocks context and tests seen-job exclusion — Task 7
