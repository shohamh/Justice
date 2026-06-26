# Transparency Export Respects Current Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Transparency page's "ייצוא לאקסל" export include every active filter (unit tree, officer/enlisted, service type, fairness group, free-text search, column dropdowns) and every visible column, by generating the `.xlsx` client-side from the exact rows `DataTable` renders, with the button moved directly above each table on the left.

**Architecture:** `DataTable` gains an `onVisibleRowsChange` callback that reports its fully filtered+sorted row set, plus an optional `exportValue` per column for cases where the rendered cell isn't already a plain value. `TransparencyPage` captures that row set per tab and feeds it to a new `ExcelExportButton` component that writes an `.xlsx` file in the browser using SheetJS. The old backend export endpoints and their dedicated frontend API calls are deleted.

**Tech Stack:** React, TypeScript, `@tanstack/react-table` (already used by `DataTable`), SheetJS `xlsx` (new dependency), `lucide-react` (already a dependency, used for the export icon), Vitest + Testing Library for frontend tests.

**Design doc:** [docs/superpowers/specs/2026-06-26-transparency-export-full-filter-design.md](../specs/2026-06-26-transparency-export-full-filter-design.md)

---

### Task 1: Add the `xlsx` dependency

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install the package**

Run (from `frontend/`):
```bash
npm install xlsx@0.18.5
```

- [ ] **Step 2: Verify it landed in `package.json` and `package-lock.json`**

Run: `grep '"xlsx"' package.json package-lock.json`
Expected: a line containing `"xlsx": "0.18.5"` (or `^0.18.5`) in both files.

- [ ] **Step 3: Commit**

```bash
git add package.json package-lock.json
git commit -m "chore: add xlsx for client-side Excel export"
```

---

### Task 2: `DataTable` — add `exportValue` to `ColDef` and `onVisibleRowsChange` prop

**Files:**
- Modify: `frontend/src/components/DataTable.tsx`
- Test: `frontend/src/components/DataTable.test.tsx`

- [ ] **Step 1: Write the failing tests**

Add to the end of `frontend/src/components/DataTable.test.tsx`:

```typescript
test("onVisibleRowsChange fires with full data on initial render", () => {
  const spy = vi.fn();
  render(<DataTable columns={cols} data={data} onVisibleRowsChange={spy} />);
  expect(spy).toHaveBeenCalledWith(data);
});

test("onVisibleRowsChange fires with filtered rows after search box input", () => {
  const spy = vi.fn();
  render(<DataTable columns={cols} data={data} onVisibleRowsChange={spy} />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Alice" } });
  expect(spy).toHaveBeenLastCalledWith([data[0]]);
});

test("onVisibleRowsChange fires with sorted rows after header click", () => {
  const spy = vi.fn();
  render(<DataTable columns={cols} data={data} onVisibleRowsChange={spy} />);
  fireEvent.click(screen.getByText("Score"));
  expect(spy).toHaveBeenLastCalledWith([data[1], data[2], data[0]]); // Bob(1), Charlie(2), Alice(3)
});
```

Add `vi` to the existing `import` line at the top of the file:
```typescript
import { render, screen, fireEvent } from "@testing-library/react";
import { test, expect, vi } from "vitest";
import { DataTable, type ColDef } from "./DataTable";
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npm test -- DataTable`
Expected: FAIL — `onVisibleRowsChange` is not a recognized prop yet, so the spy is never called (`expect(spy).toHaveBeenCalledWith(data)` fails with "Number of calls: 0").

- [ ] **Step 3: Implement `exportValue` and `onVisibleRowsChange`**

In `frontend/src/components/DataTable.tsx`, extend `ColDef<T>` (after the existing `minWidth?` field):

```typescript
  /** Minimum column width in pixels. */
  minWidth?: number;
  /** Plain value for Excel export. Falls back to filterValue, then sortValue, then "". */
  exportValue?: (row: T) => string | number | boolean | null | undefined;
}
```

Add the prop to `DataTableProps<T>` (after `rowTestId?`):

```typescript
  rowTestId?: (row: T) => string;
  /** Fires with the fully filtered + sorted row set whenever it changes (e.g. for export). */
  onVisibleRowsChange?: (rows: T[]) => void;
}
```

Add `onVisibleRowsChange` to the destructured props of `DataTable`:

```typescript
export function DataTable<T>({
  columns,
  data,
  filterPlaceholder = "סנן...",
  className,
  rowClassName,
  rowStyle,
  emptyMessage = "—",
  testId,
  rowTestId,
  onVisibleRowsChange,
}: DataTableProps<T>) {
```

`useEffect` is already imported at the top of the file (`import { useMemo, useState, useRef, useEffect } from "react";`) — no change needed there.

Right after the `const table = useReactTable({...})` block, add:

```typescript
  const visibleRows = table.getRowModel().rows.map((r) => r.original);
  useEffect(() => {
    onVisibleRowsChange?.(visibleRows);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visibleRows]);
```

Note: `visibleRows` is a new array each render, so this effect runs on every render — that's fine since `setState` calls with referentially-equal-by-value content in the parent are cheap and this table is not large enough to matter. Do not try to memoize `visibleRows` itself by reference equality of `table.getRowModel().rows`, since `@tanstack/react-table` already memoizes that array internally and only recomputes it when sorting/filtering/data change.

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- DataTable`
Expected: PASS — all tests including the 3 new ones.

- [ ] **Step 5: Commit**

```bash
git add src/components/DataTable.tsx src/components/DataTable.test.tsx
git commit -m "feat: add onVisibleRowsChange and exportValue to DataTable"
```

---

### Task 3: `ExcelExportButton` component

**Files:**
- Create: `frontend/src/components/ExcelExportButton.tsx`
- Test: `frontend/src/components/ExcelExportButton.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/ExcelExportButton.test.tsx`:

```typescript
import { render, screen, fireEvent } from "@testing-library/react";
import { test, expect, vi } from "vitest";
import * as XLSX from "xlsx";
import { ExcelExportButton } from "./ExcelExportButton";
import type { ColDef } from "./DataTable";

interface Row { name: string; score: number; }

const columns: ColDef<Row>[] = [
  { id: "name", header: "שם", cell: (r) => r.name, filterValue: (r) => r.name },
  { id: "score", header: "ניקוד", cell: (r) => String(r.score), sortValue: (r) => r.score },
  {
    id: "label",
    header: "תווית",
    cell: (r) => `${r.score}/10`,
    sortValue: (r) => r.score,
    exportValue: (r) => `${r.score} out of 10`,
  },
];

const rows: Row[] = [
  { name: "Alice", score: 3 },
  { name: "Bob", score: 7 },
];

test("is disabled when there are no rows", () => {
  render(<ExcelExportButton columns={columns} rows={[]} filename="x.xlsx" />);
  expect(screen.getByRole("button")).toBeDisabled();
});

test("is enabled when there are rows", () => {
  render(<ExcelExportButton columns={columns} rows={rows} filename="x.xlsx" />);
  expect(screen.getByRole("button")).not.toBeDisabled();
});

test("writes a workbook with header row and exportValue fallback chain on click", () => {
  const writeFileSpy = vi.spyOn(XLSX, "writeFile").mockImplementation(() => {});
  render(<ExcelExportButton columns={columns} rows={rows} filename="export.xlsx" />);
  fireEvent.click(screen.getByRole("button"));

  expect(writeFileSpy).toHaveBeenCalledTimes(1);
  const [wb, filename] = writeFileSpy.mock.calls[0];
  expect(filename).toBe("export.xlsx");
  const ws = wb.Sheets[wb.SheetNames[0]];
  const aoa = XLSX.utils.sheet_to_json(ws, { header: 1 }) as unknown[][];
  expect(aoa[0]).toEqual(["שם", "ניקוד", "תווית"]);
  // row for Alice: name via filterValue, score via sortValue, label via exportValue
  expect(aoa[1]).toEqual(["Alice", 3, "3 out of 10"]);
  expect(aoa[2]).toEqual(["Bob", 7, "7 out of 10"]);

  writeFileSpy.mockRestore();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npm test -- ExcelExportButton`
Expected: FAIL — `./ExcelExportButton` module not found.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/ExcelExportButton.tsx`:

```typescript
import { FileSpreadsheet } from "lucide-react";
import * as XLSX from "xlsx";
import type { ColDef } from "./DataTable";

interface ExcelExportButtonProps<T> {
  columns: ColDef<T>[];
  rows: T[];
  filename: string;
}

function exportValueOf<T>(col: ColDef<T>, row: T): string | number | boolean {
  const value = col.exportValue
    ? col.exportValue(row)
    : col.filterValue
      ? col.filterValue(row)
      : col.sortValue
        ? col.sortValue(row)
        : undefined;
  return value ?? "";
}

export function ExcelExportButton<T>({ columns, rows, filename }: ExcelExportButtonProps<T>) {
  function handleExport() {
    const header = columns.map((c) => c.header);
    const body = rows.map((row) => columns.map((c) => exportValueOf(c, row)));
    const ws = XLSX.utils.aoa_to_sheet([header, ...body]);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "Sheet1");
    XLSX.writeFile(wb, filename);
  }

  return (
    <button
      type="button"
      disabled={rows.length === 0}
      onClick={handleExport}
      className="text-sm text-green-700 dark:text-green-400 border border-green-300 dark:border-green-700 px-3 py-1 rounded hover:bg-green-50 dark:hover:bg-green-950 flex items-center gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent"
    >
      <FileSpreadsheet className="w-4 h-4" />
      ייצוא לאקסל
    </button>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- ExcelExportButton`
Expected: PASS — all 3 tests.

- [ ] **Step 5: Commit**

```bash
git add src/components/ExcelExportButton.tsx src/components/ExcelExportButton.test.tsx
git commit -m "feat: add ExcelExportButton for client-side xlsx export"
```

---

### Task 4: Wire `ExcelExportButton` into `TransparencyPage`, add `exportValue` to its columns, remove old export buttons

**Files:**
- Modify: `frontend/src/pages/TransparencyPage.tsx`

- [ ] **Step 1: Add imports and state**

At the top of `frontend/src/pages/TransparencyPage.tsx`, add the import (next to the other component imports):

```typescript
import { ExcelExportButton } from "../components/ExcelExportButton";
```

Inside `export default function TransparencyPage()`, after the existing `useState` declarations (right after the `fairnessComponents` state, before the `useEffect` calls), add:

```typescript
  const [exportSoldierRows, setExportSoldierRows] = useState<NumberedRow[]>([]);
  const [exportSubRows, setExportSubRows] = useState<SubRow[]>([]);
```

(`NumberedRow` is already defined later in the file as `type NumberedRow = TransparencyRow & { _row_num: number; _rank_order: number; _group?: SoldierGroupInfo };` — TypeScript type aliases are hoisted within a module, so referencing it here is fine.)

- [ ] **Step 2: Add `exportValue` to the `group_rank`, `group_dev`, and `effort_score` columns**

In the `group_rank` column definition (the one with `header: "מקום בקבוצה"`), add `exportValue` right after `sortValue`:

```typescript
      sortValue: (r: NumberedRow) => r._group?.rank ?? 9999,
      exportValue: (r: NumberedRow) => {
        const g = r._group;
        if (!g || g.compIndex === -1) return "פטור";
        if (g.groupSize < 2) return "—";
        return `${g.rank}/${g.groupSize}`;
      },
    } as ColDef<NumberedRow>,
```

In the `group_dev` column definition (the one with `header: "עודף עומס"`), add `exportValue` right after `sortValue`:

```typescript
      sortValue: (r: NumberedRow) => {
        const mean = r._group?.groupMean;
        return mean != null && !isNaN(r.effort_score) ? r.effort_score - mean : 9999;
      },
      exportValue: (r: NumberedRow) => {
        const mean = r._group?.groupMean;
        if (mean == null || isNaN(r.effort_score) || r._group?.compIndex === -1) return "—";
        const dev = r.effort_score - mean;
        return (dev >= 0 ? "+" : "") + (dev * 100).toFixed(2) + "%";
      },
    } as ColDef<NumberedRow>,
```

In the `effort_score` column definition (`header: "עומס רבעוני"`), add `exportValue` right after `sortValue`:

```typescript
      sortValue: (r) => r.effort_score,
      exportValue: (r) => {
        const n = r.effort_score;
        return isNaN(n) || n === undefined ? "—" : (n * 100).toFixed(2) + "%";
      },
    },
```

(`score_per_day` and `normalised` already have a clean numeric `sortValue` via `Number(r.score_per_day)` / `Number(r.normalised_score)`, which the fallback chain picks up automatically — no change needed there. `c_over_d`, `effort_offset_raw`, and `count_offset` debug columns also already have plain numeric `sortValue`s, so the fallback covers them too.)

- [ ] **Step 3: Wire `onVisibleRowsChange` on both `DataTable`s**

Find the soldiers `DataTable` (inside `{tab === 0 && (...)}`) and add `onVisibleRowsChange={setExportSoldierRows}`:

```typescript
            <DataTable
              columns={soldierCols}
              data={visibleRows}
              filterPlaceholder={t("table.filter_placeholder")}
              rowClassName={(r) => (r.soldier_id === user?.id ? "bg-indigo-50 dark:bg-indigo-950" : "")}
              rowStyle={(r) => {
                const g = r._group;
                if (!g || g.compIndex < 0) return {};
                const color = COMPONENT_COLORS[g.compIndex % COMPONENT_COLORS.length];
                return { borderRight: `3px solid ${color}` };
              }}
              testId="transparency-table"
              onVisibleRowsChange={setExportSoldierRows}
            />
```

Find the sub-units `DataTable` (inside `{tab === 1 && (...)}`) and add `onVisibleRowsChange={setExportSubRows}`:

```typescript
          <DataTable
            columns={subCols}
            data={subRows}
            filterPlaceholder={t("table.filter_placeholder")}
            onVisibleRowsChange={setExportSubRows}
          />
```

- [ ] **Step 4: Add the export buttons directly above each table, remove the old header-row buttons**

Remove the entire `{tab === 0 && (<div className="flex items-center gap-2">...</div>)}` and `{tab === 1 && (<button ...>📥 ייצוא לאקסל</button>)}` blocks that currently sit inside the "Header with tree filter" `<div className="flex items-center justify-between gap-4" dir="rtl">` (this removes the export buttons but **keeps** the `showDebug` toggle button, which must stay — only delete the `<button>` calling `downloadTransparencyExport`/`downloadSubUnitsExport` and, for tab 0, unwrap the `showDebug` button from the now-removed wrapping `<div className="flex items-center gap-2">`, placing it directly as a sibling so it still renders standalone when `tab === 0 && user?.role === "admin"`).

Concretely, replace this block:

```typescript
          {tab === 0 && (
            <div className="flex items-center gap-2">
              {user?.role === "admin" && (
                <button
                  className={`text-xs px-2 py-1 rounded border transition-colors ${showDebug ? "bg-amber-100 dark:bg-amber-900 border-amber-400 text-amber-800 dark:text-amber-200" : "border-gray-300 dark:border-gray-600 text-gray-500 hover:border-amber-400"}`}
                  onClick={() => setShowDebug(d => !d)}
                  title="הצג ערכי count-space לדיבאג הוגנות"
                >
                  🔧 מצב דיבאג
                </button>
              )}
              <button
                className="text-sm text-green-700 dark:text-green-400 border border-green-300 dark:border-green-700 px-3 py-1 rounded hover:bg-green-50 dark:hover:bg-green-950"
                onClick={() => void downloadTransparencyExport(selectedNodeId)}
              >
                📥 ייצוא לאקסל
              </button>
            </div>
          )}
          {tab === 1 && (
            <button
              className="text-sm text-green-700 dark:text-green-400 border border-green-300 dark:border-green-700 px-3 py-1 rounded hover:bg-green-50 dark:hover:bg-green-950"
              onClick={() => void downloadSubUnitsExport()}
            >
              📥 ייצוא לאקסל
            </button>
          )}
```

with:

```typescript
          {tab === 0 && user?.role === "admin" && (
            <button
              className={`text-xs px-2 py-1 rounded border transition-colors ${showDebug ? "bg-amber-100 dark:bg-amber-900 border-amber-400 text-amber-800 dark:text-amber-200" : "border-gray-300 dark:border-gray-600 text-gray-500 hover:border-amber-400"}`}
              onClick={() => setShowDebug(d => !d)}
              title="הצג ערכי count-space לדיבאג הוגנות"
            >
              🔧 מצב דיבאג
            </button>
          )}
```

Then, directly above the soldiers `DataTable` (right before `<DataTable columns={soldierCols} ...`, inside the `{tab === 0 && (<> ... </>)}` block), add:

```typescript
            <div className="flex justify-start" dir="ltr">
              <ExcelExportButton columns={soldierCols} rows={exportSoldierRows} filename="transparency.xlsx" />
            </div>
```

And directly above the sub-units `DataTable` (right before `<DataTable columns={subCols} ...`, inside the `{tab === 1 && (<DataTable ... />)}` block — this block currently has no wrapping fragment, so wrap it in one), add:

```typescript
        {tab === 1 && (
          <>
            <div className="flex justify-start" dir="ltr">
              <ExcelExportButton columns={subCols} rows={exportSubRows} filename="sub-units.xlsx" />
            </div>
            <DataTable
              columns={subCols}
              data={subRows}
              filterPlaceholder={t("table.filter_placeholder")}
              onVisibleRowsChange={setExportSubRows}
            />
          </>
        )}
```

- [ ] **Step 5: Remove the now-unused `downloadTransparencyExport`/`downloadSubUnitsExport` import**

In the import line at the top of the file:
```typescript
import { EffortBreakdown, FairnessComponents, TransparencyRow, getEffortBreakdown, getFairnessComponents, getTransparency, downloadTransparencyExport, downloadSubUnitsExport } from "../api/scoring";
```
change to:
```typescript
import { EffortBreakdown, FairnessComponents, TransparencyRow, getEffortBreakdown, getFairnessComponents, getTransparency } from "../api/scoring";
```

- [ ] **Step 6: Typecheck and lint**

Run (from `frontend/`):
```bash
npm run lint
```
Expected: no errors (zero warnings enforced). Fix any unused-variable or type errors surfaced (e.g. if `selectedNodeId` becomes unused anywhere else, it won't — it's still used by the tree filter and `visibleRows`/`subRows` computation).

- [ ] **Step 7: Commit**

```bash
git add src/pages/TransparencyPage.tsx
git commit -m "feat: move transparency export above table, respect all active filters"
```

---

### Task 4.5: Migrate `ExportPage` (Planning > Export) to client-side export

**Discovered during execution:** `frontend/src/pages/planning/ExportPage.tsx` is a separate, currently-working page (nav entry "ייצוא לאקסל" under Planning) that ALSO calls `downloadTransparencyExport`/`downloadSubUnitsExport` — unfiltered, full-dataset versions. Neither the design doc nor the original plan accounted for this page. Decision: keep the page, but migrate it to the same client-side `ExcelExportButton` mechanism, so Task 5/6 can safely delete the old backend-driven functions/routes without breaking it.

**Files:**
- Modify: `frontend/src/pages/planning/ExportPage.tsx`
- Modify: `frontend/src/i18n/he.json`

- [ ] **Step 1: Rewrite `ExportPage.tsx`**

Replace the full contents of `frontend/src/pages/planning/ExportPage.tsx` with:

**Note on `dfsOrder`:** `fetchFullTree()` (and `GET /hierarchy/tree` generally) returns a FLAT list of nodes — `NodeDTO.children` is declared but never populated by the API (confirmed: `backend/app/routes/hierarchy.py`'s `get_tree` returns `list[NodeOut]` with no nesting). `dfsOrder` below builds its own `parent_id`-keyed children map from the flat list and recurses from root (`parent_id === null`) — do NOT try to recurse into `n.children`, since it will always be `undefined` and silently produce a flat alphabetical sort instead of a real pre-order traversal grouped by unit hierarchy.

```typescript
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import Layout from "../../components/Layout";
import { TransparencyRow, getTransparency } from "../../api/scoring";
import { fetchFullTree, NodeDTO } from "../../api/hierarchy";
import { ExcelExportButton } from "../../components/ExcelExportButton";
import type { ColDef } from "../../components/DataTable";

function flattenTree(nodes: NodeDTO[]): NodeDTO[] {
  const result: NodeDTO[] = [];
  function traverse(node: NodeDTO) {
    result.push(node);
    node.children?.forEach(traverse);
  }
  nodes.forEach(traverse);
  return result;
}

function dfsOrder(nodes: NodeDTO[]): string[] {
  const childrenByParent = new Map<string | null, NodeDTO[]>();
  for (const n of nodes) {
    const key = n.parent_id ?? null;
    if (!childrenByParent.has(key)) childrenByParent.set(key, []);
    childrenByParent.get(key)!.push(n);
  }
  for (const list of childrenByParent.values()) {
    list.sort((a, b) => a.name.localeCompare(b.name, "he"));
  }
  const order: string[] = [];
  function traverse(parentId: string | null) {
    for (const n of childrenByParent.get(parentId) ?? []) {
      order.push(n.id);
      traverse(n.id);
    }
  }
  traverse(null);
  return order;
}

function nodePath(nodeId: string | null, nodesById: Map<string, NodeDTO>): string {
  const parts: string[] = [];
  let id = nodeId;
  while (id) {
    const node = nodesById.get(id);
    if (!node) break;
    parts.push(node.name);
    id = node.parent_id;
  }
  return parts.reverse().join(" / ");
}

interface SubRow {
  node_id: string;
  node_name: string;
  count: number;
  active_pct: number;
  avg_active_days: number;
  avg_cumulative: number;
  avg_cumulative_active: number;
  total_score_per_day: number;
  avg_normalised: number;
}

export default function ExportPage() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<TransparencyRow[]>([]);
  const [treeNodes, setTreeNodes] = useState<NodeDTO[]>([]);

  useEffect(() => { void getTransparency().then(setRows); }, []);
  useEffect(() => { void fetchFullTree().then(setTreeNodes); }, []);

  const flatNodes = useMemo(() => flattenTree(treeNodes), [treeNodes]);
  const nodesById = useMemo(() => new Map(flatNodes.map((n) => [n.id, n])), [flatNodes]);
  const nodeOrder = useMemo(() => {
    const order = dfsOrder(treeNodes);
    return new Map(order.map((id, i) => [id, i]));
  }, [treeNodes]);

  const soldierRows = useMemo(() => {
    return [...rows].sort((a, b) => {
      const oa = a.node_id ? nodeOrder.get(a.node_id) ?? 9999 : 9999;
      const ob = b.node_id ? nodeOrder.get(b.node_id) ?? 9999 : 9999;
      if (oa !== ob) return oa - ob;
      return a.full_name.localeCompare(b.full_name, "he");
    });
  }, [rows, nodeOrder]);

  const subRows = useMemo((): SubRow[] => {
    const result: SubRow[] = [];
    const sortedNodes = [...flatNodes].sort(
      (a, b) => a.path_ids.length - b.path_ids.length || a.name.localeCompare(b.name, "he"),
    );
    const avg = (vals: number[]) => vals.reduce((a, b) => a + b, 0) / vals.length;
    for (const node of sortedNodes) {
      const nodeRows = rows.filter((r) => r.node_id != null && nodesById.get(r.node_id)?.path_ids.includes(node.id));
      if (nodeRows.length === 0) continue;
      const activeRows = nodeRows.filter((r) => !r.is_globally_exempted);
      result.push({
        node_id: node.id,
        node_name: node.name,
        count: nodeRows.length,
        active_pct: Math.round((activeRows.length / nodeRows.length) * 100),
        avg_active_days: Math.round(avg(nodeRows.map((r) => r.active_days))),
        avg_cumulative: avg(nodeRows.map((r) => Number(r.cumulative_score))),
        avg_cumulative_active: activeRows.length > 0 ? avg(activeRows.map((r) => Number(r.cumulative_score))) : 0,
        total_score_per_day: nodeRows.reduce((s, r) => s + Number(r.score_per_day), 0),
        avg_normalised: avg(nodeRows.map((r) => Number(r.normalised_score))),
      });
    }
    return result;
  }, [flatNodes, nodesById, rows]);

  const soldierCols: ColDef<TransparencyRow>[] = [
    {
      id: "unit_path", header: "יחידה / תת-יחידה",
      cell: (r) => r.node_id ? nodePath(r.node_id, nodesById) : "—",
      sortValue: (r) => r.node_id ? nodePath(r.node_id, nodesById) : "",
    },
    { id: "name", header: "שם", cell: (r) => r.full_name, sortValue: (r) => r.full_name, filterValue: (r) => r.full_name },
    { id: "unit", header: "יחידה", cell: (r) => r.node_name ?? "—", sortValue: (r) => r.node_name ?? "" },
    { id: "enrolled_at", header: "תאריך הצטרפות", cell: (r) => r.enrolled_at, sortValue: (r) => r.enrolled_at },
    { id: "active_days", header: "ימים פעילים", cell: (r) => r.active_days, sortValue: (r) => r.active_days },
    { id: "rank", header: "דרגה", cell: (r) => r.rank ?? "—", sortValue: (r) => r.rank ?? "" },
    { id: "shift_count", header: "כמות משמרות", cell: (r) => r.shift_count, sortValue: (r) => r.shift_count },
    { id: "cumulative", header: "ניקוד מצטבר", cell: (r) => r.cumulative_score, sortValue: (r) => Number(r.cumulative_score) },
    { id: "score_per_day", header: "ניקוד ליום", cell: (r) => r.score_per_day, sortValue: (r) => Number(r.score_per_day) },
    { id: "normalised", header: "ניקוד מנורמל", cell: (r) => r.normalised_score, sortValue: (r) => Number(r.normalised_score) },
  ];

  const subCols: ColDef<SubRow>[] = [
    { id: "name", header: "יחידה", cell: (r) => r.node_name, sortValue: (r) => r.node_name },
    { id: "count", header: "כמות חיילים", cell: (r) => r.count, sortValue: (r) => r.count },
    { id: "active_pct", header: "חיילים פעילים (%)", cell: (r) => r.active_pct, sortValue: (r) => r.active_pct },
    { id: "avg_active_days", header: "ממוצע ימים פעילים", cell: (r) => r.avg_active_days, sortValue: (r) => r.avg_active_days },
    { id: "avg_cumulative", header: "ממוצע ניקוד לחייל", cell: (r) => r.avg_cumulative.toFixed(2), exportValue: (r) => r.avg_cumulative, sortValue: (r) => r.avg_cumulative },
    { id: "avg_cumulative_active", header: "ממוצע ניקוד לחייל פעיל", cell: (r) => r.avg_cumulative_active.toFixed(2), exportValue: (r) => r.avg_cumulative_active, sortValue: (r) => r.avg_cumulative_active },
    { id: "total_score_per_day", header: "ניקוד ליום (מסגרת)", cell: (r) => r.total_score_per_day.toFixed(2), exportValue: (r) => r.total_score_per_day, sortValue: (r) => r.total_score_per_day },
    { id: "avg_normalised", header: "ניקוד מנורמל ממוצע", cell: (r) => r.avg_normalised.toFixed(3), exportValue: (r) => r.avg_normalised, sortValue: (r) => r.avg_normalised },
  ];

  return (
    <Layout>
      <section className="bg-white dark:bg-gray-800 rounded-lg shadow p-6 space-y-6">
        <h2 className="text-xl font-semibold">{t("nav.planning_export")}</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="border dark:border-gray-700 rounded-lg p-5 space-y-3">
            <h3 className="font-medium">{t("export.transparency_title")}</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">{t("export.transparency_desc")}</p>
            <ExcelExportButton columns={soldierCols} rows={soldierRows} filename="transparency.xlsx" />
          </div>
          <div className="border dark:border-gray-700 rounded-lg p-5 space-y-3">
            <h3 className="font-medium">{t("export.sub_units_title")}</h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">{t("export.sub_units_desc")}</p>
            <ExcelExportButton columns={subCols} rows={subRows} filename="sub-units.xlsx" />
          </div>
        </div>
      </section>
    </Layout>
  );
}
```

This mirrors exactly the column set the OLD backend `transparency_export`/`transparency_sub_units_export` routes produced (full unfiltered dataset, DFS-ordered by unit path for soldiers, shallowest-first for sub-units) — just computed client-side now. No fairness/group columns (those are Transparency-page-specific enrichments, out of scope for this page, which always showed the plain unfiltered dataset).

- [ ] **Step 2: Remove the now-unused `download`/`downloading` i18n keys**

In `frontend/src/i18n/he.json`, inside the `"export"` block, remove the `"download"` and `"downloading"` keys (they were only used by the loading-button UI this rewrite removes):

```json
  "export": {
    "transparency_title": "ייצוא שקיפות",
    "transparency_desc": "ייצוא נתוני ניקוד ושיבוץ לכל החיילים לקובץ Excel.",
    "sub_units_title": "ייצוא יחידות משנה",
    "sub_units_desc": "ייצוא סיכום ניקוד לפי יחידות משנה לקובץ Excel."
  },
```

- [ ] **Step 3: Typecheck and lint**

Run (from `frontend/`): `npm run lint`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/pages/planning/ExportPage.tsx src/i18n/he.json
git commit -m "feat: migrate ExportPage to client-side Excel export"
```

---

### Task 5: Remove the now-unused frontend API functions

**Files:**
- Modify: `frontend/src/api/scoring.ts`

- [ ] **Step 1: Delete the dead functions**

Remove `_triggerBlobDownload`, `downloadTransparencyExport`, and `downloadSubUnitsExport` from `frontend/src/api/scoring.ts` (the last three functions in the file, lines 77–105 as currently written).

- [ ] **Step 2: Verify nothing else references them**

Run (from `frontend/`):
```bash
grep -rn "downloadTransparencyExport\|downloadSubUnitsExport\|_triggerBlobDownload" src
```
Expected: no output (references were in `TransparencyPage.tsx`, removed in Task 4, and `ExportPage.tsx`, migrated off them in Task 4.5).

- [ ] **Step 3: Typecheck**

Run: `npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/api/scoring.ts
git commit -m "chore: remove unused transparency export API functions"
```

---

### Task 6: Remove the backend export routes and their tests

**Files:**
- Modify: `backend/app/routes/scoring.py`
- Delete: `backend/tests/integration/test_transparency_export.py`

- [ ] **Step 1: Delete the routes and their dedicated helpers**

In `backend/app/routes/scoring.py`, delete:
- The `_dfs_order` function (lines ~116–121)
- The `_node_path` function (lines ~124–133)
- The `_xlsx_response` function (lines ~87–95)
- The `transparency_export` route (`@router.get("/transparency/export")`, lines ~136–190)
- The `transparency_sub_units_export` route (`@router.get("/transparency/sub-units/export")`, lines ~193–248)

Also remove now-unused imports at the top of the file if nothing else in the file uses them — check each before removing:
```bash
grep -n "^import io$\|StreamingResponse\|^import openpyxl$" backend/app/routes/scoring.py
```
`io` and `openpyxl` and `StreamingResponse` are only used by the deleted code in this file — remove these three import lines:
```python
import io
```
```python
import openpyxl
```
```python
from fastapi.responses import StreamingResponse
```

- [ ] **Step 2: Delete the test file**

```bash
rm backend/tests/integration/test_transparency_export.py
```

- [ ] **Step 3: Run the full scoring-related test suite**

Run (from `backend/`, with venv activated):
```bash
pytest -m scoring -q
```
Expected: PASS, with no references to the deleted tests (they're gone, not skipped).

- [ ] **Step 4: Run a quick import sanity check**

Run: `python -c "from app.main import app"`
Expected: no `ImportError` or `NameError` (confirms no other code in the file references the deleted imports/functions).

- [ ] **Step 5: Commit**

```bash
git add app/routes/scoring.py
git rm tests/integration/test_transparency_export.py
git commit -m "chore: remove backend transparency export endpoints (superseded by client-side export)"
```

---

### Task 7: End-to-end manual verification

**Files:** none (manual check only)

- [ ] **Step 1: Start the dev stack**

From the repo root:
```powershell
.\dev.ps1
```

- [ ] **Step 2: Open the Transparency page**

Navigate to `http://localhost:5173`, log in, go to the Transparency page (חיילים tab).

- [ ] **Step 3: Verify the button moved**

Confirm the "ייצוא לאקסל" button (green, with a spreadsheet icon) now appears directly above the soldiers table, aligned to the left, and is no longer in the page header.

- [ ] **Step 4: Verify filters are respected**

Apply the "קצינים" (officers) pill, type something into the table's search box, and click a column header to sort. Click "ייצוא לאקסל" and open the downloaded `transparency.xlsx` — confirm it contains only the filtered/searched rows, in the sorted order, and that every column visible in the on-screen table (including "מקום בקבוצה" and "עודף עומס") appears with a sensible plain-text/number value.

- [ ] **Step 5: Verify the sub-units tab**

Switch to "תתי יחידות", confirm the export button is above that table too, and that clicking it downloads `sub-units.xlsx` matching the currently visible/sorted rows.

- [ ] **Step 6: Verify debug mode (admin only)**

As an admin, toggle "🔧 מצב דיבאג" on the soldiers tab, then export — confirm the debug columns (C/D, effort_offset, count_offset) appear in the exported file. Toggle it off and export again — confirm they're absent.

- [ ] **Step 7: Verify zero-row state**

Apply a filter combination that yields zero rows (e.g. select a unit with no soldiers, or search for nonsense text). Confirm the export button becomes disabled (greyed out) rather than producing an empty file.

- [ ] **Step 8: Verify the migrated `ExportPage` (Planning > Export)**

Navigate to the "ייצוא לאקסל" nav entry under Planning. Confirm both cards render with their title/description text (unchanged), each with a working export button. Click each and confirm a full, unfiltered `transparency.xlsx` / `sub-units.xlsx` downloads, with a unit-path column on the soldiers export and per-node aggregates on the sub-units export — i.e. functionally equivalent to what this page produced before the migration, just generated client-side now.

No commit for this task — it's verification only.
