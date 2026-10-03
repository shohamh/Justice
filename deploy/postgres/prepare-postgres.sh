#!/usr/bin/env bash
set -euo pipefail

WAL_ARCHIVE_DIR="${WAL_ARCHIVE_DIR:-/var/lib/postgresql/wal-archive}"
if [[ "$(id -u)" -eq 0 ]]; then
    install -d -o postgres -g postgres -m 0700 "$WAL_ARCHIVE_DIR"
elif [[ ! -w "$WAL_ARCHIVE_DIR" ]]; then
    echo "WAL archive directory is not writable by the postgres user" >&2
    exit 73
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"
