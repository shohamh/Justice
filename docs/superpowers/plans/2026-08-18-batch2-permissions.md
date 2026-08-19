# Batch 2 — Permissions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four permission bugs from the user-reported-issues triage (spec:
`docs/superpowers/specs/2026-08-18-user-reported-issues-triage-design.md`,
Batch 2 / items 1, 2, 4, 7): commander soldier-delete, enrollment approval
blocked by an unrelated rank-edit gate, commander exemption grants that skip
DM approval, and hierarchy-transfer visibility limited to the direct
commander instead of every ancestor.

**Architecture:** Each task is a self-contained backend authorization fix
(plus, where the bug is UI-only, a frontend fix) verified by new
integration/unit tests. No new tables except one `system_settings` key per
task where the spec calls for a configurable minimum level — reuses the
existing `get_setting`/`SettingNotFound`-fallback pattern already used by
`exemptions.commander_exemption_min_level`. No schema migrations are needed:
`system_settings` rows are created on first `PUT` from the admin UI (there is
no seed-row requirement — `get_setting` raises `SettingNotFound` and callers
fall back to a hardcoded default until a row exists).

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + TypeScript + Vitest
(frontend), pytest (backend tests, markers: `auth`, `soldiers`, `hierarchy`).

## Global Constraints

- All permission changes must flow through `app.auth.authz` (either the
  generic `authorize()`/`can()` path, or a bespoke session-aware helper in
  `app.services.authority` for the cases that need a `system_settings`
  lookup, mirroring the existing `commander_can_grant_commander_exemption`
  pattern) — never a route-local ad hoc check.
- Frontend UI gating must mirror the backend capability exactly: a control is
  hidden/disabled only when the backend would actually reject the action, and
  the backend is the source of truth (client-side flags come from `/me`,
  never from guessing a role).
- `HierarchyLevelType.key` values are admin-defined (see
  `Action.HIERARCHY_LEVEL_TYPE_MANAGE`); in production they are commonly
  Hebrew strings ("מדור", "מרכז", ...). Hardcoded fallback level-key
  constants in `app/services/authority.py` use the Hebrew convention already
  established by `COMMANDER_EXEMPTION_MIN_LEVEL_KEY = "מדור"`. Follow it for
  any new constant.
- Backend tests: `pytest -m auth -q` and `pytest -m soldiers -q` and
  `pytest -m hierarchy -q` (see markers in `backend/pyproject.toml` /
  `AGENTS.md`) must stay green; run `pytest -q` (full fast suite) before the
  final commit of this plan.
- Frontend: `npm test`, `npm run lint` (zero warnings), `npm run typecheck`
  must stay green.
- Every step that changes an HTTP-facing behavior needs an integration test
  under `backend/tests/integration/`; every step that changes a pure
  authorization helper needs a unit test under `backend/app/services/tests/`.

---

## Task 1: Commander soldier-delete gate (item 1)

**Files:**
- Modify: `backend/app/services/authority.py` — add
  `_commander_delete_min_level()` and `commander_delete_soldier_authorized()`.
- Modify: `backend/app/auth/authz.py` — `authorize()` gains a bespoke
  fallback branch for `Action.SOLDIER_DELETE`.
- Modify: `backend/app/routes/soldiers.py` — delete endpoint: on `403`, keep
  raising via `authorize()` (no route change needed beyond the authz change
  already covering it); confirm error detail stays generic `"forbidden"`
  (frontend supplies the friendly copy).
- Modify: `backend/app/routes/me.py` — `MeResponse` gains
  `can_delete_soldier: bool`; computed via a new
  `has_any_commander_delete_scope()` helper in `authority.py`.
- Modify: `frontend/src/api/auth.ts` — `Me` interface gains
  `can_delete_soldier?: boolean`.
- Modify: `frontend/src/pages/TeamHierarchyPage.tsx` — gate the remove button
  (line 185) on `user?.can_delete_soldier`; `onRemove` gets try/catch with a
  friendly error message on 403.
- Test: `backend/app/services/tests/test_authority.py` (unit, level-gating
  logic).
- Test: `backend/tests/integration/test_soldiers_api.py` (integration,
  HTTP-level scope + 403 behavior).
- Test: `frontend/src/pages/TeamHierarchyPage.test.tsx` (button visibility +
  error handling) — create this file if it does not already exist; check
  first with `Glob` before assuming.

**Interfaces:**
- Produces: `app.services.authority.commander_delete_soldier_authorized(session, *, user: Soldier, target_node: HierarchyNode | None) -> bool`
- Produces: `app.services.authority.has_any_commander_delete_scope(session, *, user: Soldier) -> bool`
- Consumes (existing): `app.services.authority.dm_scope_covers_target(session, *, scope_root_ids: set[uuid.UUID], target_node: HierarchyNode | None, required_level_key: str) -> bool`
- Consumes (existing): `app.services.hierarchy.get_level_rank(session, level_key: str) -> int | None`
- Consumes (existing): `app.services.settings_loader.get_setting(session, key) -> Any`, `SettingNotFound`

- [ ] **Step 1: Write the failing unit test for the level-gated helper**

Add to `backend/app/services/tests/test_authority.py` (follow the existing
`_level`/`_clear_seeded_level_types` fixture pattern already in that file):

```python
from app.services.authority import commander_delete_soldier_authorized, has_any_commander_delete_scope


def test_commander_at_mador_or_above_can_delete_in_subtree(app_session):
    _level(app_session, "גדוד", 1)
    _level(app_session, "מדור", 2)
    _level(app_session, "כיתה", 3)
    cmd = _soldier(app_session, "9500001", role="commander")
    root = _node(app_session, "מדור", commander_id=cmd.id)
    target = _child(app_session, root, "כיתה")
    assert commander_delete_soldier_authorized(app_session, user=cmd, target_node=target) is True


def test_commander_below_mador_cannot_delete(app_session):
    _level(app_session, "מדור", 1)
    _level(app_session, "כיתה", 2)
    cmd = _soldier(app_session, "9500002", role="commander")
    root = _node(app_session, "כיתה", commander_id=cmd.id)
    target = _child(app_session, root, "כיתה")
    assert commander_delete_soldier_authorized(app_session, user=cmd, target_node=target) is False


def test_commander_out_of_scope_cannot_delete(app_session):
    _level(app_session, "מדור", 1)
    cmd = _soldier(app_session, "9500003", role="commander")
    _node(app_session, "מדור", commander_id=cmd.id)
    other_root = _node(app_session, "מדור", name="Other")
    assert commander_delete_soldier_authorized(app_session, user=cmd, target_node=other_root) is False


def test_commander_delete_min_level_configurable(app_session):
    from app.services.settings_loader import set_setting

    _level(app_session, "מדור", 1)
    _level(app_session, "כיתה", 2)
    cmd = _soldier(app_session, "9500004", role="commander")
    root = _node(app_session, "כיתה", commander_id=cmd.id)

    assert commander_delete_soldier_authorized(app_session, user=cmd, target_node=root) is False

    set_setting(app_session, "soldiers.commander_delete_min_level", "כיתה", actor_id=None)
    app_session.flush()
    assert commander_delete_soldier_authorized(app_session, user=cmd, target_node=root) is True


def test_has_any_commander_delete_scope_true_for_qualifying_commander(app_session):
    _level(app_session, "מדור", 1)
    cmd = _soldier(app_session, "9500005", role="commander")
    _node(app_session, "מדור", commander_id=cmd.id)
    assert has_any_commander_delete_scope(app_session, user=cmd) is True


def test_has_any_commander_delete_scope_false_for_junior_commander(app_session):
    _level(app_session, "מדור", 1)
    _level(app_session, "כיתה", 2)
    cmd = _soldier(app_session, "9500006", role="commander")
    _node(app_session, "כיתה", commander_id=cmd.id)
    assert has_any_commander_delete_scope(app_session, user=cmd) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/pytest app/services/tests/test_authority.py -k commander_delete -v`
Expected: FAIL — `ImportError: cannot import name 'commander_delete_soldier_authorized'`

- [ ] **Step 3: Implement the authority helpers**

In `backend/app/services/authority.py`, add near
`_commander_exemption_min_level` (after `commander_can_grant_commander_exemption`,
around line 199):

```python
COMMANDER_DELETE_MIN_LEVEL_KEY = "מדור"  # fallback default if no setting is configured


def _commander_delete_min_level(session: Session) -> str:
    try:
        value = get_setting(session, "soldiers.commander_delete_min_level")
        if value:
            return str(value)
    except SettingNotFound:
        pass
    return COMMANDER_DELETE_MIN_LEVEL_KEY


def commander_delete_soldier_authorized(
    session: Session, *, user: Soldier, target_node: HierarchyNode | None,
) -> bool:
    """True iff `user` commands a node at `soldiers.commander_delete_min_level`
    (default מדור) or above (closer to root) whose subtree contains
    `target_node`."""
    commander_root_ids = set(
        session.execute(
            select(HierarchyNode.id).where(HierarchyNode.commander_id == user.id)
        ).scalars().all()
    )
    required_level = _commander_delete_min_level(session)
    return dm_scope_covers_target(
        session, scope_root_ids=commander_root_ids, target_node=target_node,
        required_level_key=required_level,
    )


def has_any_commander_delete_scope(session: Session, *, user: Soldier) -> bool:
    """Cheap `/me`-level flag: True iff `user` commands ANY node at the
    configured minimum level or above — independent of any specific target
    soldier. Used only to decide whether to render the delete affordance at
    all; the actual delete call is still authorized per-target via
    `commander_delete_soldier_authorized`."""
    required_rank = get_level_rank(session, _commander_delete_min_level(session))
    if required_rank is None:
        return False
    commanded_nodes = session.execute(
        select(HierarchyNode).where(HierarchyNode.commander_id == user.id)
    ).scalars().all()
    for node in commanded_nodes:
        node_rank = get_level_rank(session, node.level)
        if node_rank is not None and node_rank <= required_rank:
            return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/pytest app/services/tests/test_authority.py -k commander_delete -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/authority.py backend/app/services/tests/test_authority.py
git commit -m "feat: add commander soldier-delete level-gate helpers"
```

- [ ] **Step 6: Write the failing integration test for the HTTP gate**

Add to `backend/tests/integration/test_soldiers_api.py` (check the file's
existing imports first — it already imports `auth_headers`, `create_node`,
`create_soldier` from `tests.helpers`; reuse them):

```python
def test_commander_at_mador_or_above_can_delete_in_scope(client: TestClient, admin_session: Session):
    from app.services.settings_loader import set_setting
    # tests/conftest.py seeds English level keys (see _LEVEL_TYPE_DEFAULTS);
    # "group" is rank 6, labeled "מדור" — use its key directly since
    # commander_delete_soldier_authorized compares against the level KEY.
    set_setting(admin_session, "soldiers.commander_delete_min_level", "group", actor_id=None)
    admin_session.commit()
    cmd = create_soldier(admin_session, personal_number="9600001", role="commander")
    root = create_node(admin_session, level="group", name="del_root", commander_id=cmd.id)
    target = create_soldier(admin_session, personal_number="9600002", hierarchy_node_id=root.id)
    admin_session.commit()

    resp = client.delete(f"/api/soldiers/{target.id}", headers=auth_headers(cmd))
    assert resp.status_code == 204, resp.text


def test_commander_below_min_level_cannot_delete(client: TestClient, admin_session: Session):
    cmd = create_soldier(admin_session, personal_number="9600003", role="commander")
    root = create_node(admin_session, level="team", name="del_root2", commander_id=cmd.id)
    target = create_soldier(admin_session, personal_number="9600004", hierarchy_node_id=root.id)
    admin_session.commit()

    resp = client.delete(f"/api/soldiers/{target.id}", headers=auth_headers(cmd))
    assert resp.status_code == 403


def test_commander_out_of_scope_cannot_delete_via_api(client: TestClient, admin_session: Session):
    from app.services.settings_loader import set_setting
    set_setting(admin_session, "soldiers.commander_delete_min_level", "group", actor_id=None)
    admin_session.commit()
    cmd = create_soldier(admin_session, personal_number="9600005", role="commander")
    create_node(admin_session, level="group", name="del_own", commander_id=cmd.id)
    other_root = create_node(admin_session, level="group", name="del_other")
    target = create_soldier(admin_session, personal_number="9600006", hierarchy_node_id=other_root.id)
    admin_session.commit()

    resp = client.delete(f"/api/soldiers/{target.id}", headers=auth_headers(cmd))
    assert resp.status_code == 403


def test_me_exposes_can_delete_soldier_flag(client: TestClient, admin_session: Session):
    from app.services.settings_loader import set_setting
    set_setting(admin_session, "soldiers.commander_delete_min_level", "group", actor_id=None)
    admin_session.commit()
    qualifying = create_soldier(admin_session, personal_number="9600007", role="commander")
    create_node(admin_session, level="group", name="me_flag_root", commander_id=qualifying.id)
    junior = create_soldier(admin_session, personal_number="9600008", role="commander")
    create_node(admin_session, level="team", name="me_flag_root2", commander_id=junior.id)
    admin_session.commit()

    r1 = client.get("/api/me", headers=auth_headers(qualifying))
    assert r1.json()["can_delete_soldier"] is True
    r2 = client.get("/api/me", headers=auth_headers(junior))
    assert r2.json()["can_delete_soldier"] is False
```

- [ ] **Step 7: Run integration tests to verify they fail**

Run: `cd backend && .venv/Scripts/pytest tests/integration/test_soldiers_api.py -k "delete_soldier or can_delete" -v`
Expected: FAIL — `test_commander_at_mador_or_above_can_delete_in_scope` gets
403 (commander branch not wired), `test_me_exposes_can_delete_soldier_flag`
gets `KeyError`/`None` on `can_delete_soldier`.

- [ ] **Step 8: Wire the authz fallback and `/me` flag**

In `backend/app/auth/authz.py`, modify `authorize()`:

```python
def authorize(
    session: Session, user: Soldier, action: str, *, target_node: HierarchyNode | None
) -> None:
    """Raise 403 unless `user` may perform `action` against `target_node`'s subtree."""
    roots = scope_root_ids(session, user)
    allowed = can(
        user,
        action,
        target_node=target_node,
        roots=roots,
        is_commander=is_commander(session, user.id),
        is_duty_manager=is_duty_manager(session, user.id),
    )
    if not allowed and action == Action.SOLDIER_DELETE and is_commander(session, user.id):
        # SOLDIER_DELETE for commanders needs a system_settings lookup
        # (minimum commanded level) that can()'s session-free signature can't
        # perform, so it's authorized here via a bespoke helper instead of
        # through _COMMANDER_ACTIONS — same pattern as
        # commander_can_grant_commander_exemption.
        from app.services.authority import commander_delete_soldier_authorized
        allowed = commander_delete_soldier_authorized(session, user=user, target_node=target_node)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
```

In `backend/app/routes/me.py`:
- Add `can_delete_soldier: bool = False` to `MeResponse`.
- Import `has_any_commander_delete_scope` from `app.services.authority`.
- In `me()`, compute:
  ```python
  can_delete_soldier = (
      user.role == "admin" or has_any_commander_delete_scope(session, user=user)
  )
  ```
  (a duty manager with `SOLDIER_DELETE` already in `_DM_ACTIONS` also
  qualifies — add `or is_duty_manager(session, user.id)` since DMs are not
  level-gated by this feature and already had the permission before this
  batch)
- Pass `can_delete_soldier=can_delete_soldier` into the returned `MeResponse(...)`.

- [ ] **Step 9: Run integration tests to verify they pass**

Run: `cd backend && .venv/Scripts/pytest tests/integration/test_soldiers_api.py -k "delete_soldier or can_delete" -v`
Expected: PASS (4 tests)

- [ ] **Step 10: Run the full auth + soldiers marker suites for regressions**

Run: `cd backend && .venv/Scripts/pytest -m "auth or soldiers" -q`
Expected: PASS, 0 failures

- [ ] **Step 11: Commit backend**

```bash
git add backend/app/auth/authz.py backend/app/routes/me.py backend/tests/integration/test_soldiers_api.py
git commit -m "feat: gate commander soldier-delete by commanded level, expose can_delete_soldier on /me"
```

- [ ] **Step 12: Add the setting to the admin UI**

In `frontend/src/pages/SystemSettingsPage.tsx`, add a new entry under the
existing "פטורים" (exemptions) section pattern — put it in a section for
soldiers/team management (create a `"חיילים"` section if none exists near the
top of the settings array; check the file first for an existing fitting
section before adding a new one):

```typescript
{
  key: "soldiers.commander_delete_min_level",
  label: "החל מאיזו רמת פיקוד ניתן למחוק חייל",
  description: "מפקד ברמה זו ומעלה (קרוב יותר לשורש) יכול למחוק (רישום היסטורי) חיילים בתת-העץ שלו",
  type: "select" as const,
  defaultValue: "מדור",
  options: [],
},
```

Add `"soldiers.commander_delete_min_level"` to the `MIN_LEVEL_SETTING_KEYS`
set (around line 406) so it renders with the real hierarchy-level dropdown
(`commanderExemptionLevelOptions`).

- [ ] **Step 13: Manual check — settings page renders the new field**

Run: `cd frontend && npm run typecheck`
Expected: no new errors.

- [ ] **Step 14: Commit settings UI**

```bash
git add frontend/src/pages/SystemSettingsPage.tsx
git commit -m "feat: add commander soldier-delete minimum-level setting to admin UI"
```

- [ ] **Step 15: Write the failing frontend test for button gating**

Read `frontend/src/pages/TeamHierarchyPage.tsx` in full first (already read
above — remove button is the `data-testid={\`remove-${s.personal_number}\`}`
button at line ~185, unconditionally rendered). Check whether
`frontend/src/pages/TeamHierarchyPage.test.tsx` already exists; if it does,
add these cases to it following its existing mocking conventions for
`useAuth`/`listSoldiers`/`fetchTree`. If it does not exist, create it
mirroring the mocking style of a similar existing page test (check
`frontend/src/pages/ApprovalsPage.test.tsx` for the pattern of mocking
`../auth/AuthContext` and API modules with `vi.mock`).

```typescript
it("hides the remove button when can_delete_soldier is false", async () => {
  mockUseAuth.mockReturnValue({ user: { id: "u1", role: "commander", is_commander: true, can_delete_soldier: false } });
  // ...render with a soldiers list fixture...
  expect(screen.queryByTestId(/^remove-/)).not.toBeInTheDocument();
});

it("shows the remove button when can_delete_soldier is true", async () => {
  mockUseAuth.mockReturnValue({ user: { id: "u1", role: "commander", is_commander: true, can_delete_soldier: true } });
  // ...render with a soldiers list fixture...
  expect(screen.getByTestId(/^remove-/)).toBeInTheDocument();
});

it("shows a friendly error and does not refresh when delete is forbidden", async () => {
  mockSoftDeleteSoldier.mockRejectedValueOnce({ response: { status: 403, data: { detail: "forbidden" } } });
  mockUseAuth.mockReturnValue({ user: { id: "u1", role: "commander", is_commander: true, can_delete_soldier: true } });
  // ...render, click remove, confirm window.confirm...
  expect(await screen.findByText(/אין לך הרשאה/)).toBeInTheDocument();
});
```

- [ ] **Step 16: Run frontend tests to verify they fail**

Run: `cd frontend && npm test -- TeamHierarchyPage`
Expected: FAIL (button always rendered; no error message shown on 403)

- [ ] **Step 17: Implement the frontend gate**

In `frontend/src/api/auth.ts`, add `can_delete_soldier?: boolean;` to the
`Me` interface (near `can_view_transparency`).

In `frontend/src/pages/TeamHierarchyPage.tsx`:
- Add `const canDeleteSoldier = user?.can_delete_soldier ?? false;` near
  `isAdmin`/`canManageLevelTypes` (line ~28).
- Add local error state: `const [removeError, setRemoveError] = useState<string | null>(null);`
- Rewrite `onRemove`:

```typescript
async function onRemove(id: string) {
  const commandedNode = nodes.find((n) => n.commander_id === id);
  if (commandedNode) {
    alert(`${t("team.cannot_delete_commander")} "${commandedNode.name}". ${t("team.reassign_commander_first")}`);
    return;
  }
  if (!confirm(t("team.remove") + "?")) return;
  setRemoveError(null);
  try {
    await softDeleteSoldier(id, new Date().toISOString().slice(0, 10));
    await refresh();
  } catch (err) {
    setRemoveError(translateApiError(err, t, "אין לך הרשאה למחוק חייל זה"));
  }
}
```

Import `translateApiError` from `../utils/translateApiError` and
`useTranslation`'s `t` is already destructured. Render `removeError` near the
top of the section (mirror how `tempPw` is surfaced elsewhere on the page).

Gate the button: `{canDeleteSoldier && (<button ... data-testid={...}>{t("team.remove")}</button>)}`.

- [ ] **Step 18: Run frontend tests to verify they pass**

Run: `cd frontend && npm test -- TeamHierarchyPage`
Expected: PASS

- [ ] **Step 19: Lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: 0 warnings, 0 errors

- [ ] **Step 20: Commit frontend**

```bash
git add frontend/src/api/auth.ts frontend/src/pages/TeamHierarchyPage.tsx frontend/src/pages/TeamHierarchyPage.test.tsx
git commit -m "fix: gate soldier-delete button on can_delete_soldier, surface friendly 403 error"
```

---

## Task 2: Enrollment approval unblocked from rank-edit gate (item 2)

**Files:**
- Modify: `backend/app/routes/enrollment.py` — `EnrollmentRequestOut` gains
  `can_edit_rank_advancement: bool`; `_soldier_to_out` and `_load_reqs` take
  a `user: Soldier` param to compute it; `list_pending` and `patch_enrollment`
  pass `user` through.
- Modify: `frontend/src/api/enrollment.ts` — `EnrollmentRequestDTO` gains
  `can_edit_rank_advancement: boolean`.
- Modify: `frontend/src/components/EnrollmentApprovalModal.tsx` —
  `handleSaveAndApprove` sends rank fields only when
  `req.can_edit_rank_advancement` is true; always calls `approveEnrollment`.
- Test: `backend/tests/integration/test_enrollment_routes.py`.
- Test: `frontend/src/components/EnrollmentApprovalModal.test.tsx` — check
  first whether it exists; if so extend it, else create it mirroring an
  existing modal test's mock/render conventions.

**Interfaces:**
- Consumes (existing): `app.services.authority.rank_advancement_edit_authorized(session, *, user: Soldier, target_node: HierarchyNode | None) -> bool`
- Produces: `_soldier_to_out(r, s, node_name, exemptions, nearest_commander, nearest_duty_manager, *, user: Soldier)` (signature change — `user` becomes required keyword-only)
- Produces: `_load_reqs(session, reqs, *, user: Soldier)` (signature change)

- [ ] **Step 1: Write the failing integration test**

Add to `backend/tests/integration/test_enrollment_routes.py` (inspect its
existing imports/fixtures first — it will already have helpers to create a
pending enrollment request; reuse them, following the same pattern as
neighboring tests in that file for creating a commander at a below-מדור
level and a `SoldierEnrollmentRequest`):

```python
def test_below_mador_commander_can_approve_without_editing_rank(client: TestClient, admin_session: Session):
    from app.db.models import SoldierEnrollmentRequest
    node = create_node(admin_session, level="team", name="enroll_low")
    cmd = create_soldier(admin_session, personal_number="9700001", role="commander")
    node.commander_id = cmd.id
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number="9700002")
    req = SoldierEnrollmentRequest(soldier_id=soldier.id, requested_node_id=node.id, status="pending")
    admin_session.add(req)
    admin_session.commit()

    list_resp = client.get("/api/enrollment-requests/pending", headers=auth_headers(cmd))
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["can_edit_rank_advancement"] is False

    approve_resp = client.post(
        f"/api/enrollment-requests/{req.id}/approve", headers=auth_headers(cmd), json={},
    )
    assert approve_resp.status_code == 200, approve_resp.text


def test_mador_plus_commander_sees_rank_edit_flag_true(client: TestClient, admin_session: Session):
    from app.db.models import SoldierEnrollmentRequest
    node = create_node(admin_session, level="group", name="enroll_high")
    cmd = create_soldier(admin_session, personal_number="9700003", role="commander")
    node.commander_id = cmd.id
    admin_session.commit()
    soldier = create_soldier(admin_session, personal_number="9700004")
    req = SoldierEnrollmentRequest(soldier_id=soldier.id, requested_node_id=node.id, status="pending")
    admin_session.add(req)
    admin_session.commit()

    list_resp = client.get("/api/enrollment-requests/pending", headers=auth_headers(cmd))
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["can_edit_rank_advancement"] is True
```

(`"group"` is rank 6 in `_LEVEL_TYPE_DEFAULTS` and
`rank_advancement_edit_authorized` requires `"מדור"` by hardcoded key — since
that constant is the Hebrew label, not the test fixture's English key, check
whether existing rank-advancement tests already work around this; if
`rank_advancement_edit_authorized` truly compares against the literal string
`"מדור"`, mirror whatever existing enrollment/rank-advancement integration
test in this same file already gets a `True` result — copy its exact level
key setup instead of guessing. If no such existing integration test exists,
use the `app_session` unit-test pattern from `test_authority.py` instead,
defining `_level(session, "מדור", ...)` custom level types directly, the same
way `test_rank_advancement_authority_requires_senior_in_scope_root` does.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/pytest tests/integration/test_enrollment_routes.py -k can_edit_rank -v`
Expected: FAIL — `KeyError: 'can_edit_rank_advancement'`

- [ ] **Step 3: Thread `user` through and add the field**

In `backend/app/routes/enrollment.py`:

Add to `EnrollmentRequestOut` (after `is_career`, ~line 72):
```python
    can_edit_rank_advancement: bool = False
```

Change `_soldier_to_out` signature to accept `*, user: Soldier` and set:
```python
        can_edit_rank_advancement=rank_advancement_edit_authorized(
            session, user=user, target_node=session.get(HierarchyNode, r.requested_node_id),
        ),
```
This requires passing `session` into `_soldier_to_out` too — add
`session: Session` as its first parameter (it currently has none; check
every call site and update them all in the same step).

Change `_load_reqs(session, reqs)` to `_load_reqs(session, reqs, *, user: Soldier)`
and thread `user` into its `_soldier_to_out(...)` call.

Update call sites:
- `list_pending`: `return _load_reqs(session, list(reqs), user=user)`
- `patch_enrollment`'s final `return _soldier_to_out(...)`: add `user=user`
- Any other `_soldier_to_out(...)` call in the file (search for all
  occurrences with `Grep` before editing — there may be one in a "get single
  request" endpoint not shown above; update every one).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/pytest tests/integration/test_enrollment_routes.py -k can_edit_rank -v`
Expected: PASS

- [ ] **Step 5: Run the full enrollment test file for regressions**

Run: `cd backend && .venv/Scripts/pytest tests/integration/test_enrollment_routes.py -v`
Expected: PASS, 0 failures (catches any missed `_soldier_to_out` call site)

- [ ] **Step 6: Commit backend**

```bash
git add backend/app/routes/enrollment.py backend/tests/integration/test_enrollment_routes.py
git commit -m "feat: expose can_edit_rank_advancement on enrollment request payloads"
```

- [ ] **Step 7: Write the failing frontend test**

In `frontend/src/components/EnrollmentApprovalModal.test.tsx` (create if
missing, mirroring an existing modal test's `vi.mock` setup for
`../api/enrollment`):

```typescript
it("does not send rank fields when can_edit_rank_advancement is false, but still approves", async () => {
  const req = { ...baseReq, can_edit_rank_advancement: false };
  render(<EnrollmentApprovalModal req={req} nodes={[]} exemptionTypes={[]} onClose={vi.fn()} onDone={vi.fn()} />);
  fireEvent.click(screen.getByText("שמור ואשר"));
  await waitFor(() => {
    expect(mockPatchEnrollment).toHaveBeenCalledWith(req.id, expect.not.objectContaining({ rank: expect.anything() }));
    expect(mockApproveEnrollment).toHaveBeenCalledWith(req.id);
  });
});

it("sends rank fields when can_edit_rank_advancement is true", async () => {
  const req = { ...baseReq, can_edit_rank_advancement: true, rank: "רב\"ט" };
  render(<EnrollmentApprovalModal req={req} nodes={[]} exemptionTypes={[]} onClose={vi.fn()} onDone={vi.fn()} />);
  fireEvent.click(screen.getByText("שמור ואשר"));
  await waitFor(() => {
    expect(mockPatchEnrollment).toHaveBeenCalledWith(req.id, expect.objectContaining({ rank: 'רב"ט' }));
  });
});
```

- [ ] **Step 8: Run tests to verify they fail**

Run: `cd frontend && npm test -- EnrollmentApprovalModal`
Expected: FAIL (current code always sends rank fields regardless of the new flag)

- [ ] **Step 9: Implement the frontend fix**

In `frontend/src/api/enrollment.ts`, add `can_edit_rank_advancement: boolean;`
to `EnrollmentRequestDTO`.

In `frontend/src/components/EnrollmentApprovalModal.tsx`, rewrite
`handleSaveAndApprove`:

```typescript
async function handleSaveAndApprove(e: FormEvent) {
  e.preventDefault();
  setSaving(true);
  setError(null);
  try {
    const patch: Parameters<typeof patchEnrollment>[1] = {
      full_name: fullName,
      personal_number: personalNumber,
      requested_node_id: requestedNodeId,
      phone: phone || null,
      email: email || null,
      gender: gender || null,
      enlistment_date: enlistmentDate || null,
      mandatory_end_date: mandatoryEndDate || null,
      discharge_date: dischargeDate || null,
      last_mitvahim_date: lastMitvahimDate || null,
      last_alal_date: lastAlalDate || null,
    };
    if (req.can_edit_rank_advancement) {
      patch.rank = rank || null;
      patch.is_officer = isOfficer;
      patch.rank_track = rank ? rankTrack : null;
    }
    await patchEnrollment(req.id, patch);
    await approveEnrollment(req.id);
    onDone();
  } catch {
    setError("שגיאה בשמירה");
  } finally {
    setSaving(false);
  }
}
```

If the rank/officer form fields (Combobox + checkbox around lines 149–177)
should stay visible but disabled when `!req.can_edit_rank_advancement`
(rather than hidden), wrap them in a `disabled`/`readOnly` state driven by
that flag so the UI still shows the requested rank without allowing edits an
unauthorized commander can't save. Use `disabled={!req.can_edit_rank_advancement}`
on the rank `Combobox` and the "קצין" checkbox.

- [ ] **Step 10: Run tests to verify they pass**

Run: `cd frontend && npm test -- EnrollmentApprovalModal`
Expected: PASS

- [ ] **Step 11: Lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: 0 warnings, 0 errors

- [ ] **Step 12: Commit frontend**

```bash
git add frontend/src/api/enrollment.ts frontend/src/components/EnrollmentApprovalModal.tsx frontend/src/components/EnrollmentApprovalModal.test.tsx
git commit -m "fix: skip rank PATCH for commanders without rank-edit authority so approve always succeeds"
```

---

## Task 3: Commander exemption grants require DM escalation (item 4)

**Files:**
- Modify: `backend/app/services/authority.py` — add
  `_commander_escalation_min_level()` and
  `duty_manager_exemption_immediate_apply_authorized()`.
- Modify: `backend/app/routes/exemptions.py` —
  `grant_commander_exemption_route` (`POST /commander-exemption`): restrict
  to admin or DM at the configured min-level (remove the commander branch).
- Modify: `backend/app/routes/exemption_requests.py` —
  `escalate_commander_exemption_route`: when `body.apply_immediately` is
  true, additionally require admin or DM-at-min-level (403 otherwise).
- Modify: `backend/app/routes/me.py` — `MeResponse` gains
  `can_apply_commander_exemption_immediately: bool`.
- Modify: `frontend/src/api/auth.ts` — `Me` gains
  `can_apply_commander_exemption_immediately?: boolean`.
- Modify: `frontend/src/components/CommanderExemptionGrantForm.tsx` — accept
  a new `canApplyImmediately: boolean` prop; hide the "don't escalate"
  immediate-grant path and the "apply immediately" checkbox when false.
- Modify: `frontend/src/components/ExemptionsPanel.tsx` — pass
  `canApplyImmediately={user?.role === "admin" || (user?.can_apply_commander_exemption_immediately ?? false)}`
  into `CommanderExemptionGrantForm` (check how `ExemptionsPanel` currently
  gets `user` — it may need a new prop or a `useAuth()` call; inspect the
  file first).
- Test: `backend/tests/integration/test_commander_exemption_escalation_api.py`.
- Test: `backend/tests/integration/test_exemptions_api.py` (for the plain
  `/commander-exemption` route gate).
- Test: `frontend/src/components/CommanderExemptionGrantForm.test.tsx` —
  check if it exists; extend or create.

**Interfaces:**
- Produces: `app.services.authority.duty_manager_exemption_immediate_apply_authorized(session, *, user: Soldier, target_node: HierarchyNode | None) -> bool`
- Produces: `app.services.authority.has_any_exemption_immediate_apply_scope(session, *, user: Soldier) -> bool`
- Consumes (existing): `app.services.exemptions.grant_commander_exemption`, `app.services.exemption_requests.submit_commander_escalation`

- [ ] **Step 1: Write the failing unit tests for the new authority helpers**

Add to `backend/app/services/tests/test_authority.py`:

```python
from app.services.authority import (
    duty_manager_exemption_immediate_apply_authorized,
    has_any_exemption_immediate_apply_scope,
)
from app.db.models import DutyManagerScope


def test_dm_at_merkaz_or_above_can_apply_immediately(app_session):
    _level(app_session, "גדוד", 1)
    _level(app_session, "מרכז", 2)
    _level(app_session, "כיתה", 3)
    dm = _soldier(app_session, "9800001", role="duty_manager")
    root = _node(app_session, "מרכז")
    app_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=root.id))
    app_session.flush()
    target = _child(app_session, root, "כיתה")
    assert duty_manager_exemption_immediate_apply_authorized(app_session, user=dm, target_node=target) is True


def test_dm_below_merkaz_cannot_apply_immediately(app_session):
    _level(app_session, "מרכז", 1)
    _level(app_session, "כיתה", 2)
    dm = _soldier(app_session, "9800002", role="duty_manager")
    root = _node(app_session, "כיתה")
    app_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=root.id))
    app_session.flush()
    assert duty_manager_exemption_immediate_apply_authorized(app_session, user=dm, target_node=root) is False


def test_commander_never_qualifies_for_immediate_apply_regardless_of_rank(app_session):
    _level(app_session, "מרכז", 1)
    cmd = _soldier(app_session, "9800003", role="commander")
    root = _node(app_session, "מרכז", commander_id=cmd.id)
    assert duty_manager_exemption_immediate_apply_authorized(app_session, user=cmd, target_node=root) is False


def test_has_any_exemption_immediate_apply_scope_true_for_qualifying_dm(app_session):
    _level(app_session, "מרכז", 1)
    dm = _soldier(app_session, "9800004", role="duty_manager")
    root = _node(app_session, "מרכז")
    app_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=root.id))
    app_session.flush()
    assert has_any_exemption_immediate_apply_scope(app_session, user=dm) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/pytest app/services/tests/test_authority.py -k immediate_apply -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement the authority helpers**

In `backend/app/services/authority.py`, add after
`commander_can_grant_commander_exemption` (~line 199):

```python
COMMANDER_ESCALATION_MIN_LEVEL_KEY = "מרכז"  # fallback default if no setting is configured


def _commander_escalation_min_level(session: Session) -> str:
    try:
        value = get_setting(session, "exemptions.commander_escalation_min_level")
        if value:
            return str(value)
    except SettingNotFound:
        pass
    return COMMANDER_ESCALATION_MIN_LEVEL_KEY


def duty_manager_exemption_immediate_apply_authorized(
    session: Session, *, user: Soldier, target_node: HierarchyNode | None,
) -> bool:
    """True iff `user` is a duty manager whose DM-scope covers `target_node`
    at `exemptions.commander_escalation_min_level` (default מרכז) or above.
    Commanders never qualify here, regardless of rank or scope — only DMs
    (and, via the caller's separate admin bypass, admins) may apply a
    commander-exemption grant immediately without DM approval."""
    dm_root_ids = {
        row.hierarchy_node_id
        for row in session.execute(
            select(DutyManagerScope).where(DutyManagerScope.duty_manager_id == user.id)
        ).scalars().all()
    }
    required_level = _commander_escalation_min_level(session)
    return dm_scope_covers_target(
        session, scope_root_ids=dm_root_ids, target_node=target_node,
        required_level_key=required_level,
    )


def has_any_exemption_immediate_apply_scope(session: Session, *, user: Soldier) -> bool:
    """Cheap `/me`-level flag mirroring has_any_commander_delete_scope: True
    iff `user` holds a DutyManagerScope at the configured minimum level or
    above, independent of any specific target soldier."""
    required_rank = get_level_rank(session, _commander_escalation_min_level(session))
    if required_rank is None:
        return False
    for node in _dm_scope_nodes(session, user.id):
        node_rank = get_level_rank(session, node.level)
        if node_rank is not None and node_rank <= required_rank:
            return True
    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/pytest app/services/tests/test_authority.py -k immediate_apply -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/authority.py backend/app/services/tests/test_authority.py
git commit -m "feat: add DM-level gate helpers for commander-exemption immediate apply"
```

- [ ] **Step 6: Write the failing integration tests for the route gates**

Add to `backend/tests/integration/test_exemptions_api.py` (inspect its
existing fixtures/imports first for the `ExemptionType` creation helper —
`test_commander_exemption_escalation_api.py` has a local `_et()` helper;
reuse or mirror it):

```python
def test_plain_commander_cannot_use_direct_commander_exemption_route(client: TestClient, admin_session: Session):
    from app.db.models import ExemptionType
    et = ExemptionType(name="פטור-ישיר-1", is_commander_exemption=True)
    admin_session.add(et)
    admin_session.commit()
    admin_session.refresh(et)
    cmd = create_soldier(admin_session, personal_number="9900001", role="commander")
    root = create_node(admin_session, level="group", name="direct_grant_root", commander_id=cmd.id)
    target = create_soldier(admin_session, personal_number="9900002", hierarchy_node_id=root.id)
    admin_session.commit()

    resp = client.post(
        f"/api/soldiers/{target.id}/exemptions/commander-exemption",
        headers=auth_headers(cmd),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "x"},
    )
    assert resp.status_code == 403


def test_dm_at_merkaz_can_use_direct_commander_exemption_route(client: TestClient, admin_session: Session):
    from app.db.models import DutyManagerScope, ExemptionType
    et = ExemptionType(name="פטור-ישיר-2", is_commander_exemption=True)
    admin_session.add(et)
    admin_session.commit()
    admin_session.refresh(et)
    dm = create_soldier(admin_session, personal_number="9900003", role="duty_manager")
    root = create_node(admin_session, level="department", name="direct_grant_root2")
    admin_session.add(DutyManagerScope(duty_manager_id=dm.id, hierarchy_node_id=root.id))
    target = create_soldier(admin_session, personal_number="9900004", hierarchy_node_id=root.id)
    admin_session.commit()

    resp = client.post(
        f"/api/soldiers/{target.id}/exemptions/commander-exemption",
        headers=auth_headers(dm),
        json={"exemption_type_id": str(et.id), "start_date": "2026-01-01", "reason": "x"},
    )
    assert resp.status_code == 201, resp.text
```

Add to `backend/tests/integration/test_commander_exemption_escalation_api.py`:

```python
def test_in_scope_commander_cannot_apply_immediately_via_escalation(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="group", name="esc_no_immediate")
    cmd = create_soldier(admin_session, personal_number="9900005", role="commander")
    d.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="9900006", hierarchy_node_id=d.id)
    official = _et(admin_session, "פטור-אסק-immediate-1")
    commander_type = _et(admin_session, "פטור-פיקודי-אסק-immediate-1", is_commander_exemption=True)

    r = client.post(
        f"/api/soldiers/{target.id}/exemptions/commander-escalate",
        headers=auth_headers(cmd),
        json={
            "official_exemption_type_id": str(official.id),
            "commander_exemption_type_id": str(commander_type.id),
            "start_date": "2026-01-01",
            "reason": "סיבה",
            "apply_immediately": True,
        },
    )
    assert r.status_code == 403


def test_in_scope_commander_can_still_submit_escalation_without_immediate(client: TestClient, admin_session: Session):
    d = create_node(admin_session, level="group", name="esc_still_ok")
    cmd = create_soldier(admin_session, personal_number="9900007", role="commander")
    d.commander_id = cmd.id
    admin_session.commit()
    target = create_soldier(admin_session, personal_number="9900008", hierarchy_node_id=d.id)
    official = _et(admin_session, "פטור-אסק-immediate-2")

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
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending_duty_manager"
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/pytest tests/integration/test_exemptions_api.py tests/integration/test_commander_exemption_escalation_api.py -k "direct_commander_exemption or apply_immediately_via_escalation" -v`
Expected: FAIL — commanders still succeed on both direct grant and immediate-apply escalation.

- [ ] **Step 8: Restrict the direct-grant route**

In `backend/app/routes/exemptions.py`, `grant_commander_exemption_route`
(~line 166), replace the `allowed` computation:

```python
    from app.services.authority import duty_manager_exemption_immediate_apply_authorized

    allowed = user.role == "admin"
    if not allowed and is_duty_manager(session, user.id):
        allowed = duty_manager_exemption_immediate_apply_authorized(
            session, user=user, target_node=target_node,
        )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
```

(remove the `if not allowed and is_commander(...)` branch entirely — the
plain immediate-grant route is no longer reachable by commanders; they must
use the escalation route instead. `commander_can_grant_commander_exemption`
stays used elsewhere by the escalation route's own `allowed` check, so keep
its import if still referenced there.)

- [ ] **Step 9: Gate `apply_immediately` on the escalation route**

In `backend/app/routes/exemption_requests.py`,
`escalate_commander_exemption_route` (~line 620), after the existing
`allowed` check block and before the `try: req = submit_commander_escalation(...)`
call, add:

```python
    if body.apply_immediately:
        from app.services.authority import duty_manager_exemption_immediate_apply_authorized
        immediate_allowed = user.role == "admin" or (
            is_duty_manager(session, user.id)
            and duty_manager_exemption_immediate_apply_authorized(
                session, user=user, target_node=target_node,
            )
        )
        if not immediate_allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/pytest tests/integration/test_exemptions_api.py tests/integration/test_commander_exemption_escalation_api.py -v`
Expected: PASS, 0 failures (including all pre-existing tests in both files)

- [ ] **Step 11: Add the `/me` flag and the setting**

In `backend/app/routes/me.py`: add
`can_apply_commander_exemption_immediately: bool = False` to `MeResponse`,
import `has_any_exemption_immediate_apply_scope`, compute:
```python
can_apply_commander_exemption_immediately = (
    user.role == "admin" or has_any_exemption_immediate_apply_scope(session, user=user)
)
```
and pass it into the response.

In `frontend/src/pages/SystemSettingsPage.tsx`, add under the existing
"פטורים" section:
```typescript
{
  key: "exemptions.commander_escalation_min_level",
  label: "החל מאיזו רמת אחראי תורנויות ניתן להחיל פטור פיקודי מיידית",
  description: "אחראי תורנויות ברמה זו ומעלה (או מנהל) יכול להחיל פטור פיקודי באופן מיידי, ללא המתנה לאישור",
  type: "select" as const,
  defaultValue: "מרכז",
  options: [],
},
```
Add `"exemptions.commander_escalation_min_level"` to `MIN_LEVEL_SETTING_KEYS`.

- [ ] **Step 12: Run backend regression suite**

Run: `cd backend && .venv/Scripts/pytest -m auth -q`
Expected: PASS

- [ ] **Step 13: Commit backend**

```bash
git add backend/app/routes/exemptions.py backend/app/routes/exemption_requests.py backend/app/routes/me.py backend/tests/integration/test_exemptions_api.py backend/tests/integration/test_commander_exemption_escalation_api.py frontend/src/pages/SystemSettingsPage.tsx
git commit -m "fix: restrict commander-exemption immediate apply to DM at min level or admin"
```

- [ ] **Step 14: Write the failing frontend test**

Check `frontend/src/components/CommanderExemptionGrantForm.tsx`'s existing
test file (search with `Glob`). Add/extend with:

```typescript
it("hides the non-escalate submit path and apply-immediately checkbox when canApplyImmediately is false", () => {
  render(<CommanderExemptionGrantForm soldierId="s1" commanderExemptionTypes={[{ id: "c1", name: "פ1" }]} officialExemptionTypes={[{ id: "o1", name: "פ2" }]} onGranted={vi.fn()} canApplyImmediately={false} />);
  expect(screen.queryByTestId("commander-exemption-apply-immediately-checkbox")).not.toBeInTheDocument();
});

it("shows the apply-immediately checkbox when canApplyImmediately is true", () => {
  render(<CommanderExemptionGrantForm soldierId="s1" commanderExemptionTypes={[{ id: "c1", name: "פ1" }]} officialExemptionTypes={[{ id: "o1", name: "פ2" }]} onGranted={vi.fn()} canApplyImmediately={true} />);
  fireEvent.click(screen.getByTestId("commander-exemption-escalate-checkbox"));
  expect(screen.getByTestId("commander-exemption-apply-immediately-checkbox")).toBeInTheDocument();
});
```

- [ ] **Step 15: Run tests to verify they fail**

Run: `cd frontend && npm test -- CommanderExemptionGrantForm`
Expected: FAIL — component doesn't accept `canApplyImmediately` prop yet;
checkbox always renders.

- [ ] **Step 16: Implement the frontend gate**

In `frontend/src/components/CommanderExemptionGrantForm.tsx`:
- Add `canApplyImmediately: boolean;` to `Props`.
- Since commanders can no longer skip escalation at all, and only qualifying
  DMs/admins may toggle immediate-apply, simplify the form: keep the
  `escalate` toggle (a commander/DM may still choose "just create the
  official request, no commander-exemption side effect"), but remove the
  non-escalate branch's direct-grant call path for anyone without
  `canApplyImmediately` — instead, when `!canApplyImmediately`, force
  `escalate` to always be treated as `true` and don't render the toggle at
  all (the plain grant is now DM/admin-only, and this form's primary users
  are commanders).

```typescript
  const [escalate, setEscalate] = useState(true);
```
Remove the `escalate` checkbox and its label entirely if `!canApplyImmediately`
is not actually gating that (re-check: `escalate` toggles between "official
request + optional commander exemption" and "commander exemption only, no
official request" — the plain grant is what needs restricting, not
`escalate` itself). Concretely:

```typescript
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
    } else if (canApplyImmediately) {
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
```

Gate the non-escalate toggle option and the "apply immediately" checkbox
both on `canApplyImmediately`:

```tsx
{canApplyImmediately && (
  <label className="flex items-center gap-2 text-sm cursor-pointer">
    <input type="checkbox" checked={escalate} onChange={(e) => setEscalate(e.target.checked)} data-testid="commander-exemption-escalate-checkbox" />
    העלה לאישור מפקד תורנויות כפטור רשמי
  </label>
)}

{escalate && (
  <div className="space-y-2 pr-4 border-r-2 border-indigo-200">
    {/* official type select unchanged */}
    {canApplyImmediately && (
      <label className="flex items-center gap-2 text-sm cursor-pointer">
        <input type="checkbox" checked={applyImmediately} onChange={(e) => setApplyImmediately(e.target.checked)} data-testid="commander-exemption-apply-immediately-checkbox" />
        החל את הפטור הפיקודי מיידית (בנוסף לבקשה)
      </label>
    )}
  </div>
)}
```

Also update `openConfirm`'s validation: `if (escalate && !officialTypeId)`
stays correct since `escalate` now defaults `true` for commanders.

- [ ] **Step 17: Update the call site**

In `frontend/src/components/ExemptionsPanel.tsx`, pass the new prop. First
check how the component currently accesses the current user (it may not
import `useAuth` yet — check imports). Add:
```typescript
import { useAuth } from "../auth/AuthContext";
// inside the component:
const { user } = useAuth();
const canApplyImmediately = user?.role === "admin" || (user?.can_apply_commander_exemption_immediately ?? false);
```
and pass `canApplyImmediately={canApplyImmediately}` to
`<CommanderExemptionGrantForm ... />`.

- [ ] **Step 18: Run tests to verify they pass**

Run: `cd frontend && npm test -- CommanderExemptionGrantForm ExemptionsPanel`
Expected: PASS

- [ ] **Step 19: Lint and typecheck**

Run: `cd frontend && npm run lint && npm run typecheck`
Expected: 0 warnings, 0 errors

- [ ] **Step 20: Commit frontend**

```bash
git add frontend/src/api/auth.ts frontend/src/components/CommanderExemptionGrantForm.tsx frontend/src/components/CommanderExemptionGrantForm.test.tsx frontend/src/components/ExemptionsPanel.tsx
git commit -m "fix: restrict commander-exemption immediate-apply UI to DM at min level or admin"
```

---

## Task 4: Ancestor commanders see and approve descendant transfer requests (item 7)

**Files:**
- Modify: `backend/app/services/hierarchy_transfers.py` —
  `_notify_destination_approvers` and `list_pending_for_approver` switch from
  exact-node matching to `path_ids` containment (ancestor-or-self).
- Test: `backend/tests/integration/test_hierarchy_transfers_api.py`.
- Test: `backend/app/services/tests/` — check if a
  `test_hierarchy_transfers.py` unit-test file already exists for this
  service; if so add unit coverage there too, else the integration test
  suffices (the service functions are simple enough that HTTP-level coverage
  exercises the same logic).

**Interfaces:**
- Consumes (existing): `HierarchyNode.path_ids: list[uuid.UUID]` (root-first,
  self-last, per `_ancestor_n_up` in `authority.py`)
- No public signature changes — `list_pending_for_approver` and
  `_notify_destination_approvers` keep their existing signatures.

- [ ] **Step 1: Write the failing integration test**

Add to `backend/tests/integration/test_hierarchy_transfers_api.py` (this
file already has `test_commander_can_create_and_approve_hierarchy_transfer`
and `test_other_commander_can_still_approve` as close models to follow):

```python
def test_ancestor_commander_sees_and_approves_descendant_transfer(client: TestClient, admin_session: Session):
    top = create_node(admin_session, level="unit", name="anc_top")
    mid = create_node(admin_session, level="department", name="anc_mid", parent=top)
    leaf = create_node(admin_session, level="branch", name="anc_leaf", parent=mid)
    ancestor_cmd = create_soldier(admin_session, personal_number="9990001", role="commander")
    top.commander_id = ancestor_cmd.id
    admin_session.commit()
    src = create_node(admin_session, level="unit", name="anc_src")
    soldier = create_soldier(admin_session, personal_number="9990002", hierarchy_node_id=src.id)
    requester = create_soldier(admin_session, personal_number="9990003", role="admin")
    admin_session.commit()

    resp = client.post(
        "/api/hierarchy-transfers",
        json={"soldier_id": str(soldier.id), "to_node_id": str(leaf.id)},
        headers=auth_headers(requester),
    )
    assert resp.status_code == 200
    req_id = resp.json()["id"]

    list_resp = client.get("/api/hierarchy-transfers/pending", headers=auth_headers(ancestor_cmd))
    assert list_resp.status_code == 200
    assert any(r["id"] == req_id for r in list_resp.json())

    approve_resp = client.post(f"/api/hierarchy-transfers/{req_id}/approve", headers=auth_headers(ancestor_cmd))
    assert approve_resp.status_code == 200, approve_resp.text


def test_unrelated_commander_does_not_see_transfer(client: TestClient, admin_session: Session):
    top = create_node(admin_session, level="unit", name="unrel_top")
    leaf = create_node(admin_session, level="branch", name="unrel_leaf", parent=top)
    unrelated_cmd = create_soldier(admin_session, personal_number="9990004", role="commander")
    other_root = create_node(admin_session, level="unit", name="unrel_other", commander_id=unrelated_cmd.id)
    src = create_node(admin_session, level="unit", name="unrel_src")
    soldier = create_soldier(admin_session, personal_number="9990005", hierarchy_node_id=src.id)
    requester = create_soldier(admin_session, personal_number="9990006", role="admin")
    admin_session.commit()

    resp = client.post(
        "/api/hierarchy-transfers",
        json={"soldier_id": str(soldier.id), "to_node_id": str(leaf.id)},
        headers=auth_headers(requester),
    )
    req_id = resp.json()["id"]

    list_resp = client.get("/api/hierarchy-transfers/pending", headers=auth_headers(unrelated_cmd))
    assert not any(r["id"] == req_id for r in list_resp.json())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/pytest tests/integration/test_hierarchy_transfers_api.py -k ancestor -v`
Expected: FAIL — `test_ancestor_commander_sees_and_approves_descendant_transfer`'s
list assertion fails (ancestor's request is not in the pending list, even
though `approve` itself already succeeds via `authorize()`'s existing
path-containment check).

- [ ] **Step 3: Implement path-containment matching**

In `backend/app/services/hierarchy_transfers.py`, replace
`_notify_destination_approvers`:

```python
def _notify_destination_approvers(session: Session, req: HierarchyTransferRequest) -> None:
    from app.db.models import DutyManagerScope, HierarchyNode
    node = session.get(HierarchyNode, req.to_node_id)
    if node is None or not node.path_ids:
        return
    ancestor_ids = node.path_ids
    approver_ids: set[uuid.UUID] = set()
    ancestor_nodes = session.execute(
        select(HierarchyNode).where(HierarchyNode.id.in_(ancestor_ids))
    ).scalars().all()
    for n in ancestor_nodes:
        if n.commander_id:
            approver_ids.add(n.commander_id)
    dm_rows = session.execute(
        select(DutyManagerScope.duty_manager_id).where(
            DutyManagerScope.hierarchy_node_id.in_(ancestor_ids)
        )
    ).scalars().all()
    approver_ids.update(dm_rows)
    for approver_id in approver_ids:
        create_notification(
            session, soldier_id=approver_id, type=NotificationType.transfer_request_pending,
            title="בקשת העברת חייל למסגרת שלך ממתינה לאישור",
            reference_type="hierarchy_transfer_request", reference_id=req.id,
        )
```

and `list_pending_for_approver`:

```python
def list_pending_for_approver(session: Session, *, approver_id: uuid.UUID) -> list[HierarchyTransferRequest]:
    from app.db.models import DutyManagerScope, HierarchyNode
    commanded_nodes = session.execute(
        select(HierarchyNode.id).where(HierarchyNode.commander_id == approver_id)
    ).scalars().all()
    dm_nodes = session.execute(
        select(DutyManagerScope.hierarchy_node_id).where(DutyManagerScope.duty_manager_id == approver_id)
    ).scalars().all()
    root_ids = set(commanded_nodes) | set(dm_nodes)
    if not root_ids:
        return []
    pending = list(session.execute(
        select(HierarchyTransferRequest).where(HierarchyTransferRequest.status == "pending")
    ).scalars())
    if not pending:
        return []
    to_node_ids = {r.to_node_id for r in pending}
    nodes_by_id = {
        n.id: n
        for n in session.execute(
            select(HierarchyNode).where(HierarchyNode.id.in_(to_node_ids))
        ).scalars().all()
    }
    return [
        r for r in pending
        if (node := nodes_by_id.get(r.to_node_id)) is not None
        and any(root_id in node.path_ids for root_id in root_ids)
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/pytest tests/integration/test_hierarchy_transfers_api.py -v`
Expected: PASS, 0 failures (including all pre-existing tests in the file)

- [ ] **Step 5: Run hierarchy marker suite for regressions**

Run: `cd backend && .venv/Scripts/pytest -m hierarchy -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/hierarchy_transfers.py backend/tests/integration/test_hierarchy_transfers_api.py
git commit -m "fix: use path_ids containment for transfer-request list/notify, matching approve authorization"
```

---

## Final Verification

- [ ] **Step 1: Run the full backend fast suite**

Run: `cd backend && .venv/Scripts/pytest -q`
Expected: PASS, 0 failures

- [ ] **Step 2: Run backend lint/type checks**

Run: `cd backend && .venv/Scripts/ruff check . && .venv/Scripts/mypy app`
Expected: 0 errors

- [ ] **Step 3: Run the full frontend suite**

Run: `cd frontend && npm test && npm run lint && npm run typecheck`
Expected: PASS, 0 warnings, 0 errors

- [ ] **Step 4: Manual smoke check in the browser**

Start the dev stack (`.\dev.ps1` from repo root) and verify in
http://localhost:5173:
- A below-מדור commander sees an enrollment request without the remove/rank
  fields blocking approval.
- A מדור+ commander sees the soldier "remove" button on `/team`; a junior
  commander does not.
- The commander-exemption grant form on a soldier's exemptions panel no
  longer offers "apply immediately" to a plain commander.
- An ancestor (grandparent-level) commander sees a pending hierarchy
  transfer into a descendant node under Approvals.

- [ ] **Step 5: Final commit if any smoke-check fixes were needed**

Otherwise, batch is ready for `merge-worktree-to-dev`.
