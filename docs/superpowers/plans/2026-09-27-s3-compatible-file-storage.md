# S3-Compatible Durable File Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Move Justice's durable user files to private S3-compatible storage, with per-request authorized streaming downloads, bounded upload validation, restartable migration, and working app download surfaces.

**Architecture:** A shared Python storage package uses boto3 to access a private MinIO/S3 bucket. The API validates and stores uploads; a separate FastAPI download gateway streams files after a separate minimal authorization service has checked the caller and parent-resource policy over mutually authenticated TLS. Compose adds MinIO, while Nginx/Vite route only the Justice download path to the gateway. Legacy bytes and local mirrors remain available through the 30-day/two-backup retention period.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, boto3/botocore, PostgreSQL, MinIO, age, Docker Compose, Nginx, React/TypeScript, Axios, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-27-s3-compatible-file-storage-design.md`

## Global Constraints

- Use HTTPS with certificate-chain and hostname verification for gateway-to-authorization and gateway-to-object-store traffic; mutual TLS is required between gateway and authorization service.
- Do not publish a host port for the gateway, authorization service, or MinIO; browsers reach downloads through the Justice origin proxy only.
- API storage identity is put/get only; gateway identity is get only; maintenance/migration identity is the only runtime identity with scoped list/delete permissions. No runtime identity gets bucket administration or credential management.
- Treat uploads and migrated payloads as untrusted. Enforce byte/type limits, MIME/signature consistency checks, and format-aware validation; do not claim files are malware-free. Reject unsupported or malformed files before storage or parsing.
- XLSX limits: at most 4,096 ZIP entries, at most 100 MiB expanded data, no entry above a 100:1 compression ratio, reject VBA and external relationships, parse with a 60-second timeout and 512 MiB memory limit.
- Generate opaque per-class object keys without names, personal numbers, or original filenames. Verify SHA-256 and size on backfill.
- Every download rechecks current account status, role/scope, ownership, medical access, and exact parent relationships. Never accept caller-provided user IDs, object keys, buckets, or URLs.
- Private responses use `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff`, and safely encoded `Content-Disposition`; only validated raster images may be inline on the Justice origin.
- Production cutover requires verified managed-key object encryption, encrypted PostgreSQL volumes, and age-encrypted base/WAL backups with a tested recovery identity. Keep legacy columns and mirrors for at least 30 days after verified cutover and two successful encrypted backups; this plan does not remove them.

## Review Focus

- User supplies unsupported or malformed content, or a MIME/signature mismatch; reject it before storage or parsing. Signature checks are not malware detection.
- User supplies a compressed XLSX with excessive entries, expanded size, ratio, external links, VBA, or parser cost; reject before import parsing.
- Caller changes one or more parent/file IDs or reuses a copied URL after access is revoked; authorization denies before any object-store read.
- Authorization service or MinIO is unavailable or presents an untrusted certificate; fail closed with no partial file success or database reference.
- Database commit fails after object upload or deletion; reconcile the orphan or retry deletion without granting API/gateway delete permissions.

---

### Task 1: Build the shared S3 storage package

**Files:**
- Create: `backend/app/storage/__init__.py`
- Create: `backend/app/storage/protocol.py`
- Create: `backend/app/storage/keys.py`
- Create: `backend/app/storage/s3.py`
- Modify: `backend/app/settings.py`
- Modify: `backend/pyproject.toml`
- Test: `backend/app/storage/tests/test_keys.py`
- Test: `backend/app/storage/tests/test_s3.py`
- Test: `backend/app/tests/test_settings.py`

**Interfaces:**
- `StoredObject`: immutable record with `key: str`, `size: int`, `sha256: str`, `encryption_algorithm: str | None`, and `encryption_key_id: str | None`.
- `ObjectStorage.put_bytes(*, key: str, data: bytes, content_type: str, sha256: str) -> StoredObject`.
- `ObjectStorage.open_read(*, key: str) -> tuple[BinaryIO, int]` returns a closeable stream and content length.
- `ObjectStorage.head(*, key: str) -> StoredObject | None` and `delete(*, key: str) -> None`.
- `iter_keys(*, prefix: str) -> Iterator[str]` is exposed only to the maintenance adapter; runtime API and gateway code must not call it.
- `make_object_key(file_class: Literal["soldier_exemption", "exemption_request", "gimelim", "bug_report_screenshot", "bug_report_comment", "import_workbook", "bug_report_json_mirror"], object_id: UUID) -> str` creates keys under fixed file-class prefixes; `validate_managed_key(key: str) -> bool` rejects traversal and keys outside those prefixes.

- [ ] **Step 1: Write failing tests for keys and the S3 adapter**

  Assert generated keys contain only the fixed file-class prefix and UUID, never the supplied filename or soldier identifier. Assert `../`, absolute paths, control bytes, unknown prefixes, and URL-shaped keys are rejected. Use `botocore.stub.Stubber` to assert PutObject receives the configured bucket, TLS-verified client, content type, SHA-256 metadata, and configured server-side encryption policy; assert GetObject returns a stream, HeadObject maps missing keys to `None`, and DeleteObject targets only a validated key.

- [ ] **Step 2: Run the focused tests and confirm they fail**

  Run from `backend/`: `pytest app/storage/tests/test_keys.py app/storage/tests/test_s3.py app/tests/test_settings.py -q`.

  Expected: FAIL because storage modules and settings do not exist.

- [ ] **Step 3: Implement the typed interface, opaque-key validation, and boto3 adapter**

  Add `boto3` to `backend/pyproject.toml`. Configure bucket, region, endpoint, path-style addressing, CA bundle, and server-side encryption/key reference through typed settings. Require `https://` outside an explicit local unit-test stub. Set `verify` to the configured CA path or system trust; do not set it to `False`. Return raw streaming bodies only to trusted internal callers.

- [ ] **Step 4: Run the focused tests and add boundary cases**

  Run the same pytest command. Assert malformed keys are rejected before any boto3 call and that no secret or endpoint credential is included in exception text.

- [ ] **Step 5: Commit the storage interface**

  Commit `backend/app/storage/`, settings, dependency lock/source files, and the focused tests as `feat: add private s3 storage adapter`.

### Task 2: Add local MinIO, TLS certificates, and least-privilege identities

**Files:**
- Modify: docker-compose.yml
- Modify: .env.defaults
- Modify: .gitignore
- Create: scripts/dev-certs.ps1
- Create: deploy/minio/init-bucket.sh
- Create: deploy/minio/policies/api-put-get.json
- Create: deploy/minio/policies/gateway-get.json
- Create: deploy/minio/policies/maintenance.json
- Test: backend/app/storage/tests/test_compose_storage.py

**Interfaces:**
- API identity has put/get only; gateway has get only; maintenance/migration has scoped list/get/put/delete. No runtime identity has bucket administration.
- Local certificates cover gateway, authorization service, MinIO, and proxy Compose DNS names. Keep generated private keys and credentials ignored by Git.

- [ ] **Step 1: Add failing tests for MinIO TLS, bucket initialization, and least-privilege policies**

  Cover API put/get, gateway get-only, and maintenance scoped list/get/put/delete permissions; assert denied actions fail.

- [ ] **Step 2: Run focused storage configuration tests and confirm they fail**

  Verify Compose services, TLS configuration, and policy wiring.

- [ ] **Step 3: Implement MinIO and its Compose topology**

  Add MinIO with TLS server certificates, persistent data, private bucket initialization, and the least-privilege policies above. Keep it on the internal storage network and do not publish its port. Only the one-shot initializer receives MinIO root credentials; it creates the bucket and service users. Add generated certificates and secrets to .gitignore.

- [ ] **Step 4: Verify Compose configuration, TLS identity, and IAM**

  Run `docker compose config --quiet` and `.\scripts\dev-certs.ps1`, then start `minio` and `minio-init`. Confirm MinIO health, private bucket policies, TLS SAN verification from an API container, and denied host connections to its port.

- [ ] **Step 5: Commit the local storage infrastructure**

  Commit Compose, the cert helper, MinIO initialization and policies, and focused infrastructure tests as the private object store infrastructure change.

### Task 3: Add file metadata, transactional delete outbox, and restartable backfill

**Files:**
- Modify: `backend/app/db/models.py`
- Create: next Alembic revision generated by `alembic revision -m "add object storage metadata"` in `backend/alembic/versions/`
- Create: `backend/app/storage/backfill.py`
- Create: `backend/app/scripts/migrate_file_storage.py`
- Create: `backend/app/scripts/reconcile_file_storage.py`
- Test: `backend/app/storage/tests/test_backfill.py`
- Test: `backend/app/storage/tests/test_reconciliation.py`

**Interfaces:**
- Add nullable `storage_key`, `storage_sha256`, and `storage_size` fields to `SoldierExemptionFile`, `ExemptionRequestFile`, `GimelimAttachment`, `BugReportCommentAttachment`, `BugReport`, and `ImportSession`; `BugReport` also gets `json_mirror_storage_key` and its hash. Retain every legacy byte column and local path.
- Add `StorageDeleteOutbox` with `id`, `object_key`, `created_at`, `attempts`, `last_error_code`, and `completed_at`; store no filename, bytes, token, or personal number.
- `backfill_record(storage, record) -> BackfillResult` derives a stable key from file class plus record UUID, validates supported format metadata and structure, uploads, reads back, compares size/SHA-256, then persists the key. Re-running it is a no-op for a verified row.
- The migration identity alone may list managed prefixes. A rejected legacy file is recorded in a restricted report and blocks cutover; never make it downloadable via the gateway.

- [ ] **Step 1: Write tests for idempotent backfill, corrupted reads, detections, and recovery**

  Use a fake storage adapter. Assert a successful row stores the exact object key/hash/size; rerun does not duplicate the object; a size/hash mismatch or unsupported/malformed payload leaves legacy bytes intact and marks the run failed without writing a live-prefix object; missing JSON mirror paths appear in the preflight report; and failed DB commit triggers best-effort delete while reconciliation discovers a remaining orphan.

- [ ] **Step 2: Run migration tests and confirm they fail**

  Run from `backend/`: `pytest app/storage/tests/test_backfill.py app/storage/tests/test_reconciliation.py -q`.

  Expected: FAIL because the new fields, migration service, and outbox do not exist.

- [ ] **Step 3: Add schema migration and batch backfill commands**

  Create an Alembic revision against the current head. Make legacy data columns nullable only where new object-only rows require it; do not drop columns or paths. Add `--dry-run`, `--batch-size`, and resumable execution. Preflight counts rows and bytes for all seven durable payload classes, verifies supported-format validation and S3 operations, verifies provider-side encryption metadata for a test object in production mode, and reports unreachable paths without leaking filenames. Store migration errors as stable error codes, not raw exception strings.

- [ ] **Step 4: Test batch restart and outbox reconciliation**

  Run the focused pytest command. Add a restart test where the process stops after an object upload and before the DB update, then reruns and verifies one object and one DB reference. Add outbox tests proving API/gateway code cannot call `delete`; only the maintenance command retries and completes deletions.

- [ ] **Step 5: Commit schema and migration tooling**

  Commit the migration, models, backfill/reconciliation services, and tests as `feat: add resumable file storage migration`.

### Task 4: Move upload, parse, and bug-report recovery flows to object storage

**Files:**
- Modify: `backend/app/routes/exemption_requests.py`
- Modify: `backend/app/routes/exemptions.py`
- Modify: `backend/app/routes/gimelim.py`
- Modify: `backend/app/routes/bug_reports.py`
- Modify: `backend/app/services/bug_reports.py`
- Modify: `backend/app/routes/import_sessions.py`
- Modify: `backend/app/services/import_sessions.py`
- Modify: `backend/app/services/file_validation.py`
- Create test: `backend/app/routes/tests/test_exemption_requests_files.py`
- Modify test: `backend/app/routes/tests/test_exemptions.py`
- Create test: `backend/app/routes/tests/test_gimelim_attachments.py`
- Modify test: `backend/app/routes/tests/test_bug_reports.py`
- Create test: `backend/app/routes/tests/test_import_session_files.py`
- Test: `backend/app/services/tests/test_import_sessions_service.py`

**Interfaces:**
- Upload handlers enforce byte limits and validate the declared type against the file signature and supported format rules before storage, then commit the domain row with object key/hash/size. On DB failure they attempt cleanup; the reconciliation command handles failed cleanup.
- `read_import_workbook(session, import_session) -> bytes` reads the verified object when a key exists and uses `raw_excel` only for unmigrated legacy rows.
- XLSX validation checks ZIP entry count, expanded size, per-entry compression ratio, VBA parts, and external relationships before `openpyxl` parses the workbook. Parsing executes in a bounded worker with the spec timeout and memory limit.
- Every file deletion adds its storage key to `StorageDeleteOutbox` in the same DB transaction as record deletion.

- [ ] **Step 1: Add failing tests for upload validation ordering and object persistence**

  In each upload route test, inject fake storage. Assert unsupported types, MIME/signature mismatches, malformed formats, and over-limit input are rejected before any DB row or S3 object exists. Assert valid data is stored once and only its object key/hash/size are committed. Assert a DB commit failure triggers cleanup and leaves no false success response.

- [ ] **Step 2: Run focused route/service tests and confirm the new expectations fail**

  Run from `backend/`: `pytest app/routes/tests/test_exemption_requests_files.py app/routes/tests/test_exemptions.py app/routes/tests/test_gimelim_attachments.py app/routes/tests/test_bug_reports.py app/routes/tests/test_import_session_files.py app/services/tests/test_import_sessions_service.py -q`.

  Expected: FAIL because upload, parse, and persistence paths still use database bytes/local paths.

- [ ] **Step 3: Convert all file writes and imports while retaining legacy read compatibility**

  Update each listed service to inject the storage dependency and shared bounded format validators. Preserve each current parent write authorization. Make import create/reparse use the object source, not database bytes. Add workbook structure limits and run parser work in a bounded child process. Preserve bug-report JSON recovery by writing the private object mirror before the report DB transaction; the maintenance-only recovery command enumerates the mirror prefix and imports validated JSON records.

- [ ] **Step 4: Add failure and migration-compatibility tests**

  Re-run the focused suite. Test a record with null `storage_key` reads legacy bytes; a verified key reads S3; an S3 outage for a verified key returns 503 without stale fallback; missing mirror plus DB failure returns a clear error; and invalid XLSX bounds fail before openpyxl is called.

- [ ] **Step 5: Commit upload and import storage changes**

  Commit route/service/model-test changes as `feat: store durable uploads in object storage`.

### Task 5: Add the private authorization service and streaming download gateway

**Files:**
- Create: `backend/app/file_authorization/__init__.py`
- Create: `backend/app/file_authorization/main.py`
- Create: `backend/app/file_authorization/schemas.py`
- Create: `backend/app/file_authorization/policies.py`
- Create: `backend/app/file_gateway/__init__.py`
- Create: `backend/app/file_gateway/main.py`
- Create: `backend/app/file_gateway/authorization_client.py`
- Create: `backend/app/file_gateway/routes.py`
- Create: `backend/app/file_gateway/response_headers.py`
- Modify: `backend/app/audit/writer.py`
- Test: `backend/app/file_authorization/tests/test_policies.py`
- Test: `backend/app/file_authorization/tests/test_routes.py`
- Test: `backend/app/file_gateway/tests/test_authorization_client.py`
- Test: `backend/app/file_gateway/tests/test_routes.py`

**Interfaces:**
- `FileAuthorizationRequest` is a discriminated union for the six file classes; it contains only relevant UUID path identifiers and never an object key.
- `FileAuthorizationDecision` returns `object_key`, `sha256`, `size`, `content_type`, and `filename`; it is serialized only over the internal mTLS channel.
- Authorization app exposes only `POST /_internal/file-authorizations`. Uvicorn requires a client certificate signed by the dedicated gateway CA; the route independently validates the user's bearer access token and current policy.
- Gateway exposes only known `GET /api/file-download/...` routes. It makes no object-store call until it receives a valid allow decision. It accepts bearer auth only and ignores cookies and caller-supplied identity headers.

- [ ] **Step 1: Write policy tests from the spec matrix**

  Cover request owner and medical document viewer for exemption requests; self/`EXEMPTION_READ` plus medical permission for soldier exemptions; current scoped Gimelim access; reporter/admin for bug report screenshot and comment files; comment/report ID binding; current duty manager plus session creator or admin for imports; missing, deleted, revoked, and mismatched resources. Assert every denial occurs before storage access.

- [ ] **Step 2: Run policy tests and confirm they fail**

  Run from `backend/`: `pytest app/file_authorization/tests/test_policies.py app/file_authorization/tests/test_routes.py -q`.

  Expected: FAIL because the authorization service does not exist.

- [ ] **Step 3: Implement the minimal mTLS authorization app and audit decisions**

  Reuse existing auth dependencies and authorization helpers. Use typed discriminated request/response models. Bind all path UUIDs to the same database relationships used by current routes. Write `file.download.allow` and `file.download.deny` audit rows for every authorization result, including missing/invalid credentials with `actor_id=None`, resource class/ID when parsed, and request ID only; never add a key, filename, token, or file content to audit context. Disable docs/OpenAPI on the internal app.

- [ ] **Step 4: Test gateway protocol and streaming headers**

  Assert TLS verification is enabled, the client certificate is configured, the user bearer token is sent only to the authorization service, and redirects are not followed. Assert unknown route kinds, forged keys, traversal keys, invalid metadata, CR/LF filenames, oversized content length, authorization outages, concurrency/rate-limit overflow, and gateway timeout fail closed. Reject Range requests with 416 because this gateway does not implement partial content. Assert streamed chunks are passed through without full buffering, disconnect cancels the S3 body, and responses include private no-store, nosniff, safe content disposition, and raster-only inline policy.

- [ ] **Step 5: Implement gateway routes and run the security-focused tests**

  Add streaming routes for exemption-request file, soldier-exemption file, Gimelim attachment, bug-report screenshot/comment attachment, and import workbook. Validate object key prefix against file class and maximum size before opening S3. Return denial/not-found/service-unavailable status without leaking object existence beyond current Justice behavior.

  Run from `backend/`: `pytest app/file_authorization/tests app/file_gateway/tests -q`.

- [ ] **Step 6: Commit authorization and gateway services**

  Commit the services, audit event changes, and tests as `feat: add authorized streaming file gateway`.

### Task 6: Route all browser downloads through the gateway

**Files:**
- Modify: `frontend/src/api/exemptions.ts`
- Modify: `frontend/src/api/gimelim.ts`
- Modify: `frontend/src/api/bugReports.ts`
- Modify: `frontend/src/api/importSessions.ts`
- Create: `frontend/src/utils/downloadFile.ts`
- Create: `frontend/src/utils/downloadFile.test.ts`
- Modify: `frontend/src/pages/ApprovalsPage.tsx`
- Modify: `frontend/src/components/ExemptionsPanel.tsx`
- Modify: `frontend/src/components/DismissalModal.tsx`
- Modify: `frontend/src/components/BugReportCommentsPanel.tsx`
- Modify: `frontend/src/components/BugReportMyReportsTab.tsx`
- Modify: `frontend/src/pages/admin/BugReportsContent.tsx`
- Modify: `frontend/src/pages/ImportSessionReviewPage.tsx`
- Test: `frontend/src/api/exemptions.test.ts`, `frontend/src/api/gimelim.test.ts`, `frontend/src/api/bugReports.test.ts`, `frontend/src/api/importSessions.test.ts`, `frontend/src/pages/ApprovalsPage.test.tsx`, and matching component tests

**Interfaces:**
- Each API helper uses the existing authenticated Axios client with `responseType: "blob"` and a `/file-download/...` path.
- Shared frontend download handling creates a temporary Blob URL, uses a sanitized display filename from authorized metadata, and revokes the URL after download/preview disposal.
- UI never renders a storage endpoint, bucket name, object key, or presigned URL.

- [ ] **Step 1: Add failing API tests for each protected download helper**

  Assert the correct route IDs and `responseType: "blob"` for all six resource classes. Assert the helper does not place credentials, file IDs, or object keys in query parameters.

- [ ] **Step 2: Run focused frontend API tests and confirm failure**

  Run from `frontend/`: `npm test -- --run src/api/exemptions.test.ts src/api/gimelim.test.ts src/api/bugReports.test.ts src/api/importSessions.test.ts`.

  Expected: FAIL for new download helpers/routes.

- [ ] **Step 3: Add the helpers and connect existing/new UI actions**

  Wire soldier-exemption file listing/download; add Gimelim attachment list/download beside its upload flow; update bug-report screenshot/comment previews to fetch Blob data through the gateway; add original XLSX download on the import review page. Keep exemption-request behavior intact and route it through the gateway. Dispose object URLs when their owning preview unmounts or changes.

- [ ] **Step 4: Test browser behavior and errors**

  Run the same API tests plus component tests for `ExemptionsPanel`, `DismissalModal`, `BugReportCommentsPanel`, `BugReportMyReportsTab`, `BugReportsContent`, and `ImportSessionReviewPage`. Assert filenames are safe, status errors render in the UI, temporary URLs are revoked, and no raw gateway URL is exposed as an anchor `href`.

- [ ] **Step 5: Run typecheck and commit the frontend work**

  Run `npm run typecheck` from `frontend/`, then commit only the changed API/components/tests as `feat: use authorized gateway for file downloads`.

### Task 7: Encrypt PostgreSQL base backups and WAL archives

**Files:**
- Create: `deploy/postgres/Dockerfile`
- Create: `deploy/postgres/archive-wal.sh`
- Create: `deploy/postgres/restore-wal.sh`
- Modify: `deploy/docker-compose.prod.yml`
- Create: `deploy/docker-compose.recovery.yml`
- Modify: `deploy/.env.production.example`
- Modify: `deploy/backup.sh`
- Modify: `deploy/restore-pitr.sh`
- Modify: `deploy/README.md`
- Create: `deploy/tests/test_backup_encryption.sh`

**Interfaces:**
- Production DB image includes the pinned PostgreSQL 16 base plus the `age` executable and two WAL helper scripts.
- `archive-wal.sh SOURCE_PATH WAL_NAME` encrypts directly to a temporary `.age` file using configured public recipients, atomically renames it into the archive, and exits nonzero on any error so PostgreSQL retries the archive.
- `restore-wal.sh WAL_NAME DESTINATION_PATH` decrypts the matching `.age` segment only when a recovery identity is mounted; missing segments return nonzero as PostgreSQL expects.
- `backup.sh` streams a tar-format `pg_basebackup` directly through `age` to `base_TIMESTAMP.tar.gz.age`; plaintext archives are never created on disk. Rotation supports both current and next recipients during key changes.

- [ ] **Step 1: Write shell tests for encrypted backup and WAL archive behavior**

  Generate a temporary age identity. Assert the base backup artifact begins with the age file header, decrypts to a readable tar archive, and never leaves a plaintext tar in the backup directory. Assert WAL archival produces a decryptable `.age` file, a second archival is idempotent, and a failed encryption leaves no final archive. Assert missing WAL restores exit nonzero and a valid restore decrypts to the requested path.

- [ ] **Step 2: Run the shell tests and confirm they fail**

  Run from repo root: `bash deploy/tests/test_backup_encryption.sh`.

  Expected: FAIL because current backup and WAL procedures write plaintext.

- [ ] **Step 3: Add age streaming to the database image and production backup scripts**

  Build a PostgreSQL image with the approved age version pinned. Configure `archive_command` to invoke the helper with `%p` and `%f`; helper writes age ciphertext to a same-filesystem temporary file before rename. Configure the recovery helper as `restore_command`. Update `backup.sh` to use `pg_basebackup -D - --format=tar --wal-method=fetch` and pipe stdout to age, requiring an empty tablespace inventory before streaming. Keep recipient public keys in protected config and private identities out of the running DB/API containers; add the recovery-only Compose override to mount the age identity read-only into PostgreSQL only for restore.

- [ ] **Step 4: Test rotation and perform a recovery rehearsal**

  Run `bash deploy/tests/test_backup_encryption.sh`. Encrypt one backup to both old and new recipients, verify each identity decrypts during the rotation window, remove the old recipient only after verifying all retained backup ages, then rehearse base plus WAL point-in-time restore using `deploy/docker-compose.recovery.yml` in an isolated Compose project. Verify archive failures surface in PostgreSQL health/backup logs and alert the operator.

- [ ] **Step 5: Commit encrypted backup and recovery tooling**

  Commit the database image, WAL helpers, backup/restore scripts, and tests as `security: encrypt database backups and wal archives`.

### Task 8: Wire Compose, dev launcher, and production proxy; finish migration operations and E2E checks

**Files:**
- Modify: `docker-compose.yml`
- Modify: `frontend/vite.config.ts`
- Modify: `deploy/docker-compose.prod.yml`
- Modify: `deploy/nginx.conf`
- Modify: `dev.ps1`
- Modify: `deploy/.env.production.example`
- Modify: `deploy/README.md`
- Create: `docs/operations/file-storage-migration.md`
- Modify: `docs/architecture.md`
- Test: `backend/app/storage/tests/test_compose_storage.py`
- Test: `frontend/tests/e2e/file-downloads.spec.ts`

**Interfaces:**
- Compose services: `minio`, `minio-init`, `backend`, `file-authorization`, `file-gateway`, and `frontend`. For production, only Nginx publishes host ports. In the developer Compose stack, existing backend/database/observability ports remain as documented, but gateway, authorization, and MinIO have no host ports. `dev.ps1 -Docker` includes MinIO, bucket initialization, authorization, and gateway services; the native launcher remains available for non-file-storage work. Each service joins only the networks and volumes it needs.
- Vite and Nginx proxy `/api/file-download/` to the gateway before the general `/api/` backend route. Nginx does not expose `/_internal/file-authorizations` or MinIO.
- Maintenance commands: `python -m app.scripts.migrate_file_storage --dry-run`, `python -m app.scripts.migrate_file_storage --batch-size 100`, and `python -m app.scripts.reconcile_file_storage --older-than-hours 24`. Schedule the restricted reconcile command every 15 minutes with host cron or the deployment scheduler.

- [ ] **Step 1: Add configuration tests and proxy route assertions**

  Test that Compose contains no published port for the gateway/authz/MinIO services, that runtime credentials are distinct, and that the S3 endpoint uses HTTPS. Assert Vite/Nginx route only the public download prefix to gateway and never route the internal auth path.

- [ ] **Step 2: Add proxy and container wiring**

  Update `dev.ps1 -Docker` service selection to include MinIO, bucket initialization, authorization, and gateway. Run dev-cert generation and make authorization/gateway containers trust the local CA. Add the separate authorization process and gateway command. Set Uvicorn client-certificate verification for the authorization listener. Configure the gateway HTTP client with the dedicated mTLS client certificate and configured CA; never set TLS verification bypass. Configure upload proxy limits to match each route's byte cap and ensure handlers read at most cap plus one byte. Keep the production S3 endpoint unset until a provider meets the deployment gates.

- [ ] **Step 3: Document preflight, rollout, and rollback commands**

  Document: generate local certs; start Compose; run S3 and format-validation preflight; dry-run inventory; backfill by batches; reconcile counts/bytes/hashes; verify allow/deny as two Justice users; retain legacy data for 30 days and two encrypted backups; rollback using the dual-read release. State that production cutover remains blocked until managed-key object encryption, encrypted object-backup restore, encrypted database/WAL backups and key recovery, encrypted PostgreSQL volumes, IAM, TLS, and exact S3 operations are verified for the selected provider.

- [ ] **Step 4: Run the end-to-end Compose journey**

  From repository root run `docker compose up --build -d`, seed only if the current local DB lacks test users, then upload/download one permitted fixture per class. Verify the browser receives expected bytes and filename; reuse the same URL under a second unauthorized account and assert denial; restart API, gateway, and MinIO and repeat. Stop MinIO and assert storage-dependent operations return clear errors without false empty-file responses. Run Excel upload, reparse, and download. Check container logs for absence of tokens, object keys, filenames, and file bytes.

- [ ] **Step 5: Run focused backend/frontend suites and review the full diff**

  Run from `backend/`: `pytest app/storage/tests app/file_authorization/tests app/file_gateway/tests app/routes/tests/test_exemption_requests_files.py app/routes/tests/test_exemptions.py app/routes/tests/test_gimelim_attachments.py app/routes/tests/test_bug_reports.py app/routes/tests/test_import_session_files.py app/services/tests/test_import_sessions_service.py -q`. Run from `frontend/`: `npm test -- --run` and `npm run typecheck`. Run `docker compose config --quiet` from repo root and `git diff --check`.

- [ ] **Step 6: Commit deployment, docs, and E2E verification**

  Commit only completed deployment, docs, and E2E files as `feat: wire file storage deployment and operations`.

## Cutover checklist

- [ ] `docker compose config --quiet` succeeds; production publishes only Nginx, and the developer stack publishes no gateway/authz/MinIO ports.
- [ ] MinIO bucket is private; API, gateway, and maintenance policies pass positive and negative IAM checks.
- [ ] Gateway-to-authorization mTLS and gateway-to-MinIO TLS hostname/CA checks succeed; invalid certificates fail.
- [ ] Backfill inventories all seven durable payload classes, validates supported format metadata and structure, verifies size/SHA-256, resumes cleanly, and reports zero unresolved source paths.
- [ ] The authorization matrix passes for all allowed/denied/stale/mismatched identities before the first live route cutover.
- [ ] Compose E2E verifies all download surfaces, Excel reparse, restart persistence, and MinIO outage behavior.
- [ ] Production remains on legacy storage until provider object encryption and object-backup restore, encrypted PostgreSQL volumes, age-encrypted backup/WAL restore, key recovery, TLS, IAM, and exact S3 operations pass the deployment gates.
- [ ] Legacy data remains for at least 30 days and two successful encrypted backups; removal requires a separate reviewed migration.
