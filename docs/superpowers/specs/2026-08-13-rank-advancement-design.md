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
*projected* state — rank, career track, departure — as of the duty's date,
not just today. Exemptions and personal constraints are already date-range
checked against the assignment's own date and need no change.

## Scope

1. Rank ladder becomes structured config (not just an allow-list), shared
   with the frontend via API instead of hand-duplicated.
2. New per-track, per-rank promotion-interval config, admin-editable.
3. Daily worker that promotes soldiers whose `next_rank_date` has arrived,
   auto-chains the next `next_rank_date`, and notifies soldier + commander.
4. Advance-warning notification a configurable number of days before
   promotion.
5. Future-eligibility projection (rank + career track + departure) reusable
   by both the manual assignment-validation path and the CP-SAT solver's
   candidate pool.

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
- Any change to how exemptions/personal constraints are checked — already
  date-range-aware against the assignment's date
  (`eligibility.py::check_soldier_for_assignment` lines 244-296).
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
    {"rank": "רסמ", "months_to_next": null}
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

No new columns on `Soldier`. `next_rank_date` (already exists) is reused
as-is.

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
months_to_next>` for the soldier's initial track. If a commander manually
edits `next_rank_date` afterward (at any point), that edit only affects the
next promotion — once it fires, the worker resumes auto-chaining from the
config table as normal (no permanent opt-out flag).

## Future-eligibility projection

Extend the existing `as_of`/`scheduled_date` projection pattern from
`range_eligibility_projection.py::project_duty_eligibility` — same shape,
new sibling logic covering rank/career instead of weapon quals.

New function, `backend/app/services/rank_eligibility_projection.py::project_soldier_state`
(exact module name TBD at implementation time — may live alongside the
range projection instead if that's a better fit):

- **Input:** soldier, `as_of` date (the duty's scheduled date).
- **Rank projection:** walk forward from the soldier's current
  `rank`/`next_rank_date` through `RankAdvancementInterval`, chaining
  promotions whose computed date falls on or before `as_of`, to determine
  the rank the soldier will hold on that date. (Track-crossing exclusion
  applies here too — the walk never leaves the current track's ladder.)
- **Career-track projection:** re-run the existing `derive_is_career` logic
  using `as_of` as the reference date instead of today.
- **Departure projection:** soldier is excluded if `left_at`/
  `discharge_date` falls on or before `as_of`.
- **Output:** the projected rank + career-track state, fed into the
  existing rank/service-type eligibility rule in
  `eligibility.py::_is_eligible` in place of the soldier's *current* rank.

### Wiring into existing checks

- **`check_soldier_for_assignment`** (`eligibility.py:205-298`): replace the
  hardcoded `today = date.today()` (line 221) with the assignment's own
  date for the rank/service-type/career portion of the check, routed
  through `project_soldier_state`. Exemption/personal-constraint/scheduling
  checks (lines 244-296) are unchanged — already date-range-aware.
- **CP-SAT solver candidate pool** (`backend/app/algorithm`): before
  scoring candidates for a duty, filter out soldiers who fail
  `project_soldier_state`-based eligibility for that duty's date — mirrors
  how `duty_eligibility_worker.py` already rechecks weapon eligibility
  post-hoc, applied instead at pool-build time. Exact integration point to
  be identified during implementation (wherever the current candidate pool
  is assembled before CP-SAT scoring).

## Testing

- Backend: unit tests for the promotion worker (mid-ladder chaining,
  top-of-enlisted-ladder stop, top-of-officer-ladder stop, no
  track-crossing, discharged soldiers skipped, manual override then
  resumed auto-chain), the warning-notification exact-day-match logic, and
  `project_soldier_state` (rank projection across zero/one/multiple
  chained promotions before `as_of`, career-track flip projected forward,
  departure exclusion).
- Backend: `check_soldier_for_assignment` and the CP-SAT candidate-pool
  filter both get cases where a soldier is eligible today but *not* as of
  the future duty date (and the reverse — ineligible today, eligible by
  the future date via projected promotion).
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
