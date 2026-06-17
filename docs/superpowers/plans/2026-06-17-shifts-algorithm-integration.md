# Shifts + Algorithm Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the Algorithm and Shifts experiences into a single `/planning/shifts` page and remove the `/planning/assignment` page entirely.

**Architecture:** A new `AlgorithmInlinePanel` component (extracted from `AlgorithmRunForm` — same settings/mode/submit logic, no date/shift picker) renders inline inside `ShiftsContent` when the "שיבוץ אוטומטי" button is clicked. A new collapsible "ריצות אלגוריתם" section above the shifts table shows `AlgorithmContent`. `ShiftsManagementPage` wires the two together: job submission in the inline panel auto-opens the runs section and pre-selects the new job.

**Tech Stack:** React 18, TypeScript, TanStack Table v8, Vitest + @testing-library/react, i18next, Tailwind CSS.

---

## File Map

| Action | File |
|--------|------|
| **Create** | `frontend/src/components/AlgorithmInlinePanel.tsx` |
| **Create** | `frontend/src/components/AlgorithmInlinePanel.test.tsx` |
| **Modify** | `frontend/src/pages/AlgorithmPage.tsx` — add `initialJobId?: string` prop |
| **Modify** | `frontend/src/pages/ShiftsPage.tsx` — checkboxes, algorithm panel, button |
| **Modify** | `frontend/src/pages/planning/ShiftsManagementPage.tsx` — runs collapsible |
| **Delete** | `frontend/src/pages/planning/AssignmentPage.tsx` |
| **Modify** | `frontend/src/App.tsx` — remove assignment route, fix redirects |
| **Modify** | `frontend/src/components/UnifiedNav.tsx` — remove "שיבוץ" nav item |

---

## Task 1: Create `AlgorithmInlinePanel`

**Files:**
- Create: `frontend/src/components/AlgorithmInlinePanel.tsx`
- Create: `frontend/src/components/AlgorithmInlinePanel.test.tsx`

### What it does

Renders the algorithm run form *without* the date picker or shift list (those come from the DataTable). Extracted from `AlgorithmRunForm`.

Props:
```ts
interface Props {
  selectedShiftIds: string[];
  dutyTypes: DutyType[];
  onJobSubmitted: (jobId: string) => void;
  onClose: () => void;
}
```

- [ ] **Step 1.1: Write the failing test**

`frontend/src/components/AlgorithmInlinePanel.test.tsx`:
```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import AlgorithmInlinePanel from "./AlgorithmInlinePanel";
import * as algorithmApi from "../api/algorithm";

vi.mock("../api/algorithm", () => ({
  submitJob: vi.fn(),
  getAlgorithmDefaults: vi.fn().mockResolvedValue({ T: 8, Wt: 14, R: 15, Wr: 28 }),
}));

vi.mock("./SubHierarchySelector", () => ({
  default: () => <div data-testid="sub-hierarchy-selector" />,
}));

vi.mock("./AlgorithmModeHelpModal", () => ({
  default: ({ onClose }: { onClose: () => void }) => (
    <div data-testid="mode-help-modal">
      <button onClick={onClose}>סגור</button>
    </div>
  ),
}));

const DUTY_TYPES = [{ id: "dt1", name: "שמירה", is_reserve_type: false }];

test("shows selected shift count badge", () => {
  render(
    <AlgorithmInlinePanel
      selectedShiftIds={["s1", "s2", "s3"]}
      dutyTypes={DUTY_TYPES}
      onJobSubmitted={vi.fn()}
      onClose={vi.fn()}
    />
  );
  expect(screen.getByText(/3 משמרות נבחרות/)).toBeInTheDocument();
});

test("run button disabled when 0 shifts selected", () => {
  render(
    <AlgorithmInlinePanel
      selectedShiftIds={[]}
      dutyTypes={DUTY_TYPES}
      onJobSubmitted={vi.fn()}
      onClose={vi.fn()}
    />
  );
  expect(screen.getByRole("button", { name: /הרץ שיבוץ/ })).toBeDisabled();
});

test("run button enabled when shifts selected", () => {
  render(
    <AlgorithmInlinePanel
      selectedShiftIds={["s1"]}
      dutyTypes={DUTY_TYPES}
      onJobSubmitted={vi.fn()}
      onClose={vi.fn()}
    />
  );
  expect(screen.getByRole("button", { name: /הרץ שיבוץ/ })).toBeEnabled();
});

test("calls submitJob and onJobSubmitted on run", async () => {
  const mockSubmit = vi.mocked(algorithmApi.submitJob).mockResolvedValue({
    id: "job-123",
  } as Awaited<ReturnType<typeof algorithmApi.submitJob>>);
  const onJobSubmitted = vi.fn();
  const onClose = vi.fn();

  render(
    <AlgorithmInlinePanel
      selectedShiftIds={["s1", "s2"]}
      dutyTypes={DUTY_TYPES}
      onJobSubmitted={onJobSubmitted}
      onClose={onClose}
    />
  );

  fireEvent.click(screen.getByRole("button", { name: /הרץ שיבוץ/ }));

  await waitFor(() => {
    expect(mockSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ shift_ids: ["s1", "s2"], mode: "shadow" })
    );
    expect(onJobSubmitted).toHaveBeenCalledWith("job-123");
    expect(onClose).toHaveBeenCalled();
  });
});

test("shows error message on submit failure", async () => {
  vi.mocked(algorithmApi.submitJob).mockRejectedValue({
    response: { data: { detail: "server_error" } },
  });

  render(
    <AlgorithmInlinePanel
      selectedShiftIds={["s1"]}
      dutyTypes={DUTY_TYPES}
      onJobSubmitted={vi.fn()}
      onClose={vi.fn()}
    />
  );

  fireEvent.click(screen.getByRole("button", { name: /הרץ שיבוץ/ }));

  await waitFor(() => {
    expect(screen.getByText("server_error")).toBeInTheDocument();
  });
});

test("close button calls onClose", () => {
  const onClose = vi.fn();
  render(
    <AlgorithmInlinePanel
      selectedShiftIds={[]}
      dutyTypes={DUTY_TYPES}
      onJobSubmitted={vi.fn()}
      onClose={onClose}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "✕" }));
  expect(onClose).toHaveBeenCalled();
});
```

- [ ] **Step 1.2: Run test to verify it fails**

```bash
cd frontend && npm test -- --reporter=verbose AlgorithmInlinePanel
```

Expected: FAIL — `AlgorithmInlinePanel` module not found.

- [ ] **Step 1.3: Create the component**

`frontend/src/components/AlgorithmInlinePanel.tsx`:
```tsx
import { useEffect, useState } from "react";
import { SolverSettings, submitJob, getAlgorithmDefaults } from "../api/algorithm";
import { DutyType } from "../api/dutyConfig";
import SubHierarchySelector from "./SubHierarchySelector";
import AlgorithmModeHelpModal from "./AlgorithmModeHelpModal";

interface Props {
  selectedShiftIds: string[];
  dutyTypes: DutyType[];
  onJobSubmitted: (jobId: string) => void;
  onClose: () => void;
}

const DEFAULT_SETTINGS: SolverSettings = {
  K: 8, T: 8, Wt: 14, R: 15, Wr: 28, alpha: 1.0, beta: 2.0, time_limit_seconds: 30,
};

export default function AlgorithmInlinePanel({ selectedShiftIds, onJobSubmitted, onClose }: Props) {
  const [mode, setMode] = useState<"draft" | "direct_publish">("draft");
  const [showModeHelp, setShowModeHelp] = useState(false);
  const [settings, setSettings] = useState<SolverSettings>(DEFAULT_SETTINGS);
  const [showSettings, setShowSettings] = useState(false);
  const [eligibleNodeIds, setEligibleNodeIds] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    void getAlgorithmDefaults()
      .then(d => setSettings(s => ({ ...s, T: d.T, Wt: d.Wt, R: d.R, Wr: d.Wr })))
      .catch(() => {});
  }, []);

  async function handleSubmit() {
    setError(null);
    setSubmitting(true);
    try {
      const apiMode = mode === "draft" ? "shadow" : "dm_reviewed";
      const resp = await submitJob({ shift_ids: selectedShiftIds, mode: apiMode, settings });
      onJobSubmitted(resp.id);
      onClose();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? "שגיאה בשליחת הבקשה");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="border dark:border-gray-600 rounded-lg bg-indigo-50 dark:bg-indigo-950 p-4 space-y-3 text-sm" dir="rtl">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-indigo-800 dark:text-indigo-200">
          {selectedShiftIds.length} משמרות נבחרות
        </span>
        <button
          type="button"
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
          aria-label="✕"
        >
          ✕
        </button>
      </div>

      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">מצב הרצה:</span>
        <div className="flex rounded border border-gray-300 dark:border-gray-600 overflow-hidden text-sm">
          <button
            type="button"
            className={`px-3 py-1 ${mode === "draft" ? "bg-indigo-600 text-white" : "bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300"}`}
            onClick={() => setMode("draft")}
          >
            טיוטה
          </button>
          <button
            type="button"
            className={`px-3 py-1 ${mode === "direct_publish" ? "bg-indigo-600 text-white" : "bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-300"}`}
            onClick={() => setMode("direct_publish")}
          >
            פרסום ישיר
          </button>
        </div>
        <button
          type="button"
          className="text-gray-400 hover:text-indigo-600 text-xs font-bold border rounded-full w-5 h-5 flex items-center justify-center flex-shrink-0"
          onClick={() => setShowModeHelp(true)}
          title="מה ההבדל?"
        >
          ?
        </button>
        {showModeHelp && <AlgorithmModeHelpModal onClose={() => setShowModeHelp(false)} />}
      </div>

      <button
        type="button"
        className="text-xs text-blue-600 dark:text-blue-400 underline"
        onClick={() => setShowSettings(s => !s)}
      >
        הגדרות מתקדמות
      </button>
      {showSettings && (
        <div className="grid grid-cols-3 gap-3 text-xs bg-gray-50 dark:bg-gray-700 p-3 rounded">
          {(["K", "T", "Wt", "R", "Wr", "alpha", "beta", "time_limit_seconds"] as const).map(key => (
            <label key={key} className="block">
              {key}
              <input
                type="number"
                value={settings[key]}
                onChange={e => setSettings(s => ({ ...s, [key]: parseFloat(e.target.value) }))}
                className="mt-1 block w-full border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100"
                step={key === "alpha" || key === "beta" ? 0.1 : 1}
              />
            </label>
          ))}
        </div>
      )}

      <details className="border dark:border-gray-600 rounded p-2">
        <summary className="cursor-pointer">הגבלת תת-עץ</summary>
        <SubHierarchySelector value={eligibleNodeIds} onChange={setEligibleNodeIds} />
      </details>

      {error && <p className="text-red-500 text-xs">{error}</p>}

      <button
        type="button"
        onClick={handleSubmit}
        disabled={submitting || selectedShiftIds.length === 0}
        className="w-full bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50 font-medium"
      >
        הרץ שיבוץ אוטומטי {selectedShiftIds.length > 0 && `(${selectedShiftIds.length})`}
      </button>
    </div>
  );
}
```

- [ ] **Step 1.4: Run test to verify it passes**

```bash
cd frontend && npm test -- --reporter=verbose AlgorithmInlinePanel
```

Expected: all 6 tests PASS.

- [ ] **Step 1.5: Run lint**

```bash
cd frontend && npm run lint
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 1.6: Commit**

```bash
git add frontend/src/components/AlgorithmInlinePanel.tsx frontend/src/components/AlgorithmInlinePanel.test.tsx
git commit -m "feat: add AlgorithmInlinePanel component"
```

---

## Task 2: Add `initialJobId` prop to `AlgorithmContent`

**Files:**
- Modify: `frontend/src/pages/AlgorithmPage.tsx`

`AlgorithmContent` currently selects a job from URL searchParams. When embedded in `ShiftsManagementPage`, we need to select a job via prop instead.

- [ ] **Step 2.1: Update `AlgorithmContent` signature and add effect**

In `frontend/src/pages/AlgorithmPage.tsx`, change line 12:

```ts
// Before:
export function AlgorithmContent() {

// After:
export function AlgorithmContent({ initialJobId }: { initialJobId?: string | null } = {}) {
```

Then add a new `useEffect` after the existing `searchParams` effect (after line ~63):

```ts
// Sync initialJobId prop → selectedJobId (used when embedded in ShiftsManagementPage)
useEffect(() => {
  if (initialJobId) setSelectedJobId(initialJobId);
}, [initialJobId]);
```

The full updated signature block (lines 12-22) becomes:

```ts
export function AlgorithmContent({ initialJobId }: { initialJobId?: string | null } = {}) {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();

  const [jobs, setJobs] = useState<JobSummaryOut[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<AlgorithmJob | null>(null);
  const [showRunForm, setShowRunForm] = useState(false);
  const [rerunOverrides, setRerunOverrides] = useState<Record<string, number> | null>(null);
  const [soldiers, setSoldiers] = useState<SoldierDTO[]>([]);
  const [dutyTypes, setDutyTypes] = useState<DutyType[]>([]);
```

And add after the existing searchParams effect (around line 63):

```ts
useEffect(() => {
  if (initialJobId) setSelectedJobId(initialJobId);
}, [initialJobId]);
```

- [ ] **Step 2.2: Run lint**

```bash
cd frontend && npm run lint
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 2.3: Run existing frontend tests to confirm no regressions**

```bash
cd frontend && npm test
```

Expected: all tests PASS.

- [ ] **Step 2.4: Commit**

```bash
git add frontend/src/pages/AlgorithmPage.tsx
git commit -m "feat: add initialJobId prop to AlgorithmContent"
```

---

## Task 3: Extend `ShiftsContent` with checkboxes, button, and inline panel

**Files:**
- Modify: `frontend/src/pages/ShiftsPage.tsx`

Changes:
1. New prop: `onJobSubmitted?: (jobId: string) => void`
2. New state: `selectedShiftIds: string[]`, `showAlgorithmPanel: boolean`
3. "שיבוץ אוטומטי" button in section header
4. "בחר הכל / בטל בחירה" links next to the date filters
5. `AlgorithmInlinePanel` rendered between filter row and DataTable when `showAlgorithmPanel` is true
6. Checkbox column added as first column in DataTable

- [ ] **Step 3.1: Add imports and update `ShiftsContent` signature**

At the top of `frontend/src/pages/ShiftsPage.tsx`, add the new import:

```ts
import AlgorithmInlinePanel from "../components/AlgorithmInlinePanel";
```

Change the `ShiftsContent` function signature (line 228):

```ts
// Before:
export function ShiftsContent() {

// After:
export function ShiftsContent({ onJobSubmitted }: { onJobSubmitted?: (jobId: string) => void } = {}) {
```

- [ ] **Step 3.2: Add new state variables**

Inside `ShiftsContent`, after the existing state declarations (after `editAssignmentsShift` state, around line 237), add:

```ts
const [selectedShiftIds, setSelectedShiftIds] = useState<string[]>([]);
const [showAlgorithmPanel, setShowAlgorithmPanel] = useState(false);
```

- [ ] **Step 3.3: Update the section header row**

Replace the section header `div` (lines 282–293, the `flex flex-wrap justify-between` div) with:

```tsx
<div className="flex flex-wrap justify-between items-center gap-2">
  <h2 className="text-xl font-semibold">{t("shifts.title")}</h2>
  <div className="flex flex-wrap gap-2">
    <button
      type="button"
      onClick={() => setShowAlgorithmPanel(p => !p)}
      className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
        showAlgorithmPanel
          ? "bg-indigo-600 text-white hover:bg-indigo-700"
          : "bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-200 dark:hover:bg-indigo-800"
      }`}
    >
      שיבוץ אוטומטי
    </button>
    <button
      type="button"
      onClick={() => setShowCreate(true)}
      className="bg-blue-600 text-white px-3 py-1 rounded text-sm hover:bg-blue-700"
    >
      {t("shifts.create")}
    </button>
  </div>
</div>
```

- [ ] **Step 3.4: Add select-all controls next to date filters**

Replace the filter row `div` (lines 295–304, the `flex flex-wrap gap-x-4 gap-y-2` div) with:

```tsx
<div className="flex flex-wrap gap-x-4 gap-y-2 items-center text-sm">
  <label className="flex items-center gap-2">
    {t("shifts.filter_from")}
    <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
  </label>
  <label className="flex items-center gap-2">
    {t("shifts.filter_to")}
    <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="border rounded p-1 dark:bg-gray-700 dark:border-gray-600 dark:text-gray-100" />
  </label>
  {shifts.length > 0 && (
    <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
      <button
        type="button"
        onClick={() => setSelectedShiftIds(shifts.map(s => s.id))}
        className="text-blue-600 dark:text-blue-400 hover:underline"
      >
        בחר הכל ({shifts.length})
      </button>
      {selectedShiftIds.length > 0 && (
        <>
          <span>·</span>
          <button
            type="button"
            onClick={() => setSelectedShiftIds([])}
            className="text-blue-600 dark:text-blue-400 hover:underline"
          >
            בטל בחירה
          </button>
          <span className="text-indigo-600 dark:text-indigo-400 font-medium">
            {selectedShiftIds.length} נבחרו
          </span>
        </>
      )}
    </div>
  )}
</div>
```

- [ ] **Step 3.5: Insert AlgorithmInlinePanel and checkbox column**

Inside the IIFE that builds `shiftCols` and renders the DataTable (lines 306–438), make these two changes:

**A) Add AlgorithmInlinePanel before the DataTable return:**

Immediately before `return (` in the IIFE, add:

```tsx
const algorithmPanel = showAlgorithmPanel ? (
  <AlgorithmInlinePanel
    selectedShiftIds={selectedShiftIds}
    dutyTypes={dutyTypes}
    onJobSubmitted={(jobId) => {
      onJobSubmitted?.(jobId);
      setShowAlgorithmPanel(false);
      setSelectedShiftIds([]);
    }}
    onClose={() => setShowAlgorithmPanel(false)}
  />
) : null;
```

**B) Add checkbox column as the first entry in `shiftCols`:**

Change `const shiftCols: ColDef<DutyShift>[] = [` to:

```ts
const shiftCols: ColDef<DutyShift>[] = [
  {
    id: "select",
    header: "",
    cell: (s) => (
      <input
        type="checkbox"
        checked={selectedShiftIds.includes(s.id)}
        onChange={() =>
          setSelectedShiftIds(prev =>
            prev.includes(s.id) ? prev.filter(id => id !== s.id) : [...prev, s.id]
          )
        }
        onClick={e => e.stopPropagation()}
        aria-label="בחר משמרת"
      />
    ),
  },
  {
    id: "duty_type",
    // ... rest of existing columns unchanged
```

**C) Update the return inside the IIFE to render the panel above the DataTable:**

```tsx
return (
  <>
    {algorithmPanel}
    <DataTable
      columns={shiftCols}
      data={shifts}
      rowClassName={(s) => s.status === "cancelled" ? "opacity-50" : ""}
      filterPlaceholder={t("table.filter_placeholder")}
      emptyMessage="אין משמרות"
    />
  </>
);
```

- [ ] **Step 3.6: Full updated IIFE block**

The entire `{(() => { ... })()}` block inside `ShiftsContent`'s `<section>` should become:

```tsx
{(() => {
  const algorithmPanel = showAlgorithmPanel ? (
    <AlgorithmInlinePanel
      selectedShiftIds={selectedShiftIds}
      dutyTypes={dutyTypes}
      onJobSubmitted={(jobId) => {
        onJobSubmitted?.(jobId);
        setShowAlgorithmPanel(false);
        setSelectedShiftIds([]);
      }}
      onClose={() => setShowAlgorithmPanel(false)}
    />
  ) : null;

  const shiftCols: ColDef<DutyShift>[] = [
    {
      id: "select",
      header: "",
      cell: (s) => (
        <input
          type="checkbox"
          checked={selectedShiftIds.includes(s.id)}
          onChange={() =>
            setSelectedShiftIds(prev =>
              prev.includes(s.id) ? prev.filter(id => id !== s.id) : [...prev, s.id]
            )
          }
          onClick={e => e.stopPropagation()}
          aria-label="בחר משמרת"
        />
      ),
    },
    {
      id: "duty_type",
      header: t("shifts.duty_type"),
      cell: (s) => dtName(s.duty_type_id),
      sortValue: (s) => dtName(s.duty_type_id),
      filterValue: (s) => dtName(s.duty_type_id),
    },
    {
      id: "location",
      header: t("shifts.location"),
      cell: (s) => locName(s.duty_location_id),
      sortValue: (s) => locName(s.duty_location_id),
      filterValue: (s) => locName(s.duty_location_id),
    },
    {
      id: "start_date",
      header: t("shifts.start_date"),
      cell: (s) => s.start_date,
      sortValue: (s) => s.start_date,
    },
    {
      id: "end_date",
      header: t("shifts.end_date"),
      cell: (s) => s.end_date,
      sortValue: (s) => s.end_date,
    },
    {
      id: "required",
      header: t("shifts.required_count"),
      cell: (s) => s.required_count,
      sortValue: (s) => s.required_count,
    },
    {
      id: "assigned",
      header: t("shifts.assigned_count"),
      cell: (s) => (s.assigned_count ?? 0) - (s.reserve_assigned_count ?? 0),
      sortValue: (s) => (s.assigned_count ?? 0) - (s.reserve_assigned_count ?? 0),
    },
    {
      id: "reserve_needed",
      header: t("shifts.reserve_needed"),
      cell: (s) => s.calculated_reserve_count ?? 0,
      sortValue: (s) => s.calculated_reserve_count ?? 0,
    },
    {
      id: "reserve_assigned",
      header: t("shifts.reserve_assigned"),
      cell: (s) => s.reserve_assigned_count ?? 0,
      sortValue: (s) => s.reserve_assigned_count ?? 0,
    },
    {
      id: "fill_status",
      header: t("shifts.status"),
      cell: (s) => (
        <span className={`px-2 py-0.5 rounded text-xs font-medium ${FILL_COLORS[s.fill_status]}`}>
          {t(`shifts.fill_${s.fill_status}`)}
        </span>
      ),
      sortValue: (s) => s.fill_status,
      filterValue: (s) => t(`shifts.fill_${s.fill_status}`),
    },
    {
      id: "shift_status",
      header: t("shifts.shift_status"),
      cell: (s) => s.status === "cancelled"
        ? <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-200 dark:bg-gray-700 text-gray-500 dark:text-gray-400">{t("shifts.cancelled")}</span>
        : null,
      sortValue: (s) => s.status,
      filterValue: (s) => s.status === "cancelled" ? t("shifts.cancelled") : t("shifts.active"),
    },
    {
      id: "actions",
      header: t("shifts.actions"),
      cell: (s) => (
        <span className="flex flex-wrap gap-1 items-center">
          <button
            type="button"
            onClick={() => setEditShift(s)}
            className="px-2 py-1 rounded text-xs font-medium bg-blue-100 dark:bg-blue-900/40 text-blue-800 dark:text-blue-300 hover:bg-blue-200 dark:hover:bg-blue-800"
          >
            ✏️ {t("shifts.edit")}
          </button>
          {s.status === "active" && (
            <button
              type="button"
              onClick={() => setEditAssignmentsShift(s)}
              className="px-2 py-1 rounded text-xs font-medium bg-indigo-100 dark:bg-indigo-900/40 text-indigo-800 dark:text-indigo-300 hover:bg-indigo-200 dark:hover:bg-indigo-800"
            >
              🛠️ ערוך שיבוצים
            </button>
          )}
          {s.status === "cancelled" ? (
            <button
              type="button"
              onClick={() => handleActivate(s)}
              className="px-2 py-1 rounded text-xs font-medium bg-green-100 dark:bg-green-900/40 text-green-800 dark:text-green-300 hover:bg-green-200 dark:hover:bg-green-800"
            >
              ▶️ {t("shifts.activate")}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => handleCancel(s)}
              className="px-2 py-1 rounded text-xs font-medium bg-amber-500 text-white hover:bg-amber-600 dark:bg-amber-600 dark:hover:bg-amber-700"
            >
              🚫 {t("shifts.cancel")}
            </button>
          )}
          <button
            type="button"
            onClick={() => handleDelete(s)}
            className="px-2 py-1 rounded text-xs font-medium bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300 hover:bg-red-200 dark:hover:bg-red-800 disabled:opacity-40"
            disabled={s.assigned_count > 0}
            title={t("shifts.delete_tooltip")}
          >
            🗑️ {t("shifts.delete")}
          </button>
        </span>
      ),
    },
  ];
  return (
    <>
      {algorithmPanel}
      <DataTable
        columns={shiftCols}
        data={shifts}
        rowClassName={(s) => s.status === "cancelled" ? "opacity-50" : ""}
        filterPlaceholder={t("table.filter_placeholder")}
        emptyMessage="אין משמרות"
      />
    </>
  );
})()}
```

- [ ] **Step 3.7: Run lint**

```bash
cd frontend && npm run lint
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 3.8: Run frontend tests**

```bash
cd frontend && npm test
```

Expected: all tests PASS.

- [ ] **Step 3.9: Commit**

```bash
git add frontend/src/pages/ShiftsPage.tsx
git commit -m "feat: add checkboxes, algorithm panel button to ShiftsContent"
```

---

## Task 4: Update `ShiftsManagementPage` with algorithm runs collapsible

**Files:**
- Modify: `frontend/src/pages/planning/ShiftsManagementPage.tsx`

Changes:
- Add `runsOpen: boolean` and `latestJobId: string | null` state
- Add "ריצות אלגוריתם" collapsible section above `<ShiftsContent>`
- Add `handleJobSubmitted` that sets `latestJobId` and opens the section
- Wire `onJobSubmitted` prop into `<ShiftsContent>`
- Import `AlgorithmContent`

- [ ] **Step 4.1: Rewrite `ShiftsManagementPage`**

Replace the entire content of `frontend/src/pages/planning/ShiftsManagementPage.tsx` with:

```tsx
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import { ShiftsContent } from "../ShiftsPage";
import { ShiftTemplatesContent } from "../ShiftTemplatesPage";
import { AlgorithmContent } from "../AlgorithmPage";

export default function ShiftsManagementPage() {
  const { t } = useTranslation();
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [runsOpen, setRunsOpen] = useState(false);
  const [latestJobId, setLatestJobId] = useState<string | null>(null);
  const runsRef = useRef<HTMLElement | null>(null);

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
            <span className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 text-sm px-2 py-1">
              {runsOpen ? "▲" : "▼"}
            </span>
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

- [ ] **Step 4.2: Run lint**

```bash
cd frontend && npm run lint
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 4.3: Run frontend tests**

```bash
cd frontend && npm test
```

Expected: all tests PASS.

- [ ] **Step 4.4: Commit**

```bash
git add frontend/src/pages/planning/ShiftsManagementPage.tsx
git commit -m "feat: add algorithm runs collapsible to ShiftsManagementPage"
```

---

## Task 5: Remove the Assignment Page

**Files:**
- Delete: `frontend/src/pages/planning/AssignmentPage.tsx`
- Modify: `frontend/src/App.tsx` — remove `/planning/assignment` route, fix redirects
- Modify: `frontend/src/components/UnifiedNav.tsx` — remove "שיבוץ" nav item

- [ ] **Step 5.1: Delete `AssignmentPage.tsx`**

```bash
Remove-Item frontend/src/pages/planning/AssignmentPage.tsx
```

- [ ] **Step 5.2: Update `App.tsx`**

Remove the import at the top:
```ts
// DELETE this line:
import AssignmentPage from "./pages/planning/AssignmentPage";
```

Remove the route (inside the `<Route element={<ProtectedRoute />}>` block):
```tsx
// DELETE this line:
<Route path="/planning/assignment" element={<AppGate><AssignmentPage /></AppGate>} />
```

Change the existing `/duty-management` and `/algorithm` redirects:
```tsx
// Before:
<Route path="/duty-management" element={<Navigate to="/planning/assignment" replace />} />
<Route path="/algorithm" element={<Navigate to="/planning/assignment?tab=1" replace />} />

// After:
<Route path="/duty-management" element={<Navigate to="/planning/shifts" replace />} />
<Route path="/algorithm" element={<Navigate to="/planning/shifts" replace />} />
```

Add a redirect for the deleted page itself:
```tsx
<Route path="/planning/assignment" element={<Navigate to="/planning/shifts" replace />} />
```

- [ ] **Step 5.3: Update `UnifiedNav.tsx`**

In the `planningItems` array (around line 111), remove the assignment nav item:

```ts
// Before:
const planningItems = [
  { label: t("nav.planning_shifts"), to: "/planning/shifts", testId: "nav-shifts-management" },
  { label: t("nav.planning_assignment"), to: "/planning/assignment", testId: "nav-assignment" },
  { label: t("nav.planning_config"), to: "/planning/config", testId: "nav-duty-config" },
  { label: "ייבוא מ-Excel", to: "/import", testId: "nav-import" },
];

// After:
const planningItems = [
  { label: t("nav.planning_shifts"), to: "/planning/shifts", testId: "nav-shifts-management" },
  { label: t("nav.planning_config"), to: "/planning/config", testId: "nav-duty-config" },
  { label: "ייבוא מ-Excel", to: "/import", testId: "nav-import" },
];
```

- [ ] **Step 5.4: Run lint**

```bash
cd frontend && npm run lint
```

Expected: 0 errors, 0 warnings. (No remaining references to AssignmentPage.)

- [ ] **Step 5.5: Run all frontend tests**

```bash
cd frontend && npm test
```

Expected: all tests PASS. (The UnifiedNav tests may reference `nav-assignment` — update if needed.)

If `UnifiedNav.test.tsx` has a test checking for the assignment nav item, remove or update it to verify the item is gone:
```ts
// If this assertion exists, replace it:
expect(screen.getByTestId("nav-assignment")).toBeInTheDocument();

// With (verify it's absent):
expect(screen.queryByTestId("nav-assignment")).not.toBeInTheDocument();
```

- [ ] **Step 5.6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/UnifiedNav.tsx
git commit -m "feat: remove assignment page, redirect /planning/assignment to /planning/shifts"
```

---

## Testing Checklist

After all tasks are complete, manually verify:

- [ ] Checkboxes appear in the first column of the shifts DataTable
- [ ] "בחר הכל" selects all loaded shifts; "בטל בחירה" clears all
- [ ] "שיבוץ אוטומטי" button toggles the inline panel; button style changes when active
- [ ] Inline panel shows "X משמרות נבחרות" that updates live
- [ ] Run button is disabled when 0 shifts selected, enabled otherwise
- [ ] Submitting a run closes the panel, clears selections, opens "ריצות אלגוריתם" section, auto-selects the new job
- [ ] "ריצות אלגוריתם" section polls and updates in real time
- [ ] Navigating to `/planning/assignment` redirects to `/planning/shifts`
- [ ] Navigating to `/algorithm` or `/duty-management` redirects to `/planning/shifts`
- [ ] "שיבוץ" nav item is gone from the planning dropdown
- [ ] Re-run from within the job detail (via "New Run" button) still works
