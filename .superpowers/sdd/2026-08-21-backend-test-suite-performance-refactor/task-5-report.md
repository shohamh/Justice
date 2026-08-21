# Task 5 report: solver profiling and bounded final verification

## Delivered

- Added a private process-local profiling callback registry in
  `app/algorithm/solver.py`. It records only when a test activates the context;
  the disabled path does not read the profiling clock, and callbacks remain
  available to solver work launched from a worker thread.
- Timed model construction, primary/coverage/fairness/tie-break solve phases,
  decomposition batching, and the post-solve swap pass.
- Added `tests/support/profiling.py` with an aggregate recorder, explicit
  `JUSTICE_TEST_SOLVER_PROFILE=1` gate, and exception-safe capture context.
- Added an optional pytest fixture/terminal summary hook in `tests/conftest.py`.
- Added profiling contracts for phase names and non-negative values, disabled
  behavior, assignment/status/seed preservation, cancellation, failures,
  context cleanup, environment gating, worker-thread capture, and serial-only
  pytest profiling.
- Updated the historical baseline without rewriting prior numbers and added the
  final benchmark report.

No solver decision branch, solve limit, random seed, worker count, status rule,
or assignment transformation changed. The only production-file changes are
timing contexts around existing operations.

## Test-first evidence

1. The first focused run failed during collection with
   `ModuleNotFoundError: No module named 'tests.support.profiling'`.
2. After adding the test recorder, three tests failed with
   `AttributeError: module 'app.algorithm.solver' has no attribute '_capture_profile'`.
3. The optional-hook contract then failed with
   `AttributeError: module 'tests.conftest' has no attribute '_solver_profile_report'`.
4. Each contract passed after its corresponding minimal seam was implemented.

## Focused verification

All commands were bounded at 180 seconds.

| Command | Result |
| --- | --- |
| `python -m pytest tests/unit/test_solver_profiling.py -q -n 0` | Final run: 6 passed in 2.8 seconds wall time; one pre-existing `python_multipart` pending-deprecation warning. |
| `python -m pytest tests/unit/test_solver_profiling.py::test_optional_pytest_hook_records_solver_phases_only_when_enabled -q -n 0` | 1 passed. |
| Brief's exact command using `test_solver_returns_assignments` | Failed at collection because that test node does not exist. |
| Same focused command using existing `test_solve_basic` | 7 passed. |
| One profiling-enabled small-solve contract | 1 passed and emitted named phase totals. |

The brief's named smoke-test node is stale for this checkout; no test was renamed
just to satisfy the command. `test_solve_basic` is the existing assignment smoke
test and was used as the bounded equivalent.

The final matrix was stopped by the user before any broad command started. All
four broad pytest commands and `py_compile` are recorded as not run with planned
180-second caps in the final benchmark report. No full/slow pass claim is made.

## Profiling result

The successful opt-in sample ranked the phases as:

1. `batching`: 0.007201 seconds.
2. `solve_primary`: 0.004550 seconds.
3. `model_construction`: 0.001249 seconds across two calls.
4. `solve_tiebreak`: 0.001007 seconds.
5. `post_solve_swap`: 0.000046 seconds.

Batching is inclusive and overlaps the nested model and solve phases.

## `_database_runtime` attribution

The error is introduced by Task 2, not by Task 5 or unrelated soldier-modal
work. Task 2 made `admin_engine`/`app_engine` depend on `_database_runtime`, but
`app/services/tests/conftest.py` re-exports those fixtures without re-exporting
their new dependency. The error is therefore a fixture visibility problem in
the services-test subtree.

No repair was included after the user explicitly limited completion to focused
profiling and requested the profiling/report commit.

## Concerns

- Broad normal/slow verification is unrun by explicit user instruction.
- The branch-introduced `_database_runtime` re-export omission remains unresolved
  and blocks the database-backed algorithm bridge tests.
- The latest fixture-phase timings are Task 2 measurements, not fresh Task 5 data.
- Unrelated dirty soldier-modal files remain unmodified and unstaged.

## Recovery verification (2026-08-22)

| Command | Output |
| --- | --- |
| `python -m pytest tests/unit/test_solver_profiling.py -q -n 0` | `...... [100%]`; 6 passed. Pytest emitted one `python_multipart` pending-deprecation warning. |
| `git diff --check` | Exit 0 with no whitespace errors. Git emitted only LF-to-CRLF conversion warnings for modified working-tree files. |

## Fix-round recovery (2026-08-22)

- Removed the root `tests.conftest` import from the pure profiling tests, so
  importing those tests does not pull in database/container support.
- Made opt-in profiling serial-only: an active xdist controller or worker
  disables collection and prints `WARNING: solver profiling is disabled because
  pytest-xdist is active; no profile data was collected. Rerun with -n 0.`
- Replaced the task-local callback with a lock-protected process-local registry;
  phase delivery confirms callbacks are still active before invoking them. The
  recorder is also lock-protected, so an internal worker-thread solve is
  captured without mutating aggregate state unsafely.
- No pytest command was run in this recovery round, by explicit instruction.

| Command | Output |
| --- | --- |
| `git diff --check` | Exit 0; no whitespace errors. |
| Commit | `test: harden solver profiling` (Task 5 files only). |
