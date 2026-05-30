# Slice 10 — Algorithm Integration with Shifts

**Date:** 2026-05-30
**Status:** Approved (brainstorm 2026-05-30).
**Depends on:** Slice 8 (eligibility), Slice 9 (shifts entity).

## Goal

Replace the current synthesized-DutyBlock approach in the algorithm bridge with real `duty_shifts` from the DB. The DM selects specific shifts when running the algorithm; each shift with `required_count=N` expands to N `DutyBlock` objects. Resulting assignments link back to their parent shift via `duty_shift_id`.

---

## 1. Algorithm bridge changes

### 1.1 Replace `load_duty_blocks` with `load_duty_blocks_from_shifts`

```python
def load_duty_blocks_from_shifts(
    session: Session,
    *,
    shift_ids: list[uuid.UUID],
) -> tuple[list[DutyBlock], dict[uuid.UUID, uuid.UUID]]:
    """Expand duty_shifts into DutyBlocks.

    Each shift with required_count=N generates N DutyBlocks with identical
    date range and duty_type. Returns (blocks, block_to_shift_map) where
    block_to_shift_map maps each ephemeral DutyBlock.id → shift_id for
    use during persistence.
    """
```

For each shift, generate `required_count` DutyBlock objects — each gets a fresh `uuid.uuid4()` as its ephemeral ID, same `duty_type_id`, `duty_location_id`, `start_date`, `end_date`, `score_per_day` from the duty type.

The returned `block_to_shift_map` is used by `persist_results` to set `duty_shift_id` on each created `DutyAssignment`.

### 1.2 Update `persist_results`

When inserting a `DutyAssignment`, look up `block_to_shift_map[assignment.duty_id]` and set `da.duty_shift_id`.

### 1.3 Eligibility: merge exemptions + eligibility requirements

`load_soldier_inputs` already builds `exempted_duty_type_ids` from soldier exemptions. Add a second pass that reads `DutyTypeRequirements` for all active duty types and applies the eligibility checks from Slice 8 §4.1, adding additional `duty_type_id`s to each soldier's `exempted_duty_type_ids`.

New helper: `compute_eligibility_exclusions(session, soldiers, settings) -> dict[uuid.UUID, set[uuid.UUID]]`

---

## 2. AlgorithmJob model changes (migration 0019)

Replace the current `duty_type_ids` (JSONB) and `duty_location_id` columns on `algorithm_jobs` with:

```sql
shift_ids  jsonb NOT NULL    -- array of duty_shift uuid strings
```

Remove `duty_type_ids` and `duty_location_id` columns (they're no longer needed — shift carries type + location).

---

## 3. API changes

### 3.1 `POST /api/algorithm/jobs` request body

```json
{
  "shift_ids": ["<uuid>", "..."],
  "mode": "shadow",
  "settings": { "K": 8, "T": 7, "W": 14, "alpha": 1.0, "beta": 2.0, "time_limit_seconds": 30 }
}
```

`planning_start` and `planning_end` are inferred from the selected shifts (min start_date, max end_date). No longer supplied by the caller.

### 3.2 Validation

- All `shift_ids` must exist and belong to the DM's scope.
- At least one shift must be unfilled or partial (reject if all selected shifts are already full).
- Only shifts with `fill_status != 'full'` are run through the algorithm; already-full slots are skipped.

---

## 4. Frontend changes

### 4.1 AlgorithmPlanningWindow

Replace date range + duty type multi-select + location select with:

- A date range filter to browse shifts
- A list of matching shifts with fill status badges
- Multi-select checkboxes to include/exclude specific shifts in the run
- "הרץ אלגוריתם" button enabled only when ≥ 1 shift selected

The proposals table stays unchanged (it shows per-assignment results), but each proposal row now also shows which shift it belongs to.

### 4.2 Shifts page

After a successful algorithm run, the shifts calendar automatically reflects the new fill status (poll-on-navigate or cache-bust).

---

## 5. Testing

- **Bridge unit tests**: `load_duty_blocks_from_shifts` — required_count=3 expands to 3 blocks, block_to_shift_map correct; eligibility exclusions applied correctly (null fields blocked, thresholds respected).
- **Integration**: full run from `POST /api/algorithm/jobs` with real shift_ids → proposals created with correct `duty_shift_id` → fill status updated on the shift.
- **Regression**: existing algorithm golden suite tests remain passing (they use the pure algorithm module directly, not the bridge, so no changes needed there).
