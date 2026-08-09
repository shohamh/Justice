# Final fix A - future eligibility table report

## Status

Implemented. The table now retains a soldier whose otherwise-current qualification cannot cover a future weapon duty, using the shared duty-date projection to make that decision. A covering planned range now carries its actual scheduled tier through the API and shared formatter, while retaining the established Hebrew wording.

## Files changed

- `backend/app/services/ineligible_soldiers.py`
- `backend/app/services/range_eligibility_projection.py`
- `backend/app/services/weapon_eligibility.py`
- `backend/app/routes/range_qualification_visibility.py`
- `backend/app/services/calendar_shifts.py`
- `backend/app/routes/calendar.py`
- `backend/tests/integration/test_ineligible_soldiers_api.py`
- `frontend/src/api/ineligibleSoldiers.ts`
- `frontend/src/components/ranges/IneligibleSoldiersTable.tsx`
- `frontend/src/utils/rangeEligibilityExplanation.ts`
- `frontend/src/utils/rangeEligibilityExplanation.test.ts`
- `.superpowers/sdd/2026-08-09-range-eligibility-guidance/final-fix-table-report.md`

## TDD evidence

### RED

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest -n 0 tests\integration\test_ineligible_soldiers_api.py -k "currently_qualified_soldier_when_qualification_expires_before_future_duty or actual_higher_tier_of_covering_planned_range" -q
```

Exit code 1. The expiring-but-currently-qualified soldier was absent (`StopIteration`), and the planned-range fact had no `covering_range_type` (`KeyError`).

From `frontend`:

```powershell
npm.cmd test -- --run src/utils/rangeEligibilityExplanation.test.ts
```

Exit code 1. The new planned higher-tier regression received `מטווח לייזר` instead of the actual `מטווח חי`.

### GREEN

From `backend` after the production change:

```powershell
.\.venv\Scripts\python.exe -m pytest -n 0 tests\integration\test_ineligible_soldiers_api.py -k "currently_qualified_soldier_when_qualification_expires_before_future_duty or actual_higher_tier_of_covering_planned_range" -q
```

Exit code 0; 2 passed. Pytest emitted only existing dependency deprecation warnings.

From `frontend` after the production change:

```powershell
npm.cmd test -- --run src/utils/rangeEligibilityExplanation.test.ts
```

Exit code 0; 5 passed.

## Final focused commands

| Command | Outcome |
| --- | --- |
| `backend\.venv\Scripts\python.exe -m pytest -n 0 tests\integration\test_ineligible_soldiers_api.py app\services\tests\test_range_eligibility_projection.py -q` | Exit code 0; 18 passed. |
| `npm.cmd test -- --run src/utils/rangeEligibilityExplanation.test.ts src/components/ranges/IneligibleSoldiersTable.test.tsx` | Exit code 0; 2 files and 11 tests passed. |
| `npm.cmd run lint` | Exit code 0. |
| `npm.cmd run typecheck` | Exit code 0. |
| `git diff --check` | Exit code 0; only line-ending conversion notices. |

## Commit

`fix: preserve future range eligibility table facts` (this commit)

## Concerns

- Focused backend tests emitted only pre-existing `testcontainers.postgres` and Starlette `TestClient` deprecation warnings.
- Git emitted CRLF conversion notices for touched files; `git diff --check` reported no whitespace errors.
