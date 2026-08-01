# Backend test optimization benchmarks

## Task 1 baseline attempt — 2026-08-01

| Command | Test count | Elapsed | Exit code | Result |
| --- | ---: | ---: | ---: | --- |
| `pytest tests/unit/test_jwt_tokens.py` | Not measured | Not run | Not run | Skipped after the Docker permission blocker was confirmed. |
| `pytest tests/integration/test_health.py` | Not measured | Not run | Not run | Skipped after the Docker permission blocker was confirmed. |
| `pytest -q` | Not measured | Not run | Not run | Skipped after the Docker permission blocker was confirmed. |
| `pytest --slow -q` | Not measured | Not run | Not run | Skipped after the Docker permission blocker was confirmed. |

The requested stopwatch baselines were not collected. The environment cannot open Docker Desktop's `//./pipe/dockerDesktopLinuxEngine` named pipe: `pywintypes.error: (5, 'CreateFile', 'Access is denied.')`. A focused pytest run through the ordinary test fixture path failed at session setup before test execution for that reason (5 setup errors, exit code 1, 0.85 seconds). Per the task direction, these are environment permission blockers, not passing test results or performance measurements.

Pytest also emitted `PytestCacheWarning` because it could not create entries under `backend/.pytest_cache` (`WinError 5: Access is denied`).

## Focused fixture-selection test

`pytest tests/unit/test_test_fixtures.py --confcutdir=tests/unit -o "addopts=-q -n 0"` completed with 5 passed in 0.67 seconds. `--confcutdir` prevents pytest from registering the root autouse database fixtures; the test still imports and exercises the real predicate without starting Docker.

## Post-change results (Tasks 1-3) - 2026-08-01

The focused fixture test improved from 5 passed in 0.67 seconds before the change to 9 passed after Task 3. The pure JWT test set completed with 5 passed. These are valid Docker-independent results.

The root/default/full-database timings are invalid: Docker named-pipe access was denied (`//./pipe/dockerDesktopLinuxEngine`, `pywintypes.error: (5, ''CreateFile'', ''Access is denied.'')`). They must not be treated as runtime measurements or passing whole-suite results.

Because the baseline and post-change database-backed timings are unavailable, no valid whole-suite speedup can be claimed.

## Focused Docker-independent evidence - 2026-08-01

| Command | Test count | Elapsed | Exit code |
| --- | ---: | ---: | ---: |
| `pytest tests/unit/test_test_fixtures.py tests/unit/test_jwt_tokens.py --confcutdir=tests/unit -o "addopts=-q -n 0" --no-header --tb=short` | 14 passed | 2.78s | 0 |

This is focused Docker-independent evidence. Whole-suite DB timing is blocked by the Docker named pipe, and no whole-suite speedup is claimed.

## Full-suite profiling - 2026-08-01

With Docker access and the existing four-worker configuration, pytest -q --durations=40 completed with 1,014 passed and 3 skipped in 319.73 seconds wall time. The largest repeatable call hotspot was 	ests/unit/test_tiebreak_e2e.py::test_range_mode_improves_average_spread_across_scenarios at 35.13 seconds; the largest setup costs were the first database-backed test on each xdist worker, ranging from about 7.35 to 12.53 seconds while each worker initialized its isolated Postgres container and schema.

A two-worker run took 404.41 seconds and had one unrelated/flaky soldier-API failure, so reducing workers is not an optimization. A reduced fairness scenario matrix and a temporary slow-test classification were also tested and reverted: their wall times were not better than the baseline. No unproven optimization is retained; the remaining fixture bottleneck requires a shared-container/per-worker-database design and separate isolation validation.
