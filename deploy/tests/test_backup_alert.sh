#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT
mkdir -p "$TMP/bin" "$TMP/backups" "$TMP/wal"
cat >"$TMP/bin/docker" <<'SH'
#!/bin/sh
if [ "$1" = exec ]; then
  echo "simulated pg_basebackup failure" >&2
  exit 1
fi
exit 0
SH
cat >"$TMP/bin/curl" <<'SH'
#!/bin/sh
cat >"$MOCK_CURL_CONFIG_FILE"
printf '%s' "${MOCK_HTTP_CODE:-204}"
SH
chmod +x "$TMP/bin/docker" "$TMP/bin/curl"
export MOCK_CURL_CONFIG_FILE="$TMP/curl-config"
export BACKUP_ALERT_WEBHOOK="https://alerts.invalid/private-token"
set +e
output="$(PATH="$TMP/bin:$PATH" BACKUP_DIR="$TMP/backups" WAL_ARCHIVE_DIR="$TMP/wal" DB_CONTAINER=fake TIMESTAMP=test "$ROOT/deploy/backup.sh" 2>&1)"
status=$?
set -e
[[ "$status" -ne 0 ]] || { echo "FAIL: simulated base backup failure returned success" >&2; exit 1; }
[[ "$output" == *"simulated pg_basebackup failure"* ]] || { echo "FAIL: root failure was not visible" >&2; exit 1; }
[[ "$output" == *"Backup failure alert delivered"* ]] || { echo "FAIL: backup failure did not notify" >&2; exit 1; }
[[ "$output" != *"$BACKUP_ALERT_WEBHOOK"* ]] || { echo "FAIL: output disclosed webhook URL" >&2; exit 1; }
grep -Fq "$BACKUP_ALERT_WEBHOOK" "$MOCK_CURL_CONFIG_FILE" || { echo "FAIL: webhook was not called" >&2; exit 1; }
echo "PASS: base-backup failures trigger a redacted operator notification"
