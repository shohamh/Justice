# Production Deployment Guide

## Architecture

- **nginx**: TLS termination, reverse proxy, static frontend serving
- **backend**: FastAPI (uvicorn, 2 workers), auto-runs migrations on start
- **telegram-bot**: Polling bot (separate process)
- **db**: PostgreSQL 16 with WAL archiving enabled

## Backup Strategy

### Continuous backup (WAL archiving)
WAL segments are archived to `/opt/justice/wal-archive/` every 60 seconds (configured in `docker-compose.prod.yml`). This enables **point-in-time recovery (PITR)** to any moment in the last 7 days.

### Daily base backup
Run `deploy/backup.sh` daily via cron. It uses `pg_basebackup` for a full physical snapshot. Combined with WAL archiving, you can recover to any point in time between any two base backups.

```bash
# Schedule daily base backup at 2am
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/justice/deploy/backup.sh >> /opt/justice/logs/backup.log 2>&1") | crontab -
```

### Recovery
See `deploy/restore-pitr.sh` for point-in-time recovery.

## First-time setup

```bash
# 1. Generate TLS cert (self-signed for internal network)
mkdir -p deploy/certs
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout deploy/certs/key.pem -out deploy/certs/cert.pem \
  -subj "/CN=justice.internal"

# 2. Configure environment
cp deploy/.env.production.example deploy/.env.production
# Edit .env.production — fill in DB_PASSWORD, JWT_SECRET, TELEGRAM_BOT_TOKEN, ALLOWED_ORIGINS

# 3. Build frontend
cd frontend && npm ci && npm run build && cd ..

# 4. Create data directories
sudo mkdir -p /opt/justice/pgdata /opt/justice/backups /opt/justice/logs /opt/justice/wal-archive

# 5. Start services
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production up -d --build

# 6. Schedule backups
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/justice/deploy/backup.sh >> /opt/justice/logs/backup.log 2>&1") | crontab -
```

## Updating

```bash
git pull
cd frontend && npm ci && npm run build && cd ..
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production up -d --build
```

## Restore from backup

```bash
# Stop backend to prevent writes
docker compose -f deploy/docker-compose.prod.yml stop backend telegram-bot

# Point-in-time restore
RECOVERY_TARGET_TIME="2026-06-29 14:30:00+00" deploy/restore-pitr.sh /opt/justice/backups/base_YYYYMMDD_HHMMSS

# Restart
docker compose -f deploy/docker-compose.prod.yml start backend telegram-bot
```

## Encrypted PostgreSQL backups

The PostgreSQL image uses the pinned age v1.2.1 binary and PostgreSQL 16.4
Alpine base. Set AGE_BACKUP_RECIPIENTS in deploy/.env.production to one or
more space-separated age public recipients. Keep the matching private identity
outside the repository and do not mount it into production database, API, or bot
services. Base backups and WAL segments are encrypted before they reach the
backup/archive directories. Base backup plaintext is streamed directly from
pg_basebackup into age and is not written to a temporary file.

For rotation, add the new public recipient to AGE_BACKUP_RECIPIENTS_NEXT while
retaining the old recipient. New archives then decrypt with either identity.
Before removing the old recipient, verify every retained base backup can be
decrypted with the new identity. WAL segments retained for recovery must also
remain decryptable; keep the old identity available in a protected offline
location until those segments expire.

Generate a private key and public recipient in a controlled environment:

    umask 077
mkdir -p /secure/justice
# Keep this identity in an encrypted/offline secret store; never commit it.
docker run --rm -v /secure/justice:/secrets justice-postgres:16-age1.2.1 age-keygen -o /secrets/age-identity

Store age-identity at the path configured by AGE_IDENTITY_PATH with permissions
readable only by the recovery operator. To prepare an isolated recovery directory:

    docker compose -f deploy/docker-compose.prod.yml -f deploy/docker-compose.recovery.yml --env-file deploy/.env.production --project-name justice-recovery run --rm --no-deps db true
    RECOVERY_TARGET_TIME="2026-09-27 14:30:00+00" deploy/restore-pitr.sh /opt/justice/backups/base_YYYYMMDD_HHMMSS.tar.gz.age

The first command validates the recovery-only Compose mounts without starting
Postgres. The restore script decrypts the selected base archive inside the
database image, extracts it into the separate PGDATA_RESTORE directory, and
configures WAL replay through restore-wal.sh. Inspect recovery Postgres logs and
confirm the expected point-in-time state before switching application services
to the restored data directory. A missing or corrupt WAL segment makes
PostgreSQL report a restore-command failure; check docker compose logs db and
the host backup logs, then alert the operator before promoting the recovery
instance.
