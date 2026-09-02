# Browser Automation Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand Justice's existing Playwright harness into a reliable, real-stack safety net for human-critical multi-role workflows.

**Architecture:** Keep browser tests in `frontend/tests/e2e`, with shared role authentication, deterministic data helpers, and journey-oriented specs. The tests run against the real FastAPI application and PostgreSQL database; setup uses trusted APIs or seeded fixtures, while assertions use the browser and visible UI. CI keeps the current Postgres/migration/seed/service startup and adds explicit smoke/full browser tiers.

**Tech Stack:** Playwright Test, Chromium, Vite preview, FastAPI, PostgreSQL, Alembic, GitHub Actions, TypeScript.

**Spec:** `docs/superpowers/specs/2026-09-01-browser-automation-strategy.md`

## Global Constraints

- Test Chrome desktop and the existing 390px mobile viewport only.
- Use the real frontend, backend, and PostgreSQL stack for workflow tests.
- Keep tests serial until database and account isolation are proven.
- Use one CI retry maximum; retry-passing tests remain failures for triage.
- Do not enable video by default.
- Preserve Hebrew/RTL behavior and assert user-visible translated states.
- Do not weaken backend authorization to make browser setup easier.

---

### Task 1: Establish shared Playwright fixtures

**Files:**
- Create: `frontend/tests/e2e/fixtures/test.ts`
- Create: `frontend/tests/e2e/fixtures/auth.ts`
- Create: `frontend/tests/e2e/fixtures/data.ts`
- Modify: `frontend/playwright.config.ts`
- Modify: existing `frontend/tests/e2e/*.spec.ts` login helpers

**Interfaces:**
- `loginAs(page, role: "soldier" | "commander" | "dutyManager" | "admin")` navigates through the visible login flow and returns an authenticated page.
- `roleStorageState(role)` supplies a saved authenticated state for tests that do not test login itself.
- `createUniqueName(prefix)` returns a run-unique domain name.
- `createScenarioData(request)` creates only test prerequisites and returns stable IDs/names for browser assertions.

- [ ] Inventory the seeded account identifiers and the existing login/password-change behavior in `frontend/tests/e2e` and `backend/app/scripts/seed.py`.
- [ ] Write a fixture test that authenticates each role and verifies the expected landing page or permission boundary.
- [ ] Run `npx playwright test frontend/tests/e2e/<fixture-test> --workers=1` and confirm the new role fixture fails before implementation.
- [ ] Implement role-specific login and storage-state reuse without changing production authentication behavior.
- [ ] Replace duplicated admin login helpers with the shared fixture while leaving the dedicated forced-password-change test on the visible login path.
- [ ] Run the fixture and existing E2E specs with `npx playwright test --workers=1`.
- [ ] Commit as `test: add shared browser role fixtures`.

### Task 2: Make test data and stack startup deterministic

**Files:**
- Create: `frontend/tests/e2e/support/api.ts`
- Create: `scripts/e2e.ps1`
- Modify: `frontend/playwright.config.ts`
- Modify: `.github/workflows/ci.yml`
- Modify: `frontend/package.json`

**Interfaces:**
- `apiRequest(method, path, body?)` performs authenticated setup/cleanup requests and fails with the response body on non-2xx status.
- `resetE2eData()` prepares the known E2E data boundary without deleting unrelated development data.
- `scripts/e2e.ps1` starts or validates Postgres, applies migrations, seeds the database, starts backend/frontend, waits on health URLs, and invokes Playwright.

- [ ] Document the exact database, migration, seed, backend health, and frontend health commands already used by CI.
- [ ] Add a failing smoke invocation that runs twice from a clean database and records different unique test data names.
- [ ] Implement the setup API and run-scoped unique identifiers; do not make tests depend on order or prior test-created records.
- [ ] Add the local PowerShell runner using the repository's Windows startup conventions and a non-destructive, explicitly scoped database setup.
- [ ] Configure Playwright `webServer` only if it can manage both services without conflicting with `dev.ps1`; otherwise make the runner the single local orchestration entry point and keep CI explicit.
- [ ] Add `npm run test:e2e:smoke` and `npm run test:e2e:full` scripts with explicit project/grep selection.
- [ ] Update CI to publish the HTML report, trace, screenshots, and backend/frontend logs on failure.
- [ ] Run the smoke command twice from fresh seeded databases.
- [ ] Commit as `test: make browser test setup deterministic`.

### Task 3: Add the cross-role request and approval journeys

**Files:**
- Create: `frontend/tests/e2e/smoke/soldier_requests.spec.ts`
- Create: `frontend/tests/e2e/smoke/approval_workflow.spec.ts`
- Create: `frontend/tests/e2e/smoke/authorization_boundaries.spec.ts`
- Modify: production components only where stable accessible labels or targeted test IDs are missing.

**Interfaces:**
- `createScenarioData` returns the request creator, authorized reviewer, unauthorized reviewer, request identifier, and future dates.
- `loginAs` opens a role-specific browser context.
- Each workflow verifies UI state after navigation/refresh, not just the initiating click.

- [ ] Write the soldier request test: open own requests, submit a future request, and assert the request appears in the list.
- [ ] Run it against the real stack and verify a genuine failure if a required button, route, or refresh is broken.
- [ ] Implement only the fixture/setup required for the test.
- [ ] Write the approval test with separate soldier and reviewer contexts: create request, approve it, refresh both contexts, and assert pending removal plus soldier-visible status.
- [ ] Write the rejection test with a required reason and assert the reason/status in the relevant UI.
- [ ] Write the authorization test for out-of-scope work and assert both route/action denial and absence of unauthorized mutation.
- [ ] Add stable selectors only at the user-action/state boundaries needed by these tests.
- [ ] Run the three specs at desktop and 390px mobile viewports.
- [ ] Commit as `test: cover request approval browser journeys`.

### Task 4: Add ordinary-user rendering and admin smoke journeys

**Files:**
- Create: `frontend/tests/e2e/smoke/regular_user_views.spec.ts`
- Create: `frontend/tests/e2e/smoke/admin_configuration.spec.ts`
- Create: `frontend/tests/e2e/smoke/table_interactions.spec.ts`
- Modify: existing page components only for missing stable selectors or user-visible error states.

- [ ] Write the regular-user test covering homepage, a representative table, calendar, navigation, and a page refresh.
- [ ] Add assertions for row visibility, table headers, empty state, and absence of uncaught page errors.
- [ ] Write the admin configuration test for one core item and verify it is visible in the downstream page that consumes it.
- [ ] Write table interaction coverage for filtering, pagination/sorting where supported, loading completion, empty state, and a controlled API error state.
- [ ] Run each test once in desktop and once in mobile mode; record any intentional responsive differences as assertions rather than viewport skips.
- [ ] Commit as `test: cover regular views and table regressions`.

### Task 5: Separate smoke/full tiers and stabilize diagnostics

**Files:**
- Modify: `frontend/playwright.config.ts`
- Modify: `frontend/package.json`
- Modify: `.github/workflows/ci.yml`
- Create: `docs/e2e-coverage-matrix.md`
- Create: `frontend/tests/e2e/support/diagnostics.ts`

- [ ] Add explicit `@smoke` and `@full` annotations or project grep conventions matching the ten initial journeys.
- [ ] Configure desktop and mobile projects with Chromium only; keep video disabled and preserve trace/screenshot-on-failure behavior.
- [ ] Add diagnostic hooks for page errors, console errors, and failed API requests, filtering only known non-actionable browser noise.
- [ ] Ensure CI retries once but marks retry-passing tests in the report.
- [ ] Add the coverage matrix with role, journey, critical assertion, viewport, CI tier, and owning spec.
- [ ] Run `npm run test:e2e:smoke` on a clean stack and then `npm run test:e2e:full`.
- [ ] Run the existing backend/frontend checks separately and report their status separately from browser checks.
- [ ] Commit as `ci: gate critical browser journeys`.

### Task 6: Prove the suite catches regressions and define maintenance rules

**Files:**
- Modify: `docs/e2e-coverage-matrix.md`
- Create: `docs/e2e-maintenance.md`
- Add focused regression commits in the relevant feature test/spec files during validation.

- [ ] Intentionally break a selector/button action in a disposable branch and confirm the relevant smoke test fails with an actionable artifact.
- [ ] Intentionally break the post-approval refresh/state update and confirm the cross-role test fails even if the mutation endpoint returns success.
- [ ] Intentionally break an authorization visibility condition and confirm the unauthorized journey fails.
- [ ] Restore the behavior and rerun the smoke suite in both viewports.
- [ ] Document rules for new features: identify the human-critical journey, add/update the browser test, use stable selectors, and include the mutation consequence.
- [ ] Define the release threshold: several consecutive clean CI runs, no retry-only green tests, and artifacts sufficient to classify failures.
- [ ] Commit as `docs: document browser test coverage and maintenance`.

## Verification commands

Run from `frontend` unless noted:

```powershell
npm run test:e2e:smoke
npm run test:e2e:full
npx playwright test --project=chromium --workers=1
```

Run the existing suites separately:

```powershell
cd ..\backend
.venv\Scripts\pytest.exe -q
cd ..\frontend
npm run typecheck
npm run lint
npx vitest run --maxWorkers=1 --no-file-parallelism
```

Before claiming completion, verify fresh-database repeatability, both viewport projects, failure artifacts, CI job results, `git diff --check`, and the coverage matrix. Treat timeouts or interrupted commands as unverified.
