# Task 1 report: enlistment-anchored rank advancement

## Result

Implemented Task 1 only. Initial and manual rank assignments now derive their
next rank date cumulatively from enlistment, while worker promotions retain
their existing promotion-date, one-interval chaining.

## Changes

- Added `compute_initial_next_rank_date()` and
  `compute_next_rank_date_for_soldier()` to the rank-advancement service.
- Cumulative initial schedules walk the resolved track through the current
  rank, honor configured intervals, return `None` for a disabled segment, and
  fall back to one-interval scheduling when enlistment is absent.
- Updated initial/manual registration, import, profile/field-update, and
  enrollment writers to stamp `current_rank_since` from enlistment (or their
  pre-existing fallback) and use cumulative scheduling.
- Interval recomputation now distinguishes initial/manual rows (missing or
  enlistment-equal rank date) from system-promoted rows (rank-date chaining).
- Kept explicit imported next-rank dates overridden and unchanged.
- Left `rank_advancement_worker` promotion callers on
  `compute_next_rank_date(..., since=today)`.

## Strict TDD evidence

1. Added the first cumulative סמ"ר service regression with the independently
   derived literal `2025-09-15`.
2. RED command:

   ```powershell
   & 'C:\Users\Shoham\workspace\Justice\backend\.venv\Scripts\python.exe' -m pytest backend/app/services/tests/test_rank_advancement.py -k "initial or cumulative" -q
   ```

   Output: exit 1; collection failed with
   `ImportError: cannot import name 'compute_initial_next_rank_date'`.
3. Implemented the smallest cumulative domain helper; the same command then
   passed (`1 passed`), followed by the remaining helper cases (`4 passed`).
4. Added the soldier-anchor helper regression. RED used the same focused
   command and failed with
   `ImportError: cannot import name 'compute_next_rank_date_for_soldier'`.
   After implementation, the focused helper suite passed (`5 passed`).
5. Added writer regressions for registration, import, profile/field update,
   and enrollment. RED command:

   ```powershell
   & 'C:\Users\Shoham\workspace\Justice\backend\.venv\Scripts\python.exe' -m pytest backend/tests/unit/test_soldiers_field_updates.py backend/tests/integration/test_soldier_profile.py backend/tests/integration/test_enrollment_routes.py backend/tests/integration/test_registration_routes.py backend/tests/integration/test_import_sessions_config_confirm.py -k "cumulative_enlistment or cumulative_next_rank" -q
   ```

   Output: exit 1; registration/import/enrollment produced the one-interval
   date `2023-01-15` instead of `2025-09-15`.
6. After writer changes, their five focused regressions passed (`5 passed`).

## Final verification

Required Task 1 command:

```powershell
& 'C:\Users\Shoham\workspace\Justice\backend\.venv\Scripts\python.exe' -m pytest backend/app/services/tests/test_rank_advancement.py backend/tests/unit/test_rank_advancement_worker.py backend/tests/unit/test_soldiers_field_updates.py backend/tests/integration/test_soldier_profile.py backend/tests/integration/test_enrollment_routes.py -q
```

Output: exit 0, `96 passed`; only existing testcontainer/TestClient/AnyIO
deprecation warnings were emitted.

Additional touched writer suites:

```powershell
& 'C:\Users\Shoham\workspace\Justice\backend\.venv\Scripts\python.exe' -m pytest backend/app/services/tests/test_rank_advancement.py backend/tests/unit/test_rank_advancement_worker.py backend/tests/unit/test_soldiers_field_updates.py backend/tests/integration/test_soldier_profile.py backend/tests/integration/test_enrollment_routes.py backend/tests/integration/test_registration_routes.py backend/tests/integration/test_import_sessions_config_confirm.py -q
```

Output: exit 0, no failures; only the same repository deprecation warnings.

`git diff --check` also exited 0.

## Notes

- Two pre-existing tests described a missing database interval row as an
  unscheduled rank. The service has runtime defaults, so those expectations
  were stale. They now insert an explicit `months_to_next=NULL` row, which is
  the supported disabled-interval contract and exercises the required NULL
  behavior.
- No Task 2/3 UI or authorization code was modified.
