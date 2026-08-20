# Add "חוליה" (squad) as a default hierarchy level

## Problem

The hierarchy tree's level types (אגף / מערך / יחידה / מרכז / ענף / מדור / צוות) are
fully admin-configurable — `hierarchy_level_types` is a generic `(key, label,
rank)` table, not a hardcoded enum, and there's already a UI to add/reorder/
delete level types (`EditNodeDialog.tsx`, reachable from any node's edit
dialog for a duty manager or admin). So a new level can already be added by
hand. The user wants "חוליה" (squad/fireteam) available **by default**,
without requiring that manual setup step, both on this already-running
deployment and on any future fresh install.

## Design

One new Alembic migration, seeding a single row into `hierarchy_level_types`:

- `key`: `"squad"`
- `label`: `"חוליה"`
- `rank`: one below the current lowest level (`team`, rank 7) → `8`

The insert is guarded with `WHERE NOT EXISTS (... key = 'squad')`, so it's
safe to run both on a fresh install (migration `0059` already seeded ranks
1–7) and on this already-migrated production database.

No other code changes: every part of the system (node CRUD, hierarchy
permission scoping, algorithm eligibility, exports) already treats `level`
as an opaque string keyed off this table — confirmed no service code
hardcodes `"team"` as the deepest level. Once the row exists, "חוליה" is a
normal level: creatable as a child of a team node, assignable a commander,
usable in scope/eligibility filters, exportable, etc., through the existing
generic hierarchy machinery.

## Out of scope

- No changes to the dev seed script (`app/scripts/seed.py`) — its sample
  data doesn't need squads to be useful for local dev/testing.
- No squad-specific behavior (e.g. duty-type eligibility rules that only
  make sense at squad level) — this only makes the level *available*.
