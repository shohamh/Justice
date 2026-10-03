# Task 7 report: encrypted PostgreSQL backups and WAL

## RED evidence

The shell harness was added before the implementation. The first host run could not reach its behavioral assertions because this Windows host has no `age` or `age-keygen` executable. Its explicit prerequisite failure was: `age is required; run this test in the PostgreSQL age image`. I then built the pinned image and ran the harness inside it using the real `age` binaries.

The requested pre-implementation behavioral RED run against the starting scripts was not captured; the environment prerequisite prevented that run before implementation. No behavioral RED result is claimed here.

## GREEN evidence

Image build:

```cmd
docker build -f deploy\postgres\Dockerfile -t justice-postgres:16-age1.2.1 .
docker run --rm justice-postgres:16-age1.2.1 age --version
```

Result: build completed successfully; `age --version` returned `v1.2.1`.

Real-crypto harness:

```cmd
docker run --rm -v "C:\Users\Shoham\workspace\Justice\.worktrees\s3-object-storage-resume:/workspace" -w /workspace justice-postgres:16-age1.2.1 bash deploy/tests/test_backup_encryption.sh
```

Relevant output:

```text
PASS: assert_age_header ...base_....tar.gz.age
PASS: assert_no_plaintext_backup
PASS: assert_base_decrypts
PASS: assert_wal_decrypts
PASS: repeated WAL archive is idempotent
PASS: assert_no_failed_artifact
PASS: missing WAL restore exits nonzero
PASS: assert_wal_restores
PASS: assert_rotation_decrypts
All encrypted backup and WAL checks passed.
```

The test creates old and new identities in its private temporary directory, does not print their secret identity contents, and verifies the same rotation-window base archive decrypts with both identities. It also decrypts the base archive as a readable tar, checks the age header, checks no plaintext backup file remains, decrypts and restores a WAL fixture, checks repeated WAL archival is idempotent, checks failed encryption leaves no published artifact or temporary file, and checks a missing segment returns nonzero. The harness substitutes only database transport and `pg_basebackup`; encryption and decryption use the image's actual `age` binary.

Syntax check:

```cmd
docker run --rm -v "C:\Users\Shoham\workspace\Justice\.worktrees\s3-object-storage-resume:/workspace" -w /workspace justice-postgres:16-age1.2.1 bash -n deploy/backup.sh deploy/restore-pitr.sh deploy/postgres/archive-wal.sh deploy/postgres/restore-wal.sh deploy/tests/test_backup_encryption.sh
```

Result: exit 0, no output.

Compose validation:

```cmd
set DB_USER=justice
set DB_PASSWORD=compose-check-only
docker compose -f deploy\docker-compose.prod.yml -f deploy\docker-compose.recovery.yml --env-file deploy\.env.production.example --project-name justice-recovery config --quiet
```

Result: exit 0, no output. A temporary `deploy/.env.production` copied from the checked-in example was used to satisfy service `env_file` references and removed after validation. The compose file's env-file paths were corrected to be relative to the compose file. The DB interpolation warnings from the first config check disappeared after supplying `DB_USER` and `DB_PASSWORD` in the command environment.

`git diff --check` completed with no whitespace errors.

## Recovery and rotation evidence

The harness proves the recovery helper decrypts an archived WAL into its requested destination and fails for a missing segment. Rotation evidence is limited to a single test backup encrypted to both recipients and independently decrypted by each temporary identity. Production runbook instructions require retaining old identities for the full lifetime of artifacts encrypted for them, and checking retained backups and WAL before removing an old recipient.

The recovery-only Compose override mounts the recovery identity read-only into the database container. Production/API services do not receive the private identity. Base backup bytes are piped from `pg_basebackup` into `age` without an intermediate plaintext file; WAL encryption uses a same-directory temporary ciphertext file followed by atomic rename.

## Limitations

- No live PostgreSQL archive/recovery or point-in-time restore rehearsal was run. The harness stubs PostgreSQL transport and the production `pg_basebackup` command; Task 8 must perform the paired base-plus-WAL Compose rehearsal.
- No long-term retained-artifact rotation inventory was tested. Operators must verify every retained base backup and WAL segment decrypts with the new identity before removing the old identity.
- Archive failure behavior is covered at the helper level and the backup script checks `pg_stat_archiver` plus recent encrypted WAL presence. External alert delivery and production monitoring were not exercised.
