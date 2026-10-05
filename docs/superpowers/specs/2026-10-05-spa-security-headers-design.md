# SPA Security Headers — Design

Date: 2026-10-05
Status: Draft for review
Audit baseline: `2e1515f7` (`dev`)

## Context

Production serves the built React application from Nginx. The backend security middleware adds a Content-Security-Policy and Referrer-Policy to API responses, but those headers do not govern the separately served SPA document. `deploy/nginx.conf` currently sets HSTS, `X-Content-Type-Options`, and `X-Frame-Options` only. `frontend/index.html` has an inline theme bootstrap. The nested static-asset location adds its own `Cache-Control` header, which changes normal Nginx `add_header` inheritance.

## Goals

1. Deliver a Content-Security-Policy from the response that serves the SPA HTML document.
2. Prevent the current inline theme script from requiring a broad inline-script allowance.
3. Deliver a restrictive Referrer-Policy on the SPA document to reduce leakage of token-bearing URLs.
4. Roll out CSP without breaking PDF rendering, downloads, Blob previews, fonts, images, API calls, or Hebrew/RTL styling.

## Design

- Move the theme bootstrap to a same-origin static JavaScript file loaded from the document head. Preserve the current pre-render theme behavior.
- Add CSP to the effective Nginx configuration for the SPA HTML response. Start with `Content-Security-Policy-Report-Only` in a controlled deployment, review browser violations across normal workflows, then enforce the reviewed policy.
- Build the policy from the app's actual production resource needs. Avoid broad `unsafe-eval`; do not add `unsafe-inline` to `script-src`. Explicitly assess workers and Blob URLs used by PDF.js and file previews, style attributes, data URLs, API connections, and any external resources before finalizing directives.
- Set `Referrer-Policy: no-referrer` on the SPA document. The backend's API response policy remains independent.
- Account for the Nginx 1.27 image's header inheritance behavior. Ensure the intended headers appear on the document response even when assets use the nested location with its own `Cache-Control` directive. Use repeated directives or a shared mounted include; do not rely on newer `add_header_inherit merge` behavior unavailable in this image.
- Preserve existing HSTS, `X-Content-Type-Options`, and `X-Frame-Options` behavior.

## Scope

Expected changes are in `frontend/index.html`, a new static theme bootstrap asset, `deploy/nginx.conf`, and if used, a small Nginx header include plus its read-only Compose mount. No backend middleware change is required for SPA document delivery.

## Acceptance criteria

1. The production SPA document response contains an enforcing CSP after rollout and `Referrer-Policy: no-referrer`.
2. The document contains no inline script requiring an inline-script CSP exception.
3. CSP testing covers login, normal navigation, API traffic, PDF display, image/Blob preview, exports, and downloads with no unexplained violation.
4. Nginx configuration validation passes, and header checks cover SPA routes, fallback routes, and relevant asset locations.
5. The policy contains no broad script execution exception added solely to silence a violation.

## Non-goals

- Replacing the Nginx deployment topology.
- Applying the SPA's policy to unrelated backend API responses.
- Treating CSP as a replacement for the untrusted-navigation fix.
