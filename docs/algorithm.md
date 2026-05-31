# Duty Assignment Algorithm

The system uses a **CP-SAT constraint-programming solver** (Google OR-Tools) to automatically assign soldiers to duty blocks in a way that is provably fair. This document explains the goal, the mechanics, and the reasoning behind each design decision.

---

## The core fairness goal

Every soldier accumulates a **normalised score** — their total duty score divided by the number of days they have been active in the unit. Soldiers who joined recently or spent time on reserve/exemption have a lower denominator, so they accumulate score more slowly and end up with a lower normalised score than veterans if assignments were random. The algorithm's primary job is to close that gap: when it finishes, the highest normalised score across all soldiers minus the lowest is at most **K** (default 8 points). This is enforced as a hard constraint, not just a goal, so the solver cannot produce a solution that violates it.

---

## What gets assigned

The inputs are:

| Input | Meaning |
|---|---|
| `SoldierInput` | One soldier: their cumulative score, how many days they have been active, which duty types they are exempt from, and any approved personal constraint dates |
| `DutyBlock` | One shift to fill: a duty type, location, start date, end date, and score-per-day value |
| `ExistingAssignment` | Already-published assignments in or near the planning window — used so the solver sees the full picture when checking spacing |
| `SolverSettings` | Tuning knobs: K, T, W, α, β, time limit, random seed |

The output is a list of `(duty_id, soldier_id)` pairs — one per duty block, with every block covered.

---

## Step 1 — Pre-filtering (domain reduction)

Before the solver even starts, each `(duty, soldier)` pair is tested for two hard disqualifiers:

1. **Exemption** — if the duty's type is in the soldier's `exempted_duty_type_ids`, that pair is dropped entirely. Exemption types map to duty types through an `exemption_duty_type_map`; the bridge service resolves this before calling the algorithm.
2. **Personal constraint** — if any of the soldier's approved constraint date ranges overlaps the duty block, the pair is dropped.

Dropping pairs up-front shrinks the search space significantly before the solver runs.

---

## Step 2 — The CP-SAT model

The solver works with integer variables and linear constraints. Scores are scaled by 1000 internally (milli-units) so all arithmetic stays in integers, which CP-SAT requires.

### Decision variables

For every surviving `(duty d, soldier s)` pair after pre-filtering:

```
x[d, s] ∈ {0, 1}     # 1 = soldier s is assigned to duty d
```

### Hard constraint 1 — Coverage

Every duty block must be assigned to exactly one soldier:

```
∀ d:  Σ_s x[d, s] = 1
```

There are no partial assignments and no unassigned duties in a valid solution.

### Hard constraint 2 — No overlap

A soldier cannot be assigned two duties that share the same calendar day. Existing assignments from outside the planning window are also checked — if a soldier is already working on day `t`, no new duty covering day `t` can be assigned to them:

```
∀ s, ∀ day t:  Σ_{d covering t} x[d, s]  ≤  1   (or = 0 if already assigned that day)
```

### Hard constraint 3 — Fairness (K variance)

For each soldier, the solver computes what their normalised score would be after the new assignments:

```
total_score(s) = cumulative_score(s) + Σ_d  block_score(d) * x[d, s]
norm(s)        = total_score(s) / active_days(s)
```

`block_score(d)` is `score_per_day * number_of_days_in_block`.

The solver then enforces:

```
max_norm - min_norm  ≤  K
```

where `max_norm` and `min_norm` track the highest and lowest normalised scores across all soldiers. This single constraint is what makes the assignment provably fair — the solver cannot produce a plan where one soldier ends up significantly ahead of another, measured on the same per-day basis.

---

## Step 3 — Soft objective (spacing and density)

Once all hard constraints are satisfied, the solver optimises a secondary goal: spread duties out as evenly as possible over time, and avoid piling too many duty-days onto any one soldier in a short window.

### Density penalty

For each soldier and each rolling window of **W days** (default 14), the solver counts how many duty-days fall in that window. If the count exceeds **T** (default 7), the excess is penalised. The penalty is piecewise-linear with increasing marginal costs:

| Excess days | Marginal cost |
|---|---|
| 1st excess day | 1× |
| 2nd–3rd excess day | 3× |
| 4th+ excess day | 5× |

This approximates a quadratic penalty without requiring non-linear terms — the solver naturally fills the cheapest bucket first, so it spreads assignments rather than concentrating them.

### Combined objective

```
maximise   α * min_gap  −  β * density_penalty_total
```

`min_gap` (the spacing reward) is not currently active in the model — it was part of the original design but the objective as implemented focuses purely on the density penalty. The α/β parameters remain as knobs for future tuning.

---

## Step 4 — Infeasibility relaxation chain

Sometimes the combination of hard constraints makes it impossible to produce a valid schedule — usually because there are too few eligible soldiers to satisfy both coverage and the K variance cap simultaneously. Rather than failing silently, the solver runs an automatic relaxation chain:

1. **Try with the original settings.**
2. If infeasible, **increment K by 1** (loosen the fairness bound) and retry. Repeat up to 3 times.
3. If still infeasible, **increment T by 1** (loosen the density cap) and retry once more.
4. If still infeasible after all attempts, return `status="INFEASIBLE"` with a log of which parameters were relaxed and by how much.

The `relaxed` field in `SolverResult` records every relaxation step (e.g. `["K→9", "K→10"]`). The UI surfaces this so the duty manager knows the schedule is slightly less fair than ideal and why.

---

## Step 5 — Explainability

For every assignment in the solution, the explainability module records what happened from every soldier's perspective:

- **Blocked soldiers** — each soldier who could not receive this duty, with the reason: `exemption`, `personal_constraint`, or `overlap` with another assignment.
- **Unblocked soldiers** — their normalised score before and after the hypothetical assignment.
- **Tiebreaker** — if multiple soldiers were unblocked, the note records that the solver chose by lowest post-assignment normalised score (though the actual selection is made holistically by the CP-SAT solver, not by a greedy tiebreaker).
- **Global metrics** — the variance and min-gap figures before and after the full run.

This feeds the "why did I get assigned this?" modal in the frontend.

---

## Step 6 — Reserve selection

After assignments are finalised, a reserve soldier is chosen for each duty block. The algorithm walks the unit's hierarchy outward from the primary assignee, looking for the nearest available substitute:

1. Start at the primary soldier's hierarchy node (their immediate team).
2. Check all soldiers in the same node — anyone who is not the primary, not exempt from this duty type, has no personal constraint on these dates, and has no conflicting assignment.
3. If no one qualifies in the same node, move up to sibling nodes (same parent), then to the parent's siblings, and so on, via a breadth-first search.
4. The first qualifying soldier found at the closest level becomes the reserve.
5. If no reserve can be found anywhere in the hierarchy, the duty is left without one — this is acceptable for rare duty types.

The intent is that the reserve is always the closest organisational neighbour: someone who knows the team, the location, and the role.

---

## Tuning knobs

| Parameter | Default | Effect |
|---|---|---|
| `K` | 8 | Max allowed normalised-score spread across soldiers. Lower = stricter fairness. |
| `T` | 7 | Duty-days per W-day window before density penalty kicks in. |
| `W` | 14 | Rolling window length in days for density calculation. |
| `beta` | 2.0 | Weight of the density penalty in the objective. Higher = more spread-out schedules. |
| `time_limit_seconds` | 30 | How long the solver is allowed to run. Longer = better solutions for large inputs. |
| `seed` | None | Random seed for the solver. Set to a fixed value for reproducible results. |

---

## Code layout

```
backend/app/algorithm/
├── types.py      ← data types: SoldierInput, DutyBlock, SolverSettings, SolverResult, …
├── model.py      ← builds the CpModel: variables, hard constraints, density objective
├── solver.py     ← runs the solver, handles the infeasibility relaxation chain
├── explain.py    ← builds per-assignment and global explainability data
├── reserve.py    ← hierarchy-walk reserve selection
└── tests/
    └── test_solver.py
```

The `algorithm/` package is intentionally pure — it imports only OR-Tools and the Python standard library. No database, no FastAPI, no SQLAlchemy. The `algorithm_bridge` service in `app/services/` is responsible for loading data from the database, calling the pure module, and persisting results.
