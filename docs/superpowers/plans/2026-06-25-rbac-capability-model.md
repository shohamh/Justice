# RBAC Capability Model Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop deriving commander/duty-manager authorization from the single `Soldier.role` string; derive it from real data (`HierarchyNode.commander_id`, `DutyManagerScope` rows) everywhere a permission decision is made, so a soldier can simultaneously command one node and be duty-manager of others without either capability clobbering the other.

**Architecture:** Add `is_commander`/`is_duty_manager` query helpers in `app/auth/authz.py`. Rewrite `can()`, `authorize()`, and `can_see_private()` to consume those instead of switching on `user.role`. Add a `recompute_role()` helper that keeps `Soldier.role` as a derived, read-only *display* label (priority: admin > commander > duty_manager > soldier) — never an authorization input. Sweep every other backend call site that checks `user.role == "commander"/"duty_manager"` for a permission decision, and the matching frontend gates, to use the same capability booleans (exposed on `Me`).

**Tech Stack:** Python/FastAPI/SQLAlchemy backend, pytest; React/TypeScript frontend, vitest.

**Spec:** `docs/superpowers/specs/2026-06-25-rbac-capability-model-design.md`

---

## Task 1: Add `is_commander`/`is_duty_manager` helpers; fix `scope_root_ids` dm-union bug

**Files:**
- Modify: `backend/app/auth/authz.py`
- Test: `backend/app/services/tests/test_dm_scope.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/app/services/tests/test_dm_scope.py` (near the other `scope_root_ids` tests):

```python
def test_scope_root_ids_includes_dm_nodes_regardless_of_role_label(admin_session):
    """A soldier labeled 'commander' who also holds a DutyManagerScope row must still
    get that node in their roots — scope_root_ids must not gate DM nodes on role=='duty_manager'."""
    from app.db.models import DutyManagerScope
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    cmd = create_soldier(admin_session, personal_number=f"cmd_{_uid()}", role="commander")
    admin_session.add(DutyManagerScope(duty_manager_id=cmd.id, hierarchy_node_id=node.id))
    admin_session.commit()

    from app.auth.authz import scope_root_ids
    roots = scope_root_ids(admin_session, cmd)
    assert node.id in roots


def test_is_commander_and_is_duty_manager_helpers(admin_session):
    from app.auth.authz import is_commander, is_duty_manager
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    cmd = create_soldier(admin_session, personal_number=f"cmd_{_uid()}", role="commander")
    node.commander_id = cmd.id
    plain = create_soldier(admin_session, personal_number=f"s_{_uid()}", role="soldier")
    admin_session.commit()

    assert is_commander(admin_session, cmd.id) is True
    assert is_duty_manager(admin_session, cmd.id) is False
    assert is_commander(admin_session, plain.id) is False
    assert is_duty_manager(admin_session, plain.id) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_dm_scope.py -k "includes_dm_nodes_regardless or is_commander_and_is_duty_manager" -v`
Expected: FAIL — `test_scope_root_ids_includes_dm_nodes_regardless_of_role_label` fails because `cmd.role == "commander"` so the current guard skips the DM union; `test_is_commander_and_is_duty_manager_helpers` fails with `ImportError`/`AttributeError` since the helpers don't exist yet.

- [ ] **Step 3: Implement the helpers and fix the guard**

In `backend/app/auth/authz.py`, add the two helpers right after `PRIVATE_FIELD_NAMES` (before `class Action`), and fix `scope_root_ids`:

```python
def is_commander(session: Session, soldier_id: uuid.UUID) -> bool:
    """True iff this soldier currently commands at least one hierarchy node."""
    return (
        session.execute(
            select(HierarchyNode.id).where(HierarchyNode.commander_id == soldier_id).limit(1)
        ).first()
        is not None
    )


def is_duty_manager(session: Session, soldier_id: uuid.UUID) -> bool:
    """True iff this soldier currently holds at least one DutyManagerScope row."""
    return (
        session.execute(
            select(DutyManagerScope.id)
            .where(DutyManagerScope.duty_manager_id == soldier_id)
            .limit(1)
        ).first()
        is not None
    )
```

Then in `scope_root_ids`, remove the `if user.role == "duty_manager":` guard so DM nodes are always unioned:

```python
def scope_root_ids(session: Session, user: Soldier) -> set[uuid.UUID]:
    """The node ids whose subtrees this user governs."""
    roots: set[uuid.UUID] = set()
    dm_nodes = (
        session.execute(
            select(DutyManagerScope.hierarchy_node_id).where(
                DutyManagerScope.duty_manager_id == user.id
            )
        )
        .scalars()
        .all()
    )
    roots.update(dm_nodes)
    commanded = (
        session.execute(select(HierarchyNode.id).where(HierarchyNode.commander_id == user.id))
        .scalars()
        .all()
    )
    roots.update(commanded)
    return roots
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_dm_scope.py -v`
Expected: PASS (all tests in the file, including the two new ones and the pre-existing ones — `scope_root_ids` behavior for plain duty managers is unchanged, only the role-label guard was removed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/auth/authz.py backend/app/services/tests/test_dm_scope.py
git commit -m "fix: derive DM scope from real data regardless of role label"
```

---

## Task 2: Rewrite `can()`/`authorize()`/`can_see_private()` to use capability flags

This is one atomic change: `can()`'s signature changes, so every caller must be updated in the same commit or the app won't import/run correctly.

**Files:**
- Modify: `backend/app/auth/authz.py`
- Modify: `backend/app/routes/calendar.py:190`
- Modify: `backend/app/routes/swaps.py:270,448`
- Modify: `backend/app/routes/soldiers.py:332,376`
- Modify: `backend/app/routes/gimelim.py:46`
- Modify: `backend/app/routes/hakpaza.py:30-51` (`_authorize_assignment_scope`)
- Modify: `backend/app/services/tests/test_dm_scope.py:74-102`
- Modify: `backend/tests/unit/test_authz.py` (full rewrite)
- Modify: `backend/tests/integration/test_hierarchy_api.py:87`

- [ ] **Step 1: Write the failing tests (rewrite `test_authz.py`)**

Replace the entire contents of `backend/tests/unit/test_authz.py` with:

```python
from app.auth import authz
from tests.helpers import create_node, create_soldier


def _roots(session, user):
    return authz.scope_root_ids(session, user)


def _caps(session, user):
    return authz.is_commander(session, user.id), authz.is_duty_manager(session, user.id)


def test_admin_can_everything_globally(admin_session):
    admin = create_soldier(admin_session, personal_number="7000001", role="admin")
    d = create_node(admin_session, level="department", name="d")
    is_cmd, is_dm = _caps(admin_session, admin)
    assert authz.can(
        admin, authz.Action.SOLDIER_CREATE, target_node=d, roots=_roots(admin_session, admin),
        is_commander=is_cmd, is_duty_manager=is_dm,
    )
    assert authz.can(
        admin, authz.Action.HIERARCHY_MANAGE, target_node=d, roots=_roots(admin_session, admin),
        is_commander=is_cmd, is_duty_manager=is_dm,
    )


def test_duty_manager_scoped_to_own_subtree(admin_session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    dm = create_soldier(
        admin_session, personal_number="7000002", role="duty_manager", hierarchy_node_id=b.id
    )
    roots = _roots(admin_session, dm)
    is_cmd, is_dm = _caps(admin_session, dm)
    assert authz.can(dm, authz.Action.SOLDIER_CREATE, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert not authz.can(dm, authz.Action.SOLDIER_CREATE, target_node=other, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_commander_read_only_in_commanded_subtree(admin_session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    cmd = create_soldier(admin_session, personal_number="7000003", role="commander")
    b.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    is_cmd, is_dm = _caps(admin_session, cmd)
    assert authz.can(cmd, authz.Action.SOLDIER_READ, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert authz.can(cmd, authz.Action.HIERARCHY_READ, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert not authz.can(cmd, authz.Action.SOLDIER_CREATE, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_plain_soldier_has_no_management(admin_session):
    d = create_node(admin_session, level="department", name="d")
    s = create_soldier(
        admin_session, personal_number="7000004", role="soldier", hierarchy_node_id=d.id
    )
    roots = _roots(admin_session, s)
    assert roots == set()
    is_cmd, is_dm = _caps(admin_session, s)
    assert not authz.can(s, authz.Action.SOLDIER_READ, target_node=d, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_commander_can_grant_and_read_exemptions_in_subtree(admin_session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    other = create_node(admin_session, level="department", name="other")
    cmd = create_soldier(admin_session, personal_number="7100001", role="commander")
    b.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    is_cmd, is_dm = _caps(admin_session, cmd)
    assert authz.can(cmd, authz.Action.EXEMPTION_GRANT, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert authz.can(cmd, authz.Action.EXEMPTION_READ, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert not authz.can(cmd, authz.Action.EXEMPTION_GRANT, target_node=other, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_duty_manager_can_grant_exemptions_in_scope(admin_session):
    d = create_node(admin_session, level="department", name="d")
    b = create_node(admin_session, level="branch", name="b", parent=d)
    dm = create_soldier(
        admin_session, personal_number="7100002", role="duty_manager", hierarchy_node_id=b.id
    )
    roots = _roots(admin_session, dm)
    is_cmd, is_dm = _caps(admin_session, dm)
    assert authz.can(dm, authz.Action.EXEMPTION_GRANT, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_plain_soldier_cannot_grant_exemptions(admin_session):
    d = create_node(admin_session, level="department", name="d")
    s = create_soldier(
        admin_session, personal_number="7100003", role="soldier", hierarchy_node_id=d.id
    )
    roots = _roots(admin_session, s)
    is_cmd, is_dm = _caps(admin_session, s)
    assert not authz.can(s, authz.Action.EXEMPTION_GRANT, target_node=d, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_duty_manager_can_manage_assignments_and_scores_in_scope(admin_session):
    d = create_node(admin_session, level="department", name="d-s4")
    b = create_node(admin_session, level="branch", name="b-s4", parent=d)
    other = create_node(admin_session, level="department", name="other-s4")
    dm = create_soldier(
        admin_session, personal_number="7400001", role="duty_manager", hierarchy_node_id=b.id
    )
    roots = _roots(admin_session, dm)
    is_cmd, is_dm = _caps(admin_session, dm)
    assert authz.can(dm, authz.Action.ASSIGNMENT_MANAGE, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert authz.can(dm, authz.Action.SCORE_ADJUST, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert not authz.can(dm, authz.Action.ASSIGNMENT_MANAGE, target_node=other, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_commander_cannot_manage_assignments(admin_session):
    d = create_node(admin_session, level="department", name="d-s4b")
    b = create_node(admin_session, level="branch", name="b-s4b", parent=d)
    cmd = create_soldier(admin_session, personal_number="7400002", role="commander")
    b.commander_id = cmd.id
    admin_session.flush()
    roots = _roots(admin_session, cmd)
    is_cmd, is_dm = _caps(admin_session, cmd)
    assert not authz.can(cmd, authz.Action.ASSIGNMENT_MANAGE, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert not authz.can(cmd, authz.Action.SCORE_ADJUST, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_plain_soldier_cannot_manage_assignments(admin_session):
    d = create_node(admin_session, level="department", name="d-s4c")
    s = create_soldier(
        admin_session, personal_number="7400003", role="soldier", hierarchy_node_id=d.id
    )
    roots = _roots(admin_session, s)
    is_cmd, is_dm = _caps(admin_session, s)
    assert not authz.can(s, authz.Action.ASSIGNMENT_MANAGE, target_node=d, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


def test_dual_role_soldier_keeps_both_capabilities(admin_session):
    """A soldier who commands node A and is DM of node B keeps DM_SCOPE_MANAGE over A
    and DM actions over B simultaneously — neither capability clobbers the other."""
    from app.db.models import DutyManagerScope

    a = create_node(admin_session, level="department", name="dual-a")
    b = create_node(admin_session, level="department", name="dual-b")
    dual = create_soldier(admin_session, personal_number="7500001", role="commander")
    dual.rank = "רסן"
    a.commander_id = dual.id
    admin_session.add(DutyManagerScope(duty_manager_id=dual.id, hierarchy_node_id=b.id))
    admin_session.commit()

    roots = _roots(admin_session, dual)
    is_cmd, is_dm = _caps(admin_session, dual)
    assert is_cmd and is_dm
    assert authz.can(dual, authz.Action.DM_SCOPE_MANAGE, target_node=a, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert authz.can(dual, authz.Action.ASSIGNMENT_MANAGE, target_node=b, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)
    assert authz.can(dual, authz.Action.ALGORITHM_RUN, target_node=None, roots=roots, is_commander=is_cmd, is_duty_manager=is_dm)


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

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_authz.py -v`
Expected: FAIL — `TypeError: can() missing 2 required keyword-only arguments: 'is_commander', 'is_duty_manager'` on every test.

- [ ] **Step 3: Rewrite `can()`, `authorize()`, `can_see_private()` in `authz.py`**

Remove `SOLDIER_ASSIGN_ROLE = "soldier.assign_role"` from `class Action` (it only existed to gate the endpoint being removed in Task 4; nothing will reference it after this task).

Replace the existing `can()` function with:

```python
def can(
    user: Soldier,
    action: str,
    *,
    target_node: HierarchyNode | None,
    roots: set[uuid.UUID],
    is_commander: bool,
    is_duty_manager: bool,
) -> bool:
    if user.role == "admin":
        return True
    allowed = False
    if is_duty_manager:
        if action in _DM_GLOBAL_ACTIONS:
            return True
        if action in _DM_ACTIONS and _node_in_scope(target_node, roots):
            allowed = True
    if is_commander:
        if action == Action.DM_SCOPE_MANAGE:
            if (
                bool(user.rank and user.rank in RANKS_RASAN_AND_ABOVE)
                and _node_in_scope(target_node, roots)
            ):
                allowed = True
        elif action in _COMMANDER_ACTIONS and _node_in_scope(target_node, roots):
            allowed = True
    return allowed
```

Replace `can_see_private()`:

```python
def can_see_private(session: Session, viewer: Soldier, target: Soldier) -> bool:
    """Return True iff viewer may read private fields on target's record."""
    if viewer.id == target.id:
        return True
    if viewer.role == "admin":
        return False
    if is_commander(session, viewer.id) or is_duty_manager(session, viewer.id):
        roots = scope_root_ids(session, viewer)
        node = session.get(HierarchyNode, target.hierarchy_node_id) if target.hierarchy_node_id else None
        return _node_in_scope(node, roots)
    return False
```

Replace `authorize()`:

```python
def authorize(
    session: Session, user: Soldier, action: str, *, target_node: HierarchyNode | None
) -> None:
    """Raise 403 unless `user` may perform `action` against `target_node`'s subtree."""
    roots = scope_root_ids(session, user)
    if not can(
        user,
        action,
        target_node=target_node,
        roots=roots,
        is_commander=is_commander(session, user.id),
        is_duty_manager=is_duty_manager(session, user.id),
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
```

`authorize()`'s signature is unchanged, so its ~10 existing call sites across the routes (hierarchy.py, dm_scope.py, soldiers.py, etc.) need no changes.

- [ ] **Step 4: Fix the remaining direct `can()` callers**

`backend/app/routes/calendar.py:190` — change:

```python
show_reason = can(user, Action.HIERARCHY_READ, target_node=node, roots=scope_root_ids(session, user))
```

to:

```python
roots = scope_root_ids(session, user)
show_reason = can(
    user, Action.HIERARCHY_READ, target_node=node, roots=roots,
    is_commander=is_commander(session, user.id), is_duty_manager=is_duty_manager(session, user.id),
)
```

Add `is_commander, is_duty_manager` to the `from app.auth.authz import ...` line at the top of `calendar.py`.

`backend/app/routes/swaps.py:270` — change:

```python
roots = scope_root_ids(session, user)
if not can(user, Action.SWAP_APPROVE, target_node=node, roots=roots):
```

to:

```python
roots = scope_root_ids(session, user)
if not can(
    user, Action.SWAP_APPROVE, target_node=node, roots=roots,
    is_commander=is_commander(session, user.id), is_duty_manager=is_duty_manager(session, user.id),
):
```

`backend/app/routes/swaps.py:448` — change:

```python
roots = scope_root_ids(session, user)
return [
    _out_bulk(r, soldiers, nodes, assignments, duty_types, duty_locations)
    for r in all_pending
    if can(user, Action.SWAP_APPROVE, target_node=_requester_node(r), roots=roots)
]
```

to:

```python
roots = scope_root_ids(session, user)
user_is_commander = is_commander(session, user.id)
user_is_duty_manager = is_duty_manager(session, user.id)
return [
    _out_bulk(r, soldiers, nodes, assignments, duty_types, duty_locations)
    for r in all_pending
    if can(
        user, Action.SWAP_APPROVE, target_node=_requester_node(r), roots=roots,
        is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
    )
]
```

Add `is_commander, is_duty_manager` to the `from app.auth.authz import ...` line at the top of `swaps.py`.

`backend/app/routes/soldiers.py:332` and `:376` — both are inside loops (`list_pending_field_updates` and `count_pending_field_updates`). In each function, compute the capability flags once before the loop (next to the existing `roots = scope_root_ids(session, user)` line) and pass them into `can()`:

```python
roots = scope_root_ids(session, user)
if not roots:
    return []
user_is_commander = is_commander(session, user.id)
user_is_duty_manager = is_duty_manager(session, user.id)
from app.auth.authz import can
result = []
for upd in all_pending:
    s = soldiers_by_id.get(upd.soldier_id)
    if s:
        node = nodes_by_id.get(s.hierarchy_node_id) if s.hierarchy_node_id else None
        if can(
            user, Action.SOLDIER_READ, target_node=node, roots=roots,
            is_commander=user_is_commander, is_duty_manager=user_is_duty_manager,
        ):
            soldier_name = s.full_name
            node_name = node.name if node else None
            include_values = can_see_private(session, user, s)
            result.append(_fu_out(upd, soldier_name=soldier_name, node_name=node_name, include_values=include_values))
return result
```

Apply the analogous change to `count_pending_field_updates` (the `if can(user, Action.SOLDIER_READ, ...)` inside its loop, same pattern, computing `user_is_commander`/`user_is_duty_manager` once before the loop). Add `is_commander, is_duty_manager` to the `from app.auth.authz import ...` line at the top of `soldiers.py`.

`backend/app/routes/gimelim.py:46` — change:

```python
roots = scope_root_ids(session, user)
if not can(user, Action.ASSIGNMENT_MANAGE, target_node=target_node, roots=roots):
```

to:

```python
roots = scope_root_ids(session, user)
if not can(
    user, Action.ASSIGNMENT_MANAGE, target_node=target_node, roots=roots,
    is_commander=is_commander(session, user.id), is_duty_manager=is_duty_manager(session, user.id),
):
```

Add `is_commander, is_duty_manager` to the `from app.auth.authz import ...` line at the top of `gimelim.py`.

`backend/app/routes/hakpaza.py` — update `_authorize_assignment_scope` (lines ~30-51):

```python
def _authorize_assignment_scope(
    session: Session,
    actor: Soldier,
    assignment_id: uuid.UUID,
) -> DutyAssignment:
    """Load assignment and verify actor has ASSIGNMENT_MANAGE scope over its soldier. Returns assignment."""
    a = session.get(DutyAssignment, assignment_id)
    if a is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="assignment_not_found")
    soldier = session.get(Soldier, a.soldier_id)
    target_node: HierarchyNode | None = None
    if soldier and soldier.hierarchy_node_id:
        target_node = session.get(HierarchyNode, soldier.hierarchy_node_id)
    # admin bypasses scope checks; duty_manager uses ASSIGNMENT_MANAGE; commanders
    # use HIERARCHY_READ (scope check) since ASSIGNMENT_MANAGE is DM-only by design.
    if actor.role == "admin":
        return a
    roots = scope_root_ids(session, actor)
    actor_is_duty_manager = is_duty_manager(session, actor.id)
    action = Action.ASSIGNMENT_MANAGE if actor_is_duty_manager else Action.HIERARCHY_READ
    if not can(
        actor, action, target_node=target_node, roots=roots,
        is_commander=is_commander(session, actor.id), is_duty_manager=actor_is_duty_manager,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return a
```

Add `is_commander, is_duty_manager` to the `from app.auth.authz import ...` line at the top of `hakpaza.py` (it will be reused again in Task 7).

`backend/app/services/tests/test_dm_scope.py` — update the three `can()` calls:

`test_dm_scope_manage_requires_rasan` (around line 87-88):

```python
    from app.auth.authz import can, scope_root_ids, is_commander, is_duty_manager, Action
    ...
    roots_h = scope_root_ids(admin_session, high_cmd)
    roots_l = scope_root_ids(admin_session, low_cmd)

    assert can(
        high_cmd, Action.DM_SCOPE_MANAGE, target_node=node, roots=roots_h,
        is_commander=is_commander(admin_session, high_cmd.id), is_duty_manager=is_duty_manager(admin_session, high_cmd.id),
    )
    assert not can(
        low_cmd, Action.DM_SCOPE_MANAGE, target_node=node, roots=roots_l,
        is_commander=is_commander(admin_session, low_cmd.id), is_duty_manager=is_duty_manager(admin_session, low_cmd.id),
    )
```

`test_dm_scope_manage_null_rank_denied` (around line 102):

```python
    from app.auth.authz import can, scope_root_ids, is_commander, is_duty_manager, Action
    ...
    roots = scope_root_ids(admin_session, cmd)
    assert not can(
        cmd, Action.DM_SCOPE_MANAGE, target_node=node, roots=roots,
        is_commander=is_commander(admin_session, cmd.id), is_duty_manager=is_duty_manager(admin_session, cmd.id),
    )
```

- [ ] **Step 5: Fix the bare duty-manager fixture in `test_hierarchy_api.py`**

`HIERARCHY_LEVEL_TYPE_MANAGE` is a `_DM_GLOBAL_ACTIONS` member gated by the real `is_duty_manager` flag. `test_create_level_type_as_duty_manager` (line 87) creates a duty manager with no backing `DutyManagerScope` row, which would now correctly fail. Fix the fixture to match how every other DM fixture in the suite is built — give it a real scope:

```python
def test_create_level_type_as_duty_manager(client: TestClient, admin_session: Session):
    node = create_node(admin_session, level="department", name="lt-dm-node")
    dm = create_soldier(
        admin_session, personal_number="5000021", role="duty_manager", hierarchy_node_id=node.id
    )
    r = client.post(
        "/api/hierarchy/level-types",
        headers=auth_headers(dm),
        json={"key": "platoon", "label": "מחלקה"},
    )
    assert r.status_code == 201
    assert r.json()["key"] == "platoon"
```

- [ ] **Step 6: Run the full backend test suite**

Run: `cd backend && pytest -q`
Expected: PASS. (If anything else fails, it's another direct `can()`/role-string caller not yet covered — re-run `grep -rn "authz.can(\|[^_]can(" backend/app` to find it and fix it the same way before moving on.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/auth/authz.py backend/app/routes/calendar.py backend/app/routes/swaps.py backend/app/routes/soldiers.py backend/app/routes/gimelim.py backend/app/routes/hakpaza.py backend/app/services/tests/test_dm_scope.py backend/tests/unit/test_authz.py backend/tests/integration/test_hierarchy_api.py
git commit -m "fix: derive can() decisions from real commander/DM capabilities, not role string"
```

---

## Task 3: Add `recompute_role()`; wire into `set_commander`/`assign_dm_scope`/`remove_dm_scope`

**Files:**
- Modify: `backend/app/services/dm_scope.py`
- Modify: `backend/app/services/hierarchy.py:138-170` (`set_commander`)
- Test: `backend/app/services/tests/test_dm_scope.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/app/services/tests/test_dm_scope.py`:

```python
def test_set_commander_downgrades_displaced_commander_to_soldier(admin_session):
    """When a node's commander is replaced, the displaced soldier (with no other
    commander_id or DM scope) must fall back to role 'soldier', not stay 'commander'."""
    from app.services.hierarchy import set_commander
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    old_cmd = create_soldier(admin_session, personal_number=f"old_{_uid()}", role="soldier")
    new_cmd = create_soldier(admin_session, personal_number=f"new_{_uid()}", role="soldier")
    set_commander(admin_session, node_id=node.id, commander_id=old_cmd.id, actor_id=None)
    admin_session.commit()

    set_commander(admin_session, node_id=node.id, commander_id=new_cmd.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(old_cmd)
    admin_session.refresh(new_cmd)

    assert old_cmd.role == "soldier"
    assert new_cmd.role == "commander"


def test_set_commander_displaced_commander_keeps_dm_role_if_also_dm(admin_session):
    """A displaced commander who is also a duty manager elsewhere falls back to
    'duty_manager', not 'soldier'."""
    from app.db.models import DutyManagerScope
    from app.services.hierarchy import set_commander
    node = create_node(admin_session, level="division", name=f"div_{_uid()}")
    other_node = create_node(admin_session, level="division", name=f"div2_{_uid()}")
    old_cmd = create_soldier(admin_session, personal_number=f"old_{_uid()}", role="soldier")
    new_cmd = create_soldier(admin_session, personal_number=f"new_{_uid()}", role="soldier")
    set_commander(admin_session, node_id=node.id, commander_id=old_cmd.id, actor_id=None)
    admin_session.add(DutyManagerScope(duty_manager_id=old_cmd.id, hierarchy_node_id=other_node.id))
    admin_session.commit()

    set_commander(admin_session, node_id=node.id, commander_id=new_cmd.id, actor_id=None)
    admin_session.commit()
    admin_session.refresh(old_cmd)

    assert old_cmd.role == "duty_manager"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest app/services/tests/test_dm_scope.py -k "displaced_commander" -v`
Expected: FAIL — today `set_commander` never touches the previous commander's role, so `old_cmd.role` stays `"commander"` in both cases.

- [ ] **Step 3: Add `recompute_role` to `dm_scope.py`**

In `backend/app/services/dm_scope.py`, add (near the top, after the imports/`DmScopeError` class):

```python
def recompute_role(session: Session, soldier: Soldier) -> None:
    """Recompute the soldier's display-label role from real capability data.
    Priority: admin > commander > duty_manager > soldier. Never touches admins.
    This is a display label only — authorization no longer reads `role` for
    the commander/duty_manager distinction (see app/auth/authz.py)."""
    if soldier.role == "admin":
        return
    from app.auth.authz import is_commander, is_duty_manager

    if is_commander(session, soldier.id):
        soldier.role = "commander"
    elif is_duty_manager(session, soldier.id):
        soldier.role = "duty_manager"
    else:
        soldier.role = "soldier"
```

Then replace the role-mutation lines inside `assign_dm_scope`:

```python
    soldier = session.get(Soldier, soldier_id)
    assert soldier is not None
    if soldier.role not in ("duty_manager", "admin"):
        soldier.role = "duty_manager"

    session.flush()
```

with:

```python
    soldier = session.get(Soldier, soldier_id)
    assert soldier is not None
    session.flush()
    recompute_role(session, soldier)
```

(`session.flush()` must run before `recompute_role` so the new `DutyManagerScope` row is visible to its query.)

And replace the role-mutation block inside `remove_dm_scope`:

```python
    remaining = session.execute(
        select(func.count()).where(DutyManagerScope.duty_manager_id == soldier_id)
    ).scalar_one()

    if remaining == 0:
        soldier = session.get(Soldier, soldier_id)
        if soldier is not None and soldier.role == "duty_manager":
            commanded = session.execute(
                select(func.count()).where(HierarchyNode.commander_id == soldier_id)
            ).scalar_one()
            soldier.role = "commander" if commanded > 0 else "soldier"
```

with:

```python
    soldier = session.get(Soldier, soldier_id)
    if soldier is not None:
        recompute_role(session, soldier)
```

(The row is already deleted and flushed above this point, so `recompute_role`'s query correctly sees zero remaining `DutyManagerScope` rows for this soldier.)

- [ ] **Step 4: Wire `recompute_role` into `set_commander`**

In `backend/app/services/hierarchy.py`, replace `set_commander` (lines ~138-170):

```python
def set_commander(
    session: Session,
    *,
    node_id: uuid.UUID,
    commander_id: uuid.UUID | None,
    actor_id: uuid.UUID | None = None,
) -> HierarchyNode:
    node = session.get(HierarchyNode, node_id)
    if node is None:
        raise HierarchyError("node not found")
    previous_commander_id = node.commander_id
    if commander_id is not None:
        soldier = session.get(Soldier, commander_id)
        if soldier is None:
            raise HierarchyError("commander not found")
        # Clear this soldier as commander from any other node
        session.query(HierarchyNode).filter(
            HierarchyNode.commander_id == soldier.id,
            HierarchyNode.id != node_id,
        ).update({"commander_id": None})
        soldier.hierarchy_node_id = node_id
    before = {"commander_id": str(node.commander_id) if node.commander_id else None}
    node.commander_id = commander_id
    session.flush()

    from app.services.dm_scope import recompute_role

    if commander_id is not None:
        recompute_role(session, session.get(Soldier, commander_id))
    if previous_commander_id is not None and previous_commander_id != commander_id:
        displaced = session.get(Soldier, previous_commander_id)
        if displaced is not None:
            recompute_role(session, displaced)

    write_audit(
        session,
        actor_id=actor_id,
        action="hierarchy_node.set_commander",
        entity_type="hierarchy_node",
        entity_id=node.id,
        before=before,
        after={"commander_id": str(commander_id) if commander_id else None},
    )
    return node
```

(`soldier.role = "commander"` was removed from the `if commander_id is not None:` block — it's now handled by `recompute_role`, which also correctly downgrades the displaced commander.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest app/services/tests/test_dm_scope.py -v`
Expected: PASS — including the two new tests and all pre-existing ones (`test_assign_dm_scope_grants_dm_role`, `test_remove_dm_scope_downgrades_to_soldier_when_last`, `test_remove_dm_scope_downgrades_to_commander_if_commands_node`, `test_remove_dm_scope_keeps_dm_role_if_other_entries_remain` all assert the exact same outcomes `recompute_role` now produces).

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/dm_scope.py backend/app/services/hierarchy.py backend/app/services/tests/test_dm_scope.py
git commit -m "feat: recompute role label from real capability data, including displaced commanders"
```

---

## Task 4: Remove the unused `POST /soldiers/{id}/role` endpoint and dead code

**Files:**
- Modify: `backend/app/routes/soldiers.py` (remove `RoleRequest`, `set_role` route)
- Modify: `backend/app/services/soldiers.py` (remove `assign_role`, `ROLES`)
- Modify: `frontend/src/api/soldiers.ts` (remove `assignRole`)

- [ ] **Step 1: Confirm nothing references the code being removed**

Run: `cd backend && grep -rn "assign_role\|RoleRequest" app/ tests/` — expect only the definitions and the route, no other callers (already verified during planning; `Action.SOLDIER_ASSIGN_ROLE` was removed in Task 2 and `test_authz.py`'s references to it were dropped in the rewrite).
Run: `cd frontend && grep -rn "assignRole" src/` — expect only the definition in `src/api/soldiers.ts`, no callers.

- [ ] **Step 2: Remove the route and request model**

In `backend/app/routes/soldiers.py`, delete the `RoleRequest` class (lines ~79-80):

```python
class RoleRequest(BaseModel):
    role: str = Field(pattern="^(soldier|commander|duty_manager|admin)$")
```

and delete the `set_role` route (lines ~640-656):

```python
@router.post("/{soldier_id}/role", response_model=SoldierOut)
def set_role(
    soldier_id: uuid.UUID,
    body: RoleRequest,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_roles("admin")),
) -> SoldierOut:
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="must_change_password")
    s = _load(session, soldier_id)
    try:
        svc.assign_role(session, soldier=s, role=body.role, actor_id=user.id)
    except svc.SoldierError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    session.refresh(s)
    return _out(s)
```

If `require_roles` is no longer used elsewhere in `soldiers.py` after this removal, drop it from the `from app.auth.deps import ...` line (check with `grep -n "require_roles" backend/app/routes/soldiers.py`).

- [ ] **Step 3: Remove the service function**

In `backend/app/services/soldiers.py`, delete `ROLES` (line 42) and `assign_role` (lines ~166-182):

```python
ROLES = {"soldier", "commander", "duty_manager", "admin"}
```

```python
def assign_role(
    session: Session, *, soldier: Soldier, role: str, actor_id: uuid.UUID | None = None
) -> Soldier:
    if role not in ROLES:
        raise SoldierError(f"unknown role: {role}")
    before = {"role": soldier.role}
    soldier.role = role
    write_audit(
        session,
        actor_id=actor_id,
        action="soldier.assign_role",
        entity_type="soldier",
        entity_id=soldier.id,
        before=before,
        after={"role": role},
    )
    return soldier
```

- [ ] **Step 4: Remove the dead frontend function**

In `frontend/src/api/soldiers.ts`, delete:

```typescript
export async function assignRole(id: string, role: string): Promise<SoldierDTO> {
  return (await api.post<SoldierDTO>(`/soldiers/${id}/role`, { role })).data;
}
```

- [ ] **Step 5: Run the backend and frontend suites**

Run: `cd backend && pytest -q`
Expected: PASS.

Run: `cd frontend && npm test`
Expected: PASS.

Run: `cd frontend && npm run lint`
Expected: PASS (no unused-import warnings).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/soldiers.py backend/app/services/soldiers.py frontend/src/api/soldiers.ts
git commit -m "chore: remove unused role-override endpoint (role is now derived, never set directly)"
```

---

## Task 5: Expose `is_commander`/`is_duty_manager` on `Me`

**Files:**
- Modify: `backend/app/routes/me.py`
- Modify: `frontend/src/api/auth.ts`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_me_capabilities.py`:

```python
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.helpers import auth_headers, create_node, create_soldier


def test_me_exposes_dual_capabilities(client: TestClient, admin_session: Session):
    from app.db.models import DutyManagerScope

    a = create_node(admin_session, level="department", name="me-cap-a")
    b = create_node(admin_session, level="department", name="me-cap-b")
    dual = create_soldier(admin_session, personal_number="me-cap-001", role="commander")
    a.commander_id = dual.id
    admin_session.add(DutyManagerScope(duty_manager_id=dual.id, hierarchy_node_id=b.id))
    admin_session.commit()

    r = client.get("/api/me", headers=auth_headers(dual))
    assert r.status_code == 200
    body = r.json()
    assert body["is_commander"] is True
    assert body["is_duty_manager"] is True


def test_me_plain_soldier_has_no_capabilities(client: TestClient, admin_session: Session):
    s = create_soldier(admin_session, personal_number="me-cap-002", role="soldier")
    r = client.get("/api/me", headers=auth_headers(s))
    assert r.status_code == 200
    body = r.json()
    assert body["is_commander"] is False
    assert body["is_duty_manager"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_me_capabilities.py -v`
Expected: FAIL with `KeyError: 'is_commander'`.

- [ ] **Step 3: Add the fields to `MeResponse` and the handler**

In `backend/app/routes/me.py`, add to `MeResponse` (after `role: str`):

```python
    role: str
    is_commander: bool
    is_duty_manager: bool
```

Add the import at the top:

```python
from app.auth.authz import is_commander, is_duty_manager
```

In the `me()` handler, add the computed values to the constructor call:

```python
    return MeResponse(
        id=user.id,
        personal_number=user.personal_number,
        full_name=user.full_name,
        role=user.role,
        is_commander=is_commander(session, user.id),
        is_duty_manager=is_duty_manager(session, user.id),
        must_change_password=user.must_change_password,
        ...
```

(keep the rest of the constructor call unchanged).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_me_capabilities.py -v`
Expected: PASS.

- [ ] **Step 5: Update the frontend `Me` type**

In `frontend/src/api/auth.ts`, add to the `Me` interface (after `role`):

```typescript
  role: "soldier" | "commander" | "duty_manager" | "admin";
  is_commander: boolean;
  is_duty_manager: boolean;
```

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/me.py backend/tests/integration/test_me_capabilities.py frontend/src/api/auth.ts
git commit -m "feat: expose is_commander/is_duty_manager capability flags on Me"
```

---

## Task 6: Fix `soldiers.py` draft-visibility check to use real capability

**Files:**
- Modify: `backend/app/routes/soldiers.py:433`
- Test: `backend/tests/integration/test_soldiers_api.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_soldiers_api.py`:

```python
def test_dual_role_commander_can_see_draft_duty_history(client, admin_session):
    """A soldier who commands a node and is separately a duty manager elsewhere must
    still be able to see draft assignments (include_drafts=true) — role label alone
    must not gate this, only real duty-manager capability."""
    from app.db.models import DutyManagerScope
    from tests.helpers import create_node, create_soldier, auth_headers

    a = create_node(admin_session, level="department", name="draft-vis-a")
    b = create_node(admin_session, level="department", name="draft-vis-b")
    dual = create_soldier(admin_session, personal_number="draft-vis-001", role="commander")
    a.commander_id = dual.id
    target = create_soldier(admin_session, personal_number="draft-vis-002", hierarchy_node_id=b.id)
    admin_session.add(DutyManagerScope(duty_manager_id=dual.id, hierarchy_node_id=b.id))
    admin_session.commit()
    admin_session.refresh(dual)

    r = client.get(
        f"/api/soldiers/{target.id}/duty-history",
        params={"include_drafts": "true"},
        headers=auth_headers(dual),
    )
    assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_soldiers_api.py -k dual_role_commander_can_see_draft -v`
Expected: FAIL with 403 — `dual.role` is recomputed to `"commander"` (priority label) by `recompute_role`, so `user.role not in ("duty_manager", "admin")` is `True` and the request is rejected even though `dual` genuinely holds a `DutyManagerScope` row.

- [ ] **Step 3: Fix the check**

In `backend/app/routes/soldiers.py`, change (around line 433):

```python
    if include_drafts and user.role not in ("duty_manager", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
```

to:

```python
    if include_drafts and user.role != "admin" and not is_duty_manager(session, user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
```

Add `is_duty_manager` to the `from app.auth.authz import ...` line at the top of the file (it's already being added there in Task 2 alongside `is_commander`; just confirm both names are present).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_soldiers_api.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/soldiers.py backend/tests/integration/test_soldiers_api.py
git commit -m "fix: gate draft duty-history visibility on real DM capability, not role label"
```

---

## Task 7: Fix `hakpaza.py` role checks

**Files:**
- Modify: `backend/app/routes/hakpaza.py`
- Test: `backend/tests/integration/test_hakpaza.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_hakpaza.py` (follow the file's existing helper pattern, e.g. its `_setup_dm`-style fixtures — read the top of the file for its exact existing soldier/node setup helpers and reuse them):

```python
def test_dual_role_commander_can_approve_hakpaza(client, admin_session):
    """A soldier who commands node A and is separately DM of node B (where the pulled
    soldier sits) must be able to approve hakpaza for B — real DM capability must be
    checked, not the (commander-prioritized) role label."""
    from app.db.models import DutyManagerScope, DutyAssignment, DutyType, DutyLocation, ForcedCallup
    from datetime import date
    from decimal import Decimal
    from tests.helpers import create_node, create_soldier, auth_headers

    a = create_node(admin_session, level="department", name="hak-dual-a")
    b = create_node(admin_session, level="department", name="hak-dual-b")
    dual = create_soldier(admin_session, personal_number="hak-dual-001", role="commander")
    a.commander_id = dual.id
    admin_session.add(DutyManagerScope(duty_manager_id=dual.id, hierarchy_node_id=b.id))
    pulled = create_soldier(admin_session, personal_number="hak-dual-002", hierarchy_node_id=b.id)
    replacement = create_soldier(admin_session, personal_number="hak-dual-003", hierarchy_node_id=b.id)
    dt = DutyType(name="hak-dual-dt", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="hak-dual-loc")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=pulled.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2027, 1, 1), end_date=date(2027, 1, 5), status="published", is_reserve=False,
    )
    admin_session.add(assignment)
    admin_session.commit()

    h = ForcedCallup(
        initiator_id=dual.id, pulled_soldier_id=pulled.id, original_assignment_id=assignment.id,
        pull_date=date(2027, 1, 3), replacement_soldier_id=replacement.id, callup_multiplier=Decimal("2.0"),
    )
    admin_session.add(h)
    admin_session.commit()

    r = client.post(f"/api/hakpaza/{h.id}/approve", headers=auth_headers(dual))
    assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_hakpaza.py -k dual_role_commander_can_approve -v`
Expected: FAIL with 403 — `_require_role(actor, _APPROVER_ROLES)` checks `actor.role not in {"duty_manager", "admin"}`, and `dual.role` is `"commander"` (priority label).

- [ ] **Step 3: Replace role-string gates with capability checks**

In `backend/app/routes/hakpaza.py`, change the import line:

```python
from app.auth.authz import Action, authorize, can, scope_root_ids
```

to:

```python
from app.auth.authz import Action, authorize, can, is_commander, is_duty_manager, scope_root_ids
```

Remove `_COMMANDER_ROLES`/`_APPROVER_ROLES` and replace `_require_role`:

```python
_COMMANDER_ROLES = {"commander", "duty_manager", "admin"}
_APPROVER_ROLES = {"duty_manager", "admin"}


def _require_role(actor: Soldier, roles: set[str]) -> None:
    if actor.role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
```

with:

```python
def _require_commander_or_dm(session: Session, actor: Soldier) -> None:
    if (
        actor.role != "admin"
        and not is_commander(session, actor.id)
        and not is_duty_manager(session, actor.id)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


def _require_dm(session: Session, actor: Soldier) -> None:
    if actor.role != "admin" and not is_duty_manager(session, actor.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
```

Update the six call sites:
- Lines ~109, ~126, ~153: `_require_role(actor, _COMMANDER_ROLES)` → `_require_commander_or_dm(session, actor)`
- Lines ~189, ~235: `_require_role(actor, _APPROVER_ROLES)` → `_require_dm(session, actor)`
- Line ~175: `if actor.role not in _APPROVER_ROLES:` → `if actor.role != "admin" and not is_duty_manager(session, actor.id):`

(all six call sites already have `session` in scope as a route parameter).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_hakpaza.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/hakpaza.py backend/tests/integration/test_hakpaza.py
git commit -m "fix: gate hakpaza initiate/approve on real commander/DM capability"
```

---

## Task 8: Fix `algorithm.py` explanation-redaction flag

**Files:**
- Modify: `backend/app/routes/algorithm.py:356`
- Test: `backend/tests/integration/test_algorithm_routes.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/integration/test_algorithm_routes.py`:

```python
def test_dual_role_commander_sees_unredacted_explanation(client, admin_session):
    """A soldier who commands node A and is separately DM of node B must see the
    unredacted explanation for an assignment in B — real DM capability must be
    checked, not the (commander-prioritized) role label."""
    from decimal import Decimal
    from datetime import date
    from app.db.models import (
        AssignmentExplanation, DutyAssignment, DutyLocation, DutyManagerScope, DutyType,
    )
    from tests.helpers import create_node, create_soldier, auth_headers

    a = create_node(admin_session, level="department", name="algo-dual-a")
    b = create_node(admin_session, level="department", name="algo-dual-b")
    dual = create_soldier(admin_session, personal_number="algo-dual-001", role="commander")
    a.commander_id = dual.id
    admin_session.add(DutyManagerScope(duty_manager_id=dual.id, hierarchy_node_id=b.id))
    assignee = create_soldier(admin_session, personal_number="algo-dual-002", hierarchy_node_id=b.id)
    dt = DutyType(name="algo-dual-dt", score_per_day=Decimal("1.00"))
    loc = DutyLocation(name="algo-dual-loc")
    admin_session.add(dt)
    admin_session.add(loc)
    admin_session.flush()
    assignment = DutyAssignment(
        soldier_id=assignee.id, duty_type_id=dt.id, duty_location_id=loc.id,
        start_date=date(2027, 2, 1), end_date=date(2027, 2, 5), status="published", is_reserve=False,
    )
    admin_session.add(assignment)
    admin_session.flush()
    admin_session.add(
        AssignmentExplanation(
            duty_assignment_id=assignment.id,
            payload={"candidates": []},
            algorithm_version="test",
            solver_seed="0",
        )
    )
    admin_session.commit()

    r = client.get(f"/api/algorithm/explanations/{assignment.id}", headers=auth_headers(dual))
    assert r.status_code == 200
    assert "candidates" in r.json()
    assert "blocked_count" not in r.json()  # only the soldier-redacted view adds this key
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/integration/test_algorithm_routes.py -k dual_role_commander_sees_unredacted -v`
Expected: FAIL — `is_dm = user.role in ("duty_manager", "admin")` is `False` for `dual` (role label is `"commander"`), and `dual` is not the assignee either, so the route raises 403 instead of returning the unredacted DM view.

- [ ] **Step 3: Fix the flag**

In `backend/app/routes/algorithm.py`, change (around line 356):

```python
    is_dm = user.role in ("duty_manager", "admin")
```

to:

```python
    is_dm = user.role == "admin" or is_duty_manager(session, user.id)
```

Add `is_duty_manager` to the `from app.auth.authz import ...` line at the top of `algorithm.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_algorithm_routes.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routes/algorithm.py backend/tests/integration/test_algorithm_routes.py
git commit -m "fix: gate explanation redaction on real DM capability, not role label"
```

---

## Task 9: Add `require_duty_manager_or_admin` dependency; wire into `duty_config.py`/`import_excel.py`

**Files:**
- Modify: `backend/app/auth/authz.py`
- Modify: `backend/app/routes/duty_config.py:23-28`
- Modify: `backend/app/routes/import_excel.py:160,326`
- Modify: `backend/tests/integration/test_duty_config_api.py:22`
- Modify: `backend/tests/integration/test_rbac_matrix.py:51`

- [ ] **Step 1: Write the failing tests**

Update `backend/tests/integration/test_duty_config_api.py`'s `test_duty_manager_allowed` (line ~21) to give the DM a real scope (matching the convention used everywhere else in the suite):

```python
def test_duty_manager_allowed(client: TestClient, admin_session: Session):
    from tests.helpers import create_node
    node = create_node(admin_session, level="department", name="dc-dm-node")
    dm = create_soldier(
        admin_session, personal_number="5100002", role="duty_manager", hierarchy_node_id=node.id
    )
    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(dm),
        json={"name": "ניקיון-א", "score_per_day": "1.00", "is_external": False},
    )
    assert r.status_code == 201
```

Update `backend/tests/integration/test_rbac_matrix.py`'s `test_rbac_duty_config_role_gate` (line ~51) the same way:

```python
def test_rbac_duty_config_role_gate(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number="5300001", role="admin")
    dm_node = create_node(admin_session, level="department", name="rbac-dc-node")
    dm = create_soldier(admin_session, personal_number="5300002", role="duty_manager", hierarchy_node_id=dm_node.id)
    cmd = create_soldier(admin_session, personal_number="5300003", role="commander")
    sol = create_soldier(admin_session, personal_number="5300004", role="soldier")
    ...
```

(keep the rest of the function body unchanged — only the `dm` fixture line changes).

Add a new dual-role regression test to `test_rbac_matrix.py`:

```python
def test_dual_role_commander_can_manage_duty_config(client: TestClient, admin_session: Session):
    """A soldier who commands a node and is separately DM elsewhere must still be able
    to manage duty-config (a DM-global action) — role label alone must not gate this."""
    from app.db.models import DutyManagerScope
    from tests.helpers import create_node

    a = create_node(admin_session, level="department", name="rbac-dual-a")
    b = create_node(admin_session, level="department", name="rbac-dual-b")
    dual = create_soldier(admin_session, personal_number="5300006", role="commander")
    a.commander_id = dual.id
    admin_session.add(DutyManagerScope(duty_manager_id=dual.id, hierarchy_node_id=b.id))
    admin_session.commit()

    r = client.post(
        "/api/duty-config/duty-types",
        headers=auth_headers(dual),
        json={"name": "rbac-dual-dt", "score_per_day": "1.00", "is_external": False},
    )
    assert r.status_code == 201
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/integration/test_rbac_matrix.py tests/integration/test_duty_config_api.py -v`
Expected: `test_dual_role_commander_can_manage_duty_config` FAILs with 403 (the `require_roles("duty_manager", "admin")` dependency checks the role string, which is `"commander"` for `dual`); the two updated fixture tests should still pass at this point since they're unaffected by today's behavior — they're updated pre-emptively so they keep passing after Step 3's fix.

- [ ] **Step 3: Add the dependency**

In `backend/app/auth/authz.py`, add (after `authorize()`):

```python
def require_duty_manager_or_admin(
    session: Session = Depends(get_session),
    user: Soldier = Depends(get_current_user),
) -> Soldier:
    """FastAPI dependency: admin, or a soldier holding at least one DutyManagerScope row."""
    if user.role != "admin" and not is_duty_manager(session, user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    return user
```

Add the necessary imports at the top of `authz.py`:

```python
from app.auth.deps import get_current_user
from app.db.session import get_session
```

(`Depends` must also be imported from `fastapi` — add it to the existing `from fastapi import HTTPException, status` line, making it `from fastapi import Depends, HTTPException, status`.)

- [ ] **Step 4: Wire it into `duty_config.py`**

In `backend/app/routes/duty_config.py`, change:

```python
from app.auth.deps import require_password_changed, require_roles
...

def require_config_manager(
    user: Soldier = Depends(require_roles("duty_manager", "admin")),
) -> Soldier:
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="must_change_password")
    return user
```

to:

```python
from app.auth.authz import require_duty_manager_or_admin
from app.auth.deps import require_password_changed
...

def require_config_manager(
    user: Soldier = Depends(require_duty_manager_or_admin),
) -> Soldier:
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="must_change_password")
    return user
```

- [ ] **Step 5: Wire it into `import_excel.py`**

In `backend/app/routes/import_excel.py`, change the import line:

```python
from app.auth.deps import require_password_changed, require_roles
```

to:

```python
from app.auth.authz import require_duty_manager_or_admin
from app.auth.deps import require_password_changed
```

Then change both call sites (lines ~160 and ~326):

```python
    actor: Soldier = Depends(require_roles("admin", "duty_manager")),
```

to:

```python
    actor: Soldier = Depends(require_duty_manager_or_admin),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest tests/integration/test_rbac_matrix.py tests/integration/test_duty_config_api.py tests/integration/test_import_excel.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/auth/authz.py backend/app/routes/duty_config.py backend/app/routes/import_excel.py backend/tests/integration/test_duty_config_api.py backend/tests/integration/test_rbac_matrix.py
git commit -m "fix: gate duty-config/import-excel management on real DM capability, not role string"
```

---

## Task 10: Frontend — `UnifiedNav.tsx`

**Files:**
- Modify: `frontend/src/components/UnifiedNav.tsx:47-49`
- Test: `frontend/src/components/UnifiedNav.test.tsx`

- [ ] **Step 1: Write the failing test**

In `frontend/src/components/UnifiedNav.test.tsx`, update the three existing `mockUseAuth.mockReturnValue` calls to include the new capability flags, and add a dual-role describe block.

Change line 80:

```typescript
mockUseAuth.mockReturnValue({ user: { role: "commander" } });
```

to:

```typescript
mockUseAuth.mockReturnValue({ user: { role: "commander", is_commander: true, is_duty_manager: false } });
```

Change line 113 and line 144 (both `role: "duty_manager"`):

```typescript
mockUseAuth.mockReturnValue({ user: { role: "duty_manager" } });
```

to:

```typescript
mockUseAuth.mockReturnValue({ user: { role: "duty_manager", is_commander: false, is_duty_manager: true } });
```

Change the soldier-role fixture at line 54 too, for explicitness:

```typescript
mockUseAuth.mockReturnValue({ user: { role: "soldier" } });
```

to:

```typescript
mockUseAuth.mockReturnValue({ user: { role: "soldier", is_commander: false, is_duty_manager: false } });
```

Add a new describe block at the end of the file (before the closing of the file):

```typescript
describe("UnifiedNav — dual-role soldier (commander label, also a duty manager)", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({
      user: { role: "commander", is_commander: true, is_duty_manager: true },
    });
  });

  test("renders both commander and planning tabs", () => {
    render(<UnifiedNav />);
    expect(screen.getAllByTestId("nav-commander").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("nav-planning").length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- UnifiedNav`
Expected: The new dual-role test FAILs (`nav-planning` not found) — `canPlan` currently checks `role === "duty_manager"`, which is `false` for `role: "commander"` even though `is_duty_manager: true`.

- [ ] **Step 3: Fix the component**

In `frontend/src/components/UnifiedNav.tsx`, change (lines ~47-49):

```typescript
  const role = user?.role;
  const canApprove = role === "commander" || role === "duty_manager" || role === "admin";
  const canPlan = role === "duty_manager" || role === "admin";
```

to:

```typescript
  const canApprove = user?.role === "admin" || user?.is_commander || user?.is_duty_manager;
  const canPlan = user?.role === "admin" || user?.is_duty_manager;
```

(`role` is no longer needed as a separate variable here — remove it if nothing else in the file uses it; check with `grep -n "\\brole\\b" frontend/src/components/UnifiedNav.tsx`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- UnifiedNav`
Expected: PASS, all describe blocks including the new dual-role one.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/UnifiedNav.tsx frontend/src/components/UnifiedNav.test.tsx
git commit -m "fix: gate UnifiedNav approve/plan tabs on capability flags, not role string"
```

---

## Task 11: Frontend — `ProfilePage.tsx`

**Files:**
- Modify: `frontend/src/pages/ProfilePage.tsx:62,413`

- [ ] **Step 1: Update the gates**

In `frontend/src/pages/ProfilePage.tsx`, change (line ~62):

```typescript
    if (user?.role === "commander" || user?.role === "duty_manager" || user?.role === "admin") {
```

to:

```typescript
    if (user?.role === "admin" || user?.is_commander || user?.is_duty_manager) {
```

Change (line ~413):

```typescript
      {(user?.role === "commander" || user?.role === "duty_manager" || user?.role === "admin") && (
```

to:

```typescript
      {(user?.role === "admin" || user?.is_commander || user?.is_duty_manager) && (
```

- [ ] **Step 2: Run the frontend suite and lint**

Run: `cd frontend && npm test && npm run lint`
Expected: PASS (no test file exercises this specific gate today, so this is a behavior-preserving rewrite — verify by manual review that `user?.role === "admin"` plus the two booleans is equivalent to the old three-way role-string check for every non-dual-role soldier).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/ProfilePage.tsx
git commit -m "fix: gate ProfilePage commander-scopes section on capability flags"
```

---

## Task 12: Frontend — `UnifiedSoldierModal.tsx`

**Files:**
- Modify: `frontend/src/components/UnifiedSoldierModal.tsx:48-50`

- [ ] **Step 1: Update the gates**

In `frontend/src/components/UnifiedSoldierModal.tsx`, change (lines ~48-50):

```typescript
  const isAdmin = user?.role === "admin";
  const isDutyManager = user?.role === "duty_manager";
  const isCommander = user?.role === "commander";
```

to:

```typescript
  const isAdmin = user?.role === "admin";
  const isDutyManager = user?.is_duty_manager ?? false;
  const isCommander = user?.is_commander ?? false;
```

(`canManage`, `canViewAll`, and the other `isCommander`/`isDutyManager` usages further down the file — e.g. the profile-save guard and the email-field gate — are unaffected since they reference these same const names, now correctly capability-driven.)

- [ ] **Step 2: Run the frontend suite and lint**

Run: `cd frontend && npm test && npm run lint`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/UnifiedSoldierModal.tsx
git commit -m "fix: gate UnifiedSoldierModal tabs/actions on capability flags"
```

---

## Task 13: Frontend — `HomePage.tsx`

**Files:**
- Modify: `frontend/src/pages/HomePage.tsx:71`

- [ ] **Step 1: Update the gate**

In `frontend/src/pages/HomePage.tsx`, change (line ~71):

```typescript
  const canApprove = user?.role === "commander" || user?.role === "duty_manager" || user?.role === "admin";
```

to:

```typescript
  const canApprove = user?.role === "admin" || user?.is_commander || user?.is_duty_manager;
```

- [ ] **Step 2: Run the frontend suite and lint**

Run: `cd frontend && npm test && npm run lint`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/HomePage.tsx
git commit -m "fix: gate HomePage approval widgets on capability flags"
```

---

## Task 14: Frontend — `ShiftDetailPanel.tsx`

**Files:**
- Modify: `frontend/src/components/ShiftDetailPanel.tsx:384`

- [ ] **Step 1: Update the gate**

In `frontend/src/components/ShiftDetailPanel.tsx`, change (line ~384):

```typescript
              (user?.role === "duty_manager" || user?.role === "admin")
```

to:

```typescript
              (user?.role === "admin" || user?.is_duty_manager)
```

- [ ] **Step 2: Run the frontend suite and lint**

Run: `cd frontend && npm test && npm run lint`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ShiftDetailPanel.tsx
git commit -m "fix: gate gimelim dismissal modal on real DM capability"
```

---

## Task 15: Frontend — `TeamHierarchyPage.tsx`

**Files:**
- Modify: `frontend/src/pages/TeamHierarchyPage.tsx:26`

- [ ] **Step 1: Update the gate**

In `frontend/src/pages/TeamHierarchyPage.tsx`, change (line ~26):

```typescript
  const canManageLevelTypes = user?.role === "admin" || user?.role === "duty_manager";
```

to:

```typescript
  const canManageLevelTypes = user?.role === "admin" || (user?.is_duty_manager ?? false);
```

- [ ] **Step 2: Run the frontend suite and lint**

Run: `cd frontend && npm test && npm run lint`
Expected: PASS.

- [ ] **Step 3: Run the full backend and frontend suites one final time**

Run: `cd backend && pytest -q`
Run: `cd frontend && npm test && npm run lint`
Expected: PASS on both — this closes out the RBAC capability model fix. The hierarchy-page duty-manager-assignment feature (sub-project #2) can now be brainstormed and built on top of `is_commander`/`is_duty_manager`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/TeamHierarchyPage.tsx
git commit -m "fix: gate level-type management on real DM capability"
```
