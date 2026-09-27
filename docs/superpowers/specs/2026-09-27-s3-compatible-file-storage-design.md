# S3-Compatible Durable File Storage and Authorized Downloads — Design

Date: 2026-09-27
Branch/worktree: `feature/s3-object-storage`
Status: Design and security requirements approved for planning; production provider selection remains a deployment gate.

## Context

This is sub-project B in the roadmap established by the runtime statelessness and observability project. That project described B as S3-compatible file storage, with MinIO for local development and an S3 API provider in production. B has its own specification, implementation plan, and delivery cycle.

The product requirement is to keep durable user files available across backend replicas and restarts, while letting authorized people download them in the relevant parts of the Justice app. The main application backend must not relay download bytes. A private download gateway will stream files from object storage and recheck Justice permissions for every request.

## Motivation

Justice currently keeps durable file bytes in Postgres and writes bug-report JSON mirrors to local disk. Database-backed bytes are shared across replicas but enlarge the relational database; disk-backed JSON mirrors depend on local files. Both approaches make object-store migration and consistent file delivery harder as the app moves toward horizontally scaled, containerized deployments.

Several file download flows already exist. Other file types can be uploaded or stored but have no complete app download path. Moving bytes to object storage must preserve file ownership, authorization, names, content types, and recovery behavior.

## Goals

1. Store durable application files in a private S3-compatible object store.
2. Use MinIO in the local Docker Compose stack and a configurable S3-compatible provider in production, behind one application storage interface.
3. Keep the object bucket private. Never return a public object URL, presigned URL, or storage credentials to the browser.
4. Serve downloads through a dedicated gateway. The gateway asks Justice's existing authorization logic about each request, then streams bytes from object storage to the client without loading entire files into the application backend.
5. Preserve the existing authorization boundary for each parent resource and deny downloads when the current user lacks permission.
6. Preserve or add app download surfaces for:
   - Exemption-request attachments in the approvals flow (existing).
   - Soldier-exemption files (storage/API helpers exist; UI download flow needs wiring).
   - Gimelim attachments (upload exists; list and download flows need adding).
   - Bug-report screenshots and comment attachments (existing flows); migrate the durable JSON mirror as well.
   - Original Excel workbooks in import sessions, including upload, reparse, and a download action on the authorized import-session review screen.
7. Provide a restartable backfill that accounts for every legacy object, verifies content, and retains a safe read path until the migration is complete.
8. Make Compose startup and migration preflight prove that the S3 API is reachable with the configured bucket and credentials.

## Non-goals

- Making the bucket publicly readable or exposing MinIO/S3 URLs to clients.
- Issuing presigned download links. A presigned URL is a bearer capability and can be reused by anyone who obtains it until expiration.
- Changing business authorization rules or parent-resource ownership.
- Moving generated exports that exist only while a request is running.
- Changing the contents of bug reports, exemption evidence, Gimelim attachments, or imported workbooks.
- Deploying the production object store or defining a specific production vendor before its endpoint and identity capabilities are known.

## Durable-file inventory and boundary

The initial inventory found these durable file payloads:

| Data | Current persistence | Required object-store use |
|---|---|---|
| Soldier exemption files | `SoldierExemptionFile.data` in Postgres | Store and retrieve through the storage interface |
| Exemption request files | `ExemptionRequestFile.data` in Postgres | Store and retrieve through the storage interface |
| Gimelim attachments | `GimelimAttachment.data` in Postgres | Store and retrieve through the storage interface |
| Bug-report comment attachments | `BugReportCommentAttachment.data` in Postgres | Store and retrieve through the storage interface |
| Bug-report screenshots | `BugReport.screenshot` in Postgres | Store and retrieve through the storage interface |
| Import-session source workbooks | `ImportSession.raw_excel` in Postgres | Store on upload; read for parse/reparse and authorized download |
| Bug-report JSON mirrors | Local files referenced by `BugReport.json_file_path` | Store and retrieve through the storage interface, including recovery after a failed DB insert |

The import-session workbook remains part of the durable-file migration even though its user-facing download is limited to the authorized review screen. Request-generated exports, such as in-memory ZIP or Excel responses, remain transient and are outside this migration.

Before implementation, the inventory step must search again for additional durable user-uploaded or user-visible file payloads.

## Architecture

### Storage interface

Implement storage access in a shared backend package. Run the download gateway as a separate FastAPI process/container using that package; run a separate, minimal authorization service process/container that exposes only the internal file-authorization contract. The gateway has no published host port and accepts browser traffic only through the Justice reverse proxy.

Add one S3-compatible storage interface for operations needed by application code, the gateway, and the maintenance job:

- Put an object.
- Open/read an object, preferably as a stream.
- Inspect object metadata as needed for verification.
- Delete an object.
- List only the narrowly scoped recovery prefix needed for bug-report JSON recovery, if required by the final recovery design.

Configuration separates public download routes from internal authorization and S3 endpoints and includes bucket, region, credentials, TLS CA, path-style/endpoint settings where required by MinIO, and the production server-side-encryption policy/key reference. The production preflight verifies the selected provider actually encrypts a test object with the configured managed key; bucket defaults alone are not assumed without read-back verification. Use distinct credentials for API put/get, gateway get-only, and maintenance/migration. Local MinIO requires its root user and password in the server environment; if unset, MinIO defaults to `minioadmin`. Generate one random root credential pair in ignored local secrets and provide it only to the MinIO server and one-shot initializer. The MinIO server needs the root identity to bootstrap; the initializer is the only admin client. API, gateway, and maintenance processes never receive root credentials. Object keys are generated opaque identifiers under fixed per-class prefixes; they must not contain soldier names, personal numbers, or original filenames. The API must not accept or return client-selected storage endpoints or keys.

### Download request path

1. The user opens a file action in the Justice UI.
2. The browser requests the existing or new Justice download route with its authenticated application request.
3. The download gateway forwards the caller's bearer access token and file/resource identifiers to the private authorization service over HTTPS with mutual TLS. The authorization service is reachable only from the gateway network and exposes no public route.
4. The authorization endpoint validates the credential with the existing auth dependencies and derives the actor from that credential; it never trusts a user ID supplied by the browser or gateway. It then applies the existing parent-resource authorization rules. On success, it returns only internal object metadata to the gateway: object key, content type, safe filename, and size when known. It never returns the key to the browser.
5. The gateway fetches the object from the private bucket and streams it to the browser with the correct content type and attachment filename.
6. On denial, the gateway returns an authorization error without requesting the object.

The gateway rechecks authorization on every request. A copied Justice route alone does not grant access to another user. Storage credentials are available only to the gateway and storage-writing application service, with the least privileges each requires. Gateway download credentials are read-only.

The frontend uses the authenticated Justice API client to fetch file bytes as a Blob, then creates a temporary browser-local URL for preview or download. This is needed because the current access token is attached by the API client; a plain HTML link to a protected route would not reliably include that bearer token. The frontend revokes temporary Blob URLs when their preview/download surface is disposed.

### Transport security

All network communication between the download gateway and its partners is encrypted in transit:

- Gateway to the authorization service: HTTPS with certificate-chain and hostname verification plus mutual TLS. The authorization service validates the gateway client certificate identity and the end-user bearer token independently.
- Gateway to MinIO or production S3: HTTPS with certificate verification. Insecure TLS and certificate-validation bypasses are prohibited.
- Deployed browser to the Justice download route: HTTPS.

The local Compose stack must exercise TLS for gateway-to-authorization and gateway-to-MinIO traffic using trusted development certificates. Development certificates and keys are generated or supplied locally and are not committed as production secrets. A TLS or trust failure fails closed before authorization metadata or object bytes are sent.

### Security boundaries and controls

The implementation must preserve the current per-resource authorization policy; it must not replace these checks with a generic "authenticated" or "owner/admin" rule. The gateway authorization contract and tests must bind every path identifier to the exact file, parent, and parent-of-parent records:

| File class | Existing download authorization to preserve |
|---|---|
| Exemption-request attachment | Request owner, or a user currently authorized to view that soldier's medical document; file must belong to the requested exemption request. |
| Soldier-exemption file | Soldier themself, or a user with `EXEMPTION_READ` scope; for medical exemptions, also require medical-document permission; file must belong to the requested exemption. |
| Gimelim attachment | Recheck the existing Gimelim permission for the soldier referenced by the exact Gimelim dismissal/assignment. |
| Bug-report screenshot/comment attachment | Report reporter or admin; an attachment must belong to the requested comment and report. Existing upload-only comment-author rules remain write rules, not a replacement download rule. |
| Import-session workbook | Admin, or a currently authorized duty manager who created the session, and only while the session is accessible under the existing import-session rules. |
| Bug-report JSON recovery mirror | Migration/recovery identity only; never a browser download route. |

The authorization endpoint re-evaluates current account status, role/scope, resource ownership, medical access, and parent relationships for every request; it does not cache allow decisions. A missing, deleted, revoked, or mismatched resource fails closed.

- The gateway is reachable by browsers only through the authenticated Justice origin/reverse proxy. Do not publish a separate unauthenticated gateway port. In Compose, the Vite `/api/file-download/` proxy and production nginx route that prefix to the gateway; neither exposes the private authorization service or MinIO. The gateway accepts only known Justice file-resource routes and resource identifiers; it never accepts a bucket, object key, storage URL, or arbitrary upstream URL from the caller.
- The authorization endpoint resolves the requested file and its parent relationship from trusted database state on every request, using the matrix above as the compatibility contract. It validates the forwarded end-user access token exactly as the public API does, derives the actor from that token, and applies the existing resource-specific rule. The gateway authenticates only with its dedicated mutual-TLS client certificate, whose SAN identifies the file gateway; the authorization service accepts no other client identity. It strips caller-supplied identity headers, never accepts a caller-supplied user ID, and never forwards the end-user token to object storage. Authorization responses are bound to the requested file/resource IDs and contain only the resolved internal object reference and approved response metadata. A mismatch or malformed response fails closed.
- Treat object keys and returned metadata as untrusted values even though they come from internal services. Restrict keys to the configured bucket and expected opaque key format/prefix; reject traversal, control characters, unexpected schemes, redirects, and out-of-contract metadata. Configure fixed authorization and object-store endpoints to prevent SSRF. Do not follow redirects from either service.
- Use separate runtime identities for API put/get, gateway get-only, and a one-shot maintenance/migration job with only the exact list/get/put/delete actions it needs under managed prefixes. Runtime identities must not have bucket administration, policy changes, cross-prefix access, or credential-management rights. Bootstrap/admin credentials are used only by idempotent initialization and are not mounted into application containers. Use a secret manager or protected secret mounts in production; keep local credentials out of source control, images, and logs. Document rotation and immediate revocation for S3 credentials and TLS certificates.
- Production objects, the legacy database during retention, and backups contain sensitive personnel and medical data. Require provider-managed server-side encryption with managed keys for every production object, encrypted PostgreSQL data volumes while legacy bytes remain, and encrypted database/WAL backups. Encrypt database base backups and WAL archives with age to an operator-managed recipient key; stream encryption directly to the backup destination so plaintext backup archives are never written there. Keep private decryption identities out of normal runtime containers and mount them only for authorized recovery. Document key rotation, recovery, and access auditing. Production cutover is blocked until the selected object-store provider demonstrates encryption and key recovery; do not silently downgrade. Local MinIO and database data rely on the host's encrypted storage. Do not enable object version retention without an explicit deletion/retention policy for sensitive files.
- Enforce upload byte limits at the reverse proxy and while reading multipart bodies (read at most the configured maximum plus one byte); never call an unbounded full-body read on an upload. Stream with bounded concurrent requests, upload/download size limits, timeouts, and cancellation handling so slow clients or oversized objects cannot exhaust gateway workers or storage connections. Never buffer an entire object in gateway memory. Apply request throttling at the gateway/reverse proxy and cap Range requests if supported.
- Validate and encode filenames for `Content-Disposition` (including CR/LF and Unicode handling); never interpolate raw database or object metadata into headers. Default untrusted uploads to attachment disposition. Inline preview is limited to validated raster image formats and must use safe response headers such as `X-Content-Type-Options: nosniff`; PDF is attachment-only unless preview runs in an isolated, sandboxed origin. Do not render HTML/SVG or other active content inline or on the Justice origin. Responses containing private files use `Cache-Control: private, no-store` and must not be cached by a shared proxy or CDN.
- MIME types and magic bytes are only consistency checks; they do not establish that a file is safe or free of malware. Treat uploaded and migrated files as untrusted. Enforce per-type byte limits and format-aware validation before storage or parsing. Reject unsupported types and mismatches between declared MIME type and file signature. For XLSX, reject more than 4,096 ZIP entries, more than 100 MiB total expanded data, or any entry with a compression ratio over 100:1; reject VBA payloads and external relationships, never extract paths to disk, and parse in a worker with a 60-second timeout and 512 MiB memory limit. Do not fetch external relationships. Files are served as attachments by default; do not claim or imply that uploads have been malware-scanned.
- Record security audit events for every download authorization result, including missing/invalid credentials (actor is null when it cannot be established), with file class/resource identifier when parsed, timestamp, outcome, and request ID. Do not record access tokens, storage credentials, object keys, file bytes, or sensitive filenames. Ensure gateway, proxy, tracing, and exception middleware redact Authorization headers and query parameters, and avoid logging response bodies.
- The end-user access token is forwarded only to the private authorization endpoint over the mutually authenticated TLS channel and is never persisted. The gateway must not accept identity from `X-User-*` or equivalent headers or authenticate from cookies. The current API client may send cookies for refresh flows, but the download gateway ignores them and requires the bearer access token. If cookie authentication is introduced, add CSRF defenses before permitting it on download routes.

### Write and import path

Uploads retain existing parent-resource authorization, content-type and magic-byte checks, and size limits, with the format-aware safety controls above. The writing service stores the bytes through the storage interface, then commits the object's opaque key and checksum with the domain record. Import-session parsing and reparsing load the original workbook through the same interface. File metadata such as original filename and content type remains associated with its domain record. No upload becomes downloadable until its required format-aware validation and other specified checks have passed. This project does not provide malware scanning.

### Persistence model

Preserve the existing domain records and their relationships. During migration, add nullable object-key and checksum metadata while retaining legacy byte/path data. Avoid a polymorphic file table in the first migration; authorization remains anchored to the concrete parent record and its current domain rules.

After backfill verification and a stability period, a later cleanup removes legacy byte columns and local-path dependencies. The cleanup is a distinct migration step so the initial object-store cutover has a rollback/read-compatibility window.

## Migration and consistency

Migration is staged:

1. Add nullable storage metadata without deleting legacy bytes or paths.
2. Run a preflight that checks endpoint reachability, bucket access, and the exact put/get/metadata/delete operations required by the app. It also inventories all legacy rows, byte sizes, and reachable bug-report JSON paths; missing source files are reported and block successful completion.
3. Backfill with deterministic, non-sensitive object keys. For each object, write to storage, read it back, compare size and SHA-256, then persist the key/checksum. The operation is idempotent and safe to resume.
4. Keep dual reads during backfill: use object storage for records with a verified key and legacy bytes/path for records not yet migrated.
5. Require migrated counts and byte totals to reconcile, all hashes to match, and no unresolved source paths before declaring cutover complete.
6. Retain legacy columns/files through the agreed rollback window; remove them only after verification and stable operation.

Object storage and Postgres do not share a transaction. Writes therefore store the object before committing a database reference, so no committed row points at an object that was never written. If the database write fails, attempt to remove the unreferenced object. Retriable cleanup/reconciliation handles failed removals and detects missing referenced objects. Object deletion happens only after the database deletion commits. Record deletion work in a transactional outbox; the isolated maintenance job retries deletes and periodically reconciles old unreferenced objects. Runtime API and gateway identities cannot delete objects.

Bug-report JSON mirrors currently provide a recovery path when the database insert fails. The object-store implementation must preserve that behavior: the mirror is durably written under a recoverable, private prefix before the database write, and recovery tooling can enumerate/import those mirrors using only the maintenance identity; no runtime identity or browser route can list that prefix. If both the database and object-store write fail, the report operation returns a clear error.

## Failure behavior

- A new upload does not create a database record if storage fails.
- A download or reparse whose required object is unavailable returns a clear service-unavailable error; it must not report a successful empty file or bypass authorization.
- During migration only, records without an object key may be read from their legacy source. Once a record has a verified key, storage failure is surfaced rather than silently falling back to stale data.
- A missing object referenced by a committed row is reported to logs/metrics and a reconciliation process; it is not treated as an empty file.
- An authorization failure is returned before the gateway opens an object.
- The gateway streams data, supports cancellation when the client disconnects, and does not log file bytes, tokens, or sensitive filenames.

## Compose and operational setup

- Add MinIO with persistent local data storage, a health check, and TLS enabled for its S3 API. Pin MinIO and PostgreSQL container images to supported release versions or immutable digests; do not use floating `latest` tags, and document a security-update cadence.
- Initialize a private bucket and narrowly scoped service credentials idempotently.
- Keep MinIO's TLS-protected S3 endpoint reachable only on the internal Compose storage network by the API, gateway, and maintenance job. Do not publish a MinIO host port; operator tooling runs as a one-shot container on that network.
- Provide trusted local development CA certificates for mutual-TLS gateway-to-authorization and verified gateway-to-MinIO TLS. Generate development leaf certificates with the required service SANs; ignore private keys and local credentials in Git. Do not disable certificate validation to make local setup pass.
- Configure API and gateway with the same endpoint/bucket contract but separate credentials. Keep MinIO on a storage-only Compose network; only API, gateway, and the one-shot maintenance job may join it.
- Document how to configure the production S3 endpoint and verify its required operations. S3 API compatibility alone does not guarantee identical behavior for every provider; verify the exact operations against the selected production service.

## User-facing download behavior

- Keep existing exemption-request, bug-report screenshot, and bug-report comment-attachment flows working through authenticated Justice requests.
- Add a soldier-exemption file listing/download action in its appropriate existing exemption UI.
- Add Gimelim attachment listing/download actions alongside the existing upload flow.
- Add an original-workbook download action to the import-session review screen. It uses the same owner/admin authorization as the import-session record and never reveals the object key or storage URL.
- Preserve file names and content types, handle errors visibly, and ensure unauthorized users cannot use a copied route.

## Verification

### Storage and migration

- Unit-test the S3 adapter's put/read/metadata/delete behavior and configuration for endpoint-style MinIO and production S3.
- Integration-test against a real MinIO service: bucket initialization, authenticated put/get, checksum verification, permission-denied behavior, and restart persistence.
- Test backfill idempotency, restart/resume, size/hash mismatch, missing legacy JSON paths, and cutover reconciliation.
- Verify an object-store outage does not create database references to missing objects; verify failed cleanup is reconciled.
- Verify bug-report JSON recovery after database insert failure and clear failure when both persistence destinations fail.

### Authorization and downloads

- For every file class, test correct bytes, media type, and attachment filename.
- Test every row of the authorization matrix for allowed users, denied users, stale/revoked access, parent/file/parent-of-parent ID mismatches, not-found objects, and storage outages.
- Test that direct gateway exposure is unavailable; caller-controlled object keys, URLs, identity headers, malformed authorization responses, redirects, traversal keys, and response-header injection are rejected.
- Test authorization-token forwarding only to the authorization service, redaction from logs/traces/errors, exact service audiences/scopes, and fail-closed behavior on TLS/certificate errors.
- Test object-store IAM for each runtime identity, including denied bucket listing/admin actions and denied writes/deletes for the gateway.
- Test private no-store cache headers, safe content disposition, nosniff, inline-type allowlisting, Range/size/concurrency limits, timeouts, and cancellation.
- Test unsupported file types, declared-MIME/signature mismatches, byte limits, and malformed/oversized/compression-bomb XLSX files, external relationships, macro payloads, ZIP entry/expanded-size/ratio bounds, and parser time/memory limits.
- Verify production object encryption, encrypted database volumes, age-encrypted base/WAL backups, key rotation, and recovery as deployment acceptance checks.
- Verify download audit events are emitted without tokens, object keys, bytes, or sensitive filenames.
- Test that no API response exposes an S3 URL, presigned URL, access key, secret, or session token.
- Test that another Justice user cannot download by reusing a copied Justice URL.
- Verify the gateway checks authorization on every request and streams without buffering whole objects in gateway memory.
- Exercise the app surfaces for exemption requests, soldier exemptions, Gimelim, bug-report files, and import-session source workbooks.

### End-to-end local verification

- Start the full Compose stack and wait for MinIO health and private-bucket initialization.
- Upload one representative file for each supported flow, restart the relevant app containers, and verify downloads and Excel reparse still work.
- Confirm the browser downloads the expected bytes and filename through the Justice origin; confirm a second user without access is denied using the same route.
- Stop MinIO and verify that uploads, downloads, and reparses surface clear failures while unrelated app screens remain usable.

## Rollout and rollback

Deploy the storage abstraction and gateway while legacy data remains available. Verify the Compose stack end to end first, then configure the production provider and verify its exact S3 operations before production cutover. Run the backfill, reconcile object counts/bytes/hashes, and verify authorized downloads before relying on object-store-only reads.

Rollback keeps legacy data until the stability window ends. Before that point, code can read the legacy source for records that have not switched to object storage and object storage for migrated records. Once new writes rely solely on object storage, rollback to a build that only understands database blobs is not supported; rollback must use a release that understands both representations. Legacy data is not dropped as part of the initial cutover.

## Deployment gates

- The gateway and authorization components are separate FastAPI processes built from the backend package. Mutual TLS is required between them; certificate-chain and hostname checks are mandatory. Browser traffic reaches the gateway only through the Justice origin proxy.
- The production S3 vendor and endpoint are not selected. Production cutover requires a documented capability check and restore rehearsal for TLS, managed-key at-rest encryption of objects, encrypted object backups, IAM prefix/action policies, and all required S3 operations. PostgreSQL volumes must be encrypted and base/WAL backups age-encrypted with a tested operator recovery identity. Until these checks pass, production storage cutover is not enabled.
- Keep legacy byte columns and JSON mirrors for at least 30 days after verified cutover and two successful encrypted backups. This project does not drop those sources; a separate reviewed migration must authorize cleanup after the retention period.
- Use a transactional outbox plus a restricted maintenance job for object deletion and orphan reconciliation. Run it every 15 minutes through the deployment scheduler; it is not part of the always-on API or gateway runtime.
