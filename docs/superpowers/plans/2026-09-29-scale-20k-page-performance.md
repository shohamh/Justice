# 20,000-Soldier Scale Seed and Page Performance Profile Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task by task. Keep all changes in the scale worktree. Do not commit unless the user explicitly asks for delivery.

**Goal:** Add a guarded, repeatable 20,000-soldier scale seed and produce measured page-load evidence plus prioritized optimization plans.

**Architecture:** A backend CLI writes deterministic synthetic records in bounded PostgreSQL batches and rejects unsafe database targets. A local-only profiling runner observes real browser navigation, API responses, SQL counts/times, and main-thread long tasks; it emits JSON consumed by the benchmark report. The report separates current observations, historical 10k measurements, and proposed optimization targets.

**Tech Stack:** Python 3.12, SQLAlchemy 2, PostgreSQL 16, FastAPI, React/Vite, Playwright, Markdown, JSON.

**Spec:** `docs/superpowers/specs/2026-09-29-scale-20k-page-performance.md`

## Global Constraints

- Seed target comes only from `JUSTICE_SCALE_DATABASE_URL`; reject database names equal to `justice` or `postgres`, and require `_scale` or `_perf` in the target name.
- Never delete/update rows outside the reserved `SCALE20-` synthetic namespace.
- Default dataset is 20,000 synthetic soldiers, 400 teams, 2 years of assignment history, about 1,000,000 duty assignments, 20,000 HR profiles, and 1% review exceptions.
- Never call an external HR provider during profiling.
- Keep benchmark output free of database URLs, passwords, tokens, and personal data.
- Measure the current branch before recommending optimizations; do not implement those optimizations in this task.
- Run focused tests for the seed utility and run the requested scale measurements; do not claim a check passed without its actual output.

## Review Focus

- Unsafe database name or missing scale URL: fail before connecting or writing.
- Partial rerun after interruption: reuse stable identifiers and fill missing batches without duplicating records.
- Existing reserved-namespace collision with incompatible data: stop with a clear error and preserve all rows.
- Assignment history spanning the requested date window: validate generated minimum/maximum dates and total count.
- HR provider unavailable or not configured: report the external sync path as unmeasured and continue measuring the local review page.

---

### Task 1: Guarded synthetic scale seed

**Files:**
- Create: `backend/app/scripts/seed_scale_test.py`
- Create: `backend/app/scripts/tests/test_seed_scale_test.py`
- Modify: `backend/app/scripts/README.md` only if that file exists; otherwise add usage to the benchmark report.

**Interfaces:**
- CLI: `python -m app.scripts.seed_scale_test [--soldiers N] [--team-size N] [--history-years N] [--assignments-per-year N] [--hr-exception-ratio R]`.
- Database URL: required environment variable `JUSTICE_SCALE_DATABASE_URL`; do not accept the normal `DATABASE_URL` fallback.
- Seed data uses the app's `Soldier`, `HierarchyNode`, `DutyAssignment`, `SoldierHrProfile`, and HR review models; all writes are idempotent and scoped to generated personal numbers beginning with `SCALE20-`.
- Assignment generation uses deterministic date/user/type distribution, bounded batches of at most 10,000 rows, and the existing duty type/location fixtures from the regular seed.

- [ ] **Step 1: Add failing tests for target validation and pure dataset shape**

Create tests that call the seed module's URL validator and deterministic row builders without a database. Assert that missing URL, `justice`, `postgres`, and names without `_scale` or `_perf` are rejected; `justice_scale_20k` is accepted. Assert the default configuration creates 20,000 soldier identities, 400 team assignments, 1,000,000 duty-assignment identities, 20,000 HR profiles, and deterministic first/last identifiers and dates.

- [ ] **Step 2: Run the focused tests and record the expected initial failure**

Run from `backend/`:

```powershell
..\.venv\Scripts\python.exe -m pytest app/scripts/tests/test_seed_scale_test.py -q
```

Expected: collection fails because `seed_scale_test` and its configuration/validation functions do not exist yet.

- [ ] **Step 3: Implement URL safety and deterministic generation**

Add a small configuration dataclass and pure helpers for target URL validation, stable synthetic personal numbers, UUID5 record keys, team assignment, HR status assignment, and 730-day duty-date distribution. Parse the target database name with SQLAlchemy's URL parser and raise before engine creation if the target fails the global constraints.

- [ ] **Step 4: Add bounded idempotent PostgreSQL writes**

Read the base root node, active duty types, and active duty locations from the target. Create 400 uniquely named team nodes under the configured root, generate 20,000 soldiers with synthetic identity fields and one shared valid test-only password hash, insert 20,000 HR profiles with 1% split among review statuses, and insert about 1,000,000 published duty assignments in batches no larger than 10,000. On rerun, count and reuse matching synthetic rows; if a reserved personal number exists with a conflicting node or field shape, abort without deleting or rewriting unrelated data. Print only aggregate counts and elapsed phases.

- [ ] **Step 5: Run focused tests and inspect the diff**

Run the focused test command above, then run `git diff --check`. Confirm the tests pass, batch size is capped, and stdout contains no URL or password.

---

### Task 2: Local page profiling runner

**Files:**
- Create: `frontend/scripts/profile-scale-pages.mjs`
- Create: `backend/app/scripts/profile_scale_server.py`
- Create: `docs/benchmarks/data/.gitkeep` only if the raw-results directory otherwise does not exist.

**Interfaces:**
- Backend runner: `python -m app.scripts.profile_scale_server --port 18000`; adds local-only response headers for SQL query count and accumulated SQL execution time, then serves the normal ASGI app.
- Browser runner: `JUSTICE_SCALE_BASE_URL`, `JUSTICE_SCALE_ADMIN_USERNAME`, `JUSTICE_SCALE_ADMIN_PASSWORD`, optional `JUSTICE_SCALE_RUNS` (default 5), and `--concurrency 1|5|10` (default 1; `JUSTICE_SCALE_CONCURRENCY` is also accepted). Sign in once per invocation, capture Playwright storage state in memory, then create independent client contexts from that state. The app restores each client session with its copied refresh cookie; drain setup traffic before shared cold/warm start barriers.
- By default, output is a run-specific JSON file under `docs/benchmarks/data/`, anchored to the repository root. `JUSTICE_SCALE_OUTPUT` overrides the destination (relative paths are also rooted at the repository); an existing destination is rejected, so prior runs and the historical baseline are never overwritten.
- Output JSON contains only route names, timings, response status/bytes, SQL counts/time, console error summaries, and long-task totals; it includes client/run/batch labels and grouped p50/p95 summaries. Never store request or response bodies, credentials, or personal numbers.

- [ ] **Step 1: Build a minimal browser capture harness**

Use the installed Playwright package. Sign in once in a setup context and capture storage state in memory; do not write its refresh cookie to an artifact. For each client, create a fresh context from a copy of that state, let the app restore its session through the refresh endpoint, and drain/reset setup API activity before the start barrier. Then visit the routes listed in the spec. For each route, wait for its page heading and network quiet for 500 ms, record navigation-to-ready time, tracked API response status/timing/`Content-Length`, page errors, and `PerformanceObserver` long tasks. A same-context revisit records warm behavior. Write JSON only after each client batch completes.

- [ ] **Step 2: Add local SQL timing middleware**

Use SQLAlchemy `before_cursor_execute`/`after_cursor_execute` events and a request-scoped context variable in the profiling server module. Add `X-Scale-Db-Queries` and `X-Scale-Db-Ms` response headers only in this local runner. Verify event context is cleared in `finally` and SQL text/binds are never returned or logged.

- [ ] **Step 3: Exercise the runner against a small isolated smoke dataset**

Start it with the profile database and a reduced `--soldiers 100` seed. Visit each route and assert the output has the expected page set, nonnegative timings, response status values, and no secrets. Do not use the root `justice` database.

- [ ] **Step 4: Run focused tooling checks**

Run:

```powershell
node --check frontend/scripts/profile-scale-pages.mjs
```

Then run the runner's 100-soldier smoke profile and preserve its JSON outside the committed 20k results.

---

### Task 3: 20k run and optimization report

**Files:**
- Create: `docs/benchmarks/2026-09-29-scale-20k-pages.md`
- Create: `docs/benchmarks/data/scale-20k-pages.json`

**Interfaces:**
- The report links the raw JSON result and identifies the source commit, dataset counts, environment, page scenarios, p50/p95, API and SQL breakdowns, and unmeasured paths.
- Optimization plan is grouped by frontend, backend/API, database, and operations; every recommendation names an observed bottleneck, a proposed change, a risk/contract dependency, and a verification metric.

- [ ] **Step 1: Prepare an isolated scale database**

Use a disposable local PostgreSQL database named with `_scale` or `_perf`; apply current Alembic migrations and the normal base seed. Keep the root `justice` database unchanged. Run `seed_scale_test` with default settings and query aggregate counts to confirm 20,000 synthetic soldiers, 400 teams, 1,000,000 duty assignments, 20,000 HR profiles, and 1% review exceptions.

- [ ] **Step 2: Run cold and warm page measurements**

Start the local profiling backend on port 18000 and the worktree frontend on an unused local port. Run five cold-session and five same-session measurements for each workload in the spec. Save JSON without credentials or request/response bodies. If any page fails or a provider is unavailable, record the actual failure and mark that dimension unmeasured.

- [ ] **Step 3: Inspect the slowest routes and database plans**

Rank by p95 page-ready and endpoint duration. For the three slowest database-heavy endpoints, capture `EXPLAIN (ANALYZE, BUFFERS)` on the isolated database using redacted, bounded representative parameters. For UI-heavy cases, compare API completion time with page-ready time and long-task duration.

- [ ] **Step 4: Write evidence-based findings and staged plans**

In the report, separate current observations from the August 10k historical values. For each finding, include endpoint/query evidence, response bytes or rendered row count, likely owner layer, and a phased UI/backend/database/operations remediation proposal. Set follow-up verification targets from the measured baseline; label the spec's 2-second/500-ms targets as proposed.

- [ ] **Step 5: Run final scoped checks**

Run focused seed tests, `node --check`, `git diff --check`, and verify the raw JSON contains no secrets. Do not run full project suites or claim production behavior from the local benchmark.

---

## Execution note

Keep the old `docs/superpowers/specs/2026-08-21-performance-audit-10k-users.md` unchanged. Its 10k direct-service results are historical context; the new report must identify that build/environment difference.
