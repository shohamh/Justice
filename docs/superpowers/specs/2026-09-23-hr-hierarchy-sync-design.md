# HR Org Hierarchy Sync (Subsystem 3 of HR Integration) — Design

## Context

Subsystem of the larger HR integration project (see
[2026-09-22-hr-api-client-design.md](2026-09-22-hr-api-client-design.md)
for the six-subsystem roadmap). Subsystems 1 (`HrApiClient`) and 2 (field
mapping + local-override tracking) are already built and merged to `dev`.

This document specs **subsystem 3**: auto-mapping HR's org structure (`Group`
records from subsystem 1's client) onto Justice's existing `HierarchyNode`
tree, auto-creating missing nodes, and holding unplaceable groups for review
— without ever guessing at ambiguous placements.

Unlike subsystem 2 (deliberately pure, no HR API calls), hierarchy sync is
inherently a whole-tree operation: placing a group correctly requires
knowing where its parent landed. This subsystem therefore **does** call
`HrApiClient` and loop — it is the first subsystem shaped like a real sync
engine, not a pure mapping layer. Subsystem 4 (the person sync engine, not
yet planned) will call into this subsystem's results (which HR groups
resolved to which Justice nodes, and which didn't) when placing individual
soldiers, using `system.holding_node_id` as its own person-placement
fallback — that fallback logic belongs to subsystem 4, not here.

## Non-goals

- No person/`Soldier` creation or field mapping (subsystems 2 and 4).
- No cron wiring (subsystem 6) — exposed as a plain callable for now.
- No admin review UI (subsystem 6) — `HrHierarchySync` rows are the data
  that UI will read later; this subsystem only writes them.
- No use of `system.holding_node_id` *within this subsystem* — an
  unresolved HR group is simply held (no node created, no attachment
  anywhere); the holding node is a subsystem-4 concern for placing people
  whose group didn't resolve.

## Precedents reused, not reimplemented

- `app.services.hierarchy.create_node` — node creation, level-rank
  validation, `path_ids` computation, audit logging. Called directly for
  every auto-created node.
- `app.services.hierarchy.get_level_rank` — level validity check.
- The existing `system.holding_node_id` `SystemSetting`, bootstrapped in
  `app/scripts/bootstrap.py`, read via `app.services.settings_loader`. Not
  referenced by this subsystem's own logic (see Non-goals), but the setting
  itself is unchanged and stays subsystem 4's to consume.
- `app.services.import_sessions._resolve_hierarchy` / `confirm_session` —
  conceptual precedent for the resolve→classify→apply shape, adapted here
  to auto-apply (no human confirm gate) and parent-scoped name matching
  (stricter than that function's flat name lookup).

## Kind→level mapping & confidence rules

Explicit dict, same discipline as subsystem 2 — an HR `Group.kind` with no
entry is unmappable, never guessed:

```python
# TODO: placeholder kind strings, unconfirmed against real HR API data.
HR_GROUP_KIND_TO_LEVEL_MAP: dict[str, str] = {
    "unit": "unit",
    "branch": "branch",
    "mador": "mador",
    "team": "team",
}
```

(Actual Justice level keys are admin-configurable via `HierarchyLevelType`,
not a fixed set — this map's values must be level *keys* that exist in that
table at sync time; a value with no matching `HierarchyLevelType.key` is
treated the same as an unmapped kind: held, with that reason.)

A group is **confidently placeable** only if, in resolution order:
1. `kind` maps to a known, currently-valid Justice level key.
2. Its parent is resolvable:
   - `parentId is None` → root-level group. Matched by exact name against
     existing top-level nodes (`parent_id IS NULL`), or auto-created as a
     new root node if no name match.
   - `parentId` set → must reference another HR group that **already
     resolved successfully earlier in this same run** (matched or
     created). If that parent group is itself held (or never seen — e.g. a
     dangling `parentId` with no matching HR group in the fetched set),
     this group is held too, with a reason naming the unresolved parent.

This makes "hold the whole unresolved subtree" automatic — no separate
cascade step, since a child can never resolve before its parent does in
processing order (see Execution algorithm).

## Node matching

For a group that passed both confidence checks: exact match on
`(name, resolved_parent_node_id)` among existing `HierarchyNode` rows
(`parent_id = resolved_parent_node_id AND name = group.name`) — scoped by
the resolved parent, not a flat name lookup across the whole tree, to avoid
same-name collisions across unrelated branches. Match found → `"matched"`,
no write. No match → `svc.create_node(session, level=mapped_level,
name=group.name, parent_id=resolved_parent_node_id)` → `"created"`.

## Execution algorithm

`run_hierarchy_sync(session: Session, client: HrApiClient) -> HrHierarchySync`:

1. Create an `HrHierarchySync` row with `status="running"`, `started_at=now()`.
2. Fetch all groups: `groups = [g async for g in client.iter_groups()]`
   (org trees are small — no pagination-safety/abort-on-anomaly concerns
   like subsystem 4 will need for the much larger person set).
3. Topologically order `groups` by `parentId` (repeated-pass or Kahn's
   algorithm over the `id`/`parentId` edges) so every group is processed
   strictly after its parent. A group whose `parentId` points to nothing in
   the fetched set (dangling reference) is treated as unresolved at
   resolution time (step 4), not excluded here — the ordering only needs
   parents-before-children among groups that *do* have a resolvable parent
   reference; a dangling one simply never finds its parent already-decided
   and is held for that reason.
4. For each group in that order: apply the confidence rules above, then
   match-or-create, recording one result entry.
5. Write all result entries to `HrHierarchySync.parsed_state` (JSONB list):
   `{hr_group_id, name, action: "matched"|"created"|"held", resolved_node_id, level, reason}`
   (`resolved_node_id`/`level` null when `action="held"`; `reason` null
   otherwise).
6. Set `created_count`/`matched_count`/`held_count` on the row from the
   result tally, `status="completed"`, `completed_at=now()`.
7. The whole operation — steps 2 through 6 — runs inside one DB transaction
   (the `HrHierarchySync` row's initial insert in step 1 may commit
   separately so a run's existence is visible even if it later fails; the
   node creation and final status update are one atomic unit). On any
   unhandled exception (e.g. `HrApiError` from a client call), catch it,
   set `status="failed"`, `error_message=str(exc)`, `completed_at=now()`,
   and roll back any uncommitted node changes from that run — no partial
   tree.

## Storage: `HrHierarchySync` table

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `status` | Text | `"running"` \| `"completed"` \| `"failed"` |
| `started_at` | timestamptz | |
| `completed_at` | timestamptz, nullable | Null while running. |
| `parsed_state` | JSONB | List of per-group result entries, per step 5 above. |
| `created_count` | Integer, default 0 | |
| `matched_count` | Integer, default 0 | |
| `held_count` | Integer, default 0 | |
| `error_message` | Text, nullable | Populated only when `status="failed"`. |

## Module layout

New file `app/services/hr/hierarchy_sync.py`:
- `HR_GROUP_KIND_TO_LEVEL_MAP` (module constant)
- `run_hierarchy_sync(session, client) -> HrHierarchySync`
- Internal helpers: a topological sort over `HrGroup` records by
  `parentId`, and the per-group resolution logic (confidence checks +
  match-or-create).

`app/db/models.py` gains `HrHierarchySync`.

## Testing plan (TDD)

Fixture-based where the HR client is involved (respx-mocked, same as
subsystem 1), DB-layer for node creation (same testcontainers pattern as
subsystem 2):

1. Root group with no existing match → new root node created.
2. Root group matching an existing top-level node by name → `"matched"`,
   no new node.
3. Child group whose parent resolved earlier in the same run → created
   under the resolved parent, correct `path_ids` (verified via
   `create_node`'s own contract, not reimplemented).
4. Group with an unmapped `kind` → held, reason names the unmapped kind.
5. Group with a mapped `kind` but a `parentId` pointing to a held group →
   held, reason names the unresolved parent.
6. Group with a mapped `kind` but a dangling `parentId` (no matching HR
   group in the fetched set) → held.
7. Two groups with the same `name` under two different parents → both
   resolve independently (parent-scoped matching, not a false collision).
8. A multi-level tree (root → branch → team, 3+ levels) processes in
   correct topological order regardless of the fetch order returned by
   `iter_groups()`.
9. `HrHierarchySync` row: `status`/`counts` correct after a run with a mix
   of matched/created/held groups.
10. `HrApiError` mid-fetch → `status="failed"`, `error_message` populated,
    no partial nodes committed.

Target: 100% coverage of `hierarchy_sync.py`.

## Open questions to resolve during implementation (not blocking the plan)

- `HR_GROUP_KIND_TO_LEVEL_MAP`'s actual kind strings are placeholders,
  unconfirmed against real HR API data — same caveat as subsystem 2's
  `SERVICE_TYPE_TO_TRACK_MAP`.
- Whether root-level groups should ever be auto-created without *any*
  admin awareness (the design allows it per your "auto-create missing
  nodes" instruction) — worth a note in subsystem 6's review UI to
  surface newly-created root nodes prominently, even though this
  subsystem doesn't build that UI.
