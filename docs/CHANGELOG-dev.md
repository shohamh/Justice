# Dev Changelog

Developer-facing log of everything merged into `dev`, written for people working
on this codebase (modules touched, migrations, API/schema changes, config,
gotchas). Entries are added by the `merge-worktree-to-dev` skill; the
user-facing `frontend/CHANGELOG.md` is derived from this file at release time
by `release-dev-to-master`.

## Unreleased

### Transparency read-model design docs (`docs/transparency-design-docs`, 2026-10-10)
Docs: docs/superpowers/plans/2026-10-05-transparency-keyset-read-model.md, docs/superpowers/specs/2026-10-05-transparency-keyset-read-model-design.md
- Added the plan and design spec for the transparency keyset read model that landed with the shell-load merge (they were never committed).
- Reworded two references in the 2026-10-08 shell-load spec/plan that pointed at dev-server FCP capture files which are not retained in the repo.
- Type: chore

### Shell-load follow-ups: auth cookie persistence, nginx limit, limiter fail-open, local-day dates (`chore/shell-load-followups`, 2026-10-10)
Docs: docs/superpowers/specs/2026-10-08-shell-and-page-load-design.md, docs/superpowers/plans/2026-10-08-shell-and-page-load-optimization.md, docs/benchmarks/2026-10-08-shell-load.md
- Auth: refresh tokens now carry a signed `persist` claim, carried across rotation like `sid`; `/auth/refresh` sets the cookie `max_age` only when it is true. A login without "remember me" stays a browser-session cookie across refreshes (before, the first refresh turned it into a 30-day cookie). Tokens issued before this deploy have no claim and are treated as persistent (no surprise logouts). OIDC/SSO logins issue `persist=False`, so SSO sessions now also end when the browser closes (user-visible); register stays persistent. Touches `routes/auth.py`, `routes/oidc.py`, `auth/jwt_tokens.py`.
- Rate limiting: the slowapi login limiter (`rate_limit.py`, new `build_limiter`) now reuses the 1 s Redis socket timeouts from `redis_client.py` and fails open (`swallow_errors` + in-memory fallback) instead of returning 500 when Redis is down; the invite-code guess limiter falls back the same way (it sets slowapi's private `_storage_dead` flag, covered by a test against a dead Redis). During an outage limits are per uvicorn worker (up to `WEB_CONCURRENCY` times the configured limit); the DB account lockout is unchanged.
- Config/ops: `deploy/nginx.conf` `limit_req` raised from `rate=10r/s burst=20` to `rate=100r/s burst=100 nodelay` (a cold Home load fires ~32 API requests and many users share one NAT IP); `deploy/README.md` now says the worker count comes from `WEB_CONCURRENCY` (default 4). The earlier nginx changes (HTTP/2, gzip 6, cache headers) still need ops review.
- Frontend: timestamps shown for constraint decisions and My Requests use the user's local calendar day (new `timestampToLocalIso` in `utils/formatDate.ts`; before, 00:00-03:00 Israel time showed the previous day). Nav badges refresh right after approve/reject in the soldier modal, duty-history and exemptions panels (`onDecided` callbacks + `hooks/useInvalidateNavCounts`). `RouteFallback` no longer shows the nav shell before the forced Telegram setup redirect.
- Tests/tooling: vitest now pins `TZ=Asia/Jerusalem` (top of `vite.config.ts`) so timezone tests are real guards; profiler (`frontend/scripts/profile-scale-pages.mjs`) stamps marker-visible time in-page (clock-free, scoped observer), warns when the base URL host is `localhost` (a ~300 ms new-connection stall; use 127.0.0.1) and records `baseUrlHost`; five superseded benchmark captures (6.1 MB) removed from `docs/benchmarks/data` (still in git history at d94e064e).
- Gotchas: the 100 r/s edge limit is far looser than before, so login brute-force protection now rests on the backend limiter plus the DB lockout; existing non-remember-me sessions stay persistent until the user logs in again (their tokens have no claim).
- Tests: new refresh-cookie persistence, limiter resilience, invite-code resilience, nav-count/onDecided, RouteFallback Telegram, date helper tests; full backend suite exit 0, frontend 240 files / 1906 tests, lint and typecheck clean.
- Type: fix

### Shell and page-load optimization (`feature/shell-load-optimization`, 2026-10-10)
Docs: docs/superpowers/specs/2026-10-08-shell-and-page-load-design.md, docs/superpowers/plans/2026-10-08-shell-and-page-load-optimization.md, docs/benchmarks/2026-10-08-shell-load.md
- Query defaults (`main.tsx`, new `api/queryRetry.ts`): global `staleTime: 30_000`; `shouldRetryQuery` retries (at most 2 failures) only network errors, 502 and 504, never other statuses or cancelled queries. Nav counts, ineligible-soldier count and algorithm jobs no longer refetch on every route change; notification and bug-report count polling runs only while the tab is visible; Team page no longer refetches hierarchy branches when hidden.
- Mutation invalidation fixes that the longer staleTime exposed: ineligible count after excusal/attendance writes, all algorithm job-list variants after job changes and shift-modal reruns, nav badge counts after approvals/swap/hakpaza actions, bell unread count from the notifications page, duty-types cache from the inline duty-type modal, and every data family an import confirm can change (new `utils/invalidateImportedData.ts`, also refreshes the import wizard pickers). Home: duplicate level-types / duty-types requests removed; lower command panels deferred to a second idle window.
- Auth (`api/client.ts`, `auth/AuthContext.tsx`): session restore and request-path 401 handling share one in-flight token refresh; an epoch guard discards a refresh that resolves (or fails) after the token was replaced, so it can neither overwrite nor expire the newer session; `/auth/refresh` times out after 15 s (`REFRESH_TIMEOUT_MS`); a login submitted during session restore is no longer dropped; the React Query cache is cleared whenever the signed-in identity changes.
- Route-level code splitting (`App.tsx`): pages are `React.lazy` except the two eager entry pages; `Suspense` fallback is the new `components/RouteFallback.tsx`, which keeps the app shell (nav) visible while a route chunk loads. `vite.config.ts` adds rolldown `codeSplitting.groups` (preload-helper, react-vendor, mermaid, react-pdf, recharts, fullcalendar, katex JS-only, markdown) so heavy libraries never land in the entry. New `chunkLoadRecovery.ts` reloads once on a failed lazy chunk load (no reload loop when storage is unavailable).
- Early paint and fonts: `index.html` paints a loading status before JS runs (local-font placeholder, no web font before boot); Heebo self-hosted under `public/fonts/` (all subsets the Google stylesheet served: hebrew, latin, latin-ext, math, symbols; OFL license included), Google Fonts link and preload dropped.
- nginx (`deploy/nginx.conf`): `http2 on` (nginx >= 1.25.1 syntax), gzip level 6 (+ `gzip_vary`, `gzip_min_length 256`, JS/SVG types), a `map $uri $static_cache_control` applied by a server-level `add_header Cache-Control` (`/assets/` and `/fonts/` immutable for a year, other static extensions as before, everything else incl. `index.html` `no-cache`, `/api/` untouched); the nested static `location` with its own `add_header` was removed so the server-level security headers now also apply to static files. `types` adds `.mjs` -> `text/javascript` and `.ttf` -> `font/ttf`. New `deploy/tests/test_nginx_static_types.sh` checks the served MIME types against a built dist.
- Backend: `services/ineligible_soldiers.py` loads only the eligibility columns, evaluates weapon-duty eligibility once per soldier profile, and coalesces concurrent identical computations through new `services/single_flight.py` (75 ms join window). `services/commander_dashboard.py` reads alert soldiers as rows and filters by a scope subquery instead of id arrays (exemption-alert statement now carries the soldier name). `error_logging.py` labels deliberate 5xx `HTTPException`s with their real status. `algorithm_bridge.py` keeps the Redis cancel-flag watcher alive on Redis errors. New read-only script `app/scripts/profile_ineligible_count.py` (phase profiler).
- Auth backend: refresh tokens carry `jti` and `sid` (`auth/jwt_tokens.py`; `sid` inherited on rotation). New `auth/refresh_revocation.py` stores revoked `jti`/`sid` in Redis; `/auth/refresh` rejects them with 401 `token_revoked`. `/auth/logout`, successful `/auth/login` and `/auth/register` revoke the presented refresh cookie. `redis_client.get_redis()` now has 1 s socket and connect timeouts.
- Migration: none.
- API: new public setting `errors.log_source_configured` (bool) on the public-settings endpoint; the frontend skips error-log calls when it is false (missing = unknown, not unconfigured). Logout/login/register revoke the presented refresh cookie; refresh tokens now include `jti`/`sid` claims; tokens issued before this change carry neither and stay valid until expiry (or a `token_version` bump).
- Config/ops: nginx changes need ops review before deploy (HTTP/2 behind the load balancer, gzip CPU cost at level 6, interaction with any `limit_req`). New Redis keys `auth:refresh:revoked:jti:*` / `auth:refresh:revoked:sid:*` (TTL = token remaining life / `refresh_token_days` + 300 s). Revocation fails open when Redis is unreachable.
- Gotchas: with the 30 s global staleTime, every new mutation must invalidate the query keys it affects (or set `staleTime` explicitly). The ineligible-count single-flight is per process, not cross-replica. The slowapi rate limiter opens its own Redis connection and has no socket timeout. Pre-existing: a non-remember-me session cookie becomes persistent after the first refresh. Benchmark JSON under `docs/benchmarks/data/` (this branch plus the stacked transparency branch add ~19 MB in 31 files).
- Tests: `lazyRoutes.test.tsx`, `buildChunks.test.ts`, `chunkLoadRecovery.test.ts`, `selfHostedFonts.test.ts`, `api/client.test.ts` (shared refresh, epoch guard, timeout), `queryRetry` and invalidation tests per page; backend `test_refresh_revocation.py`, `test_single_flight.py`, `test_ineligible_soldiers_count_parity.py` (count == list parity, guards new requirement flags), `test_public_settings.py`, `test_redis_client.py`, `test_error_logging.py`, commander-dashboard and algorithm-bridge additions.
- Type: perf

### Transparency bounded continuation and keyset read model (`feature/transparency-bounded-continuation`, 2026-10-05)
Docs: docs/superpowers/plans/2026-09-30-scale-page-optimizations.md, docs/benchmarks/2026-09-29-scale-20k-pages.md (no dedicated keyset spec/plan was written)
- Transparency source tracking: a sequence plus a transactional xid journal replace the old singleton revision row, so transparency cursors are invalidated on any source-table change without serializing writers (`fix: serialize score projection freshness repairs`, `feat: invalidate transparency cursors on source changes`).
- `/scoring/transparency/page`: bounded snapshot pages persisted server-side (`services/transparency_page_store.py`, cursor purpose `transparency-page-v2`, `409 stale_cursor` / `400 invalid_cursor`); plus a keyset fast path backed by a versioned read model (`services/transparency_read_model.py`) refreshed by a new background worker (`transparency_read_model_worker.py`, started from `main.py` lifespan, drained on shutdown, skipped when disabled).
- `/soldiers/roster`: an empty `role_order` is treated as unset.
- Migration: `20261004_src_gen` (revises `825b49ff9b2c`): drops the `bump_transparency_fairness_revision` triggers and `transparency_fairness_revision` table, adds `transparency_source_generation_seq` + `transparency_source_change_journal` with DML/TRUNCATE triggers on 14 source tables. `20261004_page_snap`: `transparency_page_snapshots` + `transparency_page_snapshot_rows`. `20261005_read_model`: `transparency_read_model_generations` + `transparency_read_model_rows`.
- API: keyset path on `/scoring/transparency/page` behind `TRANSPARENCY_READ_MODEL_ENABLED` (default false); with the flag off, keyset cursors return `409 stale_cursor` and the snapshot path is used.
- Config/ops: new env var `TRANSPARENCY_READ_MODEL_ENABLED` (default `false`) also gates the read-model worker. Journal rows are not pruned yet (see migration comment).
- Gotchas: sequence advances are non-transactional, so a rolled-back writer can conservatively invalidate a cursor. Performance benchmarks under `backend/tests/performance/` (not part of the fast suite).
- Tests: integration tests for keyset API, page snapshots, page-store capacity/chunks/cleanup/concurrency, read model, scale cursor revisions; unit tests for the worker and benchmark helpers.
- Type: feature

### Faster eligibility groups: lightweight groups endpoint, top/bottom ranked list (`perf/why-received-and-qualification-groups`, 2026-10-09)
Docs: none
- Backend: new `services.scoring.eligibility_groups(session)` backs `GET /api/scoring/eligibility-groups`. It loads `Soldier` with `load_only(...)` of just the columns the duty-type requirement checks read, skips the burden-share pass and names, and leaves exempt-from-all soldiers out of the component build. Same groups and order as `fairness_components()` (covered by a projection-equivalence test).
- Backend: `algorithm_bridge.exempted_duty_type_ids_by_soldier(..., soldiers=None)` takes an already-loaded roster; `fairness_components()` passes its visible soldiers instead of re-reading every `Soldier` row.
- Frontend: `FairnessComponentsCard` ranked list opens as the top 30 and bottom 30 (`CANDIDATE_EDGE_ROWS`) with the middle collapsed; "טען עוד מלמעלה" / "טען עוד מלמטה" buttons (up/down chevrons, stacked above/below the hidden-count label) each load `CANDIDATE_LOAD_STEP` (50) from their end. When nothing is hidden the list is one plain list and both buttons go away. Ranks stay real ranks. New name search over the whole group; the same split applies to its matches. List state is keyed to group/sub-group filter/query, so changing any of them resets to 30/30. Rank column widened 16px -> 36px (4-digit ranks overlapped names).
- No API shape changes; no migrations.
- Measured at 20k soldiers (`justice_scale_20k_scale`): `eligibility-groups` 2159 -> ~855 ms p50; `fairness-components` ~2234 -> ~1970 ms p50 (still dominated by the full `Soldier` ORM load and burden shares); opening a 5,000-soldier group (mocked response; the seed's largest real group is only 192 soldiers) ~1.7 s / 40k DOM nodes -> ~0.2 s / ~890 nodes.
- Gotchas: `fairness-components` is still ~2 s and 3.4 MB (the seed has 20,000 exempt soldiers); a cache or read model would be the real fix. Pressing the load buttons until the middle is gone renders every row of the group again. Homepage "למה קיבל/ה" was not reproducible as slow server-side (explanation endpoint ~14 ms, modal ~100 ms for admin); the visible delay there is the page's own reads (`assignments/effective` ~4.9 s at 20k) and is untouched.
- Tests: `test_eligibility_groups_service_matches_fairness_components_projection`; `FairnessComponentsCard.test.tsx` covers top/bottom split, both load buttons, merge into one list, small groups, search (rank preserved, reset, no-match).
- Type: perf

## 2026-10-04 (released, third cut)

### Native dev stack runs storage; roster 400; inline tree soldiers; i18n polish (`fix/dev-stack-roster-tree-i18n`, 2026-10-04)
Docs: none
- `dev.ps1` (native mode): generates `deploy/seaweedfs/secrets` + certs on first run via `scripts/dev-certs.ps1` (previously `docker compose` failed on the missing env files), regenerates a SeaweedFS cert that lacks the `localhost` SAN, and starts SeaweedFS + S3 proxy, `seaweedfs-init`, `file-authorization`, `file-gateway` through compose, staged with `--no-deps` (file-gateway `depends_on: backend` would otherwise start the Dockerized backend on :8000). Sets `COMPOSE_FILE` to include the new overlay and exports `STORAGE_*` (from `api.env`), `STORAGE_ENDPOINT_URL=https://localhost:19443`, `STORAGE_CA_BUNDLE_PATH` and `VITE_FILE_GATEWAY_URL=http://localhost:18080` for the native backend / Vite.
- New `docker-compose.dev-native.yml` overlay: publishes the S3 proxy (`127.0.0.1:19443`) and file-gateway (`127.0.0.1:18080`); SeaweedFS also joins `default` because `storage` is an internal network.
- `scripts/dev-certs.ps1`: SeaweedFS cert SANs are now `seaweedfs` + `localhost`.
- API: `GET /api/soldiers/roster` treats an empty `role_order` as unset (was 400 `invalid_role_order`); malformed non-empty values and `sort=role` without an order still 400. Regression test in `tests/integration/test_soldiers_api.py`.
- Frontend: `LazyHierarchyTree` lists each expanded node's direct soldiers inline (`NodeSoldiers`, infinite query nested under `hierarchyBranches(scopeKey)` so existing resets refresh it); leaf units with soldiers are expandable; drag handles use `touch-none`; `PopoverDropdown` gained an optional `icon` prop (tree actions menu uses lucide `EllipsisVertical`).
- Frontend: Transparency fairness data is a collapsible panel (`נתונים בחלוקה לקבוצות משרתים`); the group-rank cell shows `—` (not `פטור`) until fairness data is loaded; dashboard alert text `תאריך <label> אחרון לא מעודכן`.
- i18n: added missing he/en keys (`team.select_node_from_tree`, `team.soldiers_in_node`, `home.*` section labels, `soldier_profile.food_constraints_tooltip`); user-visible "HR" -> "משא"ן" (he.json notification types, `person_sync` anomaly notification title).
- Gotchas: Windows/WinNAT may reserve host ports (8xxx); the overlay uses 19443/18080 for that reason. The fairness query is still lazy (only fetched when the panel is opened), so group rank needs the panel open.
- Tests: new roster regression test; `LazyHierarchyTree.test.tsx` updated for inline soldiers.
- Type: fix

## 2026-10-04 (released, second cut)

### Fix timezone flake in EntriesExitsPanel release-date test (2026-10-04)
Docs: none
- `EntriesExitsPanel.test.tsx` computed "today" with `toISOString()` (UTC) while the component uses the local day (`todayIso`), so the test failed between local midnight and the UTC offset (00:00-03:00 in Israel). It now uses local `getFullYear/getMonth/getDate`.
- Type: fix

## 2026-10-04 (released)

### Split dev and user-facing changelogs (`chore/split-changelogs`, 2026-10-04)
Docs: none
- `merge-worktree-to-dev` skill: new Step 5 adds an entry here (under `## Unreleased`) for every merge/PR into `dev`; later steps renumbered.
- `release-dev-to-master` skill: Step 4 now writes the user-facing `frontend/CHANGELOG.md` from this file plus the plan/spec docs on each `Docs:` line (Features/Fixes, "Why:" for non-obvious changes), then renames `## Unreleased` to the release date.
- `CLAUDE.md`: "Changelog" section replaced by "Changelogs" describing both files.
- Type: chore

### Backfill: work merged to `dev` before this changelog existed (2026-09-27..2026-10-04)
Docs: docs/superpowers/specs/2026-10-02-oidc-sso-ad-username-design.md, docs/superpowers/specs/2026-10-02-database-concurrency-audit-design.md, docs/superpowers/specs/2026-09-27-s3-compatible-file-storage-design.md, docs/superpowers/specs/2026-09-29-scale-20k-page-performance.md, docs/exchange-calendar-sync.md
- OIDC SSO: config + protocol service, start/callback endpoints, stable issuer/subject identity storage, first-link matching; single-use registration context (no invite code); mador-level approval for SSO sign-ups; callback code/state kept out of logs. Migration adds `ad_username` and unique normalized email constraints with preflight; identity migration heads merged. Identity resolution service, HR identity conflicts + admin endpoints/tab.
- Concurrency audit (C1-C18, M1-M4, I1, J2, O1, ...): `FOR UPDATE` / conditional UPDATE / global lock ordering across swaps, imports, range requests, projections, algorithm jobs, tokens, outbox, workers; `recheck_assignments` no longer commits mid-transaction. Deterministic PostgreSQL race helpers + reproduction tests per fix. Report under docs/superpowers/reports.
- Storage: private S3 adapter (MinIO local), resumable migration with verification, durable uploads in object storage, authorized streaming gateway, encrypted DB backups/WAL archives.
- Exchange calendar: projection, outbox, worker (own process), admin sync status, deploy overlay; dismissals synced.
- Scale (20k soldiers): seed command + profiles; SQL-side counts for nav badges, paged/lazy hierarchy selector, deferred secondary reads, cursor paging bound to data revisions, narrower readiness/projection reads.
- CI: GitLab pipeline (validation, tests, e2e, image build); Keycloak-backed OIDC e2e stack and runner.
- Type: feature
