#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 WAL_NAME DESTINATION_PATH" >&2
    exit 64
fi

WAL_NAME="$1"
DESTINATION_PATH="$2"
ARCHIVE_DIR="${WAL_ARCHIVE_DIR:-/var/lib/postgresql/wal-archive}"
IDENTITY_FILE="${AGE_IDENTITY_FILE:-/run/secrets/age-identity}"
SOURCE_PATH="$ARCHIVE_DIR/$WAL_NAME.age"
WAL_ARCHIVE_NAME_RE='^([A-Fa-f0-9]{24}|[A-Fa-f0-9]{8}\.history|[A-Fa-f0-9]{24}\.[A-Fa-f0-9]{8}\.backup)$'

if [[ ! "$WAL_NAME" =~ $WAL_ARCHIVE_NAME_RE ]]; then
    echo "Invalid WAL archive filename" >&2
    exit 64
fi
if [[ ! -r "$IDENTITY_FILE" ]]; then
    echo "AGE_IDENTITY_FILE is unavailable; WAL restore is recovery-only" >&2
    exit 78
fi
if [[ ! -r "$SOURCE_PATH" ]]; then
    echo "WAL archive segment not found: $WAL_NAME" >&2
    exit 1
fi

DEST_DIR="$(dirname "$DESTINATION_PATH")"
mkdir -p "$DEST_DIR"
TEMP_FILE="$(mktemp "$DEST_DIR/.$(basename "$WAL_NAME").restore.XXXXXX")"
cleanup() { rm -f "$TEMP_FILE"; }
trap cleanup EXIT

age --decrypt --identity "$IDENTITY_FILE" --output "$TEMP_FILE" "$SOURCE_PATH"
[[ -s "$TEMP_FILE" ]]
mv -f "$TEMP_FILE" "$DESTINATION_PATH"
trap - EXIT
