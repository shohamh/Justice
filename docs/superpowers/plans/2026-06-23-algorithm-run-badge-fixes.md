# Algorithm Run Badge Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop cancelled algorithm runs from inflating the "failed" badge count, and make the nav badge (tab + sheet item) change color based on the worst status it represents instead of always being red.

**Architecture:** Extract the job-grouping logic that already exists inline in `ShiftsManagementPage.tsx` into a shared `frontend/src/utils/algorithmRunBadges.ts` util that also excludes cancelled jobs. Both `ShiftsManagementPage.tsx` and `UnifiedNav.tsx` call this one function, so the cancellation fix only has to be made once. `UnifiedNav.tsx` additionally derives a priority-based color (`failed > running > draft > done`) and passes it through a new optional `badgeColor` prop on `NavTab`/`NavSheetItem`, defaulting to the existing red so all other badge usages (pending approvals, swap requests) are unaffected.

**Tech Stack:** React hooks (`useState`, `useEffect`), TypeScript, Vitest + React Testing Library, Tailwind utility classes.

**Spec:** `docs/superpowers/specs/2026-06-23-algorithm-run-badge-fixes-design.md`

---

### Task 1: Shared `computeRunBadgeCounts` util

**Files:**
- Create: `frontend/src/utils/algorithmRunBadges.ts`
- Test: `frontend/src/utils/algorithmRunBadges.test.ts` (new)

- [ ] **Step 1: Write the failing test file**

Create `frontend/src/utils/algorithmRunBadges.test.ts`:

```ts
import { computeRunBadgeCounts } from "./algorithmRunBadges";

function job(status: string, mode: string, error_message: string | null = null) {
  return { status, mode, error_message };
}

describe("computeRunBadgeCounts", () => {
  test("returns all zeros for an empty list", () => {
    expect(computeRunBadgeCounts([])).toEqual({ running: 0, draft: 0, done: 0, failed: 0 });
  });

  test("groups pending/running jobs as running regardless of mode", () => {
    const counts = computeRunBadgeCounts([
      job("pending", "shadow"),
      job("running", "dm_reviewed"),
    ]);
    expect(counts).toEqual({ running: 2, draft: 0, done: 0, failed: 0 });
  });

  test("splits done jobs into draft (shadow) and done (dm_reviewed)", () => {
    const counts = computeRunBadgeCounts([
      job("done", "shadow"),
      job("done", "shadow"),
      job("done", "dm_reviewed"),
    ]);
    expect(counts).toEqual({ running: 0, draft: 2, done: 1, failed: 0 });
  });

  test("counts a genuine failure as failed", () => {
    const counts = computeRunBadgeCounts([job("failed", "shadow", "solver_timeout")]);
    expect(counts).toEqual({ running: 0, draft: 0, done: 0, failed: 1 });
  });

  test("excludes a cancelled job from every bucket", () => {
    const counts = computeRunBadgeCounts([
      job("failed", "shadow", "cancelled_by_user"),
      job("failed", "dm_reviewed", "solver_timeout"),
    ]);
    expect(counts).toEqual({ running: 0, draft: 0, done: 0, failed: 1 });
  });

  test("a published job (status not in pending/running/done/failed) counts nowhere", () => {
    const counts = computeRunBadgeCounts([job("published", "dm_reviewed")]);
    expect(counts).toEqual({ running: 0, draft: 0, done: 0, failed: 0 });
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/utils/algorithmRunBadges.test.ts`

Expected: FAIL — `Cannot find module './algorithmRunBadges'` (the file doesn't exist yet).

- [ ] **Step 3: Implement the util**

Create `frontend/src/utils/algorithmRunBadges.ts`:

```ts
export interface RunBadgeCounts {
  running: number;
  draft: number;
  done: number;
  failed: number;
}

interface RunBadgeJob {
  status: string;
  mode: string;
  error_message: string | null;
}

export function computeRunBadgeCounts(jobs: RunBadgeJob[]): RunBadgeCounts {
  return jobs.reduce<RunBadgeCounts>(
    (acc, job) => {
      if (job.status === "failed" && job.error_message === "cancelled_by_user") {
        return acc;
      }
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
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/utils/algorithmRunBadges.test.ts`

Expected: PASS — all 6 tests green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/algorithmRunBadges.ts frontend/src/utils/algorithmRunBadges.test.ts
git commit -m "feat: add computeRunBadgeCounts util that excludes cancelled jobs"
```

---

### Task 2: Use the shared util in `ShiftsManagementPage.tsx`

**Files:**
- Modify: `frontend/src/pages/planning/ShiftsManagementPage.tsx`
- Modify: `frontend/src/pages/planning/ShiftsManagementPage.test.tsx`

- [ ] **Step 1: Add a failing test for the cancelled-job exclusion**

In `frontend/src/pages/planning/ShiftsManagementPage.test.tsx`, change the `job()` helper to accept an optional `error_message`, and add a new test. Replace the existing helper and add the test at the end of the `describe` block:

```tsx
function job(status: string, mode: string, error_message: string | null = null) {
  return { status, mode, error_message };
}
```

(Replace the existing 2-argument `job()` function with this 3-argument version — the existing 3 tests call it with 2 args, which still works since `error_message` defaults to `null`.)

Add this test as a new `test(...)` inside the existing `describe("ShiftsManagementPage — algorithm run badges", ...)` block, after the "omits a badge when its group count is zero" test:

```tsx
  test("excludes a cancelled job from the failed badge", async () => {
    mockListJobs.mockResolvedValue({
      items: [
        job("failed", "shadow", "cancelled_by_user"),
        job("failed", "dm_reviewed", "solver_timeout"),
      ],
      total: 2,
    });
    render(<ShiftsManagementPage />);

    expect(await screen.findByTestId("algo-badge-failed")).toHaveTextContent("1");
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/planning/ShiftsManagementPage.test.tsx`

Expected: FAIL on the new "excludes a cancelled job from the failed badge" test — `algo-badge-failed` currently shows `"2"` because the inline `reduce` in `ShiftsManagementPage.tsx` doesn't know about `error_message`.

- [ ] **Step 3: Replace the inline grouping logic with the shared util**

In `frontend/src/pages/planning/ShiftsManagementPage.tsx`:

Replace the import block at the top:

```tsx
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import { ShiftsContent } from "../ShiftsPage";
import { ShiftTemplatesContent } from "../ShiftTemplatesPage";
import { AlgorithmContent } from "../AlgorithmPage";
import { listJobs } from "../../api/algorithm";
```

with:

```tsx
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import { ShiftsContent } from "../ShiftsPage";
import { ShiftTemplatesContent } from "../ShiftTemplatesPage";
import { AlgorithmContent } from "../AlgorithmPage";
import { listJobs } from "../../api/algorithm";
import { computeRunBadgeCounts, RunBadgeCounts } from "../../utils/algorithmRunBadges";
```

Remove the now-redundant local interface and constant:

```tsx
interface RunBadgeCounts {
  running: number;
  draft: number;
  done: number;
  failed: number;
}

const EMPTY_COUNTS: RunBadgeCounts = { running: 0, draft: 0, done: 0, failed: 0 };
```

Replace the `runBadgeCounts` state initializer (which referenced `EMPTY_COUNTS`):

```tsx
  const [runBadgeCounts, setRunBadgeCounts] = useState<RunBadgeCounts>(EMPTY_COUNTS);
```

with:

```tsx
  const [runBadgeCounts, setRunBadgeCounts] = useState<RunBadgeCounts>({ running: 0, draft: 0, done: 0, failed: 0 });
```

Replace the fetch effect's body:

```tsx
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
```

with:

```tsx
  useEffect(() => {
    async function fetchRunBadgeCounts() {
      try {
        const result = await listJobs(50);
        setRunBadgeCounts(computeRunBadgeCounts(result.items));
      } catch {
        // ignore — leave last known counts in place
      }
    }

    void fetchRunBadgeCounts();
    const interval = setInterval(() => void fetchRunBadgeCounts(), 30_000);
    return () => clearInterval(interval);
  }, [latestJobId]);
```

The rest of the file (badge JSX rendering, `handleJobSubmitted`, the two other collapsible sections) is unchanged.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/planning/ShiftsManagementPage.test.tsx`

Expected: PASS — all 4 tests green (the 3 original tests plus the new cancellation test).

- [ ] **Step 5: Run the full frontend test suite and linter**

```bash
cd frontend && npm test && npm run lint
```

Expected: all tests pass, zero lint warnings/errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/planning/ShiftsManagementPage.tsx frontend/src/pages/planning/ShiftsManagementPage.test.tsx
git commit -m "fix: exclude cancelled jobs from algorithm run section badges"
```

---

### Task 3: Color the nav badge by worst status

**Files:**
- Modify: `frontend/src/components/UnifiedNav.tsx`
- Modify: `frontend/src/components/NavSheet.tsx`
- Modify: `frontend/src/components/UnifiedNav.test.tsx`

- [ ] **Step 1: Add a `listJobs` mock and failing color tests to `UnifiedNav.test.tsx`**

In `frontend/src/components/UnifiedNav.test.tsx`, add this mock near the other `vi.mock("../api/...")` calls (after the `getIncomingSwapCount` mock, before the `NavSheet` mock):

```tsx
const mockListJobs = vi.fn();
vi.mock("../api/algorithm", () => ({
  listJobs: (...args: unknown[]) => mockListJobs(...args),
}));
```

Add a helper near the top of the file (after the imports, before the first `describe`):

```tsx
function job(status: string, mode: string, error_message: string | null = null) {
  return { status, mode, error_message };
}
```

Add `mockListJobs.mockResolvedValue({ items: [], total: 0 });` as a default inside a top-level `beforeEach`, placed right after the existing imports/mocks and before the first `describe` block:

```tsx
beforeEach(() => {
  mockListJobs.mockReset();
  mockListJobs.mockResolvedValue({ items: [], total: 0 });
});
```

Add a new `describe` block at the end of the file (after the "UnifiedNav — admin role" block):

```tsx
describe("UnifiedNav — algorithm badge color", () => {
  beforeEach(() => {
    mockUseAuth.mockReturnValue({ user: { role: "duty_manager" } });
  });

  test("shows red when any job failed, even with other statuses present", async () => {
    mockListJobs.mockResolvedValue({
      items: [job("running", "shadow"), job("failed", "dm_reviewed", "solver_timeout")],
      total: 2,
    });
    render(<UnifiedNav />);
    const badge = await screen.findAllByTestId("pending-badge");
    expect(badge.some((el) => el.className.includes("bg-red-500"))).toBe(true);
  });

  test("shows blue when running but nothing failed", async () => {
    mockListJobs.mockResolvedValue({
      items: [job("pending", "shadow"), job("done", "dm_reviewed")],
      total: 2,
    });
    render(<UnifiedNav />);
    const badge = await screen.findAllByTestId("pending-badge");
    expect(badge.some((el) => el.className.includes("bg-blue-500"))).toBe(true);
  });

  test("shows yellow when only drafts are pending review", async () => {
    mockListJobs.mockResolvedValue({
      items: [job("done", "shadow")],
      total: 1,
    });
    render(<UnifiedNav />);
    const badge = await screen.findAllByTestId("pending-badge");
    expect(badge.some((el) => el.className.includes("bg-yellow-500"))).toBe(true);
  });

  test("excludes cancelled jobs from the badge count", async () => {
    mockListJobs.mockResolvedValue({
      items: [job("failed", "shadow", "cancelled_by_user")],
      total: 1,
    });
    render(<UnifiedNav />);
    await waitFor(() => expect(mockListJobs).toHaveBeenCalled());
    expect(screen.queryByTestId("pending-badge")).not.toBeInTheDocument();
  });
});
```

Note: `screen.findAllByTestId("pending-badge")` will match badges from other tabs too (e.g. commander's `pendingCount` badge) if their count is also > 0 — but in these tests `mockUseAuth` returns `duty_manager` (not `commander`/`admin`), so `canApprove` is false and no commander badge renders. Only the planning tab/sheet algorithm badges render, both sharing the same color, so `.some(...)` is sufficient and exact.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/components/UnifiedNav.test.tsx`

Expected: FAIL on the 4 new tests in "UnifiedNav — algorithm badge color" — the badge has no color class to check yet beyond the hardcoded red, so the blue/yellow tests fail, and the cancellation test fails because the count isn't filtered yet.

- [ ] **Step 3: Add `badgeColor` to `NavSheetItem` and use it in `NavSheet.tsx`**

In `frontend/src/components/NavSheet.tsx`, replace the full file contents with:

```tsx
import { Link } from "react-router-dom";

export type BadgeColor = "red" | "blue" | "yellow" | "green";

const BADGE_COLOR_CLASSES: Record<BadgeColor, string> = {
  red: "bg-red-500 text-white",
  blue: "bg-blue-500 text-white",
  yellow: "bg-yellow-500 text-gray-900",
  green: "bg-green-500 text-white",
};

interface NavSheetItem {
  label: string;
  to: string;
  badge?: number;
  badgeColor?: BadgeColor;
  testId?: string;
}

interface NavSheetProps {
  open: boolean;
  onClose: () => void;
  items: NavSheetItem[];
  testId?: string;
}

export default function NavSheet({ open, onClose, items, testId }: NavSheetProps) {
  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 bg-black/30 z-40"
        onClick={onClose}
        data-testid={testId ? `${testId}-backdrop` : undefined}
        role="presentation"
      />
      <div
        role="dialog"
        aria-modal="true"
        className="fixed bottom-0 right-0 left-0 md:bottom-0 md:right-24 md:left-auto md:top-0 bg-white z-50 rounded-t-2xl md:rounded-none shadow-xl overflow-y-auto max-h-[50vh] md:max-h-full md:w-48 py-4 space-y-1 dark:bg-gray-800 dark:text-gray-100"
        onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}
        data-testid={testId}
      >
        <div className="flex justify-end px-3">
          <button
            autoFocus
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-lg leading-none"
            aria-label="סגור"
          >
            ✕
          </button>
        </div>
        {items.map((item) => (
          <Link
            key={item.to}
            to={item.to}
            onClick={onClose}
            className="flex items-center justify-between px-4 py-3 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700 rounded-lg"
            data-testid={item.testId}
          >
            <span>{item.label}</span>
            {item.badge != null && item.badge > 0 && (
              <span className={`${BADGE_COLOR_CLASSES[item.badgeColor ?? "red"]} text-xs rounded-full px-2 py-0.5 leading-4 min-w-[1.25rem] text-center`}>
                {item.badge}
              </span>
            )}
          </Link>
        ))}
      </div>
    </>
  );
}
```

- [ ] **Step 4: Add the color computation and `badgeColor` wiring to `UnifiedNav.tsx`**

In `frontend/src/components/UnifiedNav.tsx`:

Replace the import block:

```tsx
import { useState, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  House, FileText, ArrowLeftRight, Users, Wrench,
  Calendar, BarChart2,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { getPendingCount } from "../api/constraints";
import { getPendingExemptionCount } from "../api/exemptions";
import { getPendingFieldUpdateCount } from "../api/soldiers";
import { getIncomingSwapCount } from "../api/swaps";
import { listPendingEnrollments } from "../api/enrollment";
import { getPendingHakpazaCount } from "../api/hakpaza";
import { listJobs } from "../api/algorithm";
import NavSheet from "./NavSheet";
```

with:

```tsx
import { useState, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  House, FileText, ArrowLeftRight, Users, Wrench,
  Calendar, BarChart2,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { getPendingCount } from "../api/constraints";
import { getPendingExemptionCount } from "../api/exemptions";
import { getPendingFieldUpdateCount } from "../api/soldiers";
import { getIncomingSwapCount } from "../api/swaps";
import { listPendingEnrollments } from "../api/enrollment";
import { getPendingHakpazaCount } from "../api/hakpaza";
import { listJobs } from "../api/algorithm";
import { computeRunBadgeCounts, RunBadgeCounts } from "../utils/algorithmRunBadges";
import NavSheet, { BadgeColor } from "./NavSheet";
```

Replace the `NavTab` interface:

```tsx
interface NavTab {
  label: string;
  icon: React.ReactNode;
  to?: string;
  onClick?: () => void;
  badge?: number;
  testId: string;
}
```

with:

```tsx
interface NavTab {
  label: string;
  icon: React.ReactNode;
  to?: string;
  onClick?: () => void;
  badge?: number;
  badgeColor?: BadgeColor;
  testId: string;
}
```

Add a module-level helper above the `UnifiedNav` component (after the `NavTab` interface, before `export default function UnifiedNav()`):

```tsx
function pickBadgeColor(counts: RunBadgeCounts): BadgeColor {
  if (counts.failed > 0) return "red";
  if (counts.running > 0) return "blue";
  if (counts.draft > 0) return "yellow";
  return "green";
}
```

Replace the `algorithmBadgeCount` state declaration:

```tsx
  const [algorithmBadgeCount, setAlgorithmBadgeCount] = useState(0);
```

with:

```tsx
  const [algorithmBadgeCount, setAlgorithmBadgeCount] = useState(0);
  const [algorithmBadgeColor, setAlgorithmBadgeColor] = useState<BadgeColor>("red");
```

Replace the algorithm badge fetch effect:

```tsx
  useEffect(() => {
    if (!canPlan) return;

    async function fetchAlgorithmBadge() {
      try {
        const result = await listJobs(50);
        // The list endpoint already excludes published jobs, so all returned items need attention.
        const count = result.items.length;
        setAlgorithmBadgeCount(count);
      } catch {
        // ignore
      }
    }

    void fetchAlgorithmBadge();

    const interval = setInterval(() => void fetchAlgorithmBadge(), 30_000);
    return () => clearInterval(interval);
  }, [canPlan, location.pathname]);
```

with:

```tsx
  useEffect(() => {
    if (!canPlan) return;

    async function fetchAlgorithmBadge() {
      try {
        const result = await listJobs(50);
        const counts = computeRunBadgeCounts(result.items);
        setAlgorithmBadgeCount(counts.running + counts.draft + counts.done + counts.failed);
        setAlgorithmBadgeColor(pickBadgeColor(counts));
      } catch {
        // ignore
      }
    }

    void fetchAlgorithmBadge();

    const interval = setInterval(() => void fetchAlgorithmBadge(), 30_000);
    return () => clearInterval(interval);
  }, [canPlan, location.pathname]);
```

Replace the `planningTab` definition:

```tsx
  const planningTab: NavTab = {
    label: t("nav.planning"),
    icon: <Wrench size={20} />,
    onClick: () => setPlanningSheetOpen(true),
    badge: algorithmBadgeCount,
    testId: "nav-planning",
  };
```

with:

```tsx
  const planningTab: NavTab = {
    label: t("nav.planning"),
    icon: <Wrench size={20} />,
    onClick: () => setPlanningSheetOpen(true),
    badge: algorithmBadgeCount,
    badgeColor: algorithmBadgeColor,
    testId: "nav-planning",
  };
```

Replace the `planningItems` array's `planning_shifts` entry:

```tsx
  const planningItems = [
    { label: t("nav.planning_shifts"), to: "/planning/shifts", badge: algorithmBadgeCount, testId: "nav-shifts-management" },
```

with:

```tsx
  const planningItems = [
    { label: t("nav.planning_shifts"), to: "/planning/shifts", badge: algorithmBadgeCount, badgeColor: algorithmBadgeColor, testId: "nav-shifts-management" },
```

Replace the `tabContent` helper's badge `<span>`:

```tsx
  const tabContent = (tab: NavTab) => (
    <>
      {tab.icon}
      {tab.badge != null && tab.badge > 0 && (
        <span
          className="absolute top-1 right-1/4 md:top-2 md:left-3 bg-red-500 text-white text-[10px] rounded-full px-1.5 leading-5"
          data-testid="pending-badge"
        >
          {tab.badge}
        </span>
      )}
      <span className="text-center leading-tight">{tab.label}</span>
    </>
  );
```

with:

```tsx
  const tabContent = (tab: NavTab) => (
    <>
      {tab.icon}
      {tab.badge != null && tab.badge > 0 && (
        <span
          className={`absolute top-1 right-1/4 md:top-2 md:left-3 ${BADGE_COLOR_CLASSES[tab.badgeColor ?? "red"]} text-[10px] rounded-full px-1.5 leading-5`}
          data-testid="pending-badge"
        >
          {tab.badge}
        </span>
      )}
      <span className="text-center leading-tight">{tab.label}</span>
    </>
  );
```

Add the `BADGE_COLOR_CLASSES` constant at module scope, right after the `NavTab` interface (before `pickBadgeColor`):

```tsx
const BADGE_COLOR_CLASSES: Record<BadgeColor, string> = {
  red: "bg-red-500 text-white",
  blue: "bg-blue-500 text-white",
  yellow: "bg-yellow-500 text-gray-900",
  green: "bg-green-500 text-white",
};
```

(This duplicates the same map defined in `NavSheet.tsx` in Task 3 Step 3 — both files need it locally since `UnifiedNav.tsx`'s `tabContent` renders its own badge `<span>` independently of `NavSheet`. This is acceptable duplication: it's a 4-line constant, not logic, and extracting a shared constant for two call sites isn't worth a new shared module.)

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/components/UnifiedNav.test.tsx`

Expected: PASS — all tests green, including the 4 new color tests and all pre-existing tests (the new `beforeEach` default-mocking `listJobs` to return `{ items: [], total: 0 }` keeps prior tests' badge-count assumptions unchanged).

- [ ] **Step 6: Run the full frontend test suite and linter**

```bash
cd frontend && npm test && npm run lint
```

Expected: all tests pass, zero lint warnings/errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/UnifiedNav.tsx frontend/src/components/NavSheet.tsx frontend/src/components/UnifiedNav.test.tsx
git commit -m "feat: color the algorithm nav badge by worst run status"
```
