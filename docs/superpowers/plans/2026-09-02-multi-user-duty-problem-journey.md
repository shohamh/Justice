# Multi-user Duty Problem Journey Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove through real browser UI that a duty manager can algorithmically and manually assign a duty, and that successive exemption, גימלים, Hakpaza Pikudit, absence, and reserve failures are surfaced and resolved correctly.

**Architecture:** Extend the existing serial Playwright harness with a journey-oriented scenario. Reuse the product’s existing assignment, request, approval, Hakpaza, and duty-management screens; add only missing user-facing transitions and stable selectors. Each role uses its own browser context and every mutation is followed by a visible-state assertion.

**Tech Stack:** React, TypeScript, FastAPI, PostgreSQL, Playwright Test, Chrome.

**Spec:** `docs/superpowers/specs/2026-09-02-multi-user-duty-problem-journey.md`

## Global Constraints

- All state transitions must use visible application UI; no setup API or direct database mutation may create or change the scenario records.
- Use the real frontend, backend, and PostgreSQL stack.
- Keep the journey serial and use separate browser contexts for each actor.
- Run Chrome at the existing desktop and 390px mobile viewports.
- Assert visible state after every mutation and refresh.
- Preserve Hebrew/RTL labels and distinguish ordinary exemptions, גימלים, and Hakpaza Pikudit.

---

### Task 1: Inventory and lock the existing UI seams

**Files:**
- Read: `frontend/src/pages/planning/ShiftsManagementPage.tsx`
- Read: `frontend/src/pages/AlgorithmPage.tsx`
- Read: `frontend/src/pages/DutyManagementPage.tsx`
- Read: `frontend/src/pages/MyRequestsPage.tsx`
- Read: `frontend/src/pages/HakpazaPage.tsx`
- Read: `frontend/src/pages/ApprovalsPage.tsx`
- Read: `frontend/src/pages/UnitCalendarPage.tsx`
- Test: `frontend/tests/e2e/smoke/multi_user_duty_problems.spec.ts`

**Interfaces:**
- Produces a written inventory in the test comments of the exact visible controls and state selectors for duty creation, algorithm execution/publication, manual assignment, exemption approval, גימלים, Hakpaza Pikudit, absence, and reserve activation.
- Establishes the actor-to-context mapping used by later tasks: duty manager, commander, four assigned soldiers, first reserve, and second reserve.

- [ ] **Step 1: Trace the existing routes and API clients**

Run:

```powershell
rg -n "algorithm|assignment|reserve|hakpaza|gimel|גימלים|exemption|absence|cannot|unavailable" frontend/src/pages frontend/src/api backend/app/routes backend/app/services -g '*.tsx' -g '*.ts' -g '*.py'
```

Record the existing route and selector for each required action in the new spec file’s helper comments.

- [ ] **Step 2: Add the journey skeleton with failing user-visible checkpoints**

Create `multi_user_duty_problems.spec.ts` with separate contexts and a first test that navigates the duty manager to the current assignment screen and asserts the current page boundary. Keep all later transitions as named helper stubs until the UI seams are confirmed.

- [ ] **Step 3: Run the skeleton against the real stack**

Run from `frontend`:

```powershell
node .\\node_modules\\@playwright\\test\\cli.js test tests/e2e/smoke/multi_user_duty_problems.spec.ts --project=desktop --workers=1
```

Expected: the test either reaches the existing assignment boundary or fails with the exact missing route/control needed for Task 2.

- [ ] **Step 4: Commit the inventory checkpoint**

```powershell
git add frontend/tests/e2e/smoke/multi_user_duty_problems.spec.ts
git commit -m "test: map multi-user duty problem journey seams"
```

### Task 2: Make algorithmic and manual assignment fully visible

**Files:**
- Modify: `frontend/src/pages/planning/ShiftsManagementPage.tsx`
- Modify: `frontend/src/pages/AlgorithmPage.tsx`
- Modify: `frontend/src/pages/DutyManagementPage.tsx`
- Modify: relevant files under `frontend/src/api/`
- Test: matching existing component tests and `frontend/tests/e2e/smoke/multi_user_duty_problems.spec.ts`

**Interfaces:**
- Produces visible selectors for duty creation, algorithm start, proposal review, publish/accept, manual soldier assignment, assignment rows, and reserve rows.
- Keeps algorithm publication and manual assignment as separate user actions and preserves backend authorization.

- [ ] **Step 1: Write focused component tests for missing controls or state**

For each absent boundary, add a component test that renders the relevant page and verifies the control label, disabled/loading state, and post-success assignment row. Use the existing API mocks in the neighboring page test rather than changing production auth.

- [ ] **Step 2: Implement the smallest UI/API seam**

Add only the missing form/action/state selector required by the failing component test. Keep mutation consequences visible in the assignment list and retain existing error text.

- [ ] **Step 3: Run focused frontend tests and the assignment portion of the browser skeleton**

```powershell
npx vitest run src/pages/planning/ShiftsManagementPage.test.tsx src/pages/AlgorithmPage.test.tsx src/pages/DutyManagementPage.test.tsx --maxWorkers=1 --no-file-parallelism
node .\\node_modules\\@playwright\\test\\cli.js test tests/e2e/smoke/multi_user_duty_problems.spec.ts --project=desktop --workers=1
```

Expected: the duty manager can visibly create/publish algorithm assignments and then manually assign the additional soldier.

- [ ] **Step 4: Commit**

```powershell
git add frontend/src frontend/tests/e2e/smoke/multi_user_duty_problems.spec.ts
git commit -m "test: cover algorithm and manual duty assignment journey"
```

### Task 3: Expose post-assignment problems and reserve replacement through UI

**Files:**
- Modify: `frontend/src/pages/MyRequestsPage.tsx`
- Modify: `frontend/src/pages/ApprovalsPage.tsx`
- Modify: `frontend/src/pages/HakpazaPage.tsx`
- Modify: `frontend/src/pages/DutyManagementPage.tsx`
- Modify: `frontend/src/pages/UnitCalendarPage.tsx`
- Modify: relevant files under `frontend/src/api/`
- Test: focused component tests for each modified page

**Interfaces:**
- Produces visible status/problem records tied to a shift and assignee.
- Produces a reserve activation action that records the replaced assignee, active reserve, replacement reason, and subsequent reserve vacancy.
- Commander-facing views show the exemption and Hakpaza Pikudit as actionable duty problems.

- [ ] **Step 1: Write failing component tests for the problem taxonomy**

Add tests proving that an assigned soldier’s exemption, גימלים, inability-to-attend report, and Hakpaza Pikudit render as distinct statuses; add tests proving a commander sees the exemption conflict and a duty manager sees reserve activation controls.

- [ ] **Step 2: Implement problem display and replacement actions**

Connect the existing backend responses to the relevant page state. Add stable `data-testid` values only to the problem badge, shift problem panel, reserve activation button, replacement row, and history boundary.

- [ ] **Step 3: Verify the replacement chain in focused tests**

```powershell
npx vitest run src/pages/MyRequestsPage.test.tsx src/pages/ApprovalsPage.test.tsx src/pages/HakpazaPage.test.tsx src/pages/DutyManagementPage.test.tsx --maxWorkers=1 --no-file-parallelism
```

Expected: a first reserve can be activated, marked unavailable by a later גימלים event, and replaced by a second reserve without losing the original history.

- [ ] **Step 4: Commit**

```powershell
git add frontend/src
git commit -m "feat: surface duty problems and reserve replacements"
```

### Task 4: Complete the real-UI multi-user journey

**Files:**
- Modify: `frontend/tests/e2e/smoke/multi_user_duty_problems.spec.ts`
- Modify: `frontend/tests/e2e/fixtures/auth.ts` only if a seeded role is missing
- Modify: `docs/e2e-coverage-matrix.md`

**Interfaces:**
- The spec exposes helpers for `openRoleContext`, `createAndPublishAlgorithmDuty`, `assignManually`, `submitAndApproveExemption`, `submitGimelim`, `reportCannotAttend`, `grantHakpazaPikudit`, and `activateReserve`.
- Helpers use clicks, fills, visible dialogs, and page navigation only; they do not call `page.request`, `fetch`, database code, or setup APIs for scenario mutations.

- [ ] **Step 1: Implement the algorithm/manual assignment path**

Drive the duty manager UI through duty creation, algorithm execution, proposal publication, and manual assignment. Assert each assignment in the visible duty/shift list.

- [ ] **Step 2: Implement each user problem path**

Use the assigned soldier contexts to submit and complete the exemption, גימלים, inability-to-attend, and Hakpaza Pikudit flows. Use the commander context to complete any required approval and assert the commander-facing problem state.

- [ ] **Step 3: Implement the two-stage reserve chain**

Use the duty manager UI to activate the first reserve, then submit גימלים from that reserve’s context and activate the second reserve. Assert active/inactive assignment rows and replacement history after reload.

- [ ] **Step 4: Run both viewport projects**

```powershell
node .\\node_modules\\@playwright\\test\\cli.js test tests/e2e/smoke/multi_user_duty_problems.spec.ts --workers=1 --reporter=line
```

Expected: the journey passes on desktop and mobile with no retry-only green result.

- [ ] **Step 5: Commit**

```powershell
git add frontend/tests/e2e/smoke/multi_user_duty_problems.spec.ts docs/e2e-coverage-matrix.md
git commit -m "test: cover multi-user duty problem lifecycle"
```

### Task 5: Regression proof and handoff

**Files:**
- Modify: `docs/e2e-coverage-matrix.md`
- Modify: `docs/e2e-maintenance.md`
- Test: `frontend/tests/e2e/smoke/multi_user_duty_problems.spec.ts`

**Interfaces:**
- Documents the new journey’s actors, transitions, critical assertions, and owner.
- Records whether desktop and mobile passed independently and identifies any unverified full-suite result.

- [ ] **Step 1: Prove the main regression boundary**

In a disposable local edit, disable the exemption problem badge or second-reserve activation selector, run the focused journey, capture the actionable failure artifact, and restore the edit before committing.

- [ ] **Step 2: Run final focused verification**

```powershell
npm run typecheck
npm run lint
node .\\node_modules\\@playwright\\test\\cli.js test tests/e2e/smoke/multi_user_duty_problems.spec.ts --workers=1 --reporter=line
git diff --check
```

- [ ] **Step 3: Update the coverage and maintenance docs**

Add the exact problem taxonomy, reserve-chain rule, and selector maintenance rule to the existing docs.

- [ ] **Step 4: Commit**

```powershell
git add docs/e2e-coverage-matrix.md docs/e2e-maintenance.md
git commit -m "docs: maintain multi-user duty problem coverage"
```
