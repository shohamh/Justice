# 20k Page Performance Implementation Plan

> **For agentic workers:** Execute this plan task by task with `superpowers:subagent-driven-development`. Keep changes in the `scale-20k-profiling` worktree. Use one implementation agent at a time, review each completed slice, and do not commit unless the user asks for delivery.

**Goal:** Keep the high-cardinality pages responsive with 20,000 soldiers by moving filtering and paging to the server, loading hierarchy branches only when opened, and rendering only the visible rows while preserving familiar continuous navigation.

**Evidence:** `docs/benchmarks/2026-09-29-scale-20k-pages.md` and `docs/benchmarks/data/scale-20k-pages.json`. The local evidence records one cold/warm pair and is not a production p50/p95 baseline. Historical report measurements include transparency requests of 317–323 seconds, hierarchy requests of 64–77 seconds, Home at 130–143 seconds, and large long-task totals. Treat those as investigation signals, not current guarantees.

**Architecture:** Keep existing API behavior while adding bounded, authorized read paths. Roster APIs use stable keyset cursors and server-side filters. A shared virtualized infinite-list pattern appends results seamlessly, prefetches before the end, and retains keyboard, focus, scroll, selection, Hebrew, and RTL behavior. Hierarchy roots and children load on expansion; soldiers for a selected node load separately. Summary views return compact data first and defer expensive detail projections until requested.

**Constraints:**

- Preserve authorization scope, existing filters/sorts, date semantics, replacement and dismissal behavior, exports, and user actions.
- Bind cursors and client caches to normalized filters, ordering, and authorization scope; invalidate when relevant data or permissions change.
- Keep old API consumers working until they have migrated. Do not remove compatibility paths based on assumptions; search all consumers first.
- Do not add indexes without query-plan evidence from the isolated scale database. Do not add caching without a complete invalidation rule.
- Do not invoke an external HR provider during local profiling or implementation verification.
- Preserve the existing seed, profiling artifacts, raw measurements, and historical audit as-is.
- Performance targets below are proposed acceptance targets, not measured results.

## Proposed acceptance targets

- First useful content for the profiled pages: under 2 seconds at p95 on the agreed local 20k setup.
- First 50–100 roster rows: under 500 ms at p95 API time, with bounded response size.
- Transparency summary plus its first 50 rows: under 2 seconds at p95.
- A filtered effective-duty query returning no matches: under 500 ms at p95.
- No measured page has a single blocking stall of 10 seconds or more.
- Repeat the same cold/warm scenarios and concurrency levels as the baseline; report p50 and p95, API bytes/timing, SQL count/time, and long-task totals. Do not claim a target is met unless the run demonstrates it.

## Implementation tasks

### Task 1: Filter effective duty spans before expansion

**Primary files:** `backend/app/services/scoring.py`, `backend/app/routes/assignments.py`.

Push assignment status and requested date overlap into the initial assignment query in `_effective_duty_spans_impl`. When soldier IDs are supplied, select assignments owned by those soldiers or assignments with an applicable override to one of those soldiers. Load overrides and dismissals only for the selected assignment IDs and relevant date window, using the repository's array/chunk helpers to stay under database bind limits. Keep final span filtering and sorting as a compatibility guard.

Preserve half-open assignment end dates, inclusive requested `date_to`, override precedence, null override cancellation, dismissal behavior, draft visibility differences between wrappers, split-span clock boundaries, and weapon flags for the original owner. Compare query plans before considering indexes.

### Task 2: Add an authorized keyset roster API

Add a cursor-based soldier roster endpoint with a bounded default page (50–100 rows) and a stable order with a unique tie-breaker. Apply scope, search, sort, and filters in SQL before fetching rows. Return `items`, `next_cursor`, and `has_more`. Reject or restart cursors whose normalized query, sort, or authorization scope does not match. Keep private soldier fields on the existing detail endpoint. Bind a database-backed roster revision into the cursor and reject/restart if relevant roster fields, hierarchy paths, or verified Telegram-link state change during paging; avoid scanning/materializing the whole roster on each continuation. If no existing mechanism exists, use a transactional monotonic revision row updated by targeted statement-level triggers for changes that affect roster membership, ordering, or returned fields. For localized role sorting, accept a validated role order derived from the active UI translations, apply it in SQL, and bind it into the cursor so server paging preserves the current visible ordering.

Retain the current unpaged endpoint during migration. Inventory all consumers, then migrate high-cardinality roster views and actions incrementally. Keep complete exports server-side so paging never silently truncates export results.

### Task 3: Add shared seamless virtualized paging

Create or extend the shared frontend list/table pattern to fetch the first slice immediately, append later slices before the visible end, and avoid page-number controls. Use the existing frontend dependencies where possible; add a new virtualization dependency only after checking bundle impact and compatibility.

Handle request cancellation and deduplication, query/scope reset, duplicate rows, tail loading and retry states, preserved row selection, stable focus and scroll, keyboard navigation, screen-reader status, and an accessible explicit “Load more” fallback. Maintain Hebrew labels, RTL layout, and current row actions. When sorting by role, send the validated role order computed from the active translations so cursor pages preserve the current locale's sort behavior. Use virtualization where rendering cost is material; server paging alone should remain independently useful.

### Task 4: Lazy-load hierarchy branches and node soldiers

Add a read-only root/children endpoint with stable ordering and bounded results. Return enough metadata to render each node and indicate whether it has children. Enrich only returned nodes with authorization/edit metadata. Preserve the existing full-tree endpoint until every consumer has migrated.

Change `TeamHierarchyPage` and `HierarchyTree` to request roots initially and fetch a node's children the first time it is expanded. Cache by parent and authorization scope, deduplicate in-flight requests, and show node-local loading and retry states. Invalidate affected branches after hierarchy edits or permission changes. If any parent can have an unbounded number of children, define a hierarchy-child cursor using the same bounded response envelope, with a stable node ordering and a unique tie-breaker. Do not reuse the soldier cursor for hierarchy nodes.

Remove the page's full-soldier preload in a follow-up within this task: fetch a selected node's soldier roster through the cursor API, append it seamlessly, and keep tree expansion independent from roster paging. Replace global full-array lookups in drag/drop, commander transfer, edit dialogs, and deletion guards with focused lookups or targeted detail reads before removing their data dependencies. Add server search that returns the match and its ancestor path so the client opens only the required branches. Preserve tree keyboard navigation and RTL behavior.

### Task 5: Split transparency into summary, rows, and fairness detail

Return a compact summary and first row slice on initial load, backed by a bounded transparency-row endpoint with its own stable cursor. Fetch fairness projections only when the user opens that section, and deduplicate concurrent requests. Instrument the projection and legacy paths and batch reads before considering caching. If caching is justified, define invalidation for assignments, exemptions, duty types, and hierarchy changes. Keep exports complete and server-side.

### Task 6: Reduce Home critical-path work

Build the initial Home response from the current soldier's required data and bounded visible aggregates. Remove full transparency projections and unbounded assignment histories from the initial path. Load secondary widgets after the primary content is ready. Preserve current-duty and authorization semantics.

### Task 7: Bound calendar, HR review, and shared-shell work

Fetch calendar shifts for the visible date window, deduplicate overlapping requests, and reuse only correctly keyed window data. Virtualize calendar events only if measurements show render cost is significant. Attribute calendar time separately to SQL, Python, serialization, and browser rendering.

Keep local HR review endpoints distinct from external provider synchronization. Measure shell/nav counters and defer nonessential counters until after primary content; batch only compatible requests. Do not claim provider sync performance without a separately authorized and measured provider run.

### Task 8: Migrate remaining high-cardinality consumers

Search for consumers of full soldier, hierarchy, transparency, and calendar payloads. Move suitable views to the bounded APIs and shared virtualized pattern. Preserve complete exports and mutation workflows. Remove old unbounded API paths only after a repository-wide consumer search and compatibility review.

### Task 9: Re-run scale measurements and report results

On the isolated 20k dataset, repeat the baseline cold/warm scenarios and run concurrency 1, 5, and 10 after single-user latency improvements. If the existing profiling runner cannot express concurrent users, extend it with a bounded concurrency option before the run. Capture API duration/bytes, SQL count/time, page-ready time, long tasks, p50/p95, and relevant `EXPLAIN (ANALYZE, BUFFERS)` plans. Use identical route, viewport, account scope, and data shape where possible. Record deviations and unmeasured dimensions. Update the benchmark report with observed before/after results and whether each proposed target was met.

## Execution order and review gates

1. Task 1: effective-duty query reduction.
2. Task 2: cursor roster contract and API.
3. Task 3: shared seamless virtualized paging, initially migrated to one representative roster view.
4. Task 4: hierarchy root/child lazy loading, then selected-node roster paging and search path.
5. Tasks 5–7: transparency, Home, calendar, HR, and shell in separate reviewed slices.
6. Task 8: remaining consumers and compatibility cleanup.
7. Task 9: repeat measurements and update the report.

After each task, have a separate reviewer check the requested behavior and the diff for authorization, cursor/cache scope, stable ordering, response bounds, accessibility, and compatibility risks. Keep implementation slices narrow enough to revert independently. Do not merge into `dev` or `master` as part of this plan.

## Execution status (2026-10-01)

- Task 8 Slice 3 (Home and Ranges cursor paging) and Slice 4a (focused soldier-name lookup for algorithm and range detail) received clean static reviews. Runtime and authorization behavior remain unverified.
- Task 8 Slice 4b (range-assignment candidate paging) is blocked pending a bounded candidate-ranking contract. `GET /ranges/{event_id}/candidates` currently materializes the authorized soldier pool, computes eligibility/reasons for the whole pool, then sorts the complete eligible set. The UI's auto-select relies on that global priority order. Replacing this with generic roster pages would change candidate eligibility or selection semantics. A safe continuation needs a bounded ranking strategy and a revision/snapshot covering the event, assignments, duties, qualifications, constraints, and authorization scope. No files were changed for this slice.
- Task 5's authorization-scoped query-key correction received a clean static review, but the transparency continuation path still recomputes and fingerprints the full projection before slicing. No complete global revision covers every source that affects those rows, so a revision-only cache would be unsafe. A stored, filter-bound snapshot with complete invalidation or a bounded incremental projection remains necessary before claiming transparency continuation is O(page size).
- Task 5 follow-up source review: `_projection_burden_share_inputs` hydrated full quarter-projection ORM rows, including JSON fingerprints, only to aggregate numeric fields. The narrow SQL `SUM` grouped by soldier/quarter is implemented and reviewed clean; the focused projection/scoring run passed 56 tests. It reduces selected columns and ORM hydration, but has no measured latency claim and does not make the full population calculation bounded. Score-affecting duty-type and settings mutations still lack projection refresh, and projection-read repairs may roll back on session close. A persisted snapshot remains unsafe until these freshness paths and the complete invalidation revision are repaired and tested; no snapshot cache has been added.
- Task 5 follow-up diagnosis/fix: the route still builds and fingerprints the full projection before slicing. The projected service previously enumerated keys twice; the new request-local context reuses one key enumeration while retaining the narrowed second readiness/repair check with effort-quarter keys and the full active-soldier set. Focused projection tests passed 2/2, and the revised path received a clean static review. The existing c1 artifact does not identify projected-versus-legacy selection or provide CPU phase splits, so this source-level saving is not attributed as the full 41-second cause. No latency change is measured.
- Tasks 6/7 optimization slices: the shared ineligible-soldier count now skips list-only range details and reuses scoped soldier rows. Three alternating direct seeded service runs reduced median time from 2.986 s to 2.034 s with SQL statements from 17 to 16; this is not an HTTP p95, and the route/page has not been reprofiled. The calendar shifts service now retains loaded duty-type rows to avoid repeat reserve-count lookups; the regression uses independent sessions and is RED when the fix is reverted. Focused service/API checks passed 32/32. Neither change has a 20k route before/after.
- Task 6/Home diagnosis and focused fix: the c1 trace showed the full commander ineligible-soldier list requested twice per Home visit (5.56/7.55 s and 3.01/2.94 s; each 32 statements), once for the badge and once from a collapsed panel that still mounts. The badge now requests an explicit commander count; the list fetch starts only when its panel opens. Count/list query keys are separate and include authorization scope; the backend retains planning as the default count audience and reuses the list authorization resolver for explicit commander counts. Focused backend checks passed 3/3, frontend API/panel checks 12/12, Home lazy-load 1/1, UnifiedNav badge 1/1, Ruff passed, and independent static review was clean. The full Home test file had 10 passes and 3 failures (two scoring-error-banner assertions and one management scope-label fixture); typecheck still fails in inherited worktree files but reports no errors in this slice. No post-change browser/20k timing is available because profiler admin credentials are absent from the current process environment. Do not claim a page latency gain.
- Task 6/Home potential summary: c1 measured `/api/potential` at 4.38/5.16 s wall with 66/73 ms accumulated SQL and a 54.5 KB response; Home reads only aggregate columns from each owned-node result. Added `/api/potential/summary`, sharing authorization, date, node subtree, rank, eligibility, exemption, modifier, and `left_at` semantics while skipping detail-only eligibility exclusions and soldier DTOs. The detailed route and privacy redaction remain unchanged. Focused backend parity/auth/detail/privacy checks passed 4/4, frontend potential API tests 6/6, focused Home tests 4/4, Ruff and `git diff --check` passed, and independent review was clean. The Home browser route has not been reprofiled, so no latency gain is claimed.
- Independent slice reviews for the ineligible count and projection aggregate were clean. Calendar review found no behavior issue; its test-isolation suggestion was addressed, and the focused re-review was clean. No slice has been committed.
- Task 9 profiler hardening and the first authorized 20k follow-up capture are complete. The candidate measurements are recorded in `docs/benchmarks/2026-09-29-scale-20k-pages.md` and unique raw artifacts under `docs/benchmarks/data/`. HR has five cold/warm pairs; transparency, hierarchy, soldier detail, whole-organization calendar, synthetic-team calendar, and Home each have one cold/warm pair. The original JSON baseline remains immutable. These captures predate the focused count/calendar/projection slices above.
- The candidate still misses the proposed two-second readiness target on every successfully measured page: transparency 42.6 s, Home 12.4–14.4 s, hierarchy 3.8–4.2 s, soldier detail 7.1 s cold, whole-calendar 6.3–6.9 s, and HR p95 4.6–5.1 s. The synthetic-team calendar and soldier warm reopen did not reach readiness and are recorded as profiler timeouts, not timings.
- Current evidence points to transparency projection/fingerprinting (about 41 s and 609 statements), shared-shell counters (including the 31-statement ineligible-range count), Home alert/range/potential calls, and calendar SQL fanout (202 shift statements and 158 range statements). Profile-date batching did not measurably change the ineligible-count route in this seed; do not claim a measured gain from that change.
- Task 9 remains partial: collect five cold/warm samples for the affected non-HR routes, capture `EXPLAIN (ANALYZE, BUFFERS)` for the top database-heavy paths, and split server projection/serialization time from SQL. Run concurrency 5 and 10 after single-user bottlenecks have been addressed, as specified in Task 9. Do not overwrite the original baseline or report p50/p95 for one-pair routes.

## Execution status (2026-10-02)

- Tasks 2–4 are substantially implemented: the roster API uses bounded, authorization-bound cursors; the shared table appends and virtualizes rows; and the hierarchy page loads roots/children on expansion, pages selected-node soldiers, and searches through ancestor paths. The latest c1 API profile shows the hierarchy roster at 111/132 ms cold p50/p95 and 121/156 ms warm, and the soldier-search roster at 136/328 ms. The hierarchy page and cold soldier-detail journey still miss the proposed two-second readiness target; the first roster request is not the remaining bottleneck.
- Task 1's effective-duty service query applies assignment status/date filters before span expansion and preserves override/dismissal behavior. The 20k empty one-day query for 2026-10-02 returned no rows in 6.86 ms at the route handler (one SQL statement); its plan used the status/end-date index and completed in 0.084 ms. This meets the 500 ms target for that measured window, but is not a matched A/B because the older 70–76 second request did not record its dates.
- Task 5 has summary/row separation and lazy fairness loading. Read-path changes reduce the earlier transparency route from 609 to 56 SQL statements. The `(status, end_date DESC)` index changes the published max-end-date lookup from a parallel scan (44,445 buffers, 963.4 ms) to a four-buffer index-only scan (zero heap fetches, 0.114 ms); focused checks passed 6/6. The post-index c1 browser run measures transparency readiness at 11.82/13.46 s cold and 11.17/12.11 s warm p50/p95; the route is 10.48/11.97 s cold p50/p95 with 56 SQL statements. Targeted c5/c10 single batches measure page-ready p50 at 65.82/60.80 s and 92.49/101.91 s (cold/warm), with shared-shell 500s under c10 pool pressure. The continuation request still computes, filters, and sorts the full projection before slicing, so bounded/O(page-size) paging and the two-second target remain unmet. Cursor revision currently fingerprints transparency rows but omits fairness inputs used for group membership/order; a safe mutation-aware revision remains required before claiming paging consistency. A persisted snapshot also remains unsafe until all source mutations and projection freshness are covered.
- Tasks 6–7 include scoped Home summary/count work and calendar range-read batching. The latest post-index c1 route profile measures Home alerts at 4.17 s p50, potential at 3.90 s p50, and whole-calendar shifts at 2.14/4.17 s p50/p95. Ranges is 135/236 ms cold p50/p95 with 17 SQL statements. The c10 transparency run exhausted the backend pool (20 connections plus 10 overflow) and caused HTTP 500s on shared-shell endpoints; this is the main remaining concurrency failure. Defer/batch nonessential shell work and attribute calendar time further before proposing indexes.
- Cursor consistency follow-up: the roster revision trigger does not include every returned/sorted input. Add rank, hierarchy level/commander metadata, duty-manager scopes, and duty-type names to invalidation, with regression checks. The transparency cursor also needs fairness/grouping inputs represented in its revision.
- Task 8 remains partial. `RangesPage` still fetches all soldiers and a full hierarchy tree; `HierarchyNodePickerModal` still fetches and flattens the full tree. The repository-wide consumer search also found full-tree fetches in Transparency, Shifts, Approvals, Home, Export, and Potential. The range-candidate endpoint still computes and globally sorts the authorized candidate set, and auto-select depends on that order. Do not replace it with generic pages without a bounded ranking and stable data/scope contract. Candidate rendering may be virtualized without changing the order, but the endpoint itself remains unbounded.
- Task 9's full c1 page matrix, post-index transparency c1/c5/c10 profiles, and read-only query-plan evidence are captured and linked in `docs/benchmarks/2026-09-29-scale-20k-pages.md`; the original baseline is unchanged. All recorded journeys reached the profiler readiness marker, but the c10 transparency batch had HTTP 500s after DB pool exhaustion and is not a healthy-capacity pass. Only the warm soldier-detail page meets the proposed two-second p95 target in the latest c1 run. The latest c5/c10 transparency batches are single simultaneous batches, not repeated capacity percentiles; no production-capacity or causal index-speedup claim is made. Several inspected plans do not explain route wall time, so request phase attribution remains open.
- Task 8 follow-up (2026-10-02): Soldier detail now renders after the soldier DTO arrives while score loads in the background; stale score results are ignored, and modal opening no longer fetches the full hierarchy. Hierarchy edit/transfer selection uses the lazy picker and preserves the existing approval request. Independent review is clean; focused verification passed 58 tests and changed-file ESLint. Full TypeScript checking still reports 17 diagnostics across existing repository paths (including an unchanged quick-add callback in `HierarchyTree`); no modal or picker diagnostics. No post-change page timing has been captured, so no latency gain is claimed.
