#!/bin/sh
set -eu

cd /opt/justice
exec docker compose --env-file deploy/.env.production -f deploy/docker-compose.prod.yml --profile storage-maintenance run --rm file-storage-maintenance reconcile
