# Shell and Page-Load Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every page's first paint and readiness faster by removing wasted shell work (Loki polling, duplicate and background requests), making the ineligible-soldier count cheap, and splitting the single 4 MB JS bundle by route, and prove each change with a matched before/after browser measurement.

**Architecture:** Measure first on a production build served against a timing-instrumented backend, then change one lead at a time (Loki gating, query hygiene, server count, code splitting, per-page cleanup), and re-run the identical c1/c5 matrix at the end. Each task ships behind its own tests; the final task reports every success criterion as met or missed with the measured value.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React 18 + Vite + @tanstack/react-query + Vitest (frontend), Playwright profiler (`frontend/scripts/profile-scale-pages.mjs`), `backend/app/scripts/profile_scale_server.py`.

**Spec:** [`docs/superpowers/specs/2026-10-08-shell-and-page-load-design.md`](../specs/2026-10-08-shell-and-page-load-design.md)

## Global Constraints

- Branch: new branch `feature/shell-load-optimization` stacked on `feature/transparency-bounded-continuation` (FCP instrumentation, `e72b8cdf`, exists only there). Small per-task commits. Do not commit to `dev` or `master`; finish with the `merge-worktree-to-dev` skill, which also adds the `docs/CHANGELOG-dev.md` entry.
- Hebrew UI, English code. New user-visible strings go in `frontend/src/i18n/he.json`; `he.json` has silent duplicate keys, so `grep` the key before adding it.
- Keep the backend 503 on `/api/admin/errors*` when Loki is unconfigured. The fix is that the frontend does not ask, not that the backend lies.
- Never print or commit database URLs or passwords. The scale database is `justice_scale_fcp_scale` in container `justice-scale-20k` (host port 55432, trust auth). Admin login is `1000001`; its password is the demo password in `backend/app/scripts/seed.py` (read it from there, do not paste it into files or logs).
- Do not touch the regular dev services on ports 8000 and 5173. Profiler ports: backend 8100, frontend 5174. Stop only processes you started.
- Gains are claimed only from a matched before/after run on the Task 1 setup. Dev-server numbers (the 2026-10-08 v2 captures) are history, not the baseline.
- Frontend checks before each frontend commit: `npm test -- <file>`, `npm run lint` (zero warnings), `npm run typecheck`. Backend: `pytest <file> -n0 -o addopts=""` for focused runs, `ruff check` on touched files.
- Use `git -C` / absolute paths; run commands from the worktree root `C:\Users\Shoham\workspace\Justice\.worktrees\scale-20k-profiling` (or the new worktree if one is created).

## File Structure

| File | Responsibility |
|---|---|
| `frontend/scripts/summarize-scale-pages.mjs` (new) | Print per-page p50/p95 page-ready, FCP, request count and top endpoints from a profiler artifact; optional before/after comparison. |
| `backend/app/routes/public_settings.py` | Add derived key `errors.log_source_configured`. |
| `frontend/src/hooks/useErrorLogSource.ts` (new) | `useErrorLogSourceConfigured(): boolean \| null`. |
| `frontend/src/api/queryRetry.ts` (new) | `shouldRetryQuery` retry policy (no retry on 4xx/5xx except 502/504). |
| `frontend/src/main.tsx` | App `QueryClient` defaults (`staleTime`, `retry`). |
| `frontend/src/components/Layout.tsx`, `pages/admin/AdminSettingsPage.tsx`, `pages/admin/ErrorsContent.tsx` | Stop calling errors endpoints when Loki is not configured. |
| `frontend/src/components/UnifiedNav.tsx`, `NotificationBell.tsx`, `BugReportTrigger.tsx`, `BugReportModal.tsx` | Polling hygiene and shared queries. |
| `backend/app/services/ineligible_soldiers.py` | Cheaper `count_ineligible_soldiers` (path chosen from measured phases). |
| `frontend/src/App.tsx`, `frontend/vite.config.ts` | `React.lazy` routes, `manualChunks`. |
| `docs/benchmarks/data/shell-load-{before,after}-*.json`, `docs/benchmarks/2026-10-08-shell-load.md` | Evidence and write-up. |

---

### Task 1: Production-build baseline with server timing

**Files:**
- Create: `frontend/scripts/summarize-scale-pages.mjs`
- Create: `docs/benchmarks/data/shell-load-before-c1-20261008.json`, `docs/benchmarks/data/shell-load-before-c5-20261008.json` (profiler output)
- Create: `docs/benchmarks/2026-10-08-shell-load.md` (baseline section)

**Interfaces:**
- Produces: `node frontend/scripts/summarize-scale-pages.mjs <artifact.json> [<before.json>]` prints one line per scenario/mode: `scenario mode ready pageReady p50/p95 FCP p50/p95 requests`, then the top 5 endpoints by median total time and count; with a second argument it prints deltas. Later tasks use it to read results.

- [ ] **Step 1: Write the summarizer**

```js
#!/usr/bin/env node
import { readFileSync } from "node:fs";

const [, , afterPath, beforePath] = process.argv;
if (!afterPath) {
  console.error("Usage: summarize-scale-pages.mjs <artifact.json> [<baseline.json>]");
  process.exit(2);
}

const median = (values) => {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
};
const round = (value) => (value === null ? "-" : Math.round(value));

function load(path) {
  const artifact = JSON.parse(readFileSync(path, "utf8"));
  const rows = new Map();
  for (const m of artifact.measurements) {
    if (m.readiness !== "ready") continue;
    const key = `${m.scenario} ${m.mode}`;
    const row = rows.get(key) ?? { ready: [], fcp: [], requests: [], endpoints: new Map() };
    row.ready.push(m.pageReadyMs);
    if (m.firstContentfulPaintMs != null) row.fcp.push(m.firstContentfulPaintMs);
    row.requests.push(m.apiRequestCount ?? m.apiResponses.length);
    const perRun = new Map();
    for (const a of m.apiResponses) {
      const e = perRun.get(a.endpoint) ?? { n: 0, ms: 0 };
      e.n += 1;
      e.ms += a.durationMs;
      perRun.set(a.endpoint, e);
    }
    for (const [endpoint, e] of perRun) {
      const agg = row.endpoints.get(endpoint) ?? { n: [], ms: [] };
      agg.n.push(e.n);
      agg.ms.push(e.ms);
      row.endpoints.set(endpoint, agg);
    }
    rows.set(key, row);
  }
  return { artifact, rows };
}

const after = load(afterPath);
const before = beforePath ? load(beforePath) : null;
console.log(`# ${afterPath} (concurrency ${after.artifact.concurrency})`);
for (const [key, row] of [...after.rows].sort()) {
  const p = (values, q) => {
    const sorted = [...values].sort((a, b) => a - b);
    return sorted.length ? sorted[Math.min(sorted.length - 1, Math.ceil(q * sorted.length) - 1)] : null;
  };
  const base = before?.rows.get(key);
  const delta = base ? ` (baseline ready p50 ${round(median(base.ready))}, FCP p50 ${round(median(base.fcp))}, req ${round(median(base.requests))})` : "";
  console.log(
    `${key.padEnd(46)} ready p50/p95 ${round(median(row.ready))}/${round(p(row.ready, 0.95))}  FCP p50/p95 ${round(median(row.fcp))}/${round(p(row.fcp, 0.95))}  req ${round(median(row.requests))}${delta}`,
  );
  const top = [...row.endpoints]
    .map(([endpoint, agg]) => ({ endpoint, ms: median(agg.ms), n: median(agg.n) }))
    .sort((a, b) => b.ms - a.ms)
    .slice(0, 5);
  for (const t of top) console.log(`    ${String(round(t.ms)).padStart(7)} ms  x${t.n}  ${t.endpoint}`);
}
```

- [ ] **Step 2: Verify it on an existing artifact**

Run: `node frontend/scripts/summarize-scale-pages.mjs docs/benchmarks/data/transparency-keyset-browser-c1-fcp-recapture-v2-20261008.json`
Expected: 14 scenario/mode lines (cold and warm for 7 scenarios), each followed by 5 endpoint lines; `home-dashboard cold` shows ~45 requests.

- [ ] **Step 3: Commit the summarizer**

```bash
git add frontend/scripts/summarize-scale-pages.mjs
git commit -m "perf(profile): add scale-page artifact summarizer"
```

- [ ] **Step 4: Start the timing backend on 8100 against the scale database**

Run from `backend` (PowerShell), with the env set exactly as below (no secrets: the container uses trust auth):

```powershell
$u = "postgresql+psycopg://scale@127.0.0.1:55432/justice_scale_fcp_scale"
$env:DATABASE_URL = $u; $env:DB_ADMIN_URL = $u
$env:REDIS_URL = "redis://127.0.0.1:6379/0"; $env:TRANSPARENCY_READ_MODEL_ENABLED = "true"
Remove-Item Env:LOKI_URL -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m app.scripts.profile_scale_server --port 8100
```

Run in the background. Expected: `GET http://127.0.0.1:8100/api/health` returns 200 after ~20 s. Confirm `docker exec justice-scale-20k psql -U scale -d justice_scale_fcp_scale -Atc "select count(*) from soldiers"` prints 20120 first (if the container or database is missing, stop and report; do not reseed without asking).

- [ ] **Step 5: Build the frontend and serve the production build on 5174**

```powershell
cd frontend
npx vite build --outDir $env:TEMP\justice-fe-before
$env:VITE_BACKEND_URL = "http://127.0.0.1:8100"
npx vite preview --host 127.0.0.1 --port 5174 --strictPort --outDir $env:TEMP\justice-fe-before
```

Run `preview` in the background. Record the entry chunk size printed by the build (expected `index-*.js ~3,989 kB`). Expected: `http://localhost:5174/login` returns 200 and `GET /api/settings/public` through the preview proxy reaches port 8100.

- [ ] **Step 6: Warm up, then capture the baseline**

Warm-up (output discarded, delete the scratch file after): one run of every scenario with `JUSTICE_SCALE_RUNS=1`, `JUSTICE_SCALE_OUTPUT=docs/benchmarks/data/_warmup-scratch.json`. Then the real captures (admin password read from `seed.py`, set in the process environment only):

```powershell
$env:JUSTICE_SCALE_BASE_URL = "http://localhost:5174"
$env:JUSTICE_SCALE_ADMIN_USERNAME = "1000001"
$env:JUSTICE_SCALE_RUNS = "5"
$env:JUSTICE_SCALE_OUTPUT = "docs/benchmarks/data/shell-load-before-c1-20261008.json"
node scripts/profile-scale-pages.mjs --concurrency 1
$env:JUSTICE_SCALE_OUTPUT = "docs/benchmarks/data/shell-load-before-c5-20261008.json"
node scripts/profile-scale-pages.mjs --concurrency 5
```

Expected: both exit 0; every scenario/mode reaches ready (c1 = 70 measurements, c5 = 350). If any scenario fails, diagnose before continuing (the roster `role_order` fix `9e5f7a11` must be on the branch).

- [ ] **Step 7: Write the baseline section and fix the targets**

Run the summarizer on both artifacts. In `docs/benchmarks/2026-10-08-shell-load.md`, record: the setup (production build, `profile_scale_server`, DB, dataset counts, entry chunk size, git SHA), the per-page table (ready p50/p95, FCP p50/p95, requests per page), the top endpoints per page, and the server-vs-wall time for `/api/me`, `nav/counts`, `notifications/unread-count`, `ineligible-soldiers/count` from the `serverTiming` fields. Replace the "re-baselined in Task 1" cells in the spec's success table with these measured values and keep the spec's target column.

- [ ] **Step 8: Stop only the processes started in steps 4-5, then commit**

```bash
git add docs/benchmarks/data/shell-load-before-c1-20261008.json docs/benchmarks/data/shell-load-before-c5-20261008.json docs/benchmarks/2026-10-08-shell-load.md docs/superpowers/specs/2026-10-08-shell-and-page-load-design.md
git commit -m "docs(perf): record production-build shell-load baseline"
```

---

### Task 2: Do not look for Loki when it is not configured

**Files:**
- Modify: `backend/app/routes/public_settings.py:28-33`
- Test: `backend/tests/integration/test_public_settings.py`
- Create: `frontend/src/hooks/useErrorLogSource.ts`
- Modify: `frontend/src/components/Layout.tsx:27`, `frontend/src/pages/admin/AdminSettingsPage.tsx:26`, `frontend/src/pages/admin/ErrorsContent.tsx`
- Test: `frontend/src/components/Layout.test.tsx`, `frontend/src/pages/admin/AdminSettingsPage.test.tsx`

**Interfaces:**
- Produces: public-settings key `"errors.log_source_configured": boolean` (always present, derived from `settings.loki_url`); `useErrorLogSourceConfigured(): boolean | null` (`null` while public settings are loading).

- [ ] **Step 1: Write the failing backend tests**

Append to `backend/tests/integration/test_public_settings.py`:

```python
import pytest

from app.settings import get_settings


@pytest.fixture
def loki_env(monkeypatch):
    def _set(value: str | None):
        if value is None:
            monkeypatch.delenv("LOKI_URL", raising=False)
        else:
            monkeypatch.setenv("LOKI_URL", value)
        get_settings.cache_clear()

    yield _set
    monkeypatch.delenv("LOKI_URL", raising=False)
    get_settings.cache_clear()


def test_error_log_source_flag_is_false_when_loki_is_unset(client, admin_session, loki_env):
    loki_env(None)
    soldier = create_soldier(admin_session, personal_number="PUBSET2")

    resp = client.get("/api/settings/public", headers=auth_headers(soldier))

    assert resp.status_code == 200
    assert resp.json()["settings"]["errors.log_source_configured"] is False


def test_error_log_source_flag_is_true_when_loki_is_set(client, admin_session, loki_env):
    loki_env("http://loki.test:3100")
    soldier = create_soldier(admin_session, personal_number="PUBSET3")

    resp = client.get("/api/settings/public", headers=auth_headers(soldier))

    assert resp.json()["settings"]["errors.log_source_configured"] is True
```

- [ ] **Step 2: Run to confirm failure**

Run (from `backend`): `.venv\Scripts\python.exe -m pytest tests/integration/test_public_settings.py -n0 -o addopts="" -k error_log_source`
Expected: 2 FAIL with `KeyError: 'errors.log_source_configured'`.

- [ ] **Step 3: Implement the flag**

In `public_settings.py` add the import `from app.settings import get_settings` and change the handler:

```python
ERROR_LOG_SOURCE_KEY = "errors.log_source_configured"


@router.get("", response_model=PublicSettingsOut)
def get_public_settings(
    session: Session = Depends(get_session),
    user: Soldier = Depends(require_password_changed),
) -> PublicSettingsOut:
    rows = session.execute(select(SystemSetting)).scalars().all()
    settings = {r.key: r.value for r in rows if r.key in _PUBLIC_KEYS}
    # Derived from deployment config, not stored: lets the UI skip admin error-log
    # calls (which answer 503 by design) when no log source is configured.
    settings[ERROR_LOG_SOURCE_KEY] = bool(get_settings().loki_url.strip())
    return PublicSettingsOut(settings=settings)
```

- [ ] **Step 4: Run backend tests, ruff, commit**

Run: `.venv\Scripts\python.exe -m pytest tests/integration/test_public_settings.py tests/integration/test_admin_errors_routes.py -n0 -o addopts=""` then `.venv\Scripts\python.exe -m ruff check app/routes/public_settings.py tests/integration/test_public_settings.py`
Expected: all pass; ruff clean.

```bash
git add backend/app/routes/public_settings.py backend/tests/integration/test_public_settings.py
git commit -m "feat(settings): expose whether an error log source is configured"
```

- [ ] **Step 5: Write the failing frontend tests**

Read `Layout.test.tsx` and `AdminSettingsPage.test.tsx` first and follow their existing mocking style for `usePublicSettings` and `../api/bugReports`. Add to each, as an admin user:

```tsx
it("does not request the error-log unread count when no log source is configured", async () => {
  mockPublicSettings({ "errors.log_source_configured": false });
  renderAsAdmin();
  await screen.findByTestId(/* the component's root test id */);
  expect(getAdminErrorUnreadCount).not.toHaveBeenCalled();
  expect(getAdminBugReportUnreadCount).toHaveBeenCalled(); // other admin polling unaffected
});

it("requests the error-log unread count when a log source is configured", async () => {
  mockPublicSettings({ "errors.log_source_configured": true });
  renderAsAdmin();
  await waitFor(() => expect(getAdminErrorUnreadCount).toHaveBeenCalledTimes(1));
});

it("does not request it while public settings are still loading", () => {
  mockPublicSettings(null);
  renderAsAdmin();
  expect(getAdminErrorUnreadCount).not.toHaveBeenCalled();
});
```

(`mockPublicSettings` / `renderAsAdmin` stand for whatever helpers or `vi.mock` setup the file already uses; add a small local helper if none exists.) Run `npm test -- src/components/Layout.test.tsx src/pages/admin/AdminSettingsPage.test.tsx`; expected: the "not configured" and "loading" tests FAIL.

- [ ] **Step 6: Implement the hook and gate the calls**

`frontend/src/hooks/useErrorLogSource.ts`:

```ts
import { usePublicSettings } from "./usePublicSettings";

/** true/false once public settings have loaded; null while they are loading. */
export function useErrorLogSourceConfigured(): boolean | null {
  const settings = usePublicSettings();
  if (settings === null) return null;
  return settings["errors.log_source_configured"] === true;
}
```

`Layout.tsx` (replace line 27), after `publicSettings`/`isAdmin` are defined (move the `useErrorLogSourceConfigured()` call above the query):

```tsx
const errorLogConfigured = useErrorLogSourceConfigured();
const errorUnread = useQuery({
  queryKey: ["admin-errors-unread"],
  queryFn: getAdminErrorUnreadCount,
  enabled: isAdmin && errorLogConfigured === true,
  refetchInterval: 30000,
  refetchIntervalInBackground: false,
  retry: false,
});
```

`AdminSettingsPage.tsx` line 26: `enabled: activeTab >= 0 && errorLogConfigured === true`, `retry: false`, same hook. `ErrorsContent.tsx`: when `useErrorLogSourceConfigured() === false`, render a short notice (new key `admin_errors.not_configured`, Hebrew text "מקור יומני השגיאות אינו מוגדר בשרת זה" — grep `he.json` for the key first) instead of calling `listAdminErrors`; give its `useQuery` `enabled: configured !== false`.

- [ ] **Step 7: Run frontend checks, commit**

Run: `npm test -- src/components/Layout.test.tsx src/pages/admin/AdminSettingsPage.test.tsx src/pages/admin/ErrorsContent.test.tsx`, `npm run lint`, `npm run typecheck`
Expected: pass; lint zero warnings; typecheck no new errors (the branch has 17 pre-existing diagnostics; compare the count before and after).

```bash
git add frontend/src backend
git commit -m "perf(frontend): skip error-log calls when no log source is configured"
```

---

### Task 3: Query hygiene — retries, stale time, background polling, route-change refetches

**Files:**
- Create: `frontend/src/api/queryRetry.ts`, `frontend/src/api/queryRetry.test.ts`
- Modify: `frontend/src/main.tsx:18`, `frontend/src/components/UnifiedNav.tsx` (queries around lines 86-160), `frontend/src/components/NotificationBell.tsx:27-40`, `frontend/src/components/BugReportTrigger.tsx:126-131`, `frontend/src/components/BugReportModal.tsx:52-57`, `frontend/src/components/Layout.tsx` (bug count query)
- Test: `frontend/src/components/UnifiedNav.test.tsx`, `frontend/src/components/NotificationBell.test.tsx`

**Interfaces:**
- Produces: `shouldRetryQuery(failureCount: number, error: unknown): boolean`; `MAX_QUERY_RETRIES = 2`. Shared algorithm-jobs query key `queryKeys.algorithmJobs(50, 0)` (already used by `ShiftsPage`).

- [ ] **Step 1: Write the failing retry-policy tests** (`queryRetry.test.ts`)

```ts
import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";
import { shouldRetryQuery } from "./queryRetry";

const httpError = (status: number) =>
  new AxiosError("fail", String(status), undefined, undefined, {
    status, statusText: "", headers: {}, config: { headers: new AxiosHeaders() }, data: {},
  });

describe("shouldRetryQuery", () => {
  it("never retries client or server errors that will not change", () => {
    for (const status of [400, 401, 403, 404, 422, 500, 503]) {
      expect(shouldRetryQuery(0, httpError(status))).toBe(false);
    }
  });
  it("retries network errors and gateway errors, at most twice", () => {
    expect(shouldRetryQuery(0, new AxiosError("Network Error"))).toBe(true);
    expect(shouldRetryQuery(1, httpError(502))).toBe(true);
    expect(shouldRetryQuery(0, httpError(504))).toBe(true);
    expect(shouldRetryQuery(2, new AxiosError("Network Error"))).toBe(false);
  });
});
```

Run `npm test -- src/api/queryRetry.test.ts`; expected FAIL (module missing).

- [ ] **Step 2: Implement the policy and the app defaults**

`queryRetry.ts`:

```ts
import { isAxiosError } from "axios";

export const MAX_QUERY_RETRIES = 2;

/** Retry only failures that can plausibly succeed on a second try. */
export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_QUERY_RETRIES) return false;
  if (!isAxiosError(error)) return false;
  const status = error.response?.status;
  if (status === undefined) return true; // no response: network error
  return status === 502 || status === 504;
}
```

`main.tsx`:

```tsx
import { shouldRetryQuery } from "./api/queryRetry";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: shouldRetryQuery },
  },
});
```

Before relying on `staleTime`, run `grep -rn "invalidateQueries\|refetchQueries" frontend/src --include=*.tsx --include=*.ts | grep -v test` and confirm every mutation that changes data a page shows invalidates the matching key; list any page that depends on remount-refetch and add `staleTime: 0` to that query. Run `npm test` (whole suite) and fix only failures caused by the new defaults, noting each in the commit message.

- [ ] **Step 3: Stop refetching the ineligible count and nav counts on every route change** (`UnifiedNav.tsx`)

Delete the pathname effect that calls `queryClient.invalidateQueries({ queryKey: queryKeys.ineligibleSoldierCount() })` (and the now-unused `previousPathname` ref). Give the planning/admin count queries `staleTime: 60_000`. Remove `location.pathname` from the `queryKeys.navCounts(...)` key and `navRequestKey` only if the existing navigation-gate tests in `UnifiedNav.test.tsx` still pass; if the gate depends on it, keep the key and instead set `staleTime: 15_000` on the nav-counts query. Add a test: navigating between two routes within 15 s triggers `getNavCounts` and `getIneligibleSoldierCount` once, not once per route.

- [ ] **Step 4: Move the algorithm badge onto react-query** (`UnifiedNav.tsx`, effect at ~line 150)

Replace the `useEffect` + `setInterval` with:

```tsx
const algorithmJobsQuery = useQuery({
  queryKey: queryKeys.algorithmJobs(50, 0),
  queryFn: () => listJobs(50, 0),
  enabled: canPlan && navReadsEnabled,
  refetchInterval: 30_000,
  refetchIntervalInBackground: false,
  retry: false,
});

useEffect(() => {
  const items = Array.isArray(algorithmJobsQuery.data?.items) ? algorithmJobsQuery.data.items : [];
  if (!algorithmJobsQuery.data) return;
  setAlgorithmBadgeData({ scopeKey: navScopeKey, jobs: items });
  seedSeenIds(items);
}, [algorithmJobsQuery.data, navScopeKey, seedSeenIds]);
```

(`ShiftsPage` already uses this key, so the two share one request.) Add a test: with `canPlan`, one `listJobs` call on mount, none on route change within 30 s.

- [ ] **Step 5: Notification bell and bug-report polls: shared query, no background polling**

`NotificationBell.tsx`: replace the unread-count `useEffect`/`setInterval` with

```tsx
const unreadQuery = useQuery({
  queryKey: ["notifications", "unread-count"],
  queryFn: getUnreadCount,
  refetchInterval: 30_000,
  refetchIntervalInBackground: false,
  retry: false,
});
const unread = unreadQuery.data?.count ?? 0;
const unreadCountError = unreadQuery.isError;
```

keeping the existing "load the five newest when the dropdown is open" effect; after `handleMarkRead`, call `queryClient.setQueryData(["notifications","unread-count"], (old) => ({ count: Math.max(0, (old?.count ?? 0) - 1) }))` instead of `setUnread`. Add `refetchIntervalInBackground: false` to the polls in `BugReportTrigger.tsx`, `BugReportModal.tsx`, and the bug-report count in `Layout.tsx`. Update `NotificationBell.test.tsx` and add: one request on mount, none while `document.visibilityState === "hidden"` after 30 s with fake timers.

- [ ] **Step 6: Run checks, commit**

Run: `npm test`, `npm run lint`, `npm run typecheck`. Expected: whole suite passes except failures that already existed before this task (compare against `git stash`-free baseline: run the suite on the previous commit first and record the failing test names in the commit message).

```bash
git add frontend/src
git commit -m "perf(frontend): stop duplicate and background shell polling"
```

---

### Task 4: Make `GET /api/ranges/ineligible-soldiers/count` cheap

**Files:**
- Create: `backend/app/scripts/profile_ineligible_count.py` (phase timer, kept for repeatability)
- Modify: `backend/app/services/ineligible_soldiers.py:317-357`
- Test: `backend/tests/unit/test_ineligible_soldiers_count_parity.py` (new)

**Interfaces:**
- Consumes: existing `count_ineligible_soldiers(session, *, roots, as_of) -> int` and `list_ineligible_soldiers`; the count must always equal `len(list_ineligible_soldiers(...))`.
- Produces: same signature, same result, lower latency.

- [ ] **Step 1: Write the parity test first (guards every later change)**

```python
import datetime as dt

from app.services import ineligible_soldiers as svc


def test_count_matches_list_for_the_seeded_dataset(admin_session):
    # Uses the project's existing fixtures for soldiers, weapon duty types and ranges;
    # build at least: one soldier with no qualification, one qualified soldier with a
    # future weapon duty they are ineligible for, one fully eligible soldier.
    as_of = dt.date(2026, 10, 8)
    expected = len(svc.list_ineligible_soldiers(admin_session, roots=None, as_of=as_of))
    assert svc.count_ineligible_soldiers(admin_session, roots=None, as_of=as_of) == expected
    assert expected >= 2
```

Look at `backend/tests` for the existing ineligible-soldier fixtures (`grep -rn "ineligible" backend/tests -l`) and reuse their builders rather than creating new ones. Run it on the unchanged code; expected PASS (it records current behavior).

- [ ] **Step 2: Measure where the time goes**

Write `profile_ineligible_count.py`: build an engine from `JUSTICE_SCALE_DATABASE_URL`, and with `time.perf_counter` time each phase of `count_ineligible_soldiers` for `roots=None` and `as_of=date.today()`, five repetitions, printing median ms and row counts:

```python
statement = select(Soldier).join(HierarchyNode, Soldier.hierarchy_node_id == HierarchyNode.id)
soldiers = session.execute(statement).scalars().all()                       # phase 1: load entities
weapon_ids = svc._weapon_eligible_soldier_ids(session, soldiers=soldiers, as_of=as_of)  # phase 2: duty types x soldiers
eligible = [s for s in soldiers if s.id in weapon_ids]
quals = svc._valid_qualifications_by_soldier(session, soldiers=eligible, as_of=as_of)    # phase 3
qualified = {s.id for s in eligible if s.id in quals}
duties = svc._upcoming_weapon_duties_by_soldier(session, soldier_ids=qualified, as_of=as_of)  # phase 4
elig = project_duty_eligibility(session, soldier_ids=list(qualified),
        duty_ids=[d.assignment_id for ds in duties.values() for d in ds], as_of=as_of)          # phase 5
```

Run it against the scale DB (`python -m app.scripts.profile_ineligible_count`). Record the five phase medians in `docs/benchmarks/2026-10-08-shell-load.md` under "ineligible count phases".

- [ ] **Step 3: Choose the change from the numbers (decision gate)**

Pick the first row whose condition holds, implement only that, and re-run Step 2:

| Condition | Change |
|---|---|
| Phase 1 is >= 40% of total | Load only the columns the helpers use (`Soldier.id`, `last_mitvahim_date`, `last_alal_date`, and whatever `_is_eligible` reads) via `select(...)` instead of entities; keep helper signatures by passing lightweight row objects. |
| Phase 2 is >= 40% | Evaluate each duty type's structural requirements once per distinct soldier attribute combination (group soldiers by the fields `_is_eligible` reads) instead of once per soldier. |
| Phase 5 is >= 40% | Narrow `duty_ids`/`soldier_ids` before `project_duty_eligibility`, or batch it. |
| No phase dominates | Add a per-process cache keyed `(frozenset(roots), as_of)` with a 30 s TTL, invalidated by the existing range-qualification write paths (`grep -rn "SoldierRangeQualification(" backend/app`); state the staleness bound in the docstring. |

The code for the chosen row is written in this step against the measured numbers; if more than one row applies, do them one per commit, re-measuring after each.

- [ ] **Step 4: Verify parity and the speedup**

Run: `.venv\Scripts\python.exe -m pytest tests/unit/test_ineligible_soldiers_count_parity.py tests/integration -k ineligible -n0 -o addopts=""` and `python -m app.scripts.profile_ineligible_count`.
Expected: all pass; total median at least 3x lower than the Step 2 baseline (target: server time <= 250 ms at 20k Soldiers; if missed, report the measured figure and stop iterating after two attempts).

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "perf(ranges): speed up ineligible-soldier count"
```

---

### Task 5: Route-level code splitting

**Files:**
- Modify: `frontend/src/App.tsx` (static page imports at lines 11-22 and the other imports further down; `<Routes>` block), `frontend/vite.config.ts`
- Test: `frontend/src/App.test.tsx`; create `frontend/src/lazyRoutes.test.tsx`

**Interfaces:**
- Produces: every page component imported with `React.lazy(() => import("./pages/…"))` and rendered inside one `<Suspense fallback={<PageLoading />}>`; `PageLoading` is a minimal accessible spinner component in `frontend/src/components/PageLoading.tsx` with `data-testid="page-loading"`.

- [ ] **Step 1: Record the starting point**

Run `npx vite build --outDir $env:TEMP\justice-fe-split-before` and note the entry chunk size and chunk count. Expected: one `index-*.js` of about 3,989 kB.

- [ ] **Step 2: Write the failing test** (`lazyRoutes.test.tsx`)

```tsx
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const app = readFileSync(new URL("./App.tsx", import.meta.url), "utf8");

describe("App routes", () => {
  it("loads pages lazily instead of importing them statically", () => {
    const staticPageImports = app.match(/^import .* from "\.\/pages\/.*";$/gm) ?? [];
    expect(staticPageImports).toEqual([]);
    expect(app).toContain("lazy(() => import(");
    expect(app).toContain("<Suspense");
  });
});
```

Run `npm test -- src/lazyRoutes.test.tsx`; expected FAIL (static imports exist).

- [ ] **Step 3: Convert pages to lazy imports**

For every `import XPage from "./pages/XPage";` in `App.tsx`, replace with `const XPage = lazy(() => import("./pages/XPage"));` (import `lazy, Suspense` from `react`); for named exports use `.then((m) => ({ default: m.Name }))`. Keep the login and change-password pages eager so the unauthenticated first paint needs no extra chunk. Wrap the `<Routes>` content in `<Suspense fallback={<PageLoading />}>`. Create `PageLoading.tsx`:

```tsx
export default function PageLoading() {
  return (
    <div data-testid="page-loading" role="status" aria-live="polite" style={{ padding: "2rem", textAlign: "center" }}>
      …
    </div>
  );
}
```

(use the project's existing loading text key if one exists: `grep -n "loading" frontend/src/i18n/he.json`).

- [ ] **Step 4: Split heavy libraries into named chunks** (`vite.config.ts`)

Check what the installed Vite (`npx vite --version`) accepts for chunking; with Rolldown-based Vite use `build.rolldownOptions.output.codeSplitting` groups, otherwise `build.rollupOptions.output.manualChunks`. Groups: `mermaid`, `react-pdf`/`pdfjs-dist`, `recharts`, `@fullcalendar/*`, `katex`/`react-katex`, `react-markdown`/`remark*`/`rehype*`. Run `npx vite build` and confirm those libraries are not in the entry chunk: for each, `grep -c "<library marker string>" dist/assets/index-*.js` is 0 (use a distinctive string such as `mermaid` initialize or `FullCalendar`).

- [ ] **Step 5: Verify**

Run: `npm test -- src/lazyRoutes.test.tsx src/App.test.tsx` then the whole suite, `npm run lint`, `npm run typecheck`, and `npx vite build`.
Expected: tests pass; entry chunk <= 1.6 MB raw (target from the spec); build prints separate chunks for the six heavy groups. If the entry chunk is still above 1.6 MB, list the largest modules (`npx vite build --debug` or the reporter) in the commit message and split what the data supports; do not guess.

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "perf(frontend): lazy-load routes and split heavy libraries"
```

---

### Task 6: Per-page duplicate and slow-call cleanup

**Files:** determined per page from the Task 1 request-count table; each fix lives in that page's component or its shared query hook. Create shared hooks only where two or more components request the same data:
- Create: `frontend/src/hooks/useLevelTypes.ts`, `useDutyTypes.ts`, `useSoldierRanks.ts` (each a `useQuery` wrapper with a fixed key and `staleTime: 300_000`), plus a test per hook asserting that two simultaneous consumers produce one request.

**Interfaces:**
- Produces: `useLevelTypes()`, `useDutyTypes()`, `useSoldierRanks()` returning the `useQuery` result for `GET /api/hierarchy/level-types`, `/api/duty-config/duty-types`, `/api/soldiers/ranks`.

- [ ] **Step 1: Build the per-page checklist from the baseline**

For each of the seven scenarios (Home, Hierarchy/Team, Soldier detail, Calendar whole-org, Calendar synthetic team, Transparency, HR sync review) list from `shell-load-before-c1-*.json` (via the summarizer) every endpoint requested more than once per load. Put the list in `docs/benchmarks/2026-10-08-shell-load.md` under "per-page duplicates". After Tasks 2, 3, and 5, re-capture request counts on a production build (Task 7 step 2 procedure, `JUSTICE_SCALE_RUNS=1`, c1) and keep only the endpoints still duplicated.

- [ ] **Step 2: Fix each remaining duplicate, one page per commit**

For each remaining duplicate: find all call sites (`grep -rn "<apiFunction>" frontend/src --include=*.tsx`), switch them to one shared hook or one shared query key, and add a regression test that renders the page's components with a spy on the API function and asserts a single call. Known suspects to check first (from the dev-server capture, still unconfirmed on the production build): Home `level-types` x4 and `duty-types` x3; calendar `duty-types` x2 and `ranges` x2; Team `level-types` x2, `soldiers/roster` x2, `soldiers/ranks` x2; `/api/me` x2 on every page (check `AuthContext` for a duplicate bootstrap fetch). Anything that only doubles under `React.StrictMode` and is single on the production build is not a bug; record it and move on.

- [ ] **Step 3: Investigate the three slow Home calls with server timing**

Using the Task 1 setup (profile server + production build), read the `serverTiming` fields for `GET /api/command-dashboard/alerts`, `GET /api/hierarchy-transfers/pending`, and `GET /api/soldiers/field-updates/pending/count` at c1 and c5. If server+DB time is a small share of wall time, the delay is queuing behind the other requests of the same page; the fix is fewer concurrent requests (defer non-visible panels until idle using the existing `useDashboardIdleGate` hook). If server time dominates, run the endpoint's SQL through `EXPLAIN (ANALYZE, BUFFERS)` on the scale database (read-only), record the plan, and fix the specific cause found (missing index, per-row query, full-table load); each fix gets its own parity test and commit.

- [ ] **Step 4: Verify each page**

Run `npm test` and `npm run typecheck`. Expected: pass. Re-run the Step 1 request-count capture and confirm each page's duplicated-endpoint list is empty or justified in the write-up.

- [ ] **Step 5: Commit per page** (message form: `perf(<page>): remove duplicate <endpoint> requests`).

---

### Task 7: Matched after-measurement and write-up

**Files:**
- Create: `shell-load-after-c1-20261008.json`, `shell-load-after-c5-20261008.json` under `docs/benchmarks/data/` (raw capture removed from the working tree on 2026-10-10, still in git history at commit d94e064e)
- Modify: `docs/benchmarks/2026-10-08-shell-load.md`, `docs/superpowers/plans/2026-09-30-scale-page-optimizations.md` (add a short section linking the write-up), `docs/superpowers/specs/2026-10-08-shell-and-page-load-design.md` (fill the "result" column)

- [ ] **Step 1: Rebuild and restart exactly as Task 1 steps 4-5**

Same database, same dataset, same profile server, production build of the final code into `$env:TEMP\justice-fe-after`. Record the new entry chunk size. Run one warm-up pass of every scenario before measuring.

- [ ] **Step 2: Capture c1 and c5, five runs, all scenarios**

Same environment variables as Task 1 step 6, outputs `shell-load-after-c1-20261008.json` and `shell-load-after-c5-20261008.json`. Expected: both exit 0 with every scenario/mode ready. (raw captures removed from the working tree on 2026-10-10, still in git history at commit d94e064e.)

- [ ] **Step 3: Compare**

Run `node frontend/scripts/summarize-scale-pages.mjs <after-c5.json> docs/benchmarks/data/shell-load-before-c5-20261008.json` (and for c1). Also count `GET /api/admin/errors/unread-count` entries in the after artifacts (expected 0) and read the entry chunk sizes.

- [ ] **Step 4: Write the result**

In `2026-10-08-shell-load.md` add a table with one row per spec success criterion: baseline, target, measured, met/missed. Add per-page before/after tables (ready p50/p95, FCP p50/p95, requests per page). State plainly any metric that got worse or any target that was missed, with the measured value, and which task is the likely cause only if the data shows it. Keep the caveats: local single-machine run, production build served by `vite preview`, not a production-capacity result.

- [ ] **Step 5: Run the full verification and commit**

Run: backend focused tests for touched files, `npm test`, `npm run lint`, `npm run typecheck`, `git diff --check`. Report any pre-existing failures separately.

```bash
git add docs frontend backend
git commit -m "docs(perf): record shell-load after-measurement"
```

- [ ] **Step 6: Hand off for merge**

Use the `merge-worktree-to-dev` skill (it adds the `docs/CHANGELOG-dev.md` entry with a `Docs:` line pointing at this plan and the spec). Do not merge or push without the user's go-ahead.

---

## Self-Review

**Spec coverage:** L1 (Loki) → Task 2; L2 (ineligible count) → Task 4 and Task 3 step 3 (route-change refetch); L3 (duplicates) → Tasks 3 and 6; L4 (polling) → Task 3; L5 (bundle) → Task 5; L6 (slow Home calls) → Task 6 step 3; L7 (measurement) → Task 1 and Task 7. "All pages": Task 1 baseline covers all 7 scenarios, Task 6 handles per-page duplicates, Task 7 reports every page.

**Known gaps by design:** Task 4's final code and Task 6's per-page fixes are chosen from measurements taken inside those tasks (each has an explicit decision gate and parity/regression test), because the cause is not established until the production-build timing exists. Task 2 and 3 frontend tests say to follow each file's existing mocking style rather than pasting a guessed harness.

**Consistency:** `errors.log_source_configured` (Task 2) is the only new settings key; `useErrorLogSourceConfigured` is used in Layout, AdminSettingsPage and ErrorsContent; `queryKeys.algorithmJobs(50, 0)` matches the existing `ShiftsPage` key; output file names in Tasks 1 and 7 match the summarizer usage.
