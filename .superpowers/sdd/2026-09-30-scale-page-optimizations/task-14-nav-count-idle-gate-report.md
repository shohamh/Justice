# Task 7 follow-up: navigation count idle gate

## Scope and ruling

Started at `8ea9e3ec693c0b691645c10384eab885fd46c961` on `feature/scale-20k-profiling`. Read the Task 7 plan and the task-14 brief. `CONTEXT.md` and the two current ADRs concern bug reports and range assignments; neither adds a navigation timing constraint.

Ruling: React Query's `useIsFetching()` count is the route-settle signal for the shared query client. The count includes any unrelated active query, so a separate deadline opens the gate 1,200 ms after each navigation request key change. The gate remains open once released for that key, including when navigation queries start fetching.

## Implementation

- `UnifiedNav` now starts its counter reads after React Query reports zero active queries for 400 continuous ms. The quiet timer resets when the active-query count changes and checks `queryClient.isFetching()` again at expiry to avoid releasing on a stale notification.
- A separate 1,200 ms timer from the pathname/scope/relevant-settings request key opens the gate if a query stays active. Both timers are cleaned up when that key changes or the gate opens. The current-key comparison keeps reads disabled immediately on a key change.
- `/nav/counts`, the shared admin ineligible-count hook, the planning ineligible-count query, and the algorithm badge fetch all retain their existing enable conditions, query keys, data handling, retry behavior, and algorithm 30-second polling. Initial navigation rendering remains immediate; badge counts start at their existing zero defaults.
- The existing seen-job test fixture now uses its stable `mockSeedSeenIds` callback. Its previous fresh `vi.fn()` on each render made the badge effect rerun after each fetch and stalled the full-file test run. This is a test-harness correction; the new gate did not create the callback loop.

## Timing and verification evidence

The three new tests use a real pending React Query request in the same `QueryClient` as `UnifiedNav`, with fake time for exact gate boundaries. They cover a request still active at 500 ms, release at 500 ms followed by 399/400 ms of quiet, and a request still active at 1,199/1,200 ms. They assert that all three navigation read paths (`getNavCounts`, `getIneligibleSoldierCount`, `listJobs`) remain disabled or start at the specified boundary. The initial nav tab renders while the route query is pending.

RED: `npx vitest run src/components/UnifiedNav.test.tsx -t "UnifiedNav route query idle gate"` failed 3/3 against the original fixed 400 ms timer. After correcting an initial test selector error and settling pending fixture promises during cleanup, the expected failure in each case was `/nav/counts` being called while the route query remained active or before the required quiet interval.

GREEN: the same command passed 3/3 (38 other tests skipped). An initial full-file run was stopped after the verbose output showed the cancelled-job case passed and progress stopped at the following seen-job case. After stabilizing that fixture callback, these fresh checks completed:

| Check | Result |
| --- | --- |
| `npx vitest run src/components/UnifiedNav.test.tsx -t "excludes cancelled jobs from the badge count"` | 1 passed |
| `npx vitest run src/components/UnifiedNav.test.tsx -t "excludes a seen done job from the badge count"` | 1 passed |
| `npx vitest run src/components/UnifiedNav.test.tsx` | 41 passed, no React act warnings |
| `npx eslint src/components/UnifiedNav.tsx src/components/UnifiedNav.test.tsx --max-warnings 0` | Exit 0 |
| `git diff --check` | Exit 0 |

These are unit-level timing and component regression checks. They do not measure page-ready or endpoint latency. No database, browser, account, external provider, merge, or push operation was performed. The 2026-10-02 browser page-ready profile remains the latest matched page comparison.
