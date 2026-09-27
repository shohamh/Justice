#!/usr/bin/env bash
# Prepare an isolated data directory from an encrypted base backup. The age
# private identity is mounted only into the one-shot recovery database container.
set -euo pipefail
BASE_BACKUP="${1:-}"
BACKUP_DIR="${BACKUP_DIR:-/opt/justice/backups}"
PGDATA_RESTORE="${PGDATA_RESTORE:-/opt/justice/pgdata-restore}"
RECOVERY_TARGET_TIME="${RECOVERY_TARGET_TIME:-}"
ENV_FILE="${ENV_FILE:-deploy/.env.production}"
PROJECT_NAME="${RECOVERY_PROJECT_NAME:-justice-recovery}"
COMPOSE=(docker compose -f deploy/docker-compose.prod.yml -f deploy/docker-compose.recovery.yml --env-file "$ENV_FILE" --project-name "$PROJECT_NAME")
log() { echo "[$(date -Iseconds)] $*"; }

if [[ -z "$BASE_BACKUP" ]]; then
    echo "Usage: $0 /opt/justice/backups/base_TIMESTAMP.tar.gz.age" >&2
    exit 64
fi
BACKUP_DIR="$(realpath "$BACKUP_DIR")"
BASE_BACKUP="$(realpath "$BASE_BACKUP")"
case "$BASE_BACKUP" in
    "$BACKUP_DIR"/base_*.tar.gz.age) ;;
    *) echo "Base backup must be an encrypted base_*.tar.gz.age file inside BACKUP_DIR" >&2; exit 64 ;;
esac
if [[ ! -s "$BASE_BACKUP" ]]; then echo "Encrypted base backup is missing or empty" >&2; exit 1; fi
if [[ -e "$PGDATA_RESTORE" && -n "$(find "$PGDATA_RESTORE" -mindepth 1 -print -quit 2>/dev/null)" ]]; then
    echo "ERROR: $PGDATA_RESTORE is non-empty; select a new isolated recovery directory" >&2
    exit 1
fi
mkdir -p "$PGDATA_RESTORE"
if [[ -n "$RECOVERY_TARGET_TIME" && ! "$RECOVERY_TARGET_TIME" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}[[:space:]][0-9:.+-]+$ ]]; then
    echo "Invalid RECOVERY_TARGET_TIME; use YYYY-MM-DD HH:MM:SS+00" >&2
    exit 64
fi
log "Preparing encrypted backup in isolated recovery directory $PGDATA_RESTORE"
"${COMPOSE[@]}" run --rm --no-deps --user root db chown -R postgres:postgres /var/lib/postgresql/data
"${COMPOSE[@]}" run --rm --no-deps db bash -o pipefail -c '
    set -euo pipefail
    age --decrypt --identity "$AGE_IDENTITY_FILE" --output - "/backups/$1" |
        tar -xz -C "$PGDATA"
' _ "$(basename "$BASE_BACKUP")"
"${COMPOSE[@]}" run --rm --no-deps db bash -ceu '
    touch "$PGDATA/recovery.signal"
    {
        printf "%s\n" "restore_command = '''/usr/local/bin/restore-wal.sh %f %p'''"
        if [[ -n "$1" ]]; then
            printf "recovery_target_time = '\''%s'\''\n" "$1"
            printf "%s\n" "recovery_target_action = '''promote'''"
        fi
    } >> "$PGDATA/postgresql.auto.conf"
' _ "$RECOVERY_TARGET_TIME"
log "Encrypted base backup extracted; WAL restore is configured through restore-wal.sh"
log "To rehearse recovery, start the recovery database with the recovery Compose override and inspect its logs before pointing services at it."
