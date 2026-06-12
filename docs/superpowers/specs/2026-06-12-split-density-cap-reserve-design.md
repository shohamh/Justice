# Split density cap into T (real duties) and R (all duties incl. reserve)

**Date:** 2026-06-12
**Status:** Approved for implementation

## Problem

The CP-SAT solver enforces a single density cap: at most `T` duty-days in any
rolling `W`-day window per soldier ([model.py:182-243](../../../backend/app/algorithm/model.py)).
This cap counts **all** of a soldier's duty-days, reserve and non-reserve alike.
That conflates two different kinds of load: actually standing a duty vs. being on
reserve/standby for one. We want a tighter limit on real duties and a looser
limit on the total.

## Goal

Replace the single cap with two independent per-window caps:

- **T** — non-reserve (real) duty-days only. Baseline `7`.
- **R** — all duty-days, reserve included. Baseline `7`.

Invariant: `T <= R` at all times (baseline and after any relaxation).

## Design

### 1. Settings — `SolverSettings` and `ExistingAssignment` ([types.py](../../../backend/app/algorithm/types.py))

- Add `R: int = 7` to `SolverSettings` next to `T: int = 7`. Update the docstring:
  - `T`: non-reserve duty-day cap per rolling window.
  - `R`: total (incl. reserve) duty-day cap per rolling window.
  - Invariant `T <= R`.
- Add `is_reserve: bool = False` to `ExistingAssignment`. Published reserve duties
  must count toward `R` but not `T`, so the solver needs to know which existing
  assignments are reserve.

### 2. Bridge ([algorithm_bridge.py:352](../../../backend/app/services/algorithm_bridge.py))

When building `ExistingAssignment` from published `DutyAssignment` rows, populate
`is_reserve=a.is_reserve` (the column already exists on `DutyAssignment`).

### 3. Model — window constraints ([model.py:182-243](../../../backend/app/algorithm/model.py))

Per rolling window `[ws, we]` per soldier, emit up to two constraints instead of one:

- **R cap (all duties):** `existing_all + sum(all vars overlapping window) <= R`.
  This is today's logic, renamed to read from `R`.
- **T cap (non-reserve only):** `existing_nonreserve + sum(non-reserve vars overlapping window) <= T`,
  where a var `x[(di, si)]` is included only when `not duty_list[di].is_reserve`.

`existing_fixed` counting splits into two tallies — reserve and non-reserve —
driven by the new `ExistingAssignment.is_reserve` flag. `existing_all` is the sum
of both; `existing_nonreserve` is the non-reserve tally only.

Skip emitting a constraint when both its variable list is empty and its fixed
count is zero (preserves current behavior of not adding vacuous constraints).

### 4. Relaxation chain ([solver.py:288-302](../../../backend/app/algorithm/solver.py))

Replace the current `max_t = max(T, W)` single-cap relaxation. On `INFEASIBLE`,
relax in this order:

1. While `R < 11`: `R += 2` (7 -> 9 -> 11), append `R->{R}` to `relaxed`.
2. Then while `T < 9`: `T += 2` (7 -> 9), append `T->{T}` to `relaxed`.
3. Still infeasible at `T=9, R=11` -> return `INFEASIBLE`.

Relaxation sequence:

```
(T7,R7) -> (T7,R9) -> (T7,R11) -> (T9,R11) -> INFEASIBLE
```

`T <= R` holds at every step. R is loosened first (reserve overload absorbs
pressure before real-duty fairness is touched), then T.

### 5. Tests ([test_solver.py](../../../backend/app/algorithm/tests/test_solver.py))

Add coverage for:

- A soldier capped at `T=7` real duties in a window can still take additional
  **reserve** duties up to `R` in the same window.
- Relaxation order: a batch that is infeasible at baseline relaxes `R` (in hops
  of 2, up to 11) before `T` (up to 9); assert the `relaxed` list ordering.
- Existing **published reserve** duty-days count toward `R` but not `T`
  (via `ExistingAssignment.is_reserve`).

## Out of scope

- No change to the objective/fairness terms, reserve hierarchy proximity, or
  batching.
- No UI/API surface for configuring `R` separately (uses the new default).
