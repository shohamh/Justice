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

## Review-finding follow-up (P1/P2)

### P1: predecessor interval recomputation

Cause: `recompute_affected_soldiers()` selected only rows whose current rank
equaled the changed interval rank. Initial/manual rows at a later rank use the
predecessor in their cumulative enlistment schedule, so they were omitted.

Regression added:
`test_set_predecessor_interval_recomputes_initial_rank_but_preserves_override`.
It changes טוראי from 10 to 12 months and proves a non-overridden initial סמ"ר
changes from `2025-09-15` to `2025-11-15`; an overridden סמ"ר remains
`2099-01-01`.

RED command:

```powershell
& 'C:\Users\Shoham\workspace\Justice\backend\.venv\Scripts\python.exe' -m pytest backend/app/services/tests/test_rank_advancement.py::test_set_predecessor_interval_recomputes_initial_rank_but_preserves_override -q
```

Output: exit 1; `assert 0 == 1`, proving the current-rank-only selection
excluded the affected initial row.

Fix: scope candidate rows to ranks at or above the edited rank on the affected
ladder, then recompute only enlistment-anchored cumulative rows plus direct
one-interval rows at the edited rank. Overridden rows remain excluded.

GREEN output: exit 0, `1 passed` (only the existing testcontainer deprecation
warning).

### P2: explicit profile next-rank date and rank anchor

Cause: the profile update branch for `next_rank_date` marked the date overridden
and bypassed all rank-reset work, leaving the old rank's anchor.

Regression added:
`test_update_soldier_profile_rank_change_with_explicit_date_updates_initial_anchor`.
It changes a soldier from טוראי to סמ"ר with enlistment `2021-01-15` and an
explicit `2030-01-01` next date. It requires the date to remain overridden and
the rank anchor to become `2021-01-15`.

RED command:

```powershell
& 'C:\Users\Shoham\workspace\Justice\backend\.venv\Scripts\python.exe' -m pytest backend/app/services/tests/test_soldiers.py::test_update_soldier_profile_rank_change_with_explicit_date_updates_initial_anchor -q
```

Output: exit 1; `current_rank_since` remained `2025-01-01` instead of
`2021-01-15`.

Fix: when a profile update changes rank or rank track and supplies an explicit
next-rank date, reset only `current_rank_since` to enlistment (or the existing
today fallback), preserving the supplied date and override flag.

GREEN output: exit 0, `1 passed` (only the existing testcontainer deprecation
warning).

### Follow-up verification

```powershell
& 'C:\Users\Shoham\workspace\Justice\backend\.venv\Scripts\python.exe' -m pytest backend/app/services/tests/test_rank_advancement.py backend/app/services/tests/test_soldiers.py backend/tests/unit/test_rank_advancement_worker.py backend/tests/unit/test_soldiers_field_updates.py backend/tests/integration/test_soldier_profile.py backend/tests/integration/test_enrollment_routes.py -q
```

Output: exit 0, no failures; only the repository's existing testcontainer,
TestClient, and AnyIO deprecation warnings. `git diff --check` exited 0.
