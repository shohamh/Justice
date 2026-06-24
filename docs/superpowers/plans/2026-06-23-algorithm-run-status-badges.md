# Algorithm Run Status Badges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show 4 colored count badges (running=blue, draft=yellow, done=green, failed=red) next to the "ריצות אלגוריתם" heading in `ShiftsManagementPage`, derived from `listJobs(50)`, polling every 30s.

**Architecture:** Add a `useEffect` in `ShiftsManagementPage` that fetches `listJobs(50)` on mount, re-fetches right after a new job is submitted, and polls every 30s thereafter (mirrors the existing pattern in `UnifiedNav.tsx`). Counts are derived from the fetched `JobSummaryOut[]` by `status`/`mode` and rendered as small pill `<span>`s in the section's heading row, each shown only when its count is `> 0`.

**Tech Stack:** React hooks (`useState`, `useEffect`), existing `listJobs` API function from `frontend/src/api/algorithm.ts`, Tailwind utility classes, Vitest + React Testing Library.

**Spec:** `docs/superpowers/specs/2026-06-23-algorithm-run-status-badges-design.md`

---

### Task 1: Add badge counts state, fetch effect, and render badges

**Files:**
- Modify: `frontend/src/pages/planning/ShiftsManagementPage.tsx`
- Test: `frontend/src/pages/planning/ShiftsManagementPage.test.tsx` (new)

- [ ] **Step 1: Write the failing test file**

Create `frontend/src/pages/planning/ShiftsManagementPage.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import ShiftsManagementPage from "./ShiftsManagementPage";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("../../components/Layout", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("../ShiftsPage", () => ({
  ShiftsContent: () => <div data-testid="shifts-content" />,
}));

vi.mock("../ShiftTemplatesPage", () => ({
  ShiftTemplatesContent: () => <div data-testid="templates-content" />,
}));

vi.mock("../AlgorithmPage", () => ({
  AlgorithmContent: () => <div data-testid="algorithm-content" />,
}));

const mockListJobs = vi.fn();
vi.mock("../../api/algorithm", () => ({
  listJobs: (...args: unknown[]) => mockListJobs(...args),
}));

function job(status: string, mode: string) {
  return { status, mode };
}

describe("ShiftsManagementPage — algorithm run badges", () => {
  beforeEach(() => {
    mockListJobs.mockReset();
  });

  test("renders no badges when there are no jobs", async () => {
    mockListJobs.mockResolvedValue({ items: [], total: 0 });
    render(<ShiftsManagementPage />);
    await waitFor(() => expect(mockListJobs).toHaveBeenCalled());
    expect(screen.queryByTestId("algo-badge-running")).not.toBeInTheDocument();
    expect(screen.queryByTestId("algo-badge-draft")).not.toBeInTheDocument();
    expect(screen.queryByTestId("algo-badge-done")).not.toBeInTheDocument();
    expect(screen.queryByTestId("algo-badge-failed")).not.toBeInTheDocument();
  });

  test("groups jobs into running/draft/done/failed by status and mode", async () => {
    mockListJobs.mockResolvedValue({
      items: [
        job("pending", "shadow"),
        job("running", "dm_reviewed"),
        job("done", "shadow"),
        job("done", "shadow"),
        job("done", "dm_reviewed"),
        job("failed", "shadow"),
      ],
      total: 6,
    });
    render(<ShiftsManagementPage />);

    expect(await screen.findByTestId("algo-badge-running")).toHaveTextContent("2");
    expect(await screen.findByTestId("algo-badge-draft")).toHaveTextContent("2");
    expect(await screen.findByTestId("algo-badge-done")).toHaveTextContent("1");
    expect(await screen.findByTestId("algo-badge-failed")).toHaveTextContent("1");
  });

  test("omits a badge when its group count is zero", async () => {
    mockListJobs.mockResolvedValue({
      items: [job("pending", "shadow")],
      total: 1,
    });
    render(<ShiftsManagementPage />);

    expect(await screen.findByTestId("algo-badge-running")).toHaveTextContent("1");
    expect(screen.queryByTestId("algo-badge-draft")).not.toBeInTheDocument();
    expect(screen.queryByTestId("algo-badge-done")).not.toBeInTheDocument();
    expect(screen.queryByTestId("algo-badge-failed")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/planning/ShiftsManagementPage.test.tsx`

Expected: FAIL — `ShiftsManagementPage.test.tsx` either errors because `../../api/algorithm` has no current usage to mock against meaningfully, or (more likely) the test runs but badges are never rendered, so `findByTestId("algo-badge-running")` etc. time out / `queryByTestId` assertions pass trivially while the "groups jobs" test fails because none of the `algo-badge-*` testids exist yet.

- [ ] **Step 3: Implement the badge counts and rendering**

Replace the full contents of `frontend/src/pages/planning/ShiftsManagementPage.tsx` with:

```tsx
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import { ShiftsContent } from "../ShiftsPage";
import { ShiftTemplatesContent } from "../ShiftTemplatesPage";
import { AlgorithmContent } from "../AlgorithmPage";
import { listJobs } from "../../api/algorithm";

interface RunBadgeCounts {
  running: number;
  draft: number;
  done: number;
  failed: number;
}

const EMPTY_COUNTS: RunBadgeCounts = { running: 0, draft: 0, done: 0, failed: 0 };

export default function ShiftsManagementPage() {
  const { t } = useTranslation();
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [runsOpen, setRunsOpen] = useState(false);
  const [latestJobId, setLatestJobId] = useState<string | null>(null);
  const [runBadgeCounts, setRunBadgeCounts] = useState<RunBadgeCounts>(EMPTY_COUNTS);
  const runsRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    async function fetchRunBadgeCounts() {
      try {
        const result = await listJobs(50);
        const counts = result.items.reduce(
          (acc, job) => {
            if (job.status === "pending" || job.status === "running") {
              acc.running += 1;
            } else if (job.status === "done" && job.mode === "shadow") {
              acc.draft += 1;
            } else if (job.status === "done" && job.mode === "dm_reviewed") {
              acc.done += 1;
            } else if (job.status === "failed") {
              acc.failed += 1;
            }
            return acc;
          },
          { running: 0, draft: 0, done: 0, failed: 0 }
        );
        setRunBadgeCounts(counts);
      } catch {
        // ignore — leave last known counts in place
      }
    }

    void fetchRunBadgeCounts();
    const interval = setInterval(() => void fetchRunBadgeCounts(), 30_000);
    return () => clearInterval(interval);
  }, [latestJobId]);

  function handleJobSubmitted(jobId: string) {
    setLatestJobId(jobId);
    setRunsOpen(true);
    setTimeout(() => runsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
  }

  return (
    <Layout>
      <div className="space-y-6">
        {/* Templates collapsible */}
        <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4" dir="rtl">
          <button
            type="button"
            onClick={() => setTemplatesOpen(o => !o)}
            className="flex w-full justify-between items-center gap-2 text-right"
          >
            <h2 className="text-xl font-semibold">{t("nav.planning_templates")}</h2>
            <span className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-sm px-2 py-1">
              {templatesOpen ? "▲" : "▼"}
            </span>
          </button>
          {templatesOpen && <ShiftTemplatesContent />}
        </section>

        {/* Algorithm runs collapsible */}
        <section
          ref={runsRef}
          className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-4"
          dir="rtl"
        >
          <button
            type="button"
            onClick={() => setRunsOpen(o => !o)}
            className="flex w-full justify-between items-center gap-2 text-right"
          >
            <h2 className="text-xl font-semibold">ריצות אלגוריתם</h2>
            <div className="flex items-center gap-2">
              {runBadgeCounts.running > 0 && (
                <span
                  data-testid="algo-badge-running"
                  className="px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200"
                >
                  {runBadgeCounts.running}
                </span>
              )}
              {runBadgeCounts.draft > 0 && (
                <span
                  data-testid="algo-badge-draft"
                  className="px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200"
                >
                  {runBadgeCounts.draft}
                </span>
              )}
              {runBadgeCounts.done > 0 && (
                <span
                  data-testid="algo-badge-done"
                  className="px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
                >
                  {runBadgeCounts.done}
                </span>
              )}
              {runBadgeCounts.failed > 0 && (
                <span
                  data-testid="algo-badge-failed"
                  className="px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
                >
                  {runBadgeCounts.failed}
                </span>
              )}
              <span className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-sm px-2 py-1">
                {runsOpen ? "▲" : "▼"}
              </span>
            </div>
          </button>
          {runsOpen && (
            <div className="h-[600px]">
              <AlgorithmContent initialJobId={latestJobId} />
            </div>
          )}
        </section>

        {/* Shifts table */}
        <ShiftsContent onJobSubmitted={handleJobSubmitted} />
      </div>
    </Layout>
  );
}
```

Note: `latestJobId` is included in the effect's dependency array so that submitting a new job (which sets `latestJobId`) triggers an immediate re-fetch instead of waiting up to 30s for the next poll tick.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/planning/ShiftsManagementPage.test.tsx`

Expected: PASS — all 3 tests green.

- [ ] **Step 5: Run the full frontend test suite and linter**

Run:
```bash
cd frontend && npm test && npm run lint
```

Expected: all existing tests still pass, zero lint warnings/errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/planning/ShiftsManagementPage.tsx frontend/src/pages/planning/ShiftsManagementPage.test.tsx
git commit -m "feat: add colored status badges to algorithm runs section header"
```
