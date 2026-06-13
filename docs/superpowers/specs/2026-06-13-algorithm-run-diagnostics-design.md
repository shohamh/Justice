# Algorithm Run Diagnostics Design

**Goal:** Show rich per-batch and per-shift detail after an algorithm run — how the solver split groups, how it batched, how each batch went, and actionable guidance for partially-filled or INFEASIBLE results.

---

## Background

The solver decomposes the scheduling problem into connected components (groups of soldiers+shifts linked by eligibility) and then calendar-window batches within each component. Currently this structure is lost after the solve — the job detail view shows only a flat proposal list and a generic failure panel. Commanders can't tell which shifts failed to fill, why, or what to change.

---

## Data Model

### New `BatchResult` dataclass (pure algorithm layer, `types.py`)

```python
@dataclass
class BatchShiftFill:
    shift_id: uuid.UUID
    required_count: int
    assigned_count: int

@dataclass
class BatchResult:
    batch_index: int              # global sequential index across all components
    component_index: int          # which connected component
    date_from: date
    date_to: date
    duty_count: int               # total duty slots in batch
    soldier_count: int
    assigned_count: int
    unassigned_count: int
    outcome: str                  # "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "CANCELLED"
    relaxations: list[str]        # e.g. ["R→17", "R→19"]
    wall_time_seconds: float
    shifts: list[BatchShiftFill]  # per-shift fill detail (shift_id filled in by bridge)
```

`SolverResult` gains `batch_results: list[BatchResult]` (default empty list).

### DB changes

**`algorithm_job` table:**
- New column `batch_results` JSONB nullable — stores the serialised `list[BatchResult]` after the bridge post-processes shift IDs.

**`duty_assignment` table:**
- New column `batch_index` integer nullable — set when the assignment is created, so proposals can be grouped/filtered by batch in the frontend.

### Alembic migration
One migration covering both columns.

---

## Backend Architecture

### `solver.py` — `_decomposed_solve`

After each batch solve completes, collect:
- `component_index` (loop variable already available)
- `batch_index` (global counter across all components)
- date range from the batch's duty list
- `duty_count`, `soldier_count`, `assigned_count`, `unassigned_count`
- `outcome`, `relaxations`, `wall_time_seconds` from `SolverResult`
- `shifts`: list of `BatchShiftFill` with `shift_id=None` (placeholder — DutyBlock IDs only at this point; bridge fills in shift UUIDs)

The solver does not know about DutyShifts (it works with DutyBlocks). The `shifts` list is populated with `shift_id=None` and the block-level counts; the bridge replaces `None` with real shift IDs using `block_to_shift`.

### `algorithm_bridge.py` — post-processing

After `solve()` returns, iterate `result.batch_results` and:
1. For each `BatchShiftFill` with `shift_id=None`, look up the DutyBlock ID in `block_to_shift` to get the real `DutyShift.id`. Group by shift ID within the batch to aggregate `required_count` / `assigned_count`.
2. Serialise the final `batch_results` list to JSON and write to `job.batch_results`.
3. When persisting assignments in `persist_results`, stamp each `DutyAssignment.batch_index` from the assignment's batch.

### `routes/algorithm.py` — API

`JobOut` gains:
```python
batch_results: list[dict] = Field(default_factory=list)
```

`ProposalOut` gains:
```python
batch_index: int | None = None
```

`get_job` endpoint populates both from the DB columns.

---

## Frontend Architecture

### Three tabs on the job detail panel

Tabs: **הצעות** (Proposals) | **אצוות** (Batches) | **בעיות** (Issues)

Rendered only for `status == "done"` or `status == "failed"`. A job with `status == "done"` but with `unassigned_count > 0` in any batch gets a warning badge on the Issues tab.

---

### Proposals tab (enhanced)

- New **Batch** column: `B{batch_index}` badge, clickable (navigates to that batch in the Batches tab).
- Filter dropdown: "כל האצוות" / "אצווה 1" / "אצווה 2" / ...
- Batches with `unassigned_count > 0` are indicated with an amber warning icon on their batch badge.

---

### Batches tab

Accordion structure: **Component** → **Batch rows** → **Shift fill table** (on expand).

**Component header:** "קבוצה {N} — {soldier_count} חיילים, {batch_count} אצוות"

**Batch row columns:**
| תאריכים | משבצות | שובץ | לא שובץ | תוצאה | הרפיות | זמן |
| date_from–date_to | duty_count | assigned_count | unassigned_count | OPTIMAL/FEASIBLE/INFEASIBLE badge | "R→17" chips | wall_time_seconds |

**Shift fill table** (expanded per batch):
| משמרת | תאריכים | נדרש | שובץ | חסר |
| shift name | dates | required_count | assigned_count | unassigned_count (red if > 0) |

---

### Issues tab

Three sections, shown only when there are issues:

**1. משמרות לא מאוישות במלואן (Partially/fully unfilled shifts)**

Table: shift name · date range · required · assigned · missing slots · batch · reason (INFEASIBLE / relaxation maxed out / no eligible soldiers)

**2. אבחון (Diagnostics)**

Auto-generated bullet list based on batch_results analysis:
- "N אצוות הגיעו לתקרת R ({relax_r_ceiling}) — שקול להגדיל"
- "N אצוות הגיעו לתקרת T ({relax_t_ceiling}) — שקול להגדיל"
- "N אצוות נשארו חסרות פתרון — ייתכן שאין מספיק חיילים כשירים"

**3. המלצות והרצה מחדש (Recommendations)**

Based on diagnostics, suggest specific param adjustments:
- If R ceiling was hit: suggest `relax_r_ceiling = current + 4`
- If T ceiling was hit: suggest `relax_t_ceiling = current + 2`
- If INFEASIBLE after full relaxation: suggest checking eligibility / exemptions, no param fix available

**"הרץ שוב עם הגדרות מומלצות" button** — pre-fills `AlgorithmRunForm` with:
- Same shift IDs
- Suggested parameter overrides (only the ones with recommendations)
- Switches to the run form panel

---

## New Frontend Components

| Component | Responsibility |
|-----------|---------------|
| `AlgorithmJobTabs.tsx` | Tab container (Proposals / Batches / Issues) |
| `BatchesTab.tsx` | Accordion of components → batches → shift fill |
| `IssuesTab.tsx` | Diagnostics + recommendations + re-run button |

`AlgorithmProposalTable.tsx` — add batch column and filter dropdown (modify existing).

`AlgorithmPage.tsx` — replace current single-view with `AlgorithmJobTabs` when job is done/failed.

---

## Error Handling

- `batch_results` is nullable — jobs run before this feature have no batch data. The Batches and Issues tabs show "אין נתוני אצוות לריצה זו" for legacy jobs.
- `batch_index` on assignments is nullable for the same reason — the Proposals tab omits the Batch column if no proposals have a batch_index set.

---

## Testing

**Backend unit tests:**
- `test_solver.py`: `_decomposed_solve` returns `SolverResult.batch_results` with correct counts per batch
- `test_algorithm_bridge.py`: bridge correctly maps DutyBlock IDs → DutyShift IDs in `batch_results`; `batch_index` stamped on assignments

**Integration tests:**
- `test_algorithm_routes.py`: `GET /algorithm/jobs/{id}` returns `batch_results` list and proposals with `batch_index`

**Frontend tests:**
- `BatchesTab.tsx`: renders component accordion correctly from mock data
- `IssuesTab.tsx`: generates correct recommendations for each diagnostic case
