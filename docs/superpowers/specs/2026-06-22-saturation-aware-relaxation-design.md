# Saturation-Aware Relaxation & Diagnosis — Design

**Date:** 2026-06-22
**Status:** Approved (brainstorm 2026-06-22)

## Background

Investigated a job (`cb31641e-f43f-45c2-a1ee-76a8580816d3`) that finished `FEASIBLE` at 794/802 duties after exhausting the relaxation ladder (`R→17,19,20`, `T→10`). Replay analysis (`app/scripts/replay_solver.py` + ad-hoc instrumentation) found two distinct problems:

1. **The relaxation ladder doesn't actually use the loosened ceiling for most of the run.** In `_effort_round_solve` (the default `effort_rounds` decomposition), `_relax_step` only loosens R/T for the *leftover residual* in Phase 2 — by then Phase 1 (six disjoint effort-sorted rounds) has already consumed the eligible pool for a date window using the **base** R/T (15/8), locking in carry-forward assignments that can't be undone. Empirically, raising the **base** R/T to 20/10 from the start (not just the post-hoc ceiling) took roughly the same wall time (142s vs. 154s) and produced 801–802/802 instead of 794/802 — full restart with a higher base beats patching the residual.
   - Note: `calendar`/`none` decomposition (`_infeasibility_relaxation_chain`) does NOT have this bug — it already re-solves the whole batch from scratch on every relax step, and each step is cheap (~0.1s to prove `INFEASIBLE` on a hard `==1` model). The fix below is scoped to `effort_rounds` only.
2. **When duties genuinely can't be covered, the system doesn't tell the user why in an actionable way.** The Issues tab (`frontend/src/components/IssuesTab.tsx`) shows a generic reason ("constraints were relaxed but not enough soldiers found") and recommends raising `relax_r_ceiling`/`relax_t_ceiling` — which is actively misleading once problem (1) is fixed and we've proven raising R/T doesn't help (genuine same-day double-booking saturation: all eligible soldiers for that duty type are already committed to *other* duties on the exact same calendar days).

## Scope

- `app/algorithm/solver.py` — replace per-residual relaxation in `_effort_round_solve` with a binary-search-driven full component restart.
- `app/algorithm/explain.py` (or new `app/algorithm/saturation.py`) — saturation cluster analysis for duties that remain unassigned after the restart search is exhausted.
- `app/algorithm/types.py` — new `SaturationCluster` dataclass; extend `BatchResult` with `saturation_clusters`.
- `app/services/algorithm_bridge.py` — serialize the new field into `job.batch_results` (JSONB).
- `frontend/src/components/IssuesTab.tsx` — render saturation clusters with named competing duty types; suppress the R/T-ceiling recommendation for duties whose failure is saturation-dominated.

**Out of scope:** changing the `calendar`/`none` decomposition paths (not buggy), changing the relaxation ladder step sizes/ceilings themselves, any new settings UI.

## Part 1 — Binary-search restart in `_effort_round_solve`

### Current behavior (Phase 2)

```python
if residual:
    current = dataclasses.replace(base_settings)
    while residual:
        res = _solve_soft_coverage(full_pool, residual, carry, current, ...)
        if res.assignments:
            _absorb(res)
            if not residual: break
        label = _relax_step(current)
        if label is None: break
```

This only ever re-solves the shrinking `residual` set against the `carry` already locked in by Phase 0/1 at the **base** R/T. Raising the ceiling here can't undo Phase 1's choices.

### New behavior

Replace Phase 1 + Phase 2 with a search over **ladder positions**. A "ladder position" is a cumulative point along the existing `_relax_step` sequence (`R→17`, `R→19`, `R→20`, `T→10`, ... up to each setting's ceiling) — position 0 is the unrelaxed base settings.

For each candidate position, **one probe** = a full redo of Phase 0 (whole-component hard solve) + Phase 1 (disjoint effort-sorted rounds) + a single Phase 2 soft-coverage pass, all using that position's R/T as the base (not a post-hoc relax). This reuses the existing Phase 0/1/2 code as the "solve at this position" primitive — no separate code path needed, just parameterize the entry R/T.

```python
def _probe_at_position(component_soldiers, component_duties, existing, settings, position) -> ProbeResult:
    """Run Phase 0+1+2 fresh with R/T set to `position`'s cumulative ladder value.
    Returns assignments, assigned_count, and whether the deciding solve status was
    PROVEN (OPTIMAL/INFEASIBLE) vs time-boxed (FEASIBLE/UNKNOWN).
    """
```

**Search procedure** (per component):

1. Run position 0 (base, already what happens today) — this is the existing unmodified Phase 0/1/2 call. If it fully covers the component, done, no search needed.
2. Otherwise binary-search the ladder positions `[1, N]` (`N` = ceiling) for the **lowest position that achieves exact full coverage** (`assigned_count == duty_count`):
   - Maintain `best = ProbeResult` seen so far (prefer exact full coverage; otherwise prefer higher `assigned_count`). Never let a later probe overwrite `best` with a worse result.
   - Test the midpoint; if full coverage, search the lower half for an even cheaper position (still keeping this result as a candidate final answer); if not full coverage, search the upper half.
   - **Extended-time retry on every probe**: if a probe's deciding solve status is not *proven* (i.e., it hit its time budget and returned `FEASIBLE`/`UNKNOWN` rather than `OPTIMAL`/`INFEASIBLE`), re-run that same probe once with an extended time budget (e.g. 2× `batch_time_limit_seconds`) before accepting its result. This prevents wall-clock jitter (we observed 801 vs. 802/802 on nominally identical settings) from causing an incorrect "not fully coverable" verdict or from picking too-loose a ladder position.
3. If no position (including the ceiling) achieves full coverage even after the extended-time retry, the shortfall is **proven structural** — use `best` as the final result for this component and hand its unassigned duties to the Part 2 saturation analysis.

### Cost

Each probe costs roughly one full component solve (~140s for the investigated job, comparable to today's single failed run). Binary search bounds the number of probes to `O(log N)` where `N` is the number of ladder steps (typically ≤ 5: 3 R-steps + up to 2 T-steps with default ceilings) — worst case ~3 probes (~7 minutes) instead of a hypothetical 5 sequential full restarts (~12 minutes), while still finding the minimal sufficient relaxation.

### Why this doesn't change `_infeasibility_relaxation_chain`

That function already restarts the whole batch/problem from scratch on every step and each step is cheap to prove infeasible — no restart-cost problem to fix, and binary search would save negligible time there. Left as-is.

## Part 2 — Saturation cluster diagnosis

Runs once per component, only over duties still unassigned after Part 1's search is exhausted (a proven shortfall).

### Clustering

Group unassigned duties into clusters by **transitive date overlap** (interval-graph connected components, same union-find technique already used for eligibility components in `_connected_components`, but keyed on date ranges instead of soldier eligibility).

### Per-cluster analysis

For each cluster, using the **final** chosen assignment set (existing + new) — no need to thread intermediate carry state:

1. Compute the cluster's union of eligible soldiers (ignoring overlap — same eligibility filter as `_eligible_pairs`: exemption, personal constraint dates, hierarchy node).
2. For each eligible soldier, check whether they're already committed (an assignment, existing or new, overlapping the cluster's date range). Tally how many are free vs. busy.
3. For busy soldiers, look up *what* they're committed to (the other assignment's `duty_type_id`) and tally counts per competing duty type.
4. Emit a `SaturationCluster`:
   ```python
   @dataclass
   class SaturationCluster:
       date_from: date
       date_to: date
       shift_ids: list[uuid.UUID]          # the unfilled shifts in this cluster
       eligible_pool_size: int
       free_count: int                      # should be 0 for a genuine saturation cluster
       competing_duty_types: list[tuple[uuid.UUID, int]]   # (duty_type_id, count), sorted desc
   ```

This reuses the blocking-constraint classification already in `explain.py` (`exemption` / `personal_constraint` / `overlap`), extended to run for *unassigned* duties instead of only for the winning candidate of successful assignments.

### Wiring

- Add `saturation_clusters: list[SaturationCluster] = field(default_factory=list)` to `BatchResult` (`types.py`).
- `algorithm_bridge.py`'s `_br_to_dict` serializes the new field (duty_type_id → str, dates → isoformat) same as other `BatchResult` fields.

## Part 3 — Frontend (`IssuesTab.tsx`)

1. **Render saturation clusters** as a new section (or integrated into the existing unfilled-shifts table) showing, per cluster: date range, affected shift names, and an explanation sentence built from `competing_duty_types` resolved through the existing `dutyTypes` prop (currently unused — `_dutyTypes` — this wires it up), e.g.:
   > "57 eligible soldiers for this shift are already on duty during 2026-07-06–2026-07-15 — 42 on **שמירה כללית**, 15 on **תורנות מטבח**. Consider rescheduling or widening eligibility for this period."
2. **Suppress the misleading recommendation**: in `analyzeBatches`, when a batch's unfilled shifts are covered by a `saturation_clusters` entry (i.e., the shortfall was proven structural, not a relaxation-ceiling miss), don't count that batch's relaxations toward `rCeilingHitCount`/`tCeilingHitCount` for the "raise relax_r_ceiling" recommendation. Since Part 1 already searches the full ladder before declaring a proven shortfall, in practice this recommendation should rarely fire anymore — but keep the logic correct in case `relax_r_ceiling`/`relax_t_ceiling` themselves are raised in settings (a new, higher ceiling the binary search hasn't tried yet) and a future job run could still benefit.
3. Replace the generic per-shift `reason` string with cluster-derived text when the shift belongs to a `saturation_cluster`; keep the existing generic reasons as fallback for shifts not part of any cluster (e.g. node-eligibility-zero cases already handled elsewhere).

## Testing

- `app/algorithm/tests/test_solver.py`: unit tests for the binary-search restart — a fixture where base R/T fails, a higher (non-ceiling) position succeeds, and confirm the search lands on that minimal position with the right number of probes (not exhaustive linear). A fixture where even the ceiling fails (proven), confirming `best` (highest partial coverage) is kept and exposed for Part 2.
- A fixture replicating the investigated saturation case (overlapping same-day duties with a pool of soldiers exactly fully committed elsewhere) to verify `SaturationCluster` output: correct `free_count == 0`, correct competing duty type tally.
- Extended-time retry: a fixture forcing a time-boxed (`UNKNOWN`) status on the first attempt and confirming a second, longer attempt is made before the position is rejected.
- Frontend: `IssuesTab` snapshot/unit test asserting cluster text renders and the R/T recommendation is absent when `saturation_clusters` is non-empty for all unfilled shifts in a job.
