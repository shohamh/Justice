# Ineligible Soldiers Ranges View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a scoped table of soldiers without a valid range qualification to the existing מטווחים page, show its count on the existing מטווחים navigation item, and add a compact urgent-warning panel to the commander dashboard.

**Architecture:** Add one backend read service that derives visible soldiers from explicit commander or duty-manager roots, evaluates current qualifications and future weapon-duty/range-assignment flags, and returns a shared DTO. The מטווחים page renders the DTO grouped by hierarchy; the commander dashboard renders a compact projection. The existing מטווחים nav item remains the only navigation entry and receives the red count badge.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.0, pytest, React 18, TypeScript, TanStack Query, Vitest, existing `DataTable`/`PlanningTable` components.

## Global Constraints

- Do not add a separate `חוסר כשירות` navigation item; the existing `nav-ranges` item is the only navigation entry.
- The existing מטווחים schedule management table and actions must continue to work unchanged.
- All visibility filtering is enforced by the backend; frontend filtering is presentation only.
- Commander scope is the recursive subtree of nodes commanded by the user; duty-manager scope is the recursive subtree of every `DutyManagerScope` root; admins see all nodes.
- Count each soldier once even when scope roots overlap.
- “Today onward” uses the server’s `date.today()` for backend comparisons and the client’s current date only for display/query state.
- A soldier is in the base table when no `SoldierRangeQualification.valid_until` covers today.
- An urgent warning requires a future published weapon-required duty and no future planned matching range assignment for that soldier.
- Use existing range/weapon eligibility semantics and range-type labels; do not create a second qualification algorithm.
- Every production behavior change starts with a failing focused test and ends with focused plus broader regression verification.

---

### Task 1: Backend scoped read model for unqualified soldiers

**Files:**
- Create: `backend/app/services/ineligible_soldiers.py`
- Test: `backend/app/services/tests/test_ineligible_soldiers.py`
- Inspect and reuse: `backend/app/db/models.py` (`Soldier`, `HierarchyNode`, `SoldierRangeQualification`, `DutyAssignment`, `DutyType`, `RangeEvent`, `RangeAssignment`, `RangeType`)
- Inspect and reuse: `backend/app/auth/authz.py` (`scope_root_ids`, `is_commander`, `is_duty_manager`)

**Interfaces:**
- Produces `IneligibleSoldierScope` and `IneligibleSoldierRecord` dataclasses (or equivalent typed service DTOs) with soldier identity, hierarchy identity/path, valid qualification summaries, `has_upcoming_weapon_duty`, `has_upcoming_matching_range`, and the relevant upcoming duty/range display fields.
- Produces `list_ineligible_soldiers(session, *, roots: set[uuid.UUID] | None, as_of: date) -> list[IneligibleSoldierRecord]`; `roots=None` means all hierarchy nodes for admin use.

- [ ] **Step 1: Write failing service tests for current qualification and deduplication**

Create fixtures for a root, descendant, sibling, two scoped roots, and soldiers with valid, expired, and missing qualifications. Assert that only soldiers with no qualification valid on `as_of` are returned and overlapping roots do not duplicate a soldier.

```python
def test_lists_only_soldiers_without_a_qualification_valid_today(app_session: Session) -> None:
    result = list_ineligible_soldiers(app_session, roots={root.id}, as_of=date(2026, 8, 9))
    assert {row.soldier_id for row in result} == {expired.id, missing.id}

def test_overlapping_roots_return_each_soldier_once(app_session: Session) -> None:
    result = list_ineligible_soldiers(app_session, roots={root.id, child.id}, as_of=date(2026, 8, 9))
    assert len([row for row in result if row.soldier_id == expired.id]) == 1
```

- [ ] **Step 2: Run the focused tests and verify the expected failure**

Run from `backend/`: `pytest app/services/tests/test_ineligible_soldiers.py -q`.

Expected: FAIL because `app.services.ineligible_soldiers` and `list_ineligible_soldiers` do not exist.

- [ ] **Step 3: Write failing tests for future urgency flags**

Add one published future weapon-required assignment, one non-weapon assignment, one cancelled assignment, a future matching planned range assignment, and a future non-matching range assignment. Assert that only the published weapon duty sets `has_upcoming_weapon_duty`, and only the matching planned range sets `has_upcoming_matching_range`.

```python
def test_future_weapon_duty_without_matching_range_is_urgent(app_session: Session) -> None:
    row = next(r for r in list_ineligible_soldiers(app_session, roots={root.id}, as_of=TODAY) if r.soldier_id == soldier.id)
    assert row.has_upcoming_weapon_duty is True
    assert row.has_upcoming_matching_range is False
```

- [ ] **Step 4: Implement the minimal service query and DTOs**

Use `HierarchyNode.path_ids` to filter descendants, load soldiers once, aggregate qualifications by soldier, and query future assignments/range assignments in batches. Match a future range assignment by soldier, `RangeEvent.status == "planned"`, `RangeEvent.date >= as_of`, non-draft assignment, and `RangeEvent.range_type == DutyType.required_range_type` for at least one future weapon duty. Preserve deterministic ordering by hierarchy path then soldier name.

- [ ] **Step 5: Run the focused tests and verify they pass**

Run: `pytest app/services/tests/test_ineligible_soldiers.py -q`.

Expected: PASS with no unrelated warnings.

- [ ] **Step 6: Commit the service and tests**

```bash
git add backend/app/services/ineligible_soldiers.py backend/app/services/tests/test_ineligible_soldiers.py
git commit -m "feat: add scoped unqualified-soldier read model"
```

---

### Task 2: Backend API and authorization boundaries

**Files:**
- Create or modify: `backend/app/routes/range_qualification_visibility.py`
- Modify: `backend/app/main.py` to register the router if a new router is used
- Test: `backend/tests/integration/test_ineligible_soldiers_api.py`

**Interfaces:**
- Produces `GET /ranges/ineligible-soldiers?audience=planning|commander` returning `{count, nodes, soldiers}` (or an equivalent stable envelope) with hierarchy metadata and per-soldier urgency fields.
- Produces `GET /ranges/ineligible-soldiers/count` for the existing מטווחים nav badge, deriving planning scope from the authenticated user.
- `audience=planning` permits admin/duty-manager users; `audience=commander` permits admin/commander users. Non-authorized users receive 403.

- [ ] **Step 1: Write failing integration tests for both audience scopes and count**

Create commander roots with descendants, duty-manager scopes on separate nodes, an out-of-scope soldier, and an admin. Assert commander responses exclude duty-manager-only nodes, planning responses include all duty-manager scopes, admins see all, and the count equals the unique soldiers in the corresponding list.

- [ ] **Step 2: Run the API tests and verify the expected failure**

Run from `backend/`: `pytest tests/integration/test_ineligible_soldiers_api.py -q`.

Expected: FAIL with a missing route/404 or missing response model.

- [ ] **Step 3: Implement response models, scope resolution, and routes**

Resolve roots server-side: commander roots from `HierarchyNode.commander_id == user.id`; planning roots from `DutyManagerScope`; admin uses `roots=None`. Pass the explicit roots and `date.today()` to the service. Return only DTO fields needed by the two UIs and ensure the count is derived from the same filtered records/query.

- [ ] **Step 4: Run the API tests and verify they pass**

Run: `pytest tests/integration/test_ineligible_soldiers_api.py -q`.

Expected: PASS, including 403 cases and overlap deduplication.

- [ ] **Step 5: Commit the API**

```bash
git add backend/app/routes/range_qualification_visibility.py backend/app/main.py backend/tests/integration/test_ineligible_soldiers_api.py
git commit -m "feat: expose scoped unqualified-soldier endpoints"
```

---

### Task 3: Frontend API client, query keys, and translations

**Files:**
- Create or modify: `frontend/src/api/ineligibleSoldiers.ts`
- Modify: `frontend/src/queryKeys.ts`
- Modify: `frontend/src/i18n/he.json`
- Test: `frontend/src/api/ineligibleSoldiers.test.ts`

**Interfaces:**
- Produces `getIneligibleSoldiers(audience: "planning" | "commander")` and `getIneligibleSoldierCount()` typed against the backend envelope.
- Produces query keys `ineligibleSoldiers(audience)` and `ineligibleSoldierCount()`.
- Produces translation keys for page headings, columns, empty/loading/error states, qualification labels, regular urgency, and urgent weapon-duty-without-range warning.

- [ ] **Step 1: Write failing client contract tests**

Mock the existing `api` client and assert the two functions call the exact endpoints/params and return typed envelopes. Add an i18n test asserting all new Hebrew keys resolve.

- [ ] **Step 2: Run the focused frontend tests and verify the expected failure**

Run from `frontend/`: `npm test -- src/api/ineligibleSoldiers.test.ts`.

Expected: FAIL because the module, functions, and translation keys do not exist.

- [ ] **Step 3: Implement the client, query keys, and translations**

Keep the API response types shared by the ranges table and commander panel. Use existing range-type labels where possible and add only feature-specific copy to `he.json`.

- [ ] **Step 4: Run focused tests and typecheck**

Run: `npm test -- src/api/ineligibleSoldiers.test.ts` and `npm run typecheck`.

Expected: PASS and no TypeScript errors.

- [ ] **Step 5: Commit the frontend contract**

```bash
git add frontend/src/api/ineligibleSoldiers.ts frontend/src/api/ineligibleSoldiers.test.ts frontend/src/queryKeys.ts frontend/src/i18n/he.json
git commit -m "feat: add unqualified-soldier frontend data contract"
```

---

### Task 4: Ineligible-soldier hierarchy table on מטווחים page

**Files:**
- Create: `frontend/src/components/ranges/IneligibleSoldiersTable.tsx`
- Test: `frontend/src/components/ranges/IneligibleSoldiersTable.test.tsx`
- Modify: `frontend/src/pages/RangesPage.tsx`
- Modify: `frontend/src/queryKeys.ts` only if a page-specific key is needed beyond Task 3

**Interfaces:**
- `IneligibleSoldiersTable` consumes the planning audience response and renders hierarchy rows with expandable soldier rows.
- `RangesPage` preserves its existing event table and adds an internal tab/section selected by `?tab=ineligible`; the default event view remains unchanged.

- [ ] **Step 1: Write failing component tests**

Assert that the component renders hierarchy counts, expands a node to show a `SoldierLink`, shows valid qualification expiry details, renders a normal warning for an unqualified soldier, and renders the stronger urgent style/text when both urgency flags require it. Assert an empty state for no soldiers.

- [ ] **Step 2: Run the focused component test and verify the expected failure**

Run: `npm test -- src/components/ranges/IneligibleSoldiersTable.test.tsx`.

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement the hierarchy grouping and table**

Use `NodeDTO.path_ids`/hierarchy metadata to order and indent node rows, aggregate descendant counts, and keep soldiers unique. Use explicit expand buttons/row controls rather than making an entire card ambiguously clickable. Keep urgent styling red and regular unqualified styling visually distinct but accessible in dark mode.

- [ ] **Step 4: Integrate the internal tab/section into `RangesPage`**

Read `tab=ineligible` with `useSearchParams`, fetch planning data only when that view is selected (the badge uses the count endpoint independently), and keep existing range-event query/mutation behavior intact. Add a clear link/tab to switch between the schedule and qualification views inside the page.

- [ ] **Step 5: Run focused tests, lint, and typecheck**

Run: `npm test -- src/components/ranges/IneligibleSoldiersTable.test.tsx src/pages/RangesPage.test.tsx`, `npm run lint`, and `npm run typecheck`.

Expected: PASS with zero lint warnings and no type errors.

- [ ] **Step 6: Commit the ranges-page UI**

```bash
git add frontend/src/components/ranges/IneligibleSoldiersTable.tsx frontend/src/components/ranges/IneligibleSoldiersTable.test.tsx frontend/src/pages/RangesPage.tsx
git commit -m "feat: show unqualified soldiers on ranges page"
```

---

### Task 5: Badge on the existing מטווחים navigation item

**Files:**
- Modify: `frontend/src/components/UnifiedNav.tsx`
- Test: `frontend/src/components/UnifiedNav.test.tsx`

**Interfaces:**
- Consumes `getIneligibleSoldierCount()` and `queryKeys.ineligibleSoldierCount()`.
- Produces a red badge on the existing `nav-ranges` planning-sheet item only; no new `NavTab` or `NavSheetItem` is created.

- [ ] **Step 1: Write failing navigation tests**

Assert that a duty manager sees `nav-ranges` with a red count badge, the link remains `/ranges` (or `/ranges?tab=ineligible` if that is the established selected-view behavior), and no element with `nav-weapon-ineligible` exists. Assert that zero count hides the badge and that the existing `מטווחים` feature gate still controls visibility.

- [ ] **Step 2: Run the focused test and verify the expected failure**

Run: `npm test -- src/components/UnifiedNav.test.tsx`.

Expected: FAIL because `nav-ranges` has no ineligible count query/badge.

- [ ] **Step 3: Implement the badge with scoped loading behavior**

Fetch the count only when the user can access planning and the מטווחים feature is enabled. Keep badge failure fail-silent as with other nav badges, and invalidate/refetch on pathname changes using the existing nav pattern.

- [ ] **Step 4: Run the navigation tests**

Run: `npm test -- src/components/UnifiedNav.test.tsx`.

Expected: PASS, including no-new-nav-item assertions.

- [ ] **Step 5: Commit the navigation change**

```bash
git add frontend/src/components/UnifiedNav.tsx frontend/src/components/UnifiedNav.test.tsx
git commit -m "feat: add unqualified-soldier count to ranges nav"
```

---

### Task 6: Compact commander-dashboard panel

**Files:**
- Create: `frontend/src/components/dashboard/IneligibleSoldiersPanel.tsx`
- Test: `frontend/src/components/dashboard/IneligibleSoldiersPanel.test.tsx`
- Modify: `frontend/src/pages/CommandDashboardPage.tsx`

**Interfaces:**
- `IneligibleSoldiersPanel` consumes the commander audience response and renders a compact list/table with normal and urgent warning states.
- `CommandDashboardPage` loads the commander audience only for users who can access the commander dashboard and adds a `panel-ineligible-soldiers` panel.

- [ ] **Step 1: Write failing panel tests**

Assert that an ordinary unqualified soldier renders a normal warning, a soldier with a future weapon-required duty and no matching range renders the stronger red warning, qualified/irrelevant records are not rendered, and the empty/error states are clear.

- [ ] **Step 2: Run the focused test and verify the expected failure**

Run: `npm test -- src/components/dashboard/IneligibleSoldiersPanel.test.tsx`.

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement the compact panel**

Show soldier name, hierarchy, qualification summary, and concise upcoming-duty/range context. Use `SoldierLink` and explicit warning text; do not add an action that changes assignments or qualification state.

- [ ] **Step 4: Integrate it into the dashboard query/panel list**

Use a dedicated query key and include the panel alongside existing dashboard panels. It must not block unrelated dashboard queries if its request fails.

- [ ] **Step 5: Run focused tests, lint, and typecheck**

Run: `npm test -- src/components/dashboard/IneligibleSoldiersPanel.test.tsx src/pages/CommandDashboardPage.test.tsx`, `npm run lint`, and `npm run typecheck`.

Expected: PASS with zero lint warnings and no type errors.

- [ ] **Step 6: Commit the commander panel**

```bash
git add frontend/src/components/dashboard/IneligibleSoldiersPanel.tsx frontend/src/components/dashboard/IneligibleSoldiersPanel.test.tsx frontend/src/pages/CommandDashboardPage.tsx
git commit -m "feat: add commander unqualified-soldier panel"
```

---

### Task 7: Regression verification and release handoff

**Files:** none unless a regression is found in the feature files above.

- [ ] **Step 1: Run focused backend suites**

From `backend/`, run:

```bash
pytest app/services/tests/test_ineligible_soldiers.py tests/integration/test_ineligible_soldiers_api.py -q
```

- [ ] **Step 2: Run focused frontend suites**

From `frontend/`, run:

```bash
npm test -- src/api/ineligibleSoldiers.test.ts src/components/ranges/IneligibleSoldiersTable.test.tsx src/components/dashboard/IneligibleSoldiersPanel.test.tsx src/components/UnifiedNav.test.tsx
```

- [ ] **Step 3: Run the broader frontend checks**

From `frontend/`, run `npm test`, `npm run lint`, and `npm run typecheck`. Classify unrelated pre-existing failures separately; do not hide feature regressions behind broad-suite noise.

- [ ] **Step 4: Run the broader backend fast suite**

From `backend/`, run `pytest -q` with the repository’s normal writable temp configuration. If shared database or Docker infrastructure fails, report that separately from test regressions.

- [ ] **Step 5: Inspect the final diff and verify scope**

Run `git diff dev...HEAD --stat`, `git diff --check`, and `git status --short`. Confirm there is no `nav-weapon-ineligible` item, the existing `nav-ranges` item owns the badge, and unrelated user work remains untouched.

- [ ] **Step 6: Commit any verification fixes and hand off for merge to dev**

Use the project’s `merge-worktree-to-dev` skill only after all checks are green and the user authorizes integration.

