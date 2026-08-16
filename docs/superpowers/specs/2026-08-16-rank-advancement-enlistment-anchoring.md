# Rank advancement enlistment anchoring and scoped correction — design

Date: 2026-08-16

## Goal

Make automatic next-rank dates follow the configured cumulative rank ladder
from enlistment for an initial/manual rank, while continuing to chain dates
from the actual date of a system promotion. Give only sufficiently senior
commanders and duty managers the authority to correct rank and next-rank data.

This is an extension of the existing rank-advancement design in
`2026-08-13-rank-advancement-design.md` and the academic-officer extension in
`2026-08-14-academic-officer-track-and-career-entry-promotion.md`.

## Domain rules

### Initial and system-promoted schedules

When a rank is initially supplied or manually set without an explicit next
rank date, calculate the date for the *next* rank by summing the configured
`months_to_next` values from the beginning of the soldier's active advancement
track through the current rank, then adding that total to `enlistment_date`.

For example, with the enlisted defaults `10, 11, 11, 24`, a soldier whose
current rank is סמ"ר receives a next רס"ל date at enlistment plus 56 months.
The calculation uses database-configured intervals, including explicit NULL
intervals; if the cumulative path cannot be calculated, the automatic date is
NULL. If enlistment is unavailable, retain the existing fallback of anchoring
the current-rank interval at the available initialization date.

Initial/manual rank writers are registration, enrollment approval, profile
editing, and import. They set `current_rank_since` to enlistment (or the
fallback date) because the rank's actual attainment date is unknown.

When the worker promotes a soldier, it sets `current_rank_since` to the
promotion date and calculates the successor's next date from that date. All
later automatic promotions therefore chain from the system promotion event,
not from enlistment.

An explicit next-rank date is a manual correction. It sets
`next_rank_date_overridden = true`, is used for the next promotion, and is not
recomputed by interval-setting changes. When that promotion happens, the
worker clears the override and resumes normal chaining. Clearing the date in
the profile editor restores the automatic cumulative calculation.

### Rank correction authority

Admins retain the existing administrative bypass. For non-admins, a rank,
rank-track, or next-rank-date write is permitted only when the actor is either:

1. a commander with a directly commanded hierarchy node at level מדור or
   higher, or
2. a duty manager with a scope root at level מדור or higher,

and that qualifying commanded/scope root contains the target soldier's
hierarchy node. A lower-level commander or duty manager cannot bypass this by
editing another profile field or by calling the API directly. Initial public
registration and authorized imports remain unchanged.

Non-rank profile edits retain their existing authorization. A qualifying
commander or duty manager gets a narrow profile-modal correction flow for rank,
rank track, and next-rank date; they do not gain general profile-edit access
through this feature.

## Backend design

- Add a rank-advancement helper that computes the cumulative enlistment-based
  next date for a rank and track, using `RankAdvancementInterval` values.
- Route all initial/manual rank writers through that helper. Keep the worker's
  current promotion-date calculation unchanged.
- Make `next_rank_date` a real profile-update input and preserve the existing
  override flag semantics. Distinguish an omitted field from an explicit null
  so clearing the field can reset the automatic schedule.
- Add a shared authority predicate that checks commander roots and duty-manager
  scope roots against the fixed מדור threshold and target containment. Reuse
  the repository's hierarchy-level ordering semantics (lower numeric rank is
  more senior).
- Enforce the predicate at the profile endpoint and every existing backend
  path that directly changes an enrolled soldier's rank data, while leaving
  initial registration/import behavior intact.
- Return a per-soldier capability flag so the frontend can hide rank-edit
  controls when the actor is not eligible. Return the next-rank date and
  override state in the soldier DTO.

No database migration is required: the date, override, and current-rank-since
columns already exist.

## Frontend design

- Add `next_rank_date` and its override/capability fields to the soldier API
  type.
- Show the calculated/manual next-rank date in the profile view.
- Keep the existing full profile edit for admins/duty managers who already
  have it. For a qualifying commander or duty manager without general profile
  authority, show only the rank/rank-track/next-date correction controls.
- Show a clear Hebrew label for the next-rank date and indicate that a saved
  date is a manual correction. Clearing it returns to automatic calculation.
- Keep lower-level commander/duty-manager controls read-only, with backend
  authorization remaining authoritative.

## Tests

Backend tests cover:

- cumulative enlisted calculation for סמ"ר → רס"ל and configured interval
  overrides;
- missing enlistment fallback and an uncomputable cumulative path;
- registration, import, enrollment approval, and profile initialization using
  enlistment anchoring;
- system promotion setting `current_rank_since` and chaining from promotion;
- manual date override, clearing the override, and interval recomputation;
- commander and duty-manager authorization at מדור, above מדור, below מדור,
  in-scope, and out-of-scope targets, plus admin bypass and direct API denial.

Frontend tests cover:

- the date is displayed and submitted by the modal;
- the narrow rank/date form is available to an eligible commander or duty
  manager but not to an ineligible one;
- profile-save errors restore the usable form state.
