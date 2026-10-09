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

Decision gate: phase 1 was 77% of the baseline, so row 1 applied first. Loading rows instead of entities made phase 2 slower, because by-name attribute access on a SQLAlchemy `Row` costs more than on an entity. That left phase 2 at 61%, so row 2 applied next: group soldiers by the nine fields `_is_eligible` reads (44 distinct profiles at 20k) and build the group key positionally. The end-to-end median went from 577 to 156 ms (3.7x), This is an in-process figure (no auth, no network, no other requests); the end-to-end result of the same code is in the Task 7 section: c5 cold p50 1481 ms wall / 1146 ms server against the 1.0 s target, which was missed. No cache was added. The count still matches `len(list_ineligible_soldiers(...))` on the scale database for every scope (admin 1 = 1, branch 1 = 1, group 0 = 0, team 0 = 0).

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

## After (Task 7), 2026-10-09

Matched re-run of the Task 1 matrix on the final code.

### Setup

- Code measured: `46d6d67c`. Application code is identical to `305c805b`; the commits on top only add documentation and the `t6-final` artifact.
- Same procedure, database (`justice_scale_fcp_scale`, 20,120 soldiers, 1,000,008 assignments verified before the run), Redis, profile server on 8100 (`LOKI_URL` unset, `TRANSPARENCY_READ_MODEL_ENABLED=true`), production build served by `vite preview` on 5174, user 1000001, `localhost:5174` as base URL. A discarded 1-run warm-up of every scenario (c1, then c5) preceded the measured runs; no vitest or build ran during a capture. c1 then c5, strictly sequential, 5 runs each.
- Entry chunk `assets/index-DEVk5xgm.js` = 428.60 kB raw (428,598 bytes), 113.46 kB gzip (baseline 3,989.42 kB / 1,099.94 kB gzip). `fullcalendar`, `recharts`, `react-pdf`, `katex` and `markdown` are separate chunks, next to one chunk per page.
- Artifacts: `docs/benchmarks/data/shell-load-after-c1-20261008.json` (70 measurements) and `shell-load-after-c5-20261008.json` (350 measurements); every measurement reached readiness, exit code 0. They contain no password or database URL strings. Compare with `node frontend/scripts/summarize-scale-pages.mjs <after> <before>`.
- Single capture pair, no re-runs. Free memory was about 2.7 GB of 16 GB when the run started; other applications were running as in the baseline (Docker Desktop with the other project containers, Firefox, WhatsApp, Claude desktop, Windows Defender).

### Success criteria

| Criterion | Baseline | Target | Measured | Result |
|---|---|---|---|---|
| `GET /api/admin/errors/unread-count` requests, Loki unset | 134 (c1), 836 (c5) | 0 | 0 (c1), 0 (c5) | Met |
| Entry JS chunk, raw | 3,989 kB | <= 1.6 MB, heavy libraries in lazy chunks | 428.6 kB (113.5 kB gzip); heavy libraries in separate chunks | Met |
| Requests per cold page load | home 39, calendar team 23, calendar org 18-19, hierarchy 16-17, hr-sync 20, soldier detail 20-21, transparency 10 | no endpoint more than once per page load, except genuine refetches | home 32, calendar team 18, calendar org 14, hierarchy 12, hr-sync 16, soldier detail 16, transparency 10. Remaining pairs: Home `ranges` x2 and `calendar/shifts` x2; Calendar team `hierarchy/branches`, `ranges`, `calendar/shifts` x2; Soldier detail `soldiers/roster` x2 (all analysed in the Task 6 section as different queries or profiler steps); warm Hierarchy one aborted `hierarchy/branches` of the previous page | Met, with those documented exceptions |
| `ineligible-soldiers/count` c5 cold p50 (end to end) | 4144 ms wall, 3780 ms server (c1: 1219 / 901) | <= 1.0 s | 1481 ms wall, 1146 ms server (c1: 601 / 282) | **Missed** |
| FCP c5 cold p50, each page | 1512-1592 ms | <= 2.0 s | 1040-1168 ms (all pages together 1124 ms) | Met (already met at baseline) |
| Page-ready p95, every page, c1 and c5 | c1 cold 2.3-6.6 s, c5 cold 7.8-14.3 s | not worse than baseline | c5: no page worse (all 14 scenario/modes lower or equal). c1: 4 of 14 worse: Transparency cold 2266 -> 2536, Transparency warm 1352 -> 2218, Hierarchy warm 1842 -> 2658, HR sync warm 2065 -> 2501 ms | **Missed** (c1) |

Counts: 4 met, 2 missed.

Ineligible count in more detail (cold, 200 responses, wall / server p50): c1 1219 / 901 -> 601 / 282 ms, c5 4144 / 3780 -> 1481 / 1146 ms; warm c5 4556 / 3703 -> 1345 / 1011 ms. The in-process figure from Task 4 (156 ms) does not carry over to the page load: at c5 five browsers hit one backend with other shell reads running, and the server time is 1.1 s. At c5 the database part is 783-846 ms of it (17 queries, same as before, 2490-2602 ms at baseline).

FCP: the target was met at baseline (the 3.4-3.8 s seen earlier was Vite dev-server overhead, see the Setup section above). After the changes, cold FCP p50 is lower on every page at both concurrencies (c1 1272 -> 864 ms across pages, c5 1536 -> 1124 ms; per page 340-480 ms lower) and the c5 p95 values are lower or equal, so the cold reduction is larger than the baseline's own run-to-run spread, but it is one capture pair on one machine and this experiment does not isolate its cause (the entry chunk shrank, which is consistent with it). Warm FCP is lower on the other pages and higher on Transparency (c1 436 -> 772, c5 508 -> 840 ms) and slightly on Home at c1 (712 -> 772 ms).

### Per-page results (ms, baseline -> after)

c1, cold:

| Page | Ready p50 | Ready p95 | FCP p50 | FCP p95 | Requests |
|---|---|---|---|---|---|
| Home | 5917 -> 5020 | 6068 -> 5064 | 1272 -> 856 | 1316 -> 956 | 39 -> 32 |
| Calendar (synthetic team) | 6302 -> 5113 | 6569 -> 5277 | 1292 -> 848 | 1316 -> 1252 | 23 -> 18 |
| Calendar (whole org) | 4243 -> 3287 | 4413 -> 3342 | 1268 -> 912 | 1316 -> 956 | 18 -> 14 |
| Hierarchy/Team | 4357 -> 2757 | 4487 -> 2893 | 1288 -> 836 | 1328 -> 952 | 16 -> 12 |
| HR sync review | 4154 -> 3008 | 4346 -> 3506 | 1216 -> 828 | 1364 -> 1244 | 20 -> 16 |
| Soldier detail | 5739 -> 4170 | 6521 -> 4284 | 1256 -> 884 | 1412 -> 1012 | 20 -> 16 |
| Transparency | 2214 -> 2523 | 2266 -> 2536 | 1296 -> 944 | 1312 -> 952 | 10 -> 10 |

c1, warm:

| Page | Ready p50 | Ready p95 | FCP p50 | FCP p95 | Requests |
|---|---|---|---|---|---|
| Home | 5902 -> 4112 | 6174 -> 4661 | 712 -> 772 | 756 -> 792 | 39 -> 32 |
| Calendar (synthetic team) | 5905 -> 4210 | 6212 -> 4233 | 708 -> 428 | 736 -> 436 | 23 -> 18 |
| Calendar (whole org) | 3711 -> 2379 | 3727 -> 2461 | 528 -> 440 | 584 -> 508 | 18 -> 14 |
| Hierarchy/Team | 1829 -> 2396 | 1842 -> 2658 | 836 -> 460 | 840 -> 724 | 13 -> 13 |
| HR sync review | 2035 -> 2437 | 2065 -> 2501 | 724 -> 412 | 748 -> 468 | 16 -> 16 |
| Soldier detail (in-app modal) | 1550 -> 1356 | 1604 -> 1480 | - | - | 4 -> 3 |
| Transparency | 1346 -> 2116 | 1352 -> 2218 | 436 -> 772 | 440 -> 776 | 10 -> 10 |

c5, cold:

| Page | Ready p50 | Ready p95 | FCP p50 | FCP p95 | Requests |
|---|---|---|---|---|---|
| Home | 14116 -> 7731 | 14259 -> 7918 | 1556 -> 1124 | 1612 -> 1180 | 39 -> 32 |
| Calendar (synthetic team) | 10920 -> 6872 | 11475 -> 7166 | 1564 -> 1120 | 1896 -> 1248 | 23 -> 18 |
| Calendar (whole org) | 8168 -> 4607 | 9199 -> 4753 | 1516 -> 1140 | 1628 -> 1248 | 19 -> 14 |
| Hierarchy/Team | 7589 -> 4015 | 8018 -> 4160 | 1592 -> 1120 | 1696 -> 1216 | 17 -> 12 |
| HR sync review | 7288 -> 4196 | 8390 -> 4471 | 1532 -> 1040 | 1800 -> 1532 | 20 -> 16 |
| Soldier detail | 9569 -> 6187 | 10046 -> 6660 | 1512 -> 1072 | 1544 -> 1152 | 21 -> 16 |
| Transparency | 2677 -> 3691 | 7790 -> 3921 | 1584 -> 1168 | 1652 -> 1576 | 10 -> 10 |

c5, warm:

| Page | Ready p50 | Ready p95 | FCP p50 | FCP p95 | Requests |
|---|---|---|---|---|---|
| Home | 13714 -> 7248 | 14144 -> 7470 | 1052 -> 908 | 1116 -> 952 | 39 -> 32 |
| Calendar (synthetic team) | 10050 -> 6070 | 11477 -> 6487 | 732 -> 560 | 1124 -> 616 | 23 -> 18 |
| Calendar (whole org) | 7733 -> 4133 | 9704 -> 4383 | 1048 -> 600 | 1156 -> 648 | 19 -> 14 |
| Hierarchy/Team | 2164 -> 3211 | 6639 -> 3538 | 860 -> 644 | 1240 -> 704 | 13 -> 13 |
| HR sync review | 3701 -> 3525 | 6159 -> 3599 | 748 -> 584 | 1140 -> 648 | 20 -> 16 |
| Soldier detail (in-app modal) | 2512 -> 2547 | 2839 -> 2760 | - | - | 4 -> 3 |
| Transparency | 1618 -> 3218 | 5202 -> 3347 | 508 -> 840 | 4244 -> 880 | 10 -> 10 |

### What got worse

Page-ready p50 is higher after on: Transparency (c1 cold 2214 -> 2523, c1 warm 1346 -> 2116, c5 cold 2677 -> 3691, c5 warm 1618 -> 3218 ms), Hierarchy warm (c1 1829 -> 2396, c5 2164 -> 3211 ms) and HR sync warm at c1 (2035 -> 2437 ms). Soldier detail warm at c5 is flat (2512 -> 2547 ms). Every other page and mode is lower, (Home cold 15% lower at c1 and 45% at c5; the cold Calendar, Hierarchy, HR sync and Soldier detail pages 19-37% at c1 and 35-47% at c5). Several baseline c5 p95 values were inflated by outliers (Transparency cold 7790, Hierarchy warm 6639, Transparency warm 5202 ms), so the c5 p95 improvements on those pages come from removing the outliers while the p50 got worse.

What the data shows: "page ready" is the later of the page marker and a quiet period without API traffic. On the pages that got worse, the time at which the page's own marker becomes visible did not rise as much as the quiet time (Transparency c1 cold: marker 1659 -> 957 ms, quiet 2209 -> 2520 ms; c1 warm: marker 909 -> 1212 ms, quiet 1343 -> 2112 ms). The request lists differ: in the baseline Transparency window (10 requests) there was no `nav/counts`, `ineligible-soldiers/count` or `algorithm/jobs` call; in the after window they are present, started at about 280-330 ms and taking 1.1-1.2 s each at c5, and they end after the Transparency read itself. The navigation reads in `UnifiedNav` are gated on other queries settling (`navReadsEnabled`); the likely explanation is that, with the error-log calls and their retries gone, the gate now opens early enough for these three reads to land inside the measured window, where before they started after the page had been declared quiet. That is a hypothesis from the request timeline and the source, not tested by a separate experiment. If it is right, part of the cost moved into the measurement window rather than appeared. It does not explain the later marker on warm Transparency (c1 909 -> 1212 ms, c5 946 -> 1282 ms), which stays unexplained.

Other measured regressions:

- `GET /api/nav/counts` at c5 got slower per call: 564 -> 1380 ms wall, 228 -> 1061 ms server (c1 improved: 1031 -> 454 wall, 713 -> 276 server). The after run completes this call in all 325 page loads (baseline: 253 of 325), and it now runs concurrently with the ineligible count and the page's own reads under 5 browsers. The cause is not isolated; it is the next lead for shell cost at c5.
- Warm FCP on Transparency and (c1) Home, above.

Cheap shell calls got much cheaper on the wall clock at c1: `GET /api/me` 362 -> 47 ms, `notifications/unread-count` 346 -> 26 ms (server time 47 -> 36 and 27 -> 16 ms). The server share is small, so most of the baseline wall time of those calls was outside the handler; with fewer concurrent requests per page this is consistent with fewer new connections hitting the ~300 ms `localhost` connection stall described under the Task 6 section, but that was not tested.

### Caveats

- Local single-machine measurement: production build served by `vite preview` over loopback against a profile server (with timing headers) and a local Postgres, one capture pair, with other applications running and about 2.7 GB of free memory. It is not a production-capacity result; values are comparable only with the baseline taken on the same setup and carry run-to-run noise, especially at c5.
- Every new browser connection to `localhost:5174` waits about 300 ms before its request starts (found in Task 6). It is a measurement artifact that inflates wall times in both the baseline and these runs; it does not exist in production.
- The `ineligible-soldiers/count` target (1.0 s) was missed by about 0.5 s at c5; the remaining server time is 1.1 s, of which about 0.8 s is database time. Further work would need a different read path or a cache with an invalidation rule, which the plan reserved for when a pure query optimization was not enough.

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
