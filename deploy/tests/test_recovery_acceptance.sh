#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

# The wrapper must refuse to invoke Postgres before the ready marker and recovery config exist.
export PGDATA="$TMP/pgdata"
mkdir -p "$PGDATA"
export POSTGRES_ENTRYPOINT="$TMP/fake-entrypoint"
export ENTRYPOINT_ARGS="$TMP/entrypoint-args"
cat >"$POSTGRES_ENTRYPOINT" <<'SH'
#!/bin/sh
printf '%s\n' "$@" >"$ENTRYPOINT_ARGS"
SH
chmod +x "$POSTGRES_ENTRYPOINT"
set +e
gate_output="$("$ROOT/deploy/postgres/recovery-startup.sh" postgres -c archive_mode=off 2>&1)"
gate_status=$?
set -e
[[ "$gate_status" -eq 78 ]] || fail "unprepared recovery exited $gate_status, expected 78"
[[ ! -e "$ENTRYPOINT_ARGS" ]] || fail "unprepared recovery reached the Postgres entrypoint"
[[ "$gate_output" == *"not prepared"* ]] || fail "unprepared recovery error was not actionable"
printf '16\n' >"$PGDATA/PG_VERSION"
touch "$PGDATA/recovery.signal" "$PGDATA/.recovery-ready"
printf "%s\n" "restore_command = '/usr/local/bin/restore-wal.sh %f %p'" >"$PGDATA/postgresql.auto.conf"
"$ROOT/deploy/postgres/recovery-startup.sh" postgres -c archive_mode=off
grep -Fxq postgres "$ENTRYPOINT_ARGS" || fail "prepared startup did not invoke Postgres"
grep -Fxq -- "-c" "$ENTRYPOINT_ARGS" || fail "prepared startup dropped Postgres args"
grep -Fxq -- "archive_mode=off" "$ENTRYPOINT_ARGS" || fail "prepared startup dropped recovery settings"
pass "recovery gate refuses premature startup and delegates prepared startup with recovery args"

# Exercise the actual age binary and the production archive helper with timeline history and backup metadata.
age-keygen -o "$TMP/identity" >/dev/null 2>&1
recipient="$(age-keygen -y "$TMP/identity")"
export AGE_BACKUP_RECIPIENTS="$recipient"
export AGE_BACKUP_RECIPIENTS_NEXT=""
export WAL_ARCHIVE_DIR="$TMP/archive"
mkdir -p "$WAL_ARCHIVE_DIR"
printf "timeline history fixture\n" >"$TMP/source"
history="00000002.history"
"$ROOT/deploy/postgres/archive-wal.sh" "$TMP/source" "$history"
age --decrypt --identity "$TMP/identity" "$WAL_ARCHIVE_DIR/$history.age" >"$TMP/decrypted"
cmp "$TMP/source" "$TMP/decrypted" || fail "timeline history did not round trip"
backup="000000010000000000000001.00000028.backup"
"$ROOT/deploy/postgres/archive-wal.sh" "$TMP/source" "$backup"
age --decrypt --identity "$TMP/identity" "$WAL_ARCHIVE_DIR/$backup.age" >"$TMP/decrypted"
cmp "$TMP/source" "$TMP/decrypted" || fail "backup metadata did not round trip"
[[ ! -e "$WAL_ARCHIVE_DIR/$history" ]] || fail "plaintext history file was left in the archive"
pass "real age archive supports .history and .backup names without plaintext archive files"

# A local curl receiver shim captures the request config, including the generic body,
# while checking that notifier output never discloses the webhook or payload.
mkdir -p "$TMP/bin"
cat >"$TMP/bin/curl" <<'SH'
#!/bin/sh
cat >"$MOCK_CURL_CONFIG_FILE"
printf '%s' "${MOCK_HTTP_CODE:-204}"
exit "${MOCK_CURL_EXIT:-0}"
SH
chmod +x "$TMP/bin/curl"
export PATH="$TMP/bin:$PATH"
export MOCK_CURL_CONFIG_FILE="$TMP/curl-config"
secret="https://alerts.invalid/private-token"
set +e
success_output="$(BACKUP_ALERT_WEBHOOK="$secret" "$ROOT/deploy/notify-backup-failure.sh" 2>&1)"
success_status=$?
set -e
[[ "$success_status" -eq 0 ]] || fail "successful webhook receiver returned ${success_status}: $success_output"
[[ "$success_output" == *"Backup failure alert delivered"* ]] || fail "successful delivery was not logged"
[[ "$success_output" != *"$secret"* ]] || fail "success output disclosed webhook URL"
[[ "$success_output" != *"Justice PostgreSQL backup or WAL archiving failed"* ]] || fail "success output disclosed payload"
grep -Fq "$secret" "$MOCK_CURL_CONFIG_FILE" || fail "notifier did not send to the configured local receiver"
grep -Fq "Justice PostgreSQL backup or WAL archiving failed" "$MOCK_CURL_CONFIG_FILE" || fail "notifier payload missing"
export MOCK_HTTP_CODE=503
set +e
failure_output="$(BACKUP_ALERT_WEBHOOK="$secret" "$ROOT/deploy/notify-backup-failure.sh" 2>&1)"
failure_status=$?
set -e
[[ "$failure_status" -ne 0 ]] || fail "HTTP 503 was treated as successful delivery: $failure_output"
[[ "$failure_output" == *"delivery failed"* ]] || fail "delivery failure was not visible"
[[ "$failure_output" != *"$secret"* ]] || fail "failure output disclosed webhook URL"
[[ "$failure_output" != *"Justice PostgreSQL backup or WAL archiving failed"* ]] || fail "failure output disclosed payload"
pass "webhook success and failure are visible while URL and notification payload stay out of logs"
