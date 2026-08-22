# Backend test-suite performance baseline — 2026-08-21

## Environment

- Worktree: `C:\Users\Shoham\.paseo\worktrees\1n26l98r\adoring-cougar`
- Baseline commit: `005bb477871a79f21a20a4becc97c11c9a4475f2`
- Python: 3.13.3
- pytest: 9.0.3
- Platform: Windows PowerShell on Windows
- Measurement method: `Measure-Command`; each command had a 300-second execution cap.
- Recovery measurement: bounded collection-only marker slices, run after the Task 1
  classification helper was added. These validate selection counts without starting
  containers or executing the full suite.

## Commands and observed results

| Command | Result | Wall-clock duration | Pass/skip counts |
| --- | --- | --- | --- |
| `Measure-Command { pytest -q }` | **Timed out** at the 300-second cap; no completed result. | Timeout reported after 304.029 seconds of wrapper wall time. | Not available: pytest did not complete. |
| `Measure-Command { pytest --slow -q }` | **Timed out** at the 300-second cap; no completed result. | Timeout reported after 304.057 seconds of wrapper wall time. | Not available: pytest did not complete. |
| `Measure-Command { pytest -m algorithm -q -n 0 }` | Exit code 0, but the captured double-quiet output omitted the summary; this is an **incomplete result record**, not a count-complete baseline. | 98.804 seconds. | Not captured; pass/skip counts are unavailable. |
| `Measure-Command { pytest -m "not algorithm" -q -n 0 }` | **Incomplete**: stopped at the user's request before completion. | No completed duration recorded. | Not available: pytest did not complete. |

## Bounded classification-slice recovery measurement

| Command | Result | Wall-clock duration | Pass/skip counts | Selected/deselected counts |
| --- | --- | --- | --- | --- |
| `python -m pytest -m pure --collect-only -v -n 0 -o addopts=''` | Exit code 0. | 5.206 seconds. | 0 passed / 0 skipped (collection only). | 212 selected / 1,991 deselected (2,203 collected). |
| `python -m pytest -m database --collect-only -v -n 0 -o addopts=''` | Exit code 0. | 4.519 seconds. | 0 passed / 0 skipped (collection only). | 1,298 selected / 905 deselected (2,203 collected). |
| `python -m pytest -m http --collect-only -v -n 0 -o addopts=''` | Exit code 0. | 5.016 seconds. | 0 passed / 0 skipped (collection only). | 685 selected / 1,518 deselected (2,203 collected). |

The recovery run intentionally did not execute `pytest -q` or `pytest --slow -q`:
both were already shown above to exceed the 300-second cap. It also did not rerun
the incomplete `not algorithm` execution. The three selected counts sum to 2,195,
not 2,203: the eight `slow` items are deselected before layer markers are applied.
That arithmetic confirms every non-slow collected item has exactly one explicit
test-layer marker.

This baseline is intentionally incomplete: the long measurements were stopped or timed out before later performance refactors could run. Do not compare later timings to missing pass/skip counts as though they were successful runs.

## Task 2 adapter measurement

Task 2 extracted container, migration, pooled-engine, and reset ownership into
`backend/tests/support/database.py`. The representative database slice was
measured after the extraction with a 180-second cap:

| Command | Result | Wall-clock duration | Pass count |
| --- | --- | --- | --- |
| `pytest tests/integration/test_soldiers_api.py tests/integration/test_private_fields.py -q -n 0 --durations=30` | Exit code 0 | 37.5 seconds | 38 passed |

The slowest result was the initial setup for
`test_admin_onboards_without_password_gets_temp` (6.91 seconds). The remaining
listed database-test setups were 0.35–0.63 seconds; the slowest calls were
1.48 and 0.49 seconds, and the only listed teardown was 0.74 seconds.

There is no matching pre-Task-2 per-phase measurement in the baseline, so a
numeric before/after delta is unavailable. The duration report does not break
out the reset fixture itself; it provides no evidence that a second reset
strategy is a material contributor, so no additional reset optimization was
started.

## Task 2 review follow-up measurement

The requested representative database slice was rerun after review with a
180-second cap:

| Command | Result | Wall-clock duration | Pass count |
| --- | --- | --- | --- |
| `pytest tests/integration/test_soldiers_api.py tests/integration/test_private_fields.py -q -n 0 --durations=30` | Exit code 0 | 37.9 seconds | 38 passed |

`--durations=30` reported setup, call, and teardown phases. The first test's
setup was 7.93 seconds (session/container/migration startup included); the
remaining listed setup phases were 0.32–0.66 seconds. The two slowest calls
were 1.45 and 0.49 seconds, and the listed teardown was 0.66 seconds.

`_truncate_tables`/`reset_database` runs as part of each database test setup.
Pytest does not separately attribute fixture-internal time in the duration
report, so the 0.32–0.66-second recurring setup figures are reset-inclusive
upper bounds, not reset-only timings. The initial 7.93-second setup must not be
treated as reset cost because it also includes one-time database startup and
migration work.

A like-for-like base/head comparison is unavailable: the recorded baseline at
`005bb477` contains only timed-out full-suite runs, an incomplete algorithm
slice, and collection-only layer slices; it does not contain this exact
soldiers/private-fields command or per-phase durations. No base checkout was
measured because this follow-up authorized one bounded representative slice,
not a second test run against a historical checkout.

## Task 5 profiling and final-matrix disposition

Task 5 added an opt-in solver phase recorder. A successful focused run with
`JUSTICE_TEST_SOLVER_PROFILE=1` reported these aggregate durations for one
small deterministic solve:

| Phase | Duration | Calls |
| --- | ---: | ---: |
| `batching` | 0.007201 seconds | 1 |
| `solve_primary` | 0.004550 seconds | 1 |
| `model_construction` | 0.001249 seconds | 2 |
| `solve_tiebreak` | 0.001007 seconds | 1 |
| `post_solve_swap` | 0.000046 seconds | 1 |

The final broad verification commands were each assigned a 180-second maximum,
but none was started after the user explicitly stopped the final matrix. They
are recorded as **not run**, not as passes, failures, or timeouts. Consequently,
the historical timeout numbers above remain the only full-suite measurements
and no end-to-end runtime improvement is claimed.

The latest available fixture-phase evidence remains Task 2's focused database
slice: 7.93 seconds for the first setup (including container startup and
migrations), 1.45 seconds for the slowest call, and 0.66 seconds for the slowest
listed teardown. These are not fresh Task 5 measurements.
