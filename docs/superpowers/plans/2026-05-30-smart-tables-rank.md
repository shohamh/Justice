# Smart Tables & Soldier Rank Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-slot and cross-batch rank columns to the algorithm proposals table, and replace all plain data tables in the app with a sortable/filterable TanStack Table v8 wrapper.

**Architecture:** A generic `DataTable<T>` component wraps TanStack Table v8 (headless), owns sort/filter state, and renders Tailwind-styled markup. Each call site passes typed column defs and data; the component is a drop-in for the six existing plain tables. The backend gets a `_compute_candidate_rank` helper that is called inside `_proposals_for_job` to enrich each proposal with per-slot rank data.

**Tech Stack:** Python/FastAPI (backend), React 18 + TypeScript + TanStack Table v8 + Tailwind CSS (frontend), vitest + @testing-library/react (tests), pnpm.

---

## File Map

| File | Change |
|---|---|
| `backend/app/routes/algorithm.py` | Add `_compute_candidate_rank`, two new fields on `ProposalOut`, call in `_proposals_for_job` |
| `backend/app/routes/tests/test_candidate_rank.py` | New — unit tests for `_compute_candidate_rank` |
| `frontend/src/api/algorithm.ts` | Add `candidate_rank`, `candidate_pool_size` to `ProposalRow` |
| `frontend/src/components/DataTable.tsx` | New — generic sortable/filterable table component |
| `frontend/src/components/DataTable.test.tsx` | New — vitest tests for DataTable |
| `frontend/src/i18n/he.json` | Add `algorithm.col_slot_rank`, `algorithm.col_batch_rank`, `table.filter_placeholder` |
| `frontend/src/components/AlgorithmPlanningWindow.tsx` | Replace plain proposals table with DataTable + add rank columns |
| `frontend/src/components/ExplanationModal.tsx` | Replace plain candidates table with DataTable |
| `frontend/src/pages/ShiftsPage.tsx` | Replace plain shifts table with DataTable |
| `frontend/src/pages/TeamHierarchyPage.tsx` | Replace manual sort + plain table with DataTable |
| `frontend/src/pages/MyDutiesPage.tsx` | Replace plain duties table with DataTable |
| `frontend/src/pages/TransparencyPage.tsx` | Replace plain transparency table with DataTable |

---

### Task 1: Backend — `_compute_candidate_rank` + enrich `ProposalOut`

**Files:**
- Modify: `backend/app/routes/algorithm.py`
- Create: `backend/app/routes/tests/test_candidate_rank.py`

- [ ] **Step 1: Create the test file**

```python
# backend/app/routes/tests/test_candidate_rank.py
from __future__ import annotations

from app.routes.algorithm import _compute_candidate_rank


def test_assigned_soldier_is_rank_1_when_lowest_score() -> None:
    candidates = [
        {"soldier_id": "a", "blocked": False, "pre_norm_score": 0.5},
        {"soldier_id": "b", "blocked": False, "pre_norm_score": 1.0},
        {"soldier_id": "c", "blocked": True,  "pre_norm_score": 0.1},  # excluded
    ]
    rank, pool = _compute_candidate_rank(candidates, "a")
    assert rank == 1
    assert pool == 2


def test_second_lowest_score_is_rank_2() -> None:
    candidates = [
        {"soldier_id": "a", "blocked": False, "pre_norm_score": 2.0},
        {"soldier_id": "b", "blocked": False, "pre_norm_score": 1.0},
        {"soldier_id": "c", "blocked": False, "pre_norm_score": 3.0},
    ]
    rank, pool = _compute_candidate_rank(candidates, "a")
    assert rank == 2
    assert pool == 3


def test_soldier_not_in_unblocked_returns_none_rank() -> None:
    candidates = [
        {"soldier_id": "a", "blocked": False, "pre_norm_score": 1.0},
    ]
    rank, pool = _compute_candidate_rank(candidates, "x")
    assert rank is None
    assert pool == 1


def test_null_score_sorts_last() -> None:
    candidates = [
        {"soldier_id": "a", "blocked": False, "pre_norm_score": None},
        {"soldier_id": "b", "blocked": False, "pre_norm_score": 1.0},
    ]
    rank, pool = _compute_candidate_rank(candidates, "b")
    assert rank == 1
    assert pool == 2


def test_empty_candidates_returns_none() -> None:
    rank, pool = _compute_candidate_rank([], "a")
    assert rank is None
    assert pool == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend
uv run pytest app/routes/tests/test_candidate_rank.py -v
```

Expected: ImportError — `_compute_candidate_rank` does not exist yet.

- [ ] **Step 3: Add `_compute_candidate_rank` to `algorithm.py` and update `ProposalOut`**

Open `backend/app/routes/algorithm.py`. Make the following changes:

**3a.** Add the helper function near the top of the file, after the imports and before `ProposalOut`:

```python
def _compute_candidate_rank(
    candidates: list[dict],
    soldier_id: str,
) -> tuple[int | None, int | None]:
    """Return (1-based rank, pool_size) for soldier among unblocked candidates sorted by pre_norm_score asc."""
    unblocked = [c for c in candidates if not c.get("blocked")]
    pool_size = len(unblocked)
    if pool_size == 0:
        return None, 0
    sorted_unblocked = sorted(
        unblocked,
        key=lambda c: c.get("pre_norm_score") if c.get("pre_norm_score") is not None else float("inf"),
    )
    for i, c in enumerate(sorted_unblocked):
        if c["soldier_id"] == soldier_id:
            return i + 1, pool_size
    return None, pool_size
```

**3b.** Add two fields to `ProposalOut` (after `norm_score_after`):

```python
class ProposalOut(BaseModel):
    assignment_id: uuid.UUID
    soldier_id: uuid.UUID
    duty_type_id: uuid.UUID
    duty_location_id: uuid.UUID
    start_date: date
    end_date: date
    status: str
    reserve_soldier_id: uuid.UUID | None
    norm_score_before: float | None
    norm_score_after: float | None
    duty_shift_id: uuid.UUID | None = None
    candidate_rank: int | None = None
    candidate_pool_size: int | None = None
```

**3c.** In `_proposals_for_job`, replace the existing inner loop that finds `norm_before`/`norm_after` with:

```python
    proposals = []
    for a in rows:
        exp = exp_map.get(a.id)
        norm_before = None
        norm_after = None
        candidate_rank = None
        candidate_pool_size = None
        if exp:
            payload = exp.payload
            candidates = payload.get("candidates", [])
            for c in candidates:
                if c["soldier_id"] == str(a.soldier_id) and not c.get("blocked"):
                    norm_before = c.get("pre_norm_score")
                    norm_after = c.get("post_norm_score")
                    break
            candidate_rank, candidate_pool_size = _compute_candidate_rank(candidates, str(a.soldier_id))
        proposals.append(ProposalOut(
            assignment_id=a.id,
            soldier_id=a.soldier_id,
            duty_type_id=a.duty_type_id,
            duty_location_id=a.duty_location_id,
            start_date=a.start_date,
            end_date=a.end_date,
            status=a.status,
            reserve_soldier_id=reserve_map.get(a.id),
            norm_score_before=norm_before,
            norm_score_after=norm_after,
            duty_shift_id=a.duty_shift_id,
            candidate_rank=candidate_rank,
            candidate_pool_size=candidate_pool_size,
        ))
    return proposals
```

- [ ] **Step 4: Run tests — expect PASS**

```
uv run pytest app/routes/tests/test_candidate_rank.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```
git add backend/app/routes/algorithm.py backend/app/routes/tests/test_candidate_rank.py
git commit -m "feat(backend): add candidate_rank and candidate_pool_size to ProposalOut"
```

---

### Task 2: Frontend types

**Files:**
- Modify: `frontend/src/api/algorithm.ts`

- [ ] **Step 1: Add fields to `ProposalRow`**

In `frontend/src/api/algorithm.ts`, update `ProposalRow`:

```typescript
export interface ProposalRow {
  assignment_id: string;
  soldier_id: string;
  duty_type_id: string;
  duty_location_id: string;
  start_date: string;
  end_date: string;
  status: string;
  reserve_soldier_id: string | null;
  norm_score_before: number | null;
  norm_score_after: number | null;
  duty_shift_id: string | null;
  candidate_rank: number | null;
  candidate_pool_size: number | null;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```
git add frontend/src/api/algorithm.ts
git commit -m "feat(types): add candidate_rank and candidate_pool_size to ProposalRow"
```

---

### Task 3: Install TanStack Table and build `DataTable<T>`

**Files:**
- Create: `frontend/src/components/DataTable.tsx`
- Create: `frontend/src/components/DataTable.test.tsx`

- [ ] **Step 1: Install the package**

```
cd frontend && pnpm add @tanstack/react-table
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/components/DataTable.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { DataTable, type ColDef } from "./DataTable";

interface Row { name: string; score: number; }

const cols: ColDef<Row>[] = [
  {
    id: "name",
    header: "Name",
    cell: (r) => r.name,
    sortValue: (r) => r.name,
    filterValue: (r) => r.name,
  },
  {
    id: "score",
    header: "Score",
    cell: (r) => String(r.score),
    sortValue: (r) => r.score,
  },
];

const data: Row[] = [
  { name: "Alice", score: 3 },
  { name: "Bob", score: 1 },
  { name: "Charlie", score: 2 },
];

test("renders all rows", () => {
  render(<DataTable columns={cols} data={data} />);
  expect(screen.getByText("Alice")).toBeInTheDocument();
  expect(screen.getByText("Bob")).toBeInTheDocument();
  expect(screen.getByText("Charlie")).toBeInTheDocument();
});

test("filters rows by global filter text", () => {
  render(<DataTable columns={cols} data={data} />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Alice" } });
  expect(screen.getByText("Alice")).toBeInTheDocument();
  expect(screen.queryByText("Bob")).not.toBeInTheDocument();
  expect(screen.queryByText("Charlie")).not.toBeInTheDocument();
});

test("sorts ascending on header click", () => {
  const { container } = render(<DataTable columns={cols} data={data} />);
  fireEvent.click(screen.getByText("Score"));
  const rows = container.querySelectorAll("tbody tr");
  expect(rows[0].textContent).toContain("Bob");   // score 1
  expect(rows[1].textContent).toContain("Charlie"); // score 2
  expect(rows[2].textContent).toContain("Alice");   // score 3
});

test("sorts descending on second header click", () => {
  const { container } = render(<DataTable columns={cols} data={data} />);
  fireEvent.click(screen.getByText("Score"));
  fireEvent.click(screen.getByText("Score"));
  const rows = container.querySelectorAll("tbody tr");
  expect(rows[0].textContent).toContain("Alice");  // score 3
});

test("non-sortable column header does not show arrow", () => {
  render(<DataTable columns={[{ id: "x", header: "NoSort", cell: () => "—" }]} data={[]} />);
  const header = screen.getByText("NoSort");
  expect(header.className).not.toContain("cursor-pointer");
});

test("shows empty message when no rows match filter", () => {
  render(<DataTable columns={cols} data={data} emptyMessage="nothing" />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "zzz" } });
  expect(screen.getByText("nothing")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run to verify they fail**

```
cd frontend && pnpm test -- DataTable
```

Expected: fails with module-not-found or similar.

- [ ] **Step 4: Implement `DataTable.tsx`**

Create `frontend/src/components/DataTable.tsx`:

```tsx
import { useMemo, useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  flexRender,
  type ColumnDef as TanColumnDef,
  type SortingState,
  type FilterFn,
} from "@tanstack/react-table";

export interface ColDef<T> {
  id: string;
  header: string;
  cell: (row: T) => React.ReactNode;
  sortValue?: (row: T) => string | number | null | undefined;
  filterValue?: (row: T) => string;
}

interface DataTableProps<T> {
  columns: ColDef<T>[];
  data: T[];
  filterPlaceholder?: string;
  className?: string;
  rowClassName?: (row: T) => string;
  emptyMessage?: string;
}

export function DataTable<T>({
  columns,
  data,
  filterPlaceholder = "סנן...",
  className,
  rowClassName,
  emptyMessage = "—",
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [globalFilter, setGlobalFilter] = useState("");

  const globalFilterFn: FilterFn<T> = useMemo(() => {
    const fn: FilterFn<T> = (row, columnId, value: string) => {
      const col = columns.find((c) => c.id === columnId);
      if (!col?.filterValue) return false;
      return col.filterValue(row.original).toLowerCase().includes(value.toLowerCase());
    };
    fn.autoRemove = (val: unknown) => !val;
    return fn;
  }, [columns]);

  const tanCols: TanColumnDef<T>[] = useMemo(
    () =>
      columns.map((col) => ({
        id: col.id,
        header: col.header,
        cell: ({ row }) => col.cell(row.original),
        enableSorting: !!col.sortValue,
        enableGlobalFilter: !!col.filterValue,
        sortingFn: col.sortValue
          ? (rowA, rowB) => {
              const a = col.sortValue!(rowA.original) ?? null;
              const b = col.sortValue!(rowB.original) ?? null;
              if (a === null && b === null) return 0;
              if (a === null) return 1;
              if (b === null) return -1;
              if (typeof a === "string" && typeof b === "string")
                return a.localeCompare(b, "he");
              return (a as number) < (b as number) ? -1 : (a as number) > (b as number) ? 1 : 0;
            }
          : "auto",
      })),
    [columns]
  );

  const table = useReactTable({
    data,
    columns: tanCols,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    globalFilterFn,
  });

  return (
    <div className={className}>
      <input
        value={globalFilter}
        onChange={(e) => setGlobalFilter(e.target.value)}
        placeholder={filterPlaceholder}
        className="mb-2 border rounded p-1 text-sm w-full sm:w-64"
      />
      <table className="w-full text-xs border-collapse">
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id} className="bg-gray-100 text-right">
              {hg.headers.map((header) => (
                <th
                  key={header.id}
                  className={`border px-2 py-1 whitespace-nowrap${header.column.getCanSort() ? " cursor-pointer select-none" : ""}`}
                  onClick={header.column.getToggleSortingHandler()}
                >
                  {flexRender(header.column.columnDef.header, header.getContext())}
                  {header.column.getIsSorted() === "asc" && " ▲"}
                  {header.column.getIsSorted() === "desc" && " ▼"}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="text-center text-gray-400 py-4">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className={rowClassName ? rowClassName(row.original) : undefined}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="border px-2 py-1">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 5: Run tests — expect PASS**

```
cd frontend && pnpm test -- DataTable
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```
git add frontend/src/components/DataTable.tsx frontend/src/components/DataTable.test.tsx
git commit -m "feat(ui): DataTable generic sortable/filterable component using TanStack Table v8"
```

---

### Task 4: i18n keys

**Files:**
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Add keys**

In `frontend/src/i18n/he.json`:

**Under `"algorithm"` object**, add after `"no_proposals"`:
```json
"col_slot_rank": "דירוג במשמרת",
"col_batch_rank": "דירוג כולל"
```

**At the root level of the JSON**, add a new `"table"` key (before the closing `}`):
```json
"table": {
  "filter_placeholder": "סנן..."
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 3: Commit**

```
git add frontend/src/i18n/he.json
git commit -m "i18n: add rank column keys and table filter placeholder"
```

---

### Task 5: Migrate AlgorithmPlanningWindow proposals table

**Files:**
- Modify: `frontend/src/components/AlgorithmPlanningWindow.tsx`

- [ ] **Step 1: Replace the proposals table**

Replace the entire `<table>...</table>` block inside `{job?.status === "done" && (...)}` (currently lines 255–299) with the following. Also add the `DataTable` import and `ColDef` import at the top of the file.

**Import addition** (add to existing imports):
```typescript
import { DataTable, type ColDef } from "./DataTable";
```

**Batch rank helper** (add inside the component body, before the `return`):
```typescript
const batchRankMap = useMemo(() => {
  if (!job?.proposals) return new Map<string, number>();
  const sorted = [...job.proposals]
    .filter((p) => p.norm_score_before !== null)
    .sort((a, b) => (a.norm_score_before ?? Infinity) - (b.norm_score_before ?? Infinity));
  const map = new Map<string, number>();
  sorted.forEach((p, i) => map.set(p.assignment_id, i + 1));
  return map;
}, [job?.proposals]);
```

Also add `useMemo` to the React import at the top of the file.

**Replace the proposals `<table>` block** with:
```tsx
{job?.status === "done" && (
  <div>
    <p className="font-medium text-sm mb-2">{t("algorithm.done")}</p>
    {job.proposals.length === 0 ? (
      <p className="text-gray-500 text-sm">{t("algorithm.no_proposals")}</p>
    ) : (() => {
      const proposalCols: ColDef<ProposalRow>[] = [
        {
          id: "date",
          header: t("algorithm.col_date"),
          cell: (p) => p.start_date,
          sortValue: (p) => p.start_date,
        },
        {
          id: "type",
          header: t("algorithm.col_type"),
          cell: (p) => typeName(p.duty_type_id),
          sortValue: (p) => typeName(p.duty_type_id),
          filterValue: (p) => typeName(p.duty_type_id),
        },
        {
          id: "soldier",
          header: t("algorithm.col_soldier"),
          cell: (p) => soldierName(p.soldier_id),
          sortValue: (p) => soldierName(p.soldier_id),
          filterValue: (p) => soldierName(p.soldier_id),
        },
        {
          id: "reserve",
          header: t("algorithm.col_reserve"),
          cell: (p) => p.reserve_soldier_id ? soldierName(p.reserve_soldier_id) : "—",
        },
        {
          id: "score_before",
          header: t("algorithm.col_score_before"),
          cell: (p) => p.norm_score_before?.toFixed(3) ?? "—",
          sortValue: (p) => p.norm_score_before ?? null,
        },
        {
          id: "score_after",
          header: t("algorithm.col_score_after"),
          cell: (p) => p.norm_score_after?.toFixed(3) ?? "—",
          sortValue: (p) => p.norm_score_after ?? null,
        },
        {
          id: "batch_rank",
          header: t("algorithm.col_batch_rank"),
          cell: (p) => batchRankMap.get(p.assignment_id)?.toString() ?? "—",
          sortValue: (p) => batchRankMap.get(p.assignment_id) ?? null,
        },
        {
          id: "slot_rank",
          header: t("algorithm.col_slot_rank"),
          cell: (p) =>
            p.candidate_rank !== null && p.candidate_rank !== undefined && p.candidate_pool_size
              ? `${p.candidate_rank} / ${p.candidate_pool_size}`
              : "—",
          sortValue: (p) => p.candidate_rank ?? null,
        },
        {
          id: "actions",
          header: t("algorithm.col_actions"),
          cell: (p) => {
            const isAccepted = p.status === "published";
            const isRejected = p.status === "algorithm_rejected";
            return (
              <span className="space-x-1 space-x-reverse">
                {!isAccepted && !isRejected && (
                  <>
                    <button type="button" onClick={() => handleAccept(p)} className="text-green-700 font-bold hover:underline">{t("algorithm.accept")}</button>{" "}
                    <button type="button" onClick={() => handleReject(p)} className="text-red-700 hover:underline">{t("algorithm.reject")}</button>{" "}
                  </>
                )}
                {jobId && (
                  <button type="button" onClick={() => setExplanationTarget({ jobId, assignmentId: p.assignment_id })} className="text-blue-600 hover:underline">
                    {t("algorithm.why_button")}
                  </button>
                )}
              </span>
            );
          },
        },
      ];
      return (
        <DataTable
          columns={proposalCols}
          data={job.proposals}
          filterPlaceholder={t("table.filter_placeholder")}
          rowClassName={(p) =>
            p.status === "published" ? "bg-green-50" : p.status === "algorithm_rejected" ? "bg-gray-100 opacity-50" : ""
          }
        />
      );
    })()}
  </div>
)}
```

- [ ] **Step 2: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 3: Commit**

```
git add frontend/src/components/AlgorithmPlanningWindow.tsx
git commit -m "feat(ui): proposals table uses DataTable with slot+batch rank columns"
```

---

### Task 6: Migrate ExplanationModal candidates table

**Files:**
- Modify: `frontend/src/components/ExplanationModal.tsx`

- [ ] **Step 1: Replace the candidates table**

At the top of the file, add the import:
```typescript
import { DataTable, type ColDef } from "./DataTable";
```

Also add the `CandidateInfo` type import — check `frontend/src/api/algorithm.ts` for the type name. Looking at existing usage, the type in `DmExplanation` is `candidates: CandidateInfo[]`. Import it:
```typescript
import {
  DmExplanation,
  SoldierExplanation,
  getExplanation,
  getExplanationByAssignment,
  type CandidateInfo,
} from "../api/algorithm";
```

Replace the entire `<table>...</table>` block inside the `isDmExplanation` branch (currently lines 97–126) with:

```tsx
{(() => {
  const candidateCols: ColDef<CandidateInfo>[] = [
    {
      id: "name",
      header: "חייל",
      cell: (c) => c.soldier_name || c.soldier_id.slice(0, 8),
      sortValue: (c) => c.soldier_name || c.soldier_id,
      filterValue: (c) => c.soldier_name || c.soldier_id,
    },
    {
      id: "blocked",
      header: "חסום?",
      cell: (c) => (c.blocked ? "✗" : "✓"),
      sortValue: (c) => (c.blocked ? 1 : 0),
    },
    {
      id: "reason",
      header: "סיבה",
      cell: (c) =>
        c.blocking_constraints.map((k) => t(`algorithm.constraint_${k}`, k)).join(", "),
    },
    {
      id: "norm_before",
      header: t("algorithm.norm_before"),
      cell: (c) => c.pre_norm_score?.toFixed(3) ?? "—",
      sortValue: (c) => c.pre_norm_score ?? null,
    },
    {
      id: "norm_after",
      header: t("algorithm.norm_after"),
      cell: (c) => c.post_norm_score?.toFixed(3) ?? "—",
      sortValue: (c) => c.post_norm_score ?? null,
    },
  ];
  return (
    <DataTable
      columns={candidateCols}
      data={data.candidates}
      filterPlaceholder={t("table.filter_placeholder")}
      rowClassName={(c) => (c.blocked ? "bg-red-50" : "bg-green-50")}
    />
  );
})()}
```

- [ ] **Step 2: Verify `CandidateInfo` is exported from `algorithm.ts`**

Open `frontend/src/api/algorithm.ts` and confirm `CandidateInfo` is exported. If it is not, add:
```typescript
export interface CandidateInfo {
  soldier_id: string;
  soldier_name: string | null;
  blocked: boolean;
  blocking_constraints: string[];
  pre_norm_score: number | null;
  post_norm_score: number | null;
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 4: Commit**

```
git add frontend/src/components/ExplanationModal.tsx frontend/src/api/algorithm.ts
git commit -m "feat(ui): explanation candidates table uses DataTable"
```

---

### Task 7: Migrate ShiftsPage

**Files:**
- Modify: `frontend/src/pages/ShiftsPage.tsx`

- [ ] **Step 1: Replace the shifts table**

Add import at the top of the file:
```typescript
import { DataTable, type ColDef } from "../components/DataTable";
```

Replace the entire `<table>...</table>` block (lines 76–126) with:

```tsx
{(() => {
  const shiftCols: ColDef<DutyShift>[] = [
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
      cell: (s) => s.assigned_count,
      sortValue: (s) => s.assigned_count,
    },
    {
      id: "status",
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
      id: "actions",
      header: t("shifts.actions"),
      cell: (s) => (
        <span className="space-x-2 space-x-reverse">
          <button
            type="button"
            onClick={() => setEditShift(s)}
            className="text-blue-600 text-xs hover:underline"
          >
            {t("shifts.edit")}
          </button>
          <button
            type="button"
            onClick={() => handleDelete(s)}
            className="text-red-600 text-xs hover:underline"
            disabled={s.assigned_count > 0}
          >
            {t("shifts.delete")}
          </button>
        </span>
      ),
    },
  ];
  return (
    <DataTable
      columns={shiftCols}
      data={shifts}
      filterPlaceholder={t("table.filter_placeholder")}
      emptyMessage="אין משמרות"
    />
  );
})()}
```

- [ ] **Step 2: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 3: Commit**

```
git add frontend/src/pages/ShiftsPage.tsx
git commit -m "feat(ui): shifts table uses DataTable"
```

---

### Task 8: Migrate TeamHierarchyPage

**Files:**
- Modify: `frontend/src/pages/TeamHierarchyPage.tsx`

- [ ] **Step 1: Remove manual sort state and replace table**

**Remove** the following state and functions (lines 24–56 approximately):
- `const [tableSearch, setTableSearch] = useState("");`
- `const [sortKey, setSortKey] = useState<...>("");`
- `const [sortDir, setSortDir] = useState<...>("asc");`
- `function toggleSort(...) {...}`
- `const filteredSoldiers = ...` (manual filter)
- `const sortedSoldiers = ...` (manual sort)

**Remove** the search input block (the `<div className="border rounded p-3">...</div>` containing the search input).

**Add** import at the top:
```typescript
import { DataTable, type ColDef } from "../components/DataTable";
```

**Remove** `useState` for `tableSearch`, `sortKey`, `sortDir` from imports (keep other useState uses).

**Replace** the `<div className="overflow-x-auto">` block and its table (lines 130–164) with:

```tsx
<div className="overflow-x-auto">
  {(() => {
    const soldierCols: ColDef<SoldierDTO>[] = [
      {
        id: "personal_number",
        header: t("team.personal_number"),
        cell: (s) => s.personal_number,
        sortValue: (s) => s.personal_number,
        filterValue: (s) => s.personal_number,
      },
      {
        id: "full_name",
        header: t("team.full_name"),
        cell: (s) => s.full_name,
        sortValue: (s) => s.full_name,
        filterValue: (s) => s.full_name,
      },
      {
        id: "role",
        header: t("team.role"),
        cell: (s) => t(`role.${s.role}`),
        sortValue: (s) => t(`role.${s.role}`),
      },
      {
        id: "node",
        header: t("team.node"),
        cell: (s) => nodes.find((n) => n.id === s.hierarchy_node_id)?.name ?? "—",
        sortValue: (s) => nodes.find((n) => n.id === s.hierarchy_node_id)?.name ?? "",
        filterValue: (s) => nodes.find((n) => n.id === s.hierarchy_node_id)?.name ?? "",
      },
      {
        id: "actions",
        header: "",
        cell: (s) => (
          <span className="space-x-2 space-x-reverse">
            <button onClick={() => setEditSoldier(s)} className="text-indigo-600" data-testid={`edit-${s.personal_number}`}>{t("duty_config.save")}</button>
            <button onClick={() => onReset(s.id)} className="text-indigo-600" data-testid={`reset-${s.personal_number}`}>{t("team.reset_password")}</button>
            <button onClick={() => onRemove(s.id)} className="text-red-600" data-testid={`remove-${s.personal_number}`}>{t("team.remove")}</button>
          </span>
        ),
      },
    ];
    const activeSoldiers = soldiers.filter((s) => !s.left_at);
    return (
      <DataTable
        columns={soldierCols}
        data={activeSoldiers}
        filterPlaceholder={t("team.search_placeholder")}
        emptyMessage={t("team.no_soldiers")}
      />
    );
  })()}
</div>
```

- [ ] **Step 2: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 3: Commit**

```
git add frontend/src/pages/TeamHierarchyPage.tsx
git commit -m "feat(ui): team table uses DataTable, removes manual sort"
```

---

### Task 9: Migrate MyDutiesPage

**Files:**
- Modify: `frontend/src/pages/MyDutiesPage.tsx`

- [ ] **Step 1: Replace the duties table**

Add import at the top:
```typescript
import { DataTable, type ColDef } from "../components/DataTable";
```

Add `EffectiveDuty` is already imported. Replace the entire conditional block `{filteredRows.length === 0 ? (...) : (<table>...</table>)}` with:

```tsx
{filteredRows.length === 0 ? (
  <p data-testid="my-duties-empty">{t("my_duties.none")}</p>
) : (() => {
  const dutyCols: ColDef<EffectiveDuty>[] = [
    {
      id: "duty_type",
      header: t("my_duties.duty_type"),
      cell: (a) => types[a.duty_type_id] ?? a.duty_type_id,
      sortValue: (a) => types[a.duty_type_id] ?? a.duty_type_id,
      filterValue: (a) => types[a.duty_type_id] ?? a.duty_type_id,
    },
    {
      id: "location",
      header: t("my_duties.location"),
      cell: (a) => locs[a.duty_location_id] ?? a.duty_location_id,
      sortValue: (a) => locs[a.duty_location_id] ?? a.duty_location_id,
      filterValue: (a) => locs[a.duty_location_id] ?? a.duty_location_id,
    },
    {
      id: "from",
      header: t("my_duties.from"),
      cell: (a) => a.start_date,
      sortValue: (a) => a.start_date,
    },
    {
      id: "to",
      header: t("my_duties.to"),
      cell: (a) => a.end_date,
      sortValue: (a) => a.end_date,
    },
    {
      id: "why",
      header: "",
      cell: (a) => (
        <button
          type="button"
          onClick={() => setWhyTarget({ assignmentId: a.assignment_id })}
          className="text-xs text-blue-600 underline"
        >
          {t("algorithm.why_button")}
        </button>
      ),
    },
  ];
  return (
    <DataTable
      columns={dutyCols}
      data={filteredRows}
      filterPlaceholder={t("table.filter_placeholder")}
    />
  );
})()}
```

- [ ] **Step 2: Verify TypeScript compiles**

```
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 3: Commit**

```
git add frontend/src/pages/MyDutiesPage.tsx
git commit -m "feat(ui): my duties table uses DataTable"
```

---

### Task 10: Migrate TransparencyPage

**Files:**
- Modify: `frontend/src/pages/TransparencyPage.tsx`

- [ ] **Step 1: Replace the transparency table**

Add import at the top:
```typescript
import { DataTable, type ColDef } from "../components/DataTable";
```

Replace the entire `<table>...</table>` block (lines 26–54) with:

```tsx
{(() => {
  const transCols: ColDef<TransparencyRow>[] = [
    {
      id: "name",
      header: t("transparency.name"),
      cell: (r) =>
        r.soldier_id === user?.id ? (
          <button className="text-indigo-600" onClick={toggleOwn} data-testid="own-row-toggle">
            {r.full_name}
          </button>
        ) : (
          r.full_name
        ),
      sortValue: (r) => r.full_name,
      filterValue: (r) => r.full_name,
    },
    {
      id: "unit",
      header: t("transparency.unit"),
      cell: (r) => r.node_name ?? "—",
      sortValue: (r) => r.node_name ?? "",
      filterValue: (r) => r.node_name ?? "",
    },
    {
      id: "enrolled_at",
      header: t("transparency.enrolled_at"),
      cell: (r) => r.enrolled_at,
      sortValue: (r) => r.enrolled_at,
    },
    {
      id: "active_days",
      header: t("transparency.active_days"),
      cell: (r) => r.active_days,
      sortValue: (r) => r.active_days,
    },
    {
      id: "cumulative",
      header: t("transparency.cumulative"),
      cell: (r) => r.cumulative_score,
      sortValue: (r) => Number(r.cumulative_score),
    },
    {
      id: "normalised",
      header: t("transparency.normalised"),
      cell: (r) => r.normalised_score,
      sortValue: (r) => Number(r.normalised_score),
    },
  ];
  return (
    <DataTable
      columns={transCols}
      data={rows}
      filterPlaceholder={t("table.filter_placeholder")}
      rowClassName={(r) => (r.soldier_id === user?.id ? "bg-indigo-50" : "")}
    />
  );
})()}
```

Check `frontend/src/api/scoring.ts` to confirm the `TransparencyRow` type fields match (`full_name`, `node_name`, `enrolled_at`, `active_days`, `cumulative_score`, `normalised_score`, `soldier_id`). Adjust field names if they differ.

- [ ] **Step 2: Verify TypeScript compiles and tests pass**

```
cd frontend && pnpm tsc --noEmit && pnpm test
```

- [ ] **Step 3: Commit**

```
git add frontend/src/pages/TransparencyPage.tsx
git commit -m "feat(ui): transparency table uses DataTable"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|---|---|
| Per-slot rank (`candidate_rank`, `candidate_pool_size`) in backend | Task 1 |
| Cross-batch rank computed client-side | Task 5 |
| Both rank columns in proposals table | Task 5 |
| TanStack Table v8 installed | Task 3 |
| `DataTable<T>` component with sort + filter | Task 3 |
| AlgorithmPlanningWindow proposals migrated | Task 5 |
| ExplanationModal candidates migrated | Task 6 |
| ShiftsPage migrated | Task 7 |
| TeamHierarchyPage migrated (manual sort removed) | Task 8 |
| MyDutiesPage migrated | Task 9 |
| TransparencyPage migrated | Task 10 |
| i18n keys added | Task 4 |

**Placeholder scan:** No TBD/TODO/placeholders found.

**Type consistency:** `ColDef<T>` defined in Task 3 and used identically in Tasks 5–10. `candidate_rank`/`candidate_pool_size` defined in Task 1 backend and Task 2 frontend, consumed in Task 5.
