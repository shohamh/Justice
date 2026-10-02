#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == postgres ]]; then
    READY_FILE="${PGDATA:-/var/lib/postgresql/data}/.recovery-ready"
    RECOVERY_SIGNAL="${PGDATA:-/var/lib/postgresql/data}/recovery.signal"
    AUTO_CONF="${PGDATA:-/var/lib/postgresql/data}/postgresql.auto.conf"
    if [[ ! -s "${PGDATA:-/var/lib/postgresql/data}/PG_VERSION" ||
          ! -f "$RECOVERY_SIGNAL" || ! -f "$READY_FILE" ||
          ! -s "$AUTO_CONF" ]] ||
       ! grep -Fq "restore_command = '/usr/local/bin/restore-wal.sh %f %p'" "$AUTO_CONF"; then
        echo "Recovery database is not prepared; run deploy/restore-pitr.sh first" >&2
        exit 78
    fi
fi

POSTGRES_ENTRYPOINT="${POSTGRES_ENTRYPOINT:-/usr/local/bin/docker-entrypoint.sh}"
exec "$POSTGRES_ENTRYPOINT" "$@"
