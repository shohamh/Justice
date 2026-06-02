# Algorithm Bulk Reset Buttons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two buttons to the algorithm planning panel that bulk-cancel published assignments and bulk-reject algorithm-draft assignments beyond a configurable number of days in the future.

**Architecture:** Two new POST endpoints on the existing `/algorithm` FastAPI router perform the bulk operations in a single transaction and return a count. The frontend adds a new UI section in `AlgorithmPlanningWindow` with two independent number-input + button rows and calls two new API client functions.

**Tech Stack:** FastAPI (Python), SQLAlchemy, React + TypeScript, react-i18next, Tailwind CSS

---

## File Map

| File | Change |
|------|--------|
| `backend/app/routes/algorithm.py` | Add `POST /algorithm/reset-published` and `POST /algorithm/reset-drafts` endpoints |
| `backend/tests/integration/test_algorithm_routes.py` | Add integration tests for both new endpoints |
| `frontend/src/api/algorithm.ts` | Add `resetPublished` and `resetDrafts` API functions |
| `frontend/src/components/AlgorithmPlanningWindow.tsx` | Add danger-zone UI section with two reset button rows |
| `frontend/src/i18n/he.json` | Add new i18n keys for reset buttons |

---

### Task 1: Backend — `POST /algorithm/reset-published` endpoint

**Files:**
- Modify: `backend/app/routes/algorithm.py`
- Test: `backend/tests/integration/test_algorithm_routes.py`

- [ ] **Step 1: Write the failing integration test**

Add to `backend/tests/integration/test_algorithm_routes.py`:

```python
from datetime import date, timedelta
from decimal import Decimal

from app.db.models import DutyAssignment, DutyLocation, DutyShift, DutyType
from tests.helpers import auth_headers, create_node, create_soldier


def _make_published_assignment(session, personal_number: str, start_date: date) -> DutyAssignment:
    """Helper: creates a soldier + duty type + location + published assignment."""
    node = create_node(session, level="branch", name=f"branch_{personal_number}")
    soldier = create_soldier(session, personal_number=personal_number, hierarchy_node_id=node.id)
    dt = DutyType(name=f"dt_{personal_number}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{personal_number}")
    session.add(dt)
    session.add(loc)
    session.flush()
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=start_date,
        end_date=start_date,
        status="published",
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def test_reset_published_cancels_future_assignments(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rp_dm_001")
    dm = create_soldier(admin_session, personal_number="rp_dm_001", role="duty_manager", hierarchy_node_id=dm_node.id)

    future = date.today() + timedelta(days=60)
    near = date.today() + timedelta(days=5)

    far_assignment = _make_published_assignment(admin_session, "rp_s_001", future)
    near_assignment = _make_published_assignment(admin_session, "rp_s_002", near)

    resp = client.post(
        "/api/algorithm/reset-published",
        params={"days_ahead": 30},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["cancelled"] >= 1

    admin_session.expire(far_assignment)
    admin_session.expire(near_assignment)
    admin_session.refresh(far_assignment)
    admin_session.refresh(near_assignment)

    assert far_assignment.status == "cancelled"
    assert near_assignment.status == "published"  # within 30 days, untouched


def test_reset_published_returns_zero_when_no_matches(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rp_dm_002")
    dm = create_soldier(admin_session, personal_number="rp_dm_002", role="duty_manager", hierarchy_node_id=dm_node.id)

    resp = client.post(
        "/api/algorithm/reset-published",
        params={"days_ahead": 365},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert resp.json()["cancelled"] == 0


def test_reset_published_rejects_days_ahead_zero(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rp_dm_003")
    dm = create_soldier(admin_session, personal_number="rp_dm_003", role="duty_manager", hierarchy_node_id=dm_node.id)

    resp = client.post(
        "/api/algorithm/reset-published",
        params={"days_ahead": 0},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend
uv run pytest tests/integration/test_algorithm_routes.py::test_reset_published_cancels_future_assignments tests/integration/test_algorithm_routes.py::test_reset_published_returns_zero_when_no_matches tests/integration/test_algorithm_routes.py::test_reset_published_rejects_days_ahead_zero -v
```

Expected: 3 failures — `404 Not Found` (endpoint doesn't exist yet)

- [ ] **Step 3: Implement the endpoint**

Add to `backend/app/routes/algorithm.py` after the existing imports, before the first `@router` decorator:

```python
from datetime import timedelta
```

Add after the `cancel_job` endpoint (after line ~313):

```python
@router.post("/reset-published", status_code=status.HTTP_200_OK)
def reset_published_assignments(
    days_ahead: int = Query(ge=1),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    from datetime import date, timedelta
    from sqlalchemy import select
    from app.services.assignments import cancel_assignment

    cutoff = date.today() + timedelta(days=days_ahead)
    assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.status == "published",
            DutyAssignment.start_date > cutoff,
        )
    ).scalars().all()

    for a in assignments:
        cancel_assignment(session, assignment=a, reason="bulk_reset", actor_id=user.id)

    session.commit()
    return {"cancelled": len(assignments)}
```

Also add `Query` to the FastAPI imports at the top of `algorithm.py`:

```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend
uv run pytest tests/integration/test_algorithm_routes.py::test_reset_published_cancels_future_assignments tests/integration/test_algorithm_routes.py::test_reset_published_returns_zero_when_no_matches tests/integration/test_algorithm_routes.py::test_reset_published_rejects_days_ahead_zero -v
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/algorithm.py backend/tests/integration/test_algorithm_routes.py
git commit -m "feat: POST /algorithm/reset-published bulk-cancel future published assignments"
```

---

### Task 2: Backend — `POST /algorithm/reset-drafts` endpoint

**Files:**
- Modify: `backend/app/routes/algorithm.py`
- Test: `backend/tests/integration/test_algorithm_routes.py`

- [ ] **Step 1: Write the failing integration test**

Add to `backend/tests/integration/test_algorithm_routes.py`:

```python
def _make_draft_assignment(session, personal_number: str, start_date: date) -> DutyAssignment:
    node = create_node(session, level="branch", name=f"branch_{personal_number}")
    soldier = create_soldier(session, personal_number=personal_number, hierarchy_node_id=node.id)
    dt = DutyType(name=f"dt_{personal_number}", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name=f"loc_{personal_number}")
    session.add(dt)
    session.add(loc)
    session.flush()
    a = DutyAssignment(
        soldier_id=soldier.id,
        duty_type_id=dt.id,
        duty_location_id=loc.id,
        start_date=start_date,
        end_date=start_date,
        status="algorithm_draft",
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def test_reset_drafts_rejects_future_drafts(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rd_dm_001")
    dm = create_soldier(admin_session, personal_number="rd_dm_001", role="duty_manager", hierarchy_node_id=dm_node.id)

    future = date.today() + timedelta(days=60)
    near = date.today() + timedelta(days=5)

    far_draft = _make_draft_assignment(admin_session, "rd_s_001", future)
    near_draft = _make_draft_assignment(admin_session, "rd_s_002", near)

    resp = client.post(
        "/api/algorithm/reset-drafts",
        params={"days_ahead": 30},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rejected"] >= 1

    admin_session.expire(far_draft)
    admin_session.expire(near_draft)
    admin_session.refresh(far_draft)
    admin_session.refresh(near_draft)

    assert far_draft.status == "algorithm_rejected"
    assert near_draft.status == "algorithm_draft"  # within 30 days, untouched


def test_reset_drafts_returns_zero_when_no_matches(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rd_dm_002")
    dm = create_soldier(admin_session, personal_number="rd_dm_002", role="duty_manager", hierarchy_node_id=dm_node.id)

    resp = client.post(
        "/api/algorithm/reset-drafts",
        params={"days_ahead": 365},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 200
    assert resp.json()["rejected"] == 0


def test_reset_drafts_rejects_days_ahead_zero(client, admin_session):
    dm_node = create_node(admin_session, level="branch", name="branch_rd_dm_003")
    dm = create_soldier(admin_session, personal_number="rd_dm_003", role="duty_manager", hierarchy_node_id=dm_node.id)

    resp = client.post(
        "/api/algorithm/reset-drafts",
        params={"days_ahead": 0},
        headers=auth_headers(dm),
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend
uv run pytest tests/integration/test_algorithm_routes.py::test_reset_drafts_rejects_future_drafts tests/integration/test_algorithm_routes.py::test_reset_drafts_returns_zero_when_no_matches tests/integration/test_algorithm_routes.py::test_reset_drafts_rejects_days_ahead_zero -v
```

Expected: 3 failures — `404 Not Found`

- [ ] **Step 3: Implement the endpoint**

Add after the `reset_published_assignments` endpoint in `backend/app/routes/algorithm.py`:

```python
@router.post("/reset-drafts", status_code=status.HTTP_200_OK)
def reset_draft_assignments(
    days_ahead: int = Query(ge=1),
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    from datetime import date, timedelta
    from sqlalchemy import select

    cutoff = date.today() + timedelta(days=days_ahead)
    assignments = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.status == "algorithm_draft",
            DutyAssignment.start_date > cutoff,
        )
    ).scalars().all()

    for a in assignments:
        a.status = "algorithm_rejected"
        write_audit(
            session,
            actor_id=user.id,
            action="algorithm.proposal.bulk_reject",
            entity_type="duty_assignment",
            entity_id=a.id,
            before={"status": "algorithm_draft"},
            after={"status": "algorithm_rejected"},
            context={"days_ahead": days_ahead},
        )

    session.commit()
    return {"rejected": len(assignments)}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd backend
uv run pytest tests/integration/test_algorithm_routes.py::test_reset_drafts_rejects_future_drafts tests/integration/test_algorithm_routes.py::test_reset_drafts_returns_zero_when_no_matches tests/integration/test_algorithm_routes.py::test_reset_drafts_rejects_days_ahead_zero -v
```

Expected: 3 PASSED

- [ ] **Step 5: Run the full algorithm test file to check for regressions**

```bash
cd backend
uv run pytest tests/integration/test_algorithm_routes.py -v
```

Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/algorithm.py backend/tests/integration/test_algorithm_routes.py
git commit -m "feat: POST /algorithm/reset-drafts bulk-reject future algorithm draft assignments"
```

---

### Task 3: Frontend — API client functions

**Files:**
- Modify: `frontend/src/api/algorithm.ts`

- [ ] **Step 1: Add the two API functions**

Append to the end of `frontend/src/api/algorithm.ts`:

```typescript
export async function resetPublished(daysAhead: number): Promise<{ cancelled: number }> {
  return (await api.post<{ cancelled: number }>("/algorithm/reset-published", null, {
    params: { days_ahead: daysAhead },
  })).data;
}

export async function resetDrafts(daysAhead: number): Promise<{ rejected: number }> {
  return (await api.post<{ rejected: number }>("/algorithm/reset-drafts", null, {
    params: { days_ahead: daysAhead },
  })).data;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/algorithm.ts
git commit -m "feat: resetPublished and resetDrafts API client functions"
```

---

### Task 4: Frontend — i18n keys

**Files:**
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add keys to the `algorithm` section**

In `frontend/src/i18n/he.json`, find the `"algorithm"` object and add before its closing `}`:

```json
    "reset_published_label": "ביטול שיבוצים מפורסמים מעבר ל-",
    "reset_published_btn": "בטל שיבוצים",
    "reset_drafts_label": "דחיית טיוטות אלגוריתם מעבר ל-",
    "reset_drafts_btn": "דחה טיוטות",
    "reset_days_suffix": "ימים",
    "reset_confirm_published": "לבטל את כל השיבוצים המפורסמים החל מ-{{date}}?",
    "reset_confirm_drafts": "לדחות את כל טיוטות האלגוריתם החל מ-{{date}}?",
    "reset_result_cancelled": "בוטלו {{count}} שיבוצים",
    "reset_result_rejected": "נדחו {{count}} טיוטות",
    "reset_none": "לא נמצאו שיבוצים לביטול"
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/i18n/he.json
git commit -m "i18n: algorithm bulk reset button labels"
```

---

### Task 5: Frontend — UI in AlgorithmPlanningWindow

**Files:**
- Modify: `frontend/src/components/AlgorithmPlanningWindow.tsx`

- [ ] **Step 1: Import the new API functions**

At the top of `frontend/src/components/AlgorithmPlanningWindow.tsx`, add `resetPublished` and `resetDrafts` to the existing import from `"../api/algorithm"`:

```typescript
import {
  AlgorithmJob,
  ProposalRow,
  SolverSettings,
  acceptProposal,
  pollJob,
  rejectProposal,
  resetDrafts,
  resetPublished,
  submitJob,
} from "../api/algorithm";
```

- [ ] **Step 2: Add state for the reset section**

Inside the `AlgorithmPlanningWindow` component function, after the existing `useState` declarations (around line 54), add:

```typescript
const [resetPublishedDays, setResetPublishedDays] = useState(30);
const [resetDraftsDays, setResetDraftsDays] = useState(30);
const [resetPublishedMsg, setResetPublishedMsg] = useState<string | null>(null);
const [resetDraftsMsg, setResetDraftsMsg] = useState<string | null>(null);
const [resetPublishedLoading, setResetPublishedLoading] = useState(false);
const [resetDraftsLoading, setResetDraftsLoading] = useState(false);
```

- [ ] **Step 3: Add the handler functions**

Inside the component function, after `handleApproveSelected` (around line 155), add:

```typescript
async function handleResetPublished() {
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() + resetPublishedDays);
  const dateStr = cutoff.toISOString().slice(0, 10);
  const confirmed = window.confirm(
    t("algorithm.reset_confirm_published", { date: dateStr })
  );
  if (!confirmed) return;
  setResetPublishedLoading(true);
  setResetPublishedMsg(null);
  try {
    const result = await resetPublished(resetPublishedDays);
    setResetPublishedMsg(
      result.cancelled === 0
        ? t("algorithm.reset_none")
        : t("algorithm.reset_result_cancelled", { count: result.cancelled })
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
  const confirmed = window.confirm(
    t("algorithm.reset_confirm_drafts", { date: dateStr })
  );
  if (!confirmed) return;
  setResetDraftsLoading(true);
  setResetDraftsMsg(null);
  try {
    const result = await resetDrafts(resetDraftsDays);
    setResetDraftsMsg(
      result.rejected === 0
        ? t("algorithm.reset_none")
        : t("algorithm.reset_result_rejected", { count: result.rejected })
    );
  } catch {
    setResetDraftsMsg(t("errors.generic"));
  } finally {
    setResetDraftsLoading(false);
  }
}
```

- [ ] **Step 4: Add the UI section**

In the JSX returned by the component, find the closing `</div>` of the `{open && (<div className="p-4 space-y-4">` block — it is directly before the `{explanationTarget && ...}` block (around line 451). Add the danger zone section immediately before that closing `</div>`:

```tsx
          {/* Bulk reset */}
          <div className="border-t pt-3 space-y-3">
            {/* Reset published */}
            <div className="flex items-center gap-2 text-sm flex-wrap">
              <span className="text-gray-700">{t("algorithm.reset_published_label")}</span>
              <input
                type="number"
                min={1}
                value={resetPublishedDays}
                onChange={e => setResetPublishedDays(Math.max(1, parseInt(e.target.value) || 1))}
                className="w-16 border rounded p-1 text-sm text-center"
              />
              <span className="text-gray-700">{t("algorithm.reset_days_suffix")}</span>
              <button
                type="button"
                onClick={handleResetPublished}
                disabled={resetPublishedLoading}
                className="bg-red-600 text-white px-3 py-1 rounded text-xs hover:bg-red-700 disabled:opacity-50"
              >
                {t("algorithm.reset_published_btn")}
              </button>
              {resetPublishedMsg && (
                <span className="text-xs text-gray-600">{resetPublishedMsg}</span>
              )}
            </div>

            {/* Reset drafts */}
            <div className="flex items-center gap-2 text-sm flex-wrap">
              <span className="text-gray-700">{t("algorithm.reset_drafts_label")}</span>
              <input
                type="number"
                min={1}
                value={resetDraftsDays}
                onChange={e => setResetDraftsDays(Math.max(1, parseInt(e.target.value) || 1))}
                className="w-16 border rounded p-1 text-sm text-center"
              />
              <span className="text-gray-700">{t("algorithm.reset_days_suffix")}</span>
              <button
                type="button"
                onClick={handleResetDrafts}
                disabled={resetDraftsLoading}
                className="bg-amber-600 text-white px-3 py-1 rounded text-xs hover:bg-amber-700 disabled:opacity-50"
              >
                {t("algorithm.reset_drafts_btn")}
              </button>
              {resetDraftsMsg && (
                <span className="text-xs text-gray-600">{resetDraftsMsg}</span>
              )}
            </div>
          </div>
```

- [ ] **Step 5: Run TypeScript type check**

```bash
cd frontend
pnpm tsc --noEmit
```

Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/AlgorithmPlanningWindow.tsx
git commit -m "feat: bulk reset buttons in algorithm planning panel"
```

---

## Self-Review Checklist

- [x] `POST /algorithm/reset-published` — implemented and tested (Tasks 1)
- [x] `POST /algorithm/reset-drafts` — implemented and tested (Task 2)
- [x] `Query` import added to `algorithm.py` FastAPI imports (Task 1 step 3)
- [x] `days_ahead` validated `ge=1` — 422 returned for 0 (tested in both tasks)
- [x] Zero-match case returns 0, not an error (tested in both tasks)
- [x] `cancel_assignment` used for published resets — notification + audit included
- [x] Manual audit write for draft resets — matches existing per-proposal reject pattern
- [x] API client functions use `params: { days_ahead }` to pass query params (not body)
- [x] All i18n keys used in JSX are defined in `he.json`
- [x] State variables and handlers are consistent between steps 2, 3, and 4 of Task 5
- [x] `resetPublished` / `resetDrafts` import names match function names defined in Task 3
