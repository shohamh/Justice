# Browser E2E maintenance

For every human-critical feature, identify the role journey, the visible post-mutation state, and the authorization boundary. Add the browser assertion at that boundary and use a stable `data-testid` only when the user-facing label is not a durable selector.

Keep workflow tests serial until their data isolation is proven. Run the smoke tier on both configured viewports; run the full tier before release. Do not hide failures with broad waits or production-only test branches.

The release threshold is several consecutive clean CI runs, no retry-only green tests, and failure artifacts sufficient to classify the problem. The suite publishes the Playwright report on failure; traces, screenshots, console/page errors, and failed requests should be attached to the test result.

The multi-user duty-problem journey is serial because it deliberately carries one
shift through several authenticated roles. It uses the seeded journey accounts
from `fixtures/auth.ts`; keep their dates in the future relative to the seeded
clock and preserve the UI-only rule (no request, fetch, or database setup in the
spec). The journey needs a running backend and PostgreSQL seed; the in-app
browser is optional, while the Playwright desktop project is the reproducible
fallback for local validation.
