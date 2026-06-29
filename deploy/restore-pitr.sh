#!/usr/bin/env bash
# deploy/restore-pitr.sh
# Restore from base backup + WAL archive to a point in time.
# Run this OUTSIDE the container on the host. Stop the DB container first.
#
# Usage: RECOVERY_TARGET_TIME="2026-06-29 14:30:00+00" ./restore-pitr.sh <base_backup_dir>
#
# Example:
#   docker compose -f deploy/docker-compose.prod.yml stop db
#   RECOVERY_TARGET_TIME="2026-06-29 14:30:00+00" ./restore-pitr.sh /opt/justice/backups/base_20260629_020000
#   docker compose -f deploy/docker-compose.prod.yml start db

set -euo pipefail

BASE_BACKUP="${1:-}"
WAL_ARCHIVE_DIR="${WAL_ARCHIVE_DIR:-/opt/justice/wal-archive}"
PGDATA_RESTORE="${PGDATA_RESTORE:-/opt/justice/pgdata-restore}"
RECOVERY_TARGET_TIME="${RECOVERY_TARGET_TIME:-}"

if [ -z "$BASE_BACKUP" ]; then
    echo "Usage: $0 <base_backup_dir>"
    echo "Available base backups:"
    ls -lt /opt/justice/backups/ | grep base_
    exit 1
fi

log() { echo "[$(date -Iseconds)] $*"; }

log "Restoring from $BASE_BACKUP to $PGDATA_RESTORE"
mkdir -p "$PGDATA_RESTORE"

# Extract base backup
if [ -f "$BASE_BACKUP/base.tar.gz" ]; then
    tar -xzf "$BASE_BACKUP/base.tar.gz" -C "$PGDATA_RESTORE"
else
    cp -a "$BASE_BACKUP/." "$PGDATA_RESTORE/"
fi

# Create recovery.signal to trigger WAL replay
touch "$PGDATA_RESTORE/recovery.signal"

# Write recovery config
cat >> "$PGDATA_RESTORE/postgresql.auto.conf" <<EOF
restore_command = 'cp $WAL_ARCHIVE_DIR/%f %p'
EOF

if [ -n "$RECOVERY_TARGET_TIME" ]; then
    cat >> "$PGDATA_RESTORE/postgresql.auto.conf" <<EOF
recovery_target_time = '$RECOVERY_TARGET_TIME'
recovery_target_action = 'promote'
EOF
    log "Recovery target: $RECOVERY_TARGET_TIME"
fi

log "Restore prepared at $PGDATA_RESTORE"
log "To use: set PGDATA to $PGDATA_RESTORE and start postgres"
log "Or update your docker-compose volume mount and restart the db service."
