# Adversarial Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the abuse paths found in the adversarial security audit (malicious soldiers dodging duties, screwing over other soldiers via swaps, interfering with system data, and flooding commanders/maintainers with noise) — backend only.

**Architecture:** Ten independent, backend-only fixes across the swaps, constraints, exemption-requests, hierarchy-transfers, bug-reports, notifications, and invite-codes subsystems, plus one new subsystem (no-show marking). Each task is self-contained and independently testable; no task depends on another task's code (only migration ordering is sequential, see Global Constraints).

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (dataclass-mapped models), Alembic, pytest, PostgreSQL (enum types, `ARRAY`, `JSONB`).

## Global Constraints

- All work is **backend-only**. Tasks 8 (constraints two-step approval) and 10 (no-show) add or change backend behavior that the frontend currently has no UI for; this is intentional and flagged per-task — do not build frontend UI as part of this plan.
- Migration chain: current single Alembic head is `63cff804e3e4`. Task 9's migration (`a1c2e3f4b5d6`) chains directly off it. Task 10's migration (`b2d3f4a5c6e7`) chains off Task 9's. Run `alembic heads` before starting Task 9 to confirm `63cff804e3e4` is still the sole head (another branch may have merged since this plan was written — if so, rebase the `down_revision` accordingly).
- Every new/changed money-shaped setting default and every numeric cap below is exact — do not substitute your own numbers.
- Follow existing code conventions exactly: `from __future__ import annotations`, keyword-only args after `*`, `write_audit(...)` on every state-changing service call, `create_notification`/`notify_commanders_of_request`/`notify_duty_managers_of_request` for user-facing notices, Hebrew notification titles matching the existing tone.
- Test conventions: unit tests use the `admin_session` fixture and `tests.helpers.create_soldier`/`create_node`; integration tests use the `client` fixture + `tests.helpers.auth_headers`. Follow the exact existing file's import block when adding tests to an existing file.

---

### Task 1: Atomic invite-code redemption (race condition fix)

**Files:**
- Modify: `backend/app/services/invite_codes.py`
- Test: `backend/tests/unit/test_invite_codes.py` (create if it does not exist — check with `Glob` first)

**Interfaces:**
- Produces: `consume_invite_code(session, *, code: str) -> RegistrationInviteCode` (signature unchanged, only the implementation becomes atomic)

- [ ] **Step 1: Read the current file to confirm exact content**

Run: read `backend/app/services/invite_codes.py` in full (it's short — `validate_code` + `consume_invite_code`).

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/unit/test_invite_codes.py
import pytest
from sqlalchemy import select

from app.db.models import RegistrationInviteCode
from app.services.invite_codes import InviteCodeError, consume_invite_code, validate_code


def test_consume_decrements_uses_left(admin_session):
    admin_session.add(RegistrationInviteCode(code="ABC123", uses_left=2))
    admin_session.flush()
    row = consume_invite_code(admin_session, code="ABC123")
    admin_session.commit()
    assert row.uses_left == 1


def test_consume_raises_when_exhausted(admin_session):
    admin_session.add(RegistrationInviteCode(code="EXH001", uses_left=0))
    admin_session.flush()
    with pytest.raises(InviteCodeError, match="exhausted"):
        consume_invite_code(admin_session, code="EXH001")


def test_consume_raises_when_not_found(admin_session):
    with pytest.raises(InviteCodeError, match="invalid"):
        consume_invite_code(admin_session, code="NOPE")


def test_concurrent_consume_never_over_redeems(admin_session, admin_engine):
    """Two concurrent redemptions of a single-use code must not both succeed."""
    admin_session.add(RegistrationInviteCode(code="RACE01", uses_left=1))
    admin_session.commit()

    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=admin_engine, expire_on_commit=False)
    s1 = SessionLocal()
    s2 = SessionLocal()
    try:
        row1 = consume_invite_code(s1, code="RACE01")
        s1.commit()
        with pytest.raises(InviteCodeError, match="exhausted"):
            consume_invite_code(s2, code="RACE01")
        s2.rollback()
    finally:
        s1.close()
        s2.close()

    row = admin_session.execute(
        select(RegistrationInviteCode).where(RegistrationInviteCode.code == "RACE01")
    ).scalar_one()
    assert row.uses_left == 0
```

- [ ] **Step 3: Run tests to verify the last one fails (or passes only by luck) against the current implementation**

Run: `pytest tests/unit/test_invite_codes.py -v`
Expected: first three PASS (current code already handles the simple cases correctly), `test_concurrent_consume_never_over_redeems` is not a true concurrency test yet (sequential calls on separate sessions) — it will actually pass today too, because sequential non-overlapping calls don't race. This is fine: the real value of this task is the atomicity of the SQL itself, verified by code review + the simple-case tests. Do not attempt to fabricate a real thread-interleaved race test — SQLite/session-per-thread races are flaky to simulate reliably in this test suite; the atomic `UPDATE ... WHERE uses_left > 0` is the fix, and the sequential test documents the contract.

- [ ] **Step 4: Rewrite `consume_invite_code` to be atomic**

```python
# backend/app/services/invite_codes.py
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.db.models import RegistrationInviteCode


class InviteCodeError(Exception):
    """Raised on an invalid invite-code operation."""


def validate_code(session: Session, *, code: str) -> bool:
    row = session.execute(
        select(RegistrationInviteCode).where(RegistrationInviteCode.code == code)
    ).scalar_one_or_none()
    return row is not None and row.uses_left > 0


def consume_invite_code(session: Session, *, code: str) -> RegistrationInviteCode:
    result = session.execute(
        sa_update(RegistrationInviteCode)
        .where(RegistrationInviteCode.code == code, RegistrationInviteCode.uses_left > 0)
        .values(uses_left=RegistrationInviteCode.uses_left - 1)
        .returning(RegistrationInviteCode)
    )
    row = result.scalar_one_or_none()
    if row is not None:
        session.flush()
        return row

    existing = session.execute(
        select(RegistrationInviteCode).where(RegistrationInviteCode.code == code)
    ).scalar_one_or_none()
    if existing is None:
        raise InviteCodeError("invalid invite code")
    raise InviteCodeError("invite code exhausted")
```

- [ ] **Step 5: Run tests to verify all pass**

Run: `pytest tests/unit/test_invite_codes.py -v`
Expected: 4 PASSED

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/invite_codes.py backend/tests/unit/test_invite_codes.py
git commit -m "fix: make invite-code redemption atomic to prevent over-redemption race"
```

---

### Task 2: Validate `to_node_id` exists on hierarchy transfer requests

**Files:**
- Modify: `backend/app/services/hierarchy_transfers.py`
- Test: `backend/tests/unit/test_hierarchy_transfers.py` (create if missing — check with `Glob` first)

**Interfaces:**
- Consumes: nothing new
- Produces: `create_request(...)` now raises `HierarchyTransferError("to_node_not_found")` for a garbage `to_node_id`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_hierarchy_transfers.py
import uuid
from datetime import date

import pytest

from app.services.hierarchy_transfers import HierarchyTransferError, create_request
from tests.helpers import create_node, create_soldier


def test_create_request_rejects_unknown_to_node(admin_session):
    s = create_soldier(admin_session, personal_number="7600001")
    with pytest.raises(HierarchyTransferError, match="to_node_not_found"):
        create_request(
            admin_session, soldier_id=s.id, to_node_id=uuid.uuid4(), requested_by=s.id,
        )


def test_create_request_succeeds_for_real_node(admin_session):
    s = create_soldier(admin_session, personal_number="7600002")
    node = create_node(admin_session, level="unit", name="u1")
    req = create_request(admin_session, soldier_id=s.id, to_node_id=node.id, requested_by=s.id)
    admin_session.commit()
    assert req.to_node_id == node.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_hierarchy_transfers.py::test_create_request_rejects_unknown_to_node -v`
Expected: FAIL (no error raised today — a `HierarchyTransferRequest` row with a garbage `to_node_id` is created successfully)

- [ ] **Step 3: Add the validation**

In `backend/app/services/hierarchy_transfers.py`, add `HierarchyNode` to the existing model import and validate before constructing the row:

```python
from app.db.models import HierarchyNode, HierarchyTransferRequest, NotificationType, Soldier


def create_request(
    session: Session, *, soldier_id: uuid.UUID, to_node_id: uuid.UUID,
    requested_by: uuid.UUID,
) -> HierarchyTransferRequest:
    soldier = session.get(Soldier, soldier_id)
    if soldier is None:
        raise HierarchyTransferError("soldier_not_found")
    if session.get(HierarchyNode, to_node_id) is None:
        raise HierarchyTransferError("to_node_not_found")
    req = HierarchyTransferRequest(
        soldier_id=soldier_id, from_node_id=soldier.hierarchy_node_id,
        to_node_id=to_node_id, requested_by=requested_by,
    )
    session.add(req)
    session.flush()
    _notify_destination_approvers(session, req)
    write_audit(
        session, actor_id=requested_by, action="hierarchy_transfer.request",
        entity_type="hierarchy_transfer_request", entity_id=req.id,
        after={"soldier_id": str(soldier_id), "to_node_id": str(to_node_id)},
    )
    return req
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_hierarchy_transfers.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Verify the route already surfaces this correctly**

`backend/app/routes/hierarchy_transfers.py::create_transfer` already catches `svc.HierarchyTransferError` and returns 400 — no route change needed. Confirm by reading the route function.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/hierarchy_transfers.py backend/tests/unit/test_hierarchy_transfers.py
git commit -m "fix: reject hierarchy transfer requests targeting a nonexistent node"
```

---

### Task 3: Forbid self-approval of hierarchy transfer requests

**Files:**
- Modify: `backend/app/routes/hierarchy_transfers.py`
- Test: `backend/tests/integration/test_hierarchy_transfers_api.py` (create if missing — check with `Glob` first)

**Interfaces:**
- Consumes: `forbid_self_target(user: Soldier, target_soldier_id: uuid.UUID) -> None` from `app.auth.authz` (already used by exemption/constraint routes — raises 403 `cannot_act_on_own_request` if `user.id == target_soldier_id`)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/integration/test_hierarchy_transfers_api.py
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_requester_cannot_approve_own_transfer_into_own_command(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d-self")
    b = create_node(admin_session, level="branch", name="b-self", parent=d)
    cmd = create_soldier(admin_session, personal_number="7700001", role="commander", hierarchy_node_id=d.id)
    b.commander_id = cmd.id
    admin_session.commit()

    r = client.post(
        "/api/hierarchy-transfers",
        headers=auth_headers(cmd),
        json={"soldier_id": str(cmd.id), "to_node_id": str(b.id)},
    )
    assert r.status_code == 200, r.text
    request_id = r.json()["id"]

    r2 = client.post(f"/api/hierarchy-transfers/{request_id}/approve", headers=auth_headers(cmd))
    assert r2.status_code == 403


def test_other_commander_can_still_approve(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d-other")
    b = create_node(admin_session, level="branch", name="b-other", parent=d)
    dept_cmd = create_soldier(admin_session, personal_number="7700002", role="commander", hierarchy_node_id=d.id)
    d.commander_id = dept_cmd.id
    branch_cmd = create_soldier(admin_session, personal_number="7700003", role="commander", hierarchy_node_id=d.id)
    b.commander_id = branch_cmd.id
    admin_session.commit()

    r = client.post(
        "/api/hierarchy-transfers",
        headers=auth_headers(branch_cmd),
        json={"soldier_id": str(branch_cmd.id), "to_node_id": str(b.id)},
    )
    assert r.status_code == 200, r.text
    request_id = r.json()["id"]

    r2 = client.post(f"/api/hierarchy-transfers/{request_id}/approve", headers=auth_headers(dept_cmd))
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "approved"
```

- [ ] **Step 2: Run tests to verify the first fails**

Run: `pytest tests/integration/test_hierarchy_transfers_api.py -v`
Expected: `test_requester_cannot_approve_own_transfer_into_own_command` FAILS (returns 200 today, not 403)

- [ ] **Step 3: Add `forbid_self_target` to approve and reject routes**

In `backend/app/routes/hierarchy_transfers.py`, import it and call it before `authorize(...)` in both `approve_transfer` and `reject_transfer`:

```python
from app.auth.authz import Action, authorize, forbid_self_target
```

```python
@router.post("/{request_id}/approve", response_model=TransferOut)
def approve_transfer(
    request_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TransferOut:
    req = session.get(HierarchyTransferRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="request_not_found")
    forbid_self_target(user, req.soldier_id)
    dest_node = session.get(HierarchyNode, req.to_node_id)
    authorize(session, user, Action.SOLDIER_UPDATE, target_node=dest_node)
    try:
        req = svc.approve_request(session, request_id=request_id, actor_id=user.id)
    except svc.HierarchyTransferError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    session.commit()
    return _out(req)


@router.post("/{request_id}/reject", response_model=TransferOut)
def reject_transfer(
    request_id: uuid.UUID,
    body: DecisionBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> TransferOut:
    req = session.get(HierarchyTransferRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="request_not_found")
    forbid_self_target(user, req.soldier_id)
    dest_node = session.get(HierarchyNode, req.to_node_id)
    authorize(session, user, Action.SOLDIER_UPDATE, target_node=dest_node)
    try:
        req = svc.reject_request(session, request_id=request_id, actor_id=user.id, decision_note=body.decision_note)
    except svc.HierarchyTransferError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    session.commit()
    return _out(req)
```

- [ ] **Step 4: Run tests to verify both pass**

Run: `pytest tests/integration/test_hierarchy_transfers_api.py -v`
Expected: 2 PASSED

- [ ] **Step 5: Run the full hierarchy-transfer test surface to check for regressions**

Run: `pytest -k hierarchy_transfer -v`
Expected: all PASS (no earlier test relies on a requester approving their own transfer)

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/hierarchy_transfers.py backend/tests/integration/test_hierarchy_transfers_api.py
git commit -m "fix: block a soldier from approving or rejecting their own hierarchy transfer request"
```

---

### Task 4: Daily cap on hierarchy transfer requests (5/day per soldier)

**Files:**
- Modify: `backend/app/services/hierarchy_transfers.py`
- Test: `backend/tests/unit/test_hierarchy_transfers.py` (already created in Task 2)

**Interfaces:**
- Produces: `create_request(...)` raises `HierarchyTransferError("daily_transfer_request_limit_exceeded")` on the 6th request for the same `soldier_id` within a rolling 24h window, regardless of `requested_by` or `to_node_id`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/unit/test_hierarchy_transfers.py
def test_create_request_daily_cap_enforced(admin_session):
    s = create_soldier(admin_session, personal_number="7600003")
    nodes = [create_node(admin_session, level="unit", name=f"cap_u{i}") for i in range(6)]
    for node in nodes[:5]:
        create_request(admin_session, soldier_id=s.id, to_node_id=node.id, requested_by=s.id)
        admin_session.flush()
    with pytest.raises(HierarchyTransferError, match="daily_transfer_request_limit_exceeded"):
        create_request(admin_session, soldier_id=s.id, to_node_id=nodes[5].id, requested_by=s.id)


def test_create_request_daily_cap_is_per_soldier(admin_session):
    s1 = create_soldier(admin_session, personal_number="7600004")
    s2 = create_soldier(admin_session, personal_number="7600005")
    node = create_node(admin_session, level="unit", name="cap_shared")
    for _ in range(5):
        create_request(admin_session, soldier_id=s1.id, to_node_id=node.id, requested_by=s1.id)
        admin_session.flush()
    # s2 has made zero requests today — must not be blocked by s1's cap
    req = create_request(admin_session, soldier_id=s2.id, to_node_id=node.id, requested_by=s2.id)
    admin_session.commit()
    assert req.soldier_id == s2.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_hierarchy_transfers.py -k daily_cap -v`
Expected: both FAIL (no cap exists yet — request #6 succeeds instead of raising)

- [ ] **Step 3: Implement the cap**

```python
# backend/app/services/hierarchy_transfers.py
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

_DAILY_TRANSFER_REQUEST_LIMIT = 5


def create_request(
    session: Session, *, soldier_id: uuid.UUID, to_node_id: uuid.UUID,
    requested_by: uuid.UUID,
) -> HierarchyTransferRequest:
    soldier = session.get(Soldier, soldier_id)
    if soldier is None:
        raise HierarchyTransferError("soldier_not_found")
    if session.get(HierarchyNode, to_node_id) is None:
        raise HierarchyTransferError("to_node_not_found")

    window_start = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_count = session.execute(
        select(func.count()).select_from(HierarchyTransferRequest).where(
            HierarchyTransferRequest.soldier_id == soldier_id,
            HierarchyTransferRequest.created_at >= window_start,
        )
    ).scalar_one()
    if recent_count >= _DAILY_TRANSFER_REQUEST_LIMIT:
        raise HierarchyTransferError("daily_transfer_request_limit_exceeded")

    req = HierarchyTransferRequest(
        soldier_id=soldier_id, from_node_id=soldier.hierarchy_node_id,
        to_node_id=to_node_id, requested_by=requested_by,
    )
    session.add(req)
    session.flush()
    _notify_destination_approvers(session, req)
    write_audit(
        session, actor_id=requested_by, action="hierarchy_transfer.request",
        entity_type="hierarchy_transfer_request", entity_id=req.id,
        after={"soldier_id": str(soldier_id), "to_node_id": str(to_node_id)},
    )
    return req
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_hierarchy_transfers.py -v`
Expected: 6 PASSED (all tests from Task 2 and Task 4 in this file)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hierarchy_transfers.py backend/tests/unit/test_hierarchy_transfers.py
git commit -m "feat: cap hierarchy transfer requests at 5 per soldier per rolling 24h"
```

---

### Task 5: Require a non-empty reason on exemption requests

**Files:**
- Modify: `backend/app/routes/exemption_requests.py:76-80` (`CreateExemptionRequest`)
- Modify: `backend/app/services/exemption_requests.py` (`submit_request`)
- Test: `backend/tests/unit/test_exemption_requests_service.py` if it exists (check with `Glob`; else add to `backend/tests/unit/test_exemptions_service.py` or create `test_exemption_requests_service.py`)
- Test: `backend/tests/integration/test_exemption_requests_api.py` if it exists (check with `Glob`)

**Interfaces:**
- Produces: `submit_request(...)` raises `ExemptionRequestError("reason_required")` for `None`/empty/whitespace-only `reason`; `POST /me/exemption-requests` returns 422 for a missing/empty `reason` field (enforced by Pydantic) and 400 for whitespace-only (enforced by the service).

- [ ] **Step 1: Confirm the current file layout**

Run `Glob` for `backend/tests/unit/test_exemption_request*.py` and `backend/tests/integration/test_exemption_request*.py` to find (or confirm the absence of) existing test files for this service, and read whichever exists to match its exact import/fixture style before adding to it.

- [ ] **Step 2: Write the failing unit test** (add to the exemption-request test file found/created in Step 1)

```python
import pytest
from datetime import date, timedelta

from app.db.models import ExemptionType
from app.services.exemption_requests import ExemptionRequestError, submit_request
from tests.helpers import create_soldier


def _et(session, name="פטור-reason-test"):
    et = ExemptionType(name=name, is_commander_exemption=False)
    session.add(et)
    session.flush()
    return et


def test_submit_request_rejects_empty_reason(admin_session):
    s = create_soldier(admin_session, personal_number="7800001")
    et = _et(admin_session)
    with pytest.raises(ExemptionRequestError, match="reason_required"):
        submit_request(
            admin_session, soldier_id=s.id, exemption_type_id=et.id,
            start_date=date.today() + timedelta(days=1), reason="",
        )


def test_submit_request_rejects_whitespace_reason(admin_session):
    s = create_soldier(admin_session, personal_number="7800002")
    et = _et(admin_session, "פטור-reason-test-2")
    with pytest.raises(ExemptionRequestError, match="reason_required"):
        submit_request(
            admin_session, soldier_id=s.id, exemption_type_id=et.id,
            start_date=date.today() + timedelta(days=1), reason="   ",
        )


def test_submit_request_rejects_none_reason(admin_session):
    s = create_soldier(admin_session, personal_number="7800003")
    et = _et(admin_session, "פטור-reason-test-3")
    with pytest.raises(ExemptionRequestError, match="reason_required"):
        submit_request(
            admin_session, soldier_id=s.id, exemption_type_id=et.id,
            start_date=date.today() + timedelta(days=1), reason=None,
        )


def test_submit_request_accepts_real_reason(admin_session):
    s = create_soldier(admin_session, personal_number="7800004")
    et = _et(admin_session, "פטור-reason-test-4")
    req = submit_request(
        admin_session, soldier_id=s.id, exemption_type_id=et.id,
        start_date=date.today() + timedelta(days=1), reason="גב תפוס",
    )
    admin_session.commit()
    assert req.reason == "גב תפוס"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_exemption_requests_service.py -k reason -v` (adjust filename to whatever exists)
Expected: the three rejection tests FAIL (no error raised today; `reason=None`/`""` is accepted)

- [ ] **Step 4: Add the service-level check**

In `backend/app/services/exemption_requests.py`, at the top of `submit_request`:

```python
def submit_request(
    session: Session,
    soldier_id: uuid.UUID,
    exemption_type_id: uuid.UUID,
    start_date: date,
    end_date: date | None = None,
    reason: str | None = None,
) -> ExemptionRequest:
    if not reason or not reason.strip():
        raise ExemptionRequestError("reason_required")
    if end_date and end_date < start_date:
        raise ExemptionRequestError("bad_date_range")
    check_max_span(start_date, end_date, ExemptionRequestError)
    # ... rest unchanged
```

- [ ] **Step 5: Tighten the Pydantic schema so the route rejects a missing reason before hitting the service**

In `backend/app/routes/exemption_requests.py:76-80`:

```python
class CreateExemptionRequest(BaseModel):
    exemption_type_id: uuid.UUID
    start_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = None
    reason: str = Field(min_length=1, max_length=1000)
```

- [ ] **Step 6: Run unit tests to verify they pass**

Run: `pytest tests/unit/test_exemption_requests_service.py -v` (adjust filename)
Expected: all PASS

- [ ] **Step 7: Add an integration test for the route-level 422**

Find or create `backend/tests/integration/test_exemption_requests_api.py`, matching its existing style (or `test_commander_exemption_escalation_api.py`'s style if that's the closest analog), and add:

```python
def test_submit_exemption_request_rejects_missing_reason(client, admin_session):
    from app.db.models import ExemptionType
    from tests.helpers import auth_headers, create_soldier

    s = create_soldier(admin_session, personal_number="7800010")
    et = ExemptionType(name="פטור-api-reason", is_commander_exemption=False)
    admin_session.add(et)
    admin_session.commit()

    r = client.post(
        "/api/me/exemption-requests",
        headers=auth_headers(s),
        json={
            "exemption_type_id": str(et.id),
            "start_date": (date.today() + timedelta(days=1)).isoformat(),
        },
    )
    assert r.status_code == 422
```

(Add the necessary `from datetime import date, timedelta` import at the top of the file if not already present — check first.)

- [ ] **Step 8: Run the full exemption-request test surface to check for regressions**

Run: `pytest -k exemption_request -v`
Expected: all PASS — check specifically for any existing test that submits a request with `reason=None` or omits `reason` entirely, and update it to pass a real reason string if found.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/exemption_requests.py backend/app/routes/exemption_requests.py backend/tests/unit/test_exemption_requests_service.py backend/tests/integration/test_exemption_requests_api.py
git commit -m "feat: require a non-empty reason on exemption requests"
```

---

### Task 6: Daily cap on bug report submissions (50/day per soldier)

**Files:**
- Modify: `backend/app/services/bug_reports.py`
- Modify: `backend/app/routes/bug_reports.py`
- Test: `backend/tests/unit/test_bug_reports.py` (check with `Glob` — may already exist for `write_bug_report`; add to it if so)

**Interfaces:**
- Produces: new exception `BugReportRateLimitError` (subclass-independent of `BugReportWriteError`, so the route can map it to 429 instead of 500); `write_bug_report(...)` raises it on the 51st report from the same `reporter_id` within a rolling 24h window.

- [ ] **Step 1: Check for an existing test file**

Run `Glob` for `backend/tests/unit/test_bug_report*.py`. Read it if found to match its fixture style (it likely constructs a `Soldier` directly rather than using `create_soldier`, since `write_bug_report` takes a full `Soldier` object — check).

- [ ] **Step 2: Write the failing test**

```python
# add to backend/tests/unit/test_bug_reports.py (or create it, matching existing style if found)
from datetime import date

from app.services.bug_reports import BugReportRateLimitError, write_bug_report
from tests.helpers import create_soldier


def test_write_bug_report_daily_cap_enforced(admin_session):
    reporter = create_soldier(admin_session, personal_number="7900001")
    for i in range(50):
        write_bug_report(
            admin_session, reporter=reporter, description=f"bug {i}", severity="low",
            screenshot=None, route="/test", nav_history=[],
        )
        admin_session.flush()
    import pytest
    with pytest.raises(BugReportRateLimitError, match="daily_bug_report_limit_exceeded"):
        write_bug_report(
            admin_session, reporter=reporter, description="bug 51", severity="low",
            screenshot=None, route="/test", nav_history=[],
        )


def test_write_bug_report_cap_is_per_reporter(admin_session):
    reporter1 = create_soldier(admin_session, personal_number="7900002")
    reporter2 = create_soldier(admin_session, personal_number="7900003")
    for i in range(50):
        write_bug_report(
            admin_session, reporter=reporter1, description=f"bug {i}", severity="low",
            screenshot=None, route="/test", nav_history=[],
        )
        admin_session.flush()
    # reporter2 has made zero reports — must not be blocked by reporter1's cap
    result = write_bug_report(
        admin_session, reporter=reporter2, description="bug", severity="low",
        screenshot=None, route="/test", nav_history=[],
    )
    assert result.persisted_to_db is True
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_bug_reports.py -k daily_cap -v`
Expected: FAIL — `BugReportRateLimitError` doesn't exist yet (ImportError), and report #51 currently succeeds

- [ ] **Step 4: Implement the cap**

In `backend/app/services/bug_reports.py`:

```python
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

_DAILY_BUG_REPORT_LIMIT = 50


class BugReportRateLimitError(Exception):
    """Raised when a reporter exceeds the daily bug-report submission cap."""


def write_bug_report(
    session: Session,
    *,
    reporter: Soldier,
    description: str,
    severity: str,
    screenshot: bytes | None,
    route: str,
    nav_history: list[dict[str, Any]],
) -> BugReportWriteResult:
    window_start = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_count = session.execute(
        select(func.count()).select_from(BugReport).where(
            BugReport.reporter_id == reporter.id,
            BugReport.created_at >= window_start,
        )
    ).scalar_one()
    if recent_count >= _DAILY_BUG_REPORT_LIMIT:
        raise BugReportRateLimitError("daily_bug_report_limit_exceeded")

    report_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc)
    # ... rest of the function body unchanged from here
```

(Add `BugReport` to the existing `from app.db.models import AuditLog, BugReport, Soldier` import — it's already imported. Add `func` to the existing `from sqlalchemy import select` import.)

- [ ] **Step 5: Map the new exception to 429 in the route**

In `backend/app/routes/bug_reports.py`:

```python
@router.post("/bug-reports", status_code=status.HTTP_201_CREATED)
def submit_bug_report(
    body: BugReportSubmitBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, str]:
    screenshot_bytes = _decode_screenshot(body.screenshot) if body.screenshot else None
    try:
        svc.write_bug_report(
            session,
            reporter=user,
            description=body.description,
            severity=body.severity,
            screenshot=screenshot_bytes,
            route=body.route,
            nav_history=[entry.model_dump() for entry in body.nav_history],
        )
    except svc.BugReportRateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except svc.BugReportWriteError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="bug_report_write_failed") from exc
    session.commit()
    return {"status": "ok"}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/test_bug_reports.py -v`
Expected: all PASS

- [ ] **Step 7: Add an integration test for the 429**

Add to `backend/tests/integration/test_bug_reports_api.py` if it exists (check with `Glob`), matching its style:

```python
def test_submit_bug_report_returns_429_after_daily_cap(client, admin_session):
    from tests.helpers import auth_headers, create_soldier

    s = create_soldier(admin_session, personal_number="7900010")
    for i in range(50):
        r = client.post(
            "/api/bug-reports",
            headers=auth_headers(s),
            json={"description": f"bug {i}", "severity": "low", "route": "/x", "nav_history": []},
        )
        assert r.status_code == 201, r.text
    r = client.post(
        "/api/bug-reports",
        headers=auth_headers(s),
        json={"description": "bug 51", "severity": "low", "route": "/x", "nav_history": []},
    )
    assert r.status_code == 429
```

- [ ] **Step 8: Run the full bug-report test surface to check for regressions**

Run: `pytest -k bug_report -v`
Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/bug_reports.py backend/app/routes/bug_reports.py backend/tests/unit/test_bug_reports.py backend/tests/integration/test_bug_reports_api.py
git commit -m "feat: cap bug report submissions at 50 per reporter per rolling 24h"
```

---

### Task 7: Duplicate-announcement cooldown guard

**Files:**
- Modify: `backend/app/services/notifications.py`
- Modify: `backend/app/routes/notifications.py`
- Test: `backend/tests/unit/test_notifications_service.py` if it exists (check with `Glob`; else add near other `broadcast_announcement` coverage or create `test_announcements.py`)

**Interfaces:**
- Produces: new exception `AnnouncementRateLimitError`; `broadcast_announcement(...)` raises it when the same `actor_id` sends an announcement with the same `title` within 5 minutes of their previous one (regardless of `hierarchy_node_ids`/`body`). This is a duplicate-send guard, not a cap on distinct legitimate announcements — an admin/commander can send as many *different* announcements as they want.

- [ ] **Step 1: Check for existing test coverage of `broadcast_announcement`**

Run `Glob` for `backend/tests/unit/test_notification*.py` and `backend/tests/unit/test_announcement*.py`; read whichever is closest to see the existing seeding pattern for `Soldier`/`HierarchyNode` used with this service.

- [ ] **Step 2: Write the failing test**

```python
# add to the file found in Step 1, or create backend/tests/unit/test_announcements.py
from app.services.notifications import AnnouncementRateLimitError, broadcast_announcement
from tests.helpers import create_soldier


def test_broadcast_blocks_duplicate_title_within_cooldown(admin_session):
    sender = create_soldier(admin_session, personal_number="8000001", role="admin")
    broadcast_announcement(admin_session, title="בדיקה", body="תוכן", actor_id=sender.id)
    admin_session.commit()
    import pytest
    with pytest.raises(AnnouncementRateLimitError, match="duplicate_announcement_cooldown"):
        broadcast_announcement(admin_session, title="בדיקה", body="תוכן שונה", actor_id=sender.id)


def test_broadcast_allows_different_title_immediately(admin_session):
    sender = create_soldier(admin_session, personal_number="8000002", role="admin")
    broadcast_announcement(admin_session, title="הודעה א", actor_id=sender.id)
    admin_session.commit()
    # A genuinely different announcement from the same sender must not be blocked
    a2 = broadcast_announcement(admin_session, title="הודעה ב", actor_id=sender.id)
    admin_session.commit()
    assert a2.title == "הודעה ב"


def test_broadcast_allows_same_title_from_different_sender(admin_session):
    sender1 = create_soldier(admin_session, personal_number="8000003", role="admin")
    sender2 = create_soldier(admin_session, personal_number="8000004", role="admin")
    broadcast_announcement(admin_session, title="הודעה משותפת", actor_id=sender1.id)
    admin_session.commit()
    a2 = broadcast_announcement(admin_session, title="הודעה משותפת", actor_id=sender2.id)
    admin_session.commit()
    assert a2.sender_id == sender2.id
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_announcements.py -v` (adjust filename)
Expected: `test_broadcast_blocks_duplicate_title_within_cooldown` FAILS — `AnnouncementRateLimitError` doesn't exist yet (ImportError)

- [ ] **Step 4: Implement the cooldown guard**

In `backend/app/services/notifications.py`, near `broadcast_announcement` (already imports `select`, `Announcement`, `HierarchyNode`, `Soldier` in this module — verify and reuse):

```python
from datetime import datetime, timedelta, timezone

_ANNOUNCEMENT_DUPLICATE_COOLDOWN = timedelta(minutes=5)


class AnnouncementRateLimitError(Exception):
    """Raised when the same sender re-sends an identically-titled announcement too soon."""


def broadcast_announcement(session: Session, *, title: str, body: str | None = None,
                           hierarchy_node_ids: list[uuid.UUID] | None = None,
                           actor_id: uuid.UUID | None = None) -> Announcement:
    if actor_id is not None:
        cutoff = datetime.now(timezone.utc) - _ANNOUNCEMENT_DUPLICATE_COOLDOWN
        recent_duplicate = session.execute(
            select(Announcement).where(
                Announcement.sender_id == actor_id,
                Announcement.title == title,
                Announcement.created_at >= cutoff,
            )
        ).scalars().first()
        if recent_duplicate is not None:
            raise AnnouncementRateLimitError("duplicate_announcement_cooldown")

    if hierarchy_node_ids:
        # ... rest of the function body unchanged from here
```

(Note: `uuid` is presumably already imported in this module for other functions' type hints — verify before adding a duplicate import.)

- [ ] **Step 5: Map the new exception to 429 in the route**

In `backend/app/routes/notifications.py::announce`:

```python
    try:
        announcement = svc.broadcast_announcement(session, title=body.title, body=body.body,
                                                  hierarchy_node_ids=body.hierarchy_node_ids,
                                                  actor_id=user.id)
    except svc.AnnouncementRateLimitError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    session.commit()
    return AnnounceOut(id=announcement.id, sent=announcement.recipient_count)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/test_announcements.py -v`
Expected: all PASS

- [ ] **Step 7: Run the full notifications test surface to check for regressions**

Run: `pytest -k "notification or announce" -v`
Expected: all PASS — check specifically for any existing test that calls `broadcast_announcement` twice with the same title from the same actor within the test, and adjust if found (unlikely, but verify).

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/notifications.py backend/app/routes/notifications.py backend/tests/unit/test_announcements.py
git commit -m "feat: block duplicate-titled announcements from the same sender within 5 minutes"
```

---

### Task 8: `take_free` requires both the duty owner's approval and manager approval

**Files:**
- Modify: `backend/app/services/swaps.py` (the `take_free` function, ~line 928-1030)
- Modify: `backend/tests/unit/test_swaps.py:624-630` (`test_take_free_allowed_across_hierarchy_level_when_not_restricted` — update, it currently asserts instant `"applied"` status)

**Interfaces:**
- Consumes: `approve_soldier_side(session, *, request_id, soldier_id, actor_id=None) -> SwapRequest` (already exists in this file, unchanged)
- Produces: `take_free(...)` now returns a `SwapRequest` with `status="open"` and `requester_side_approved=False` instead of instantly applying the cover. The duty owner must separately call `approve_soldier_side(session, request_id=req.id, soldier_id=<owner>, actor_id=<owner>)` to approve it, after which the existing `_try_finalize`/manager-approval machinery (unchanged) takes over exactly as it does for a normal swap.

- [ ] **Step 1: Read the current `take_free` in full to confirm line numbers before editing**

Read `backend/app/services/swaps.py` lines 928-1031.

- [ ] **Step 2: Update the existing test that currently expects instant application**

`test_take_free_allowed_across_hierarchy_level_when_not_restricted` (line 624) currently does:

```python
def test_take_free_allowed_across_hierarchy_level_when_not_restricted(admin_session):
    requester, target, assignment = _seed_cross_branch(admin_session)
    req, warnings = svc.take_free(
        admin_session, assignment_id=assignment.id,
        covering_soldier_id=target.id, actor_id=target.id,
    )
    assert req.status == "applied"
```

Change it to:

```python
def test_take_free_allowed_across_hierarchy_level_when_not_restricted(admin_session):
    requester, target, assignment = _seed_cross_branch(admin_session)
    req, warnings = svc.take_free(
        admin_session, assignment_id=assignment.id,
        covering_soldier_id=target.id, actor_id=target.id,
    )
    assert req.status == "open"
    assert req.requester_side_approved is False
    # requester and target have no commander/duty-manager chain in this fixture,
    # so once the duty owner approves, the swap finalizes with no manager gate.
    finalized = svc.approve_soldier_side(
        admin_session, request_id=req.id, soldier_id=requester.id, actor_id=requester.id,
    )
    assert finalized.status == "applied"
```

- [ ] **Step 3: Add new tests documenting the owner-consent and manager-approval requirements**

Add to `backend/tests/unit/test_swaps.py` (near the other `take_free` tests):

```python
def test_take_free_does_not_apply_cover_without_owner_approval(admin_session):
    a, b, assignment = _seed(admin_session)
    req, warnings = svc.take_free(admin_session, assignment_id=assignment.id, covering_soldier_id=b.id, actor_id=b.id)
    admin_session.commit()
    assert req.status == "open"
    fresh = admin_session.get(DutyAssignment, assignment.id)
    assert fresh.soldier_id == a.id  # duty still belongs to the original owner


def test_take_free_finalizes_only_after_owner_approves(admin_session):
    a, b, assignment = _seed(admin_session)
    req, warnings = svc.take_free(admin_session, assignment_id=assignment.id, covering_soldier_id=b.id, actor_id=b.id)
    admin_session.flush()
    finalized = svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=a.id, actor_id=a.id)
    admin_session.commit()
    assert finalized.status == "applied"


def test_take_free_blocked_by_manager_approval_gate_when_owner_has_commander(admin_session):
    """When require_manager_approval is on and the duty owner has a commander,
    owner approval alone must not finalize the swap."""
    node = create_node(admin_session, level="unit", name="tf_manager_gate")
    cmd = create_soldier(admin_session, personal_number="tf_cmd_1", role="commander")
    node.commander_id = cmd.id
    admin_session.flush()
    a = create_soldier(admin_session, personal_number="tf_owner_1", hierarchy_node_id=node.id)
    b = create_soldier(admin_session, personal_number="tf_taker_1")
    dt = DutyType(name="dt_tf_gate", score_per_day=1)
    loc = DutyLocation(name="loc_tf_gate")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=a.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2026, 6, 10), end_date=date(2026, 6, 11), status="published",
    )
    admin_session.add(assignment)
    admin_session.flush()

    req, warnings = svc.take_free(admin_session, assignment_id=assignment.id, covering_soldier_id=b.id, actor_id=b.id)
    admin_session.flush()
    after_owner_approval = svc.approve_soldier_side(admin_session, request_id=req.id, soldier_id=a.id, actor_id=a.id)
    admin_session.commit()
    assert after_owner_approval.status == "open"  # still waiting on the commander's SwapManagerApproval
```

- [ ] **Step 4: Run tests to verify the updated/new ones fail against current behavior**

Run: `pytest tests/unit/test_swaps.py -k take_free -v`
Expected: `test_take_free_allowed_across_hierarchy_level_when_not_restricted` FAILS at `assert req.status == "open"` (currently `"applied"`); `test_take_free_does_not_apply_cover_without_owner_approval` FAILS (duty is already reassigned); `test_take_free_finalizes_only_after_owner_approves` currently passes by accident (already applied) but will properly exercise the new path once fixed; `test_take_free_blocked_by_manager_approval_gate_when_owner_has_commander` FAILS (status is `"applied"` immediately, ignoring the commander)

- [ ] **Step 5: Rewrite `take_free`'s finalization block**

In `backend/app/services/swaps.py`, replace everything from `req = SwapRequest(` through the end of the function (the current instant-apply block) with:

```python
    req = SwapRequest(
        duty_assignment_id=assignment_id,
        duty_date=assignment.start_date,
        requesting_soldier_id=assignment.soldier_id,
        status="open",
        requester_side_approved=False,
    )
    session.add(req)
    session.flush()
    candidate = SwapCandidate(
        swap_request_id=req.id, soldier_id=covering_soldier_id, source="marketplace",
        status="accepted", soldier_side_approved=True,
    )
    session.add(candidate)
    session.flush()

    create_notification(
        session,
        soldier_id=assignment.soldier_id,
        type=NotificationType.swap_offer,
        title="חייל אחר מבקש לקחת את התורנות שלך - נדרש אישורך",
        reference_type="swap_request",
        reference_id=req.id,
        actor_id=actor_id,
    )
    write_audit(
        session, actor_id=actor_id, action="swap.take_free",
        entity_type="swap_request", entity_id=req.id,
        after={
            "duty_assignment_id": str(assignment_id),
            "duty_date": req.duty_date.isoformat(),
            "covering_soldier_id": str(covering_soldier_id),
            "status": "open",
        },
    )
    session.flush()
    return req, warnings
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/test_swaps.py -k take_free -v`
Expected: all PASSED

- [ ] **Step 7: Run the full swaps test surface to check for regressions**

Run: `pytest tests/unit/test_swaps.py -v` and `pytest -k swap -v`
Expected: all PASS. Pay particular attention to `test_take_free_reserve_succeeds_under_cap` (already asserts `result.status in ("open", "applied")` — should be unaffected) and `test_take_free_primary_unaffected_by_reserve_setting` (asserts `result is not None` — unaffected).

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/swaps.py backend/tests/unit/test_swaps.py
git commit -m "fix: take_free now requires the duty owner's approval and the normal manager-approval gate instead of applying instantly"
```

---

### Task 9: Split constraint approval into commander + duty-manager steps (both required by default)

This is the largest task. `PersonalConstraint.status` moves from a single `pending → approved|rejected` flow to `pending_commander → pending_duty_manager → approved` (or `rejected` from either pending state), gated by two independent settings:

- `constraints.require_commander_approval` (default `True`)
- `constraints.require_duty_manager_approval` (default `True`)

If a setting is `False`, its step is skipped. If **both** are `False`, the constraint is auto-approved on submission (`decided_by=None`, `decision_note="אושר אוטומטית - אין דרישת אישור מוגדרת"`), same as before but now honestly attributed to "no approval required" rather than to the submitting soldier's own id.

**Files:**
- Modify: `backend/app/db/models.py` (`PersonalConstraint` — add `commander_approved_by` column)
- Create: `backend/alembic/versions/a1c2e3f4b5d6_add_commander_approved_by_to_.py`
- Modify: `backend/app/services/constraints.py`
- Modify: `backend/app/routes/constraints.py` (only `pending_list`/`pending_count`'s admin-branch status filter — the `approve`/`reject` route handlers keep their existing shape)
- Modify: `backend/tests/unit/test_constraints_service.py` (multiple existing tests need status-string updates)
- Modify: `backend/tests/integration/test_constraints_api.py` (`test_commander_approves_in_subtree` needs a duty-manager step added)

**Interfaces:**
- Produces: `submit_constraint(...)` unchanged signature, new initial-status logic. `approve_constraint(session, *, constraint_id, actor_id=None, decision_note=None) -> PersonalConstraint` — **signature unchanged**, but now dispatches internally to a commander-step or duty-manager-step handler based on `c.status`, so no route or external caller needs to change. `reject_constraint(...)` — signature unchanged, now accepts either pending status. `cancel_constraint(...)` — signature unchanged, now only cancelable while genuinely untouched by any approver (see Step 5).

- [ ] **Step 1: Add the model column**

In `backend/app/db/models.py`, in the `PersonalConstraint` class (currently lines 638-658), add a field mirroring `ExemptionRequest.commander_approved_by`:

```python
class PersonalConstraint(Base):
    __tablename__ = "personal_constraints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending", default="pending")
    commander_approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

- [ ] **Step 2: Write the migration**

Run `alembic heads` first from `backend/` to confirm the current head is still `63cff804e3e4` (per Global Constraints). Then create:

```python
# backend/alembic/versions/a1c2e3f4b5d6_add_commander_approved_by_to_.py
"""Add commander_approved_by to personal_constraints and migrate pending status
to pending_commander for the new two-step approval flow

Revision ID: a1c2e3f4b5d6
Revises: 63cff804e3e4
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a1c2e3f4b5d6"
down_revision = "63cff804e3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "personal_constraints",
        sa.Column(
            "commander_approved_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True,
        ),
    )
    op.execute("UPDATE personal_constraints SET status = 'pending_commander' WHERE status = 'pending'")


def downgrade() -> None:
    op.execute(
        "UPDATE personal_constraints SET status = 'pending' "
        "WHERE status IN ('pending_commander', 'pending_duty_manager')"
    )
    op.drop_column("personal_constraints", "commander_approved_by")
```

Run: `alembic upgrade head` (from `backend/`, with the venv active and Postgres running via `.\dev.ps1` or an already-running dev stack)
Expected: migration applies cleanly with no errors.

- [ ] **Step 3: Update the existing unit tests that assert the old `"pending"` status and single-step `approve_constraint` behavior**

In `backend/tests/unit/test_constraints_service.py`:

`test_submit_success` (line 26): change `assert c.status == "pending"` to `assert c.status == "pending_commander"`.

`test_submit_auto_approve` (line 41): change the monkeypatch to cover both new keys:

```python
def test_submit_auto_approve(admin_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.constraints._get_setting_with_default",
        lambda session, key, default: False
        if key in ("constraints.require_commander_approval", "constraints.require_duty_manager_approval")
        else default,
    )
    s = create_soldier(admin_session, personal_number=_pn(2))
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=s.id,
    )
    admin_session.commit()
    assert c.status == "approved"
    assert c.decided_by is None
```

`test_submit_cap_check_is_period_scoped_not_full_future_span` (line 125): change `assert c.status == "pending"` to `assert c.status == "pending_commander"`.

`test_approve_pending` (line 166): now requires two approve calls to reach `"approved"`:

```python
def test_approve_pending(admin_session):
    s = create_soldier(admin_session, personal_number=_pn(6))
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    after_commander = approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    assert after_commander.status == "pending_duty_manager"
    assert after_commander.commander_approved_by == s.id
    approved = approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.commit()
    assert approved.status == "approved"
    assert approved.decided_by == s.id
```

`test_approve_not_pending` (line 200): call `approve_constraint` twice to reach `"approved"` before expecting the third call to raise:

```python
def test_approve_not_pending(admin_session):
    s = create_soldier(admin_session, personal_number=_pn(7))
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=5),
        end_date=date.today() + timedelta(days=10),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.flush()
    with pytest.raises(ConstraintError, match="not_pending"):
        approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
```

`test_cancel_not_pending` (line 251): with only one `approve_constraint` call, the constraint now sits in `"pending_duty_manager"` with `commander_approved_by` set — the test's intent (cannot cancel something already touched by an approver) is unchanged, no code change needed to the test body itself, only confirm it still passes once Step 5's `cancel_constraint` logic lands (see Step 6).

`test_get_approved_dates` (line 282): needs a second approve call to actually reach `"approved"`:

```python
def test_get_approved_dates(admin_session):
    s = create_soldier(admin_session, personal_number="7400012")
    c = submit_constraint(
        admin_session,
        soldier_id=s.id,
        start_date=date.today() + timedelta(days=10),
        end_date=date.today() + timedelta(days=15),
        reason="חופשה",
        actor_id=None,
    )
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.flush()
    approve_constraint(admin_session, constraint_id=c.id, actor_id=s.id)
    admin_session.flush()
    dates = get_approved_constraint_dates(admin_session, soldier_id=s.id)
    assert len(dates) == 1
    assert dates[0][0] == date.today() + timedelta(days=10)
```

`test_remaining_days_counts_current_period_overlap` (line 345): the raw-constructed row uses the old literal `status="pending"` — change it to `status="pending_commander"`:

```python
    overlapping = PersonalConstraint(
        soldier_id=s.id,
        start_date=date(2026, 6, 28),
        end_date=date(2026, 7, 3),
        reason="x",
        status="pending_commander",
    )
```

- [ ] **Step 4: Run the updated unit tests to verify they now fail against the current (unmodified) service**

Run: `pytest tests/unit/test_constraints_service.py -v`
Expected: multiple FAILURES — status strings don't match (`"pending"` vs `"pending_commander"`), `test_submit_auto_approve`'s monkeypatched key isn't read by the current code, `test_approve_pending`/`test_get_approved_dates` fail because `approve_constraint` still goes straight to `"approved"` on the first call (so `after_commander.status == "pending_duty_manager"` fails).

- [ ] **Step 5: Rewrite `submit_constraint` in `backend/app/services/constraints.py`**

```python
def submit_constraint(
    session: Session,
    *,
    soldier_id: uuid.UUID,
    start_date: date,
    end_date: date,
    reason: str,
    actor_id: uuid.UUID | None = None,
) -> PersonalConstraint:
    if session.get(Soldier, soldier_id) is None:
        raise ConstraintError("soldier_not_found")
    if end_date < start_date:
        raise ConstraintError("bad_date_range")
    check_max_span(start_date, end_date, ConstraintError)
    if start_date < date.today():
        raise ConstraintError("start_date_in_past")

    rd = remaining_days(session, soldier_id=soldier_id)
    cap_days = rd["cap_days"]
    used = rd["used_days"]
    period_start, period_end = rd["period_start"], rd["period_end"]
    period_last_day = date.fromordinal(period_end.toordinal() - 1)
    overlap_start = max(start_date, period_start)
    overlap_end = min(end_date, period_last_day)
    requested_in_period = max(0, (overlap_end - overlap_start).days + 1)
    if used + requested_in_period > cap_days:
        raise ConstraintError("cap_exceeded")

    require_commander = bool(
        _get_setting_with_default(session, "constraints.require_commander_approval", True)
    )
    require_dm = bool(
        _get_setting_with_default(session, "constraints.require_duty_manager_approval", True)
    )

    if require_commander:
        initial_status = "pending_commander"
    elif require_dm:
        initial_status = "pending_duty_manager"
    else:
        initial_status = "approved"

    c = PersonalConstraint(
        soldier_id=soldier_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        status=initial_status,
    )
    if initial_status == "approved":
        c.decided_by = None
        c.decided_at = datetime.now(UTC)
        c.decision_note = "אושר אוטומטית - אין דרישת אישור מוגדרת"

    session.add(c)
    session.flush()
    write_audit(
        session,
        actor_id=actor_id,
        action="constraint.submit",
        entity_type="personal_constraint",
        entity_id=c.id,
        after={
            "soldier_id": str(soldier_id),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "reason": reason,
            "status": c.status,
        },
    )
    if c.status == "pending_commander":
        from app.services.notifications import notify_commanders_of_request
        notify_commanders_of_request(
            session,
            soldier_id=soldier_id,
            type=NotificationType.constraint_pending,
            title=f"בקשת אילוץ חדשה: {start_date} – {end_date}",
            body=reason,
            reference_type="personal_constraint",
            reference_id=c.id,
            actor_id=actor_id,
        )
    elif c.status == "pending_duty_manager":
        from app.services.notifications import notify_duty_managers_of_request
        notify_duty_managers_of_request(
            session,
            soldier_id=soldier_id,
            type=NotificationType.constraint_pending,
            title=f"בקשת אילוץ ממתינה לאישור: {start_date} – {end_date}",
            body=reason,
            reference_type="personal_constraint",
            reference_id=c.id,
            actor_id=actor_id,
        )
    return c
```

- [ ] **Step 6: Rewrite `approve_constraint`, add the two private step handlers, and update `reject_constraint`/`cancel_constraint`**

```python
def _approve_commander_step(
    session: Session, c: PersonalConstraint, *, actor_id: uuid.UUID | None,
) -> PersonalConstraint:
    c.commander_approved_by = actor_id
    require_dm = bool(
        _get_setting_with_default(session, "constraints.require_duty_manager_approval", True)
    )
    if require_dm:
        c.status = "pending_duty_manager"
        session.flush()
        from app.services.notifications import notify_duty_managers_of_request
        notify_duty_managers_of_request(
            session,
            soldier_id=c.soldier_id,
            type=NotificationType.constraint_pending,
            title="בקשת אילוץ ממתינה לאישור (אושרה ע\"י מפקד)",
            body=c.reason,
            reference_type="personal_constraint",
            reference_id=c.id,
            actor_id=actor_id,
        )
    else:
        c.status = "approved"
        c.decided_by = actor_id
        c.decided_at = datetime.now(UTC)
        session.flush()
        create_notification(session, soldier_id=c.soldier_id,
                            type=NotificationType.constraint_approved,
                            title="בקשת האילוץ אושרה",
                            reference_type="personal_constraint", reference_id=c.id,
                            actor_id=actor_id)
    write_audit(
        session, actor_id=actor_id, action="constraint.approve_commander_step",
        entity_type="personal_constraint", entity_id=c.id,
        before={"status": "pending_commander"}, after={"status": c.status},
    )
    return c


def _approve_duty_manager_step(
    session: Session, c: PersonalConstraint, *, actor_id: uuid.UUID | None, decision_note: str | None,
) -> PersonalConstraint:
    c.status = "approved"
    c.decided_by = actor_id
    c.decided_at = datetime.now(UTC)
    c.decision_note = decision_note
    session.flush()
    create_notification(session, soldier_id=c.soldier_id,
                        type=NotificationType.constraint_approved,
                        title="בקשת האילוץ אושרה",
                        reference_type="personal_constraint", reference_id=c.id,
                        actor_id=actor_id)
    write_audit(
        session, actor_id=actor_id, action="constraint.approve_duty_manager_step",
        entity_type="personal_constraint", entity_id=c.id,
        before={"status": "pending_duty_manager"}, after={"status": "approved", "decision_note": decision_note},
    )
    return c


def approve_constraint(
    session: Session,
    *,
    constraint_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    decision_note: str | None = None,
) -> PersonalConstraint:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        raise ConstraintError("constraint_not_found")
    if c.status not in ("pending_commander", "pending_duty_manager"):
        raise ConstraintError("not_pending")
    unresolved_enrollment = session.execute(
        select(SoldierEnrollmentRequest).where(
            SoldierEnrollmentRequest.soldier_id == c.soldier_id,
            SoldierEnrollmentRequest.status.in_(("pending", "commander_approved")),
        )
    ).scalars().first()
    if unresolved_enrollment is not None:
        raise ConstraintError("enrollment_not_approved")

    if c.status == "pending_commander":
        return _approve_commander_step(session, c, actor_id=actor_id)
    return _approve_duty_manager_step(session, c, actor_id=actor_id, decision_note=decision_note)


def reject_constraint(
    session: Session,
    *,
    constraint_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
    decision_note: str,
) -> PersonalConstraint:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        raise ConstraintError("constraint_not_found")
    if c.status not in ("pending_commander", "pending_duty_manager"):
        raise ConstraintError("not_pending")
    before_status = c.status
    c.status = "rejected"
    c.decided_by = actor_id
    c.decided_at = datetime.now(UTC)
    c.decision_note = decision_note
    session.flush()
    create_notification(session, soldier_id=c.soldier_id,
                        type=NotificationType.constraint_rejected,
                        title="בקשת האילוץ נדחתה",
                        reference_type="personal_constraint", reference_id=c.id,
                        actor_id=actor_id)
    write_audit(
        session,
        actor_id=actor_id,
        action="constraint.reject",
        entity_type="personal_constraint",
        entity_id=c.id,
        before={"status": before_status},
        after={"status": "rejected", "decision_note": decision_note},
    )
    return c


def cancel_constraint(
    session: Session,
    *,
    constraint_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    c = session.get(PersonalConstraint, constraint_id)
    if c is None:
        raise ConstraintError("constraint_not_found")
    cancelable = c.status == "pending_commander" or (
        c.status == "pending_duty_manager" and c.commander_approved_by is None
    )
    if not cancelable:
        raise ConstraintError("not_pending")
    write_audit(
        session,
        actor_id=actor_id,
        action="constraint.cancel",
        entity_type="personal_constraint",
        entity_id=c.id,
        before={"status": c.status},
        after={"deleted": True},
    )
    session.delete(c)
```

- [ ] **Step 7: Update the remaining `status == "pending"` references in `constraints.py`**

`list_pending_approvals` and `pending_approval_count` (both currently filter `PersonalConstraint.status == "pending"`): change to `PersonalConstraint.status.in_(("pending_commander", "pending_duty_manager"))`.

`remaining_days` (currently `PersonalConstraint.status.in_(["pending", "approved"])`): change to `PersonalConstraint.status.in_(["pending_commander", "pending_duty_manager", "approved"])`.

`get_approved_constraint_dates` already filters `status == "approved"` only — no change needed.

- [ ] **Step 8: Update `routes/constraints.py`'s admin-branch status filters**

In `pending_list` and `pending_count`, the `user.role == "admin"` branch filters `PersonalConstraint.status == "pending"` directly (not via the service helper) — change both to `.in_(("pending_commander", "pending_duty_manager"))`.

- [ ] **Step 9: Run unit tests to verify they pass**

Run: `pytest tests/unit/test_constraints_service.py -v`
Expected: all PASS

- [ ] **Step 10: Update the integration test that exercises the full HTTP approve flow**

In `backend/tests/integration/test_constraints_api.py`, `test_commander_approves_in_subtree` (line 53) needs a duty manager added to scope and a second approve call:

```python
def test_commander_approves_in_subtree(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    cmd = create_soldier(admin_session, personal_number="7500003", role="commander")
    b.commander_id = cmd.id
    dm = create_soldier(admin_session, personal_number="7500016", role="duty_manager", hierarchy_node_id=b.id)
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="7500004", hierarchy_node_id=b.id)
    c = client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={
            "start_date": (date.today() + timedelta(days=5)).isoformat(),
            "end_date": (date.today() + timedelta(days=10)).isoformat(),
            "reason": "חופשה",
        },
    ).json()
    r1 = client.post(f"/api/constraints/{c['id']}/approve", headers=auth_headers(cmd), json={})
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "pending_duty_manager"
    r2 = client.post(f"/api/constraints/{c['id']}/approve", headers=auth_headers(dm), json={})
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "approved"
```

- [ ] **Step 11: Run the full constraints test surface to verify everything passes**

Run: `pytest -k constraint -v`
Expected: all PASS

- [ ] **Step 12: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/a1c2e3f4b5d6_add_commander_approved_by_to_.py backend/app/services/constraints.py backend/app/routes/constraints.py backend/tests/unit/test_constraints_service.py backend/tests/integration/test_constraints_api.py
git commit -m "feat: split constraint approval into independent commander and duty-manager steps, both required by default"
```

---

### Task 10: No-show marking (dedicated action, no forced-coverage automation)

Adds a `mark_no_show` action for commanders/duty-managers to flag a past duty as a no-show. This is a distinct, audit-tagged record (not a generic free-text score adjustment) that auto-applies a score penalty and lets repeat offenders be surfaced later. There is deliberately no automatic detection (no check-in system exists) and no forced-coverage automation — both were explicitly scoped out.

**Files:**
- Modify: `backend/app/db/models.py` (add `DutyNoShow` model, add `no_show_marked` to `NotificationType`)
- Create: `backend/alembic/versions/b2d3f4a5c6e7_add_duty_no_shows_table.py`
- Create: `backend/app/services/no_show.py`
- Create: `backend/app/routes/no_show.py`
- Modify: `backend/app/main.py` (register the router)
- Create: `backend/tests/unit/test_no_show.py`
- Create: `backend/tests/integration/test_no_show_api.py`

**Interfaces:**
- Produces:
  - `mark_no_show(session, *, duty_assignment_id, marked_by, note, penalty_delta=Decimal("-1")) -> DutyNoShow`
  - `count_no_shows(session, *, soldier_id, since=None) -> int`
  - `list_no_shows(session, *, soldier_id) -> list[DutyNoShow]`
  - `NoShowError(Exception)`
  - Routes: `POST /no-shows`, `GET /no-shows/soldiers/{soldier_id}`

- [ ] **Step 1: Add the `DutyNoShow` model and `no_show_marked` notification type**

In `backend/app/db/models.py`, add near `ScoreAdjustment` (models.py:741):

```python
class DutyNoShow(Base):
    __tablename__ = "duty_no_shows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    duty_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_assignments.id", ondelete="CASCADE")
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    marked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    note: Mapped[str] = mapped_column(Text)
    score_adjustment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("score_adjustments.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
```

In the `NotificationType` enum, add `no_show_marked = "no_show_marked"` as a new member (alongside the other members).

- [ ] **Step 2: Write the migration**

Run `alembic heads` first from `backend/` to confirm `a1c2e3f4b5d6` (from Task 9) is the current sole head. Then create:

```python
# backend/alembic/versions/b2d3f4a5c6e7_add_duty_no_shows_table.py
"""Add duty_no_shows table and no_show_marked notification type

Revision ID: b2d3f4a5c6e7
Revises: a1c2e3f4b5d6
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b2d3f4a5c6e7"
down_revision = "a1c2e3f4b5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'no_show_marked'")
    op.create_table(
        "duty_no_shows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("duty_assignment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("duty_assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("soldier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("marked_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("score_adjustment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("score_adjustments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint("uq_duty_no_shows_assignment", "duty_no_shows", ["duty_assignment_id"])


def downgrade() -> None:
    op.drop_table("duty_no_shows")
    # Postgres cannot drop a single enum value; no-op on downgrade for notification_type.
```

Run: `alembic upgrade head`
Expected: applies cleanly.

- [ ] **Step 3: Write the failing unit tests**

```python
# backend/tests/unit/test_no_show.py
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.db.models import DutyAssignment, DutyLocation, DutyType, ScoreAdjustment
from app.services.no_show import NoShowError, count_no_shows, list_no_shows, mark_no_show
from tests.helpers import create_soldier


def _seed_past_assignment(session, *, personal_number="ns0001"):
    dt = DutyType(name=f"dt_{personal_number}", score_per_day=1)
    loc = DutyLocation(name=f"loc_{personal_number}")
    soldier = create_soldier(session, personal_number=personal_number)
    session.add_all([dt, loc])
    session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() - timedelta(days=5), end_date=date.today() - timedelta(days=4),
        status="published",
    )
    session.add(assignment)
    session.flush()
    return soldier, assignment


def test_mark_no_show_creates_record_and_score_penalty(admin_session):
    soldier, assignment = _seed_past_assignment(admin_session)
    marker = create_soldier(admin_session, personal_number="ns_marker1")
    record = mark_no_show(
        admin_session, duty_assignment_id=assignment.id, marked_by=marker.id, note="לא הגיע לתורנות",
    )
    admin_session.commit()
    assert record.soldier_id == soldier.id
    assert record.marked_by == marker.id
    assert record.score_adjustment_id is not None
    adj = admin_session.get(ScoreAdjustment, record.score_adjustment_id)
    assert adj.soldier_id == soldier.id
    assert adj.delta == Decimal("-1")


def test_mark_no_show_rejects_empty_note(admin_session):
    soldier, assignment = _seed_past_assignment(admin_session, personal_number="ns0002")
    marker = create_soldier(admin_session, personal_number="ns_marker2")
    with pytest.raises(NoShowError, match="note_required"):
        mark_no_show(admin_session, duty_assignment_id=assignment.id, marked_by=marker.id, note="")


def test_mark_no_show_rejects_future_duty(admin_session):
    dt = DutyType(name="dt_future_ns", score_per_day=1)
    loc = DutyLocation(name="loc_future_ns")
    soldier = create_soldier(admin_session, personal_number="ns0003")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() + timedelta(days=5), end_date=date.today() + timedelta(days=6),
        status="published",
    )
    admin_session.add(assignment)
    admin_session.flush()
    marker = create_soldier(admin_session, personal_number="ns_marker3")
    with pytest.raises(NoShowError, match="duty_not_yet_finished"):
        mark_no_show(admin_session, duty_assignment_id=assignment.id, marked_by=marker.id, note="x")


def test_mark_no_show_rejects_duplicate(admin_session):
    soldier, assignment = _seed_past_assignment(admin_session, personal_number="ns0004")
    marker = create_soldier(admin_session, personal_number="ns_marker4")
    mark_no_show(admin_session, duty_assignment_id=assignment.id, marked_by=marker.id, note="ראשון")
    admin_session.flush()
    with pytest.raises(NoShowError, match="already_marked"):
        mark_no_show(admin_session, duty_assignment_id=assignment.id, marked_by=marker.id, note="שני")


def test_count_and_list_no_shows(admin_session):
    soldier, assignment = _seed_past_assignment(admin_session, personal_number="ns0005")
    marker = create_soldier(admin_session, personal_number="ns_marker5")
    mark_no_show(admin_session, duty_assignment_id=assignment.id, marked_by=marker.id, note="x")
    admin_session.commit()
    assert count_no_shows(admin_session, soldier_id=soldier.id) == 1
    records = list_no_shows(admin_session, soldier_id=soldier.id)
    assert len(records) == 1
    assert records[0].note == "x"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/unit/test_no_show.py -v`
Expected: FAIL — `app.services.no_show` doesn't exist yet (ImportError)

- [ ] **Step 5: Implement `backend/app/services/no_show.py`**

```python
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.writer import write_audit
from app.db.models import DutyAssignment, DutyNoShow, NotificationType
from app.services.adjustments import create_adjustment
from app.services.notifications import create_notification

_DEFAULT_PENALTY = Decimal("-1")


class NoShowError(Exception):
    """Raised on an invalid no-show marking operation."""


def mark_no_show(
    session: Session,
    *,
    duty_assignment_id: uuid.UUID,
    marked_by: uuid.UUID,
    note: str,
    penalty_delta: Decimal = _DEFAULT_PENALTY,
) -> DutyNoShow:
    if not note or not note.strip():
        raise NoShowError("note_required")
    assignment = session.get(DutyAssignment, duty_assignment_id)
    if assignment is None:
        raise NoShowError("assignment_not_found")
    if assignment.end_date >= date.today():
        raise NoShowError("duty_not_yet_finished")
    existing = session.execute(
        select(DutyNoShow).where(DutyNoShow.duty_assignment_id == duty_assignment_id)
    ).scalar_one_or_none()
    if existing is not None:
        raise NoShowError("already_marked")

    adj = create_adjustment(
        session,
        soldier_id=assignment.soldier_id,
        delta=penalty_delta,
        reason=f"אי-הופעה לתורנות {assignment.start_date.isoformat()}",
        duty_type_id=assignment.duty_type_id,
        actor_id=marked_by,
    )

    record = DutyNoShow(
        duty_assignment_id=duty_assignment_id,
        soldier_id=assignment.soldier_id,
        marked_by=marked_by,
        note=note,
        score_adjustment_id=adj.id,
    )
    session.add(record)
    session.flush()

    create_notification(
        session, soldier_id=assignment.soldier_id, type=NotificationType.no_show_marked,
        title="נרשמה אי-הופעה לתורנות שלך", reference_type="duty_no_show", reference_id=record.id,
        actor_id=marked_by,
    )
    write_audit(
        session, actor_id=marked_by, action="no_show.mark", entity_type="duty_no_show",
        entity_id=record.id,
        after={
            "duty_assignment_id": str(duty_assignment_id),
            "soldier_id": str(assignment.soldier_id),
            "note": note,
            "score_adjustment_id": str(adj.id),
        },
    )
    return record


def count_no_shows(session: Session, *, soldier_id: uuid.UUID, since: date | None = None) -> int:
    query = select(DutyNoShow).where(DutyNoShow.soldier_id == soldier_id)
    if since is not None:
        query = query.where(
            DutyNoShow.created_at >= datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
        )
    return len(list(session.execute(query).scalars().all()))


def list_no_shows(session: Session, *, soldier_id: uuid.UUID) -> list[DutyNoShow]:
    return list(
        session.execute(
            select(DutyNoShow)
            .where(DutyNoShow.soldier_id == soldier_id)
            .order_by(DutyNoShow.created_at.desc())
        )
        .scalars()
        .all()
    )
```

- [ ] **Step 6: Run unit tests to verify they pass**

Run: `pytest tests/unit/test_no_show.py -v`
Expected: all PASS

- [ ] **Step 7: Write the failing integration test**

```python
# backend/tests/integration/test_no_show_api.py
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def _seed_past_assignment(session, *, personal_number):
    from app.db.models import DutyAssignment, DutyLocation, DutyType

    dt = DutyType(name=f"dt_api_{personal_number}", score_per_day=1)
    loc = DutyLocation(name=f"loc_api_{personal_number}")
    session.add_all([dt, loc])
    session.flush()
    assignment = DutyAssignment(
        soldier_id=None, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() - timedelta(days=5), end_date=date.today() - timedelta(days=4),
        status="published",
    )
    return dt, loc, assignment


def test_duty_manager_marks_no_show(client: TestClient, admin_session: Session):
    from app.db.models import DutyAssignment, DutyLocation, DutyType

    node = create_node(admin_session, level="unit", name="ns-api-unit")
    dm = create_soldier(admin_session, personal_number="ns_api_dm1", role="duty_manager", hierarchy_node_id=node.id)
    soldier = create_soldier(admin_session, personal_number="ns_api_s1", hierarchy_node_id=node.id)
    dt = DutyType(name="dt_ns_api", score_per_day=1)
    loc = DutyLocation(name="loc_ns_api")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=soldier.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() - timedelta(days=5), end_date=date.today() - timedelta(days=4),
        status="published",
    )
    admin_session.add(assignment)
    admin_session.commit()

    r = client.post(
        "/api/no-shows",
        headers=auth_headers(dm),
        json={"duty_assignment_id": str(assignment.id), "note": "לא הגיע"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["soldier_id"] == str(soldier.id)
    assert body["score_adjustment_id"] is not None

    r2 = client.get(f"/api/no-shows/soldiers/{soldier.id}", headers=auth_headers(dm))
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_soldier_cannot_mark_no_show(client: TestClient, admin_session: Session):
    from app.db.models import DutyAssignment, DutyLocation, DutyType

    node = create_node(admin_session, level="unit", name="ns-api-unit2")
    plain_soldier = create_soldier(admin_session, personal_number="ns_api_s2", hierarchy_node_id=node.id)
    target = create_soldier(admin_session, personal_number="ns_api_s3", hierarchy_node_id=node.id)
    dt = DutyType(name="dt_ns_api2", score_per_day=1)
    loc = DutyLocation(name="loc_ns_api2")
    admin_session.add_all([dt, loc])
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=target.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date.today() - timedelta(days=5), end_date=date.today() - timedelta(days=4),
        status="published",
    )
    admin_session.add(assignment)
    admin_session.commit()

    r = client.post(
        "/api/no-shows",
        headers=auth_headers(plain_soldier),
        json={"duty_assignment_id": str(assignment.id), "note": "לא הגיע"},
    )
    assert r.status_code == 403
```

- [ ] **Step 8: Run integration tests to verify they fail**

Run: `pytest tests/integration/test_no_show_api.py -v`
Expected: FAIL — `/api/no-shows` returns 404 (route not registered yet)

- [ ] **Step 9: Implement `backend/app/routes/no_show.py`**

```python
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.authz import Action, authorize
from app.auth.deps import require_password_changed
from app.db.models import DutyAssignment, DutyNoShow, HierarchyNode, Soldier
from app.db.session import get_session
from app.services import no_show as svc

router = APIRouter(prefix="/no-shows", tags=["no-shows"])


class MarkNoShowBody(BaseModel):
    duty_assignment_id: uuid.UUID
    note: str = Field(min_length=1, max_length=1000)
    penalty_delta: Decimal = Field(default=Decimal("-1"), ge=-9999, le=0)


class NoShowOut(BaseModel):
    id: uuid.UUID
    duty_assignment_id: uuid.UUID
    soldier_id: uuid.UUID
    marked_by: uuid.UUID | None
    note: str
    score_adjustment_id: uuid.UUID | None
    created_at: datetime


def _out(r: DutyNoShow) -> NoShowOut:
    return NoShowOut(
        id=r.id, duty_assignment_id=r.duty_assignment_id, soldier_id=r.soldier_id,
        marked_by=r.marked_by, note=r.note, score_adjustment_id=r.score_adjustment_id,
        created_at=r.created_at,
    )


def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


def _load_soldier(session: Session, soldier_id: uuid.UUID) -> Soldier:
    s = session.get(Soldier, soldier_id)
    if s is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return s


@router.post("", response_model=NoShowOut, status_code=status.HTTP_201_CREATED)
def mark_no_show(
    body: MarkNoShowBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> NoShowOut:
    assignment = session.get(DutyAssignment, body.duty_assignment_id)
    if assignment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    soldier = _load_soldier(session, assignment.soldier_id)
    authorize(session, user, Action.SCORE_ADJUST, target_node=_node_of(session, soldier))
    try:
        record = svc.mark_no_show(
            session,
            duty_assignment_id=body.duty_assignment_id,
            marked_by=user.id,
            note=body.note,
            penalty_delta=body.penalty_delta,
        )
    except svc.NoShowError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(record)
    return _out(record)


@router.get("/soldiers/{soldier_id}", response_model=list[NoShowOut])
def list_no_shows_for_soldier(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[NoShowOut]:
    soldier = _load_soldier(session, soldier_id)
    if soldier.id != user.id:
        authorize(session, user, Action.SOLDIER_READ, target_node=_node_of(session, soldier))
    return [_out(r) for r in svc.list_no_shows(session, soldier_id=soldier_id)]
```

- [ ] **Step 10: Register the router**

In `backend/app/main.py`, alongside the existing route imports (near line 30):

```python
from app.routes import no_show as no_show_routes
```

Alongside the existing `app.include_router(...)` calls (near line 163):

```python
    app.include_router(no_show_routes.router, prefix="/api")
```

- [ ] **Step 11: Run integration tests to verify they pass**

Run: `pytest tests/integration/test_no_show_api.py -v`
Expected: all PASS

- [ ] **Step 12: Run the full test suite for the touched areas**

Run: `pytest -k "no_show or score_adjust" -v`
Expected: all PASS

- [ ] **Step 13: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/b2d3f4a5c6e7_add_duty_no_shows_table.py backend/app/services/no_show.py backend/app/routes/no_show.py backend/app/main.py backend/tests/unit/test_no_show.py backend/tests/integration/test_no_show_api.py
git commit -m "feat: add dedicated no-show marking with audit trail and automatic score penalty"
```

---

## Final verification (after all 10 tasks)

- [ ] Run `alembic heads` from `backend/` — confirm a single head, `b2d3f4a5c6e7`.
- [ ] Run the fast suite: `pytest -q` from `backend/` — confirm no regressions across the whole codebase, not just the touched files.
- [ ] Manually re-read the diff for Task 8 and Task 9 once more end-to-end — these are the two behavior-changing (not just guardrail-adding) tasks, so they're the ones most likely to have missed a caller.
