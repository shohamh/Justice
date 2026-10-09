# Shell and page-load optimization: benchmarks

Spec: `docs/superpowers/specs/2026-10-08-shell-and-page-load-design.md`.
Plan: `docs/superpowers/plans/2026-10-08-shell-and-page-load-optimization.md`.

## Baseline (before any optimization), 2026-10-09

### Setup

- Frontend: production Vite build (`npx vite build`, served by `vite preview` on `127.0.0.1:5174`, proxying `/api` to the backend). Entry chunk `assets/index-BGCgDM-q.js` = 3,989.42 kB raw (1,099.94 kB gzip).
- Backend: `python -m app.scripts.profile_scale_server --port 8100` (adds server-timing and DB-query-count headers), `TRANSPARENCY_READ_MODEL_ENABLED=true`, `LOKI_URL` unset (so `/api/admin/errors/unread-count` answers 503).
- Data: Postgres container `justice-scale-20k`, database `justice_scale_fcp_scale`: 20,120 soldiers, 1,000,008 duty assignments. Redis on 6379.
- Profiler: `frontend/scripts/profile-scale-pages.mjs`, 5 runs per scenario, c1 (70 measurements) and c5 (350 measurements); every measurement reached readiness. A discarded 1-run warm-up preceded both.
- Git SHA of the code measured: `e03c9532` (application code identical to the branch base `09a5b787`; the commits on top only add the summarizer and a profiler login fix).
- Artifacts: `docs/benchmarks/data/shell-load-before-c1-20261008.json`, `docs/benchmarks/data/shell-load-before-c5-20261008.json`. Read them with `node frontend/scripts/summarize-scale-pages.mjs <artifact> [<baseline>]`.
- Machine caveat: a developer workstation with other applications running (browser, IDE, Docker Desktop, other worktrees idle); values are comparable only against runs on this same setup and carry noise, especially the c5 p95 values.
- Profiler fix made for this capture: the login helper now waits for network idle before submitting. Without it the app's startup session-restore can finish after the submit and abort the in-flight login (the page stays on `/login`), which made the profiler time out against the production build.

### Page readiness and FCP (ms; p50/p95)

c1:

| Scenario | Mode | Ready | FCP | Requests |
|---|---|---|---|---|
| home-dashboard | cold | 5917/6068 | 1272/1316 | 39 |
| home-dashboard | warm | 5902/6174 | 712/756 | 39 |
| calendar-synthetic-team | cold | 6302/6569 | 1292/1316 | 23 |
| calendar-synthetic-team | warm | 5905/6212 | 708/736 | 23 |
| calendar-whole-organization | cold | 4243/4413 | 1268/1316 | 18 |
| calendar-whole-organization | warm | 3711/3727 | 528/584 | 18 |
| hierarchy-whole-organization | cold | 4357/4487 | 1288/1328 | 16 |
| hierarchy-whole-organization | warm | 1829/1842 | 836/840 | 13 |
| hr-sync-review | cold | 4154/4346 | 1216/1364 | 20 |
| hr-sync-review | warm | 2035/2065 | 724/748 | 16 |
| soldier-detail | cold | 5739/6521 | 1256/1412 | 20 |
| soldier-detail | warm | 1550/1604 | - (SPA navigation) | 4 |
| transparency-whole-organization | cold | 2214/2266 | 1296/1312 | 10 |
| transparency-whole-organization | warm | 1346/1352 | 436/440 | 10 |

c5:

| Scenario | Mode | Ready | FCP | Requests |
|---|---|---|---|---|
| home-dashboard | cold | 14116/14259 | 1556/1612 | 39 |
| home-dashboard | warm | 13714/14144 | 1052/1116 | 39 |
| calendar-synthetic-team | cold | 10920/11475 | 1564/1896 | 23 |
| calendar-synthetic-team | warm | 10050/11477 | 732/1124 | 23 |
| calendar-whole-organization | cold | 8168/9199 | 1516/1628 | 19 |
| calendar-whole-organization | warm | 7733/9704 | 1048/1156 | 19 |
| hierarchy-whole-organization | cold | 7589/8018 | 1592/1696 | 17 |
| hierarchy-whole-organization | warm | 2164/6639 | 860/1240 | 13 |
| hr-sync-review | cold | 7288/8390 | 1532/1800 | 20 |
| hr-sync-review | warm | 3701/6159 | 748/1140 | 20 |
| soldier-detail | cold | 9569/10046 | 1512/1544 | 21 |
| soldier-detail | warm | 2512/2839 | - (SPA navigation) | 4 |
| transparency-whole-organization | cold | 2677/7790 | 1584/1652 | 10 |
| transparency-whole-organization | warm | 1618/5202 | 508/4244 | 10 |

Aggregates: FCP cold p50 across all pages is 1272 ms (c1) and 1536 ms (c5). `GET /api/ranges/ineligible-soldiers/count` cold p50 is 1229 ms (c1) and 4144 ms (c5) wall, 917 ms and 3780 ms server-side.

### Duplicate requests (home-dashboard cold, median per page load)

`GET /api/admin/errors/unread-count` x3 (all 503 with Loki unset; 134 requests in the c1 artifact, 836 in the c5 artifact), `POST /api/auth/refresh` x2, `GET /api/settings/public` x2, `GET /api/duty-config/duty-types` x2, `GET /api/hierarchy/level-types` x2, `GET /api/ranges` x2, `GET /api/calendar/shifts` x2. The other pages show the same shell-level duplicates (errors unread-count x2 on calendar, hierarchy, hr-sync and soldier-detail cold).

### Top endpoints by total time per page (c1 median, ms)

| Page (cold) | Top 5 |
|---|---|
| home-dashboard | command-dashboard/alerts 1794; calendar/shifts 1741 (x2); duty-config/duty-types 1716 (x2); ranges 1604 (x2); potential/summary 1575 |
| calendar-synthetic-team | errors/unread-count 1447 (x3); ineligible-soldiers/count 1242; nav/counts 1199; hierarchy/branches 782 (x2); ranges 752 (x2) |
| calendar-whole-organization | errors/unread-count 1396 (x2); ineligible-soldiers/count 1248; nav/counts 1203; ranges 393; hierarchy/branches 384 |
| hierarchy-whole-organization | errors/unread-count 1386 (x2); ineligible-soldiers/count 1308; nav/counts 996; soldiers/roster 703; hierarchy/branches 398 |
| hr-sync-review | errors/unread-count 1344 (x2); ineligible-soldiers/count 1194; nav/counts 1151; hr-sync/runs 773; bug-reports/unread-count 755 |
| soldier-detail | errors/unread-count 1412 (x2); ineligible-soldiers/count 1281; soldiers/roster 1281 (x2); nav/counts 1165; soldiers/:id/score 668 |
| transparency-whole-organization | scoring/transparency/page 400; me 365; errors/unread-count 354; notifications/unread-count 352; bug-reports/unread-count 350 |

Warm home-dashboard is dominated by the pending-count endpoints (command-dashboard/alerts 2519, hierarchy-transfers/pending 2290, field-updates/pending/count 2062, enrollment-requests/pending 1994, exemption-requests/pending/count 1993). Full per-page lists: run the summarizer.

### Server time versus wall time (shell endpoints, 200 responses, medians, ms)

`serverMs`, `dbMs` and `dbQueryCount` come from the profile server's headers, recorded per response (1318 of 1323 c1 and 6898 of 6951 c5 responses carry them; the rest are aborted requests).

| Endpoint | c1 wall | c1 server | c1 db (queries) | c5 wall | c5 server | c5 db (queries) |
|---|---|---|---|---|---|---|
| `GET /api/me` | 362 | 47 | 28 (18) | 416 | 101 | 66 (18) |
| `GET /api/nav/counts` | 1033 | 717 | 641 (33) | 564 | 228 | 167 (33) |
| `GET /api/notifications/unread-count` | 346 | 27 | 6 (2) | 439 | 102 | 13 (2) |
| `GET /api/ranges/ineligible-soldiers/count` | 1248 | 928 | 106 (17) | 4191 | 3773 | 2509 (17) |

Reading: `me` and `notifications/unread-count` spend about 300 ms outside the handler (roughly 350 ms wall for 27-47 ms of server work at c1), which points at the browser, proxy or network path rather than the database. `nav/counts` and `ineligible-soldiers/count` are server-bound; the latter is not database-bound at c1 (106 ms of 928 ms), so about 800 ms is application time in the handler, and at c5 it degrades to 3.8 s.
`GET /api/admin/errors/unread-count` answers 503 on this setup (Loki unset), so it has no 200 timings; its wall time is still 0.7-1.4 s per call in the top-endpoint lists above.

## Ineligible count phases (Task 4), 2026-10-09

Measured in-process with `python -m app.scripts.profile_ineligible_count` (read-only transaction, 5 repetitions, medians) against `justice_scale_fcp_scale` (20,116 soldiers with a hierarchy node, 1,000,008 assignments, 7 active weapon duty types). Admin scope (`roots=None`); scoped runs (largest branch, 65 soldiers; largest group, 25; a synthetic team, 50) stay under 20 ms throughout. Each row is one commit.

| Phase (admin scope, ms) | Baseline | Row 1: column-only load | Row 2: one check per soldier profile |
|---|---|---|---|
| 1 load soldiers | 434 (77%) | 82 (31%) | 90 (67%) |
| 2 structural eligibility | 108 (19%) | 163 (61%) | 20 (15%) |
| 3 qualifications | 5 | 5 | 5 |
| 4 future weapon duties | 4 | 4 | 4 |
| 5 duty eligibility | 15 | 15 | 16 |
| `count_ineligible_soldiers` end to end | 577 | 278 | 156 |

Decision gate: phase 1 was 77% of the baseline, so row 1 applied first. Loading rows instead of entities made phase 2 slower, because by-name attribute access on a SQLAlchemy `Row` costs more than on an entity. That left phase 2 at 61%, so row 2 applied next: group soldiers by the nine fields `_is_eligible` reads (44 distinct profiles at 20k) and build the group key positionally. The in-process median of `count_ineligible_soldiers` went from 577 to 156 ms (3.7x). This is an in-process figure (no auth, no network, no other requests), not the end-to-end one; the final end-to-end result of the same code is in the Task 7 section: c5 cold p50 1396 ms wall / 1070 ms server against the 1.0 s target, which was missed. No cache was added. The count still matches `len(list_ineligible_soldiers(...))` on the scale database for every scope (admin 1 = 1, branch 1 = 1, group 0 = 0, team 0 = 0).

Sanity check against the baseline: the in-process 577 ms sits below the 928 ms server median at c1, because the server number also includes auth, `_resolve_roots` and contention with the other shell requests of the same page load.

## Per-page duplicates (Task 6), 2026-10-09

Counted per page load in cold mode. Warm mode has the same request lists for the page-load scenarios, except Hierarchy (one extra aborted request, below) and Soldier detail, where warm is an in-app modal opened on an already loaded Team page, not a page load: it makes 3 requests (`soldiers/:id`, `soldiers/ranks`, `soldiers/:id/score`; 4 at baseline) and is not comparable with the 16-20 of the cold load. "Baseline" is the median per load in `shell-load-before-c1-20261008.json` (code `e03c9532`). "Before Task 6" is a fresh production-build capture after Tasks 2-5 (`31db05aa`, `JUSTICE_SCALE_RUNS=1`, c1). "After" is `docs/benchmarks/data/shell-load-t6-final-c1-20261008.json` (code `305c805b`, same procedure). That capture was taken while vitest was running on the same machine, so its timings are noisy and are not used anywhere in this document; only its request counts are. The artifact strips query strings, so every remaining pair was checked against full request URLs with a separate Playwright trace of the same build.

| Page | Baseline duplicates (requests) | Before Task 6 (requests) | After Task 6 (requests) | Kept, with reason |
|---|---|---|---|---|
| Home | settings/public x2, auth/refresh x2, duty-types x2, errors/unread-count x3, level-types x2, ranges x2, calendar/shifts x2 (39) | settings/public x2 (401, then 200), auth/refresh x2, duty-types x2, level-types x2, ranges x2, calendar/shifts x2 (36) | ranges x2, calendar/shifts x2 (32) | `calendar/shifts` and `ranges` are two different queries: the command calendar loads `?node_id=<scope>` and then `?soldier_id=<me>`, so the manager's own cross-unit duties appear (the `highlightSoldierId` merge in `UnitCalendar`). |
| Hierarchy/Team | settings/public x2, auth/refresh x2, errors/unread-count x2 (16) | settings/public x2, auth/refresh x2 (14) | none (12) | Warm mode only: one `hierarchy/branches` with no status, a request of the previous page aborted by the navigation, not part of this load. |
| Soldier detail | settings/public x2, auth/refresh x2, errors/unread-count x2, soldiers/roster x2 (20) | settings/public x2, auth/refresh x2, soldiers/roster x2 (18) | soldiers/roster x2 (16) | The second `soldiers/roster` is `?search=scale20-00001`: the profiler types the soldier's number into the roster filter before it opens the modal. |
| Calendar whole-org | settings/public x2, auth/refresh x2, errors/unread-count x2 (18) | settings/public x2, auth/refresh x2 (16) | none (14) | - |
| Calendar synthetic team | settings/public x2, auth/refresh x2, errors/unread-count x3, hierarchy/branches x2, calendar/shifts x2, ranges x2 (23) | settings/public x2, auth/refresh x2, hierarchy/branches x2, ranges x2, calendar/shifts x2 (20) | hierarchy/branches x2, ranges x2, calendar/shifts x2 (18) | All three follow the team selection: shifts and ranges for the new `node_id`, and `branches?parent_id=<parent>` to show the selected node in the picker. |
| Transparency | settings/public x2, auth/refresh x2 (10) | settings/public x2, auth/refresh x2 (12) | none (10) | - |
| HR sync review | settings/public x2, auth/refresh x2, errors/unread-count x2 (20) | settings/public x2, auth/refresh x2 (18) | none (16) | - |

Baseline request counts are the Task 1 c1 cold medians; the other two columns are single runs. Transparency shows 12 requests in the "before Task 6" column against 10 at baseline and 10 after; the cause of the two extra requests is not established (that capture was a single run and its artifact was not kept, and both later captures, including the Task 7 matrix, show 10), so treat the 12 as an unexplained single-run observation.

Single on the production build (dev-server React StrictMode doubles, not bugs): `/api/me`, Team `level-types` and `soldiers/ranks`, calendar `duty-types`. `errors/unread-count` was already gone after Task 2.

Fixes:

- `auth/refresh` x2 and `settings/public` 401 then 200 on every page (`552ac146`): session restore and the 401 handler each sent their own refresh, and `/settings/public` (requested by `App` before the token existed) went out unauthenticated. Both now share the client's single-flight `refreshAccessToken()`, and a request issued while that refresh is in flight waits for it. Two requests fewer on every page.
- Home `level-types` x2 (`f3e205ae`): `useLevelTypes` kept per-component state. It is now a react-query hook on `queryKeys.levelTypes()` (5 min staleTime), and its `refresh()` refetches for every consumer.
- Home `duty-types` x2 (`b4e9243f`): `UnitCalendar` fetched duty types itself. It and Home now use `useDutyTypes()` on the shared `queryKeys.dutyTypes()` key.
- No `useSoldierRanks` hook: ranks are requested once per load on the production build.

## Slow Home calls (Task 6)

Admin user, Home cold, medians. "c1 before" is one run of `31db05aa` plus the duplicate fixes; "c5 before" is three runs of the same code at c5; the next two columns add the alerts fix, then the panel staging (three runs each, Home only). Wall time is the browser's; server and db come from the profile server's headers.

| Endpoint | c1 before: wall / server / db (queries) | c5 before: wall / server | c5 + alerts fix: wall / server | c5 + staging: wall / server |
|---|---|---|---|---|
| `GET /api/command-dashboard/alerts` | 1549 / 1228 / 673 (16) | 4913 / 4396 | 2170 / 1799 | 2152 / 1677 |
| `GET /api/hierarchy-transfers/pending` | 1332 / 25 / 7 (6) | 5130 / 358 | 2511 / 236 | 2164 / 618 |
| `GET /api/soldiers/field-updates/pending/count` | 1220 / 9 / 4 (2) | 4990 / 368 | 2287 / 356 | 2102 / 582 |
| `GET /api/constraints/pending/count` | 1027 / 187 / 33 (8) | 4984 / 993 | 2322 / 581 | 867 / 345 |
| `GET /api/exemption-requests/pending/count` | 1027 / 187 / 94 (13) | 5085 / 1249 | 2388 / 548 | 1012 / 405 |
| `GET /api/enrollment-requests/pending` | 996 / 637 / 610 (15) | 3750 / 1645 | 1652 / 836 | 846 / 354 |
| `GET /api/swaps/pending` | 1012 / 208 / 16 (2) | 4808 / 2384 | 2200 / 1022 | 802 / 180 |
| `GET /api/command-dashboard/upcoming` | 454 / 65 / 38 (13) | 1574 / 474 | 1104 / 603 | 1721 / 490 |
| Home ready p50 (cold) | c1 5245 | 10417 | 7652 (c1: 4791) | 7479 (c1: 4809) |

`alerts` is server-bound (1.2 s of 1.5 s at c1). In-process on the scale database (read-only, 5 runs) it took 1198 ms: ~395 ms to build 20,117 `Soldier` ORM entities (the same columns as rows: 43 ms), ~200 ms to build and send four `uuid[]` parameters of 20,116 ids (the expiring-exemption query executes in 0.8 ms but took 70-95 ms client-side), and the warning-score aggregate. `EXPLAIN (ANALYZE, BUFFERS)` of the aggregate: parallel seq scan of all 1,000,008 `duty_assignments`, partial and final hash aggregate to 20,008 groups (5 batches, under 1 MB spilled to temp), 339 ms execution. Fixes: rows instead of entities (`9673e871`) and a soldier-scope subquery instead of the id arrays (`ed96e360`). In-process 1198 -> 505 ms; server time c1 1228 -> 620-706 ms, c5 4396 -> 1799 ms; Home ready at c5 10417 -> 7652 ms. A 50-soldier team scope is unchanged (score sieve 6.4 vs 8.4 ms, identical results). The aggregate itself (~350 ms) stays: an organization-wide scope needs every soldier's all-time score and no index helps a full aggregate; the score-projection read path (setting `SCORE_PROJECTION_COMMANDER_READS_ENABLED_KEY`, off on this database) is the existing answer to that.

`hierarchy-transfers/pending` and `field-updates/pending/count` are not server-bound (9-25 ms server for 1.2-1.3 s wall at c1). Playwright request timing on the same build showed them waiting ~760-790 ms in the browser before the request was sent: the command dashboard opened with 11 reads at once, and Chrome allows six HTTP/1.1 connections per host. `305c805b` moves upcoming, potential, own-potential summaries and the upcoming-ranges widget behind a second `useDashboardIdleGate` window, leaving alerts, approvals and the calendar in the first burst. The other approval reads gained most (c5: constraints 2322 -> 867 ms, swaps 2200 -> 802); transfers and field updates gained less (c1 842 -> 716 and 825 -> 685 ms; c5 2511 -> 2164 and 2287 -> 2102 ms) because one approval read still queues behind alerts and the calendar. These two gains are within run-to-run variance: in the same runs the transfers server time went from 236 to 618 ms, a change in the other direction that is larger than the wall-time gain, and the wall times moved by 8-17%. Treat them as no measurable change. Page ready did not change. Upcoming and potential now finish later (c5 1104 -> 1721 ms wall).

Not fixed:

- The warning-score aggregate (above).
- `deploy/nginx.conf` serves HTTPS without `http2`, so production has the same six-connection queue; `listen 443 ssl http2;` would remove it. Its `limit_req` (10 r/s, burst 20, per client IP) is also close to one cold Home load (32 API requests in 4-5 s) and would be reached by users behind a shared NAT. Deployment configuration is outside this task.
- The Home command calendar loads the scope window (`node_id`) and then the personal window (`soldier_id`) one after the other. Running them in parallel would take ~350 ms off the end of the page. They are not duplicates, so this is left for a separate change.
- Measurement artifact: on this machine every new browser connection to `localhost:5174` waits ~300 ms before its request starts (Playwright `requestStart` ~300 ms on fresh connections, 0 on reused ones), consistent with an IPv6-then-IPv4 fallback for `localhost` against a server bound to 127.0.0.1. It adds to all wall times in these captures and does not exist in production.

## After (final, Task 7b), 2026-10-09

Matched re-run of the Task 1 matrix on the final code. This is the official "after". It repeats the earlier capture (Task 7, `shell-load-after-*-20261008.json`, code `46d6d67c`, called "intermediate" below) because three code commits landed after that capture: `16d902a4` (logging label for deliberate 5xx responses), `d2283607` (the Team page no longer refetches hierarchy branches on a hidden page) and `6d12dd49` (the katex chunk is no longer a static import of the entry).

### Setup

- Code measured: `2d5b9682` (application code identical to `6d12dd49`; the commit on top only adds documentation).
- Same procedure, database (`justice_scale_fcp_scale`, 20,120 soldiers and 1,000,008 assignments verified before the run), Redis, profile server on 8100 (`LOKI_URL` unset, `TRANSPARENCY_READ_MODEL_ENABLED=true`), fresh production build served by `vite preview` on 5174 (`VITE_BACKEND_URL=http://127.0.0.1:8100`), user 1000001, `localhost:5174` as base URL. A discarded 1-run warm-up of every scenario (c1, then c5) preceded the measured runs; no vitest or build ran during a capture. c1 then c5, strictly sequential, 5 runs each.
- Entry chunk `assets/index-D2VlxfxZ.js` = 428.54 kB raw (428,539 bytes), 112.96 kB gzip (zlib default level; baseline 3,989.42 kB raw / 1,099.94 kB gzip; intermediate 428.60 kB / 113.46 kB). The 19 assets referenced by `index.html` (entry, 17 modulepreloaded chunks, 1 stylesheet) are 857.7 kB raw and 244.2 kB gzip at zlib level 6; the same asset set measured at gzip level 1 in the FCP investigation (`6d12dd49`, same frontend code) is 287 kB. The intermediate build still had the 264.8 kB katex chunk among the entry's static imports.
- Artifacts: `docs/benchmarks/data/shell-load-final-c1-20261009.json` (70 measurements) and `shell-load-final-c5-20261009.json` (350 measurements); every measurement reached readiness, exit code 0, no console or page errors. They contain no password or database URL strings. Compare with `node frontend/scripts/summarize-scale-pages.mjs <final> <baseline>`.
- Single capture pair, no re-runs. Free memory was about 1.9-2.0 GB of 16 GB at the start of the captures (the intermediate capture started with about 2.7 GB). Running at the same time: Docker Desktop with the other project containers (one of them, `runtime-statelessness-observability-backend-1`, was in a restart loop), Firefox, WhatsApp, Claude desktop, Windows Defender.

### Success criteria

"Intermediate" is the earlier capture of nearly the same code; the difference between it and "final" shows the run-to-run variation to keep in mind when reading any single cell. Call-level medians in this section were recomputed with one script for all three captures, so the baseline c1 ineligible figure (1224 / 909 ms) differs by a few milliseconds from the rounding used in the baseline section (1219 / 901).

| Criterion | Baseline | Target | Intermediate | Final (official) | Result |
|---|---|---|---|---|---|
| `GET /api/admin/errors/unread-count` requests, Loki unset | 134 (c1), 836 (c5) | 0 | 0 / 0 | 0 (c1), 0 (c5). Responses with status >= 400 of any endpoint: baseline 199 / 1141, final 0 / 0 | Met |
| Entry JS chunk, raw | 3,989 kB | <= 1.6 MB, heavy libraries in lazy chunks | 428.6 kB | 428.5 kB (113.0 kB gzip); heavy libraries in separate chunks | Met |
| Requests per cold page load (Home / Calendar team / Calendar org / Hierarchy / HR sync / Soldier detail / Transparency) | 39 / 23 / 18-19 / 16-17 / 20 / 20-21 / 10 | no endpoint more than once per page load, except genuine refetches | 32 / 18 / 14 / 12 / 16 / 16 / 10 | 32 / 18 / 14 / 12 / 16 / 16 / 10. Remaining pairs: Home `ranges` x2 and `calendar/shifts` x2; Calendar team `hierarchy/branches`, `ranges`, `calendar/shifts` x2; Soldier detail `soldiers/roster` x2 (all analysed in the Task 6 section as different queries or profiler steps). Warm Hierarchy 13 -> 12: the aborted `hierarchy/branches` of the previous page is gone (`d2283607`) | Met, with those documented exceptions |
| `ineligible-soldiers/count` c5 cold p50 (end to end) | 4144 ms wall, 3780 ms server (c1: 1224 / 909) | <= 1.0 s | 1481 / 1146 ms (c1: 601 / 282) | **1396 ms wall, 1070 ms server** (c1: 623 / 317) | **Missed** (0.4 s over the target; 3.0x faster than baseline) |
| FCP c5 cold p50, each page | 1512-1592 ms | <= 2.0 s | 1040-1168 ms | 1032-1144 ms (all pages together 1064 ms) | Met (already met at baseline) |
| Page-ready p95, every page and mode, c1 and c5 | c1 cold 2.3-6.6 s, c5 cold 7.8-14.3 s | not worse than baseline | c1: 4 of 14 worse; c5: none | c1: 4 of 14 worse (Transparency cold 2266 -> 2662, Transparency warm 1352 -> 2197, Hierarchy warm 1842 -> 2695, HR sync warm 2065 -> 2422 ms). c5: none worse. Transparency warm: the shell badge reads now inside the window plus a new-connection measurement artifact, see [Follow-up batch 4](#item-9-warm-transparency-is-not-a-lazy-chunk-waterfall) | **Missed** (c1) |

Counts: 4 met, 2 missed (the same two as in the intermediate capture). Other numbers asked for:

- Ineligible count, end to end, c5 cold p50: 1396 ms wall, 1070 ms server (782 ms of it database time, 17 queries, as before; baseline 2602 ms database). Warm c5: 1345 ms wall, 988 ms server (baseline 4556 / 3703).
- Error-log requests: 0 in both artifacts (`GET /api/admin/errors/unread-count`), and no response with status 400 or above anywhere in the final captures.
- Eager assets (referenced by `index.html`): 857.7 kB raw, 244.2 kB gzip (zlib level 6); entry 428.5 kB raw, 113.0 kB gzip.
- Requests per page load: cold as in the table above. Warm is the same except Hierarchy (12; baseline 13) and Soldier detail, which is an in-app modal (3 requests; baseline 4).

### FCP

The target (<= 2.0 s) was already met at baseline on the production build over loopback (c5 cold p50 1512-1592 ms; the 3.4-3.8 s seen earlier was Vite dev-server overhead, see the baseline Setup). In the final run cold FCP p50 is lower than baseline on every page: pooled over all pages c1 1272 -> 868 ms and c5 1536 -> 1064 ms (per page c1 828-1024 against 1216-1296, c5 1032-1144 against 1512-1592), and the c5 cold p95 is lower on every page as well (1132-1500 against 1544-1896). The intermediate capture shows the same size of gain (c1 864 ms, c5 1124 ms), so the gain is larger than the run-to-run difference between captures. This experiment does not isolate its cause (the entry chunk shrank, which is consistent with it). The target was met before the work, so this is a secondary improvement and not a criterion result.

Warm FCP is lower than baseline on every page except Transparency, at both concurrencies: Transparency warm 436 -> 760 ms (c1) and 508 -> 848 ms (c5), the same as in the intermediate capture. Follow-up batch 4 attributes this to the warm document request opening a new connection and paying the ~300 ms `localhost` connect stall (the `vite preview` proxy closes every API connection, and the shell badge reads at the end of the cold load use up the idle ones); over `127.0.0.1` warm FCP is equal to baseline (156 vs 152 ms). See [Item 9](#item-9-warm-transparency-is-not-a-lazy-chunk-waterfall). The Home warm c1 increase seen in the intermediate capture (712 -> 772 ms) did not persist (712 -> 432 ms), which suggests it was noise.

Loopback without throttling is not what a user sees. The throttled FCP investigation below gives the realistic numbers: on fast 4G (9 Mbps, 150 ms, CPU x4) cold FCP is about 1.2 s for `/login` and 1.7 s for `/` and `/transparency`; on slow 4G (1.6 Mbps, 300 ms) it is 2.4 s for `/login` and 3.3 s for `/` and `/transparency`, so a 2.0 s target would be missed for the post-login pages on slow 4G. That section also explains why the FCP of the code-split build is the loading text, not the page.

### Per-page results (ms, baseline -> final (intermediate))

Each cell reads `baseline -> final (intermediate)`.

c1, cold:

| Page | Ready p50 | Ready p95 | FCP p50 | FCP p95 | Requests |
|---|---|---|---|---|---|
| Home | 5917 -> 4994 (5020) | 6068 -> 5261 (5064) | 1272 -> 884 (856) | 1316 -> 1208 (956) | 39 -> 32 (32) |
| Calendar (synthetic team) | 6302 -> 4785 (5113) | 6569 -> 5391 (5277) | 1292 -> 852 (848) | 1316 -> 928 (1252) | 23 -> 18 (18) |
| Calendar (whole org) | 4243 -> 3049 (3287) | 4413 -> 3587 (3342) | 1268 -> 828 (912) | 1316 -> 1184 (956) | 18 -> 14 (14) |
| Hierarchy/Team | 4357 -> 2946 (2757) | 4487 -> 3139 (2893) | 1288 -> 1024 (836) | 1328 -> 1172 (952) | 16 -> 12 (12) |
| HR sync review | 4154 -> 3077 (3008) | 4346 -> 3404 (3506) | 1216 -> 880 (828) | 1364 -> 1200 (1244) | 20 -> 16 (16) |
| Soldier detail | 5739 -> 4229 (4170) | 6521 -> 4477 (4284) | 1256 -> 840 (884) | 1412 -> 1060 (1012) | 20 -> 16 (16) |
| Transparency | 2214 -> 2496 (2523) | 2266 -> 2662 (2536) | 1296 -> 900 (944) | 1312 -> 1028 (952) | 10 -> 10 (10) |

c1, warm:

| Page | Ready p50 | Ready p95 | FCP p50 | FCP p95 | Requests |
|---|---|---|---|---|---|
| Home | 5902 -> 4150 (4112) | 6174 -> 4417 (4661) | 712 -> 432 (772) | 756 -> 760 (792) | 39 -> 32 (32) |
| Calendar (synthetic team) | 5905 -> 4410 (4210) | 6212 -> 4578 (4233) | 708 -> 428 (428) | 736 -> 464 (436) | 23 -> 18 (18) |
| Calendar (whole org) | 3711 -> 2388 (2379) | 3727 -> 2397 (2461) | 528 -> 432 (440) | 584 -> 508 (508) | 18 -> 14 (14) |
| Hierarchy/Team | 1829 -> 2355 (2396) | 1842 -> 2695 (2658) | 836 -> 444 (460) | 840 -> 488 (724) | 13 -> 12 (13) |
| HR sync review | 2035 -> 2349 (2437) | 2065 -> 2422 (2501) | 724 -> 452 (412) | 748 -> 464 (468) | 16 -> 16 (16) |
| Soldier detail (in-app modal) | 1550 -> 1360 (1356) | 1604 -> 1500 (1480) | - | - | 4 -> 3 (3) |
| Transparency | 1346 -> 2169 (2116) | 1352 -> 2197 (2218) | 436 -> 760 (772) | 440 -> 776 (776) | 10 -> 10 (10) |

c5, cold:

| Page | Ready p50 | Ready p95 | FCP p50 | FCP p95 | Requests |
|---|---|---|---|---|---|
| Home | 14116 -> 7887 (7731) | 14259 -> 8077 (7918) | 1556 -> 1076 (1124) | 1612 -> 1320 (1180) | 39 -> 32 (32) |
| Calendar (synthetic team) | 10920 -> 6932 (6872) | 11475 -> 7107 (7166) | 1564 -> 1096 (1120) | 1896 -> 1204 (1248) | 23 -> 18 (18) |
| Calendar (whole org) | 8168 -> 4561 (4607) | 9199 -> 4700 (4753) | 1516 -> 1064 (1140) | 1628 -> 1276 (1248) | 19 -> 14 (14) |
| Hierarchy/Team | 7589 -> 3963 (4015) | 8018 -> 4167 (4160) | 1592 -> 1144 (1120) | 1696 -> 1212 (1216) | 17 -> 12 (12) |
| HR sync review | 7288 -> 4083 (4196) | 8390 -> 4202 (4471) | 1532 -> 1060 (1040) | 1800 -> 1132 (1532) | 20 -> 16 (16) |
| Soldier detail | 9569 -> 6224 (6187) | 10046 -> 6908 (6660) | 1512 -> 1032 (1072) | 1544 -> 1500 (1152) | 21 -> 16 (16) |
| Transparency | 2677 -> 3592 (3691) | 7790 -> 3725 (3921) | 1584 -> 1056 (1168) | 1652 -> 1148 (1576) | 10 -> 10 (10) |

c5, warm:

| Page | Ready p50 | Ready p95 | FCP p50 | FCP p95 | Requests |
|---|---|---|---|---|---|
| Home | 13714 -> 7370 (7248) | 14144 -> 7740 (7470) | 1052 -> 888 (908) | 1116 -> 944 (952) | 39 -> 32 (32) |
| Calendar (synthetic team) | 10050 -> 6042 (6070) | 11477 -> 6242 (6487) | 732 -> 564 (560) | 1124 -> 592 (616) | 23 -> 18 (18) |
| Calendar (whole org) | 7733 -> 3696 (4133) | 9704 -> 4353 (4383) | 1048 -> 612 (600) | 1156 -> 748 (648) | 19 -> 14 (14) |
| Hierarchy/Team | 2164 -> 3361 (3211) | 6639 -> 3470 (3538) | 860 -> 564 (644) | 1240 -> 616 (704) | 13 -> 12 (13) |
| HR sync review | 3701 -> 3466 (3525) | 6159 -> 3827 (3599) | 748 -> 552 (584) | 1140 -> 592 (648) | 20 -> 16 (16) |
| Soldier detail (in-app modal) | 2512 -> 2443 (2547) | 2839 -> 2693 (2760) | - | - | 4 -> 3 (3) |
| Transparency | 1618 -> 3171 (3218) | 5202 -> 3210 (3347) | 508 -> 848 (840) | 4244 -> 900 (880) | 10 -> 10 (10) |

### What got worse, and what did not change

Targets missed (both repeat the intermediate capture):

1. `ineligible-soldiers/count` at c5 cold: 1396 ms wall / 1070 ms server against <= 1.0 s. It improved from 4144 / 3780 ms, but the target is missed by about 0.4 s. At c1 it is 623 / 317 ms. Later work: single-flight coalescing (`f7b77ed6`, bounded to a 75 ms join window in `abf967ca`) brings it to about 0.9-1.0 s wall in a two-scenario c5 A/B, see [Follow-up batch 4](#follow-up-batch-4-concurrency-2026-10-09); the official verdict here stays "missed" until the full matrix is re-run.
2. Page-ready p95 not worse than baseline: missed at c1 on four scenario/modes (numbers in the success table).

Page-ready p50 or p95 higher than baseline in the final capture (ms, baseline -> final (intermediate)):

| Scenario / mode | p50 | p95 |
|---|---|---|
| c1 cold Transparency | 2214 -> 2496 (2523) | 2266 -> 2662 (2536) |
| c1 warm Transparency (badge reads in the window plus the new-connection artifact, see [Item 9](#item-9-warm-transparency-is-not-a-lazy-chunk-waterfall)) | 1346 -> 2169 (2116) | 1352 -> 2197 (2218) |
| c1 warm Hierarchy | 1829 -> 2355 (2396) | 1842 -> 2695 (2658) |
| c1 warm HR sync | 2035 -> 2349 (2437) | 2065 -> 2422 (2501) |
| c5 cold Transparency | 2677 -> 3592 (3691) | better (7790 -> 3725) |
| c5 warm Transparency | 1618 -> 3171 (3218) | better (5202 -> 3210) |
| c5 warm Hierarchy | 2164 -> 3361 (3211) | better (6639 -> 3470) |

All other scenario/modes are lower than baseline at both percentiles; c5 p95 is not worse anywhere. Several baseline c5 p95 values were inflated by outliers (Transparency cold 7790, Hierarchy warm 6639, Transparency warm 5202 ms), so the c5 p95 improvements on those pages come from removing outliers while the p50 got worse. HR sync warm at c5 is no longer worse (3701 -> 3466 ms; 3525 in the intermediate capture) and Soldier detail warm c5 is slightly better (2512 -> 2443 ms). The largest gains are the c5 cold pages: Home 14116 -> 7887, Calendar team 10920 -> 6932, Calendar org 8168 -> 4561, Hierarchy 7589 -> 3963, HR sync 7288 -> 4083, Soldier detail 9569 -> 6224 ms.

Run-to-run variation between the two captures of nearly the same code (ready p50, 14 scenario/modes per concurrency): c1 -7.2% to +6.8% (median absolute difference about 2%), c5 -10.6% to +4.7% (median about 1.7%). The four c1 regressions (+13%, +61%, +29%, +15% on p50 against baseline) are larger than that and appeared in both captures at the same size, so they are not explained by run-to-run noise. All earlier c1 regressions persisted (Transparency cold and warm, Hierarchy warm, HR sync warm).

### The earlier hypothesis for the c1 regressions: what the artifacts can and cannot show

The hypothesis from the intermediate capture: the shell's navigation reads (`nav/counts`, `ineligible-soldiers/count`, `algorithm/jobs`) now start early enough to land inside the measured window of the affected pages, so "page ready" (the later of the page marker and the end of API traffic) waits for them. The profiler artifacts record, per API call, only the wall duration and the server and database time; there is no start offset or end time relative to navigation, and `phaseTimings` is empty for these scenarios. So the start offsets quoted earlier (about 280-330 ms) cannot be checked from the artifacts, and the hypothesis cannot be proven or refuted with existing data. What the artifacts do show, c1, medians of 5 runs (calls in window, then wall / server ms):

| Scenario / mode | Capture | Marker visible | API quiet (= ready) | `nav/counts` | `ineligible count` | `algorithm/jobs` |
|---|---|---|---|---|---|---|
| Transparency cold | baseline | 1659 | 2209 | 0 of 5 | 0 of 5 | 0 of 5 |
| | intermediate | 957 | 2520 | 5 of 5, 280 / 276 | 5 of 5, 284 / 280 | 5 of 5, 337 / 27 |
| | final | 927 | 2492 | 5 of 5, 287 / 281 | 5 of 5, 282 / 276 | 5 of 5, 356 / 38 |
| Transparency warm | baseline | 909 | 1343 | 0 of 5 | 0 of 5 | 0 of 5 |
| | intermediate | 1212 | 2112 | 5 of 5, 299 / 293 | 5 of 5, 295 / 290 | 5 of 5, 334 / 24 |
| | final | 1210 | 2165 | 5 of 5, 301 / 295 | 5 of 5, 295 / 287 | 5 of 5, 349 / 29 |
| Hierarchy warm | baseline | 1268 | 1825 | 0 of 5 | 0 of 5 | 0 of 5 |
| | intermediate | 481 | 2391 | 5 of 5, 599 / 281 | 5 of 5, 595 / 277 | 5 of 5, 575 / 256 |
| | final | 903 | 2349 | 5 of 5, 616 / 296 | 5 of 5, 603 / 282 | 5 of 5, 577 / 259 |
| HR sync warm | baseline | 831 | 2029 | 0 of 5 | 0 of 5 | 0 of 5 |
| | intermediate | 899 | 2433 | 5 of 5, 659 / 337 | 5 of 5, 654 / 331 | 5 of 5, 444 / 115 |
| | final | 902 | 2344 | 5 of 5, 576 / 266 | 5 of 5, 574 / 262 | 5 of 5, 409 / 89 |

- Consistent with the hypothesis: in the baseline the three calls are absent from the measured window of all four scenario/modes (0 of 5 in every case), in both later captures they are in all of them, and the added quiet time (final minus baseline: Transparency cold +283 ms, Transparency warm +822, Hierarchy warm +524, HR sync warm +315 ms) is of the same order as the wall time of these calls (about 280-620 ms). The page marker is earlier in two of the four cells (Transparency cold 1659 -> 927 ms, Hierarchy warm 1268 -> 903 ms), so there the added time is waiting for API quiet, not the page rendering later.
- Not explained by it: Transparency warm adds 822 ms, more than the 300-350 ms of any one of the three calls, and its marker is also later (909 -> 1210 ms; later explained as Playwright's 500 ms polling steps plus the ~300 ms new-connection stall of the warm document, see [Item 9](#item-9-warm-transparency-is-not-a-lazy-chunk-waterfall)); HR sync warm marker is later by 71 ms. Whether the baseline calls were outside the window because they started before it opened or after readiness was declared cannot be seen without start offsets.
- Conclusion: the window composition changed in the way described and the added time is of the right size, but the cause is still a hypothesis here (the bisect section below gives a code-reading cause). Testing it needs per-request start offsets (for example a start-time field in the profiler's `apiResponses`), which is a profiler change and was not made here.

Persisting follow-up, `GET /api/nav/counts` at c5 is slower per call than at baseline. Cold wall / server p50: baseline 560 / 226 ms (153 of 175 loads completed it in the window), intermediate 1421 / 1116, final 1350 / 1038 ms (all 175). Warm: 764 / 291 -> 1288 / 961 ms. At c1 it improved (cold 1062 / 743 -> 611 / 306 ms). It now runs concurrently with the ineligible count and the page's own reads under 5 browsers; the cause is not isolated and it is the next lead for shell cost at c5. The ineligible count behaves the same way at c5 (1396 ms wall, 1070 ms server, see the success table).

Cheap shell calls got much cheaper on the wall clock: `GET /api/me` cold p50 c1 366 -> 35 ms and c5 446 -> 119 ms, `notifications/unread-count` c1 361 -> 24 ms and c5 498 -> 113 ms (server time: c1 35 -> 16 ms, c5 135 -> 70 ms). The server share is small, so most of the baseline wall time of those calls was outside the handler; with fewer concurrent requests per page this is consistent with fewer new connections hitting the ~300 ms `localhost` connection stall, but that was not tested.

### Caveats

- Local single-machine measurement: production build served by `vite preview` over loopback against a profile server (with timing headers) and a local Postgres, one capture pair per code state, with other applications running and about 2 GB of free memory. It is not a production-capacity result; values are comparable only with the baseline taken on the same setup and carry run-to-run noise (the two captures of nearly the same code differ by up to about 10% on a cell, and a p95 of 5 runs is the maximum).
- Every new browser connection to `localhost:5174` waits about 300 ms before its request starts (found in Task 6). It is a measurement artifact that inflates wall times in the baseline and in these runs; it does not exist in production.
- The `ineligible-soldiers/count` target (1.0 s) was missed by about 0.4 s at c5; the remaining server time is 1.07 s, of which about 0.8 s is database time. Further work would need a different read path or a cache with an invalidation rule, which the plan reserved for when a pure query optimization was not enough. Follow-up: the c5 cost turned out to be five identical counts serializing on the GIL; single-flight coalescing (`f7b77ed6`, join window `abf967ca`) is measured in [Follow-up batch 4](#follow-up-batch-4-concurrency-2026-10-09). The official result above is unchanged.
- The intermediate capture ran on `46d6d67c` (application code `305c805b`); its raw data are kept in `shell-load-after-*-20261008.json`.

## FCP investigation (throttled), 2026-10-09

Question: can first contentful paint improve further? The Task 7 numbers above were taken over loopback without network or CPU throttling, which hides transfer and parse costs, so this section measures with throttling.

### Method

- Harness: Playwright Chromium (headless, 1366x768), a script outside the repo. For every run, scenario and build: a new browser context (cold cache), one navigation measured as **cold**, then a second navigation in the same context measured as **warm** (hashed assets come from the HTTP cache, `index.html` is revalidated). Per measurement: FCP (`PerformancePaintTiming`), the last LCP entry after network idle (45 s cap), navigation timing, every resource timing entry (`transferSize`, encoded/decoded size, `renderBlockingStatus`, `Content-Encoding` from the response headers), the DOM present when the FCP entry was delivered (data-testids, text, whether Heebo had loaded), and the first DOM appearance of `login-form`, `sidebar` (the app shell) and the page marker (`personal-data-panel` on Home, `transparency-page`) through a MutationObserver.
- Throttling (CDP, measured loads only): **fast 4G** = 9 Mbps down / 1.5 Mbps up / 150 ms latency, CPU 4x; **slow 4G** = 1.6 Mbps / 0.75 Mbps / 300 ms, CPU 4x (`Network.emulateNetworkConditions`, `Emulation.setCPUThrottlingRate`). DevTools-style throttling adds latency per request; DNS, TCP and TLS setup are not emulated, so new connections (in particular the one to `fonts.googleapis.com`) are cheaper here than on a real network.
- Scenarios: logged-out first visit to `/login`; returning user (valid refresh cookie) loading `/` and `/transparency`. One unthrottled login per profile (the profiler's procedure: wait for network idle before submitting); every returning-user context starts from a copy of that storage state.
- Compression and caching: `vite preview` does not compress, so the builds were served by a small Node server that copies what `deploy/nginx.conf` does: gzip level 1 (nginx's default `gzip_comp_level`) for HTML, CSS, JS and JSON including the proxied `/api` responses, `Cache-Control: max-age=31536000, public, immutable` for `*.js|css|woff2|png|svg|ico`, only ETag/Last-Modified for `index.html`, SPA fallback, `/api` proxied to the profile server. HTTP/1.1 like production (nginx has no `http2`), plain HTTP (no TLS), base URL `127.0.0.1` (avoids the ~300 ms `localhost` connection stall described in Task 6). The response headers confirmed `Content-Encoding: gzip` on every same-origin script, stylesheet and API response.
- Backend and data: `app.scripts.profile_scale_server` on 8100, `justice_scale_fcp_scale` (20,120 soldiers verified), Redis, `LOKI_URL` unset, `TRANSPARENCY_READ_MODEL_ENABLED=true`, user 1000001.
- Runs: 7 measured runs per cell plus one discarded warm-up run; builds interleaved within each run (A, B, C, A, B, C ...) so drift affects all builds alike; strictly sequential; no build or vitest during a capture. p95 of 7 samples is the 7th value (the maximum).
- Builds: **before** = `d2283607` (branch head when this investigation started), **after** = `6d12dd49`, **e6ef3dd7** = the commit before the lazy-routes commit `2d3ab5cc` (built from a temporary worktree, removed afterwards). Experiment builds are described under "Ideas evaluated".
- Raw data: `docs/benchmarks/data/fcp-throttled-20261008.json` (`final`: the matched run below, with each load's resource waterfall up to the shell marker; `experiments`: per-measurement metrics of the three exploratory captures, without waterfalls).

### What first contentful paint is

- `/login` (logged out): the login form (`login-form`, logo, inputs), in the fallback font: Heebo had not loaded at FCP in any cold run.
- `/` and `/transparency` (returning user) on the code-split builds: the text "טוען..." (`page-loading`), the `Suspense` fallback. `ProtectedRoute` renders nothing while the session is restored, then the lazy page suspends and the fallback paints. The shell (`sidebar`) and page appear 0.8-3 s later. On `e6ef3dd7` (no route splitting) FCP is the full shell and page, because nothing suspends. **FCP measures different things on the two code bases; the shell-visible time is the comparable metric.**

Critical path of a cold returning-user load (fast 4G, Home, `before`, medians, ms from navigation start): HTML 174; the entry, its 18 modulepreloaded chunks and 2 stylesheets download in parallel until 1014; the entry stylesheet's `@import` of the Google Fonts CSS starts only after `index.css` has arrived and ends at 939; module execution and the first React render until 1201, when `POST /api/auth/refresh` starts; refresh done 1379; `GET /api/me` done 1565; the route chunk graph (Home: about 25 chunks including recharts and fullcalendar) 1589-2386; FCP (loading text) 1804; shell 2554. Slow 4G has the same shape: JS 2699, refresh 2883-3214, me 3556, FCP 3772, shell 6119.

### Results: before vs after vs e6ef3dd7 (ms, p50 / p95, 7 runs)

Cold cache:

| Profile | Page | FCP before | FCP after | FCP e6ef3dd7 | Shell (or login form) visible: before | after | e6ef3dd7 |
|---|---|---|---|---|---|---|---|
| fast 4G | /login | 1260 / 1344 | 1232 / 1604 | 2428 / 2452 | 1157 | 1127 | 2298 |
| fast 4G | / | 1804 / 2184 | 1708 / 1860 | 2948 / 3096 | 2554 | 2544 | 2844 |
| fast 4G | /transparency | 1780 / 1808 | 1724 / 1752 | 3108 / 3320 | 2581 | 2609 | 2829 |
| slow 4G | /login | 2964 / 2968 | 2404 / 2628 | 8212 / 8324 | 2854 | 2307 | 8057 |
| slow 4G | / | 3772 / 4088 | 3292 / 4420 | 9008 / 9148 | 6119 | 5623 | 8893 |
| slow 4G | /transparency | 3812 / 3924 | 3304 / 3360 | 9272 / 9408 | 6468 | 6390 | 9021 |

Warm cache (second visit, same context):

| Profile | Page | FCP before | FCP after | FCP e6ef3dd7 |
|---|---|---|---|---|
| fast 4G | /login | 176 / 236 | 168 / 180 | 268 / 320 |
| fast 4G | / | 964 / 1024 | 960 / 1076 | 848 / 940 |
| fast 4G | /transparency | 836 / 988 | 876 / 932 | 856 / 912 |
| slow 4G | /login | 204 / 248 | 192 / 256 | 304 / 400 |
| slow 4G | / | 1208 / 1288 | 1196 / 1332 | 1112 / 1188 |
| slow 4G | /transparency | 1188 / 1240 | 1140 / 1200 | 1108 / 1184 |

Transferred before FCP (cold, gzip, medians): before 368-379 kB, after 280-292 kB, e6ef3dd7 1,271-1,274 kB.

Reading:

- **What route-level splitting bought, under throttling.** Logged-out `/login`: FCP 2428 -> 1260 ms on fast 4G and 8212 -> 2964 ms on slow 4G (a 1.27 MB gzip entry against 0.37 MB). Returning users: the comparable shell-visible time improved by 0.25-0.3 s on fast 4G (Home 2844 -> 2554, Transparency 2829 -> 2581) and 2.55-2.8 s on slow 4G (8893 -> 6119, 9021 -> 6468). The 1.1-1.3 s FCP gain on fast 4G in the FCP column is mostly a change of what is painted (a loading text instead of the page), not of when the page shows. Warm-cache loads did not gain: e6ef3dd7 is equal or up to ~115 ms faster on `/` and `/transparency`, because the split build still loads the route chunks (from cache) after the session restore before it paints the page.
- **This task (before -> after).** Cold FCP is lower on slow 4G by 480-560 ms on every page, with non-overlapping ranges on `/login` (2936-2968 vs 2380-2628) and `/transparency` (3768-3924 vs 3208-3360); Home's after p95 is one 4420 ms outlier, its other six runs are 3208-3388 (before: 3724-4088). On fast 4G the change is 28-96 ms and the ranges overlap (one 1604 ms login run after; Transparency 1736-1808 vs 1692-1752), so it is not distinguishable from noise there. Shell visible: slow 4G Home 6119 -> 5623 ms, Transparency 6468 -> 6390 ms; fast 4G unchanged. Warm cache: unchanged within noise.

### Improvement implemented

`6d12dd49` perf(frontend): keep the katex chunk out of the entry's static imports. `main.tsx` imports `katex/dist/katex.min.css` for the whole app, and the `katex` chunk group in `vite.config.ts` matched that CSS module too, so the entry statically imported the whole katex chunk (264.8 kB raw JS: katex, react-katex, prop-types) and `index.html` modulepreloaded it on every page, the login page included. The group now matches only `.js/.mjs/.cjs`; the stylesheet stays global (merged into the entry CSS, 79 -> 108 kB raw) and katex JS loads with the lazy pages and modals that render formulas. Assets referenced by `index.html`: 1,122 kB raw / 378 kB gzip-1 -> 858 kB raw / 287 kB gzip-1. No behaviour change. Test: `frontend/src/buildChunks.test.ts` asserts that the group does not capture the stylesheet and still captures katex and react-katex JS.

### Ideas evaluated and not implemented

Each was built from `6d12dd49` plus the change and measured against it with the same harness (7 runs, interleaved; exploratory captures 2 and 3 in the data file). Cold FCP p50, `6d12dd49` -> variant, in that capture.

| Idea | fast 4G FCP (login / home / transparency) | slow 4G FCP | Other effect | Verdict |
|---|---|---|---|---|
| Google Fonts as `<link rel=stylesheet>` + `preconnect` in `index.html` instead of the CSS `@import` | 1176 -> 1172 / 1732 -> 1700 / 1772 -> 1696 | 2436 -> 2412 / 3312 -> 3292 / 3264 -> 3284 | render-blocking CSS ends 936 -> 579 ms (fast) and 1940 -> 1448 ms (slow) | Not implemented: FCP change within noise under emulation (the JS, not the CSS, is the long pole). Recommended anyway (recommendation 1): emulation does not model the new-origin connection. |
| Start the current route's chunk at startup (`import()` in `main.tsx`, experiment hack) | 1176 -> 1192 / 1732 -> 2236 / 1772 -> 2492 | 2436 -> 2416 / 3312 -> 4664 / 3264 -> 4700 | Shell earlier: fast Home 2636 -> 2102, Transparency 2686 -> 2262; slow 5533 -> 4585, 6380 -> 5271. But `refresh`/`me` queue behind ~25 chunk requests on six HTTP/1.1 connections (slow 4G Home `me` done 3003 -> 4338) | Rejected: FCP 0.5-1.4 s worse. The shell gain is real; see recommendation 2. |
| `ProtectedRoute` renders `PageLoading` during the session restore instead of `null` | 1176 -> 1216 / 1732 -> 1152 / 1772 -> 1144 | 2436 -> 2408 / 3312 -> 2344 / 3264 -> 2344 | Shell unchanged; warm FCP ~0.85-1.2 s -> 0.24-0.35 s | Not implemented: only paints the loading text earlier (the metric moves, the page does not), and it is a visible change that needs a product decision (recommendation 3). |
| Load `UnifiedSoldierModal` on demand in `SoldierModalProvider` (in parallel with the soldier request, behind the existing "opening" overlay) | 1256 -> 1128 / 1688 -> 1672 / 1708 -> 1704 | 2400 -> 2252 / 3288 -> 3172 / 3320 -> 3104 | Entry 428 -> 290 kB raw, eager gzip 287 -> 222 kB. But Home shell **later**: fast 2493 -> 3009, slow 5546 -> 6050 ms (the modules it took out of the entry are needed by Home and now load after the session restore, in more chunks) | Rejected: FCP gain 0-220 ms, overlapping noise on fast 4G, and Home time-to-shell regresses by 0.5 s. |
| Plus: shared dialogs import `EventDetailModal` directly instead of through the `components/planning` barrel (the barrel pulls `PlanningTable` -> `DataTable` -> `@tanstack/table-core` into the entry) | 1128 -> 1128 / 1672 -> 1676 / 1704 -> 1664 | 2252 -> 2216 / 3172 -> 3200 / 3104 -> 3152 | Entry 290 -> 221 kB raw; Home shell later again (slow 6050 -> 6505) | Rejected: no FCP change beyond noise. Without the modal change it removes almost nothing (eager gzip 287 -> 287 kB), because `UnifiedSoldierModal` imports the same modules. |

Also checked:

- Entry composition (`6d12dd49`, source-map attribution, raw output bytes): i18next 63 kB plus about 60 kB of output without source mapping, consistent with the inlined `he.json` (116 kB source; it is the UI language and must be parsed before the first render, and `en.json` is 2.4 kB, so lazy-loading locales would save nothing); `UnifiedSoldierModal` and its panels about 80 kB; `@tanstack/table-core` 49 kB; `react-calendar` 30 kB; the App, Login and ChangePassword pages; `BugReportModal`. React and react-dom are in the separate 140 kB `react-vendor` chunk; lucide icons are tree-shaken (<1 kB). Rolldown's `experimental.chunkOptimization.mergeCommonChunks: false` did not change the entry: these modules are reached statically from the app-level providers (`SoldierModalProvider`, `BugReportModalProvider`).
- Modulepreload hints: Vite already emits `modulepreload` for every static dependency of the entry, and they download in parallel with it; there is no entry-to-dependency waterfall to fix.
- Render-blocking resources: `index.css` and, through its `@import`, the Google Fonts CSS. No third-party scripts. The theme script in `index.html` is inline and small.
- Cache headers (`deploy/nginx.conf`): hashed assets get `expires 1y` plus `Cache-Control: public, immutable` (correct). `index.html` gets no Cache-Control, so browsers may reuse it heuristically for a while after a deploy. gzip is on at level 1 for JS/CSS/JSON (HTML always); no brotli, no `gzip_static`.

### Recommendations (not implemented)

1. **Self-host Heebo** (woff2 in `public/fonts`, `@font-face` with `font-display: swap`, ideally Hebrew and Latin subsets) and drop the `fonts.googleapis.com` `@import`. After the katex fix the font stylesheet chain (index.css -> Google CSS) ends close to the JS on fast 4G (render-blocking end 896 vs JS end 919 ms), and module scripts do not run before pending stylesheets have loaded; on a real network the new-origin DNS+TCP+TLS adds two to three round trips this harness does not emulate. If the deployment network cannot reach Google, rendering waits until that connection fails. Minimum version: move the stylesheet to a `<link>` with `preconnect` in `index.html` (measured above: render-blocking end 360-490 ms earlier, FCP within noise).
2. **Fetch the current route's chunk in parallel with `/api/me`, not before `/api/auth/refresh`.** The measured startup preload brought the shell 0.4-1.1 s earlier but delayed the session restore, because the restore requests queued behind the chunk requests (HTTP/1.1, six connections). Starting the route import once the refresh has returned, or enabling HTTP/2 in nginx, should keep most of the shell gain without delaying auth; it needs its own measurement. With such a prefetch, the `UnifiedSoldierModal`/barrel entry reductions above would probably stop regressing Home and become worth re-measuring.
3. **Product decision: paint during the session restore.** Rendering the existing loading indicator (or an app-shell skeleton) while `/api/auth/refresh` and `/api/me` run moves FCP from ~1.7 to ~1.15 s (fast 4G) and from ~3.3 to ~2.35 s (slow 4G), but does not show any content sooner.
4. **nginx** (deployment config, not changed): `listen 443 ssl http2;` (removes the six-connection queue behind recommendation 2 and the Task 6 request queueing); `Cache-Control: no-cache` on `index.html` so a deploy is picked up on the next visit; a higher `gzip_comp_level` (5-6) or pre-compressed assets (`gzip_static`, brotli) would shave further bytes off the 287 kB.

### Caveats

- One machine (developer workstation, other applications running, about 2.5 GB free RAM), emulated network and CPU over loopback, headless Chromium, plain HTTP/1.1 without TLS, a Node server imitating nginx rather than nginx itself. Not a production RUM result.
- DevTools-style throttling applies latency per request and does not model TCP slow start, DNS, TLS or the connection setup to Google Fonts; the Google Fonts requests went over the real internet with the throttling on top.
- 7 runs per cell; p95 is the maximum of 7 and is sensitive to single outliers (for example Home slow 4G `after` 4420 ms, Login fast 4G `after` 1604 ms). The exploratory captures were separate sessions, so compare variants only with the `6d12dd49` column of the same capture.
- FCP on the code-split builds is a loading text for returning users; use the shell-visible times for user-perceived speed.

## Regression bisect: page-ready at c1, 2026-10-09

Measurement only, no application code changed. Frontend of each commit built separately; ONE fixed backend (branch HEAD, `profile_scale_server` on 8100, 20,120 soldiers); profiler from HEAD; c1, RUNS=5 after a RUNS=1 warm-up; scenarios transparency, hierarchy, hr-sync-review, calendar (control). Two passes: pass 1 in order 09a5b787, a1a56cb4, 31db05aa, HEAD; pass 2 in the reverse order. Free RAM was 1.7-2.1 GB throughout (low but stable). Numbers are `pass1 / pass2`; the passes agree within ~5%.

| Scenario | Mode | Commit | pageReady p50 pass1 / pass2 (ms) | pageReady p95 (p1 / p2) | selectorVisible p50 (p1 / p2) | FCP p50 (p1 / p2) | API requests |
|---|---|---|---|---|---|---|---|
| Transparency | cold | 09a5b787 | 2251 / 2285 | 2291 / 2317 | 1674 / 1720 | 1296 / 1344 | 10 |
| Transparency | cold | a1a56cb4 | 3373 / 3194 | 3649 / 3418 | 1894 / 1828 | 1504 / 1452 | 12 |
| Transparency | cold | 31db05aa | 2410 / 2439 | 2928 / 2621 | 901 / 883 | 892 / 872 | 12 |
| Transparency | cold | HEAD | 2559 / 2411 | 2898 / 2548 | 996 / 870 | 984 / 828 | 10 |
| Transparency | warm | 09a5b787 | 1426 / 1336 | 1444 / 1411 | 912 / 899 | 464 / 420 | 10 |
| Transparency | warm | a1a56cb4 | 2426 / 2485 | 2651 / 2749 | 732 / 737 | 704 / 720 | 12 |
| Transparency | warm | 31db05aa | 2399 / 2389 | 2451 / 2426 | 1211 / 1214 | 756 / 748 | 12 |
| Transparency | warm | HEAD | 2147 / 2154 | 2194 / 2192 | 1227 / 1221 | 772 / 776 | 10 |
| Hierarchy (/team) | cold | 09a5b787 | 3709 / 3671 | 4064 / 3739 | 1677 / 1721 | 1284 / 1340 | 16 |
| Hierarchy (/team) | cold | a1a56cb4 | 3395 / 3353 | 3614 / 3420 | 1836 / 1806 | 1456 / 1380 | 14 |
| Hierarchy (/team) | cold | 31db05aa | 2733 / 2723 | 2936 / 3431 | 842 / 917 | 828 / 872 | 14 |
| Hierarchy (/team) | cold | HEAD | 2718 / 3048 | 2915 / 3188 | 870 / 976 | 844 / 952 | 12 |
| Hierarchy (/team) | warm | 09a5b787 | 1869 / 1851 | 1876 / 1862 | 1246 / 1242 | 832 / 816 | 13 |
| Hierarchy (/team) | warm | a1a56cb4 | 2768 / 2713 | 2883 / 2794 | 1273 / 1263 | 800 / 792 | 15 |
| Hierarchy (/team) | warm | 31db05aa | 2363 / 2387 | 2493 / 2460 | 468 / 472 | 452 / 456 | 15 |
| Hierarchy (/team) | warm | HEAD | 2399 / 2459 | 2478 / 2568 | 909 / 913 | 448 / 468 | 12 |
| HR sync review | cold | 09a5b787 | 3782 / 3628 | 3842 / 3790 | 1695 / 1704 | 1336 / 1284 | 20 |
| HR sync review | cold | a1a56cb4 | 3703 / 3628 | 3822 / 3765 | 1749 / 1785 | 1332 / 1360 | 18 |
| HR sync review | cold | 31db05aa | 2970 / 2985 | 3156 / 3183 | 820 / 855 | 816 / 792 | 18 |
| HR sync review | cold | HEAD | 3157 / 3043 | 3326 / 3274 | 907 / 850 | 904 / 840 | 16 |
| HR sync review | warm | 09a5b787 | 1827 / 1842 | 2048 / 1973 | 968 / 1009 | 588 / 576 | 16 |
| HR sync review | warm | a1a56cb4 | 2869 / 2701 | 2914 / 2787 | 980 / 974 | 528 / 524 | 18 |
| HR sync review | warm | 31db05aa | 2610 / 2655 | 2995 / 2751 | 917 / 885 | 432 / 412 | 18 |
| HR sync review | warm | HEAD | 2350 / 2468 | 2404 / 2475 | 900 / 896 | 416 / 472 | 16 |
| Calendar (control) | cold | 09a5b787 | 3658 / 3680 | 3913 / 4075 | 1802 / 1770 | 1300 / 1292 | 18 |
| Calendar (control) | cold | a1a56cb4 | 3413 / 3318 | 3520 / 3814 | 1865 / 1864 | 1376 / 1368 | 16 |
| Calendar (control) | cold | 31db05aa | 2725 / 2753 | 2996 / 2759 | 1202 / 1159 | 812 / 772 | 16 |
| Calendar (control) | cold | HEAD | 3076 / 3218 | 3516 / 3924 | 1277 / 1285 | 848 / 828 | 14 |
| Calendar (control) | warm | 09a5b787 | 3060 / 3056 | 3098 / 3112 | 995 / 1005 | 528 / 540 | 18 |
| Calendar (control) | warm | a1a56cb4 | 2758 / 2606 | 2870 / 2763 | 1576 / 1111 | 736 / 700 | 16 |
| Calendar (control) | warm | 31db05aa | 2427 / 2409 | 2473 / 2469 | 1090 / 1047 | 424 / 448 | 16 |
| Calendar (control) | warm | HEAD | 2270 / 2286 | 2503 / 2362 | 991 / 995 | 444 / 432 | 14 |

### Which step regressed
- **09a5b787 -> a1a56cb4 (Task 2 + Task 3) introduced the warm regression.** Warm page-ready: Transparency 1426/1336 -> 2426/2485 (+75-85%), Hierarchy 1869/1851 -> 2768/2713 (+46%), HR sync 1827/1842 -> 2869/2701 (+50-57%). Cold Transparency 2251/2285 -> 3373/3194 (+40-50%). At this step warm Transparency selectorVisible was 912 -> 732 ms, i.e. not later, but warm FCP was already later than baseline (464/420 -> 704/720 ms in the bisect table), so the growth is not only the tail of the measured window. The later warm content and FCP from this step on are the warm document's new-connection stall (the shell badge reads at the end of the cold load close the idle connections through the `vite preview` proxy), a measurement artifact; see [Item 9](#item-9-warm-transparency-is-not-a-lazy-chunk-waterfall).
- **a1a56cb4 -> 31db05aa (Task 5, lazy routes + chunk splitting) did not cause it; it helped cold.** Cold Transparency 3373 -> 2410, cold FCP 1504 -> 892, cold selectorVisible 1894 -> 901. Warm page-ready is unchanged (2426 -> 2399), but warm Transparency content (selectorVisible) is about 300 ms later from this commit on (912 -> ~1211/1227 ms in both captures), which Follow-up batch 4 traced to Playwright's polling (the wait re-checks in 500 ms steps; the in-DOM mark is at ~730 ms in both a1a56cb4 and HEAD). No route-chunk waterfall effect is visible on loopback for cold loads or for the other pages (FCP and selectorVisible fell or stayed flat there), and the batch 4 trace shows none for warm Transparency either (the cached page chunk takes 2-20 ms): H1 (lazy chunk waterfall) is rejected for warm Transparency too. The in-DOM delay against baseline began at a1a56cb4 and is the new-connection stall described in [Item 9](#item-9-warm-transparency-is-not-a-lazy-chunk-waterfall).
- **31db05aa -> HEAD (Task 6 + later)**: roughly neutral to slightly better (warm Transparency 2399 -> 2147, request count 12 -> 10, `/api/me` + duplicate `settings/public`/`auth/refresh`/`level-types` gone). H3 rejected as cause.
- Control (calendar) improves monotonically (warm 3060/3056 -> 2286/2270), so the machine did not drift.

### Cause: H2 (nav/shell gate timing), plus an artifact of the measurement window
Requests inside the measured window (warm Transparency, count per run / median ms):
- 09a5b787 (10 requests): bug-reports/unread-count, **admin/errors/unread-count (503, retried)**, me, unseen-count, notifications/unread-count, transparency/page, settings/public x2, auth/refresh x2. NOT present: `/api/nav/counts`, `/api/ranges/ineligible-soldiers/count`, `/api/algorithm/jobs`.
- a1a56cb4 and 31db05aa (12 requests): same minus errors/unread-count (Task 2/3 gate it on error-log being configured and set retry false), PLUS `nav/counts` (170-322 ms; 586-614 ms on /team), `ranges/ineligible-soldiers/count` (268-317; ~590-620 on /team) and `algorithm/jobs` (339-358; 377-562 on /team).
- HEAD (10 requests): these three still in the window; the duplicates are gone.
So in the baseline the three slow shell reads (UnifiedNav, behind its settle gate: gate opens when no query is in flight, or after a 1.2 s deadline) started AFTER the profiler's 500 ms API-quiet period had already closed, so they were never counted. The baseline's failing `errors/unread-count` (503, default retry with 1/2/4 s backoff) kept `useIsFetching() > 0` so the gate stayed shut until the 1.2 s deadline. Task 2/3 removed that 503 retry loop (and cut other requests), so the gate now opens as soon as the page's own queries finish, which is inside the quiet period; the 3 reads (~300-600 ms each, they run concurrently on one loopback backend) then extend the window by about their duration plus the 500 ms quiet time (+~1.0 s warm). This inference of why the baseline gate stayed closed is from reading the code and the 503 counts in the artifacts (134 503s in the baseline artifact), not from an instrumented trace.

Consequence: the "regression" in page-ready is mostly the shell badge reads moving into the measured window, not additional work (the baseline artifact simply did not see them). Content is not slower except warm Transparency, whose selectorVisible is about 300 ms later and whose warm FCP is later too; Follow-up batch 4 found both to be measurement artifacts (Playwright polling steps and the `localhost` new-connection stall, equal to baseline over `127.0.0.1`), see [Item 9](#item-9-warm-transparency-is-not-a-lazy-chunk-waterfall). It is still a real change in when the badge requests fire (earlier, concurrent with the tail of page load), and it contends with the page's own tail requests (e.g. /team `hierarchy/branches` stays ~330-370 ms).

### Recommendation (not implemented)
1. Keep the nav counts / ineligible count / algorithm jobs behind a deliberately later gate: after page-ready, e.g. `requestIdleCallback` plus a minimum ~700 ms after the last in-flight query (longer than the profiler's 500 ms quiet window), rather than "as soon as nothing is fetching". Expected effect: warm page-ready returns to ~1.3-1.4 s Transparency, ~1.8 s Hierarchy/HR sync (baseline-comparable, and with the Task 5/6 gains maybe lower); badges appear ~0.3-0.7 s later. Risk: badge staleness on first paint; keep an immediate fetch when the user opens the nav drawer.
2. Alternatively (or additionally) make the profiler's end condition wait for the shell badge reads so before/after are comparable, and report both "content ready" (selectorVisible) and "all requests settled" - the honest metric is selectorVisible/FCP, which improved or stayed flat except warm Transparency selector (912 -> 1227 at 31db05aa/HEAD). Resolved in Follow-up batch 4 as a measurement artifact; for future captures use `127.0.0.1` as the profiler base URL (no `localhost` connect stall) or record an in-DOM mark instead of a polled selector.
3. Not recommended: eager-bundling pages or modulepreload of route chunks - Task 5 did not hurt cold loads (they got faster), so H1 gives nothing to fix there. Closed: the warm Transparency +300 ms is not a chunk waterfall either ([Item 9](#item-9-warm-transparency-is-not-a-lazy-chunk-waterfall)).

Caveats: single browser, c1 only, 5 runs; baseline frontend against HEAD backend got 401 on settings/public (pre-login) and 503 on errors/unread-count exactly like its original artifact, so no API-shape incompatibility was introduced. One warm-up run per build.

## Follow-up batch 4 (concurrency), 2026-10-09

Three open items: the ineligible count at c5 (missed target), `nav/counts` slower at c5 than at baseline, and warm Transparency content about 300 ms later since the lazy-routes commit. Setup as in Task 7b (profile server on 8100, `justice_scale_fcp_scale` with 20,120 soldiers verified, Redis, `LOKI_URL` unset, `TRANSPARENCY_READ_MODEL_ENABLED=true`, production build served by `vite preview` on 5174, user 1000001). Free RAM about 2.3 GB at the start; nothing else heavy ran during a capture. Python 3.12.1.

### Items 7 and 8: one cause, GIL convoy behind five identical counts

Micro-bench (scratch script, httpx, admin token; `server` = the profile server's `x-scale-server-ms`, medians, p95 in brackets). "seq" is 25 sequential requests from one client; "c5" is 10 rounds of 5 simultaneous requests per endpoint (barrier start), the profiler's `startBarrier` pattern.

| Backend | Load | `ineligible-soldiers/count` server | `nav/counts` server |
|---|---|---|---|
| baseline `09a5b787` | seq | 728 (810) | 44 (75) |
| branch HEAD `321a9b15` | seq | 235 (329) | 42 (75) |
| HEAD | c5, `nav/counts` only | - | 91 (137) |
| HEAD | c5, ineligible count only | 890 (1028) | - |
| HEAD | c5, both together | 896 (1015) | **905 (1024)** |
| baseline | c5, both together | 3270 (3732) | 167 (199) |
| HEAD + single-flight (`f7b77ed6`) | c5, ineligible count only | 252 (289) | - |
| HEAD + single-flight | c5, both together | 311 (413) | 329 (430) |

- `nav/counts` code is unchanged on this branch (`git log 09a5b787..HEAD` lists no commit for the route, its service or the helpers it calls), and in isolation it costs the same at baseline and HEAD (44 vs 42 ms server, 33 statements, about 23-34 ms of database time; the slowest statement is the admin exemption count at 4.8 ms, so `EXPLAIN` had nothing to find). Its c5 slowdown is contention, not a slower query.
- What it contends with: run alone at c5 it takes 91 ms; next to five simultaneous ineligible counts it takes 905 ms, and the extra time is inside statement execution (`dbMs` 867 ms). In-process (one thread timing `get_nav_counts` per statement while N threads run `count_ineligible_soldiers`, no HTTP): N=0 46 ms, N=1 601 ms, N=5 1954 ms, and trivial statements such as `SAVEPOINT` take 80-150 ms each under N=5. That is the GIL convoy: each of the 33 round trips releases the GIL for I/O and must win it back from CPU-bound count threads. `sys.setswitchinterval(0.001)` did not help (1918 ms), consistent with the coarse Windows wait timer.
- Why `nav/counts` got slower than baseline at c5 although the count got faster: at baseline the shell's badge reads ran outside the measured window (bisect section), and in the HTTP burst the baseline backend's 3.2 s counts slowed `nav/counts` much less (167 ms). Why is not explained: the same in-process experiment on the baseline code gives 1951 ms at N=5, so the convoy exists on both code states. On this branch the shell fires `nav/counts` and the count together on every page load.
- The ineligible count itself at c5: five identical CPU-bound computations (about 200 ms CPU each) serialize on the GIL, so each takes about 0.9 s.

Change (`f7b77ed6`, `app/services/single_flight.py`, `count_ineligible_soldiers_coalesced`): per-process single-flight. Concurrent callers with the same key `(frozenset(roots) or None, as_of)` share one computation; the entry is removed when the computation ends (no cache); an exception reaches every waiter and the next call recomputes. Joining was later bounded to a 75 ms window for read-your-writes (`abf967ca`, below). Scope is part of the key, so callers with different scopes never share (test `test_coalesced_count_never_shares_between_different_scopes`). The count's result is unchanged (it still calls `count_ineligible_soldiers`; parity tests pass). Option (b), more CPU work removed, and (c), a TTL cache, were not attempted.

Profiler A/B, c5, scenarios Hierarchy and Calendar whole-org, 5 runs (25 samples per scenario and mode), in the order after (pass 1, preceded by a discarded 1-run warm-up), before (pass 1), before (pass 2), after (pass 2), both on the same production build and database. Artifacts: `docs/benchmarks/data/followup-b4-ineligible-c5-{before,after}-pass{1,2}.json`. Pooled over both scenarios (50 calls per cell), ms, pass 1 / pass 2:

| Call (c5) | Mode | Before wall p50 (p95) | After wall p50 (p95) | Before server p50 | After server p50 |
|---|---|---|---|---|---|
| `ineligible-soldiers/count` | cold | 1553 (1718) / 1440 (1708) | **756 (948) / 786 (1282)** | 1164 / 1014 | 425 / 440 |
| `ineligible-soldiers/count` | warm | 1303 (1731) / 1391 (1831) | 793 (950) / 725 (873) | 947 / 1083 | 431 / 408 |
| `nav/counts` | cold | 1447 (1669) / 1362 (1655) | **742 (892) / 793 (1237)** | 1072 / 951 | 391 / 453 |
| `nav/counts` | warm | 1168 (1669) / 1298 (1823) | 778 (920) / 648 (833) | 810 / 834 | 438 / 393 |

Page ready p50, before -> after (pass 1 / pass 2): Hierarchy cold 3860 / 3782 -> 3134 / 3385, warm 3332 / 3331 -> 2771 / 2614; Calendar org cold 4480 / 4594 -> 3713 / 3729, warm 3809 / 3751 -> 3187 / 3148. FCP and selectorVisible did not change beyond noise (for example Hierarchy cold FCP 1068 / 1028 -> 1028 / 1144).

Reading (unbounded sharing, `f7b77ed6`): the ineligible count at c5 cold was 756-786 ms wall in both passes; about 300 ms of that wall time is the `localhost` connection artifact described in Task 6. `nav/counts` at c5 roughly halved with the same change, without touching its code. These numbers are superseded by the join-window version below. The Task 7b success table is not updated: this is a two-scenario A/B, not a re-run of the full final matrix.

#### Join window (`abf967ca`), review fix

Unbounded sharing broke read-your-writes: the frontend refetches the count right after mutations (`RangeDetailModal`, `NotificationBell`, `NotificationsPage`), and a refetch that joined a computation already reading the pre-write state got a stale badge for up to the 60 s `staleTime`. A caller now joins only if it arrives within `JOIN_WINDOW_SECONDS` = 75 ms of the leader's start; a later caller computes on its own (and does not replace the leader's entry). Residual: a follower that joins inside the window can still miss a write committed after the leader began reading, so staleness is bounded by 75 ms of arrival skew, which is acceptable for a badge count. Waiters now get a fresh `SingleFlightLeaderError` chained from the leader's exception.

Re-measured with the same method (c5, Hierarchy + Calendar whole-org, 25 samples per scenario and mode, discarded 1-run warm-up, order after, before, before, after). Free RAM was lower than in the first A/B (about 1.2 GB). Artifacts: `docs/benchmarks/data/followup-b4-window-c5-{before,after}-pass{1,2}.json`. Pooled, ms, pass 1 / pass 2:

| Call (c5) | Mode | Before wall p50 (p95) | After (window) wall p50 (p95) | Before server p50 | After server p50 |
|---|---|---|---|---|---|
| `ineligible-soldiers/count` | cold | 1449 (1868) / 1565 (1868) | **1013 (1490) / 898 (1794)** | 1084 / 1219 | 613 / 571 |
| `ineligible-soldiers/count` | warm | 1393 (1941) / 1377 (1925) | 900 (1627) / 760 (1209) | 1039 / 1047 | 560 / 460 |
| `nav/counts` | cold | 1284 (1809) / 1364 (1816) | 998 (1451) / 858 (1746) | 923 / 1021 | 632 / 506 |
| `nav/counts` | warm | 1334 (1747) / 1311 (1877) | 847 (1582) / 663 (1123) | 985 / 983 | 512 / 350 |

Page ready p50, before -> after (pass 1 / pass 2): Hierarchy cold 3811 / 3912 -> 3701 / 3531, warm 3342 / 3277 -> 2769 / 2765; Calendar org cold 4521 / 4646 -> 3923 / 4007, warm 4032 / 4255 -> 3269 / 3285.

Reading: with the window the gain is smaller but survives: cold p50 wall 1449-1565 -> 898-1013 ms (server about -45%), against 756-786 ms with unbounded sharing. The p95 stays high (1490-1794 ms) because some browsers now arrive more than 75 ms after the leader and run their own count, which brings back part of the GIL contention. The 1.0 s target is met in one pass and missed by 13 ms in the other, so call it borderline. The barrier start of the profiler (all five browsers navigate together) is still the favourable case; real users arrive less aligned and will share less, approaching the "before" numbers. The window stays in place anyway, because correctness comes first. Further gains would need less CPU per count (option (b)), which was not attempted.

Caveats: c5 here means five headless browsers started together on one machine, all with the same admin scope, which is the case single-flight helps most. Real users with different scopes, or requests that do not arrive within 75 ms of each other, get no sharing; they still pay the full count (about 220-240 ms server alone). A follower waits as long as the leader takes; there is no separate timeout. Single process only (uvicorn workers or replicas each run their own computation).

### Item 9: warm Transparency is not a lazy-chunk waterfall

Harness: a scratch Playwright script (Chromium headless, 1366x768, c1), per run a new context from a logged-in storage state, one cold and one warm navigation to `/transparency`; per load the performance timeline (navigation, resource entries with start / requestStart / responseEnd / transferSize, FCP), the first DOM appearance of `sidebar` and `transparency-page` (MutationObserver), and Playwright's `selectorVisible` as the profiler measures it. 7 runs per build, builds interleaved, 1 discarded run. Same backend (HEAD + single-flight) for all builds. Builds: HEAD frontend (`321a9b15`), `a1a56cb4` (before route splitting) and `09a5b787` (baseline), the latter two from temporary worktrees (removed). Data: `docs/benchmarks/data/followup-b4-transparency-warm-trace.json`.

Warm load, medians (ms from navigation start):

| Base URL | Build | Document response end | `/api/me` end | Transparency chunk | Page in DOM | FCP | Playwright selectorVisible |
|---|---|---|---|---|---|---|---|
| `localhost` | HEAD | 320 | 690 | 691 -> 693 (cached) | 734 | 760 | 1205 (6 of 7 runs ~1205, 1 run 741) |
| `localhost` | `a1a56cb4` (one bundle) | 326 | 700 | in entry | 711 | 728 | 745 (bimodal: 727-761 or 1223-1240) |
| `localhost` | `09a5b787` | 6 | 404 | in entry | 412 | 424 | 897 |
| `127.0.0.1` | HEAD | 8 | 95 | 96 -> 99 | 133 | 156 | 156 |
| `127.0.0.1` | `09a5b787` | 9 | 130 | in entry | 139 | 152 | 181 |

- The route chunk costs 2-20 ms on a warm load (TransparencyPage, recharts and katex chunks come from the cache right after `/api/me`), and the page appears about 40 ms after `/api/me` in both the split and the single-bundle build. The waterfall hypothesis is rejected: `a1a56cb4`, which has no route splitting, shows the page at the same time as HEAD (711 vs 734 ms) and the same FCP (728 vs 760 ms).
- The selectorVisible jump (912 -> ~1210 ms in the bisect) is Playwright's polling: `locator.waitFor` re-checks on a back-off schedule that ends in 500 ms steps, so a page that appears at ~730 ms is seen at either ~730 or ~1210 ms depending on when the wait started; both earlier builds show the same two values. The in-page DOM mark is the reliable number.
- The real difference to the baseline (page 412 -> 734 ms, FCP 424 -> 760 ms) is one connection setup: the warm document response ends at 6 ms at baseline and at 320 ms on HEAD and `a1a56cb4`. CDP (`Network.responseReceived`) shows why: every proxied `/api` response from `vite preview` carries `Connection: close` (http-proxy without a keep-alive agent; uvicorn itself sends none, checked with curl), so each API call closes its socket. Since Task 2/3 the shell badge reads (`nav/counts`, ineligible count, `algorithm/jobs`) run at the end of the cold load and use up the remaining idle sockets, so the warm navigation opens a new connection and pays the ~300 ms `localhost` connect stall (connect timing 309 ms on HEAD; connection reused at baseline). Over `127.0.0.1`, where there is no stall, HEAD and baseline are equal (page 133 vs 139 ms, FCP 156 vs 152 ms).
- Production does not have this: nginx keeps client connections alive (`keepalive_timeout` default 75 s) and does not pass the upstream's `Connection` header on, and the `localhost` stall is a property of this machine.

No frontend change is justified, so no remedy (route-level prefetch, modulepreload of the page chunk, eager chunks) was built or measured: there is no waterfall to remove, and the earlier FCP investigation showed that preloading route chunks at startup costs FCP. A profiler-side fix (base URL `127.0.0.1`, or record the DOM mark instead of a polled selector) would remove both artifacts from future captures; the profiler was not changed here.

## Follow-up batch 6 (FCP: fonts, nginx, early paint), 2026-10-09

Three recommendations of the [FCP investigation](#fcp-investigation-throttled-2026-10-09), approved by the product owner: A. self-host Heebo; B. nginx with HTTP/2, better compression and explicit cache headers; C. paint a loading status before the JS has run. All three are kept. Commits: A `6e140eab`, B `e1668a03`, C `a0fe3a62`.

### Method

- Harness: the throttled harness of the FCP investigation (Playwright Chromium headless, 1366x768; CDP `Network.emulateNetworkConditions` and `Emulation.setCPUThrottlingRate`; **fast 4G** = 9 / 1.5 Mbps, 150 ms, CPU 4x; **slow 4G** = 1.6 / 0.75 Mbps, 300 ms, CPU 4x; per run and build a new context with one **cold** and one **warm** navigation; FCP, the last LCP entry after network idle, resource timing, the DOM at FCP, and the first DOM appearance of `boot-placeholder`, `page-loading`, `login-form`, `sidebar` (the shell) and the page marker through a MutationObserver). Two changes to the script: it logs in once per profile **and origin**, and it records the new `boot-placeholder` marker.
- Builds, served at the same time by the Node static server of the FCP investigation, which imitates the **pre-batch** `deploy/nginx.conf` (gzip level 1 for HTML/CSS/JS/JSON including the proxied API responses, `immutable` for `*.js|css|woff2|png|svg|ico`, ETag only for `index.html`, SPA fallback, `/api` proxied to the profile server, HTTP/1.1, no TLS). One loopback address per build on port 5174, so the builds have separate origins and cookies and none pays the `localhost` connection stall: **base** = `15a4adfa` on `127.0.0.1`, **fonts** = base + A on `127.0.0.2`, **fonts+placeholder** = base + A + C on `127.0.0.3`. C is measured on top of A, as the commits stack: C's effect is *fonts+placeholder vs fonts*.
- Scenarios: logged-out `/login`; returning user (refresh cookie from one unthrottled login per profile and origin) on `/` and `/transparency`.
- 7 measured runs per cell plus one discarded warm-up run, builds interleaved within each run (base, fonts, fonts+placeholder, ...), strictly sequential, nothing else heavy running, about 2.2 GB free RAM. Backend: `app.scripts.profile_scale_server` on 8100, `justice_scale_fcp_scale` (20,120 soldiers verified), Redis, `LOKI_URL` unset, `TRANSPARENCY_READ_MODEL_ENABLED=true`, user 1000001. p95 of 7 samples is the maximum. Differences below about 10% are treated as noise.
- B was not measured in the browser (the harness serves plain HTTP/1.1 and DevTools throttling adds latency per request, so it cannot show what HTTP/2 multiplexing changes); it was validated with `nginx -t` and a header/size check in the real nginx image, see B below.
- Raw data: `docs/benchmarks/data/followup-b6-fcp-throttled.json` (summary rows and per-measurement metrics, no waterfalls), `docs/benchmarks/data/followup-b6-nginx-check.json`.

### Results, cold cache (ms, p50 / p95)

| Profile | Page | FCP base | FCP fonts | FCP fonts+placeholder | Shell or login form visible: base | fonts | fonts+placeholder | LCP p50: base | fonts | fonts+placeholder |
|---|---|---|---|---|---|---|---|---|---|---|
| fast 4G | /login | 1204 / 1480 | 1184 / 1228 | 636 / 656 | 1106 | 1085 | 1104 | 1204 | 1184 | 1192 |
| fast 4G | / | 1748 / 2152 | 1728 / 2076 | 644 / 660 | 1626 | 1620 | 1691 | 3088 | 3032 | 3120 |
| fast 4G | /transparency | 1824 / 1868 | 1784 / 2068 | 644 / 656 | 1728 | 1676 | 1670 | 2608 | 2584 | 2568 |
| slow 4G | /login | 2548 / 2584 | 2620 / 2728 | 1568 / 1576 | 2434 | 2525 | 2648 | 2548 | 2620 | 2736 |
| slow 4G | / | 3432 / 3724 | 3572 / 3884 | 1564 / 1580 | 3300 | 3456 | 3523 | 6264 | 6352 | 6364 |
| slow 4G | /transparency | 3404 / 3588 | 3540 / 3824 | 1564 / 1572 | 3285 | 3423 | 3543 | 6472 | 6432 | 6484 |

"Shell visible" is the first DOM appearance of `sidebar` (on the returning-user pages; with `15a4adfa` the shell renders around the route fallback), "login form" the first appearance of `login-form`. Page content (page marker p50) moved by at most 30 ms between fonts and fonts+placeholder (slow 4G Home 5709 -> 5736, Transparency 6343 -> 6357).

Warm cache (second visit), FCP p50 base / fonts / fonts+placeholder: fast 4G `/login` 184 / 164 / 56, `/` 932 / 956 / 200, `/transparency` 908 / 908 / 144; slow 4G 184 / 168 / 56, 1156 / 1208 / 156, 1120 / 1088 / 68. Warm shell visible is unchanged within noise (for example slow 4G Home 1129 / 1187 / 1169).

Other per-load values (cold p50): render-blocking stylesheets done fast 4G 912-953 ms (base) -> 590-598 ms (fonts), slow 4G 1969-1995 -> 1515-1522 ms; Heebo loaded at FCP in 0 of 7 cold runs per cell on base and in 7 of 7 with fonts; the Hebrew subset arrives at about 400 ms (fast) and 915 ms (slow); static JS done fast 919-927 -> 942-954 -> 958-962 ms, slow 2286-2291 -> 2375-2379 -> 2515-2520 ms.

### A. Self-hosted Heebo: kept (neutral, removes a third-party dependency)

Change: `frontend/src/styles/globals.css` no longer `@import`s the Google Fonts stylesheet; it declares the faces itself, `font-display: swap`, with the Hebrew and Latin subsets for the weights the old stylesheet provided (300, 400, 500, 700, one face per weight as before, so `font-semibold` still renders with the 700 face; the font is variable, so all weights of a subset are one file). `frontend/index.html` preloads the Hebrew subset (`<link rel="preload" as="font" type="font/woff2" crossorigin>`). Files, in `frontend/public/fonts/` (copied unhashed to `dist/fonts/`; chosen over `src/assets/` because `index.html` must preload a stable URL and the existing Cinzel font already lives there; the file names carry the Google Fonts version `v28`, because `/fonts/` is served `immutable`, so a changed file must get a new name):

| File | Source URL | Bytes |
|---|---|---|
| `Heebo-v28-hebrew.woff2` | `https://fonts.gstatic.com/s/heebo/v28/NGS6v5_NC0k9P9H0TbFzsQ.woff2` | 12,036 |
| `Heebo-v28-latin.woff2` | `https://fonts.gstatic.com/s/heebo/v28/NGS6v5_NC0k9P9H2TbE.woff2` | 30,116 |
| `Heebo-OFL.txt` | `https://raw.githubusercontent.com/google/fonts/main/ofl/heebo/OFL.txt` (SIL Open Font License 1.1, "Copyright 2014 The Heebo Project Authors") | 4,474 |

The woff2 URLs and unicode ranges come from `https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;500;700&display=swap` fetched with a Chrome User-Agent; both files start with the `wOF2` signature. Google's `latin-ext`, `math` and `symbols` subsets were not copied, so those characters now fall back to Arial. CSP: the only CSP in the repository is the backend's (`backend/app/middleware/security_headers.py`, `font-src 'self'`), which applies to backend responses, not to the SPA served by nginx; it never allowed the Google hosts, and nothing changes there.

Result: FCP and LCP are unchanged within noise: fast 4G -1 to -2%, slow 4G +3 to +4% (+70 to +140 ms). The slow 4G increase has the same direction on all three pages and the `/login` ranges do not overlap (2520-2584 vs 2596-2728 ms), so it is probably real but small: the preloaded Hebrew subset (12 kB) now downloads alongside the JS, which then ends about 90 ms later at 1.6 Mbps. In exchange, the first paint is already in Heebo (7/7 vs 0/7 runs; on base the font arrived after the measured load, so users saw a font swap later), the render-blocking stylesheet chain ends 320-470 ms earlier (no second-origin CSS behind `index.css`), and the app no longer needs `fonts.googleapis.com` / `fonts.gstatic.com` at all, a connection this harness does not even emulate (DNS, TCP and TLS to a new origin) and one that blocks rendering until it fails on a network that cannot reach Google. Kept as neutral-and-removes-a-third-party-dependency, not as a speed-up.

### B. nginx (`deploy/nginx.conf`): kept, **needs ops review before rollout**

Image from `deploy/docker-compose.prod.yml`: `nginx:1.27-alpine` (stock nginx, no `ngx_brotli`, so no brotli directives). Changes:

- `http2 on;` in the TLS server (syntax for nginx >= 1.25.1). TLS settings unchanged.
- gzip: `gzip_comp_level 6` (default was 1), `gzip_min_length 256`, `gzip_vary on`, `gzip_types` plus `text/javascript` and `image/svg+xml` (woff2 stays out, it is already compressed). The 20 `/assets/` files `index.html` loads: 308,995 -> 262,618 bytes transferred (-15%).
- Cache-Control from a `map $uri` applied with one server-level `add_header`: `/assets/` and `/fonts/` `public, max-age=31536000, immutable`; other `*.js|css|woff2?|png|svg|ico` keep year-long caching as before; everything else, notably `index.html` and the SPA fallback (which ends as `/index.html`), `no-cache`, so a deploy is picked up on the next visit and a stale `index.html` cannot point at deleted chunks; nothing is added on `/api/`. This replaces the nested `location` with `expires 1y` + `add_header`, which sent two Cache-Control headers and, because an `add_header` in a location replaces all inherited ones, dropped HSTS, `X-Content-Type-Options` and `X-Frame-Options` on every static file. The security headers now apply to static files again.
- Unchanged: security headers, `limit_req` and all proxy settings.

Validation, in the locally present `nginx:1.27-alpine` (nginx/1.27.5), config and a throwaway self-signed certificate mounted read-only, upstream host names mapped with `--add-host`: `nginx -t` -> "syntax is ok" / "test is successful", no warnings. Serving the fonts+placeholder build from that container: ALPN `h2` (old config: none); `/`, `/login`, `/index.html` -> `Cache-Control: no-cache`, gzip, `Vary: Accept-Encoding`; a hashed `/assets/*.js` and `/fonts/Heebo-v28-hebrew.woff2` -> `public, max-age=31536000, immutable` with all three security headers (old config: `Expires`, two Cache-Control headers, no security headers). Temporary container, certificates and files were removed.

Ops review: check that nothing between the client and nginx strips ALPN (a TLS-terminating load balancer in front would need its own HTTP/2 setting), that the extra gzip CPU is acceptable, and the `no-cache` on HTML. Observation, not changed: `limit_req zone=api rate=10r/s burst=20 nodelay` per IP is close to one cold Home load (about 32 requests, most of them `/api/`); users behind one NAT or proxy address share that budget and could get 503s on a burst. With HTTP/2 the requests arrive faster, which makes the burst limit more likely to bite.

`/pdfjs/pdf.worker.min.mjs` is served as `application/octet-stream` with `X-Content-Type-Options: nosniff` (stock `mime.types` has no `.mjs`); this was the same before the change and is not addressed here; if the worker is loaded as a module script from that URL in production, it needs a `types { application/javascript mjs; }` entry.

### C. Early loading paint: kept (FCP earlier, shell not earlier)

Change: `frontend/index.html` puts a static status inside `#root`: `<div data-testid="boot-placeholder" role="status" aria-live="polite" style="padding: 2rem; text-align: center">טוען...</div>`, the same text and box as `PageLoading`. It paints as soon as the stylesheet has loaded, before the module scripts have downloaded. React's first render replaces it. `ProtectedRoute` now renders `PageLoading` during the session restore instead of `null`, so the sequence for a returning user is placeholder -> identical React status -> shell with the status (route fallback) -> page, with no blank frame and no layout shift; the app's own loading states are unchanged. Decisions:

- Neutral status, no nav skeleton: the auth state is unknown before JS, and a nav skeleton would flash on the login page. On `/login` the visitor now sees "טוען..." for about 0.45 s (fast 4G) / 1.1 s (slow 4G) before the form, instead of a blank page.
- Theme: no extra code needed. The stylesheet is render-blocking, so the placeholder never paints before `globals.css` (body colours, `.dark body`), and the existing inline theme script in `<head>` sets `.dark` before `<body>` is parsed. It inherits the page font and colour like `PageLoading`.
- CSP: the SPA has no CSP (nginx sets none; the inline theme script already relies on that), and the placeholder needs no script; it uses a `style` attribute only.
- Tests: `frontend/src/bootPlaceholder.test.tsx` (the `#root` markup has the status role, `aria-live`, the `app.loading` text, no nav/header/aside and no script; its box matches `PageLoading`; `ProtectedRoute` shows the status while `authLoading`).

Result, fonts -> fonts+placeholder (cold p50):

| Metric | fast 4G | slow 4G |
|---|---|---|
| FCP `/login` | 1184 -> 636 | 2620 -> 1568 |
| FCP `/` | 1728 -> 644 | 3572 -> 1564 |
| FCP `/transparency` | 1784 -> 644 | 3540 -> 1564 |
| Shell visible `/` | 1620 -> 1691 (+4%) | 3456 -> 3523 (+2%) |
| Shell visible `/transparency` | 1676 -> 1670 | 3423 -> 3543 (+4%) |
| Login form visible | 1085 -> 1104 | 2525 -> 2648 (+5%) |
| Page content | +11 / -3 ms | +27 / +14 ms |

FCP now measures the placeholder. It moves 0.55-1.1 s earlier on fast 4G and 1.05-2.0 s earlier on slow 4G, and warm FCP drops to 56-200 ms. **Nothing useful appears sooner:** the shell, the login form and the page content are unchanged within noise, and on slow 4G they are 2-5% (70-120 ms) later. The likely reason: the placeholder's "..." is a Latin character, so its paint makes the browser fetch the 30 kB Latin subset of Heebo while the JS is still downloading (slow 4G: Latin subset done at 2274 instead of 3211 ms, JS done 2519 instead of 2377 ms). This is the result the FCP investigation predicted for painting during the session restore. Do not read the FCP drop as a shell speed-up.

A + C together against base, shell visible: fast 4G Home 1626 -> 1691, Transparency 1728 -> 1670; slow 4G Home 3300 -> 3523 (+7%), Transparency 3285 -> 3543 (+8%); `/login` form slow 4G 2434 -> 2648 (+9%). Each is below the 10% noise threshold, but the slow 4G direction is the same everywhere: on a 1.6 Mbps link the two font files (42 kB) compete with the JS. If that matters more than the earlier first paint and the font being right on the first paint, the options are to drop the Hebrew preload or keep the placeholder free of Latin characters; neither was measured.

### Caveats

- One workstation, emulated network and CPU over loopback, headless Chromium, plain HTTP/1.1 without TLS, a Node server imitating the old nginx config; not production RUM. DevTools throttling applies latency per request and does not model DNS, TCP or TLS setup, so the base build's Google Fonts connection is cheaper here than on a real network (A's real-world benefit is larger than measured) and HTTP/2 (B) cannot be measured this way.
- 7 runs per cell; p95 is the maximum of 7. C's numbers are relative to A (stacked builds).
- The nginx change was validated with `nginx -t` and response headers in the production image, not under real traffic, and needs ops review before rollout.
