# Per-hierarchy fairness reset-date override + effective active start

## Problem

The system is mid-rollout: one branch (Focus) is piloted today, another
(Polaris) joins in a few weeks, and the whole מרכז (Pasifas) follows months
later. Focus's history since `fairness.reset_date` (1.7.26) was hand-backfilled
with real `DutyAssignment`/`ScoreAdjustment` records so their fairness numbers
are accurate. There's no appetite to repeat that manual, trust-dependent
backfill for every new branch.

Two gaps make that unavoidable today:

1. **`fairness.reset_date` is a single global value** (`scoring.py:686-709`,
   backed by one row in `SystemSetting`). Every soldier in the system is
   measured from the same historical starting point, regardless of when their
   branch actually joined the system. A branch that joins later than the
   global reset date, without a manual backfill, starts every fairness quarter
   at `effort_offset = 0` — the system's floor — and the CP-SAT fairness
   objective (`model.py:76-163`) responds by over-assigning them duties to
   "catch up" to a mean they never actually fell behind on.

2. **Effort scoring keys off `Soldier.enrolled_at`** (`effort_score.py:240,
   528`) — when an admin got around to adding someone to the roster — instead
   of `Soldier.unit_join_date` (`models.py:40`) — when they actually joined
   the unit. A soldier who joined Polaris on day one but was only entered into
   the app two weeks into the pilot is, today, indistinguishable from someone
   who is genuinely new.

## Goals

- Let an admin set a fairness reset date **per hierarchy node**, with a global
  default that applies where no override exists.
- Compute each soldier's effective history-start from `unit_join_date`
  (falling back to `enrolled_at` when unset), not `enrolled_at` alone.
- Do this without breaking the scale-invariance property `effort_score.py`
  already documents, and without materially regressing algorithm-run
  performance (this computation runs on every solver invocation).

## Non-goals

- Backfilling any soldier's actual duty history. This feature removes the
  *need* to backfill for onboarding fairness — it doesn't invent history that
  wasn't recorded.
- Changing how `effective_active_start`/`_active_day_interval` compute active
  *days* for on-call counting (`scoring.py:338-365`) — that's a separate,
  already-correct use of `unit_join_date` and is untouched.

## Design

### 1. Storage: reuse `SystemSetting`, no new table

Add a second setting key, `fairness.reset_date_overrides`, holding a JSON
object `{node_id: "YYYY-MM-DD"}` in the existing `SystemSetting.value` JSONB
column. `fairness.reset_date` remains the global default. This reuses
`get_setting`/`set_setting`/`apply_settings` and the existing settings audit
trail (`updated_by`/`updated_at`) as-is — only `validate_settings_update`
gains a case for the new key's shape (dict of valid UUID → ISO date, each
node id checked against the hierarchy table).

### 2. Resolution: nearest-ancestor override, else global default

New `resolve_reset_date(session, path_ids: list[uuid.UUID]) -> date` in
`scoring.py`. `path_ids` is already present on `Soldier` and already used the
same way for eligibility scoping (`availability.py`). Walk `path_ids` from the
soldier's own node toward the root; return the first node id present in the
overrides dict. If none match, fall back to the existing
`_burden_share_reset_date` (global).

**Performance:** don't call this per soldier. A run typically has many
soldiers sharing a handful of distinct hierarchy nodes. Callers
(`compute_effort_data`, `compute_burden_share_breakdown`) build one
`dict[node_id, date]` up front by resolving each *distinct* node id appearing
in the soldiers list exactly once (`O(distinct_nodes × path_depth)`), then do
an `O(1)` dict lookup per soldier. Path depth in this hierarchy is small
(single digits), so even the one-time resolution is negligible next to the
cost of the duty-day aggregation it sits next to.

### 3. Algorithm: per-soldier reset date AND per-soldier quarter length

This is the part that changed shape mid-design (see "Rejected approaches"
below) — both the *numerator* (how many days was this soldier active) and the
*denominator* (how many days did this quarter effectively have) must be
clipped to the same per-soldier floor, or the ratio undercounts a veteran
soldier's activity whenever their branch's reset date differs from whichever
soldier's reset date the shared quarter list happened to be built from.

For each soldier, in each tracked quarter `(q_start, q_end)`:

```
own_reset   = resolved_reset_dates[soldier.hierarchy_node_id]   # from step 2, O(1) lookup
activation  = soldier.unit_join_date or soldier.enrolled_at     # Feature 2

own_floor   = max(q_start, own_reset)               # this soldier's real quarter start
q_days_i    = (q_end - own_floor).days + 1          # denominator, clipped per-soldier
soldier_start = max(own_floor, activation)
if soldier_start > q_end:
    continue  # not active in this quarter at all
active_in_q = (q_end - soldier_start).days + 1
active_frac = active_in_q / q_days_i
```

Worked example: branch reset date Aug 20, soldier already active since before
then (`activation <= own_reset`). `own_floor = Aug 20`, `q_days_i = 42`
(Aug 20 → Sep 30), `soldier_start = Aug 20`, `active_in_q = 42` →
`active_frac = 100%`. Matches today's single-global-reset-date behavior
exactly. A soldier whose `activation` date falls *after* their own branch's
reset date (a genuinely new arrival) gets a fraction below 100%, computed
against their own relevant window — not diluted by an unrelated branch's
earlier reset date.

`quarter_soldier_scores`/`quarter_unit_scores` aggregation is unaffected — it
stays a single pass over `effective_duty_days`, unfiltered by soldier, exactly
as today. Only the ratio computed per `(soldier, quarter)` pair changes, and
that loop is already `O(soldiers × quarters)`, dominated in practice by the
duty-day fetch, so this is a same-order-of-magnitude change, not a new
complexity class.

**Query range still uses the minimum reset date across the run.** The
`effective_duty_days(date_from=..., date_to=...)` call's lower bound becomes
`min(resolved_reset_dates.values())` instead of one global value, so no
soldier's needed history is truncated at the query level — the per-soldier
`own_floor` clip above is what actually excludes irrelevant history for
soldiers with a later reset date, not the query bound.

Both `compute_effort_data` and `compute_burden_share_breakdown` (the
single-soldier score-breakdown used by the score-detail UI) get this same
treatment — they currently duplicate the same quarter loop and must stay
consistent with each other.

### 4. Frontend

New "Reset date overrides" section in `SystemSettingsPage.tsx`, next to the
existing `fairness.reset_date` field: a list of override rows (hierarchy node
+ date), add/remove. Reuses the existing `HierarchyNodePickerModal`
(`frontend/src/components/HierarchyNodePickerModal.tsx`, already used by
`AnnouncementsPage.tsx`) for single-node selection — it already does exactly
what's needed (searchable tree modal, `onPicked(nodeId, nodeName)`), so no new
picker component is built.

### 5. Score-projection cache: bail out, don't extend

`scoring.py` has a second, cache-backed implementation of this same math
(`_try_projected_effort_data`, `_try_projected_burden_share_breakdown`,
`_try_projected_transparency_rows`) used only by read paths (the transparency
page, a soldier's score-detail view) — never by the live algorithm solve,
which always calls `compute_effort_data` directly. This cache's precomputed
quarter windows (`_burden_share_quarter_windows`,
`_projection_burden_share_inputs`) are built from one global reset date and
would need real work to become hierarchy-override-aware — a separate,
cache-invalidation-shaped problem in its own right.

**Decision: don't extend it.** Both cache entry points resolve each soldier's
reset date the same way the live path does and bail out (`return None`,
triggering the caller's existing fallback to the live recompute) whenever any
soldier's resolved date differs from the plain global default. Soldiers
affected by a hierarchy override pay a latency cost on those read paths
(recomputed live instead of served from cache) but never see an incorrect
number. Making the cache itself override-aware is an explicit non-goal here.

### 6. Rejected approaches (kept for context)

- **Reset-everyone-on-each-pilot-stage.** The user's own fallback if the
  system didn't self-balance. Rejected: it discards legitimate
  hard-earned/hard-suffered duty credit at every stage transition, which is
  exactly what backfilling was trying to avoid in the first place.
- **Denominator clipped to the run's shared minimum reset date, not each
  soldier's own.** This was the first fix attempted and is wrong: it still
  uses someone else's reset date as this soldier's quarter length (e.g. `52`
  days from an earlier branch's Aug 10 reset, when this soldier's own branch
  resets Aug 20) — under-counts `active_frac` for anyone whose branch's reset
  date is later than the run's minimum, exactly the soldiers this feature
  exists to protect.

## Testing

- Backend (`-m scoring` / `-m algorithm`): `resolve_reset_date` ancestor-walk
  and global fallback; the per-soldier `q_days_i`/`active_frac` clip for (a) a
  veteran soldier active since before their branch's own reset date (expect
  100% for that quarter), (b) a soldier whose `activation` lands after their
  own branch's reset date, (c) two soldiers in the same run with different
  resolved reset dates, confirming neither's ratio is computed against the
  other's window.
- Frontend (vitest): override-row add/remove/validate in
  `SystemSettingsPage.tsx`; `SubHierarchySelector`'s single-select mode.
