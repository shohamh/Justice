# Design: Transparency Export Respects Current Filters (Client-Side)

**Date:** 2026-06-26
**Status:** Approved
**Supersedes:** [2026-06-06-transparency-excel-export-design.md](2026-06-06-transparency-excel-export-design.md) — the backend-driven export endpoints it introduced are removed by this design.

## Summary

The existing "ייצוא לאקסל" export on the Transparency page only respects the unit-tree filter, and only includes a hardcoded subset of columns — it ignores the officer/enlisted pill, service-type pill, fairness-group filter, and the `DataTable`'s own free-text search box and column dropdown filters. It also lives in the page header, not next to the table it exports.

This design moves export generation entirely to the frontend: the button reads the exact rows `DataTable` is currently rendering (after every filter, search, and sort has been applied) and writes them straight to an `.xlsx` file using the SheetJS `xlsx` library. This guarantees the export always matches what's on screen, for both tabs, with no second filtering implementation to keep in sync.

## Problem with the current approach

`TransparencyPage` narrows `rows` → `visibleRows` via the tree filter, officer/enlisted pill, service-type pill, and group filter. `DataTable` then applies its *own* internal state (free-text search box, per-column dropdown filters, sort order) on top of whatever `data` it's given — none of that internal state is visible to the parent or the backend. The backend export endpoints (`GET /scoring/transparency/export`, `GET /scoring/transparency/sub-units/export`) only know about `node_id`, so officer/enlisted, service-type, group, and search-box filtering are silently dropped from the export, and the exported columns are a separate hand-maintained list that has drifted from the on-screen columns (missing effort score, group rank, group deviation, and the debug columns).

## Frontend Changes

### `frontend/package.json`

Add `xlsx` (SheetJS) as a dependency.

### `frontend/src/components/DataTable.tsx`

1. Extend `ColDef<T>`:
   ```typescript
   /** Plain value for Excel export. Falls back to filterValue, then sortValue, then "". */
   exportValue?: (row: T) => string | number | boolean | null | undefined;
   ```
2. Add a prop:
   ```typescript
   /** Fires with the fully filtered + sorted row set whenever it changes (for export). */
   onVisibleRowsChange?: (rows: T[]) => void;
   ```
3. After `table.getRowModel().rows` is computed, add a `useEffect` that calls `onVisibleRowsChange?.(table.getRowModel().rows.map(r => r.original))`, keyed on the row model's row identities (e.g. depend on `table.getRowModel().rows` directly — react-table recomputes this memoized value only when sorting/filtering/data actually change).

No changes to existing column behavior — `exportValue` is purely additive and only needs to be set on columns whose cell rendering diverges meaningfully from a plain value.

### `frontend/src/components/ExcelExportButton.tsx` (new)

```typescript
interface ExcelExportButtonProps<T> {
  columns: ColDef<T>[];
  rows: T[];
  filename: string;
}
```

- Renders a small Excel-green logo (inline SVG — a simple green rounded-square with a white "X", not a trademarked Microsoft asset) plus the label "ייצוא לאקסל".
- On click:
  1. Build `header = columns.map(c => c.header)`.
  2. Build `body = rows.map(r => columns.map(c => exportValueOf(c, r)))` where `exportValueOf` tries `c.exportValue`, then `c.filterValue`, then `c.sortValue`, then falls back to `""`.
  3. `const ws = XLSX.utils.aoa_to_sheet([header, ...body]); const wb = XLSX.utils.book_new(); XLSX.utils.book_append_sheet(wb, ws, "Sheet1"); XLSX.writeFile(wb, filename);`
- Disabled (greyed out, no-op) when `rows.length === 0`.
- Styling matches the current button's look: `text-sm text-green-700 dark:text-green-400 border border-green-300 dark:border-green-700 px-3 py-1 rounded hover:bg-green-50 dark:hover:bg-green-950 flex items-center gap-1.5`.

### `frontend/src/pages/TransparencyPage.tsx`

1. Remove the two header-row export buttons (the `tab === 0` and `tab === 1` blocks under "Header with tree filter").
2. Add state: `const [exportSoldierRows, setExportSoldierRows] = useState<NumberedRow[]>([]);` and `const [exportSubRows, setExportSubRows] = useState<SubRow[]>([]);`.
3. Pass `onVisibleRowsChange={setExportSoldierRows}` to the soldiers `DataTable`, and `onVisibleRowsChange={setExportSubRows}` to the sub-units `DataTable`.
4. Directly above each `DataTable`, add:
   ```tsx
   <div className="flex justify-start" dir="ltr">
     <ExcelExportButton columns={soldierCols} rows={exportSoldierRows} filename="transparency.xlsx" />
   </div>
   ```
   (and the equivalent for `subCols` / `exportSubRows` / `"sub-units.xlsx"`, above the sub-units table). The `dir="ltr"` wrapper is what pins the button to the visual left inside this otherwise-RTL page, consistent with how the existing tree-filter dropdown already anchors itself with `left-0`.
5. Add `exportValue` to columns where the rendered cell isn't already a plain value:
   - `group_rank`: `exportValue: (r) => { const g = r._group; if (!g || g.compIndex === -1) return "פטור"; if (g.groupSize < 2) return "—"; return \`${g.rank}/${g.groupSize}\`; }`
   - `group_dev`: `exportValue: (r) => { const mean = r._group?.groupMean; if (mean == null || isNaN(r.effort_score) || r._group?.compIndex === -1) return "—"; return ((r.effort_score - mean) * 100).toFixed(2) + "%"; }`
   - `effort_score`: `exportValue: (r) => isNaN(r.effort_score) ? "—" : (r.effort_score * 100).toFixed(2) + "%"`
   - `score_per_day`, `normalised`: reuse the same `.toFixed(...)` string already used in `cell`.
   - `count_offset` (debug): plain numeric value, no progress bar.
   - All other columns (name, unit, rank, cumulative, etc.) already have a `sortValue`/`filterValue` that's a clean primitive, so no `exportValue` needed — the fallback chain covers them.
6. Debug columns (`c_over_d`, `effort_offset_raw`, `count_offset`) are already conditionally spliced into `soldierCols` only when `showDebug` is true — since the export button is handed `soldierCols` as-is, toggling debug mode automatically changes both the table and the export together, with no extra logic needed.

### `frontend/src/api/scoring.ts`

Remove `downloadTransparencyExport`, `downloadSubUnitsExport`, and the now-unused `_triggerBlobDownload` helper.

## Backend Changes

Remove the two now-unused routes from `backend/app/routes/scoring.py`:
- `GET /scoring/transparency/export` (and its helpers `_dfs_order`, `_node_path`, `_xlsx_response` if nothing else uses them — `_xlsx_response` is also used by the sub-units export, so check usage before deleting `_xlsx_response`/`_node_path`/`_dfs_order`; if both routes are removed together, all three helpers become dead and should be deleted too)
- `GET /scoring/transparency/sub-units/export`

Remove `openpyxl` from `backend/pyproject.toml` if nothing else in the backend uses it (check first — `_xlsx_response` is the only current consumer found).

Remove the corresponding backend integration tests (`backend/tests/integration/test_transparency_export.py` or wherever they live — confirm exact file during implementation).

## Error Handling

- `ExcelExportButton` is a no-op when `rows.length === 0` (button disabled) — there's nothing to export, no error state needed.
- `XLSX.writeFile` runs synchronously in the browser; no network call, so no loading/error UI is needed beyond what SheetJS itself throws (extremely rare, e.g. browser blocking the download).

## Testing

- Frontend: extend `DataTable` tests to assert `onVisibleRowsChange` fires with the correct row set after a search-box filter, a column dropdown filter, and a sort change.
- Frontend: new test for `ExcelExportButton`'s export-value fallback chain (`exportValue` → `filterValue` → `sortValue` → `""`), and that it's disabled with zero rows.
- No backend tests needed (routes are deleted, not modified).

## Out of Scope

- Column auto-width / cell styling in the generated `.xlsx` (plain data only, matching the prior implementation's scope).
- Exporting the `FairnessComponentsCard` or summary stat cards — only the two `DataTable`s.
- A loading spinner on the button — generation is synchronous and fast for the data sizes involved.
