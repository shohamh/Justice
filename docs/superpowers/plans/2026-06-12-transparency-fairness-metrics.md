# Transparency Fairness Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add CV-based effort inequality metrics to the Transparency page — a fairness card, effort column color bands, and sub-unit inequality columns/card.

**Architecture:** All stats are computed frontend-only from the already-returned `effort_score` field on `TransparencyRow`. A shared `computeEffortStats` utility computes mean/stddev/CV/min/max. No backend changes. Stats always reflect the current filter state (filtered `visibleRows` / `subRows`).

**Tech Stack:** React, TypeScript, Tailwind CSS, vitest + @testing-library/react

---

## File Map

| File | Role |
|---|---|
| `frontend/src/utils/effortStats.ts` | **Create** — pure stats functions (`computeEffortStats`, `getEffortColor`) |
| `frontend/src/utils/effortStats.test.ts` | **Create** — unit tests for stats functions |
| `frontend/src/pages/TransparencyPage.tsx` | **Modify** — add fairness card, color bands, sub-unit columns |
| `frontend/src/i18n/he.json` | **Modify** — add Hebrew translation keys |

---

### Task 1: i18n keys

**Files:**
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add translation keys**

Open `frontend/src/i18n/he.json`. Find the `"transparency"` object (search for `"effort_spread"` to verify it doesn't already exist). Add the following keys at the end of the `"transparency"` object, before its closing `}`:

```json
"effort_spread": "פיזור עומס",
"effort_mean": "ממוצע עומס",
"effort_stddev": "סטיית תקן",
"effort_range": "טווח",
"subunit_avg_effort": "ממוצע עומס",
"subunit_cv_effort": "פיזור (CV)"
```

The `"transparency"` object already ends with `"exempted_count_tooltip": "..."`. Insert a comma after that line, then the new keys.

- [ ] **Step 2: Verify lint passes**

Run from `frontend/`:
```
pnpm lint
```
Expected: 0 errors, 0 warnings.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/he.json
git commit -m "i18n: add fairness metrics translation keys"
```

---

### Task 2: `effortStats` utility and tests

**Files:**
- Create: `frontend/src/utils/effortStats.ts`
- Create: `frontend/src/utils/effortStats.test.ts`

- [ ] **Step 1: Write failing tests**

Create `frontend/src/utils/effortStats.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { computeEffortStats, getEffortColor } from "./effortStats";

describe("computeEffortStats", () => {
  it("returns null for empty array", () => {
    expect(computeEffortStats([])).toBeNull();
  });

  it("returns null for single-element array", () => {
    expect(computeEffortStats([0.5])).toBeNull();
  });

  it("returns correct stats for uniform array", () => {
    const result = computeEffortStats([0.1, 0.1, 0.1]);
    expect(result).not.toBeNull();
    expect(result!.mean).toBeCloseTo(0.1);
    expect(result!.stddev).toBeCloseTo(0);
    expect(result!.cv).toBeCloseTo(0);
    expect(result!.min).toBeCloseTo(0.1);
    expect(result!.max).toBeCloseTo(0.1);
  });

  it("returns correct stats for varied array", () => {
    // [0.1, 0.3] → mean=0.2, variance=0.01, stddev=0.1, cv=0.5
    const result = computeEffortStats([0.1, 0.3]);
    expect(result).not.toBeNull();
    expect(result!.mean).toBeCloseTo(0.2);
    expect(result!.stddev).toBeCloseTo(0.1);
    expect(result!.cv).toBeCloseTo(0.5);
    expect(result!.min).toBeCloseTo(0.1);
    expect(result!.max).toBeCloseTo(0.3);
  });

  it("returns cv=0 when mean is 0", () => {
    const result = computeEffortStats([0, 0, 0]);
    expect(result).not.toBeNull();
    expect(result!.cv).toBe(0);
  });
});

describe("getEffortColor", () => {
  it("returns green class when value is within 1 stddev of mean", () => {
    // mean=0.2, stddev=0.1: value 0.25 is 0.5σ away
    expect(getEffortColor(0.25, 0.2, 0.1)).toContain("green");
  });

  it("returns yellow class when value is between 1 and 2 stddev", () => {
    // mean=0.2, stddev=0.1: value 0.35 is 1.5σ away
    expect(getEffortColor(0.35, 0.2, 0.1)).toContain("yellow");
  });

  it("returns red class when value is beyond 2 stddev", () => {
    // mean=0.2, stddev=0.1: value 0.45 is 2.5σ away
    expect(getEffortColor(0.45, 0.2, 0.1)).toContain("red");
  });

  it("returns empty string when stddev is 0", () => {
    expect(getEffortColor(0.2, 0.2, 0)).toBe("");
  });
});
```

- [ ] **Step 2: Run tests to confirm they fail**

Run from `frontend/`:
```
pnpm test --run src/utils/effortStats.test.ts
```
Expected: FAIL — cannot find module `./effortStats`.

- [ ] **Step 3: Create the utility**

Create `frontend/src/utils/effortStats.ts`:

```ts
export interface EffortStats {
  mean: number;
  stddev: number;
  cv: number;
  min: number;
  max: number;
}

export function computeEffortStats(values: number[]): EffortStats | null {
  if (values.length < 2) return null;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const variance = values.reduce((s, v) => s + (v - mean) ** 2, 0) / values.length;
  const stddev = Math.sqrt(variance);
  const cv = mean === 0 ? 0 : stddev / mean;
  return { mean, stddev, cv, min: Math.min(...values), max: Math.max(...values) };
}

/** Tailwind bg class based on distance from mean in stddev units. Empty string when stddev === 0. */
export function getEffortColor(value: number, mean: number, stddev: number): string {
  if (stddev === 0) return "";
  const dev = Math.abs(value - mean) / stddev;
  if (dev <= 1) return "bg-green-100 dark:bg-green-950";
  if (dev <= 2) return "bg-yellow-100 dark:bg-yellow-950";
  return "bg-red-100 dark:bg-red-950";
}
```

- [ ] **Step 4: Run tests to confirm they pass**

Run from `frontend/`:
```
pnpm test --run src/utils/effortStats.test.ts
```
Expected: PASS — all 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/utils/effortStats.ts frontend/src/utils/effortStats.test.ts
git commit -m "feat: add computeEffortStats and getEffortColor utilities"
```

---

### Task 3: Fairness card on soldiers tab

**Files:**
- Modify: `frontend/src/pages/TransparencyPage.tsx`

The page already has four summary cards in a `grid-cols-2 sm:grid-cols-4` grid. We'll add a 5th card (the fairness card) and extend the grid.

- [ ] **Step 1: Import the utilities**

At the top of `frontend/src/pages/TransparencyPage.tsx`, after all existing imports (around line 11), add:

```ts
import { computeEffortStats, getEffortColor, type EffortStats } from "../utils/effortStats";
```

- [ ] **Step 2: Add the FairnessCard component**

Add this component above the `export default function TransparencyPage()` line (after the `FilterPills` component, around line 115):

```tsx
function FairnessCard({ stats }: { stats: EffortStats | null }) {
  const { t } = useTranslation();
  if (!stats) {
    return (
      <div className="bg-gray-50 dark:bg-gray-700 rounded-lg p-3 border border-gray-200 dark:border-gray-600 text-center">
        <p className="text-xs text-gray-500 dark:text-gray-400">{t("transparency.effort_spread")}</p>
        <p className="text-lg font-semibold text-gray-400">—</p>
      </div>
    );
  }
  const cvPct = stats.cv * 100;
  const cardClass = cvPct < 25
    ? "bg-green-50 dark:bg-green-950 border-green-300 dark:border-green-700"
    : cvPct < 50
      ? "bg-yellow-50 dark:bg-yellow-950 border-yellow-300 dark:border-yellow-700"
      : "bg-red-50 dark:bg-red-950 border-red-300 dark:border-red-700";
  const dotClass = cvPct < 25 ? "bg-green-500" : cvPct < 50 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className={`rounded-lg p-3 border text-center ${cardClass}`}>
      <p className="text-xs text-gray-500 dark:text-gray-400 flex items-center justify-center gap-1">
        <span className={`inline-block w-2 h-2 rounded-full ${dotClass}`} />
        {t("transparency.effort_spread")}
      </p>
      <p className="text-lg font-semibold text-gray-800 dark:text-gray-100">{cvPct.toFixed(1)}%</p>
      <div className="mt-1 text-xs text-gray-500 dark:text-gray-400 space-y-0.5">
        <p>{t("transparency.effort_mean")}: {(stats.mean * 100).toFixed(1)}%</p>
        <p>{t("transparency.effort_stddev")}: ±{(stats.stddev * 100).toFixed(1)}%</p>
        <p>{t("transparency.effort_range")}: {(stats.min * 100).toFixed(1)}%–{(stats.max * 100).toFixed(1)}%</p>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Compute effortStats and subEffortStats**

Inside `TransparencyPage`, after the `avgNormalised` computed value (around line 252, before `handleSelectNode`), add:

```ts
const effortStats: EffortStats | null = tab === 0
  ? computeEffortStats(visibleRows.map((r) => r.effort_score).filter((v) => !isNaN(v)))
  : null;

const subEffortStats: EffortStats | null = tab === 1
  ? computeEffortStats(subRows.map((r) => r.avg_effort).filter((v) => !isNaN(v) && v > 0))
  : null;
```

Note: `subRows` already exists above this point. `subRows` includes `avg_effort` which will be added in Task 5. For now, TypeScript will error until Task 5. You can temporarily comment out the `subEffortStats` line if needed and un-comment it in Task 5.

- [ ] **Step 4: Extend the summary grid and add FairnessCard**

Find the summary cards grid opening tag (around line 457):
```tsx
<div className="grid grid-cols-2 sm:grid-cols-4 gap-3" dir="rtl">
```

Replace with:
```tsx
<div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-5 gap-3" dir="rtl">
```

Then, after the last existing card (`avg_normalised`), add:
```tsx
{tab === 0 && <FairnessCard stats={effortStats} />}
{tab === 1 && <FairnessCard stats={subEffortStats} />}
```

- [ ] **Step 5: Run lint**

Run from `frontend/`:
```
pnpm lint
```
Expected: TypeScript may report `Property 'avg_effort' does not exist on type 'SubRow'` — this is expected and will be resolved in Task 5. If lint errors are only this type error, note it and continue. If there are other lint errors, fix them.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/TransparencyPage.tsx
git commit -m "feat: add effort spread (CV) fairness card to transparency page"
```

---

### Task 4: Effort column color bands

**Files:**
- Modify: `frontend/src/pages/TransparencyPage.tsx`

`getEffortColor` is already imported (from Task 3). `effortStats` is already computed (from Task 3).

- [ ] **Step 1: Update the effort_score column cell**

Find the `effort_score` column definition in `soldierCols` (around line 313). It currently looks like:

```tsx
cell: (r) => {
  const n = r.effort_score;
  const label = isNaN(n) || n === undefined ? "—" : (n * 100).toFixed(2) + "%";
  return (
    <button
      className="text-indigo-600 dark:text-indigo-400 hover:underline font-medium"
      onClick={() => void openEffortBreakdown(r.soldier_id, r.full_name)}
      title="לחץ לפירוט רבעוני"
    >
      {label}
    </button>
  );
},
```

Replace it with:

```tsx
cell: (r) => {
  const n = r.effort_score;
  const label = isNaN(n) || n === undefined ? "—" : (n * 100).toFixed(2) + "%";
  const colorClass = effortStats ? getEffortColor(n, effortStats.mean, effortStats.stddev) : "";
  return (
    <span className={`inline-block w-full rounded px-0.5 ${colorClass}`}>
      <button
        className="text-indigo-600 dark:text-indigo-400 hover:underline font-medium"
        onClick={() => void openEffortBreakdown(r.soldier_id, r.full_name)}
        title="לחץ לפירוט רבעוני"
      >
        {label}
      </button>
    </span>
  );
},
```

- [ ] **Step 2: Run lint**

Run from `frontend/`:
```
pnpm lint
```
Expected: 0 lint errors (excluding the pre-existing `avg_effort` type error from Task 3 if still present).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/TransparencyPage.tsx
git commit -m "feat: add effort column color bands based on stddev distance"
```

---

### Task 5: Sub-units tab — avg effort, CV columns, and fairness card

**Files:**
- Modify: `frontend/src/pages/TransparencyPage.tsx`

This task adds `avg_effort` and `cv_effort` to `SubRow`, computes them in `subRows`, adds two table columns, and wires up `subEffortStats` (already declared in Task 3 — remove the comment if you added one).

- [ ] **Step 1: Extend SubRow interface**

Find the `SubRow` interface (around line 119). Add two fields at the end:

```ts
interface SubRow {
  node_id: string;
  node_name: string;
  depth: number;
  count: number;
  active_count: number;
  exempted_count: number;
  avg_cumulative: number;
  avg_cumulative_active: number;
  total_score_per_day: number;
  avg_active_days: number;
  avg_normalised: number;
  avg_effort: number;
  cv_effort: number | null;
}
```

- [ ] **Step 2: Compute avg_effort and cv_effort in subRows**

Find the `result.push({...})` call inside the `subRows` useMemo (around line 215). It ends with `avg_normalised: avg(nodeRows.map((r) => Number(r.normalised_score))),`. Add after that (still inside the same object):

```ts
avg_effort: (() => {
  const efforts = nodeRows.map((r) => r.effort_score).filter((v) => !isNaN(v));
  return efforts.length > 0 ? efforts.reduce((a, b) => a + b, 0) / efforts.length : 0;
})(),
cv_effort: (() => {
  const efforts = nodeRows.map((r) => r.effort_score).filter((v) => !isNaN(v));
  const stats = computeEffortStats(efforts);
  return stats ? stats.cv : null;
})(),
```

- [ ] **Step 3: Add avg_effort and cv_effort columns to subCols**

Find the `subCols` array (around line 333). Add two columns before the closing `]`:

```ts
{
  id: "avg_effort",
  header: t("transparency.subunit_avg_effort"),
  cell: (r) => r.avg_effort > 0 ? (r.avg_effort * 100).toFixed(1) + "%" : "—",
  sortValue: (r) => r.avg_effort,
},
{
  id: "cv_effort",
  header: t("transparency.subunit_cv_effort"),
  cell: (r) => {
    if (r.cv_effort === null) return "—";
    const pct = r.cv_effort * 100;
    const colorClass = pct < 25
      ? "text-green-600 dark:text-green-400"
      : pct < 50
        ? "text-yellow-600 dark:text-yellow-400"
        : "text-red-600 dark:text-red-400 font-medium";
    return <span className={colorClass}>{pct.toFixed(1)}%</span>;
  },
  sortValue: (r) => r.cv_effort ?? -1,
},
```

- [ ] **Step 4: Ensure subEffortStats is active**

In Task 3 Step 3, `subEffortStats` was added (possibly commented out pending `avg_effort`). Now that `SubRow.avg_effort` exists, confirm the line is active (not commented):

```ts
const subEffortStats: EffortStats | null = tab === 1
  ? computeEffortStats(subRows.map((r) => r.avg_effort).filter((v) => !isNaN(v) && v > 0))
  : null;
```

- [ ] **Step 5: Run lint and all tests**

Run from `frontend/`:
```
pnpm lint
pnpm test --run
```
Expected: 0 lint errors, all tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/TransparencyPage.tsx
git commit -m "feat: add avg effort and CV spread to sub-units tab"
```
