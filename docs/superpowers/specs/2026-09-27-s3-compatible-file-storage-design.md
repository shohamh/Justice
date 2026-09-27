# S3-Compatible Durable File Storage and Authorized Downloads — Design

Date: 2026-09-27
Branch/worktree: `feature/s3-object-storage`
Status: Conversational design approved; written spec pending user review.

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

Add one S3-compatible storage interface for operations needed by application code and the gateway:

- Put an object.
- Open/read an object, preferably as a stream.
- Inspect object metadata as needed for verification.
- Delete an object.
- List only the narrowly scoped recovery prefix needed for bug-report JSON recovery, if required by the final recovery design.

Configuration separates the public application URL from the internal S3 endpoint and includes bucket, region, credentials, and path-style/endpoint settings where required by MinIO. Object keys are generated opaque identifiers; they must not contain soldier names, personal numbers, or original filenames.

### Download request path

1. The user opens a file action in the Justice UI.
2. The browser requests the existing or new Justice download route with its authenticated application request.
3. The download gateway forwards the caller's authentication credential and file/resource identifier to a private Justice authorization endpoint over a service-authenticated channel.
4. The authorization endpoint validates the credential with the existing auth dependencies and derives the actor from that credential; it never trusts a user ID supplied by the browser or gateway. It then applies the existing parent-resource authorization rules. On success, it returns only internal object metadata to the gateway: object key, content type, safe filename, and size when known. It never returns the key to the browser.
5. The gateway fetches the object from the private bucket and streams it to the browser with the correct content type and attachment filename.
6. On denial, the gateway returns an authorization error without requesting the object.

The gateway rechecks authorization on every request. A copied Justice route alone does not grant access to another user. Storage credentials are available only to the gateway and storage-writing application service, with the least privileges each requires. Gateway download credentials are read-only.

The frontend uses the authenticated Justice API client to fetch file bytes as a Blob, then creates a temporary browser-local URL for preview or download. This is needed because the current access token is attached by the API client; a plain HTML link to a protected route would not reliably include that bearer token. The frontend revokes temporary Blob URLs when their preview/download surface is disposed.

### Write and import path

Uploads retain existing parent-resource authorization, content-type and magic-byte checks, and size limits. The writing service stores the bytes through the storage interface, then commits the object's opaque key and checksum with the domain record. Import-session parsing and reparsing load the original workbook through the same interface. File metadata such as original filename and content type remains associated with its domain record.

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

Object storage and Postgres do not share a transaction. Writes therefore store the object before committing a database reference, so no committed row points at an object that was never written. If the database write fails, attempt to remove the unreferenced object. Retriable cleanup/reconciliation handles failed removals and detects missing referenced objects. Object deletion happens only after the database deletion commits and is retried if storage is temporarily unavailable.

Bug-report JSON mirrors currently provide a recovery path when the database insert fails. The object-store implementation must preserve that behavior: the mirror is durably written under a recoverable, private prefix before the database write, and recovery tooling can enumerate/import those mirrors without exposing bucket listing to ordinary users. If both the database and object-store write fail, the report operation returns a clear error.

## Failure behavior

- A new upload does not create a database record if storage fails.
- A download or reparse whose required object is unavailable returns a clear service-unavailable error; it must not report a successful empty file or bypass authorization.
- During migration only, records without an object key may be read from their legacy source. Once a record has a verified key, storage failure is surfaced rather than silently falling back to stale data.
- A missing object referenced by a committed row is reported to logs/metrics and a reconciliation process; it is not treated as an empty file.
- An authorization failure is returned before the gateway opens an object.
- The gateway streams data, supports cancellation when the client disconnects, and does not log file bytes, tokens, or sensitive filenames.

## Compose and operational setup

- Add MinIO with persistent local data storage and a health check.
- Initialize a private bucket and narrowly scoped service credentials idempotently.
- Keep MinIO's S3 endpoint reachable on the internal Compose network by the application and gateway. Host exposure is optional for operator tooling and is not needed by the browser.
- Configure the app and gateway with the same endpoint/bucket contract, while using separate credentials when practical (write access for uploads; read access for downloads).
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
- Test allowed users, disallowed users, parent/file ID mismatches, not-found objects, and storage outages.
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

## Open decisions for implementation planning

- Select the concrete gateway implementation and internal authorization exchange while preserving the approved per-request authorization and streaming behavior.
- Confirm production S3 provider, endpoint, credentials delivery, TLS, and any provider-specific operation differences.
- Choose the cleanup/reconciliation mechanism for failed object deletion and orphaned uploads.
- Confirm the legacy-data retention/rollback window before dropping database byte columns or local JSON mirrors.
