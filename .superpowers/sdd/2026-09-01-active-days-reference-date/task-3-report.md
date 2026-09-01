# Task 3 report — registration, enrollment, profile DTOs, and validation

## Delivered

- Added nullable `unit_join_date` to registration, enrollment, soldier, and authenticated-profile DTOs, plus their frontend API types.
- Registration accepts and persists the date, requires it when the configured active-days reference date is before today, and preserves nullable records at the reference-date boundary.
- Shared soldier-date validation now enforces `enlistment_date <= unit_join_date <= enrolled_at` and `unit_join_date < discharge_date`.
- Enrollment reviewers can correct the date before activation; the enrollment DTO and approval modal carry the value.
- Registration validates ordering in Hebrew, and profile views display a stored unit-entry date.
- Post-activation edits were deliberately not added: Task 4 owns the approval workflow required by the spec.

## Tests added

- Backend registration tests for equal boundaries, discharge equality rejection, post-reference missing date rejection, and nullable reference-boundary fallback.
- Backend enrollment integration test for pre-activation correction.
- Frontend tests for registration input/order validation, enrollment payload wiring, and profile/modal display.

## Verification

- Passed: Python compilation of all modified backend modules.
- Passed: `git diff --check`.
- Unverified: focused backend pytest ran for 60 seconds without output and hit the command timeout before reporting a result.
- Unverified: frontend Vitest/typecheck could not resolve the worktree's frontend dependencies (`vitest`, `@vitejs/plugin-react`, React/Axios types), despite the shared dependency path being available; no frontend tests executed.
- Unrun: frontend lint, for the same dependency-resolution issue.

## Scope and concerns

- This task intentionally leaves post-activation changes read-only. The existing field-update approval flow will be extended in Task 4.
- Re-run focused backend/frontend checks from a worktree with its own installed dependencies (and a responsive test database) before integration.

## Fix round 1 (2026-09-01)

### Findings addressed

- Enrollment PATCH now parses `unit_join_date` as a Pydantic `date` before assignment and shared soldier-date validation. Valid pre-activation corrections persist successfully; dates before enlistment return the expected 400 validation code instead of raising `TypeError`.
- The unauthenticated registration-settings DTO now exposes `active_days_reference_date`. Registration mirrors backend requiredness: `unit_join_date` is required only when today is after that configured date, blocks step progression when missing, and shows the existing Hebrew required-field feedback.
- Enrollment DTOs now expose `enrolled_at`, allowing the approval modal to apply the same enlistment/enrollment/discharge ordering checks with Hebrew messages before sending the PATCH.
- Repaired the abandoned assertions to use the application's established dot-formatted date display and added regressions for enrollment correction, invalid enrollment ordering, registration required/reference-boundary behavior, and legacy profile fallback display.

### Verification

The earlier unverified results above are superseded by these completed checks:

- `C:\Users\Shoham\workspace\Justice\backend\.venv\Scripts\python.exe -m pytest -q -n 0 app/services/tests/test_registration.py::test_register_rejects_unit_join_date_on_discharge_date tests/integration/test_enrollment_routes.py::test_enrollment_reviewer_can_correct_unit_join_date_before_activation tests/integration/test_enrollment_routes.py::test_enrollment_reviewer_cannot_set_unit_join_date_before_enlistment tests/integration/test_public_settings.py::test_registration_public_settings_no_auth_required tests/integration/test_public_settings.py::test_registration_public_settings_defaults_to_none` — passed, 5 tests.
- `C:\Users\Shoham\workspace\Justice\backend\.venv\Scripts\python.exe -m pytest -q -n 0 app/services/tests/test_registration.py tests/integration/test_registration_routes.py tests/integration/test_enrollment_routes.py tests/integration/test_public_settings.py tests/integration/test_me_capabilities.py tests/integration/test_soldier_profile.py tests/integration/test_soldiers_api.py` — passed, 125 tests.
- `npx vitest run src/pages/RegisterPage.test.tsx src/components/EnrollmentApprovalModal.test.tsx src/components/UnifiedSoldierModal.test.tsx src/pages/ProfilePage.test.tsx --maxWorkers=1 --no-file-parallelism` — passed before final scope cleanup, 4 files / 54 tests; the final focused rerun is recorded below.
- `npm run typecheck` — passed (`tsc --noEmit`).
- `npm run lint` — passed (`tsc --noEmit` and ESLint with zero warnings).
- `git diff --check` — passed.

### Remaining scope and concerns

- Post-activation changes remain intentionally excluded; Task 4 owns the approval workflow.
- `npm ci` reported 9 dependency audit findings (4 moderate, 5 high); no dependency versions were changed in Task 3.

### Final verification before focused commit (2026-09-01)

- Passed: `C:\Users\Shoham\workspace\Justice\backend\.venv\Scripts\python.exe -m pytest -q -n 0 app/services/tests/test_registration.py tests/integration/test_registration_routes.py tests/integration/test_enrollment_routes.py tests/integration/test_public_settings.py tests/integration/test_me_capabilities.py tests/integration/test_soldier_profile.py tests/integration/test_soldiers_api.py` — 125 tests passed in 61.6 seconds.
- Passed: `npx vitest run src/pages/RegisterPage.test.tsx src/components/EnrollmentApprovalModal.test.tsx src/components/UnifiedSoldierModal.test.tsx src/pages/ProfilePage.test.tsx --maxWorkers=1 --no-file-parallelism` — 4 files and 52 tests passed in 46.08 seconds.
- Passed: `npm run typecheck` — `tsc --noEmit` exited 0.
- Passed: `npm run lint` — TypeScript and ESLint exited 0 with zero warnings.
- Passed: `git diff --check` — no whitespace errors.

The focused verification confirms the two reviewer findings: enrollment accepts and validates `unit_join_date` as a date, and registration requiredness/feedback follows the configured public reference date. Regression coverage includes enrollment correction and invalid ordering, plus registration required-after-reference and optional-at-reference-boundary behavior.

Focused code commit: `9fcca8c4` (`fix: complete active days reference date task 3`).

### Final commit/status reconciliation (2026-09-01)

- Task-scoped regression hardening commit: `d0cfc8c4` (`test: cover registration date requiredness progression`).
- Final Task 3 commit range: `9fcca8c4..d0cfc8c4` (inclusive commits: `9fcca8c4`, `83b10a26`, `d0cfc8c4`).
- Final focused regression after the hardening change: `npx vitest run src/pages/RegisterPage.test.tsx --maxWorkers=1 --no-file-parallelism` — 1 file and 11 tests passed in 3.32 seconds.
- Final worktree status: tracked Task 3 files clean; intentionally preserved unrelated untracked files are `docs/superpowers/plans/2026-09-01-active-days-reference-date.md` and `docs/superpowers/specs/2026-09-01-active-days-reference-date.md`.

## Fix round 2 (2026-09-01)

- Replaced `RegisterPage` UTC calendar-day calculations with the shared local-date `todayIso()` helper, including configured requiredness and the page's related date-order checks.
- Added a local Israel-time boundary regression at `2026-06-15 00:30`, where UTC is still June 14; the test verifies `todayIso()` returns June 15 and registration remains required when the reference date is June 14. The regression failed against the old UTC implementation and passed after the fix.
- Passed: `npx vitest run src/pages/RegisterPage.test.tsx --maxWorkers=1 --no-file-parallelism` — 1 file and 11 tests passed in 5.56 seconds.
- Passed: `npm run typecheck` — `tsc --noEmit` exited 0.
- Passed: `npm run lint` — TypeScript and ESLint exited 0 with zero warnings.
- Passed: `git diff --check` — no whitespace errors.
