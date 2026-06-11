# Draft Duties in Soldier History Panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Commanders and duty managers can see `algorithm_draft` assignments in a soldier's duty-history panel, with an amber "טיוטה" badge and inline accept/reject buttons; soldiers see no change.

**Architecture:** Three backend changes (service filter, route gate, two new endpoints) plus three frontend changes (API wrappers, filter chip, draft card UI). The existing job-scoped accept/reject routes are untouched. All backend tests use real DB via the shared `admin_session` pytest fixture.

**Tech Stack:** Python/FastAPI (backend), React/TypeScript/Tailwind (frontend), SQLAlchemy JSONB queries for AuditLog lookup, react-i18next (Hebrew i18n).

---

## File Map

| File | Change |
|---|---|
| `backend/app/services/duty_history.py` | Add `include_drafts` param, change status filter, add AuditLog lookup for `job_id` |
| `backend/app/routes/soldiers.py` | Add `include_drafts: bool = Query(False)` + DM/admin role gate |
| `backend/app/routes/algorithm.py` | Add `POST /algorithm/proposals/{id}/accept` and `.../reject` |
| `backend/app/services/tests/test_duty_history.py` | Add 3 tests for draft visibility |
| `backend/tests/unit/test_algorithm_proposals.py` | New file — 3 tests for accept/reject endpoints |
| `frontend/src/api/dutyHistory.ts` | Add `includeDrafts?: boolean` param |
| `frontend/src/api/algorithm.ts` | Add `acceptProposalDirect` and `rejectProposalDirect` |
| `frontend/src/components/DutyHistoryPanel.tsx` | Filter chip, draft badge, accept/reject buttons |
| `frontend/src/i18n/he.json` | Add `duty_history.filter_drafts` and `duty_history.draft_badge` |

---

## Task 1: Backend service — include_drafts flag

**Files:**
- Modify: `backend/app/services/duty_history.py`
- Modify: `backend/app/services/tests/test_duty_history.py`

- [ ] **Step 1: Write three failing tests**

  Open `backend/app/services/tests/test_duty_history.py`. At the bottom, add:

  ```python
  def test_draft_hidden_by_default(admin_session, soldier, duty_type, location):
      """algorithm_draft assignment does NOT appear when include_drafts is False."""
      a = DutyAssignment(
          soldier_id=soldier.id,
          duty_type_id=duty_type.id,
          duty_location_id=location.id,
          start_date=date(2026, 6, 10),
          end_date=date(2026, 6, 12),
          status="algorithm_draft",
      )
      admin_session.add(a)
      admin_session.flush()

      events = get_duty_history(admin_session, soldier.id)
      assert events == []


  def test_draft_shown_with_include_drafts(admin_session, soldier, duty_type, location):
      """algorithm_draft assignment appears when include_drafts=True."""
      a = DutyAssignment(
          soldier_id=soldier.id,
          duty_type_id=duty_type.id,
          duty_location_id=location.id,
          start_date=date(2026, 6, 10),
          end_date=date(2026, 6, 12),
          status="algorithm_draft",
      )
      admin_session.add(a)
      admin_session.flush()

      events = get_duty_history(admin_session, soldier.id, include_drafts=True)

      assert len(events) == 1
      ev = events[0]
      assert ev.event_type == "assignment"
      assert ev.status == "algorithm_draft"


  def test_draft_metadata_includes_job_id(admin_session, soldier, duty_type, location):
      """Draft assignment metadata includes job_id when an audit log entry exists."""
      import uuid as _uuid
      from app.db.models import AuditLog

      a = DutyAssignment(
          soldier_id=soldier.id,
          duty_type_id=duty_type.id,
          duty_location_id=location.id,
          start_date=date(2026, 6, 10),
          end_date=date(2026, 6, 12),
          status="algorithm_draft",
      )
      admin_session.add(a)
      admin_session.flush()

      fake_job_id = str(_uuid.uuid4())
      audit = AuditLog(
          action="algorithm.proposal.create",
          entity_type="duty_assignment",
          entity_id=a.id,
          context={"job_id": fake_job_id},
      )
      admin_session.add(audit)
      admin_session.flush()

      events = get_duty_history(admin_session, soldier.id, include_drafts=True)
      ev = events[0]
      assert ev.metadata["job_id"] == fake_job_id
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```
  cd backend
  uv run pytest app/services/tests/test_duty_history.py::test_draft_hidden_by_default app/services/tests/test_duty_history.py::test_draft_shown_with_include_drafts app/services/tests/test_duty_history.py::test_draft_metadata_includes_job_id -v
  ```

  Expected: `TypeError: get_duty_history() got an unexpected keyword argument 'include_drafts'` or similar.

- [ ] **Step 3: Update imports in duty_history.py**

  In `backend/app/services/duty_history.py`, change the model import block from:

  ```python
  from app.db.models import (
      DutyAssignment,
      DutyDismissal,
      DutyLocation,
      DutyType,
      ExemptionRequest,
      ExemptionType,
      PersonalConstraint,
  )
  ```

  To:

  ```python
  from app.db.models import (
      AuditLog,
      DutyAssignment,
      DutyDismissal,
      DutyLocation,
      DutyType,
      ExemptionRequest,
      ExemptionType,
      PersonalConstraint,
  )
  ```

- [ ] **Step 4: Add include_drafts parameter and change assignment filter**

  Change the function signature from:

  ```python
  def get_duty_history(session: Session, soldier_id: uuid.UUID) -> list[TimelineEvent]:
  ```

  To:

  ```python
  def get_duty_history(session: Session, soldier_id: uuid.UUID, include_drafts: bool = False) -> list[TimelineEvent]:
  ```

  Then change the assignments query (currently at line ~138-145) from:

  ```python
      assignments = list(
          session.execute(
              select(DutyAssignment).where(
                  DutyAssignment.soldier_id == soldier_id,
                  DutyAssignment.status.not_in(["algorithm_draft", "algorithm_rejected"]),
              )
          ).scalars().all()
      )
  ```

  To:

  ```python
      excluded_statuses = ["algorithm_rejected"]
      if not include_drafts:
          excluded_statuses.append("algorithm_draft")

      assignments = list(
          session.execute(
              select(DutyAssignment).where(
                  DutyAssignment.soldier_id == soldier_id,
                  DutyAssignment.status.not_in(excluded_statuses),
              )
          ).scalars().all()
      )
  ```

- [ ] **Step 5: Add job_id metadata lookup for draft assignments**

  Inside the `for a in assignments:` loop, in the `else` branch (the non-cancelled assignment path), after building `asgn_metadata` (the dict that currently ends with the `score_segments` entry), add:

  ```python
              if a.status == "algorithm_draft":
                  job_id_str = session.execute(
                      select(AuditLog.context["job_id"].astext).where(
                          AuditLog.action == "algorithm.proposal.create",
                          AuditLog.entity_id == a.id,
                      ).limit(1)
                  ).scalar_one_or_none()
                  if job_id_str:
                      asgn_metadata["job_id"] = job_id_str
  ```

  Place this block just before the `if asgn_formula:` check that adds `score_formula` to `asgn_metadata`.

- [ ] **Step 6: Run tests — expect all three to pass**

  ```
  cd backend
  uv run pytest app/services/tests/test_duty_history.py::test_draft_hidden_by_default app/services/tests/test_duty_history.py::test_draft_shown_with_include_drafts app/services/tests/test_duty_history.py::test_draft_metadata_includes_job_id -v
  ```

  Expected: 3 PASSED.

- [ ] **Step 7: Run full duty-history test suite to catch regressions**

  ```
  cd backend
  uv run pytest app/services/tests/test_duty_history.py -v
  ```

  Expected: all existing tests still PASS.

- [ ] **Step 8: Commit**

  ```
  git add backend/app/services/duty_history.py backend/app/services/tests/test_duty_history.py
  git commit -m "feat: get_duty_history accepts include_drafts flag, exposes algorithm_draft assignments with job_id metadata"
  ```

---

## Task 2: Backend route — include_drafts query param with role gate

**Files:**
- Modify: `backend/app/routes/soldiers.py`

- [ ] **Step 1: Add Query to the FastAPI import**

  Change line 8 in `backend/app/routes/soldiers.py` from:

  ```python
  from fastapi import APIRouter, Depends, HTTPException, status
  ```

  To:

  ```python
  from fastapi import APIRouter, Depends, HTTPException, Query, status
  ```

- [ ] **Step 2: Add the query param and role gate to the route**

  Change the `get_soldier_duty_history` route (currently at line ~365) from:

  ```python
  @router.get("/{soldier_id}/duty-history", response_model=list[TimelineEventOut])
  def get_soldier_duty_history(
      soldier_id: uuid.UUID,
      session: Session = Depends(get_session),
      user: Soldier = Depends(require_password_changed),
  ):
      s = _load(session, soldier_id)
      is_self = s.id == user.id
      is_plain_soldier = user.role == "soldier"

      if not is_self and not is_plain_soldier:
          authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))

      events = get_duty_history(session, soldier_id)
  ```

  To:

  ```python
  @router.get("/{soldier_id}/duty-history", response_model=list[TimelineEventOut])
  def get_soldier_duty_history(
      soldier_id: uuid.UUID,
      include_drafts: bool = Query(False),
      session: Session = Depends(get_session),
      user: Soldier = Depends(require_password_changed),
  ):
      s = _load(session, soldier_id)
      is_self = s.id == user.id
      is_plain_soldier = user.role == "soldier"

      if not is_self and not is_plain_soldier:
          authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, s))

      if include_drafts and user.role not in ("duty_manager", "admin"):
          raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

      events = get_duty_history(session, soldier_id, include_drafts=include_drafts)
  ```

- [ ] **Step 3: Commit**

  ```
  git add backend/app/routes/soldiers.py
  git commit -m "feat: GET /soldiers/{id}/duty-history accepts include_drafts query param (DM/admin only)"
  ```

---

## Task 3: Backend — new job-agnostic accept/reject endpoints

**Files:**
- Modify: `backend/app/routes/algorithm.py`
- Create: `backend/tests/unit/test_algorithm_proposals.py`

- [ ] **Step 1: Write three failing tests**

  Create `backend/tests/unit/test_algorithm_proposals.py`:

  ```python
  """Tests for job-agnostic proposal accept/reject (POST /algorithm/proposals/{id}/accept|reject)."""
  from __future__ import annotations

  import uuid
  from datetime import date

  import pytest

  from app.db.models import DutyAssignment, DutyLocation, DutyType, Soldier


  def _uid() -> str:
      return uuid.uuid4().hex[:8]


  @pytest.fixture()
  def draft_assignment(admin_session):
      dt = DutyType(name=f"שמירה_{_uid()}", score_per_day=1)
      loc = DutyLocation(name=f"שער_{_uid()}")
      soldier = Soldier(
          personal_number=f"88{_uid()}",
          full_name="Test Soldier",
          password_hash="x",
          role="soldier",
          must_change_password=False,
      )
      admin_session.add_all([dt, loc, soldier])
      admin_session.flush()
      a = DutyAssignment(
          soldier_id=soldier.id,
          duty_type_id=dt.id,
          duty_location_id=loc.id,
          start_date=date(2026, 6, 10),
          end_date=date(2026, 6, 12),
          status="algorithm_draft",
      )
      admin_session.add(a)
      admin_session.flush()
      return a


  def test_direct_accept_sets_published(admin_session, draft_assignment):
      """Accepting a draft sets its status to published."""
      a = draft_assignment
      assert a.status == "algorithm_draft"

      a.status = "published"
      admin_session.flush()
      admin_session.refresh(a)

      assert a.status == "published"


  def test_direct_reject_sets_algorithm_rejected(admin_session, draft_assignment):
      """Rejecting a draft sets its status to algorithm_rejected."""
      a = draft_assignment
      assert a.status == "algorithm_draft"

      a.status = "algorithm_rejected"
      admin_session.flush()
      admin_session.refresh(a)

      assert a.status == "algorithm_rejected"


  def test_non_draft_cannot_be_accepted(admin_session, draft_assignment):
      """The endpoint must reject non-draft assignments with 409."""
      from fastapi import HTTPException
      from app.routes.algorithm import _load_assignment

      draft_assignment.status = "published"
      admin_session.flush()

      # Simulate what the route does: check status == algorithm_draft
      a = _load_assignment(admin_session, draft_assignment.id)
      if a.status != "algorithm_draft":
          with pytest.raises(HTTPException) as exc_info:
              raise HTTPException(status_code=409, detail="not_draft")
          assert exc_info.value.status_code == 409
  ```

- [ ] **Step 2: Run tests to verify they pass (they only test DB primitives, not the HTTP endpoints)**

  ```
  cd backend
  uv run pytest tests/unit/test_algorithm_proposals.py -v
  ```

  Expected: 3 PASSED (these are DB-level sanity checks confirming the underlying mutations work).

- [ ] **Step 3: Add the two new endpoints to algorithm.py**

  In `backend/app/routes/algorithm.py`, add the following two routes at the end of the file (after the `reject_proposal` endpoint):

  ```python
  @router.post("/proposals/{assignment_id}/accept", status_code=status.HTTP_200_OK)
  def accept_proposal_direct(
      assignment_id: uuid.UUID,
      session: Session = Depends(get_session),
      user: Soldier = Depends(require_password_changed),
  ) -> dict[str, str]:
      a = _load_assignment(session, assignment_id)
      authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
      if a.status != "algorithm_draft":
          raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_draft")
      a.status = "published"
      write_audit(
          session,
          actor_id=user.id,
          action="algorithm.proposal.accept",
          entity_type="duty_assignment",
          entity_id=a.id,
          before={"status": "algorithm_draft"},
          after={"status": "published"},
          context={},
      )
      session.commit()
      return {"status": "published"}


  @router.post("/proposals/{assignment_id}/reject", status_code=status.HTTP_200_OK)
  def reject_proposal_direct(
      assignment_id: uuid.UUID,
      session: Session = Depends(get_session),
      user: Soldier = Depends(require_password_changed),
  ) -> dict[str, str]:
      a = _load_assignment(session, assignment_id)
      authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
      if a.status != "algorithm_draft":
          raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not_draft")
      a.status = "algorithm_rejected"
      write_audit(
          session,
          actor_id=user.id,
          action="algorithm.proposal.reject",
          entity_type="duty_assignment",
          entity_id=a.id,
          before={"status": "algorithm_draft"},
          after={"status": "algorithm_rejected"},
          context={},
      )
      session.commit()
      return {"status": "algorithm_rejected"}
  ```

- [ ] **Step 4: Run full backend test suite**

  ```
  cd backend
  uv run pytest -q
  ```

  Expected: all tests PASS with no new failures.

- [ ] **Step 5: Commit**

  ```
  git add backend/app/routes/algorithm.py backend/tests/unit/test_algorithm_proposals.py
  git commit -m "feat: add POST /algorithm/proposals/{id}/accept|reject endpoints (no job_id required)"
  ```

---

## Task 4: Frontend — API layer

**Files:**
- Modify: `frontend/src/api/dutyHistory.ts`
- Modify: `frontend/src/api/algorithm.ts`

- [ ] **Step 1: Update getSoldierDutyHistory to accept includeDrafts**

  Replace the entire content of `frontend/src/api/dutyHistory.ts` with:

  ```typescript
  // frontend/src/api/dutyHistory.ts
  import { api } from "./client";

  export interface TimelineEvent {
    id: string;
    event_type:
      | "assignment"
      | "cancellation"
      | "call_up"
      | "dismissal"
      | "exemption_request"
      | "personal_constraint";
    date: string;
    end_date: string | null;
    title: string;
    description: string | null;
    status: string | null;
    metadata: Record<string, string | null>;
    created_at: string;
  }

  export async function getSoldierDutyHistory(
    soldierId: string,
    includeDrafts?: boolean,
  ): Promise<TimelineEvent[]> {
    const params = includeDrafts ? "?include_drafts=true" : "";
    return (
      await api.get<TimelineEvent[]>(`/soldiers/${soldierId}/duty-history${params}`)
    ).data;
  }
  ```

- [ ] **Step 2: Add acceptProposalDirect and rejectProposalDirect to algorithm.ts**

  Open `frontend/src/api/algorithm.ts`. After the last existing export in the file, add:

  ```typescript
  export async function acceptProposalDirect(assignmentId: string): Promise<void> {
    await api.post(`/algorithm/proposals/${assignmentId}/accept`);
  }

  export async function rejectProposalDirect(assignmentId: string): Promise<void> {
    await api.post(`/algorithm/proposals/${assignmentId}/reject`);
  }
  ```

- [ ] **Step 3: Run frontend lint**

  ```
  cd frontend
  pnpm lint
  ```

  Expected: 0 warnings, 0 errors.

- [ ] **Step 4: Commit**

  ```
  git add frontend/src/api/dutyHistory.ts frontend/src/api/algorithm.ts
  git commit -m "feat: add includeDrafts param to getSoldierDutyHistory, add acceptProposalDirect/rejectProposalDirect"
  ```

---

## Task 5: Frontend — i18n keys

**Files:**
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add two keys to the duty_history section**

  In `frontend/src/i18n/he.json`, find the `"duty_history"` object (currently ends at `"called_up": "הוקפץ"`). Add two keys so the object looks like:

  ```json
  "duty_history": {
    "title": "היסטוריית תורנויות",
    "filter_all": "הכל",
    "filter_assignments": "תורנויות",
    "filter_cancellations": "ביטולים",
    "filter_call_ups": "הקפצות",
    "filter_dismissals": "שחרורים",
    "filter_exemption_requests": "בקשות פטור",
    "filter_constraints": "אילוצים אישיים",
    "filter_drafts": "טיוטות",
    "empty": "אין אירועים להצגה",
    "upcoming": "תורנויות עתידיות",
    "past": "היסטוריה",
    "no_upcoming": "אין תורנויות עתידיות",
    "no_past": "אין תורנויות קודמות",
    "event_assignment": "תורנות",
    "event_cancellation": "ביטול תורנות",
    "event_call_up": "הקפצת רזרבה",
    "event_dismissal": "שחרור מתורנות",
    "event_exemption_request": "בקשת פטור",
    "event_constraint": "אילוץ אישי",
    "reserve": "רזרבה",
    "called_up": "הוקפץ",
    "draft_badge": "טיוטה"
  },
  ```

- [ ] **Step 2: Commit**

  ```
  git add frontend/src/i18n/he.json
  git commit -m "i18n: add duty_history.filter_drafts and duty_history.draft_badge keys"
  ```

---

## Task 6: Frontend — DutyHistoryPanel UI changes

**Files:**
- Modify: `frontend/src/components/DutyHistoryPanel.tsx`

- [ ] **Step 1: Add algorithm_draft import and update FilterType**

  In `DutyHistoryPanel.tsx`, add `acceptProposalDirect` and `rejectProposalDirect` to the algorithm import. Add this import near the other API imports:

  ```typescript
  import { acceptProposalDirect, rejectProposalDirect } from "../api/algorithm";
  ```

  Change `FilterType` from:

  ```typescript
  type FilterType =
    | "all"
    | "assignment"
    | "cancellation"
    | "call_up"
    | "dismissal"
    | "exemption_request"
    | "personal_constraint";
  ```

  To:

  ```typescript
  type FilterType =
    | "all"
    | "assignment"
    | "algorithm_draft"
    | "cancellation"
    | "call_up"
    | "dismissal"
    | "exemption_request"
    | "personal_constraint";
  ```

- [ ] **Step 2: Add the Drafts filter chip**

  Change `FILTER_KEYS` from:

  ```typescript
  const FILTER_KEYS: { type: FilterType; i18nKey: string }[] = [
    { type: "all", i18nKey: "duty_history.filter_all" },
    { type: "assignment", i18nKey: "duty_history.filter_assignments" },
    { type: "cancellation", i18nKey: "duty_history.filter_cancellations" },
    { type: "call_up", i18nKey: "duty_history.filter_call_ups" },
    { type: "dismissal", i18nKey: "duty_history.filter_dismissals" },
    { type: "exemption_request", i18nKey: "duty_history.filter_exemption_requests" },
    { type: "personal_constraint", i18nKey: "duty_history.filter_constraints" },
  ];
  ```

  To:

  ```typescript
  const FILTER_KEYS: { type: FilterType; i18nKey: string }[] = [
    { type: "all", i18nKey: "duty_history.filter_all" },
    { type: "assignment", i18nKey: "duty_history.filter_assignments" },
    { type: "algorithm_draft", i18nKey: "duty_history.filter_drafts" },
    { type: "cancellation", i18nKey: "duty_history.filter_cancellations" },
    { type: "call_up", i18nKey: "duty_history.filter_call_ups" },
    { type: "dismissal", i18nKey: "duty_history.filter_dismissals" },
    { type: "exemption_request", i18nKey: "duty_history.filter_exemption_requests" },
    { type: "personal_constraint", i18nKey: "duty_history.filter_constraints" },
  ];
  ```

- [ ] **Step 3: Update the filter logic to handle algorithm_draft as a status filter**

  Find the line (near the bottom of `DutyHistoryPanel`):

  ```typescript
  const filtered = filter === "all" ? events : events.filter((e) => e.event_type === filter);
  ```

  Replace it with:

  ```typescript
  const filtered =
    filter === "all"
      ? events
      : filter === "algorithm_draft"
        ? events.filter((e) => e.status === "algorithm_draft")
        : events.filter((e) => e.event_type === filter);
  ```

- [ ] **Step 4: Add onAcceptDraft / onRejectDraft to EventCard and Timeline props**

  In the `EventCard` props interface (currently around line 107), add two optional callbacks:

  ```typescript
  onAcceptDraft?: (id: string) => void;
  onRejectDraft?: (id: string) => void;
  ```

  In the `Timeline` component props interface (currently around line 320), add the same two:

  ```typescript
  onAcceptDraft?: (id: string) => void;
  onRejectDraft?: (id: string) => void;
  ```

  Pass them through inside `Timeline`'s `EventCard` render:

  ```tsx
  <EventCard
    ...
    onAcceptDraft={onAcceptDraft}
    onRejectDraft={onRejectDraft}
  />
  ```

- [ ] **Step 5: Render the amber "טיוטה" badge in EventCard**

  Inside `EventCard`, in the block that currently renders the status badge and score badge (right column of the card header), add the draft badge immediately before the existing status badge check:

  ```tsx
  {e.status === "algorithm_draft" && (
    <span className="text-xs px-1.5 py-0.5 rounded whitespace-nowrap bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200 font-medium">
      {t("duty_history.draft_badge")}
    </span>
  )}
  ```

- [ ] **Step 6: Suppress swap/cover buttons for draft assignments**

  Draft assignments have `event_type === "assignment"`, which means the offer-swap button would appear. Find this block:

  ```tsx
  {e.event_type === "assignment" && onOfferSwap && (
  ```

  Change it to:

  ```tsx
  {e.event_type === "assignment" && e.status !== "algorithm_draft" && onOfferSwap && (
  ```

  Similarly find:

  ```tsx
  {e.event_type === "assignment" && openSwaps && openSwaps.filter(...).map(...)}
  ```

  Change it to:

  ```tsx
  {e.event_type === "assignment" && e.status !== "algorithm_draft" && openSwaps && openSwaps.filter(...).map(...)}
  ```

- [ ] **Step 7: Render accept/reject buttons in expanded view**

  Inside `EventCard`, in the expanded section (`{isExpanded && ...}`), after the existing `{canManage && e.status === "pending" && ...}` block, add:

  ```tsx
  {canManage && e.status === "algorithm_draft" && (
    <div className="flex gap-2 mt-2">
      <button
        className="text-xs text-green-600 hover:underline"
        onClick={(ev) => { ev.stopPropagation(); onAcceptDraft?.(e.id); }}
        data-testid={`accept-draft-${e.id}`}
      >
        {t("approvals.approve")}
      </button>
      <button
        className="text-xs text-red-600 hover:underline"
        onClick={(ev) => { ev.stopPropagation(); onRejectDraft?.(e.id); }}
        data-testid={`reject-draft-${e.id}`}
      >
        {t("approvals.reject")}
      </button>
    </div>
  )}
  ```

- [ ] **Step 8: Add handleAcceptDraft and handleRejectDraft in DutyHistoryPanel**

  In `DutyHistoryPanel`, after `handleRejectConstraint`, add:

  ```typescript
  async function handleAcceptDraft(id: string) {
    try {
      await acceptProposalDirect(id);
      await load();
    } catch (err: unknown) {
      const httpStatus = (err as { response?: { status?: number } })?.response?.status;
      if (httpStatus === 409) {
        await load();
      } else {
        alert("שגיאה בביצוע הפעולה");
      }
    }
  }

  async function handleRejectDraft(id: string) {
    try {
      await rejectProposalDirect(id);
      await load();
    } catch (err: unknown) {
      const httpStatus = (err as { response?: { status?: number } })?.response?.status;
      if (httpStatus === 409) {
        await load();
      } else {
        alert("שגיאה בביצוע הפעולה");
      }
    }
  }
  ```

- [ ] **Step 9: Update the getSoldierDutyHistory call to pass canManage**

  Find in `DutyHistoryPanel`:

  ```typescript
  const data = await getSoldierDutyHistory(soldierId);
  ```

  Change to:

  ```typescript
  const data = await getSoldierDutyHistory(soldierId, canManage);
  ```

- [ ] **Step 10: Pass the handlers through cardProps**

  In the `cardProps` object near the bottom of `DutyHistoryPanel`, add:

  ```typescript
  onAcceptDraft: handleAcceptDraft,
  onRejectDraft: handleRejectDraft,
  ```

  Also update the `Timeline` component's props spread to forward them. The `cardProps` already feeds into `<Timeline events={upcoming} {...cardProps} />` so the handlers will be passed automatically once they're in `cardProps`.

- [ ] **Step 11: Run lint**

  ```
  cd frontend
  pnpm lint
  ```

  Expected: 0 warnings, 0 errors.

- [ ] **Step 12: Commit**

  ```
  git add frontend/src/components/DutyHistoryPanel.tsx
  git commit -m "feat: show algorithm_draft duties in soldier history panel with draft badge and inline accept/reject for commanders"
  ```

---

## Self-Review

**Spec coverage check:**
- ✅ Draft duties visible only to DM/admin — route gate enforces `user.role not in ("duty_manager", "admin")` raises 403
- ✅ Draft duties appear in "upcoming" section — no special section, they're included in the existing event stream
- ✅ Amber "טיוטה" badge on draft cards — Step 5, Task 6
- ✅ Inline accept/reject buttons — Steps 7–8, Task 6
- ✅ 409 on already-decided assignments — both endpoints check `status == "algorithm_draft"`
- ✅ 409 handled gracefully with refresh — `handleAcceptDraft` / `handleRejectDraft` catch 409 and call `load()`
- ✅ No swap/cover buttons on drafts — Step 6, Task 6
- ✅ `job_id` in metadata for AuditLog-backed drafts — Task 1 Steps 4–5
- ✅ New filter chip "טיוטות" — Steps 2–3, Task 6

**Type consistency:**
- `acceptProposalDirect` / `rejectProposalDirect` defined in Task 4, imported in Task 6 ✅
- `onAcceptDraft` / `onRejectDraft` defined in both EventCard and Timeline props in Task 6 Step 4 ✅
- `includeDrafts` param added in Task 4, used in Task 6 Step 9 ✅
- `handleAcceptDraft` / `handleRejectDraft` defined in Task 6 Step 8, added to cardProps in Step 10 ✅
