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
- [ ] Task 3: Add file metadata, transactional delete outbox, and restartable backfill
- [x] Task 4: Move upload, parse, and bug-report recovery flows to object storage
- [x] Task 5: Add the private authorization service and streaming download gateway
- [ ] Task 6: Route all browser downloads through the gateway
- [ ] Task 7: Encrypt PostgreSQL base backups and WAL archives
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
