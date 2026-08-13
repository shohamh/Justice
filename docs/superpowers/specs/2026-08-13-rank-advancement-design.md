# Rank advancement & future-eligibility projection — design

Date: 2026-08-13

## Background

Soldiers currently have a free-text `rank` field and an unused
`next_rank_date` column (`backend/app/db/models.py:56-57`). The rank ladder
itself exists only as two hardcoded, ordered Python lists —
`ENLISTED_RANKS`/`OFFICER_RANKS` in `backend/app/services/eligibility.py:18-24`
— duplicated by hand in `frontend/src/constants/ranks.ts:3-11`.

This feature adds automatic rank advancement (a soldier's rank updates on
`next_rank_date`, with notification to the soldier and their commander), and
extends duty-assignment eligibility checking so it accounts for a soldier's
*projected* state — rank, career track, mitvahim/alal recency, driving-license
expiry, exemptions, and departure — as of the duty's date, not just today.

Investigating the CP-SAT solver path surfaced a broader existing gap than
just rank: `eligibility.py::_is_eligible` already evaluates mitvahim/alal
recency and driving-license expiry correctly *for whatever `today` it's
given* — but `compute_eligibility_exclusions` (`eligibility.py:171-202`) is
only ever called **once**, at a single `reference_date`, for an entire
multi-week/multi-month solver run (`algorithm_bridge.py:240-242`), and its
result is stored as one static `exempted_duty_type_ids` set per soldier
(`SoldierInput.exempted_duty_type_ids`) applied identically to every duty
block regardless of that block's own date. The same is true of exemptions:
`algorithm_bridge.py`'s exemption-to-duty-type mapping (lines ~210-217) is
evaluated once at `as_of`, so an exemption that starts later in the planning
window (or one that would end before it) is invisible to the solver. Manual
assignment validation (`check_soldier_for_assignment`) already handles
exemptions correctly against the specific assignment's date range — only the
CP-SAT solver path has this gap, because it precomputes one exclusion set
per soldier for the whole run instead of per (soldier, duty-block-date)
pair. Personal-constraint checking in the solver is already correctly
date-based (`solver.py:305-317`, checked against each duty block's own
dates) and needs no change.

## Scope

1. Rank ladder becomes structured config (not just an allow-list), shared
   with the frontend via API instead of hand-duplicated.
2. New per-track, per-rank promotion-interval config, admin-editable —
   editing it recomputes `next_rank_date` for affected soldiers who don't
   have a manual override.
3. Daily worker that promotes soldiers whose `next_rank_date` has arrived,
   auto-chains the next `next_rank_date`, and notifies soldier + commander.
4. Advance-warning notification a configurable number of days before
   promotion.
5. Future-eligibility projection (rank + career track + departure) reusable
   by both the manual assignment-validation path and the CP-SAT solver's
   candidate pool.
6. CP-SAT solver: make eligibility exclusion evaluation per-(soldier,
   duty-block-date) instead of once per solve, covering every factor that
   can change value within a planning window — projected rank (via #5),
   mitvahim/alal recency, driving-license expiry, and exemptions (including
   ones that start or end within the window). This generalizes the existing
   per-block-date pattern already used for weapon qualification
   (`weapon_ineligible_duty_block_ids`).

## Out of scope

- Adding a dedicated "קבע entry date" field — career-track status is already
  derived (`derive_is_career`) from `mandatory_end_date` vs. a reference
  date; the projection reuses that derivation as-of a future date instead of
  today. No schema change needed.
- Auto-advancement crossing from the enlisted ladder onto the officer
  ladder — becoming an officer requires a separate manual/commissioning
  process. Auto-chaining only moves a soldier up within their current
  track's ladder, and stops (clears `next_rank_date`) at the top of that
  ladder.
- Manual-path exemption/personal-constraint checking
  (`eligibility.py::check_soldier_for_assignment` lines 244-296) — already
  date-range-aware against the assignment's date, unchanged. Only the
  CP-SAT solver's exemption handling changes (see scope item 6), since that
  path currently evaluates exemptions once at solve-start rather than per
  duty-block date.
- Solver-side personal-constraint checking (`solver.py:305-317`) — already
  correctly checks each duty block's own dates against each soldier's
  approved constraint date ranges. No change.
- Weapon/range qualification projection — already handled by
  `range_eligibility_projection.py`; this feature composes with it rather
  than modifying it.

## Data model

### Rank ladder as structured config

Keep `ENLISTED_RANKS`/`OFFICER_RANKS` as the canonical ordered lists in
`eligibility.py`, but stop hand-duplicating them in the frontend. Add:

**`GET /soldiers/rank-ladder`** — returns both tracks in order, plus each
rank's configured advancement interval (see below), so the frontend derives
everything from one source:

```json
{
  "enlisted": [
    {"rank": "טוראי", "months_to_next": 4},
    {"rank": "רבט", "months_to_next": 8},
    ...
    {"rank": "רנג", "months_to_next": null}
  ],
  "officer": [
    {"rank": "קמא", "months_to_next": 6},
    ...
    {"rank": "רב אלוף", "months_to_next": null}
  ]
}
```

`frontend/src/constants/ranks.ts` fetches and caches this instead of
hardcoding the arrays; existing helpers (`RANK_TRACK_COMPATIBILITY`,
`derive_is_career`-equivalent, `derive_bahad1_graduate`) keep their current
duplicated form — out of scope to unify beyond the ladder itself.

### New table — `RankAdvancementInterval`

```
track: enum(enlisted, officer)
rank: text (must match a rank in that track's ladder)
months_to_next: int, nullable (null = top of ladder, no further advancement)
```

Seeded from a sensible default on migration; editable via a new admin
settings screen (mirrors the pattern used for other admin-configurable
business rules in `frontend/src/pages/settings` — confirm exact location
during implementation).

### New global setting

`rank_advancement_warning_days: int` — single value, not per-rank, alongside
other global settings (confirm storage mechanism during implementation —
likely the same settings table/loader used for existing global toggles in
`settings_loader.py`).

### New columns on `Soldier`

- `next_rank_date_overridden: bool`, default `false`. Distinguishes an
  auto-computed `next_rank_date` from one a commander manually set, so that
  editing `RankAdvancementInterval` only recomputes the soldiers who
  haven't been manually overridden. See "Reacting to interval-config
  changes" below.
- `current_rank_since: date`, nullable. The date the soldier's current
  `rank` took effect (enlistment date for their initial rank, or the
  promotion date for any subsequent one). Needed to recompute
  `next_rank_date` correctly when interval config changes after the fact.

## Promotion worker

New `backend/app/services/rank_advancement_worker.py::run_rank_advancement_worker`,
following the existing daily-poll pattern (`duty_eligibility_worker.py`,
86400s loop, wired into `main.py` lifespan alongside the other workers).

Each run:

1. **Promote:** query soldiers where `next_rank_date <= today` and not yet
   discharged/departed (`left_at`/`discharge_date` not passed). For each:
   - Determine current track (enlisted vs. officer) from which ladder
     `rank` belongs to.
   - Look up the next rank in that same track's ladder. If none (top of
     ladder), clear `next_rank_date` to `null` and stop — no promotion
     possible past the top.
   - Otherwise: set `rank` to the next rank, look up that new rank's
     `months_to_next` from `RankAdvancementInterval` for the same track, and
     set `next_rank_date = today + months_to_next` (auto-chain). If
     `months_to_next` is null (new rank is top of ladder), leave
     `next_rank_date = null`.
   - Fire the existing event-triggered notification system: one
     notification to the soldier, one to their commander, via whatever
     `NotificationType` pattern `notifications.py` already uses for
     soldier-state-change events (new `RANK_ADVANCED` type, following the
     existing enum + `_FRONTEND_PATHS` pattern at
     `notifications.py:39-68`).
2. **Warn:** separately, query soldiers where
   `next_rank_date == today + rank_advancement_warning_days` (exact match,
   so it fires once per soldier per promotion cycle without needing extra
   "already warned" state) and fire a second new `RANK_ADVANCEMENT_SOON`
   notification type to the soldier + commander.

### Initial `next_rank_date`

Set at enlistment: when a soldier is created/enrolled with an initial rank,
`next_rank_date = enlistment_date + <that rank's configured
months_to_next>` for the soldier's initial track, with
`next_rank_date_overridden = false`.

If a commander manually edits `next_rank_date` via the soldier profile/edit
endpoint (promotion, delay, or correction), set
`next_rank_date_overridden = true`. That edit only affects the *next*
promotion — once the worker fires it, it auto-chains the following date
from the config table and resets `next_rank_date_overridden = false`, so
auto-computation resumes as normal (no permanent opt-out).

### Reacting to interval-config changes

When an admin edits `RankAdvancementInterval` (adds/changes
`months_to_next` for a rank+track), recompute `next_rank_date` for every
soldier where `next_rank_date_overridden = false` and current `rank`
matches the changed row's track+rank: new `next_rank_date` =
`current_rank_since + new months_to_next`. Soldiers with
`next_rank_date_overridden = true` are left untouched.

`current_rank_since` must be set everywhere `rank` is written: the
enlistment-time initializer (= `enlistment_date`) and the promotion worker
(= `today`, the promotion date).

## Future-eligibility projection

### Rank/career projection

New function, `backend/app/services/rank_eligibility_projection.py::project_soldier_state`:

- **Input:** soldier, `as_of` date (the duty's scheduled date).
- **Rank projection:** walk forward from the soldier's current
  `rank`/`next_rank_date` through `RankAdvancementInterval`, chaining
  promotions whose computed date falls on or before `as_of`, to determine
  the rank the soldier will hold on that date. (Track-crossing exclusion
  applies here too — the walk never leaves the current track's ladder.)
- **Career-track projection:** re-run the existing `derive_is_career` logic
  (`eligibility.py:95-111`, which already accepts a `today` reference-date
  parameter — no signature change needed) using `as_of` in place of today.
- **Departure projection:** soldier is excluded if `left_at`/
  `discharge_date` falls on or before `as_of`.
- **Output:** the projected rank + career-track state.

### Why rank is the only field that needs projecting

`eligibility.py::_is_eligible` (lines 124-168) already takes an explicit
`today` parameter and correctly re-evaluates mitvahim/alal recency
(`(today - last_mitvahim_date) > mitvahim_months`), driving-license expiry
(`military_driving_license_expiry < today`), and service-type/קבע
(`inferred_service_type(soldier, today)`, which itself recomputes from
`mandatory_end_date`/`discharge_date` rather than reading a stored flag) —
all correctly, for whatever date is passed in. The one thing it does NOT
recompute is rank: `allowed_ranks` checks `soldier.rank` directly, the
soldier's *current* stored value, regardless of `today`. `_is_eligible`
gets a new optional parameter, `rank_override: str | None = None`, used in
place of `soldier.rank` for the `allowed_ranks` check when provided —
callers that don't pass it are unaffected. `is_officer` needs no projected
override: auto-chaining never crosses the enlisted/officer track boundary
(see "Out of scope"), so a soldier's officer status can't change via
advancement.

### Per-duty-block-date exclusion (CP-SAT path)

New function, `backend/app/services/rank_eligibility_projection.py::bulk_future_ineligible_duty_blocks(session, *, soldier_ids, duties) -> dict[uuid.UUID, set[uuid.UUID]]`,
mirroring `weapon_eligibility.py::bulk_ineligible_duty_blocks`'s exact
shape/contract — for each soldier, the set of duty-block ids (among the ones
passed in) they will NOT be eligible for, evaluated at that block's own
`start_date`:

- Group blocks by distinct `start_date` (evaluating once per distinct date,
  not once per block) and call `project_soldier_state` once per
  (soldier, date) to get the projected rank for that date.
- For each block, resolve its `DutyType.requirements`, and call
  `_is_eligible(soldier, reqs, mitvahim_months=.., alal_months=..,
  today=block.start_date, rank_override=projected.rank)` — this single call
  now correctly covers rank, service-type/career, mitvahim/alal recency,
  gender, bahad1, and driving-license expiry, all as of that block's date.
- Additionally check exemptions active as of `block.start_date` (reusing
  the same `SoldierExemption`/`ExemptionType`/`ExemptionDutyTypeMap`/
  `ExemptionDutyLocationMap` lookup `check_soldier_for_assignment` already
  does at lines 244-273, adapted to a specific block's duty type/location
  and date instead of a specific assignment) — a global exemption, or one
  mapped to the block's duty type or location, active on that date,
  excludes the block.
- Departure (`discharge_date`/`left_at` on or before the block's date)
  excludes the block.

### Wiring into existing checks

- **`check_soldier_for_assignment`** (`eligibility.py:205-298`): replace the
  hardcoded `today = date.today()` (line 221) with the assignment's own
  date for the rank/service-type/career portion of the check, passing
  `rank_override=project_soldier_state(session, soldier=soldier,
  as_of=assignment.start_date).rank` into `_is_eligible`.
  Exemption/personal-constraint/scheduling checks (lines 244-296) are
  unchanged — already date-range-aware.
- **CP-SAT solver candidate pool**: `algorithm_bridge.py` calls
  `bulk_future_ineligible_duty_blocks` alongside (not replacing) the
  existing `bulk_ineligible_duty_blocks` weapon-eligibility call, storing
  the result in a new `SoldierInput.future_ineligible_duty_block_ids`
  field — same shape as the existing
  `SoldierInput.weapon_ineligible_duty_block_ids`, checked at the same
  three call sites in `solver.py` (x2) and `model.py` (x1) that already
  check the weapon-eligibility field. The existing static
  `SoldierInput.exempted_duty_type_ids` /
  `compute_eligibility_exclusions`/single-`as_of` exemption computation in
  `algorithm_bridge.py` stays in place for the callers that still want a
  same-day snapshot (e.g. `diagnose.py`/`explain.py`'s "why isn't this
  soldier assigned today" explanations, and the active-days/fairness
  calculation, which is about historical days and must keep using `as_of`
  as "today") — it is not removed, just no longer the sole gate for the
  solver's candidate pairing.

## Testing

- Backend: unit tests for the promotion worker (mid-ladder chaining,
  top-of-enlisted-ladder stop, top-of-officer-ladder stop, no
  track-crossing, discharged soldiers skipped, manual override then
  resumed auto-chain, `current_rank_since` set correctly on both
  enlistment and promotion), the interval-config-change recompute
  (overridden soldiers untouched, non-overridden soldiers recomputed from
  `current_rank_since`), the warning-notification exact-day-match logic, and
  `project_soldier_state` (rank projection across zero/one/multiple
  chained promotions before `as_of`, career-track flip projected forward,
  departure exclusion).
- Backend: `check_soldier_for_assignment` and the CP-SAT candidate-pool
  filter both get cases where a soldier is eligible today but *not* as of
  the future duty date (and the reverse — ineligible today, eligible by
  the future date via projected promotion).
- Backend: `bulk_future_ineligible_duty_blocks` gets cases for each
  newly-date-sensitive factor independently: mitvahim/alal recency crossing
  the threshold between two block dates in the same run, driving-license
  expiring between two block dates, an exemption starting after `as_of` but
  before a later block's date, and an exemption ending before a later
  block's date despite being active at `as_of`. Plus a same-run case
  combining two soldiers with different block-date outcomes, to confirm the
  per-block-date grouping doesn't leak one soldier's projection into
  another's.
- Backend: `_is_eligible`'s new `rank_override` parameter — a case proving
  it's used in place of `soldier.rank` when provided, and that omitting it
  preserves every existing caller's current behavior (regression guard for
  `check_soldier_for_assignment`'s and `compute_eligibility_exclusions`'s
  existing call sites, which don't pass it).
- Frontend: new admin settings screen for `RankAdvancementInterval` +
  warning-days setting; rank ladder now fetched from
  `GET /soldiers/rank-ladder` instead of hardcoded — update any test fixture
  that currently imports the hardcoded `ranks.ts` arrays directly.

## Open questions for implementation time

- Exact admin-settings screen location/pattern to follow in the frontend.
- Exact global-settings storage mechanism for `rank_advancement_warning_days`.
- Exact CP-SAT candidate-pool integration point in `backend/app/algorithm`.
- Default seed values for `RankAdvancementInterval` per rank (real-world
  time-in-rank durations) — needs domain input, not derivable from code.
