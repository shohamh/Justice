# Private Fields Access Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guard gender, phone, email, constraint reasons, exemption reasons, and exemption types so only the soldier themselves, their duty manager, and their chain-of-command commanders can see them — admins and plain soldiers cannot.

**Architecture:** Add a shared `can_see_private(session, viewer, target)` utility to `authz.py`. Each route file threads an `include_sensitive` boolean into its `_out()` helper; when False, private fields are `None`. Frontend shows `"מידע פרטי"` wherever a private field is `null` in a context where the field conceptually exists.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TypeScript (frontend). Tests: pytest (backend, `admin_session` + `client` fixtures), vitest (frontend, not used here — TypeScript compilation is the verification step for frontend tasks).

---

## File Map

| File | Change |
|------|--------|
| `backend/app/auth/authz.py` | Add `PRIVATE_FIELD_NAMES`, `can_see_private()` |
| `backend/app/routes/soldiers.py` | Remove `_can_see_private_fields`, fix admin bypass, thread `include_values` into `_fu_out` |
| `backend/app/routes/constraints.py` | `ConstraintOut.reason → str\|None`, `_out(include_reason)`, thread into call sites |
| `backend/app/routes/exemptions.py` | `ExemptionOut` fields nullable, `_out(include_sensitive)`, thread into call sites |
| `backend/app/routes/exemption_requests.py` | `ExemptionRequestOut` fields nullable, `_out(include_sensitive)`, admin safety net |
| `backend/tests/unit/test_authz.py` | Add `can_see_private` unit tests |
| `backend/tests/integration/test_private_fields.py` | New file: integration tests for all privacy endpoints |
| `frontend/src/api/constraints.ts` | `PersonalConstraint.reason: string \| null` |
| `frontend/src/api/exemptions.ts` | `Exemption.exemption_type_id: string \| null`, `ExemptionRequest.exemption_type_id: string \| null` |
| `frontend/src/api/soldiers.ts` | `FieldUpdateDTO.new_value: string \| null` |
| `frontend/src/pages/ApprovalsPage.tsx` | `"מידע פרטי"` fallbacks for reason, type, field-update values |
| `frontend/src/components/ExemptionsPanel.tsx` | Null-safe `exemption_type_id` and `reason` |
| `frontend/src/components/UnifiedSoldierModal.tsx` | Null-safe constraint `reason` |

---

### Task 1: Add `can_see_private` to `authz.py`

**Files:**
- Modify: `backend/app/auth/authz.py`
- Test: `backend/tests/unit/test_authz.py`

- [ ] **Step 1: Write failing unit tests**

Append to `backend/tests/unit/test_authz.py`:

```python
# ── can_see_private ──────────────────────────────────────────────────────────


def test_can_see_private_self(admin_session):
    d = create_node(admin_session, level="department", name="csp-d1")
    s = create_soldier(admin_session, personal_number="csp001", hierarchy_node_id=d.id)
    assert authz.can_see_private(admin_session, viewer=s, target=s)


def test_admin_cannot_see_private(admin_session):
    admin = create_soldier(admin_session, personal_number="csp-adm001", role="admin")
    target = create_soldier(admin_session, personal_number="csp002")
    assert not authz.can_see_private(admin_session, viewer=admin, target=target)


def test_dm_in_scope_can_see_private(admin_session):
    d = create_node(admin_session, level="department", name="csp-d2")
    dm = create_soldier(admin_session, personal_number="csp-dm001", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="csp003", hierarchy_node_id=d.id)
    assert authz.can_see_private(admin_session, viewer=dm, target=target)


def test_dm_out_of_scope_cannot_see_private(admin_session):
    d = create_node(admin_session, level="department", name="csp-d3")
    other = create_node(admin_session, level="department", name="csp-d4")
    dm = create_soldier(admin_session, personal_number="csp-dm002", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="csp004", hierarchy_node_id=other.id)
    assert not authz.can_see_private(admin_session, viewer=dm, target=target)


def test_commander_in_chain_can_see_private(admin_session):
    d = create_node(admin_session, level="department", name="csp-d5")
    cmd = create_soldier(admin_session, personal_number="csp-cmd001", role="commander")
    d.commander_id = cmd.id
    admin_session.flush()
    target = create_soldier(admin_session, personal_number="csp005", hierarchy_node_id=d.id)
    assert authz.can_see_private(admin_session, viewer=cmd, target=target)


def test_plain_soldier_cannot_see_peer_private(admin_session):
    d = create_node(admin_session, level="department", name="csp-d6")
    viewer = create_soldier(admin_session, personal_number="csp006", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="csp007", hierarchy_node_id=d.id)
    assert not authz.can_see_private(admin_session, viewer=viewer, target=target)
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd backend && .venv\Scripts\activate && pytest tests/unit/test_authz.py -k "can_see_private" -v
```

Expected: 6 failures with `AttributeError: module 'app.auth.authz' has no attribute 'can_see_private'`.

- [ ] **Step 3: Implement in `authz.py`**

Add at the top of `backend/app/auth/authz.py` (after the existing imports):

```python
PRIVATE_FIELD_NAMES: frozenset[str] = frozenset({"gender", "phone", "email"})
```

Add after the `can()` function:

```python
def can_see_private(session: Session, viewer: Soldier, target: Soldier) -> bool:
    """Return True iff viewer may read private fields on target's record."""
    if viewer.id == target.id:
        return True
    if viewer.role == "admin":
        return False
    if viewer.role in ("duty_manager", "commander"):
        roots = scope_root_ids(session, viewer)
        node = session.get(HierarchyNode, target.hierarchy_node_id) if target.hierarchy_node_id else None
        return _node_in_scope(node, roots)
    return False
```

- [ ] **Step 4: Run tests to confirm they pass**

```
cd backend && pytest tests/unit/test_authz.py -k "can_see_private" -v
```

Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/app/auth/authz.py backend/tests/unit/test_authz.py
git commit -m "feat: add can_see_private and PRIVATE_FIELD_NAMES to authz"
```

---

### Task 2: Fix `soldiers.py` — admin bypass and field-update redaction

**Files:**
- Modify: `backend/app/routes/soldiers.py`
- Test: `backend/tests/integration/test_private_fields.py` (create)

- [ ] **Step 1: Create the integration test file with failing tests**

Create `backend/tests/integration/test_private_fields.py`:

```python
"""Integration tests for private-field access control across all routes."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ExemptionType
from tests.helpers import auth_headers, create_node, create_soldier


def _et(session: Session, name: str) -> ExemptionType:
    et = ExemptionType(name=name)
    session.add(et)
    session.commit()
    session.refresh(et)
    return et


# ── Soldier private fields ───────────────────────────────────────────────────


def test_admin_cannot_see_gender_phone_email(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="pf-adm001", role="admin")
    d = create_node(admin_session, level="department", name="pf-d1")
    dm = create_soldier(admin_session, personal_number="pf-dm001", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s001", hierarchy_node_id=d.id)
    admin_session.commit()
    # DM sets profile with private fields
    client.patch(
        f"/api/soldiers/{target.id}/profile",
        json={"gender": "male"},
        headers=auth_headers(dm),
    )
    # Admin fetches individual soldier
    r = client.get(f"/api/soldiers/{target.id}", headers=auth_headers(admin))
    assert r.status_code == 200
    body = r.json()
    assert body["gender"] is None
    assert body["phone"] is None
    assert body["email"] is None


def test_admin_list_soldiers_private_fields_null(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="pf-adm002", role="admin")
    d = create_node(admin_session, level="department", name="pf-d2")
    dm = create_soldier(admin_session, personal_number="pf-dm002", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s002", hierarchy_node_id=d.id)
    admin_session.commit()
    client.patch(
        f"/api/soldiers/{target.id}/profile",
        json={"gender": "female"},
        headers=auth_headers(dm),
    )
    r = client.get("/api/soldiers", headers=auth_headers(admin))
    assert r.status_code == 200
    rows = {s["id"]: s for s in r.json()}
    row = rows[str(target.id)]
    assert row["gender"] is None


def test_dm_in_scope_can_see_gender(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="pf-d3")
    dm = create_soldier(admin_session, personal_number="pf-dm003", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s003", hierarchy_node_id=d.id)
    admin_session.commit()
    client.patch(
        f"/api/soldiers/{target.id}/profile",
        json={"gender": "male"},
        headers=auth_headers(dm),
    )
    r = client.get(f"/api/soldiers/{target.id}", headers=auth_headers(dm))
    assert r.status_code == 200
    assert r.json()["gender"] == "male"


def test_plain_soldier_cannot_see_peer_gender(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="pf-d4")
    dm = create_soldier(admin_session, personal_number="pf-dm004", role="duty_manager", hierarchy_node_id=d.id)
    viewer = create_soldier(admin_session, personal_number="pf-s004a", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s004b", hierarchy_node_id=d.id)
    admin_session.commit()
    client.patch(
        f"/api/soldiers/{target.id}/profile",
        json={"gender": "female"},
        headers=auth_headers(dm),
    )
    r = client.get(f"/api/soldiers/{target.id}", headers=auth_headers(viewer))
    # Soldiers without command scope get 403 (authz blocks them)
    assert r.status_code == 403


# ── Field-update redaction ───────────────────────────────────────────────────


def test_admin_sees_redacted_values_for_private_field_updates(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="pf-adm003", role="admin")
    d = create_node(admin_session, level="department", name="pf-d5")
    target = create_soldier(admin_session, personal_number="pf-s005", hierarchy_node_id=d.id)
    admin_session.commit()
    # target submits a gender field update
    client.post(
        f"/api/soldiers/{target.id}/field-updates",
        json={"field_name": "gender", "new_value": "male"},
        headers=auth_headers(target),
    )
    r = client.get("/api/soldiers/field-updates/pending", headers=auth_headers(admin))
    assert r.status_code == 200
    items = [i for i in r.json() if i["soldier_id"] == str(target.id) and i["field_name"] == "gender"]
    assert len(items) == 1
    assert items[0]["new_value"] is None


def test_dm_sees_real_values_for_private_field_updates(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="pf-d6")
    dm = create_soldier(admin_session, personal_number="pf-dm005", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s006", hierarchy_node_id=d.id)
    admin_session.commit()
    client.post(
        f"/api/soldiers/{target.id}/field-updates",
        json={"field_name": "gender", "new_value": "female"},
        headers=auth_headers(target),
    )
    r = client.get("/api/soldiers/field-updates/pending", headers=auth_headers(dm))
    assert r.status_code == 200
    items = [i for i in r.json() if i["soldier_id"] == str(target.id) and i["field_name"] == "gender"]
    assert len(items) == 1
    assert items[0]["new_value"] == "female"


# ── Constraint reason ────────────────────────────────────────────────────────


def test_admin_cannot_see_constraint_reason_in_pending_list(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="pf-adm004", role="admin")
    d = create_node(admin_session, level="department", name="pf-d7")
    target = create_soldier(admin_session, personal_number="pf-s007", hierarchy_node_id=d.id)
    admin_session.commit()
    client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={"start_date": "2026-08-01", "end_date": "2026-08-05", "reason": "סיבה פרטית"},
    )
    r = client.get("/api/constraints/pending", headers=auth_headers(admin))
    assert r.status_code == 200
    rows = [row for row in r.json() if row["soldier_id"] == str(target.id)]
    assert len(rows) == 1
    assert rows[0]["reason"] is None


def test_dm_can_see_constraint_reason_in_pending_list(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="pf-d8")
    dm = create_soldier(admin_session, personal_number="pf-dm006", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s008", hierarchy_node_id=d.id)
    admin_session.commit()
    client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={"start_date": "2026-08-01", "end_date": "2026-08-05", "reason": "חופשה"},
    )
    r = client.get("/api/constraints/pending", headers=auth_headers(dm))
    assert r.status_code == 200
    rows = [row for row in r.json() if row["soldier_id"] == str(target.id)]
    assert len(rows) == 1
    assert rows[0]["reason"] == "חופשה"


def test_self_can_see_own_constraint_reason(client: TestClient, admin_session: Session):
    target = create_soldier(admin_session, personal_number="pf-s009")
    admin_session.commit()
    client.post(
        "/api/me/constraints",
        headers=auth_headers(target),
        json={"start_date": "2026-08-01", "end_date": "2026-08-05", "reason": "פרטי"},
    )
    r = client.get("/api/me/constraints", headers=auth_headers(target))
    assert r.status_code == 200
    assert r.json()[0]["reason"] == "פרטי"


# ── Exemption sensitive fields ───────────────────────────────────────────────


def test_admin_cannot_see_exemption_type_or_reason(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="pf-adm005", role="admin")
    d = create_node(admin_session, level="department", name="pf-d9")
    dm = create_soldier(admin_session, personal_number="pf-dm007", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s010", hierarchy_node_id=d.id)
    et = _et(admin_session, "pf-et-001")
    admin_session.commit()
    client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(dm),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "סיבה"},
    )
    r = client.get(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(admin))
    assert r.status_code == 200
    exs = r.json()
    assert len(exs) == 1
    assert exs[0]["reason"] is None
    assert exs[0]["exemption_type_id"] is None


def test_dm_can_see_exemption_type_and_reason(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="pf-d10")
    dm = create_soldier(admin_session, personal_number="pf-dm008", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s011", hierarchy_node_id=d.id)
    et = _et(admin_session, "pf-et-002")
    admin_session.commit()
    client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(dm),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "סיבה"},
    )
    r = client.get(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(dm))
    assert r.status_code == 200
    exs = r.json()
    assert exs[0]["reason"] == "סיבה"
    assert exs[0]["exemption_type_id"] == str(et.id)


def test_self_can_see_own_exemption_type_and_reason(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="department", name="pf-d11")
    dm = create_soldier(admin_session, personal_number="pf-dm009", role="duty_manager", hierarchy_node_id=d.id)
    target = create_soldier(admin_session, personal_number="pf-s012", hierarchy_node_id=d.id)
    et = _et(admin_session, "pf-et-003")
    admin_session.commit()
    client.post(
        f"/api/soldiers/{target.id}/exemptions",
        headers=auth_headers(dm),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "טעם"},
    )
    r = client.get(f"/api/soldiers/{target.id}/exemptions", headers=auth_headers(target))
    assert r.status_code == 200
    exs = r.json()
    assert exs[0]["reason"] == "טעם"
    assert exs[0]["exemption_type_id"] == str(et.id)
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd backend && pytest tests/integration/test_private_fields.py -v
```

Expected: failures because private-field logic hasn't been implemented yet. Note which tests fail — only those covering soldiers, field-updates, constraints, and exemptions. Keep the test file; subsequent tasks will make each group green.

- [ ] **Step 3: Implement `soldiers.py` changes**

In `backend/app/routes/soldiers.py`:

**3a.** Replace the import block to add `can_see_private` and `PRIVATE_FIELD_NAMES`:

```python
from app.auth.authz import Action, authorize, scope_root_ids, can_see_private, PRIVATE_FIELD_NAMES
```

**3b.** Delete the entire `_can_see_private_fields` function (lines 158-169 in the current file).

**3c.** Change `FieldUpdateOut.new_value` to nullable:

```python
class FieldUpdateOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str = ""
    node_name: str | None = None
    field_name: str
    previous_value: str | None
    new_value: str | None        # None when viewer cannot see private field values
    status: str
    decided_by: uuid.UUID | None
    decided_at: Any
    decision_note: str | None
    created_at: Any
```

**3d.** Update `_fu_out` to accept `include_values`:

```python
def _fu_out(u: SoldierFieldUpdate, soldier_name: str = "", node_name: str | None = None, include_values: bool = True) -> FieldUpdateOut:
    redact = not include_values and u.field_name in PRIVATE_FIELD_NAMES
    return FieldUpdateOut(
        id=u.id,
        soldier_id=u.soldier_id,
        soldier_name=soldier_name,
        node_name=node_name,
        field_name=u.field_name,
        previous_value=None if redact else u.previous_value,
        new_value=None if redact else u.new_value,
        status=u.status,
        decided_by=u.decided_by,
        decided_at=u.decided_at,
        decision_note=u.decision_note,
        created_at=u.created_at,
    )
```

**3e.** In `list_soldiers` — fix the admin branch (line `return [_out(s, include_private=True, ...)`):

```python
    if user.role == "admin":
        rows = session.execute(select(Soldier)).scalars().all()
        return [_out(s, include_private=False, telegram_linked=s.id in linked_ids) for s in rows]
```

**3f.** In `get_soldier` — replace `_can_see_private_fields(...)` call:

```python
    return _out(
        s,
        include_private=can_see_private(session, user, s),
        telegram_linked=link is not None,
        direct_commander=commander,
    )
```

**3g.** In `update_profile` — replace `_can_see_private_fields(...)` call:

```python
    return _out(s, include_private=can_see_private(session, user, s))
```

**3h.** In `list_all_pending_field_updates` — in the admin branch, replace `_fu_out(upd, ...)` call:

```python
        for upd in all_pending:
            s = soldiers_by_id.get(upd.soldier_id)
            soldier_name = s.full_name if s else str(upd.soldier_id)[:8]
            node_name = (
                nodes_by_id[s.hierarchy_node_id].name
                if s and s.hierarchy_node_id and s.hierarchy_node_id in nodes_by_id
                else None
            )
            include_values = s is not None and can_see_private(session, user, s)
            result.append(_fu_out(upd, soldier_name=soldier_name, node_name=node_name, include_values=include_values))
        return result
```

And in the non-admin branch:

```python
    for upd in all_pending:
        s = soldiers_by_id.get(upd.soldier_id)
        if s:
            node = nodes_by_id.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
            if can(user, Action.SOLDIER_READ, target_node=node, roots=roots):
                soldier_name = s.full_name
                node_name = node.name if node else None
                include_values = can_see_private(session, user, s)
                result.append(_fu_out(upd, soldier_name=soldier_name, node_name=node_name, include_values=include_values))
    return result
```

- [ ] **Step 4: Run soldier-related tests**

```
cd backend && pytest tests/integration/test_private_fields.py -k "gender or phone or email or field_update" -v
cd backend && pytest tests/integration/test_soldier_profile.py -v
cd backend && pytest tests/integration/test_soldiers_api.py -v
```

Expected: soldier and field-update tests in `test_private_fields.py` PASS. All existing soldier tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/soldiers.py backend/tests/integration/test_private_fields.py
git commit -m "feat: redact private soldier fields and field-update values from admin"
```

---

### Task 3: Guard constraint reason in `constraints.py`

**Files:**
- Modify: `backend/app/routes/constraints.py`

- [ ] **Step 1: Run existing constraint tests to establish baseline**

```
cd backend && pytest tests/integration/test_constraints_api.py -v
```

Expected: all PASS.

- [ ] **Step 2: Implement `constraints.py` changes**

**2a.** Add import for `can_see_private` at the top of `backend/app/routes/constraints.py`:

```python
from app.auth.authz import Action, authorize, scope_root_ids, can_see_private
```

**2b.** Change `ConstraintOut.reason` to nullable:

```python
class ConstraintOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str = ""
    node_name: str | None = None
    start_date: date
    end_date: date
    reason: str | None          # None when viewer cannot see private field
    status: str
    decided_by: uuid.UUID | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    created_at: datetime
```

**2c.** Add `include_reason` parameter to `_out`:

```python
def _out(c: PersonalConstraint, soldier_name: str = "", node_name: str | None = None, include_reason: bool = True) -> ConstraintOut:
    return ConstraintOut(
        id=c.id,
        soldier_id=c.soldier_id,
        soldier_name=soldier_name,
        node_name=node_name,
        start_date=c.start_date,
        end_date=c.end_date,
        reason=c.reason if include_reason else None,
        status=c.status,
        decided_by=c.decided_by,
        decided_at=c.decided_at,
        decision_note=c.decision_note,
        created_at=c.created_at,
    )
```

**2d.** Add `user: Soldier` parameter to `_attach_names` and compute `include_reason` per row:

```python
def _attach_names(
    session: Session, rows: list[PersonalConstraint], user: Soldier
) -> list[ConstraintOut]:
    if not rows:
        return []
    soldier_ids = {c.soldier_id for c in rows}
    soldiers_by_id = {
        s.id: s
        for s in session.execute(select(Soldier).where(Soldier.id.in_(soldier_ids))).scalars().all()
    }
    node_ids = {s.hierarchy_node_id for s in soldiers_by_id.values() if s.hierarchy_node_id}
    nodes_by_id = (
        {
            n.id: n
            for n in session.execute(
                select(HierarchyNode).where(HierarchyNode.id.in_(node_ids))
            ).scalars().all()
        }
        if node_ids
        else {}
    )
    result = []
    for c in rows:
        s = soldiers_by_id.get(c.soldier_id)
        soldier_name = s.full_name if s else str(c.soldier_id)[:8]
        node_name = (
            nodes_by_id[s.hierarchy_node_id].name
            if s and s.hierarchy_node_id and s.hierarchy_node_id in nodes_by_id
            else None
        )
        include_reason = s is not None and can_see_private(session, user, s)
        result.append(_out(c, soldier_name=soldier_name, node_name=node_name, include_reason=include_reason))
    return result
```

**2e.** Update `pending_list` call sites — both now pass `user`:

```python
    if user.role == "admin":
        rows = list(
            session.execute(
                select(PersonalConstraint)
                .where(PersonalConstraint.status == "pending")
                .order_by(PersonalConstraint.start_date.asc())
            )
            .scalars()
            .all()
        )
        return _attach_names(session, rows, user)
    return _attach_names(session, svc.list_pending_approvals(session, node_ids=roots), user)
```

**2f.** Update `list_for_soldier` to thread `include_reason`:

```python
@router.get("/soldiers/{soldier_id}/constraints", response_model=list[ConstraintOut])
def list_for_soldier(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ConstraintOut]:
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.CONSTRAINT_READ, target_node=_node_of(session, s))
    include_reason = can_see_private(session, user, s)
    return [_out(c, include_reason=include_reason) for c in svc.list_constraints(session, soldier_id=soldier_id)]
```

**2g.** Update `approve` and `reject` endpoints to include `include_reason=True` (caller is authorized DM/commander):

In `approve`:
```python
    return _out(c, include_reason=True)
```

In `reject`:
```python
    return _out(c, include_reason=True)
```

- [ ] **Step 3: Run constraint-related tests**

```
cd backend && pytest tests/integration/test_private_fields.py -k "constraint" -v
cd backend && pytest tests/integration/test_constraints_api.py -v
```

Expected: all constraint tests PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/constraints.py
git commit -m "feat: redact constraint reason from admin and unauthorized viewers"
```

---

### Task 4: Guard exemption sensitive fields in `exemptions.py`

**Files:**
- Modify: `backend/app/routes/exemptions.py`

- [ ] **Step 1: Run existing exemption tests to establish baseline**

```
cd backend && pytest tests/integration/test_exemptions_api.py -v
```

Expected: all PASS.

- [ ] **Step 2: Implement `exemptions.py` changes**

**2a.** Add import for `can_see_private` at the top of `backend/app/routes/exemptions.py`:

```python
from app.auth.authz import Action, authorize, can_see_private
```

**2b.** Change `ExemptionOut` fields to nullable:

```python
class ExemptionOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    exemption_type_id: uuid.UUID | None    # None when viewer cannot see private fields
    start_date: date
    end_date: date | None
    reason: str | None                      # None when viewer cannot see private fields
    granted_by: uuid.UUID | None
```

**2c.** Add `include_sensitive` to `_out`:

```python
def _out(ex: SoldierExemption, include_sensitive: bool = True) -> ExemptionOut:
    return ExemptionOut(
        id=ex.id,
        soldier_id=ex.soldier_id,
        exemption_type_id=ex.exemption_type_id if include_sensitive else None,
        start_date=ex.start_date,
        end_date=ex.end_date,
        reason=ex.reason if include_sensitive else None,
        granted_by=ex.granted_by,
    )
```

**2d.** Update `list_` endpoint:

```python
@router.get("", response_model=list[ExemptionOut])
def list_(
    soldier_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[ExemptionOut]:
    s = _load_soldier(session, soldier_id)
    if s.id != user.id:
        authorize(session, user, Action.EXEMPTION_READ, target_node=_node_of(session, s))
    include_sensitive = can_see_private(session, user, s)
    return [_out(ex, include_sensitive=include_sensitive) for ex in svc.list_exemptions(session, soldier_id=soldier_id)]
```

**2e.** Update `grant` endpoint (actor is authorized DM/commander → `include_sensitive=True`):

```python
    return _out(ex, include_sensitive=True)
```

The `revoke` endpoint returns 204 (no body) — no change needed.

- [ ] **Step 3: Run exemption-related tests**

```
cd backend && pytest tests/integration/test_private_fields.py -k "exemption" -v
cd backend && pytest tests/integration/test_exemptions_api.py -v
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routes/exemptions.py
git commit -m "feat: redact exemption type and reason from admin and unauthorized viewers"
```

---

### Task 5: Safety net in `exemption_requests.py`

**Files:**
- Modify: `backend/app/routes/exemption_requests.py`

Admin already gets `[]` from `/exemption-requests/pending` (empty `scope_root_ids`). This task adds a belt-and-suspenders guard so that if an admin were somehow scoped as a commander, the sensitive fields are still redacted.

- [ ] **Step 1: Implement changes**

**1a.** Change nullable fields in `ExemptionRequestOut`:

```python
class ExemptionRequestOut(BaseModel):
    id: uuid.UUID
    soldier_id: uuid.UUID
    soldier_name: str = ""
    node_name: str | None = None
    exemption_type_id: uuid.UUID | None    # None when viewer cannot see private fields
    start_date: str
    end_date: str | None
    reason: str | None                      # None when viewer cannot see private fields
    status: str
    decided_by: uuid.UUID | None
    decision_note: str | None
    created_at: str
    files: list[ExemptionFileOut] = []
```

**1b.** Add `include_sensitive` to `_out`:

```python
def _out(
    req: ExemptionRequest,
    soldier_name: str = "",
    node_name: str | None = None,
    files: list[ExemptionFileOut] | None = None,
    include_sensitive: bool = True,
) -> ExemptionRequestOut:
    return ExemptionRequestOut(
        id=req.id,
        soldier_id=req.soldier_id,
        soldier_name=soldier_name,
        node_name=node_name,
        exemption_type_id=req.exemption_type_id if include_sensitive else None,
        start_date=req.start_date.isoformat(),
        end_date=req.end_date.isoformat() if req.end_date else None,
        reason=req.reason if include_sensitive else None,
        status=req.status,
        decided_by=req.decided_by,
        decision_note=req.decision_note,
        created_at=req.created_at.isoformat(),
        files=files or [],
    )
```

**1c.** Update `/me/exemption-requests` — self always sees own data:

```python
    return [_out(r, include_sensitive=True) for r in list_own_requests(session, user.id)]
```

**1d.** Update `/exemption-requests/pending` — add safety net in the result loop:

```python
    for r in reqs:
        s = soldiers_by_id.get(r.soldier_id)
        soldier_name = s.full_name if s else str(r.soldier_id)[:8]
        node_name = (
            nodes_by_id[s.hierarchy_node_id].name
            if s and s.hierarchy_node_id and s.hierarchy_node_id in nodes_by_id
            else None
        )
        include_sensitive = user.role != "admin"
        result.append(_out(r, soldier_name=soldier_name, node_name=node_name, files=files_by_req.get(r.id, []), include_sensitive=include_sensitive))
    return result
```

**1e.** `approve` and `reject` endpoints — caller is authorized, `include_sensitive=True`:

```python
    return _out(result, include_sensitive=True)
```

(both `approve_exemption_request` and `reject_exemption_request`)

- [ ] **Step 2: Run full backend suite for affected tests**

```
cd backend && pytest tests/integration/test_private_fields.py -v
cd backend && pytest tests/integration/ -v --ignore=tests/integration/test_algorithm_shifts.py -q
```

Expected: all PASS. (Skipping the slow algorithm test.)

- [ ] **Step 3: Commit**

```bash
git add backend/app/routes/exemption_requests.py
git commit -m "feat: add include_sensitive guard to exemption_requests routes"
```

---

### Task 6: Update frontend TypeScript types

**Files:**
- Modify: `frontend/src/api/constraints.ts`
- Modify: `frontend/src/api/exemptions.ts`
- Modify: `frontend/src/api/soldiers.ts`

- [ ] **Step 1: Update `constraints.ts`**

Change `PersonalConstraint.reason`:

```typescript
export interface PersonalConstraint {
  id: string;
  soldier_id: string;
  soldier_name: string;
  node_name: string | null;
  start_date: string;
  end_date: string;
  reason: string | null;   // null when viewer cannot see private field
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
}
```

- [ ] **Step 2: Update `exemptions.ts`**

Change `Exemption.exemption_type_id` and `ExemptionRequest.exemption_type_id`:

```typescript
export interface Exemption {
  id: string;
  soldier_id: string;
  exemption_type_id: string | null;   // null when viewer cannot see private fields
  start_date: string;
  end_date: string | null;
  reason: string | null;
  granted_by: string | null;
}
```

```typescript
export interface ExemptionRequest {
  id: string;
  soldier_id: string;
  soldier_name: string;
  node_name: string | null;
  exemption_type_id: string | null;   // null when viewer cannot see private fields
  start_date: string;
  end_date: string | null;
  reason: string | null;
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  decision_note: string | null;
  created_at: string;
  files: ExemptionFile[];
}
```

- [ ] **Step 3: Update `soldiers.ts`**

Change `FieldUpdateDTO.new_value`:

```typescript
export interface FieldUpdateDTO {
  id: string;
  soldier_id: string;
  soldier_name: string;
  node_name: string | null;
  field_name: string;
  previous_value: string | null;
  new_value: string | null;   // null when viewer cannot see private field values
  status: "pending" | "approved" | "rejected";
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
}
```

- [ ] **Step 4: Verify TypeScript compiles (type errors will surface in next tasks)**

```
cd frontend && npm run lint
```

Expected: TypeScript errors appear wherever components access `exemption_type_id` as non-nullable or `reason`/`new_value` as `string`. These are fixed in Tasks 7–9.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/constraints.ts frontend/src/api/exemptions.ts frontend/src/api/soldiers.ts
git commit -m "feat: make private fields nullable in frontend API types"
```

---

### Task 7: `ApprovalsPage.tsx` — "מידע פרטי" fallbacks

**Files:**
- Modify: `frontend/src/pages/ApprovalsPage.tsx`

- [ ] **Step 1: Fix constraint reason display**

Find line (around line 233):
```tsx
<p className="text-xs text-gray-500 mb-2">{c.reason}</p>
```

Replace with:
```tsx
<p className="text-xs text-gray-500 mb-2">{c.reason ?? "מידע פרטי"}</p>
```

- [ ] **Step 2: Fix exemption request reason display**

Find line (around line 276):
```tsx
<p className="text-xs text-gray-500 mb-2">{er.reason}</p>
```

Replace with:
```tsx
<p className="text-xs text-gray-500 mb-2">{er.reason ?? "מידע פרטי"}</p>
```

- [ ] **Step 3: Fix field-update value display**

Find these two lines (around lines 331–332):

```tsx
<div className="text-gray-500 dark:text-gray-400">{t("soldier_profile.previous_value")}: <span className="font-mono">{item.previous_value ? (item.field_name === "gender" ? t(`soldier_profile.gender_${item.previous_value}`) : item.previous_value) : "—"}</span></div>
<div className="text-gray-600 dark:text-gray-300">{t("approvals.field_update_new_value")}<strong>{item.field_name === "gender" ? t(`soldier_profile.gender_${item.new_value}`) : item.new_value}</strong></div>
```

Replace with:

```tsx
<div className="text-gray-500 dark:text-gray-400">
  {t("soldier_profile.previous_value")}:{" "}
  <span className="font-mono">
    {item.new_value === null
      ? "מידע פרטי"
      : item.previous_value
        ? (item.field_name === "gender" ? t(`soldier_profile.gender_${item.previous_value}`) : item.previous_value)
        : "—"
    }
  </span>
</div>
<div className="text-gray-600 dark:text-gray-300">
  {t("approvals.field_update_new_value")}
  <strong>
    {item.new_value === null
      ? "מידע פרטי"
      : item.field_name === "gender"
        ? t(`soldier_profile.gender_${item.new_value}`)
        : item.new_value
    }
  </strong>
</div>
```

- [ ] **Step 4: Verify lint passes**

```
cd frontend && npm run lint
```

Expected: no errors in `ApprovalsPage.tsx`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ApprovalsPage.tsx
git commit -m "feat: show מידע פרטי for redacted fields in ApprovalsPage"
```

---

### Task 8: `ExemptionsPanel.tsx` — null-safe type and reason

**Files:**
- Modify: `frontend/src/components/ExemptionsPanel.tsx`

The panel uses `typeName(ex.exemption_type_id)` and `dutyTypeMap[ex.exemption_type_id]`. Both break when `exemption_type_id` is `null`.

- [ ] **Step 1: Fix active exemptions section**

Find (around line 112 inside the active items map):
```tsx
const names = dutyTypeMap[ex.exemption_type_id] ?? [];
```
Replace with:
```tsx
const names = ex.exemption_type_id ? (dutyTypeMap[ex.exemption_type_id] ?? []) : [];
```

Find (around line 124):
```tsx
<p className="font-medium text-sm text-indigo-900 dark:text-indigo-100">
  {typeName(ex.exemption_type_id)}
</p>
```
Replace with:
```tsx
<p className="font-medium text-sm text-indigo-900 dark:text-indigo-100">
  {ex.exemption_type_id ? typeName(ex.exemption_type_id) : "מידע פרטי"}
</p>
```

The `reason` display (around line 147–149) already uses `{isExpanded && ex.reason && ...}` which correctly hides null. No change needed there.

- [ ] **Step 2: Fix past exemptions section**

Find (around line 165 inside the past items map):
```tsx
const names = dutyTypeMap[ex.exemption_type_id] ?? [];
```
Replace with:
```tsx
const names = ex.exemption_type_id ? (dutyTypeMap[ex.exemption_type_id] ?? []) : [];
```

Find (around line 175):
```tsx
<span className="font-medium">{typeName(ex.exemption_type_id)}</span>
```
Replace with:
```tsx
<span className="font-medium">{ex.exemption_type_id ? typeName(ex.exemption_type_id) : "מידע פרטי"}</span>
```

The past `ex.reason` display (around line 191) uses `{ex.reason && ...}` — correctly handles null already.

- [ ] **Step 3: Verify lint passes**

```
cd frontend && npm run lint
```

Expected: no errors in `ExemptionsPanel.tsx`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ExemptionsPanel.tsx
git commit -m "feat: show מידע פרטי for redacted exemption type in ExemptionsPanel"
```

---

### Task 9: `UnifiedSoldierModal.tsx` — null-safe constraint reason

**Files:**
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx`

- [ ] **Step 1: Fix constraint reason display**

Find (around line 462):
```tsx
{c.reason && <p className="text-gray-700 dark:text-gray-300">{c.reason}</p>}
```

Replace with:
```tsx
<p className="text-gray-700 dark:text-gray-300">
  {c.reason ?? "מידע פרטי"}
</p>
```

(Always render the paragraph, show "מידע פרטי" when null. A constraint always has a reason, so null means redacted.)

- [ ] **Step 2: Verify lint passes**

```
cd frontend && npm run lint
```

Expected: no errors.

- [ ] **Step 3: Run full backend suite to confirm nothing regressed**

```
cd backend && pytest tests/ -q --ignore=tests/unit/test_algorithm_perf.py
```

Expected: all PASS (or pre-existing failures only).

- [ ] **Step 4: Final commit**

```bash
git add frontend/src/components/UnifiedSoldierModal.tsx
git commit -m "feat: show מידע פרטי for redacted constraint reason in UnifiedSoldierModal"
```

---

## Done

All private fields are now guarded end-to-end:
- **Backend:** `can_see_private` is the single source of truth; each route computes the flag and passes it into `_out()`
- **Frontend:** TypeScript types are nullable; components show `"מידע פרטי"` rather than blank or crashing when private fields are `null`
