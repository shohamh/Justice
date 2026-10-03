# 20,000-Soldier Scale Seed and Page Performance Profile

Date: 2026-09-29

## Goal

Provide a repeatable, safe 20,000-synthetic-soldier dataset and use it to measure the slow Justice pages end to end, then give a prioritized optimization plan across frontend, API, database, and runtime.

## Scope

- Add a new backend scale-seed command. It adds 20,000 synthetic soldiers, distributes them among 400 synthetic teams, adds two years of published duty history at about 25 assignments per soldier per year (about 1,000,000 assignment rows), and adds synthetic HR profiles plus a small review-exception queue. Existing demo users and settings remain intact.
- Use a stable synthetic namespace so reruns are idempotent. The command must use batched PostgreSQL writes and must refuse a production/default database target. It requires an explicit `JUSTICE_SCALE_DATABASE_URL` targeting a database whose name contains `_scale` or `_perf`.
- Profile the HR sync review, transparency/fairness, hierarchy management, individual-soldier detail, calendar, and commander dashboard flows. Measure cold page readiness, API request duration/status/count, response bytes, and per-request database query count/time. Capture p50 and p95 over repeated runs and separate page rendering from API/DB time.
- Compare the new run with the archived 10,000-soldier report only as historical context. That report measured a different August build and database; its numbers are not a before/after comparison for this run.
- Do not execute a live HR provider sync. The HR page workload uses local synthetic profiles and review records; external-provider time is explicitly reported as unmeasured.
- Do not implement the page optimizations in this change. The final report gives concrete UI, API, database, and operations work packages with measurable acceptance targets.

## Dataset shape

| Data | Default size | Purpose |
|---|---:|---|
| Synthetic soldiers | 20,000 added | Exercises lists, hierarchy membership, profiles, and search |
| Synthetic teams | 400, 50 soldiers each | Exercises hierarchy tree and team distribution |
| Published duty assignments | About 1,000,000 over 730 days | Exercises calendar, duty history, transparency, and score reads |
| HR profiles | 20,000 | Represents a full roster after synchronization |
| HR review exceptions | 1% of profiles, split by review status | Exercises review-list payloads without calling the external HR system |

Names, personal numbers, email addresses, and credentials are synthetic. Generated identities use a reserved `SCALE20-` namespace. The seed writes only rows in that namespace and never deletes or updates unrelated rows.

## Measurement method

- Run against an isolated PostgreSQL database with migrations and the normal demo base seed applied. Keep the root `justice` database unchanged.
- Run the backend and frontend from the same commit in the scale worktree. Record host CPU/memory, PostgreSQL version, worker count, browser version, and dataset counts.
- Use the seeded root administrator to exercise whole-organization scope. For each page, record five cold-session runs and five same-session reloads; report median and p95.
- Record page-ready time, API endpoint wall time and status, response bytes, SQL statement count and accumulated SQL time, console errors, and long tasks over 50 ms. Preserve raw JSON results alongside the Markdown report.
- Treat missing runtime access, unavailable routes, or an unavailable external HR provider as unmeasured; do not substitute estimates for observed values.

## Workloads

1. HR sync review page initial load, using the seeded held/divergent/vanished/conflict review rows. Do not start a synchronization run.
2. Transparency whole-organization initial load and fairness view, including all requests started on initial render.
3. Hierarchy management initial load and visible soldier list at whole-organization scope.
4. Open one synthetic soldier from the hierarchy page and wait for the detail modal's initial data to settle.
5. Calendar whole-organization load for the current month and one team-scoped load.
6. Commander dashboard summary, alerts, and soldier list.

## Hypotheses to test

1. Transparency/fairness latency is dominated by database work across assignment history. The historical 10k run attributed 238.1 of 269.5 seconds to database time for transparency; current measurements must confirm whether this remains true after intervening changes.
2. Hierarchy management is dominated by full-roster response size and client-side grouping/rendering because it loads both the tree and the unpaged soldier list.
3. Individual-soldier opening is affected by request fan-out and serialized UI updates, even when each endpoint is reasonably fast.
4. Calendar load is sensitive to whole-organization scope and date-window size; the tree request and calendar-event request must be measured separately.
5. HR sync review page load is driven by review-queue volume and parallel endpoint count; the external roster fetch/reconciliation path is a separate workload and remains unmeasured unless a safe local provider fixture is available.

## Deliverables

- `backend/app/scripts/seed_scale_test.py` and focused tests for target safety, deterministic generation, batching, and idempotent reruns.
- A reusable local profiling runner that emits machine-readable measurements and does not change production response behavior.
- `docs/benchmarks/2026-09-29-scale-20k-pages.md` with observed measurements, setup details, caveats, ranked root causes, and phased optimization plans for UI, backend, database, and operations.
- Raw result JSON under `docs/benchmarks/data/` with secrets and credentials excluded.

## Proposed optimization acceptance targets

These are targets for the follow-up optimization plans, not claims about the current build: p95 page-ready under 2 seconds for the named read pages, p95 ordinary read API under 500 ms, and no main-thread long task over 200 ms during initial render. Expensive whole-history/admin operations may need separately agreed budgets after their product semantics are confirmed.
