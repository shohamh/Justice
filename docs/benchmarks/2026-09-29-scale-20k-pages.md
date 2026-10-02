# 20,000-Soldier Scale Seed and Page Performance

Date: 2026-09-30; follow-up updated 2026-10-02
Branch: feature/scale-20k-profiling
Original baseline source commit: 4bb2131b60ea1754199095afc0e349cf81145ab1

## Summary

The isolated scale seed and browser profiler are in place. The database contains 20,000 synthetic soldiers plus 121 preexisting soldiers (20,121 total), 400 synthetic teams, about 1,000,000 published duty assignments over two years, 20,000 HR profiles, 200 HR review rows, and 50 rank conflicts. Score projection backfill completed for the synthetic soldiers.

The original pre-implementation run did not meet the quick-readiness goal: transparency took 317–323 seconds, Home 130–143 seconds, hierarchy 65–77 seconds, and the cold soldier-detail workflow 91 seconds. Calendar took about 8–10 seconds. HR review took 5.8–7.0 seconds even though its HR-specific APIs were much faster than shared navigation calls.

The later uncommitted worktree candidate added bounded roster and hierarchy loading, transparency paging, virtualized lists, and route changes. It observed hierarchy at 3.8–4.2 seconds, Home at 12.4–14.4 seconds, whole-calendar at 6.3–6.9 seconds, and transparency at about 42.6 seconds. HR is the only follow-up route with five samples; the other candidate routes have one pair each. The runs are diagnostic evidence, not a commit-pinned before/after comparison or production SLO.

The full-page concurrency matrix below predates the transparency end-date index. The latest post-index captures are a five-pair c1 run across all seven journeys, plus targeted transparency batches at c5 and c10. All browser measurements reached the configured readiness marker, but the c10 transparency batch also produced HTTP 500s after exhausting the backend SQLAlchemy connection pool. Treat the c1 values as current single-client observations and the c5/c10 results as one-batch contention evidence, not healthy-capacity percentiles. The original baseline remains unchanged.

## Method and limits

- The benchmark used a disposable local PostgreSQL database, a local profiling backend on port 18000, the worktree Vite frontend on port 5174, and Chromium 148.0.7778.96.
- A cold sample was the first visit in the run. A warm sample revisited the page in the same browser context. The soldier warm sample reopens the already-loaded soldier modal.
- The runner measured route readiness after the page marker appeared and the network was quiet for 500 ms. This is an end-to-end readiness measure, not first paint, Largest Contentful Paint, or a production SLO.
- The original baseline has one cold/warm pair per workload. The 2026-10-01 candidate follow-up has five cold/warm samples for HR and one pair for each other workload. Only the HR samples support descriptive n=5 p50/p95 summaries; the other candidate results are exploratory single samples.
- Follow-up runs can use `node frontend/scripts/profile-scale-pages.mjs --concurrency 1`, `--concurrency 5`, or `--concurrency 10`. The runner signs in once in an unmeasured setup context, captures Playwright storage state in memory, then starts independent client contexts from that state. Each client restores its app session through the normal refresh-cookie flow; setup traffic is drained before the cold/warm start barriers. Login and setup requests do not enter route measurements. The runner writes p50/p95/sample-count summaries to a unique run artifact by default; set `JUSTICE_SCALE_OUTPUT` to choose another path, and the runner refuses to overwrite an existing file. This existing raw result remains the original single-client baseline.
- The default five runs produce descriptive single-client p50/p95 values from n=5 samples, not stable production percentiles. API response-byte and database totals omit samples when any tracked request lacks that telemetry; endpoint summaries report the available sample count.
- The runner records sanitized route names, status, duration, response bytes, SQL count and accumulated SQL time, console/page errors, and browser long tasks. It does not store request/response bodies, SQL text, query parameters, or credentials.
- HR review was read-only. An external HR provider sync was not invoked.
- The 10k audit in [the August audit](../superpowers/specs/2026-08-21-performance-audit-10k-users.md) is historical context only. Its dashboard endpoint, application revision, and environment differ, so it is not a direct before/after comparison.
- The raw results are in [scale-20k-pages.json](data/scale-20k-pages.json). The seed and profiler are [seed_scale_test.py](../../backend/app/scripts/seed_scale_test.py), [profile-scale-pages.mjs](../../frontend/scripts/profile-scale-pages.mjs), and [profile_scale_server.py](../../backend/app/scripts/profile_scale_server.py).

## 2026-10-01 implementation-candidate follow-up

The follow-up used the same disposable local database, profile backend on port 18000, frontend on port 5174, and Chromium 148.0.7778.96. It ran at concurrency 1 after the current worktree changes. The tree is still uncommitted, so these numbers describe this worktree state and cannot be attributed to a commit. They should not be read as a controlled before/after comparison with the original baseline.

The hierarchy and soldier cold-path observations are much shorter than the original baseline, but the runs are not a controlled comparison and the difference cannot be attributed to one change. The candidate still misses the proposed two-second page target on every successfully measured route. Transparency remains the largest bottleneck. The one-sample routes do not support percentile claims.

| Workload | Cold ready | Warm ready | API calls, cold/warm | Browser long tasks, cold/warm | Sample count |
|---|---:|---:|---|---|---:|
| Transparency, whole organization | 42.63 s | 42.60 s | 31 / 31 | 2 (181 ms) / 0 | 1 pair |
| Hierarchy, whole organization | 4.22 s | 3.82 s | 26 / 27 | 2 (144 ms) / 0 | 1 pair |
| Soldier detail, roster search then modal | 7.08 s | **not ready** (60.09 s timeout) | 34 / 14 | 2 (141 ms) / 0 | 1 cold success; warm failed |
| Calendar, whole organization | 6.88 s | 6.33 s | 28 / 28 | 3 (619 ms) / 2 (174 ms) | 1 pair |
| Calendar, synthetic team | **not ready** (37.51 s timeout) | **not ready** (36.37 s timeout) | 35 / 35 | 6 (526 ms) / 2 (143 ms) | Both attempts failed |
| Home dashboard | 14.42 s | 12.38 s | 54 / 53 | 3 (251 ms) / 1 (125 ms) | 1 pair |
| HR sync review | 4.97 s p50 / 5.14 s p95 | 4.44 s p50 / 4.56 s p95 | 27 / 27 p50 | 1 task, 90 ms p50 / 0 p50 | 5 pairs |

Failed journeys are not reported as page timings. The synthetic-team calendar interaction and warm soldier-modal reopen hit the profiler's generic timeout with no page exception. They need a reliable interaction/readiness trace before they can be compared. HR p50/p95 are descriptive n=5 sample percentiles, not production SLOs.

### Current slow API evidence

| Route or API | Candidate result | SQL / accumulated DB time | Response bytes |
|---|---:|---:|---:|
| Transparency page, cold/warm | 42.63 / 42.60 s page-ready | 609 statements; API DB time 9.23 / 9.75 s | 73,874 |
| `GET /api/scoring/transparency/page`, cold/warm | 40.67 / 41.07 s | 609; 9.23 / 9.75 s | 73,874 |
| `GET /api/soldiers/roster`, hierarchy cold/warm | 770 / 752 ms | 7; 99 / 60 ms | 34,637 |
| `GET /api/soldiers/roster`, soldier-detail cold | 729 ms | 7; 35 ms | 34,637 |
| `GET /api/soldiers/:id/score`, soldier-detail cold | 718 ms | 27; 87 ms | 155 |
| `GET /api/calendar/shifts`, whole calendar cold/warm | 4.21 / 4.38 s | 202; 2.69 / 2.96 s | 94,570 |
| `GET /api/ranges`, calendar cold/warm | 3.70 / 4.15 s | 158; 3.24 / 3.70 s | 8,023 |
| `GET /api/ranges/ineligible-soldiers`, Home cold/warm | 5.56 / 7.55 s | 32; 3.06 / 3.21 s | 1,912 |
| `GET /api/command-dashboard/alerts`, Home cold/warm | 5.40 / 5.80 s | 17; 4.02 / 1.51 s | 175 |
| `GET /api/potential`, Home cold/warm | 4.38 / 5.16 s | 58; 66 / 73 ms | 54,516 |

The transparency page no longer issued the whole-organization burden-share-gap request on the default Soldiers tab. Its remaining page API still takes about 41 seconds, with 609 SQL statements and a 74 KB response. The code path materializes and fingerprints the full transparency projection before applying the requested slice; database-accounted time is only part of endpoint wall time, so the remaining time needs separate projection, hashing, and serialization instrumentation.

Source follow-up found that the projected service enumerates and validates all projection keys, then its burden-share helper enumerates the full key set again and repeats readiness checks. A request-local reuse change is in progress. The c1 artifact does not record projected-versus-legacy path selection or phase CPU time, so this duplicated work is an avoidable source-level cost but is not yet attributed as the cause of the measured 41 seconds.

The lazy hierarchy path now returns a bounded roster slice (34.6 KB, seven statements) and a bounded branch response in this sample. The hierarchy page still takes 3.8–4.2 seconds; shared-shell counters such as the ineligible-soldier count took about 1.8 seconds in both visits. The soldier-detail cold path took 7.1 seconds, while its roster and score calls were each about 0.7 seconds; shared-shell traffic and the failed warm reopen prevent a clean detail-only conclusion.

Calendar latency is not mainly browser rendering in this sample: its longest page long task was 619 ms. The shifts route issued 202 statements, while a separate ranges request issued 158. The API and SQL work need query-level profiling before index changes. Home also remains slow despite modest page long tasks; the ineligible-soldier response and command-dashboard alerts are top contributors. `GET /api/potential` returned 54.5 KB in 4.4–5.2 seconds despite only 66–73 ms accumulated SQL, which points to work outside measured SQL but does not identify its exact phase.

The raw Home trace contained two full `GET /api/ranges/ineligible-soldiers?audience=commander` calls on each visit. The first took 5.56 s cold / 7.55 s warm, and the second 3.01 s / 2.94 s; both returned the same 32 SQL statements. `HomePage` separately fetched the list for its badge, while the collapsed `IneligibleSoldiersPanel` also mounted and fetched it under a different query key. The implementation now uses an explicitly commander-scoped count for the badge and defers the full list until that panel opens; the existing count route retains its planning-scope default. Focused checks and a static authorization/cache-scope review passed, but this candidate change has not been reprofiled in the browser.

Read-only source tracing also found Home requests `/api/potential` for each node commanded by the user. That endpoint returns per-soldier eligibility, rank, and exemption details, while Home displays only each node's eligible count, modifier total, and final potential. A summary response can skip detail-only qualification/exemption construction while preserving the same as-of eligibility and authorization rules; the 4.4â€“5.2 s wall time versus 66â€“73 ms accumulated SQL makes this a measured candidate, but the trace does not isolate the Python phase or prove expected savings.

The new `/api/potential/summary` route is implemented for this Home consumer. It keeps the full route's node authorization, reference date, subtree, rank, eligibility, exemption, modifier, and `left_at` semantics, while omitting per-soldier details and detail-only eligibility exclusions. Focused backend checks passed 4/4, potential API tests 6/6, focused Home tests 4/4, Ruff and `git diff --check` passed, and independent static review was clean. A later c1 browser profile is recorded below; because it uses a different endpoint and is not controlled to the earlier `/api/potential` sample, it provides no evidence of improvement from this implementation.

HR's five HR-specific routes were substantially faster than the full page: cold p95 ranged from 386 ms to 737 ms, and warm p95 from 388 ms to 779 ms, each with two or three SQL statements. By comparison, the shared `GET /api/ranges/ineligible-soldiers/count` took 2.89 s cold p95 and 2.79 s warm p95 with 31 statements. Algorithm-job and hierarchy-transfer shell requests were also around 2.6–2.7 s p95. `GET /api/admin/errors/unread-count` returned 503 because Loki is not configured in this local profile environment; this is an environment result, not an HR endpoint failure.

The profile-date batching change in `project_duty_eligibility` did not reduce the 31-statement count or improve the ineligible-count timing in this seed. The synthetic assignment dates did not exercise the future-duty profile path where that per-duty lookup could grow, so this capture does not prove an improvement or a regression from that change.

### Focused backend optimization follow-up (2026-10-01)

The code slices below were implemented after the c1 page capture above. Their results are focused service/test evidence only; the route timings and page-readiness table above do not include these changes.

- **Ineligible-soldier count:** three alternating direct service runs on the seeded database kept the count unchanged and reduced the median from 2.986 s to 2.034 s, with SQL statements reduced from 17 to 16. This is a service-level median, not an HTTP p95. The count route and HR page have not been reprofiled after the change. The Home page's full ineligible-soldier list is a separate endpoint and remains unmeasured after the shared refactor.
- **Home ineligible-soldier badge and panel:** the badge now calls the scoped count endpoint with `audience=commander`; the collapsed list panel no longer fetches until opened. The count and list have different React Query keys, each bound to the current authorization scope, and the backend preserves planning as the count route default while applying the list's commander authorization resolver for explicit commander counts. Backend commander/list parity, planning-default, and unauthorized-audience checks passed (3); frontend API/panel checks passed (12), the Home lazy-load check passed (1), the UnifiedNav badge check passed (1), Ruff passed, and independent static review was clean. The broader Home test file had 10 passes and 3 failures (two scoring-error-banner assertions and one management scope-label fixture); typecheck still reports errors in inherited WIP files, with none in this slice. No post-change 20k route timing is available: profiler admin credentials are absent from the current process environment.
- **Calendar shifts:** a focused regression exposed query growth from one shift to six shifts before the change (16 to 19 SELECTs). The fix retains loaded duty-type rows so reserve-count lookup can reuse them. The regression now measures each case in a fresh session; reverting the fix makes it fail, and the focused service/API suite passed 32/32. No 20k route rerun has measured the effect on the 202-statement calendar request.
- **Transparency projection inputs:** the burden-share input now groups and sums the two numeric score columns in SQL rather than hydrating projection ORM rows and their JSON fingerprints. The focused projection/scoring run passed 56 tests, and the regression checks the result and selected SQL shape. No latency or end-to-end query-count improvement has been measured for the 41-second transparency request.
- **Transparency readiness reuse:** the projected request now enumerates projection keys once and reuses that request-local set, while retaining the narrower second readiness/repair check over the effort quarters and full active-soldier scope. The regression verifies one key enumeration, both readiness checks, and legacy-equivalent output; it passed 2/2 focused tests and received a clean static re-review. No latency change has been measured.

The full backend suite did not pass cleanly: it reported two failures and three skips. The range-count regression passed on isolated rerun. The remaining `test_breakdown_contributions_reconstruct_scores` failure uses an adjustment dated from the current date (October 1, 2026, Q4) while its assertion expects Q3. This date-sensitive test failure is not evidence about the aggregate change, and the full suite remains unverified.

### Current target status and next optimizations

Home's badge/count and collapsed-list changes were applied after the first candidate capture. A later c1 rerun near the end of this report records the updated page readiness, but its one cold/warm pair is not a controlled before/after comparison.
Home's own-potential table also now uses the aggregate-only summary route; the full endpoint remains available to detail views. The later c1 run includes this summary route, but does not isolate its cost against the earlier `/api/potential` request.

| Area | Proposed target | Follow-up status | Next work |
|---|---|---|---|
| Transparency | First summary and first 50 rows under 2 s | Not met: page ~42.6 s; main endpoint ~41 s | Replace per-request full projection/fingerprint with a bounded incremental projection or filter-bound snapshot. Define complete invalidation across assignments, exemptions, duty types, and hierarchy; instrument Python projection, hashing, SQL, and serialization. |
| Home | Runner page-ready under 2 s without full transparency/history | Not met: latest 5-pair p50/p95 is 12.00/12.55 s cold and 11.58/12.68 s warm; earlier candidate was 12.4–14.4 s. No matched pre-cache baseline. | Build a compact current-soldier summary; move ineligible ranges, alert aggregates, potential, and other widgets off the critical path. Keep authorization and current-duty semantics. |
| Hierarchy and soldier lookup | First roster page under 500 ms; hierarchy under 2 s | Partial: roster 0.75–0.77 s; hierarchy 3.8–4.2 s; soldier cold journey 7.1 s | Keep tree roots/branches and rosters bounded; diagnose 21-query hierarchy branch work and shared-shell requests. Add a phase trace for the soldier modal and repair the warm-reopen profiler interaction. |
| Calendar | Visible-window API under 500 ms; page under 2 s | Not met: shifts 4.2–4.4 s; whole page 6.3–6.9 s | Query only the visible date window and remove the 202-statement shifts fanout. Profile the 158-statement ranges request and split SQL, Python, and response serialization time. Repair the synthetic-team selector trace. |
| HR and shared shell | Readiness tracks HR routes; nonessential counters are deferred | Not met: HR routes p95 below 0.78 s, page p95 4.56–5.14 s | Defer shell counters until primary page content is ready; batch only semantically compatible counts and preserve per-counter authorization/error behavior. Optimize the 31-statement ineligible count and slow algorithm/transfer counters. |

The user-facing page times still exceed the proposed targets. The requested concurrency-5/10 runs are deferred until the single-user bottlenecks are addressed. Follow-up work also remains to collect five samples for each affected route, capture `EXPLAIN (ANALYZE, BUFFERS)` for the top SQL-heavy paths, and separate server CPU/serialization from database and browser time. The immutable original results remain in [scale-20k-pages.json](data/scale-20k-pages.json); candidate follow-up artifacts are [HR n=5](data/scale-20k-pages-run-20261001T171011566Z-41968-63e6d510.json) and [single-pair routes](data/scale-20k-pages-run-20261001T171223051Z-44428-cb7f3040.json).

### Plans by layer

#### Transparency

- **UI:** keep the first response to the visible summary and first bounded row slice; fetch fairness/detail data only when its section is opened; keep the table virtualized and exports server-side and complete. Continue to include authorization scope in query keys and cursor bindings.
- **API/service:** first make the existing calculation cheaper without changing its global ordering or normalization: aggregate quarter projection rows in SQL instead of hydrating full ORM rows with JSON fingerprints, reuse readiness and calculation inputs within one request, and build viewer-scope visibility once. Validate cursor signature, purpose, expiry, and request binding before expensive row calculation. Measure each change independently.
- **Data correctness:** a persisted continuation snapshot is a later stage. It must bind the ordered, redacted rows and summary to user, full authorization scope, filters, locale rank order, sort, calculation version, effective date, and a complete data revision. Expiry alone is not invalidation. The revision must cover assignments/overrides/dismissals/adjustments, exemptions and mappings, duty types, soldier scoring inputs, hierarchy and grants, settings, projection repairs, and clock boundaries.
- **Blockers before snapshots:** source inspection found score-affecting mutations in duty-type and settings paths without projection refresh. Projection-read repairs may also roll back when the read session closes; their contribution to the 609 statements has not been profiled. Resolve these freshness paths before a snapshot can be considered correct. Never add a route-wide `session.commit()` to hide the issue.

#### Home and shared navigation

- **UI:** show the current soldier's primary panel as soon as its required data is ready. Load alert lists, potential, range summaries, and navigation badges independently after that point, with local loading/error/retry states. Keep virtualized range continuation seamless and preserve selected IDs across appended pages only.
- **API/service:** define a compact, authorization-scoped Home summary with current-duty and personal score fields plus only bounded visible aggregates. Keep full history and organization-wide projections off this path. Split the ineligible-soldier count from detail construction if its semantics permit it; profile the 17-statement command-alert route and the 58-statement potential route separately.
- **Database/operations:** identify the 31-statement count path and repeated eligibility reads before changing indexes. The `potential` route has only 66–73 ms accumulated SQL against 4.4–5.2 seconds wall time, so time its Python calculation and serialization explicitly. Recheck the Loki-backed admin-error counter as an expected local 503; do not turn it into an empty success response.

#### Hierarchy and individual soldier

- **UI:** keep root and child branches lazy, with node-local loading/retry and scoped branch caches. Fetch the selected node's soldier roster by cursor, append rows before the viewport reaches its tail, and keep tree expansion independent from roster paging. Individual lookup should open from a focused name/result rather than preload a full roster.
- **API/service:** retain stable bounded root/child ordering and focused detail reads; preserve authorization checks for each branch and soldier. The current roster first slice is 0.75–0.77 seconds and seven SQL statements, so it still misses the proposed 500 ms API target. The observed 3.8–4.2 second hierarchy route includes shared-shell calls; separate first tree paint from network-idle readiness before attributing that whole duration to the tree.
- **Verification:** repair the profiler's warm soldier-modal interaction and record team page, filter, selected-row, and modal phases even when one phase times out.

#### Calendar

- **UI:** request only the currently visible date window, deduplicate overlapping windows, and reuse data only for a matching node/date scope. Keep the current calendar responsive while slower secondary data loads; virtualize events only if the updated browser trace shows rendering cost.
- **API/service:** retain authorization and inclusive/exclusive date behavior while eliminating the measured query fanout from shifts and ranges. Return only fields needed by visible events, and fetch edit-only details when a user opens an event.
- **Database/operations:** capture actual SQL shapes and `EXPLAIN (ANALYZE, BUFFERS)` for the 202-statement shifts path and 158-statement ranges path before changing indexes. Separately time ORM processing, eligibility/problem enrichment, serialization, and browser long tasks. Repair the synthetic-team profiler selector before treating its timeout as calendar latency.

#### HR and capacity

- **UI:** keep provider sync distinct from read-only local HR review; let the HR content become ready before nonessential shared-shell counters finish.
- **API/service:** preserve the measured HR endpoints (two or three statements each) and defer/aggregate compatible shell counts only when their authorization and error behavior match. Do not invoke an external provider for this benchmark.
- **Capacity:** repeat single-client samples for affected routes after fixes. Only then run 5- and 10-client batches, capture SQL plans, and tune worker/pool settings from the measured bottleneck. The present c1 data does not establish production concurrency capacity.

## Original baseline page measurements

| Workload | Cold ready | Warm ready | Captured API requests, cold/warm | Browser long tasks, cold/warm |
|---|---:|---:|---:|---|
| Transparency, whole organization | 317.4 s | 323.1 s | 137 / 101 | 28 tasks, 193.7 s total, 17.4 s max / 0 |
| Home dashboard | 129.9 s | 143.5 s | 130 / 86 | 1 task, 83 ms total / 2 tasks, 227 ms total, 150 ms max |
| Hierarchy, whole organization | 77.4 s | 64.6 s | 100 / 56 | 4 tasks, 16.8 s total, 10.7 s max / 1 task, 5.6 s |
| Soldier detail, roster search then modal | 91.1 s | 9.3 s | 111 / 5 | 12 tasks, 31.5 s total, 10.6 s max / 3 tasks, 7.9 s total |
| Calendar, whole organization | 8.1 s | 7.9 s | 91 / 43 | 1 task, 127 ms / 0 |
| Calendar, synthetic team | 8.8 s | 9.8 s | 94 / 46 | 1 task, 53 ms / 1 task, 64 ms |
| HR sync review | 7.0 s | 5.8 s | 86 / 38 | 0 / 0 |

“Captured API requests” includes attempted requests that were later aborted and had no HTTP status. It is not a count of successful responses.

The soldier-detail phases were: team page ready 57.7 s, synthetic-soldier filter 25.9 s, and modal ready 7.5 s on the cold path; reopening the modal took 9.3 s warm. This shows that loading and searching the roster dominate the cold individual-soldier journey; the individual detail and score calls were much shorter on the warm path.

## Original baseline slow API evidence

| Endpoint or route group | Observed result | SQL count and SQL time | Response bytes |
|---|---|---|---:|
| GET /api/soldiers | 56.6–76.2 s | 40,237; 39.2–53.2 s | 18,570,635 |
| GET /api/assignments/effective | 70.1–75.7 s; returned an empty array | 4; 28.1–29.4 s | 2 |
| GET /api/scoring/transparency | 122.8–267.8 s | 605; cold sample 82.6 s | 14,411,892 |
| GET /api/scoring/fairness-components | 83.6–315.0 s across successful calls; repeated 2–3 times per transparency visit | 30 per call; 43.5–163.0 s | 3,710,319 |
| GET /api/scoring/soldiers/:id/burden-share on home | 104.5–105.7 s | 29; 68.4–70.0 s | 162 |
| GET /api/calendar/shifts | 3.9–7.1 s | 75; 0.28–1.13 s | 24,194 |

The HR-specific routes were materially faster: divergences 0.24–0.51 s, rank conflicts 0.31–0.58 s, runs 0.32–0.61 s, vanished 0.24–0.67 s, and held-for-review 0.20–0.67 s. They used two or three SQL statements each and returned at most about 25 KB. The shared navigation request for GET /api/ranges/ineligible-soldiers/count took 3.3–5.5 s and issued 31 statements, which is a more plausible contributor to the HR page’s total readiness than the HR review endpoints themselves.

The local profile also recorded GET /api/settings/public as 401, GET /api/hakpaza/pending-count as 403, and GET /api/admin/errors/unread-count as 503. The latter is expected in this environment because Loki is not configured. These shared-shell responses are environment/authorization results, not evidence that the HR page failed. Unstated or blank request statuses are treated as aborted or unclassified, not server errors.

## Findings and ranked optimization plan

### 1. Filter effective duty history before loading and expanding it

GET /api/assignments/effective returned no rows for the requested soldier, yet took 70–76 seconds. The route accepts a soldier ID and optional date bounds in [assignments.py](../../backend/app/routes/assignments.py#L135). Its service helper currently selects all published assignments, then expands each assignment day-by-day, and only later filters the generated spans by soldier ID and date in [scoring.py](../../backend/app/services/scoring.py#L120). That source shape matches the observed empty-but-slow request.

**Backend change:** apply soldier, status, and date-overlap predicates in the assignment query before materializing records. Load only overrides and dismissal ranges for the selected assignments, and avoid expanding days outside the requested window. Preserve effective-owner and dismissal semantics.

**Database change:** inspect EXPLAIN (ANALYZE, BUFFERS) for the scoped query, then add or adjust indexes only where the plan shows benefit. Candidate predicates include status, soldier ID, and date overlap; do not add an index based on the page timing alone.

**Verification:** a one-soldier request with no matching duties should return in under 500 ms and its row count and SQL work must not grow with the total assignment count. Also compare results for override, dismissal, date-boundary, and multi-day cases.

### 2. Replace the full roster response with a paged roster contract

The hierarchy and cold soldier workflow both load GET /api/soldiers. It returned 18.6 MB and issued 40,237 SQL statements at 20,000 soldiers. The current list route loads all soldiers and builds an output object for every row in [soldiers.py](../../backend/app/routes/soldiers.py#L446). The hierarchy page remains slow on a warm revisit because it still spends over a minute in that request.

**Backend/API change:** add a roster-specific response with cursor or page-size pagination, server-side search/sort, and only the fields needed for the visible rows. Keep full private/profile details behind the individual soldier endpoint. Profile SQL statement fingerprints without personal data to identify the remaining per-row query work, then batch any uncached authorization or lookup work.

**UI change:** render the first page promptly, virtualize or page the table, debounce search, and fetch the next page on demand. Avoid loading every soldier merely to locate one soldier before opening their detail view.

**Verification:** first roster page of 50–100 records under 500 ms API p95 and under 2 seconds to interactive hierarchy view; query count should stay bounded as the total roster grows. Recheck search, visibility, and authorization behavior with page boundaries.

### 3. Split transparency overview, row data, and fairness details

Transparency returned 14.4 MB with 605 SQL statements, and fairness-components returned 3.7 MB while taking up to 315 seconds per call. Two or three successful fairness-components responses appeared during a single page visit. The cold browser sample also had 28 long tasks totaling 193.7 seconds, with a longest task of 17.4 seconds. This workload is expensive in both the server/API path and the browser.

**UI/API change:** make the first response an aggregate summary and a bounded first page of rows. Fetch fairness details when their section is opened, deduplicate identical in-flight queries, and avoid rendering/parsing all rows at once. Use a virtualized table and move nonurgent chart/export transformations off the main thread where useful.

**Backend change:** verify whether the transparency read used the projection path or fell back to legacy computation during this run; the projection backfill is complete, but the benchmark did not record that branch choice. Batch remaining per-soldier reads and use versioned cached or incrementally maintained aggregates for stable fairness results. Invalidate on assignment, exemption, duty-type, or hierarchy changes.

**Verification:** first visible summary and first 50 rows under 2 seconds, no multi-second browser long tasks, and one fairness request per active view. Track response size, SQL count, SQL time, and Python/serialization time separately.

### 4. Give the home dashboard summary-specific data

The home page took 130–143 seconds despite almost no browser long-task time. It requested the full transparency response, individual burden share, and effective assignments. The home component currently uses the transparency query to derive its own-row and aggregate values in [HomePage.tsx](../../frontend/src/pages/HomePage.tsx#L212). The effective-assignment request is the all-history expansion described in finding 1.

**UI/API change:** add a dashboard summary endpoint containing the current soldier’s values and only the aggregate counts/averages displayed on the page. Do not fetch the entire organization’s transparency rows for a dashboard card. Load secondary widgets after the main dashboard is interactive.

**Verification:** home summary under 500 ms API p95 and dashboard interactive under 2 seconds, with no full-roster or full-transparency response on the critical path.

### 5. Reduce shared-shell fanout and inspect calendar request time outside SQL

The HR-specific endpoints finish within 0.7 seconds, while shared navigation requests include slower counters. Across page visits the runner saw 38–137 attempted API calls. On calendars, the shifts endpoint took 3.9–7.1 seconds even though accumulated SQL time was 0.28–1.13 seconds and browser long tasks were tiny. This points to time outside measured SQL—such as synchronous processing, serialization, or server request contention—rather than a demonstrated slow index.

**UI change:** aggregate compatible navigation counts, deduplicate shared queries, and defer low-priority badges until after the page’s core content is ready. For calendars, request only the visible date range and avoid refetching unchanged whole-organization data when scope changes do not require it.

**Backend/operations change:** profile calendar route CPU and response serialization separately from SQL. Capture concurrent request timing before raising worker or connection-pool limits; this single-process local run is not a production concurrency test.

**Verification:** HR page readiness should track the HR endpoints rather than unrelated badges; calendar API p95 under 500 ms and page interactive under 2 seconds for both whole-organization and team scopes.

## Follow-up benchmark

Run at least five cold/warm pairs per workload in the target-like environment, then report p50/p95. Add 1, 5, and 10 concurrent browser/API clients after the single-user bottlenecks are addressed. Capture LCP/INP and API timing phases, and capture EXPLAIN (ANALYZE, BUFFERS) for the top database-heavy routes. The current results are a single local diagnostic pass and must not be presented as production latency or p95.

The 2-second page and 500-ms API goals above are proposed follow-up targets, not achieved results.

## Later c1 rerun (2026-10-01)

The later artifact [scale-20k-pages-run-20261001T193118152Z-53024-f983ac69.json](data/scale-20k-pages-run-20261001T193118152Z-53024-f983ac69.json) was generated at `2026-10-01T19:31:18.151Z`. It contains one cold/warm pair for each of seven workloads (14 measurements), with concurrency 1 and one client. These are individual diagnostic samples, not percentiles, a controlled before/after comparison, or evidence about concurrent load. Earlier captures above are retained as separate observations.

| Workload | Cold result | Warm result | API requests, cold/warm |
|---|---:|---:|---:|
| HR sync review | ready 4,114.96 ms | ready 3,664.15 ms | 27 / 27 |
| Transparency, whole organization | ready 14,512.57 ms | ready 15,230.49 ms | 26 / 26 |
| Hierarchy, whole organization | ready 4,246.97 ms | ready 3,432.45 ms | 26 / 27 |
| Soldier detail | ready 5,369.92 ms | **failed timeout after 120,063.93 ms; no ready time** | 34 / 31 |
| Calendar, whole organization | ready 5,291.81 ms | ready 5,346.49 ms | 29 / 29 |
| Calendar, synthetic team | **failed timeout after 35,811.80 ms; no ready time** | **failed timeout after 36,009.16 ms; no ready time** | 35 / 35 |
| Home dashboard | ready 12,973.98 ms | ready 11,857.28 ms | 52 / 52 |

The timeout elapsed values above record failed waits, not page latencies. In particular, this run does not establish a warm soldier-detail readiness time or a synthetic-team calendar readiness time.

### Slow API evidence from this run

API wall time is shown separately from accumulated SQL time. Accumulated SQL time explains only the instrumented database portion; the remaining wall time is not attributed here to Python, serialization, queueing, or any other single phase.

| Page context and route | API wall time, cold / warm | SQL statements, cold / warm | Accumulated SQL time, cold / warm | Response bytes |
|---|---:|---:|---:|---:|
| Transparency: `GET /api/scoring/transparency/page` | 12,870.08 / 14,024.77 ms | 611 / 611 | 5,941.91 / 6,346.85 ms | 72,974 |
| Home: `GET /api/potential/summary` | 9,548.87 / 9,625.36 ms | 51 / 51 | 1,417.86 / 1,126.90 ms | 137 |
| Home: `GET /api/ranges` | 9,636.20 / 9,685.84 ms | 158 / 158 | 4,263.65 / 3,656.16 ms | 8,023 |
| Home: `GET /api/calendar/shifts` | 8,237.59 / 8,647.08 ms | 34 / 34 | 1,949.47 / 1,631.28 ms | 94,570 |
| Home: `GET /api/command-dashboard/alerts` | 6,233.68 / 4,500.72 ms | 17 / 17 | 5,164.48 / 3,091.02 ms | 175 |
| Home: `GET /api/command-dashboard/potential` | 3,529.10 / 6,160.47 ms | 14 / 14 | 2,685.71 / 5,273.18 ms | 281 |
| Home: `GET /api/command-dashboard/upcoming` | 4,127.35 / 6,160.57 ms | 18 / 18 | 3,282.50 / 4,589.65 ms | 32,026 |
| Whole calendar: `GET /api/ranges` | 1,913.31 / 3,261.18 ms | 158 / 158 | 1,724.90 / 3,146.43 ms | 8,023 |
| Whole calendar: `GET /api/calendar/shifts` | 3,739.15 / 1,949.68 ms | 34 / 34 | 791.30 / 1,102.86 ms | 94,570 |
| Synthetic-team calendar: `GET /api/ranges` | 3,061.71 / 3,191.33 ms | 158 / 158 | 2,940.09 / 3,087.19 ms | 8,023 |
| Synthetic-team calendar: `GET /api/calendar/shifts` | 1,588.67 / 1,730.71 ms | 34 / 34 | 874.86 / 1,003.86 ms | 94,570 |
| Hierarchy: `GET /api/soldiers/roster` | 159.93 / 81.41 ms | 7 / 7 | 62.73 / 29.13 ms | 34,646 |

`GET /api/ranges/ineligible-soldiers/count` still appeared in the shared shell: HR took 2,306.62 / 2,242.49 ms (17 SQL each; 1,119.62 / 1,006.02 ms accumulated SQL). Home recorded two count responses in each visit: cold 4,836.18 and 6,843.95 ms, warm 3,926.63 and 5,299.87 ms. Each returned HTTP 200 with 17 SQL statements and 11 bytes; their accumulated SQL times were respectively 3,246.31 / 5,584.10 ms cold and 2,520.74 / 4,000.83 ms warm.

The soldier-detail cold journey reached its ready marker, but the trace also contains a later `GET /api/soldiers/roster` response with HTTP 500 (221.48 ms, two SQL statements, 21 bytes); the first roster response was HTTP 200 (72.03 ms, seven SQL statements, 34,646 bytes). This route error is recorded separately from the successful cold page readiness. The synthetic-team calendar's measured `/api/ranges` and `/api/calendar/shifts` calls returned HTTP 200, but both page journeys still failed their readiness wait.

The Home sample includes the new summary route, but its 9.55 / 9.63 second wall time does not establish whether the aggregate-only implementation improved cost: the earlier 4.38 / 5.16 second observation used `/api/potential`, and the route, code state, and run differ. That earlier c1 pair measured 11.86 / 12.97 seconds page-ready and predates the service-level eligibility-helper change below; a later five-pair post-potential-cache Home capture follows. There is no matching five-pair pre-change baseline, so no Home improvement is claimed.

### Service-level eligibility-helper follow-up (2026-10-01)

Four sequential direct service runs used the same isolated database, largest/root subtree (20,116 soldiers), reference date `2026-10-01`, query/session setup, and eligibility inputs. The order was legacy, cached, cached, legacy; the eligibility helper was the only changed variable.

| Service variant | Two-run median wall time | `DutyTypeRequirements.model_validate` calls | Aggregate result in both runs |
|---|---:|---:|---|
| Legacy helper | 2.222 s | 241,404 (12 request preparse + 241,392 per-soldier) | raw eligible 115; modifiers 0; final 115 |
| Cached helper | 0.867 s | 12 | raw eligible 115; modifiers 0; final 115 |

This is a service-level two-sample median comparison, not HTTP timing or page p50/p95. A separate direct cProfile capture on the same database, subtree, date, and aggregate output recorded 5.682 s, 241,392 validations, and 9,561,781 calls before the change, versus 1.624 s, 12 validations, and 2,620,734 calls after it. Those single-run cProfile timings are kept separate from the sequential A/B medians because they are a different measurement method.

At the time of the service A/B, no Home browser profile had run after the eligibility-helper change. The later post-potential-cache Home capture below provides page and route measurements, but has no matching five-pair pre-change baseline. The direct service A/B therefore remains separate evidence and does not establish its effect on API wall time or Home readiness.

### Post-potential-cache Home browser capture (2026-10-01)

The [Home run artifact](data/scale-20k-pages-run-20261001T195809161Z-58112-83cef81f.json) was generated at `2026-10-01T19:58:09.160Z`. It contains five cold and five warm Home page samples at concurrency 1; all 10 reached the ready marker. These n=5 percentiles describe this single local run. They are not a matched before/after comparison or evidence about concurrent load.

The runner's `pageReadyMs` is measured from before the Home scenario action until the final API-quiescence check in `recordMeasurement`. The scenario readiness helper first waits for its configured selectors to be visible and for tracked API requests to settle; quiescence requires no active or pending tracked requests and at least 500 ms without tracked API activity. `recordMeasurement` waits for quiescence again before stopping the timer. The runner does not record the selector-visible-to-API-idle gap separately, so these are selector-visible-plus-API-idle readiness measurements, not true time-to-first-content.

For custom soldier-detail flows, selector-visible marks when the soldier modal appears. For synthetic-team calendar, it marks when the unit-search combobox reflects the selected hierarchy path; the runner then waits for the matching `/api/calendar/shifts?node_id=...` response and API quiescence before recording API-quiet. This selector milestone does not mean calendar events have rendered. Both elapsed values use the same scenario start time.

| Home metric | Cold p50 / p95 | Warm p50 / p95 |
|---|---:|---:|
| Page ready | 12,000.14 / 12,553.24 ms | 11,578.22 / 12,677.97 ms |
| API requests per page | 52 / 52 | 52 / 52 |
| Aggregate response bytes | 344,609 / 344,609 | 344,609 / 344,609 |
| Aggregate SQL statements | 545 / 545 | 545 / 545 |
| Accumulated DB time | 37,831.14 / 39,848.49 ms | 37,495.38 / 39,860.81 ms |
| Browser long tasks: count / total / max | 5 / 507 / 149 ms | 3 / 243 / 110 ms |

The database time is summed across measured API requests and can exceed the page-ready duration when requests overlap; it is not the page's serial critical-path duration. The proposed two-second Home readiness target remains unmet.

| Home route | Cold wall p50 / p95 | Warm wall p50 / p95 | SQL statements p50 / p95 | Accumulated DB p50 / p95, cold / warm | Response bytes p50 / p95 |
|---|---:|---:|---:|---:|---:|
| `GET /api/potential/summary` | 8,584.61 / 9,584.43 ms | 9,091.79 / 10,139.09 ms | 51 | 2,056.76 / 3,490.82; 2,622.83 / 3,075.03 ms | 137 |
| `GET /api/command-dashboard/alerts` | 6,616.65 / 7,524.82 ms | 4,932.46 / 7,644.06 ms | 17 | 4,598.79 / 6,145.19; 3,712.02 / 6,003.34 ms | 175 |
| `GET /api/ranges/ineligible-soldiers/count` | 4,710.10 / 9,445.91 ms | 5,209.82 / 9,064.55 ms | 17 | 2,724.41 / 7,689.04; 3,471.84 / 7,419.16 ms | 11 |

The count-route summary contains 10 responses in each phase (two per page visit), with the cold and warm groups reported separately. The summary route remains about 9.1 seconds at warm p50 despite the direct service A/B; service timing and API/page timing are different measurements, and this capture does not isolate the route's remaining wall time. There is no matching five-pair pre-cache Home profile, so no page improvement is attributed to the cache change. The temporary profiler authorization and scope changes were restored after the run; no identity values are included here.

### Home selector and API-idle readiness split (2026-10-01)

The [readiness split artifact](data/scale-20k-home-readiness-run-20261001T201031346Z-60684.json) is a separate n=1 diagnostic at concurrency 1. Measured from the scenario start, the `personal-data-panel` and `panel-alerts` selectors became visible at 1,346.56 ms cold and 1,313.53 ms warm. The API-quiet timestamps were 11,395.07 ms cold and 12,372.72 ms warm; each journey recorded 52 API responses.

Selector visibility and API-idle are separate elapsed observations whose work overlaps. Do not add them as serial costs or interpret API-idle as first useful content. The artifact does not capture the selector-to-idle gap separately, and this n=1 diagnostic is not a replacement for the five-pair page profile.

### Alerts route source diagnosis

In the separate five-pair Home profile, `GET /api/command-dashboard/alerts` had wall p50 6,616.65 ms cold / 4,932.46 ms warm, 17 SQL statements, accumulated DB p50 4,598.79 / 3,712.02 ms, and a 175-byte response. These route measurements are not a page-readiness split, and overlapping request wall times are not additive page costs.

Source tracing shows the alerts route first resolves the commander's authorized roots and subtree in `backend/app/routes/commander_dashboard.py`. `backend/app/services/commander_dashboard.py` loads every active soldier in that subtree, requests score totals for that complete soldier list, normalizes each score, and checks expiring exemptions before returning alerts. The small response body therefore does not imply a small source workload. `commander_score_totals` branches on the database setting `scoring.commander_dashboard_projection_reads_enabled`: with the gate off it runs broad aggregate score totals; with the gate on it checks projection state and keys, handles incomplete or dirty buckets, and may repair or fall back to canonical totals. The isolated scale database had no row for this setting, and the code defaults the gate to false, so this request used the legacy aggregate path. This identifies the selected path but does not prove that it explains the full measured latency; there is no route-phase attribution.

A separate `EXPLAIN (ANALYZE, BUFFERS)` run for the same commander aggregate query shape over 20,116 active soldiers and the 1M-assignment scale dataset completed in 558.27 ms (49.42 ms planning) and produced 20,116 totals. The plan used a parallel sequential scan and aggregate over `duty_assignments`, with about 32,006 shared-read blocks and temporary I/O (178 blocks read, 405 written). This is one direct database run outside Home request concurrency. It is plan evidence for one aggregate query, not an explanation for the alerts route's 3.71-4.60 seconds of accumulated DB time across 17 statements; additional query work or concurrent database activity remains unverified.

### Five-pair navigation readiness capture (2026-10-01)

The [navigation artifact](data/scale-20k-pages-run-20261001T202722666Z-59880-b3af9269.json) was generated at `2026-10-01T20:27:22.662Z`. It contains five cold and five warm samples each for HR sync, transparency, hierarchy, whole-organization calendar, and Home at concurrency 1; all 50 measurements reached their ready milestone. This is a single-user diagnostic. It used an admin authorization scope, which differs from the earlier commander-scope Home runs; these measurements are not a before/after comparison and do not support an improvement claim.

Selector-visible and API-quiet are separate elapsed timestamps from the same measurement start. Their work overlaps, so they are not additive. API-quiet records when tracked API requests have settled and remained quiet for 500 ms; it is not first useful content. In the custom soldier-detail flow selector-visible marks the modal, and in synthetic-team calendar it marks the selected path in the unit-search combobox. The team-calendar flow also awaits the `/api/calendar/shifts` response whose `node_id` matches that option before API-quiet is recorded; selector visibility itself does not establish that events rendered.

| Page | Selector-visible cold p50 / p95 | Selector-visible warm p50 / p95 | API-quiet cold p50 / p95 | API-quiet warm p50 / p95 |
|---|---:|---:|---:|---:|
| HR sync | 867.08 / 936.99 ms | 517.25 / 605.71 ms | 4,127.67 / 4,260.44 ms | 3,544.85 / 3,951.72 ms |
| Transparency | 958.30 / 1,044.20 ms | 581.46 / 664.24 ms | 14,472.86 / 19,439.33 ms | 14,421.51 / 16,780.56 ms |
| Hierarchy | 992.15 / 1,062.91 ms | 599.48 / 767.08 ms | 4,209.17 / 4,525.59 ms | 3,843.85 / 4,175.90 ms |
| Whole-organization calendar | 1,237.42 / 1,300.33 ms | 801.94 / 884.54 ms | 5,642.98 / 6,242.58 ms | 5,116.67 / 5,977.12 ms |
| Home | 2,344.82 / 2,760.53 ms | 1,910.80 / 2,404.28 ms | 10,901.53 / 15,181.17 ms | 10,576.03 / 11,779.58 ms |

Route evidence from the same run:

| Page / route | Cold wall p50 / p95 | Warm wall p50 / p95 | SQL statements p50 | Accumulated DB time p50, cold / warm |
|---|---:|---:|---:|---:|
| Transparency: `GET /api/scoring/transparency/page` | 12,977.27 / 17,852.65 ms | 13,292.98 / 15,706.56 ms | 611 | 5,676.65 / 5,418.63 ms |
| Hierarchy first roster page: `GET /api/soldiers/roster` | 132.44 / 145.45 ms | 109.33 / 133.09 ms | 7 | 57.72 / 39.93 ms |
| Whole calendar: `GET /api/ranges` | 3,512.02 / 3,720.13 ms | 3,633.16 / 4,473.31 ms | 158 | 3,279.17 / 3,513.31 ms |
| Whole calendar: `GET /api/calendar/shifts` | 1,550.78 / 1,625.22 ms | 1,326.60 / 2,778.99 ms | 34 | 548.73 / 566.06 ms |
| Home: `GET /api/command-dashboard/alerts` | 6,678.28 / 9,486.60 ms | 6,946.77 / 8,554.64 ms | 17 | 3,554.53 / 4,416.97 ms |
| Home: `GET /api/potential/summary` | 5,569.31 / 8,912.50 ms | 6,213.09 / 7,044.77 ms | 51 | 758.52 / 203.23 ms |

On the whole-calendar page, the shared-shell ineligible-count endpoint had p50 3,655.77 ms cold / 3,635.07 ms warm (17 SQL statements). Route wall times and accumulated DB times describe different measurements; requests can overlap. Because the authorization scope differs from prior commander runs and there is no matched baseline, these values are descriptive only.

### Custom soldier-detail and synthetic-team diagnostic (2026-10-01)

The [custom journey artifact](data/scale-20k-pages-run-20261001T204134539Z-60244-47e7b5b5.json) was generated at `2026-10-01T20:41:34.534Z`. It is a single cold/warm pair at concurrency 1 under admin authorization scope, for diagnosis only; it is not an SLO measurement or a before/after comparison.

Soldier detail reached its cold ready marker in 5,493.03 ms: the team page took 4,131.44 ms, filtering took 48.25 ms, and opening the modal took 1,313.19 ms. Selector-visible was 5,125.44 ms and API-quiet was 5,492.95 ms. The trace contains two `/api/soldiers/roster` responses: HTTP 500 in 233.41 ms and HTTP 200 in 145.40 ms. The artifact's response list records the 200 before the 500; the cause was still unresolved at capture time and is described in the follow-up below. The warm soldier-detail journey timed out after 60,165.41 ms before either selector-visible or API-quiet was recorded. That failed wait is not a latency measurement.

Synthetic-team calendar reached its cold/warm ready markers in 7,154.55 / 6,786.99 ms. Team-scope selection took 1,873.92 / 1,832.96 ms; the selected-path selector milestones were 6,569.49 / 6,186.26 ms and API-quiet was 7,154.28 / 6,786.96 ms after the matching team-shifts response and global quiescence. This is n=1 per phase and remains a single admin-scope diagnostic, not an SLO or before/after result.

### Roster-search failure diagnosis and focused recheck (2026-10-01)

Direct reproduction confirmed the `/api/soldiers/roster` failure as a SQLAlchemy `InvalidRequestError` from auto-correlation in the page SELECT at `backend/app/routes/soldiers.py:712`. It occurs when search or `sort=node` outer-joins `HierarchyNode`, while the commander `EXISTS` and commander-node-name subqueries also reference that table. The focused fix adds `.correlate(Soldier)` to both subqueries, preventing the outer join from being mistaken for their correlation source; independent review was CLEAN. A direct route check after the fix returned one matching search result, and `sort=node` returned 100 rows with a continuation cursor.

The [recheck artifact](data/scale-20k-pages-run-20261001T210947290Z-54176-6f255d57.json) was generated at `2026-10-01T21:09:47.289Z`. It is one cold/warm pair at concurrency 1 under admin authorization scope. Cold soldier detail reached ready at 5,369.92 ms (team page 3,926.64 ms, filter 32.83 ms, modal 1,410.30 ms); selector-visible was 4,409.27 ms and API-quiet 5,369.81 ms. Its two roster responses were HTTP 200: 137.20 ms (7 SQL, 77.88 ms DB, 34,638 bytes) and 115.71 ms (7 SQL, 61.32 ms DB, 390 bytes). Warm soldier detail reached ready at 1,018.51 ms (selector-visible 960.32 ms; API-quiet 1,018.46 ms) and made no roster refetch.

Compared with the prior n=1 admin-scope diagnostic, the cold capture is a single observation with the prior roster error absent, and the warm journey reached readiness instead of timing out. These two isolated runs do not support a latency-improvement claim or SLO conclusion. Profiler credentials are absent from the current environment and are not recorded in the artifact or report.

### Calendar range-read batching implementation (2026-10-02)

The five-pair admin-scope capture above identifies the whole-calendar GET /api/ranges request as a high-cost path: 158 SQL statements per request, with cold/warm p50 wall times of 3,512/3,633 ms and accumulated DB times of 3,279/3,513 ms. The UnitCalendar caller supplies the visible date window. This is the baseline evidence, not a post-change measurement.

The shared serializer in backend/app/routes/ranges.py now batch-loads assignments, hierarchy nodes, and range locations for both GET /ranges and GET /ranges/page. It also supports a batched soldier lookup when food summaries are requested; current list/page behavior still omits food summaries and assignment details as before. Draft filtering, confirmed fill counts, assigned-to-me, response order, missing-row fallbacks, and existing authorization calls are preserved. When the route-level manage gate is true for an admin, per-event can-manage resolves directly to true; non-admin checks and false manage gates are unchanged. Independent static review was CLEAN, and git diff --check for the route passed.

No post-change profile, tests, or compilation were run. The environment currently lacks the profiler login inputs, so no latency improvement is claimed. Per-event authorization reads for non-admins remain a possible source of query fanout.

## 2026-10-02 pre-index full 20k page concurrency profile

These [c1](data/scale-20k-pages-run-20261002T055914458Z-31736-96c901ce.json), [c5](data/scale-20k-pages-run-20261002T060644315Z-14120-3e8a736d.json), and [c10](data/scale-20k-pages-run-20261002T061233794Z-50584-6ae3a85b.json) artifacts were collected against the isolated seeded PostgreSQL database (20,121 soldiers and about 1,000,008 assignments) with Chromium 148.0.7778.96 and a temporary admin authorization scope. The c1 invocation ran five independent cold/warm pairs. The c5 and c10 invocations ran one simultaneous batch of five or ten independent clients for each cold/warm mode; p50/p95 within those batches are descriptive snapshots, not repeated-batch capacity percentiles. All 70/70 c1, 70/70 c5, and 140/140 c10 measurements reached the configured ready marker. HR review remained local and read-only; no provider sync was invoked. These remain useful as a pre-index full-page contention baseline, not the latest page profile.

`pageReadyMs` is the scenario elapsed time through selector visibility and 500 ms of tracked API quiet. It is not LCP or proof that every row is painted. The selector milestone is recorded separately; for synthetic-team calendar it confirms the selected hierarchy path, not that the event list has painted. The runner records long tasks, API response bytes, route wall/server time, SQL count and accumulated SQL time. Accumulated SQL can overlap across API requests; server-minus-DB is a residual, not CPU-only time.

| Journey | c1 cold p50/p95 | c1 warm p50/p95 | c5 cold p50/p95 | c5 warm p50/p95 | c10 cold p50/p95 | c10 warm p50/p95 |
|---|---:|---:|---:|---:|---:|---:|
| HR sync review | 2.75/2.91 s | 2.51/2.66 s | 9.65/9.83 s | 9.23/9.36 s | 24.22/25.51 s | 20.22/22.30 s |
| Transparency, whole organization | 15.79/26.47 s | 16.04/16.42 s | 67.53/83.91 s | 46.21/63.44 s | 131.74/181.86 s | 105.58/144.42 s |
| Hierarchy, whole organization | 3.34/3.56 s | 2.97/3.11 s | 10.79/10.92 s | 7.61/7.74 s | 23.04/23.05 s | 20.45/21.89 s |
| Soldier detail, roster search then open | 4.34/4.57 s | 1.20/1.24 s | 13.14/13.16 s | 3.06/3.11 s | 25.76/25.76 s | 4.72/4.82 s |
| Calendar, whole organization | 4.43/6.34 s | 3.77/6.89 s | 20.89/21.14 s | 19.97/20.16 s | 35.57/39.32 s | 31.29/33.84 s |
| Calendar, synthetic team | 5.61/6.67 s | 5.22/5.54 s | 20.06/20.63 s | 20.66/20.89 s | 36.23/38.33 s | 42.15/42.24 s |
| Home dashboard | 6.42/10.71 s | 6.25/7.15 s | 29.50/30.60 s | 23.56/24.79 s | 58.16/58.26 s | 62.16/62.47 s |

The original single-observation cold/warm baseline and this pre-index c1 p50 are compared below as historical context. Differences are descriptive, not controlled A/B effects: the baseline has one sample per mode and was recorded on an earlier application revision.

| Journey | Original baseline cold/warm (n=1) | Pre-index c1 cold/warm p50 (n=5) |
|---|---:|---:|
| HR sync review | 6.98/5.83 s | 2.75/2.51 s |
| Transparency | 317.41/323.10 s | 15.79/16.04 s |
| Hierarchy | 77.41/64.63 s | 3.34/2.97 s |
| Soldier detail | 91.12/9.31 s | 4.34/1.20 s |
| Whole calendar | 8.12/7.94 s | 4.43/3.77 s |
| Synthetic-team calendar | 8.81/9.76 s | 5.61/5.22 s |
| Home dashboard | 129.91/143.46 s | 6.42/6.25 s |

All successful c1 cold page p95s miss the proposed two-second readiness target. Warm soldier-detail p95 is 1.24 s; the other warm page p95s also exceed two seconds. Under c5 and c10, all page medians rise substantially, especially transparency. The latest profile shows the roster API itself is bounded and fast, but it does not make every page ready within the target.

### Current c1 route and browser attribution

Across the c1 journeys, the largest page blockers are server/API work and shared-shell fanout rather than long browser main-thread tasks. The median long-task total is below 200 ms on each journey except whole-calendar, whose median is 195 ms; this does not rule out paint/layout cost, but it does not support a multi-second JavaScript stall as the primary cause.

| Area / route | Current c1 measurement | Interpretation |
|---|---|---|
| Transparency page / `GET /api/scoring/transparency/page` | Page ready 15.79/16.04 s cold/warm p50. Route wall p50/p95: 14.18/24.88 s cold and 14.70/15.09 s warm; 56 SQL statements, 73,873 response bytes, accumulated DB p50 5.19/6.02 s cold/warm, server-minus-DB p50 8.96/8.67 s. | SQL count fell from 609 in the earlier trace to 56, but the page remains the dominant single-user bottleneck. Full projection/filter/sort work still precedes slicing. A separate current query profile is in progress; these page values predate the end-date index change. |
| Hierarchy first roster | `GET /api/soldiers/roster` p50/p95 111/132 ms cold and 121/156 ms warm; 7 SQL statements and about 34.6 KB. Ineligible-count shell route p50 is about 1.2 s. | First roster request meets the proposed 500 ms API target. The remaining 3.34/2.97 s page p50 is mostly outside that roster request; optimize shared shell/page readiness next. |
| Soldier search and detail | Search roster response p50/p95 136/328 ms, 7 SQL, 390 bytes; `/api/soldiers/:id/score` p50/p95 347/466 ms, 27 SQL, 155 bytes. Page ready is 4.34 s cold and 1.20 s warm. | The individual detail APIs are bounded. Cold page latency includes shared navigation and page setup, so a profile of the detail API alone understates the cold user journey. |
| Whole calendar | `GET /api/calendar/shifts` p50/p95 1.81/4.35 s, 34 SQL, 94,570 bytes, accumulated DB p50 696 ms. `GET /api/ranges` p50 is about 116 ms with 17 SQL (the previous 20k trace had 158 SQL and about 3.5 s). | Range serialization now has much lower observed fanout. Calendar shifts remain a multi-second route, with material wall time outside accumulated SQL and a long-tail under the c1 run. Do not attribute the difference to one change without a matched run. |
| Synthetic-team calendar | `GET /api/calendar/shifts` p50 is about 95–102 ms across cold/warm with 16 SQL, but p95 is about 2.0 s and response body is only 13 bytes in the current synthetic-team scenario. | Team-scope API work is usually small in this batch, while the page-ready marker takes 5.2–5.6 s. Inspect the team-selection interaction and readiness path before inferring that event loading is complete. |
| Home | `GET /api/command-dashboard/alerts` p50/p95 3.75/4.52 s, 17 SQL, 175 bytes; `/api/command-dashboard/potential` 3.83/4.59 s, 14 SQL, 281 bytes; `/api/command-dashboard/upcoming` p50 625 ms, 14 SQL, 32,026 bytes. The ineligible-count route is requested twice per page visit; across 20 calls its p50/p95 is 1.78/4.17 s. | The first two compact responses still require seconds of backend work. Shared count calls and dashboard summaries should be traced/optimized separately; their route timings overlap and must not be summed as serial page time. |
| HR review and shared shell | Five HR-specific review routes have cold wall p50s of 48–103 ms (p95 87–250 ms) and warm p50s of 52–129 ms (p95 150–189 ms), with 2–3 SQL statements each. The shared ineligible-count route is about 0.9–1.0 s p50 with 17 SQL; whole-page readiness is 2.5–2.8 s p50. | Local HR data is not the main measured bottleneck. Defer or reduce shared-shell counters and inspect the slower count path; provider synchronization was not tested. `GET /api/admin/errors/unread-count` returned 503 because this isolated profile had no Loki endpoint configured. |

The remaining work is to rerun the transparency browser page after the end-date index, trace/defer costly Home and shared-shell paths, add server-phase attribution where route and SQL times still diverge, and review the remaining full-payload consumers in `RangesPage` and `HierarchyNodePickerModal`. Transparency continuation still computes a whole-population projection before slicing, and range candidate paging still requires a stable global ranking/snapshot contract. These gaps are not concealed by the improved c1 page table.

### Query-plan evidence on the isolated scale database (2026-10-02)

These are single warmed local reads, not page percentiles. The EXPLAIN statements were read-only. The database held 20,121 soldiers, 1,000,008 duty assignments, 258 shifts, 16 range events, and 125 range assignments. The direct route timings exclude the browser's whole-page critical path and can differ materially under concurrent load.

| Query path | Direct read / plan result | What it establishes |
|---|---|---|
| Transparency planning end date: `max(end_date)` over published assignments | Before index: parallel sequential scan, 44,445 shared buffers, 963.428 ms. After the migration: index-only scan using `(status, end_date DESC)`, 4 shared buffers, zero heap fetches, 0.114 ms. A separate post-index direct route sample was 25.43 s with 55 SQL statements and 12.71 s accumulated SQL, versus one earlier 37.67 s / 55 statement / 26.55 s accumulated-SQL sample. | The targeted lookup is now cheap. The two route samples are uncontrolled and do not establish an end-to-end speedup. Remaining post-index SQL costs in the direct profile were grouped quarter score 4.798 s, projection-key enumeration 2.547 s, two bucket-health checks 1.838 s, and two expected-total aggregates 1.435 s. The full projection is still computed before page slicing. The page table above predates this index. |
| Empty effective-duty window: `GET /api/assignments/effective` for `date_from=date_to=2026-10-02` | 6.86 ms direct handler, 1 SQL statement, empty result. The SELECT plan used `ix_duty_assignments_status_end_date`, filtered to zero rows (8 rows removed), 4 shared-hit buffers, 0.084 ms executor time. Override existence is indexed and was not entered for this window. | Meets the proposed 500 ms empty-query target for this one-day window. The old 70–76 s request did not record its date range, so this is not a matched before/after run. |
| Whole-calendar shifts | Direct handler: 1.266 s, 33 SQL statements, 166 shifts. Largest plans: assignment index scan, 5 rows/499 shared hits/1.25 ms plan time; Soldier subtree sequential scan, 20,116 rows/746 hits/7.12 ms. Browser route p50/p95 was 2.34/4.35 s cold and 1.74/4.19 s warm. | The two inspected SELECTs do not account for the route's whole wall time; no single plan explains all 33 statements. |
| Whole-calendar range events | Direct read/serialization path: 37 ms, 15 SQL statements, 16 events. Event scan: 0.082 ms; location primary-key lookup: 0.048 ms. To keep the connection read-only, this diagnostic bypassed only the route's conditional past-event maintenance hook, which otherwise issues an UPDATE even when no rows need changing. Browser route p50 was about 116 ms cold / 107 ms warm with 17 statements. | Read cost is low at this seed size, but only 16 events and 125 assignments were present; the database does not establish large range-event capacity. The direct 37 ms value is not the unmodified full GET handler. |
| Home alerts / commander score totals | Direct alerts handler: 1.769 s, 16 SQL statements, 1 alert. The aggregate plan hashes 20,116 soldiers while scanning all 1,000,008 assignments with three workers, 44,346 shared-read buffers, and temp spill (154 read / 348 written blocks); plan time 425.4 ms. Browser c1 alerts p50 was 3.88 s cold / 3.70 s warm, with accumulated DB p50 1.95/2.02 s. | This is the clearest remaining database-heavy shape. The one plan is only part of the multi-statement request and does not explain the full route wall time. |
| Home potential: `/api/command-dashboard/potential` | Direct handler: 583 ms, 13 SQL statements, 5 cards. Its active-soldier sequential-scan plan returned 20,116 rows in 6.54 ms. Browser c1 route p50 was 3.83/3.85 s cold/warm, with accumulated DB p50 2.54/2.71 s. | Direct and browser timings disagree substantially; request-level attribution, authorization/scope work, and overlapping requests remain to be isolated. The latest page profile called this route, not `/api/potential/summary`. |
| Home/shared-shell ineligible count | Direct handler: 814 ms, 16 SQL statements. The future-duty query used `ix_duty_assignments_hakpaza_next` and returned 8 rows; the active Soldier/Hierarchy join plan returned 20,116 rows in 16.66 ms. Browser c1 HR count p50 was 0.90/0.98 s cold/warm; the calendar-page count was 2.36/2.26 s, reflecting shared-load variance. | Much of the direct count cost is outside the measured SQL plan nodes, including Python eligibility checks. The profile records an additional request-level statement in the browser route. |
| HR held-for-review | Direct route: 49 ms, 1 SQL statement, 100 returned rows. Its plan scanned and sorted 20,000 HR profiles in 4.90 ms. | This does not justify an index by itself. The five HR-specific routes remain much faster than the full HR page and shared-shell requests. |

The effective-duty case meets its target for the measured empty one-day request. Transparency's max-date query is fixed at the DB-plan level. Calendar, Home, and shared-shell traces still need phase instrumentation before proposing additional indexes: their inspected plans do not explain route wall time, and the alert aggregate is the first evidenced follow-up candidate.

## 2026-10-02 post-index profile and comparison

The post-index [c1 artifact](data/scale-20k-pages-run-20261002T065543215Z-63128-1b48733d.json) contains five cold/warm pairs for all seven journeys (70/70 readiness markers). The targeted [c5 artifact](data/scale-20k-pages-run-20261002T070222229Z-46012-f52c2430.json) contains five clients per mode; the targeted [c10 artifact](data/scale-20k-pages-run-20261002T070516840Z-30280-30543f26.json) contains ten clients per mode. These batches followed the end-date index migration and used the same isolated database, Chromium version, and temporary admin profile scope. The temporary profile account was removed afterward; the database was checked at 20,121 soldiers, 1,000,008 assignments, and 16 range events. The c5/c10 captures measure transparency only and are one simultaneous batch per mode.

| Journey | Post-index c1 cold p50/p95 | Post-index c1 warm p50/p95 |
|---|---:|---:|
| HR sync review | 2.83/3.26 s | 2.28/2.52 s |
| Transparency, whole organization | 11.82/13.46 s | 11.17/12.11 s |
| Hierarchy, whole organization | 2.77/2.96 s | 2.53/3.14 s |
| Soldier detail, roster search then open | 3.71/3.94 s | 0.98/1.06 s |
| Calendar, whole organization | 5.27/6.58 s | 3.53/4.52 s |
| Calendar, synthetic team | 6.32/7.12 s | 5.91/6.28 s |
| Home dashboard | 6.92/8.30 s | 6.48/7.12 s |

Only the warm soldier-detail journey meets the proposed two-second page-readiness p95 target in this c1 run. Selector visibility occurs earlier than full readiness for several journeys: transparency is 0.92 s cold/0.52 s warm p50, while its full page readiness is 11.82/11.17 s. Browser long-task totals are low (102 ms cold p50 and zero warm p50), so the remaining transparency wait is in API/server work rather than a sustained main-thread stall.

| Transparency concurrency | Cold page-ready p50/p95 | Warm page-ready p50/p95 | Selector-visible p50/p95 cold/warm | Readiness / API health |
|---|---:|---:|---:|---|
| c1, five repeated pairs | 11.82/13.46 s | 11.17/12.11 s | 0.92/1.03 s; 0.52/0.62 s | 5/5 ready in each mode; no app HTTP 500s |
| c5, one five-client batch | 65.82/87.52 s | 60.80/80.21 s | 3.94/3.96 s; 2.77/2.79 s | 5/5 ready in each mode; admin-errors route returned expected 503 because Loki was not configured |
| c10, one ten-client batch | 92.49/126.57 s | 101.91/149.64 s | 8.82/8.83 s; 4.56/5.07 s | 10/10 ready in each mode, but cold requests included 17 HTTP 500 responses across four shared-shell endpoints |

For context, the earlier pre-index c5 transparency p50 was 67.53 s cold/46.21 s warm, and c10 was 131.74/105.58 s. The new c5/c10 batches are not controlled A/Bs: they followed other code changes and ran later, so the c10 cold difference cannot be assigned to the index. All concurrent page times remain far above the two-second target; c10 readiness is not a healthy-pass result because some shared-shell requests failed.

The c10 backend log records SQLAlchemy `QueuePool` exhaustion at the configured size of 20 connections plus 10 overflow connections, followed by timeouts and HTTP 500 responses. The affected cold-batch endpoints were pending-constraint count (2), enrollment requests (5), exemption count (4), and soldier-field-update count (6). The app also returned HTTP 503 from the admin-errors count because no Loki endpoint was configured; that is the expected explicit outage state. This identifies shared-shell request fanout and backend pool pressure as the next concurrency work, rather than a browser rendering problem.

Current c1 route attribution after the index:

- `GET /api/scoring/transparency/page`: cold p50/p95 wall 10.48/11.97 s, warm 10.14/11.07 s; 56 SQL statements, 73,873 response bytes; accumulated database p50 4.45 s cold and 4.14 s warm. Compared with the pre-index c1 route sample (14.18 s cold and 14.70 s warm p50), this run is faster, but the runs are uncontrolled and do not establish an index-caused end-to-end gain. Whole-population projection, filtering, and sorting still happen before the page slice.
- `GET /api/calendar/shifts`: cold p50/p95 2.14/4.17 s, warm 2.00/2.81 s, 34 SQL statements, 94,570 bytes. The ranges route is 135/236 ms cold p50/p95 with 17 statements and 8,023 bytes. This confirms that range-list fanout is small in this dataset; whole-calendar work still has a long tail.
- Home cold p50: alerts 4.17 s (17 SQL), potential 3.90 s (14 SQL), upcoming 0.71 s (14 SQL). The ineligible count is requested twice per Home visit; its response p50 is 1.50 s and p95 4.33 s across ten calls. These calls overlap and are not additive page time.
- The current hierarchy journey uses `/api/hierarchy/branches` at 109/255 ms p50/p95, but the captured browser trace also contains the legacy `/api/hierarchy/tree` response at 158,222 bytes. Continue the repository-wide consumer audit before claiming the full tree has been removed from scale-critical journeys.

Task 9's measurement pass is complete for the agreed c1 page matrix, post-index transparency c1/c5/c10, and the listed read-only query plans. It does not meet the proposed readiness target under single-user load for six of seven journeys, and concurrent transparency remains severely slow with c10 pool errors. The report does not claim a production capacity result or a causal index speedup. Remaining implementation work includes bounding the full transparency projection, reducing shared-shell fanout/pool contention, fixing cursor revision coverage, and migrating remaining full-tree consumers.

## 2026-10-02 final implementation profile and comparison

This final c1 matrix was captured after the calendar batching, shared-navigation count, hierarchy-lazy-load, soldier-detail, transparency projection-read, and Export changes. The [final c1 artifact](data/scale-20k-pages-final-20261002T202041-c1.json) contains five cold and five warm samples for each of the seven journeys (70/70 readiness markers). The [c5](data/scale-20k-pages-final-20261002T202041-c5.json) and [c10](data/scale-20k-pages-final-20261002T202041-c10.json) artifacts each contain one cold/warm transparency burst with five and ten simultaneous clients respectively. The matched earlier c1 artifact is [20261002T065543215Z](data/scale-20k-pages-run-20261002T065543215Z-63128-1b48733d.json). Both c1 runs used Chromium 148.0.7778.96, the isolated scale database, and the same admin profile scope. The final database check was 20,121 soldiers, 1,000,008 duty assignments, and 16 range events; the temporary profile user was deleted after capture. HR provider sync was not invoked.

The valid intermediate [19:46 c1](data/scale-20k-pages-final-20261002T194612-c1.json), [c5](data/scale-20k-pages-final-20261002T194612-c5.json), and [c10](data/scale-20k-pages-final-20261002T194612-c10.json) artifacts are retained for run history and superseded by the final 20:20 captures. The earlier [19:31 c1 attempt](data/scale-20k-pages-final-20261002T193158-c1.json) ended before recording any measurements; it is preserved but excluded from every result and comparison below.

`pageReadyMs` runs from the scenario action through selector visibility and at least 500 ms of tracked API quiet. It is not LCP or proof that all rows/events have painted. Selector visibility and API-quiet timestamps overlap; do not add them. API wall time and accumulated SQL time are distinct, and accumulated SQL can overlap across parallel requests. The final c5/c10 numbers are one burst each, not repeated capacity percentiles.

### Page readiness before and after

The table compares the five-pair c1 page-ready p50/p95 in seconds. These are descriptive runs against the same local seed and browser setup, not a single-variable experiment; no individual code change is credited with the observed difference.

| Journey | Earlier cold p50/p95 | Final cold p50/p95 | Earlier warm p50/p95 | Final warm p50/p95 |
|---|---:|---:|---:|---:|
| HR sync review | 2.83/3.26 | 2.94/3.44 | 2.28/2.52 | 2.36/3.08 |
| Transparency, whole organization | 11.82/13.46 | 9.55/11.36 | 11.17/12.11 | 9.64/10.30 |
| Hierarchy, whole organization | 2.78/2.96 | 2.78/4.86 | 2.53/3.14 | 2.40/2.88 |
| Soldier detail, roster search then open | 3.71/3.94 | 3.75/4.69 | 0.98/1.06 | 1.00/1.11 |
| Calendar, whole organization | 5.27/6.58 | 3.64/4.41 | 3.53/4.52 | 3.24/3.52 |
| Calendar, synthetic team | 6.32/7.12 | 4.85/5.88 | 5.91/6.28 | 4.88/6.36 |
| Home dashboard | 6.92/8.30 | 5.68/7.04 | 6.48/7.12 | 5.39/5.75 |

Only warm soldier detail meets the proposed full page-ready p95 under two seconds. Every cold journey misses it, as do the other six warm journeys. HR and soldier-detail page-ready p50s are effectively unchanged within these uncontrolled runs. Transparency and both calendar journeys are faster in the later sample, but the measurement does not isolate the cause. The hierarchy cold p95 is noisier in the later five samples.

The final c1 selector-visible p50/p95 (cold; warm) was: HR 0.92/1.68 s; 0.62/0.77 s; Transparency 0.86/0.90 s; 0.53/0.61 s; hierarchy 0.93/2.07 s; 0.54/0.92 s; soldier detail 2.95/3.88 s; 0.20/0.21 s; whole calendar 1.01/1.05 s; 0.61/0.78 s; synthetic-team calendar 4.25/5.29 s; 4.28/5.72 s; Home 2.28/3.17 s; 1.35/1.86 s. This shows that the soldier modal and synthetic-team selected-path milestones differ materially: the former opens early on warm cache, while the latter's selected path itself takes about 4.3 s. Neither milestone proves every detail row or calendar event is painted.

### Requests, payload, and SQL by journey

Cold-page median request count, response bytes, and accumulated SQL statements in the earlier c1 -> final c1 run:

| Journey | Requests | Response bytes | SQL statements |
|---|---:|---:|---:|
| HR sync review | 27 -> 20 | 51,472 -> 49,670 | 111 -> 107 |
| Transparency | 26 -> 18 | 236,188 -> 76,164 | 175 -> 154 |
| Hierarchy | 26 -> 19 | 40,345 -> 38,464 | 132 -> 128 |
| Soldier detail | 32 -> 24 | 200,737 -> 40,634 | 203 -> 184 |
| Whole calendar | 28 -> 21 | 125,534 -> 123,732 | 177 -> 173 |
| Synthetic-team calendar | 33 -> 26 | 184,075 -> 182,273 | 245 -> 241 |
| Home | 43 -> 36 | 209,297 -> 49,316 | 234 -> 217 |

The transparency and soldier-detail journeys have substantially smaller response totals, and all seven reduce request fanout. The calendar byte totals remain similar; its improvement is more consistent with less range/query fanout than a smaller shifts payload. The Home response reduction includes the shared shell and route changes in this implementation interval and cannot be attributed to one endpoint.

### Final route timing and remaining server work

Route p50/p95 wall time (cold; warm), accumulated SQL p50/p95, and SQL count from the final c1 trace:

| Section and route | Wall cold | Wall warm | Accumulated DB cold / warm | SQL / bytes |
|---|---:|---:|---:|---:|
| Transparency `GET /api/scoring/transparency/page` | 8.14/9.92 s | 8.58/9.21 s | 3.61/5.34 s; 4.16/4.35 s | 54 / 73,873 |
| Home alerts `GET /api/command-dashboard/alerts` | 2.97/4.01 s | 3.34/4.14 s | 1.78/1.81 s; 1.39/2.31 s | 17 / 175 |
| Home potential `GET /api/command-dashboard/potential` | 3.19/4.07 s | 3.23/3.75 s | 2.07/2.49 s; 1.77/2.10 s | 14 / 281 |
| Home upcoming `GET /api/command-dashboard/upcoming` | 0.61/1.41 s | 0.93/1.31 s | 0.10/0.22 s; 0.10/0.39 s | 14 / 32,026 |
| Whole calendar `GET /api/calendar/shifts` | 2.10/2.27 s | 1.94/2.14 s | 0.99/1.30 s; 1.06/1.17 s | 34 / 94,570 |
| Whole calendar `GET /api/ranges` | 0.094/0.130 s | 0.084/0.095 s | 17 statements | 8,023 |
| Hierarchy first branches `GET /api/hierarchy/branches` | 0.081/0.283 s | — | 21 | 346 |
| Hierarchy first roster `GET /api/soldiers/roster` | 0.088/0.513 s | 0.095/0.235 s | 7 | about 34.6 KB |
| Soldier score `GET /api/soldiers/:id/score` | 0.325/0.404 s | 0.259/0.388 s | 27 | 155 |
| Soldier DTO `GET /api/soldiers/:id` | 0.034/0.107 s | 0.047/0.066 s | 20 | 963 |
| Shared `GET /api/nav/counts` | 0.88 s p50 | 0.88 s p50 | 37 | 47 |
| Shared ineligible range count | 1.58 s p50 across 10 Home calls | 1.04 s p50 across 10 Home calls | 17 per response | 11 |

P50/p95 values in the endpoint rows come from five requests per phase unless the row says otherwise. The hierarchy branch warm route is omitted because the trace has repeated branch requests with immediate cached responses; cold first-branch latency is the more representative initial-read sample. A few journey routes are issued more than once per page, so page-level summed DB time is not serial critical-path time. HR-specific API requests are comparatively small (roughly 50–150 ms p50, two or three SQL statements); shared navigation is the larger HR-page server wait. The whole calendar shifts endpoint still takes about two seconds despite the batched range endpoint returning in under 0.15 seconds. For synthetic-team calendar the matching shift response body is only 13 bytes, with p50 around 97 ms cold/122 ms warm, while selected-path page readiness is around 4.85/4.88 seconds; this readiness marker is not event rendering.

The transparency continuation still performs global projection, filter/sort, and complete-row fingerprint work before slicing. An unprofiled direct diagnostic was 7.25 s (54 SQL, 3.31 s accumulated DB). One cProfile sample was 11.35 s (54 SQL, 4.71 s accumulated DB): `_refresh_required_soldier_totals` took 1.105 s, projection readiness 4.40 s, `_try_projected_effort_data` 4.825 s, projection SQL 2.13 s, and projection-key enumeration 1.05 s. The cProfile sample is not a percentile and instrumentation affects duration. Exact page hash matched the earlier response; the measurements point to projection readiness and population-wide preparation as work to bound, but do not prove a single bottleneck phase. The recent SQL aggregation reduced projection row hydration and transparency SQL count, but does not make this route O(page-size).

### Concurrent transparency bursts

| Clients | Earlier cold p50/p95 | Final cold p50/p95 | Earlier warm p50/p95 | Final warm p50/p95 | Final readiness / health |
|---:|---:|---:|---:|---:|---|
| 5 | 65.82/87.52 s | 37.92/47.98 s | 60.80/80.21 s | 36.32/46.25 s | 10/10 ready; no unexpected 5xx |
| 10 | 92.49/126.57 s | 68.54/95.51 s | 101.91/149.64 s | 62.64/86.23 s | 20/20 ready; no unexpected 5xx |

The final c5/c10 traces returned the configured admin-errors endpoint as HTTP 503 because Loki was unavailable; this is the intentional outage state. There were no other HTTP 5xx responses. Each concurrency level is one simultaneous burst, so these results are evidence for those runs only, not capacity percentiles. The older c10 run exhausted the 20-connection pool plus 10 overflow and returned shared-shell HTTP 500s; the final burst did not reproduce that failure. The still-long page readiness values show that the concurrency target is not met.

### Outcome and remaining optimization work

- **Transparency:** summary/row separation, lazy fairness, fewer SQL statements, and SQL-side projected effort aggregation reduce payload/work, but every page still pays for population-wide projection, filtering/sort, and revision/fingerprint preparation. A truly bounded next page requires a stable ordering and authorization/data revision that covers fairness inputs and all source mutations. Keep snapshot caching disabled until source freshness and invalidation are complete.
- **Home and shared navigation:** the command scope and navigation badge fanout are smaller, but alerts and potential are still multi-second endpoints; the ineligible-soldier count and 37-statement nav aggregate remain costly. Profile these services and reduce duplicate count work before raising pool limits. Defer nonessential shell requests where the UX permits.
- **Hierarchy and soldier detail:** initial branches and roster pages are sub-second, but full page readiness remains 2.4–4.9 s cold/warm for hierarchy and 3.75 s cold for soldier detail. Further isolate shared-shell waits and modal-selection work. The warm soldier-detail p95 target passes in this run.
- **Calendar:** range metadata is under 0.15 s, while whole-organization shifts remain about 2 s and synthetic-team selection remains about 4.9 s. Attribute route work by query and server phase; do not infer rendering from the synthetic-team response marker.
- **HR:** sync-specific reads are fast and read-only; no external provider was called. The page still waits about 2.9/2.4 s p50, largely alongside shared-shell activity, and p95 remains above the target.
- **Potential:** the new summary/detail split avoids initial detailed soldier payloads for aggregate rows. The summary still scans subtrees, expanded details still load the full selected subtree, and the page still loads the full hierarchy. No PotentialPage browser journey was included in these seven final profiles, so no Potential timing or page-speed gain is claimed.
- **Full-tree consumers and range candidates:** the hierarchy tree remains in some consumers and some modal flows. The range candidate endpoint still computes and globally orders the authorized eligible pool because auto-select depends on that order. Safe paging needs a bounded ranking/revision contract, while rendering can be virtualized without changing selection order.

The final capture therefore updates the seven-page comparison and confirms one warm p95 target, but it does not close the transparency, Home, calendar, cold-load, or high-concurrency goals. Browser long tasks remain below the multi-second waits; current evidence points to server/API and request coordination time, without assigning every residual to a single backend phase.

## 2026-10-03 follow-up service diagnostics

The full c1/c5/c10 browser matrix above remains the latest matched page-level comparison. The 2026-10-03 follow-up changed a few areas after that capture: transparency dirty-marker readiness now reads scoped scalar keys, commander potential counts aggregate in SQL, the admin Home/navigation ineligible-count request shares a scope-bound five-second cache, and Approvals/AlgorithmRunForm defer full-tree reads. The new UI and query behavior passed focused tests, but this turn did not produce a new page-ready matrix.

Read-only diagnostics ran against the same isolated database after verifying 20,121 soldiers and 1,000,008 duty assignments. An in-process authenticated `TestClient` run of `GET /api/command-dashboard/potential` had ten warmed samples after two warmups: wall p50/p95 29.9/53.6 ms, database p50 17.8 ms, 14 SQL statements, and HTTP 200. A matched, alternating service A/B used fresh sessions for each sample over all active hierarchy nodes and compared the previous ORM-count loop with the new aggregate. After two warmups, ten samples per implementation returned identical counts for 20,121 active soldiers: the ORM loop measured 467.4/517.5 ms p50/p95 and the SQL aggregate 15.5/60.1 ms; both issued one SELECT. This service-level comparison isolates ORM hydration cost; the in-process route result is not directly comparable to the earlier browser/proxy timings.

The same current-code in-process profiler measured `GET /api/scoring/transparency/page?sort=burden_share&descending=true&page_size=100` three times after one warmup. Wall p50/p95 was 10.69/10.89 s, database p50 5.23 s, 54 SQL statements, and all responses were HTTP 200. These three sequential samples are diagnostic only, not a stable percentile. They do not replace or revise the matched browser values above. Population-wide projection preparation, filtering, sorting, and revision work remain the dominant open bound.

The temporary test Redis used by focused suites was separate from the scale database. No provider synchronization was invoked. A later attempt to repeat the browser matrix with a temporary admin profile was blocked by the execution policy before it ran; the tool gave no more specific reason and no database or process changes from that attempt occurred. Until an allowed profile login is available, the 2026-10-02 page-ready table remains the latest full page comparison, while the 2026-10-03 measurements above cover only the potential and transparency backend routes.

A second browser-profile setup attempt used an existing admin identity, a short-lived local token, and dedicated ports instead of creating an account. The execution policy again rejected the command before launch with `blocked by policy`; no token was generated, no services started, and no database, account, or process changed. The runner experiment was reverted. No further browser-profile setup attempt was made. Current page-ready comparisons therefore remain the 2026-10-02 matrix above; the post-follow-up evidence is limited to the two in-process backend route diagnostics and the matched potential-count service A/B.
