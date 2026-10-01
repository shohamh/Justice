# SDD ledger -- plan: docs/superpowers/plans/2026-09-27-s3-compatible-file-storage.md

Worktree: C:\Users\Shoham\.paseo\worktrees\1n26l98r\s3-object-storage
Branch: feature/s3-object-storage
Starting implementation commit: 57417f8d
Plan workspace: .superpowers/sdd/2026-09-27-s3-compatible-file-storage

## Preflight scan: shared task pairs

| Tasks | Shared output/input | Finding and ruling |
|---|---|---|
| 1 and 3 | Storage protocol, settings, S3 adapter consumed by backfill | Ordered dependency is clear: Task 1 defines the adapter; Task 3 uses it. |
| 1 and 4 | Storage interface and settings consumed by routes/services | Task 4 follows Task 1; route adapters must use only the typed storage API. |
| 1 and 5 | Storage adapter consumed by the gateway | Task 5 must use the get-only identity and validated managed keys; no circular dependency. |
| 1 and 8 | Typed storage settings consumed by Compose environment wiring | Task 8 follows and wires the Task 1 setting names without weakening HTTPS verification. |
| 2 and 5 | Task 2 certificate SANs/CA consumed by gateway and authorization service | Task 2 establishes local identities; Task 5 configures mTLS against those exact identities. |
| 2 and 8 | docker-compose.yml and test_compose_storage.py; Task 2 creates test, Task 8 extends it | Task 2 covers MinIO/TLS/IAM in RED/GREEN; Task 8 adds gateway/proxy assertions in the same test file. |
| 3 and 4 | Metadata and StorageDeleteOutbox consumed by upload/deletion paths | Task 3 owns schema/outbox; Task 4 records object keys transactionally and preserves legacy reads. |
| 3 and 5 | Storage metadata consumed by authorization decisions | Task 5 resolves exact DB relationships and metadata after Task 3; auth never accepts caller keys. |
| 3 and 8 | Migration/reconciliation commands consumed by operations and E2E | Task 8 documents and invokes Task 3 commands; names/options must match implementation. |
| 4 and 5 | Upload/resource relationships consumed by authorization matrix | Task 4 preserves ownership links; Task 5 binds each route ID to those exact records. |
| 4 and 6 | Upload/download API contracts and filenames/content types | Task 6 uses authenticated Blob requests and surfaces route errors; no S3 URL/key enters UI. |
| 5 and 6 | Known gateway routes and bearer-token contract | Task 6 must call only Task 5 routes through Justice proxy and use the authenticated API client. |
| 5 and 8 | Gateway/authz entrypoints, TLS config, Compose services | Task 8 wires the separate processes with Task 5 contracts and Task 2 certificates. |
| 6 and 8 | frontend/vite.config.ts download proxy prefix | Task 8 routes the same public prefix used by Task 6; internal auth path remains private. |
| 7 and 8 | deploy/docker-compose.prod.yml, production env example, deploy README | Task 7 adds encrypted backup/recovery design; Task 8 integrates it with storage deployment docs without exposing recovery identity to runtime. |

## Preflight scan: task self-consistency

| Task | Findings |
|---|---|
| 1 | Test-first sequence, S3 TLS/SSE settings, opaque-key validation, and adapter operations align. |
| 2 | Test target was missing from Files although Step 1 requires tests. Added backend/app/storage/tests/test_compose_storage.py; Task 8 extends it. Root docker-compose.yml and .env.defaults exist. |
| 3 | Model metadata, idempotent backfill, read-back hash verification, and outbox retry are consistent. Unsupported/malformed legacy payloads must block cutover and retain source bytes. |
| 4 | Route/service scope covers each durable application file class, validation before persistence, object-first writes, rollback cleanup, legacy reads, and Excel parsing. |
| 5 | Six browser-download classes match the spec matrix; JSON mirror recovery remains maintenance-only. Bearer auth, mTLS, audit, and object reads are ordered to deny before S3 access. |
| 6 | UI surfaces map to authenticated file APIs; frontend Blob URLs are local-only and must be revoked. |
| 7 | Production base/WAL backup encryption and recovery identity are separate from normal app runtime; backup/restore scripts must remain paired. |
| 8 | Compose/proxy/dev launcher, migration docs, and E2E are final integration work and consume the earlier task contracts. |

## Rulings

- Ruling: Replaced the stale spec requirement that scanning pass before download with bounded format validation and an explicit statement that malware scanning is not provided. Reason: the user explicitly removed ClamAV; the approved spec and plan must not retain a contradictory scan gate. Cost if wrong: uploaded malware will not be detected by this system, so downstream consumers must continue treating files as untrusted. Recorded in commit 8d471631.
- Ruling: Added Task 2's missing Compose test target and assigned Task 8 to extend that file. Reason: Task 2 mandates RED/GREEN tests but named no test file; sharing the config test is the narrowest consistent ownership. Cost if wrong: task boundaries may need reshaping if infrastructure tests become coupled; reviewers must verify each task's assertions remain scoped.

## Task checklist

- [x] Task 1: Build the shared S3 storage package
- [ ] Task 2: Add local MinIO, TLS certificates, and least-privilege identities
- [x] Task 3: Add file metadata, transactional delete outbox, and restartable backfill
- [x] Task 4: Move upload, parse, and bug-report recovery flows to object storage
- [x] Task 5: Add the private authorization service and streaming download gateway
- [x] Task 6: Route all browser downloads through the gateway
- [x] Task 7: Encrypt PostgreSQL base backups and WAL archives
- [ ] Task 8: Wire Compose, dev launcher, and production proxy; finish migration operations and E2E checks

Task 1: dispatched /root/storage_task_1; BASE 57417f8d4077e9218c4bebd4389c9daf514d16bf; brief and report paths are plan-scoped.

Task 1: implementer DONE; commit d84fbd02; RED exposed missing modules/settings (initial pytest import-path issue recorded); GREEN 31/31 with PYTHONPATH=.; Ruff clean. Review package: review-57417f8d..d84fbd02.diff.

Task 1: review found settings.py:66 accepts HTTPS endpoint query/fragment values, which may leak through boto3 error URLs; fix required. Reviewer cannot verify IAM, production provider SSE enforcement, or real MinIO TLS identity here; these remain assigned to Tasks 2 and 8 plus production preflight, not dismissed.

Task 1: fix round 1/5 started from d84fbd02; original implementer resumed.

Task 1: complete commits d84fbd02..7d0c59a5; fix-only independent re-review PASS for spec compliance and task quality. Endpoint query/fragment rejection verified by implementer RED/GREEN; focused suite 33 passed, Ruff clean. Reviewer still cannot verify runtime IAM, production SSE policy, or live TLS; assigned to Tasks 2/8 and production preflight.
Task 2: dispatched brief .superpowers/sdd/2026-09-27-s3-compatible-file-storage/task-2-brief.md; implementation committed in f4555791 and reviewer fixes in 3832b9ce.

Task 2: implementation committed as f4555791d3460e9c2800039b0cc14adf875c97eb; report task-2-report.md. RED: 7 expected failures before implementation. GREEN: focused suite 7 passed, Compose config --quiet passed, bash -n passed, git diff --check passed. dev-certs.ps1 generated ignored random identity env files and CA-signed SAN certs; OpenSSL chain/hostname checks passed for minio, gateway, file-authorization, proxy; gateway cert has serverAuth and clientAuth. Live startup/IAM checks blocked: Docker Hub denied minio/minio and official Quay returned 401 for quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z. Compose keeps official Quay defaults with MINIO_IMAGE/MINIO_MC_IMAGE overrides; no unofficial image substituted. Independent review pending; live real-IAM/init-repeat/network checks are unresolved due registry access.


Task 2 security ruling from review: MinIO server necessarily receives generated `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` env values; otherwise MinIO falls back to `minioadmin`. Same random pair is mounted to MinIO server and one-shot initializer in separate ignored env files. The initializer is the only root admin client; API, gateway, and maintenance never receive root credentials. Spec and plan now record this boundary.
Task 2 review fix implementation: added regression assertions for separate root env, configurable bucket rendering, and changed policy source rerender; implementation validates bucket names, substitutes policy templates, and unconditionally re-applies same-name policies (failure remains fatal). RED: expanded suite showed 5 assertion failures; changed-policy test fails against prior skip-existing logic (1 failed). GREEN: 9 focused tests passed, Compose config, PowerShell helper, shell syntax, root-pair equivalence, and TLS SAN checks passed. Report task-2-report.md updated. Independent re-review PASS: all three implementation findings resolved. Live S3 operations remain partial/unverified because the official Quay image pull returns 401.

Task 2 review-fix commit: 3832b9ce3b232b476a772c4bc496b5734690c1c6; worktree clean after commit; independent re-review PASS. Task 3 may proceed; MinIO live verification remains unverified due to Quay 401.

Task 2 generated brief aligned with approved spec/plan credential boundary. Review status: PASS for the three findings. Live MinIO health, TLS-in-container, IAM allow/deny, repeat init, and host-port denial are PARTIAL/UNVERIFIED because official Quay image pull returned 401; static topology/certificate/policy checks passed.


Task 3: implementation complete; commit `3fe72d5bfa5ca71b90272fa951b587ac75be3651` (`feat: add resumable file storage migration`). RED: exact planned tests failed collection because backfill/reconciliation modules were missing. GREEN: `pytest app/storage/tests/test_backfill.py app/storage/tests/test_reconciliation.py -q` 14 passed; `pytest app/storage/tests/test_s3.py -q` 9 passed; Ruff passed with only existing UP042 enum style warnings excluded; `git diff --check` passed; isolated Task 3 PostgreSQL Alembic SQL generation passed (63 lines); both maintenance CLIs `--help` passed. Full offline Alembic traversal stops in unchanged ba8eaf68d98c because it calls fetchall() on a static result. No live PostgreSQL or MinIO/S3 behavior verified; Task 2 Quay 401 remains the provider blocker. Report: task-3-report.md.


Task 3 review finding: Medium, existing `storage_key` references were skipped, allowing false cutover readiness. Fix committed as `b0afef16e6f67e022c92b2ef187ec8df41dff0a2`. RED: `pytest app/storage/tests/test_migration.py -q` 3 failed (missing object, invalid prefix were not blocking, corrupt body was not read). GREEN: same suite 4 passed; planned backfill/reconciliation suite 14 passed; S3 adapter suite 9 passed; scoped Ruff and `git diff --check` passed. Existing refs now get key namespace validation, HEAD metadata checks, and streamed body size/hash verification; any failure blocks cutover. Independent re-review pending. Do not start Task 4 until review passes. Report updated: task-3-report.md. Live PostgreSQL/MinIO/S3 remains unverified.


Task 3 follow-up review finding: same-class references could point to another row's object UUID. Fix committed as `0481ad4432d074d4272fcac337c553dd0a3b9186`. RED: `pytest app/storage/tests/test_migration.py -q` 5 failed because the iterator/verifier lacked owner UUID. GREEN: migration regression suite 6 passed; planned backfill/reconciliation 14 passed; S3 adapter 9 passed; scoped Ruff and diff check passed. Every reference now carries its row UUID and must equal `make_object_key(file_class, row_id)` before any S3 access; mismatch blocks cutover. Final re-review PASS on 2026-09-27; Task 3 complete. Live provider behavior remains unverified. Report updated: task-3-report.md.

Task 3: implementation commits 3fe72d5b + fixes b0afef16 / 0481ad44; evidence commits 475ce475 / 71460590 / a8cc3759. Independent final re-review PASS. Tests: migration 6/6, backfill/reconciliation 14/14, S3 adapter 9/9; scoped Ruff, diff checks, isolated Alembic SQL generation pass. Existing references are verified for canonical owner key, metadata, size, and streamed hash before cutover. Live PostgreSQL/MinIO/S3 remains unverified; full-history offline migration command hits a pre-existing static-result error in ba8eaf68d98c.
Task 4: complete; implementation cb52cb7e, review fixes 7b8ff5d0 and a7e2dc33. Final independent re-review PASS with cleanup-grace caveat (worker termination may add up to 5s after the parser deadline). Full suite 127 passed, 1 skipped; live MinIO/S3 unverified and Windows XLSX requires bounded Linux container.

Task 4: implementation complete; focused fake-storage route/service suite passed with `python -m pytest app/routes/tests/test_exemption_requests_files.py app/routes/tests/test_exemptions.py app/routes/tests/test_gimelim_attachments.py app/routes/tests/test_bug_reports.py app/routes/tests/test_import_session_files.py app/services/tests/test_import_sessions_service.py -q -n0`; scoped Ruff passed (`UP017` ignored for existing timezone style); diff/encoding checks passed. Live MinIO/S3 remains unverified because the official Quay image pull returned HTTP 401. Report: task-4-report.md. Commit: `feat: store durable uploads in object storage`.

Task 4 independent review fixes: fail closed if the OS memory cap is unavailable or setrlimit fails; drain the parser pipe result before joining the worker; validate XLSX declared MIME before reading/parsing/storing; recovery verifies referenced screenshot key, bounded PNG bytes, size, and SHA-256. RED/GREEN and verification: `task-4-report.md`; focused suite 125 passed, 1 skipped (native Windows parser integration), 2 dependency deprecation warnings. Native Windows Excel parsing requires the bounded Linux container path.

Task 4 re-review follow-up: complete multiprocessing `recv()` is bounded by the remaining parser deadline using a reader thread; timeout terminates the worker and closes the pipe. Parser memory-cap unavailability is HTTP 503 (not a user input 400). RED/GREEN tests cover a partial response that stalls and worker termination, plus capability status. Full focused suite: 127 passed, 1 skipped, 2 dependency warnings; scoped Ruff, diff, and encoding checks passed. Task 4 report updated.

Task 5 implementation complete in the feature worktree; final independent scoped re-review PASS on 2026-09-27. RED: `python -m pytest app/file_authorization/tests/test_policies.py app/file_authorization/tests/test_routes.py -q` failed collection with 2 expected errors for not-yet-created auth schema/main modules. GREEN: `python -m pytest app/file_authorization/tests app/file_gateway/tests -n0 -ra --tb=short` passed 31 tests, 1 deprecation warning (2.24s); scoped Ruff and `git diff --check` passed. Current medical-viewer access for exemption-request files is tested allow/deny. Auth `run()` requires client certificates and is launchable with `python -m app.file_authorization.main`; Task 8 owns Compose/proxy wiring and deployed mTLS verification. Live MinIO/S3 remains unverified because the official Quay image pull returned HTTP 401. Report: task-5-report.md.

Task 5: fix round 1/5 implemented after review (two Important lifecycle findings, one Minor request-ID trace finding). Real ASGI disconnect and late open_read timeout tests were RED then GREEN; full auth/gateway suite 33 passed, 1 installed-Starlette multipart deprecation warning; scoped Ruff and diff check passed. Fix commit d507fefb + 2c40ca27 and scoped re-review PASS. The warning originates from installed Starlette 0.37.2, while uv.lock resolves Starlette 1.3.1; no suppression or dependency downgrade.
Task 5 fix round 1 self-review follow-up: guard lease close with a thread lock and invoke background cleanup on the event loop; concurrency regression added. Final lifecycle suite 3 passed and auth/gateway suite 34 passed, each with the same installed-Starlette warning; scoped Ruff and diff check passed. Scoped re-review PASS: all findings addressed, no new Critical/Important breakage.
Task 5 fix round 2/5: Minor local Starlette warning addressed with exact pytest filter for PendingDeprecationWarning message and starlette.formparsers module. Locked offline uv run blocked by uncached botocore==1.43.103. Focused auth/gateway suite 34 passed with no warning summary. Temporary three-case warning probe showed other message, module, and category warnings remain visible; probe removed. No dependency declarations changed. Independent scoped re-review PASS: exact warning filter verified; no new breakage.

Task 5: complete commits ca398445 + d507fefb + 2c40ca27 + 87674f98; fix rounds 1 and 2 independently re-reviewed PASS. Auth/gateway tests 34 passed without warnings; scoped Ruff and diff checks passed. mTLS startup enforces CERT_REQUIRED; Compose and deployed listener verification remain Task 8. Live MinIO/S3 remains unverified due to the official Quay 401.

Task 5 out-of-scope observation for final whole-branch review: the syncio.to_thread(body.read, ...) worker can persist after its 8-second wait times out until the underlying read returns. The response closes the body and releases its lease; evaluate whether the storage socket timeout is sufficient or if worker lifecycle needs a separate fix.

Task 6: dispatched to fresh implementer; initial dispatch base 4921e52e, actual implementation base c806ee6c; brief .superpowers/sdd/2026-09-27-s3-compatible-file-storage/task-6-brief.md.

Task 6 fix round: added attachment listing/download for existing primary.dismissals rows marked is_gimelim, preserving dismissal IDs per attachment; query-item effects now revoke screenshot Blob URLs for disappeared IDs in MyReports and admin. Regression RED: existing dismissal test failed when no list call occurred; GREEN: focused suite 11 files, 162 passed. Frontend typecheck and lint passed. Gimelim metadata route/test previously passed 2/2 including unrelated-soldier 403. Actual Task 6 implementation base: c806ee6c. Commit pending.

Task 6 review fix round 1: independent review found a medium load-bearing Gimelim UI defect: on failed attachment upload the modal sets the failure message, then setting completedDismissalId triggers the attachment-list effect, whose setAttachmentError(null) clears the message before the user can see it. Regression RED: DismissalModal suite 1 failed/6 passed with the upload failure alert absent after list refresh. Fixed by preserving attachmentError across list refresh; GREEN: DismissalModal suite 7/7, npm run typecheck passed, npm run lint passed. Fix commit pending.

Task 6: complete (implementation 845d9f9d, review fix 02b47dab; scoped review PASS). Frontend tests: 11 files, 162 passed; typecheck and lint passed. Gimelim attachment listing/download is permission checked and the upload failure alert remains visible across list refresh. Blob URLs are revoked on resource changes and unmount.


Task 7: complete. Shell syntax passed for all deployment and backup scripts; recovery acceptance passed 3/3. The source deploy/restore-pitr.sh completed a live PostgreSQL PITR run in an isolated recovery project. The restored marker table contained before_base and keep with no post-target marker. Recovery database containers were stopped after verification; volumes preserved.

Task 8: partial. Added isolated authz/gateway Compose wiring, mTLS certificate generation, public download proxy routes, production service wiring, migration operations docs, and anonymous-denial browser test definitions. docker compose config --quiet, 11 Compose configuration tests, frontend typecheck/lint, PowerShell AST parsing, git diff --check, and Playwright discovery (12 desktop/mobile cases) passed. Full Compose E2E is blocked: official quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z pull returned 401 UNAUTHORIZED. A reduced app build also failed because the Docker build cannot reach PyPI for setuptools>=68; no Compose services started. Browser runtime had no connected browser sessions, so no visual/browser execution is claimed. Re-run Task 8 E2E and complete final review after registry/PyPI access is available.Task 7 follow-up review: added a failure-exit notification so base backup and later WAL checks alert through the redacted HTTPS notifier. Regression test deploy/tests/test_backup_alert.sh passed using local docker/curl shims; recovery acceptance passed 3/3 again; bash -n and git diff --check passed.


Task 8 continuation (2026-09-28): Rechecked registry/cache/mirror availability without printing credentials. No local MinIO image, no Docker credential-helper registry entries, no PIP_INDEX_URL/proxy environment setting, and no cached setuptools wheel. Retried `docker pull quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z`; registry manifest HEAD returns HTTP 401 Unauthorized. `docker compose config --quiet` exits 0. The previous backend PyPI build failure is no longer reproducible: `docker compose build backend` succeeded and produced `s3-object-storage-resume-backend:latest` after downloading requirements. The production backend image does not include pytest; a no-deps one-off run ended with `No module named pytest`, and no application services started. Coordinating agent reports the local focused backend suite and frontend all 208 files / 1,573 tests, typecheck, and lint pass. The live Compose/browser journey remains blocked by the unavailable official Quay MinIO image; Task 8 stays partial. See task-8-report.md. User-local deploy/.env.production untouched.

Task 8 source-build investigation: independently pulled `minio` and `minio-init`; both official Quay images return 401 (server `quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z`, client `quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z`). Upstream MinIO's signed-artifact Dockerfile.release verifies MinIO and mc binaries with minisign and uses UBI micro, but official `dl.min.io` probes for MinIO binary, MinIO signature, and mc binary return HTTP 410; UBI registry manifest returned 200. Upstream `make docker` depends on `FROM minio/minio:latest`, and upstream mc Dockerfile installs `@latest`, so neither upstream path works reproducibly here. A local build needs pinned upstream Go source for both components plus verified tag authenticity and Go base/module access; not yet established. No Compose edit made. A short-lived no-deps backend run exited because the production image intentionally lacks pytest; no application services were started.

### Task 8 continuation   pinned source provenance (2026-09-28)

- GitHub API verified mc tag RELEASE.2025-04-16T18-13-26Z as a signed annotated tag (Minio Trusted, valid), targeting verified commit b00526b153a31b36767991a4f5ce2cced435ee8e.
- MinIO tag RELEASE.2025-10-15T17-29-55Z is lightweight and resolves to unsigned commit 9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a; GitHub API reason: unsigned.
- Official Go builder pull succeeded (Docker Hub golang:1.24.8-alpine; digest recorded in task-8-report.md). Root scratch build using Go 1.24.13 failed during proxy.golang.org downloads with TLS handshake timeouts and unexpected EOF. Host lacks Go and GPG; direct Go checksum database probes returned HTTP 400.
- No Compose edits were made. Task 8 remains partial pending official MinIO availability or an approved, verified source path.


Task 8 continuation (2026-09-28): Fixed final spec-review gaps in the working tree. The authz service now reaches Postgres on a separate internal authz-db network; only authz and the download gateway share file-authz in development and production. Added deployment instructions for a distinct, bucket-scoped maintenance identity, preflight/migration commands, and 15-minute reconciliation. Added deploy/reconcile-file-storage.sh for a flock-serialized host cron schedule. Regression checks: `python -m pytest app/storage/tests app/file_authorization/tests app/file_gateway/tests -q` passed (93 tests; pytest showed 77% then 100%); `docker compose config --quiet`, `git diff --check`, and `bash -n deploy/reconcile-file-storage.sh` passed. Compose end-to-end, browser runtime, real MinIO TLS, and IAM allow/deny remain blocked/unverified: the official Quay images return 401 and MinIO Community Edition is now source-only upstream. Task 8 remains partial. Fresh standards review still flags the pre-existing UI i18n/file-size issues in DismissalModal and inline text in related UI files; these were not changed in this storage continuation. Local `deploy/.env.production` was not opened or modified.


Task 8 continuation (2026-09-28): Resolved the standards review finding for hard-coded file-transfer UI messages by moving download/upload strings into `frontend/src/i18n/he.json` and wiring DismissalModal, ExemptionsPanel, and ImportSessionReviewPage through `t()`. Updated the dismissal upload-failure assertion for the i18n key. Verification: `npm run lint` passed; focused DismissalModal suite 7/7; full frontend suite 208 files / 1,573 tests passed; `git diff --check` passed (only CRLF normalization warnings). The separate low-priority component-size observation remains. Task 8 stays partial because MinIO cannot be obtained here, so no live Compose or browser-to-S3 verification is claimed.

Task 8 provider acquisition check (2026-09-28): Tried Docker Hub alias `minio/minio:RELEASE.2025-04-22T22-12-26Z`; registry returned `pull access denied` / repository does not exist. Thus the recorded Quay 401 is not bypassed by Docker Hub. Current upstream README marks the repository unmaintained/archived; AIStor Free is license-gated and its docs prohibit encryption at rest, so it is not an approved drop-in for this security spec. No provider change or service start made.


SeaweedFS continuation (2026-09-29): pinned SeaweedFS 4.40; local Compose S3 is loopback-bound behind the HTTPS Nginx proxy with scoped static identities and a local SSE-S3 key. TLS/bootstrap initializer is in place. Focused Compose/storage tests pass (7); Ruff passes. Docker runtime remains unverified: earlier `docker compose up`, `docker compose ps`, and `docker version` calls hung; no teardown or volume commands were issued. Generated certs/secrets remain ignored. Production env remains untouched. Live S3 allow/deny, SSE, and restart checks remain outstanding.


SeaweedFS live-start attempt (2026-09-29): Docker 29.8.0 and `docker compose config --quiet` work. `docker compose up -d` built all images, but the S3 proxy health check failed with 502; SeaweedFS logs identify a UTF-8 BOM at byte 1 of the mounted static IAM JSON as invalid input, and S3 ports do not listen. Fixed `scripts/dev-certs.ps1` to emit BOM-free JSON for newly created configs and made its default output path robust; the existing ignored local config is still unchanged pending approval for an encoding-only repair. App services depending on the proxy have not started. No production env or old MinIO secret files were accessed.

### Task 8 continuation (2026-09-29): SeaweedFS runtime and validation
- Recreated only `seaweedfs` and `seaweedfs-s3-proxy`; persistent volumes were retained. Live process args confirm `-ip.bind=0.0.0.0` and `-s3.ip.bind=127.0.0.1`; both services report healthy. SeaweedFS logs report `Loaded KEK from s3.sse.kek config`.
- With SeaweedFS stopped, the backend S3 adapter raised `EndpointConnectionError` for a valid managed key; it did not return an empty-object result. After `docker compose up -d --force-recreate seaweedfs seaweedfs-s3-proxy`, both services were healthy and a missing-key lookup returned `None`.
- Focused backend storage/authz/gateway/file-route suite passed; one import parser test was skipped because its bounded parser execution requires the Linux container path. Ruff passed after import-order fixes in the initializer and two storage test files.
- Frontend unit suite passed: 208 files / 1,573 tests. `npm run typecheck` and `npm run lint` passed. `docker compose config --quiet` and `git diff --check` passed; Git printed only line-ending normalization warnings.
- Browser denial suite passed all six anonymous download endpoint checks using the discovery config. The standard authenticated global setup still fails at its seeded-role login redirect and has also hit the shared 10-per-5-minute login limit after repeated attempts. A single admin login probe reached `/` and retained only a `refresh_token` cookie; the temporary probe was removed.
- Still unverified: authenticated browser downloads for all six classes, second-user denial on a real resource, Excel upload/reparse/download, and the full restart/outage browser journey. Task 8 remains partial. Existing ignored `deploy/.env.production` was not inspected or changed; no volumes were removed.

### Task 8 follow-up: dev.ps1 provider pivot fix (2026-09-29)
- Found `dev.ps1 -Docker` still selecting removed `minio` and `minio-init` services. Added a regression test, observed it fail against the old list, then changed the launcher to select `seaweedfs`, `seaweedfs-s3-proxy`, and `seaweedfs-init`.
- The regression test passes; targeted Ruff passes; PowerShell parser validation and `docker compose config --quiet` pass. The Docker launcher itself was not started because it attaches/restarts the local app stack.

### Authenticated browser setup result (2026-09-29)
- A standard Playwright run was attempted after the limiter window cleared. The shared setup logs nine seeded login requests as HTTP 200, then rejects the next at `10 per 5 minutes`; setup aborts before the file-download tests. No auth rate limit was weakened. The isolated six-case anonymous denial suite remains green.

### Browser setup recovery and final verification (2026-09-29)
- Compose now passes through the existing `LOGIN_RATE_LIMIT` setting with its unchanged default `10/5minutes`; the regression test verified that fallback and override syntax.
- With a temporary process-only `LOGIN_RATE_LIMIT=30/5minutes`, the standard desktop Playwright global setup authenticated its seeded roles and the six file-download anonymous-denial tests passed. The process variable was removed and only the backend container was recreated; in-container settings read back `10/5minutes`.
- Final focused backend suite passed; its one platform-specific parser test remains skipped on Windows. Ruff, frontend unit tests/typecheck/lint, Compose config, PowerShell AST parse, and diff check pass.
- Remaining E2E coverage gap: the browser spec validates anonymous denial for six routes, but does not yet create permitted file records to prove positive downloads, cross-user denial on a real record, or Excel upload/reparse/download end to end.

### Task 8 completion evidence (2026-10-01)

- Fixed HTTPX mTLS setup by supplying an explicitly verified SSL context with the client certificate chain; the live authorization preflight confirms mTLS and rejects an invalid bearer.
- Split `StorageSettings` from database/JWT application settings for the gateway. Added `StorageMaintenanceSettings` for migration/reconciliation so the dedicated maintenance service needs its database URL and storage credentials without receiving the backend JWT signing secret.
- The isolated Compose run applied Alembic migrations and ran maintenance `preflight` against a disposable database. Seven file-class inventories had zero legacy rows/bytes and zero pending rows; S3 put/get/metadata/checksum/delete/encryption checks all passed. `cutover_ready` remained false, and no non-empty legacy dataset was present.
- Re-running `seaweedfs-init` reported the private bucket ready. A managed object retained its exact bytes across SeaweedFS and TLS-proxy recreation; stopping SeaweedFS surfaced a connection failure, and both services recovered with the object still readable.
- Live S3 TLS negative checks rejected an untrusted CA and a mismatched hostname. The live mTLS preflight verified the gateway certificate path and rejected an invalid bearer.
- Live least-privilege checks passed: runtime identity denied list/delete, gateway identity allowed get and denied put/list/delete, and maintenance identity allowed list/delete.
- The full browser journey passed 8/8: anonymous requests denied for all six download classes; owner scoped bug-report screenshot/comment and exemption/gimelim files downloaded while other users were denied; Excel uploaded, reparsed, downloaded, and denied to another user.
- The harness checked ownership labels before cleanup and removed only the `justice-task8-e2e` project resources. The frontend listener skips Chromium's blocked local port 10080.
- Production cutover remains pending: no non-empty legacy backfill/resume rehearsal, complete stale/mismatched authorization matrix, production encryption/key recovery and backup restore, or 30-day/two-backup retention evidence is claimed. The production environment file was not inspected or modified. No commit, merge, or push was made.

### Final continuation validation (2026-10-01)

- Re-ran focused storage/settings/migration/Compose/mTLS authorization tests: 28 passed.
- Ruff passed for the changed storage settings, adapter, maintenance, lifecycle preflight, and authorization client/test modules. Compose config with the maintenance profile and isolated E2E overlay passed; the PowerShell harness parsed successfully; `git diff --check` passed (Git only reported LF/CRLF normalization warnings).
- Backup failure notification test passed. Recovery acceptance test passed in the repository's age-enabled PostgreSQL image, including premature-start rejection, prepared-start argument forwarding, encryption/decryption of WAL `.history` and `.backup` files with age, no plaintext archive output, and webhook log redaction for success/failure cases.
- The age-enabled acceptance script does not constitute a PostgreSQL point-in-time restore rehearsal. Production database/object restore, key recovery, non-empty migration, stale/mismatched identity matrix, and retention gates remain open. No production environment file or credential was read or changed; no commit, merge, or push was made.
