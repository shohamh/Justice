# Background Algorithm Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow algorithm runs to execute in the background, send an in-app notification when done, and provide a dedicated `/algorithm` page with job history list and proposal review panel.

**Architecture:** The backend already runs jobs asynchronously via FastAPI `BackgroundTasks`. This plan adds a `GET /algorithm/jobs` list endpoint, triggers a notification via the existing `create_notification` service after each job completes or fails, and replaces the inline `AlgorithmPlanningWindow` collapsible with a dedicated page. The frontend splits the old 576-line component into `AlgorithmRunForm` (start a run) and `AlgorithmProposalTable` (review results), wired together in `AlgorithmPage`.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL; React 18, react-router-dom v6, react-i18next, Tailwind CSS v3; vitest (frontend tests), pytest (backend tests)

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `backend/alembic/versions/0030_add_algorithm_notification_types.py` | Add algorithm_job_done/failed to NotificationType enum |
| Modify | `backend/app/db/models.py` | Add two new values to NotificationType Python enum |
| Modify | `backend/app/routes/algorithm.py` | Add JobSummaryOut schema + GET /algorithm/jobs endpoint |
| Modify | `backend/app/services/algorithm_bridge.py` | Call create_notification on job done/failed |
| Create | `backend/tests/integration/test_algorithm_jobs_list.py` | Test GET /algorithm/jobs |
| Create | `backend/tests/integration/test_algorithm_notification.py` | Test notification created on job completion |
| Modify | `frontend/src/api/algorithm.ts` | Add JobSummaryOut interface + listJobs() |
| Create | `frontend/src/components/AlgorithmRunForm.tsx` | Run form (date, shifts, mode, settings) |
| Create | `frontend/src/components/AlgorithmProposalTable.tsx` | Proposal review table + bulk ops |
| Create | `frontend/src/pages/AlgorithmPage.tsx` | Two-panel job history + results page |
| Modify | `frontend/src/App.tsx` | Add /algorithm route |
| Modify | `frontend/src/components/ManageSheet.tsx` | Add "ניהול אלגוריתם" link |
| Modify | `frontend/src/components/ManageSheet.test.tsx` | Update planning section test |
| Modify | `frontend/src/i18n/he.json` | Add nav.algorithm + algorithm.* keys |
| Modify | `frontend/src/components/NotificationBell.tsx` | Add algorithm notification icons + link routing |
| Modify | `frontend/src/pages/DutyManagementPage.tsx` | Remove AlgorithmPlanningWindow |
| Delete | `frontend/src/components/AlgorithmPlanningWindow.tsx` | Replaced by AlgorithmPage |

---

## Task 1: DB migration — extend NotificationType enum

**Files:**
- Create: `backend/alembic/versions/0030_add_algorithm_notification_types.py`
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Add enum values to models.py**

In `backend/app/db/models.py`, find the `NotificationType` class and add two new values after `announcement`:

```python
class NotificationType(str, _enum.Enum):
    swap_offer = "swap_offer"
    swap_accepted = "swap_accepted"
    swap_rejected = "swap_rejected"
    exemption_approved = "exemption_approved"
    exemption_rejected = "exemption_rejected"
    constraint_approved = "constraint_approved"
    constraint_rejected = "constraint_rejected"
    assignment_created = "assignment_created"
    assignment_removed = "assignment_removed"
    score_adjusted = "score_adjusted"
    announcement = "announcement"
    algorithm_job_done = "algorithm_job_done"
    algorithm_job_failed = "algorithm_job_failed"
```

- [ ] **Step 2: Create Alembic migration**

Create `backend/alembic/versions/0030_add_algorithm_notification_types.py`:

```python
"""add algorithm_job_done and algorithm_job_failed notification types

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-02

"""
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'algorithm_job_done'")
    op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'algorithm_job_failed'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is intentionally a no-op.
    pass
```

- [ ] **Step 3: Run migration**

```bash
cd backend && uv run alembic upgrade head
```
Expected: "Running upgrade 0029 -> 0030, add algorithm_job_done and algorithm_job_failed notification types"

- [ ] **Step 4: Verify enum values exist in DB**

```bash
cd backend && uv run python -c "
from app.db.session import get_engine
from sqlalchemy import text
with get_engine().connect() as c:
    rows = c.execute(text(\"SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_type.oid = enumtypid WHERE pg_type.typname = 'notificationtype' ORDER BY enumsortorder\")).fetchall()
    print([r[0] for r in rows])
"
```
Expected: list ending with `'algorithm_job_done', 'algorithm_job_failed'`

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/0030_add_algorithm_notification_types.py backend/app/db/models.py
git commit -m "feat: add algorithm_job_done/failed notification types (migration 0030)"
```

---

## Task 2: Backend — GET /algorithm/jobs list endpoint

**Files:**
- Modify: `backend/app/routes/algorithm.py`
- Create: `backend/tests/integration/test_algorithm_jobs_list.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_algorithm_jobs_list.py`:

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


def test_list_jobs_empty(client, admin_session):
    dm, _ = _setup(admin_session, "jlist_001")
    resp = client.get("/api/algorithm/jobs", headers=auth_headers(dm))
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)


def test_list_jobs_returns_own_job(client, admin_session):
    dm, shift = _setup(admin_session, "jlist_002")
    create_soldier(admin_session, personal_number="jlist_002s")
    admin_session.commit()

    create_resp = client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"K": 8, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 5},
        },
        headers=auth_headers(dm),
    )
    assert create_resp.status_code == 202

    list_resp = client.get("/api/algorithm/jobs", headers=auth_headers(dm))
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) >= 1
    item = items[0]
    assert item["status"] in ("pending", "running", "done", "failed")
    assert item["shift_count"] == 1
    assert item["planning_start"] == "2027-03-01"
    assert item["planning_end"] == "2027-03-01"
    assert "created_at" in item
    assert "id" in item


def test_list_jobs_does_not_return_other_users_jobs(client, admin_session):
    dm1, shift = _setup(admin_session, "jlist_003a")
    dm2, _ = _setup(admin_session, "jlist_003b")
    create_soldier(admin_session, personal_number="jlist_003s")
    admin_session.commit()

    client.post(
        "/api/algorithm/jobs",
        json={
            "shift_ids": [str(shift.id)],
            "mode": "shadow",
            "settings": {"K": 8, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 5},
        },
        headers=auth_headers(dm1),
    )

    list_resp = client.get("/api/algorithm/jobs", headers=auth_headers(dm2))
    assert list_resp.status_code == 200
    # dm2 has no jobs
    for item in list_resp.json()["items"]:
        # None of dm2's items should belong to dm1
        assert item.get("status") is not None


def test_soldier_cannot_list_jobs(client, admin_session):
    node = create_node(admin_session, level="branch", name="jlist_004_node")
    soldier = create_soldier(admin_session, personal_number="jlist_004", role="soldier", hierarchy_node_id=node.id)
    admin_session.commit()
    resp = client.get("/api/algorithm/jobs", headers=auth_headers(soldier))
    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/integration/test_algorithm_jobs_list.py -v
```
Expected: FAIL — "404 Not Found" or "ImportError" (endpoint doesn't exist yet)

- [ ] **Step 3: Add JobSummaryOut and the endpoint to algorithm.py**

In `backend/app/routes/algorithm.py`, after the `JobOut` class definition (after line 92), add:

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


class JobListOut(BaseModel):
    items: list[JobSummaryOut]
    total: int
```

Then add the endpoint after the `create_job` endpoint (after line 272):

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

    jobs = session.execute(
        select(AlgorithmJob)
        .where(AlgorithmJob.created_by == user.id)
        .order_by(AlgorithmJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()

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
            )
            for j in jobs
        ],
        total=total,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/integration/test_algorithm_jobs_list.py -v
```
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/algorithm.py backend/tests/integration/test_algorithm_jobs_list.py
git commit -m "feat: add GET /algorithm/jobs list endpoint"
```

---

## Task 3: Backend — Notification trigger on job completion

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py`
- Create: `backend/tests/integration/test_algorithm_notification.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_algorithm_notification.py`:

```python
from __future__ import annotations

import time
from decimal import Decimal

from app.db.models import DutyLocation, DutyShift, DutyType, Notification, NotificationType
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
        start_date="2027-04-01",
        end_date="2027-04-01",
        required_count=1,
    )
    session.add(shift)
    session.commit()
    return dm, shift


def test_notification_created_when_job_completes(client, admin_session):
    dm, shift = _setup(admin_session, "alg_notif_001")
    create_soldier(admin_session, personal_number="alg_notif_001s")
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
    assert create_resp.status_code == 202
    job_id = create_resp.json()["id"]

    # Poll until done or failed
    for _ in range(20):
        poll = client.get(f"/api/algorithm/jobs/{job_id}", headers=auth_headers(dm))
        if poll.json()["status"] in ("done", "failed"):
            break
        time.sleep(2)

    final_status = poll.json()["status"]
    assert final_status in ("done", "failed")

    # Check notification was created for the dm
    admin_session.expire_all()
    notif = admin_session.query(Notification).filter(
        Notification.soldier_id == dm.id,
        Notification.reference_type == "algorithm_job",
    ).first()

    assert notif is not None
    assert str(notif.reference_id) == job_id
    if final_status == "done":
        assert notif.type == NotificationType.algorithm_job_done
        assert "הצעות" in notif.title
    else:
        assert notif.type == NotificationType.algorithm_job_failed
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/integration/test_algorithm_notification.py -v
```
Expected: FAIL — assertion `notif is not None` fails (no notification created yet)

- [ ] **Step 3: Add create_notification calls to run_algorithm_job**

In `backend/app/services/algorithm_bridge.py`, add the import near the top of the file (with other imports or at the function-local import block inside `run_algorithm_job`). The cleanest approach is a function-local import inside `run_algorithm_job` to avoid circular imports.

Find the section where `job.status = "done"` is set (after the `session.refresh(job)` check, before `session.commit()`). Replace that block:

```python
            session.refresh(job)
            if job.status == "failed":
                session.rollback()
                return

            job.status = "done"
            job.finished_at = datetime.now(tz=timezone.utc)
            session.commit()
```

With:

```python
            session.refresh(job)
            if job.status == "failed":
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
```

Then find the exception handler at the bottom of `run_algorithm_job` (the `except Exception as exc:` block) and update it:

```python
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
```

Also add the helper function `_count_proposals_for_job` just before `run_algorithm_job` in `algorithm_bridge.py`. This counts proposals by checking audit log entries for the job — the same logic used in `_proposals_for_job` in the routes file, but a lightweight count version:

```python
def _count_proposals_for_job(session: "Session", job: "AlgorithmJob") -> int:
    """Count proposals created for a job via the audit log."""
    from sqlalchemy import select, func
    from app.db.models import AuditLog
    return session.execute(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "algorithm.proposal.create",
            AuditLog.context["job_id"].astext == str(job.id),
        )
    ).scalar_one()
```

And update the done notification to use it:
```python
                proposal_count = _count_proposals_for_job(session, job)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/integration/test_algorithm_notification.py -v
```
Expected: PASS (may take up to 40 seconds due to solver run).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/algorithm_bridge.py backend/tests/integration/test_algorithm_notification.py
git commit -m "feat: send notification when algorithm job completes or fails"
```

---

## Task 4: Frontend — API additions

**Files:**
- Modify: `frontend/src/api/algorithm.ts`

- [ ] **Step 1: Add JobSummaryOut interface and listJobs() to algorithm.ts**

Add after the `AlgorithmJob` interface (after line 46) in `frontend/src/api/algorithm.ts`:

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
}

export interface JobListOut {
  items: JobSummaryOut[];
  total: number;
}
```

Add after the `pollJob` function:

```typescript
export async function listJobs(limit = 20, offset = 0): Promise<JobListOut> {
  return (await api.get<JobListOut>("/algorithm/jobs", { params: { limit, offset } })).data;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && pnpm exec tsc --noEmit --skipLibCheck 2>&1 | head -20
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/algorithm.ts
git commit -m "feat: add JobSummaryOut interface and listJobs() API function"
```

---

## Task 5: Frontend — AlgorithmRunForm component

**Files:**
- Create: `frontend/src/components/AlgorithmRunForm.tsx`

- [ ] **Step 1: Create AlgorithmRunForm.tsx**

Create `frontend/src/components/AlgorithmRunForm.tsx` with EXACTLY this content:

```tsx
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { SolverSettings, submitJob } from "../api/algorithm";
import { DutyShift, listShifts } from "../api/shifts";
import { DutyType } from "../api/dutyConfig";
import SubHierarchySelector from "./SubHierarchySelector";

interface Props {
  dutyTypes: DutyType[];
  onJobSubmitted: (jobId: string) => void;
}

const DEFAULT_SETTINGS: SolverSettings = {
  K: 8, T: 7, W: 14, alpha: 1.0, beta: 2.0, time_limit_seconds: 30,
};

const FILL_COLORS: Record<string, string> = {
  empty: "text-red-600",
  partial: "text-amber-600",
  full: "text-green-600",
};

export default function AlgorithmRunForm({ dutyTypes, onJobSubmitted }: Props) {
  const { t } = useTranslation();
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [availableShifts, setAvailableShifts] = useState<DutyShift[]>([]);
  const [selectedShiftIds, setSelectedShiftIds] = useState<string[]>([]);
  const [mode, setMode] = useState<"shadow" | "dm_reviewed">("shadow");
  const [settings, setSettings] = useState<SolverSettings>(DEFAULT_SETTINGS);
  const [showSettings, setShowSettings] = useState(false);
  const [eligibleNodeIds, setEligibleNodeIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const typeName = (id: string) => dutyTypes.find(d => d.id === id)?.name ?? id.slice(0, 8);
  const shiftLabel = (shift: DutyShift) =>
    `${typeName(shift.duty_type_id)} — ${shift.start_date} עד ${shift.end_date} (${shift.assigned_count}/${shift.required_count})`;

  const loadShifts = useCallback(async () => {
    const ss = await listShifts({
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    });
    setAvailableShifts(ss.filter(s => s.fill_status !== "full"));
  }, [dateFrom, dateTo]);

  useEffect(() => {
    if (dateFrom || dateTo) void loadShifts();
    else setAvailableShifts([]);
  }, [loadShifts, dateFrom, dateTo]);

  function toggleShift(id: string) {
    setSelectedShiftIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  }

  async function handleSubmit() {
    setError(null);
    if (selectedShiftIds.length === 0) {
      setError("נא לבחור לפחות משמרת אחת");
      return;
    }
    setSubmitting(true);
    try {
      const resp = await submitJob({ shift_ids: selectedShiftIds, mode, settings });
      onJobSubmitted(resp.id);
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה בשליחת הבקשה");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-4 text-sm" dir="rtl">
      <div className="grid grid-cols-2 gap-4">
        <label className="block">
          {t("shifts.filter_from")}
          <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" />
        </label>
        <label className="block">
          {t("shifts.filter_to")}
          <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="mt-1 block w-full border rounded p-1 text-sm" />
        </label>
      </div>

      {availableShifts.length > 0 && (
        <div>
          <div className="flex items-center gap-3 mb-1">
            <p className="font-medium">בחר משמרות להרצה</p>
            <button type="button" onClick={() => setSelectedShiftIds(availableShifts.map(s => s.id))} className="text-xs text-blue-600 hover:underline">בחר הכל</button>
            <button type="button" onClick={() => setSelectedShiftIds([])} className="text-xs text-blue-600 hover:underline">בטל בחירה</button>
          </div>
          <div className="space-y-1 max-h-48 overflow-y-auto border rounded p-2">
            {availableShifts.map(shift => (
              <label key={shift.id} className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={selectedShiftIds.includes(shift.id)}
                  onChange={() => toggleShift(shift.id)}
                />
                <span className={FILL_COLORS[shift.fill_status]}>{shiftLabel(shift)}</span>
              </label>
            ))}
          </div>
        </div>
      )}
      {availableShifts.length === 0 && (
        <p className="text-gray-400">
          {dateFrom || dateTo ? "אין משמרות פתוחות בטווח הנבחר" : "הזן טווח תאריכים לצפייה במשמרות"}
        </p>
      )}

      <label className="block">
        {t("algorithm.mode_label")}
        <select value={mode} onChange={e => setMode(e.target.value as "shadow" | "dm_reviewed")} className="mt-1 block w-full border rounded p-1 text-sm">
          <option value="shadow">{t("algorithm.shadow_mode")}</option>
          <option value="dm_reviewed">{t("algorithm.dm_reviewed_mode")}</option>
        </select>
      </label>

      <button type="button" className="text-xs text-blue-600 underline" onClick={() => setShowSettings(s => !s)}>
        {t("algorithm.settings")}
      </button>
      {showSettings && (
        <div className="grid grid-cols-3 gap-3 text-xs bg-gray-50 p-3 rounded">
          {(["K", "T", "W", "alpha", "beta", "time_limit_seconds"] as const).map(key => (
            <label key={key} className="block">
              {key}
              <input
                type="number"
                value={settings[key]}
                onChange={e => setSettings(s => ({ ...s, [key]: parseFloat(e.target.value) }))}
                className="mt-1 block w-full border rounded p-1"
                step={key === "alpha" || key === "beta" ? 0.1 : 1}
              />
            </label>
          ))}
        </div>
      )}

      <details className="border rounded p-2">
        <summary className="cursor-pointer">{t("algorithm.restrict_to_subtree")}</summary>
        <SubHierarchySelector value={eligibleNodeIds} onChange={setEligibleNodeIds} />
      </details>

      {error && <p className="text-red-500">{error}</p>}

      <button
        onClick={handleSubmit}
        disabled={submitting || selectedShiftIds.length === 0}
        type="button"
        className="w-full bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
      >
        {t("algorithm.run_button")} {selectedShiftIds.length > 0 && `(${selectedShiftIds.length} משמרות)`}
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && pnpm exec tsc --noEmit --skipLibCheck 2>&1 | head -20
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AlgorithmRunForm.tsx
git commit -m "feat: extract AlgorithmRunForm component"
```

---

## Task 6: Frontend — AlgorithmProposalTable component

**Files:**
- Create: `frontend/src/components/AlgorithmProposalTable.tsx`

- [ ] **Step 1: Create AlgorithmProposalTable.tsx**

Create `frontend/src/components/AlgorithmProposalTable.tsx`:

```tsx
import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlgorithmJob, ProposalRow, acceptProposal, rejectProposal, resetDrafts, resetPublished } from "../api/algorithm";
import { DutyType } from "../api/dutyConfig";
import { SoldierDTO } from "../api/soldiers";
import { DataTable, type ColDef } from "./DataTable";
import ExplanationModal from "./ExplanationModal";
import SoldierLink from "./SoldierLink";

interface Props {
  job: AlgorithmJob;
  jobId: string;
  soldiers: SoldierDTO[];
  dutyTypes: DutyType[];
  onProposalUpdate: (updated: AlgorithmJob) => void;
}

export default function AlgorithmProposalTable({ job, jobId, soldiers, dutyTypes, onProposalUpdate }: Props) {
  const { t } = useTranslation();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [explanationTarget, setExplanationTarget] = useState<{ jobId: string; assignmentId: string } | null>(null);
  const [resetPublishedDays, setResetPublishedDays] = useState(30);
  const [resetDraftsDays, setResetDraftsDays] = useState(30);
  const [resetPublishedMsg, setResetPublishedMsg] = useState<string | null>(null);
  const [resetDraftsMsg, setResetDraftsMsg] = useState<string | null>(null);
  const [resetPublishedLoading, setResetPublishedLoading] = useState(false);
  const [resetDraftsLoading, setResetDraftsLoading] = useState(false);

  const soldierName = (id: string) => soldiers.find(s => s.id === id)?.full_name ?? id.slice(0, 8);
  const soldierLink = (id: string): React.ReactNode => {
    const s = soldiers.find(s => s.id === id);
    if (!s) return id.slice(0, 8);
    return <SoldierLink id={s.id} name={s.full_name} />;
  };
  const typeName = (id: string) => dutyTypes.find(d => d.id === id)?.name ?? id.slice(0, 8);

  function isPending(p: ProposalRow) {
    return p.status !== "published" && p.status !== "algorithm_rejected";
  }

  function toggleSelection(id: string) {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function handleAccept(proposal: ProposalRow) {
    await acceptProposal(jobId, proposal.assignment_id);
    onProposalUpdate({
      ...job,
      proposals: job.proposals.map(p =>
        p.assignment_id === proposal.assignment_id ? { ...p, status: "published" } : p
      ),
    });
  }

  async function handleReject(proposal: ProposalRow) {
    await rejectProposal(jobId, proposal.assignment_id);
    onProposalUpdate({
      ...job,
      proposals: job.proposals.map(p =>
        p.assignment_id === proposal.assignment_id ? { ...p, status: "algorithm_rejected" } : p
      ),
    });
  }

  async function handleApproveSelected() {
    const toApprove = job.proposals.filter(p => selectedIds.has(p.assignment_id) && isPending(p));
    await Promise.all(toApprove.map(p => handleAccept(p)));
    setSelectedIds(new Set());
  }

  async function handleResetPublished() {
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() + resetPublishedDays);
    const dateStr = cutoff.toISOString().slice(0, 10);
    if (!window.confirm(t("algorithm.reset_confirm_published", { date: dateStr }))) return;
    setResetPublishedLoading(true);
    setResetPublishedMsg(null);
    try {
      const result = await resetPublished(resetPublishedDays);
      setResetPublishedMsg(
        result.cancelled === 0 ? t("algorithm.reset_none") : t("algorithm.reset_result_cancelled", { count: result.cancelled })
      );
    } catch {
      setResetPublishedMsg(t("errors.generic"));
    } finally {
      setResetPublishedLoading(false);
    }
  }

  async function handleResetDrafts() {
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() + resetDraftsDays);
    const dateStr = cutoff.toISOString().slice(0, 10);
    if (!window.confirm(t("algorithm.reset_confirm_drafts", { date: dateStr }))) return;
    setResetDraftsLoading(true);
    setResetDraftsMsg(null);
    try {
      const result = await resetDrafts(resetDraftsDays);
      setResetDraftsMsg(
        result.rejected === 0 ? t("algorithm.reset_none") : t("algorithm.reset_result_rejected", { count: result.rejected })
      );
    } catch {
      setResetDraftsMsg(t("errors.generic"));
    } finally {
      setResetDraftsLoading(false);
    }
  }

  const batchRankMap = useMemo(() => {
    const sorted = [...job.proposals]
      .filter(p => p.norm_score_before !== null)
      .sort((a, b) => (a.norm_score_before ?? Infinity) - (b.norm_score_before ?? Infinity));
    const map = new Map<string, number>();
    sorted.forEach((p, i) => map.set(p.assignment_id, i + 1));
    return map;
  }, [job.proposals]);

  const pendingProposals = job.proposals.filter(isPending);
  const allPendingSelected = pendingProposals.length > 0 && pendingProposals.every(p => selectedIds.has(p.assignment_id));

  function toggleSelectAll() {
    if (allPendingSelected) setSelectedIds(new Set());
    else setSelectedIds(new Set(pendingProposals.map(p => p.assignment_id)));
  }

  const cols: ColDef<ProposalRow>[] = [
    {
      id: "select",
      header: "",
      cell: (p) => {
        const pending = isPending(p);
        return (
          <input
            type="checkbox"
            checked={pending ? selectedIds.has(p.assignment_id) : p.status === "published"}
            disabled={!pending}
            onChange={() => pending && toggleSelection(p.assignment_id)}
            className="cursor-pointer disabled:cursor-default"
          />
        );
      },
    },
    { id: "date", header: t("algorithm.col_date"), cell: (p) => p.start_date, sortValue: (p) => p.start_date },
    { id: "type", header: t("algorithm.col_type"), cell: (p) => typeName(p.duty_type_id), sortValue: (p) => typeName(p.duty_type_id), filterValue: (p) => typeName(p.duty_type_id) },
    { id: "soldier", header: t("algorithm.col_soldier"), cell: (p) => soldierLink(p.soldier_id), sortValue: (p) => soldierName(p.soldier_id), filterValue: (p) => soldierName(p.soldier_id) },
    { id: "reserve", header: t("algorithm.col_reserve"), cell: (p) => p.reserve_soldier_id ? soldierLink(p.reserve_soldier_id) : "—" },
    { id: "score_before", header: t("algorithm.col_score_before"), cell: (p) => p.norm_score_before?.toFixed(3) ?? "—", sortValue: (p) => p.norm_score_before ?? null },
    { id: "score_after", header: t("algorithm.col_score_after"), cell: (p) => p.norm_score_after?.toFixed(3) ?? "—", sortValue: (p) => p.norm_score_after ?? null },
    { id: "batch_rank", header: t("algorithm.col_batch_rank"), cell: (p) => batchRankMap.get(p.assignment_id)?.toString() ?? "—", sortValue: (p) => batchRankMap.get(p.assignment_id) ?? null },
    {
      id: "slot_rank",
      header: t("algorithm.col_slot_rank"),
      cell: (p) => p.candidate_rank != null && p.candidate_pool_size ? `${p.candidate_rank} / ${p.candidate_pool_size}` : "—",
      sortValue: (p) => p.candidate_rank ?? null,
    },
    {
      id: "actions",
      header: t("algorithm.col_actions"),
      cell: (p) => {
        const isAccepted = p.status === "published";
        const isRejected = p.status === "algorithm_rejected";
        return (
          <span className="space-x-1 space-x-reverse">
            {!isAccepted && !isRejected && (
              <>
                <button type="button" onClick={() => handleAccept(p)} className="text-green-700 font-bold hover:underline">{t("algorithm.accept")}</button>{" "}
                <button type="button" onClick={() => handleReject(p)} className="text-red-700 hover:underline">{t("algorithm.reject")}</button>{" "}
              </>
            )}
            <button type="button" onClick={() => setExplanationTarget({ jobId, assignmentId: p.assignment_id })} className="text-blue-600 hover:underline">
              {t("algorithm.why_button")}
            </button>
          </span>
        );
      },
    },
  ];

  return (
    <div className="space-y-3" dir="rtl">
      {job.proposals.length === 0 ? (
        <p className="text-gray-500 text-sm">{t("algorithm.no_proposals")}</p>
      ) : (
        <>
          <div className="flex items-center gap-3 text-sm">
            <button type="button" onClick={toggleSelectAll} className="text-blue-600 hover:underline">
              {allPendingSelected ? "בטל בחירה הכל" : "בחר הכל"}
            </button>
            <button
              type="button"
              onClick={handleApproveSelected}
              disabled={selectedIds.size === 0}
              className="bg-green-600 text-white px-3 py-1 rounded text-xs hover:bg-green-700 disabled:opacity-40"
            >
              {`אשר נבחרים (${selectedIds.size})`}
            </button>
          </div>
          <DataTable
            columns={cols}
            data={job.proposals}
            filterPlaceholder={t("table.filter_placeholder")}
            rowClassName={(p) =>
              p.status === "published" ? "bg-green-50" : p.status === "algorithm_rejected" ? "bg-gray-100 opacity-50" : ""
            }
          />
        </>
      )}

      <div className="border-t pt-3 space-y-3">
        <div className="flex items-center gap-2 text-sm flex-wrap">
          <span className="text-gray-700">{t("algorithm.reset_published_label")}</span>
          <input type="number" min={1} value={resetPublishedDays} onChange={e => setResetPublishedDays(Math.max(1, parseInt(e.target.value) || 1))} className="w-16 border rounded p-1 text-sm text-center" />
          <span className="text-gray-700">{t("algorithm.reset_days_suffix")}</span>
          <button type="button" onClick={handleResetPublished} disabled={resetPublishedLoading} className="bg-red-600 text-white px-3 py-1 rounded text-xs hover:bg-red-700 disabled:opacity-50">
            {t("algorithm.reset_published_btn")}
          </button>
          {resetPublishedMsg && <span className="text-xs text-gray-600">{resetPublishedMsg}</span>}
        </div>
        <div className="flex items-center gap-2 text-sm flex-wrap">
          <span className="text-gray-700">{t("algorithm.reset_drafts_label")}</span>
          <input type="number" min={1} value={resetDraftsDays} onChange={e => setResetDraftsDays(Math.max(1, parseInt(e.target.value) || 1))} className="w-16 border rounded p-1 text-sm text-center" />
          <span className="text-gray-700">{t("algorithm.reset_days_suffix")}</span>
          <button type="button" onClick={handleResetDrafts} disabled={resetDraftsLoading} className="bg-amber-600 text-white px-3 py-1 rounded text-xs hover:bg-amber-700 disabled:opacity-50">
            {t("algorithm.reset_drafts_btn")}
          </button>
          {resetDraftsMsg && <span className="text-xs text-gray-600">{resetDraftsMsg}</span>}
        </div>
      </div>

      {explanationTarget && (
        <ExplanationModal
          jobId={explanationTarget.jobId}
          assignmentId={explanationTarget.assignmentId}
          onClose={() => setExplanationTarget(null)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && pnpm exec tsc --noEmit --skipLibCheck 2>&1 | head -20
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AlgorithmProposalTable.tsx
git commit -m "feat: extract AlgorithmProposalTable component"
```

---

## Task 7: Frontend — AlgorithmPage

**Files:**
- Create: `frontend/src/pages/AlgorithmPage.tsx`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add new i18n keys to he.json**

In `frontend/src/i18n/he.json`, inside the `"algorithm"` block, add before the closing `}`:

```json
    "runs_title": "הרצות",
    "new_run": "+ הרצה חדשה",
    "no_runs": "אין הרצות עדיין",
    "select_run": "בחר הרצה מהרשימה",
    "reset_none": "לא נמצאו שיבוצים לביטול"
```

Also in the `"nav"` block, after `"section_planning": "תכנון"`, add:

```json
    "algorithm": "ניהול אלגוריתם"
```

- [ ] **Step 2: Create AlgorithmPage.tsx**

Create `frontend/src/pages/AlgorithmPage.tsx`:

```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthContext";
import Layout from "../components/Layout";
import AlgorithmRunForm from "../components/AlgorithmRunForm";
import AlgorithmProposalTable from "../components/AlgorithmProposalTable";
import { AlgorithmJob, JobSummaryOut, listJobs, pollJob } from "../api/algorithm";
import { DutyType, listDutyTypes } from "../api/dutyConfig";
import { SoldierDTO, listSoldiers } from "../api/soldiers";

export default function AlgorithmPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [searchParams] = useSearchParams();

  const role = user?.role;
  const canManageDuties = role === "duty_manager" || role === "admin";

  const [jobs, setJobs] = useState<JobSummaryOut[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<AlgorithmJob | null>(null);
  const [showRunForm, setShowRunForm] = useState(false);
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);

  const listPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const jobPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  if (!canManageDuties) return <Navigate to="/" replace />;

  const loadJobs = useCallback(async () => {
    try {
      const result = await listJobs();
      setJobs(result.items);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    Promise.all([listSoldiers(), listDutyTypes()]).then(([ss, dts]) => {
      setSoldiers(ss);
      setDutyTypes(dts);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  // Poll job list every 3s while any job is active
  useEffect(() => {
    const hasActive = jobs.some(j => j.status === "pending" || j.status === "running");
    if (hasActive) {
      listPollRef.current = setInterval(() => void loadJobs(), 3000);
    } else {
      if (listPollRef.current) clearInterval(listPollRef.current);
    }
    return () => {
      if (listPollRef.current) clearInterval(listPollRef.current);
    };
  }, [jobs, loadJobs]);

  // Pre-select job from URL param
  useEffect(() => {
    const jobIdParam = searchParams.get("jobId");
    if (jobIdParam) setSelectedJobId(jobIdParam);
  }, [searchParams]);

  // Poll selected job every 1s while pending/running
  useEffect(() => {
    if (!selectedJobId) return;
    setSelectedJob(null);

    const poll = async () => {
      try {
        const j = await pollJob(selectedJobId);
        setSelectedJob(j);
        if (j.status === "done" || j.status === "failed") {
          if (jobPollRef.current) clearInterval(jobPollRef.current);
        }
      } catch { /* ignore */ }
    };

    void poll();
    jobPollRef.current = setInterval(() => void poll(), 1000);

    return () => {
      if (jobPollRef.current) clearInterval(jobPollRef.current);
    };
  }, [selectedJobId]);

  function handleJobSubmitted(jobId: string) {
    setShowRunForm(false);
    setSelectedJobId(jobId);
    void loadJobs();
  }

  const statusIcon = (status: string) => {
    if (status === "done") return "✓";
    if (status === "failed") return "✗";
    return "⏳";
  };

  return (
    <Layout>
      <div className="flex h-full gap-4 overflow-hidden" dir="rtl">
        {/* Left panel: job history */}
        <div className="w-72 shrink-0 border rounded-lg bg-white flex flex-col overflow-hidden">
          <div className="flex justify-between items-center p-3 border-b">
            <h2 className="font-semibold text-sm">{t("algorithm.runs_title")}</h2>
            <button
              onClick={() => setShowRunForm(true)}
              className="text-xs bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700"
            >
              {t("algorithm.new_run")}
            </button>
          </div>
          <div className="overflow-y-auto flex-1 p-2 space-y-1">
            {jobs.length === 0 && (
              <p className="text-sm text-gray-400 text-center mt-4">{t("algorithm.no_runs")}</p>
            )}
            {jobs.map(job => (
              <button
                key={job.id}
                onClick={() => setSelectedJobId(job.id)}
                className={`w-full text-right px-3 py-2 rounded border text-sm transition-colors ${
                  selectedJobId === job.id
                    ? "bg-indigo-50 border-indigo-300 text-indigo-800"
                    : "hover:bg-gray-50 border-transparent"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className={job.status === "done" ? "text-green-600" : job.status === "failed" ? "text-red-600" : "text-gray-400"}>
                    {statusIcon(job.status)}
                  </span>
                  <span className="font-medium truncate text-xs">
                    {job.planning_start} — {job.planning_end}
                  </span>
                </div>
                <div className="text-xs text-gray-500 mt-0.5">{job.shift_count} משמרות · {job.mode === "shadow" ? t("algorithm.shadow_mode") : t("algorithm.dm_reviewed_mode")}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Right panel: job detail */}
        <div className="flex-1 border rounded-lg bg-white overflow-y-auto p-4">
          {!selectedJobId && (
            <p className="text-gray-400 text-sm text-center mt-16">{t("algorithm.select_run")}</p>
          )}

          {selectedJobId && !selectedJob && (
            <p className="text-sm text-gray-500 animate-pulse">{t("app.loading")}</p>
          )}

          {selectedJob && (
            <div className="space-y-4">
              {/* Job header */}
              <div className="text-sm space-y-1 border-b pb-3">
                <div className="flex items-center gap-3">
                  <span className={`font-semibold text-base ${selectedJob.status === "done" ? "text-green-700" : selectedJob.status === "failed" ? "text-red-600" : "text-gray-600"}`}>
                    {statusIcon(selectedJob.status)}
                  </span>
                  <span className="font-semibold">{selectedJob.planning_start} — {selectedJob.planning_end}</span>
                  <span className="text-gray-500 text-xs">{selectedJob.mode === "shadow" ? t("algorithm.shadow_mode") : t("algorithm.dm_reviewed_mode")}</span>
                </div>
                {(selectedJob.status === "pending" || selectedJob.status === "running") && (
                  <p className="text-gray-600 animate-pulse">{t("algorithm.running")}</p>
                )}
              </div>

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

              {/* Proposals table */}
              {selectedJob.status === "done" && (
                <AlgorithmProposalTable
                  job={selectedJob}
                  jobId={selectedJobId}
                  soldiers={soldiers}
                  dutyTypes={dutyTypes}
                  onProposalUpdate={setSelectedJob}
                />
              )}
            </div>
          )}
        </div>

        {/* New run drawer */}
        {showRunForm && (
          <>
            <div className="fixed inset-0 bg-black/30 z-40" onClick={() => setShowRunForm(false)} />
            <div className="fixed inset-y-0 right-0 w-96 bg-white z-50 shadow-xl overflow-y-auto">
              <div className="p-6 space-y-4">
                <div className="flex justify-between items-center">
                  <h2 className="font-semibold">{t("algorithm.new_run")}</h2>
                  <button onClick={() => setShowRunForm(false)} className="text-gray-400 hover:text-gray-600 text-lg">✕</button>
                </div>
                <AlgorithmRunForm
                  dutyTypes={dutyTypes}
                  onJobSubmitted={handleJobSubmitted}
                />
              </div>
            </div>
          </>
        )}
      </div>
    </Layout>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && pnpm exec tsc --noEmit --skipLibCheck 2>&1 | head -30
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/AlgorithmPage.tsx frontend/src/i18n/he.json
git commit -m "feat: add AlgorithmPage with job history list and results panel"
```

---

## Task 8: Wire navigation and remove old component

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/ManageSheet.tsx`
- Modify: `frontend/src/components/ManageSheet.test.tsx`
- Modify: `frontend/src/pages/DutyManagementPage.tsx`
- Delete: `frontend/src/components/AlgorithmPlanningWindow.tsx`

- [ ] **Step 1: Add /algorithm route to App.tsx**

In `frontend/src/App.tsx`, add the import at the top:
```tsx
import AlgorithmPage from "./pages/AlgorithmPage";
```

Inside the `<Route element={<ProtectedRoute />}>` block, add after the `/command-dashboard` route:
```tsx
<Route path="/algorithm" element={<ForcedPasswordGate><AlgorithmPage /></ForcedPasswordGate>} />
```

- [ ] **Step 2: Add algorithm link to ManageSheet**

In `frontend/src/components/ManageSheet.tsx`, inside the `{canManageDuties && ...}` Planning section block, add after the Shift Templates link:

```tsx
<Link to="/algorithm" onClick={onClose} className={linkClass}>{t("nav.algorithm")}</Link>
```

The full Planning section should look like:
```tsx
{canManageDuties && (
  <div>
    <h3 className={sectionHeadClass}>{t("nav.section_planning")}</h3>
    <Link to="/duty-config" onClick={onClose} className={linkClass}>{t("nav.duty_config")}</Link>
    <Link to="/duty-management" onClick={onClose} className={linkClass}>{t("nav.duty_management")}</Link>
    <Link to="/shifts" onClick={onClose} className={linkClass}>{t("nav.shifts")}</Link>
    <Link to="/shift-templates" onClick={onClose} className={linkClass}>{t("nav.shift_templates")}</Link>
    <Link to="/algorithm" onClick={onClose} className={linkClass}>{t("nav.algorithm")}</Link>
  </div>
)}
```

- [ ] **Step 3: Update ManageSheet test**

In `frontend/src/components/ManageSheet.test.tsx`, update the planning section test:

```tsx
  test("renders planning section for canManageDuties roles", () => {
    mockUseAuth.mockReturnValue({ user: { role: "duty_manager" } });
    render(<ManageSheet open={true} onClose={() => {}} />);
    expect(screen.getByText("nav.section_planning")).toBeInTheDocument();
    expect(screen.getByText("nav.duty_config")).toBeInTheDocument();
    expect(screen.getByText("nav.shifts")).toBeInTheDocument();
    expect(screen.getByText("nav.algorithm")).toBeInTheDocument();
  });
```

- [ ] **Step 4: Remove AlgorithmPlanningWindow from DutyManagementPage**

In `frontend/src/pages/DutyManagementPage.tsx`:

Remove the import line:
```tsx
import AlgorithmPlanningWindow from "../components/AlgorithmPlanningWindow";
```

Remove the JSX usage (it appears at lines ~118-121):
```tsx
<AlgorithmPlanningWindow
  dutyTypes={types}
  soldiers={soldiers}
/>
```

- [ ] **Step 5: Delete AlgorithmPlanningWindow.tsx**

```bash
Remove-Item frontend/src/components/AlgorithmPlanningWindow.tsx
```

- [ ] **Step 6: Run full test suite**

```bash
cd frontend && pnpm test
```
Expected: All tests PASS (ManageSheet tests updated, others unaffected).

- [ ] **Step 7: Verify TypeScript compiles**

```bash
cd frontend && pnpm exec tsc --noEmit --skipLibCheck 2>&1 | head -20
```
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/ManageSheet.tsx frontend/src/components/ManageSheet.test.tsx frontend/src/pages/DutyManagementPage.tsx
git rm frontend/src/components/AlgorithmPlanningWindow.tsx
git commit -m "feat: wire /algorithm route, add ManageSheet link, remove old planning window"
```

---

## Task 9: Notification bell routing for algorithm jobs

**Files:**
- Modify: `frontend/src/components/NotificationBell.tsx`

- [ ] **Step 1: Update NotificationBell to handle algorithm notifications**

In `frontend/src/components/NotificationBell.tsx`:

**1.** Add `useNavigate` to the imports:
```tsx
import { Link, useNavigate } from "react-router-dom";
```

**2.** Add `algorithm_job_done` and `algorithm_job_failed` to `typeLabels`:
```tsx
const typeLabels: Record<string, string> = {
  swap_offer: "🔄", swap_accepted: "✅", swap_rejected: "❌",
  exemption_approved: "✔️", exemption_rejected: "✖️",
  constraint_approved: "✔️", constraint_rejected: "✖️",
  assignment_created: "📋", assignment_removed: "🗑️",
  score_adjusted: "⭐", announcement: "📢",
  algorithm_job_done: "🤖", algorithm_job_failed: "⚠️",
};
```

**3.** Add `navigate` inside the component (after `const ref = ...`):
```tsx
const navigate = useNavigate();
```

**4.** Add a helper function to get the notification link URL:
```tsx
function notifLink(n: NotificationDTO): string | null {
  if (n.reference_type === "algorithm_job" && n.reference_id) {
    return `/algorithm?jobId=${n.reference_id}`;
  }
  return null;
}
```

**5.** Wrap the notification title in the dropdown to be clickable when it has a link. Replace the notification row JSX:

```tsx
notifications.map((n) => (
  <div key={n.id} className="flex items-start gap-2 p-3 border-b hover:bg-gray-50">
    <span className="text-lg">{typeLabels[n.type] || "🔔"}</span>
    <div className="flex-1 min-w-0">
      {notifLink(n) ? (
        <button
          className="text-sm font-medium truncate text-right w-full hover:text-indigo-600"
          onClick={() => { void handleMarkRead(n.id); navigate(notifLink(n)!); setOpen(false); }}
        >
          {n.title}
        </button>
      ) : (
        <p className="text-sm font-medium truncate">{n.title}</p>
      )}
      {n.body && <p className="text-xs text-gray-500 truncate">{n.body}</p>}
    </div>
    <div className="flex gap-1">
      <button onClick={() => handleMarkRead(n.id)} className="text-xs text-gray-400 hover:text-gray-600" title={t("notifications.mark_read")}>✓</button>
      <button onClick={() => handleDelete(n.id)} className="text-xs text-gray-400 hover:text-red-600" title={t("notifications.dismiss")}>✕</button>
    </div>
  </div>
))
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && pnpm exec tsc --noEmit --skipLibCheck 2>&1 | head -20
```
Expected: no errors.

- [ ] **Step 3: Run full test suite**

```bash
cd frontend && pnpm test
```
Expected: All 18 tests PASS (NotificationBell has no unit tests — covered visually).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/NotificationBell.tsx
git commit -m "feat: route algorithm job notifications to /algorithm page"
```
