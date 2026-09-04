# Task 1 report - shared Playwright fixtures

## Status

Task 1 is implemented and committed in two commits:

- `a837d08e test: add shared browser role fixtures`
- `ff187b19 test: stabilize shared browser auth fixtures`

The second commit makes storage-state paths independent of the invoking working
directory and exercises saved states through Playwright's configured page
fixture, avoiding manual contexts without a `baseURL`.

## Files changed

- `frontend/playwright.config.ts`
- `frontend/tests/e2e/fixtures/auth.ts`
- `frontend/tests/e2e/fixtures/data.ts`
- `frontend/tests/e2e/fixtures/test.ts`
- `frontend/tests/e2e/fixtures/auth.spec.ts`
- `frontend/tests/e2e/assignments.spec.ts`
- `frontend/tests/e2e/duty_calendar.spec.ts`
- `frontend/tests/e2e/duty_config.spec.ts`
- `frontend/tests/e2e/exemption_requests.spec.ts`
- `frontend/tests/e2e/exemptions.spec.ts`
- `frontend/tests/e2e/feedback_screenshot.spec.ts`
- `frontend/tests/e2e/hierarchy.spec.ts`
- `frontend/tests/e2e/personal_constraints.spec.ts`
- `frontend/tests/e2e/seed_views.spec.ts`

The pre-existing untracked strategy and plan documents under
`docs/superpowers/` were preserved and excluded from both Task 1 commits.

## Implemented behavior

- `loginAs(page, role)` uses the visible login form for the four accounts
  verified in `backend/app/scripts/seed.py`: soldier `1000003`, commander
  `2000001`, duty manager `2500001`, and admin `1000001`, using the documented
  seed password.
- Global setup signs in each role and writes ignored browser states under
  `frontend/.playwright/auth`; `roleStorageState(role)` returns a stable path
  based on the fixture module rather than `process.cwd()`.
- The shared `test` fixture opens `/` before each test, allowing non-login specs
  to use saved role state. Nine duplicated admin login helpers were removed.
- `admin_flow.spec.ts` and `login.spec.ts` remain untouched on the visible login
  path, including the dedicated forced-password-change flow.
- `createUniqueName(prefix)` adds a process/run identifier and monotonic
  sequence.
- `createScenarioData(request)` refreshes an authenticated admin state through
  `/api/auth/refresh`, creates exactly one duty type, duty location, and
  exemption type through existing production endpoints, validates each API
  response, and returns stable `{id, name}` resources for browser assertions.
- Playwright remains serial (`workers: 1`, `fullyParallel: false`), Chromium
  only, at the existing 390x844 viewport, with video explicitly disabled.

## Commands and outputs

Run from `frontend` unless stated otherwise.

- Focused runtime RED:
  `npx playwright test tests/e2e/fixtures/auth.spec.ts --workers=1`
  - Did not reach fixture assertions. Global setup remained on `/login` and
    failed at `auth.ts:29` after 5 seconds.
  - Boundary diagnosis showed ports 5173 and 8000 belonged to the main checkout,
    not this worktree. Direct and proxied seeded login requests returned HTTP
    500 for the tested accounts (and one later 429 after repeated attempts).
    Therefore browser runtime behavior is unverified against a healthy seeded
    stack; no production auth/backend change was made.
- Focused fixture TypeScript:
  `npx tsc --noEmit --incremental false --target ES2022 --lib 'ES2022,DOM,DOM.Iterable' --module ESNext --moduleResolution Bundler --strict --skipLibCheck --esModuleInterop --allowSyntheticDefaultImports --types node tests/e2e/fixtures/auth.spec.ts tests/e2e/fixtures/auth.ts tests/e2e/fixtures/data.ts tests/e2e/fixtures/test.ts playwright.config.ts`
  - Passed, exit 0.
- Focused fixture lint:
  `npx eslint playwright.config.ts tests/e2e/fixtures --ext .ts --max-warnings 0`
  - Passed, exit 0.
- Frontend application typecheck:
  `npm run typecheck`
  - Passed, exit 0.
- Fixture discovery:
  `npx playwright test tests/e2e/fixtures/auth.spec.ts --list`
  - Passed; 9 tests discovered in 1 file.
- Full E2E discovery:
  `npx playwright test --list`
  - Passed; 24 tests discovered in 12 files.
- Broad E2E lint:
  `npx eslint playwright.config.ts tests/e2e --ext .ts --max-warnings 0`
  - Blocked by two pre-existing unused locals in `hierarchy.spec.ts`:
    `targetName` at line 135 and `wasVisible` at line 156. Task 1 did not add
    those locals.
- Broad E2E strict TypeScript:
  custom `npx tsc --noEmit ...` over `playwright.config.ts` and all
  `tests/e2e/**/*.ts` files.
  - Blocked by four pre-existing element-type errors in
    `feedback_screenshot.spec.ts` at lines 29, 31, 32, and 34 (`decode`,
    `naturalWidth`, `naturalHeight`, and `CanvasImageSource`). Task 1 only
    changed that spec's authentication imports/setup.
- Repository checks from the worktree root:
  `git diff --check 980c5ad0..HEAD`
  - Passed, exit 0.
  `git diff --exit-code 980c5ad0..HEAD -- frontend/tests/e2e/admin_flow.spec.ts frontend/tests/e2e/login.spec.ts`
  - Passed, confirming both dedicated visible-login specs are unchanged.
  `git diff --name-only 980c5ad0..HEAD -- backend`
  - Empty, confirming no backend changes.

## Self-review

- Requirements were checked against `task-1-brief.md`, the seed script, login
  UI/AuthContext, auth refresh cookie flow, duty-config route schemas, all
  current E2E specs, Playwright config, and CI's seed/browser setup.
- No credentials or endpoints were guessed. The seed supports all four required
  roles, including the scoped duty manager whose persisted role is recomputed by
  `assign_dm_scope`.
- Saved auth persists only the HttpOnly refresh cookie; each page mount or setup
  request obtains a fresh access token through the existing refresh endpoint.
- Scenario setup fails loudly on non-2xx or malformed API responses and creates
  prerequisites only. It does not weaken authorization or add test-only backend
  routes.
- The final diff removes all `loginAsAdmin` duplicates, uses saved state for
  tests that are not testing login, keeps accessible/stable existing selectors,
  and preserves the forced-password visible flow.
- No unrelated dirty files were staged or committed.

## Concerns

- The browser fixture suite still needs a run against a healthy database seeded
  by this branch's expected startup flow; the currently running main-checkout
  backend returns HTTP 500 for seeded login.
- The committed `admin_flow.spec.ts` expects the bootstrap admin's one-time
  password, while CI currently runs `seed.py`, which resets that account to the
  shared seed password and clears `must_change_password`. The brief required the
  forced-password test to remain visible and untouched; deterministic isolation
  for that test remains follow-up work.
- Broad E2E lint/type checking is not fully green because of the unrelated
  `hierarchy.spec.ts` and `feedback_screenshot.spec.ts` issues listed above.

## Review-finding fix: Chrome-only Playwright execution

### Files changed

- `frontend/playwright.config.ts`
- `frontend/tests/e2e/fixtures/auth.ts`

### Change

- The project-level Playwright `use` configuration now selects the supported
  branded Chrome channel with `channel: "chrome"` while retaining the Chromium
  engine type required by Playwright's API.
- Global setup now launches the same Chrome channel via
  `chromium.launch({ channel: "chrome" })`; its role-login and storage-state
  fixture behavior is otherwise unchanged.

### Commands and outputs

- Focused configuration RED check:
  - Confirmed both required Chrome-channel declarations were absent before the
    fix. The check exited 1 with `playwright.config.ts does not select the
    Chrome channel.` and `auth.ts global setup does not launch the Chrome
    channel.`
- Focused configuration check:
  - Passed, exit 0: both `channel: "chrome"` declarations are present.
- Chrome-channel launch:
  - `node --input-type=module -e "import { chromium } from '@playwright/test'; const browser = await chromium.launch({ channel: 'chrome' }); console.log('Chrome channel launched: ' + browser.version()); await browser.close();"`
  - Passed, exit 0: `Chrome channel launched: 152.0.7977.65`.
- Focused fixture TypeScript:
  - `npx tsc --noEmit --incremental false --target ES2022 --lib 'ES2022,DOM,DOM.Iterable' --module ESNext --moduleResolution Bundler --strict --skipLibCheck --esModuleInterop --allowSyntheticDefaultImports --types node tests/e2e/fixtures/auth.spec.ts tests/e2e/fixtures/auth.ts tests/e2e/fixtures/data.ts tests/e2e/fixtures/test.ts playwright.config.ts`
  - Passed, exit 0.
- Targeted lint:
  - `npx eslint playwright.config.ts tests/e2e/fixtures/auth.ts --ext .ts --max-warnings 0`
  - Passed, exit 0.
- Fixture discovery:
  - `npx playwright test tests/e2e/fixtures/auth.spec.ts --list`
  - Passed, exit 0: 9 tests discovered in 1 file.

### Self-review

- This corrects the sole Task 1 review finding without changing browser
  viewport, serial execution, video policy, login flow, or saved-state paths.

### Commit

- `29d754e5 fix: use Chrome for Playwright E2E`

## Fix round: isolate the forced-password admin flow

### Scope and findings

This fix round reviewed the uncommitted Task 1 changes in:

- `frontend/playwright.admin-flow.config.ts`
- `frontend/playwright.config.ts`
- `frontend/tests/e2e/fixtures/admin-flow.ts`
- `frontend/tests/e2e/fixtures/auth.spec.ts`
- `frontend/tests/e2e/admin_flow.spec.ts`

The dedicated config is isolated from seeded-role setup: it matches only
`admin_flow.spec.ts` and uses `fixtures/admin-flow.ts` as its sole global setup.
The default config ignores that spec and continues to use
`fixtures/auth.ts` for seeded role storage states. The dedicated config also
preserves the required Chrome channel, 390x844 mobile viewport, serial worker,
trace-on-first-retry, and `video: "off"` settings.

`admin-flow.ts` invokes the existing `app.scripts.reset_password` module with
the known bootstrap admin personal number and password. That module sets
`must_change_password=True`, so the visible forced-password journey can start
from a deterministic precondition without invoking the seeded-role global
setup. It fails the setup on a missing Python process or non-zero reset result.

The role assertions were checked against `UnifiedNav` and the shared
permission helpers: soldiers have neither management tab, commanders have
commander access but not planning access, and duty managers/admins have both.
Saved-session assertions now verify both the expected personal number and the
API role (`duty_manager` for the `dutyManager` fixture key).

### Correction made

`auth.spec.ts` used `toHaveJSON`, which is not a matcher on Playwright's
`APIResponse` assertion type in this repository's installed version. The
assertion now parses `response.json()` and uses the supported Jest-style
`toEqual(expect.objectContaining(...))` matcher. No production code or
unrelated worktree files were changed.

### Focused verification

All commands were run from `frontend`:

- Focused TypeScript over both configs, the admin flow, and the shared fixture
  files: passed, exit 0.
- Focused ESLint over both configs, the admin flow, and the shared fixture
  files: passed with `--max-warnings 0`, exit 0.
- `npx playwright test --config=playwright.admin-flow.config.ts --list`:
  passed; exactly 1 test in 1 file, `admin_flow.spec.ts`.
- `npx playwright test --config=playwright.config.ts --list`:
  passed; 23 tests in 11 files, with no `admin_flow.spec.ts` entry.

No Playwright runtime test was claimed in this fix round. A healthy backend,
database, and seeded/reset account were not established here, so browser
runtime behavior remains unverified; the earlier report records the seeded
login HTTP 500 boundary diagnosis.

### Commit scope

The fix commit includes the two Playwright configs, the admin-flow global
setup, the corrected role/session spec, the existing forced-password spec, and
this report. The pre-existing untracked strategy and plan documents under
`docs/superpowers/` remain untouched and uncommitted.

### Completion verification (2026-09-02)

- `npx playwright test --config=playwright.admin-flow.config.ts --list`: passed, 1 test in 1 file.
- `npx playwright test --list`: passed, 23 tests in 11 files.
- `git diff --check`: passed.
- Inspected only the four requested implementation files for obvious syntax/config issues; none found.
- Runtime browser tests were not run; this task requested test discovery only.

## Task 1 re-review: authenticated identity checks and executable admin-flow gate

### Findings confirmed

The two Important re-review findings reproduced against commit `30f94056`:

- The saved-session identity assertion called bearer-protected `/api/me` with
  only the stored refresh cookie. The access token returned by
  `/api/auth/refresh` was never attached, so the role and personal-number
  assertions could not authenticate the endpoint they were intended to check.
- `playwright.admin-flow.config.ts` correctly isolated the forced-password
  journey, but neither `frontend/package.json` nor CI invoked it. The default
  config intentionally ignored `admin_flow.spec.ts`, leaving the flow absent
  from the executable test gate.

### Files changed

- `frontend/tests/e2e/fixtures/auth.spec.ts`
- `frontend/package.json`
- `.github/workflows/ci.yml`
- `.superpowers/sdd/2026-09-01-browser-automation-tests/task-1-report.md`

No Playwright config, application frontend code, or backend production code was
changed. The pre-existing untracked strategy and plan documents under
`docs/superpowers/` remain untouched.

### Fixes

- Each saved role session now posts to `/api/auth/refresh`, verifies the refresh
  succeeded, reads the access token, and sends `/api/me` an explicit
  `Authorization: Bearer <token>` header before asserting the seeded personal
  number and API role.
- `frontend/package.json` now exposes
  `test:e2e:admin-flow = playwright test --config=playwright.admin-flow.config.ts`.
- CI invokes `npm run test:e2e` first. That normal run keeps the default
  config's `admin_flow.spec.ts` exclusion and consumes the database's ordinary
  seeded role credentials.
- CI then invokes `npm run test:e2e:admin-flow`. Its dedicated global setup runs
  the existing `app.scripts.reset_password` command, changing bootstrap admin
  `1000001` to `ChangeMeOnFirstLogin!` with `must_change_password=True` only
  after the seeded-role suite is finished. The forced-flow CI step prepends
  `backend/.venv/bin` to `PATH` so the reset subprocess uses the Linux backend
  venv installed earlier in the job.
- Both configs still select branded Chrome, use one serial worker with
  `fullyParallel: false`, retain the 390x844 viewport, and keep video disabled.

### RED evidence

All checks were run from the named worktree.

- A focused Node contract check failed with all three expected diagnostics:
  `/api/me is not called with bearer headers`,
  `test:e2e:admin-flow package script is missing`, and
  `CI does not run normal E2E before forced-password E2E`.
- `npm run test:e2e:admin-flow -- --list` failed with
  `Missing script: "test:e2e:admin-flow"`.

### Focused verification

Run from `frontend` unless stated otherwise:

- Focused Node contract/static check over `auth.spec.ts`, both Playwright
  configs, package scripts, and CI ordering/state setup: passed, exit 0,
  `Task 1 re-review contract satisfied.`
- `npx playwright test --config=playwright.config.ts --list`: passed, exit 0;
  23 tests in 11 files, with no `admin_flow.spec.ts` entry.
- `npx playwright test --config=playwright.admin-flow.config.ts --list`:
  passed, exit 0; exactly 1 test in 1 file, `admin_flow.spec.ts`.
- Focused strict TypeScript over both configs, the admin flow, and shared
  fixture files: passed, exit 0.
- Focused ESLint over both configs, the admin flow, and shared fixture files:
  passed with `--max-warnings 0`, exit 0.
- `git diff --check`: passed, exit 0 before the report append.

### Runtime boundary and concerns

This npm version stripped the attempted trailing `--list` argument from package
script invocations, so both commands attempted runtime execution instead of
discovery. Those attempts were useful boundary checks but are not green browser
test evidence:

- The normal package script reached shared auth setup but the locally running
  stack stayed on `/login`, matching the report's existing unhealthy/unseeded
  local-stack concern.
- The dedicated package script reached its reset setup and failed because this
  worktree's ambient `DATABASE_URL` resolves the Docker-only host `db` outside
  Docker. CI does not use that ambient value: its job-level `DATABASE_URL`
  targets `localhost`, and the forced-flow step now exposes the already-created
  backend venv Python to the reset subprocess.

Accordingly, static/config/discovery verification is green, while browser
runtime remains unverified locally. The CI ordering and environment now provide
the intended seed-then-reset state transition without weakening production
authorization or changing backend production code.

## Task 1 completion: branded Chrome CI install (2026-09-02)

The CI browser install command was aligned with the `channel: "chrome"` setting
used by both Playwright configurations:

- `.github/workflows/ci.yml`: `npx playwright install --with-deps chrome`

Exact verification results from the named worktree:

- `npx playwright test --config=playwright.config.ts --list`: exit 0; `Total: 23 tests in 11 files`.
- `npx playwright test --config=playwright.admin-flow.config.ts --list`: exit 0; `Total: 1 test in 1 file`.
- Node config/static contract check over CI, package scripts, auth fixture, and both Playwright configs: exit 0; `Task 1 config/static contract satisfied.`
- `git diff --check`: exit 0; Git emitted only LF-to-CRLF working-copy warnings for the three modified files.

No browser runtime tests were run; this completion pass is discovery/config/static
verification only.
