# Task 5: Authorized streaming file gateway

## Scope and result

Implemented the private file authorization service and streaming download gateway. The authorization endpoint is `POST /_internal/file-authorizations`, disabled from public OpenAPI/docs, and resolves each request against current database records and permissions. The gateway exposes the six intended download route families, sends the end-user bearer token only to the fixed internal authorization endpoint, and accesses object storage only after an allow decision.

Authorization covers exemption-request files (owner or current medical-document viewer), soldier exemption files (self or scoped exemption permission, with current medical-document permission for medical files and rejection of revoked records), Gimelim attachments (exact dismissal/assignment relationship and current assignment management scope), bug report screenshots and comment attachments (reporter or admin with exact parent binding), and import workbooks (creator who remains a duty manager or admin). Protected classes enforce the existing password-change gate; import workbooks retain their DM/admin behavior.

The gateway validates canonical object keys against route resource UUIDs, rejects Range requests, initializes a default sliding-window rate limiter, holds a bounded concurrent-stream semaphore through body completion/closure, bounds response sizes, validates authorization metadata and headers, disables authorization redirects, and fails closed on authorization/storage errors.

## RED evidence

Before implementation:

```text
python -m pytest app/file_authorization/tests/test_policies.py app/file_authorization/tests/test_routes.py -q
```

Result: collection failed with 2 errors because the planned `app.file_authorization.schemas` and `app.file_authorization.main` modules did not yet exist.

## GREEN evidence

```text
python -m pytest app/file_authorization/tests app/file_gateway/tests -n0 -ra --tb=short
31 passed, 1 warning in 2.24s
```

The suite covers the policy matrix (including exemption-request medical viewer allow/deny), password-change gate, parent and route-ID mismatch, revoked/missing resources, auth outage/timeout/redirect, malformed/oversized decisions, cookie-only denial, active stream limits, streamed size failure, cancellation/body closure, default rate-limit wiring, and secure response headers.

```text
python -m ruff check --output-format concise app/file_authorization app/file_gateway app/audit/writer.py
All checks passed!
git diff --check
passed (Git emitted only an LF-to-CRLF working-copy advisory for backend/app/audit/writer.py)
```

## mTLS boundary and remaining verification

The authorization service `run()` configures Uvicorn with `ssl_cert_reqs=ssl.CERT_REQUIRED`, the server certificate/key, and the dedicated gateway CA bundle. Start it with `python -m app.file_authorization.main`. This applies client-certificate enforcement when that startup path is used. Compose/proxy wiring and deployed listener verification belong to Task 8 and are not complete in this deliverable.

Tests use fakes/unit transports. Live MinIO/S3 was not verified; the Task 4 official Quay image pull returned HTTP 401. Independent Task 5 review is pending.
