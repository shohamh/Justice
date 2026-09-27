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

Tests use fakes/unit transports. Live MinIO/S3 was not verified; the Task 4 official Quay image pull returned HTTP 401. Independent Task 5 review found two Important lifecycle issues and one Minor request-ID trace issue; fix round 1 is implemented and pending scoped re-review.


## Fix round 1: stream ownership and request trace

The first review found that Starlette cancellation could skip the generator finalizer and background task, leaving the object body and semaphore permit open. A managed response now closes an idempotent lease in its ASGI call's synchronous finally, and the generator/background paths use the same lease. A real ASGI disconnect test was RED (body remained open) and is GREEN.

The review also found that asyncio.wait_for(asyncio.to_thread(open_read)) can time out while the worker still opens a body. The pending-open owner now records abandonment under a lock, closes any body already returned, and makes a late worker close its own result. The open task is shielded so timeout does not cancel the bookkeeping, and its terminal result is retrieved. A late-open timeout test was RED (body remained open) and is GREEN. Pre-response cleanup now releases the permit even if body closure raises.

A validated ingress X-Request-ID UUID (or one generated once at ingress) is forwarded by AuthorizationClient to the authorization service. Its existing audit path stores that same header UUID. The ASGI test checks ingress-to-client propagation; the redirect transport test checks the client's outgoing header.

Evidence:

    python -m pytest app/file_gateway/tests/test_review_lifecycle.py -q -n0 -ra --tb=short
    3 passed, 1 warning
    python -m pytest app/file_authorization/tests app/file_gateway/tests -q -n0 -ra --tb=short
    34 passed, 1 warning
    python -m ruff check --output-format concise app/file_authorization app/file_gateway app/audit/writer.py
    All checks passed!
    git diff --check
    passed

The warning is from the installed environment's Starlette 0.37.2 starlette/formparsers.py:12, which imports multipart; installed python-multipart 0.0.30 emits PendingDeprecationWarning: Please use import python_multipart instead. The repository's backend/uv.lock resolves newer FastAPI 0.137.1 and Starlette 1.3.1. No application code imports that legacy module, and this fix does not change framework dependency resolution or suppress warnings. Container dependency validation remains in Task 8.

After the first fix commit, a self-review found that Starlette can run synchronous background callbacks in a worker thread while ASGI finally closes on the event loop. The lease now locks close through object closure and permit release; a concurrent close regression checks that a second caller waits for the first and capacity is released exactly once. The background cleanup callback is async so the asyncio semaphore is released on the event loop. The final focused results above include this follow-up.
