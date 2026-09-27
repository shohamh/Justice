# Task 3 implementation report

## Result

Implemented additive storage metadata for all six database payload-bearing models plus the seventh bug-report JSON mirror payload, the transactional delete outbox model, an Alembic revision, format-aware resumable backfill, preflight inventory, and maintenance-only reconciliation commands. Legacy byte columns and JSON mirror paths remain in place. Runtime S3 storage no longer exposes `delete`; only the migration/maintenance adapter does.

Commit: `3fe72d5bfa5ca71b90272fa951b587ac75be3651` (`feat: add resumable file storage migration`), on `feature/s3-object-storage`.

## RED evidence

Command from `backend/`: `python -m pytest app/storage/tests/test_backfill.py app/storage/tests/test_reconciliation.py -q` before implementation.

Result: collection failed because `app.storage.backfill` and `app.storage.reconciliation` did not exist.

## GREEN evidence

- `python -m pytest app/storage/tests/test_backfill.py app/storage/tests/test_reconciliation.py -q` ? final observed output: **14 passed**.
- `python -m pytest app/storage/tests/test_s3.py -q` ? **9 passed**, including assertion that runtime adapter lacks delete and maintenance adapter owns it.
- `python -m ruff check --ignore UP042 ...` over every touched Python file ? passed. `UP042` was excluded because the large existing model module contains unrelated enum style findings.
- `git diff --check` ? passed.
- Isolated Alembic `upgrade()` rendering through a PostgreSQL static `MigrationContext` ? passed; generated 63 SQL lines and asserted nullable legacy bytes, metadata columns, and the outbox table.
- Both migration/reconciliation CLI `--help` commands ? passed.
- Full Alembic history offline rendering was attempted with UTF-8. It stops in unchanged revision `ba8eaf68d98c` because that older migration calls `.fetchall()` on the offline static result. The new Task 3 revision was separately rendered and passed.

## Self-review

- Deterministic per-class UUID keys are used. Supported MIME types match the existing upload surfaces; image/PDF signatures and XLSX ZIP bounds/structure are checked before upload. JSON mirror reads are confined to the configured `LOG_DIR/bug_reports` root and reject missing, oversized, malformed, or outside-root paths.
- Backfill verifies storage write metadata and read-back size/SHA-256 before setting DB metadata. Legacy bytes remain unchanged. A failed commit restores in-memory metadata and best-effort deletes the object; reconciliation reports any orphan left behind.
- Restarted backfills verify the existing object and do not issue a second put for a verified row. Dry-run inventories all seven payload classes and validates supported formats; cutover readiness remains false in dry-run and when any source is unreachable, any object operation fails, any error remains, or any row is pending.
- Production preflight requires read-back server-side encryption algorithm and key ID to match configured managed-key settings. This check was exercised with the fake storage adapter only.
- The outbox contains only its UUID, opaque object key, timestamps, attempts, and stable error code. Reconciliation uses only the maintenance identity for listing/deletion, reports missing references and cleanup failures without raw provider errors, and age-gates orphan deletion. Dry-run processes neither orphan deletion nor outbox deletes.
- Downgrade raises before changing schema because dropping storage references after object-only writes could orphan user data. Restore from a pre-migration database backup is the safe rollback.

## Remaining verification limits

No live PostgreSQL migration or MinIO/S3 operation was run. Task 2's official MinIO image pull was blocked by Quay HTTP 401; storage preflight, IAM behavior, production SSE metadata, and listing/deletion behavior against a real provider remain unverified. No production cutover is claimed.
