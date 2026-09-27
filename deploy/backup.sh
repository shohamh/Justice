#!/usr/bin/env bash
# Stream a tar-format PostgreSQL base backup through age. Plaintext backup bytes
# only exist in the pg_basebackup-to-age pipe and are never written to disk.
set -euo pipefail
BACKUP_DIR="${BACKUP_DIR:-/opt/justice/backups}"
WAL_ARCHIVE_DIR="${WAL_ARCHIVE_DIR:-/opt/justice/wal-archive}"
KEEP_DAYS="${KEEP_DAYS:-7}"
DB_CONTAINER="${DB_CONTAINER:-$(docker compose -f "$(dirname "$0")/docker-compose.prod.yml" ps -q db 2>/dev/null | head -1)}"
TIMESTAMP="${TIMESTAMP:-$(date +%Y%m%d_%H%M%S)}"
FINAL_FILE="$BACKUP_DIR/base_$TIMESTAMP.tar.gz.age"
log() { echo "[$(date -Iseconds)] $*"; }
if [[ -z "$DB_CONTAINER" ]]; then echo "No PostgreSQL container found; set DB_CONTAINER explicitly" >&2; exit 1; fi
if [[ -e "$FINAL_FILE" ]]; then echo "Backup already exists: $FINAL_FILE" >&2; exit 1; fi
mkdir -p "$BACKUP_DIR" "$WAL_ARCHIVE_DIR"
TEMP_FILE="$(mktemp "$BACKUP_DIR/.base_$TIMESTAMP.tmp.XXXXXX")"
cleanup() { rm -f "$TEMP_FILE"; }
trap cleanup EXIT
log "Streaming encrypted base backup to $FINAL_FILE"
docker exec "$DB_CONTAINER" bash -o pipefail -c '
    set -euo pipefail
    recipients="${AGE_BACKUP_RECIPIENTS:-} ${AGE_BACKUP_RECIPIENTS_NEXT:-}"
    if [[ -z "${recipients//[[:space:]]/}" ]]; then echo "No AGE_BACKUP_RECIPIENTS configured" >&2; exit 78; fi
    custom_tablespaces="$(psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT count(*) FROM pg_tablespace WHERE oid NOT IN (1663,1664)")"
    if [[ "$custom_tablespaces" != 0 ]]; then echo "Refusing streamed backup: custom tablespaces require a separate backup strategy" >&2; exit 1; fi
    read -r -a recipients_array <<<"$recipients"
    age_args=()
    for recipient in "${recipients_array[@]}"; do [[ -n "$recipient" ]] && age_args+=(--recipient "$recipient"); done
    pg_basebackup -U "$POSTGRES_USER" -D - --format=tar --gzip --wal-method=fetch --checkpoint=fast | age "${age_args[@]}"
' >"$TEMP_FILE"
if [[ ! -s "$TEMP_FILE" ]]; then echo "Encrypted base backup is empty" >&2; exit 1; fi
mv -f "$TEMP_FILE" "$FINAL_FILE"
trap - EXIT
log "Encrypted base backup complete ($(du -h "$FINAL_FILE" | cut -f1))"
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'base_*.tar.gz.age' -mtime "+$KEEP_DAYS" -delete
find "$WAL_ARCHIVE_DIR" -maxdepth 1 -type f -name '*.age' -mtime "+$KEEP_DAYS" -delete
ARCHIVE_FAILURES="$(docker exec "$DB_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc 'SELECT CASE WHEN last_failed_time IS NOT NULL AND (last_archived_time IS NULL OR last_failed_time > last_archived_time) THEN 1 ELSE 0 END FROM pg_stat_archiver')"
if [[ ! "$ARCHIVE_FAILURES" =~ ^[0-9]+$ ]]; then log "ERROR: Could not read pg_stat_archiver; inspect PostgreSQL logs."; exit 1; fi
if [[ "$ARCHIVE_FAILURES" -ne 0 ]]; then log "ERROR: PostgreSQL has an unrecovered WAL archive failure; operator alert required."; exit 1; fi
WAL_COUNT="$(find "$WAL_ARCHIVE_DIR" -maxdepth 1 -type f -name '*.age' -mmin -120 | wc -l)"
if [[ "$WAL_COUNT" -eq 0 ]]; then log "WARNING: No encrypted WAL segments in the last 2 hours; check PostgreSQL archive_command and logs."; else log "Encrypted WAL archive healthy: $WAL_COUNT segment(s) in the last 2 hours"; fi
