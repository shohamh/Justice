# Algorithm Runs Badge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a badge on the planning nav tab and the "ריצות אלגוריתם" sheet item when there are algorithm jobs in `pending`, `running`, `done`, or `failed` status.

**Architecture:** Add a single `useEffect` in `UnifiedNav.tsx` that calls `listJobs(50)`, counts attention-needing jobs, and stores the count in state. The count is auto-polled every 30s while active (pending/running) jobs exist. The badge is forwarded to both `planningTab` and the `planning_shifts` entry in `planningItems`.

**Tech Stack:** React hooks, existing `listJobs` API function, existing `NavTab.badge` field, existing `NavSheet` badge support.

---

### Task 1: Add algorithm badge to UnifiedNav

**Files:**
- Modify: `frontend/src/components/UnifiedNav.tsx`

- [ ] **Step 1: Import `listJobs` at the top of the file**

In `frontend/src/components/UnifiedNav.tsx`, add to the existing imports:

```ts
import { listJobs } from "../api/algorithm";
```

- [ ] **Step 2: Add state and polling effect**

After the existing `const [planningSheetOpen, setPlanningSheetOpen] = useState(false);` line, add:

```ts
const [algorithmBadgeCount, setAlgorithmBadgeCount] = useState(0);
```

Then add a new `useEffect` after the existing swap count effect (after the `}, [location.pathname]);` that closes the swap effect):

```ts
useEffect(() => {
  if (!canPlan) return;

  async function fetchAlgorithmBadge() {
    try {
      const result = await listJobs(50);
      const count = result.items.filter(
        (j) => j.status === "pending" || j.status === "running" || j.status === "done" || j.status === "failed"
      ).length;
      setAlgorithmBadgeCount(count);
    } catch {
      // ignore
    }
  }

  void fetchAlgorithmBadge();

  // Poll every 30s while there may be active runs
  const interval = setInterval(() => void fetchAlgorithmBadge(), 30_000);
  return () => clearInterval(interval);
}, [canPlan, location.pathname]);
```

- [ ] **Step 3: Add badge to planningTab**

Find the `planningTab` definition:

```ts
const planningTab: NavTab = {
  label: t("nav.planning"),
  icon: <Wrench size={20} />,
  onClick: () => setPlanningSheetOpen(true),
  testId: "nav-planning",
};
```

Replace with:

```ts
const planningTab: NavTab = {
  label: t("nav.planning"),
  icon: <Wrench size={20} />,
  onClick: () => setPlanningSheetOpen(true),
  badge: algorithmBadgeCount,
  testId: "nav-planning",
};
```

- [ ] **Step 4: Add badge to planning_shifts sheet item**

Find the `planningItems` array and the `planning_shifts` entry:

```ts
{ label: t("nav.planning_shifts"), to: "/planning/shifts", testId: "nav-shifts-management" },
```

Replace with:

```ts
{ label: t("nav.planning_shifts"), to: "/planning/shifts", badge: algorithmBadgeCount, testId: "nav-shifts-management" },
```

- [ ] **Step 5: Run the frontend linter to verify no type errors**

```bash
cd frontend && npm run lint
```

Expected: zero warnings, zero errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/UnifiedNav.tsx
git commit -m "feat: add algorithm runs badge to planning nav tab and sheet item"
```
