# Scoring Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace repeated all-history scoring work on transparency, fairness, effort breakdown, and dashboard reads with a rebuildable projection that is current immediately after scoring-affecting writes.

**Architecture:** Canonical assignment, override, dismissal, exemption, adjustment, soldier, and hierarchy tables remain authoritative. A scoring projection stores per-soldier totals and quarter buckets; a shared service rebuilds affected buckets from canonical rows in the same transaction, while read services use the projection only after a completeness check and retain the legacy path as a diagnostic/fallback during rollout.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, PostgreSQL, Alembic, pytest.

**Spec:** `docs/superpowers/specs/2026-08-21-scoring-projection-design.md`

## Global Constraints

- Existing canonical assignment, override, dismissal, exemption, adjustment, soldier, and hierarchy tables remain authoritative.
- A committed scoring-affecting write is visible to subsequent scoring reads.
- Missing, incomplete, or divergent projection data never silently replaces a correct canonical result.
- Every projection bucket is rebuildable from canonical data.
- The optimized result preserves all-time score semantics, reserve and call-up multipliers, dismissal handling, effective-soldier overrides, exemption-covered active days, quarter boundaries, and normalization rules.
- Normal reads must not hydrate or iterate all historical assignment rows in Python.
- Backfill and rebuild operations are resumable, idempotent, and partitioned by soldier/quarter.

---

### Task 1: Lock down the canonical/projected scoring contract

**Files:**
- Create: `backend/app/services/score_projection.py`
- Create: `backend/app/services/tests/test_score_projection.py`
- Modify: `backend/app/services/scoring.py:388-668` only where a shared input helper is required

**Interfaces:**
- Consumes: existing `effective_duty_days`, `DutyAssignment`, `DutyDayOverride`, `DutyDismissal`, `ScoreAdjustment`, and `quarter_start` semantics.
- Produces: `ProjectionBucket`, `project_soldier_bucket(session, soldier_id, quarter_start_value)`, and `project_all_buckets(session, soldier_ids=None, quarter_starts=None)`; these are rebuild-only helpers and must return raw Decimal values, not formatted API rows.

- [ ] **Step 1: Write differential tests first.** Build fixtures covering ordinary multi-day assignments, reserve standby/call-up multipliers, a dismissal, a day override that changes the effective soldier, a manual adjustment, a quarter boundary, and a full-coverage exemption. Assert the projection bucket's duty score, shift count, adjustment score, and quarter key match the existing canonical service outputs.
- [ ] **Step 2: Run the focused tests and verify they fail** because the projection module and bucket contract do not exist.
- [ ] **Step 3: Implement the pure bucket contract.** Reuse the canonical scoring semantics rather than duplicating multiplier rules. A bucket must contain `soldier_id`, `quarter_start`, `duty_score`, `adjustment_score`, `shift_count`, and `source_fingerprint`; the fingerprint must include the canonical row identifiers and values used for that bucket so drift can be detected.
- [ ] **Step 4: Add bounded-scope rebuild support.** `project_soldier_bucket` may inspect only canonical rows relevant to the requested soldier and quarter; `project_all_buckets` must accept optional soldier and quarter filters and be safe to rerun.
- [ ] **Step 5: Run `pytest -q backend/app/services/tests/test_score_projection.py` and the existing scoring service tests.**
- [ ] **Step 6:** Commit with message `feat: define scoring projection bucket contract`.

### Task 2: Add projection tables and idempotent rebuild/backfill

**Files:**
- Create: `backend/alembic/versions/6a7b8c9d0e1f_add_score_projections.py` with `down_revision = "595a35bbf19e"`
- Modify: `backend/app/db/models.py` near scoring models
- Modify: `backend/app/services/score_projection.py`
- Create: `backend/app/services/tests/test_score_projection_persistence.py`
- Create: `backend/app/scripts/score_projection.py`

**Interfaces:**
- Consumes: Task 1 bucket functions.
- Produces: `SoldierScoreProjection`, `SoldierQuarterScoreProjection`, `ScoreProjectionQuarterTotal`, and `ScoreProjectionState` models; `rebuild_projection_bucket(session, soldier_id, quarter_start_value)`; `backfill_score_projection(session, batch_size=500, resume_after=None)`.

- [ ] **Step 1: Write failing persistence tests.** Assert unique keys, foreign keys, Decimal preservation, replacement of an existing bucket, resumable batch boundaries, and no duplicate rows after a second backfill.
- [ ] **Step 2: Run the focused persistence tests and verify failure.**
- [ ] **Step 3: Add the migration with indexes on `(soldier_id)`, `(quarter_start)`, and `(soldier_id, quarter_start)`, plus a state row recording the canonical version and completion status.** Use PostgreSQL UUID/date/numeric types consistent with existing models.
- [ ] **Step 4: Implement transactional bucket replacement and resumable backfill.** Rebuild from canonical data, delete/reinsert only requested buckets, update state in the same transaction, and never mark a bucket complete before replacement succeeds.
- [ ] **Step 5: Run migration upgrade/downgrade checks and focused persistence tests.**
- [ ] **Step 6:** Commit with message `feat: persist rebuildable score projections`.

### Task 3: Wire synchronous freshness and reconciliation

**Files:**
- Modify: `backend/app/services/score_projection.py`
- Create: `backend/app/services/tests/test_score_projection_freshness.py`
- Modify: scoring-affecting service seams found in `backend/app/services/assignments.py`, `reserves.py`, `swaps.py`, `adjustments.py`, exemption services, hierarchy transfer services, and import commit services
- Create: `backend/app/services/score_projection_reconciliation.py`

**Interfaces:**
- Consumes: persisted models and rebuild functions from Task 2.
- Produces: `refresh_projection_for_change(session, *, soldier_ids, affected_dates, old_node_ids=(), new_node_ids=())`; `projection_is_current(session, required_quarters)`; `reconcile_score_projection(session, limit=500)`.

- [ ] **Step 1: Add failing integration tests for each mutation family.** After commit, query the projection and assert it equals canonical recomputation; cover publish/cancel, day override, dismissal, reserve call-up, adjustment, exemption, hierarchy transfer, and import commit.
- [ ] **Step 2: Run the tests to capture the missing freshness behavior.**
- [ ] **Step 3: At each shared application-service seam, collect old/new affected soldier IDs and quarter dates before mutation, then call `refresh_projection_for_change` before the service transaction commits.** Recompute affected buckets from canonical rows; do not use inverse delta arithmetic.
- [ ] **Step 4: Add a dirty/reconciliation record written in the same transaction and a repair routine that rebuilds dirty buckets and records divergence.** Reconciliation must be a safety net, never the only freshness mechanism.
- [ ] **Step 5: Run all focused mutation tests plus the existing assignment, reserve, swap, adjustment, exemption, hierarchy, and import tests.**
- [ ] **Step 6:** Commit with message `feat: keep score projections current on writes`.

### Task 4: Move transparency and fairness reads to shared projection data

**Files:**
- Modify: `backend/app/services/scoring.py:544-850`
- Modify: `backend/app/services/effort_score.py:190-510`
- Create: `backend/app/services/tests/test_projected_scoring_reads.py`
- Modify: `backend/app/routes/scoring.py` only if response serialization needs an unchanged contract adapter

**Interfaces:**
- Consumes: `projection_is_current`, projected soldier totals, quarter soldier rows, and quarter totals.
- Produces: shared helpers returning the same Decimal/API shapes as the legacy paths; `transparency_rows` and `fairness_components` must not invoke each other or expand all published assignments during a normal read.

- [ ] **Step 1: Write differential tests comparing legacy and projected output for the complete scenario matrix in the spec, including viewer scoping and exemption visibility.** Add a test proving fairness does not call `transparency_rows`.
- [ ] **Step 2: Run the tests and verify the projected path is not yet selected.**
- [ ] **Step 3: Replace transparency score/shift/effort inputs with bounded projection queries, preserving active-day calculation, normalization, scope filtering, exemption redaction, sorting, and response keys.**
- [ ] **Step 4: Make fairness consume the same projected effort inputs and retain its eligibility graph behavior independently.**
- [ ] **Step 5: Make single-soldier effort breakdown read quarter buckets, while preserving hypothetical-adjustment preview behavior by applying the extra adjustment in memory only.**
- [ ] **Step 6: If a required bucket is missing, incomplete, or divergent, synchronously rebuild that bucket and then retry; if it still cannot be proven current, use the legacy calculation and emit diagnostic logging.**
- [ ] **Step 7: Run focused differential tests, scoring route tests, and the existing effort/fairness tests.**
- [ ] **Step 8:** Commit with message `perf: serve scoring reads from projections`.

### Task 5: Add dashboard integration and rollout observability

**Files:**
- Modify: `backend/app/services/commander_dashboard.py`
- Modify: `backend/app/services/score_projection.py`
- Create: `backend/app/services/tests/test_score_projection_observability.py`
- Modify: `backend/app/routes/scoring.py` if a rollout setting is exposed through existing configuration conventions

**Interfaces:**
- Consumes: projected totals and current-state checks from Task 4.
- Produces: projected dashboard score summaries, dual-read comparison counters/log fields, and an explicit feature setting defaulting to safe fallback behavior until backfill is complete.

- [ ] **Step 1: Write tests for incomplete projection fallback, matching dual-read output, and divergent projection repair.**
- [ ] **Step 2: Implement the rollout gate and structured diagnostics without changing API contracts.**
- [ ] **Step 3: Update dashboard score reads to use the same projection helper, keeping the existing unrelated dashboard optimizations intact.**
- [ ] **Step 4: Run dashboard service tests and the full scoring-related suite.**
- [ ] **Step 5:** Commit with message `perf: share score projections with dashboard reads`.

### Task 6: Verify scale, backfill operation, and documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-08-21-scoring-projection-design.md` only if implementation decisions need recording
- Create: `docs/performance/scoring-projection-runbook.md`
- Create or modify: performance test/benchmark support under `backend/tests/performance/` following existing conventions

**Interfaces:**
- Consumes: completed projection migration, backfill, mutation hooks, and projected reads.
- Produces: measured evidence for 10,000 soldiers/500,000 assignments, a resumable backfill command, repair instructions, and a differential benchmark.

- [ ] **Step 1: Add a benchmark that records DB query count/time, Python processing time, and mutation refresh time separately.**
- [ ] **Step 2: Run the benchmark against the disposable overloaded database and verify normal transparency/fairness reads no longer expand all assignment history.**
- [ ] **Step 3: Run `pytest -q`, the relevant migration checks, and frontend type/lint checks if API code changed.**
- [ ] **Step 4: Document deployment order, backfill resume behavior, fallback behavior, reconciliation, and rollback.**
- [ ] **Step 5:** Commit with message `docs: document scoring projection rollout`.
