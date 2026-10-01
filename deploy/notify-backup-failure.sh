#!/usr/bin/env bash
# Send a generic backup failure notification to an HTTPS webhook. Credentials
# are read from the host scheduler environment and never included in output.
set -euo pipefail

WEBHOOK="${BACKUP_ALERT_WEBHOOK:-}"
if [[ -z "$WEBHOOK" ]]; then
    echo "ERROR: Backup alert not delivered; BACKUP_ALERT_WEBHOOK is not configured" >&2
    exit 78
fi
if ! printf '%s' "$WEBHOOK" | grep -Eq '^https://[^[:space:]"\\]+$'; then
    echo "ERROR: Backup alert not delivered; BACKUP_ALERT_WEBHOOK must be an HTTPS URL without whitespace or quotes" >&2
    exit 64
fi

HTTP_CODE=""
CURL_STATUS=0
if HTTP_CODE="$(
    printf 'url = "%s"\nrequest = "POST"\nheader = "Content-Type: application/json"\ndata = "{\\"text\\":\\"Justice PostgreSQL backup or WAL archiving failed. Review protected host backup logs.\\"}"\nmax-time = 10\nsilent\noutput = "/dev/null"\nwrite-out = "%%{http_code}"\n' "$WEBHOOK" |
        curl --config - 2>/dev/null
)"; then
    CURL_STATUS=0
else
    CURL_STATUS=$?
fi
if [[ "$CURL_STATUS" -eq 0 && "$HTTP_CODE" =~ ^2[0-9][0-9]$ ]]; then
    echo "Backup failure alert delivered"
    exit 0
fi
echo "ERROR: Backup alert delivery failed (curl status ${CURL_STATUS}, HTTP ${HTTP_CODE:-none}); webhook details redacted" >&2
exit 1
