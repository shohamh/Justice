#!/usr/bin/env bash
# Restore an encrypted base backup, configure PITR, then start and observe recovery.
set -euo pipefail

BASE_BACKUP="${1:-}"
BACKUP_DIR="${BACKUP_DIR:-/opt/justice/backups}"
PGDATA_RESTORE="${PGDATA_RESTORE:-/opt/justice/pgdata-restore}"
RECOVERY_TARGET_TIME="${RECOVERY_TARGET_TIME:-}"
ENV_FILE="${ENV_FILE:-deploy/.env.production}"
PROJECT_NAME="${RECOVERY_PROJECT_NAME:-justice-recovery}"
WAIT_SECONDS="${RECOVERY_WAIT_SECONDS:-180}"
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
if [[ -n "$RECOVERY_TARGET_TIME" && ! "$RECOVERY_TARGET_TIME" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}[[:space:]][0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?([+-][0-9]{2}(:?[0-9]{2})?)?$ ]]; then
    echo "Invalid RECOVERY_TARGET_TIME; use YYYY-MM-DD HH:MM:SS+00" >&2
    exit 64
fi
if [[ ! -r "$ENV_FILE" ]]; then echo "Recovery environment file is missing: $ENV_FILE" >&2; exit 1; fi
if [[ -n "$(MSYS_NO_PATHCONV=1 "${COMPOSE[@]}" ps --status running -q db)" ]]; then
    echo "Recovery database is already running; stop it before preparing a new restore" >&2
    exit 1
fi
if [[ -e "$PGDATA_RESTORE" && -n "$(find "$PGDATA_RESTORE" -mindepth 1 -print -quit 2>/dev/null)" ]]; then
    echo "ERROR: $PGDATA_RESTORE is non-empty; select a new isolated recovery directory" >&2
    exit 1
fi
mkdir -p "$PGDATA_RESTORE"
log "Extracting encrypted base backup into isolated recovery storage"
# The recovery entrypoint permits helper commands but rejects postgres until marked ready.
MSYS_NO_PATHCONV=1 "${COMPOSE[@]}" run --rm --no-deps --user root db chown -R postgres:postgres /var/lib/postgresql/data
MSYS_NO_PATHCONV=1 "${COMPOSE[@]}" run --rm --no-deps --user root db bash -o pipefail -c '
    set -euo pipefail
    age --decrypt --identity "$AGE_IDENTITY_FILE" --output - "/backups/$1" |
        tar -xz -C "$PGDATA"
' _ "$(basename "$BASE_BACKUP")"
MSYS_NO_PATHCONV=1 "${COMPOSE[@]}" run --rm --no-deps --user root db bash -ceu '
    touch "$PGDATA/recovery.signal"
    quote=$(printf "\\047")
    {
        printf "restore_command = %s/usr/local/bin/restore-wal.sh %%f %%p%s\n" "$quote" "$quote"
        if [[ -n "$1" ]]; then
            printf "recovery_target_time = %s%s%s\n" "$quote" "$1" "$quote"
            printf "recovery_target_action = %spromote%s\n" "$quote" "$quote"
        fi
    } >> "$PGDATA/postgresql.auto.conf"
    chown -R postgres:postgres "$PGDATA"
    touch "$PGDATA/.recovery-ready.tmp"
    chown postgres:postgres "$PGDATA/.recovery-ready.tmp"
    mv "$PGDATA/.recovery-ready.tmp" "$PGDATA/.recovery-ready"
' _ "$RECOVERY_TARGET_TIME"
log "Starting recovery PostgreSQL; its entrypoint verifies the readiness marker"
MSYS_NO_PATHCONV=1 "${COMPOSE[@]}" up -d db
log "Waiting for PostgreSQL to finish WAL replay"
deadline=$((SECONDS + WAIT_SECONDS))
while (( SECONDS < deadline )); do
    if in_recovery="$(MSYS_NO_PATHCONV=1 "${COMPOSE[@]}" exec -T db bash -ceu 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT pg_is_in_recovery()" ' 2>/dev/null)"; then
        if [[ "$in_recovery" == f ]]; then
            log "Point-in-time recovery completed; inspect the recovery database before routing application services"
            exit 0
        fi
    fi
    sleep 2
done
log "ERROR: Recovery database did not finish WAL replay within ${WAIT_SECONDS}s; inspect logs with docker compose --project-name ${PROJECT_NAME} logs db"
exit 1
