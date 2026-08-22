# Backend test-suite performance final report — 2026-08-22

## Environment and bounds

- Worktree: `C:\Users\Shoham\.paseo\worktrees\1n26l98r\adoring-cougar`
- Implementation base: `500f9c4b`
- Python: 3.13.3
- pytest: 9.0.3
- Platform: Windows PowerShell on Windows
- Broad final-matrix commands were run sequentially without the earlier
  exploratory cap; both completed successfully.
- Solver profiling is serial-only. The normal `-n 4` pytest default is
  unchanged; profiling commands must override it with `-n 0`.

## Focused profiling verification

| Command | Limit | Result | Counts / duration |
| --- | ---: | --- | --- |
| `python -m pytest tests/unit/test_solver_profiling.py -q -n 0` | 180 seconds | Passed before review round 1. The whole file was not rerun after the review fixes because the user stopped at the focused-test boundary. | 6 passed; 2.8 seconds wall time. |
| `python -m pytest tests/unit/test_solver_profiling.py app/algorithm/tests/test_solver.py::test_solve_basic -q -n 0` | 180 seconds | Passed before review round 1 using the existing solver assignment smoke test. | 7 passed; approximately 2.6 seconds. |
| PowerShell: set `JUSTICE_TEST_SOLVER_PROFILE=1`, then run `python -m pytest tests/unit/test_solver_profiling.py::test_profiled_small_solve_reports_named_non_negative_phases_without_changing_result -q -n 0` | 180 seconds | Passed before review round 1 and emitted the optional phase summary. | 1 passed; approximately 2.7 seconds. |
| `python -m pytest tests/unit/test_solver_profiling.py::test_profiled_solve_from_worker_thread_reports_phases -q -n 0` | 120 seconds | Review regression failed before the callback fix, then passed after it. | Final focused run: 1 passed in 3.3 seconds pytest time. |
| `python -m pytest tests/unit/test_solver_profiling.py::test_requested_profiling_is_disabled_under_xdist tests/unit/test_solver_profiling.py::test_requested_profiling_is_enabled_for_serial_pytest -q -n 0` | 120 seconds | Review regressions failed during collection before the pure support API existed, then passed after it. | Final focused run: 2 passed in 3.3 seconds pytest time. |

One exploratory combined run enabled the session-wide profiling hook while also
executing the contract that proves the disabled path does not read the profiling
clock. It correctly failed that contract because profiling was explicitly on.
The final verification separates disabled-path contracts from the enabled
measurement; no assertion or implementation was weakened.

The brief's stale `test_solver_returns_assignments` node is omitted here because
that node does not exist in this checkout; `test_solve_basic` is the existing
equivalent. The profiling contracts cover named non-negative durations, equality of
profiled and unprofiled assignments/status/seed, the zero-clock-read disabled
path, cancellation cleanup, exception cleanup and context detachment, explicit
environment gating, worker-thread capture, and serial-only pytest gating.

## Solver phase measurements

The successful small deterministic profiling run reported:

| Phase | Aggregate duration | Calls | Meaning |
| --- | ---: | ---: | --- |
| `batching` | 0.007201 seconds | 1 | Inclusive time for the selected decomposition path. |
| `solve_primary` | 0.004550 seconds | 1 | Primary CP-SAT search. |
| `model_construction` | 0.001249 seconds | 2 | Initial model build plus tie-break model mutation. |
| `solve_tiebreak` | 0.001007 seconds | 1 | Lexicographic tie-break search. |
| `post_solve_swap` | 0.000046 seconds | 1 | Post-solve assignment swap pass. |

`batching` is intentionally inclusive and overlaps its nested model/solve
phases. The other phase totals are suitable for ranking solver work, not for
summing into wall-clock duration.

Profiling is inactive by default. The inactive path does not read
`time.perf_counter`; tests activate the private process-local callback context
directly, and the pytest report hook activates it only when
`JUSTICE_TEST_SOLVER_PROFILE=1`. The callback registry and recorder are
thread-safe so solves launched from internal worker threads are included.

Profiling does not aggregate xdist worker results. If the environment setting is
combined with any active xdist worker count, pytest prints a terminal warning,
collects no solver profile data, and directs the operator to rerun with `-n 0`.
This refusal prevents a partial per-worker report from being mistaken for a
complete profile. Solver time limits, random seeds, worker counts, status
handling, and returned assignments are unchanged.

The supported PowerShell invocation is:

```powershell
$env:JUSTICE_TEST_SOLVER_PROFILE = "1"
python -m pytest tests/unit/test_solver_profiling.py::test_profiled_small_solve_reports_named_non_negative_phases_without_changing_result -q -n 0
Remove-Item Env:JUSTICE_TEST_SOLVER_PROFILE
```

## Final verification matrix

| Command | Result | Pass/skip counts |
| --- | --- | --- |
| `pytest -q` | Exit 0; completed in 294.7 seconds. | Full normal suite completed at 100%; existing warnings only. |
| `pytest --slow -q` | Exit 0; completed in 598.6 seconds. | Full normal plus slow suite completed at 100%; existing warnings only. |
| `python -m py_compile app/main.py app/algorithm/solver.py tests/conftest.py tests/support/database.py tests/support/app.py tests/support/profiling.py` | Exit 0. | Not applicable. |
| `git diff --check` | Exit 0. | Not applicable. |

## Fixture phases and remaining bottlenecks

No fresh `--durations` run was performed after the stop instruction. The latest
available fixture evidence is the Task 2 representative database slice already
recorded in the baseline report:

- 7.93 seconds: first test setup, including one-time container startup and migrations.
- 1.45 seconds: slowest test call.
- 0.66 seconds: slowest listed teardown.
- 0.32–0.66 seconds: recurring reset-inclusive setup range.

The remaining known bottlenecks are one-time PostgreSQL/container migration
startup, per-database-test reset/setup, primary CP-SAT search, and the intentionally
large/statistical solver coverage available through `--slow`.

## Attribution

- Task 1 made pure/database/HTTP layers explicit and prevented pure-only marker
  selections from starting PostgreSQL.
- Task 2 moved database lifecycle and reset work behind one worker runtime with
  pooled engines. Its numeric suite-level improvement remains unmeasured.
- Task 3 isolated application/client lifecycle state without widening client scope.
- Task 4 excluded one 20-scenario statistical fairness sweep from normal runs
  while retaining deterministic normal coverage.
- Task 5 makes solver bottlenecks visible without changing production solve
  decisions when profiling is off.

The normal and slow suites both passed after the final harness fixes. Exact
pytest count summaries were not retained because the terminal tool truncated
the final summary lines, so this report records the authoritative exit codes,
completion times, and successful completion at 100% rather than inventing
counts.

## `_database_runtime` classification

The Task 4 algorithm-area run's `fixture '_database_runtime' not found` error
was branch-introduced by Task 2: commit `11a18c94` changed the re-exported
`admin_engine` and `app_engine` fixtures to depend on `_database_runtime`, while
`app/services/tests/conftest.py` still imported the old fixture list from
`tests.conftest` and omitted `_database_runtime`. Pytest therefore saw the
consumer fixtures in that subtree but not their new dependency.

That blocker was repaired by commit `8890467c` (`test: re-export database
runtime fixture`), which re-exports `_database_runtime` in the service-test
conftest. Its focused algorithm-bridge regression passed in 10.4 seconds. The
old unresolved-blocker conclusion is stale and must not be used for the current
branch status.

## Final harness-fix addendum — 2026-08-22

- Default parallel pytest invocation now distinguishes configured `testpaths`
  from actual command-line path selectors with `invocation_params.args`, so
  `pytest -q` still enables the shared migrated template while explicit focused
  paths remain isolated.
- Direct FastAPI lifecycle tests in `test_test_app.py` explicitly declare
  `@pytest.mark.test_layer("http")`; they no longer rely on their unit-test path
  to infer the wrong layer.
- The enabled solver-profile fixture is covered end-to-end through the terminal
  summary hook, including a recorded phase line.
- `range_locations` is included in the reset sequence after `range_events`,
  preserving its foreign-key dependency order.

Focused final-harness verification (not a broad suite):

```text
python -m pytest tests/unit/test_test_fixtures.py tests/unit/test_test_app.py tests/unit/test_database_test_adapter.py -n 0
63 passed, 1 warning in 9.00s
```


## Post-verification optimization round — 2026-08-22 (`77ec37c7`)

Profiling the verified branch surfaced three hotspots; all three were addressed.

### Findings

| Hotspot | Evidence | Fix |
| --- | --- | --- |
| Argon2 password hashing in test seeding | ~2,075 `create_soldier()` callsites × ~96 ms measured hash cost ≈ ~200 s of suite worker time | `hash_password` memoizes per plaintext when `JUSTICE_TESTING=1` (set process-wide in `pytest_configure`). Production salting unchanged; the salt unit test now asserts against the raw hasher |
| Migration-regression tests each booted a private container and replayed the full alembic chain | 5 slowest default-suite calls were 13.7 s / 7.5 s / 6.1 s / 5.7 s / 5.2 s, all migration tests | `tests/support/database.py::get_migrated_template` + `cloned_migration_database`: one process-cached container migrated to the down_revision per module; each test runs on a cheap `CREATE DATABASE ... TEMPLATE` clone. The 7 migration tests are additionally marked `slow` |
| `create_app()` reuse hypothesis | Measured 0.6 ms median per call (module import 5 s, once) | Rejected — function-scoped clients stay; no change needed |

Also fixed en route: dev's newer `app/routes/tests` and `app/scripts/tests`
sub-conftests re-export root fixtures but lacked `_database_runtime`, erroring
every database test under those trees with "fixture '_database_runtime' not
found" (`58238b6f`).

### Full-suite results (same worktree, fresh venv, pytest 9.1.1)

| Command | Before (recorded above) | After | Exit |
| --- | ---: | ---: | --- |
| `pytest -q` | 294.7 s | **177.9 s** (−34%) | 0 |
| `pytest --slow -q` | 598.6 s | **555.7 s** (−7%) | 0 |

Focused spot-checks after the changes:

```text
tests/unit/test_password.py + 3 migration files + announcement pagination test (--slow -n 0)
13 passed in ~33s
keva upgrade test call:        13.74s -> 5.68s (first test builds the template)
keva downgrade test call:       6.12s -> 0.49s (clone only)
announcement pagination call:   5.65s -> 0.68s (26 memoized soldier hashes)
```

Caveats: CI skips `--slow`, so migration-regression coverage no longer runs in
CI by default — run `pytest --slow -q` before releases (existing convention).
The pre-existing `test_seed_creates_stable_range_scenarios_without_duplicates`
failure (15 != 3 range events) reproduces identically on pristine `dev` and is
unrelated to this branch.