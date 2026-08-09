# Final fix B - calendar warning count report

## Result

Corrected the calendar weapon-ineligibility warning count so it starts at today even when the displayed window includes the past, and so called-up reserve assignees count with active primaries. Authorization and scoped-soldier filtering remain unchanged.

## Changed files

- `backend/app/services/calendar_shifts.py`
  - Clamps the count query's `date_from` to `max(requested_date_from, date.today())`, preserving `date_to`.
  - Includes a reserve assignee only when `called_up_from` is set, matching the existing calendar and shift-detail active-assignee semantics.
- `backend/tests/integration/test_calendar_api.py`
  - Adds `test_calendar_weapon_ineligible_count_excludes_past_duties_and_counts_called_up_reserves`.
- `.superpowers/sdd/2026-08-09-range-eligibility-guidance/final-fix-calendar-report.md`
  - This report.

## TDD evidence

### RED

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_calendar_api.py -k "calendar_weapon_ineligible_count" -q -n 0
```

Run from `backend`. Outcome: exit code 1; 2 tests passed and the new regression failed as intended. The endpoint returned `{"count": 2}` while the regression expected `{"count": 1}`. This proves the pre-fix implementation counted two past primary duties and omitted the future called-up reserve.

### GREEN

Command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_calendar_api.py -k "calendar_weapon_ineligible_count" -q -n 0
```

Run from `backend` after the production change. Outcome: exit code 0; 3 passed. Pytest emitted only existing dependency deprecation warnings for `testcontainers.postgres` and Starlette's `TestClient`.

## Focused verification

```powershell
npm.cmd test -- --run src/components/ShiftDetailPanel.test.tsx
```

Run from `frontend`. Outcome: exit code 0; 1 test file and 10 tests passed. The run emitted existing React `act(...)` warnings from `ShiftDetailPanel` tests.

```powershell
npm.cmd run lint
```

Run from `frontend`. Outcome: exit code 0; `tsc --noEmit && eslint src --max-warnings 0` completed successfully.

```powershell
npm.cmd run typecheck
```

Run from `frontend`. Outcome: exit code 0; `tsc --noEmit` completed successfully.

```powershell
git diff --check
git diff --cached --check
```

Run from the repository root. Outcome: both exit code 0 with no whitespace errors. Git printed only line-ending conversion notices for touched and pre-existing modified files.

## Commit

Implementation commit: `52ca8f72 fix: correct calendar range warning count`

## Concerns

- The focused frontend test passes but emits pre-existing React `act(...)` warnings; this backend-only fix did not modify those tests or component behavior.
- The shared worktree contained unrelated staged and unstaged changes before this fix. They were neither modified nor included in either fix commit.
