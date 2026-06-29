#!/usr/bin/env bash
# deploy/backup.sh
# Continuous backup strategy:
#   - WAL archiving: configured in docker-compose.prod.yml (archive_mode=on, archive_timeout=60s)
#     WAL segments are written to /opt/justice/wal-archive/ every 60 seconds max.
#   - Base backup: run this script daily via cron for a full physical snapshot.
#
# Add to crontab (daily at 2am):
#   0 2 * * * /opt/justice/deploy/backup.sh >> /opt/justice/logs/backup.log 2>&1
#
# Point-in-time recovery:
#   1. Restore a base backup to a new pgdata directory
#   2. Create recovery.signal in the pgdata directory
#   3. Set restore_command in postgresql.conf to replay WAL from wal-archive
#   4. Optionally set recovery_target_time to a specific point
#   See: https://www.postgresql.org/docs/16/continuous-archiving.html

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/justice/backups}"
WAL_ARCHIVE_DIR="${WAL_ARCHIVE_DIR:-/opt/justice/wal-archive}"
DB_CONTAINER="${DB_CONTAINER:-$(docker compose -f "$(dirname "$0")/docker-compose.prod.yml" ps -q db 2>/dev/null | head -1)}"
# Override DB_CONTAINER if your container name differs (docker ps to check)
DB_USER="${DB_USER:-justice}"
KEEP_DAYS="${KEEP_DAYS:-7}"          # Keep 7 days of base backups (WAL archive covers gaps)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BASE_BACKUP_DIR="$BACKUP_DIR/base_$TIMESTAMP"

mkdir -p "$BACKUP_DIR" "$WAL_ARCHIVE_DIR"

log() { echo "[$(date -Iseconds)] $*"; }

log "=== Justice backup started ==="

# ── Base backup (full physical snapshot via pg_basebackup) ──────────────────
log "Taking base backup → $BASE_BACKUP_DIR"
docker exec "$DB_CONTAINER" pg_basebackup \
    -U "$DB_USER" \
    -D "/backups/base_$TIMESTAMP" \
    --format=tar \
    --gzip \
    --wal-method=stream \
    --checkpoint=fast \
    --progress

SIZE=$(du -sh "$BASE_BACKUP_DIR" 2>/dev/null | cut -f1 || echo "unknown")
log "Base backup complete — $SIZE"

# ── Prune old base backups ───────────────────────────────────────────────────
log "Pruning base backups older than $KEEP_DAYS days"
find "$BACKUP_DIR" -maxdepth 1 -name "base_*" -mtime +"$KEEP_DAYS" -exec rm -rf {} + 2>/dev/null || true

# ── WAL archive health check ─────────────────────────────────────────────────
WAL_COUNT=$(find "$WAL_ARCHIVE_DIR" -maxdepth 1 -type f -mmin -120 2>/dev/null | wc -l || echo 0)
if [ "$WAL_COUNT" -eq 0 ]; then
    log "WARNING: No WAL segments archived in the last 2 hours. Check archive_command in docker-compose.prod.yml."
else
    log "WAL archive healthy — $WAL_COUNT segments in last 2h"
fi

log "=== Justice backup complete ==="
