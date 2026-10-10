# Transparency Keyset Read Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the common transparency view from a current indexed scoring read model with stable keyset cursors, while preserving the snapshot path for other filters and fallback.

**Architecture:** Add a versioned, rebuildable relational model containing the canonical per-Soldier scoring/display scalars and a generation freshness fence. A coalesced background worker publishes complete generations. The default burden-share descending route reads an authorized bounded slice and summary from the current generation; existing immutable snapshots continue to serve non-default queries, v2 cursors, and periods without a ready generation.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, PostgreSQL, pytest/Testcontainers, React Query and the existing `CursorPagedTable` virtualization.

**Spec:** `docs/superpowers/specs/2026-10-05-transparency-keyset-read-model-design.md`

## Global Constraints

- Optimize only `sort=burden_share`, descending, empty search, and no node/officer/service/group/rank filter in the first fast-path release.
- Keep the current `/scoring/transparency/page` response fields and the snapshot path for every unsupported query combination and stale/missing model fallback.
- Keyset order is `burden_share DESC, soldier_id ASC`; cursor score values must round-trip losslessly from the stored numeric key.
- Keep full-population normalization independent of the requesting viewer's visibility.
- Preserve the current self-row and scoped-row authorization behavior, and return exemption detail only after applying the existing scope visibility rules.
- Read page size is at most 100; use one extra row to compute `has_more`.
- A source-generation/date-stale cursor returns 409; invalid signature/shape/binding returns 400; revoked transparency access remains 403.
- Do not claim a performance gain without separately measured model build, current-model API, fallback API, continuation API, and matched browser readiness results on the isolated 20k dataset.
- Leave unrelated worktree changes unstaged and untouched. Make each task commit contain only that task's files.

## Review Focus

1. Source writes during model build or page query must never publish or return mixed generations; test the journal race and post-read fence.
2. Non-admin visibility must include the viewer's own row plus only authorized scope rows; exemption details and aggregate flags must remain redacted outside scope.
3. Equal burden shares must cross page boundaries exactly once using the numeric score and UUID tiebreaker; row numbers must remain continuous.
4. Missing, incomplete, stale, or failed models must use the existing snapshot fallback; old v2 cursors must continue to resolve through that path.
5. Date rollover, empty/single-row summary populations, and projection-readiness fallback must preserve their current response semantics.

---

### Task 1: Versioned transparency read-model storage and builder

**Files:**
- Create: `backend/alembic/versions/20261005_transparency_read_model.py`
- Create: `backend/app/services/transparency_read_model.py`
- Create: `backend/tests/integration/test_transparency_read_model.py`
- Modify: `backend/tests/support/database.py`

**Interfaces:**
- `capture_source_state(session) -> tuple[int, str]` returns source generation and `pg_current_snapshot()` text.
- `source_changed_since_snapshot(session, snapshot: str) -> bool` uses the same journal visibility rule as the current paged route.
- `current_generation(session, *, source_generation: int, as_of: date) -> dict | None` returns only a ready exact match.
- `rebuild_generation(session) -> dict | None` builds rows via `app.services.scoring.transparency_rows(session, viewer=None)`, persists them in batches, validates the captured source fence, and atomically publishes a complete generation. It returns `None` if source input changed or projections are not ready.
- `read_page(session, *, generation_id: UUID, viewer: Soldier, visibility: SoldierScopeVisibility, after_score: Decimal | None, after_soldier_id: UUID | None, limit: int) -> list[dict]` returns no more than `limit` authorized read-model rows in stable keyset order. It does not load exemption records.
- `read_summary(session, *, generation_id: UUID, viewer: Soldier, visibility: SoldierScopeVisibility) -> dict` returns scalar aggregates over the same authorized rows.

- [ ] **Step 1: Write failing PostgreSQL tests** for generation schema, incomplete generations being invisible, exact-current generation lookup, batch row persistence, and abort when source generation/journal changes during build. Assert persisted score ordering keys use `NUMERIC` and UUID values, not JSONB ordinal payloads. Exercise `read_page`/`read_summary` parity for admins and scoped viewers, including expanded commander/DM ancestors, `sees_every_soldier`, rank-threshold visibility, self rows outside scope, and Soldiers without a node. Verify old-generation pruning leaves only current plus previous completed generation.
- [ ] **Step 2: Run the tests and confirm the expected RED failures.**

Run from `backend/`:

```powershell
python -m pytest -n 0 -q --tb=short tests/integration/test_transparency_read_model.py
```

Expected: failures because the new migration and read-model service do not exist.

- [ ] **Step 3: Add the derived read-model migration.** Create generation metadata with UUID ID, source generation, captured source snapshot, as-of date, normalization denominator, ready state, and timestamps. Create one row per `(generation_id, soldier_id)` with numeric burden share and scores, active/shift counts, offset, `is_globally_exempted`, and the display scalars needed by the default table. Add `(generation_id, burden_share DESC, soldier_id ASC)` and the generation/soldier primary key. Cascade-delete model rows with their generation. Downgrade only these derived tables and indexes.
- [ ] **Step 4: Implement the service interfaces.** Build through the existing `transparency_rows` function so there is one scoring formula. Capture generation/snapshot before reading, persist scalar rows in bounded batches, check generation/journal/as-of again before atomically marking ready, and leave partial generations unreadable. Build viewer visibility once with `build_soldier_scope_visibility`; mirror `can_view_soldier_scope_fast` in SQL using expanded commander/DM ancestor IDs, `sees_every_soldier`, and rank-threshold fields, plus the self-row exception. Implement authorized SQL page selection and scalar summary aggregates. Preserve the existing global normalization denominator. After publishing, prune generations older than the current and immediately previous completed generation. Leave page-sized exemption record loading/redaction to the route layer in Task 3.
- [ ] **Step 5: Include the new tables in the test reset list and run the focused RED/GREEN suite.** Verify aborted publication leaves no ready partial generation and exact cursor boundary predicate returns the expected order.
- [ ] **Step 6: Run Ruff and `git diff --check`, inspect the migration chain for a single head, then commit only Task 1 files.**

---

### Task 2: Coalesced refresh worker and lifecycle integration

**Files:**
- Create: `backend/app/transparency_read_model_worker.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/unit/test_transparency_read_model_worker.py`
- Modify: `backend/tests/integration/test_transparency_read_model.py`

**Interfaces:**
- `transparency_read_model_worker._refresh_tick() -> bool` acquires one PostgreSQL transaction-scoped advisory lock, reads the current source generation/as-of date, and calls Task 1's `current_generation` / `rebuild_generation` only when stale or missing.
- `run_transparency_read_model_worker() -> None` runs an immediate first tick, then polls every 10 seconds so a stale model does not leave requests on the fallback path for a minute.
- Startup runs the worker alongside existing maintenance workers; `JUSTICE_TESTING=1` continues to skip all background workers.

- [ ] **Step 1: Add failing worker tests** for one build when stale, no duplicate build when two ticks race for the advisory lock, no rebuild for a current generation, retry after build failure, and cancellation-safe polling behavior.
- [ ] **Step 2: Run the focused worker tests and confirm RED.**

```powershell
python -m pytest -n 0 -q --tb=short tests/unit/test_transparency_read_model_worker.py
```

- [ ] **Step 3: Implement the worker using the existing `session_scope` and transaction-scoped advisory-lock patterns.** Run blocking database work through `asyncio.to_thread`; commit a completed generation in one transaction; log generation ID, source generation, result, and duration without logging row payloads; sleep 10 seconds between ticks.
- [ ] **Step 4: Register and cancel the worker in `app.main.lifespan`.** Preserve the current test-mode short circuit and clean cancellation behavior.
- [ ] **Step 5: Add integration coverage that a worker tick publishes one complete current generation and that a second tick reuses it. Run focused worker and read-model tests.**
- [ ] **Step 6: Run Ruff and `git diff --check`, then commit only Task 2 files.**

---

### Task 3: Default-route keyset cursors with snapshot compatibility

**Files:**
- Modify: `backend/app/routes/scoring.py`
- Create: `backend/tests/integration/test_transparency_keyset_api.py`
- Modify: `backend/tests/integration/test_transparency_page_snapshots.py`
- Modify: `backend/tests/integration/test_scale_cursor_revisions.py`

**Interfaces:**
- Add private helpers `_transparency_keyset_binding(...)`, `_transparency_keyset_cursor(...)`, and `_transparency_keyset_page(...)` in `routes/scoring.py`.
- Dispatch a first-page request to the fast path only for the exact default query shape. Requests with a valid `transparency-page-v2` cursor stay on the snapshot path; requests without a ready read model use the existing snapshot builder.
- New cursors use purpose `transparency-page-v3` and contain binding, model ID, source generation, as-of date, exact score string, Soldier UUID, emitted-row count, and expiry.

- [ ] **Step 1: Add failing endpoint tests** for default first page, multiple continuations, equal-score boundary, continuous row numbers, full authorized summary, scoped self-row visibility, exemption redaction, invalid/binding/stale errors, default fallback without a model, and an existing v2 cursor continuing against its saved snapshot.
- [ ] **Step 2: Run the new endpoint tests and verify the failures are caused by the absent v3 fast path.**

```powershell
python -m pytest -n 0 -q --tb=short tests/integration/test_transparency_keyset_api.py tests/integration/test_transparency_page_snapshots.py tests/integration/test_scale_cursor_revisions.py
```

- [ ] **Step 3: Implement v3 cursor binding/signing and route dispatch.** Bind user, role, sorted scope roots, supported query shape, page size, model ID, source generation, and as-of date. Preserve v2 token validation and snapshot fallback unchanged.
- [ ] **Step 4: Implement the fast response using Task 1's `read_page` and `read_summary`.** Fetch at most 101 rows for page size 100; batch-load active exemption records only for the returned Soldier IDs; apply `scope_root_ids` to labels/details and the existing aggregate-visibility rule to the three exemption flags; assign row numbers from the cursor's emitted count; and use the existing response schemas. Do not call the full-population `transparency_rows` builder to decorate a keyset page.
- [ ] **Step 5: Recheck source generation/journal/date and authorization after reading the page.** Return 409 for stale generation/date, 400 for invalid token or binding, and 403 for revoked transparency access. Verify the frontend can use the new opaque cursor without changes and still resets on 409.
- [ ] **Step 6: Run the focused integration suites, Ruff, and `git diff --check`; commit only Task 3 files.**

---

### Task 4: Matched scale verification and report update

**Files:**
- Create: `backend/tests/performance/transparency_keyset_read_model_benchmark.py`
- Create: `backend/tests/unit/test_transparency_keyset_read_model_benchmark.py`
- Create: `docs/benchmarks/data/transparency-keyset-read-model-20261005.json`
- Modify: `docs/benchmarks/2026-09-29-scale-20k-pages.md`
- Modify: `docs/superpowers/plans/2026-09-30-scale-page-optimizations.md`

**Interfaces:**
- The benchmark requires `JUSTICE_SCALE_DATABASE_URL` pointing to an isolated database name containing `_scale` or `_perf`; it must refuse the normal `justice` database and must not seed or mutate unrelated rows.
- It records model build, current-model first-page API, fallback first-page API, continuation API, response bytes, SQL count/time, and query plan separately. Browser page-ready results are recorded only when a browser run actually completes.

- [ ] **Step 1: Add failing/contract tests for benchmark target safety and the JSON artifact schema.** Reuse the existing seed target-safety helpers and do not run against the development database.
- [ ] **Step 2: Run the focused benchmark-script tests and verify the expected failures.**
- [ ] **Step 3: Implement the benchmark runner with repeated current-model first-page and continuation samples, a separate stale/missing-model fallback sample, SQL event timing, and `EXPLAIN (ANALYZE, BUFFERS)` capture.** Keep generated credentials out of artifacts.
- [ ] **Step 4: Prepare or restore a disposable isolated 20k database, apply migrations, seed/backfill, and run the matched API measurements.** If isolated database provisioning or the target browser environment is unavailable, record the exact missing dependency and leave that measurement explicitly unverified; do not substitute Testcontainers microbenchmarks for endpoint/browser results.
- [ ] **Step 5: Run the matched browser matrix at c1 and agreed concurrent load when the browser environment is available.** Record page-ready and first-render separately from API and SQL timings.
- [ ] **Step 6: Update the performance report and Task 5 ledger with results, fallback frequency/build lag, raw artifact path, regressions, and any still-open <2 s / <500 ms targets.** Run the full backend fast suite, changed-file Ruff, Alembic single-head check, benchmark safety tests, and `git diff --check`; commit only Task 4 files/artifacts.

---

## Integration review before implementation

The plan is sequential by interface: Task 1 produces the model service used by Task 2's worker and Task 3's endpoint; Task 2 publishes the current generation Task 3 reads; Task 4 measures Tasks 1–3. No implementation tasks may be dispatched in parallel because each adds to the same read-model interface. The existing snapshot route and v2 token remain the fallback contract throughout.
