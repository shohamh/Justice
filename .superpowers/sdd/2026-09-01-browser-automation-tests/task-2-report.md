# Task 2A report - browser command and CI determinism

## Status

Implemented the package/CI slice only. Existing Task 1 browser fixture and CI changes were preserved.

## Changes

- Added `npm run test:e2e:smoke`, using the explicit `@smoke` grep convention.
- Added `npm run test:e2e:full`, running the regular suite and the dedicated `playwright.admin-flow.config.ts` forced-password flow.
- CI now invokes the smoke tier for pull requests and the full tier for pushes.
- Preserved the existing Postgres service, migrations, seed, backend/frontend startup, health checks, Chrome installation, serial Playwright configuration, and no-video setting.

## Verification

- Confirmed the Task 1 commits are ancestors of this slice; no existing Task 1 changes were reverted.
- Confirmed the CI browser installation remains `npx playwright install --with-deps chrome`.
- Confirmed the CI migration, seed, backend startup, frontend build/preview, and health-check commands remain unchanged.
- `git diff --check`: passed before commit and again on the committed diff.
- Package script discovery: passed; the regular suite lists 23 tests and the dedicated forced-password config lists 1 test.
- Smoke discovery: lists 0 tests because no current Task 1 test has an `@smoke` annotation.
- `npm run test:e2e:smoke` and `npm run test:e2e:full`: attempted against the local stack; both reached the existing auth global setup and failed at `fixtures/auth.ts:31` because login remained at `http://localhost:5173/login`. Browser runtime results are therefore unverified.

## Task 2A follow-up verification (2026-09-02)

- `npx playwright test --config=playwright.discovery.config.ts --grep "@smoke" --list`: passed; listed 3 tests in 3 files (`login.spec.ts`, `personal_constraints.spec.ts`, and `seed_views.spec.ts`).
- `npx playwright test --config=playwright.discovery.config.ts --list`: passed; listed 23 tests in 11 files.
- Static CI/admin/discovery assertions: passed; CI push triggers include `master, dev`, pull-request triggers include `master, dev`, pull requests run `npm run test:e2e:smoke`, pushes run `npm run test:e2e:full`, and admin-flow checks `.venv\\Scripts\\python.exe` then `.venv\\bin\\python` before falling back to `python`.
- `npm run typecheck`: passed (`tsc --noEmit`).
- `git diff --check`: passed.
- `git status --short`: intended changed files are the CI workflow, Task 2 report, admin-flow fixture, three smoke specs, and discovery config. The unrelated untracked plan/spec files were left untouched and are excluded from the commit.

## Concerns

- This slice does not add smoke annotations, the local runner, API setup, or Playwright project changes; those remain outside the requested package/CI scope.
- The current Playwright config has no named project and uses the existing 390px viewport. Desktop-project configuration belongs to the Playwright-config portion of Task 2 rather than this package/CI-only slice.
- Smoke annotations are not present in the current Task 1 tests; the smoke command is wired to the agreed `@smoke` convention for the later journey slices.
