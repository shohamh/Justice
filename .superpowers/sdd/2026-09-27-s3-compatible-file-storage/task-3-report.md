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


## Review-fix round

The independent Task 3 review found that migration inventory ignored rows already carrying `storage_key`, allowing cutover readiness without verifying referenced objects. Fix commit: `b0afef16e6f67e022c92b2ef187ec8df41dff0a2` (`fix: verify existing storage refs before cutover`).

### RED evidence

Command from `backend/`: `python -m pytest app/storage/tests/test_migration.py -q` before the fix. Result: **3 failed**. A missing object and an invalid managed prefix incorrectly left `cutover_ready=True`; an object whose HEAD metadata matched but bytes were corrupt was not read.

### GREEN evidence

- `python -m pytest app/storage/tests/test_migration.py -q` ? **4 passed**, covering missing object, same-size corrupted bytes despite matching HEAD metadata, invalid managed prefix, and valid existing object.
- `python -m pytest app/storage/tests/test_backfill.py app/storage/tests/test_reconciliation.py -q` ? **14 passed**.
- `python -m pytest app/storage/tests/test_s3.py -q` ? **9 passed**.
- Scoped Ruff with the existing `UP042` enum style warnings excluded ? passed; `git diff --check` ? passed.

The migration now enumerates every DB object reference, checks that its key is valid and belongs to its declared managed prefix, compares HEAD key/hash/size against persisted metadata, and streams the body in bounded chunks to verify byte count and SHA-256. Verification failures use stable aggregate error codes and block `cutover_ready`.

The same limits still apply: these checks used fake storage; no live PostgreSQL, MinIO, or provider S3 behavior was verified. Re-review is pending; Task 4 must not start until the coordinator records that review result.


## Ownership-binding review fix

The follow-up review found that a database row could reference another object with a valid key under the same managed class. Fix commit: `0481ad4432d074d4272fcac337c553dd0a3b9186` (`fix: bind storage keys to owning file records`).

### RED evidence

Command from `backend/`: `python -m pytest app/storage/tests/test_migration.py -q` before the fix. Result: **5 failed** because the reference iterator/verifier did not carry the owner UUID; it rejected the new five-field reference contract before evaluating row ownership. The new case used a valid `gimelim/` key with a UUID different from the owning row.

### GREEN evidence

- `python -m pytest app/storage/tests/test_migration.py -q` ? **6 passed**, including a valid same-prefix key bound to a different UUID and direct verification that DB enumeration yields the owning row UUID.
- `python -m pytest app/storage/tests/test_backfill.py app/storage/tests/test_reconciliation.py -q` ? **14 passed**.
- `python -m pytest app/storage/tests/test_s3.py -q` ? **9 passed**.
- Scoped Ruff and `git diff --check` ? passed.

The reference query now includes each model's primary key. Verification requires `object_key == make_object_key(file_class, row_id)` before any object-store read; a mismatch is aggregated as `object_key_record_mismatch` and blocks cutover readiness.

Independent re-review is pending. Task 4 remains paused until that review passes. Live PostgreSQL and S3-compatible provider behavior remain unverified.
