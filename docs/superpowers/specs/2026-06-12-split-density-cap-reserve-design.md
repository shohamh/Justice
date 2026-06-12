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

## Out of scope (Phase 1)

- No change to the objective/fairness terms, reserve hierarchy proximity, or
  batching.

---

# Phase 2 — Configurable T/R/W and relaxation ceilings

Phase 1 hardcodes the caps (`T=R=7`, `W=14`) and the relaxation ceilings
(`R→11`, `T→9`). Phase 2 makes these admin-configurable in system settings and
overrideable per run, following the existing settings pattern in
[algorithm_bridge.py:576-577](../../../backend/app/services/algorithm_bridge.py)
(`job.settings_json.get(key, _setting_int(system_key, default))`).

## System-setting keys

Read in the bridge as fallback defaults; per-run `settings_json` values override them.

| Key | Meaning | Default |
|-----|---------|---------|
| `algorithm.max_duties_per_window` | `T` — non-reserve cap per window | 7 |
| `algorithm.max_total_duties_per_window` | `R` — total cap incl. reserve | 7 |
| `algorithm.window_days` | `W` — rolling window length | 14 |
| `algorithm.relax_t_ceiling` | `T` relaxation ceiling | 9 |
| `algorithm.relax_r_ceiling` | `R` relaxation ceiling | 11 |

`T` and `W` already exist as bridge fallbacks; `R` and the two ceilings are new.

## Design

### 1. SolverSettings ([types.py](../../../backend/app/algorithm/types.py))

Add `relax_t_ceiling: int = 9` and `relax_r_ceiling: int = 11` to `SolverSettings`
(alongside the Phase 1 `T`, `R`, `W`).

### 2. Solver ([solver.py](../../../backend/app/algorithm/solver.py))

Replace the Phase 1 `R_MAX = 11` / `T_MAX = 9` constants with
`current.relax_r_ceiling` / `current.relax_t_ceiling`. Hop size stays 2.

### 3. Bridge ([algorithm_bridge.py:575-585](../../../backend/app/services/algorithm_bridge.py))

Wire `R` and both ceilings from `settings_json` with system-setting fallbacks,
mirroring the existing `T`/`W` lines:

```python
R=int(job.settings_json.get("R", _setting_int("algorithm.max_total_duties_per_window", 7))),
relax_t_ceiling=int(job.settings_json.get("relax_t_ceiling", _setting_int("algorithm.relax_t_ceiling", 9))),
relax_r_ceiling=int(job.settings_json.get("relax_r_ceiling", _setting_int("algorithm.relax_r_ceiling", 11))),
```

### 4. Per-run advanced options ([algorithm.py:53](../../../backend/app/routes/algorithm.py))

Add `R: int = 7` to `SolverSettingsIn`. Relaxation ceilings stay system-only
(not per-run). Frontend `SolverSettings` type, `DEFAULT_SETTINGS`, and the field
list in [AlgorithmRunForm.tsx:163](../../../frontend/src/components/AlgorithmRunForm.tsx)
gain `R`.

### 5. `GET /algorithm/defaults`

New endpoint authorized by `Action.ALGORITHM_RUN`, returning resolved
`{T, R, W}` from system settings (falling back to 7/7/14). The run form fetches
it on mount to initialize the override fields, so a system setting acts as the
per-run default a DM can override. Without this, a non-admin DM cannot read the
admin-only `/admin/system-settings`, and the form's hardcoded `7` would always
win over the system value.

### 6. System Settings UI ([SystemSettingsPage.tsx](../../../frontend/src/pages/SystemSettingsPage.tsx))

New `SETTING_GROUPS` entry — group label **"מגבלות צפיפות (אלגוריתם)"** — with
five `type: "number"` fields:

- `algorithm.max_duties_per_window` — "מכסת תורנויות (ללא רזרבה) בחלון", default 7
- `algorithm.max_total_duties_per_window` — "מכסת תורנויות כוללת (כולל רזרבה) בחלון", default 7
- `algorithm.window_days` — "אורך החלון (ימים)", default 14
- `algorithm.relax_t_ceiling` — "תקרת הרפיה — תורנויות (ללא רזרבה)", default 9
- `algorithm.relax_r_ceiling` — "תקרת הרפיה — תורנויות כוללת", default 11

### 7. Validation — enforce `T <= R` (HTTP 400)

- **System settings `PUT`** ([system_settings.py:38](../../../backend/app/routes/system_settings.py)):
  after merging the update over existing values, reject with 400 if any of:
  `T > R`, `relax_t_ceiling > relax_r_ceiling`, `T > relax_t_ceiling`,
  `R > relax_r_ceiling`. Resolve each via the merged map, falling back to the
  table defaults when a key is absent.
- **Job submit `POST /algorithm/jobs`** ([algorithm.py:329](../../../backend/app/routes/algorithm.py)):
  reject with 400 (`detail="t_exceeds_r"`) if `body.settings.T > body.settings.R`.

## Phase 2 out of scope

- Relaxation hop size stays a code constant (2).
- `K`, `alpha`, `beta`, `time_limit_seconds` per-run defaults stay hardcoded in
  the form (not loaded from system settings) — only the density caps are.
