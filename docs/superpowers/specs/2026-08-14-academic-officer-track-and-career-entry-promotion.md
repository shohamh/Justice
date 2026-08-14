# Academic officer track & קבע-entry auto-promotion — design

Date: 2026-08-14

## Background

The rank advancement feature (shipped on `dev`) currently treats "officer" as
a single flat ladder: קמא → סגמ → סגן → קאב → סרן → קאם → רסן → סאל → אלמ →
תאל → אלוף → רב אלוף (`ENLISTED_RANKS`/`OFFICER_RANKS` in
`backend/app/services/eligibility.py:18-23`, mirrored into an advancement
ladder in `backend/app/services/rank_advancement.py`). Two gaps surfaced
from real usage:

1. Academic officers (קצינים אקדמאים) actually advance קמא → קאב → קאם — a
   different, shorter path than the standard combat-officer ladder. קאב and
   קאם already exist as rank values (both already קבע-only per
   `RANK_TRACK_COMPATIBILITY`), but the current single ladder chains them
   into the standard path (…סגן → **קאב** → סרן → **קאם** → רסן…), which is
   wrong for an academic officer and right for a standard one — the same
   rank name means a different "next rank" depending on which track the
   officer is actually on.
2. Some ranks' promotion should fire automatically the moment a soldier
   enters קבע, even if their scheduled `next_rank_date` for that rank
   hasn't arrived yet. No such trigger exists today — advancement is purely
   `next_rank_date <= today`.

## Scope

1. Split the advancement ladder (not the general rank-validity list) into
   three tracks: enlisted (unchanged), officer/regular (קמא, קאב, קאם
   removed), officer/academic (קאב → קאם, new).
2. New per-(track, rank) config flag, `advance_on_career_entry`, editable
   in the same admin screen as `months_to_next`, with an explanatory
   tooltip. When set, the daily worker promotes a soldier off that rank
   the moment they enter קבע, regardless of `next_rank_date`.
3. The future-eligibility projection (`project_soldier_state`, used by
   both the CP-SAT solver and the manual duty-assignment check) accounts
   for this early trigger when projecting a soldier's rank forward to a
   future duty date.

## Out of scope

- קמא is removed from every advancement ladder (see below) — promoting a
  קמא officer to either track becomes a manual action, using the existing
  profile-edit path. This isn't new work; that path already supports
  setting `rank` directly.
- `eligibility.py`'s `ENLISTED_RANKS`/`OFFICER_RANKS` (the full
  rank-validity lists used by gender/service-type checks, בה"ד 1
  inference, `RANK_TRACK_COMPATIBILITY`) are **not** touched — only the
  advancement-specific ladders in `rank_advancement.py` change. A soldier
  can still hold, and be validated as holding, any of these ranks; only
  *automatic* advancement chaining changes.
- No change to `Soldier.is_career`'s existing (already-known-stale)
  semantics elsewhere in the app. The קבע-entry trigger deliberately never
  reads that stored column — it recomputes career status live from
  `mandatory_end_date`/`discharge_date` every time, so there is no
  backfill/rollout risk from historically-stale data (see "קבע-entry
  detection" below).
- No UI change to how a soldier's rank is manually set (existing
  profile-edit/field-update-approval/import paths already handle it,
  including for קמא).

## Ladder restructuring

`backend/app/services/rank_advancement.py` currently aliases
`ENLISTED_RANKS`/`OFFICER_RANKS` directly as its ladders. It gets its own
explicit ladder definitions instead:

```python
ENLISTED_LADDER = ENLISTED_RANKS  # unchanged, 9 ranks
OFFICER_LADDER = ["סגמ", "סגן", "סרן", "רסן", "סאל", "אלמ", "תאל", "אלוף", "רב אלוף"]
OFFICER_ACADEMIC_LADDER = ["קאב", "קאם"]

Track = Literal["enlisted", "officer", "officer_academic"]
_LADDERS: dict[Track, list[str]] = {
    "enlisted": ENLISTED_LADDER,
    "officer": OFFICER_LADDER,
    "officer_academic": OFFICER_ACADEMIC_LADDER,
}
```

`get_track("קמא")` returns `None` (present in neither ladder) —
`get_next_rank("קמא")` therefore also returns `None`, so no automated
chain ever starts from קמא. `get_track("קאב")`/`get_track("קאם")` now
unambiguously resolve to `"officer_academic"`.

No DB schema change needed for the `track` column itself — `track` on
`RankAdvancementInterval` is a free-text column (`Text`, not a DB enum),
so `"officer_academic"` is just a new value in existing rows. Admins
configure `months_to_next` for `(officer_academic, קאב)` and
`(officer_academic, קאם)` the same way they already do for other ranks.

### Consumers needing the third track

- `GET /soldiers/rank-ladder` (`rank_advancement.py::get_rank_ladder`)
  already iterates `_LADDERS.items()`, so it automatically returns a third
  `"officer_academic"` key once the ladder dict above ships — no route
  change needed, only the frontend's shape assumption.
- `frontend/src/constants/ranks.ts`'s `useRankLadder()` hook and its
  consumers (`RegisterPage.tsx`, `EnrollmentApprovalModal.tsx`) currently
  assume two groups (`enlisted`/`officer`). They need a third group. Exact
  UI treatment (a labeled sub-section under "officer," or a separate
  top-level group) — implementer's call, matching how the page already
  presents the enlisted/officer split.
- The admin interval-editor section in `SystemSettingsPage.tsx` (`RankAdvancementIntervalsSection`)
  iterates the ladder to render one row per rank — needs to render the new
  `officer_academic` group's rows too (קאב, קאם), and NOT render a row for
  קמא (since it has no ladder entry at all now — confirm the ladder
  endpoint's response simply omits קמא, so "don't render a row for a rank
  not in the ladder" falls out naturally rather than needing a special
  case).
- The `PUT /soldiers/rank-advancement-intervals` validation (added in the
  final-review fix wave — `track` ∈ {enlisted, officer}, `rank` in that
  track's ladder) needs `"officer_academic"` added to the allowed `track`
  values.

## New config field — `advance_on_career_entry`

New column on `RankAdvancementInterval`: `advance_on_career_entry: bool`,
`server_default=false`. New Alembic migration (simple `add_column`, no
data migration — defaults to off for every existing row).

Admin UI (`RankAdvancementIntervalsSection`): a checkbox column next to
the existing `months_to_next` input, per rank row. A question-mark icon
next to the column header, with a tooltip/popover (existing UI pattern in
this codebase — implementer to confirm and match) explaining:

> "אם מסומן, החייל יקודם אוטומטית לדרגה הבאה ברגע שהוא נכנס לשירות קבע, גם
> אם התאריך המתוכנן לקידום לדרגה זו עדיין לא הגיע."

("If checked, the soldier is automatically promoted to the next rank the
moment they enter career service, even if the scheduled promotion date for
this rank hasn't arrived yet.")

## קבע-entry detection (live, not stored)

`Soldier.is_career` is a stored column that is only recomputed when a
soldier's profile is edited (`update_soldier_profile`,
`approve_field_update`) — it is not kept fresh daily, and is therefore
unreliable for detecting "did this soldier cross into קבע today." Per
explicit decision, the trigger **never reads or compares that stored
column**. Instead:

```python
def _career_entry_date(mandatory_end_date: date | None, discharge_date: date | None) -> date | None:
    """The first calendar day this soldier is career, or None if they
    never reach it (no mandatory_end_date, or discharged before/at it)."""
    if mandatory_end_date is None:
        return None
    if discharge_date is not None and discharge_date <= mandatory_end_date:
        return None
    return mandatory_end_date + timedelta(days=1)
```

This mirrors `derive_is_career`'s existing True/False boundary exactly
(`eligibility.py:95-111`) but as a single deterministic date rather than a
per-call boolean — computed fresh from `mandatory_end_date`/
`discharge_date` every time, with no persisted "was career" state to go
stale. A soldier who has been career for a year computes the exact same
`_career_entry_date` as one who became career yesterday; there is nothing
to backfill or accidentally re-trigger on rollout day.

### Daily worker

New step in `rank_advancement_worker.py`, run before (or interleaved with,
implementer's call as long as no soldier is double-processed in one run)
the existing `_promote_due_soldiers`:

1. Load the set of `(track, rank)` pairs with `advance_on_career_entry =
   True` from `RankAdvancementInterval`. If empty, skip entirely (cheap
   short-circuit — expected to be a small, deliberately-curated set).
2. Query soldiers whose current `rank` is in that set, excluding
   discharged/departed soldiers (same filter `_promote_due_soldiers`
   already uses).
3. For each, compute `_career_entry_date(soldier.mandatory_end_date,
   soldier.discharge_date)`. If it's `<= today`, promote now via the same
   `_promote_soldier` logic already used for date-due promotions
   (rank → next rank, `current_rank_since`/`next_rank_date` recomputed,
   `notify_rank_advanced` fired) — bypassing the `next_rank_date <= today`
   gate entirely for this soldier.

This is naturally idempotent per soldier: promotion changes their `rank`,
so the next day's query (keyed on current `rank` being in the flagged set)
only re-matches if the *new* rank is *also* flagged — which is a
legitimate, if unusual, admin configuration (chaining several
career-entry-triggered promotions), not a bug.

## Future-eligibility projection

`project_soldier_state` (`rank_eligibility_projection.py`) currently walks
the rank chain purely off `next_rank_date`. It's extended so that, at each
step, the effective advancement date is the **earlier** of the scheduled
`next_rank_date` and (if the current rank has `advance_on_career_entry`
set) `_career_entry_date(soldier.mandatory_end_date,
soldier.discharge_date)`:

```python
effective_date = next_date  # scheduled date, as today
if advances_on_career_entry(session, track, rank):  # new lookup, interval_cache-aware
    entry_date = _career_entry_date(soldier.mandatory_end_date, soldier.discharge_date)
    if entry_date is not None and (effective_date is None or entry_date < effective_date):
        effective_date = entry_date
if effective_date is None or effective_date > as_of:
    break  # no further advancement projected by as_of
```

The existing `interval_cache` mechanism (added in the shipped feature's
final-review fix wave, to avoid a DB query per chain step) is extended to
also carry `advance_on_career_entry` per `(track, rank)`, loaded once per
`bulk_future_ineligible_duty_blocks` call rather than adding a second
uncached lookup.

## Testing

- Ladder: `get_track`/`get_next_rank` for קמא (None), קאב/קאם under both
  `officer` (should no longer resolve — confirm removed) and
  `officer_academic` (correct chain, קאם is top-of-ladder), and the
  regular officer ladder skipping קאב/קאם correctly (סגן → סרן directly).
- Worker: a soldier holding a flagged rank whose `mandatory_end_date` was
  yesterday gets promoted today regardless of `next_rank_date`; one whose
  `mandatory_end_date` is still in the future does not; one who was
  already career for months when the checkbox gets turned on for their
  rank IS promoted the next worker run (this is correct, not a backfill
  bug — the live check has no memory of "already been career a while");
  a discharged soldier is excluded even if otherwise flagged.
- Projection: a soldier not yet career, holding a flagged rank, with a
  `next_rank_date` far in the future but a `mandatory_end_date` that falls
  before a projected duty date, is correctly projected as promoted by that
  duty date (via the career-entry path, not the scheduled one) — and the
  reverse (scheduled date earlier than career-entry date) still uses the
  scheduled date.
- Frontend: rank ladder fetch/display handles three groups; admin interval
  table renders the checkbox + tooltip and round-trips
  `advance_on_career_entry` through `PUT /soldiers/rank-advancement-intervals`;
  `track` validation accepts `"officer_academic"`.
