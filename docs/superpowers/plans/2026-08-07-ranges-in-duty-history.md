# Ranges in Duty History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every range a soldier is/was connected to appears in their duty-history timeline — current assignments (attended, not-yet-attended, unactivated reserve, promoted-from-reserve) and removals (via excusal or direct removal), the latter now carrying a reason and surviving assignment deletion.

**Architecture:** `RangeExcusalRequest` gains a permanent `range_event_id` so excusal-based removals keep their range identity after the `RangeAssignment` row is deleted. `remove_range_assignment` gains a required reason and an audit-log write, giving direct removals the same durability. `duty_history.py::get_duty_history` reads both as one normalized `range_removed` event type, alongside a new `range_assignment` event type for everything still on the roster.

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy 2.0 (backend), React 18 / TypeScript / Vite (frontend), pytest (backend tests), Vitest (frontend tests), Alembic (migrations).

## Global Constraints

- Design spec: [`docs/superpowers/specs/2026-08-07-ranges-in-duty-history-design.md`](../specs/2026-08-07-ranges-in-duty-history-design.md).
- `RangeExcusalRequest.range_event_id` is nullable — existing rows whose assignment is already deleted stay incomplete; only new rows going forward are guaranteed complete.
- `remove_range_assignment`'s new `reason` parameter is required (no default) — this is a breaking signature change; every call site must be updated in the same task that changes the signature to avoid a broken intermediate state.
- Backend tests run via `pytest -q <path>` from `backend/` (venv activated); frontend tests via `npm test -- <path>` from `frontend/`.

---

### Task 1: Migration — `RangeExcusalRequest.range_event_id`

**Files:**
- Create: `backend/alembic/versions/<new_revision>_add_range_event_id_to_excusal_requests.py`

**Interfaces:**
- Produces: `range_excusal_requests.range_event_id` (nullable UUID FK to `range_events.id`, `ondelete="SET NULL"`).

- [ ] **Step 1: Generate the revision skeleton**

```bash
cd backend
alembic revision -m "add_range_event_id_to_excusal_requests"
```

- [ ] **Step 2: Write the migration body**

```python
"""add_range_event_id_to_excusal_requests

Revision ID: <new_revision>
Revises: <auto-filled head>
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "<new_revision>"
down_revision = "<auto-filled head>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "range_excusal_requests",
        sa.Column(
            "range_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("range_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE range_excusal_requests r
        SET range_event_id = a.range_event_id
        FROM range_assignments a
        WHERE r.range_assignment_id = a.id
        """
    )


def downgrade() -> None:
    op.drop_column("range_excusal_requests", "range_event_id")
```

(The backfill `UPDATE` recovers `range_event_id` for every existing request whose assignment hasn't been deleted yet — only requests whose assignment was *already* deleted before this migration stay `NULL`, as documented in the spec.)

- [ ] **Step 3: Apply and verify**

```bash
alembic upgrade head
```
Expected: applies cleanly.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/*_add_range_event_id_to_excusal_requests.py
git commit -m "feat: add range_event_id to range_excusal_requests with backfill"
```

---

### Task 2: Model — `RangeExcusalRequest.range_event_id`

**Files:**
- Modify: `backend/app/db/models.py:922-960` (`RangeExcusalRequest` class)

**Interfaces:**
- Produces: `RangeExcusalRequest.range_event_id: uuid.UUID | None`.

- [ ] **Step 1: Add the field**

In `backend/app/db/models.py`, inside `RangeExcusalRequest` (after `range_assignment_id`, line 938-940):

```python
    range_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("range_assignments.id", ondelete="SET NULL"), nullable=True
    )
    # Set once at request creation and never cleared — survives range_assignment_id
    # being nulled out when the assignment row is later deleted (approved excusal),
    # so duty-history can still identify which range this request was for.
    range_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("range_events.id", ondelete="SET NULL"), nullable=True, default=None
    )
```

- [ ] **Step 2: Verify**

```bash
python -c "from app.db.models import RangeExcusalRequest; import inspect; print('range_event_id' in RangeExcusalRequest.__init__.__annotations__ or True)"
```
Run `pytest tests/unit/test_range_excusal.py -v` (existing suite) to confirm the model change doesn't break anything requiring a positional-arg count match — `RangeExcusalRequest(...)` is always constructed with keyword args in this codebase, so this should be a no-op for existing callers.
Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat: add RangeExcusalRequest.range_event_id model field"
```

---

### Task 3: `range_excusal.py` — populate `range_event_id`

**Files:**
- Modify: `backend/app/services/range_excusal.py:58-112` (`request_primary_excusal`, `request_reserve_excusal`)
- Test: `backend/tests/unit/test_range_excusal.py` (add cases; check the file first for exact fixture/import style)

**Interfaces:**
- Produces: every newly-created `RangeExcusalRequest` has `range_event_id` set to `assignment.range_event_id`.

- [ ] **Step 1: Write the failing tests**

```python
# Add to backend/tests/unit/test_range_excusal.py (match existing imports/fixtures already in the file)
def test_primary_excusal_request_stores_range_event_id(app_session):
    from datetime import date, timedelta
    from app.services.range_excusal import request_primary_excusal
    from app.services.ranges import add_range_assignment, create_range_event
    from app.db.models import RangeType
    from tests.helpers import create_node, create_range_location, create_soldier

    node = create_node(app_session, level="branch", name="rex-node-1")
    soldier = create_soldier(app_session, personal_number="rex-001", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id, required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    request = request_primary_excusal(app_session, assignment=assignment, reason="בדיקה", requested_by=soldier.id)

    assert request.range_event_id == event.id


def test_reserve_excusal_request_stores_range_event_id(app_session):
    from datetime import date, timedelta
    from app.services.range_excusal import request_reserve_excusal
    from app.services.ranges import add_range_assignment, create_range_event
    from app.db.models import RangeType
    from tests.helpers import create_node, create_range_location, create_soldier

    node = create_node(app_session, level="branch", name="rex-node-2")
    soldier = create_soldier(app_session, personal_number="rex-002", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id, required_count=1, reserve_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=True)

    request = request_reserve_excusal(app_session, assignment=assignment, reason="בדיקה", requested_by=soldier.id)

    assert request.range_event_id == event.id
    # The assignment is deleted synchronously by request_reserve_excusal — confirm
    # range_event_id survives that even within the same request/response cycle.
    assert request.range_assignment_id is None
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/unit/test_range_excusal.py -v -k range_event_id
```
Expected: FAIL — `request.range_event_id` is `None` (field exists per Task 2 but nothing populates it yet).

- [ ] **Step 3: Implement**

In `backend/app/services/range_excusal.py`, add `range_event_id=assignment.range_event_id` to both `RangeExcusalRequest(...)` constructions:

`request_primary_excusal` (line 67-70):
```python
    request = RangeExcusalRequest(
        range_assignment_id=assignment.id, range_event_id=assignment.range_event_id,
        requested_by=requested_by, reason=_validate_reason(reason), status=RangeExcusalStatus.pending,
    )
```

`request_reserve_excusal` (line 92-96):
```python
    request = RangeExcusalRequest(
        range_assignment_id=assignment.id, range_event_id=assignment.range_event_id,
        requested_by=requested_by, reason=_validate_reason(reason), status=RangeExcusalStatus.approved,
        decided_by=None, decided_at=datetime.now(UTC),
    )
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/unit/test_range_excusal.py -v
```
Expected: all PASS (new + pre-existing).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/range_excusal.py backend/tests/unit/test_range_excusal.py
git commit -m "feat: store range_event_id on excusal requests at creation time"
```

---

### Task 4: `remove_range_assignment` — required reason + audit log

**Files:**
- Modify: `backend/app/services/ranges.py:393-407`
- Test: `backend/tests/unit/test_ranges_service.py` (check the file first for exact style; create if it doesn't exist alongside other `ranges.py` service tests)

**Interfaces:**
- Produces: `remove_range_assignment(session, *, assignment, reason: str, actor_id=None) -> None`, writes `AuditLog(action="range_assignment.remove", entity_type="range_assignment", entity_id=assignment.id, before={"soldier_id": str, "range_event_id": str, "is_reserve": bool}, context={"reason": str})` before deleting.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_ranges_service.py — check if this file already exists; if so append, else create with these imports:
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import AuditLog, RangeAssignment, RangeType
from app.services.ranges import RangeValidationError, add_range_assignment, create_range_event, remove_range_assignment
from tests.helpers import create_node, create_range_location, create_soldier


def test_remove_range_assignment_requires_reason(app_session):
    node = create_node(app_session, level="branch", name="rra-node-1")
    soldier = create_soldier(app_session, personal_number="rra-001", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id, required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)

    with pytest.raises(TypeError):
        remove_range_assignment(app_session, assignment=assignment, actor_id=soldier.id)  # type: ignore[call-arg]


def test_remove_range_assignment_writes_audit_log(app_session):
    node = create_node(app_session, level="branch", name="rra-node-2")
    soldier = create_soldier(app_session, personal_number="rra-002", hierarchy_node_id=node.id)
    manager = create_soldier(app_session, personal_number="rra-003", role="duty_manager", hierarchy_node_id=node.id)
    event = create_range_event(
        app_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(app_session).id, required_count=1,
    )
    assignment = add_range_assignment(app_session, event=event, soldier_id=soldier.id, is_reserve=False)
    assignment_id = assignment.id

    remove_range_assignment(app_session, assignment=assignment, reason="חייל שוחרר מהיחידה", actor_id=manager.id)

    remaining = app_session.execute(
        select(RangeAssignment).where(RangeAssignment.id == assignment_id)
    ).scalar_one_or_none()
    assert remaining is None

    audit = app_session.execute(
        select(AuditLog).where(
            AuditLog.action == "range_assignment.remove",
            AuditLog.entity_id == assignment_id,
        )
    ).scalar_one()
    assert audit.before["soldier_id"] == str(soldier.id)
    assert audit.before["range_event_id"] == str(event.id)
    assert audit.context["reason"] == "חייל שוחרר מהיחידה"
    assert audit.actor_id == manager.id
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/unit/test_ranges_service.py -v -k remove_range_assignment
```
Expected: FAIL — `remove_range_assignment` currently has no `reason` param (so the first test's `TypeError` expectation actually fails today because the call *without* reason succeeds), and no `AuditLog` row is written for the second test.

- [ ] **Step 3: Implement**

In `backend/app/services/ranges.py`, replace `remove_range_assignment` (lines 393-407):

```python
def remove_range_assignment(
    session: Session, *, assignment: RangeAssignment, reason: str, actor_id: uuid.UUID | None = None,
) -> None:
    event = session.get(RangeEvent, assignment.range_event_id)
    if event is not None and event.status != RangeEventStatus.planned:
        raise RangeValidationError("event_not_planned")
    remaining_ids = set(session.execute(select(RangeAssignment.soldier_id).where(
        RangeAssignment.range_event_id == assignment.range_event_id,
        RangeAssignment.id != assignment.id,
    )).scalars())
    soldier_id = assignment.soldier_id
    write_audit(
        session, actor_id=actor_id, action="range_assignment.remove", entity_type="range_assignment",
        entity_id=assignment.id,
        before={
            "soldier_id": str(soldier_id),
            "range_event_id": str(assignment.range_event_id),
            "is_reserve": assignment.is_reserve,
        },
        context={"reason": reason},
    )
    session.delete(assignment)
    session.flush()
    _notify_roster_change(
        session, event=event, soldier_ids=remaining_ids | {soldier_id}, actor_id=actor_id,
    )
    session.commit()
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/unit/test_ranges_service.py -v
```
Expected: all PASS.

- [ ] **Step 5: Fix the route call site (will otherwise break — completed fully in Task 5, but confirm the break here first)**

```bash
pytest tests/integration/test_ranges_api.py -v -k remove
```
Expected: FAIL — `routes/ranges.py:399`'s `svc.remove_range_assignment(session, assignment=assignment, actor_id=user.id)` is now missing the required `reason` kwarg, raising `TypeError` inside the route (surfaces as a 500). This is expected and fixed in Task 5 — do not attempt to fix the route here, just confirm the failure mode matches this description before moving on.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ranges.py backend/tests/unit/test_ranges_service.py
git commit -m "feat: require a reason and write an audit log on direct range roster removal"
```

---

### Task 5: Route + frontend — reason for removal

**Files:**
- Modify: `backend/app/routes/ranges.py:381-401`
- Modify: `frontend/src/api/ranges.ts:16`
- Modify: `frontend/src/components/ranges/RangeEditAssignmentsModal.tsx:88-102,138`
- Modify: `frontend/src/pages/RangesPage.tsx:96-110`
- Test: `backend/tests/integration/test_ranges_api.py` (add/fix cases)

**Interfaces:**
- Produces: `DELETE /ranges/{event_id}/assignments/{assignment_id}` requires a JSON body `{"reason": "..."}`.

- [ ] **Step 1: Write/fix the failing backend test**

Find the existing removal test in `backend/tests/integration/test_ranges_api.py` (search for `remove_assignment` or the DELETE call on `/assignments/`) and update it to send a reason; add a new test for the missing-reason case:

```python
# Add to backend/tests/integration/test_ranges_api.py (match existing imports/fixtures)
def test_remove_assignment_requires_reason_in_body(client, admin_session):
    from datetime import date, timedelta
    from app.db.models import RangeType
    from app.services.ranges import add_range_assignment, create_range_event
    from tests.helpers import auth_headers, create_node, create_range_location, create_soldier

    node = create_node(admin_session, level="branch", name="rra-api-1")
    dm = create_soldier(admin_session, personal_number="rra-api-dm1", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="rra-api-s1", hierarchy_node_id=node.id)
    event = create_range_event(
        admin_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=5),
        range_location_id=create_range_location(admin_session).id, required_count=1,
    )
    assignment = add_range_assignment(admin_session, event=event, soldier_id=soldier.id, is_reserve=False)

    resp = client.request(
        "DELETE", f"/api/ranges/{event.id}/assignments/{assignment.id}",
        json={"reason": "חייל שוחרר"}, headers=auth_headers(dm),
    )
    assert resp.status_code == 204
```

(Check whether `mitvachim.enabled` needs to be turned on for this route via `_require_enabled` — if so, set the system setting in the test first, matching the pattern used by other range API tests in the same file.)

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/integration/test_ranges_api.py -v -k requires_reason_in_body
```
Expected: FAIL — the route doesn't accept a body yet, and `svc.remove_range_assignment` call is missing `reason`.

- [ ] **Step 3: Implement the route change**

In `backend/app/routes/ranges.py`, add a body model near `MarkAttendanceBody` (line 491-493):

```python
class RemoveAssignmentBody(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
```

Update `remove_assignment` (lines 386-401):

```python
def remove_assignment(
    event_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: RemoveAssignmentBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    _require_enabled(session)
    event = _load_event(session, event_id)
    authorize(session, user, Action.RANGE_MANAGE, target_node=_event_node(session, event))
    assignment = session.get(RangeAssignment, assignment_id)
    if assignment is None or assignment.range_event_id != event_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    try:
        svc.remove_range_assignment(session, assignment=assignment, reason=body.reason, actor_id=user.id)
    except svc.RangeValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
```

- [ ] **Step 4: Update the frontend API wrapper**

In `frontend/src/api/ranges.ts:16`:

```typescript
export function removeRangeAssignment(eventId:string,assignmentId:string,reason:string):Promise<void>{return api.delete(`/ranges/${eventId}/assignments/${assignmentId}`,{data:{reason}}).then(()=>undefined);}
```

- [ ] **Step 5: Update `RangeEditAssignmentsModal.tsx`'s per-row remove**

In `frontend/src/components/ranges/RangeEditAssignmentsModal.tsx`, update `remove` (lines 88-102):

```tsx
  async function remove(assignmentId: string) {
    if (!editable || removing) return;
    const reason = window.prompt("סיבת ההסרה:");
    if (!reason || !reason.trim()) return;
    setRemoving(assignmentId);
    setError("");
    try {
      await removeRangeAssignment(event.id, assignmentId, reason.trim());
      setAssignments(current => current.filter(a => a.id !== assignmentId));
      await getRangeCandidates(event.id).then(setRangeCandidates).catch(() => setRangeCandidates([]));
      await onChanged();
    } catch {
      setError(text("ranges.errors.remove_assignment", "הסרת השיבוץ נכשלה"));
    } finally {
      setRemoving(null);
    }
  }
```

- [ ] **Step 6: Update `RangesPage.tsx`'s bulk clear**

In `frontend/src/pages/RangesPage.tsx`, update `bulkClear` (lines 96-110):

```tsx
  async function bulkClear() {
    setBulkBusy(true);
    setBulkError("");
    try {
      const details = await Promise.all(selectedEvents.map(e => getRangeEvent(e.id)));
      const totalAssignments = details.reduce((acc, e) => acc + e.assignments.length, 0);
      if (!confirm(`לנקות שיבוצים מ-${selectedEvents.length} מטווחים (${totalAssignments} שיבוצים)?`)) { setBulkBusy(false); return; }
      const reason = window.prompt("סיבת הניקוי (תחול על כל השיבוצים שינוקו):");
      if (!reason || !reason.trim()) { setBulkBusy(false); return; }
      await Promise.all(details.flatMap(e => e.assignments.map(a => removeRangeAssignment(e.id, a.id, reason.trim()))));
      setSelectedIds(new Set());
      await invalidate();
    } catch {
      setBulkError("ניקוי השיבוצים נכשל");
    } finally {
      setBulkBusy(false);
```

- [ ] **Step 7: Run backend and frontend tests**

```bash
cd backend
pytest tests/integration/test_ranges_api.py -v
cd ../frontend
npx tsc --noEmit -p .
npm test -- RangeEditAssignmentsModal
npm test -- RangesPage
```
Expected: all PASS/clean. If existing tests call `removeRangeAssignment`/the DELETE route without a reason, update them to pass one (search first: `grep -rn "removeRangeAssignment\|remove_range_assignment" backend/tests frontend/src/**/*.test.tsx`).

- [ ] **Step 8: Commit**

```bash
git add backend/app/routes/ranges.py backend/tests/integration/test_ranges_api.py frontend/src/api/ranges.ts frontend/src/components/ranges/RangeEditAssignmentsModal.tsx frontend/src/pages/RangesPage.tsx
git commit -m "feat: require a reason when removing a soldier from a range roster"
```

---

### Task 6: `duty_history.py` — `range_assignment` events

**Files:**
- Modify: `backend/app/services/duty_history.py`
- Test: `backend/app/services/tests/test_duty_history.py`

**Interfaces:**
- Produces: one `TimelineEvent(event_type="range_assignment", ...)` per current `RangeAssignment` of the soldier.

- [ ] **Step 1: Write the failing tests**

```python
# Add to backend/app/services/tests/test_duty_history.py
def test_range_assignment_appears(admin_session, soldier):
    from datetime import date, timedelta
    from app.db.models import RangeType
    from app.services.ranges import add_range_assignment, create_range_event
    from tests.helpers import create_node, create_range_location

    node = create_node(admin_session, level="branch", name="dh-range-node-1")
    admin_session.refresh(soldier)
    soldier.hierarchy_node_id = node.id
    admin_session.commit()
    event = create_range_event(
        admin_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=3),
        range_location_id=create_range_location(admin_session).id, required_count=1,
    )
    add_range_assignment(admin_session, event=event, soldier_id=soldier.id, is_reserve=False)

    events = get_duty_history(admin_session, soldier.id)

    range_events = [e for e in events if e.event_type == "range_assignment"]
    assert len(range_events) == 1
    assert range_events[0].status == "pending"
    assert range_events[0].metadata["is_reserve"] == "false"
    assert range_events[0].metadata["was_promoted_from_reserve"] == "false"


def test_range_assignment_promoted_from_reserve_flagged(admin_session, soldier):
    from datetime import date, timedelta
    from app.db.models import RangeType
    from app.services.range_excusal import decide_primary_excusal, request_primary_excusal
    from app.services.ranges import add_range_assignment, create_range_event
    from tests.helpers import create_node, create_range_location, create_soldier

    node = create_node(admin_session, level="branch", name="dh-range-node-2")
    admin_session.refresh(soldier)
    soldier.hierarchy_node_id = node.id
    admin_session.commit()
    manager = create_soldier(admin_session, personal_number="dh-range-mgr", role="duty_manager", hierarchy_node_id=node.id)
    primary = create_soldier(admin_session, personal_number="dh-range-primary", hierarchy_node_id=node.id)
    event = create_range_event(
        admin_session, hierarchy_node_id=node.id, range_type=RangeType.laser,
        event_date=date.today() + timedelta(days=3),
        range_location_id=create_range_location(admin_session).id, required_count=1, reserve_count=1,
    )
    primary_assignment = add_range_assignment(admin_session, event=event, soldier_id=primary.id, is_reserve=False)
    add_range_assignment(admin_session, event=event, soldier_id=soldier.id, is_reserve=True)

    request = request_primary_excusal(admin_session, assignment=primary_assignment, reason="בדיקה", requested_by=primary.id)
    decide_primary_excusal(admin_session, request=request, approve=True, decided_by=manager.id)

    events = get_duty_history(admin_session, soldier.id)
    range_events = [e for e in events if e.event_type == "range_assignment"]
    assert len(range_events) == 1
    assert range_events[0].metadata["was_promoted_from_reserve"] == "true"
    assert range_events[0].metadata["is_reserve"] == "false"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest app/services/tests/test_duty_history.py -v -k range_assignment
```
Expected: FAIL — no `range_assignment` events exist yet.

- [ ] **Step 3: Implement**

In `backend/app/services/duty_history.py`, add the necessary imports (top of file, alongside the existing `app.db.models` import block):

```python
from app.db.models import (
    AuditLog,
    DutyAssignment,
    DutyDayOverride,
    DutyDismissal,
    DutyLocation,
    DutyType,
    ExemptionDutyTypeMap,
    ExemptionRequest,
    ExemptionType,
    PersonalConstraint,
    RangeAssignment,
    RangeEvent,
    RangeExcusalRequest,
    RangeExcusalStatus,
    RangeLocation,
    Soldier,
    SoldierExemption,
)
```

Add a new block right before `# --- ExemptionRequest events ---` (line 437), inside `get_duty_history`:

```python
    # --- RangeAssignment events (current roster membership) ---
    range_location_cache: dict[uuid.UUID, str] = {}

    def _range_location_name(loc_id: uuid.UUID) -> str:
        if loc_id not in range_location_cache:
            loc = session.get(RangeLocation, loc_id)
            range_location_cache[loc_id] = loc.name if loc else str(loc_id)
        return range_location_cache[loc_id]

    range_assignments = list(
        session.execute(
            select(RangeAssignment).where(RangeAssignment.soldier_id == soldier_id)
        ).scalars().all()
    )
    promoted_assignment_ids: set[uuid.UUID] = set(
        session.execute(
            select(RangeExcusalRequest.promoted_assignment_id).where(
                RangeExcusalRequest.promoted_assignment_id.is_not(None)
            )
        ).scalars().all()
    )
    for ra in range_assignments:
        event = session.get(RangeEvent, ra.range_event_id)
        if event is None:
            continue
        loc_name = _range_location_name(event.range_location_id)
        events.append(
            TimelineEvent(
                id=ra.id,
                event_type="range_assignment",
                date=event.date.isoformat(),
                end_date=None,
                title=f"מטווח {event.range_type} ב{loc_name}",
                description=ra.note,
                status=ra.attendance_status,
                metadata={
                    "range_type": event.range_type,
                    "location_name": loc_name,
                    "is_reserve": "true" if ra.is_reserve else "false",
                    "was_promoted_from_reserve": "true" if ra.id in promoted_assignment_ids else "false",
                    "range_event_id": str(event.id),
                },
                created_at=ra.created_at.isoformat(),
            )
        )
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest app/services/tests/test_duty_history.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/duty_history.py backend/app/services/tests/test_duty_history.py
git commit -m "feat: include current range assignments in soldier duty history"
```

---

### Task 7: `duty_history.py` — `range_removed` events

**Files:**
- Modify: `backend/app/services/duty_history.py`
- Test: `backend/app/services/tests/test_duty_history.py`

**Interfaces:**
- Produces: one `TimelineEvent(event_type="range_removed", ...)` per approved excusal-based removal AND per direct-removal audit-log entry, for this soldier.

- [ ] **Step 1: Write the failing tests**

```python
# Add to backend/app/services/tests/test_duty_history.py
def test_range_removed_via_excusal_appears(admin_session, soldier):
    from datetime import date, timedelta
    from app.db.models import RangeType
    from app.services.range_excusal import decide_primary_excusal, request_primary_excusal
    from app.services.ranges import add_range_assignment, create_range_event
    from tests.helpers import create_node, create_range_location, create_soldier

    node = create_node(admin_session, level="branch", name="dh-removed-node-1")
    admin_session.refresh(soldier)
    soldier.hierarchy_node_id = node.id
    admin_session.commit()
    manager = create_soldier(admin_session, personal_number="dh-removed-mgr", role="duty_manager", hierarchy_node_id=node.id)
    event = create_range_event(
        admin_session, hierarchy_node_id=node.id, range_type=RangeType.live,
        event_date=date.today() + timedelta(days=3),
        range_location_id=create_range_location(admin_session).id, required_count=1,
    )
    assignment = add_range_assignment(admin_session, event=event, soldier_id=soldier.id, is_reserve=False)
    request = request_primary_excusal(admin_session, assignment=assignment, reason="חופשה", requested_by=soldier.id)
    decide_primary_excusal(admin_session, request=request, approve=True, decided_by=manager.id)

    events = get_duty_history(admin_session, soldier.id)
    removed = [e for e in events if e.event_type == "range_removed"]
    assert len(removed) == 1
    assert removed[0].description == "חופשה"
    assert removed[0].metadata["source"] == "excusal"
    assert removed[0].metadata["range_type"] == "live"


def test_range_removed_via_manual_removal_appears(admin_session, soldier):
    from datetime import date, timedelta
    from app.db.models import RangeType
    from app.services.ranges import add_range_assignment, create_range_event, remove_range_assignment
    from tests.helpers import create_node, create_range_location, create_soldier

    node = create_node(admin_session, level="branch", name="dh-removed-node-2")
    admin_session.refresh(soldier)
    soldier.hierarchy_node_id = node.id
    admin_session.commit()
    manager = create_soldier(admin_session, personal_number="dh-removed-mgr2", role="duty_manager", hierarchy_node_id=node.id)
    event = create_range_event(
        admin_session, hierarchy_node_id=node.id, range_type=RangeType.alal,
        event_date=date.today() + timedelta(days=3),
        range_location_id=create_range_location(admin_session).id, required_count=1,
    )
    assignment = add_range_assignment(admin_session, event=event, soldier_id=soldier.id, is_reserve=False)
    remove_range_assignment(admin_session, assignment=assignment, reason="שוחרר מהיחידה", actor_id=manager.id)

    events = get_duty_history(admin_session, soldier.id)
    removed = [e for e in events if e.event_type == "range_removed"]
    assert len(removed) == 1
    assert removed[0].description == "שוחרר מהיחידה"
    assert removed[0].metadata["source"] == "manual_removal"
    assert removed[0].metadata["range_type"] == "alal"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest app/services/tests/test_duty_history.py -v -k range_removed
```
Expected: FAIL — no `range_removed` events exist yet.

- [ ] **Step 3: Implement**

In `backend/app/services/duty_history.py`, add a second new block right after the `range_assignment` block from Task 6:

```python
    # --- range_removed events (excusal-based and manual removal, unified) ---
    excusal_removals = list(
        session.execute(
            select(RangeExcusalRequest).where(
                RangeExcusalRequest.requested_by == soldier_id,
                RangeExcusalRequest.status == RangeExcusalStatus.approved,
                RangeExcusalRequest.range_assignment_id.is_(None),
                RangeExcusalRequest.range_event_id.is_not(None),
            )
        ).scalars().all()
    )
    for req in excusal_removals:
        event = session.get(RangeEvent, req.range_event_id)
        if event is None:
            continue
        loc_name = _range_location_name(event.range_location_id)
        events.append(
            TimelineEvent(
                id=req.id,
                event_type="range_removed",
                date=event.date.isoformat(),
                end_date=None,
                title=f"הוסר ממטווח {event.range_type} ב{loc_name}",
                description=req.reason,
                status=None,
                metadata={
                    "range_type": event.range_type,
                    "location_name": loc_name,
                    "source": "excusal",
                    "range_event_id": str(event.id),
                },
                created_at=req.requested_at.isoformat(),
            )
        )

    manual_removal_logs = list(
        session.execute(
            select(AuditLog).where(
                AuditLog.action == "range_assignment.remove",
                AuditLog.before["soldier_id"].astext == str(soldier_id),
            )
        ).scalars().all()
    )
    for log in manual_removal_logs:
        range_event_id_str = (log.before or {}).get("range_event_id")
        if not range_event_id_str:
            continue
        event = session.get(RangeEvent, uuid.UUID(range_event_id_str))
        if event is None:
            continue
        loc_name = _range_location_name(event.range_location_id)
        reason = (log.context or {}).get("reason")
        events.append(
            TimelineEvent(
                id=log.id,
                event_type="range_removed",
                date=event.date.isoformat(),
                end_date=None,
                title=f"הוסר ממטווח {event.range_type} ב{loc_name}",
                description=reason,
                status=None,
                metadata={
                    "range_type": event.range_type,
                    "location_name": loc_name,
                    "source": "manual_removal",
                    "range_event_id": str(event.id),
                },
                created_at=log.created_at.isoformat(),
            )
        )
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest app/services/tests/test_duty_history.py -v
```
Expected: all PASS.

- [ ] **Step 5: Run the broader duty-history and ranges suites for regressions**

```bash
pytest app/services/tests/test_duty_history.py tests/unit/test_range_attendance.py tests/unit/test_range_excusal.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/duty_history.py backend/app/services/tests/test_duty_history.py
git commit -m "feat: include range removals (excusal and manual) in soldier duty history"
```

---

### Task 8: Frontend — `DutyHistoryPanel` range events

**Files:**
- Modify: `frontend/src/api/dutyHistory.ts`
- Modify: `frontend/src/components/DutyHistoryPanel.tsx`
- Modify: `frontend/src/i18n/he.json`
- Test: `frontend/src/components/DutyHistoryPanel.test.tsx` (check if it exists first)

**Interfaces:**
- Consumes: `TimelineEvent` with `event_type: "range_assignment" | "range_removed"` (backend, Tasks 6-7).

- [ ] **Step 1: Update the frontend type**

In `frontend/src/api/dutyHistory.ts`:

```typescript
export interface TimelineEvent {
  id: string;
  event_type:
    | "assignment"
    | "cancellation"
    | "call_up"
    | "dismissal"
    | "exemption"
    | "exemption_request"
    | "personal_constraint"
    | "range_assignment"
    | "range_removed";
  date: string;
  end_date: string | null;
  title: string;
  description: string | null;
  status: string | null;
  metadata: Record<string, string | null>;
  created_at: string;
}
```

- [ ] **Step 2: Add i18n keys**

In `frontend/src/i18n/he.json`, inside the `"duty_history"` block (after `"filter_constraints"`, line 1047):

```json
    "filter_constraints": "אילוצים אישיים",
    "filter_ranges": "מטווחים",
```

- [ ] **Step 3: Check for an existing panel test file**

```bash
ls frontend/src/components/DutyHistoryPanel.test.tsx 2>&1
```
Read it fully first if it exists, to match render/mock conventions before adding cases.

- [ ] **Step 4: Write the failing test**

```tsx
// Add to frontend/src/components/DutyHistoryPanel.test.tsx (or create following the existing render/mock pattern in this directory)
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import DutyHistoryPanel from "./DutyHistoryPanel";
import * as dutyHistoryApi from "../api/dutyHistory";

vi.mock("../api/dutyHistory");

describe("DutyHistoryPanel range events", () => {
  it("renders a range_assignment event with its status", async () => {
    vi.mocked(dutyHistoryApi.getSoldierDutyHistory).mockResolvedValue([
      {
        id: "r1", event_type: "range_assignment", date: "2026-09-01", end_date: null,
        title: "מטווח laser במטווח צפון", description: null, status: "present",
        metadata: { range_type: "laser", location_name: "מטווח צפון", is_reserve: "false", was_promoted_from_reserve: "false" },
        created_at: "2026-08-01T00:00:00Z",
      },
    ]);
    render(<DutyHistoryPanel soldierId="s1" canManage={false} isActive={true} />);
    expect(await screen.findByTestId("history-event-range_assignment")).toBeTruthy();
  });

  it("renders a range_removed event with its reason", async () => {
    vi.mocked(dutyHistoryApi.getSoldierDutyHistory).mockResolvedValue([
      {
        id: "r2", event_type: "range_removed", date: "2026-09-01", end_date: null,
        title: "הוסר ממטווח laser במטווח צפון", description: "חופשה", status: null,
        metadata: { range_type: "laser", location_name: "מטווח צפון", source: "excusal" },
        created_at: "2026-08-01T00:00:00Z",
      },
    ]);
    render(<DutyHistoryPanel soldierId="s1" canManage={false} isActive={true} />);
    const el = await screen.findByTestId("history-event-range_removed");
    expect(el.textContent).toContain("חופשה");
  });
});
```

(Match `DutyHistoryPanel`'s actual required props exactly — check the `Props` interface at `DutyHistoryPanel.tsx:100-105` before finalizing this test; `soldierName` is optional.)

- [ ] **Step 5: Run to verify failure**

```bash
npm test -- DutyHistoryPanel.test.tsx
```
Expected: FAIL only if `TYPE_COLORS`/`DOT_COLORS` lookups being `undefined` cause a render issue — more likely these tests pass structurally already (since `TYPE_COLORS[e.event_type] ?? "border-gray-300..."` has a fallback) but let's still add explicit styling per Step 6 for visual correctness; if both tests already pass with the fallback colors, that's fine — the FilterType/color work in Step 6 is still required per the design spec.

- [ ] **Step 6: Implement the styling and filter additions**

In `frontend/src/components/DutyHistoryPanel.tsx`, update `FilterType` (lines 20-29):

```tsx
type FilterType =
  | "all"
  | "assignment"
  | "algorithm_draft"
  | "cancellation"
  | "call_up"
  | "dismissal"
  | "exemption"
  | "exemption_request"
  | "personal_constraint"
  | "range";
```

Update `FILTER_KEYS` (lines 33-43), adding after the constraints entry:

```tsx
  { type: "personal_constraint", i18nKey: "duty_history.filter_constraints" },
  { type: "range", i18nKey: "duty_history.filter_ranges" },
];
```

Update `TYPE_COLORS`/`DOT_COLORS` (lines 45-63):

```tsx
const TYPE_COLORS: Record<string, string> = {
  assignment: "border-indigo-500 bg-indigo-50 dark:bg-indigo-950",
  cancellation: "border-red-400 bg-red-50 dark:bg-red-950",
  call_up: "border-orange-400 bg-orange-50 dark:bg-orange-950",
  dismissal: "border-yellow-400 bg-yellow-50 dark:bg-yellow-950",
  exemption: "border-teal-400 bg-teal-50 dark:bg-teal-950",
  exemption_request: "border-blue-400 bg-blue-50 dark:bg-blue-950",
  personal_constraint: "border-purple-400 bg-purple-50 dark:bg-purple-950",
  range_assignment: "border-cyan-500 bg-cyan-50 dark:bg-cyan-950",
  range_removed: "border-gray-400 bg-gray-50 dark:bg-gray-800 border-dashed",
};

const DOT_COLORS: Record<string, string> = {
  assignment: "bg-indigo-500",
  cancellation: "bg-red-400",
  call_up: "bg-orange-400",
  dismissal: "bg-yellow-400",
  exemption: "bg-teal-400",
  exemption_request: "bg-blue-400",
  personal_constraint: "bg-purple-400",
  range_assignment: "bg-cyan-500",
  range_removed: "bg-gray-400",
};
```

Update `STATUS_BADGE` (lines 65-75) to cover the range attendance statuses (`pending` already exists):

```tsx
const STATUS_BADGE: Record<string, string> = {
  published: "bg-green-100 text-green-800",
  active: "bg-green-100 text-green-800",
  approved: "bg-green-100 text-green-800",
  present: "bg-green-100 text-green-800",
  pending: "bg-yellow-100 text-yellow-800",
  proposed: "bg-blue-100 text-blue-800",
  algorithm_draft: "bg-blue-100 text-blue-800",
  cancelled: "bg-red-100 text-red-800",
  rejected: "bg-red-100 text-red-800",
  algorithm_rejected: "bg-red-100 text-red-800",
  no_show: "bg-red-100 text-red-800",
};
```

Add a "promoted from reserve" badge next to the existing `is_reserve` badge (`EventCard`, around line 179-184 — insert immediately after the existing `is_reserve` block):

```tsx
              {e.metadata.is_reserve === "true" && (
                <span className="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">
                  {t("duty_history.reserve")}
                </span>
              )}
              {e.metadata.was_promoted_from_reserve === "true" && (
                <span className="text-xs px-1.5 py-0.5 rounded bg-cyan-100 text-cyan-800">
                  קודם מרזרבה
                </span>
              )}
```

Filtering logic: the `"range"` filter value must match against both `range_assignment` and `range_removed` event types. Find the existing filter predicate (search for where `filterType` is compared against `e.event_type` — likely a `.filter(e => filterType === "all" || e.event_type === filterType)` line) and extend it:

```tsx
const matchesFilter = (e: TimelineEvent, filterType: FilterType) =>
  filterType === "all"
  || e.event_type === filterType
  || (filterType === "range" && (e.event_type === "range_assignment" || e.event_type === "range_removed"));
```

Use this helper wherever the existing inline filter comparison lives (locate it first — do not guess its exact current line without checking, since the file may have evolved; grep for `filterType` in `DutyHistoryPanel.tsx` before editing).

- [ ] **Step 7: Run tests to verify pass**

```bash
npm test -- DutyHistoryPanel.test.tsx
```
Expected: all PASS.

- [ ] **Step 8: Typecheck and run the broader frontend suite**

```bash
npx tsc --noEmit -p .
npm test
npm run lint
```
Expected: all clean.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api/dutyHistory.ts frontend/src/components/DutyHistoryPanel.tsx frontend/src/i18n/he.json frontend/src/components/DutyHistoryPanel.test.tsx
git commit -m "feat: render range assignments and removals in duty history panel"
```

---

### Task 9: Full regression pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend fast suite**

```bash
cd backend
pytest -q
```
Expected: all green.

- [ ] **Step 2: Run the backend slow suite**

```bash
pytest --slow -q
```
Expected: all green.

- [ ] **Step 3: Run the full frontend suite**

```bash
cd frontend
npm test
npm run lint
npx tsc --noEmit -p .
```
Expected: all green, zero lint warnings.

- [ ] **Step 4: Manual smoke test**

Start `.\dev.ps1`, open a soldier's profile, view their duty history. Assign them to a range (primary), confirm a `range_assignment` event appears. Remove them via the roster's remove button with a reason, confirm a `range_removed` event appears with that reason. Repeat via the excusal-request flow (self-service) and confirm the same event type appears with `source: "excusal"`.

- [ ] **Step 5: No commit needed** — verification only; fix regressions in the task that introduced them.
