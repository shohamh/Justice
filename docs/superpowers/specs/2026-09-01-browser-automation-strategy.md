# Browser Automation Strategy

## Goal

Protect the human-critical Justice workflows that are currently vulnerable to regressions between the frontend and backend: broken buttons, failed approvals, stale tables, navigation failures, and incorrect role visibility.

## Decisions

- Use Playwright in the existing `frontend/tests/e2e` harness.
- Exercise the real frontend, backend, and PostgreSQL database.
- Use deterministic seeded fixtures and isolated test data per run.
- Cover regular soldiers, commanders, duty managers/deputies, and admins.
- Use Chrome desktop and a 390px mobile viewport.
- Keep the first blocking suite to 8-10 critical journeys.
- Use authenticated browser state for most tests; retain direct UI login coverage separately.
- Use one browser context per role and multiple contexts for cross-user workflows.
- Run serially first; introduce parallel workers only after isolation is demonstrated.
- Allow one retry in CI only; retry-passing tests remain flaky defects.
- Capture traces, screenshots, console errors, failed requests, and backend logs on failure. Do not enable video by default.
- Assert visible post-mutation state, including cross-user consequences, rather than only HTTP success.
- Prefer accessible roles and labels, adding targeted `data-testid` attributes for dynamic domain state.

## Initial blocking journeys

1. Login, forced password change, and session persistence.
2. Regular soldier sees the homepage, representative table, and calendar.
3. Soldier submits a personal constraint and sees it in their request list.
4. Soldier sees the request status after another user acts on it.
5. Authorized commander or duty manager sees pending work in scope.
6. Authorized reviewer approves a request and the pending row disappears.
7. Authorized reviewer rejects a request with a required reason.
8. Unauthorized role cannot access or mutate another unit's work.
9. Admin creates a core configuration item through the UI.
10. A representative table filters, paginates, and renders empty/error states.

## Acceptance criteria

- `npm run test:e2e -- --project=chromium` runs the blocking suite against the real stack.
- Both configured viewports pass for the blocking journeys.
- Cross-role tests create, approve/reject, refresh, and re-read the same domain record.
- A failed test retains enough artifacts to identify whether the failure was browser, API, backend, or data setup related.
- CI runs the smoke suite on pull requests and the broader suite on `dev`/release validation.
- `docs/superpowers/plans/2026-09-01-browser-automation-tests.md` records the implementation and verification steps.
