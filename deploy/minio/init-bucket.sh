#!/bin/sh
set -eu

required='MINIO_ROOT_USER MINIO_ROOT_PASSWORD MINIO_BUCKET API_ACCESS_KEY API_SECRET_KEY GATEWAY_ACCESS_KEY GATEWAY_SECRET_KEY MAINTENANCE_ACCESS_KEY MAINTENANCE_SECRET_KEY'
for name in $required; do
  eval "value=\${$name:-}"
  if [ -z "$value" ]; then
    echo "required environment variable $name is empty" >&2
    exit 2
  fi
done

case "$MINIO_BUCKET" in
  ''|[-]*|*[-]|*[!a-z0-9-]*)
    echo "MINIO_BUCKET must be a 3-63 character lowercase S3 bucket name using letters, digits, and internal hyphens" >&2
    exit 2
    ;;
esac
if [ "${#MINIO_BUCKET}" -lt 3 ] || [ "${#MINIO_BUCKET}" -gt 63 ]; then
  echo "MINIO_BUCKET must be between 3 and 63 characters" >&2
  exit 2
fi

mc alias set local https://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" --api S3v4
mc mb --ignore-existing "local/$MINIO_BUCKET"
mc anonymous set none "local/$MINIO_BUCKET"

# Re-apply each policy on every run so policy files remain the source of truth.
# Existing users are retained and their policy attachments are reapplied.
for policy in api-put-get gateway-get maintenance; do
  rendered_policy="/tmp/$policy.json"
  sed "s/__BUCKET__/$MINIO_BUCKET/g" "/policies/$policy.json" > "$rendered_policy"
  # MinIO mc admin policy create replaces an existing same-name policy.
  # Do not mask failures: stale permissions must never survive initialization.
  mc admin policy create local "$policy" "$rendered_policy"
done

mc admin user info local "$API_ACCESS_KEY" >/dev/null 2>&1 || mc admin user add local "$API_ACCESS_KEY" "$API_SECRET_KEY"
mc admin policy attach local api-put-get --user "$API_ACCESS_KEY"
mc admin user info local "$GATEWAY_ACCESS_KEY" >/dev/null 2>&1 || mc admin user add local "$GATEWAY_ACCESS_KEY" "$GATEWAY_SECRET_KEY"
mc admin policy attach local gateway-get --user "$GATEWAY_ACCESS_KEY"
mc admin user info local "$MAINTENANCE_ACCESS_KEY" >/dev/null 2>&1 || mc admin user add local "$MAINTENANCE_ACCESS_KEY" "$MAINTENANCE_SECRET_KEY"
mc admin policy attach local maintenance --user "$MAINTENANCE_ACCESS_KEY"

echo "MinIO bucket $MINIO_BUCKET initialized with private access and three scoped users"
