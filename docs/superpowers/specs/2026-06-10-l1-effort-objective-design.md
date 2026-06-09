# Design: L1 Effort-Score Objective for CP-SAT Solver

**Date:** 2026-06-10  
**Status:** Approved

## Problem

The CP-SAT solver currently optimises for `score_per_day` fairness (cumulative score ÷ active days) using a min-max objective. This has two problems:

1. **Wrong metric.** The transparency UI shows `עומס רבעוני` (quarterly effort score), not `score_per_day`. The solver optimises for something different than what is displayed to the commander.
2. **Weak objective.** Min-max only watches the two extreme soldiers (highest and lowest). The entire middle of the distribution is unconstrained — soldiers at effort=0.3 and effort=0.7 get no attention as long as the max and min are acceptable.

The effort fields (`effort_offset`, `effort_per_milli`) are already computed and injected into every `SoldierInput` before the solver runs — they are just never read by `model.py`.

## Goal

Replace the `score_per_day` min-max objective with an L1 effort-score objective that:
- Uses `עומס רבעוני` as the single fairness metric (consistent with the UI)
- Minimises spread across **all** soldiers, not just the two extremes
- Scales to 5,000 soldiers without model-size problems

## L1 vs L2

**L2 (squared deviations):** penalises outliers quadratically — an effort score of 0.9 when the target is 0.5 contributes `0.16` while 0.6 contributes only `0.01`. Aggressive about pulling outliers in. Requires `AddMultiplicationEquality` per soldier in CP-SAT — slower to solve.

**L1 (absolute deviations):** penalises outliers linearly. Tolerates unavoidable outliers (soldiers with high historical load or limited eligibility) and focuses solver effort on the controllable majority. Maps directly to linear constraints — faster to solve. Chosen approach.

## Core Objective

For each soldier `si`, the projected effort score after new assignments is linear:

```
projected_effort[si] = effort_offset[si]
                      + effort_per_milli[si] × Σ(_block_score(d) × x[di,si])
```

Where:
- `effort_offset[si]` = `int(historical_effort_score × EFFORT_SCALE)` — fixed constant
- `effort_per_milli[si]` = `int(C_over_D / unit_score_milli × EFFORT_SCALE)` — fixed constant
- `_block_score(d)` = score of duty block in milli-units (×1000) — fixed constant
- `x[di,si]` = assignment decision variable (0/1)

Introduce one free integer variable `target` (the L1 centre, driven to the median by the solver) and one deviation variable `dev[si]` per soldier:

```
dev[si] >= projected_effort[si] - target
dev[si] >= target - projected_effort[si]
dev[si] >= 0

Minimise: Σ dev[si] + dist_term
```

`dist_term` is the existing reserve hierarchy proximity penalty — unchanged, naturally scaled small enough to act as a tiebreaker.

## Scaling

| Approach | Aux variables | Scales to 5k? |
|---|---|---|
| Current min-max | O(1) | ✓ |
| **New L1 (this design)** | **O(n)** | **✓** |
| Pairwise L1 | O(n²) — 25M at 5k | ✗ |

At 5,000 soldiers: 5,001 extra variables, 10,000 extra constraints. Negligible.

## Variable Bounds

`EFFORT_SCALE = 1_000_000_000`

- `projected_effort[si]`: `[0, 2 × EFFORT_SCALE]`
- `dev[si]`: `[0, 2 × EFFORT_SCALE]`
- `target`: `[0, 2 × EFFORT_SCALE]`

Derivation: `effort_offset` ∈ [0, EFFORT_SCALE]. Maximum increment from duties: when `C_over_D = 1` and the soldier receives all duties, the increment equals exactly `EFFORT_SCALE`. Bound of `2 × EFFORT_SCALE` covers both.

## Edge Cases

**`effort_per_milli = 0`** (soldier not active in planning window, or all duties have zero score): `projected_effort[si]` is a constant. `dev[si]` is fixed regardless of assignments — the solver correctly ignores this soldier when distributing duties.

**No history (first run, W_i = 0 for all):** `C_over_D = 1` and `effort_offset = 0` for all soldiers. `effort_per_milli` is equal for all (same `C_over_D`, same `unit_score_milli`). The objective degenerates to distributing score evenly — correct behaviour for a fresh start.

**Ineligible soldiers:** A soldier exempt from most duty types structurally keeps low effort. The L1 objective accepts their constant `dev[si]` contribution and focuses solver effort on the others. Min-max would fixate on them; L1 does not.

## What Gets Removed

- `AddDivisionEquality` (one per soldier — a known CP-SAT bottleneck for large instances)
- `norm` IntVar per soldier
- `max_norm_var`, `min_norm_var`
- `all_norm_exprs`, `eligible_norm_exprs`
- `hist_penalty_terms`
- `alpha_int` weighting on max/min norm (alpha setting becomes unused; can be removed or repurposed later)

## Files Touched

| File | Change |
|---|---|
| `app/algorithm/model.py` | Replace norm/division objective with L1 effort objective |
| `app/algorithm/types.py` | Add `EFFORT_SCALE = 1_000_000_000` constant |
| `app/services/effort_score.py` | Import `EFFORT_SCALE` from `app.algorithm.types` instead of defining it |
| `app/algorithm/tests/test_solver.py` | Update tests: pass effort fields on `SoldierInput`, verify L1 behaviour |

**No changes to:** `algorithm_bridge.py`, `solver.py`, `reserve.py`, `explain.py`, `diagnose.py`, any route or service code.

## What Stays the Same

- All hard constraints: coverage (every duty assigned), no-overlap, density (T/W rolling window)
- Reserve hierarchy proximity term (`dist_term`) — unchanged, acts as tiebreaker
- `SoldierInput.effort_offset` and `effort_per_milli` — already set correctly by `inject_effort_scores` in the bridge
- The bridge's call to `inject_effort_scores` before `solve()` — already in place
