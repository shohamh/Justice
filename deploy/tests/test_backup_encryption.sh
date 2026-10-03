#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
for program in age age-keygen; do
    if ! command -v "$program" >/dev/null; then
        echo "$program is required; run this test in the PostgreSQL age image" >&2
        exit 2
    fi
done
age-keygen -o "$TMP/old.identity" 2>"$TMP/old.pub"
age-keygen -o "$TMP/new.identity" 2>"$TMP/new.pub"
OLD_RECIPIENT="$(sed -n 's/^Public key: //p' "$TMP/old.pub")"
NEW_RECIPIENT="$(sed -n 's/^Public key: //p' "$TMP/new.pub")"
[[ -n "$OLD_RECIPIENT" && -n "$NEW_RECIPIENT" ]]
export AGE_BACKUP_RECIPIENTS="$OLD_RECIPIENT"
export AGE_BACKUP_RECIPIENTS_NEXT=""
export AGE_IDENTITY_FILE="$TMP/old.identity"
export WAL_ARCHIVE_DIR="$TMP/wal"
export BACKUP_DIR="$TMP/backups"
export DB_CONTAINER=fake-db
export POSTGRES_USER=justice POSTGRES_DB=justice
mkdir -p "$TMP/bin" "$WAL_ARCHIVE_DIR" "$BACKUP_DIR"
cat >"$TMP/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == exec ]] || exit 91
shift
[[ "$1" == fake-db ]] || exit 92
shift
if [[ "$1" == bash ]]; then
    shift
    exec bash "$@"
fi
if [[ "$1" == psql ]]; then
    shift
    exec psql "$@"
fi
exit 93
DOCKER
chmod +x "$TMP/bin/docker"
cat >"$TMP/bin/psql" <<'PSQL'
#!/usr/bin/env bash
printf '0\n'
PSQL
chmod +x "$TMP/bin/psql"
cat >"$TMP/bin/pg_basebackup" <<'PG'
#!/usr/bin/env bash
set -euo pipefail
[[ " $* " == *" -D - "* ]]
[[ " $* " == *" --format=tar "* ]]
[[ " $* " == *" --wal-method=fetch "* ]]
mkdir -p "$FAKE_BASE_DIR"
printf 'fixture database bytes\n' >"$FAKE_BASE_DIR/data"
tar -czf - -C "$FAKE_BASE_DIR" .
PG
chmod +x "$TMP/bin/pg_basebackup"
export FAKE_BASE_DIR="$TMP/base-content"
export PATH="$TMP/bin:$PATH"

fails=0
check() { if "$@"; then echo "PASS: $*"; else echo "FAIL: $*" >&2; fails=$((fails + 1)); fi; }
assert_age_header() { [[ "$(head -c 4 "$1")" == "age-" ]]; }
assert_no_plaintext_backup() { ! find "$BACKUP_DIR" -maxdepth 1 -type f ! -name '*.age' | grep -q .; }
assert_base_decrypts() {
    local path
    path="$(find "$BACKUP_DIR" -name 'base_*.tar.gz.age' -print -quit)"
    age -d -i "$TMP/old.identity" "$path" | tar -tzf - >/dev/null
}
assert_wal_decrypts() {
    age -d -i "$TMP/old.identity" "$WAL_ARCHIVE_DIR/000000010000000000000001.age" | cmp - "$TMP/wal-source"
}
assert_no_failed_artifact() {
    [[ ! -e "$WAL_ARCHIVE_DIR/000000010000000000000002.age" ]] &&
      ! find "$WAL_ARCHIVE_DIR" -name '*.tmp.*' | grep -q .
}
assert_wal_restores() {
    "$ROOT/deploy/postgres/restore-wal.sh" 000000010000000000000001 "$TMP/restored" &&
      cmp "$TMP/restored" "$TMP/wal-source"
}
assert_rotation_decrypts() {
    local path
    path="$(find "$BACKUP_DIR" -name 'base_rotation.tar.gz.age' -print -quit)"
    age -d -i "$TMP/old.identity" "$path" | tar -tzf - >/dev/null &&
      age -d -i "$TMP/new.identity" "$path" | tar -tzf - >/dev/null
}

"$ROOT/deploy/backup.sh"
check assert_age_header "$(find "$BACKUP_DIR" -name 'base_*.tar.gz.age' -print -quit)"
check assert_no_plaintext_backup
check assert_base_decrypts
printf 'wal fixture bytes\n' >"$TMP/wal-source"
"$ROOT/deploy/postgres/archive-wal.sh" "$TMP/wal-source" 000000010000000000000001
check assert_wal_decrypts
before="$(sha256sum "$WAL_ARCHIVE_DIR/000000010000000000000001.age" | cut -d' ' -f1)"
"$ROOT/deploy/postgres/archive-wal.sh" "$TMP/wal-source" 000000010000000000000001
after="$(sha256sum "$WAL_ARCHIVE_DIR/000000010000000000000001.age" | cut -d' ' -f1)"
[[ "$before" == "$after" ]] && echo 'PASS: repeated WAL archive is idempotent' || fails=$((fails + 1))
if AGE_BACKUP_RECIPIENTS=not-an-age-recipient "$ROOT/deploy/postgres/archive-wal.sh" "$TMP/wal-source" 000000010000000000000002 >/dev/null 2>&1; then
    echo 'FAIL: invalid recipient unexpectedly archived' >&2
    fails=$((fails + 1))
fi
check assert_no_failed_artifact
if "$ROOT/deploy/postgres/restore-wal.sh" 000000010000000000000099 "$TMP/missing" >/dev/null 2>&1; then
    echo 'FAIL: missing WAL unexpectedly restored' >&2
    fails=$((fails + 1))
else
    echo 'PASS: missing WAL restore exits nonzero'
fi
check assert_wal_restores
AGE_BACKUP_RECIPIENTS="$OLD_RECIPIENT"
AGE_BACKUP_RECIPIENTS_NEXT="$NEW_RECIPIENT"
export AGE_BACKUP_RECIPIENTS AGE_BACKUP_RECIPIENTS_NEXT
TIMESTAMP=rotation "$ROOT/deploy/backup.sh"
check assert_rotation_decrypts
if (( fails > 0 )); then echo "$fails encryption check(s) failed" >&2; exit 1; fi
echo 'All encrypted backup and WAL checks passed.'
