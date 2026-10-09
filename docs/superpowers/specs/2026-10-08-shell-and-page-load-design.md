# Shell and page-load optimization — design

Date: 2026-10-08. Branch: stacks on `feature/transparency-bounded-continuation` (the Paint Timing instrumentation, `e72b8cdf`, lives only there).

## Problem

The 2026-10-08 FCP recapture (`docs/benchmarks/data/transparency-keyset-browser-c{1,5}-fcp-recapture-v2-20261008.json`, 20,120 Soldiers / 1,000,008 assignments) shows that every page, not just Transparency, is slow, and slow in the same way:

- c5 cold first-contentful-paint (FCP) is 3.4-3.8 s on every page; c1 is 1.2-1.6 s.
- c5 cold page-ready is 9-17 s on every page except Transparency.
- The page-specific API calls are not the dominant cost. The same shell requests appear on every page.

## Evidence (leads, each from the v2 captures or source)

| # | Lead | Evidence | Confidence |
|---|---|---|---|
| L1 | `GET /api/admin/errors/unread-count` is called when Loki is not configured | Backend returns 503 by design when `LOKI_URL` is unset (`routes/admin_errors.py:_read`). `Layout.tsx:27` polls it every 30 s for admins, and react-query's default retry (3x) turns each failed poll into 4 requests: 64 requests in one 10-minute `soldier-detail` run, 473 across the c5 cold runs. `AdminSettingsPage.tsx:26` polls it too. | Confirmed by source |
| L2 | `GET /api/ranges/ineligible-soldiers/count` is the slowest shell call on every page | 1.0-1.3 s at c1, 3.6-5.4 s at c5 (cold p50). `count_ineligible_soldiers` (`services/ineligible_soldiers.py:317`) loads every in-scope `Soldier` entity (up to 20k) and does Python-side set work. `UnifiedNav.tsx` also invalidates and refetches it on every route change. | Confirmed by source; phase split not measured |
| L3 | Duplicate requests per page | Per cold page load (c1 medians): `level-types` x2-4, `duty-types` x2-3, `/api/me` x2, `notifications/unread-count` x2, `soldiers/roster` x2, `ranges` x2, `soldiers/ranks` x2. Home makes 45 requests. Some doubling is `React.StrictMode` in the dev server; the rest is missing shared query keys or a default `staleTime`. | Partly confirmed; production-build counts are not yet measured |
| L4 | Polling that does not need to run | `UnifiedNav` re-fetches `GET /api/algorithm/jobs?limit=50` on every route change and every 30 s; `NotificationBell`, `BugReportTrigger` and `BugReportModal` each poll every 30 s with no visibility gating; Layout polls bug-report counts too. | Confirmed by source |
| L5 | One 3.99 MB JS entry chunk (1.10 MB gzip), no route-level code splitting | `vite build` output; `App.tsx` has 0 `lazy()` calls and statically imports pages; `mermaid`, `react-pdf`, `recharts`, `@fullcalendar/*`, `katex`, `react-markdown` ship to every page. | Confirmed |
| L6 | Per-page slow calls at c5 | Home: `hierarchy-transfers/pending` 7.6 s, `soldiers/field-updates/pending/count` 7.5 s, `command-dashboard/alerts` 6.7 s (already ~1.6 s at c1). | Observed; cause unknown |
| L7 | Benchmark itself may mislead | Profiling ran on the Vite dev server (unbundled modules, `StrictMode` double effects) with plain `uvicorn` (no server/DB timing headers). FCP and request counts there are not production numbers. Even `GET /api/me` costs ~330 ms at c1 while unauthenticated `settings/public` costs ~14 ms; the source of that fixed per-request cost is not identified. | Confirmed gap |

## Design

Fix in measurement order. Nothing is claimed as a gain until a matched before/after run shows it.

1. **Fix the measurement first** (L7). Profile a production build (`vite build` + `vite preview`) against `profile_scale_server` so each response carries SQL and ASGI timing. Record a "before" baseline on this setup. The existing dev-server v2 captures stay as history, not as the baseline.
2. **Do not look for Loki when it is not configured** (L1). The backend exposes whether the error-log source is configured through the already-fetched authenticated public settings (`errors.log_source_configured`). The frontend does not call, poll, or retry the errors endpoints when it is false. The backend 503 stays, so a misconfigured deployment is never shown as "no errors". 503 and 4xx responses are not retried.
3. **Make shell reads cheap and non-repeating** (L3, L4). A default `staleTime` for the app `QueryClient`; shared query hooks for `level-types`, `duty-types`, `ranks`, `me`; notification, algorithm-badge and bug-report polling moved onto react-query with `refetchIntervalInBackground: false` (no polling in hidden tabs); stop invalidating the ineligible count on every route change.
4. **Make the ineligible count cheap on the server** (L2). Measure phases with `profile_scale_server`, then pick the smallest change that reaches the target (column projection, SQL aggregation, or a short per-scope cache); parity-tested against the current result.
5. **Code-split by route** (L5). `React.lazy` for every page, `Suspense` fallback, and `manualChunks` for the heavy libraries so they load only on the pages that use them.
6. **Per-page cleanup** (L6, L3). Per page, remove remaining duplicate calls, then investigate the three slow Home calls with the new server timing and fix what the phase data supports.
7. **Measure the change** on the same setup as the baseline: c1 and c5, five runs, cold and warm, all scenarios.

## Success criteria (checked in the final task; reported either way)

| Metric | Baseline | Target |
|---|---|---|
| `GET /api/admin/errors/unread-count` requests when Loki unset | 134 (c1, 70 page loads), 836 (c5, 350 page loads) | 0 |
| Entry JS chunk (raw) | 3.99 MB | <= 1.6 MB, heavy libs in separate lazy chunks |
| Requests per cold page load, each page | home 39, calendar team 23, calendar org 18-19, hierarchy 16-17, hr-sync 20, soldier detail 20-21, transparency 10 (c1/c5 medians) | no endpoint requested more than once per page load, except where the page genuinely refetches |
| `ineligible-soldiers/count` c5 cold p50 | 4.14 s (production build, measured in Task 1; c1 1.23 s) | <= 1.0 s |
| FCP c5 cold p50, every navigation page | 1.52-1.59 s (production build, measured in Task 1; c1 1.22-1.30 s) | <= 2.0 s |
| Page-ready p95 (every page, c1 and c5) | measured in Task 1: c1 cold 2.3-6.6 s, c5 cold 7.8-14.3 s by page (see `docs/benchmarks/2026-10-08-shell-load.md`) | not worse than baseline; reported per page |

Targets are goals, not promises. If a target is missed, the result is reported as missed with the measured value.

## Non-goals

- Production capacity claims. These are local, single-machine runs.
- Changing the transparency read model or its API.
- Removing the 503 from the backend errors endpoints.
- Server-side rendering or a CDN.

## Risks

- Route-level lazy loading can change test setup (`React.lazy` needs `Suspense`) and the first navigation to each page now loads a chunk. Measured, not assumed.
- Changing `QueryClient` defaults is global. The default `staleTime` is chosen small (30 s) and mutations that need fresh data must already invalidate their keys; Task 3 audits `invalidateQueries` call sites before relying on it.
- A cache on the ineligible count must not serve stale eligibility after a range qualification changes; the plan prefers a pure query optimization and only uses a cache if the measurement requires it.
