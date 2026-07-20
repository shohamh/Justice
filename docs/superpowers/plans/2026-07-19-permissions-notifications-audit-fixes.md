# Permissions & Notifications Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every permission and notification gap found by the 2026-07-19 full-system audit (5 parallel subagent audits across all route domains), except the unscoped `config_export.py` finding which the user explicitly said to leave alone.

**Architecture:** Each task is a small, targeted patch to an existing route or service file — no new modules, no new DB migrations. Permission fixes either add a missing/duplicate scope check or correct a wrong `Action` constant. Notification fixes call the existing `app.services.notifications` helpers (`create_notification`, `notify_duty_managers_in_scope`, etc.) at points where a state change currently produces none, reusing existing `NotificationType` enum values wherever semantically reasonable instead of adding new ones (avoids a migration + frontend `_FRONTEND_PATHS` + Telegram bot label wiring for every fix). Bulk operations (shift bulk-delete/bulk-clear, Excel import) fetch affected soldier IDs in one query up front and loop `create_notification` over that in-memory list — never adding a query-per-row to an existing bulk SQL statement — so bulk performance is unaffected.

**Tech Stack:** FastAPI + SQLAlchemy (Python), pytest with a real Postgres testcontainer (`app_session`/`admin_session`/`client` fixtures in `backend/tests/conftest.py`).

## Global Constraints

- Excluded from this plan per explicit user instruction: the unscoped `config_export.py` finding (Gap 3 in the audit). Do not touch `backend/app/routes/config_export.py`.
- Do not add new `NotificationType` enum values, new Alembic migrations, or new frontend routes — reuse existing types (`exemption_approved`, `exemption_revoked`, `assignment_created`, `assignment_removed`, `gimelim_reserve_called_up`, `swap_accepted`, `swap_rejected`, `enrollment_approved`, `enrollment_rejected`, `algorithm_job_done`, `algorithm_job_failed`) so no frontend/bot changes are required.
- Self-approval guard applies to **every** role including admins — segregation of duties, not just a commander-scope quirk.
- Bulk-affecting fixes (shifts bulk endpoints, Excel import) must not turn an existing single bulk `DELETE`/`INSERT` into a per-row `SELECT`/notification storm beyond what is strictly necessary: fetch `(id, soldier_id)` pairs in one query before the bulk mutation, then loop notifications only over that already-fetched list.
- Every new/changed permission check must use the existing `app.auth.authz` primitives (`authorize`, `can`, `_node_in_scope`, `scope_root_ids`, `is_commander`, `is_duty_manager`) — no new ad hoc scope logic.
- Run `pytest -q` only for the specific test file(s) touched by each task (per project convention — full suite only at the end, and only if requested).

---

### Task 1: Self-approval guard for constraint & exemption-request approve/reject

**Files:**
- Modify: `backend/app/auth/authz.py`
- Modify: `backend/app/routes/constraints.py:234-277` (approve/reject)
- Modify: `backend/app/routes/exemption_requests.py:322-392` (approve-commander, approve-duty-manager, reject)
- Test: `backend/app/services/tests/test_authz_potential.py` (new test in same style) — actually add to a new focused file `backend/tests/unit/test_self_approval_guard.py` since this is a route-level behavior; use the `client` fixture.

**Interfaces:**
- Produces: `forbid_self_target(user: Soldier, target_soldier_id: uuid.UUID) -> None` in `app.auth.authz`, raising `HTTPException(403, "cannot_act_on_own_request")` when `user.id == target_soldier_id`.

- [ ] **Step 1: Add `forbid_self_target` to `app/auth/authz.py`**

Add after `authorize(...)` at the end of the file:

```python
def forbid_self_target(user: Soldier, target_soldier_id: uuid.UUID) -> None:
    """Raise 403 if `user` is attempting to decide (approve/reject) their own request.

    Approval-style actions rely on scope containment (`_node_in_scope`), which does
    not by itself exclude the requester deciding their own request — a commander's
    own hierarchy node is typically inside their own commanded subtree. This is an
    explicit segregation-of-duties check layered on top of `authorize()`, and it
    applies even to admins.
    """
    if user.id == target_soldier_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="cannot_act_on_own_request")
```

- [ ] **Step 2: Wire it into `constraints.py` approve/reject**

In `backend/app/routes/constraints.py`, change the import line:

```python
from app.auth.authz import Action, authorize, scope_root_ids, can_see_private, forbid_self_target
```

In `approve()` (currently at line 244-245):

```python
    s = _load_soldier(session, c.soldier_id)
    forbid_self_target(user, s.id)
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=_node_of(session, s))
```

Apply the identical two-line change (add `forbid_self_target(user, s.id)` right before the existing `authorize(...)` call) in `reject()` (currently line 267-268).

- [ ] **Step 3: Wire it into `exemption_requests.py` approve-commander / approve-duty-manager / reject**

In `backend/app/routes/exemption_requests.py`, change the import line:

```python
from app.auth.authz import (
    Action, authorize, can_see_private, forbid_self_target, is_commander, is_duty_manager, scope_root_ids,
)
```

In `approve_exemption_request_commander_step` (line 328-333), insert the guard right after `target_soldier` is loaded and before `authorize(...)`:

```python
    target_soldier = session.get(Soldier, req.soldier_id)
    target_node = session.get(HierarchyNode, target_soldier.hierarchy_node_id) if target_soldier else None
    forbid_self_target(user, req.soldier_id)
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=target_node)
```

In `approve_exemption_request_duty_manager_step` (line 349-364), insert right after `target_soldier`/`target_node` are computed, before the `if user.role != "admin":` block:

```python
    target_soldier = session.get(Soldier, req.soldier_id)
    target_node = session.get(HierarchyNode, target_soldier.hierarchy_node_id) if target_soldier else None
    forbid_self_target(user, req.soldier_id)

    from app.auth.authz import is_duty_manager, scope_root_ids
    if user.role != "admin":
```

(Keep the rest of that function unchanged — the existing `if user.role != "admin":` block and its body stay exactly as they are.)

In `reject_exemption_request` (line 381-386), same pattern:

```python
    target_soldier = session.get(Soldier, req.soldier_id)
    target_node = session.get(HierarchyNode, target_soldier.hierarchy_node_id) if target_soldier else None
    forbid_self_target(user, req.soldier_id)
    authorize(session, user, Action.CONSTRAINT_APPROVE, target_node=target_node)
```

- [ ] **Step 4: Write failing tests**

Create `backend/tests/unit/test_self_approval_guard.py`:

```python
"""Regression tests: a commander/DM must not be able to approve or reject
their own submitted constraint or exemption request, even though their own
hierarchy node normally falls inside their own commanded/managed scope."""
import uuid
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.duty


def _make_commander_with_own_request(app_session, admin_session):
    """Create a hierarchy node commanded by soldier X, put X in that node,
    and have X submit a constraint against themselves. Returns (soldier, node, constraint)."""
    from app.db.models import HierarchyNode, PersonalConstraint, Soldier
    from app.auth.password import hash_password

    node = HierarchyNode(name="Test Unit", level="group", path_ids=[])
    admin_session.add(node)
    admin_session.flush()
    node.path_ids = [node.id]
    admin_session.flush()

    soldier = Soldier(
        personal_number="99001", full_name="Self Approver",
        password_hash=hash_password("x"), role="soldier",
        hierarchy_node_id=node.id,
    )
    admin_session.add(soldier)
    admin_session.flush()

    node.commander_id = soldier.id
    admin_session.commit()

    c = PersonalConstraint(
        soldier_id=soldier.id,
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=2),
        reason="test",
        status="pending",
    )
    admin_session.add(c)
    admin_session.commit()
    return soldier, node, c


def test_commander_cannot_approve_own_constraint(client, admin_session, app_session):
    soldier, node, c = _make_commander_with_own_request(app_session, admin_session)
    from tests.helpers import login  # existing test helper module, adjust import if named differently
    token = login(client, soldier.personal_number, "x")
    resp = client.post(
        f"/constraints/{c.id}/approve",
        json={"decision_note": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "cannot_act_on_own_request"
```

Check `backend/tests` for the actual login/auth-header helper used by other API tests (e.g. grep `def login` or look at how `test_constraints_api.py` authenticates) and adjust the helper import/usage to match — do not invent a helper that doesn't exist.

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest backend/tests/unit/test_self_approval_guard.py -v`
Expected: FAIL (403 not yet raised, or import error before Step 1-3 land — reorder so this runs after Steps 1-3 are applied, then expect FAIL only because the guard doesn't exist yet if you're doing strict TDD; otherwise apply Steps 1-3 first, then use this test purely as a regression check).

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest backend/tests/unit/test_self_approval_guard.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/auth/authz.py backend/app/routes/constraints.py backend/app/routes/exemption_requests.py backend/tests/unit/test_self_approval_guard.py
git commit -m "fix: block self-approval of own constraint/exemption requests"
```

---

### Task 2: Exemption grant — block commander-exemption bypass, add missing notifications

**Files:**
- Modify: `backend/app/services/exemptions.py`
- Test: `backend/tests/unit/test_exemptions_service.py`

**Interfaces:**
- Consumes: `create_notification`, `notify_duty_managers_in_scope` from `app.services.notifications` (same signatures already used by `revoke_exemption` in this file).
- Produces: `grant_exemption` now raises `ExemptionError("commander_exemption_requires_dedicated_endpoint")` if the referenced `ExemptionType.is_commander_exemption` is `True`; both `grant_exemption` and `grant_commander_exemption` now notify the affected soldier (`NotificationType.exemption_approved`) and duty managers in scope.

- [ ] **Step 1: Add the type-mismatch guard and notifications to `grant_exemption`**

In `backend/app/services/exemptions.py`, replace the body of `grant_exemption`:

```python
def grant_exemption(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    exemption_type_id: uuid.UUID,
    start_date: date,
    end_date: date | None,
    reason: str | None,
    actor_id: uuid.UUID | None = None,
) -> SoldierExemption:
    from app.db.models import NotificationType
    from app.services.notifications import create_notification, notify_duty_managers_in_scope

    if session.get(Soldier, soldier_id) is None:
        raise ExemptionError("soldier_not_found")
    et = session.get(ExemptionType, exemption_type_id)
    if et is None:
        raise ExemptionError("exemption_type_not_found")
    if et.is_commander_exemption:
        raise ExemptionError("commander_exemption_requires_dedicated_endpoint")
    if end_date is not None and end_date < start_date:
        raise ExemptionError("bad_date_range")
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
        action="exemption.grant",
        entity_type="soldier_exemption",
        entity_id=ex.id,
        after={
            "soldier_id": str(soldier_id),
            "exemption_type_id": str(exemption_type_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat() if end_date else None,
        },
    )
    create_notification(
        session, soldier_id=soldier_id,
        type=NotificationType.exemption_approved,
        title="ניתן לך פטור",
        body=reason,
        reference_type="soldier_exemption", reference_id=ex.id,
        actor_id=actor_id,
    )
    notify_duty_managers_in_scope(
        session, soldier_id=soldier_id,
        type=NotificationType.exemption_approved,
        title="ניתן פטור",
        body=reason,
        reference_type="soldier_exemption", reference_id=ex.id,
        actor_id=actor_id,
    )
    return ex
```

- [ ] **Step 2: Add the same notifications to `grant_commander_exemption`**

Append, right before the final `return ex` in `grant_commander_exemption`:

```python
    from app.db.models import NotificationType
    from app.services.notifications import create_notification, notify_duty_managers_in_scope

    create_notification(
        session, soldier_id=soldier_id,
        type=NotificationType.exemption_approved,
        title="ניתן לך פטור מפקדתי",
        body=reason,
        reference_type="soldier_exemption", reference_id=ex.id,
        actor_id=actor_id,
    )
    notify_duty_managers_in_scope(
        session, soldier_id=soldier_id,
        type=NotificationType.exemption_approved,
        title="ניתן פטור מפקדתי",
        body=reason,
        reference_type="soldier_exemption", reference_id=ex.id,
        actor_id=actor_id,
    )
    return ex
```

- [ ] **Step 3: Write failing tests**

Add to `backend/tests/unit/test_exemptions_service.py` (follow the existing fixture style already in that file — read the top of the file for the `admin_session` soldier/exemption-type setup helpers already defined there and reuse them):

```python
def test_grant_exemption_rejects_commander_exemption_type(admin_session):
    """A commander-exemption type must only be grantable via grant_commander_exemption,
    not the generic grant_exemption — otherwise the rasan+/level rank gate on commander
    exemptions is bypassable."""
    from app.services.exemptions import ExemptionError, grant_exemption
    # reuse this file's existing soldier/exemption-type fixtures; create an
    # ExemptionType with is_commander_exemption=True as `commander_et`
    with pytest.raises(ExemptionError, match="commander_exemption_requires_dedicated_endpoint"):
        grant_exemption(
            admin_session,
            soldier_id=soldier.id,
            exemption_type_id=commander_et.id,
            start_date=date.today(),
            end_date=None,
            reason="test",
        )


def test_grant_exemption_notifies_soldier(admin_session):
    from app.db.models import EmailOutbox, Notification, NotificationType
    from app.services.exemptions import grant_exemption
    ex = grant_exemption(
        admin_session,
        soldier_id=soldier.id,
        exemption_type_id=regular_et.id,
        start_date=date.today(),
        end_date=None,
        reason="test",
    )
    admin_session.flush()
    notif = admin_session.query(Notification).filter_by(
        soldier_id=soldier.id, type=NotificationType.exemption_approved,
    ).one_or_none()
    assert notif is not None
```

Adapt variable names (`soldier`, `commander_et`, `regular_et`) to whatever fixtures/helpers already exist at the top of `test_exemptions_service.py` — read that file first and reuse its existing setup instead of duplicating it.

- [ ] **Step 4: Run tests to verify they fail, then implement Steps 1-2, then re-run**

Run: `pytest backend/tests/unit/test_exemptions_service.py -v`
Expected first: FAIL. After Steps 1-2: PASS.

- [ ] **Step 5: Run full file to check no regressions**

Run: `pytest backend/tests/unit/test_exemptions_service.py backend/app/services/tests/test_exemptions.py -v`
Expected: PASS (note: `grant_exemption` calls in `backend/app/services/tests/test_exemptions.py` must not be passing a commander-exemption type — check that file too and fix any test row that now legitimately needs `grant_commander_exemption` instead).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/exemptions.py backend/tests/unit/test_exemptions_service.py
git commit -m "fix: block commander-exemption grants via generic endpoint, notify on direct exemption grants"
```

---

### Task 3: Exemption escalation — notify duty managers on commander-approve step

**Files:**
- Modify: `backend/app/services/exemption_requests.py`
- Test: `backend/app/services/tests/test_exemption_requests.py`

**Interfaces:**
- Consumes: `notify_duty_managers_of_request` (already imported/used elsewhere in this file for `submit_commander_escalation`).
- Produces: `approve_commander_step` now sends `NotificationType.exemption_request_pending` to duty managers in scope, matching what `submit_commander_escalation` already does when a request lands in `pending_duty_manager` status.

- [ ] **Step 1: Add the missing notification**

In `backend/app/services/exemption_requests.py`, replace `approve_commander_step`:

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

    from app.services.notifications import notify_duty_managers_of_request
    notify_duty_managers_of_request(
        session,
        soldier_id=req.soldier_id,
        type=NotificationType.exemption_request_pending,
        title="בקשת פטור ממתינה לאישור (אושרה ע\"י מפקד)",
        body=req.reason,
        reference_type="exemption_request",
        reference_id=req.id,
        actor_id=approved_by,
    )
    return req
```

- [ ] **Step 2: Write failing test**

Add to `backend/app/services/tests/test_exemption_requests.py` (this file already has fixtures for soldier/DM-scope setup used by `test_escalation_request_only_does_not_grant_exemption` — reuse them):

```python
def test_approve_commander_step_notifies_duty_managers(app_session):
    """When a commander approves their step, duty managers in scope over the
    soldier's node must get a pending-approval notification — mirroring what
    submit_commander_escalation already does when landing directly in
    pending_duty_manager."""
    from app.db.models import Notification, NotificationType
    from app.services.exemption_requests import approve_commander_step, submit_request
    # ... reuse this file's existing soldier/dm/exemption_type fixtures to create
    # a pending_commander request via submit_request, and a duty manager scoped
    # over the soldier's node ...
    req = submit_request(app_session, soldier_id=soldier.id, exemption_type_id=et.id,
                          start_date=date.today(), end_date=None, reason="test")
    app_session.commit()
    approve_commander_step(app_session, req.id, approved_by=commander.id)
    app_session.commit()
    notif = app_session.query(Notification).filter_by(
        soldier_id=dm.id, type=NotificationType.exemption_request_pending,
    ).one_or_none()
    assert notif is not None
```

- [ ] **Step 3: Run to verify FAIL then PASS**

Run: `pytest backend/app/services/tests/test_exemption_requests.py -v`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/exemption_requests.py backend/app/services/tests/test_exemption_requests.py
git commit -m "fix: notify duty managers when commander approves their exemption-request step"
```

---

### Task 4: Fix wrong `Action` on shift-template endpoints

**Files:**
- Modify: `backend/app/routes/shift_templates.py`
- Test: `backend/tests/unit/test_shift_templates_permissions.py` (new)

**Interfaces:**
- Produces: all 6 `shift_templates.py` endpoints (`list_templates`, `create_template`, `update_template`, `delete_template`, `preview`, `generate`) now authorize with `Action.SHIFT_MANAGE` instead of `Action.ASSIGNMENT_MANAGE`, matching the sibling `shifts.py` file which already uses `SHIFT_MANAGE` (a DM-global action) for the same `target_node=None` pattern.

- [ ] **Step 1: Replace the Action constant everywhere in the file**

In `backend/app/routes/shift_templates.py`, every occurrence of:

```python
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=None)
```

becomes:

```python
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
```

This applies at the 6 call sites: `list_templates` (line 105), `create_template` (115), `update_template` (141), `delete_template` (171), `preview` (184), `generate` (197).

- [ ] **Step 2: Write failing test**

Create `backend/tests/unit/test_shift_templates_permissions.py`:

```python
"""A duty manager (non-admin) must be able to manage shift templates — this
previously failed because the endpoints gated on Action.ASSIGNMENT_MANAGE
(scope-restricted, non-DM-global) with target_node=None, which `can()` never
grants to a non-admin duty manager. SHIFT_MANAGE is DM-global and is the
Action the sibling shifts.py endpoints correctly use for the same pattern."""
import pytest

pytestmark = pytest.mark.duty


def test_duty_manager_can_list_shift_templates(client, admin_session):
    # ... create a duty_manager-role soldier via existing test helpers (see
    # test_shifts_routes.py or test_duty_config_api.py for the DM-login pattern
    # used elsewhere in this test suite) ...
    resp = client.get("/shift-templates", headers={"Authorization": f"Bearer {dm_token}"})
    assert resp.status_code == 200
```

Check how other duty-manager-authenticated route tests set up a DM soldier + `DutyManagerScope` row + login (e.g. `backend/tests/unit/test_shifts_routes.py` or `test_duty_config_api.py`) and copy that exact setup pattern rather than inventing a new one.

- [ ] **Step 3: Run to verify FAIL (403) then PASS (200) after Step 1**

Run: `pytest backend/tests/unit/test_shift_templates_permissions.py -v`

- [ ] **Step 4: Run existing shift-template tests for regressions**

Run: `pytest -k shift_template -q`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/shift_templates.py backend/tests/unit/test_shift_templates_permissions.py
git commit -m "fix: shift-template endpoints use SHIFT_MANAGE instead of ASSIGNMENT_MANAGE so duty managers can access them"
```

---

### Task 5: Reserves — authorize the covering reserve's scope in `dismiss_and_reallocate`

**Files:**
- Modify: `backend/app/routes/reserves.py`
- Test: `backend/tests/unit/test_reserves.py` (or wherever `test_reserves` area tests live — check `_AREA_MARKERS` mapping: `"test_reserves": "duty"`)

**Interfaces:**
- Produces: `dismiss_and_reallocate` now also calls `authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=_node_of_assignment(session, reserve_a))` for the covering reserve assignment, in addition to the existing check on `primary_a`.

- [ ] **Step 1: Add the second authorize call**

In `backend/app/routes/reserves.py`, in `dismiss_and_reallocate` (around line 293-300), change:

```python
    primary_a = _load_assignment(session, body.primary_assignment_id)
    if primary_a.duty_shift_id != shift_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_in_shift")
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=_node_of_assignment(session, primary_a))

    reserve_a = _load_assignment(session, body.covering_reserve_assignment_id)
    if reserve_a.duty_shift_id != shift_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="reserve_not_in_shift")
```

to:

```python
    primary_a = _load_assignment(session, body.primary_assignment_id)
    if primary_a.duty_shift_id != shift_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_in_shift")
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=_node_of_assignment(session, primary_a))

    reserve_a = _load_assignment(session, body.covering_reserve_assignment_id)
    if reserve_a.duty_shift_id != shift_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="reserve_not_in_shift")
    authorize(session, user, Action.ASSIGNMENT_MANAGE, target_node=_node_of_assignment(session, reserve_a))
```

- [ ] **Step 2: Write failing test**

Add to the reserves test file (find the exact path with `Glob backend/tests/unit/test_reserves*.py` or `backend/app/services/tests/test_reserves*` first):

```python
def test_dismiss_and_reallocate_rejects_out_of_scope_covering_reserve(client, admin_session):
    """A duty manager scoped to unit A must not be able to pull in a covering
    reserve from unit B via /shifts/{id}/dismissals — only the primary's node
    was checked before this fix."""
    # ... set up two DutyManagerScope-disjoint units, a primary assignment in
    # unit A (in scope) and a reserve assignment in unit B (out of scope),
    # log in as the unit-A-scoped DM, and call dismiss_and_reallocate ...
    resp = client.post(
        f"/shifts/{shift_id}/dismissals",
        json={
            "primary_assignment_id": str(primary_a.id),
            "covering_reserve_assignment_id": str(reserve_b_out_of_scope.id),
            "from_date": str(from_date), "to_date": str(to_date),
        },
        headers={"Authorization": f"Bearer {dm_token}"},
    )
    assert resp.status_code == 403
```

- [ ] **Step 3: Run to verify FAIL then PASS**

Run: `pytest -k dismiss_and_reallocate -q`

- [ ] **Step 4: Run full reserves test file for regressions**

Run: `pytest -k test_reserves -q`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/reserves.py
git commit -m "fix: authorize covering reserve's own scope in dismiss_and_reallocate, not just the primary's"
```

---

### Task 6: Reserves — add missing notifications on call-up and dismissal

**Files:**
- Modify: `backend/app/services/reserves.py`
- Test: same reserves test file as Task 5

**Interfaces:**
- Consumes: `create_notification` from `app.services.notifications`; `NotificationType.gimelim_reserve_called_up` and `NotificationType.assignment_removed` (reused, not new).
- Produces: `call_up_reserve` and `dismiss_primary`/`dismiss_reserve` now notify the affected soldier. `reallocate_orphaned_primaries` (pure relink, no day-to-day change for the primary) is deliberately left un-notified — see Global Constraints on avoiding notification noise for non-actionable relinks.

- [ ] **Step 1: Add imports**

In `backend/app/services/reserves.py`, change:

```python
from app.db.models import DutyAssignment, DutyDismissal, DutyReserveLink
```

to:

```python
from app.db.models import DutyAssignment, DutyDismissal, DutyReserveLink, NotificationType, Soldier
from app.services.notifications import create_notification
```

- [ ] **Step 2: Notify on `call_up_reserve`**

Insert right after the existing `write_audit(...)` call in `call_up_reserve`, before `return assignment`:

```python
    soldier = session.get(Soldier, assignment.soldier_id)
    create_notification(
        session, soldier_id=assignment.soldier_id,
        type=NotificationType.gimelim_reserve_called_up,
        title="הוקפצת לכיסוי תורנות",
        body=f"הוקפצת לתורנות בתאריכים {from_date} – {to_date}",
        reference_type="duty_assignment", reference_id=assignment.id,
        actor_id=actor_id,
    )
    return assignment
```

(Remove the now-unused `soldier` variable if you don't need it in the message — keeping it here only because the title is static; simplify by dropping the `session.get(Soldier, ...)` line since the title doesn't reference the soldier's name.)

- [ ] **Step 3: Notify on `dismiss_primary`**

Insert right after the existing `write_audit(...)` call in `dismiss_primary`, before `return dismissal`:

```python
    create_notification(
        session, soldier_id=assignment.soldier_id,
        type=NotificationType.assignment_removed,
        title="שוחררת מתורנות",
        body=f"שוחררת מתורנות בתאריכים {from_date} – {to_date}" + (f" — {reason}" if reason else ""),
        reference_type="duty_assignment", reference_id=assignment.id,
        actor_id=actor_id,
    )
    return dismissal
```

- [ ] **Step 4: Notify on `dismiss_reserve`**

Insert right after the existing `write_audit(...)` call in `dismiss_reserve`, before the `if covering_reserve_id is not None:` block:

```python
    create_notification(
        session, soldier_id=assignment.soldier_id,
        type=NotificationType.assignment_removed,
        title="שוחררת מכוננות רזרבה",
        body=f"שוחררת מכוננות בתאריכים {from_date} – {to_date}" + (f" — {reason}" if reason else ""),
        reference_type="duty_assignment", reference_id=assignment.id,
        actor_id=actor_id,
    )
```

- [ ] **Step 5: Write failing tests**

Add to the reserves test file:

```python
def test_call_up_reserve_notifies_soldier(app_session):
    from app.db.models import Notification, NotificationType
    from app.services.reserves import call_up_reserve
    # ... build a reserve DutyAssignment as in existing tests in this file ...
    call_up_reserve(app_session, assignment=reserve_assignment, from_date=d1, to_date=d2)
    app_session.flush()
    notif = app_session.query(Notification).filter_by(
        soldier_id=reserve_assignment.soldier_id, type=NotificationType.gimelim_reserve_called_up,
    ).one_or_none()
    assert notif is not None


def test_dismiss_primary_notifies_soldier(app_session):
    from app.db.models import Notification, NotificationType
    from app.services.reserves import dismiss_primary
    dismiss_primary(app_session, assignment=primary_assignment, from_date=d1, to_date=d2, reason="test")
    app_session.flush()
    notif = app_session.query(Notification).filter_by(
        soldier_id=primary_assignment.soldier_id, type=NotificationType.assignment_removed,
    ).one_or_none()
    assert notif is not None
```

- [ ] **Step 6: Run to verify FAIL then PASS**

Run: `pytest -k "test_reserves" -q`

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/reserves.py
git commit -m "feat: notify affected soldier on reserve call-up and primary/reserve dismissal"
```

---

### Task 7: Assignments — notify on day-override substitution changes

**Files:**
- Modify: `backend/app/services/assignments.py`
- Test: `backend/app/services/tests/test_assignments.py`

**Interfaces:**
- Produces: new private helper `_notify_day_override_change(session, *, assignment, date, old_effective_id, new_effective_id, actor_id)` in `assignments.py`; called from both `set_day_override` and `clear_day_override`.

- [ ] **Step 1: Add the helper**

In `backend/app/services/assignments.py`, add right after `_day_busy`:

```python
def _notify_day_override_change(
    session: Session,
    *,
    assignment: DutyAssignment,
    date: date,
    old_effective_id: uuid.UUID | None,
    new_effective_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
) -> None:
    if old_effective_id == new_effective_id:
        return
    date_str = date.isoformat()
    if old_effective_id is not None:
        create_notification(
            session, soldier_id=old_effective_id,
            type=NotificationType.assignment_removed,
            title=f"בוטל שיבוץ יומי עבורך בתאריך {date_str}",
            reference_type="duty_assignment", reference_id=assignment.id,
            actor_id=actor_id,
        )
    if new_effective_id is not None:
        create_notification(
            session, soldier_id=new_effective_id,
            type=NotificationType.assignment_created,
            title=f"שובצת ליום {date_str} כתחליף",
            reference_type="duty_assignment", reference_id=assignment.id,
            actor_id=actor_id,
        )
```

- [ ] **Step 2: Call it from `set_day_override`**

In `set_day_override`, change the `if existing is not None:` branch from:

```python
    if existing is not None:
        before = {
            "effective_soldier_id": str(existing.effective_soldier_id)
            if existing.effective_soldier_id
            else None,
            "reason": existing.reason,
        }
        existing.effective_soldier_id = effective_soldier_id
        existing.reason = reason
        write_audit(
            session,
            actor_id=actor_id,
            action="assignment.override",
            entity_type="duty_day_override",
            entity_id=existing.id,
            before=before,
            after=after,
        )
        return existing
```

to:

```python
    if existing is not None:
        old_effective_id = existing.effective_soldier_id
        before = {
            "effective_soldier_id": str(old_effective_id) if old_effective_id else None,
            "reason": existing.reason,
        }
        existing.effective_soldier_id = effective_soldier_id
        existing.reason = reason
        write_audit(
            session,
            actor_id=actor_id,
            action="assignment.override",
            entity_type="duty_day_override",
            entity_id=existing.id,
            before=before,
            after=after,
        )
        _notify_day_override_change(
            session, assignment=assignment, date=date,
            old_effective_id=old_effective_id, new_effective_id=effective_soldier_id,
            actor_id=actor_id,
        )
        return existing
```

And right before the final `return ov` (the new-override path), insert:

```python
    _notify_day_override_change(
        session, assignment=assignment, date=date,
        old_effective_id=None, new_effective_id=effective_soldier_id,
        actor_id=actor_id,
    )
    return ov
```

- [ ] **Step 3: Call it from `clear_day_override`**

Change:

```python
    write_audit(
        session,
        actor_id=actor_id,
        action="assignment.override_clear",
        entity_type="duty_day_override",
        entity_id=ov.id,
        before={
            "effective_soldier_id": str(ov.effective_soldier_id)
            if ov.effective_soldier_id
            else None
        },
    )
    session.delete(ov)
```

to:

```python
    write_audit(
        session,
        actor_id=actor_id,
        action="assignment.override_clear",
        entity_type="duty_day_override",
        entity_id=ov.id,
        before={
            "effective_soldier_id": str(ov.effective_soldier_id)
            if ov.effective_soldier_id
            else None
        },
    )
    _notify_day_override_change(
        session, assignment=assignment, date=date,
        old_effective_id=ov.effective_soldier_id, new_effective_id=None,
        actor_id=actor_id,
    )
    session.delete(ov)
```

- [ ] **Step 4: Write failing test**

Add to `backend/app/services/tests/test_assignments.py`:

```python
def test_set_day_override_notifies_both_sides(app_session):
    from app.db.models import Notification, NotificationType
    from app.services.assignments import set_day_override
    # ... build `assignment` (base soldier A) and `replacement` soldier B as in
    # existing tests in this file for set_day_override ...
    ov = set_day_override(
        app_session, assignment=assignment, date=assignment.start_date,
        effective_soldier_id=replacement.id, reason="replacement",
    )
    app_session.flush()
    removed = app_session.query(Notification).filter_by(
        soldier_id=assignment.soldier_id, type=NotificationType.assignment_removed,
    ).one_or_none()
    created = app_session.query(Notification).filter_by(
        soldier_id=replacement.id, type=NotificationType.assignment_created,
    ).one_or_none()
    assert created is not None
```

Note: the base assignee (`assignment.soldier_id`) is only notified `assignment_removed` when there was a *previous* effective override to replace (per `_notify_day_override_change`'s `old_effective_id`/`new_effective_id` comparison) — for a brand-new override there's no "old" to notify about removing, only the new replacement soldier gets `assignment_created`. Adjust the test assertion accordingly (don't assert `removed is not None` on a first-time override).

- [ ] **Step 5: Run to verify FAIL then PASS**

Run: `pytest backend/app/services/tests/test_assignments.py -v`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/assignments.py backend/app/services/tests/test_assignments.py
git commit -m "feat: notify affected soldiers when a duty-day override substitution changes"
```

---

### Task 8: Shifts — audit + notify on bulk/single assignment removal endpoints

**Files:**
- Modify: `backend/app/routes/shifts.py`
- Test: `backend/tests/unit/test_shifts_routes.py` (check actual filename first with Glob)

**Interfaces:**
- Produces: `remove_shift_assignment` and `clear_shift_assignments` now `write_audit` + `create_notification(type=NotificationType.assignment_removed)` per affected assignment (both operate on a single shift's assignments — bounded, small `n`). `bulk_delete_shifts` and `bulk_clear_assignments` fetch `(id, soldier_id)` pairs in one query before the bulk `DELETE`, write **one** summary `write_audit` row per call (not one per assignment — see Global Constraints), and loop `create_notification` over the already-fetched soldier ids after the delete commits.

- [ ] **Step 1: Add a bulk-safe id+soldier_id fetch helper**

In `backend/app/routes/shifts.py`, add right after `_assignment_ids_for_shifts`:

```python
def _assignment_soldier_pairs_for_shifts(
    session: Session, shift_ids: list[uuid.UUID]
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    if not shift_ids:
        return []
    return list(session.execute(
        select(DutyAssignment.id, DutyAssignment.soldier_id).where(
            DutyAssignment.duty_shift_id.in_(shift_ids)
        )
    ).all())
```

- [ ] **Step 2: Wire notifications + a summary audit row into `bulk_delete_shifts`**

Add the needed imports at the top of the file:

```python
from app.audit.writer import write_audit
from app.db.models import NotificationType
from app.services.notifications import create_notification
```

Change `bulk_delete_shifts`:

```python
@router.delete("/bulk-delete", status_code=status.HTTP_200_OK)
def bulk_delete_shifts(
    date_from: date,
    date_to: date,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)

    shifts = _shifts_in_range(session, date_from, date_to)
    shift_ids = [s.id for s in shifts]
    pairs = _assignment_soldier_pairs_for_shifts(session, shift_ids)
    assignment_ids = [p[0] for p in pairs]

    if assignment_ids:
        session.execute(sa_delete(SwapRequest).where(SwapRequest.duty_assignment_id.in_(assignment_ids)))
        session.execute(sa_delete(DutyDismissal).where(DutyDismissal.duty_assignment_id.in_(assignment_ids)))
        session.execute(sa_delete(DutyReserveLink).where(
            DutyReserveLink.primary_assignment_id.in_(assignment_ids) |
            DutyReserveLink.reserve_assignment_id.in_(assignment_ids)
        ))
        session.execute(sa_delete(DutyAssignment).where(DutyAssignment.id.in_(assignment_ids)))

    if shift_ids:
        session.execute(sa_delete(DutyShift).where(DutyShift.id.in_(shift_ids)))

    write_audit(
        session, actor_id=user.id, action="shift.bulk_delete", entity_type="duty_shift",
        after={"date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
               "deleted_shifts": len(shift_ids), "deleted_assignments": len(assignment_ids)},
    )
    session.commit()

    for assignment_id, soldier_id in pairs:
        create_notification(
            session, soldier_id=soldier_id,
            type=NotificationType.assignment_removed,
            title="שיבוץ בוטל (מחיקת משמרות גורפת)",
            reference_type="duty_assignment", reference_id=assignment_id,
            actor_id=user.id,
        )
    session.commit()

    return {"deleted_shifts": len(shift_ids), "deleted_assignments": len(assignment_ids)}
```

- [ ] **Step 3: Same pattern for `bulk_clear_assignments`**

```python
@router.delete("/bulk-clear-assignments", status_code=status.HTTP_200_OK)
def bulk_clear_assignments(
    date_from: date,
    date_to: date,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, int]:
    """Delete all assignments (and their cascading data) for shifts in range, keeping the shifts."""
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)

    shift_ids = [s.id for s in _shifts_in_range(session, date_from, date_to)]
    pairs = _assignment_soldier_pairs_for_shifts(session, shift_ids)
    assignment_ids = [p[0] for p in pairs]

    if assignment_ids:
        session.execute(sa_delete(SwapRequest).where(SwapRequest.duty_assignment_id.in_(assignment_ids)))
        session.execute(sa_delete(DutyDismissal).where(DutyDismissal.duty_assignment_id.in_(assignment_ids)))
        session.execute(sa_delete(DutyReserveLink).where(
            DutyReserveLink.primary_assignment_id.in_(assignment_ids) |
            DutyReserveLink.reserve_assignment_id.in_(assignment_ids)
        ))
        session.execute(sa_delete(DutyAssignment).where(DutyAssignment.id.in_(assignment_ids)))

    write_audit(
        session, actor_id=user.id, action="shift.bulk_clear_assignments", entity_type="duty_shift",
        after={"date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
               "cleared_assignments": len(assignment_ids)},
    )
    session.commit()

    for assignment_id, soldier_id in pairs:
        create_notification(
            session, soldier_id=soldier_id,
            type=NotificationType.assignment_removed,
            title="שיבוץ בוטל (ניקוי משמרות גורף)",
            reference_type="duty_assignment", reference_id=assignment_id,
            actor_id=user.id,
        )
    session.commit()

    return {"cleared_assignments": len(assignment_ids)}
```

- [ ] **Step 4: Audit + notify on `remove_shift_assignment` and `clear_shift_assignments`**

```python
@router.delete("/{shift_id}/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def remove_shift_assignment(
    shift_id: uuid.UUID,
    assignment_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    """Cancel a single assignment that belongs to this shift."""
    _load(session, shift_id)
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    a = session.get(DutyAssignment, assignment_id)
    if a is None or a.duty_shift_id != shift_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    if a.status != "cancelled":
        if a.is_reserve:
            session.execute(
                sa_delete(DutyReserveLink).where(DutyReserveLink.reserve_assignment_id == assignment_id)
            )
        else:
            session.execute(
                sa_delete(DutyReserveLink).where(DutyReserveLink.primary_assignment_id == assignment_id)
            )
        before_status = a.status
        a.status = "cancelled"
        write_audit(
            session, actor_id=user.id, action="assignment.cancel", entity_type="duty_assignment",
            entity_id=a.id, before={"status": before_status}, after={"status": "cancelled"},
            context={"source": "shift_assignment_remove"},
        )
        create_notification(
            session, soldier_id=a.soldier_id,
            type=NotificationType.assignment_removed,
            title="שיבוץ בוטל",
            reference_type="duty_assignment", reference_id=a.id,
            actor_id=user.id,
        )
        session.commit()


@router.delete("/{shift_id}/assignments", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def clear_shift_assignments(
    shift_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> None:
    """Remove all non-cancelled assignments linked to this shift."""
    _load(session, shift_id)
    authorize(session, user, Action.SHIFT_MANAGE, target_node=None)
    rows = session.execute(
        select(DutyAssignment).where(
            DutyAssignment.duty_shift_id == shift_id,
            DutyAssignment.status != "cancelled",
        )
    ).scalars().all()
    for a in rows:
        a.status = "cancelled"
        write_audit(
            session, actor_id=user.id, action="assignment.cancel", entity_type="duty_assignment",
            entity_id=a.id, before={"status": "published"}, after={"status": "cancelled"},
            context={"source": "shift_assignments_clear"},
        )
        create_notification(
            session, soldier_id=a.soldier_id,
            type=NotificationType.assignment_removed,
            title="שיבוץ בוטל",
            reference_type="duty_assignment", reference_id=a.id,
            actor_id=user.id,
        )
    session.commit()
```

- [ ] **Step 5: Write failing tests**

Find the existing test file covering these routes (Glob `backend/tests/**/test_shifts*.py`) and add:

```python
def test_remove_shift_assignment_notifies_soldier(client, admin_session):
    from app.db.models import Notification, NotificationType
    # ... reuse this file's existing shift+assignment setup helpers ...
    resp = client.delete(f"/shifts/{shift.id}/assignments/{assignment.id}", headers=admin_headers)
    assert resp.status_code == 204
    notif = admin_session.query(Notification).filter_by(
        soldier_id=assignment.soldier_id, type=NotificationType.assignment_removed,
    ).one_or_none()
    assert notif is not None


def test_bulk_delete_shifts_notifies_all_affected_soldiers(client, admin_session):
    from app.db.models import Notification, NotificationType
    # ... create 2+ shifts in range with assignments for different soldiers ...
    resp = client.delete(
        "/shifts/bulk-delete", params={"date_from": str(date_from), "date_to": str(date_to)},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    for soldier_id in affected_soldier_ids:
        notif = admin_session.query(Notification).filter_by(
            soldier_id=soldier_id, type=NotificationType.assignment_removed,
        ).one_or_none()
        assert notif is not None
```

- [ ] **Step 6: Run to verify FAIL then PASS**

Run: `pytest -k "shift" -q` (narrow further to the specific test file once located)

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/shifts.py
git commit -m "fix: audit-log and notify affected soldiers on single/bulk shift-assignment removal"
```

---

### Task 9: Swaps — notify both parties on no-approval-required paths and on reject/cancel

**Files:**
- Modify: `backend/app/services/swaps.py`
- Test: `backend/tests/unit/test_swaps.py` / `backend/app/services/tests/test_swaps*.py` (check actual location — `_AREA_MARKERS` lists `test_swaps` and `test_swaps_eligibility` under "duty")

**Interfaces:**
- Produces: `claim_request`'s and `cover_offer`'s "no approval required" branches now notify both `req.requesting_soldier_id` and the covering soldier with `NotificationType.swap_accepted`. `reject_request` now also notifies `req.covering_soldier_id` (if set) with `swap_rejected`. `cancel_request` now notifies `req.covering_soldier_id` (if set) with `swap_rejected`.

- [ ] **Step 1: `claim_request` — notify both sides when no approval is required**

Change the `else:` branch in `claim_request`:

```python
    else:
        _apply_cover(session, req=req, actor_id=actor_id)
        create_notification(session, soldier_id=req.requesting_soldier_id,
                            type=NotificationType.swap_accepted,
                            title="בקשת ההחלפה בוצעה",
                            reference_type="swap_request", reference_id=req.id,
                            actor_id=actor_id)
        create_notification(session, soldier_id=covering_soldier_id,
                            type=NotificationType.swap_accepted,
                            title="בקשת ההחלפה בוצעה",
                            reference_type="swap_request", reference_id=req.id,
                            actor_id=actor_id)
        write_audit(
            session, actor_id=actor_id, action="swap.claim", entity_type="swap_request",
            entity_id=req.id, before={"status": before_status},
            after={"status": "applied", "covering_soldier_id": str(covering_soldier_id)},
        )
```

- [ ] **Step 2: `cover_offer` — same fix**

Change the `else:` branch in `cover_offer`:

```python
    else:
        _apply_cover(session, req=req, actor_id=actor_id)
        create_notification(
            session, soldier_id=req.requesting_soldier_id,
            type=NotificationType.swap_accepted,
            title="בקשת ההחלפה בוצעה",
            reference_type="swap_request", reference_id=req.id,
            actor_id=actor_id,
        )
        create_notification(
            session, soldier_id=covering_soldier_id,
            type=NotificationType.swap_accepted,
            title="בקשת ההחלפה בוצעה",
            reference_type="swap_request", reference_id=req.id,
            actor_id=actor_id,
        )
```

- [ ] **Step 3: `reject_request` — also notify the covering soldier**

In `reject_request`, right after the existing `create_notification(session, soldier_id=req.requesting_soldier_id, ...)` call, add:

```python
    if req.covering_soldier_id is not None:
        create_notification(session, soldier_id=req.covering_soldier_id,
                            type=NotificationType.swap_rejected,
                            title="בקשת ההחלפה נדחתה",
                            reference_type="swap_request", reference_id=req.id,
                            actor_id=actor_id)
```

- [ ] **Step 4: `cancel_request` — notify the covering soldier**

In `cancel_request`, right after `req.status = "cancelled"` and before `write_audit`, add:

```python
    if req.covering_soldier_id is not None:
        create_notification(session, soldier_id=req.covering_soldier_id,
                            type=NotificationType.swap_rejected,
                            title="בקשת ההחלפה בוטלה ע\"י המבקש",
                            reference_type="swap_request", reference_id=req.id,
                            actor_id=actor_id)
```

(`cancel_request` is only reachable by the requester per `routes/swaps.py:378`'s ownership check, so only the covering soldier — not the requester — needs telling.)

- [ ] **Step 5: Write failing tests**

Add to the swaps test file:

```python
def test_claim_request_no_approval_notifies_both_sides(app_session):
    from app.db.models import Notification, NotificationType
    from app.services.swaps import claim_request
    # ... set swaps.require_manager_approval=False via existing settings helper,
    # create an open SwapRequest as in other tests in this file ...
    claim_request(app_session, request_id=req.id, covering_soldier_id=covering.id)
    app_session.flush()
    for sid in (req.requesting_soldier_id, covering.id):
        notif = app_session.query(Notification).filter_by(
            soldier_id=sid, type=NotificationType.swap_accepted,
        ).one_or_none()
        assert notif is not None


def test_reject_request_notifies_covering_soldier(app_session):
    from app.db.models import Notification, NotificationType
    from app.services.swaps import reject_request
    # ... req already has covering_soldier_id set (pending_approval) ...
    reject_request(app_session, request_id=req.id)
    app_session.flush()
    notif = app_session.query(Notification).filter_by(
        soldier_id=req.covering_soldier_id, type=NotificationType.swap_rejected,
    ).one_or_none()
    assert notif is not None


def test_cancel_request_notifies_covering_soldier(app_session):
    from app.db.models import Notification, NotificationType
    from app.services.swaps import cancel_request
    cancel_request(app_session, request_id=req.id)
    app_session.flush()
    notif = app_session.query(Notification).filter_by(
        soldier_id=req.covering_soldier_id, type=NotificationType.swap_rejected,
    ).one_or_none()
    assert notif is not None
```

- [ ] **Step 6: Run to verify FAIL then PASS**

Run: `pytest -k swap -q`

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/swaps.py
git commit -m "fix: notify both swap parties on no-approval paths, and covering soldier on reject/cancel"
```

---

### Task 10: Enrollment — notify soldier on approve/reject

**Files:**
- Modify: `backend/app/services/enrollment.py`
- Test: `backend/tests/unit/test_enrollment_routes.py` (per `_AREA_MARKERS`, this maps to "auth")

**Interfaces:**
- Produces: `approve_enrollment` and `reject_enrollment` now call `create_notification` with the pre-existing `NotificationType.enrollment_approved` / `enrollment_rejected` (already defined in the models, already wired into `_FRONTEND_PATHS` and the Telegram bot's category labels per migration `0034_enrollment_notification_types.py` — this task only adds the missing call sites).

- [ ] **Step 1: Add the import and notification calls**

In `backend/app/services/enrollment.py`, add to imports:

```python
from app.db.models import ExemptionRequest, HierarchyNode, NotificationType, Soldier, SoldierEnrollmentRequest
from app.services.notifications import create_notification
```

In `approve_enrollment`, right after `write_audit(...)` and before `try_activate(session, req.id)`:

```python
    create_notification(
        session, soldier_id=req.soldier_id,
        type=NotificationType.enrollment_approved,
        title="בקשת ההצטרפות אושרה",
        body=decision_note,
        reference_type="soldier_enrollment_request", reference_id=req.id,
        actor_id=decider_id,
    )
```

In `reject_enrollment`, right after `write_audit(...)`, before `return req`:

```python
    create_notification(
        session, soldier_id=req.soldier_id,
        type=NotificationType.enrollment_rejected,
        title="בקשת ההצטרפות נדחתה",
        body=decision_note,
        reference_type="soldier_enrollment_request", reference_id=req.id,
        actor_id=decider_id,
    )
```

- [ ] **Step 2: Write failing tests**

Add to `backend/tests/unit/test_enrollment_routes.py` (or the corresponding service-level test file if one exists — check `Glob backend/**/test_enrollment*.py` first):

```python
def test_approve_enrollment_notifies_soldier(app_session):
    from app.db.models import Notification, NotificationType
    from app.services.enrollment import approve_enrollment
    # ... reuse this file's existing pending-enrollment-request fixture ...
    approve_enrollment(app_session, request_id=req.id, decider_id=commander.id, decision_note=None)
    app_session.flush()
    notif = app_session.query(Notification).filter_by(
        soldier_id=req.soldier_id, type=NotificationType.enrollment_approved,
    ).one_or_none()
    assert notif is not None


def test_reject_enrollment_notifies_soldier(app_session):
    from app.db.models import Notification, NotificationType
    from app.services.enrollment import reject_enrollment
    reject_enrollment(app_session, request_id=req.id, decider_id=commander.id, decision_note="no")
    app_session.flush()
    notif = app_session.query(Notification).filter_by(
        soldier_id=req.soldier_id, type=NotificationType.enrollment_rejected,
    ).one_or_none()
    assert notif is not None
```

- [ ] **Step 3: Run to verify FAIL then PASS**

Run: `pytest -k enrollment -q`

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/enrollment.py
git commit -m "feat: notify soldier when their enrollment request is approved or rejected"
```

---

### Task 11: Hakpaza — notify both soldiers on approve/reject

**Files:**
- Modify: `backend/app/routes/hakpaza.py`
- Test: `backend/tests/unit/test_hakpaza.py` (check exact path via Glob — `_AREA_MARKERS` lists `test_hakpaza` under "duty")

**Interfaces:**
- Produces: `approve()` now notifies the pulled soldier (`assignment_removed`, for the original assignment being cut short) and the replacement soldier (`assignment_created`, for the new assignment). `reject()` notifies the initiator is not needed (rejection just means "no change happened" to the pulled/replacement soldiers) — instead, this task only adds notifications to `approve()`, since `reject()` produces no state change for any soldier (the `ForcedCallup.status` flips to `"rejected"` but no `DutyAssignment` is touched).

- [ ] **Step 1: Add imports**

In `backend/app/routes/hakpaza.py`, add:

```python
from app.db.models import DutyAssignment, ForcedCallup, HierarchyNode, NotificationType, Soldier
from app.services.notifications import create_notification
```

(merge `NotificationType` into the existing `app.db.models` import line rather than duplicating it.)

- [ ] **Step 2: Notify both soldiers in `approve()`**

In `approve()`, right after `session.flush()` (which follows `session.add(new_assignment)`) and before `h.status = "approved"`, keep the flush as-is; then right before `session.commit()` at the end of the function, add:

```python
    create_notification(
        session, soldier_id=h.pulled_soldier_id,
        type=NotificationType.assignment_removed,
        title="שוחררת מתורנות עקב הקפצה פיקודית",
        reference_type="duty_assignment", reference_id=original.id,
        actor_id=actor.id,
    )
    create_notification(
        session, soldier_id=h.replacement_soldier_id,
        type=NotificationType.assignment_created,
        title="שובצת לתורנות עקב הקפצה פיקודית",
        reference_type="duty_assignment", reference_id=new_assignment.id,
        actor_id=actor.id,
    )

    session.commit()
    session.refresh(h)
    return _out(h)
```

(This replaces the existing bare `session.commit(); session.refresh(h); return _out(h)` at the end of `approve()` — insert the two `create_notification` calls immediately before that existing `session.commit()`.)

- [ ] **Step 3: Write failing test**

Add to the hakpaza test file:

```python
def test_hakpaza_approve_notifies_both_soldiers(client, admin_session):
    from app.db.models import Notification, NotificationType
    # ... reuse this file's existing pending-ForcedCallup fixture setup ...
    resp = client.post(f"/hakpaza/{hakpaza.id}/approve", headers=admin_headers)
    assert resp.status_code == 200
    pulled_notif = admin_session.query(Notification).filter_by(
        soldier_id=hakpaza.pulled_soldier_id, type=NotificationType.assignment_removed,
    ).one_or_none()
    replacement_notif = admin_session.query(Notification).filter_by(
        soldier_id=hakpaza.replacement_soldier_id, type=NotificationType.assignment_created,
    ).one_or_none()
    assert pulled_notif is not None
    assert replacement_notif is not None
```

- [ ] **Step 4: Run to verify FAIL then PASS**

Run: `pytest -k hakpaza -q`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/hakpaza.py
git commit -m "feat: notify pulled and replacement soldiers when a hakpaza call-up is approved"
```

---

### Task 12: Algorithm job runner — notify on all terminal states

**Files:**
- Modify: `backend/app/services/algorithm_bridge.py`
- Test: `backend/app/services/tests/test_algorithm_bridge.py` or `backend/tests/unit/test_algorithm_notification.py` (per `_AREA_MARKERS`, `test_algorithm_notification` already exists — extend it)

**Interfaces:**
- Produces: the `NOTHING_TO_ASSIGN` early return (~line 1119-1131), the `no_soldiers_or_duties` early return (~line 1183-1188), and the `INFEASIBLE` early return (~line 1280-1297) each now notify `job.created_by` before returning — the `NOTHING_TO_ASSIGN` path with `algorithm_job_done` (it's a clean success, just with nothing to do), the other two with `algorithm_job_failed`.

- [ ] **Step 1: `NOTHING_TO_ASSIGN` — notify with `algorithm_job_done`**

In `backend/app/services/algorithm_bridge.py`, change:

```python
                if not duties:
                    # Every selected shift is already fully staffed (published or
                    # pending draft) — there is nothing to assign. Finish cleanly
                    # rather than failing, and surface a clear reason for the UI.
                    job.status = "done"
                    job.progress_message = json.dumps({"pct": 100, "label": "הושלם"})
                    job.error_message = json.dumps({
                        "status": "NOTHING_TO_ASSIGN",
                        "reasons": ["כל המשמרות שנבחרו כבר מאוישות במלואן — אין מה לשבץ."],
                    })
                    job.finished_at = datetime.now(tz=UTC)
                    session.commit()
                    return
```

to:

```python
                if not duties:
                    # Every selected shift is already fully staffed (published or
                    # pending draft) — there is nothing to assign. Finish cleanly
                    # rather than failing, and surface a clear reason for the UI.
                    job.status = "done"
                    job.progress_message = json.dumps({"pct": 100, "label": "הושלם"})
                    job.error_message = json.dumps({
                        "status": "NOTHING_TO_ASSIGN",
                        "reasons": ["כל המשמרות שנבחרו כבר מאוישות במלואן — אין מה לשבץ."],
                    })
                    job.finished_at = datetime.now(tz=UTC)
                    if job.created_by:
                        from app.db.models import NotificationType
                        from app.services.notifications import create_notification
                        create_notification(
                            session, soldier_id=job.created_by,
                            type=NotificationType.algorithm_job_done,
                            title="הרצת האלגוריתם הסתיימה — אין מה לשבץ",
                            reference_type="algorithm_job", reference_id=job.id,
                        )
                    session.commit()
                    return
```

- [ ] **Step 2: `no_soldiers_or_duties` — notify with `algorithm_job_failed`**

Change:

```python
                if not soldiers:
                    job.status = "failed"
                    job.error_message = "no_soldiers_or_duties"
                    job.finished_at = datetime.now(tz=UTC)
                    session.commit()
                    return
```

to:

```python
                if not soldiers:
                    job.status = "failed"
                    job.error_message = "no_soldiers_or_duties"
                    job.finished_at = datetime.now(tz=UTC)
                    if job.created_by:
                        from app.db.models import NotificationType
                        from app.services.notifications import create_notification
                        create_notification(
                            session, soldier_id=job.created_by,
                            type=NotificationType.algorithm_job_failed,
                            title="הרצת האלגוריתם נכשלה — אין חיילים זמינים",
                            reference_type="algorithm_job", reference_id=job.id,
                        )
                    session.commit()
                    return
```

- [ ] **Step 3: `INFEASIBLE` — notify with `algorithm_job_failed`**

Change:

```python
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
                    processed = _postprocess_batch_results(result.batch_results, block_to_shift_map)
                    job.batch_results = [_br_to_dict(br) for br in processed]
                    job.finished_at = datetime.now(tz=UTC)
                    session.commit()
                    return
```

to:

```python
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
                    processed = _postprocess_batch_results(result.batch_results, block_to_shift_map)
                    job.batch_results = [_br_to_dict(br) for br in processed]
                    job.finished_at = datetime.now(tz=UTC)
                    if job.created_by:
                        from app.db.models import NotificationType
                        from app.services.notifications import create_notification
                        create_notification(
                            session, soldier_id=job.created_by,
                            type=NotificationType.algorithm_job_failed,
                            title="הרצת האלגוריתם נכשלה — לא נמצא פתרון אפשרי",
                            body="; ".join(reasons[:3]) if reasons else None,
                            reference_type="algorithm_job", reference_id=job.id,
                        )
                    session.commit()
                    return
```

- [ ] **Step 4: Write failing tests**

Extend `backend/app/services/tests/test_algorithm_bridge.py` (or `test_algorithm_notification.py` if that's where notification assertions for this module already live — check both):

```python
def test_infeasible_job_notifies_creator(app_session):
    from app.db.models import Notification, NotificationType
    # ... reuse this test file's existing pattern for forcing an INFEASIBLE
    # result (e.g. zero eligible soldiers for a required duty) and run
    # run_algorithm_job as done in other tests here ...
    notif = app_session.query(Notification).filter_by(
        soldier_id=job.created_by, type=NotificationType.algorithm_job_failed,
    ).one_or_none()
    assert notif is not None


def test_nothing_to_assign_notifies_creator(app_session):
    from app.db.models import Notification, NotificationType
    # ... reuse this test file's existing pattern for a job whose shifts are
    # already fully staffed ...
    notif = app_session.query(Notification).filter_by(
        soldier_id=job.created_by, type=NotificationType.algorithm_job_done,
    ).one_or_none()
    assert notif is not None
```

- [ ] **Step 5: Run to verify FAIL then PASS**

Run: `pytest -k "algorithm_bridge or algorithm_notification" -q`

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/algorithm_bridge.py
git commit -m "feat: notify job creator on all algorithm-run terminal states, not just success/exception"
```

---

### Task 13: Excel import — enforce DM scope, add audit trail and assignment notifications

**Files:**
- Modify: `backend/app/routes/import_excel.py`
- Test: `backend/tests/unit/test_import_excel.py` (per `_AREA_MARKERS`, maps to "soldiers")

**Interfaces:**
- Consumes: `is_node_in_actor_scope` from `app.services.import_scope` (already used by the newer `import_sessions.py` pipeline — reused here, not reimplemented).
- Produces: `apply()` now 403s with a list of out-of-scope rows for any non-admin actor whose soldiers/assignments touch a hierarchy node outside their `DutyManagerScope`; writes one summary `write_audit` row; sends `assignment_created` notifications for imported assignments (mirroring what the interactive `assignments.py:create_assignment` does).

- [ ] **Step 1: Add a scope-check helper and imports**

In `backend/app/routes/import_excel.py`, add to imports:

```python
from app.audit.writer import write_audit
from app.db.models import (
    DutyAssignment,
    DutyLocation,
    DutyShift,
    DutyShiftNodeQuota,
    DutyType,
    HierarchyNode,
    NotificationType,
    ShiftTemplate,
    Soldier,
)
from app.services.import_scope import is_node_in_actor_scope
from app.services.notifications import create_notification
```

Add the helper right before `apply()`:

```python
def _out_of_scope_rows(session: Session, actor: Soldier, req: ApplyRequest) -> list[str]:
    """Return a list of human-readable row descriptions the actor may not import,
    because they touch a hierarchy node outside the actor's DutyManagerScope.
    Empty for admins."""
    if actor.role == "admin":
        return []
    errors: list[str] = []
    for row in req.soldiers:
        if row.action == "skip":
            continue
        if row.action == "new":
            if not is_node_in_actor_scope(session=session, actor=actor, node_id=row.hierarchy_node_id):
                errors.append(f"soldier row {row.row}: hierarchy node out of your scope")
        elif row.action == "update" and row.existing_id:
            existing = session.get(Soldier, row.existing_id)
            current_node_id = existing.hierarchy_node_id if existing else None
            if not is_node_in_actor_scope(session=session, actor=actor, node_id=current_node_id):
                errors.append(f"soldier row {row.row}: soldier's current node is out of your scope")
            if row.hierarchy_node_id is not None and not is_node_in_actor_scope(
                session=session, actor=actor, node_id=row.hierarchy_node_id
            ):
                errors.append(f"soldier row {row.row}: destination node out of your scope")
    for row in req.assignments:
        if row.action == "skip":
            continue
        soldier = session.get(Soldier, row.resolved_soldier_id)
        node_id = soldier.hierarchy_node_id if soldier else None
        if not is_node_in_actor_scope(session=session, actor=actor, node_id=node_id):
            errors.append(f"assignment row {row.row}: soldier out of your scope")
    return errors
```

- [ ] **Step 2: Enforce it at the top of `apply()`**

In `apply()`, right after the function signature and before `from app.auth.password import hash_password`:

```python
def apply(
    req: ApplyRequest,
    session: Session = Depends(get_session),
    actor: Soldier = Depends(require_duty_manager_or_admin),
):
    out_of_scope = _out_of_scope_rows(session, actor, req)
    if out_of_scope:
        raise HTTPException(status_code=403, detail={"out_of_scope_rows": out_of_scope})

    from app.auth.password import hash_password
```

- [ ] **Step 3: Add audit trail + assignment notifications**

Track created soldier/assignment ids as the loop runs, and add the summary audit + notifications right before the function's `return`. Change the end of `apply()` from:

```python
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc))

    return ApplyResult(created=created, updated=updated, skipped=skipped, errors=errors)
```

to:

```python
        write_audit(
            session, actor_id=actor.id, action="import.excel_apply", entity_type="import_batch",
            after={"created": created, "updated": updated, "skipped": skipped,
                   "created_assignment_ids": [str(a.id) for a in created_assignments]},
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(exc))

    for a in created_assignments:
        create_notification(
            session, soldier_id=a.soldier_id,
            type=NotificationType.assignment_created,
            title="שיבוץ חדש נוצר עבורך (ייבוא Excel)",
            reference_type="duty_assignment", reference_id=a.id,
            actor_id=actor.id,
        )
    if created_assignments:
        session.commit()

    return ApplyResult(created=created, updated=updated, skipped=skipped, errors=errors)
```

And in the assignments loop earlier in the same function, collect the created rows — change:

```python
    created = updated = skipped = 0
    errors: list[str] = []

    try:
```

to:

```python
    created = updated = skipped = 0
    errors: list[str] = []
    created_assignments: list[DutyAssignment] = []

    try:
```

and change:

```python
            assignment = DutyAssignment(
                soldier_id=row.resolved_soldier_id,
                duty_type_id=row.resolved_duty_type_id,
                duty_location_id=loc.id,
                start_date=date_type.fromisoformat(row.start_date),
                end_date=date_type.fromisoformat(row.end_date),
                status="published",
                is_reserve=row.is_reserve,
            )
            session.add(assignment)
            created += 1
```

to:

```python
            assignment = DutyAssignment(
                soldier_id=row.resolved_soldier_id,
                duty_type_id=row.resolved_duty_type_id,
                duty_location_id=loc.id,
                start_date=date_type.fromisoformat(row.start_date),
                end_date=date_type.fromisoformat(row.end_date),
                status="published",
                is_reserve=row.is_reserve,
            )
            session.add(assignment)
            session.flush()
            created_assignments.append(assignment)
            created += 1
```

(The `session.flush()` here assigns `assignment.id` so it's available for the audit/notification block after commit — a small, bounded per-row flush cost already implicitly paid by the ORM before commit either way, not a new bulk-performance regression since Excel imports are human-reviewed batches, not large mechanical bulk deletes like Task 8's shift endpoints.)

- [ ] **Step 4: Write failing tests**

Add to `backend/tests/unit/test_import_excel.py`:

```python
def test_apply_rejects_out_of_scope_hierarchy_node(client, admin_session):
    """A duty manager scoped to unit A must not be able to import a soldier
    into unit B via /import/apply."""
    # ... create two disjoint units, a DM scoped only to unit A, and an
    # ApplyRequest with a soldier row targeting unit B's hierarchy_node_id ...
    resp = client.post("/import/apply", json=req_body, headers=dm_headers)
    assert resp.status_code == 403
    assert "out_of_scope_rows" in resp.json()["detail"]


def test_apply_notifies_soldier_of_new_assignment(client, admin_session):
    from app.db.models import Notification, NotificationType
    # ... build a valid in-scope ApplyRequest with one assignment row for an
    # existing soldier ...
    resp = client.post("/import/apply", json=req_body, headers=admin_headers)
    assert resp.status_code == 200
    notif = admin_session.query(Notification).filter_by(
        soldier_id=soldier.id, type=NotificationType.assignment_created,
    ).one_or_none()
    assert notif is not None
```

- [ ] **Step 5: Run to verify FAIL then PASS**

Run: `pytest backend/tests/unit/test_import_excel.py -v`

- [ ] **Step 6: Run existing import-excel tests for regressions**

Run: `pytest -k import_excel -q`

(If existing tests call `/import/apply` as a plain duty manager without a `DutyManagerScope` row covering the target node, they will now correctly 403 — update those fixtures to either act as admin or add the appropriate scope row, since that's the gap being fixed.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/import_excel.py backend/tests/unit/test_import_excel.py
git commit -m "fix: enforce duty-manager scope and add audit/notifications on Excel import apply"
```

---

### Task 14: Fix announcement broadcast — correct action, enforce scope

**Files:**
- Modify: `backend/app/routes/notifications.py`
- Test: `backend/tests/unit/test_notifications_api.py` (per `_AREA_MARKERS`)

**Interfaces:**
- Produces: `announce()` no longer reuses `Action.ALGORITHM_RUN` (a DM-global action that was never actually about announcements). Non-admin callers must supply `hierarchy_node_ids` and every one of those nodes must be within their own `scope_root_ids`; org-wide (no `hierarchy_node_ids`) announcements are admin-only.

- [ ] **Step 1: Replace the `announce()` permission check**

In `backend/app/routes/notifications.py`, change:

```python
@router.post("/notifications/announce", status_code=201)
def announce(
    body: AnnounceBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    authorize(session, user, Action.ALGORITHM_RUN, target_node=None)
    count = svc.broadcast_announcement(session, title=body.title, body=body.body,
                                        hierarchy_node_ids=body.hierarchy_node_ids,
                                        actor_id=user.id)
    session.commit()
    return {"sent": count}
```

to:

```python
@router.post("/notifications/announce", status_code=201)
def announce(
    body: AnnounceBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict:
    from app.auth.authz import _node_in_scope, is_commander, is_duty_manager, scope_root_ids

    if user.role != "admin":
        if not body.hierarchy_node_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="org_wide_announcement_requires_admin"
            )
        if not (is_commander(session, user.id) or is_duty_manager(session, user.id)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        roots = scope_root_ids(session, user)
        for node_id in body.hierarchy_node_ids:
            node = session.get(HierarchyNode, node_id)
            if not _node_in_scope(node, roots):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="hierarchy_node_out_of_scope"
                )

    count = svc.broadcast_announcement(session, title=body.title, body=body.body,
                                        hierarchy_node_ids=body.hierarchy_node_ids,
                                        actor_id=user.id)
    session.commit()
    return {"sent": count}
```

- [ ] **Step 2: Write failing tests**

Add to `backend/tests/unit/test_notifications_api.py`:

```python
def test_non_admin_cannot_broadcast_org_wide(client, admin_session):
    # ... log in as a plain duty manager with a DutyManagerScope row ...
    resp = client.post("/notifications/announce", json={"title": "hi"}, headers=dm_headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "org_wide_announcement_requires_admin"


def test_dm_cannot_broadcast_to_out_of_scope_node(client, admin_session):
    # ... DM scoped to unit A only; target unit B's id in hierarchy_node_ids ...
    resp = client.post(
        "/notifications/announce",
        json={"title": "hi", "hierarchy_node_ids": [str(unit_b.id)]},
        headers=dm_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "hierarchy_node_out_of_scope"


def test_dm_can_broadcast_to_own_scope(client, admin_session):
    resp = client.post(
        "/notifications/announce",
        json={"title": "hi", "hierarchy_node_ids": [str(unit_a.id)]},
        headers=dm_headers,
    )
    assert resp.status_code == 201
```

- [ ] **Step 3: Run to verify FAIL then PASS**

Run: `pytest backend/tests/unit/test_notifications_api.py -v`

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/notifications.py backend/tests/unit/test_notifications_api.py
git commit -m "fix: announce() no longer reuses ALGORITHM_RUN action; enforce scope on non-admin broadcasts"
```

---

## Final verification

- [ ] **Run the fast suite once all 14 tasks are committed**

Run: `pytest -q`
Expected: all green (per project convention, this is the fast suite — `--slow` is only for pre-release).

- [ ] **Hand off to code review**

Use `superpowers:requesting-code-review` once all tasks are committed on the feature branch, before merging via the project's `merge-worktree-to-dev` skill.
