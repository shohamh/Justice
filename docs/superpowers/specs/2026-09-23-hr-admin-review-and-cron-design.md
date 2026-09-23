# HR Admin Review UI + Cron Wiring — Design Spec

Subsystem 6 (final) of the HR integration project. Subsystems 1-5 (HR API
client, field mapping, hierarchy sync, person sync engine, activation codes)
are built and merged to `dev`. `run_hierarchy_sync`/`run_person_sync` exist
as pure async functions but have **zero production callers today** — no
route, worker, or script invokes them outside tests. This subsystem wires
them onto a schedule, resolves a rank-advancement ownership conflict between
HR sync and the existing `rank_advancement_worker`, and gives admins a UI for
the things sync already flags but nothing surfaces (`held_for_review`,
field-override divergences, `vanished` profiles) plus new rank-conflict
visibility.

## A. Cron wiring

`app/hr_sync_worker.py` (new), following the existing pattern used by
`rank_advancement_worker.py` and the other six background workers started in
`main.py`'s lifespan (`while True: sleep; do work`, no external
scheduler/APScheduler — this codebase's established convention):

```python
_POLL_SECONDS = get from setting "hr_sync.poll_hours" (default 6) * 3600
```

Each cycle:
1. If `not settings.hr_api_configured` (property already exists on
   `Settings`, checks `hr_api_base_url`/`hr_api_key` both set) — skip the
   cycle silently (no error, no log spam; this lets every non-HR-enabled
   environment, including most dev machines, run the worker loop as a no-op).
2. Construct `HrApiClient(settings.hr_api_base_url, settings.hr_api_key,
   ca_bundle_path=settings.hr_api_ca_bundle_path,
   page_size=settings.hr_api_page_size)`.
3. `await run_hierarchy_sync(session, client)` — hierarchy must sync first;
   `run_person_sync`'s placement resolution (`resolve_placement_node_id`)
   depends on `HrHierarchyNodeMap` already being current.
4. `await run_person_sync(session, client)`.
5. Catch and log (`logger.warning(..., exc_info=True)`) any exception from
   either call, same as every other worker — one bad cycle must not kill the
   loop or the process.

Wired into `main.py`'s lifespan exactly like `rank_advancement_task`.

A manual "run sync now" admin action (Section C) calls the same
`run_hierarchy_sync`/`run_person_sync` pair directly, outside the poll loop
— it does not touch or reset the loop's own timer.

## B. Rank-advancement / HR-sync reconciliation

**Scope check, confirmed against the actual code:** `_apply_existing_person`
(person sync) already overwrites `rank`, `mandatory_end_date`, and
`discharge_date` from HR on every sync, for every field not locally
overridden — HR is *already* authoritative for all three today. Nothing
else in the system independently computes `mandatory_end_date` or
`discharge_date`, so those two can never conflict with another source; they
only ever get silently synced (existing, unchanged behavior) or diverted to
`record_sync_divergence` when overridden (existing, unchanged behavior).

`rank` is the one field with a second, independent writer:
`rank_advancement_worker._promote_due_soldiers()` (and
`_promote_on_career_entry`) advance a soldier's rank on their own schedule,
based on `Soldier.next_rank_date`. This is the only real conflict surface,
and it is where this section's changes land.

**1. The worker stops acting on HR-linked soldiers.** Each of
`_promote_on_career_entry`, `_promote_due_soldiers`, `_warn_upcoming_soldiers`
in `app/rank_advancement_worker.py` adds an exclusion:

```python
Soldier.id.not_in(select(SoldierHrProfile.soldier_id).where(SoldierHrProfile.soldier_id.is_not(None)))
```

(a soldier with *any* linked HR profile — status doesn't matter, since even
a `vanished` profile still represents a real, once-linked HR identity whose
rank should keep coming from the last-known HR sync, not from independent
local computation.) A non-HR-linked soldier's rank progression is unchanged.

**2. Ownership tracking.** New column `Soldier.rank_last_set_by: str | None`
(`"hr_sync"` | `"worker"` | `"manual"`), written at each of the three
existing rank-write sites:
- `_apply_existing_person` (person_sync.py) → `"hr_sync"`, whenever it
  actually changes `rank` (not on every sync, only on an actual write).
- `_promote_soldier` (soldiers.py, called by the worker) → `"worker"`.
- `update_soldier_profile`'s rank-edit path (soldiers.py, admin/DM direct
  edit) → `"manual"`.

**3. Conflict detection**, in `_apply_existing_person`, at the point HR's
incoming `rank` differs from the soldier's stored `rank` (only reached when
the field isn't locally overridden — same gate `record_sync_divergence`
already uses): flag a conflict when **either**:
- `soldier.rank_last_set_by == "worker"` — the worker made an independent
  decision that HR is now about to silently override. This is exactly the
  promote-then-revert loop scenario.
- The new HR rank is not `get_next_rank(old_rank, track=resolve_track(old_rank,
  soldier.rank_track))` — i.e. not a simple one-step advance from where the
  soldier was (a skip, a demotion, or any other non-sequential jump signals
  HR's data disagrees with normal progression logic and is worth a human
  glance, regardless of who set the old value).

HR's value is applied either way (HR stays authoritative — this was your
explicit decision). When either condition is true, additionally:
- Insert a new `HrRankConflict` row (Section D) recording old/new rank,
  which condition(s) fired, the soldier, and the triggering sync run.
- Notify the soldier directly (`create_notification`, new
  `NotificationType.hr_rank_conflict`) and their commander(s)
  (`notify_commanders_of_request`, same type) — both need to know their rank
  changed via HR reconciliation and why it was flagged, using the dual-notify
  shape already used elsewhere in the codebase (soldier gets a direct
  notification, commanders get a separate `cascade_to_commanders`-backed one).
- The conflict is also visible in the admin review UI (Section C), read-only
  for v1 — no resolution action, since HR's write already happened and
  cannot be "undone" from this UI; it's a visibility/audit surface, not a
  pending-approval queue.

No conflict fires → identical to today's silent sync behavior.

## C. Admin review UI

New tab in `AdminSettingsPage.tsx` ("HR Sync"), following the existing
tab-bar-over-content-component pattern (`AuditLogContent`,
`BugReportsContent`, etc. are the precedent). Five sub-views, as one new
content component with internal sub-navigation (exact frontend structure —
single component with sections vs. nested tabs — is a plan-level decision,
not a spec-level one):

1. **Held for review** (`SoldierHrProfile.sync_status == 'held_for_review'`,
   filtered per item C.3 below) — personal_number, `review_reason`, raw
   payload. **Action: dismiss** (Section C.3).
2. **Field divergences** — `AuditLog` rows with `action ==
   "hr_sync.field_skipped_overridden"` (written by `record_sync_divergence`,
   already wired in subsystem 4, never consumed until now) — soldier,
   field_name, hr_value, local_value, when. **Action: clear override**
   (removes `field_name` from `SoldierHrProfile.overridden_fields`, so the
   *next* sync applies HR's value normally — does not retroactively apply it
   immediately; that happens on the next scheduled or manual sync run,
   consistent with how overrides already work).
3. **Held-for-review dismissal, with persistence.** New columns on
   `SoldierHrProfile`: `review_dismissed_at: datetime | None`,
   `review_dismissed_reasons: list[str] | None` (JSONB, snapshot of the
   `reasons` list at the moment of dismissal). `_mark_held` (person_sync.py)
   compares the new run's `reasons` list to `review_dismissed_reasons`: if
   equal and `review_dismissed_at` is set, the profile stays out of the
   "held for review" admin view (still `sync_status = 'held_for_review'`
   underneath — unchanged — just filtered from the UI query); if the reasons
   list differs (HR's data changed, even if still broken in a new way),
   clear both dismissal fields so it resurfaces for review. Dismissing sets
   both fields to the current run's values.
4. **Vanished soldiers** (`sync_status == 'vanished'`) — read-only list.
5. **Rank conflicts** (`HrRankConflict`, Section B) — read-only list.
6. **Sync run history** — `HrHierarchySync`/`HrPersonSync` rows (status,
   counts, timing) with their `HrPersonSyncError` children expandable, plus
   a **"run sync now"** button (admin-only) that calls both sync functions
   directly (Section A.5) and returns the resulting run records.

All routes admin-only (`role == "admin"`, matching the existing admin-route
authorization pattern elsewhere in `app/routes/`).

## D. Data model additions

New migration, after `20260926_hr_activation_codes`:

- `soldiers.rank_last_set_by TEXT NULL` — `"hr_sync"` | `"worker"` |
  `"manual"`, no default (existing rows stay `NULL`, meaning "unknown
  provenance," which is fine: `NULL != "worker"`, so no false-positive
  conflict on old data).
- `soldier_hr_profiles.review_dismissed_at TIMESTAMPTZ NULL`.
- `soldier_hr_profiles.review_dismissed_reasons JSONB NULL`.
- New table `hr_rank_conflicts`: `id` (pk), `soldier_id` (FK → soldiers,
  CASCADE), `old_rank TEXT`, `new_rank TEXT`, `triggered_by_worker_decision
  BOOLEAN` (condition 1), `non_sequential_jump BOOLEAN` (condition 2),
  `hr_person_sync_id` (FK → hr_person_syncs, nullable, SET NULL — points at
  the run that caused it), `created_at TIMESTAMPTZ default now()`.
- New `NotificationType.hr_rank_conflict`.
- New setting `hr_sync.poll_hours` (int, default 6), read via the existing
  `get_setting_int`/`SettingNotFound` fallback convention used throughout
  this project (e.g. `hr_activation.code_expiry_days`).

## Non-goals (explicit)

- No retry/backoff policy changes to `HrApiClient` — out of scope, already
  decided as "no retry, caller's responsibility" in an earlier subsystem.
- No action UI for vanished soldiers or rank conflicts in v1 (read-only, per
  your decision) — a future subsystem could add "reactivate"/"acknowledge"
  actions if needed.
- No change to `held_for_review`'s underlying mapping logic (Section C.3
  only changes what the *admin UI* surfaces, not what `_mark_held` persists
  to `sync_status`).
- No editable "fix the bad HR data by hand" flow for held-for-review records
  — dismissal only, per your decision.
- Does not touch `require_hr_onboarding_complete`'s retrofit gap (a
  documented, separate follow-up from subsystem 5's final review) — orthogonal
  to this subsystem's scope.
