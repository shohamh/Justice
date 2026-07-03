# Exemption Flows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework פטור רשמי (regular exemption) requests into a mandatory sequential dual-approval flow (commander → duty manager scoped to מרכז+), and add a single-step פטור פיקודי (commander exemption) grant path gated to רסן+ commanders, מדור+ commanders, or duty managers — removing the old `exemptions_require_rasn` setting entirely.

**Architecture:** `ExemptionRequest.status` gains two pending sub-states (`pending_commander`, `pending_duty_manager`) replacing the single `pending` state; a new `commander_approved_by` column records the first approver. A new session-aware authority-check module resolves hierarchy-level-based gates (מדור+, מרכז+) by looking up `HierarchyLevelType.rank` — reusable by both the commander-exemption grant gate and the duty-manager approval-step gate. The existing direct-grant endpoint (`POST /soldiers/{id}/exemptions`) is repurposed as the single-step פטור פיקודי path, restricted to `is_commander_exemption=True` types only.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, React + TypeScript.

**Depends on spec:** `docs/superpowers/specs/2026-07-03-potential-design.md`
**Independent of:** `docs/superpowers/plans/2026-07-03-potential-core.md` (can be built in parallel)

---

### Task 1: Migration — `commander_approved_by` column

**Files:**
- Create: `backend/alembic/versions/<new_revision>_add_exemption_dual_approval.py`

- [ ] **Step 1: Check current head**

Run: `cd backend && alembic heads`
Expected: single head (will be the `<REV>` from the potential-core plan if that migration already landed on this branch; otherwise `52cd8f7417e1`). Use whatever `alembic heads` reports as `down_revision`.

- [ ] **Step 2: Generate the migration**

Run: `cd backend && alembic revision -m "add_exemption_dual_approval"`

- [ ] **Step 3: Write the migration**

```python
"""add_exemption_dual_approval

Revision ID: <REV2>
Revises: <REV_FROM_STEP_1>
Create Date: 2026-07-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '<REV2>'
down_revision: Union[str, Sequence[str], None] = '<REV_FROM_STEP_1>'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "exemption_requests",
        sa.Column("commander_approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
    )
    op.execute("UPDATE exemption_requests SET status = 'pending_commander' WHERE status = 'pending'")


def downgrade() -> None:
    op.execute("UPDATE exemption_requests SET status = 'pending' WHERE status = 'pending_commander'")
    op.drop_column("exemption_requests", "commander_approved_by")
```

- [ ] **Step 4: Apply the migration**

Run: `cd backend && alembic upgrade head`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/<REV2>_add_exemption_dual_approval.py
git commit -m "feat: add commander_approved_by column, migrate pending status to pending_commander"
```

---

### Task 2: Model change

**Files:**
- Modify: `backend/app/db/models.py`

- [ ] **Step 1: Add `commander_approved_by` to `ExemptionRequest`**

In the `ExemptionRequest` class (around line 514-542), add after `decided_by`:

```python
    commander_approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
```

- [ ] **Step 2: Verify import**

Run: `cd backend && python -c "import app.db.models"`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/models.py
git commit -m "feat: add commander_approved_by to ExemptionRequest model"
```

---

### Task 3: Hierarchy-level authority helper

**Files:**
- Modify: `backend/app/services/hierarchy.py`
- Create: `backend/app/services/authority.py`
- Test: `backend/app/services/tests/test_authority.py`

- [ ] **Step 1: Expose `get_level_rank` publicly**

In `backend/app/services/hierarchy.py`, rename the existing private helper `_get_level_rank` to `get_level_rank` (drop the leading underscore) and update its one call site within the same file.

Run: `cd backend && grep -n "_get_level_rank" app/services/hierarchy.py`

Rename every occurrence found.

- [ ] **Step 2: Write failing tests for the authority helper**

```python
# backend/app/services/tests/test_authority.py
from __future__ import annotations

import uuid

from app.db.models import HierarchyLevelType, HierarchyNode, Soldier
from app.services.authority import commander_can_grant_commander_exemption, dm_scope_covers_level


def _level(session, key, rank):
    lt = HierarchyLevelType(key=key, label=key, rank=rank)
    session.add(lt)
    session.flush()
    return lt


def test_commander_below_rasan_without_hamador_command_cannot_grant(app_session):
    _level(app_session, "גדוד", 1)
    _level(app_session, "פלוגה", 2)
    _level(app_session, "מדור", 3)
    node = HierarchyNode(level="פלוגה", name="Co", path_ids=[])
    app_session.add(node)
    app_session.flush()
    node.path_ids = [node.id]
    s = Soldier(personal_number="1", full_name="X", password_hash="x", rank="סרן")
    app_session.add(s)
    app_session.flush()
    assert commander_can_grant_commander_exemption(app_session, commander_id=s.id, commander_rank=s.rank) is False


def test_commander_rasan_can_grant_regardless_of_command_level(app_session):
    s = Soldier(personal_number="2", full_name="X", password_hash="x", rank="רסן")
    app_session.add(s)
    app_session.flush()
    assert commander_can_grant_commander_exemption(app_session, commander_id=s.id, commander_rank=s.rank) is True


def test_commander_of_mador_or_above_can_grant_even_below_rasan(app_session):
    _level(app_session, "גדוד", 1)
    _level(app_session, "מדור", 2)
    _level(app_session, "כיתה", 3)
    node = HierarchyNode(level="מדור", name="Sector", path_ids=[])
    app_session.add(node)
    app_session.flush()
    node.path_ids = [node.id]
    s = Soldier(personal_number="3", full_name="X", password_hash="x", rank="סמל")
    app_session.add(s)
    app_session.flush()
    node.commander_id = s.id
    app_session.flush()
    assert commander_can_grant_commander_exemption(app_session, commander_id=s.id, commander_rank=s.rank) is True


def test_dm_scope_covers_level_true_when_scope_node_at_or_above_target_level(app_session):
    _level(app_session, "גדוד", 1)
    _level(app_session, "מרכז", 2)
    _level(app_session, "פלוגה", 3)
    scope_node = HierarchyNode(level="מרכז", name="Center", path_ids=[])
    app_session.add(scope_node)
    app_session.flush()
    scope_node.path_ids = [scope_node.id]
    app_session.flush()
    assert dm_scope_covers_level(app_session, scope_node=scope_node, required_level_key="מרכז") is True


def test_dm_scope_covers_level_false_when_scope_node_below_target_level(app_session):
    _level(app_session, "גדוד", 1)
    _level(app_session, "מרכז", 2)
    _level(app_session, "פלוגה", 3)
    scope_node = HierarchyNode(level="פלוגה", name="Co", path_ids=[])
    app_session.add(scope_node)
    app_session.flush()
    scope_node.path_ids = [scope_node.id]
    app_session.flush()
    assert dm_scope_covers_level(app_session, scope_node=scope_node, required_level_key="מרכז") is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_authority.py -v`
Expected: FAIL — `app.services.authority` module doesn't exist yet.

- [ ] **Step 4: Implement the authority module**

```python
# backend/app/services/authority.py
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import HierarchyNode
from app.services.eligibility import RANKS_RASAN_AND_ABOVE
from app.services.hierarchy import get_level_rank

COMMANDER_EXEMPTION_MIN_LEVEL_KEY = "מדור"
REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY = "מרכז"


def dm_scope_covers_level(session: Session, *, scope_node: HierarchyNode, required_level_key: str) -> bool:
    """True iff scope_node's level rank is <= required_level_key's rank (i.e. scope_node
    is at that level or closer to root — lower rank number = closer to root)."""
    required_rank = get_level_rank(session, required_level_key)
    scope_rank = get_level_rank(session, scope_node.level)
    if required_rank is None or scope_rank is None:
        return False
    return scope_rank <= required_rank


def commander_can_grant_commander_exemption(
    session: Session, *, commander_id: uuid.UUID, commander_rank: str | None,
) -> bool:
    """True iff commander_rank is רסן+, OR the soldier commands at least one node
    at level 'מדור' or above (closer to root)."""
    if commander_rank and commander_rank in RANKS_RASAN_AND_ABOVE:
        return True
    mador_rank = get_level_rank(session, COMMANDER_EXEMPTION_MIN_LEVEL_KEY)
    if mador_rank is None:
        return False
    commanded_nodes = session.execute(
        select(HierarchyNode).where(HierarchyNode.commander_id == commander_id)
    ).scalars().all()
    for node in commanded_nodes:
        node_rank = get_level_rank(session, node.level)
        if node_rank is not None and node_rank <= mador_rank:
            return True
    return False
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_authority.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/hierarchy.py backend/app/services/authority.py backend/app/services/tests/test_authority.py
git commit -m "feat: add hierarchy-level authority helpers for exemption gates"
```

---

### Task 4: Service layer — dual-approval submit/approve/reject

**Files:**
- Modify: `backend/app/services/exemption_requests.py`
- Test: `backend/app/services/tests/test_exemption_requests.py` (check if it exists first; create if not)

- [ ] **Step 1: Check for an existing test file**

Run: `cd backend && ls app/services/tests/test_exemption_requests.py 2>/dev/null || echo "none"`

If it exists, add tests to it following its existing fixture conventions; if not, create it modeled on `test_gimelim.py`'s structure (check with `head -30 app/services/tests/test_gimelim.py`).

- [ ] **Step 2: Write failing tests**

```python
# backend/app/services/tests/test_exemption_requests.py (new or appended)
from __future__ import annotations

import uuid
from datetime import date

from app.db.models import ExemptionType, Soldier
from app.services.exemption_requests import (
    ExemptionRequestError, approve_commander_step, approve_duty_manager_step,
    reject_request, submit_request,
)


def _soldier(session, **kw):
    s = Soldier(personal_number=str(uuid.uuid4())[:8], full_name="X", password_hash="x", **kw)
    session.add(s)
    session.flush()
    return s


def test_submit_request_starts_at_pending_commander(app_session):
    et = ExemptionType(name="פטור רפואי", is_commander_exemption=False)
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1))
    assert req.status == "pending_commander"


def test_approve_commander_step_moves_to_pending_duty_manager(app_session):
    et = ExemptionType(name="פטור רפואי 2", is_commander_exemption=False)
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    approver = _soldier(app_session)
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1))
    result = approve_commander_step(app_session, req.id, approved_by=approver.id)
    assert result.status == "pending_duty_manager"
    assert result.commander_approved_by == approver.id


def test_approve_duty_manager_step_finalizes_and_creates_exemption(app_session):
    et = ExemptionType(name="פטור רפואי 3", is_commander_exemption=False)
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    commander = _soldier(app_session)
    dm = _soldier(app_session)
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1))
    approve_commander_step(app_session, req.id, approved_by=commander.id)
    result = approve_duty_manager_step(app_session, req.id, decided_by=dm.id)
    assert result.status == "approved"
    assert result.decided_by == dm.id

    from app.db.models import SoldierExemption
    from sqlalchemy import select
    ex = app_session.execute(select(SoldierExemption).where(SoldierExemption.soldier_id == soldier.id)).scalar_one()
    assert ex.granted_by == dm.id


def test_cannot_skip_commander_step(app_session):
    et = ExemptionType(name="פטור רפואי 4", is_commander_exemption=False)
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    dm = _soldier(app_session)
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1))
    try:
        approve_duty_manager_step(app_session, req.id, decided_by=dm.id)
        assert False, "expected ExemptionRequestError"
    except ExemptionRequestError as exc:
        assert "not_pending_duty_manager" in str(exc)


def test_reject_works_at_commander_stage(app_session):
    et = ExemptionType(name="פטור רפואי 5", is_commander_exemption=False)
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    commander = _soldier(app_session)
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1))
    result = reject_request(app_session, req.id, decided_by=commander.id)
    assert result.status == "rejected"


def test_reject_works_at_duty_manager_stage(app_session):
    et = ExemptionType(name="פטור רפואי 6", is_commander_exemption=False)
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    commander = _soldier(app_session)
    dm = _soldier(app_session)
    req = submit_request(app_session, soldier.id, et.id, date(2026, 1, 1))
    approve_commander_step(app_session, req.id, approved_by=commander.id)
    result = reject_request(app_session, req.id, decided_by=dm.id)
    assert result.status == "rejected"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_exemption_requests.py -v`
Expected: FAIL — `approve_commander_step`/`approve_duty_manager_step` not defined (old code only has `approve_request`).

- [ ] **Step 4: Rewrite the service**

Replace `submit_request`'s `status="pending"` with `status="pending_commander"`:

```python
    req = ExemptionRequest(
        soldier_id=soldier_id,
        exemption_type_id=exemption_type_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        status="pending_commander",
    )
```

Replace `approve_request` with two functions, and update `reject_request` to accept either pending state:

```python
def approve_commander_step(
    session: Session,
    request_id: uuid.UUID,
    approved_by: uuid.UUID,
) -> ExemptionRequest:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise ExemptionRequestError("exemption_request_not_found")
    if req.status != "pending_commander":
        raise ExemptionRequestError("exemption_request_not_pending_commander")
    req.status = "pending_duty_manager"
    req.commander_approved_by = approved_by
    session.flush()
    return req


def approve_duty_manager_step(
    session: Session,
    request_id: uuid.UUID,
    decided_by: uuid.UUID,
    decision_note: str | None = None,
) -> ExemptionRequest:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise ExemptionRequestError("exemption_request_not_found")
    if req.status != "pending_duty_manager":
        raise ExemptionRequestError("exemption_request_not_pending_duty_manager")

    req.status = "approved"
    req.decided_by = decided_by
    req.decision_note = decision_note

    exemption = SoldierExemption(
        soldier_id=req.soldier_id,
        exemption_type_id=req.exemption_type_id,
        start_date=req.start_date,
        end_date=req.end_date,
        reason=req.reason,
        granted_by=decided_by,
    )
    session.add(exemption)
    session.flush()
    create_notification(session, soldier_id=req.soldier_id,
                        type=NotificationType.exemption_approved,
                        title="בקשת הפטור אושרה",
                        reference_type="exemption_request", reference_id=req.id,
                        actor_id=decided_by)
    if req.enrollment_request_id:
        from app.services.enrollment import try_activate
        try_activate(session, req.enrollment_request_id)
    return req


def reject_request(
    session: Session,
    request_id: uuid.UUID,
    decided_by: uuid.UUID,
    decision_note: str | None = None,
) -> ExemptionRequest:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise ExemptionRequestError("exemption_request_not_found")
    if req.status not in ("pending_commander", "pending_duty_manager"):
        raise ExemptionRequestError("exemption_request_not_pending")

    req.status = "rejected"
    req.decided_by = decided_by
    req.decision_note = decision_note
    session.flush()
    create_notification(session, soldier_id=req.soldier_id,
                        type=NotificationType.exemption_rejected,
                        title="בקשת הפטור נדחתה",
                        reference_type="exemption_request", reference_id=req.id,
                        actor_id=decided_by)
    if req.enrollment_request_id:
        from app.services.enrollment import try_activate
        try_activate(session, req.enrollment_request_id)
    return req
```

Also update `list_pending_requests` and `count_pending_requests` to match either pending state:

```python
def list_pending_requests(session: Session, soldier_ids: list[uuid.UUID]) -> list[ExemptionRequest]:
    stmt = select(ExemptionRequest).where(
        ExemptionRequest.soldier_id.in_(soldier_ids),
        ExemptionRequest.status.in_(("pending_commander", "pending_duty_manager")),
    ).order_by(ExemptionRequest.created_at.desc())
    return list(session.execute(stmt).scalars().all())


def count_pending_requests(session: Session, soldier_ids: list[uuid.UUID]) -> int:
    stmt = select(ExemptionRequest).where(
        ExemptionRequest.soldier_id.in_(soldier_ids),
        ExemptionRequest.status.in_(("pending_commander", "pending_duty_manager")),
    )
    return len(list(session.execute(stmt).scalars().all()))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_exemption_requests.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/exemption_requests.py backend/app/services/tests/test_exemption_requests.py
git commit -m "feat: rework exemption request service into sequential dual approval"
```

---

### Task 5: Routes — dual-approval endpoints, remove `exemptions_require_rasn`

**Files:**
- Modify: `backend/app/routes/exemption_requests.py`
- Modify: `backend/app/services/settings_loader.py`

- [ ] **Step 1: Remove the `exemptions_require_rasn` setting function**

Run: `cd backend && grep -n "exemptions_require_rasn" app/services/settings_loader.py`

Delete the `exemptions_require_rasn` function found there (around line 54).

- [ ] **Step 2: Replace the approve/reject routes**

In `backend/app/routes/exemption_requests.py`, replace the single `approve_exemption_request` route (lines ~302-325) with two routes, and simplify `reject_exemption_request` to drop the rank check entirely:

```python
from app.services.authority import dm_scope_covers_level, REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY
from app.services.exemption_requests import approve_commander_step, approve_duty_manager_step


@router.post("/exemption-requests/{request_id}/approve-commander", response_model=ExemptionRequestOut)
def approve_exemption_request_commander_step(
    request_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionRequestOut:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exemption_request_not_found")
    target_soldier = session.get(Soldier, req.soldier_id)
    target_node = session.get(HierarchyNode, target_soldier.hierarchy_node_id) if target_soldier else None
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=target_node)
    try:
        result = approve_commander_step(session, request_id, approved_by=user.id)
    except ExemptionRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return _out(result, include_sensitive=True)


@router.post("/exemption-requests/{request_id}/approve-duty-manager", response_model=ExemptionRequestOut)
def approve_exemption_request_duty_manager_step(
    request_id: uuid.UUID,
    body: ApproveRejectRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionRequestOut:
    req = session.get(ExemptionRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exemption_request_not_found")
    target_soldier = session.get(Soldier, req.soldier_id)
    target_node = session.get(HierarchyNode, target_soldier.hierarchy_node_id) if target_soldier else None

    from app.auth.authz import is_duty_manager, scope_root_ids
    if user.role != "admin":
        if not is_duty_manager(session, user.id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        roots = scope_root_ids(session, user)
        covering_scope_nodes = [
            n for n in session.execute(select(HierarchyNode)).scalars().all()
            if n.id in roots and target_node is not None and n.id in target_node.path_ids
        ]
        if not any(dm_scope_covers_level(session, scope_node=n, required_level_key=REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY) for n in covering_scope_nodes):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient_scope_level_for_exemption_approval")

    try:
        result = approve_duty_manager_step(session, request_id, decided_by=user.id, decision_note=body.decision_note)
    except ExemptionRequestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return _out(result, include_sensitive=True)
```

Update the import line at the top of the file to include `ExemptionRequestError` if not already imported, and remove the now-unused `exemptions_require_rasn` import.

- [ ] **Step 3: Simplify the reject route**

In `reject_exemption_request` (around line 329-353), delete the `if exemptions_require_rasn(session): ...` block entirely — rejection now works at either pending stage for any authorized commander/DM in scope, matching `reject_request`'s relaxed status check from Task 4.

- [ ] **Step 4: Run existing exemption-request route tests**

Run: `cd backend && grep -rl "approve_exemption_request\|/exemption-requests/.*approve" app/ --include=*.py | grep test`

Update any existing tests referencing the old single `/approve` endpoint to call `/approve-commander` then `/approve-duty-manager` in sequence. Run:

Run: `cd backend && pytest app/services/tests/ -v -k exemption_request`
Expected: PASS after updates (fix any tests broken by the endpoint rename/split).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/exemption_requests.py backend/app/services/settings_loader.py backend/app/services/tests/
git commit -m "feat: split exemption approval into sequential commander+duty-manager routes, remove exemptions_require_rasn"
```

---

### Task 6: Single-step פטור פיקודי grant

**Files:**
- Modify: `backend/app/routes/exemptions.py`
- Modify: `backend/app/services/exemptions.py`
- Test: `backend/app/services/tests/test_exemptions.py` (check existence first)

- [ ] **Step 1: Check the existing `grant_exemption` service function**

Run: `cd backend && cat app/services/exemptions.py`

Note its current signature and validation before modifying.

- [ ] **Step 2: Write failing tests**

```python
# append to backend/app/services/tests/test_exemptions.py (or create it)
from __future__ import annotations

import uuid
from datetime import date

from app.db.models import ExemptionType, Soldier
from app.services.exemptions import ExemptionError, grant_commander_exemption


def _soldier(session, **kw):
    s = Soldier(personal_number=str(uuid.uuid4())[:8], full_name="X", password_hash="x", **kw)
    session.add(s)
    session.flush()
    return s


def test_grant_commander_exemption_rejects_regular_type(app_session):
    et = ExemptionType(name="פטור רפואי", is_commander_exemption=False)
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    granter = _soldier(app_session, rank="רסן")
    try:
        grant_commander_exemption(
            app_session, soldier_id=soldier.id, exemption_type_id=et.id,
            start_date=date(2026, 1, 1), reason="test", actor_id=granter.id,
        )
        assert False, "expected ExemptionError"
    except ExemptionError as exc:
        assert "not_commander_exemption_type" in str(exc)


def test_grant_commander_exemption_succeeds_for_commander_type(app_session):
    et = ExemptionType(name="פטור פיקודי", is_commander_exemption=True)
    app_session.add(et)
    app_session.flush()
    soldier = _soldier(app_session)
    granter = _soldier(app_session, rank="רסן")
    ex = grant_commander_exemption(
        app_session, soldier_id=soldier.id, exemption_type_id=et.id,
        start_date=date(2026, 1, 1), reason="special case", actor_id=granter.id,
    )
    assert ex.exemption_type_id == et.id
    assert ex.granted_by == granter.id
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_exemptions.py -v -k commander_exemption`
Expected: FAIL — `grant_commander_exemption` not defined.

- [ ] **Step 4: Implement the service function**

Append to `backend/app/services/exemptions.py`:

```python
def grant_commander_exemption(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    exemption_type_id: uuid.UUID,
    start_date: date,
    end_date: date | None = None,
    reason: str | None = None,
    actor_id: uuid.UUID | None = None,
) -> SoldierExemption:
    et = session.get(ExemptionType, exemption_type_id)
    if et is None:
        raise ExemptionError("exemption_type_not_found")
    if not et.is_commander_exemption:
        raise ExemptionError("not_commander_exemption_type")
    if session.get(Soldier, soldier_id) is None:
        raise ExemptionError("soldier_not_found")
    ex = SoldierExemption(
        soldier_id=soldier_id,
        exemption_type_id=exemption_type_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        granted_by=actor_id,
    )
    session.add(ex)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="exemption.grant_commander",
        entity_type="soldier_exemption",
        entity_id=ex.id,
        after={"soldier_id": str(soldier_id), "exemption_type_id": str(exemption_type_id)},
        context={"reason": reason},
    )
    return ex
```

Check `backend/app/services/exemptions.py`'s existing imports for `write_audit`, `ExemptionType`, `date` — add any missing.

- [ ] **Step 5: Add the route and authorization gate**

In `backend/app/routes/exemptions.py`, add a new route (do not modify the existing generic `grant`/`POST` route — keep it for admin/legacy use, but add a dedicated commander-exemption endpoint):

```python
from app.services.authority import commander_can_grant_commander_exemption
from app.auth.authz import is_duty_manager, is_commander


class GrantCommanderExemptionRequest(BaseModel):
    exemption_type_id: uuid.UUID
    start_date: date
    end_date: date | None = None
    reason: str = Field(min_length=1, max_length=1000)


@router.post("/commander-exemption", response_model=ExemptionOut, status_code=status.HTTP_201_CREATED)
def grant_commander_exemption_route(
    soldier_id: uuid.UUID,
    body: GrantCommanderExemptionRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionOut:
    s = _load_soldier(session, soldier_id)
    target_node = _node_of(session, s)

    allowed = user.role == "admin"
    if not allowed and is_duty_manager(session, user.id):
        from app.auth.authz import scope_root_ids, _node_in_scope
        allowed = _node_in_scope(target_node, scope_root_ids(session, user))
    if not allowed and is_commander(session, user.id):
        from app.auth.authz import scope_root_ids, _node_in_scope
        in_scope = _node_in_scope(target_node, scope_root_ids(session, user))
        allowed = in_scope and commander_can_grant_commander_exemption(
            session, commander_id=user.id, commander_rank=user.rank,
        )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    from app.services.exemptions import ExemptionError, grant_commander_exemption
    try:
        ex = grant_commander_exemption(
            session,
            soldier_id=soldier_id,
            exemption_type_id=body.exemption_type_id,
            start_date=body.start_date,
            end_date=body.end_date,
            reason=body.reason,
            actor_id=user.id,
        )
    except ExemptionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(ex)
    return _out(ex, include_sensitive=True)
```

Note: `_node_in_scope` in `authz.py` is currently a private (underscore-prefixed) helper — check `grep -n "_node_in_scope" app/auth/authz.py` and, if it's still private, either import it as-is (same-package access is fine in Python) or promote it to a public `node_in_scope` matching the existing exported one in `app.algorithm.types` (do not conflict the names — keep the authz one distinctly named if promoting, e.g. `scope_includes_node`). For this task, importing the existing private `_node_in_scope` directly is acceptable and avoids a wider rename.

- [ ] **Step 6: Run tests**

Run: `cd backend && pytest app/services/tests/test_exemptions.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/exemptions.py backend/app/routes/exemptions.py backend/app/services/tests/test_exemptions.py
git commit -m "feat: add single-step פטור פיקודי grant endpoint gated by rank/מדור+/DM"
```

---

### Task 7: Frontend — dual-approval status UI

**Files:**
- Modify: `frontend/src/api/exemptions.ts`
- Modify: `frontend/src/pages/ApprovalsPage.tsx` (or wherever exemption-request approvals render — confirm exact file first)

- [ ] **Step 1: Locate the approval UI**

Run: `cd frontend && grep -rl "exemption-requests\|exemption_request" src/pages src/api --include=*.ts --include=*.tsx`

Identify the exact file(s) rendering the approve/reject buttons for exemption requests.

- [ ] **Step 2: Update the API client**

In `frontend/src/api/exemptions.ts` (or the relevant file found in Step 1), replace any single `approveExemptionRequest` call with two:

```typescript
export async function approveExemptionRequestCommanderStep(requestId: string): Promise<void> {
  await api.post(`/exemption-requests/${requestId}/approve-commander`, {});
}

export async function approveExemptionRequestDutyManagerStep(requestId: string, decisionNote?: string): Promise<void> {
  await api.post(`/exemption-requests/${requestId}/approve-duty-manager`, { decision_note: decisionNote ?? null });
}
```

Update the `status` type/union used by the exemption-request DTO to include `"pending_commander" | "pending_duty_manager" | "approved" | "rejected"` instead of `"pending" | "approved" | "rejected"`.

- [ ] **Step 3: Update the UI to show stage and the correct action button**

In the approval list component found in Step 1, render a stage label based on `status`:
- `pending_commander` → "ממתין לאישור מפקד" with an "אשר (שלב מפקד)" button calling `approveExemptionRequestCommanderStep`.
- `pending_duty_manager` → "ממתין לאישור קצין אג\"ם/מרכז ומעלה" with an "אשר (שלב סופי)" button calling `approveExemptionRequestDutyManagerStep`.
- `approved` / `rejected` → unchanged final-state display.

Reject stays a single button available at either pending stage, calling the existing reject endpoint unchanged.

- [ ] **Step 4: Typecheck and lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/exemptions.ts frontend/src/pages/
git commit -m "feat: show two-stage exemption approval status and actions in UI"
```

---

### Task 8: Frontend — פטור פיקודי grant form

**Files:**
- Modify: `frontend/src/api/exemptions.ts`
- Create: `frontend/src/components/CommanderExemptionGrantForm.tsx`

- [ ] **Step 1: Add the API client function**

Append to `frontend/src/api/exemptions.ts`:

```typescript
export async function grantCommanderExemption(soldierId: string, input: {
  exemption_type_id: string; start_date: string; end_date?: string | null; reason: string;
}): Promise<void> {
  await api.post(`/soldiers/${soldierId}/exemptions/commander-exemption`, input);
}
```

- [ ] **Step 2: Write the form component**

```tsx
// frontend/src/components/CommanderExemptionGrantForm.tsx
import { useState } from "react";
import { grantCommanderExemption } from "../api/exemptions";

interface Props {
  soldierId: string;
  commanderExemptionTypes: { id: string; name: string }[];
  onGranted: () => void;
}

export default function CommanderExemptionGrantForm({ soldierId, commanderExemptionTypes, onGranted }: Props) {
  const [typeId, setTypeId] = useState(commanderExemptionTypes[0]?.id ?? "");
  const [startDate, setStartDate] = useState(new Date().toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!reason.trim()) {
      setError("נדרשת סיבה");
      return;
    }
    try {
      await grantCommanderExemption(soldierId, {
        exemption_type_id: typeId,
        start_date: startDate,
        end_date: endDate || null,
        reason,
      });
      setReason("");
      onGranted();
    } catch (e) {
      setError("שגיאה במתן הפטור");
    }
  }

  return (
    <div className="space-y-2 border rounded p-3" dir="rtl">
      <h3 className="font-semibold">מתן פטור פיקודי</h3>
      <p className="text-sm text-gray-600">
        שימו לב: פטור פיקודי לא מפחית את הפוטנציאל של היחידה — עומס התורנות יתחלק על פחות חיילים. יש להשתמש בו בצמצום.
      </p>
      <select value={typeId} onChange={(e) => setTypeId(e.target.value)} className="border rounded p-1 w-full">
        {commanderExemptionTypes.map((t) => (
          <option key={t.id} value={t.id}>{t.name}</option>
        ))}
      </select>
      <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="border rounded p-1 w-full" />
      <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} placeholder="תאריך סיום (רשות)" className="border rounded p-1 w-full" />
      <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="סיבה (חובה)" className="border rounded p-1 w-full" />
      {error && <p className="text-red-600 text-sm">{error}</p>}
      <button onClick={handleSubmit} className="bg-blue-600 text-white rounded px-3 py-1">הענק פטור</button>
    </div>
  );
}
```

- [ ] **Step 3: Wire the form into the soldier profile / commander view**

Run: `cd frontend && grep -rl "ExemptionOut\|listExemptions\|SoldierExemption" src/pages --include=*.tsx`

Add `<CommanderExemptionGrantForm>` to the soldier detail view found, passing exemption types filtered to `is_commander_exemption === true` (fetch via the existing duty-config exemption-types list endpoint, filtering client-side or adding a query param if one already exists — check `frontend/src/api/dutyConfig.ts` for the exemption-types list function first).

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/exemptions.ts frontend/src/components/CommanderExemptionGrantForm.tsx frontend/src/pages/
git commit -m "feat: add commander-exemption grant form to soldier view"
```

---

### Task 9: Duty-config UI — `is_commander_exemption` field

**Files:**
- Modify: `backend/app/routes/duty_config.py`
- Modify: `frontend/src/api/dutyConfig.ts`
- Modify: `frontend/src/pages/planning/ConfigPage.tsx`

- [ ] **Step 1: Add the field to the backend exemption-type schemas**

In `backend/app/routes/duty_config.py`, the `ExemptionTypeOut`/create/update schemas already have `is_global`/`is_medical` (lines ~341-412). Add `is_commander_exemption: bool = False` alongside each of those three schema classes, and add it to `ExemptionTypeOut(...)` construction and to whatever service call creates/updates the `ExemptionType` row (mirror exactly how `is_medical` is threaded through — `grep -n "is_medical" app/routes/duty_config.py app/services/*.py` to find every call site to update).

- [ ] **Step 2: Update the frontend type and form**

In `frontend/src/api/dutyConfig.ts`, add `is_commander_exemption: boolean` to the exemption-type DTO/create/update interfaces (mirroring `is_medical`).

In `frontend/src/pages/planning/ConfigPage.tsx`, add a checkbox for "פטור פיקודי" alongside the existing "פטור גלובלי"/"פטור רפואי" checkboxes in the exemption-type form (`grep -n "is_medical\|is_global" src/pages/planning/ConfigPage.tsx` to find the exact form).

- [ ] **Step 3: Run backend tests**

Run: `cd backend && pytest -k duty_config -v`
Expected: PASS (existing tests unaffected; add one asserting `is_commander_exemption` round-trips if the existing test file has a create/update round-trip test to extend).

- [ ] **Step 4: Typecheck frontend**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/duty_config.py frontend/src/api/dutyConfig.ts frontend/src/pages/planning/ConfigPage.tsx
git commit -m "feat: expose is_commander_exemption in exemption-type config UI"
```

---

### Task 10: Help modal documentation — פטור פיקודי

**Files:**
- Modify: `frontend/src/components/HelpModal.tsx`

- [ ] **Step 1: Add the entry**

In the same icon/title/desc array used for the פוטנציאל entry (from the potential-core plan) around line 146-152, add:

```typescript
          { icon: "🎖️", title: "פטור פיקודי", desc: "פטור שניתן בשלב אחד בלבד על ידי מפקד בדרגת רס\"ן ומעלה, מפקד תת-יחידה ברמת מדור ומעלה, או קצין תורן. הפטור פוטר את החייל הבודד מתורנויות מסוימות, אך לא מפחית את הפוטנציאל של יחידתו — כלומר אותה כמות תורנויות תתחלק על פחות חיילים ביחידה. יש להשתמש בכלי זה בצמצום ובמקרים חריגים בלבד." },
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/HelpModal.tsx
git commit -m "docs: document פטור פיקודי concept in help modal"
```

---

### Task 11: Full verification pass

- [ ] **Step 1: Run backend exemption-related tests**

Run: `cd backend && pytest -m "misc or hierarchy" -q -v app/services/tests/test_exemption_requests.py app/services/tests/test_exemptions.py app/services/tests/test_authority.py`
Expected: All PASS.

- [ ] **Step 2: Run the full backend fast suite to check for regressions from removing `exemptions_require_rasn`**

Run: `cd backend && pytest -q`
Expected: All PASS. Pay particular attention to any test that referenced `exemptions_require_rasn` or the old `/exemption-requests/{id}/approve` single endpoint — these must be updated, not deleted, unless they tested behavior that no longer exists by design.

- [ ] **Step 3: Run frontend checks**

Run: `cd frontend && npm run typecheck && npm run lint && npm test`
Expected: no errors; existing exemption-request UI tests updated to match the two-stage flow.

- [ ] **Step 4: Manual smoke check**

Start the dev stack, submit a exemption request as a soldier, approve it as a commander (confirm status moves to pending_duty_manager), approve it as a duty manager scoped to מרכז+ (confirm it becomes approved and a `SoldierExemption` row appears), then separately grant a פטור פיקודי directly as a רסן+ commander and confirm it appears immediately with no approval step.

- [ ] **Step 5: Final commit if any fixups were needed**

```bash
git add -A
git commit -m "fix: address issues found during exemption-flows verification pass"
```
