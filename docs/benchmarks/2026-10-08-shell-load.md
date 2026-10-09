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

Decision gate: phase 1 was 77% of the baseline, so row 1 applied first. Loading rows instead of entities made phase 2 slower, because by-name attribute access on a SQLAlchemy `Row` costs more than on an entity. That left phase 2 at 61%, so row 2 applied next: group soldiers by the nine fields `_is_eligible` reads (44 distinct profiles at 20k) and build the group key positionally. The end-to-end median went from 577 to 156 ms (3.7x), under the 250 ms target. No cache was added. The count still matches `len(list_ineligible_soldiers(...))` on the scale database for every scope (admin 1 = 1, branch 1 = 1, group 0 = 0, team 0 = 0).

Sanity check against the baseline: the in-process 577 ms sits below the 928 ms server median at c1, because the server number also includes auth, `_resolve_roots` and contention with the other shell requests of the same page load.
