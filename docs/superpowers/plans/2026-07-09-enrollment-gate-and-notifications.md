# Enrollment Permission Gate & Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Soldiers whose intake (קליטה למסגרת) is still pending can view their own data but cannot perform soldier-initiated write actions, and get notified when their enrollment is approved/rejected.

**Architecture:** Add a new FastAPI dependency `require_enrolled` (backend/app/auth/deps.py) that 403s if the current user has an in-progress `SoldierEnrollmentRequest`; swap it in for `require_password_changed` on the soldier-initiated write endpoints (swap create/claim/offer/take-free, constraint submit, exemption-request create). Add `create_notification` calls to the existing `approve_enrollment`/`reject_enrollment` service functions. Expose the pending state on `/me` so the frontend can show a banner and disable the relevant forms instead of surfacing a raw 403.

**Tech Stack:** FastAPI, SQLAlchemy, pytest (backend); React, TypeScript, Vitest (frontend).

## Global Constraints

- Read access is never restricted by this change — only soldier-initiated write endpoints (swap create/claim/offer/take-free, constraint submit, exemption-request create).
- A soldier with **no** `SoldierEnrollmentRequest` row at all (e.g. created outside the registration flow) is treated as fully enrolled — never gated.
- `SoldierEnrollmentRequest.status` values in play: `"pending"`, `"commander_approved"` (both count as "still pending" for this gate), `"approved"`, `"rejected"`.

---

### Task 1: `require_enrolled` dependency

**Files:**
- Modify: `backend/app/auth/deps.py`
- Test: `backend/tests/integration/test_enrollment_gate.py` (new)

**Interfaces:**
- Produces: `require_enrolled(session: Session = Depends(get_session), user: Soldier = Depends(require_password_changed)) -> Soldier` — raises `HTTPException(403, detail="enrollment_pending")` if the user has a `SoldierEnrollmentRequest` with `status` in `("pending", "commander_approved")`; otherwise returns `user` unchanged. Importable as `from app.auth.deps import require_enrolled`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_enrollment_gate.py
from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.deps import require_enrolled
from app.db.models import SoldierEnrollmentRequest
from app.db.session import get_session
from tests.helpers import auth_headers, create_node, create_soldier


def _make_probe_app(real_app):
    """Mount a throwaway endpoint gated by require_enrolled onto the real app,
    reusing its already-wired get_session override."""
    @real_app.get("/__probe/require_enrolled")
    def _probe(user=Depends(require_enrolled)):
        return {"id": str(user.id)}


def test_soldier_with_pending_enrollment_is_blocked(client: TestClient, admin_session: Session):
    from app.main import app
    _make_probe_app(app)
    node = create_node(admin_session, level="unit", name="probe_unit_pending")
    s = create_soldier(admin_session, personal_number="7600001", hierarchy_node_id=node.id)
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id, status="pending"))
    admin_session.commit()

    r = client.get("/__probe/require_enrolled", headers=auth_headers(s))
    assert r.status_code == 403
    assert r.json()["detail"] == "enrollment_pending"


def test_soldier_with_commander_approved_enrollment_is_blocked(client: TestClient, admin_session: Session):
    from app.main import app
    _make_probe_app(app)
    node = create_node(admin_session, level="unit", name="probe_unit_commander_approved")
    s = create_soldier(admin_session, personal_number="7600002", hierarchy_node_id=node.id)
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id, status="commander_approved"))
    admin_session.commit()

    r = client.get("/__probe/require_enrolled", headers=auth_headers(s))
    assert r.status_code == 403


def test_soldier_with_approved_enrollment_passes(client: TestClient, admin_session: Session):
    from app.main import app
    _make_probe_app(app)
    node = create_node(admin_session, level="unit", name="probe_unit_approved")
    s = create_soldier(admin_session, personal_number="7600003", hierarchy_node_id=node.id)
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id, status="approved"))
    admin_session.commit()

    r = client.get("/__probe/require_enrolled", headers=auth_headers(s))
    assert r.status_code == 200


def test_soldier_with_no_enrollment_request_passes(client: TestClient, admin_session: Session):
    from app.main import app
    _make_probe_app(app)
    s = create_soldier(admin_session, personal_number="7600004")

    r = client.get("/__probe/require_enrolled", headers=auth_headers(s))
    assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_enrollment_gate.py -v`
Expected: FAIL with `ImportError: cannot import name 'require_enrolled' from 'app.auth.deps'`

- [ ] **Step 3: Implement `require_enrolled`**

In `backend/app/auth/deps.py`, add the import and the new dependency:

```python
def require_enrolled(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> Soldier:
    """Block soldier-initiated write actions while intake (enrollment) is still
    pending. Read access is never gated here — only used on write endpoints."""
    from app.db.models import SoldierEnrollmentRequest

    pending = session.execute(
        select(SoldierEnrollmentRequest.id).where(
            SoldierEnrollmentRequest.soldier_id == user.id,
            SoldierEnrollmentRequest.status.in_(("pending", "commander_approved")),
        ).limit(1)
    ).first()
    if pending is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="enrollment_pending")
    return user
```

Add `from sqlalchemy import select` to the top-level imports of `backend/app/auth/deps.py` (it currently only imports `Session` from `sqlalchemy.orm`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_enrollment_gate.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/auth/deps.py backend/tests/integration/test_enrollment_gate.py
git commit -m "feat: add require_enrolled dependency to gate soldier write actions during pending intake"
```

---

### Task 2: Apply the gate to soldier-initiated write endpoints

**Files:**
- Modify: `backend/app/routes/swaps.py` (create, take_free, submit_cover_offer, claim)
- Modify: `backend/app/routes/constraints.py` (submit)
- Modify: `backend/app/routes/exemption_requests.py` (create_exemption_request)
- Test: `backend/tests/integration/test_enrollment_gate.py` (append)

**Interfaces:**
- Consumes: `require_enrolled` from Task 1 (`from app.auth.deps import require_enrolled`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/integration/test_enrollment_gate.py`:

```python
from datetime import date, timedelta

from app.db.models import DutyAssignment, DutyType


def _make_assignment(session, *, soldier, node):
    dt = DutyType(name="probe_duty_type", hierarchy_node_id=node.id)
    session.add(dt)
    session.flush()
    a = DutyAssignment(
        duty_type_id=dt.id,
        soldier_id=soldier.id,
        start_date=date.today() + timedelta(days=3),
        end_date=date.today() + timedelta(days=4),
        status="published",
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def test_pending_soldier_cannot_create_swap(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="unit", name="probe_unit_swap")
    s = create_soldier(admin_session, personal_number="7600010", hierarchy_node_id=node.id)
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id, status="pending"))
    admin_session.commit()
    assignment = _make_assignment(admin_session, soldier=s, node=node)

    r = client.post(
        "/api/me/swaps",
        headers=auth_headers(s),
        json={"duty_assignment_id": str(assignment.id), "target_soldier_id": None, "reason": None},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "enrollment_pending"


def test_pending_soldier_cannot_submit_constraint(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="unit", name="probe_unit_constraint")
    s = create_soldier(admin_session, personal_number="7600011", hierarchy_node_id=node.id)
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id, status="pending"))
    admin_session.commit()

    r = client.post(
        "/api/me/constraints",
        headers=auth_headers(s),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "test",
        },
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "enrollment_pending"


def test_pending_soldier_cannot_submit_exemption_request(client: TestClient, admin_session: Session):
    from app.db.models import ExemptionType

    node = create_node(admin_session, level="unit", name="probe_unit_exemption")
    s = create_soldier(admin_session, personal_number="7600012", hierarchy_node_id=node.id)
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id, status="pending"))
    et = ExemptionType(name="probe_exemption_type", description=None)
    admin_session.add(et)
    admin_session.commit()

    r = client.post(
        "/api/me/exemption-requests",
        headers=auth_headers(s),
        json={
            "exemption_type_id": str(et.id),
            "start_date": (date.today() + timedelta(days=1)).isoformat(),
            "end_date": None,
            "reason": "test",
        },
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "enrollment_pending"


def test_pending_soldier_can_still_read_own_duties(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="unit", name="probe_unit_read")
    s = create_soldier(admin_session, personal_number="7600013", hierarchy_node_id=node.id)
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id, status="pending"))
    admin_session.commit()

    r = client.get("/api/me/constraints", headers=auth_headers(s))
    assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/integration/test_enrollment_gate.py -v`
Expected: the three new "cannot" tests FAIL (status 201 instead of 403); `test_pending_soldier_can_still_read_own_duties` already passes.

- [ ] **Step 3: Swap the dependency on the write endpoints**

In `backend/app/routes/swaps.py`, change the import on line 12:

```python
from app.auth.deps import require_enrolled, require_password_changed
```

Then change the `user` dependency from `require_password_changed` to `require_enrolled` on exactly these four functions (leave every other endpoint in the file — including `cancel`, `pending`, `approve_side`, `reject` — on `require_password_changed`):
- `create` (line ~288, `POST /me/swaps`)
- `take_free` (line ~311, `POST /swaps/take-free`)
- `submit_cover_offer` (line ~336, `POST /swaps/{swap_id}/offer`)
- `claim` (line ~358, `POST /swaps/{request_id}/claim`)

In `backend/app/routes/constraints.py`, change the import on line 12:

```python
from app.auth.deps import require_enrolled, require_password_changed
```

Change the `user` dependency on `submit` (line ~102, `POST /me/constraints`) from `require_password_changed` to `require_enrolled`. Leave `list_own` and `cancel` on `require_password_changed`.

In `backend/app/routes/exemption_requests.py`, change the import on line 16:

```python
from app.auth.deps import require_enrolled, require_password_changed
```

Change the `user` dependency on `create_exemption_request` (line ~111, `POST /me/exemption-requests`) from `require_password_changed` to `require_enrolled`. Leave every other endpoint in the file on `require_password_changed`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_enrollment_gate.py -v`
Expected: 8 passed

- [ ] **Step 5: Run the full backend test suite to check for regressions**

Run: `cd backend && pytest -q`
Expected: no new failures (existing swap/constraint/exemption-request tests that create as a fully-enrolled soldier — i.e. no `SoldierEnrollmentRequest` row — are unaffected, since `require_enrolled` only blocks when a pending/commander_approved row exists).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/swaps.py backend/app/routes/constraints.py backend/app/routes/exemption_requests.py backend/tests/integration/test_enrollment_gate.py
git commit -m "feat: block swap/constraint/exemption-request creation while enrollment is pending"
```

---

### Task 3: Enrollment approve/reject notifications

**Files:**
- Modify: `backend/app/services/enrollment.py`
- Test: `backend/app/services/tests/test_enrollment.py`

**Interfaces:**
- Consumes: `create_notification(session, *, soldier_id, type, title, reference_type=None, reference_id=None, actor_id=None) -> Notification | None` (`backend/app/services/notifications.py:256`); `NotificationType.enrollment_approved` / `NotificationType.enrollment_rejected` (`backend/app/db/models.py:844-845`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/app/services/tests/test_enrollment.py`:

```python
def test_approve_sends_notification_to_soldier(admin_session):
    from sqlalchemy import select
    from app.db.models import Notification, NotificationType

    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)

    from app.services.enrollment import approve_enrollment
    approve_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note=None)
    admin_session.commit()

    notif = admin_session.execute(
        select(Notification).where(
            Notification.soldier_id == soldier.id,
            Notification.type == NotificationType.enrollment_approved,
        )
    ).scalar_one_or_none()
    assert notif is not None


def test_reject_sends_notification_to_soldier(admin_session):
    from sqlalchemy import select
    from app.db.models import Notification, NotificationType

    holding = _make_holding(admin_session)
    node = create_node(admin_session, level="unit", name=f"unit_{_uid()}", parent=holding)
    decider = create_soldier(admin_session, personal_number=f"dec_{_uid()}", role="admin")
    soldier = create_soldier(admin_session, personal_number=f"s_{_uid()}", hierarchy_node_id=holding.id)
    req = _make_req(admin_session, soldier, node)

    from app.services.enrollment import reject_enrollment
    reject_enrollment(admin_session, request_id=req.id, decider_id=decider.id, decision_note="not eligible")
    admin_session.commit()

    notif = admin_session.execute(
        select(Notification).where(
            Notification.soldier_id == soldier.id,
            Notification.type == NotificationType.enrollment_rejected,
        )
    ).scalar_one_or_none()
    assert notif is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_enrollment.py -k notification -v`
Expected: FAIL — both `notif is not None` assertions fail (no notification created).

- [ ] **Step 3: Implement the notification calls**

In `backend/app/services/enrollment.py`, add the import and two calls:

```python
from app.db.models import ExemptionRequest, HierarchyNode, NotificationType, Soldier, SoldierEnrollmentRequest
from app.services.notifications import create_notification
```

In `approve_enrollment`, right after `write_audit(...)` and before `try_activate(session, req.id)`:

```python
    create_notification(
        session,
        soldier_id=req.soldier_id,
        type=NotificationType.enrollment_approved,
        title="בקשת הקליטה למסגרת אושרה",
        reference_type="soldier_enrollment_request",
        reference_id=req.id,
        actor_id=decider_id,
    )
```

In `reject_enrollment`, right after `write_audit(...)`:

```python
    create_notification(
        session,
        soldier_id=req.soldier_id,
        type=NotificationType.enrollment_rejected,
        title="בקשת הקליטה למסגרת נדחתה",
        reference_type="soldier_enrollment_request",
        reference_id=req.id,
        actor_id=decider_id,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_enrollment.py -v`
Expected: all passed (including the two new tests and the six pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/enrollment.py backend/app/services/tests/test_enrollment.py
git commit -m "feat: notify soldier when their enrollment request is approved or rejected"
```

---

### Task 4: Expose pending state on `/me` and gate the frontend forms

**Files:**
- Modify: `backend/app/routes/me.py`
- Modify: `frontend/src/api/auth.ts`
- Modify: `frontend/src/auth/AuthContext.tsx`
- Modify: `frontend/src/pages/MyRequestsPage.tsx`
- Modify: `frontend/src/pages/SwapsPage.tsx`
- Test: `backend/tests/integration/test_me_capabilities.py`

**Interfaces:**
- Produces: `MeResponse.enrollment_pending: bool` (backend); `Me.enrollment_pending: boolean` and `useAuth().enrollmentPending: boolean` (frontend) — read by any page that needs to disable soldier-initiated actions.

- [ ] **Step 1: Write the failing backend test**

Append to `backend/tests/integration/test_me_capabilities.py` (check the file's existing imports/fixtures first and match them — it already uses `client`/`admin_session`/`auth_headers`/`create_soldier`/`create_node`):

```python
def test_me_reports_enrollment_pending(client, admin_session):
    from app.db.models import SoldierEnrollmentRequest
    from tests.helpers import create_node, create_soldier, auth_headers

    node = create_node(admin_session, level="unit", name="me_enrollment_pending_unit")
    s = create_soldier(admin_session, personal_number="7600020", hierarchy_node_id=node.id)
    admin_session.add(SoldierEnrollmentRequest(soldier_id=s.id, requested_node_id=node.id, status="pending"))
    admin_session.commit()

    r = client.get("/api/me", headers=auth_headers(s))
    assert r.status_code == 200
    assert r.json()["enrollment_pending"] is True


def test_me_reports_not_pending_when_no_enrollment_request(client, admin_session):
    from tests.helpers import create_soldier, auth_headers

    s = create_soldier(admin_session, personal_number="7600021")
    r = client.get("/api/me", headers=auth_headers(s))
    assert r.status_code == 200
    assert r.json()["enrollment_pending"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_me_capabilities.py -k enrollment_pending -v`
Expected: FAIL with `KeyError: 'enrollment_pending'`

- [ ] **Step 3: Add the field to `/me`**

In `backend/app/routes/me.py`, add to `MeResponse`:

```python
    enrollment_pending: bool = False
```

Add the import at the top (alongside the existing `HierarchyNode, Soldier, TelegramLink` import):

```python
from app.db.models import HierarchyNode, Soldier, SoldierEnrollmentRequest, TelegramLink
```

In the `me()` handler, before the `return MeResponse(...)`:

```python
    enrollment_pending = session.execute(
        select(SoldierEnrollmentRequest.id).where(
            SoldierEnrollmentRequest.soldier_id == user.id,
            SoldierEnrollmentRequest.status.in_(("pending", "commander_approved")),
        ).limit(1)
    ).first() is not None
```

And add `enrollment_pending=enrollment_pending,` to the `MeResponse(...)` constructor call.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/integration/test_me_capabilities.py -v`
Expected: all passed

- [ ] **Step 5: Commit backend change**

```bash
git add backend/app/routes/me.py backend/tests/integration/test_me_capabilities.py
git commit -m "feat: expose enrollment_pending on /me"
```

- [ ] **Step 6: Wire the flag through the frontend**

In `frontend/src/api/auth.ts`, add to the `Me` interface (next to `telegram_required`):

```typescript
  enrollment_pending: boolean;
```

In `frontend/src/auth/AuthContext.tsx`, add `enrollmentPending` to the context value:

```typescript
  enrollmentPending: boolean;
```
(add to the `AuthContextValue` interface, and in the `value` object add `enrollmentPending: user?.enrollment_pending ?? false,` next to the existing `telegramRequired: user?.telegram_required ?? false,` line, including it in the `useMemo` dependency array alongside `user`)

- [ ] **Step 7: Gate the constraint/exemption submit forms**

In `frontend/src/pages/MyRequestsPage.tsx`, import `useAuth` and read `enrollmentPending`:

```typescript
import { useAuth } from "../auth/AuthContext";
```

Inside `MyRequestsPage()`, near the top of the function body:

```typescript
  const { enrollmentPending } = useAuth();
```

On both `<form onSubmit={onSubmit} ...>` (line ~164) and `<form onSubmit={onErSubmit} ...>` (line ~233), add a banner immediately before the form and disable its submit button:

```tsx
{enrollmentPending && (
  <div className="rounded border border-yellow-400 bg-yellow-50 dark:bg-yellow-900/20 px-3 py-2 text-sm text-yellow-800 dark:text-yellow-200 mb-2">
    בקשת הקליטה שלך למסגרת עדיין ממתינה לאישור — לא ניתן להגיש בקשות חדשות עד לאישור.
  </div>
)}
```

Find each form's submit `<button type="submit">` and add `disabled={enrollmentPending}`.

- [ ] **Step 8: Gate the swap creation form**

In `frontend/src/pages/SwapsPage.tsx`, `useAuth` is already imported (line 8). Inside `SwapsPage()` (line 223), `const { user } = useAuth();` (line 225) becomes:

```typescript
  const { user, enrollmentPending } = useAuth();
```

Before the `<form onSubmit={handleSubmit} ...>` (line ~193), add the same banner pattern as Step 7, and add `disabled={enrollmentPending}` to that form's submit button.

- [ ] **Step 9: Manually verify in the browser**

Start the dev stack (`.\dev.ps1` from repo root), log in as a soldier who has a `SoldierEnrollmentRequest` with `status="pending"` (create one via the DB or the registration flow), and confirm:
- `/my-requests` shows the banner and the submit buttons are disabled
- `/swaps` shows the banner and the create-swap submit button is disabled
- the soldier can still view their existing duties/profile normally

- [ ] **Step 10: Commit frontend change**

```bash
git add frontend/src/api/auth.ts frontend/src/auth/AuthContext.tsx frontend/src/pages/MyRequestsPage.tsx frontend/src/pages/SwapsPage.tsx
git commit -m "feat: show pending-enrollment banner and disable soldier-initiated forms until approved"
```
