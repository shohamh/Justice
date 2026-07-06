# Commander Exemption Escalation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a commander who grants a פטור פיקודי (informal, commander-authority exemption that doesn't count toward potential) also escalate it to the duty manager for approval as an official exemption — plus surface the full exemption-request history inside a soldier's own exemptions tab, and gate the grant behind an explicit confirmation.

**Architecture:** A new `ExemptionRequest.linked_commander_exemption_id` column links an escalated request back to the informal `SoldierExemption` it was paired with (when the commander chose to apply it immediately). A new service function `submit_commander_escalation` creates the `ExemptionRequest` directly at `status="pending_duty_manager"` (skipping the `pending_commander` stage, since a commander is the one initiating) and optionally grants the informal exemption via the existing `grant_commander_exemption`. A new notification helper targets duty managers directly (mirroring the existing commander-cascade helper, but DM-scoped). On the frontend, `ExemptionsPanel` grows a request-history section, and `CommanderExemptionGrantForm` gains a confirmation modal plus the escalation checkboxes.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, React + TypeScript, Vitest.

**Depends on spec:** `docs/superpowers/specs/2026-07-05-commander-exemption-escalation-design.md`

## Global Constraints

- Backend tests: `pytest -q` for the fast suite; new tests should live under existing area markers (`duty` for exemptions, per `backend/tests/conftest.py::_AREA_MARKERS`).
- Frontend: `npm test` (vitest), `npm run lint` (zero warnings), `npm run typecheck`.
- Follow existing code conventions exactly: service functions take `session: Session, *, ...` keyword-only args; routes catch domain errors (`ExemptionError`, `ExemptionRequestError`) and re-raise as `HTTPException(400, ...)`.
- Hebrew UI strings, English code/identifiers.

---

### Task 1: Migration — `linked_commander_exemption_id` column

**Files:**
- Create: `backend/alembic/versions/<new_revision>_add_linked_commander_exemption_id.py`

- [ ] **Step 1: Check current head**

Run: `cd backend && alembic heads`
Expected: prints one revision id. Use it as `down_revision` below.

- [ ] **Step 2: Generate the migration**

Run: `cd backend && alembic revision -m "add_linked_commander_exemption_id"`

This creates a new file under `backend/alembic/versions/`. Open it and replace its contents with:

```python
"""add_linked_commander_exemption_id

Revision ID: <REV>
Revises: <REV_FROM_STEP_1>
Create Date: 2026-07-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '<REV>'
down_revision: Union[str, Sequence[str], None] = '<REV_FROM_STEP_1>'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "exemption_requests",
        sa.Column(
            "linked_commander_exemption_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldier_exemptions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_constraint(
        "exemption_requests_linked_commander_exemption_id_fkey",
        "exemption_requests",
        type_="foreignkey",
    )
    op.drop_column("exemption_requests", "linked_commander_exemption_id")
```

Leave `<REV>` as whatever `alembic revision` generated (don't hand-edit it), and set `<REV_FROM_STEP_1>` to the value printed by `alembic heads` in Step 1.

- [ ] **Step 3: Apply the migration**

Run: `cd backend && alembic upgrade head`
Expected: no errors, ends at the new revision.

- [ ] **Step 4: Commit**

```bash
cd backend
git add alembic/versions/
git commit -m "feat: add linked_commander_exemption_id to exemption_requests"
```

---

### Task 2: Model change

**Files:**
- Modify: `backend/app/db/models.py:518-550` (the `ExemptionRequest` class)

**Interfaces:**
- Produces: `ExemptionRequest.linked_commander_exemption_id: uuid.UUID | None` — consumed by Task 3 and Task 4.

- [ ] **Step 1: Add the column to the model**

In `backend/app/db/models.py`, inside `class ExemptionRequest(Base):`, add this field directly after the existing `enrollment_request_id` field (currently lines 533-538):

```python
    linked_commander_exemption_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soldier_exemptions.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
```

- [ ] **Step 2: Verify import**

Run: `cd backend && python -c "import app.db.models"`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd backend
git add app/db/models.py
git commit -m "feat: add linked_commander_exemption_id to ExemptionRequest model"
```

---

### Task 3: `notify_duty_managers_of_request` notification helper

**Files:**
- Modify: `backend/app/services/notifications.py`
- Test: `backend/app/services/tests/test_notifications_dm.py` (new file)

**Interfaces:**
- Consumes: `Session`, `NotificationType`, `_create_notif` (existing private helper in the same file), `Soldier`, `HierarchyNode`, `DutyManagerScope` (add to the file's existing model import block), `dm_scope_covers_target`/`REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY` from `app.services.authority`.
- Produces: `notify_duty_managers_of_request(session, *, soldier_id, type, title, body=None, reference_type=None, reference_id=None, actor_id=None) -> None` — consumed by Task 4.

- [ ] **Step 1: Write the failing unit test**

Create `backend/app/services/tests/test_notifications_dm.py`:

```python
# backend/app/services/tests/test_notifications_dm.py
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from app.db.models import (
    DutyManagerScope,
    HierarchyLevelType,
    HierarchyNode,
    Notification,
    NotificationType,
    Soldier,
)
from app.services.notifications import notify_duty_managers_of_request


@pytest.fixture(autouse=True)
def _clear_seeded_level_types(app_session):
    """This module defines its own Hebrew-keyed levels/ranks — see
    app/services/tests/test_authority.py for why the shared English-keyed
    defaults must be cleared first."""
    app_session.execute(delete(HierarchyLevelType))
    app_session.flush()


def _level(session, key, rank):
    lt = HierarchyLevelType(key=key, label=key, rank=rank)
    session.add(lt)
    session.flush()
    return lt


def _soldier(session, **kw):
    s = Soldier(personal_number=str(uuid.uuid4())[:8], full_name="X", password_hash="x", **kw)
    session.add(s)
    session.flush()
    return s


def test_notifies_dm_whose_scope_meets_rank_but_not_below_rank_dm(app_session):
    _level(app_session, "גדוד", 1)
    _level(app_session, "מרכז", 2)
    _level(app_session, "פלוגה", 3)

    center_node = HierarchyNode(level="מרכז", name="Center", path_ids=[])
    app_session.add(center_node)
    app_session.flush()
    center_node.path_ids = [center_node.id]

    co_node = HierarchyNode(level="פלוגה", name="Co", path_ids=[])
    app_session.add(co_node)
    app_session.flush()
    co_node.path_ids = [center_node.id, co_node.id]
    app_session.flush()

    soldier = _soldier(app_session, hierarchy_node_id=co_node.id)
    qualified_dm = _soldier(app_session)
    unqualified_dm = _soldier(app_session)
    app_session.add(DutyManagerScope(duty_manager_id=qualified_dm.id, hierarchy_node_id=center_node.id))
    app_session.add(DutyManagerScope(duty_manager_id=unqualified_dm.id, hierarchy_node_id=co_node.id))
    app_session.flush()

    notify_duty_managers_of_request(
        app_session,
        soldier_id=soldier.id,
        type=NotificationType.exemption_request_pending,
        title="בקשת פטור חדשה",
    )

    notified_ids = set(
        app_session.execute(select(Notification.soldier_id)).scalars().all()
    )
    assert qualified_dm.id in notified_ids
    assert unqualified_dm.id not in notified_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest app/services/tests/test_notifications_dm.py -v`
Expected: FAIL — `ImportError: cannot import name 'notify_duty_managers_of_request'`.

- [ ] **Step 3: Add `DutyManagerScope` to the model imports**

In `backend/app/services/notifications.py`, in the existing `from app.db.models import (...)` block (lines 12-23), add `DutyManagerScope` alphabetically:

```python
from app.db.models import (
    CommanderNotificationDepth,
    CommanderNotificationScope,
    DutyManagerScope,
    EmailOutbox,
    HierarchyNode,
    Notification,
    NotificationPreference,
    NotificationType,
    Soldier,
    TelegramLink,
    TelegramOutbox,
)
```

- [ ] **Step 4: Implement `notify_duty_managers_of_request`**

Add this function to `backend/app/services/notifications.py`, directly after `notify_commanders_of_request` (after line 321 in the current file):

```python
def notify_duty_managers_of_request(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    type: NotificationType,
    title: str,
    body: str | None = None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> None:
    """Send notification only to duty managers whose scope covers the soldier's
    node at or above the regular-exemption approval level — not to commanders.

    Used for commander-escalated exemption requests, which start at
    pending_duty_manager and so skip the commander notification cascade."""
    from app.services.authority import REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY, dm_scope_covers_target

    soldier = session.get(Soldier, soldier_id)
    if soldier is None or soldier.hierarchy_node_id is None:
        return
    target_node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    if target_node is None:
        return
    dm_ids = set(
        session.execute(select(DutyManagerScope.duty_manager_id)).scalars().all()
    )
    for dm_id in dm_ids:
        roots = set(
            session.execute(
                select(DutyManagerScope.hierarchy_node_id).where(
                    DutyManagerScope.duty_manager_id == dm_id
                )
            ).scalars().all()
        )
        if not dm_scope_covers_target(
            session, scope_root_ids=roots, target_node=target_node,
            required_level_key=REGULAR_EXEMPTION_DM_MIN_LEVEL_KEY,
        ):
            continue
        _create_notif(
            session, soldier_id=dm_id, type=type,
            title=f"{soldier.full_name}: {title}", body=body,
            reference_type=reference_type, reference_id=reference_id,
            actor_id=actor_id,
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest app/services/tests/test_notifications_dm.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/services/notifications.py app/services/tests/test_notifications_dm.py
git commit -m "feat: add notify_duty_managers_of_request notification helper"
```

---

### Task 4: `submit_commander_escalation` service function

**Files:**
- Modify: `backend/app/services/exemption_requests.py`
- Test: `backend/app/services/tests/test_exemption_requests.py`

**Interfaces:**
- Consumes: `ExemptionType`, `ExemptionRequest`, `SoldierExemption` (from `app.db.models`); `grant_commander_exemption` and `ExemptionError` (from `app.services.exemptions`); `notify_duty_managers_of_request` (Task 3).
- Produces: `submit_commander_escalation(session, *, soldier_id, official_exemption_type_id, start_date, end_date, reason, apply_immediately, commander_exemption_type_id=None, actor_id) -> ExemptionRequest` — consumed by Task 5. Raises `ExemptionRequestError` with messages `"official_exemption_type_required"` (target type is a commander type), `"commander_exemption_type_required"` (apply_immediately=True but no commander type given), or propagates `ExemptionError` from `grant_commander_exemption`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/app/services/tests/test_exemption_requests.py`:

```python
from app.services.exemption_requests import submit_commander_escalation


def test_escalation_apply_immediately_grants_and_creates_pending_dm_request(app_session):
    official = ExemptionType(name="פטור רפואי אסקלציה 1")
    commander_type = ExemptionType(name="פטור פיקודי אסקלציה 1", is_commander_exemption=True)
    app_session.add_all([official, commander_type])
    app_session.flush()
    soldier = _soldier(app_session)
    commander = _soldier(app_session)

    req = submit_commander_escalation(
        app_session,
        soldier_id=soldier.id,
        official_exemption_type_id=official.id,
        commander_exemption_type_id=commander_type.id,
        start_date=date(2026, 1, 1),
        end_date=None,
        reason="סיבה",
        apply_immediately=True,
        actor_id=commander.id,
    )

    assert req.status == "pending_duty_manager"
    assert req.commander_approved_by == commander.id
    assert req.exemption_type_id == official.id
    assert req.linked_commander_exemption_id is not None

    from app.db.models import SoldierExemption
    from sqlalchemy import select
    ex = app_session.execute(
        select(SoldierExemption).where(SoldierExemption.id == req.linked_commander_exemption_id)
    ).scalar_one()
    assert ex.soldier_id == soldier.id
    assert ex.exemption_type_id == commander_type.id
    assert ex.granted_by == commander.id


def test_escalation_request_only_does_not_grant_exemption(app_session):
    official = ExemptionType(name="פטור רפואי אסקלציה 2")
    app_session.add(official)
    app_session.flush()
    soldier = _soldier(app_session)
    commander = _soldier(app_session)

    req = submit_commander_escalation(
        app_session,
        soldier_id=soldier.id,
        official_exemption_type_id=official.id,
        commander_exemption_type_id=None,
        start_date=date(2026, 1, 1),
        end_date=None,
        reason="סיבה",
        apply_immediately=False,
        actor_id=commander.id,
    )

    assert req.status == "pending_duty_manager"
    assert req.linked_commander_exemption_id is None

    from app.db.models import SoldierExemption
    from sqlalchemy import select
    count = len(
        app_session.execute(
            select(SoldierExemption).where(SoldierExemption.soldier_id == soldier.id)
        ).scalars().all()
    )
    assert count == 0


def test_escalation_rejects_commander_type_as_official_target(app_session):
    commander_type = ExemptionType(name="פטור פיקודי אסקלציה 3", is_commander_exemption=True)
    app_session.add(commander_type)
    app_session.flush()
    soldier = _soldier(app_session)
    commander = _soldier(app_session)

    try:
        submit_commander_escalation(
            app_session,
            soldier_id=soldier.id,
            official_exemption_type_id=commander_type.id,
            commander_exemption_type_id=None,
            start_date=date(2026, 1, 1),
            end_date=None,
            reason="סיבה",
            apply_immediately=False,
            actor_id=commander.id,
        )
        assert False, "expected ExemptionRequestError"
    except ExemptionRequestError as exc:
        assert "official_exemption_type_required" in str(exc)


def test_escalation_apply_immediately_requires_commander_type(app_session):
    official = ExemptionType(name="פטור רפואי אסקלציה 4")
    app_session.add(official)
    app_session.flush()
    soldier = _soldier(app_session)
    commander = _soldier(app_session)

    try:
        submit_commander_escalation(
            app_session,
            soldier_id=soldier.id,
            official_exemption_type_id=official.id,
            commander_exemption_type_id=None,
            start_date=date(2026, 1, 1),
            end_date=None,
            reason="סיבה",
            apply_immediately=True,
            actor_id=commander.id,
        )
        assert False, "expected ExemptionRequestError"
    except ExemptionRequestError as exc:
        assert "commander_exemption_type_required" in str(exc)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_exemption_requests.py -k escalation -v`
Expected: FAIL — `ImportError: cannot import name 'submit_commander_escalation'`.

- [ ] **Step 3: Implement `submit_commander_escalation`**

In `backend/app/services/exemption_requests.py`, add the import of `grant_commander_exemption` and `ExemptionError` at the top:

```python
from app.services.exemptions import ExemptionError, grant_commander_exemption
```

Then add this function after `submit_request` (after line 55 in the current file):

```python
def submit_commander_escalation(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    official_exemption_type_id: uuid.UUID,
    start_date: date,
    end_date: date | None,
    reason: str | None,
    apply_immediately: bool,
    actor_id: uuid.UUID,
    commander_exemption_type_id: uuid.UUID | None = None,
) -> ExemptionRequest:
    official_type = session.get(ExemptionType, official_exemption_type_id)
    if official_type is None:
        raise ExemptionRequestError("exemption_type_not_found")
    if official_type.is_commander_exemption:
        raise ExemptionRequestError("official_exemption_type_required")
    if apply_immediately and commander_exemption_type_id is None:
        raise ExemptionRequestError("commander_exemption_type_required")

    linked_exemption_id = None
    if apply_immediately:
        exemption = grant_commander_exemption(
            session,
            soldier_id=soldier_id,
            exemption_type_id=commander_exemption_type_id,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            actor_id=actor_id,
        )
        linked_exemption_id = exemption.id

    req = ExemptionRequest(
        soldier_id=soldier_id,
        exemption_type_id=official_exemption_type_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        status="pending_duty_manager",
        commander_approved_by=actor_id,
        linked_commander_exemption_id=linked_exemption_id,
    )
    session.add(req)
    session.flush()

    from app.services.notifications import notify_duty_managers_of_request
    notify_duty_managers_of_request(
        session,
        soldier_id=soldier_id,
        type=NotificationType.exemption_request_pending,
        title="בקשת פטור חדשה (הועלתה ע\"י מפקד)",
        body=reason,
        reference_type="exemption_request",
        reference_id=req.id,
        actor_id=actor_id,
    )
    return req
```

`ExemptionError` from `grant_commander_exemption` (e.g. `not_commander_exemption_type`, `soldier_not_found`, `bad_date_range`) propagates unchanged — the route layer (Task 5) catches both exception types.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_exemption_requests.py -k escalation -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full exemption_requests test module**

Run: `cd backend && pytest app/services/tests/test_exemption_requests.py -v`
Expected: PASS (all tests, old and new).

- [ ] **Step 6: Commit**

```bash
cd backend
git add app/services/exemption_requests.py app/services/tests/test_exemption_requests.py
git commit -m "feat: add submit_commander_escalation service function"
```

---

### Task 5: Backend routes — escalate + per-soldier request history

**Files:**
- Modify: `backend/app/routes/exemption_requests.py`
- Test: Create `backend/tests/integration/test_commander_exemption_escalation_api.py`
- Modify: `backend/tests/conftest.py:97` (add area marker for the new test file)

**Interfaces:**
- Consumes: `submit_commander_escalation`, `ExemptionRequestError` (Task 4); `ExemptionError` (`app.services.exemptions`); `is_commander`, `is_duty_manager`, `_node_in_scope`, `scope_root_ids`, `authorize`, `Action`, `can_see_private` (`app.auth.authz`); `commander_can_grant_commander_exemption` (`app.services.authority`); the existing `ExemptionRequestOut`/`_out`/`ExemptionFileOut` Pydantic models already defined in this file.
- Produces: `POST /soldiers/{soldier_id}/exemptions/commander-escalate` and `GET /soldiers/{soldier_id}/exemption-requests`, both registered on the existing `router` in this file (included at `/api` prefix in `app/main.py`).

- [ ] **Step 1: Add the area marker for the new test file**

In `backend/tests/conftest.py`, in the `_AREA_MARKERS` dict, add this line next to the existing `"test_exemptions_api": "duty"` entry (around line 59):

```python
    "test_commander_exemption_escalation_api": "duty",
```

- [ ] **Step 2: Write the failing integration tests**

Create `backend/tests/integration/test_commander_exemption_escalation_api.py`:

```python
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ExemptionType
from tests.helpers import auth_headers, create_node, create_soldier


def _et(session, name, is_commander_exemption=False):
    et = ExemptionType(name=name, is_commander_exemption=is_commander_exemption)
    session.add(et)
    session.commit()
    session.refresh(et)
    return et


def test_admin_escalates_with_apply_immediately(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    target = create_soldier(admin_session, personal_number="5300001", hierarchy_node_id=d.id)
    admin = create_soldier(admin_session, personal_number="5300002", role="admin")
    official = _et(admin_session, "פטור-אסק-1")
    commander_type = _et(admin_session, "פטור-פיקודי-אסק-1", is_commander_exemption=True)

    r = client.post(
        f"/api/soldiers/{target.id}/exemptions/commander-escalate",
        headers=auth_headers(admin),
        json={
            "official_exemption_type_id": str(official.id),
            "commander_exemption_type_id": str(commander_type.id),
            "start_date": "2026-01-01",
            "reason": "סיבה",
            "apply_immediately": True,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending_duty_manager"

    exemptions = client.get(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(admin)).json()
    assert len(exemptions) == 1
    assert exemptions[0]["exemption_type_id"] == str(commander_type.id)


def test_admin_escalates_request_only(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d2")
    target = create_soldier(admin_session, personal_number="5300003", hierarchy_node_id=d.id)
    admin = create_soldier(admin_session, personal_number="5300004", role="admin")
    official = _et(admin_session, "פטור-אסק-2")

    r = client.post(
        f"/api/soldiers/{target.id}/exemptions/commander-escalate",
        headers=auth_headers(admin),
        json={
            "official_exemption_type_id": str(official.id),
            "start_date": "2026-01-01",
            "reason": "סיבה",
            "apply_immediately": False,
        },
    )
    assert r.status_code == 201, r.text
    exemptions = client.get(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(admin)).json()
    assert exemptions == []


def test_out_of_scope_commander_forbidden(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d3")
    other = create_node(admin_session, level="department", name="other3")
    cmd = create_soldier(admin_session, personal_number="5300005", role="commander")
    other.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="5300006", hierarchy_node_id=d.id)
    official = _et(admin_session, "פטור-אסק-3")

    r = client.post(
        f"/api/soldiers/{target.id}/exemptions/commander-escalate",
        headers=auth_headers(cmd),
        json={
            "official_exemption_type_id": str(official.id),
            "start_date": "2026-01-01",
            "reason": "סיבה",
            "apply_immediately": False,
        },
    )
    assert r.status_code == 403


def test_escalate_rejects_commander_type_as_official_target(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d4")
    target = create_soldier(admin_session, personal_number="5300007", hierarchy_node_id=d.id)
    admin = create_soldier(admin_session, personal_number="5300008", role="admin")
    commander_type = _et(admin_session, "פטור-פיקודי-אסק-4", is_commander_exemption=True)

    r = client.post(
        f"/api/soldiers/{target.id}/exemptions/commander-escalate",
        headers=auth_headers(admin),
        json={
            "official_exemption_type_id": str(commander_type.id),
            "start_date": "2026-01-01",
            "reason": "סיבה",
            "apply_immediately": False,
        },
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "official_exemption_type_required"


def test_soldier_exemption_request_history_shows_all_statuses(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d5")
    target = create_soldier(admin_session, personal_number="5300009", hierarchy_node_id=d.id)
    admin = create_soldier(admin_session, personal_number="5300010", role="admin")
    official = _et(admin_session, "פטור-אסק-5")

    req = client.post(
        f"/api/soldiers/{target.id}/exemptions/commander-escalate",
        headers=auth_headers(admin),
        json={
            "official_exemption_type_id": str(official.id),
            "start_date": "2026-01-01",
            "reason": "סיבה",
            "apply_immediately": False,
        },
    ).json()
    client.post(
        f"/api/exemption-requests/{req['id']}/reject",
        headers=auth_headers(admin),
        json={"decision_note": "לא רלוונטי"},
    )

    r = client.get(f"/api/soldiers/{target.id}/exemption-requests", headers=auth_headers(admin))
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "rejected"


def test_soldier_cannot_read_others_exemption_request_history(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d6")
    target = create_soldier(admin_session, personal_number="5300011", hierarchy_node_id=d.id)
    other_soldier = create_soldier(admin_session, personal_number="5300012")

    r = client.get(f"/api/soldiers/{target.id}/exemption-requests", headers=auth_headers(other_soldier))
    assert r.status_code == 403
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/integration/test_commander_exemption_escalation_api.py -v`
Expected: FAIL — 404s (routes don't exist yet).

- [ ] **Step 4: Implement the routes**

In `backend/app/routes/exemption_requests.py`, add these imports to the existing import block near the top:

```python
from app.auth.authz import (
    Action, authorize, can_see_private, is_commander, is_duty_manager, scope_root_ids,
)
from app.services.authority import commander_can_grant_commander_exemption
from app.services.exemption_requests import submit_commander_escalation
from app.services.exemptions import ExemptionError
```

(Merge these with the file's existing imports rather than duplicating — `ExemptionRequestError`, `HierarchyNode`, `Soldier`, `Action`, `authorize`, `can_see_private`, `scope_root_ids` are already imported at the top of this file; only add the new names: `is_commander`, `is_duty_manager`, `commander_can_grant_commander_exemption`, `submit_commander_escalation`, `ExemptionError`.)

Add these two Pydantic models next to `CreateExemptionRequest`:

```python
class CommanderEscalateRequest(BaseModel):
    official_exemption_type_id: uuid.UUID
    commander_exemption_type_id: uuid.UUID | None = None
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = None
    reason: str = Field(min_length=1, max_length=1000)
    apply_immediately: bool
```

Add the two routes at the end of the file:

```python
@router.post(
    "/soldiers/{soldier_id}/exemptions/commander-escalate",
    response_model=ExemptionRequestOut,
    status_code=status.HTTP_201_CREATED,
)
def escalate_commander_exemption_route(
    soldier_id: uuid.UUID,
    body: CommanderEscalateRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> ExemptionRequestOut:
    target_soldier = session.get(Soldier, soldier_id)
    if target_soldier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    target_node = (
        session.get(HierarchyNode, target_soldier.hierarchy_node_id)
        if target_soldier.hierarchy_node_id
        else None
    )

    allowed = user.role == "admin"
    if not allowed and is_duty_manager(session, user.id):
        from app.auth.authz import _node_in_scope
        allowed = _node_in_scope(target_node, scope_root_ids(session, user))
    if not allowed and is_commander(session, user.id):
        from app.auth.authz import _node_in_scope
        in_scope = _node_in_scope(target_node, scope_root_ids(session, user))
        allowed = in_scope and commander_can_grant_commander_exemption(
            session, commander_id=user.id, commander_rank=user.rank,
        )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    try:
        req = submit_commander_escalation(
            session,
            soldier_id=soldier_id,
            official_exemption_type_id=body.official_exemption_type_id,
            commander_exemption_type_id=body.commander_exemption_type_id,
            start_date=date.fromisoformat(body.start_date),
            end_date=date.fromisoformat(body.end_date) if body.end_date else None,
            reason=body.reason,
            apply_immediately=body.apply_immediately,
            actor_id=user.id,
        )
    except (ExemptionRequestError, ExemptionError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return _out(req, include_sensitive=True)


@router.get("/soldiers/{soldier_id}/exemption-requests", response_model=list[ExemptionRequestOut])
def get_soldier_exemption_request_history(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ExemptionRequestOut]:
    target_soldier = session.get(Soldier, soldier_id)
    if target_soldier is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if target_soldier.id != user.id:
        target_node = (
            session.get(HierarchyNode, target_soldier.hierarchy_node_id)
            if target_soldier.hierarchy_node_id
            else None
        )
        authorize(session, user, Action.EXEMPTION_READ, target_node=target_node)
    include_sensitive = can_see_private(session, user, target_soldier)
    reqs = session.execute(
        select(ExemptionRequest)
        .where(ExemptionRequest.soldier_id == soldier_id)
        .order_by(ExemptionRequest.created_at.desc())
    ).scalars().all()
    req_ids = [r.id for r in reqs]
    all_files = (
        session.execute(
            select(ExemptionRequestFile).where(ExemptionRequestFile.exemption_request_id.in_(req_ids))
        ).scalars().all()
        if req_ids
        else []
    )
    files_by_req: dict[uuid.UUID, list[ExemptionFileOut]] = {}
    for f in all_files:
        files_by_req.setdefault(f.exemption_request_id, []).append(
            ExemptionFileOut(id=f.id, file_name=f.file_name, content_type=f.content_type, created_at=f.created_at.isoformat())
        )
    return [
        _out(r, soldier_name=target_soldier.full_name, files=files_by_req.get(r.id, []), include_sensitive=include_sensitive)
        for r in reqs
    ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_commander_exemption_escalation_api.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Run the broader exemption test suite for regressions**

Run: `cd backend && pytest -m duty -q`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
cd backend
git add app/routes/exemption_requests.py tests/integration/test_commander_exemption_escalation_api.py tests/conftest.py
git commit -m "feat: add commander-escalate and per-soldier exemption-request-history routes"
```

---

### Task 6: Frontend — let commanders see exemption grant forms

**Files:**
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx:52,434`

**Interfaces:**
- Produces: `canManageExemptions: boolean` local variable, passed only to `<ExemptionsPanel canManage={...} />`. Leaves the existing `canManage` variable (used at lines 164, 322, 473 for soldier-detail editing and constraints) untouched.

- [ ] **Step 1: Add the new variable**

In `frontend/src/components/UnifiedSoldierModal.tsx`, directly after the existing line 52 (`const canManage = isAdmin || isDutyManager;`), add:

```tsx
  // Backend authorizes commanders to grant exemptions too (Action.EXEMPTION_GRANT
  // is in _COMMANDER_ACTIONS) — this is scoped to ExemptionsPanel only, not the
  // broader `canManage` used for soldier-detail editing and constraint approval.
  const canManageExemptions = isAdmin || isDutyManager || isCommander;
```

- [ ] **Step 2: Use it for the exemptions tab**

Change line 434 from:

```tsx
          <ExemptionsPanel soldierId={soldier.id} canManage={canManage} />
```

to:

```tsx
          <ExemptionsPanel soldierId={soldier.id} canManage={canManageExemptions} />
```

- [ ] **Step 3: Verify typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
cd frontend
git add src/components/UnifiedSoldierModal.tsx
git commit -m "fix: let in-scope commanders see exemption grant forms, matching backend authorization"
```

---

### Task 7: Frontend API wrappers

**Files:**
- Modify: `frontend/src/api/exemptions.ts`

**Interfaces:**
- Produces: `escalateCommanderExemption(soldierId, input): Promise<ExemptionRequest>`, `listExemptionRequestsForSoldier(soldierId): Promise<ExemptionRequest[]>` — both consumed by Task 8 and Task 9.

- [ ] **Step 1: Add the wrappers**

At the end of `frontend/src/api/exemptions.ts`, add:

```ts
export async function escalateCommanderExemption(soldierId: string, input: {
  official_exemption_type_id: string;
  commander_exemption_type_id?: string;
  start_date: string;
  end_date?: string | null;
  reason: string;
  apply_immediately: boolean;
}): Promise<ExemptionRequest> {
  return (await api.post<ExemptionRequest>(`/soldiers/${soldierId}/exemptions/commander-escalate`, input)).data;
}

export async function listExemptionRequestsForSoldier(soldierId: string): Promise<ExemptionRequest[]> {
  return (await api.get<ExemptionRequest[]>(`/soldiers/${soldierId}/exemption-requests`)).data;
}
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd frontend
git add src/api/exemptions.ts
git commit -m "feat: add escalateCommanderExemption and listExemptionRequestsForSoldier API wrappers"
```

---

### Task 8: Frontend — request history section in `ExemptionsPanel`

**Files:**
- Modify: `frontend/src/components/ExemptionsPanel.tsx`
- Modify: `frontend/src/i18n/he.json:161-173` (the `exemptions` block)
- Modify: `frontend/src/components/ExemptionsPanel.test.tsx`

**Interfaces:**
- Consumes: `listExemptionRequestsForSoldier`, `ExemptionRequest` (Task 7); `approveExemptionRequestCommanderStep`, `approveExemptionRequestDutyManagerStep`, `rejectExemptionRequest` (already exported from `../api/exemptions`, used by `ApprovalsPage.tsx`).
- Produces: a "בקשות פטור" section rendered inside `ExemptionsPanel`, `data-testid="exemption-requests-list"`.

- [ ] **Step 1: Add new i18n keys**

In `frontend/src/i18n/he.json`, inside the `"exemptions"` block (currently lines 161-173), add these keys before the closing `}`:

```json
    "requests_title": "בקשות פטור",
    "requests_none": "אין בקשות פטור",
    "request_status_pending_commander": "ממתין לאישור מפקד",
    "request_status_pending_duty_manager": 'ממתין לאישור קצין אג"ם/מרכז ומעלה',
    "request_status_approved": "אושר",
    "request_status_rejected": "נדחה",
    "approve_commander_step": "אשר (שלב מפקד)",
    "approve_duty_manager_step": "אשר (שלב סופי)",
    "reject": "דחה"
```

Note: this is a `.json` file, so use a double-quoted string with an escaped quote for the `קצין אג"ם` value (JSON doesn't support single-quoted strings) — write it as `"ממתין לאישור קצין אג\"ם/מרכז ומעלה"`.

- [ ] **Step 2: Write the failing test**

Extend `frontend/src/components/ExemptionsPanel.test.tsx`:

```tsx
vi.mock("../api/exemptions", () => ({
  listExemptions: vi.fn(() => Promise.resolve([])),
  grantExemption: vi.fn(() => Promise.resolve({})),
  revokeExemption: vi.fn(() => Promise.resolve()),
  grantCommanderExemption: vi.fn(() => Promise.resolve()),
  escalateCommanderExemption: vi.fn(() => Promise.resolve({})),
  listExemptionRequestsForSoldier: vi.fn(() => Promise.resolve([
    {
      id: "req-1",
      soldier_id: "abc",
      soldier_name: "X",
      node_name: null,
      exemption_type_id: "et-1",
      start_date: "2026-01-01",
      end_date: null,
      reason: "סיבה",
      status: "pending_duty_manager",
      enrollment_request_id: null,
      decided_by: null,
      decision_note: null,
      created_at: "2026-01-01T00:00:00Z",
      files: [],
    },
  ])),
  approveExemptionRequestCommanderStep: vi.fn(() => Promise.resolve()),
  approveExemptionRequestDutyManagerStep: vi.fn(() => Promise.resolve()),
  rejectExemptionRequest: vi.fn(() => Promise.resolve({})),
}));

test("shows exemption request history with a pending duty-manager approve button", async () => {
  render(<ExemptionsPanel soldierId="abc" canManage={true} />);
  const row = await screen.findByTestId("exemption-request-row-req-1");
  expect(row).toBeTruthy();
  expect(screen.getByTestId("exemption-request-approve-req-1")).toBeTruthy();
});
```

Also update the top-level mock block (lines 14-19 currently) to include the two new exports, since every test in the file shares that one `vi.mock` call — replace the existing block with the extended one above (don't duplicate the `vi.mock` call).

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/ExemptionsPanel.test.tsx`
Expected: FAIL — `exemption-request-row-req-1` not found.

- [ ] **Step 4: Implement the request-history section**

In `frontend/src/components/ExemptionsPanel.tsx`:

Add to the imports:

```tsx
import {
  Exemption, ExemptionRequest, grantExemption, listExemptions, revokeExemption,
  listExemptionRequestsForSoldier, approveExemptionRequestCommanderStep,
  approveExemptionRequestDutyManagerStep, rejectExemptionRequest,
} from "../api/exemptions";
```

Add state and a refresh function, next to the existing `items`/`refresh` state (around line 31-43):

```tsx
  const [requests, setRequests] = useState<ExemptionRequest[]>([]);
  const [rejectNotes, setRejectNotes] = useState<Record<string, string>>({});

  const refreshRequests = useCallback(async () => {
    setRequests(await listExemptionRequestsForSoldier(soldierId));
  }, [soldierId]);
  useEffect(() => { void refreshRequests(); }, [refreshRequests]);
```

Add handlers next to `onRevoke` (around line 90):

```tsx
  async function onApproveCommanderStep(id: string) {
    await approveExemptionRequestCommanderStep(id);
    await refreshRequests();
  }
  async function onApproveDutyManagerStep(id: string) {
    await approveExemptionRequestDutyManagerStep(id);
    await refreshRequests();
  }
  async function onRejectRequest(id: string) {
    const note = rejectNotes[id];
    if (!note) return;
    await rejectExemptionRequest(id, note);
    setRejectNotes((prev) => { const next = { ...prev }; delete next[id]; return next; });
    await refreshRequests();
  }
```

Add the section markup directly after the "Expired / past exemptions" block (after line 207, before the "Grant form" comment):

```tsx
      {/* Exemption request history */}
      <div>
        <h3 className="font-semibold text-sm text-gray-700 dark:text-gray-200 mb-2">
          {t("exemptions.requests_title")} ({requests.length})
        </h3>
        {requests.length === 0 ? (
          <p className="text-sm text-gray-500" data-testid="exemption-requests-empty">
            {t("exemptions.requests_none")}
          </p>
        ) : (
          <ul className="space-y-2" data-testid="exemption-requests-list">
            {requests.map((req) => (
              <li
                key={req.id}
                className="border dark:border-gray-600 rounded p-3"
                data-testid={`exemption-request-row-${req.id}`}
              >
                <p className="text-xs text-gray-500 mb-1" data-testid={`exemption-request-status-${req.id}`}>
                  {t(`exemptions.request_status_${req.status}`)}
                </p>
                <p className="text-sm flex items-center gap-2" dir="ltr">
                  <span>{formatDate(req.start_date)} → {req.end_date ? formatDate(req.end_date) : t("exemptions.forever")}</span>
                </p>
                {req.reason && <p className="text-xs text-gray-500 mb-2">{req.reason}</p>}
                {canManage && (req.status === "pending_commander" || req.status === "pending_duty_manager") && (
                  <div className="flex items-center gap-2">
                    {req.status === "pending_commander" && (
                      <button
                        className="bg-green-600 text-white px-3 py-1 rounded text-sm"
                        onClick={() => void onApproveCommanderStep(req.id)}
                        data-testid={`exemption-request-approve-${req.id}`}
                      >
                        {t("exemptions.approve_commander_step")}
                      </button>
                    )}
                    {req.status === "pending_duty_manager" && (
                      <button
                        className="bg-green-600 text-white px-3 py-1 rounded text-sm"
                        onClick={() => void onApproveDutyManagerStep(req.id)}
                        data-testid={`exemption-request-approve-${req.id}`}
                      >
                        {t("exemptions.approve_duty_manager_step")}
                      </button>
                    )}
                    <input
                      className="border rounded p-1 text-sm w-28 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                      value={rejectNotes[req.id] ?? ""}
                      onChange={(e) => setRejectNotes((prev) => ({ ...prev, [req.id]: e.target.value }))}
                      placeholder={t("approvals.decision_note")}
                      data-testid={`exemption-request-reject-note-${req.id}`}
                    />
                    <button
                      className="bg-red-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
                      disabled={!rejectNotes[req.id]}
                      onClick={() => void onRejectRequest(req.id)}
                      data-testid={`exemption-request-reject-${req.id}`}
                    >
                      {t("exemptions.reject")}
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/ExemptionsPanel.test.tsx`
Expected: PASS.

- [ ] **Step 6: Run lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: no errors, no warnings.

- [ ] **Step 7: Commit**

```bash
cd frontend
git add src/components/ExemptionsPanel.tsx src/components/ExemptionsPanel.test.tsx src/i18n/he.json
git commit -m "feat: show exemption request history in ExemptionsPanel"
```

---

### Task 9: Frontend — confirmation modal + escalation checkboxes in `CommanderExemptionGrantForm`

**Files:**
- Modify: `frontend/src/components/CommanderExemptionGrantForm.tsx`
- Modify: `frontend/src/components/ExemptionsPanel.tsx` (pass the list of official exemption types down)
- Create: `frontend/src/components/CommanderExemptionGrantForm.test.tsx`

**Interfaces:**
- Consumes: `escalateCommanderExemption` (Task 7); `grantCommanderExemption` (existing).
- Produces: `CommanderExemptionGrantForm` now takes an additional prop `officialExemptionTypes: { id: string; name: string }[]`.

- [ ] **Step 1: Pass official exemption types from `ExemptionsPanel`**

In `frontend/src/components/ExemptionsPanel.tsx`, next to the existing `commanderExemptionTypes` computation (line 64: `const commanderExemptionTypes = types.filter((tp) => tp.is_commander_exemption === true);`), add:

```tsx
  const officialExemptionTypes = types.filter((tp) => tp.is_commander_exemption !== true);
```

Then update the existing block (currently lines 248-254):

```tsx
      {canManage && commanderExemptionTypes.length > 0 && (
        <CommanderExemptionGrantForm
          soldierId={soldierId}
          commanderExemptionTypes={commanderExemptionTypes.map((tp) => ({ id: tp.id, name: tp.name }))}
          onGranted={() => void refresh()}
        />
      )}
```

to (only the `<CommanderExemptionGrantForm>` props change — the surrounding `{canManage && ...}` wrapper stays as-is):

```tsx
      {canManage && commanderExemptionTypes.length > 0 && (
        <CommanderExemptionGrantForm
          soldierId={soldierId}
          commanderExemptionTypes={commanderExemptionTypes.map((tp) => ({ id: tp.id, name: tp.name }))}
          officialExemptionTypes={officialExemptionTypes.map((tp) => ({ id: tp.id, name: tp.name }))}
          onGranted={() => { void refresh(); void refreshRequests(); }}
        />
      )}
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/components/CommanderExemptionGrantForm.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import CommanderExemptionGrantForm from "./CommanderExemptionGrantForm";
import { grantCommanderExemption, escalateCommanderExemption } from "../api/exemptions";

vi.mock("../api/exemptions", () => ({
  grantCommanderExemption: vi.fn(() => Promise.resolve()),
  escalateCommanderExemption: vi.fn(() => Promise.resolve({})),
}));

const commanderTypes = [{ id: "c1", name: "פטור פיקודי כללי" }];
const officialTypes = [{ id: "o1", name: "פטור רפואי" }];

test("grant is blocked until the confirmation checkbox is ticked", () => {
  render(
    <CommanderExemptionGrantForm
      soldierId="s1"
      commanderExemptionTypes={commanderTypes}
      officialExemptionTypes={officialTypes}
      onGranted={() => {}}
    />
  );
  fireEvent.change(screen.getByTestId("commander-exemption-reason"), { target: { value: "סיבה" } });
  fireEvent.click(screen.getByTestId("commander-exemption-submit"));

  const modalConfirm = screen.getByTestId("commander-exemption-confirm");
  expect(modalConfirm).toBeDisabled();
  fireEvent.click(screen.getByTestId("commander-exemption-ack-checkbox"));
  expect(modalConfirm).not.toBeDisabled();
});

test("plain grant calls grantCommanderExemption when escalate is off", async () => {
  render(
    <CommanderExemptionGrantForm
      soldierId="s1"
      commanderExemptionTypes={commanderTypes}
      officialExemptionTypes={officialTypes}
      onGranted={() => {}}
    />
  );
  fireEvent.change(screen.getByTestId("commander-exemption-reason"), { target: { value: "סיבה" } });
  fireEvent.click(screen.getByTestId("commander-exemption-submit"));
  fireEvent.click(screen.getByTestId("commander-exemption-ack-checkbox"));
  fireEvent.click(screen.getByTestId("commander-exemption-confirm"));

  await waitFor(() => expect(grantCommanderExemption).toHaveBeenCalledWith("s1", expect.objectContaining({ reason: "סיבה" })));
  expect(escalateCommanderExemption).not.toHaveBeenCalled();
});

test("escalate on with apply-immediately calls escalateCommanderExemption with apply_immediately true", async () => {
  render(
    <CommanderExemptionGrantForm
      soldierId="s1"
      commanderExemptionTypes={commanderTypes}
      officialExemptionTypes={officialTypes}
      onGranted={() => {}}
    />
  );
  fireEvent.change(screen.getByTestId("commander-exemption-reason"), { target: { value: "סיבה" } });
  fireEvent.click(screen.getByTestId("commander-exemption-escalate-checkbox"));
  fireEvent.click(screen.getByTestId("commander-exemption-apply-immediately-checkbox"));
  fireEvent.click(screen.getByTestId("commander-exemption-submit"));
  fireEvent.click(screen.getByTestId("commander-exemption-ack-checkbox"));
  fireEvent.click(screen.getByTestId("commander-exemption-confirm"));

  await waitFor(() =>
    expect(escalateCommanderExemption).toHaveBeenCalledWith(
      "s1",
      expect.objectContaining({ apply_immediately: true, official_exemption_type_id: "o1", commander_exemption_type_id: "c1" })
    )
  );
});

test("escalate on without apply-immediately defaults apply_immediately to false", async () => {
  render(
    <CommanderExemptionGrantForm
      soldierId="s1"
      commanderExemptionTypes={commanderTypes}
      officialExemptionTypes={officialTypes}
      onGranted={() => {}}
    />
  );
  fireEvent.change(screen.getByTestId("commander-exemption-reason"), { target: { value: "סיבה" } });
  fireEvent.click(screen.getByTestId("commander-exemption-escalate-checkbox"));
  fireEvent.click(screen.getByTestId("commander-exemption-submit"));
  fireEvent.click(screen.getByTestId("commander-exemption-ack-checkbox"));
  fireEvent.click(screen.getByTestId("commander-exemption-confirm"));

  await waitFor(() =>
    expect(escalateCommanderExemption).toHaveBeenCalledWith(
      "s1",
      expect.objectContaining({ apply_immediately: false })
    )
  );
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/CommanderExemptionGrantForm.test.tsx`
Expected: FAIL — `commander-exemption-confirm` / escalate checkboxes don't exist yet, and the component doesn't accept `officialExemptionTypes`.

- [ ] **Step 4: Rewrite `CommanderExemptionGrantForm.tsx`**

Replace the full contents of `frontend/src/components/CommanderExemptionGrantForm.tsx` with:

```tsx
import { useState } from "react";
import { escalateCommanderExemption, grantCommanderExemption } from "../api/exemptions";

interface Props {
  soldierId: string;
  commanderExemptionTypes: { id: string; name: string }[];
  officialExemptionTypes: { id: string; name: string }[];
  onGranted: () => void;
}

export default function CommanderExemptionGrantForm({
  soldierId, commanderExemptionTypes, officialExemptionTypes, onGranted,
}: Props) {
  const [typeId, setTypeId] = useState(commanderExemptionTypes[0]?.id ?? "");
  const [startDate, setStartDate] = useState(new Date().toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [escalate, setEscalate] = useState(false);
  const [officialTypeId, setOfficialTypeId] = useState(officialExemptionTypes[0]?.id ?? "");
  const [applyImmediately, setApplyImmediately] = useState(false);

  const [showConfirm, setShowConfirm] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);

  function openConfirm() {
    if (!reason.trim()) {
      setError("נדרשת סיבה");
      return;
    }
    if (escalate && !officialTypeId) {
      setError("יש לבחור סוג פטור רשמי לבקשה");
      return;
    }
    setError(null);
    setAcknowledged(false);
    setShowConfirm(true);
  }

  async function handleConfirm() {
    try {
      if (escalate) {
        await escalateCommanderExemption(soldierId, {
          official_exemption_type_id: officialTypeId,
          commander_exemption_type_id: applyImmediately ? typeId : undefined,
          start_date: startDate,
          end_date: endDate || null,
          reason,
          apply_immediately: applyImmediately,
        });
      } else {
        await grantCommanderExemption(soldierId, {
          exemption_type_id: typeId,
          start_date: startDate,
          end_date: endDate || null,
          reason,
        });
      }
      setReason("");
      setShowConfirm(false);
      onGranted();
    } catch {
      setError("שגיאה במתן הפטור");
      setShowConfirm(false);
    }
  }

  return (
    <div className="space-y-2 border rounded p-3" dir="rtl" data-testid="commander-exemption-form">
      <h3 className="font-semibold">צור פטור פיקודי</h3>
      <p className="text-sm text-gray-600">
        שימו לב: פטור פיקודי לא מפחית את הפוטנציאל של היחידה — עומס התורנות יתחלק על פחות חיילים. יש להשתמש בו בצמצום.
      </p>
      <select value={typeId} onChange={(e) => setTypeId(e.target.value)} className="border rounded p-1 w-full" data-testid="commander-exemption-type">
        {commanderExemptionTypes.map((t) => (
          <option key={t.id} value={t.id}>{t.name}</option>
        ))}
      </select>
      <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="border rounded p-1 w-full" data-testid="commander-exemption-start" />
      <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} placeholder="תאריך סיום (רשות)" className="border rounded p-1 w-full" data-testid="commander-exemption-end" />
      <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="סיבה (חובה)" className="border rounded p-1 w-full" data-testid="commander-exemption-reason" />

      <label className="flex items-center gap-2 text-sm cursor-pointer">
        <input
          type="checkbox"
          checked={escalate}
          onChange={(e) => setEscalate(e.target.checked)}
          data-testid="commander-exemption-escalate-checkbox"
        />
        העלה לאישור מפקד תורנויות כפטור רשמי
      </label>

      {escalate && (
        <div className="space-y-2 pr-4 border-r-2 border-indigo-200">
          <select
            value={officialTypeId}
            onChange={(e) => setOfficialTypeId(e.target.value)}
            className="border rounded p-1 w-full"
            data-testid="commander-exemption-official-type"
          >
            {officialExemptionTypes.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={applyImmediately}
              onChange={(e) => setApplyImmediately(e.target.checked)}
              data-testid="commander-exemption-apply-immediately-checkbox"
            />
            החל את הפטור הפיקודי מיידית (בנוסף לבקשה)
          </label>
        </div>
      )}

      {error && <p className="text-red-600 text-sm">{error}</p>}
      <button type="button" onClick={openConfirm} className="bg-blue-600 text-white rounded px-3 py-1" data-testid="commander-exemption-submit">
        צור פטור פיקודי
      </button>

      {showConfirm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setShowConfirm(false)}>
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl p-6 max-w-md w-full mx-4" dir="rtl" onClick={(e) => e.stopPropagation()}>
            <h4 className="font-bold text-lg mb-3">אישור מתן פטור פיקודי</h4>
            <p className="text-sm text-gray-600 dark:text-gray-300 mb-4">
              פטור פיקודי לא נספר בחישובי הפוטנציאל — היחידה תישא בעומס במקום החייל. יש להשתמש בכלי זה בצמצום.
            </p>
            <label className="flex items-center gap-2 text-sm cursor-pointer mb-4">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(e) => setAcknowledged(e.target.checked)}
                data-testid="commander-exemption-ack-checkbox"
              />
              אני מבין/ה
            </label>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowConfirm(false)}
                className="px-4 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-lg text-gray-600 dark:text-gray-300"
              >
                ביטול
              </button>
              <button
                onClick={() => void handleConfirm()}
                disabled={!acknowledged}
                className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg disabled:opacity-40"
                data-testid="commander-exemption-confirm"
              >
                אשר
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/CommanderExemptionGrantForm.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 6: Run the full frontend test suite for regressions**

Run: `cd frontend && npm test`
Expected: PASS, no regressions (in particular `ExemptionsPanel.test.tsx`, since its props changed).

- [ ] **Step 7: Run lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: no errors, no warnings.

- [ ] **Step 8: Manual verification in the dev stack**

Run `.\dev.ps1` from the repo root, log in as a soldier with `is_commander` scope over another soldier, open that soldier's profile, go to the פטורים tab, and confirm:
- The "צור פטור פיקודי" button opens the confirmation modal, and its "אשר" button stays disabled until "אני מבין/ה" is ticked.
- Ticking "העלה לאישור מפקד תורנויות כפטור רשמי" reveals the official-type dropdown and the "החל מיידית" checkbox.
- Submitting with escalate + apply-immediately both on creates a granted exemption AND a pending-duty-manager entry in the new "בקשות פטור" section.
- Submitting with escalate on but apply-immediately off creates only the pending request (no new row in the active exemptions list).

- [ ] **Step 9: Commit**

```bash
cd frontend
git add src/components/CommanderExemptionGrantForm.tsx src/components/CommanderExemptionGrantForm.test.tsx src/components/ExemptionsPanel.tsx
git commit -m "feat: add confirmation modal and duty-manager escalation to CommanderExemptionGrantForm"
```

---

## Self-Review Notes

- **Spec coverage:** confirmation gate (Task 9), escalation checkboxes + official-type picker (Task 9), request history in the exemptions tab (Task 8), backend escalation service + routes (Tasks 3-5), `linked_commander_exemption_id` (Tasks 1-2), commander visibility fix (Task 6) — every section of the design doc has a corresponding task.
- **Type consistency:** `ExemptionRequest.linked_commander_exemption_id` (Task 2) → read by `submit_commander_escalation` (Task 4) → exposed via `ExemptionRequestOut` unchanged (the field isn't surfaced in the API response; it's DB-internal bookkeeping, matching the design doc which only specifies it for the DM approval UI's *future* use — not required by this plan's frontend tasks). `officialExemptionTypes` prop name is consistent between `ExemptionsPanel.tsx` (Task 9, Step 1) and `CommanderExemptionGrantForm.tsx` (Task 9, Step 4).
- **No placeholders:** all steps contain complete, runnable code.


