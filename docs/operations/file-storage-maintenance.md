# File storage maintenance

The maintenance runner is an opt-in, one-shot container. It is the only application process with object listing and deletion permissions. The API and download gateway use separate, narrower identities. Never put maintenance credentials in the main Compose environment file or pass them on a command line.

## Credentials

Create a dedicated S3 identity with access limited to the Justice bucket and only the list, get, put, and delete operations required by migration and reconciliation. It must not manage buckets, users, or policies.

For production, store a Compose-format environment file at `/opt/justice/secrets/storage-maintenance.env`, owned by root with mode `0600`:

```sh
STORAGE_MAINTENANCE_ACCESS_KEY_ID=...
STORAGE_MAINTENANCE_SECRET_ACCESS_KEY=...
```

The Compose service reads that separate file; it does not receive the credentials configured for the API or gateway. For local MinIO, put the maintenance user credentials in the ignored `deploy/minio/secrets/maintenance.env` file using the same variable names. They must match the maintenance identity created by the MinIO initializer.

## Run manually

Run these from the repository root. The default `preflight` checks storage connectivity and inventories legacy data without migrating it. `migrate` writes objects and database references; take and verify the required backups and review the preflight report before running it.

```sh
# Local MinIO
docker compose --profile storage-maintenance run --rm file-storage-maintenance preflight

# Production preflight
docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml \
  --profile storage-maintenance run --rm file-storage-maintenance preflight

# Explicit production migration, in bounded batches
docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml \
  --profile storage-maintenance run --rm file-storage-maintenance migrate --batch-size 100
```

## Schedule reconciliation

Reconciliation removes orphan objects and retries the deletion outbox. Schedule it every 15 minutes on the production host. Install this root crontab entry after verifying the checkout path, secret file, Docker access, and log directory. `flock` prevents overlapping runs.

```cron
*/15 * * * * flock -n /run/lock/justice-storage-reconcile.lock sh /opt/justice/deploy/reconcile-file-storage.sh >> /opt/justice/logs/storage-maintenance.log 2>&1
```

Monitor the log and alert on a nonzero command exit. Keep this schedule on the host or deployment scheduler; do not run the maintenance profile as a long-lived service.

Production migration remains gated on validating the selected S3 provider's TLS, IAM allow/deny behavior, encryption, encrypted object-backup restore, encrypted database/WAL backups and key recovery, and encrypted PostgreSQL volumes. Reconciliation scheduling does not indicate cutover readiness.
