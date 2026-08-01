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
