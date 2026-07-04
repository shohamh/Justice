# רשנ"צ (military driving license) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a soldier profile property for רשנ"צ (military driving license: has-license flag + expiry date), editable only via the existing soldier-request/approval flow, with approval extended to commanders ranked רסן+ within their chain of command (duty managers/admins keep today's access) — and add a matching `requires_military_driving_license` duty-type eligibility flag.

**Architecture:** Two new nullable `Soldier` columns. The two values travel together as one `SoldierFieldUpdate` request (`field_name="military_driving_license"`, `new_value` a JSON string) reusing the existing generic pending-request table — no new tables. A new `Action.MILITARY_LICENSE_DECIDE` is added to the existing `can()`/`authorize()` authorization framework (`app/auth/authz.py`), following the exact pattern already used there for `POTENTIAL_READ`/`DM_SCOPE_MANAGE` (rank רסן+ AND in-scope). Eligibility gating follows the existing `requires_bahad1` pattern in `app/services/eligibility.py`.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (backend), React + TypeScript + react-i18next (frontend), pytest (backend tests).

## Global Constraints

- Follow existing patterns exactly — this is a small addition to a mature codebase, not a redesign.
- No new DB tables. No two-stage approval. No background jobs for expiry.
- Hebrew label for the field: `רשנ"צ (רישיון נהיגה צבאי)`.
- Spec: `docs/superpowers/specs/2026-07-04-rashan-tzva-license-design.md`

---

### Task 1: Data model + migration

**Files:**
- Modify: `backend/app/db/models.py:55-57` (Soldier class, right after `bahad1_graduate`)
- Create: `backend/alembic/versions/<generated>_add_military_driving_license.py`

**Interfaces:**
- Produces: `Soldier.has_military_driving_license: bool | None`, `Soldier.military_driving_license_expiry: date | None` — consumed by Tasks 2, 4, 5.

- [ ] **Step 1: Add the two columns to the `Soldier` model**

In `backend/app/db/models.py`, right after the `bahad1_graduate` column (currently lines 55-57):

```python
    bahad1_graduate: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    has_military_driving_license: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=None
    )
    military_driving_license_expiry: Mapped[date | None] = mapped_column(
        Date, nullable=True, default=None
    )
```

- [ ] **Step 2: Generate the Alembic migration**

Run (from `backend/`, venv active):
```bash
alembic revision -m "add_military_driving_license"
```
This creates a new file under `backend/alembic/versions/`. Note the generated revision id and the `down_revision` it filled in (should be `4f9731b4a496`, today's head).

- [ ] **Step 3: Fill in the migration body**

Edit the generated file's `upgrade`/`downgrade`:

```python
def upgrade() -> None:
    op.add_column("soldiers", sa.Column("has_military_driving_license", sa.Boolean(), nullable=True))
    op.add_column("soldiers", sa.Column("military_driving_license_expiry", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("soldiers", "military_driving_license_expiry")
    op.drop_column("soldiers", "has_military_driving_license")
```

- [ ] **Step 4: Apply the migration and verify**

```bash
alembic upgrade head
```
Expected: runs without error, ends at the new revision (`alembic current` shows the new id).

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/
git commit -m "feat: add military driving license columns to Soldier"
```

---

### Task 2: Eligibility rule

**Files:**
- Modify: `backend/app/services/eligibility.py:29` (`SOLDIER_EDITABLE_FIELDS`), `:32-40` (`DutyTypeRequirements`), `:55-93` (`_is_eligible`)
- Test: `backend/tests/unit/test_eligibility.py`

**Interfaces:**
- Consumes: `Soldier.has_military_driving_license`, `Soldier.military_driving_license_expiry` (Task 1).
- Produces: `DutyTypeRequirements.requires_military_driving_license: bool`, `"military_driving_license"` added to `SOLDIER_EDITABLE_FIELDS` — consumed by Task 4 (routes) and Task 6 (frontend requirements editor).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_eligibility.py`:

```python
def test_military_driving_license_required_passes_no_expiry():
    s = _soldier(has_military_driving_license=True, military_driving_license_expiry=None)
    reqs = DutyTypeRequirements(requires_military_driving_license=True)
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_military_driving_license_required_blocks_when_absent():
    s = _soldier(has_military_driving_license=False)
    reqs = DutyTypeRequirements(requires_military_driving_license=True)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_military_driving_license_required_blocks_when_null():
    s = _soldier(has_military_driving_license=None)
    reqs = DutyTypeRequirements(requires_military_driving_license=True)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_military_driving_license_future_expiry_passes():
    s = _soldier(has_military_driving_license=True, military_driving_license_expiry=TODAY + timedelta(days=30))
    reqs = DutyTypeRequirements(requires_military_driving_license=True)
    assert _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)


def test_military_driving_license_past_expiry_blocks():
    s = _soldier(has_military_driving_license=True, military_driving_license_expiry=TODAY - timedelta(days=1))
    reqs = DutyTypeRequirements(requires_military_driving_license=True)
    assert not _is_eligible(s, reqs, mitvahim_months=6, alal_months=3, today=TODAY)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest backend/tests/unit/test_eligibility.py -k military_driving_license -v
```
Expected: FAIL — `DutyTypeRequirements` has no field `requires_military_driving_license` (pydantic validation error) / `Soldier` has no field `has_military_driving_license` (only true after Task 1 lands; if Task 1 already committed, expect `AssertionError` instead since the flag has no effect yet).

- [ ] **Step 3: Implement the eligibility rule**

In `backend/app/services/eligibility.py`:

Change line 29:
```python
SOLDIER_EDITABLE_FIELDS = {"last_mitvahim_date", "last_alal_date", "gender", "rank", "phone", "military_driving_license"}
```

Add to `DutyTypeRequirements` (after `requires_bahad1: bool = False`):
```python
    requires_bahad1: bool = False
    requires_military_driving_license: bool = False
```

Add to `_is_eligible`, right after the `requires_bahad1` check (currently lines 90-91):
```python
    if reqs.requires_bahad1 and not soldier.bahad1_graduate:
        return False

    if reqs.requires_military_driving_license:
        if not soldier.has_military_driving_license:
            return False
        if soldier.military_driving_license_expiry and soldier.military_driving_license_expiry < today:
            return False

    return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest backend/tests/unit/test_eligibility.py -v
```
Expected: all PASS, including the 5 new tests and all pre-existing ones (no regressions).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/eligibility.py backend/tests/unit/test_eligibility.py
git commit -m "feat: add requires_military_driving_license eligibility rule"
```

---

### Task 3: Authorization action for rank-gated commander approval

**Files:**
- Modify: `backend/app/auth/authz.py:37-59` (`Action` class), `:62-80` (`_DM_ACTIONS`), `:127-159` (`can()`)
- Test: `backend/tests/unit/test_authz.py`

**Interfaces:**
- Produces: `Action.MILITARY_LICENSE_DECIDE` — consumed by Task 5 (routes/soldiers.py approve/reject).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_authz.py`:

```python
def test_dm_can_decide_military_license_in_scope(admin_session):
    d = create_node(admin_session, level="department", name="mdl-d1")
    dm = create_soldier(admin_session, personal_number="7600001", role="duty_manager", hierarchy_node_id=d.id)
    roots = _roots(admin_session, dm)
    is_cmd, is_dm = _caps(admin_session, dm)
    assert authz.can(dm, authz.Action.MILITARY_LICENSE_DECIDE, target_node=d, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_commander_below_rasan_cannot_decide_military_license(admin_session):
    d = create_node(admin_session, level="department", name="mdl-d2")
    cmd = create_soldier(admin_session, personal_number="7600002", role="commander")
    cmd.rank = "סרן"
    d.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    is_cmd, is_dm = _caps(admin_session, cmd)
    assert not authz.can(cmd, authz.Action.MILITARY_LICENSE_DECIDE, target_node=d, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_commander_rasan_and_above_can_decide_military_license_in_scope(admin_session):
    d = create_node(admin_session, level="department", name="mdl-d3")
    cmd = create_soldier(admin_session, personal_number="7600003", role="commander")
    cmd.rank = "רסן"
    d.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    is_cmd, is_dm = _caps(admin_session, cmd)
    assert authz.can(cmd, authz.Action.MILITARY_LICENSE_DECIDE, target_node=d, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_commander_rasan_out_of_scope_cannot_decide_military_license(admin_session):
    d = create_node(admin_session, level="department", name="mdl-d4")
    other = create_node(admin_session, level="department", name="mdl-d4-other")
    cmd = create_soldier(admin_session, personal_number="7600004", role="commander")
    cmd.rank = "רסן"
    d.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    is_cmd, is_dm = _caps(admin_session, cmd)
    assert not authz.can(cmd, authz.Action.MILITARY_LICENSE_DECIDE, target_node=other, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest backend/tests/unit/test_authz.py -k military_license -v
```
Expected: FAIL with `AttributeError: type object 'Action' has no attribute 'MILITARY_LICENSE_DECIDE'`.

- [ ] **Step 3: Add the action and gating logic**

In `backend/app/auth/authz.py`, add to the `Action` class (after `POTENTIAL_MODIFIER_MANAGE`, line 59):
```python
    POTENTIAL_MODIFIER_MANAGE = "potential.modifier_manage"
    MILITARY_LICENSE_DECIDE = "military_license.decide"
```

Add to `_DM_ACTIONS` (line 62-80), so duty managers keep today's access:
```python
_DM_ACTIONS = {
    Action.SOLDIER_CREATE,
    Action.SOLDIER_READ,
    Action.SOLDIER_UPDATE,
    Action.SOLDIER_RESET_PASSWORD,
    Action.SOLDIER_DELETE,
    Action.HIERARCHY_READ,
    Action.HIERARCHY_MANAGE,
    Action.EXEMPTION_GRANT,
    Action.EXEMPTION_READ,
    Action.CONSTRAINT_READ,
    Action.CONSTRAINT_APPROVE,
    Action.SWAP_APPROVE,
    Action.ASSIGNMENT_MANAGE,
    Action.SCORE_ADJUST,
    Action.ENROLLMENT_APPROVE,
    Action.POTENTIAL_READ,
    Action.POTENTIAL_MODIFIER_MANAGE,
    Action.MILITARY_LICENSE_DECIDE,
}
```

In `can()` (lines 144-158), add a rank-gated branch alongside the existing `POTENTIAL_READ`/`DM_SCOPE_MANAGE` ones:
```python
    if is_commander:
        if action in (Action.POTENTIAL_READ, Action.POTENTIAL_MODIFIER_MANAGE):
            if (
                bool(user.rank and user.rank in RANKS_RASAN_AND_ABOVE)
                and _node_in_scope(target_node, roots)
            ):
                allowed = True
        elif action == Action.DM_SCOPE_MANAGE:
            if (
                bool(user.rank and user.rank in RANKS_RASAN_AND_ABOVE)
                and _node_in_scope(target_node, roots)
            ):
                allowed = True
        elif action == Action.MILITARY_LICENSE_DECIDE:
            if (
                bool(user.rank and user.rank in RANKS_RASAN_AND_ABOVE)
                and _node_in_scope(target_node, roots)
            ):
                allowed = True
        elif action in _COMMANDER_ACTIONS and _node_in_scope(target_node, roots):
            allowed = True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest backend/tests/unit/test_authz.py -v
```
Expected: all PASS, including the 4 new tests and all pre-existing ones.

- [ ] **Step 5: Commit**

```bash
git add backend/app/auth/authz.py backend/tests/unit/test_authz.py
git commit -m "feat: add rank-gated MILITARY_LICENSE_DECIDE authorization action"
```

---

### Task 4: Service layer — submit/approve JSON payload handling

**Files:**
- Modify: `backend/app/services/soldiers.py:1-8` (imports), `:198-204` (`_get_current_value`), `:248-284` (`approve_field_update`)
- Create: `backend/tests/unit/test_soldiers_service.py`

**Interfaces:**
- Consumes: `SOLDIER_EDITABLE_FIELDS` (Task 2), `Soldier.has_military_driving_license`/`military_driving_license_expiry` (Task 1).
- Produces: `submit_field_update`/`approve_field_update` now handle `field_name="military_driving_license"` with a JSON `new_value` shaped `{"has_license": bool, "expiry_date": "YYYY-MM-DD" | null}` — consumed by Task 5 (routes) and Task 7 (frontend).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_soldiers_service.py`:

```python
from __future__ import annotations

import json
from datetime import date

from app.services.soldiers import approve_field_update, submit_field_update
from tests.helpers import create_soldier


def test_submit_military_license_captures_previous_value(admin_session):
    s = create_soldier(admin_session, personal_number="7700001")
    req = submit_field_update(
        admin_session,
        soldier_id=s.id,
        field_name="military_driving_license",
        new_value=json.dumps({"has_license": True, "expiry_date": "2027-01-01"}),
        actor_id=s.id,
    )
    admin_session.commit()
    assert json.loads(req.previous_value) == {"has_license": False, "expiry_date": None}


def test_approve_military_license_sets_both_columns(admin_session):
    s = create_soldier(admin_session, personal_number="7700002")
    req = submit_field_update(
        admin_session,
        soldier_id=s.id,
        field_name="military_driving_license",
        new_value=json.dumps({"has_license": True, "expiry_date": "2027-06-15"}),
        actor_id=s.id,
    )
    admin_session.flush()
    approve_field_update(admin_session, update=req, actor_id=s.id)
    admin_session.commit()
    admin_session.refresh(s)
    assert s.has_military_driving_license is True
    assert s.military_driving_license_expiry == date(2027, 6, 15)


def test_approve_military_license_with_no_expiry(admin_session):
    s = create_soldier(admin_session, personal_number="7700003")
    req = submit_field_update(
        admin_session,
        soldier_id=s.id,
        field_name="military_driving_license",
        new_value=json.dumps({"has_license": True, "expiry_date": None}),
        actor_id=s.id,
    )
    admin_session.flush()
    approve_field_update(admin_session, update=req, actor_id=s.id)
    admin_session.commit()
    admin_session.refresh(s)
    assert s.has_military_driving_license is True
    assert s.military_driving_license_expiry is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest backend/tests/unit/test_soldiers_service.py -v
```
Expected: FAIL — `submit_field_update` raises `SoldierError("field_not_editable")` unless Task 2 already landed; `previous_value` won't be the expected JSON shape and `approve_field_update` won't set the new columns.

- [ ] **Step 3: Implement**

In `backend/app/services/soldiers.py`, add `import json` to the top imports (line 3, alphabetically before `re`):
```python
from __future__ import annotations

import json
import re
import secrets
import string
import uuid
from datetime import date, datetime, timezone
from typing import Any, NamedTuple
```

Replace `_get_current_value` (lines 198-204):
```python
def _get_current_value(soldier: Soldier, field_name: str) -> str | None:
    if field_name == "military_driving_license":
        return json.dumps({
            "has_license": bool(soldier.has_military_driving_license),
            "expiry_date": soldier.military_driving_license_expiry.isoformat()
                if soldier.military_driving_license_expiry else None,
        })
    raw = getattr(soldier, field_name, None)
    if raw is None:
        return None
    if isinstance(raw, date):
        return raw.isoformat()
    return str(raw)
```

In `approve_field_update` (lines 260-271), add a branch:
```python
    field = update.field_name
    raw = update.new_value
    if field == "last_mitvahim_date":
        soldier.last_mitvahim_date = date.fromisoformat(raw)
    elif field == "last_alal_date":
        soldier.last_alal_date = date.fromisoformat(raw)
    elif field == "gender":
        soldier.gender = raw
    elif field == "rank":
        soldier.rank = raw
    elif field == "phone":
        soldier.phone = raw
    elif field == "military_driving_license":
        payload = json.loads(raw)
        soldier.has_military_driving_license = payload["has_license"]
        expiry = payload.get("expiry_date")
        soldier.military_driving_license_expiry = date.fromisoformat(expiry) if expiry else None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest backend/tests/unit/test_soldiers_service.py -v
```
Expected: all 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/soldiers.py backend/tests/unit/test_soldiers_service.py
git commit -m "feat: handle military_driving_license JSON payload in field-update service"
```

---

### Task 5: Route wiring — serialization + rank-gated approval

**Files:**
- Modify: `backend/app/routes/soldiers.py:42-66` (`SoldierOut`), `:164-195` (`_out`), `:216-224` (near `_load`/`_node_of`), `:592-634` (`approve_update`/`reject_update`)
- Modify: `backend/app/routes/me.py:21-47` (`MeResponse`), `:91-118` (`me()`)
- Modify: `backend/tests/integration/test_soldier_profile.py`

**Interfaces:**
- Consumes: `Action.MILITARY_LICENSE_DECIDE` (Task 3), `Soldier.has_military_driving_license`/`military_driving_license_expiry` (Task 1).
- Produces: `SoldierOut.has_military_driving_license`, `SoldierOut.military_driving_license_expiry`, same two fields on `MeResponse` — consumed by Task 7 (frontend).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/integration/test_soldier_profile.py`:

```python
import json


def test_soldier_submits_military_license_dm_approves(client, admin_session):
    dm, node = _setup_dm(admin_session, "prof_dm_005")
    s = create_soldier(admin_session, personal_number="prof_s_005", hierarchy_node_id=node.id)

    resp = client.post(
        f"/api/soldiers/{s.id}/field-updates",
        json={
            "field_name": "military_driving_license",
            "new_value": json.dumps({"has_license": True, "expiry_date": "2028-01-01"}),
        },
        headers=auth_headers(s),
    )
    assert resp.status_code == 201
    update_id = resp.json()["id"]

    resp2 = client.post(
        f"/api/soldiers/{s.id}/field-updates/{update_id}/approve",
        json={},
        headers=auth_headers(dm),
    )
    assert resp2.status_code == 200

    profile = client.get(f"/api/soldiers/{s.id}", headers=auth_headers(dm))
    assert profile.json()["has_military_driving_license"] is True
    assert profile.json()["military_driving_license_expiry"] == "2028-01-01"


def test_commander_below_rasan_cannot_approve_military_license(client, admin_session):
    node = create_node(admin_session, level="branch", name="branch_prof_006")
    cmd = create_soldier(admin_session, personal_number="prof_cmd_006", role="commander")
    cmd.rank = "סרן"
    node.commander_id = cmd.id
    admin_session.commit()
    s = create_soldier(admin_session, personal_number="prof_s_006", hierarchy_node_id=node.id)

    resp = client.post(
        f"/api/soldiers/{s.id}/field-updates",
        json={
            "field_name": "military_driving_license",
            "new_value": json.dumps({"has_license": True, "expiry_date": None}),
        },
        headers=auth_headers(s),
    )
    update_id = resp.json()["id"]

    resp2 = client.post(
        f"/api/soldiers/{s.id}/field-updates/{update_id}/approve",
        json={},
        headers=auth_headers(cmd),
    )
    assert resp2.status_code == 403


def test_commander_rasan_and_above_can_approve_military_license(client, admin_session):
    node = create_node(admin_session, level="branch", name="branch_prof_007")
    cmd = create_soldier(admin_session, personal_number="prof_cmd_007", role="commander")
    cmd.rank = "רסן"
    node.commander_id = cmd.id
    admin_session.commit()
    s = create_soldier(admin_session, personal_number="prof_s_007", hierarchy_node_id=node.id)

    resp = client.post(
        f"/api/soldiers/{s.id}/field-updates",
        json={
            "field_name": "military_driving_license",
            "new_value": json.dumps({"has_license": True, "expiry_date": None}),
        },
        headers=auth_headers(s),
    )
    update_id = resp.json()["id"]

    resp2 = client.post(
        f"/api/soldiers/{s.id}/field-updates/{update_id}/approve",
        json={},
        headers=auth_headers(cmd),
    )
    assert resp2.status_code == 200, resp2.text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest backend/tests/integration/test_soldier_profile.py -k military_license -v
```
Expected: FAIL — `has_military_driving_license`/`military_driving_license_expiry` missing from the `SoldierOut` response (`KeyError`/`None`), and both commander tests fail because `approve_update` still calls the blanket `Action.SOLDIER_UPDATE` check (which isn't in `_COMMANDER_ACTIONS`, so both commander cases currently 403 regardless of rank).

- [ ] **Step 3: Implement route changes**

In `backend/app/routes/soldiers.py`, add to `SoldierOut` (after `bahad1_graduate: bool = False`, currently line 56):
```python
    bahad1_graduate: bool = False
    has_military_driving_license: bool | None = None
    military_driving_license_expiry: date_type | None = None
```

Add to `_out()` (after `bahad1_graduate=s.bahad1_graduate,`, currently line 184):
```python
        bahad1_graduate=s.bahad1_graduate,
        has_military_driving_license=s.has_military_driving_license,
        military_driving_license_expiry=s.military_driving_license_expiry,
```

Add a shared authorization helper right after `_node_of` (currently lines 223-224):
```python
def _node_of(session: Session, s: Soldier) -> HierarchyNode | None:
    return session.get(HierarchyNode, s.hierarchy_node_id) if s.hierarchy_node_id else None


def _authorize_field_update_decision(session: Session, user: Soldier, s: Soldier, field_name: str) -> None:
    action = Action.MILITARY_LICENSE_DECIDE if field_name == "military_driving_license" else Action.SOLDIER_UPDATE
    authorize(session, user, action, target_node=_node_of(session, s))
```

Update `approve_update` (currently lines 592-611) to use it instead of the bare `authorize(...)` call:
```python
@router.post("/{soldier_id}/field-updates/{update_id}/approve", response_model=FieldUpdateOut)
def approve_update(
    soldier_id: uuid.UUID,
    update_id: uuid.UUID,
    body: FieldUpdateDecisionRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> FieldUpdateOut:
    s = _load(session, soldier_id)
    upd = session.get(SoldierFieldUpdate, update_id)
    if upd is None or upd.soldier_id != soldier_id:
        raise HTTPException(status_code=404, detail="not_found")
    _authorize_field_update_decision(session, user, s, upd.field_name)
    try:
        approve_field_update(session, update=upd, actor_id=user.id, decision_note=body.decision_note)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    session.refresh(upd)
    return _fu_out(upd, include_values=can_see_private(session, user, s))
```

Update `reject_update` (currently lines 614-633) the same way:
```python
@router.post("/{soldier_id}/field-updates/{update_id}/reject", response_model=FieldUpdateOut)
def reject_update(
    soldier_id: uuid.UUID,
    update_id: uuid.UUID,
    body: FieldUpdateDecisionRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> FieldUpdateOut:
    s = _load(session, soldier_id)
    upd = session.get(SoldierFieldUpdate, update_id)
    if upd is None or upd.soldier_id != soldier_id:
        raise HTTPException(status_code=404, detail="not_found")
    _authorize_field_update_decision(session, user, s, upd.field_name)
    try:
        reject_field_update(session, update=upd, actor_id=user.id, decision_note=body.decision_note)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.commit()
    session.refresh(upd)
    return _fu_out(upd, include_values=can_see_private(session, user, s))
```

In `backend/app/routes/me.py`, add to `MeResponse` (after `bahad1_graduate: bool = False`, currently line 36):
```python
    bahad1_graduate: bool = False
    has_military_driving_license: bool | None = None
    military_driving_license_expiry: str | None = None
```

Add to `me()` construction (after `bahad1_graduate=user.bahad1_graduate or False,`, currently line 106):
```python
        bahad1_graduate=user.bahad1_graduate or False,
        has_military_driving_license=user.has_military_driving_license,
        military_driving_license_expiry=_date(user.military_driving_license_expiry),
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest backend/tests/integration/test_soldier_profile.py -v
```
Expected: all PASS, including the 3 new tests and all pre-existing ones in this file.

- [ ] **Step 5: Run the full fast backend suite**

```bash
pytest -q
```
Expected: PASS (no regressions in `test_authz.py`, `test_eligibility.py`, `test_soldiers_service.py`, or elsewhere).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/soldiers.py backend/app/routes/me.py backend/tests/integration/test_soldier_profile.py
git commit -m "feat: serialize military license fields and gate approval by rank"
```

---

### Task 6: Frontend types + duty-type requirements editor + i18n

**Files:**
- Modify: `frontend/src/api/soldiers.ts:3-27,79` (`SoldierDTO`, `updateSoldierProfile` field union)
- Modify: `frontend/src/api/auth.ts:9-36` (`Me` interface)
- Modify: `frontend/src/api/dutyConfig.ts:11-20` (`DutyType["requirements"]`)
- Modify: `frontend/src/components/DutyTypeRequirementsEditor.tsx:102-118` (boolean-flags list)
- Modify: `frontend/src/i18n/he.json:470-515` (`soldier_profile`, `eligibility` sections)

**Interfaces:**
- Consumes: `has_military_driving_license`/`military_driving_license_expiry` fields on `SoldierOut`/`MeResponse` (Task 5), `requires_military_driving_license` on `DutyTypeRequirements` (Task 2).
- Produces: typed fields available to Task 7 (`ProfilePage.tsx`).

- [ ] **Step 1: Add fields to `SoldierDTO`**

In `frontend/src/api/soldiers.ts`, after `bahad1_graduate: boolean;` (line 16):
```typescript
  bahad1_graduate: boolean;
  has_military_driving_license: boolean | null;
  military_driving_license_expiry: string | null;
```

- [ ] **Step 2: Add fields to `Me`**

In `frontend/src/api/auth.ts`, after `bahad1_graduate?: boolean;` (line 24):
```typescript
  bahad1_graduate?: boolean;
  has_military_driving_license?: boolean | null;
  military_driving_license_expiry?: string | null;
```

- [ ] **Step 3: Add the requirement flag to `DutyType`**

In `frontend/src/api/dutyConfig.ts`, after `requires_bahad1?: boolean;` (line 19):
```typescript
    requires_bahad1?: boolean;
    requires_military_driving_license?: boolean;
```

- [ ] **Step 4: Add the boolean flag to the requirements editor**

In `frontend/src/components/DutyTypeRequirementsEditor.tsx`, in the boolean-flags array (lines 103-108):
```typescript
      {[
        { key: "requires_mitvahim", label: t("eligibility.requires_mitvahim") },
        { key: "requires_alal", label: t("eligibility.requires_alal") },
        { key: "requires_bahad1", label: t("eligibility.requires_bahad1") },
        { key: "requires_military_driving_license", label: t("eligibility.requires_military_driving_license") },
        { key: "officers_allowed", label: t("eligibility.officers_allowed"), defaultVal: true },
        { key: "enlisted_allowed", label: t("eligibility.enlisted_allowed"), defaultVal: true },
      ].map(({ key, label, defaultVal }) => (
```

- [ ] **Step 5: Add i18n labels**

In `frontend/src/i18n/he.json`, in `soldier_profile` (after `"bahad1_graduate": "בוגר בה\"ד 1",` on line 481):
```json
    "bahad1_graduate": "בוגר בה\"ד 1",
    "military_driving_license": "רשנ\"צ (רישיון נהיגה צבאי)",
    "military_driving_license_expiry": "תאריך תפוגה",
    "military_driving_license_has": "יש רשנ\"צ",
```

In `eligibility` (after `"requires_bahad1": "נדרש בוגר בה\"ד 1",` on line 513):
```json
    "requires_bahad1": "נדרש בוגר בה\"ד 1",
    "requires_military_driving_license": "נדרש רשנ\"צ",
```

- [ ] **Step 6: Typecheck**

```bash
npm run typecheck
```
(run from `frontend/`)
Expected: no new errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/soldiers.ts frontend/src/api/auth.ts frontend/src/api/dutyConfig.ts frontend/src/components/DutyTypeRequirementsEditor.tsx frontend/src/i18n/he.json
git commit -m "feat: add military driving license types, requirements flag, and i18n labels"
```

---

### Task 7: ProfilePage — display, request form, history rendering

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx:23-48` (state), `:88-101` (`requestUpdate`), `:199-222` (display block), `:224-305` (request form block), `:307-327` (history block)

**Interfaces:**
- Consumes: `SoldierDTO.has_military_driving_license`/`military_driving_license_expiry` (Task 6), `submitFieldUpdate`/`listFieldUpdates` (existing, unchanged signatures).

- [ ] **Step 1: Add local state for the request form**

In `frontend/src/pages/ProfilePage.tsx`, after `const [phoneReq, setPhoneReq] = useState("");` (line 32):
```typescript
  const [phoneReq, setPhoneReq] = useState("");
  const [licenseHasReq, setLicenseHasReq] = useState(false);
  const [licenseExpiryReq, setLicenseExpiryReq] = useState("");
```

- [ ] **Step 2: Add a JSON-encoding helper and wire it into `requestUpdate`'s reset logic**

Add near the top of the component body (after the `useState` declarations, before `useEffect`s), and extend `requestUpdate`'s reset block (currently lines 94-98):

```typescript
  function militaryLicensePayload(hasLicense: boolean, expiry: string): string {
    return JSON.stringify({ has_license: hasLicense, expiry_date: expiry || null });
  }
```

```typescript
      if (field === "last_mitvahim_date") setMitvahimReq("");
      if (field === "last_alal_date") setAlalReq("");
      if (field === "gender") setGenderReq("");
      if (field === "rank") setRankReq("");
      if (field === "phone") setPhoneReq("");
      if (field === "military_driving_license") { setLicenseHasReq(false); setLicenseExpiryReq(""); }
```

- [ ] **Step 3: Add the display block**

In the profile display grid, after the `bahad1_graduate` block (currently lines 208-210):
```typescript
          {user?.bahad1_graduate !== undefined && (
            <div><span className="font-medium">{t("soldier_profile.bahad1_graduate")}:</span> {user.bahad1_graduate ? "✓" : "—"}</div>
          )}
          {user?.has_military_driving_license !== undefined && user?.has_military_driving_license !== null && (
            <div>
              <span className="font-medium">{t("soldier_profile.military_driving_license")}:</span>{" "}
              {user.has_military_driving_license
                ? (user.military_driving_license_expiry
                    ? `✓ (${t("soldier_profile.military_driving_license_expiry")}: ${formatDate(user.military_driving_license_expiry)})`
                    : "✓")
                : "—"}
            </div>
          )}
```

- [ ] **Step 4: Add the request form row**

In the "submit_update" section, after the `last_alal_date` row (currently lines 269-275):
```typescript
          <div className="flex gap-2 items-center">
            <label className="w-40">{t("soldier_profile.military_driving_license")}</label>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={licenseHasReq} onChange={e => setLicenseHasReq(e.target.checked)} />
              {t("soldier_profile.military_driving_license_has")}
            </label>
            <input
              type="date"
              lang="he"
              value={licenseExpiryReq}
              onChange={e => setLicenseExpiryReq(e.target.value)}
              disabled={!licenseHasReq}
              className="border rounded p-1 text-sm dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100 disabled:opacity-50"
            />
            <button
              type="button"
              onClick={() => requestUpdate("military_driving_license", militaryLicensePayload(licenseHasReq, licenseExpiryReq))}
              className="bg-blue-600 text-white px-3 py-1 rounded text-xs hover:bg-blue-700"
            >
              {t("soldier_profile.submit_update")}
            </button>
          </div>
```

- [ ] **Step 5: Format the field in the pending-updates history block**

Replace the `previous_value`/`new_value` rendering (currently lines 318-323) to special-case the new JSON-encoded field, alongside the existing `gender` special case:
```typescript
                <div className="text-gray-500">
                  {t("soldier_profile.previous_value")}: <span className="font-mono">{formatFieldUpdateValue(u.field_name, u.previous_value, t)}</span>
                </div>
                <div className="text-gray-500">
                  {t("soldier_profile.new_value")}: <span className="font-mono">{formatFieldUpdateValue(u.field_name, u.new_value, t)}</span>
                </div>
```

Add `formatFieldUpdateValue` as a module-level function (outside the component, near the top of the file, after the imports):
```typescript
function formatFieldUpdateValue(
  fieldName: string,
  value: string | null,
  t: (key: string) => string
): string {
  if (!value) return "—";
  if (fieldName === "gender") return t(`soldier_profile.gender_${value}`);
  if (fieldName === "military_driving_license") {
    try {
      const parsed = JSON.parse(value) as { has_license: boolean; expiry_date: string | null };
      if (!parsed.has_license) return "—";
      return parsed.expiry_date ? `✓ (${formatDate(parsed.expiry_date)})` : "✓";
    } catch {
      return value;
    }
  }
  return value;
}
```

- [ ] **Step 6: Manual verification (no automated frontend test exists for this page today)**

Start the dev stack (`.\dev.ps1`), log in as a soldier, go to Profile:
- Confirm the request row renders with a checkbox + date input (date input disabled until checkbox checked).
- Submit a request with the checkbox checked and a future expiry date; confirm it appears in the pending-updates list as "רשנ״צ (רישיון נהיגה צבאי)" with status "ממתין לאישור" and the new value showing `✓ (<date>)`.
- Log in as the soldier's duty manager, approve the request; reload the soldier's profile and confirm the display block now shows `✓ (תאריך תפוגה: <date>)`.
- In Duty Config, open a duty type's requirements editor and confirm the new "נדרש רשנ״צ" checkbox appears and saves.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/ProfilePage.tsx
git commit -m "feat: add military driving license request UI to profile page"
```

---

## Self-Review Notes

- **Spec coverage:** data model (Task 1), eligibility rule (Task 2), approval authorization rank-gating (Task 3, implemented via the existing `can()`/`authorize()` framework rather than the spec's originally-sketched ad hoc `commander_can_grant_commander_exemption` reuse — this is a cleaner fit with the codebase's existing rank-gated-commander-action pattern already used for `POTENTIAL_READ`/`DM_SCOPE_MANAGE`, and satisfies the same requirement: commander must be rank רסן+ AND in the soldier's chain of command), JSON payload encode/decode (Task 4), route serialization + wiring (Task 5), frontend types/requirements editor/i18n (Task 6), profile UI (Task 7) — all covered.
- **Type consistency:** `military_driving_license` field name, `has_license`/`expiry_date` JSON keys, and `has_military_driving_license`/`military_driving_license_expiry` column/field names are used identically across all seven tasks.
- **No placeholders:** every step has literal code.
