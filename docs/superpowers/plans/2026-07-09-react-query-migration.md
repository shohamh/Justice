# React Query Data-Freshness Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop screens from going stale until the user navigates away and back. `@tanstack/react-query` is already installed and wired up globally (`frontend/src/main.tsx`), but almost no page uses it — most fetch data via a manual `useEffect` + `useState`, with no shared cache and no invalidation after a mutation elsewhere changes the same data.

**Architecture:** Introduce one shared query-key module so every page/mutation references the same cache keys, then migrate every data-fetching page from manual `useEffect`/`useState` to `useQuery`, and every mutation to call `queryClient.invalidateQueries` for the keys it affects. This plan establishes the pattern in full detail on two representative pages (`HomePage.tsx`, `MyDutiesPage.tsx`) and closes with a complete, page-by-page checklist for migrating the rest — each remaining page follows the exact same mechanical transformation demonstrated in Tasks 2–3, so later tasks aren't re-specified line-by-line.

**Tech Stack:** React, TypeScript, `@tanstack/react-query` (already a dependency — check `frontend/package.json` to confirm the installed major version before starting, since v4 and v5 have different `useQuery` object-argument requirements; the code below assumes v5's single-object signature).

## Global Constraints

- This plan is scheduled **last** among the feedback-sweep plans, specifically so it lands after the swaps chain-of-command rework (`2026-07-09-swaps-chain-approval.md`) and the enrollment gate (`2026-07-09-enrollment-gate-and-notifications.md`), both of which touch `SwapsPage.tsx`, `ApprovalsPage.tsx`, and `MyRequestsPage.tsx`. Before starting Task 4's checklist items for those three files, re-read their current state — they will look different from what's described elsewhere in this repo's history by the time this plan executes.
- Every migrated page keeps its existing JSX/rendering logic untouched — only the data-fetching (state + effect) layer changes to `useQuery`/`useMutation`. Do not restyle or restructure components while migrating them; that's a separate concern.
- Default `QueryClient` options stay conservative: no custom `staleTime` override (default `0`, i.e. always considered stale, refetched on mount/focus) — this directly serves the "screens don't update" complaint, so don't add a long `staleTime` that would reintroduce staleness.
- A page is "done" when zero `useState`+`useEffect` pairs remain for server data, and every mutation on that page invalidates the query keys it affects.

---

### Task 1: Query key conventions module

**Files:**
- Create: `frontend/src/queryKeys.ts`

**Interfaces:**
- Produces: a `queryKeys` object with one function per distinct piece of server data used across the pages this plan touches. Every subsequent task imports from this module — no page should invent its own ad hoc key array.

- [ ] **Step 1: Create the module**

```typescript
// frontend/src/queryKeys.ts
//
// Central registry of react-query cache keys. Add a new entry here whenever a
// page starts fetching a new piece of server data — this keeps invalidation
// call sites (in mutations) and read sites (in useQuery calls) referring to
// the exact same key shape instead of hand-typed arrays that can drift apart.

export const queryKeys = {
  effectiveDuties: (soldierId: string, params?: Record<string, unknown>) =>
    ["effectiveDuties", soldierId, params ?? {}] as const,
  dutyTypes: () => ["dutyTypes"] as const,
  dutyLocations: () => ["dutyLocations"] as const,
  mySwaps: () => ["swaps", "mine"] as const,
  incomingSwaps: () => ["swaps", "incoming"] as const,
  pendingSwaps: () => ["swaps", "pending"] as const,
  swapBoard: (filters?: Record<string, unknown>) => ["swaps", "board", filters ?? {}] as const,
  pendingEnrollments: () => ["enrollment", "pending"] as const,
  systemSettings: () => ["systemSettings"] as const,
  transparency: () => ["scoring", "transparency"] as const,
  breakdown: (soldierId: string) => ["scoring", "breakdown", soldierId] as const,
  reserveStats: () => ["soldiers", "reserveStats"] as const,
  pendingConstraintsCount: () => ["constraints", "pendingCount"] as const,
  pendingExemptionsCount: () => ["exemptions", "pendingCount"] as const,
  pendingFieldUpdatesCount: () => ["soldiers", "pendingFieldUpdatesCount"] as const,
  myConstraints: () => ["constraints", "mine"] as const,
  myExemptionRequests: () => ["exemptionRequests", "mine"] as const,
  pendingConstraints: () => ["constraints", "pending"] as const,
  pendingExemptionRequests: () => ["exemptionRequests", "pending"] as const,
  pendingFieldUpdates: () => ["soldiers", "pendingFieldUpdates"] as const,
};
```

- [ ] **Step 2: Verify it compiles**

Run: `cd frontend && npm run typecheck`
Expected: no new errors (this file has no consumers yet, so it should compile in isolation).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/queryKeys.ts
git commit -m "feat: add central react-query key registry"
```

---

### Task 2: Migrate `HomePage.tsx`

**Files:**
- Modify: `frontend/src/pages/HomePage.tsx`

**Interfaces:**
- Consumes: `queryKeys` from Task 1.

- [ ] **Step 1: Replace the manual fetch with `useQuery` calls**

`HomePage.tsx` currently declares 12 `useState` variables (lines 57-69) and fetches all of them in one `Promise.all` inside a single `useEffect` (lines 87-134). Replace that whole block with individual queries. First, update the imports (add to the top, alongside the existing ones):

```typescript
import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
```

Replace the 12 `useState` declarations and the `useEffect` (lines 57-69 and 87-134) with:

```typescript
  const dutiesQuery = useQuery({
    queryKey: user ? queryKeys.effectiveDuties(user.id, { date_from: offsetDate(-365), date_to: offsetDate(60) }) : ["effectiveDuties", "anonymous"],
    queryFn: () => listEffectiveDuties(user!.id, { date_from: offsetDate(-365), date_to: offsetDate(60) }),
    enabled: !!user,
  });
  const duties = dutiesQuery.data ?? [];

  const typesQuery = useQuery({ queryKey: queryKeys.dutyTypes(), queryFn: listDutyTypes });
  const typeNames = Object.fromEntries((typesQuery.data ?? []).map((t) => [t.id, t.name]));

  const locsQuery = useQuery({ queryKey: queryKeys.dutyLocations(), queryFn: listLocations });
  const locationNames = Object.fromEntries((locsQuery.data ?? []).map((l) => [l.id, l.name]));

  const mySwapsQuery = useQuery({ queryKey: queryKeys.mySwaps(), queryFn: listMySwaps });
  const mySwaps = mySwapsQuery.data ?? [];

  const settingsQuery = useQuery({ queryKey: queryKeys.systemSettings(), queryFn: getSystemSettings });
  const settings = settingsQuery.data ?? ({} as SettingsMap);

  const transparencyQuery = useQuery({
    queryKey: queryKeys.transparency(),
    queryFn: () => getTransparency().then((out) => out.rows),
  });
  const transparencyRows = transparencyQuery.data ?? [];

  const breakdownQuery = useQuery({
    queryKey: user ? queryKeys.breakdown(user.id) : ["breakdown", "anonymous"],
    queryFn: () => getBreakdown(user!.id),
    enabled: !!user,
  });
  const breakdown = breakdownQuery.data ?? null;

  const enrollQuery = useQuery({
    queryKey: queryKeys.pendingEnrollments(),
    queryFn: listPendingEnrollments,
    enabled: canApprove,
  });
  const pendingEnrollments = enrollQuery.data ?? [];

  const pendingSwapsQuery = useQuery({
    queryKey: queryKeys.pendingSwaps(),
    queryFn: listPendingSwaps,
    enabled: canApprove,
  });
  const pendingSwaps = pendingSwapsQuery.data ?? [];

  const pendingConstraintsQuery = useQuery({
    queryKey: queryKeys.pendingConstraintsCount(),
    queryFn: getPendingCount,
    enabled: canApprove,
  });
  const pendingConstraints = pendingConstraintsQuery.data ?? 0;

  const pendingExemptionsQuery = useQuery({
    queryKey: queryKeys.pendingExemptionsCount(),
    queryFn: getPendingExemptionCount,
    enabled: canApprove,
  });
  const pendingExemptions = pendingExemptionsQuery.data ?? 0;

  const pendingFieldUpdatesQuery = useQuery({
    queryKey: queryKeys.pendingFieldUpdatesCount(),
    queryFn: getPendingFieldUpdateCount,
    enabled: canApprove,
  });
  const pendingFieldUpdates = pendingFieldUpdatesQuery.data ?? 0;
```

Note: `canApprove` (line 71 currently) must be computed *before* these queries since several `enabled` flags reference it — move `const canApprove = ...` above this block if it isn't already (it currently is, at line 71, right after `useAuth()` — keep it there, just make sure the query block goes after it).

The rest of the component (everything from `function handleOpenDuty` onward, and the whole JSX return) references `duties`, `typeNames`, `locationNames`, `mySwaps`, `settings`, `transparencyRows`, `breakdown`, `pendingEnrollments`, `pendingSwaps`, `pendingConstraints`, `pendingExemptions`, `pendingFieldUpdates` by name — since those are now `const`s derived from query results with the exact same names and shapes as before (empty array/`0`/`null` defaults matching the old `useState` initial values), nothing else in the file needs to change.

- [ ] **Step 2: Remove now-unused imports**

`useEffect` and `useState` are still used elsewhere in the file for `selectedDuty` (`const [selectedDuty, setSelectedDuty] = useState<EffectiveDuty | null>(null);` stays — that's local UI state, not server data, and correctly stays as `useState`). Only remove `useEffect` from the import line if nothing else in the file uses it — check with `grep -n "useEffect" frontend/src/pages/HomePage.tsx` after the edit.

- [ ] **Step 3: Manually verify in the browser**

Start the dev stack, log in, load the home dashboard, and confirm every widget (upcoming duties, swap status, pending approvals, duty history, stat cards) still renders with the same data as before. Open two browser tabs as a commander: approve a pending swap/constraint/exemption in one tab, switch to the other tab (no reload) — within a few seconds (default react-query refetch-on-window-focus) the pending counts should update without a manual page reload.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/HomePage.tsx
git commit -m "refactor: migrate HomePage to react-query"
```

---

### Task 3: Migrate `MyDutiesPage.tsx`

**Files:**
- Modify: `frontend/src/pages/MyDutiesPage.tsx`

**Interfaces:**
- Consumes: `queryKeys` from Task 1.

- [ ] **Step 1: Replace the manual fetch with `useQuery` calls**

Update the imports at the top:

```typescript
import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "../queryKeys";
```

Replace the 5 `useState` declarations (lines 49-54: `allRows`, `breakdown`, `pastCount`, `pastDays`, `reserveStats`, `loading`) and the `useEffect` (lines 56-74) with:

```typescript
  const transparencyQuery = useQuery({
    queryKey: queryKeys.transparency(),
    queryFn: () => getTransparency().then((out) => out.rows),
  });
  const allRows = transparencyQuery.data ?? [];

  const breakdownQuery = useQuery({
    queryKey: user ? queryKeys.breakdown(user.id) : ["breakdown", "anonymous"],
    queryFn: () => getBreakdown(user!.id),
    enabled: !!user,
  });
  const breakdown = breakdownQuery.data ?? null;

  const dutiesQuery = useQuery({
    queryKey: user ? queryKeys.effectiveDuties(user.id) : ["effectiveDuties", "anonymous"],
    queryFn: () => listEffectiveDuties(user!.id),
    enabled: !!user,
  });

  const reserveStatsQuery = useQuery({ queryKey: queryKeys.reserveStats(), queryFn: getReserveStats });
  const reserveStats = reserveStatsQuery.data ?? null;

  const today = new Date().toISOString().split("T")[0];
  // end_date is exclusive, so "over" means end_date is today or earlier.
  const pastDuties = (dutiesQuery.data ?? []).filter((d) => d.end_date <= today);
  const pastCount = pastDuties.length;
  const pastDays = pastDuties.reduce((s, d) => s + dayCount(d as { start_date: string; end_date: string }), 0);

  const loading = transparencyQuery.isLoading || breakdownQuery.isLoading || dutiesQuery.isLoading;
```

Everything below (the `useMemo` blocks for `myRow`, `unitAvgNormRaw`, etc., and the JSX) references `allRows`, `breakdown`, `pastCount`, `pastDays`, `reserveStats`, `loading` by name — unchanged, since those names now resolve to the `const`s above with matching shapes/defaults.

- [ ] **Step 2: Manually verify in the browser**

Log in as a soldier, open "היומן שלי" (`/my-duties` or wherever this page is routed — check `grep -n "MyDutiesPage" frontend/src/App.tsx`), and confirm the stat cards, breakdown chart, and comparison chart all render the same as before.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/MyDutiesPage.tsx
git commit -m "refactor: migrate MyDutiesPage to react-query"
```

---

### Task 4: Migrate the remaining pages

**Files:** every page listed below.

Apply the exact same transformation demonstrated in Tasks 2–3 to each page in this list: replace `useState` + `useEffect`-driven server-data fetches with `useQuery`, add any new keys needed to `frontend/src/queryKeys.ts` (Task 1) as you go, and make every mutation on the page call `queryClient.invalidateQueries({ queryKey: ... })` for the query keys it affects (import `useQueryClient` from `@tanstack/react-query`, call `const queryClient = useQueryClient();` at the top of the component, and call `queryClient.invalidateQueries(...)` after each successful mutation instead of the manual `refresh()`/`fetchAll()` re-fetch functions those pages currently hand-roll).

Do each page as its own commit (`refactor: migrate <PageName> to react-query`), and manually verify each in the browser before moving to the next — don't batch multiple pages into one commit, so a regression in one page doesn't block/hide the others.

Check off each as done:

- [ ] `ApprovalsPage.tsx` — re-read current state first (touched by the swaps and enrollment plans); has 5 tabs (constraints, exemptions, field_updates, swaps, enrollment), each with its own pending-list fetch and several approve/reject mutations. Add query keys for each tab's list; every approve/reject mutation should invalidate that tab's list key plus the relevant `*PendingCount` key from Task 2 (so `HomePage`'s badge counts update too).
- [ ] `SwapsPage.tsx` — re-read current state first (touched by the swaps plan). Migrate `mySwaps`, `boardSwaps`, `incomingSwaps` fetches to `useQuery`; every create/claim/cancel/approve/reject mutation invalidates `queryKeys.mySwaps()`, `queryKeys.incomingSwaps()`, `queryKeys.swapBoard()`, and `queryKeys.pendingSwaps()` as appropriate.
- [ ] `MyRequestsPage.tsx` — re-read current state first (touched by the enrollment plan). Migrate the constraints and exemption-request lists; submit/cancel mutations invalidate `queryKeys.myConstraints()`/`queryKeys.myExemptionRequests()`.
- [ ] `ProfilePage.tsx`
- [ ] `NotificationsPage.tsx`
- [ ] `TransparencyPage.tsx`
- [ ] `CommandDashboardPage.tsx`
- [ ] `TeamHierarchyPage.tsx`
- [ ] `DutyManagementPage.tsx`
- [ ] `DutyConfigPage.tsx`
- [ ] `ShiftsPage.tsx`
- [ ] `ShiftTemplatesPage.tsx`
- [ ] `AlgorithmPage.tsx`
- [ ] `HakpazaPage.tsx`
- [ ] `UnitCalendarPage.tsx`
- [ ] `SystemSettingsPage.tsx`
- [ ] `AdminInviteCodesPage.tsx`
- [ ] `ImportSessionsListPage.tsx`
- [ ] `ImportSessionReviewPage.tsx`
- [ ] `ImportUploadPage.tsx`
- [ ] `TelegramSetupPage.tsx`
- [ ] `admin/` subdirectory pages — run `ls frontend/src/pages/admin/` to enumerate; apply the same treatment to each.
- [ ] `planning/` subdirectory pages — run `ls frontend/src/pages/planning/` to enumerate; apply the same treatment to each.

Pages intentionally **not** in scope (no meaningful server-data staleness concern): `LoginPage.tsx`, `RegisterPage.tsx`, `ForgotPasswordPage.tsx`, `ResetPasswordPage.tsx`, `ChangePasswordPage.tsx`, `VerifyEmailPage.tsx`, `ActionPage.tsx` — these are single-action forms with no list/dashboard data to keep fresh.

- [ ] **Final step once every page above is checked off: run the full frontend test suite**

Run: `cd frontend && npm test && npm run typecheck && npm run lint`
Expected: all passing, zero lint warnings (lint is a zero-warnings gate per this repo's conventions).
