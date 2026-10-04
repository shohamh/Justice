# Dev Changelog

Developer-facing log of everything merged into `dev`, written for people working
on this codebase (modules touched, migrations, API/schema changes, config,
gotchas). Entries are added by the `merge-worktree-to-dev` skill; the
user-facing `frontend/CHANGELOG.md` is derived from this file at release time
by `release-dev-to-master`.

## Unreleased

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
