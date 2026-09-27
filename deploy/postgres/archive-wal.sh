#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 SOURCE_PATH WAL_NAME" >&2
    exit 64
fi

SOURCE_PATH="$1"
WAL_NAME="$2"
ARCHIVE_DIR="${WAL_ARCHIVE_DIR:-/var/lib/postgresql/wal-archive}"
DESTINATION="$ARCHIVE_DIR/$WAL_NAME.age"
RECIPIENTS="${AGE_BACKUP_RECIPIENTS:-} ${AGE_BACKUP_RECIPIENTS_NEXT:-}"

if [[ ! -f "$SOURCE_PATH" || ! "$WAL_NAME" =~ ^[A-Fa-f0-9]{24}$ ]]; then
    echo "Invalid WAL source or segment name" >&2
    exit 64
fi
if [[ -z "${RECIPIENTS//[[:space:]]/}" ]]; then
    echo "No AGE_BACKUP_RECIPIENTS configured" >&2
    exit 78
fi
mkdir -p "$ARCHIVE_DIR"

# PostgreSQL can retry archive_command after an uncertain result. Keeping an
# already-published archive is safe and avoids replacing a complete segment.
if [[ -f "$DESTINATION" ]]; then
    exit 0
fi

TEMP_FILE="$(mktemp "$ARCHIVE_DIR/.${WAL_NAME}.tmp.XXXXXX")"
cleanup() { rm -f "$TEMP_FILE"; }
trap cleanup EXIT

read -r -a RECIPIENT_LIST <<<"$RECIPIENTS"
AGE_ARGS=()
for recipient in "${RECIPIENT_LIST[@]}"; do
    [[ -n "$recipient" ]] && AGE_ARGS+=(--recipient "$recipient")
done

age "${AGE_ARGS[@]}" --output "$TEMP_FILE" "$SOURCE_PATH"
[[ -s "$TEMP_FILE" ]]
mv -f "$TEMP_FILE" "$DESTINATION"
trap - EXIT
