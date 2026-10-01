# File storage migration and operations

This runbook covers the controlled move from legacy database-backed file payloads to the S3-compatible object store. Keep the old payloads until the retention and rollback gates below are satisfied.

## Local development

1. Generate the local CA, service certificates, and separate MinIO identities:

   ```powershell
   .\scripts\dev-certs.ps1
   ```

2. Start the Docker development stack with `docker compose up --build -d`, or use `.dev.ps1 -Docker`. The latter creates local credentials first. MinIO, its initializer, file authorization, and the file gateway have no published host ports. Use the frontend at `http://localhost:5173`.

3. Run the storage and format-validation preflight. Exercise uploads and downloads through the application and verify that a missing or unavailable object store produces a clear error. The app must not present an unavailable file as an empty successful response.

## Production preflight

Production cutover remains blocked until every item is verified for the selected provider and deployment:

- HTTPS with a verified provider certificate, authenticated TLS, and a distinct mTLS client certificate from the gateway to the authorization service.
- Separate least-privilege API write/read and gateway read-only identities; no root credentials in app or gateway containers.
- Managed-key object encryption and an encrypted object-backup restore test.
- Encrypted PostgreSQL data volumes, encrypted base backups and WAL archives, and tested recovery key custody.
- Provider-tested S3 operations used by this application, including object metadata, streaming reads, content type, conditional behavior, and multipart behavior where applicable.
- Restore and reconcile preflight succeeds without exposing credentials, bearer tokens, object keys, filenames, or file contents in logs.

Do not configure a production endpoint until those checks pass. Set `STORAGE_ENDPOINT_URL` to an HTTPS endpoint and configure the API and gateway identities separately in the protected production environment file. Keep `AGE_IDENTITY_PATH` outside normal application containers.

## Inventory and backfill

Use the restricted maintenance identity only for maintenance commands. First capture two encrypted PostgreSQL backups and retain the legacy database payloads for at least 30 days.

Run an inventory without writes:

```powershell
cd backend
python -m app.scripts.migrate_file_storage --dry-run
```

Resolve every unsupported or malformed legacy payload before continuing. Do not skip rows with existing `storage_key` references; cutover validation must confirm canonical owner keys, metadata, byte length, and streamed SHA-256.

Backfill in bounded batches:

```powershell
python -m app.scripts.migrate_file_storage --batch-size 100
```

Re-run the dry-run after the backfill. Compare row counts, object counts, total bytes, checksums, and rejected rows. Re-run batches until no eligible rows remain.

Schedule reconciliation every 15 minutes:

```powershell
python -m app.scripts.reconcile_file_storage --older-than-hours 24
```

Review the reconciliation counts and bytes after every run. Reconciliation must not delete a database payload until the object has been verified and the configured grace period has elapsed.

## Authorization and browser verification

Test downloads with two real Justice accounts: one permitted for the resource and one without permission. Confirm the first receives the expected bytes and filename, and the second is denied. Reuse the URL under the second account; no reusable S3 URL should be present in the browser.

Vite and Nginx route only `/api/file-download/` to the private gateway. Do not expose `/_internal/file-authorizations`, MinIO, the gateway, or the authorization service on host ports. The gateway checks the Justice bearer token and resource permission before it reads the object. Excel imports use the same protected object storage and gateway download path.

Check logs after the journey. They must not contain access tokens, storage credentials, object keys, filenames, or uploaded/downloaded bytes.

## Rollback

Keep the dual-read application release and legacy payloads available during the rollback window. If object reads or authorization fail, roll back to that release and restore the previous application configuration. Do not delete newly written objects until the rollback decision is complete; the object metadata and delete outbox must remain consistent.

After 30 days, require two verified encrypted database backups and a tested object-backup restore before removing retained legacy payloads. Preserve audit records and reconcile the object inventory after rollback.
