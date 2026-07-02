# Transparency table: פטורים column + subunit exemption aggregates

## Context

The transparency page (`frontend/src/pages/TransparencyPage.tsx`) has two tabs:
"soldiers" (per-soldier rows) and "sub_units" (hierarchy rollup). Data comes
from `GET /scoring/transparency`, backed by `transparency_rows()` in
`backend/app/services/scoring.py`.

Exemptions are modeled by `ExemptionType` (`is_global: bool`, `is_medical: bool`)
and `SoldierExemption` (`start_date`, optional `end_date`; a partial exemption
is scoped to specific duty types via `ExemptionDutyTypeMap`). "Temporary"
(זמני) is not a stored flag — it's derived: `end_date is not None`.

Goal: add a **פטורים** column to the soldiers tab showing each soldier's
active exemptions, gated by the viewer's responsibility scope. Add three
aggregate exemption-count columns (גלובלי / חלקי / זמני) to the sub-units tab,
gated by a coarser role check. Excel export should reflect exactly what's on
screen, so exporting produces a usable "טבלת פוטנציאל" without further work.

## Scope semantics (two independent gates)

**Per-soldier row (soldiers tab) — fine-grained, scope-based:**
Visible only if the viewer is in responsibility scope over that soldier's
hierarchy node. Reuses existing `app.auth.authz`:
- `roots = scope_root_ids(session, viewer)` — union of the viewer's
  `DutyManagerScope` nodes and nodes they command.
- `_node_in_scope(soldier_node, roots)` — checks `roots` against
  `soldier_node.path_ids`.
- **No admin bypass.** An admin with no assigned `DutyManagerScope`/commanded
  node sees `חסוי` here, same as anyone else. This diverges from `authz.can()`,
  which does bypass for admins — that helper is not reused for this check;
  the scope check is applied directly.

**Sub-units tab aggregates — coarse, role-based:**
Visible to the viewer if `viewer.role == "admin"` OR
`scope_root_ids(session, viewer)` is non-empty (i.e. they hold at least one
`DutyManagerScope` row or command at least one node — regardless of which
node). This is a single yes/no gate, independent of which subunit is being
rendered — a duty manager scoped only to unit A still sees real counts for
unit B's rollup. Not scope-gated per node, because aggregate counts don't
reveal individual identities.

These two gates are independent and use different data: the per-soldier gate
redacts the display string per row; the aggregate gate controls whether raw
per-soldier boolean fields are included in the payload at all.

## Backend changes

### `backend/app/services/scoring.py`

`transparency_rows(session, *, viewer: Soldier)` gains a required `viewer`
param (all callers updated). For each active exemption
(`start_date <= today` and (`end_date is null` or `end_date >= today`)),
classify:
- `category = "גלובלי" if exemption_type.is_global else "חלקי"`
- `is_temporary = end_date is not None` (independent overlay — a global
  exemption with an end_date counts as both global and temporary)

Per soldier, compute:
- `exemptions_display: str` — if in scope: joined labels
  `"<exemption_type.name> (<category>[, עד <DD/MM/YYYY>])"`, comma-separated,
  or `""` if the soldier has no active exemptions. If out of scope: `"חסוי"`.
- `exemptions_visible: bool` — whether this row's real data was used.
- `has_global_exemption`, `has_partial_exemption`, `has_temporary_exemption: bool`
  — real values (not scope-redacted per soldier), computed as "this soldier
  has at least one active exemption in this category" for
  global/partial, and "at least one active exemption with an end_date" for
  temporary. These are included on each row **only if** the aggregate gate
  (see above) passes for the viewer; otherwise omitted from the row entirely.

Function returns `(rows, can_see_exemption_aggregates)` — a tuple, or a dict
wrapping both — for the route to assemble into the response.

### `backend/app/routes/scoring.py`

- `transparency()` now passes `user` (already available via
  `require_password_changed`) into `svc.transparency_rows(session, viewer=user)`.
- Response shape changes from `list[TransparencyRow]` to an object:
  ```python
  class TransparencyOut(BaseModel):
      rows: list[TransparencyRow]
      can_see_exemption_aggregates: bool
  ```
- `TransparencyRow` gains: `exemptions_display: str`, `exemptions_visible: bool`,
  and optional `has_global_exemption: bool | None = None`,
  `has_partial_exemption: bool | None = None`, `has_temporary_exemption: bool | None = None`
  (all `None` when the aggregate gate fails for the viewer).

This is a breaking response-shape change to `/scoring/transparency` (was a
bare array, now `{ rows, can_see_exemption_aggregates }`). The only consumer
is the frontend transparency page, updated in the same change.

## Frontend changes

### `frontend/src/api/scoring.ts`

Update the `getTransparency()` return type to match the new
`{ rows, can_see_exemption_aggregates }` shape.

### `frontend/src/pages/TransparencyPage.tsx`

- Soldiers tab: new column **פטורים**, `row.exemptions_display` as both
  display and `exportValue`. No special styling required beyond what the
  string already conveys (`חסוי` reads as redacted on its own).
- Sub-units tab (existing rollup ~lines 399-447 building `SubRow`s from
  `flatNodes`/`childrenMap`): three new columns **פטורים גלובליים**,
  **פטורים חלקיים**, **פטורים זמניים**.
  - If `can_see_exemption_aggregates` is `false`: render `"חסוי"` for all
    three columns on every subunit row (uniform, not per-node).
  - If `true`: for each subunit, count distinct soldiers in its subtree with
    `has_global_exemption` / `has_partial_exemption` / `has_temporary_exemption`
    `=== true`, respectively.
- Both new export columns flow through the existing `ExcelExportButton`
  usages unchanged (they already export whatever `rows`/columns are passed),
  so `transparency.xlsx` and `sub-units.xlsx` automatically match the screen.

## Testing

- Backend: unit tests for `transparency_rows()` covering: soldier in scope
  vs out of scope (correct `exemptions_display`/`exemptions_visible`);
  global+temporary overlay classification; aggregate booleans present only
  when viewer passes the role gate; admin with no scope sees `חסוי` at
  per-soldier level but real aggregate counts.
- Backend: route test for `/scoring/transparency` response shape
  (`rows` + `can_see_exemption_aggregates`).
- Frontend: extend `ImportSessionReviewPage`-style existing test patterns —
  actually `TransparencyPage.test.tsx` (if present) or add one — covering:
  פטורים column renders `exemptions_display` verbatim; sub-units columns
  show `חסוי` when the flag is false and correct sums when true.
