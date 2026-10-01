# PostgreSQL is pinned to the 16.4 Alpine release used by the production data
# volume. age is built from its pinned upstream release, then copied into the
# final database image without a Go toolchain.
FROM golang:1.23.1-alpine3.20 AS age-builder
RUN CGO_ENABLED=0 go install filippo.io/age/cmd/...@v1.2.1

FROM postgres:16.4-alpine3.20
RUN apk add --no-cache bash curl
COPY --from=age-builder /go/bin/age /usr/local/bin/age
COPY --from=age-builder /go/bin/age-keygen /usr/local/bin/age-keygen
COPY deploy/postgres/archive-wal.sh /usr/local/bin/archive-wal.sh
COPY deploy/postgres/restore-wal.sh /usr/local/bin/restore-wal.sh
COPY deploy/postgres/prepare-postgres.sh /usr/local/bin/prepare-postgres.sh
COPY deploy/postgres/recovery-startup.sh /usr/local/bin/recovery-startup.sh
RUN chmod 0755 /usr/local/bin/archive-wal.sh /usr/local/bin/restore-wal.sh /usr/local/bin/prepare-postgres.sh /usr/local/bin/recovery-startup.sh
