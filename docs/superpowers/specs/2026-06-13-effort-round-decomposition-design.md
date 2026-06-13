# Effort-round decomposition (fair, coverage-safe batching)

**Date:** 2026-06-13
**Status:** Approved for implementation

## Problem

The CP-SAT solver decomposes large runs into batches for tractability. The current
strategy (`_decomposed_solve` → `_calendar_window_batches` in
[solver.py](../../../backend/app/algorithm/solver.py)) splits each eligibility
component into **fixed calendar windows of `batch_window_days` (=28) days**, solved
**sequentially with one-way carry-forward**.

This silently drops duties. A real run (`job f9ec194e`, 410 duty-blocks, 118
soldiers, window 2026-06-14…07-16) left **14 unassigned** — all 4 "labour" shifts on
2026-07-12 (ליווים, עבודות רס"ר, אבות בית, עבודות רס"ר בינוי), each `got=0`.

Root cause (confirmed by faithful replay):

1. `batch_window_days` (28) equals the density window `Wr` (28). A duty on calendar
   day 28 (07-12) still couples — via the 28-day `Wr` rolling window — back to day 0,
   yet it is forced into a **separate, trailing batch**.
2. The first batch (06-14…07-09, 356 duties) is solved first and greedily loads the
   component's **only 60 eligible soldiers** to their density cap.
3. The trailing batch (07-12, 14 duties) inherits a saturated state. One-way
   carry-forward cannot rebalance, so it is `INFEASIBLE` even after the relaxation
   chain exhausts `R→20, T→10`, and the 14 are dropped.

Proof it is a batching artifact, not real over-capacity: solving the component as
**one un-batched problem yields `OPTIMAL, 370/370`, zero relaxation**.

A secondary observation: partial (`FEASIBLE`) jobs are marked `done` and do **not**
run `diagnose_infeasibility`, so a shortfall reports no reason in the UI.

## Goal

Replace calendar-window batching with an **effort-round decomposition** that (a)
never strands a duty on a time boundary, (b) is fair by construction, and (c) stays
tractable. Add reasons for partial jobs.

## Key insight

The calendar split fails because of **myopia**: when the first batch solves June, it
cannot see the July duties, so it has no reason to leave capacity for them. Fix by
flipping the decomposition axis: **keep all duties in scope at all times and
decompose the soldiers instead.** Because every duty is visible in every round,
nothing can be stranded by a boundary.

## Design

Everything below operates **per connected component** of the bipartite eligibility
graph (`_connected_components`), exactly as today. Components with zero eligible
soldiers remain unassignable (already reported by `diagnose_infeasibility`).

### Two-phase, effort-ordered rounds

Sort the component's soldiers by **initial effort ascending** and chunk into
**disjoint groups of `round_soldier_count` (default 50)**, lowest-effort first.

**Phase 1 — disjoint first-pass at base caps.**
For each group in order, solve the **current residual** duties using **only that
group**, at **hard base caps** (`T/Wt`, `R/Wr` from settings), with **soft coverage**
(cover what you can; defer the rest). Freeze the group's assignments (carry forward
as fixed density + effort load), shrink the residual, advance to the next group.
After all groups, every soldier has had exactly **one base-cap turn** and the
residual is small.

**Phase 2 — full pool, graduated relaxation up to the ceilings.**
Solve the remaining residual against the **entire component pool** (all groups), with
soft coverage, using the existing graduated relaxation chain: start at **base** (this
absorbs any spare base capacity from under-filled later groups for free), then step
one constraint at a time (`R` up to `relax_r_ceiling`, then `T` up to `relax_t_ceiling`).

**The relaxation ceilings are an absolute bound.** There is **no** further "last
resort" pass that exceeds them. Whatever cannot be placed within the ceilings is left
**unassigned** and **reported** (see partial-job diagnostics below) — coverage is not
forced at the expense of the rest-window protection. This makes the ceilings the
single, honest control over how much density may be relaxed: setting
`relax_t_ceiling = T` and `relax_r_ceiling = R` disables relaxation entirely, and any
shortfall is surfaced to the planner rather than silently absorbed by overworking
soldiers beyond the configured limit.

### Why the "no relaxation on a soldier's first round" rule needs no per-soldier caps

The phase boundary **is** the first-appearance boundary. Every soldier is a
first-timer in Phase 1 (uniform **base** caps for the whole solve) and a repeater in
Phase 2+ (uniform **relaxable** caps). So the cap regime is a property of the phase,
not the soldier — the existing **global** per-batch relaxation chain already
expresses it. No per-soldier cap bookkeeping is required.

### Tier selection is static; the objective uses live effort

Soldiers are sorted **once** by initial effort. Re-ranking the not-yet-activated pool
between rounds would give the identical order (un-activated soldiers have taken
nothing this run, so their effort is unchanged), so no re-scoring is needed for
selection. The dynamic rebalancing happens inside each solve: the existing
**effort carry-forward** (`effort_offset += effort_per_milli × block_score`) feeds
**live** effort into the next round's L1 fairness objective, so a group that was
loaded in Phase 1 looks high-effort in Phase 2 and is naturally deprioritised.

### Fairness properties

- Lowest-effort soldiers get **first pick** (Phase 1, lowest group first) and fill
  toward base cap first — equalising upward.
- Relaxation (exceeding the rest-window cap) only ever lands on **repeaters**
  (Phase 2+), never on a soldier's first exposure.
- The over-base residual is shared across the **whole** pool in Phase 2 (not dumped
  on the last/highest-effort group, which a single disjoint pass would do).

### Tractability

Phase 1 rounds are always exactly `round_soldier_count` soldiers, and the residual
shrinks each round, so Phase 2 (full pool) runs against only a small leftover. A
component with ≤ `round_soldier_count` soldiers is solved in a **single Phase-1
round = whole solve** (no behaviour change for small components).

## Model changes

### Soft coverage in `build_model` ([model.py](../../../backend/app/algorithm/model.py))

Add a `coverage: str = "hard"` parameter:

- `"hard"` (default, unchanged): `sum(vars_for_duty) == 1`.
- `"soft"`: `sum(vars_for_duty) <= 1`, plus a **max-coverage** objective term
  weighted **above** every existing fairness/spread/reserve tier, so the solver
  always prefers covering one more duty over any fairness gain. Uncovered duties are
  read back by the caller (a duty with no selected var is residual).

No per-soldier cap parameter is needed (see above).

### Orchestration ([solver.py](../../../backend/app/algorithm/solver.py))

New `_effort_round_solve(...)` parallel to `_decomposed_solve`, implementing the
three phases. Reuses `_connected_components`, `_infeasibility_relaxation_chain`
(soft-coverage variant), and the effort/density carry-forward already in
`_decomposed_solve`.

`solve()` selects the decomposition via a new setting (below). Default =
`effort_rounds`. `calendar` preserves today's behaviour; `none` solves whole.

### Settings ([types.py](../../../backend/app/algorithm/types.py))

```python
decomposition: str = "effort_rounds"   # "effort_rounds" | "calendar" | "none"
round_soldier_count: int = 50          # disjoint Phase-1 group size
```

`batching_enabled` is retained for back-compat: `False` ⇒ `decomposition="none"`.

### Partial-job diagnostics ([algorithm_bridge.py](../../../backend/app/services/algorithm_bridge.py))

When a `done` job is **incomplete** (`assigned < len(duties)` — now an expected
outcome when demand exceeds what fits within the relaxation ceilings), run
`diagnose_infeasibility` and store the reasons + the unassigned count on the job (same
JSON shape as the `INFEASIBLE` path), so the UI shows *why* instead of silence.

## Verification

- **Unit (TDD):**
  - soft coverage leaves a genuinely-unplaceable duty unassigned instead of going
    `INFEASIBLE`; hard mode unchanged.
  - an adversarial fixture the calendar batcher drops, effort-rounds covers fully
    **within the relaxation ceilings** (no ceiling-breaking).
  - a component with ≤ `round_soldier_count` soldiers runs exactly one Phase-1 round.
  - an over-capacity instance leaves the excess unassigned (does NOT exceed the
    ceilings) and the result is reported as partial.
- **Real-data benchmark harness** (script, not committed to prod) on `job f9ec194e`
  inputs comparing `{calendar, effort_rounds, none}`: **coverage** (expect
  effort_rounds = 410/410), **effort spread** (fairness), and **solve time**.
- Full existing solver suite (`app/algorithm/`) green, including golden fixtures and
  the large-scale fairness tests, to confirm no regression for batched behaviour.

## Decisions (locked)

1. Coverage is **not** forced. The relaxation ceilings (`relax_t_ceiling`,
   `relax_r_ceiling`) are an **absolute bound** — there is no last-resort pass that
   exceeds them. Anything that cannot fit within the ceilings is left unassigned and
   **reported** (partial-job diagnostics), never silently dropped. (This supersedes an
   earlier "relax beyond ceilings to guarantee coverage" decision.)
2. **Effort-rounds is the default** decomposition. Small components (≤ group size)
   collapse to a single whole-solve round automatically.
3. **Fixed `round_soldier_count = 50`** soldiers per Phase-1 group.
4. Phase 1 groups are **disjoint**; Phase 2 brings the **full** pool back.
5. Tier **selection** is static (initial-effort sort); the **objective** uses live
   carried-forward effort.

## Out of scope

- No change to the eligibility model, reserve linkage, hierarchy proximity, or the
  effort-scoring formula.
- No backtracking/optimality guarantee (Benders / column generation) — the two-phase
  scheme is a heuristic; the benchmark validates it empirically.
- Widening soldier eligibility for high-volume duty types (a real fairness lever
  surfaced during investigation) is a separate, configuration-level concern.

## Benchmark results (job f9ec194e)

Inputs: job `f9ec194e`, 449 duty-blocks (primary + reserve), 118 soldiers,
planning window 2026-06-14 → 07-16. `existing=[]` (proposals were published after
the original run). All three modes run from identical effort-scored soldier inputs,
at the **default** settings (`time_limit_seconds=30`, `batch_time_limit_seconds=10`).

| mode | covered / total | assign-count spread | wall time | status | relaxed |
|---|---|---|---|---|---|
| `calendar` | 402 / 449 | 14 | 72 s | FEASIBLE | R→17, R→19, R→20, T→10 |
| `effort_rounds` | 449 / 449 | 11 | **69 s** | OPTIMAL | — |
| `none` (unbatched) | 449 / 449 | 11 | 39 s | FEASIBLE | — |

`effort_rounds` covers all 449 duties (vs. 402 for calendar, 47 dropped) and
produces a fairer result (spread 11 vs. 14), with zero density-cap relaxation.

**Performance note (Phase 0).** An earlier implementation ran the two-stage
`_solve_soft_coverage` for every group/relaxation step and took **655 s** (and at the
default 10 s batch limit it returned `CANCELLED` — useless in production). Profiling
showed each soft solve burned its entire time budget proving the L1 fairness optimum.
Since the real components are fully coverable at base caps, `_effort_round_solve` now
tries a single **hard-coverage** solve per component first (Phase 0); the soft rounds
only engage for genuinely over-capacity or intractable components. This brought the
run to **69 s at the default settings** (2 CP-SAT solves, one per component, vs. 6+
before) with identical coverage and fairness — and removed the CANCELLED failure
mode. The remaining gap to whole-solve (`none`, 39 s) is just that effort_rounds
solves each connected component separately.
