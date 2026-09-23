# HR Person Sync Engine (Subsystem 4 of HR Integration) — Design

## Context

Subsystem of the larger HR integration project (see
[2026-09-22-hr-api-client-design.md](2026-09-22-hr-api-client-design.md)
for the roadmap). Subsystems 1 (`HrApiClient`), 2 (field mapping +
local-override tracking), and 3 (org hierarchy sync) are already built and
merged to `dev`.

This document specs **subsystem 4**: pulling all soldiers from HR, creating
Justice profiles for anyone missing, updating existing HR-linked profiles,
flagging soldiers who vanished from HR, and rerunning dependent logic
(rank advancement, duty eligibility) when HR-driven changes warrant it. It
also carries two small retrofits to subsystem 3, and confirms the
`system.holding_node_id` fallback path that subsystem 3 deliberately left
unused.

## Non-goals

- Activation codes / turning an HR-created profile into a loggable-in
  account (subsystem 5).
- Admin review UI, cron wiring (subsystem 6).
- Acting on `sync_status="vanished"` beyond flagging — no soft-delete, no
  notification to the affected soldier, no hierarchy change.
- The Excel import/export password-hash-preservation feature (separate,
  unrelated bounded task, scheduled after this subsystem).

## Retrofit 1: `HrHierarchyNodeMap` (subsystem 3)

Subsystem 3's `_resolve_group` matches-or-creates a `HierarchyNode` per HR
`Group` by **name**, scoped to the resolved parent — but never durably
records *which HR group produced which node*. Subsystem 4 needs the
reverse lookup: given a person's HR org-unit id, find the Justice node.

New table `hr_hierarchy_node_map`: `id`, `hr_group_id` (unique, Text),
`node_id` (unique, FK → `hierarchy_nodes.id`), `created_at`, `updated_at`.
A join table, not a column on `HierarchyNode` — keeps HR-sync bookkeeping
in its own bounded context, same reasoning as subsystem 2's
`soldier_hr_profile` (a separate table, not columns bolted onto `Soldier`).

`_resolve_group` (subsystem 3) gets a small patch: after a group resolves
to a node (matched or created), upsert
`HrHierarchyNodeMap(hr_group_id=group.id, node_id=node.id)`.

## Retrofit 2: match scope adds `level` (subsystem 3)

`_resolve_group`'s existing-node lookup currently filters by
`(name, parent_id)` only — not `level`. A team and a mador sharing a name
under the same parent would both match, landing in the "ambiguous match"
hold path (safe, but an unnecessary hold — same name + same parent +
different level is never actually the same real-world entity). Add
`HierarchyNode.level == level` to both branches of the existing-node
query. `level` is already computed earlier in the function (from
`HR_GROUP_KIND_TO_LEVEL_MAP`) — no new lookup needed, just one more filter.

## Hierarchy pre-pass: person-derived cross-validation

HR's `Group.parentId`/`parentKind` chain (already fetched by subsystem 3)
is the **sole source of tree shape** — the one place HR states nesting
order explicitly, so no guessing is needed. Some org-unit fields on
`HrUser` (`hulia`/`huliaId`, `shetach`/`shetachId`, etc.) may have **no
corresponding `Group.kind`** at all — invisible to subsystem 3's
group-based sync. `palga` has a name field but no `palgaId`, so it can
never participate in id-based lookups.

Before per-person placement, `run_person_sync` runs a pre-pass over every
fetched `HrUser`:
1. For each person, extract the present id fields in priority order:
   `team_id`, `mador_id`, `branch_id`, `department_id`, `shetach_id`,
   `unit_id` (the same order used for placement below — see "Person
   placement").
2. For each id present, check it resolves via `HrHierarchyNodeMap`. An id
   with no corresponding row (the group was never seen by subsystem 3, or
   its own resolution was held) is recorded as an **unresolved org
   reference** for that person — not silently skipped, not guessed.
3. This pre-pass does **not** attempt to build new tree edges from
   co-occurring ids (that would require guessing the real nesting order
   among fields with no confirmed rank, violating the project's "never
   guess" rule throughout). It is purely a resolution check feeding into
   placement (step 4 of the person loop) and the divergence signal
   recorded when a person's chain doesn't resolve.

## Password / role handling

Reuses the exact precedent already in `import_sessions.py`'s Excel import:
`password_hash = hash_password(secrets.token_hex(16))` (a real-format hash
of a random token nobody knows) + `must_change_password=True`. This is
**only** for genuinely new `Soldier` rows created by sync. For a person
whose `personal_number` matches an existing Justice soldier (already
linked or newly linking via a `SoldierHrProfile` match), sync **never**
touches `password_hash` or `role` — matching the original brief's "sync
never writes password/role" instruction literally for anyone who already
has credentials.

`Soldier` fields not covered by HR's mapped set (`food_type`,
`food_constraints`, `last_mitvahim_date`, `last_alal_date`, weapon
qualification, etc.) are left at their column defaults/`NULL` on creation
— "requested at first login" per the original brief is subsystem 5's
activation-flow concern, not this subsystem's.

## Person placement

For a new or previously-unresolved person, resolve their `hierarchy_node_id`:
1. Walk `team_id → mador_id → branch_id → department_id → shetach_id → unit_id`
   (TODO: this priority order is a placeholder — the correct "deepest
   assigned unit" field per real HR data is unconfirmed; revisit once real
   fixture data is available), take the first non-null id.
2. Look it up in `HrHierarchyNodeMap`. Resolved → use that `node_id`.
3. No id present at all, or the resolved id has no map entry → place under
   `system.holding_node_id` (the existing setting, bootstrapped by
   `app/scripts/bootstrap.py`, previously only consumed by manual
   enrollment — this subsystem is its first HR-sync consumer). Record the
   fallback reason on the person's outcome (see "Run tracking").

## Person processing loop

`run_person_sync(session: Session, client: HrApiClient) -> HrPersonSync`:

1. Insert an `HrPersonSync` row, commit separately (same pattern as
   subsystem 3's `HrHierarchySync`).
2. Fetch all people: `users = [u async for u in client.iter_users()]`.
3. **Anomaly check**: read the last `HrPersonSync` row with
   `status="completed"`. If one exists and `len(users)` is below
   `hr_sync.min_fraction_of_last_run` (new `SystemSetting`, default `0.5`)
   times that run's total, abort immediately: set
   `status="aborted_anomaly"` on this run, `completed_at`, notify all
   `role="admin"` soldiers (new helper, queries `Soldier` by role, calls
   `create_notification` per admin with a new `NotificationType`), commit,
   return — no group/person data touched. First-ever run has no baseline
   and always proceeds.
4. Run the hierarchy pre-pass (above) across all fetched users.
5. For each `HrUser`, in fetched order (people have no parent-child
   relationship to each other, so no topological ordering is needed
   here — unlike subsystem 3's groups):
   - `map_hr_user(user)` → `MappedSoldierFields` or `HeldForReview`.
   - Look up `SoldierHrProfile` by `personal_number`.
   - **`HeldForReview`**: upsert the profile with
     `sync_status="held_for_review"`, `review_reason` from the mapping
     result's reasons (joined). No `Soldier` touched. Commit this person's
     work; continue.
   - **Mapped, no existing profile (or profile with `soldier_id IS NULL`,
     i.e. was previously held and is now mappable)**: resolve placement
     (above). Create the `Soldier` row (placeholder password if genuinely
     new — see above; if a `Soldier` with this `personal_number` already
     exists from manual enrollment, link to it instead of creating a
     duplicate, and never touch its `password_hash`/`role`). Create/update
     the `SoldierHrProfile` (`soldier_id` set, `raw_dto` = the full raw
     payload, `sync_status="synced"`, `last_synced_at=now()`). Commit;
     continue.
   - **Mapped, existing linked profile**: for each HR-owned field
     (subsystem 2's `HR_OWNED_FIELDS`) not present in
     `profile.overridden_fields`, apply the mapped value; for each that
     *is* overridden, call `record_sync_divergence` instead of applying
     it. Track whether `rank`, `mandatory_end_date`, or `discharge_date`
     actually changed. If `sync_status` was `"vanished"`, flip it back to
     `"synced"` (the person reappeared). Update `raw_dto`/`last_synced_at`.
     If any of the three tracked fields changed, rerun dependent logic
     (below) after the field writes. Commit; continue.
   - Any unhandled exception while processing one person: roll back just
     that person's uncommitted changes, record an error entry (see "Run
     tracking"), continue to the next person — never aborts the run.
6. After all people are processed (and the run didn't abort on the
   anomaly check): any `SoldierHrProfile` with `soldier_id IS NOT NULL`
   and `sync_status` currently `"synced"` whose `personal_number` wasn't
   among this run's fetched people gets `sync_status="vanished"`. Flag
   only — no other change, per your explicit choice.
7. Set `status="completed"`, `completed_at`, final counts. Commit.

## Dependent-logic reruns

Reuses existing functions, not reimplemented:
- `app.services.soldiers._reset_rank_advancement(session, soldier, since=today)`
- `app.services.duty_eligibility_watch.recheck_soldier_assignments(session, soldier_id)`

Called only when `rank`, `mandatory_end_date`, or `discharge_date` actually
changed on an update (comparing old vs. new mapped value) — never on
create (a brand-new person has no prior assignments to recheck) and never
when the changed field was skipped due to being locally overridden.

## Run tracking: `HrPersonSync`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `status` | Text | `"running"` \| `"completed"` \| `"failed"` \| `"aborted_anomaly"` |
| `started_at` / `completed_at` | timestamptz | `completed_at` nullable while running |
| `total_fetched` | Integer, default 0 | Count of people HR returned this run — the baseline future runs compare against. |
| `created_count` / `updated_count` / `held_count` / `vanished_count` / `error_count` | Integer, default 0 | |
| `error_message` | Text, nullable | Populated on `status="failed"` (an unhandled exception outside the per-person loop, e.g. the initial `iter_users()` fetch itself failing) or `status="aborted_anomaly"`. |

No `parsed_state` JSONB list (unlike `HrHierarchySync`) — a full per-person
log for potentially thousands of people is unbounded. Per-person outcomes
are already durably recorded on each `SoldierHrProfile` row
(`sync_status`, `review_reason`, `last_synced_at`); per-person *errors*
(the rollback-and-continue case) get a lightweight record too — a new
`HrPersonSyncError` table (`id`, `hr_person_sync_id` FK, `personal_number`,
`error_message`, `created_at`) rather than an unbounded JSONB column,
since errors specifically need investigation later (subsystem 6's review
page) and a proper table is queryable/indexable in a way a JSONB blob
isn't.

## Module layout

`app/services/hr/person_sync.py` (new):
- `run_person_sync(session, client) -> HrPersonSync`
- Internal helpers: the hierarchy pre-pass, per-person resolution/apply
  logic, the anomaly-check + admin-notify helper.

`app/services/hr/hierarchy_sync.py` (modified, additive):
- `_resolve_group` gains the `HrHierarchyNodeMap` upsert and the `level`
  filter on existing-node lookups.

`app/db/models.py` gains `HrHierarchyNodeMap`, `HrPersonSync`,
`HrPersonSyncError`.

New `NotificationType` value (migration, `ALTER TYPE ... ADD VALUE`,
matching existing precedent): `hr_sync_anomaly_aborted`.

New `SystemSetting`: `hr_sync.min_fraction_of_last_run` (default `"0.5"`).

## Testing plan (TDD)

Fixture-based for the HR-client-facing parts (respx-mocked, subsystem 1
style), DB-layer (testcontainers) for everything touching `Soldier`/
`SoldierHrProfile`/hierarchy tables:

1. New mappable person, no existing profile → `Soldier` + linked
   `SoldierHrProfile` created, placeholder password, `must_change_password=True`.
2. New mappable person whose `personal_number` matches an existing
   (manually-enrolled) `Soldier` → linked, `password_hash`/`role` untouched.
3. Existing linked person, a non-overridden field changes → applied.
4. Existing linked person, an overridden field's HR value differs from
   local → `record_sync_divergence` called, local value preserved.
5. Existing linked person, `rank` changes → dependent-logic reruns called;
   unchanged fields → not called.
6. `HeldForReview` person → profile held, no `Soldier` touched.
7. Person's org-id resolves via `HrHierarchyNodeMap` → placed correctly.
8. Person's org-id doesn't resolve (or no id present) → placed under
   `system.holding_node_id`.
9. A linked, previously-synced person absent from this run's fetch →
   `sync_status="vanished"`.
10. A previously-`"vanished"` person reappears → flips back to `"synced"`.
11. Anomaly check: first-ever run (no baseline) proceeds regardless of
    count.
12. Anomaly check: count below the configured fraction → aborts,
    `status="aborted_anomaly"`, no data touched, admins notified.
13. Per-person exception → that person's changes roll back, an
    `HrPersonSyncError` row is recorded, the run continues and completes.
14. `_resolve_group` (subsystem 3, retrofit): upserts `HrHierarchyNodeMap`
    on both match and create paths; the new `level` filter prevents a
    same-name-different-level false ambiguous-hold.

Target: 100% coverage of `person_sync.py`; the `hierarchy_sync.py`
retrofit's new lines covered by extending subsystem 3's existing test
file.

## Open questions to resolve during implementation (not blocking the plan)

- The `team_id → mador_id → branch_id → department_id → shetach_id → unit_id`
  placement priority order is an explicit placeholder — confirm against
  real HR data when available.
- Whether `hulia`/`palga` should ever become first-class placement
  candidates (they currently never appear in the priority list at all,
  by design, since we have no confirmed rank for them) is a product
  decision for later, not something this subsystem resolves.
