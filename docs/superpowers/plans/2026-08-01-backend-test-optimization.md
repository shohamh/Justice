# Backend Test Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make backend pytest database setup conditional on actual database use, preserve integration isolation, and prove runtime improvements with repeatable profiling.

**Architecture:** Keep the existing root fixture API, centralize the database-fixture names in a predicate, and use pytest's collected item fixture names to decide whether session bootstrap and per-test reset should request the database. Benchmark commands provide evidence without changing application code.

**Tech Stack:** pytest 8, pytest-xdist, pytest-asyncio, testcontainers PostgreSQL, SQLAlchemy, PowerShell timing.

## Global Constraints

- Preserve existing database fixture names and `TRUNCATE ... RESTART IDENTITY CASCADE` isolation.
- Do not change application code, assertions, worker count, or slow-test selection.
- Do not touch existing frontend changes.
- Report Docker/temp permission blockers separately from test failures.

---

### Task 1: Add fixture-selection coverage and baseline profiling

**Files:** `backend/tests/conftest.py`, `backend/tests/unit/test_test_fixtures.py`, `docs/benchmarks/2026-08-01-backend-test-optimization.md`

- [ ] Add tests for `_item_needs_database`: pure fixture names return false; `client` and `admin_session` return true.
- [ ] Run the focused test and confirm it fails because the predicate is absent.
- [ ] Add one constant set containing `client`, `admin_session`, `app_session`, `admin_engine`, `app_engine`, `pg_container`, and `db_admin_url`, plus `_item_needs_database(item: pytest.Item) -> bool`.
- [ ] Measure `tests/unit/test_jwt_tokens.py`, `tests/integration/test_health.py`, `pytest -q`, and `pytest --slow -q` with a PowerShell Stopwatch. Record counts, elapsed time, exit code, and permission blockers.
- [ ] Run the focused tests and commit with `test: profile backend fixture overhead`.

### Task 2: Make session database setup lazy

**Files:** `backend/tests/conftest.py`, `backend/tests/unit/test_test_fixtures.py`

- [ ] Add coverage proving a pure-only collected item set does not need database setup and a set containing `client` does.
- [ ] Run the focused test and confirm the expected failure against eager setup.
- [ ] Change `_apply_schema` to accept `request: pytest.FixtureRequest`, inspect `request.session.items`, return for pure-only selections, and otherwise call `request.getfixturevalue('db_admin_url')` before preserving the existing environment, engine reset, and migration logic.
- [ ] Run fixture tests and pure algorithm/auth tests with `-o addopts='-q -n 0'`; do not claim integration coverage if Docker is unavailable.
- [ ] Commit with `test: defer database bootstrap for pure tests`.

### Task 3: Make per-test reset lazy and validate isolation

**Files:** `backend/tests/conftest.py`, `backend/tests/unit/test_test_fixtures.py`, selected existing integration tests

- [ ] Add coverage for dispatch: pure items do not request `admin_engine`; DB items do.
- [ ] Change `_truncate_tables` to accept `request`, call `request.getfixturevalue('admin_engine')` only for DB items, and preserve all truncation and reseeding SQL.
- [ ] Remove only the unused `db_admin_url` parameter from `client`, if confirmed unused.
- [ ] Run pure tests and, with Docker access, `tests/integration/test_health.py` plus `tests/integration/test_assignments_api.py`.
- [ ] Commit with `test: defer database reset for pure tests`.

### Task 4: Profile after the change and document results

**Files:** `docs/benchmarks/2026-08-01-backend-test-optimization.md`; fixture code only if a measured, tested fixture-only bottleneck remains

- [ ] Repeat the exact baseline commands under the same worker/temp settings.
- [ ] Compare pure startup, integration runtime, plain-suite runtime, slow-suite runtime, test counts, and failures; never infer speedup from failed runs.
- [ ] Run fixture tests, `pytest -q`, `ruff check tests`, and `pytest --slow -q` when Docker is available.
- [ ] Commit with `docs: record backend test optimization benchmarks`.
