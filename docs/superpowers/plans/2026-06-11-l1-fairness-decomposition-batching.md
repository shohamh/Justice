# Plan: L1-variance fairness via eligibility decomposition + chronological batching

Date: 2026-06-11
Status: IMPLEMENTED — validated on real data (792/792 coverage, effort dispersion
shrinks, officers balanced by effort); fairness test suite migrated to L1 +
count-space; settings + UI added. Density made adaptive (relax T→W per-batch only
when tight). Secondary tiebreak = prior-effort + count-spread (cheap, no squares).

## Goal

Replace the assignment objective with **L1 variance of load** (sum of absolute
deviations from a common centre) so fairness equalises the *whole* distribution,
including interior sub-populations (e.g. officers) the current `max−min` spread
objective is blind to. L1 is intractable on the full model, so make it tractable
by **decomposing** every run into small, independently-solvable pieces:

1. **Connected components** of the soldier↔duty eligibility graph (exact split).
2. **Chronological batches** of ≤ `batch_size` duties within each component
   (greedy, with load + density feedback between batches).

Every individual solve is then tiny, so L1 applies uniformly. All batching knobs
live in a dedicated **System Settings** section.

## Why this shape (recap of the investigation)

- `max−min` spread only constrains the two global extremes (always enlisted),
  so officers in the low-load interior were balanced only by raw counts →
  אינפרה 13 (loaded) kept getting duties while רוקט 5 sat idle.
- L1 fixes that (every soldier contributes a `|deviation|` term) but adding ~118
  deviation vars to the ~74k-var full model makes CP-SAT find **no feasible
  solution** in the time budget — confirmed 4 ways (free μ, fixed μ, scaled,
  count-space). It is the L1 *structure* at *scale*, not the magnitude.
- Decomposition shrinks every solve: the officer-only sub-problem already solves
  OPTIMAL in 9.4s. Chronological batching shrinks the large (enlisted) component
  the same way, so L1 is tractable everywhere.

## Fairness metric: count-space EFFORT (effort × K)

L1 needs small integers, so we scale the **effort score itself** by a resolution
`K = effort_resolution` and round. This keeps the metric = effort (all the
W / unit-score normalisation stays baked into `effort_offset` and
`effort_per_milli`); the only loss is rounding below `1/K`.

```
DIV            = EFFORT_SCALE // K                              # e.g. K=10000 → DIV=100000
count_offset_i = effort_offset_i // DIV                         # prior effort, small int (officers ~0..207)
weight_i(duty) = max(1, (effort_per_milli_i × block_score(duty)) // DIV)   # effort one duty adds, floored ≥1
total_i        = count_offset_i + Σ_{d assigned to i} weight_i(duty)
```

A reserve's `block_score` is already `standby_multiplier`× its primary, so
`weight(reserve) ≈ 0.2 × weight(primary)` for free; the `max(1, …)` floor keeps a
reserve worth ≥ 1 unit even at modest K (this is what "scale by 5" really
controls — the resolution).

Per-batch objective (maximise the negation):

```
minimize   L1   = Σ_i | total_i − μ |          (μ FIXED to the post-batch mean)
        +  ε · reserve_proximity                (tiny tiebreaker, unchanged)
```

μ is a **constant** (`(Σ count_offset + Σ new weight) / n`), so the deviation
vars decouple → fast. No `max`/`min`/spread anywhere.

CRITICAL — compute effort ONCE over the **full** duty set (not per batch).
`effort_per_milli` divides by the run's total unit-score; feeding a batch's small
duty subset would re-inflate it (one duty would dwarf the history). So
`compute_effort_data`/`inject_effort_scores` run once globally, before batching.

Cross-batch feedback stays in effort space: after a batch, bump each soldier's
`effort_offset += effort_per_milli_i × (assigned block score)`, so the next
batch's `count_offset` reflects what they just received. No separate load field.

## Architecture

```
solve(soldiers, duties, existing, settings, reserve_dist)
 ├─ if not batching_enabled: single L1 solve (current behaviour, whole problem)
 └─ else:
     components = connected_components(soldiers, duties)      # exact
     for comp in components:
         comp_duties sorted by (start_date, id)
         carry_existing = existing ∩ comp
         for batch in chunks(comp_duties, batch_size):
             model = build_model(comp_soldiers, batch, carry_existing, settings, dist_subset)
             result = relaxation_chain(model)          # per-batch T-relax, seeded
             assignments += result
             carry_existing += result                  # density/no-overlap feedforward
             for s: s.recent_load += load assigned to s in this batch   # L1 feedforward
     merge all assignments; reserve-linking over the combined result (unchanged)
```

- **Exactness**: components share no soldier/duty → no optimality loss.
- **Greedy**: batches within a component are solved in date order and cannot be
  revised — acceptable for a soft fairness goal; mitigated by chronological order
  (coupled duties land together), load feedforward, and the T-relaxation chain.
- **Determinism**: each batch solve keeps the fixed seed (already added).

## Settings (new "פירוק ואצווה" / Batching section)

Backend reads via `get_setting` with matching inline defaults; frontend adds a
`SETTING_GROUPS` entry in `SystemSettingsPage.tsx`.

| key | type | default | meaning |
|---|---|---|---|
| `algorithm.batching_enabled` | boolean | `true` | decompose + batch, else single whole-problem solve |
| `algorithm.batch_size` | number | `50` | max duties per chronological batch |
| `algorithm.batch_time_limit_seconds` | number | `10` | solver budget per batch |
| `fairness.effort_resolution` | number | `10000` | K — effort×K granularity in count-space (higher = finer) |

`SolverSettings` gains: `batching_enabled`, `batch_size`,
`batch_time_limit_seconds`, `effort_resolution`. The bridge populates them from
system settings (like the existing `T`/`W`/`alpha` reads).

## Implementation steps

1. **types.py** — `SolverSettings` gains the four fields above. (No new
   `SoldierInput` field — we reuse `effort_offset`/`effort_per_milli`.)
2. **algorithm_bridge.py** — read the new settings into `SolverSettings`. Effort
   is already computed once globally; nothing else needed there.
3. **model.py** — replace the spread+count objective with the **count-space
   effort L1**: `count_offset = effort_offset // DIV`,
   `weight = max(1, per_milli × block_score // DIV)`, fixed-μ deviations,
   reserve-proximity ε. `DIV = EFFORT_SCALE // effort_resolution` from settings.
4. **solver.py** — new orchestration: `connected_components()` (union-find over
   eligibility), chronological batching, per-batch relaxation chain, merge.
   Between batches: add solved assignments to `existing`, and bump each soldier's
   `effort_offset += per_milli × assigned_block_score`. `batching_enabled=False`
   keeps the single whole-problem path.
5. **SystemSettingsPage.tsx** — new section + four `SettingDef`s (Hebrew labels).
6. **Tests**
   - `connected_components` unit test (disjoint officer/enlisted; bridged case).
   - batching balances load (officer case: אינפרה 13 → fewer than רוקט 5).
   - full-instance run is tractable within the per-batch budget.
   - rewrite the effort/spread-based fairness tests (`test_fairness*.py`,
     `test_model*.py`) to assert **load-balance** properties under L1.

## Risks / open questions

- **Greedy quality** on large components — accepted for fairness; revisit if a
  globally optimal schedule is ever needed.
- **Bridged components** (a permissive duty type allowing both officers and
  enlisted) collapse into one big component → that component is still batched, so
  still tractable, just greedier. OK.
- **UI/metric drift** — algorithm now equalises load, transparency shows effort.
  Follow-up to align the display.
- **Existing fairness test suite** is effort/spread-based and will need a
  meaningful rewrite to load-based assertions (largest single chunk of work).
