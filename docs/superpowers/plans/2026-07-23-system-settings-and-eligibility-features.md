# System Settings & Eligibility Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a batch of admin-configurable system settings (forced-callup on/off, commander-exemption authority level, medical-document view authority) plus three eligibility/UX features: a medical-document preview modal, duty-type filter pills on the Potential page, and mandatory exemption↔duty-type/location mapping review when creating duty types or exemption types (including a brand-new exemption↔location mapping).

**Architecture:** This is a FastAPI (`backend/`) + React/Vite (`frontend/`) app with Postgres via SQLAlchemy/Alembic. System settings are a generic `SystemSetting` key-value store (no backend schema/registry — `frontend/src/pages/SystemSettingsPage.tsx`'s `SETTING_GROUPS` array is the sole source of truth for what settings exist and their types). Existing eligibility/exemption mapping (`ExemptionDutyTypeMap`) is a plain many-to-many join table read directly by services — the new location mapping follows the identical pattern. Feature-toggle gating already has an established pattern (`gimalim.enabled`: backend 403's every route via a small guard function; frontend hides nav/routes via `usePublicSettings()`), which the forced-callup toggle will replicate exactly.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (Mapped/mapped_column, dataclass-style models), Alembic, Pydantic v2, React 18, TanStack Query, react-i18next, Tailwind. New dependency: `react-pdf` (pdf.js wrapper) for in-browser PDF preview.

## Global Constraints

- Hebrew UI strings, English code/identifiers (per project convention — see every existing file touched below).
- No new backend settings registry — every new setting is a `SettingDef` entry in `frontend/src/pages/SystemSettingsPage.tsx`'s `SETTING_GROUPS`, read backend-side via `get_setting`/`bool(get_setting(...))` wrapped in `try/except SettingNotFound`. No migration needed for setting rows (`set_setting` inserts lazily).
- Public (non-admin) settings consumed by the frontend outside `/admin/settings` MUST be added to `_PUBLIC_KEYS` in `backend/app/routes/public_settings.py` — otherwise `usePublicSettings()` returns `undefined` for them.
- Every new backend route follows existing auth patterns: `Depends(require_password_changed)` for the user, then `authorize(session, user, Action.X, target_node=...)` or a role/setting check — never skip auth on a new route.
- Every migration: run `alembic revision -m "description"` from `backend/`, then hand-edit the generated file (this repo's autogenerate is not used for hand-written column/table migrations — every existing migration in `backend/alembic/versions/` is hand-written).
- Backend tests: `pytest -q` (fast suite, parallel via `-n auto`) run from `backend/` with `DATABASE_URL` pointing at the worktree's Postgres. Frontend tests: `npm test` from `frontend/`. Typecheck: `npm run typecheck`. Lint: `npm run lint` (zero warnings enforced).
- DRY/YAGNI: reuse `ExemptionDutyTypeMap`'s exact shape/pattern for the new `ExemptionDutyLocationMap` table and its CRUD routes/service functions — do not invent a different shape.

---

## File Structure

**New files:**
- `backend/alembic/versions/<hash>_add_forced_callup_enabled_setting_key.py` — NOT NEEDED (settings are key-value, no migration) — skip.
- `backend/alembic/versions/<hash>_add_exemption_duty_location_map.py` — new join table migration.
- `frontend/src/components/DocumentPreviewModal.tsx` — new PDF/image preview modal with download button.
- `frontend/src/components/ExemptionTypeFormModal.tsx` — new modal replacing the inline exemption-type creation form, with mandatory duty-type + duty-location review/confirm.

**Modified files (by task):**
- `backend/app/routes/hakpaza.py`, `frontend/src/pages/HakpazaPage.tsx`, `frontend/src/App.tsx`, `frontend/src/components/UnifiedNav.tsx`, `backend/app/routes/public_settings.py`, `frontend/src/pages/SystemSettingsPage.tsx` — Task 1 (forced-callup toggle).
- `backend/app/services/authority.py`, `frontend/src/pages/SystemSettingsPage.tsx` — Task 2 (commander-exemption min level).
- `backend/app/auth/authz.py`, `backend/app/routes/exemption_requests.py`, `frontend/src/pages/SystemSettingsPage.tsx` — Task 3 (medical document view permission).
- `frontend/src/pages/ApprovalsPage.tsx`, `frontend/package.json` — Task 4 (document preview modal wiring).
- `backend/app/services/eligibility.py`, `backend/app/routes/potential.py`, `frontend/src/pages/planning/PotentialPage.tsx`, `frontend/src/api/potential.ts` — Task 5 (Potential page duty-type pills).
- `frontend/src/components/DutyTypeFormModal.tsx` — Task 6 (mandatory exemption-type review on duty-type creation).
- `backend/app/db/models.py`, `backend/app/services/duty_config.py`, `backend/app/routes/duty_config.py`, `frontend/src/api/dutyConfig.ts`, `frontend/src/pages/DutyConfigPage.tsx`, `frontend/src/components/ExemptionTypeFormModal.tsx` — Tasks 7-9 (exemption↔location mapping + mandatory review on exemption-type creation).

---

### Task 1: Forced-callup ("הקפצה פיקודית") feature toggle — backend

**Files:**
- Modify: `backend/app/routes/hakpaza.py`
- Modify: `backend/app/routes/public_settings.py`
- Test: `backend/app/services/tests/test_hakpaza_toggle.py` (new)

**Interfaces:**
- Produces: `_require_hakpaza_enabled(session: Session) -> None` in `hakpaza.py`, raising `HTTPException(403, "hakpaza_disabled")` when `system.setting "forced_callup.enabled"` is `False`. Public setting key `"forced_callup.enabled"` exposed via `GET /settings/public`.

- [ ] **Step 1: Write the failing test**

```python
# backend/app/services/tests/test_hakpaza_toggle.py
from __future__ import annotations

import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.settings_loader import set_setting
from tests.helpers import auth_headers, create_soldier


def _uid():
    return uuid.uuid4().hex[:8]


def test_hakpaza_routes_403_when_disabled(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number=f"hk_{_uid()}", role="admin")
    set_setting(admin_session, "forced_callup.enabled", False, actor_id=admin.id)
    admin_session.commit()

    r = client.get("/api/hakpaza/pending/count", headers=auth_headers(admin))
    assert r.status_code == 403
    assert r.json()["detail"] == "hakpaza_disabled"


def test_hakpaza_routes_enabled_by_default(client: TestClient, admin_session: Session):
    admin = create_soldier(admin_session, personal_number=f"hk2_{_uid()}", role="admin")
    r = client.get("/api/hakpaza/pending/count", headers=auth_headers(admin))
    assert r.status_code == 200
```

Note: `tests/integration/test_swaps_api.py` uses the `client`/`admin_session` fixtures from `tests/conftest.py` — this new test file lives under `backend/app/services/tests/` so it must use the fixtures from `backend/app/services/tests/conftest.py`. Check that file first: if it doesn't provide a `client` fixture (FastAPI `TestClient`), move this test file to `backend/tests/integration/test_hakpaza_toggle.py` instead (that directory's `conftest.py` is confirmed to provide `client` + `admin_session`, per `tests/integration/test_swaps_api.py`).

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`, venv activated, `DATABASE_URL` set): `pytest tests/integration/test_hakpaza_toggle.py -q` (or wherever Step 1 placed it)
Expected: FAIL — `/api/hakpaza/pending/count` returns 200 even when disabled (no gating exists yet), or 404 if that exact route doesn't exist — **first inspect `backend/app/routes/hakpaza.py` to find its actual route paths and pick one GET route that requires no request body to use in the test** (e.g. a "list pending" or "count" route). Adjust the test's URL to match reality before proceeding.

- [ ] **Step 3: Write minimal implementation**

In `backend/app/routes/hakpaza.py`, add near the top (after existing imports):

```python
from app.services.settings_loader import SettingNotFound, get_setting


def _require_hakpaza_enabled(session: Session) -> None:
    try:
        enabled = get_setting(session, "forced_callup.enabled")
        if not bool(enabled):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="hakpaza_disabled")
    except SettingNotFound:
        pass  # enabled by default
```

Then add `_require_hakpaza_enabled(session)` as the first line of every route handler's body in this file (mirror `backend/app/routes/gimelim.py`'s `_require_gimelim_enabled` usage exactly — check that file for the precise call-site convention, i.e. whether it's called manually inside each function or via `Depends`). Match whichever pattern `gimelim.py` uses so the codebase stays consistent.

In `backend/app/routes/public_settings.py`, add `"forced_callup.enabled"` to the `_PUBLIC_KEYS` set:

```python
_PUBLIC_KEYS = {
    "gimalim.enabled",
    "gimalim.default_rest_days",
    "gimalim.reserve_fate",
    "shifts.auto_split_node_quotas",
    "telegram.enabled",
    "forced_callup.enabled",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_hakpaza_toggle.py -q`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/hakpaza.py backend/app/routes/public_settings.py backend/tests/integration/test_hakpaza_toggle.py
git commit -m "feat: gate forced-callup routes behind forced_callup.enabled setting"
```

---

### Task 2: Forced-callup feature toggle — frontend + settings UI

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/UnifiedNav.tsx`
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`
- Test: `frontend/src/App.test.tsx` (new, or add to existing App test file if one exists — check `frontend/src/App.test.tsx` first)

**Interfaces:**
- Consumes: `usePublicSettings()` from `frontend/src/hooks/usePublicSettings.ts` (already exists), returning `SettingsMap | null`.
- Produces: `/commander/hakpaza` route only mounted when `settings?.["forced_callup.enabled"] !== false`; nav item hidden under the same condition.

- [ ] **Step 1: Write the failing test**

First check whether `frontend/src/App.test.tsx` exists (`ls frontend/src/App.test.tsx`). If it does, add a test there; if not, skip straight to a simpler assertion inside `frontend/src/components/UnifiedNav.test.tsx` if that file exists, otherwise write a minimal new test:

```tsx
// frontend/src/App.test.tsx (add if file exists; create with this content if not)
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import * as publicSettingsApi from "./api/publicSettings";

vi.mock("./api/publicSettings");

describe("App - forced callup gating", () => {
  it("does not register /commander/hakpaza route when forced_callup.enabled is false", async () => {
    vi.mocked(publicSettingsApi.getPublicSettings).mockResolvedValue({
      "forced_callup.enabled": false,
    });
    // Render App at /commander/hakpaza and confirm it does NOT show HakpazaPage content —
    // exact assertion depends on how ProtectedRoute/AppGate behave when a route isn't
    // matched (likely falls through to a 404 or redirect). Inspect App.tsx's route
    // fallback behavior before finalizing this assertion.
  });
});
```

Since `usePublicSettings` caches at module level (per the research: "module-level cached fetch"), this test needs to reset that cache between tests — check `frontend/src/hooks/usePublicSettings.ts` for an exported reset function or re-check its implementation; if no reset hook exists, this test may need `vi.resetModules()` + dynamic re-import of `App`. **Read `usePublicSettings.ts` fully before writing this test** — the plan cannot specify the exact reset mechanism without seeing that file's caching implementation first.

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/App.test.tsx`
Expected: FAIL (route currently always mounted)

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/App.tsx`, add next to the existing `telegramEnabled` line:

```tsx
const telegramEnabled = settings?.["telegram.enabled"] !== false;
const hakpazaEnabled = settings?.["forced_callup.enabled"] !== false;
```

Wrap the hakpaza route:

```tsx
{hakpazaEnabled && (
  <Route path="/commander/hakpaza" element={<AppGate><HakpazaPage /></AppGate>} />
)}
```

In `frontend/src/components/UnifiedNav.tsx`, find the `commanderItems` array (contains the `{ label: "הקפצה פיקודית", to: "/commander/hakpaza", testId: "nav-hakpaza" }` entry) and the component function that builds/renders nav items. Add:

```tsx
import { usePublicSettings } from "../hooks/usePublicSettings";
```

Then inside the component, before building the final nav list:

```tsx
const settings = usePublicSettings();
const hakpazaEnabled = settings?.["forced_callup.enabled"] !== false;
```

Filter the hakpaza entry out of `commanderItems` when `!hakpazaEnabled` before rendering (exact filter syntax depends on how `commanderItems` is consumed — read the surrounding ~30 lines of `UnifiedNav.tsx` around the `commanderItems` array to see if it's rendered via `.map()` directly or merged into a combined list first, then filter at that point):

```tsx
const visibleCommanderItems = hakpazaEnabled
  ? commanderItems
  : commanderItems.filter(item => item.to !== "/commander/hakpaza");
```

Use `visibleCommanderItems` wherever `commanderItems` was rendered.

In `frontend/src/pages/SystemSettingsPage.tsx`, add a new setting group (or add to an existing relevant group — "הקפצה פיקודית" doesn't have its own group yet, so add a new one after the `"החלפות"` group):

```tsx
{
  label: "הקפצה פיקודית",
  settings: [
    { key: "forced_callup.enabled", label: "הקפצה פיקודית מופעלת", description: "כיבוי מסתיר את דף ההקפצה הפיקודית ומבטל את כל הפעולות הקשורות אליה", type: "boolean", defaultValue: true },
  ],
},
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/App.test.tsx`
Expected: PASS

- [ ] **Step 5: Run typecheck and lint**

Run: `npm run typecheck && npm run lint`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/UnifiedNav.tsx frontend/src/pages/SystemSettingsPage.tsx frontend/src/App.test.tsx
git commit -m "feat: hide forced-callup nav/route when forced_callup.enabled is off"
```

---

### Task 3: Commander-exemption minimum command level — system setting

**Files:**
- Modify: `backend/app/services/authority.py`
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`
- Test: `backend/app/services/tests/test_authority.py` (existing file — add to it)

**Interfaces:**
- Consumes: `get_level_rank(session, level_key)` (existing, `backend/app/services/hierarchy.py`), `get_setting`/`SettingNotFound` (existing, `backend/app/services/settings_loader.py`).
- Produces: `commander_can_grant_commander_exemption` now reads the minimum level from setting `"exemptions.commander_exemption_min_level"` (falling back to the existing hardcoded `"מדור"` constant when unset), instead of the hardcoded constant alone.

- [ ] **Step 1: Write the failing test**

Open `backend/app/services/tests/test_authority.py` first to see existing test structure/fixtures for `commander_can_grant_commander_exemption`, then add:

```python
def test_commander_exemption_min_level_configurable(admin_session):
    from app.services.authority import commander_can_grant_commander_exemption
    from app.services.settings_loader import set_setting
    from tests.helpers import create_node, create_soldier

    # A commander of a "צוות" (team) node — below the default "מדור" threshold.
    team_node = create_node(admin_session, level="צוות", name=f"team_{uuid.uuid4().hex[:8]}")
    cmd = create_soldier(admin_session, personal_number=f"ace_{uuid.uuid4().hex[:8]}", role="commander")
    team_node.commander_id = cmd.id
    admin_session.commit()

    # Default threshold ("מדור") — a צוות commander should NOT qualify.
    assert not commander_can_grant_commander_exemption(
        admin_session, commander_id=cmd.id, commander_rank=None
    )

    # Lower the required threshold to "צוות" via setting — now they should qualify.
    set_setting(admin_session, "exemptions.commander_exemption_min_level", "צוות", actor_id=None)
    admin_session.commit()
    assert commander_can_grant_commander_exemption(
        admin_session, commander_id=cmd.id, commander_rank=None
    )
```

Adjust the `level="צוות"` argument to `create_node` to match whatever level-key strings `test_authority.py`'s existing tests already use (check for an existing helper/fixture creating hierarchy level types, since `HierarchyLevelType` rows must exist for `get_level_rank` to resolve "צוות"/"מדור" — if the test DB doesn't seed level types automatically, find how other tests in this file already get `get_level_rank` to work, e.g. a fixture that creates `HierarchyLevelType` rows, and reuse it).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/services/tests/test_authority.py::test_commander_exemption_min_level_configurable -q`
Expected: FAIL — second assertion fails because `commander_can_grant_commander_exemption` ignores the setting today.

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/authority.py`, find the existing `commander_can_grant_commander_exemption` function (currently uses the module constant `COMMANDER_EXEMPTION_MIN_LEVEL_KEY = "מדור"`). Modify it:

```python
from app.services.settings_loader import SettingNotFound, get_setting

COMMANDER_EXEMPTION_MIN_LEVEL_KEY = "מדור"  # fallback default if no setting is configured


def _commander_exemption_min_level(session: Session) -> str:
    try:
        value = get_setting(session, "exemptions.commander_exemption_min_level")
        if value:
            return str(value)
    except SettingNotFound:
        pass
    return COMMANDER_EXEMPTION_MIN_LEVEL_KEY


def commander_can_grant_commander_exemption(
    session: Session, *, commander_id: uuid.UUID, commander_rank: str | None,
) -> bool:
    if commander_rank and commander_rank in RANKS_RASAN_AND_ABOVE:
        return True
    min_level_key = _commander_exemption_min_level(session)
    mador_rank = get_level_rank(session, min_level_key)
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

(Keep the rest of the function's existing body/imports intact — only the level-key resolution changes from a hardcoded constant read to `_commander_exemption_min_level(session)`.)

In `frontend/src/pages/SystemSettingsPage.tsx`, add a new setting to the existing settings group that covers exemptions (find the group housing `"registration.telegram_required"`-adjacent or exemption-related settings — if none exists yet, add a new group `"פטורים"` after `"הרשמה"`, checking first whether a `"פטורים"` group already exists from the existing `"מאשר פטורים — דרג רסן ומעלה בלבד"` setting seen in the live app — **reuse that existing group if found** rather than creating a duplicate):

```tsx
{
  key: "exemptions.commander_exemption_min_level",
  label: "החל מאיזו רמת פיקוד ניתן להעניק פטור פיקודי",
  description: "מפקד ברמה זו ומעלה (קרוב יותר לשורש) יכול להעניק פטור פיקודי, גם ללא דרגת קצונה מתאימה",
  type: "select" as const,
  defaultValue: "מדור",
  options: [],  // populated dynamically from hierarchy level types — see rendering special-case below
},
```

Then in the render code, find where `hierarchyLevelOptions` is built (used for `swaps.restrict_to_hierarchy_level`) and extend the special-case condition that swaps in `hierarchyLevelOptions` for the select's `options` prop:

```tsx
const useHierarchyLevelOptions = def.key === "swaps.restrict_to_hierarchy_level"
  || def.key === "exemptions.commander_exemption_min_level";
```

Use `useHierarchyLevelOptions ? hierarchyLevelOptions : def.options` wherever the existing single special-case (`def.key === "swaps.restrict_to_hierarchy_level" ? hierarchyLevelOptions : def.options`) is currently written — but note `hierarchyLevelOptions` includes a `{ value: "", label: "ללא הגבלה" }` "no restriction" option (appropriate for the swap-restriction setting) which is **not** appropriate here (there must always be a minimum level). Build a second options array without that entry:

```tsx
const commanderExemptionLevelOptions = levelTypes.map(lt => ({ value: lt.key, label: lt.label }));
```

And use `commanderExemptionLevelOptions` specifically for the `exemptions.commander_exemption_min_level` key, keeping `hierarchyLevelOptions` (with the "no restriction" entry) reserved for `swaps.restrict_to_hierarchy_level` only.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest app/services/tests/test_authority.py -q`
Expected: PASS (all tests in file, including the new one)

- [ ] **Step 5: Typecheck/lint frontend**

Run: `npm run typecheck && npm run lint`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/authority.py frontend/src/pages/SystemSettingsPage.tsx backend/app/services/tests/test_authority.py
git commit -m "feat: make commander-exemption minimum command level configurable"
```

---

### Task 4: Medical document view permission — system setting + backend enforcement

**Files:**
- Modify: `backend/app/auth/authz.py`
- Modify: `backend/app/routes/exemption_requests.py`
- Modify: `frontend/src/pages/SystemSettingsPage.tsx`
- Test: `backend/tests/integration/test_exemption_requests.py` (or wherever the existing file-download tests live — search `grep -rl "download_exemption_file\|exemption-requests.*files" backend/tests backend/app/services/tests` first to find the right file)

**Interfaces:**
- Produces: `can_view_medical_document(session: Session, viewer: Soldier, target_soldier: Soldier) -> bool` in `backend/app/auth/authz.py`. Two new settings: `"exemptions.medical_doc_min_commander_level"` (default `"מדור"`) and `"exemptions.medical_doc_min_duty_manager_level"` (default `"מרכז"`).

- [ ] **Step 1: Write the failing test**

First run `grep -rn "download_exemption_file\|files/{file_id}" backend/tests backend/app/services/tests` to find existing tests for the download route, then add a new test file/function alongside them:

```python
def test_medical_document_requires_minimum_commander_level(client, admin_session):
    """A commander below the configured minimum level (a plain team/צוות
    commander, by default requiring מדור-and-above) cannot download a
    medical exemption's attached file, even if they're in the soldier's
    command chain and could otherwise see the exemption's other fields."""
    from app.db.models import ExemptionRequest, ExemptionRequestFile, ExemptionType
    from app.services.settings_loader import set_setting
    from tests.helpers import auth_headers, create_node, create_soldier

    root = create_node(admin_session, level="מרכז", name="root_md")
    team = create_node(admin_session, level="צוות", name="team_md", parent=root)
    team_cmd = create_soldier(admin_session, personal_number="md_team_cmd", role="commander")
    team.commander_id = team_cmd.id
    admin_session.commit()

    soldier = create_soldier(admin_session, personal_number="md_soldier", hierarchy_node_id=team.id)
    et = ExemptionType(name="med_test", is_medical=True)
    admin_session.add(et)
    admin_session.flush()
    req = ExemptionRequest(
        soldier_id=soldier.id, exemption_type_id=et.id, status="pending_commander",
        start_date="2026-01-01",
    )
    admin_session.add(req)
    admin_session.flush()
    f = ExemptionRequestFile(
        exemption_request_id=req.id, file_name="note.pdf",
        content_type="application/pdf", data=b"%PDF-1.4 test",
    )
    admin_session.add(f)
    admin_session.commit()

    r = client.get(
        f"/api/exemption-requests/{req.id}/files/{f.id}",
        headers=auth_headers(team_cmd),
    )
    assert r.status_code == 403
```

Check `ExemptionRequest`'s exact required fields in `backend/app/db/models.py` before finalizing this test (the plan's snippet above may be missing a required column — read the model first and adjust).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest <path from step 1> -k medical_document_requires_minimum -q`
Expected: FAIL (currently returns 200 — the download route only checks scope containment, not rank/level, per Task research)

- [ ] **Step 3: Write minimal implementation**

In `backend/app/auth/authz.py`, add:

```python
def can_view_medical_document(
    session: Session, viewer: Soldier, target: Soldier
) -> bool:
    """Stricter than can_see_private: viewing the medical DOCUMENT itself
    (not just the exemption's other fields) requires the viewer be a
    commander at or above a configured minimum level in the target's own
    command chain, or a duty manager at or above a separate configured
    minimum level — plain scope containment is not enough."""
    from app.services.hierarchy import get_level_rank
    from app.services.settings_loader import SettingNotFound, get_setting

    if viewer.id == target.id:
        return True
    node = session.get(HierarchyNode, target.hierarchy_node_id) if target.hierarchy_node_id else None
    if node is None:
        return False
    roots = scope_root_ids(session, viewer)
    if not _node_in_scope(node, roots):
        return False

    def _min_rank(key: str, default_level: str) -> int | None:
        try:
            level_key = get_setting(session, key) or default_level
        except SettingNotFound:
            level_key = default_level
        return get_level_rank(session, str(level_key))

    if is_commander(session, viewer.id):
        min_rank = _min_rank("exemptions.medical_doc_min_commander_level", "מדור")
        commanded = session.execute(
            select(HierarchyNode).where(HierarchyNode.commander_id == viewer.id)
        ).scalars().all()
        for cn in commanded:
            cn_rank = get_level_rank(session, cn.level)
            if min_rank is not None and cn_rank is not None and cn_rank <= min_rank:
                return True
    if is_duty_manager(session, viewer.id):
        min_rank = _min_rank("exemptions.medical_doc_min_duty_manager_level", "מרכז")
        dm_nodes = session.execute(
            select(DutyManagerScope.hierarchy_node_id).where(DutyManagerScope.duty_manager_id == viewer.id)
        ).scalars().all()
        for nid in dm_nodes:
            n = session.get(HierarchyNode, nid)
            if n is None:
                continue
            n_rank = get_level_rank(session, n.level)
            if min_rank is not None and n_rank is not None and n_rank <= min_rank:
                return True
    return False
```

Add `DutyManagerScope` to this file's existing `from app.db.models import ...` line if not already imported.

In `backend/app/routes/exemption_requests.py`, find `download_exemption_file` (the route handler for `GET /exemption-requests/{request_id}/files/{file_id}`). Replace its current scope-only check with:

```python
from app.auth.authz import can_view_medical_document

# ... inside download_exemption_file, after loading `req` and the target soldier:
if req.soldier_id != user.id:
    target_soldier = session.get(Soldier, req.soldier_id)
    if target_soldier is None or not can_view_medical_document(session, user, target_soldier):
        raise HTTPException(status_code=403, detail="no_permission")
```

Replace whatever the existing inline scope-check block was (per Task research: `lines ~465-494`, computing `root_ids`/`node.path_ids` manually) with this call — keep the rest of the function (loading `ef`, building the `Response`) unchanged.

In `frontend/src/pages/SystemSettingsPage.tsx`, add both new settings to the same exemptions-related group used in Task 3:

```tsx
{
  key: "exemptions.medical_doc_min_commander_level",
  label: "צפייה במסמך רפואי — החל מאיזו רמת מפקד בשרשרת הפיקוד",
  description: "מפקדים ברמה זו ומעלה בשרשרת הפיקוד של החייל יכולים לצפות במסמך הרפואי עצמו (לא רק בפרטי הפטור)",
  type: "select" as const,
  defaultValue: "מדור",
  options: [],
},
{
  key: "exemptions.medical_doc_min_duty_manager_level",
  label: "צפייה במסמך רפואי — החל מאיזו רמת אחראי תורנויות",
  description: "אחראי תורנויות עם סמכות ברמה זו ומעלה יכול לצפות במסמך הרפואי עצמו",
  type: "select" as const,
  defaultValue: "מרכז",
  options: [],
},
```

Extend the `useHierarchyLevelOptions`/`commanderExemptionLevelOptions` special-case set from Task 3 to also cover these two new keys (same no-"ללא הגבלה" options array, since both require a concrete minimum level).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest <path> -k medical_document_requires_minimum -q`
Expected: PASS

- [ ] **Step 5: Regression-check existing download tests**

Run: `pytest <the file from step 1 in full> -q`
Expected: all PASS — a soldier's own commander at/above the configured level, and the soldier themself, must still be able to download. If any existing test now fails, it was relying on the old (looser) scope-only check with a commander/DM below the new default threshold — fix that test's fixture to create a commander/DM at an appropriate level, don't loosen the new check.

- [ ] **Step 6: Commit**

```bash
git add backend/app/auth/authz.py backend/app/routes/exemption_requests.py frontend/src/pages/SystemSettingsPage.tsx <test file>
git commit -m "feat: require minimum command/duty-manager level to view medical exemption documents"
```

---

### Task 5: Document preview modal (image/PDF) with download button

**Files:**
- Create: `frontend/src/components/DocumentPreviewModal.tsx`
- Modify: `frontend/src/pages/ApprovalsPage.tsx`
- Modify: `frontend/package.json`
- Test: `frontend/src/components/DocumentPreviewModal.test.tsx` (new)

**Interfaces:**
- Consumes: `exemptionFileDownloadUrl(erId, fileId)` (existing, `frontend/src/api/exemptions.ts`), `api` client (existing, `frontend/src/api/client.ts`).
- Produces: `<DocumentPreviewModal fileUrl={string} fileName={string} contentType={string} onClose={() => void} />`.

- [ ] **Step 1: Install `react-pdf`**

```bash
cd frontend
npm install react-pdf
```

Run: `npm run typecheck` immediately after to confirm the new dependency doesn't break the build (react-pdf ships its own types).

- [ ] **Step 2: Write the failing test**

```tsx
// frontend/src/components/DocumentPreviewModal.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import DocumentPreviewModal from "./DocumentPreviewModal";

vi.mock("react-pdf", () => ({
  Document: ({ children }: { children: React.ReactNode }) => <div data-testid="pdf-document">{children}</div>,
  Page: () => <div data-testid="pdf-page" />,
  pdfjs: { GlobalWorkerOptions: { workerSrc: "" }, version: "0.0.0" },
}));

describe("DocumentPreviewModal", () => {
  it("renders an image preview for image content types", () => {
    render(
      <DocumentPreviewModal
        fileUrl="blob:mock-image"
        fileName="note.png"
        contentType="image/png"
        onClose={() => {}}
      />
    );
    const img = screen.getByRole("img");
    expect(img).toHaveAttribute("src", "blob:mock-image");
  });

  it("renders a PDF viewer for application/pdf content type", () => {
    render(
      <DocumentPreviewModal
        fileUrl="blob:mock-pdf"
        fileName="note.pdf"
        contentType="application/pdf"
        onClose={() => {}}
      />
    );
    expect(screen.getByTestId("pdf-document")).toBeInTheDocument();
  });

  it("has a working download link pointing at the file URL", () => {
    render(
      <DocumentPreviewModal
        fileUrl="blob:mock-pdf"
        fileName="note.pdf"
        contentType="application/pdf"
        onClose={() => {}}
      />
    );
    const link = screen.getByRole("link", { name: /הורדה/ });
    expect(link).toHaveAttribute("href", "blob:mock-pdf");
    expect(link).toHaveAttribute("download", "note.pdf");
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(
      <DocumentPreviewModal
        fileUrl="blob:mock-pdf"
        fileName="note.pdf"
        contentType="application/pdf"
        onClose={onClose}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "✕" }));
    expect(onClose).toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npx vitest run src/components/DocumentPreviewModal.test.tsx`
Expected: FAIL — module doesn't exist yet.

- [ ] **Step 4: Write minimal implementation**

```tsx
// frontend/src/components/DocumentPreviewModal.tsx
import { useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface Props {
  fileUrl: string;
  fileName: string;
  contentType: string;
  onClose: () => void;
}

export default function DocumentPreviewModal({ fileUrl, fileName, contentType, onClose }: Props) {
  const [numPages, setNumPages] = useState<number | null>(null);
  const isPdf = contentType === "application/pdf";

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[70] p-4" onClick={onClose}>
      <div
        className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-4 w-full max-w-2xl max-h-[90dvh] overflow-y-auto"
        dir="rtl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex justify-between items-center mb-3">
          <h3 className="font-semibold text-sm truncate">{fileName}</h3>
          <div className="flex items-center gap-3">
            <a
              href={fileUrl}
              download={fileName}
              className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              הורדה
            </a>
            <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">✕</button>
          </div>
        </div>

        {isPdf ? (
          <Document
            file={fileUrl}
            onLoadSuccess={({ numPages: n }) => setNumPages(n)}
            loading={<p className="text-sm text-gray-500">טוען מסמך...</p>}
            error={<p className="text-sm text-red-500">שגיאה בטעינת המסמך</p>}
          >
            {Array.from({ length: numPages ?? 0 }, (_, i) => (
              <Page key={i} pageNumber={i + 1} width={600} />
            ))}
          </Document>
        ) : (
          <img src={fileUrl} alt={fileName} className="max-w-full h-auto mx-auto" />
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npx vitest run src/components/DocumentPreviewModal.test.tsx`
Expected: PASS (4 tests)

- [ ] **Step 6: Wire into ApprovalsPage.tsx**

In `frontend/src/pages/ApprovalsPage.tsx`, replace the body of `openExemptionFile` (currently does `window.open` on a blob URL) so it stores the blob URL + metadata in new state instead, and render `DocumentPreviewModal` when that state is set:

```tsx
import DocumentPreviewModal from "../components/DocumentPreviewModal";

// inside ApprovalsPage component, alongside other useState calls:
const [previewFile, setPreviewFile] = useState<{ url: string; name: string; contentType: string } | null>(null);

async function openExemptionFile(erId: string, fileId: string, fileName: string) {
  try {
    const resp = await api.get(exemptionFileDownloadUrl(erId, fileId), { responseType: "blob" });
    const blob = resp.data as Blob;
    const url = URL.createObjectURL(blob);
    setPreviewFile({ url, name: fileName, contentType: blob.type || "application/octet-stream" });
  } catch (err) {
    setActionError(describeError(err));
  }
}
```

Update the call site (`onClick={() => openExemptionFile(er.id, f.id)}`) to pass the file name too: `onClick={() => openExemptionFile(er.id, f.id, f.file_name)}`.

Add near the bottom of the JSX (alongside the existing `{selectedEnrollment && <EnrollmentApprovalModal .../>}` block):

```tsx
{previewFile && (
  <DocumentPreviewModal
    fileUrl={previewFile.url}
    fileName={previewFile.name}
    contentType={previewFile.contentType}
    onClose={() => {
      URL.revokeObjectURL(previewFile.url);
      setPreviewFile(null);
    }}
  />
)}
```

Remove the now-unused `window.open`/`beforeunload` logic from the old `openExemptionFile` body.

- [ ] **Step 7: Typecheck and lint**

Run: `npm run typecheck && npm run lint`
Expected: no errors

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/DocumentPreviewModal.tsx frontend/src/components/DocumentPreviewModal.test.tsx frontend/src/pages/ApprovalsPage.tsx frontend/package.json frontend/package-lock.json
git commit -m "feat: preview exemption medical documents in-app (PDF/image) with download button"
```

---

### Task 6: Potential page — duty-type filter pills

**Files:**
- Modify: `backend/app/services/eligibility.py`
- Modify: `backend/app/routes/potential.py`
- Modify: `frontend/src/api/potential.ts`
- Modify: `frontend/src/pages/planning/PotentialPage.tsx`
- Test: `backend/app/services/tests/test_potential.py` (existing — add to it)

**Interfaces:**
- Consumes: `compute_eligibility_exclusions(session, soldiers, *, mitvahim_months, alal_months) -> dict[UUID, set[UUID]]` (existing, `backend/app/services/eligibility.py`).
- Produces: `GET /potential` response's `soldiers[]` entries gain a new field `eligible_duty_type_ids: list[str]`. Frontend `PotentialResult.soldiers[]` type gains `eligible_duty_type_ids: string[]`.

- [ ] **Step 1: Write the failing test**

Open `backend/app/services/tests/test_potential.py` to see the existing fixture setup for `compute_potential` (it already imports `ExemptionDutyTypeMap` per Task research), then add:

```python
def test_compute_potential_includes_eligible_duty_type_ids(admin_session):
    from app.db.models import DutyType
    from app.services.potential import compute_potential
    from tests.helpers import create_node, create_soldier

    node = create_node(admin_session, level="unit", name=f"pot_dt_{uuid.uuid4().hex[:8]}")
    male_only = DutyType(name=f"male_only_{uuid.uuid4().hex[:8]}", score_per_day=1, requirements={"allowed_genders": ["male"]})
    unrestricted = DutyType(name=f"any_{uuid.uuid4().hex[:8]}", score_per_day=1)
    admin_session.add_all([male_only, unrestricted])
    admin_session.flush()

    soldier = create_soldier(
        admin_session, personal_number=f"pot_s_{uuid.uuid4().hex[:8]}", hierarchy_node_id=node.id,
    )
    soldier.gender = "female"
    admin_session.commit()

    result = compute_potential(admin_session, node_id=node.id, reference_date=None)
    detail = next(s for s in result.soldiers if s.soldier_id == soldier.id)
    assert unrestricted.id in detail.eligible_duty_type_ids
    assert male_only.id not in detail.eligible_duty_type_ids
```

Check `compute_potential`'s exact signature (parameter names, whether `reference_date` accepts `None`) in `backend/app/services/potential.py` before finalizing — adjust the call if it differs. Check `SoldierPotentialDetail`'s exact current field set in the same file (dataclass or Pydantic model) so the new field is added consistently.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/services/tests/test_potential.py -k eligible_duty_type_ids -q`
Expected: FAIL — `AttributeError: 'SoldierPotentialDetail' object has no attribute 'eligible_duty_type_ids'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/potential.py`, find the `SoldierPotentialDetail` class definition and add a new field:

```python
eligible_duty_type_ids: list[uuid.UUID]
```

(Match the exact style already used — dataclass field with no default if the class is a plain `@dataclass`, or `Field(default_factory=list)` if Pydantic — read the class definition first.)

In `compute_potential` (same file), find where `SoldierPotentialDetail` instances are constructed per soldier and where `compute_eligibility_exclusions` (or an equivalent per-soldier exclusion lookup) may already run for `counted`/`reason` computation — reuse that pass instead of adding a second one. Add, near the top of the function (after loading `soldiers` and before building per-soldier details):

```python
from app.services.eligibility import compute_eligibility_exclusions
from app.db.models import DutyType

all_duty_type_ids = {
    dt.id for dt in session.execute(select(DutyType).where(DutyType.active.is_(True))).scalars().all()
}
exclusions = compute_eligibility_exclusions(
    session, soldiers, mitvahim_months=mitvahim_months, alal_months=alal_months,
)
```

(`mitvahim_months`/`alal_months` should already be in scope in this function — if not, read them via the same `get_setting`/default pattern used elsewhere in `potential.py` or `eligibility.py`.) Then when constructing each `SoldierPotentialDetail`, add:

```python
eligible_duty_type_ids=list(all_duty_type_ids - exclusions.get(soldier.id, set())),
```

In `backend/app/routes/potential.py`, find the Pydantic response model for a per-soldier entry (likely `SoldierPotentialOut` or similar, inside `PotentialOut`) and add:

```python
eligible_duty_type_ids: list[uuid.UUID]
```

Update wherever that model is constructed from `SoldierPotentialDetail` (a `_to_out`-style function or inline in the route) to pass through `detail.eligible_duty_type_ids`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest app/services/tests/test_potential.py -q`
Expected: PASS (all tests in file)

- [ ] **Step 5: Write the frontend failing test**

Check `frontend/src/pages/planning/PotentialPage.test.tsx` — if it exists, add to it; otherwise this step focuses purely on manual verification via `npm run typecheck` + `npm run dev` since a full page-level filter test would need extensive mock data setup already established in that file (read it first to match its existing mock shape).

```tsx
// Add to frontend/src/pages/planning/PotentialPage.test.tsx (adjust to match its existing mock/render helpers)
it("filters soldiers to only those eligible for all selected duty type pills", async () => {
  // Arrange mock getPotential() to return two soldiers: one eligible for duty type A and B,
  // one eligible for only A. Render the page, click pills for A and B.
  // Assert only the fully-eligible soldier's row remains visible.
  // (Exact render/query helpers depend on this file's existing setup — read it before writing.)
});
```

- [ ] **Step 6: Run test to verify it fails**

Run: `npx vitest run src/pages/planning/PotentialPage.test.tsx`
Expected: FAIL (no pill filter UI exists yet)

- [ ] **Step 7: Write minimal implementation**

In `frontend/src/api/potential.ts`, add `eligible_duty_type_ids: string[];` to the `SoldierPotentialDetail` interface (line ~4-13 per Task research).

In `frontend/src/pages/planning/PotentialPage.tsx`:

```tsx
import { listDutyTypes, DutyType } from "../../api/dutyConfig";

// inside the component:
const dutyTypesQuery = useQuery({ queryKey: queryKeys.dutyTypes(), queryFn: listDutyTypes });
const dutyTypes = dutyTypesQuery.data ?? [];
const [selectedDutyTypeIds, setSelectedDutyTypeIds] = useState<string[]>([]);

function toggleDutyTypePill(id: string) {
  setSelectedDutyTypeIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
}
```

(Check `queryKeys.ts` for whether `dutyTypes()` already exists as a key — reuse it if so, since `DutyTypeFormModal`/`DutyConfigPage` already fetch duty types somewhere.)

Render pills above the existing table (adjust container/className to match the page's existing header layout):

```tsx
<div className="flex flex-wrap gap-2 mb-3" dir="rtl">
  {dutyTypes.map(dt => (
    <button
      key={dt.id}
      type="button"
      onClick={() => toggleDutyTypePill(dt.id)}
      className={`px-3 py-1 rounded-full text-xs border ${
        selectedDutyTypeIds.includes(dt.id)
          ? "bg-indigo-600 text-white border-indigo-600"
          : "bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-200 border-gray-300 dark:border-gray-600"
      }`}
    >
      {dt.name}
    </button>
  ))}
</div>
```

Then, wherever the per-node soldier list is filtered/rendered before being passed to `soldierCols`'s table (the expandable sub-table from Task research), filter it:

```tsx
const filteredSoldiers = selectedDutyTypeIds.length === 0
  ? result.soldiers
  : result.soldiers.filter(s =>
      selectedDutyTypeIds.every(dtId => s.eligible_duty_type_ids.includes(dtId))
    );
```

Use `filteredSoldiers` in place of `result.soldiers` wherever the sub-table currently reads it (find the exact variable name in the existing render — it may not be named `result.soldiers` verbatim; match whatever `PotentialResult`'s actual per-node soldier array is called).

- [ ] **Step 8: Run test to verify it passes**

Run: `npx vitest run src/pages/planning/PotentialPage.test.tsx`
Expected: PASS

- [ ] **Step 9: Typecheck and lint**

Run: `npm run typecheck && npm run lint`
Expected: no errors

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/potential.py backend/app/routes/potential.py backend/app/services/tests/test_potential.py frontend/src/api/potential.ts frontend/src/pages/planning/PotentialPage.tsx frontend/src/pages/planning/PotentialPage.test.tsx
git commit -m "feat: add duty-type filter pills to the Potential page"
```

---

### Task 7: Duty type creation — mandatory exemption-type review & confirmation

**Files:**
- Modify: `frontend/src/components/DutyTypeFormModal.tsx`
- Test: `frontend/src/components/DutyTypeFormModal.test.tsx` (existing or new — check first)

**Interfaces:**
- Consumes: `listExemptionTypes()`, `getAllExemptionDutyTypeMaps()`, `setExemptionDutyTypes(id, duty_type_ids)` (all existing, `frontend/src/api/dutyConfig.ts`), `createDutyType(input)` (existing).
- Produces: no new backend endpoint — the modal composes existing per-exemption-type `setExemptionDutyTypes` calls after the new duty type is created.

- [ ] **Step 1: Write the failing test**

Check whether `frontend/src/components/DutyTypeFormModal.test.tsx` exists; if so, read it fully to match its existing mocking conventions, then add:

```tsx
it("requires reviewing exemption types and checking the confirmation box before allowing submit", async () => {
  vi.mocked(dutyConfigApi.listExemptionTypes).mockResolvedValue([
    { id: "et1", name: "רפואי", description: null, active: true },
  ]);
  render(<DutyTypeFormModal onSaved={vi.fn()} onClose={vi.fn()} />);

  const submitBtn = await screen.findByRole("button", { name: /הוסף|שמור/ });
  expect(submitBtn).toBeDisabled();

  fireEvent.click(screen.getByLabelText(/רפואי/));
  fireEvent.click(screen.getByLabelText(/עברתי על הרשימה ומאשר/));

  expect(submitBtn).not.toBeDisabled();
});
```

If no such test file exists yet, check `frontend/src/pages/DutyConfigPage.test.tsx` for how `DutyTypeFormModal` is currently exercised (it may only be tested indirectly through `DutyConfigPage`) — in that case add the test there instead, following its existing render/mock setup exactly.

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/DutyTypeFormModal.test.tsx` (or the file chosen in Step 1)
Expected: FAIL — submit button isn't disabled today (no review-gate exists).

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/components/DutyTypeFormModal.tsx`, add:

```tsx
import { listExemptionTypes, ExemptionType, setExemptionDutyTypes, getAllExemptionDutyTypeMaps } from "../api/dutyConfig";

// new state, alongside existing useState calls:
const [exemptionTypes, setExemptionTypesState] = useState<ExemptionType[]>([]);
const [selectedExemptionIds, setSelectedExemptionIds] = useState<string[]>([]);
const [reviewConfirmed, setReviewConfirmed] = useState(false);

useEffect(() => { void listExemptionTypes().then(setExemptionTypesState); }, []);
```

For the edit case (`initial` is set), pre-populate `selectedExemptionIds` and treat review as already-confirmed (this gate is only for *creating* a new duty type, per the request — editing an existing one keeps today's optional-review behavior via the separate `eligModal`):

```tsx
useEffect(() => {
  if (!initial) return;
  void getAllExemptionDutyTypeMaps().then(map => {
    const mine = Object.entries(map).filter(([, dtIds]) => dtIds.includes(initial.id)).map(([etId]) => etId);
    setSelectedExemptionIds(mine);
    setReviewConfirmed(true);
  });
}, [initial]);
```

Add a new section in the JSX, after the "Eligibility section" block and before the "Hierarchy scope section":

```tsx
{!initial && (
  <div className="border dark:border-gray-600 rounded p-3">
    <p className="text-sm font-medium text-gray-700 dark:text-gray-200 mb-1">אילו סוגי פטור פוטרים מסוג תורנות זה?</p>
    <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">חובה לעבור על הרשימה ולסמן את כל סוגי הפטור הרלוונטיים לפני יצירת סוג התורנות.</p>
    <div className="space-y-1 max-h-40 overflow-y-auto">
      {exemptionTypes.map(et => (
        <label key={et.id} className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={selectedExemptionIds.includes(et.id)}
            onChange={() => setSelectedExemptionIds(prev =>
              prev.includes(et.id) ? prev.filter(x => x !== et.id) : [...prev, et.id]
            )}
          />
          {et.name}
        </label>
      ))}
    </div>
    <label className="flex items-center gap-2 text-xs mt-2 font-medium">
      <input type="checkbox" checked={reviewConfirmed} onChange={e => setReviewConfirmed(e.target.checked)} />
      עברתי על הרשימה ומאשר את הבחירה
    </label>
  </div>
)}
```

Update the submit button to also require `reviewConfirmed` when creating (not editing):

```tsx
<button type="submit" disabled={saving || (!initial && !reviewConfirmed)}
  className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50">
  {initial ? t("duty_config.save", "שמור") : t("duty_config.add")}
</button>
```

In `handleSubmit`, after `dt = await createDutyType(payload);` (the create-only branch), add the mapping calls:

```tsx
dt = await createDutyType(payload);
if (Object.keys(mergedReqs).length > 0) {
  dt = await updateDutyTypeRequirements(dt.id, mergedReqs);
}
if (selectedExemptionIds.length > 0) {
  const currentMap = await getAllExemptionDutyTypeMaps();
  for (const etId of selectedExemptionIds) {
    const existingDutyTypeIds = currentMap[etId] ?? [];
    await setExemptionDutyTypes(etId, [...existingDutyTypeIds, dt.id]);
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/DutyTypeFormModal.test.tsx` (or wherever placed)
Expected: PASS

- [ ] **Step 5: Typecheck and lint**

Run: `npm run typecheck && npm run lint`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DutyTypeFormModal.tsx <test file>
git commit -m "feat: require reviewing exemption-type coverage before creating a duty type"
```

---

### Task 8: Exemption-type ↔ duty-location mapping — backend

**Files:**
- Modify: `backend/app/db/models.py`
- Create: `backend/alembic/versions/<hash>_add_exemption_duty_location_map.py`
- Modify: `backend/app/services/duty_config.py`
- Modify: `backend/app/routes/duty_config.py`
- Modify: `backend/app/services/eligibility.py`
- Test: `backend/app/services/tests/test_duty_config_service.py` (existing — add to it), `backend/app/services/tests/test_eligibility.py` (existing — add to it; if it doesn't exist, check `backend/tests/unit/` for the right eligibility test file first)

**Interfaces:**
- Produces: `ExemptionDutyLocationMap` model (mirrors `ExemptionDutyTypeMap`). Service functions `list_exemption_duty_location_ids(session, *, exemption_type_id) -> list[uuid.UUID]` and `set_exemption_duty_locations(session, *, exemption_type_id, duty_location_ids, actor_id) -> None` in `duty_config.py`. Routes `GET/PUT /duty-config/exemption-types/{id}/duty-locations` and `GET /duty-config/exemption-types/duty-location-map`. `check_soldier_for_assignment` in `eligibility.py` now also excludes a soldier when their active exemption maps to the assignment's `duty_location_id`.

- [ ] **Step 1: Write the failing model/migration test**

```python
# add to backend/app/services/tests/test_duty_config_service.py
def test_set_and_list_exemption_duty_locations(admin_session):
    from app.db.models import DutyLocation, ExemptionType
    from app.services.duty_config import list_exemption_duty_location_ids, set_exemption_duty_locations

    et = ExemptionType(name=f"loc_ex_{uuid.uuid4().hex[:8]}")
    loc1 = DutyLocation(name=f"loc1_{uuid.uuid4().hex[:8]}")
    loc2 = DutyLocation(name=f"loc2_{uuid.uuid4().hex[:8]}")
    admin_session.add_all([et, loc1, loc2])
    admin_session.commit()

    set_exemption_duty_locations(
        admin_session, exemption_type_id=et.id, duty_location_ids=[loc1.id], actor_id=None,
    )
    admin_session.commit()
    assert list_exemption_duty_location_ids(admin_session, exemption_type_id=et.id) == [loc1.id]

    set_exemption_duty_locations(
        admin_session, exemption_type_id=et.id, duty_location_ids=[loc1.id, loc2.id], actor_id=None,
    )
    admin_session.commit()
    assert set(list_exemption_duty_location_ids(admin_session, exemption_type_id=et.id)) == {loc1.id, loc2.id}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest app/services/tests/test_duty_config_service.py -k exemption_duty_locations -q`
Expected: FAIL — `ImportError: cannot import name 'ExemptionDutyLocationMap'` (or similar)

- [ ] **Step 3: Add the model**

In `backend/app/db/models.py`, immediately after the existing `ExemptionDutyTypeMap` class (per Task research, `models.py:247-255`), add:

```python
class ExemptionDutyLocationMap(Base):
    __tablename__ = "exemption_duty_location_map"

    exemption_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exemption_types.id", ondelete="CASCADE"), primary_key=True
    )
    duty_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_locations.id", ondelete="CASCADE"), primary_key=True
    )
```

- [ ] **Step 4: Create the migration**

```bash
cd backend
source .venv/Scripts/activate
alembic revision -m "add exemption_duty_location_map table"
```

Edit the generated file in `backend/alembic/versions/` (find its exact filename from the command's output) — set `down_revision = "dbb2a58b0f63"` (today's confirmed single head; **re-run `alembic heads` immediately before setting this** in case another migration landed on `dev` since this plan was written) and fill in:

```python
def upgrade() -> None:
    op.create_table(
        "exemption_duty_location_map",
        sa.Column("exemption_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("exemption_types.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("duty_location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("duty_locations.id", ondelete="CASCADE"), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("exemption_duty_location_map")
```

No explicit `GRANT` is needed: migration `0001_create_app_and_admin_roles.py` already runs `ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app`, which auto-applies to every table created afterward, including this one. (The one-off `GRANT` in `0051_grant_shift_templates_to_app.py` was a fix for a table that predated that default-privileges setup — not something new tables need.)

Run: `alembic upgrade head`
Expected: migration applies cleanly.

- [ ] **Step 5: Add service functions**

In `backend/app/services/duty_config.py`, find the existing `list_exemption_duty_type_ids`/`set_exemption_duty_types` functions and add mirror functions immediately after them:

```python
def list_exemption_duty_location_ids(session: Session, *, exemption_type_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        session.execute(
            select(ExemptionDutyLocationMap.duty_location_id).where(
                ExemptionDutyLocationMap.exemption_type_id == exemption_type_id
            )
        ).scalars().all()
    )


def set_exemption_duty_locations(
    session: Session, *, exemption_type_id: uuid.UUID, duty_location_ids: list[uuid.UUID],
    actor_id: uuid.UUID | None,
) -> None:
    session.execute(
        delete(ExemptionDutyLocationMap).where(
            ExemptionDutyLocationMap.exemption_type_id == exemption_type_id
        )
    )
    for loc_id in duty_location_ids:
        session.add(ExemptionDutyLocationMap(exemption_type_id=exemption_type_id, duty_location_id=loc_id))
    session.flush()
    write_audit(
        session, actor_id=actor_id, action="exemption_type.set_duty_locations",
        entity_type="exemption_type", entity_id=exemption_type_id,
        after={"duty_location_ids": [str(i) for i in duty_location_ids]},
    )
```

Match the exact `delete`/`write_audit` import and call pattern already used by `set_exemption_duty_types` in this file (read it first — the plan's snippet above assumes `delete` is already imported from `sqlalchemy` and `write_audit` from `app.audit.writer`; adjust imports if the existing function does it differently, e.g. delete-then-insert vs diff-based).

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest app/services/tests/test_duty_config_service.py -q`
Expected: PASS (all tests)

- [ ] **Step 7: Add routes**

In `backend/app/routes/duty_config.py`, immediately after the existing `get_exemption_duty_types`/`put_exemption_duty_types` routes (per Task research, lines ~502-528), add mirror routes:

```python
@router.get("/exemption-types/duty-location-map", response_model=dict[str, list[str]])
def get_all_exemption_duty_location_maps(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> dict[str, list[str]]:
    rows = session.execute(select(ExemptionDutyLocationMap)).scalars().all()
    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(str(row.exemption_type_id), []).append(str(row.duty_location_id))
    return result


@router.get("/exemption-types/{exemption_type_id}/duty-locations", response_model=list[uuid.UUID])
def get_exemption_duty_locations(
    exemption_type_id: uuid.UUID,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[uuid.UUID]:
    return svc.list_exemption_duty_location_ids(session, exemption_type_id=exemption_type_id)


class SetExemptionDutyLocationsBody(BaseModel):
    duty_location_ids: list[uuid.UUID]


@router.put("/exemption-types/{exemption_type_id}/duty-locations", response_model=list[uuid.UUID])
def put_exemption_duty_locations(
    exemption_type_id: uuid.UUID,
    body: SetExemptionDutyLocationsBody,
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> list[uuid.UUID]:
    authorize(session, user, Action.HIERARCHY_MANAGE, target_node=None)  # match whichever Action the existing duty-type mapping PUT route uses — read it first, do not guess
    svc.set_exemption_duty_locations(
        session, exemption_type_id=exemption_type_id,
        duty_location_ids=body.duty_location_ids, actor_id=user.id,
    )
    session.commit()
    return svc.list_exemption_duty_location_ids(session, exemption_type_id=exemption_type_id)
```

**Before finalizing this step**, read the existing `put_exemption_duty_types` route in full to copy its exact authorization check (the plan's `Action.HIERARCHY_MANAGE` placeholder above is a guess — replace it with whatever action/admin-only check that sibling route actually uses).

- [ ] **Step 8: Extend eligibility enforcement**

In `backend/app/services/eligibility.py`, find `check_soldier_for_assignment`'s exemption loop (Step 2 of that function, per Task research: checks `et.is_global` then `assignment.duty_type_id in dtype_ids`). Add a third check:

```python
from app.db.models import ExemptionDutyLocationMap  # add to existing import block

# inside the `for ex in exemptions:` loop, after the duty-type-map check:
        loc_ids = session.execute(
            select(ExemptionDutyLocationMap.duty_location_id).where(
                ExemptionDutyLocationMap.exemption_type_id == ex.exemption_type_id
            )
        ).scalars().all()
        if assignment.duty_location_id in loc_ids:
            return False, "פטור ממיקום תורנות זה"
```

Add a test alongside the existing eligibility tests (find the right file per the header note above):

```python
def test_check_soldier_for_assignment_excludes_by_duty_location(admin_session):
    from datetime import date, timedelta
    from app.db.models import DutyAssignment, DutyLocation, DutyType, ExemptionDutyLocationMap, ExemptionType, SoldierExemption
    from app.services.eligibility import check_soldier_for_assignment
    from tests.helpers import create_soldier

    dt = DutyType(name=f"loc_excl_dt_{uuid.uuid4().hex[:8]}", score_per_day=1)
    loc = DutyLocation(name=f"loc_excl_loc_{uuid.uuid4().hex[:8]}")
    et = ExemptionType(name=f"loc_excl_et_{uuid.uuid4().hex[:8]}")
    admin_session.add_all([dt, loc, et])
    admin_session.flush()
    admin_session.add(ExemptionDutyLocationMap(exemption_type_id=et.id, duty_location_id=loc.id))

    soldier = create_soldier(admin_session, personal_number=f"loc_excl_s_{uuid.uuid4().hex[:8]}")
    admin_session.add(SoldierExemption(
        soldier_id=soldier.id, exemption_type_id=et.id, start_date=date.today() - timedelta(days=1),
    ))
    assignment = DutyAssignment(
        duty_type_id=dt.id, duty_location_id=loc.id, soldier_id=soldier.id,
        start_date=date.today() + timedelta(days=1), end_date=date.today() + timedelta(days=2),
        status="published",
    )
    admin_session.add(assignment)
    admin_session.commit()

    ok, reason = check_soldier_for_assignment(admin_session, soldier.id, assignment.id)
    assert ok is False
    assert reason == "פטור ממיקום תורנות זה"
```

Check `SoldierExemption`'s exact required fields before finalizing (the plan's snippet may be missing a required column — read the model first).

- [ ] **Step 9: Run test to verify it passes**

Run: `pytest app/services/tests/test_duty_config_service.py app/services/tests/test_eligibility.py -q` (adjust paths to match Step 1/8's actual file locations)
Expected: PASS

- [ ] **Step 10: Full backend regression run**

Run: `pytest -q`
Expected: all PASS (no regressions from the new table/import)

- [ ] **Step 11: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/*_add_exemption_duty_location_map.py backend/app/services/duty_config.py backend/app/routes/duty_config.py backend/app/services/eligibility.py backend/app/services/tests/test_duty_config_service.py <eligibility test file>
git commit -m "feat: add exemption-type to duty-location eligibility mapping"
```

**Known limitation (call out, don't silently skip):** this task wires location-based exemption into `check_soldier_for_assignment` (used for manual assignment/swap eligibility checks) but NOT into the CP-SAT algorithm's candidate-pool exclusion (`backend/app/algorithm/`, `backend/app/services/algorithm_bridge.py`) — that integration point was not conclusively located during planning and needs its own follow-up investigation/plan once this ships, so the solver doesn't assign soldiers to duties at locations they're exempted from.

---

### Task 9: Frontend API + query keys for exemption-duty-location mapping

**Files:**
- Modify: `frontend/src/api/dutyConfig.ts`
- Modify: `frontend/src/queryKeys.ts`

**Interfaces:**
- Produces: `getAllExemptionDutyLocationMaps(): Promise<Record<string, string[]>>`, `setExemptionDutyLocations(id: string, duty_location_ids: string[]): Promise<string[]>` in `frontend/src/api/dutyConfig.ts`. New query key `queryKeys.exemptionDutyLocationMap()`.

- [ ] **Step 1: Add the API functions**

In `frontend/src/api/dutyConfig.ts`, immediately after the existing `getAllExemptionDutyTypeMaps`/`setExemptionDutyTypes` functions:

```ts
export async function getAllExemptionDutyLocationMaps(): Promise<Record<string, string[]>> {
  return (await api.get<Record<string, string[]>>("/duty-config/exemption-types/duty-location-map")).data;
}
export async function setExemptionDutyLocations(id: string, duty_location_ids: string[]): Promise<string[]> {
  return (await api.put<string[]>(`/duty-config/exemption-types/${id}/duty-locations`, { duty_location_ids })).data;
}
```

- [ ] **Step 2: Add the query key**

In `frontend/src/queryKeys.ts`, find `exemptionDutyTypeMap` and add a sibling entry immediately after it, matching its exact style (function returning a tuple/array):

```ts
exemptionDutyLocationMap: () => ["exemptionDutyLocationMap"] as const,
```

- [ ] **Step 3: Typecheck**

Run: `npm run typecheck`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/dutyConfig.ts frontend/src/queryKeys.ts
git commit -m "feat: add frontend API client for exemption-duty-location mapping"
```

---

### Task 10: Exemption-type creation modal — mandatory duty-type + duty-location review & confirmation

**Files:**
- Create: `frontend/src/components/ExemptionTypeFormModal.tsx`
- Modify: `frontend/src/pages/DutyConfigPage.tsx`
- Test: `frontend/src/components/ExemptionTypeFormModal.test.tsx` (new)

**Interfaces:**
- Consumes: `createExemptionType`, `listDutyTypes`, `listLocations`, `setExemptionDutyTypes`, `setExemptionDutyLocations` (all `frontend/src/api/dutyConfig.ts`).
- Produces: `<ExemptionTypeFormModal onSaved={(et: ExemptionType) => void} onClose={() => void} />`, replacing the inline `addExType` form in `DutyConfigPage.tsx`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/ExemptionTypeFormModal.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ExemptionTypeFormModal from "./ExemptionTypeFormModal";
import * as dutyConfigApi from "../api/dutyConfig";

vi.mock("../api/dutyConfig");

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(dutyConfigApi.listDutyTypes).mockResolvedValue([
    { id: "dt1", name: "שמירה", score_per_day: "1", description: null, active: true },
  ]);
  vi.mocked(dutyConfigApi.listLocations).mockResolvedValue([
    { id: "loc1", name: "שער צפוני", base: null, active: true },
  ]);
  vi.mocked(dutyConfigApi.createExemptionType).mockResolvedValue({
    id: "et1", name: "רפואי", description: null, active: true,
  });
  vi.mocked(dutyConfigApi.setExemptionDutyTypes).mockResolvedValue([]);
  vi.mocked(dutyConfigApi.setExemptionDutyLocations).mockResolvedValue([]);
});

describe("ExemptionTypeFormModal", () => {
  it("disables submit until both duty-type and duty-location review are confirmed", async () => {
    render(<ExemptionTypeFormModal onSaved={vi.fn()} onClose={vi.fn()} />);
    const nameInput = await screen.findByLabelText(/שם/);
    fireEvent.change(nameInput, { target: { value: "רפואי" } });

    const submitBtn = screen.getByRole("button", { name: /הוסף|שמור/ });
    expect(submitBtn).toBeDisabled();

    fireEvent.click(await screen.findByLabelText(/שמירה/));
    fireEvent.click(screen.getByLabelText(/עברתי על רשימת סוגי התורנות/));
    expect(submitBtn).toBeDisabled(); // location review still missing

    fireEvent.click(screen.getByLabelText(/עברתי על רשימת המיקומים/));
    expect(submitBtn).not.toBeDisabled();
  });

  it("saves duty-type and duty-location mappings after creating the exemption type", async () => {
    const onSaved = vi.fn();
    render(<ExemptionTypeFormModal onSaved={onSaved} onClose={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText(/שם/), { target: { value: "רפואי" } });
    fireEvent.click(await screen.findByLabelText(/שמירה/));
    fireEvent.click(await screen.findByLabelText(/שער צפוני/));
    fireEvent.click(screen.getByLabelText(/עברתי על רשימת סוגי התורנות/));
    fireEvent.click(screen.getByLabelText(/עברתי על רשימת המיקומים/));

    fireEvent.click(screen.getByRole("button", { name: /הוסף|שמור/ }));

    await waitFor(() => {
      expect(dutyConfigApi.setExemptionDutyTypes).toHaveBeenCalledWith("et1", ["dt1"]);
      expect(dutyConfigApi.setExemptionDutyLocations).toHaveBeenCalledWith("et1", ["loc1"]);
      expect(onSaved).toHaveBeenCalled();
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/components/ExemptionTypeFormModal.test.tsx`
Expected: FAIL — module doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

```tsx
// frontend/src/components/ExemptionTypeFormModal.tsx
import { FormEvent, useEffect, useState } from "react";
import {
  createExemptionType, ExemptionType, DutyType, DutyLocation,
  listDutyTypes, listLocations, setExemptionDutyTypes, setExemptionDutyLocations,
} from "../api/dutyConfig";

interface Props {
  onSaved: (et: ExemptionType) => void;
  onClose: () => void;
}

export default function ExemptionTypeFormModal({ onSaved, onClose }: Props) {
  const [name, setName] = useState("");
  const [isGlobal, setIsGlobal] = useState(false);
  const [isMedical, setIsMedical] = useState(false);
  const [isCommanderExemption, setIsCommanderExemption] = useState(false);
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);
  const [locations, setLocations] = useState<DutyLocation[]>([]);
  const [selectedDutyTypeIds, setSelectedDutyTypeIds] = useState<string[]>([]);
  const [selectedLocationIds, setSelectedLocationIds] = useState<string[]>([]);
  const [dutyTypesReviewed, setDutyTypesReviewed] = useState(false);
  const [locationsReviewed, setLocationsReviewed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void listDutyTypes().then(setDutyTypes);
    void listLocations().then(setLocations);
  }, []);

  const canSubmit = name.trim().length > 0 && dutyTypesReviewed && locationsReviewed && !saving;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true);
    setError(null);
    try {
      const et = await createExemptionType({
        name, is_global: isGlobal, is_medical: isMedical, is_commander_exemption: isCommanderExemption,
      });
      if (selectedDutyTypeIds.length > 0) {
        await setExemptionDutyTypes(et.id, selectedDutyTypeIds);
      }
      if (selectedLocationIds.length > 0) {
        await setExemptionDutyLocations(et.id, selectedLocationIds);
      }
      onSaved(et);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4" onClick={onClose}>
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 w-full max-w-lg max-h-[90dvh] overflow-y-auto" dir="rtl" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-semibold text-base">הוספת סוג פטור</h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="et-modal-name" className="block text-sm font-medium mb-1">שם *</label>
            <input id="et-modal-name" required autoFocus value={name} onChange={e => setName(e.target.value)}
              className="block w-full border border-gray-300 dark:border-gray-600 rounded-lg p-2 text-sm dark:bg-gray-700 dark:text-gray-100" />
          </div>

          <div className="flex gap-4">
            <label className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={isGlobal} onChange={e => setIsGlobal(e.target.checked)} /> גורף
            </label>
            <label className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={isMedical} onChange={e => setIsMedical(e.target.checked)} /> 🏥 רפואי
            </label>
            <label className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={isCommanderExemption} onChange={e => setIsCommanderExemption(e.target.checked)} /> 🎖️ פטור פיקודי
            </label>
          </div>

          <div className="border dark:border-gray-600 rounded p-3">
            <p className="text-sm font-medium mb-1">מאילו סוגי תורנות פוטר סוג פטור זה?</p>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">חובה לעבור על הרשימה המלאה לפני יצירת סוג הפטור.</p>
            <div className="space-y-1 max-h-32 overflow-y-auto">
              {dutyTypes.map(dt => (
                <label key={dt.id} className="flex items-center gap-2 text-xs">
                  <input type="checkbox" checked={selectedDutyTypeIds.includes(dt.id)}
                    onChange={() => setSelectedDutyTypeIds(prev =>
                      prev.includes(dt.id) ? prev.filter(x => x !== dt.id) : [...prev, dt.id]
                    )} />
                  {dt.name}
                </label>
              ))}
            </div>
            <label className="flex items-center gap-2 text-xs mt-2 font-medium">
              <input type="checkbox" checked={dutyTypesReviewed} onChange={e => setDutyTypesReviewed(e.target.checked)} />
              עברתי על רשימת סוגי התורנות ומאשר את הבחירה
            </label>
          </div>

          <div className="border dark:border-gray-600 rounded p-3">
            <p className="text-sm font-medium mb-1">מאילו מיקומי תורנות פוטר סוג פטור זה?</p>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">חובה לעבור על הרשימה המלאה לפני יצירת סוג הפטור.</p>
            <div className="space-y-1 max-h-32 overflow-y-auto">
              {locations.map(loc => (
                <label key={loc.id} className="flex items-center gap-2 text-xs">
                  <input type="checkbox" checked={selectedLocationIds.includes(loc.id)}
                    onChange={() => setSelectedLocationIds(prev =>
                      prev.includes(loc.id) ? prev.filter(x => x !== loc.id) : [...prev, loc.id]
                    )} />
                  {loc.name}
                </label>
              ))}
            </div>
            <label className="flex items-center gap-2 text-xs mt-2 font-medium">
              <input type="checkbox" checked={locationsReviewed} onChange={e => setLocationsReviewed(e.target.checked)} />
              עברתי על רשימת המיקומים ומאשר את הבחירה
            </label>
          </div>

          {error && <p className="text-red-500 text-xs">{error}</p>}

          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-3 py-1 text-sm border dark:border-gray-600 dark:text-gray-300 rounded">ביטול</button>
            <button type="submit" disabled={!canSubmit} className="px-3 py-1 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50">
              הוסף
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/components/ExemptionTypeFormModal.test.tsx`
Expected: PASS (2 tests)

- [ ] **Step 5: Wire into DutyConfigPage.tsx, replacing the inline form**

In `frontend/src/pages/DutyConfigPage.tsx`, remove the inline `<form onSubmit={addExType} data-testid="exemption-type-form">...</form>` block (lines ~397-412 per Task research) and the now-unused `exName`/`exGlobal`/`exMedical`/`exCommanderExemption` state + `addExType` function. Add modal state instead, following the exact pattern already used for `dtModal`/`DutyTypeFormModal` in this same file:

```tsx
import ExemptionTypeFormModal from "../components/ExemptionTypeFormModal";

// alongside the existing `const [dtModal, setDtModal] = useState<{ initial?: DutyType } | null>(null);`
const [etModalOpen, setEtModalOpen] = useState(false);
```

Replace the removed form with a button that opens the modal:

```tsx
<button
  type="button"
  onClick={() => setEtModalOpen(true)}
  className="bg-indigo-600 text-white px-3 py-1 rounded mb-2"
  data-testid="et-open-modal"
>
  {t("duty_config.add")} {t("duty_config.exemption_types")}
</button>
```

Add the modal render, mirroring the existing `{dtModal && <DutyTypeFormModal .../>}` block:

```tsx
{etModalOpen && (
  <ExemptionTypeFormModal
    onSaved={async () => { setEtModalOpen(false); await refresh(); }}
    onClose={() => setEtModalOpen(false)}
  />
)}
```

Check `refresh()`'s existing definition in this file to confirm it already re-fetches `exTypes` (it should, since it's used by the current inline form's `addExType`) — no change needed there if so.

- [ ] **Step 6: Update or remove now-stale existing tests**

Search for tests referencing the removed inline form: `grep -rn "exemption-type-form\|et-name\|et-global\|et-medical\|et-commander-exemption\|et-submit" frontend/src`. Any test using those `data-testid`s (likely in `frontend/src/pages/DutyConfigPage.test.tsx`) needs updating to instead: click `et-open-modal`, interact with the new modal's fields (by label, matching `ExemptionTypeFormModal.test.tsx`'s query style), tick both review checkboxes, then submit. Update each such test in place — do not delete test coverage, adapt it to the new flow.

- [ ] **Step 7: Run full frontend test suite**

Run: `npm test`
Expected: all PASS

- [ ] **Step 8: Typecheck and lint**

Run: `npm run typecheck && npm run lint`
Expected: no errors

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/ExemptionTypeFormModal.tsx frontend/src/components/ExemptionTypeFormModal.test.tsx frontend/src/pages/DutyConfigPage.tsx frontend/src/pages/DutyConfigPage.test.tsx
git commit -m "feat: require reviewing duty-type and duty-location coverage before creating an exemption type"
```

---

### Task 11: Full-suite regression check

**Files:** none (verification only)

- [ ] **Step 1: Run full backend suite**

```bash
cd backend
source .venv/Scripts/activate
export DATABASE_URL="postgresql+psycopg://app:app_pw@localhost:5432/justice"
pytest -q
```

Expected: all PASS, 0 failures.

- [ ] **Step 2: Run full frontend suite**

```bash
cd frontend
npm test
npm run typecheck
npm run lint
```

Expected: all PASS, 0 type errors, 0 lint warnings.

- [ ] **Step 3: Manual smoke test in browser**

Start the dev stack for this worktree on non-conflicting ports if the main checkout's `dev.ps1` is already running (check `dev.ps1` for a way to override `8000`/`5173`, or stop the other instance first — coordinate with the user before touching a stack they may be actively using). Verify:
1. `/admin/settings` shows the five new settings (forced-callup toggle, commander-exemption min level, two medical-doc min-level settings) with working selects/checkbox.
2. Toggling `forced_callup.enabled` off hides "הקפצה פיקודית" from the nav and 403's `/api/hakpaza/...`.
3. Opening a medical exemption's attached file (as an appropriately-privileged commander) shows the new preview modal with a working download link, for both a PDF and an image test file.
4. The Potential page shows duty-type pills; selecting two pills narrows the soldier list to only those eligible for both.
5. Creating a new duty type forces ticking at least reviewing the exemption-type list + the confirm checkbox before "הוסף" is enabled.
6. Creating a new exemption type forces reviewing both the duty-type and duty-location lists + both confirm checkboxes before "הוסף" is enabled.

- [ ] **Step 4: Report to the user**

Summarize what was built, list the known limitation from Task 8 (CP-SAT solver not yet wired to location-based exemptions), and hand off for review before merging.
