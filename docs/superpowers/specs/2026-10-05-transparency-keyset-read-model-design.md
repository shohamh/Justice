# Transparency Keyset Read Model Design

Date: 2026-10-05

Status: proposed design for review. The direction is approved for exploration; implementation remains gated on review of this spec.

## Problem

The paged transparency endpoint has fast cache hits and continuation requests, but a cold first-page miss still builds the complete population in Python, filters and sorts it, serializes every row, and persists the full result before returning 100 rows. On the isolated 20,270-active-Soldier dataset, the measured miss was 11.313 s p50 / 12.326 s p95. That measurement predates the latest snapshot cap, chunk writer, and scalar projection read, so it is historical evidence rather than a current baseline. There is no matched post-change 20k endpoint measurement yet.

Keyset pagination alone does not solve that miss if its sort key still has to be computed for the entire population in the request. The page needs a queryable, current scoring read model whose order can be indexed, and the endpoint needs to fetch only the requested slice from it.

## Goals

- Make the common transparency view (`burden_share` descending) read a bounded page from a relational, indexed model instead of constructing and persisting every API row on the request path.
- Keep page navigation seamless: the client continues to fetch ahead while scrolling and render only virtual rows, with no visible page controls.
- Preserve the current response shape, scoring fields, viewer authorization, exemption redaction, summary meanings, `has_more`, and stale-data handling.
- Make the cursor stable for ties and bound it to the viewer, query, model generation, and expiration.
- Keep the current snapshot implementation available for unsupported query combinations, cursor compatibility, and a correctness fallback while the model is unavailable.
- Measure the model refresh, first-page API, continuation API, and browser readiness separately on the same isolated 20k workload.

## Non-goals

- Rework scoring formulas, fairness components, exports, or the unpaged `/scoring/transparency` route.
- Move all transparency sorts and filters to SQL in the first implementation.
- Change the UI table, scrolling behavior, or virtualization implementation unless a regression requires it.
- Claim a speedup from a SQL or synthetic microbenchmark without matched endpoint and browser measurements.

## Existing behavior to preserve

`svc.transparency_rows` validates the score projections and computes rows for the active Soldier population. It calculates `normalised_score` using the average score-per-day across the full active population before applying viewer visibility. Non-admin viewers receive their self row and rows visible under their scope rules. Exemption labels/details are returned only when the Soldier is in the viewer's exemption-visible scope; aggregate exemption flags are omitted when the viewer cannot see those aggregates.

`GET /scoring/transparency/page` currently applies node-subtree, officer, service-type, and optional fairness-group filters. It calculates the page summary over the rows after those four filters, before rank and text search. `row_num` is assigned to those rows before rank/search and before the requested final sort. Rank and search then filter rows, and the requested sort is applied with Soldier UUID as an ascending tie-breaker. This ordering is unusual but observable and must remain on the existing snapshot path until a separate semantics change is approved.

The current cursor binds the request and viewer scope to a persisted snapshot and offset. Source generation, a PostgreSQL visibility snapshot/journal check, `as_of` date, expiry, and refreshed authorization protect against stale pages. The frontend `CursorPagedTable` fetches another page near the end of the virtualized viewport and resets once on a 409 stale-cursor response.

## Proposed design

### 1. Versioned canonical transparency read model

Add a versioned relational read model separate from the per-request page cache:

- A generation metadata row records a unique generation ID, the captured transparency source generation, captured database source snapshot, `as_of` date, build status/timestamps, and the full-population normalization denominator needed for `normalised_score`.
- One row per active Soldier stores the scalar scoring and display fields needed to filter/order/return the common transparency table: Soldier ID, burden share, cumulative score, score per day, normalized score, active days, shift count, burden-share offset, globally-exempted flag, name, rank, officer/service classification, enrollment date, and hierarchy node ID/name.
- A composite index on `(generation_id, burden_share DESC, soldier_id ASC)` supports the default page order and keyset continuation. Add only indexes justified by the first supported query shape and measured plans.
- Exemption detail is loaded in a bounded batch for the returned Soldier IDs, with the existing scope predicate applied before returning labels or details. Do not place viewer-redacted exemption payloads in a globally shared row model.
- The model generation is published atomically only after every active Soldier has a complete row and projection readiness checks pass. A failed or interrupted build remains invisible to readers.
- Retain only the current and immediately previous completed generations; prune older derived rows after publication. Old-generation cursors are stale by contract and return 409, so they do not require old model rows to remain queryable.

The model builder reuses validated score projections and the existing canonical scoring functions where practical. It must not create a second scoring formula. It captures source generation and snapshot before reading inputs, then checks source generation, invisible journal transactions, and `as_of` again immediately before publish. If any check differs, it abandons the build and retries/coalesces rather than publishing mixed data.

Model refresh is coalesced by source generation and runs outside the page request. A source write invalidates the current generation through the existing transparency source-generation/journal mechanism and schedules refresh. When no fresh complete model is available, the endpoint uses the existing snapshot builder so responses remain correct; this is a deliberately slower fallback and is measured separately. The fast-path performance target is not considered met until the normal page-load workload has a fresh model available and the fallback frequency/build lag are reported.

### 2. Keyset first page and continuation

Use the fast path only when the request is the default query shape:

- `sort=burden_share` and `descending=true`;
- empty/whitespace-only search;
- no selected node, officer restriction, service-type restriction, fairness group, or rank filter.

Other sort/filter combinations continue through the existing immutable snapshot path. This keeps the first change narrow and preserves the current row-number and summary behavior for complex queries.

The first request validates the user's current transparency access, resolves current scope roots, captures the current source generation, and verifies that the published model generation matches that source generation and today's `as_of` date. It then reads at most `page_size + 1` authorized rows in this order:

```sql
ORDER BY burden_share DESC, soldier_id ASC
```

The extra row sets `has_more`; only the requested rows are returned. A continuation uses the last returned exact burden-share key and Soldier UUID:

```sql
burden_share < :last_burden_share
OR (burden_share = :last_burden_share AND soldier_id > :last_soldier_id)
```

The cursor carries the last score as a lossless decimal string, last Soldier UUID, emitted row count (for `row_num`), model generation, source generation, `as_of`, request/viewer binding, and expiration. It is signed with the existing JWT configuration. The server recomputes the binding and authorization on every request. Source-generation or date staleness returns the existing 409 stale-cursor response; a changed request/viewer binding follows the existing 400 invalid-cursor behavior, and revoked access remains 403. The server never silently combines rows from two generations.

Within this default mode, `row_num` is the one-based position in the same stable visible order returned by the query. Equal burden shares are therefore deterministic. This removes current tie-order ambiguity in the default view; a regression must explicitly cover equal scores and row numbers.

The external API remains `GET /scoring/transparency/page` with the existing response fields. New fast-path cursors use a new purpose/version and do not collide with the existing `transparency-page-v2` snapshot cursors. Valid v2 cursors continue to use their persisted snapshots until those snapshots expire or are cleaned up.

### 3. Authorization, row fields, and summaries

The SQL visibility predicate must match the current service behavior: admins see all active Soldiers; non-admins see Soldiers allowed by `can_view_soldier_scope` plus their own Soldier row. Build the viewer context once with `build_soldier_scope_visibility`, then mirror `can_view_soldier_scope_fast` in SQL using its expanded commander/DM ancestor IDs, `sees_every_soldier`, and rank-threshold fields against hierarchy `path_ids`. Do not treat raw scope roots alone as the authorization predicate. Raw `scope_root_ids` are still resolved fresh for exemption-redaction rules and cursor binding. The selected-node filter is absent from the first fast-path shape, so hierarchy subtree semantics remain on the snapshot path initially.

The read model contains full-population `normalised_score`, computed with the existing denominator across all active Soldiers, independent of viewer visibility. It does not use a viewer-filtered denominator.

The fast response summary is calculated from the complete authorized row set, not from the current 100-row slice. Match existing behavior for empty/single-row populations and rounding:

- row count, mean cumulative score, rounded mean active days, mean score/day, and mean normalized score;
- burden-share mean, population standard deviation, coefficient of variation, minimum, and maximum, with the existing null rules when fewer than two rows exist;
- burden-share offset min/max over the authorized source rows.

Summary aggregation must be bounded to database scalar aggregates; it must not hydrate every read-model row into Python. `can_see_exemption_aggregates` remains true only under the current role/scope rule. Page exemption flags/details are populated only for the returned page and only when authorized.

### 4. Freshness and failure handling

- A missing, incomplete, stale-source, stale-date, or expired model selects the existing snapshot path for a first-page request.
- A valid keyset cursor whose generation is missing or no longer current returns 409, allowing the existing client stale-cursor reset to restart from the first page.
- Invalid signature, malformed cursor fields, or a changed request/viewer binding returns 400, consistent with current invalid-cursor handling. Revoked transparency access remains 403.
- A model build failure does not publish partial rows. It is logged with generation and duration, and the previous completed generation may be retained for diagnosis but is not served as fresh data.
- The bounded snapshot capacity and cleanup rules remain unchanged for fallback requests and v2 cursors.
- Background refresh must be single-flight/coalesced per source generation so a burst of page requests or source updates cannot trigger duplicate population-wide builds.

### 5. Client behavior

Keep `CursorPagedTable` as the consumer. Its existing virtual list requests another page before the viewport reaches the end, deduplicates rows by Soldier ID, and resets once when the API reports a stale cursor. The read-model cursor is opaque to the client. Users continue scrolling through one table without page buttons or a visible paging transition.

The page-size cap remains 100. No request is made for later rows until scrolling approaches them, and only the virtual viewport is rendered. A changed filter/sort/query identity continues to reset the cursor chain and scroll position as it does today.

## Rollout and compatibility

1. Add the model schema and builder behind a feature flag/config switch; keep it disabled by default during backfill verification.
2. Build and validate a full model on the isolated 20k database. Compare all output fields against the existing snapshot path for admin and scoped users, including hidden exemptions, self-row visibility, normalization, empty cases, and score ties.
3. Enable the keyset fast path for the exact default query only. Continue issuing v2 snapshot cursors for all other query shapes and for default requests served by fallback.
4. Observe model age/build lag, fast-path share, fallback rate, invalidation/restart counts, query plans, and errors. Roll back by disabling the fast path; persisted snapshots remain available.
5. Broaden SQL-supported filters/sorts only in separately measured follow-up slices, each with an explicit parity test for that query's summary, row-number, and filtering semantics.

No source data is rewritten by this feature. The model tables are derived and rebuildable. Migration downgrade drops only these derived tables/indexes after the fast path is disabled.

## Verification and measurement

Correctness checks must compare fast-path pages with the existing snapshot result for the same frozen source generation and viewer. Cover first page and multiple continuations, tied scores, exact cursor boundary behavior, all response fields, complete-set summary parity, row count/`has_more`, self plus scoped visibility, admin visibility, hidden exemption details, normalized scores, source-generation invalidation, journal races, date rollover, concurrent/coalesced builds, interrupted publication, missing projections, and v2 cursor compatibility.

On the same isolated 20k database and commit, record separately:

1. Model build wall time, per-phase duration, SQL statement count/time, rows read/written, index/storage size, memory peak, and source generation published.
2. First-page endpoint latency with a current model, continuation latency at beginning/middle/end, response bytes, SQL count/time, and `EXPLAIN (ANALYZE, BUFFERS)` for the indexed keyset query.
3. First-page latency and fallback frequency while the model is missing/stale. This must not be folded into the current-model latency distribution.
4. Browser page-ready and first-render latency, page request timing, long tasks, and errors at c1 and the agreed concurrent load. Preserve the same browser/build/workload as the prior matrix.

Use at least five cold API runs and five warm/cached runs for each state; report p50 and p95 with raw results. The acceptance target remains p95 page-ready below 2 seconds and ordinary read API p95 below 500 ms. Also report model rebuild lag/fallback frequency so a fast warm path cannot hide a slow or frequently unavailable refresh path. Compare against the 11.313/12.326 s cold miss only as historical context because it predates recent backend changes.

## Risks and open review points

- The keyset predicate and index make page reads bounded only if the published model has the burden-share key precomputed. They do not make model construction cheap by themselves; build time and freshness coverage are release gates.
- Reusing existing projection readiness and source-change tracking needs careful audit so every input affecting burden share, normalization, row display, and visibility invalidates or refreshes the model.
- The model adds derived storage proportional to the active Soldier count plus indexes. Measure size and write amplification before enabling it broadly.
- Stable UUID ordering clarifies tie behavior and makes paging safe, but default `row_num` can change for rows tied on burden share compared with the current incidental service-query order. Validate this explicitly and surface any user-visible difference during review.
- Exemption details and aggregate flags are sensitive. The shared model must never make them visible outside the same current scope rules.
- If model refresh lag makes the slow snapshot fallback common, the system has not met the performance goal even if current-model keyset requests are fast; the refresh mechanism must be improved before calling this complete.
