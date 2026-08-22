# Backend Test Suite Performance Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce backend test runtime while preserving per-test database/authentication isolation and complete normal plus slow solver coverage.

**Architecture:** Keep one isolated PostgreSQL database per xdist worker, but move database lifecycle/reset behavior behind a focused test adapter. Keep FastAPI clients function-scoped behind an explicit test-app helper. Classify pure algorithm tests so they never acquire database or application fixtures, and move only large randomized/stress solver cases to `--slow`.

**Tech Stack:** Python, pytest, pytest-xdist, FastAPI `TestClient`, SQLAlchemy, Alembic, PostgreSQL testcontainers, OR-Tools CP-SAT.

**Spec:** `docs/superpowers/specs/2026-08-21-backend-test-suite-performance-design.md`

## Global Constraints

- `pytest -q` remains the complete normal backend suite.
- `pytest --slow -q` must include and pass every intentionally large or stochastic solver test.
- Pure algorithm tests must not start PostgreSQL or FastAPI.
- Database tests retain one isolated database per xdist worker and reset mutable data before each database test.
- HTTP clients remain function-scoped unless explicit state-reset tests prove a reusable scope safe.
- Do not use solver-result caching or shared mutable authentication/database state.
- Do not modify production soldier visibility, authorization, or solver semantics as part of this refactor.
- Preserve unrelated existing worktree changes.

---

### Task 1: Establish test-layer classification and baseline timing

**Files:**
- Modify: `backend/tests/conftest.py: pytest options, collection markers, fixture classification`
- Modify: `backend/tests/unit/test_test_fixtures.py: classification and option tests`
- Create: `backend/tests/unit/test_test_layer_classification.py`
- Create: `backend/tests/support/__init__.py`
- Create: `docs/superpowers/benchmarks/2026-08-21-backend-test-suite-performance-baseline.md`

**Interfaces:**
- Produces the existing pytest markers plus an explicit pure-algorithm classification helper that later fixture tasks can call.
- Produces a recorded baseline for `pytest -q`, `pytest --slow -q`, and the algorithm/database/HTTP slices.

- [ ] **Step 1: Write classification tests**

  Add tests for representative collected items proving that pure files under `backend/app/algorithm/tests/` and pure algorithm cases under `backend/tests/unit/` do not require database fixtures, while route/service integration items do. Assert that `slow` items are deselected without `--slow` and included with it.

- [ ] **Step 2: Run the classification tests to verify the current seam is insufficient**

  Run:

  ```powershell
  cd backend
  pytest tests/unit/test_test_layer_classification.py tests/unit/test_test_fixtures.py -q -n 0
  ```

  Expected: the new classification assertions identify the current fixture/marker behavior that must be made explicit.

- [ ] **Step 3: Implement the smallest classification helper**

  Add a pure function with an interface equivalent to:

  ```python
  def item_layer(item: pytest.Item) -> Literal["pure", "database", "http"]:
      ...
  ```

  Base the result on fixture requirements and the existing area/path conventions, not on a broad algorithm marker alone. Keep the existing automatic area markers unchanged.

- [ ] **Step 4: Capture the baseline before performance edits**

  From `backend/`, record wall-clock duration and pass/skip counts for:

  ```powershell
  Measure-Command { pytest -q }
  Measure-Command { pytest --slow -q }
  Measure-Command { pytest -m algorithm -q -n 0 }
  Measure-Command { pytest -m "not algorithm" -q -n 0 }
  ```

  Include the commands, environment, commit, and observed durations in the benchmark Markdown file. If a command exceeds the normal command timeout, record it as a timeout rather than inventing a duration.

- [ ] **Step 5: Run the focused checks**

  Run:

  ```powershell
  pytest tests/unit/test_test_layer_classification.py tests/unit/test_test_fixtures.py -q -n 0
  git diff --check
  ```

- [ ] **Step 6: Commit**

  ```powershell
  git add backend/tests/conftest.py backend/tests/unit/test_test_fixtures.py backend/tests/unit/test_test_layer_classification.py backend/tests/support/__init__.py docs/superpowers/benchmarks/2026-08-21-backend-test-suite-performance-baseline.md
  git commit -m "test: classify backend test layers"
  ```

### Task 2: Extract and optimize the database test adapter

**Files:**
- Create: `backend/tests/support/database.py`
- Modify: `backend/tests/conftest.py: PostgreSQL, migration, engine, and reset fixtures`
- Modify: `backend/tests/unit/test_test_fixtures.py: adapter contract tests`
- Create: `backend/tests/unit/test_database_test_adapter.py`

**Interfaces:**
- `TestDatabaseRuntime` owns the worker database URL, migration decision, session-scoped engines, reset SQL, and seeded defaults.
- `reset_database(engine: Engine) -> None` performs the same data reset currently provided by `_truncate_tables`.
- Existing fixture names (`pg_container`, `db_admin_url`, `admin_engine`, `app_engine`, `admin_session`, `app_session`) remain compatible with test modules.

- [ ] **Step 1: Write adapter contract tests without starting a container**

  Test that the reset table list is ordered, the generated reset statement contains `RESTART IDENTITY CASCADE`, seed rows contain the current settings and hierarchy defaults, and focused runs migrate while shared xdist workers do not migrate a cloned database.

- [ ] **Step 2: Run the adapter tests and confirm missing interfaces**

  ```powershell
  cd backend
  pytest tests/unit/test_database_test_adapter.py -q -n 0
  ```

  Expected: FAIL because the adapter module and contract functions do not yet exist.

- [ ] **Step 3: Move database constants and pure SQL construction into the adapter**

  Move `_ALL_DATA_TABLES`, `_SYSTEM_SETTINGS_DEFAULTS`, and `_LEVEL_TYPE_DEFAULTS` behind the adapter. Precompute the table-list and seed SQL once per process, while continuing to use safe internal constants rather than interpolating test-controlled values.

- [ ] **Step 4: Route existing fixtures through the adapter**

  Change `conftest.py` so container/template creation, migration setup, engine construction, and `_truncate_tables` call the adapter. Preserve the current shared-template behavior for default xdist runs and the independent container behavior for focused runs.

- [ ] **Step 5: Verify database isolation and query behavior**

  ```powershell
  pytest tests/unit/test_database_test_adapter.py tests/unit/test_test_fixtures.py -q -n 0
  pytest tests/integration/test_soldiers_api.py tests/integration/test_private_fields.py -q -n 0
  ```

  Confirm that hardcoded unique values still work in consecutive tests, app-role tests still exercise database RBAC, and no pure test starts a database fixture.

- [ ] **Step 6: Measure reset cost and compare with baseline**

  Run representative database files with `--durations=30` and record setup/call/teardown changes in the benchmark report. Do not proceed to a further reset strategy unless the measured reset cost is a material contributor.

- [ ] **Step 7: Commit**

  ```powershell
  git add backend/tests/support/database.py backend/tests/conftest.py backend/tests/unit/test_test_fixtures.py backend/tests/unit/test_database_test_adapter.py docs/superpowers/benchmarks/2026-08-21-backend-test-suite-performance-baseline.md
  git commit -m "test: isolate database lifecycle adapter"
  ```

### Task 3: Extract the test application lifecycle seam

**Files:**
- Create: `backend/tests/support/app.py`
- Modify: `backend/tests/conftest.py: client and process-state fixtures`
- Modify: `backend/app/main.py: preserve the JUSTICE_TESTING production-test seam only if required by focused tests`
- Create: `backend/tests/unit/test_test_app.py`
- Test: `backend/tests/integration/test_notifications_api.py::test_unread_count_zero`

**Interfaces:**
- `test_app() -> Iterator[FastAPI]` creates an app with test-only worker suppression and restores environment state.
- `test_client() -> Iterator[TestClient]` creates a function-scoped client from `test_app`.
- `reset_process_state() -> None` resets rate limiting and any other explicitly identified in-memory test state.

- [ ] **Step 1: Write lifecycle isolation tests**

  Add tests proving that two clients created in separate fixture invocations do not share authentication headers/cookies, rate-limit state, or app lifespan worker state. Include the regression scenario represented by `test_unread_count_zero` so a session-scoped client cannot be reintroduced accidentally.

- [ ] **Step 2: Run lifecycle tests before extraction**

  ```powershell
  cd backend
  pytest tests/unit/test_test_app.py tests/integration/test_notifications_api.py::test_unread_count_zero -q -n 0
  ```

- [ ] **Step 3: Implement the test app helper**

  Move environment save/restore, `JUSTICE_TESTING=1`, `create_app()`, `TestClient` context management, and rate-limiter reset into `tests/support/app.py`. Keep the client function-scoped.

- [ ] **Step 4: Keep production lifespan behavior explicit**

  Ensure `app/main.py` only suppresses production background workers when the test environment flag is set, while normal application startup remains unchanged. Add a focused assertion that the test lifespan does not create worker tasks.

- [ ] **Step 5: Run lifecycle and integration verification**

  ```powershell
  pytest tests/unit/test_test_app.py tests/integration/test_notifications_api.py tests/integration/test_login.py -q -n 0
  ```

- [ ] **Step 6: Commit**

  ```powershell
  git add backend/tests/support/app.py backend/tests/conftest.py backend/app/main.py backend/tests/unit/test_test_app.py backend/tests/integration/test_notifications_api.py
  git commit -m "test: isolate application lifecycle state"
  ```

### Task 4: Split normal and slow solver coverage

**Files:**
- Modify: `backend/tests/unit/test_tiebreak_e2e.py: large randomized fairness scenarios`
- Modify: `backend/app/algorithm/tests/test_solver.py: large or redundant scenarios selected by the Task 4 timing report`
- Modify: `backend/app/algorithm/tests/test_relaxation_search.py: large or redundant scenarios selected by the Task 4 timing report`
- Modify: `backend/tests/conftest.py: slow marker registration and collection behavior`
- Create: `backend/app/algorithm/tests/test_solver_performance.py`
- Modify: `backend/tests/unit/test_fairness_e2e.py` and/or `backend/tests/unit/test_fairness_batching.py` only where duplicate coverage is proven by test names and assertions

**Interfaces:**
- Production `solve(...)` and model interfaces do not change.
- `pytest.mark.slow` identifies scale/statistical tests and remains controlled by the existing `--slow` option.
- A test-only timing helper records named solver phases without changing solver results or budgets in production.

- [ ] **Step 1: Collect solver timing evidence**

  Run the algorithm tests with:

  ```powershell
  cd backend
  pytest -m algorithm -q -n 0 --durations=50
  pytest -m algorithm --slow -q -n 0 --durations=50
  ```

  Identify tests that perform multiple large randomized solves, duplicate an invariant already covered by a deterministic test, or spend most time in a budget that is irrelevant to the assertion.

- [ ] **Step 2: Write/adjust normal deterministic tests first**

  For every moved scenario, retain or add a small deterministic test that directly proves the same production contract: status, coverage, eligibility, fairness mechanics, cancellation, decomposition, relaxation, or post-solve behavior.

- [ ] **Step 3: Mark only scale/statistical scenarios as slow**

  Add `@pytest.mark.slow` to the broad randomized fairness sweep and large-scale stress cases. Move them to `test_solver_performance.py` when doing so makes the normal test file materially easier to understand; do not duplicate the same expensive scenario in both files.

- [ ] **Step 4: Bound normal test budgets**

  Lower only budgets whose assertion does not depend on proving optimality, and assert the accepted `FEASIBLE`/`OPTIMAL` status as appropriate. Keep at least one larger-budget slow case for scale behavior.

- [ ] **Step 5: Verify solver coverage and determinism**

  ```powershell
  pytest app/algorithm/tests tests/unit/test_tiebreak_e2e.py -q -n 0
  pytest app/algorithm/tests tests/unit/test_tiebreak_e2e.py --slow -q -n 0
  ```

  Confirm that normal collection excludes only marked slow cases, slow collection includes all of them, deterministic seeds remain fixed, and assignment invariants remain unchanged.

- [ ] **Step 6: Commit**

  ```powershell
  git add backend/tests/conftest.py backend/app/algorithm/tests backend/tests/unit/test_tiebreak_e2e.py backend/tests/unit/test_fairness_e2e.py backend/tests/unit/test_fairness_batching.py
  git commit -m "test: separate normal and slow solver coverage"
  ```

### Task 5: Add solver phase profiling and complete verification

**Files:**
- Modify: `backend/app/algorithm/solver.py: internal timing seam only if production-safe and disabled by default`
- Create: `backend/tests/support/profiling.py`
- Create: `backend/tests/unit/test_solver_profiling.py`
- Modify: `backend/tests/conftest.py: optional timing/report hook`
- Modify: `docs/superpowers/benchmarks/2026-08-21-backend-test-suite-performance-baseline.md`
- Create: `docs/superpowers/benchmarks/2026-08-21-backend-test-suite-performance-final.md`

**Interfaces:**
- Test-only profiling returns named durations for model construction, solve phases, batching, and post-solve swap work.
- Profiling is disabled during ordinary production execution unless explicitly enabled by a test environment setting.

- [ ] **Step 1: Write profiling contract tests**

  Assert that a small solve produces named, non-negative timing entries, that profiling-disabled execution produces no timing side effect, and that cancellation/failure still closes the timing context.

- [ ] **Step 2: Implement the narrow timing seam**

  Use an optional callback/context object passed only by tests or an environment-gated test hook. Do not alter solver decisions, time limits, seeds, or returned assignments.

- [ ] **Step 3: Run focused profiling tests**

  ```powershell
  cd backend
  pytest tests/unit/test_solver_profiling.py app/algorithm/tests/test_solver.py::test_solver_returns_assignments -q -n 0
  ```

- [ ] **Step 4: Run the complete verification matrix**

  ```powershell
  pytest -q
  pytest --slow -q
  pytest -m algorithm -q -n 0
  pytest -m "not algorithm" -q -n 0
  python -m py_compile app/main.py app/algorithm/solver.py tests/conftest.py tests/support/database.py tests/support/app.py tests/support/profiling.py
  git diff --check
  ```

- [ ] **Step 5: Record final timings and remaining bottlenecks**

  Update the final benchmark report with commands, durations, pass/skip counts, slowest fixture phases, slowest solver phases, and a short attribution of each improvement. State explicitly if any benchmark timed out or was run serially for diagnosis.

- [ ] **Step 6: Commit**

  ```powershell
  git add backend/app/algorithm/solver.py backend/tests/support/profiling.py backend/tests/unit/test_solver_profiling.py backend/tests/conftest.py docs/superpowers/benchmarks
  git commit -m "test: profile backend suite bottlenecks"
  ```
