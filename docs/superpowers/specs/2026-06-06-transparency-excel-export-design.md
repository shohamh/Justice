# Design: Transparency Page Excel Export

**Date:** 2026-06-06
**Status:** Approved

## Summary

Add an "ייצוא לאקסל" (Export to Excel) button to both tabs of the Transparency page. Each button calls a dedicated backend API endpoint that generates and streams a `.xlsx` file. The soldiers-tab export respects the active unit filter; the sub-units export always returns the full tree.

## Backend Changes

### `backend/pyproject.toml`
Add `openpyxl>=3.1` to `dependencies`.

### `backend/app/routes/scoring.py`

#### 1. `GET /scoring/transparency/export`

Query params:
- `node_id: uuid.UUID | None = None` (optional)

Auth: `require_password_changed` (same as existing transparency endpoint).

Logic:
1. Call `svc.transparency_rows(session)` to get all rows.
2. If `node_id` is provided, load the `HierarchyNode` for that node; keep only rows whose soldier's `HierarchyNode.path_ids` includes `node_id`. Use a single bulk query to load all relevant nodes.
3. Build an `openpyxl` workbook with one sheet named `"חיילים"`.
4. Header row columns (in order): שם, יחידה, תאריך הצטרפות, ימים פעילים, דרגה, כמות משמרות, ניקוד מצטבר, ניקוד ליום, ניקוד מנורמל.
5. One data row per soldier.
6. Return `StreamingResponse` with:
   - `media_type`: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
   - `Content-Disposition`: `attachment; filename="transparency.xlsx"`

#### 2. `GET /scoring/transparency/sub-units/export`

No query params. Auth: same.

Logic:
1. Call `svc.transparency_rows(session)` and `session.execute(select(HierarchyNode)).scalars().all()` to get all nodes.
2. Build a lookup: `node_path_map: dict[uuid, list[uuid]]` mapping each node's id to its `path_ids`.
3. For each node (sorted by `len(path_ids)` ascending, then `name`), collect all rows whose soldier's node `path_ids` include this node's id. Skip nodes with zero matching rows.
4. Compute per-node aggregates:
   - `count`: total matching rows
   - `active_count`: rows where `cumulative_score > 0`
   - `avg_cumulative`: mean of `cumulative_score`
   - `avg_cumulative_active`: mean of `cumulative_score` for active rows only (0 if none)
   - `total_score_per_day`: sum of `score_per_day`
   - `avg_active_days`: mean of `active_days` (rounded to int)
   - `avg_normalised`: mean of `normalised_score`
5. Build workbook with one sheet `"תתי יחידות"`, columns: יחידה, כמות חיילים, חיילים פעילים (%), ממוצע ימים פעילים, ממוצע ניקוד לחייל, ממוצע ניקוד לחייל פעיל, ניקוד ליום (מסגרת), ניקוד מנורמל ממוצע.
6. Return `StreamingResponse` same as above, filename `"sub-units.xlsx"`.

## Frontend Changes

### `frontend/src/api/scoring.ts`

Add two functions:

```typescript
export function downloadTransparencyExport(nodeId: string | null): void {
  const params = nodeId ? `?node_id=${nodeId}` : "";
  window.location.href = `/api/scoring/transparency/export${params}`;
}

export function downloadSubUnitsExport(): void {
  window.location.href = `/api/scoring/transparency/sub-units/export`;
}
```

No axios — direct URL navigation triggers the browser's native file download.

### `frontend/src/pages/TransparencyPage.tsx`

Import `downloadTransparencyExport` and `downloadSubUnitsExport` from `../api/scoring`.

Add one button per tab in the header row (the `flex items-center justify-between` div), alongside the existing unit filter:

- **Tab 0 (חיילים):** Button "📥 ייצוא לאקסל" → calls `downloadTransparencyExport(selectedNodeId)`. Visible only when `tab === 0`.
- **Tab 1 (תתי יחידות):** Button "📥 ייצוא לאקסל" → calls `downloadSubUnitsExport()`. Visible only when `tab === 1`.

Button styling: `text-sm text-green-700 dark:text-green-400 border border-green-300 dark:border-green-700 px-3 py-1 rounded hover:bg-green-50 dark:hover:bg-green-950`.

## Authorization

Both endpoints use `require_password_changed` — the same guard as `GET /scoring/transparency`. Any authenticated user with a changed password can export.

## Error Handling

- If `node_id` is provided but not found: return `404` with `detail: "not_found"`.
- Backend Excel generation errors: unhandled (500 — acceptable for a file export edge case).
- Frontend: no special handling — browser will show its own error if the download fails.

## Testing

Backend integration tests in a new file `backend/tests/integration/test_transparency_export.py`:
- `GET /scoring/transparency/export` returns 200 with correct content-type
- `GET /scoring/transparency/export?node_id=<uuid>` filters rows to that subtree
- `GET /scoring/transparency/export?node_id=<unknown>` returns 404
- `GET /scoring/transparency/sub-units/export` returns 200 with correct content-type
- Soldier cannot call either endpoint (403) — actually both endpoints use `require_password_changed` not `ALGORITHM_RUN`, so soldiers CAN call them (same as transparency). No auth restriction beyond login.

## Out of Scope

- Column auto-width / cell styling in the Excel file (plain data only)
- Multiple sheets in one workbook
- Loading spinner on the button (browser handles download natively)
- Filtering the sub-units export by node
