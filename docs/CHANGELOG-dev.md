# Dev Changelog

Developer-facing log of everything merged into `dev`, written for people working
on this codebase (modules touched, migrations, API/schema changes, config,
gotchas). Entries are added by the `merge-worktree-to-dev` skill; the
user-facing `frontend/CHANGELOG.md` is derived from this file at release time
by `release-dev-to-master`.

## Unreleased

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
