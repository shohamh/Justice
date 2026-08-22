# Backend Test Suite Performance Design

## Status

Approved in conversation for specification work. Implementation has not started.

## Goal

Reduce Justice backend test-suite runtime while preserving database isolation, authentication isolation, and complete normal coverage.

The normal command remains `pytest -q`. Intentionally large or stochastic solver coverage remains available through `pytest --slow -q`.

## Current evidence

- The default backend suite is approximately 319 seconds after the first optimization pass.
- The algorithm area remains the largest subsystem; a serial algorithm slice was approximately 284 seconds.
- Several large timing entries attributed to algorithm tests are actually database/container setup, with representative setup spikes of roughly 20–58 seconds in isolated runs.
- A session-scoped `TestClient` experiment caused authentication/configuration state leakage and a 401 failure, so client reuse cannot be introduced by widening fixture scope alone.
- The current full-suite worker template and per-worker database clone approach already reduces repeated migration cost and must remain intact.

## Design principles

1. Preserve behavior and isolation before optimizing runtime.
2. Put each optimization behind a focused test-only interface.
3. Keep pure algorithm tests independent from PostgreSQL and FastAPI.
4. Measure each change against a repeatable baseline.
5. Do not use result caching or shared mutable test state to disguise solver or authorization regressions.

## Architecture

### 1. Test-layer separation

The test suite will have three explicit layers:

- Pure algorithm/model tests: direct calls into `app.algorithm`, with no database or application fixtures.
- Database/service tests: direct service and persistence behavior using the worker database.
- HTTP/application integration tests: FastAPI routes through a function-scoped test client.

Collection and fixture behavior should make these layers visible through existing pytest markers and fixture names. Tests must not acquire database or application fixtures merely because they live under an algorithm-named path.

### 2. Database test adapter

Database lifecycle behavior currently concentrated in `backend/tests/conftest.py` will be organized behind a focused test-only adapter. Its interface will cover:

- starting or receiving the worker database;
- applying migrations when a focused run needs its own database;
- resetting mutable tables between database tests;
- restoring migration-seeded system settings and hierarchy defaults.

The adapter will retain one isolated database per xdist worker and one reset boundary per database test. It may optimize connection reuse, prebuilt reset SQL, and seed insertion, but it must not replace isolation with shared rows or a global rollback assumption.

Transaction rollback is explicitly rejected as the universal reset mechanism because FastAPI requests and test sessions use independent database connections.

### 3. Application lifecycle seam

Test application creation will be isolated in a helper that:

- enables `JUSTICE_TESTING` for the lifetime of the app/client;
- prevents production background workers from starting in tests;
- resets process-global test state such as rate limits;
- restores environment state after the test.

The HTTP client remains function-scoped unless a later benchmark proves a safe reusable scope with explicit state reset and regression coverage.

### 4. Solver coverage split

Normal solver coverage will use small deterministic inputs and retain distinct production-path assertions for:

- hard constraints and eligibility;
- coverage and duplicate prevention;
- batching and decomposition;
- cancellation;
- quota relaxation;
- fairness objective mechanics;
- post-solve behavior where it is a distinct production contract.

Large randomized fairness sweeps and scale/stress scenarios will be marked `slow`. They remain part of `pytest --slow -q` and are not deleted.

Normal-test solver budgets will be bounded according to the assertion being protected. At least one larger-budget scale validation remains in slow coverage. Solver result caching is prohibited.

## Profiling and acceptance criteria

The implementation will establish and compare a baseline for:

- `pytest -q`;
- `pytest --slow -q`;
- pure algorithm tests;
- database-backed tests;
- HTTP integration tests;
- representative fixture setup/reset durations;
- solver model construction, solve phases, batching, and post-solve swap phases.

Acceptance criteria:

1. `pytest -q` passes and retains all normal coverage.
2. `pytest --slow -q` passes all large/stochastic coverage.
3. Pure algorithm tests do not start PostgreSQL or FastAPI.
4. No test depends on ordering, shared authentication state, or rows created by another test.
5. Runtime improvements are measurable and attributable to named changes.
6. Remaining slow tests are visible in timing output and documented rather than hidden.

## Implementation order

1. Add classification/seam tests and isolate pure algorithm fixtures.
2. Extract and optimize the database test adapter while preserving reset semantics.
3. Extract the application lifecycle helper and add state-isolation regression coverage.
4. Split normal versus slow solver scenarios and tune only justified test budgets.
5. Add profiling output, run the full verification matrix, and document remaining hotspots.

## Out of scope

- Changes to production authorization, soldier visibility, or solver semantics.
- Global database transactions as a replacement for reset isolation.
- Sharing a mutable FastAPI app or authentication state across tests.
- Removing large solver coverage without an equivalent `--slow` path.
