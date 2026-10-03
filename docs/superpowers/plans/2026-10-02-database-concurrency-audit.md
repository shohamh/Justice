# Database Transaction and Concurrency Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Identify and fix demonstrated high-risk transaction and concurrency defects in Justice services, with PostgreSQL regression tests and an evidence-backed residual-risk report.

**Architecture:** Audit route/job callers together with service methods and database constraints. Reproduce candidate races with independent PostgreSQL sessions and barriers, then make the smallest constraint, conditional update, row lock, or transaction-boundary change that passes the test. Keep external effects outside open transactions unless an existing outbox or idempotent handoff makes the operation safe.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, PostgreSQL, Alembic, pytest, Testcontainers, existing fixtures in `backend/tests`.

**Spec:** `docs/superpowers/specs/2026-10-02-database-concurrency-audit-design.md`

## Global Constraints

- PostgreSQL is the source of truth for relational invariants.
- Every accepted race fix has a deterministic PostgreSQL test using independent sessions and explicit barriers; no sleeps or SQLite concurrency claims.
- Preserve current permission checks and re-evaluate them inside the transaction when a race could invalidate their result.
- Do not make speculative locking changes; reproduce suspected races before fixing them.
- Keep transactions short and define consistent lock order for shared workflows.
- Do not claim the audit proves freedom from all races.

## Review Focus

- Two requests concurrently satisfy a check-then-write invariant; pin each confirmed case with two independent sessions and a barrier.
- A transaction partially commits linked changes; assert all rows roll back when any step fails.
- A request retries after an integrity/deadlock/serialization error; assert it neither duplicates effects nor returns a misleading success.
- Competing workflows acquire shared rows in opposite order; verify lock order or demonstrate a deterministic deadlock regression.
- Permission or active-state changes race with a write; assert the in-transaction authorization/state predicate rejects stale decisions.

---

## File Map

- Modify only service/route/job files implicated by reproduced findings under `backend/app/services/`, `backend/app/routes/`, or the corresponding job module.
- Create Alembic revisions under `backend/alembic/versions/` only when a demonstrated invariant needs a database constraint or index.
- Add PostgreSQL race coverage to `backend/tests/integration/test_concurrency_<workflow>.py`; shared synchronization helpers belong in `backend/tests/conftest.py` only if at least two tests need them.
- Create `docs/superpowers/notes/2026-10-02-database-concurrency-audit-report.md` with reviewed invariants, evidence, severity, disposition, and residual risk.

### Task 1: Establish baseline and inventory transaction-sensitive flows

**Files:** Read `backend/app/services/`, route/job callers, `backend/app/db/models.py`, and `backend/alembic/versions/`; create the audit report.

- [ ] Record starting revision and run the fast backend suite to separate baseline failures from changes.
- [ ] Inventory service operations that reserve shared resources, perform check-then-write logic, create linked rows, consume one-time tokens, apply imports, claim jobs, or publish external effects.
- [ ] For each operation, record its caller, transaction owner, checked invariant, database constraint/lock, external effects, existing test, and initial risk rating in the report.
- [ ] Inspect lock order across assignments, swaps, constraints, exemptions, hierarchy transfers, soldier updates, imports, and notification/job transitions; record reviewed paths even when no defect is found.
- [ ] Run `git diff --check` and review that the inventory makes no unverified safety claims.

### Task 2: Build deterministic PostgreSQL race tests for confirmed candidates

**Files:** Create `backend/tests/integration/test_concurrency_<workflow>.py` for each confirmed candidate; modify `backend/tests/conftest.py` only for reusable independent-session/barrier fixtures.

- [ ] For each candidate, write a test using two independent SQLAlchemy sessions and `threading.Barrier` or explicit events to stop both transactions after the contested read and before the write.
- [ ] Assert the invariant directly in the database after both operations finish: exactly one winner, no duplicate reservation, no partial linked rows, or the expected conflict status.
- [ ] Run the test against the PostgreSQL integration fixture and capture the failing outcome on the unmodified implementation.
- [ ] Add equivalent negative/control coverage for a non-conflicting request if needed to show normal behavior remains accepted.
- [ ] Update the audit report with the reproduced schedule and database state; remove any candidate that could not be demonstrated from the confirmed-findings list.

### Task 3: Fix confirmed critical/high findings

**Files:** Only the service/route/job files and Alembic revisions named for reproduced findings; regression test files from Task 2.

- [ ] Choose the narrowest database-backed repair supported by the invariant: unique/exclusion constraint, conditional `UPDATE ... WHERE`, `SELECT ... FOR UPDATE`, optimistic version predicate, or a shorter transaction with an existing idempotent handoff.
- [ ] Implement one fix at a time and ensure the contested read/check is repeated or protected inside the transaction that writes.
- [ ] If a database constraint is needed, write migration upgrade/downgrade behavior and migration tests before relying on it in the service.
- [ ] Re-run the new PostgreSQL race test and confirm it now produces the required single-winner/atomic result without sleeps.
- [ ] Run the focused workflow tests and check permissions, API error mapping, and lock order on every caller of the changed service.

### Task 4: Address rollback, retry, lock-order, and side-effect findings

**Files:** The additional confirmed service/job modules and regression tests; audit report.

- [ ] Add a failure-injection test at each confirmed multi-row transaction boundary and assert rollback leaves no partial state.
- [ ] Add retry/idempotency coverage for each confirmed retryable database error or duplicate job claim; assert external effects occur at most once.
- [ ] Move network, email, object-storage, or long solver work outside the transaction where the reproduction shows locks are held across it; retain a tested outbox/idempotent handoff when atomicity requires one.
- [ ] Encode a consistent lock acquisition order in each affected workflow and add a competing-workflow test when opposite order was reproduced.
- [ ] If a medium/low finding remains, record impact, evidence, recovery path, owner, and why deferral is reasonable; if a critical/high issue needs a product choice, stop that fix and record the decision needed without weakening safeguards.

### Task 5: Complete report and verification

**Files:** `docs/superpowers/notes/2026-10-02-database-concurrency-audit-report.md` and all focused regression tests.

- [ ] Complete the severity-ranked report for every inventory row with evidence, result, disposition, and test reference.
- [ ] Run all new concurrency tests against PostgreSQL and the focused suites for changed workflows.
- [ ] Run the fast backend suite; compare failures with the Task 1 baseline and report any unchanged failures explicitly.
- [ ] Run Alembic upgrade/downgrade validation for new revisions and verify the schema at head.
- [ ] Confirm every critical/high item is fixed and tested or explicitly awaiting a product decision, and list remaining untested boundaries.

## Execution Handoff

This plan covers a broad audit with several independent workflows. Use subagent-driven execution only after review of this plan; keep each workflow's service, migration, tests, and report entry together, then perform an integrated lock-order and full-suite review.
