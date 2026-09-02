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
- `git diff --check`: run after the edits; result recorded in the handoff status.

## Concerns

- This slice does not add smoke annotations, the local runner, API setup, or Playwright project changes; those remain outside the requested package/CI scope.
- The current Playwright config has no named project and uses the existing 390px viewport. Desktop-project configuration belongs to the Playwright-config portion of Task 2 rather than this package/CI-only slice.
- Smoke annotations are not present in the current Task 1 tests; the smoke command is wired to the agreed `@smoke` convention for the later journey slices.
