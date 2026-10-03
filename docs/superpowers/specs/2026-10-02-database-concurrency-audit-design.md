# Database Transaction and Concurrency Audit — Design

Date: 2026-10-02  
Roadmap element: C  
Status: Spec approved by user; implementation plan prepared.

## Context

Justice uses PostgreSQL and SQLAlchemy. Requests often update related rows,
and several services already use row locks or database constraints for specific
workflows. Those safeguards have grown in response to individual incidents;
there is not yet a systematic audit of service transaction boundaries and
race-sensitive invariants across `backend/app/services/*`.

This workstream checks whether concurrent requests can violate domain rules,
lose updates, create duplicate effects, or leave partial state. It produces
reproducible tests and fixes for confirmed high-risk cases, plus a written
record of residual risks.

## Goals

1. Inventory multi-row state changes and externally visible side effects in
   backend services.
2. Identify and reproduce race conditions using independent PostgreSQL
   transactions.
3. Fix confirmed high- and critical-severity issues while preserving current
   API behavior except where an explicit error outcome is required for
   correctness.
4. Add deterministic concurrency regression tests for every accepted fix.
5. Record reviewed low- and medium-severity risks with evidence, impact, and
   rationale for any deferral.

## Non-goals

- Rewriting all services to use a new transaction framework.
- Replacing PostgreSQL with distributed locks or moving relational invariants
  into Redis.
- Broad business-rule changes unrelated to a demonstrated transaction or
  concurrency failure.
- Claiming that single-session unit tests prove concurrent correctness.
- Deploying additional replicas or changing production infrastructure as part
  of the audit.

## Audit boundaries

Review service methods and their route/job callers together. Include workflows
that reserve or mutate shared resources, perform check-then-write sequences,
create linked rows, consume one-time tokens, apply imports, or publish external
effects. Initial attention should include assignments, swaps, constraints,
exemption requests, hierarchy transfers, soldier updates, import confirmation,
and job/notification state transitions. Existing `with_for_update()` calls,
unique constraints, and idempotency handling are audit subjects: confirm their
scope and lock order rather than assuming their presence proves safety.

Review each transaction for:

- reads that authorize or validate a later write, and whether the checked row
  is locked or the write is conditional;
- uniqueness, capacity, ownership, status-transition, and “only one winner”
  invariants that need database enforcement;
- multi-row mutations that can be partially committed or observed halfway;
- lost updates and stale decisions made before a transaction begins;
- duplicate retries, concurrent token consumption, and concurrent job claims;
- consistent lock ordering and possible deadlocks across call paths;
- database transactions held open while sending mail, calling remote services,
  or streaming files;
- rollback and retry behavior after `IntegrityError`, deadlock, or
  serialization failure.

## Design principles

- PostgreSQL is the source of truth for relational invariants. Prefer unique or
  exclusion constraints, conditional updates, and appropriately scoped row
  locks over process-local locks.
- Use optimistic version checks when conflicts should be detected rather than
  serialized. Return a stable conflict result instead of silently overwriting
  a newer value.
- Keep transactions short. Do not hold row locks across network, email, object
  storage, or long-running solver work. Use existing outbox patterns or a
  reviewed idempotent handoff where atomic database-plus-external effects are
  required.
- Define and follow one lock order for workflows that touch the same rows.
- Preserve current permission checks and re-evaluate them inside the
  transaction when a race could invalidate their result.
- Reproduce a suspected race before fixing it. Each fix must include a
  deterministic PostgreSQL test with independent sessions and explicit
  synchronization barriers; do not rely on sleeps or SQLite behavior.
- Do not make speculative locking changes without evidence. Record
  unconfirmed risks and explain what evidence would confirm them.

## Severity and acceptance

Critical findings can bypass authorization, corrupt core duty assignments, or
duplicate an irreversible external effect. High findings violate a user or
business invariant under a realistic concurrent request. Medium findings
require unusual timing or cause recoverable inconsistency; low findings have
bounded impact and a reliable recovery path.

The workstream is complete when:

1. The service inventory and severity-ranked audit report cover the stated
   boundaries.
2. Every confirmed critical/high finding has a regression test and a fix, or
   is explicitly presented for a product decision before implementation.
3. Medium findings have an owner, impact description, and concrete deferral
   rationale; no finding is silently discarded.
4. The backend suite passes apart from failures independently reproduced on
   the starting `dev` revision, and all new PostgreSQL concurrency tests pass.
5. The report identifies remaining untested concurrency boundaries and does
   not claim that the audit proves freedom from all races.

## Expected deliverables

- A severity-ranked audit report listing each reviewed invariant, evidence,
  result, and disposition.
- Focused service fixes and any required Alembic constraints or indexes.
- Deterministic PostgreSQL concurrency tests for fixed findings.
- A final verification summary suitable for review before merging to `dev`.

