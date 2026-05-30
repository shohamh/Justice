---
title: Smart Tables & Soldier Rank
date: 2026-05-30
status: approved
---

# Smart Tables & Soldier Rank

## Goal

1. Show **two rank columns** in the algorithm proposals table so the DM can confirm the assigned soldier is genuinely the most deserving.
2. Make **all data tables** in the app sortable and filterable using TanStack Table v8.

---

## Rank Columns

### Cross-proposal rank (`דירוג כולל`)
Computed **client-side** from the current batch's proposals. Sort all proposals by `norm_score_before` ascending; assign rank 1 = lowest score (most deserving). Ties share a rank. No backend change needed.

### Per-slot rank (`דירוג במשמרת`)
Computed **in `_proposals_for_job`** in `backend/app/routes/algorithm.py`, which already fetches `AssignmentExplanation.payload.candidates` for each proposal. For each assignment:

1. Filter candidates where `blocked == false`.
2. Sort by `pre_norm_score` ascending.
3. Find the index of the assigned soldier → `candidate_rank` (1-based).
4. Count unblocked candidates → `candidate_pool_size`.

Add two new nullable fields to `ProposalOut`:
```python
candidate_rank: int | None = None
candidate_pool_size: int | None = None
```

Display as `"1 / 8"` in the proposals table. If data is unavailable (no explanation stored), show `"—"`.

Add matching fields to the frontend `ProposalRow` TypeScript interface.

---

## Table Library: TanStack Table v8

Install `@tanstack/react-table` (headless, same ecosystem as `@tanstack/react-query` already in use). The library provides sort/filter state machines and row models; we own all markup and Tailwind styles — RTL is unaffected.

### `DataTable<T>` component

Location: `frontend/src/components/DataTable.tsx`

```tsx
interface ColumnDef<T> {
  id: string;
  header: string;
  cell: (row: T) => React.ReactNode;
  // If provided, column is sortable; return comparable value
  sortingFn?: (row: T) => string | number | null | undefined;
  // If provided, value is included in global text filter
  filterFn?: (row: T) => string;
  // Don't render a sort header even if sortingFn is set
  disableSort?: boolean;
}

interface DataTableProps<T> {
  columns: ColumnDef<T>[];
  data: T[];
  filterPlaceholder?: string;
  className?: string;
}
```

**Features:**
- Global text-filter input above the table (searches across all columns that declare `filterFn`)
- Sortable column headers (click: asc → desc → unsorted); active sort shown with ▲/▼
- TanStack Table manages sort/filter state; component is fully controlled by its own `useState`
- RTL layout via `dir="rtl"` on the wrapping element (inherited from page; no change needed)
- Tailwind classes consistent with existing tables (`border`, `px-2 py-1`, `text-xs`, `text-right`)

---

## Tables Updated

### 1. `AlgorithmPlanningWindow` — proposals table
**New columns** (inserted after score after):
- `דירוג כולל` — cross-proposal rank computed from `norm_score_before`
- `דירוג במשמרת` — `candidate_rank / candidate_pool_size` from backend

**Sortable:** date, both rank columns, norm score before/after  
**Filterable:** soldier name, duty type

### 2. `ExplanationModal` — candidates table
**Sortable:** blocked status, norm before, norm after  
**Filterable:** soldier name  
No new columns.

### 3. `ShiftsPage`
**Sortable:** duty type, start date, end date, required count, assigned count, status  
**Filterable:** duty type name, location name

### 4. `TeamHierarchyPage`
Replaces existing manual `toggleSort` implementation with TanStack Table.  
**Sortable:** personal number, full name, role, node  
**Filterable:** full name, personal number, node name

### 5. `MyDutiesPage`
**Sortable:** duty type, start date, end date  
**Filterable:** duty type name, location name

### 6. `TransparencyPage`
**Sortable:** name, enrolled_at, active_days, cumulative score, normalised score  
**Filterable:** name, unit

### Not updated
`UnitCalendar` detail popups — one is a key-value card, the other is a tiny per-click list. Neither benefits from sort/filter.

---

## i18n

Add to `he.json` under `algorithm`:
```json
"col_slot_rank": "דירוג במשמרת",
"col_batch_rank": "דירוג כולל"
```

Add a shared key for the filter input placeholder (reused across tables):
```json
"table": {
  "filter_placeholder": "סנן..."
}
```

---

## Data Flow

```
_proposals_for_job (backend)
  → iterates AssignmentExplanation.payload.candidates
  → computes candidate_rank, candidate_pool_size
  → returns in ProposalOut

ProposalRow (frontend interface)
  → adds candidate_rank: number | null
  → adds candidate_pool_size: number | null

AlgorithmPlanningWindow
  → computes batch_rank client-side from norm_score_before
  → passes both rank values into DataTable column defs
```

---

## Implementation Order

1. Backend: add `candidate_rank` + `candidate_pool_size` to `ProposalOut` / `_proposals_for_job`
2. Frontend types: update `ProposalRow`
3. Install `@tanstack/react-table`
4. Build `DataTable<T>` component
5. Migrate proposals table (AlgorithmPlanningWindow) — includes both rank columns
6. Migrate ExplanationModal candidates table
7. Migrate ShiftsPage
8. Migrate TeamHierarchyPage (remove manual sort)
9. Migrate MyDutiesPage
10. Migrate TransparencyPage
11. Add i18n keys
