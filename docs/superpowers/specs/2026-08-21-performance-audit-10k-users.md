# Performance Audit — Scaling to 10,000 Users

Date: 2026-08-21

## Summary

The system was load-tested against a database seeded with **10,000 soldiers** spread across 200 teams and **500,200 duty-assignment rows** (2 years of history, ~25 assignments/soldier/year — the realistic steady state once the org has been running this system for a couple of years). Measurements were taken against a locally-run backend (`uvicorn`, single process, matching the production `Dockerfile`/`docker-compose.prod.yml` command exactly) talking to a real Postgres instance — not against unit tests or mocks.

**Verdict: the system does not survive 10,000 users today.** The core commander/admin dashboard — the screen every commander opens on login — takes **22–47 seconds per request** at this scale, and **degrades linearly with concurrent users** because the backend runs as a single OS process with no worker parallelism. Five commanders opening their dashboard at the same moment turns a 22s wait into a 110s wait for all five, and everyone else's requests queue up behind them.

This is not a tuning problem at the margins — it's four compounding architectural gaps that all point at the same handful of endpoints:

1. No pagination anywhere except two endpoints.
2. No caching layer of any kind.
3. Historical queries with no date bound (load *all* duty history ever, every time).
4. Single-process deployment, so CPU-bound response building serializes across users instead of parallelizing.

## Methodology

- Seeded via a one-off bulk script (raw `COPY`, not the ORM — 10k+ row ORM inserts would have taken the audit itself too long) that reused the existing hierarchy/duty-type fixtures from `python -m app.scripts.seed` and added 200 synthetic teams × 50 soldiers, plus 500,200 `duty_assignments` rows dated across the last 730 days.
- Ran `uvicorn app.main:app` locally (same invocation as `backend/Dockerfile:23` and `deploy/docker-compose.prod.yml`), pointed at the seeded Postgres via `DATABASE_URL`.
- Logged in as the root admin (`1000001`) — worst case, since the admin's "subtree" is the entire 10,000-soldier org, exactly what a top-level commander sees.
- Timed real HTTP requests with `curl -w time_total`, and ran a 5-way concurrent request test with a `ThreadPoolExecutor`.
- Ran `EXPLAIN ANALYZE` directly against Postgres for the query pattern behind the slowest endpoint.

## Findings, ranked by severity

### 1. `GET /api/command-dashboard/alerts` — 47.5s per request

`backend/app/services/commander_dashboard.py:373-408`. For every soldier in the commander's subtree, this loop runs a separate `SELECT` for exemption status plus a `session.get()`. At 10,000 soldiers that's ~20,000 round trips to Postgres, each paying full ORM overhead. This is the textbook N+1 pattern, at N=10,000.

**Fix:** batch it. Replace the per-soldier loop with two set-based queries — one `SELECT ... WHERE soldier_id IN (...)` for exemptions, one for whatever the `session.get()` calls are fetching — then join in Python with dicts keyed by `soldier_id`, the same pattern `_score_data` (`commander_dashboard.py:42-84`) already uses correctly for scores. `backend/app/services/commander_dashboard.py:215-234` (`soldiers_in_subtree`) has the identical bug and needs the identical fix.

### 2. `GET /api/command-dashboard/soldiers` — 24.5s, 3.2MB unpaginated response

`backend/app/routes/soldiers.py` and the dashboard soldier-list route return every soldier in the subtree in one response, with no `limit`/`offset`. At 10k soldiers this is a multi-megabyte JSON payload the frontend has to parse and render in one shot, on top of the backend time. Every unpaginated list endpoint (`soldiers`, `hierarchy`, `notifications`) has this problem; only `algorithm.py:651-652` and `bug_reports.py:222` paginate today.

**Fix:** add `limit`/`offset` (or cursor) pagination to every list endpoint that can return one row per soldier or per historical record, with a sane default page size (e.g. 50) and a hard max. This is a contract change the frontend needs to adopt (infinite-scroll or paged tables), so it should land as one coordinated backend+frontend change per endpoint, not a backend-only patch.

### 3. `GET /api/command-dashboard/summary` — 21.8s, driven by an unbounded historical scan

`backend/app/services/commander_dashboard.py:49-58` (`_score_data`) loads **every published `DutyAssignment` ever** for the subtree, with no date filter. `EXPLAIN ANALYZE` on the equivalent query (10,000 soldier IDs, no date bound) shows Postgres correctly choosing a sequential scan — 470ms just for the scan — because the predicate matches ~400,000 of the 500,000 rows in the table; no index changes this once you're asking for most of the table. The real cost above that 470ms is the Python-side ORM hydration and aggregation over ~400k rows, which is where the other ~21 seconds goes.

This is a **design bug, not a missing index**: cumulative score should not require re-scanning all of history on every dashboard load. The query has no reason to look further back than whatever window "cumulative score" is actually defined over.

**Fix, in order of effort:**
- **Short term:** bound the query by a rolling window (matches how the product already talks about score — check whether "cumulative" is meant to be all-time or a rolling period; if all-time, this needs option 2 below, not a date filter).
- **Medium term:** maintain a running per-soldier score total (incremented on assignment publish/cancel, the same way `docs/superpowers/specs/2026-06-23-algorithm-run-load-perf-design.md` denormalized job scores onto `duty_assignments` to kill a similar unbounded-scan problem) instead of recomputing from full history on every read.

### 4. Limited concurrency headroom — only 2 uvicorn workers, and the prod image didn't actually build

**Correction after further investigation:** an earlier version of this doc claimed production ran a single uvicorn process with no worker flag at all. That was wrong — `deploy/docker-compose.prod.yml` already passed `--workers 2`. What I'd missed on first read was the rest of that command line. The load-test numbers in this doc's summary (5 concurrent requests → 110s each) were measured against a **1-worker** local run, which is worse than prod's 2 workers, so treat that specific multiplier as an upper bound, not prod's actual behavior — the qualitative finding (response time degrades with concurrent load on expensive endpoints) still holds, just not at exactly that ratio.

Separately — and this is independent of the 10k-user scale question — `deploy/docker-compose.prod.yml` builds the backend with `target: production`, but `backend/Dockerfile` had no stage named `production` (only one unnamed-target stage, originally `AS base`). **`docker build --target production` failed outright** (verified directly: `target stage "production" could not be found`). As written, the documented prod deploy could not have built. Fixed as part of this pass by renaming the Dockerfile's stage to `production` — worth independently confirming this wasn't masking some other deploy path actually in use.

Route handlers in `commander_dashboard.py` are synchronous `def`s, so FastAPI runs them in a thread pool per worker process, but the CPU-bound Python-side aggregation (hydrating and summing hundreds of thousands of ORM rows) holds the GIL and serializes across threads within a worker. 2 workers gives 2-way process parallelism; at 10,000 users, that's still thin — a handful of commanders opening their dashboard within the same minute will still queue behind each other, just with a lower multiplier than the 1-worker number above.

**Fix implemented:** worker count is now `${WEB_CONCURRENCY:-4}` (`deploy/docker-compose.prod.yml`, `deploy/.env.production.example`) — configurable per host instead of hardcoded, defaulted up from 2 to 4. Also re-check `slowapi`'s in-memory rate-limit store (`backend/app/routes/auth.py`, `algorithm.py`) — in-memory state doesn't share across workers, so per-IP limits are effectively divided by worker count today.

### 5. Connection pool ceiling vs. background workers

`backend/app/db/session.py:12-20` caps the pool at `pool_size=20 + max_overflow=10` = 30 connections per backend process. Seven standalone polling workers (`*_worker.py`) run alongside the API and share this ceiling with user-facing traffic. Findings 1–3 mean a single dashboard load can hold a connection for 20–50 seconds; a modest handful of concurrent dashboard opens plus the background pollers can plausibly exhaust the pool, queuing out unrelated requests (including logins) behind them. Not independently reproduced under this audit's time budget, but it's a direct consequence of findings 1 and 4 combined and should be re-measured once those land.

**Fix:** re-measure pool saturation after fixes 1–3 land (the ceiling may turn out to be adequate once queries are fast). If still tight, raise `pool_size`/`max_overflow` and/or move the pollers to their own DB role with a separate, smaller pool so they can't starve user-facing requests.

### Not yet measured (flag for follow-up, not blocking)

- `UnifiedSoldierModal.tsx` fires multiple independent `useQuery` calls per soldier open (score, range status, constraints, ranks) — fan-out cost not measured at scale in this audit; worth a follow-up pass once 1–3 land, since faster backend queries reduce but don't eliminate the round-trip multiplication.
- The `ortools` CP-SAT scheduling algorithm is CPU-bound and has its own load profile, separate from CRUD traffic; it was already the subject of a prior perf fix (`docs/superpowers/specs/2026-06-23-algorithm-run-load-perf-design.md`) and wasn't re-tested here — flag for a dedicated algorithm-scale audit if job sizes are expected to grow with soldier count.
- `AuditLog` write volume at 10k-user scale (every mutating action logs a row) — not measured; the table has no explicit index today, worth checking for the same query patterns that hit the pre-fix `algorithm.py` audit-log scan.

## Remediation plan

Phased so each phase is independently shippable and each fixes a specific measured number above.

**Phase 1 — stop the bleeding (no schema changes, days not weeks) — DONE 2026-08-21**
- ✅ Batched the two N+1 loops in `commander_dashboard.py` (finding 1): `soldiers_in_subtree`'s per-soldier exemption check and `alerts`'s per-soldier expiring-exemption query are now each a single set-based query (`_active_global_exemption_soldier_ids`, `_soon_expiring_exemptions`). TDD'd with query-count regression tests in `app/services/tests/test_commander_dashboard.py` (`select_count` asserted not to scale with soldier count) plus behavioral tests for the "exempt" status and expiring-exemption alert message. Not yet re-measured against the 10k/500k dataset — the query-count tests prove the fix is O(1) queries instead of O(n), but the wall-clock number in this doc (47.5s) hasn't been re-run; do that before calling finding 1 closed.
- ✅ Made uvicorn worker count configurable (`WEB_CONCURRENCY`, default 4, up from the hardcoded 2) in `docker-compose.prod.yml` / `.env.production.example` (finding 4).
- ✅ Incidental fix: `docker-compose.prod.yml` referenced a `target: production` Docker build stage that didn't exist in `backend/Dockerfile` — the documented prod build was broken independent of scale. Fixed by naming the stage `production`; verified with a real `docker build --target production`.
- Not done in this pass: `soldiers_in_nodes`'s own N+1 exposure via `_score_data`'s unbounded scan (finding 3) is a separate, larger fix — see Phase 2.

**Phase 2 — bound the unbounded (schema + query changes)**
- Decide what "cumulative score" is actually supposed to mean (all-time vs. rolling window) — this is a product question, not just an engineering one, and determines whether finding 3's fix is a date filter or a denormalized running total.
- ✅ The existing scoring contract resolves this as **all-time**: `cumulative_score` is the sum of published assignment days × duty-type score plus score adjustments. `_score_data` now performs the assignment-history total in PostgreSQL with a grouped `SUM`, avoiding ORM hydration of every historical assignment while preserving the dashboard's previous result for that computation. Regression coverage verifies both the numeric result and the aggregate query shape.
- Not yet done: a durable running-score projection. The grouped query still scans the historical rows that match the commander scope, so it is an intermediate improvement rather than the final scale solution. It also deliberately preserves the dashboard's pre-existing assignment scoring semantics; reconciling it with the full effective-day/override scoring service needs a separate correctness decision.

**Phase 3 — pagination (backend + frontend, coordinated)**
- Add `limit`/`offset` to `command-dashboard/soldiers` and the other unpaginated list endpoints (finding 2), paired with frontend changes to consume paged results. Largest-effort item; sequence it after Phases 1–2 since those alone remove the two slowest endpoints.

**Phase 4 — re-measure**
- Re-run this audit's load test against the same 10k-soldier/500k-assignment dataset after Phases 1–3 land, to confirm the numbers actually moved and to check whether the connection-pool ceiling (finding 5) is still a concern once per-request time drops.
- The original bulk-seed/load-test scratch artifacts are not present in this checkout, and the persistent local database currently contains only 120 soldiers and 8 assignments. The Phase 1 and Phase 2 changes therefore have focused regression evidence but no new 10k-scale wall-clock measurement yet.

## Reproducing this audit

The bulk-seed script and load-test commands used here were throwaway (not committed — they live in a scratch directory, not the repo). To repeat:
1. Seed base fixtures: `python -m app.scripts.seed` (from `backend/`, with `DATABASE_URL` pointed at a local Postgres).
2. Bulk-generate 10k soldiers + 2 years of duty history via raw `COPY` (see this audit's session for the exact script — reusing existing hierarchy/duty-type/duty-location rows, ~500k `duty_assignments` rows, ~25/soldier/year).
3. Run `uvicorn app.main:app` locally against that DB, log in as `1000001` / `1234567890` (the seed script's default password), and time `GET /api/command-dashboard/{summary,soldiers,alerts}` — those three endpoints alone reproduce every finding above.
