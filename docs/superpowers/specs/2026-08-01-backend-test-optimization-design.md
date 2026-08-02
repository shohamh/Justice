# Backend Test Optimization Design

## Goal

Reduce both default and full backend pytest runtime without weakening isolation or coverage.

## Findings

`backend/tests/conftest.py` uses root-level autouse database setup and per-test truncation. Pure unit tests therefore request Postgres even when they do not use `client`, `admin_session`, or another database fixture. The suite already uses four xdist workers and tuned Postgres durability settings, so the next safe gain is avoiding database work for tests that do not need it.

The initial benchmark attempt was invalid because the environment denied pytest temp/cache access and Docker named-pipe access. Valid before/after measurements must use an accessible temp path and Docker access; those permission failures must be reported separately from test results.

## Design

1. Make database bootstrap lazy. Session schema setup starts Postgres only when a selected test requests a database fixture.
2. Make per-test reset lazy. It requests `admin_engine` only for database-dependent items.
3. Keep fixture names and `TRUNCATE ... RESTART IDENTITY CASCADE` behavior unchanged.
4. Remove the unused database dependency from `client` only if inspection confirms it is unnecessary.
5. Add fixture-selection regression tests and repeatable before/after benchmarks.

## Correctness and scope

This changes pytest fixture scheduling only. It does not change application code, test assertions, schema, worker count, or slow-test selection. App/client reuse is deferred unless profiling shows a separately safe, tested opportunity.

## Acceptance criteria

- Pure tests do not construct `PostgresContainer`.
- Database tests still migrate once per worker and reset data before every test.
- Plain and slow suites are measured with exact commands, counts, elapsed times, exit codes, and environment limitations.
