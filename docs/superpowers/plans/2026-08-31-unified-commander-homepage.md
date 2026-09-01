# Unified Commander Homepage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Combine the regular soldier homepage and commander dashboard into one role-aware homepage where commanders and duty managers see their own information normally and command-scope information prominently, while regular soldiers never receive commander-only content.

**Architecture:** Keep `/` as the single dashboard route and make `HomePage` the composition root. Reuse existing widgets once per dashboard, with each widget receiving an explicit scope (`personal` or `command`) and visual emphasis (`normal` or `highlighted`). A shared role predicate will treat admins, commanders, active commander deputies, and duty managers as management users; backend authorization remains authoritative for command-scope data.

**Tech Stack:** React, TypeScript, TanStack Query, React Router, Tailwind CSS, FastAPI, SQLAlchemy, pytest, Vitest.

**Spec:** This plan is the implementation specification for the requested unified homepage and role-aware command view.

## Global Constraints

- Regular soldiers must not fetch or render commander-only data or controls.
- Commanders and duty managers use the same management-dashboard behavior; their command data remains scoped to their authorized hierarchy.
- Personal information is shown in the normal visual treatment; command-scope information is visually highlighted and clearly labeled as unit/subtree information.
- Existing backend authorization must remain enforced; frontend visibility is not a security boundary.
- Do not reintroduce the removed three-card summary row.
- Reuse existing widgets and API contracts where possible; do not maintain two independent dashboard implementations.
- Preserve unrelated working-tree changes.

---

## Domain model and UX decisions

Use these canonical concepts throughout the implementation:

- **Personal scope:** the logged-in soldier's duties, ranges, qualification alerts, swaps, history, score, and personal notifications.
- **Command scope:** soldiers and assignments in the manager's authorized subtree(s), including command alerts, approvals, ineligible soldiers, upcoming coverage, and potential.
- **Management user:** `admin || is_commander || is_duty_manager`. A duty manager is not a weaker commander for dashboard composition; both receive the command section. The backend may still apply its own scope and action rules.
- **Highlighted command content:** a distinct tinted/bordered section with a heading such as “ניהול היחידה” and visible scope text. It should be prominent, not merely moved above personal content.
- **Normal personal content:** the existing personal widgets retain the normal card styling and a heading such as “המידע שלי” only where needed for orientation.

The unified page should have this order:

1. Welcome and personal alerts/deputy banner.
2. For management users, the single Homepage calendar shows their authorized subtree duties, including their own duties, with their own duties highlighted. For regular soldiers, the same Homepage calendar shows only their own duties.
3. The remaining highlighted command content for management users is approvals, command alerts, ineligible soldiers, upcoming command snapshot, and command potential; the separate unit duty board continues to show all unit duties.
4. Normal personal content includes upcoming personal duties/ranges, swaps, duty history, reserve totals, breakdown, and manual score adjustments.

Where a widget can display both scopes, render it once with an explicit effective scope rather than rendering duplicate personal and command copies. The Homepage calendar is one calendar: regular soldiers see their own duties, while management users see the duties of everyone in their authorized subtree, including themselves. The separate “unit duty board” page remains the all-unit operational calendar and is not replaced by the Homepage calendar.

## File map

- Modify `frontend/src/pages/HomePage.tsx`: become the unified composition root and conditionally load command queries only for management users.
- Retire or reduce `frontend/src/pages/CommandDashboardPage.tsx`: remove duplicate orchestration after the unified page is live; keep a compatibility redirect if existing bookmarks/navigation still point to `/command-dashboard`.
- Modify `frontend/src/components/Layout.tsx` and route/navigation consumers: make the homepage the canonical dashboard destination and remove the duplicate dashboard entry where appropriate.
- Create `frontend/src/auth/dashboardRoles.ts`: centralize `isManagementUser` and related role predicates, including duty managers and admins.
- Create `frontend/src/components/dashboard/CommandDashboardSection.tsx`: highlighted command-scope layout and shared section heading/scope treatment.
- Modify `frontend/src/components/dashboard/PendingApprovalsWidget.tsx`, `AlertsPanel.tsx`, `UpcomingSnapshot.tsx`, `IneligibleSoldiersPanel.tsx`, `DutyPotentialPanel.tsx`, and `UnitCalendar.tsx` only where explicit scope labels or visual variants are needed.
- Modify `frontend/src/api/commanderDashboard.ts`: remove the unused summary-card contract after migration and retain only command-scope APIs that the unified page actually uses.
- Modify `frontend/src/queryKeys.ts`: keep command query keys stable; remove only keys made unreachable after migration.
- Modify `frontend/src/pages/HomePage.test.tsx`, `frontend/src/pages/CommandDashboardPage.test.tsx`, and component tests: cover all role/scope/visibility cases.
- Modify `backend/app/routes/commander_dashboard.py` only if the unified page exposes an existing authorization inconsistency, especially admin access or duty-manager scope; do not weaken authorization to make the UI work.
- Modify `backend/tests/routes/tests/test_commander_dashboard.py` (actual repository path: `backend/app/routes/tests/test_commander_dashboard.py`) for command endpoint authorization and scope regression coverage.
- Add this plan's decision to `CONTEXT.md` only if the project wants “personal scope”, “command scope”, and “management user” as permanent domain terms; otherwise keep them as UI architecture terms.

## Task 1: Establish one shared management-role predicate

**Files:**
- Create: `frontend/src/auth/dashboardRoles.ts`
- Modify: `frontend/src/pages/HomePage.tsx`
- Test: `frontend/src/auth/dashboardRoles.test.ts`

**Interfaces:**
- Produces `isManagementUser(user: PermissionUser | null): boolean`.
- Produces `isCommandScopeAvailable(user: PermissionUser | null): boolean`; initially the same role predicate, kept separate so backend scope availability can be represented without sprinkling role checks through JSX.

- [ ] **Step 1: Write failing role tests**

```ts
it.each([
  [{ role: "admin", is_commander: false, is_duty_manager: false }, true],
  [{ role: "commander", is_commander: true, is_duty_manager: false }, true],
  [{ role: "duty_manager", is_commander: false, is_duty_manager: true }, true],
  [{ role: "soldier", is_commander: false, is_duty_manager: false }, false],
])("classifies dashboard user", (user, expected) => {
  expect(isManagementUser(user as PermissionUser)).toBe(expected);
});
```

- [ ] **Step 2: Run the focused test and verify it fails because the shared module is absent**

Run: `npm test -- --run src/auth/dashboardRoles.test.ts`

- [ ] **Step 3: Implement the predicate by delegating to the existing `canApprove` semantics**

```ts
export function isManagementUser(user: PermissionUser | null): boolean {
  return canApprove(user);
}

export function isCommandScopeAvailable(user: PermissionUser | null): boolean {
  return isManagementUser(user);
}
```

- [ ] **Step 4: Replace ad-hoc `canApprove` dashboard composition checks with the shared predicate and rerun the test**

Run: `npm test -- --run src/auth/dashboardRoles.test.ts`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/auth/dashboardRoles.ts frontend/src/auth/dashboardRoles.test.ts frontend/src/pages/HomePage.tsx
git commit -m "refactor: centralize dashboard management roles"
```

## Task 2: Extract the highlighted command-scope container

**Files:**
- Create: `frontend/src/components/dashboard/CommandDashboardSection.tsx`
- Modify: `frontend/src/pages/HomePage.tsx`
- Test: `frontend/src/components/dashboard/CommandDashboardSection.test.tsx`

**Interfaces:**
- Consumes `children`, optional `title`, optional `scopeLabel`, and an optional `data-testid`.
- Produces one highlighted RTL section with accessible heading and a consistent visual treatment.

- [ ] **Step 1: Write the failing rendering test**

```tsx
it("labels command content and applies highlighted treatment", () => {
  render(<CommandDashboardSection><span>command content</span></CommandDashboardSection>);
  expect(screen.getByRole("region", { name: "ניהול היחידה" })).toBeInTheDocument();
  expect(screen.getByText("command content")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `npm test -- --run src/components/dashboard/CommandDashboardSection.test.tsx`

- [ ] **Step 3: Implement the container**

Use a wrapper such as `border-2 border-indigo-400 bg-indigo-50/50 dark:border-indigo-500 dark:bg-indigo-950/30`, `dir="rtl"`, and a heading. Do not encode authorization in this component; it only presents already-authorized children.

- [ ] **Step 4: Add a personal section wrapper only if the resulting page needs orientation**

Keep personal widgets’ existing styling. Add a plain heading, not a second highlighted card, so the visual hierarchy stays intentional.

- [ ] **Step 5: Run the focused component test**

Run: `npm test -- --run src/components/dashboard/CommandDashboardSection.test.tsx`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/dashboard/CommandDashboardSection.tsx frontend/src/components/dashboard/CommandDashboardSection.test.tsx frontend/src/pages/HomePage.tsx
git commit -m "feat: add highlighted command dashboard section"
```

## Task 3: Move command-scope queries into the unified homepage

**Files:**
- Modify: `frontend/src/pages/HomePage.tsx`
- Modify: `frontend/src/api/commanderDashboard.ts`
- Modify: `frontend/src/queryKeys.ts`
- Test: `frontend/src/pages/HomePage.test.tsx`

**Interfaces:**
- Management-only queries use the existing command-dashboard API functions and query keys.
- Regular soldiers must have `enabled: false` for all command-scope queries; no command API function may be called for them.

- [ ] **Step 1: Add role-specific query tests**

Mock command-dashboard functions and render HomePage with a regular soldier, commander, duty manager, and admin. Assert command APIs are not called for the soldier and are called for management users. Assert the command section is absent for the soldier and present for management users.

- [ ] **Step 2: Run the tests and verify the new assertions fail**

Run: `npm test -- --run src/pages/HomePage.test.tsx`

- [ ] **Step 3: Add management-only command queries to HomePage**

Use the shared predicate for every command query:

```ts
const commandEnabled = isCommandScopeAvailable(user);
const alertsQuery = useQuery({
  queryKey: queryKeys.commandDashboardAlerts(),
  queryFn: getAlerts,
  enabled: commandEnabled,
});
```

Apply the same `enabled` gate to command upcoming, potential, approvals, ineligible-soldiers, hierarchy tree/command-node data, and command calendar data. Keep personal queries enabled for authenticated users regardless of management role.

- [ ] **Step 4: Compose command widgets inside `CommandDashboardSection`**

Move the command-only panels currently assembled by `CommandDashboardPage` into the unified page. Keep the existing pending-approval widget once in the command section; remove the current `HomePage` copy from the normal personal flow rather than rendering it twice. Keep `AlertsPanel` command data separate from `AlertBanners`, because banners are personal qualification/upcoming-duty alerts.

- [ ] **Step 5: Remove the three summary cards and their fetch**

Do not add `SummaryCards` back. Delete `getSummary` usage and, once no consumers remain, delete only the unused frontend summary contract/function and corresponding query key. Leave backend removal for Task 6 after endpoint usage is verified.

- [ ] **Step 6: Run the role and page tests**

Run: `npm test -- --run src/pages/HomePage.test.tsx src/pages/CommandDashboardPage.test.tsx`

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/HomePage.tsx frontend/src/pages/HomePage.test.tsx frontend/src/api/commanderDashboard.ts frontend/src/queryKeys.ts
git commit -m "feat: compose command dashboard into homepage"
```

## Task 4: Make shared widgets scope-aware and visually unambiguous

**Files:**
- Modify: `frontend/src/components/dashboard/PendingApprovalsWidget.tsx`
- Modify: `frontend/src/components/dashboard/AlertsPanel.tsx`
- Modify: `frontend/src/components/dashboard/UpcomingSnapshot.tsx`
- Modify: `frontend/src/components/dashboard/IneligibleSoldiersPanel.tsx`
- Modify: `frontend/src/components/dashboard/DutyPotentialPanel.tsx`
- Modify: `frontend/src/components/UnitCalendar.tsx`
- Test: each modified component’s existing test file

**Interfaces:**
- Add `scope: "personal" | "command"` only where a component needs different labels or styles.
- Add `emphasis?: "normal" | "highlighted"` only where the parent container cannot provide the visual distinction.
- Never infer command scope from a role inside a reusable widget; the parent passes the scope explicitly.

- [ ] **Step 1: Add failing assertions for scope labels**

Assert command instances say “יחידה/פיקוד” or an equivalent translated scope label, while personal instances retain personal wording. Assert the ineligible-soldiers and approvals widgets are not mounted at all for a regular soldier.

- [ ] **Step 2: Run focused component tests and verify failures**

Run: `npm test -- --run src/components/dashboard/PendingApprovalsWidget.test.tsx src/components/dashboard/AlertsPanel.test.tsx src/components/dashboard/UpcomingSnapshotWidget.test.tsx src/components/dashboard/IneligibleSoldiersPanel.test.tsx`

- [ ] **Step 3: Implement explicit scope props and translations**

Use translation keys under `command_dashboard` and `home` rather than adding new hard-coded Hebrew strings. Keep links and actions appropriate to the scope; a command approval link must remain `/approvals` and a personal swap link must remain the personal swap flow.

- [ ] **Step 4: Ensure each calendar has its correct scope**

Render exactly one Homepage `UnitCalendar`: pass the authorized `nodeIds` for management users, and pass `soldierId` for regular soldiers. The command calendar’s `nodeIds` must include the manager’s own commanded nodes and all descendants, so the manager’s own assignments are included by the same query. Keep the separate unit duty board’s existing all-unit behavior unchanged.

- [ ] **Step 5: Run all modified component tests**

Run: `npm test -- --run src/components/dashboard src/pages/HomePage.test.tsx`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/dashboard frontend/src/components/UnitCalendar.tsx frontend/src/pages/HomePage.tsx frontend/src/i18n
git commit -m "feat: clarify personal and command dashboard scopes"
```

## Task 4A: Highlight the manager’s own duties inside the unit calendar

**Files:**
- Modify: `frontend/src/components/UnitCalendar.tsx`
- Modify: `frontend/src/styles/globals.css`
- Modify: `frontend/src/pages/HomePage.tsx`
- Test: `frontend/src/components/UnitCalendar.test.tsx`

**Interfaces:**
- Add `highlightSoldierId?: string` to `UnitCalendarProps`. It is used by the Homepage’s management-scope calendar to identify the manager’s own duties; the regular-soldier Homepage calendar continues using `soldierId`.
- Add a local `showOnlyMine` checkbox state, defaulting to `false`, with the exact Hebrew label `הצג רק אירועים שלי`.
- The duty event model already exposes `CalendarShift.assignees[].soldier_id`; use that existing identity to classify a duty as mine. Do not infer ownership from hierarchy or event creator.

- [ ] **Step 1: Add failing calendar tests**

Using the existing `CalendarShift` test fixtures, render a unit calendar with `highlightSoldierId="me"` and two shifts: one whose assignees include `me`, and one assigned only to another soldier. Assert both events render by default, the own event receives a dedicated class/test marker, and clicking `הצג רק אירועים שלי` leaves only the own event. Also assert the checkbox is absent from a personal calendar rendered with `soldierId`.

- [ ] **Step 2: Run the focused tests and verify the new assertions fail**

Run from `frontend`: `npm test -- --run src/components/UnitCalendar.test.tsx`

- [ ] **Step 3: Add explicit ownership classification to unit duty events**

When `highlightSoldierId` is present, add classes such as `my-duty-calendar-event` and `my-duty-sparkle-border` to events where `shift.assignees.some((a) => a.soldier_id === highlightSoldierId)`. Keep the existing holiday classes unchanged. Use a distinct accessible color (for example indigo/blue) and a sparkle/border animation parallel to the holiday styling; add a `prefers-reduced-motion` rule so the animation is disabled for users who request reduced motion.

- [ ] **Step 4: Add the “show only mine” filter**

Render the checkbox only when `highlightSoldierId` is present. Filter `filteredShifts` after the duty-type filter and before event conversion:

```ts
const visibleShifts = showOnlyMine
  ? filteredShifts.filter((shift) => shift.assignees.some((a) => a.soldier_id === highlightSoldierId))
  : filteredShifts;
```

Use `aria-label="הצג רק אירועים שלי"`, preserve the existing duty-type and holiday filters, and keep range events visible unless the range API explicitly identifies the user as assigned. The requested filter is specifically for duties, not a hidden range-assignment rule.

- [ ] **Step 5: Pass the current user into the command/unit calendar**

In the unified Homepage, render one calendar branch: for management users pass `nodeIds` plus `highlightSoldierId={user.id}`; for regular soldiers pass `soldierId={user.id}`. Do not render a second personal calendar for management users. The “הצג רק אירועים שלי” checkbox appears only for the management users’ subtree view.

- [ ] **Step 6: Run the calendar and homepage tests**

Run from `frontend`: `npm test -- --run src/components/UnitCalendar.test.tsx src/pages/HomePage.test.tsx`

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/UnitCalendar.tsx frontend/src/components/UnitCalendar.test.tsx frontend/src/styles/globals.css frontend/src/pages/HomePage.tsx
git commit -m "feat: highlight manager duties in unit calendar"
```

## Task 5: Remove the duplicate command-dashboard page after migration

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/CommandDashboardPage.tsx`
- Modify: `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/searchRegistry.ts`
- Test: `frontend/src/pages/CommandDashboardPage.test.tsx`, `frontend/src/App.test.tsx` or the existing route test

**Interfaces:**
- `/` is the canonical combined dashboard.
- After the unified homepage is verified, there is no standalone `/command-dashboard` page. Preserving a redirect is out of scope because the standalone page must be removed.

- [ ] **Step 1: Add a removal regression test**

Assert the application no longer registers `/command-dashboard`, the unified homepage renders the command section for management users, and a regular soldier cannot access command content through the old path.

- [ ] **Step 2: Run the route test and verify it fails**

Run: `npm test -- --run src/App.test.tsx src/pages/CommandDashboardPage.test.tsx`

- [ ] **Step 3: Delete the standalone page and all navigation/search references**

Remove the `CommandDashboardPage` import and route from `frontend/src/App.tsx`, delete `frontend/src/pages/CommandDashboardPage.tsx` and its test, remove the `nav-command-dashboard` item from `frontend/src/components/UnifiedNav.tsx`, and remove `page-command-dashboard` from `frontend/src/searchRegistry.ts`. Keep management-only navigation entries such as approvals and planning governed by their existing permission predicates.

- [ ] **Step 4: Run route and search tests**

Run: `npm test -- --run src/App.test.tsx src/searchRegistry.test.ts`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/CommandDashboardPage.tsx frontend/src/components/UnifiedNav.tsx frontend/src/searchRegistry.ts frontend/src/pages/CommandDashboardPage.test.tsx
git commit -m "refactor: remove standalone commander dashboard"
```

## Task 6: Verify backend scope and remove obsolete summary code only if unused

**Files:**
- Inspect/modify: `backend/app/routes/commander_dashboard.py`
- Inspect/modify: `backend/app/services/commander_dashboard.py`
- Test: `backend/app/routes/tests/test_commander_dashboard.py`

**Interfaces:**
- Existing command endpoints remain management-authorized and subtree-scoped.
- If admins are intended to see the command section, define an explicit admin scope rule in the backend rather than relying on the frontend’s `canApprove` predicate.

- [ ] **Step 1: Add/adjust authorization tests**

Cover: regular soldier receives 403 from command endpoints; commander receives only their subtree; duty manager receives their authorized command scope; admin behavior is explicit and tested. Also test that no endpoint accepts a caller-supplied node ID that bypasses the caller’s scope.

- [ ] **Step 2: Run the backend command-dashboard tests and inspect failures**

Run: `pytest -q app/routes/tests/test_commander_dashboard.py`

- [ ] **Step 3: Align only the backend behavior required by the unified UI**

Preserve `_assert_commander`/authorization boundaries. If admin access is required, implement a documented admin scope resolution using existing hierarchy authorization helpers and add tests for it. Do not broaden commander or duty-manager access.

- [ ] **Step 4: Search for obsolete summary endpoint consumers**

Run: `rg -n "command-dashboard/summary|getSummary|SummaryCards|commandDashboardSummary" frontend backend`

- [ ] **Step 5: Remove obsolete backend summary code only when the search confirms zero consumers**

Delete the endpoint/service/schema only if it is not part of an external API contract that must remain. If retained for compatibility, mark it as unused and do not fetch it from the frontend.

- [ ] **Step 6: Run command-dashboard and authorization regression tests**

Run: `pytest -q app/routes/tests/test_commander_dashboard.py app/services/tests/test_dm_scope.py`

- [ ] **Step 7: Commit**

```bash
git add backend/app/routes/commander_dashboard.py backend/app/services/commander_dashboard.py backend/app/routes/tests/test_commander_dashboard.py
git commit -m "test: preserve command dashboard scope authorization"
```

## Task 7: Full verification and visual review

**Files:**
- Test: all modified frontend/backend test files
- Inspect: `frontend/src/pages/HomePage.tsx`, rendered homepage at desktop and mobile widths

- [ ] **Step 1: Run frontend focused tests**

Run from `frontend`: `npm test -- --run src/pages/HomePage.test.tsx src/pages/CommandDashboardPage.test.tsx src/auth/dashboardRoles.test.ts src/components/dashboard`

- [ ] **Step 2: Run frontend typecheck and lint**

Run from `frontend`: `npm run typecheck; npm run lint`

- [ ] **Step 3: Run backend command and role regression tests**

Run from `backend`: `pytest -q app/routes/tests/test_commander_dashboard.py app/services/tests/test_dm_scope.py`

- [ ] **Step 4: Perform a browser review with four identities**

Check regular soldier, commander, duty manager, and admin at `/`. Verify:

- regular soldier sees personal content only;
- commander and duty manager see the highlighted command section plus normal personal content;
- command widgets show subtree/unit labels and personal widgets show personal labels;
- no duplicate approvals/upcoming/calendar widgets appear unintentionally;
- command data is not requested for a regular soldier;
- mobile layout keeps command emphasis without horizontal overflow.

- [ ] **Step 5: Run the full backend suite with the repository’s normal timeout**

Run from `backend`: `pytest -q`

Record a timeout separately from a test failure if the suite exceeds the execution limit.

- [ ] **Step 6: Review the final diff and commit**

Run: `git diff --check; git status --short; git diff --stat`

```bash
git add frontend backend docs/superpowers/plans/2026-08-31-unified-commander-homepage.md
git commit -m "feat: unify commander and soldier home dashboards"
```

## Self-review checklist

- [x] The three removed summary cards are explicitly excluded from the design.
- [x] Commanders and duty managers share one management predicate and one highlighted command section.
- [x] Regular soldiers are prevented from both rendering and fetching command-only content.
- [x] Personal and command scopes are named and visually distinct.
- [x] Existing authorization remains a backend responsibility and is covered by tests.
- [x] The duplicate route has a bookmark-compatible retirement path.
- [x] The plan identifies exact files, interfaces, tests, commands, and commit boundaries.
