# Frontend Untrusted Data and Telemetry Remediation — Design

Date: 2026-10-05
Status: Draft for review
Audit baseline: `2e1515f7` (`dev`)

## Context

The frontend security audit found two confirmed data-flow problems:

1. Bug-report navigation history accepts an arbitrary string in `backend/app/routes/bug_reports.py` and later passes it to React Router as a link in `frontend/src/pages/admin/BugReportsContent.tsx`. A malicious reporter can therefore persist an executable URL for an administrator to follow.
2. Frontend error reports include the full current URL for HTTP 500s and global JavaScript errors. Reset-password, verification, and action pages put one-time workflow tokens in the query string. Client and server redaction is key-based, so the token inside a URL string can reach backend logs.

The same audit found no conventional CSRF path to business mutations. Business requests require a JavaScript-set Bearer token; the refresh cookie is HttpOnly, SameSite Strict, and scoped to `/api/auth`. This design preserves that session model and does not add a generic CSRF token framework.

## Goals

1. Ensure neither new nor previously stored navigation-history values can execute or navigate when an administrator views a report.
2. Keep reset, verification, and email-action tokens out of frontend telemetry, backend logs, and referrer headers.
3. Preserve legitimate bug reporting, error diagnosis, and email-action behavior.
4. Add regression coverage at the API, rendering, telemetry, and log-scrubbing boundaries.

## Design

### Bug-report navigation history

- Treat each history value as a path emitted by `location.pathname`, not as a general URL.
- Validate new `nav_history[].path` values at the backend boundary. Accept a local absolute path beginning with exactly one `/`; reject a scheme, authority/protocol-relative path, backslash, control character, query, or fragment. Return a normal validation error for invalid submissions.
- Render all stored navigation-history paths as React text, not as `<Link>` or `<a>` destinations. This also makes old database rows safe without a migration or destructive rewrite.
- Keep the existing path text and timestamp visible to administrators. The text remains copyable for manual navigation if needed.

### Error telemetry and workflow tokens

- Frontend telemetry sends only the current pathname. It omits query and fragment values. Axios request URL fields are reduced to a safe path and do not retain query values.
- The backend applies URL-aware scrubbing to URL-valued fields before passing the payload to structured logging. It removes query and fragment components even for older clients that still send full URLs.
- Reset-password, email-verification, and email-action pages capture the token once into component state/ref, then use a replace navigation to remove it from the visible URL. The POST continues to send the token in its request body. The action page guards the replace navigation and effect lifecycle so clearing the query cannot drop the captured token or issue a duplicate action request.
- Do not place tokens in error messages or diagnostic context. Continue applying existing key-based redaction to structured fields.

### Email action and CSRF disposition

- Preserve the current email-action semantics by default: the action still requires the matching signed-in user and the user-bound action token.
- During deployment review, check the actual trusted CORS origins and whether any untrusted sibling origin shares the app's site. Add Origin or Fetch Metadata checks to cookie-authenticated endpoints only if that deployment condition exists.
- Do not add CSRF tokens to ordinary Bearer-authenticated business endpoints. If an authenticated mail scanner is shown to execute the email action, require a visible confirmation click before posting it; otherwise keep the one-click workflow.

## Scope

Expected implementation areas include `backend/app/routes/bug_reports.py`, `frontend/src/pages/admin/BugReportsContent.tsx`, `frontend/src/errorReporting.ts`, the reset/verification/action pages, `backend/app/routes/client_errors.py`, and `backend/app/error_logging.py`. No database schema change is required.

## Acceptance criteria

1. API requests containing `javascript:`, `//external.example`, backslashes, control characters, queries, or fragments in history paths are rejected.
2. A historical unsafe path is displayed only as text and creates no active anchor destination.
3. A reset, verification, action, HTTP-500, uncaught-error, and unhandled-rejection report contains no query or fragment token.
4. Backend log payloads contain no query or fragment from URL-valued telemetry fields, including payloads from legacy clients.
5. Email actions still redeem only for the matching authenticated user; their token is removed from the address bar after capture.
6. The production document's `Referrer-Policy` is covered by the separate SPA headers design.
7. Removing an action token from the URL does not trigger a second redemption attempt or lose the token before the single POST.

## Non-goals

- Changing the app's JWT/refresh-cookie architecture.
- Changing email-action UX without evidence of an authenticated scanner risk.
- Rewriting or deleting old bug reports.
- Adding broad input sanitization to ordinary React text nodes, which React already escapes.
