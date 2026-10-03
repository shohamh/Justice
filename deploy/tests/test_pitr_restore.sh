#!/usr/bin/env bash
# Disposable end-to-end test of encrypted pg_basebackup + encrypted WAL archive
# + point-in-time recovery. It never reads the production Compose files or env.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT="justice-pitr-test-$(date +%s)-$$-${RANDOM}"
IMAGE="${PROJECT}:postgres"
WORK_DIR=""
DOCKER_WORK_DIR=""
TEMP_PARENT="${TMPDIR:-$ROOT}"
COMPOSE_FILE=""
IMAGE_CREATED=0
COMPOSE_TOUCHED=0
WORK_DIR_CREATED=0

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

log() { printf '[pitr-test] %s\n' "$*"; }

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    set +e

    if [[ "$COMPOSE_TOUCHED" == 1 && -f "$COMPOSE_FILE" ]]; then
        local container_ids container_id label volume_ids volume_id network_ids network_id safe_to_down
        safe_to_down=1
        container_ids="$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")"
        for container_id in $container_ids; do
            label="$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project" }}' "$container_id" 2>/dev/null)"
            if [[ "$label" != "$PROJECT" ]]; then
                echo "CLEANUP ERROR: refusing to remove container without this test's Compose label" >&2
                status=1
                safe_to_down=0
            fi
        done
        volume_ids="$(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT")"
        for volume_id in $volume_ids; do
            label="$(docker volume inspect --format '{{ index .Labels "com.docker.compose.project" }}' "$volume_id" 2>/dev/null)"
            if [[ "$label" != "$PROJECT" ]]; then
                echo "CLEANUP ERROR: refusing to remove volume without this test's Compose label" >&2
                status=1
                safe_to_down=0
            fi
        done
        network_ids="$(docker network ls -q --filter "label=com.docker.compose.project=$PROJECT")"
        for network_id in $network_ids; do
            label="$(docker network inspect --format '{{ index .Labels "com.docker.compose.project" }}' "$network_id" 2>/dev/null)"
            if [[ "$label" != "$PROJECT" ]]; then
                echo "CLEANUP ERROR: refusing to remove network without this test's Compose label" >&2
                status=1
                safe_to_down=0
            fi
        done
        if [[ "$safe_to_down" == 1 ]]; then
            if ! docker compose --project-name "$PROJECT" -f "$COMPOSE_FILE" down --volumes --remove-orphans >/dev/null; then
                echo "CLEANUP ERROR: isolated Compose project could not be removed; project=$PROJECT" >&2
                status=1
                echo "CLEANUP ERROR: preserving test image and temporary inputs for manual cleanup: $WORK_DIR" >&2
                IMAGE_CREATED=0
                WORK_DIR_CREATED=0
            fi
        else
            echo "CLEANUP ERROR: preserving temporary inputs because resource ownership could not be verified: $WORK_DIR" >&2
            WORK_DIR_CREATED=0
            IMAGE_CREATED=0
        fi
    fi

    if [[ "$IMAGE_CREATED" == 1 ]]; then
        local image_id image_label
        image_id="$(docker image inspect --format '{{.Id}}' "$IMAGE" 2>/dev/null)"
        image_label="$(docker image inspect --format '{{ index .Config.Labels "com.justice.pitr-test" }}' "$IMAGE" 2>/dev/null)"
        if [[ -n "$image_id" && "$image_label" == "true" ]]; then
            docker image rm "$IMAGE" >/dev/null || {
                echo "CLEANUP ERROR: isolated test image could not be removed: $IMAGE" >&2
                status=1
            }
        elif [[ -n "$image_id" ]]; then
            echo "CLEANUP ERROR: refusing to remove image without this test's label: $IMAGE" >&2
            status=1
        fi
    fi

    if [[ "$WORK_DIR_CREATED" == 1 && "$WORK_DIR" == "$TEMP_PARENT"/justice-pitr-restore.* && -d "$WORK_DIR" ]]; then
        rm -rf -- "$WORK_DIR"
    elif [[ "$WORK_DIR_CREATED" == 1 && -n "$WORK_DIR" ]]; then
        echo "CLEANUP ERROR: refusing to remove unexpected temporary path: $WORK_DIR" >&2
        status=1
    fi

    if [[ "$status" -eq 0 ]]; then
        log "cleanup complete; only this test's labeled resources were removed"
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for command_name in docker bash tar head cp sed; do
    command -v "$command_name" >/dev/null 2>&1 || fail "required command is missing: $command_name"
done
docker compose version >/dev/null 2>&1 || fail "Docker Compose plugin is required"

WORK_DIR="$(mktemp -d "$TEMP_PARENT/justice-pitr-restore.XXXXXX")" || fail "could not create a private temporary directory"
WORK_DIR_CREATED=1
chmod 0700 "$WORK_DIR"
if command -v cygpath >/dev/null 2>&1; then
    DOCKER_WORK_DIR="$(cygpath -m "$WORK_DIR")"
else
    DOCKER_WORK_DIR="$WORK_DIR"
fi
mkdir -p "$WORK_DIR/bin" "$WORK_DIR/backups" "$WORK_DIR/wal" "$WORK_DIR/build-context/deploy/postgres"
chmod 0777 "$WORK_DIR/wal"
COMPOSE_FILE="$WORK_DIR/compose.yml"

# Use only the already-selected local engine while bypassing host credential
# helpers. Public base images are pulled anonymously; no user Docker auth file is
# read or copied into this test.
DOCKER_CONTEXT="$(docker context show 2>/dev/null)" || fail "could not identify the selected Docker context"
DOCKER_ENDPOINT="$(docker context inspect "$DOCKER_CONTEXT" --format '{{ .Endpoints.docker.Host }}' 2>/dev/null)" || fail "could not inspect the selected Docker endpoint"
case "$DOCKER_ENDPOINT" in
    npipe:////./pipe/dockerDesktopLinuxEngine|npipe:////./pipe/docker_engine|unix:///var/run/docker.sock|unix:///run/user/*/docker.sock) ;;
    *) fail "refusing non-local Docker context endpoint: $DOCKER_ENDPOINT" ;;
esac
mkdir "$WORK_DIR/docker-config"
chmod 0700 "$WORK_DIR/docker-config" 2>/dev/null || true
printf '{"auths":{}}\n' >"$WORK_DIR/docker-config/config.json"
export DOCKER_HOST="$DOCKER_ENDPOINT" DOCKER_CONFIG="$WORK_DIR/docker-config"
docker info >/dev/null 2>&1 || fail "local Docker daemon is unavailable"

# Prove the generated project name has no resources before Compose can mutate it.
if [[ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ||
      -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT")" ||
      -n "$(docker network ls -q --filter "label=com.docker.compose.project=$PROJECT")" ]]; then
    fail "generated project label already exists; refusing to reuse it: $PROJECT"
fi
if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    fail "generated image tag already exists; refusing to reuse it: $IMAGE"
fi

log "building the repository PostgreSQL image with age helpers"
for postgres_file in Dockerfile archive-wal.sh restore-wal.sh prepare-postgres.sh recovery-startup.sh; do
    cp "$ROOT/deploy/postgres/$postgres_file" "$WORK_DIR/build-context/deploy/postgres/$postgres_file"
done
docker build --label com.justice.pitr-test=true --tag "$IMAGE" \
    --file "$WORK_DIR/build-context/deploy/postgres/Dockerfile" "$WORK_DIR/build-context"
IMAGE_CREATED=1

RECIPIENT="pending"

cat >"$COMPOSE_FILE" <<YAML
services:
  keygen:
    image: "$IMAGE"
    volumes:
      - age-keys:/run/secrets
    labels:
      com.justice.pitr-test: "true"

  db:
    image: "$IMAGE"
    entrypoint: ["/usr/local/bin/prepare-postgres.sh"]
    command:
      - postgres
      - -c
      - wal_level=replica
      - -c
      - archive_mode=on
      - -c
      - archive_timeout=2s
      - -c
      - "archive_command=/usr/local/bin/archive-wal.sh %p %f"
      - -c
      - max_wal_senders=4
    environment:
      POSTGRES_USER: pitr_test
      POSTGRES_PASSWORD: disposable-pitr-password
      POSTGRES_DB: pitr_test
      PGDATA: /var/lib/postgresql/data
      AGE_BACKUP_RECIPIENTS: "\${PITR_AGE_BACKUP_RECIPIENTS:-pending}"
      AGE_BACKUP_RECIPIENTS_NEXT: "\${PITR_AGE_BACKUP_RECIPIENTS_NEXT:-}"
      AGE_IDENTITY_FILE: /run/secrets/new.identity
      WAL_ARCHIVE_DIR: /var/lib/postgresql/wal-archive
    volumes:
      - pgdata:/var/lib/postgresql/data
      - "$DOCKER_WORK_DIR/wal:/var/lib/postgresql/wal-archive"
      - age-keys:/run/secrets:ro
      - "$DOCKER_WORK_DIR/backups:/backups:ro"
    labels:
      com.justice.pitr-test: "true"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U pitr_test -d pitr_test"]
      interval: 2s
      timeout: 2s
      retries: 45

  recovery:
    image: "$IMAGE"
    entrypoint: ["/usr/local/bin/recovery-startup.sh"]
    command: ["postgres"]
    environment:
      POSTGRES_USER: pitr_test
      POSTGRES_PASSWORD: disposable-pitr-password
      POSTGRES_DB: pitr_test
      PGDATA: /var/lib/postgresql/data
      AGE_IDENTITY_FILE: /run/secrets/new.identity
      WAL_ARCHIVE_DIR: /var/lib/postgresql/wal-archive
    volumes:
      - recovery-data:/var/lib/postgresql/data
      - "$DOCKER_WORK_DIR/wal:/var/lib/postgresql/wal-archive:ro"
      - age-keys:/run/secrets:ro
      - "$DOCKER_WORK_DIR/backups:/backups:ro"
    labels:
      com.justice.pitr-test: "true"

volumes:
  age-keys:
  pgdata:
  recovery-data:
YAML

compose() { docker compose --project-name "$PROJECT" -f "$COMPOSE_FILE" "$@"; }
COMPOSE_TOUCHED=1
compose config --quiet || fail "temporary Compose configuration is invalid"

# Generate both identities in a project-labeled Docker volume. Capture public
# recipients only; never emit identity material.
KEYGEN_OUTPUT="$(compose run --rm --no-deps -T --user root --entrypoint bash keygen -ceu '
    age-keygen -o /run/secrets/old.identity 2>/dev/null
    age-keygen -o /run/secrets/new.identity 2>/dev/null
    chmod 0444 /run/secrets/old.identity /run/secrets/new.identity
    printf "old=%s\n" "$(age-keygen -y /run/secrets/old.identity)"
    printf "new=%s\n" "$(age-keygen -y /run/secrets/new.identity)"
' 2>/dev/null)" || fail "could not generate temporary age identities in isolated volume"
OLD_RECIPIENT="$(printf '%s\n' "$KEYGEN_OUTPUT" | sed -n 's/^old=//p')"
NEW_RECIPIENT="$(printf '%s\n' "$KEYGEN_OUTPUT" | sed -n 's/^new=//p')"
[[ "$OLD_RECIPIENT" =~ ^age1[[:alnum:]]+$ && "$NEW_RECIPIENT" =~ ^age1[[:alnum:]]+$ && "$OLD_RECIPIENT" != "$NEW_RECIPIENT" ]] || fail "generated age recipients are malformed or duplicated"
export PITR_AGE_BACKUP_RECIPIENTS="$OLD_RECIPIENT" PITR_AGE_BACKUP_RECIPIENTS_NEXT="$NEW_RECIPIENT"

# The backup helper expects an age executable on the host. Route it through a
# one-shot container from this test project, so the host needs no age install.
cat >"$WORK_DIR/bin/age" <<'SH'
#!/usr/bin/env bash
set -Eeuo pipefail
export MSYS_NO_PATHCONV=1
compose_file="$(cygpath -m "$PITR_COMPOSE_FILE")"
exec docker compose --project-name "$PITR_PROJECT" -f "$compose_file" \
    run --rm --no-deps -T --entrypoint age db "$@"
SH
chmod 0700 "$WORK_DIR/bin/age"
export PITR_PROJECT="$PROJECT" PITR_COMPOSE_FILE="$COMPOSE_FILE"
export PATH="$WORK_DIR/bin:$PATH"

log "starting isolated synthetic PostgreSQL"
compose up -d db
deadline=$((SECONDS + 120))
until compose exec -T db pg_isready -U pitr_test -d pitr_test >/dev/null 2>&1; do
    (( SECONDS < deadline )) || {
        compose logs db >&2
        fail "synthetic PostgreSQL did not become ready"
    }
    sleep 2
done

compose exec -T db psql -U pitr_test -d pitr_test -v ON_ERROR_STOP=1 \
    -c 'CREATE TABLE pitr_probe (marker text PRIMARY KEY)' \
    -c "INSERT INTO pitr_probe VALUES ('before-target')" >/dev/null

# Use the production backup helper, with its age subprocess isolated in Compose.
DB_CONTAINER="$(compose ps -q db)"
[[ -n "$DB_CONTAINER" ]] || fail "isolated database container ID is unavailable"
export DB_CONTAINER POSTGRES_USER=pitr_test POSTGRES_DB=pitr_test
export AGE_BACKUP_RECIPIENTS="$OLD_RECIPIENT" AGE_BACKUP_RECIPIENTS_NEXT="$NEW_RECIPIENT"
export BACKUP_DIR="$WORK_DIR/backups" WAL_ARCHIVE_DIR="$WORK_DIR/wal"
export TIMESTAMP="pitr_dual_$(date +%Y%m%d_%H%M%S)_$$"
log "creating dual-recipient encrypted base backup with deploy/backup.sh"
"$ROOT/deploy/backup.sh"
BASE_BACKUP="$BACKUP_DIR/base_${TIMESTAMP}.tar.gz.age"
[[ -s "$BASE_BACKUP" ]] || fail "encrypted base backup was not created"
[[ "$(head -c 4 "$BASE_BACKUP")" == "age-" ]] || fail "base backup does not have an age envelope"

# Record a target immediately before the second transaction. The known row is
# inside the base backup; the later row must be absent after recovery.
TARGET_TIME="$(compose exec -T db psql -U pitr_test -d pitr_test -Atqc \
    "SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS.US')")"
[[ "$TARGET_TIME" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}$ ]] || fail "could not record a valid UTC recovery target"
TARGET_TIME+="+00"
compose exec -T db psql -U pitr_test -d pitr_test -v ON_ERROR_STOP=1 \
    -c "INSERT INTO pitr_probe VALUES ('after-target')" >/dev/null
POST_TARGET_WAL="$(compose exec -T db psql -U pitr_test -d pitr_test -Atqc \
    'SELECT pg_walfile_name(pg_current_wal_lsn())')"
[[ "$POST_TARGET_WAL" =~ ^[0-9A-Fa-f]{24}$ ]] || fail "could not identify the WAL segment containing the post-target commit"
compose exec -T db psql -U pitr_test -d pitr_test -Atqc 'SELECT pg_switch_wal()' >/dev/null

log "waiting for encrypted WAL segment $POST_TARGET_WAL"
deadline=$((SECONDS + 180))
while [[ ! -s "$WAL_ARCHIVE_DIR/$POST_TARGET_WAL.age" ]]; do
    (( SECONDS < deadline )) || {
        compose logs db >&2
        fail "PostgreSQL did not archive an encrypted WAL segment"
    }
    sleep 2
done

# Recreate only the PostgreSQL container, retaining its labeled data volume,
# age-key volume, and WAL archive. The replacement receives only the new age
# recipient; the old identity remains available until every retained-artifact
# and PITR check has completed.
log "recreating PostgreSQL with only the new age recipient"
OLD_DB_CONTAINER="$DB_CONTAINER"
compose stop db >/dev/null
compose rm --force db >/dev/null
export PITR_AGE_BACKUP_RECIPIENTS="$NEW_RECIPIENT" PITR_AGE_BACKUP_RECIPIENTS_NEXT=""
export AGE_BACKUP_RECIPIENTS="$NEW_RECIPIENT" AGE_BACKUP_RECIPIENTS_NEXT=""
compose up -d db
deadline=$((SECONDS + 120))
until compose exec -T db pg_isready -U pitr_test -d pitr_test >/dev/null 2>&1; do
    (( SECONDS < deadline )) || {
        compose logs db >&2
        fail "PostgreSQL did not restart with the new-only recipient"
    }
    sleep 2
done
DB_CONTAINER="$(compose ps -q db)"
[[ -n "$DB_CONTAINER" && "$DB_CONTAINER" != "$OLD_DB_CONTAINER" ]] || fail "PostgreSQL container was not recreated"
before_persisted="$(compose exec -T db psql -U pitr_test -d pitr_test -Atqc "SELECT count(*) FROM pitr_probe WHERE marker='before-target'")"
after_persisted="$(compose exec -T db psql -U pitr_test -d pitr_test -Atqc "SELECT count(*) FROM pitr_probe WHERE marker='after-target'")"
[[ "$before_persisted" == 1 && "$after_persisted" == 1 ]] || fail "database rows did not survive container recreation"

export DB_CONTAINER
export TIMESTAMP="pitr_new_only_$(date +%Y%m%d_%H%M%S)_$$"
log "creating new-recipient-only backup with deploy/backup.sh"
"$ROOT/deploy/backup.sh"
NEW_ONLY_BACKUP="$BACKUP_DIR/base_${TIMESTAMP}.tar.gz.age"
[[ -s "$NEW_ONLY_BACKUP" && "$(head -c 4 "$NEW_ONLY_BACKUP")" == "age-" ]] || fail "new-only encrypted backup was not created"

assert_backup_decrypts() {
    local identity_name="$1" backup_name="$2"
    if ! "$WORK_DIR/bin/age" --decrypt --identity "/run/secrets/$identity_name" \
        --output - "/backups/$backup_name" | tar -tzf - >/dev/null; then
        fail "age identity $identity_name could not decrypt retained backup $backup_name"
    fi
}
assert_backup_decrypts new.identity "$(basename "$BASE_BACKUP")"
assert_backup_decrypts new.identity "$(basename "$NEW_ONLY_BACKUP")"
assert_backup_decrypts old.identity "$(basename "$BASE_BACKUP")"
if "$WORK_DIR/bin/age" --decrypt --identity /run/secrets/old.identity \
    --output /dev/null "/backups/$(basename "$NEW_ONLY_BACKUP")" >/dev/null 2>&1; then
    fail "old age identity unexpectedly decrypted the new-only backup"
fi
log "PASS: new identity decrypts both retained backups; old identity decrypts only the dual-recipient backup"

# Confirm WAL encrypted before and after rotation remains decryptable by the
# intended identities. The post-target segment is dual-recipient; the later
# segment generated after container recreation is new-recipient-only.
decrypt_wal() {
    local identity_name="$1" wal_name="$2"
    "$WORK_DIR/bin/age" --decrypt --identity "/run/secrets/$identity_name" \
        --output /dev/null "/var/lib/postgresql/wal-archive/$wal_name.age"
}
decrypt_wal new.identity "$POST_TARGET_WAL" || fail "new identity cannot decrypt post-target WAL archived before rotation"
decrypt_wal old.identity "$POST_TARGET_WAL" || fail "old identity cannot decrypt the retained dual-recipient WAL"

POST_ROTATION_WAL="$(compose exec -T db psql -U pitr_test -d pitr_test -Atqc \
    'SELECT pg_walfile_name(pg_current_wal_lsn())')"
[[ "$POST_ROTATION_WAL" =~ ^[0-9A-Fa-f]{24}$ && "$POST_ROTATION_WAL" != "$POST_TARGET_WAL" ]] || fail "could not identify a distinct post-rotation WAL segment"
compose exec -T db psql -U pitr_test -d pitr_test -Atqc 'SELECT pg_switch_wal()' >/dev/null
log "waiting for new-only encrypted WAL segment $POST_ROTATION_WAL"
deadline=$((SECONDS + 180))
while [[ ! -s "$WAL_ARCHIVE_DIR/$POST_ROTATION_WAL.age" ]]; do
    (( SECONDS < deadline )) || {
        compose logs db >&2
        fail "PostgreSQL did not archive post-rotation WAL"
    }
    sleep 2
done
decrypt_wal new.identity "$POST_ROTATION_WAL" || fail "new identity cannot decrypt post-rotation WAL"
if decrypt_wal old.identity "$POST_ROTATION_WAL" >/dev/null 2>&1; then
    fail "old age identity unexpectedly decrypted post-rotation WAL"
fi
log "PASS: post-rotation WAL decrypts with the new identity only"

# Decrypt the base archive inside the isolated recovery service volume, configure
# the same restore helper/readiness contract as restore-pitr.sh, and start PITR.
log "preparing isolated PITR restore to $TARGET_TIME"
compose run --rm --no-deps --user root --entrypoint bash recovery -ceu '
    age --decrypt --identity "$AGE_IDENTITY_FILE" --output - "/backups/$1" |
        tar -xz -C "$PGDATA"
    touch "$PGDATA/recovery.signal"
    quote=$(printf "\\047")
    {
        printf "restore_command = %s/usr/local/bin/restore-wal.sh %%f %%p%s\\n" "$quote" "$quote"
        printf "recovery_target_time = %s%s%s\\n" "$quote" "$2" "$quote"
        printf "recovery_target_action = %spromote%s\\n" "$quote" "$quote"
    } >>"$PGDATA/postgresql.auto.conf"
    chown -R postgres:postgres "$PGDATA"
    touch "$PGDATA/.recovery-ready.tmp"
    chown postgres:postgres "$PGDATA/.recovery-ready.tmp"
    mv "$PGDATA/.recovery-ready.tmp" "$PGDATA/.recovery-ready"
' _ "$(basename "$BASE_BACKUP")" "$TARGET_TIME" || fail "could not extract and prepare the encrypted base backup"

compose up -d recovery
deadline=$((SECONDS + 180))
while :; do
    if recovery_state="$(compose exec -T recovery bash -ceu \
        'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT pg_is_in_recovery()"' 2>/dev/null)"; then
        [[ "$recovery_state" == "f" ]] && break
    fi
    (( SECONDS < deadline )) || {
        compose logs recovery >&2
        fail "PITR did not complete and promote within 180 seconds"
    }
    sleep 2
done

before_count="$(compose exec -T recovery psql -U pitr_test -d pitr_test -Atqc \
    "SELECT count(*) FROM pitr_probe WHERE marker='before-target'")"
after_count="$(compose exec -T recovery psql -U pitr_test -d pitr_test -Atqc \
    "SELECT count(*) FROM pitr_probe WHERE marker='after-target'")"
[[ "$before_count" == 1 ]] || fail "pre-target row missing after PITR (count=$before_count)"
[[ "$after_count" == 0 ]] || fail "post-target row survived PITR (count=$after_count)"

log "PASS: encrypted base backup and WAL restored; before-target=present, after-target=absent"
