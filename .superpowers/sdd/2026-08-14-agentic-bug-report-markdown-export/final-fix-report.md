# Final fix report

Date: 2026-08-14
Base commit: `35eb9db5`
Scope: actionable final-review CORS header exposure fix only

## Requirement addressed

Added `Content-Disposition` to the existing backend CORS `expose_headers` list in `backend/app/main.py`, while preserving `Retry-After` and leaving all unrelated CORS settings unchanged.

## Changes made

- Updated `backend/app/main.py` CORS middleware config:
  - from `["Retry-After"]`
  - to `["Retry-After", "Content-Disposition"]`
- Added a focused regression test in `backend/tests/test_security_hardening.py` that verifies the registered `CORSMiddleware` config exposes exactly those two headers.

## Test-first evidence

Red:

```text
pytest -n 0 tests/test_security_hardening.py -k "cors_exposes_retry_after_and_content_disposition" -vv
FAILED
E       AssertionError: assert ['Retry-After'] == ['Retry-After', 'Content-Disposition']
```

Green:

```text
pytest -n 0 tests/test_security_hardening.py -k "cors_disallows_put_method or cors_exposes_retry_after_and_content_disposition" -q
..                                                                       [100%]
```

Formatting:

```text
git diff --check
exit 0
```

## Additional verification note

Running the entire `backend/tests/test_security_hardening.py` file in this checkout is not a clean signal for this fix because the pre-existing `test_security_headers_present` test currently reaches `/api/health`, which attempts a database connection to host `db` and fails in this environment with `psycopg.OperationalError: failed to resolve host 'db'`. That issue is unrelated to the scoped CORS change and was not modified here.

## Scope control

- No frontend files changed for this fix.
- No `BugReportsContent.tsx` refactor was performed.
- No unrelated CORS settings were changed.
