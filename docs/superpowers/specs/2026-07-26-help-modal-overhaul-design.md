# Help modal overhaul — design spec

## Goal

Audit and modernize the in-app help system (`HelpModal.tsx` + the algorithm
mode help, `AlgorithmModeHelpModal.tsx`) so that:

1. Help content is accurate and reflects currently-shipped behavior.
2. Help is role-aware: a tab whose underlying feature a role cannot access
   at all is not shown; tabs everyone sees get role-tailored wording,
   role-specific callout sections, and a role banner for orientation.
3. New tabs cover systems that currently have no help text at all
   (Approvals, Hierarchy/Eligibility, Hakpaza, Import).
4. The flow diagrams become genuinely interactive: live, read-only
   widgets driven by the viewing user's real data where meaningful
   (nothing writes to the DB), plus a clickable step-through for the
   swap process.
5. A real privacy gap found during the audit (gimelim medical reason
   visible to anyone who can see the record, contrary to what the help
   text claims) gets fixed in the backend, not just documented correctly.

## Current state

- `frontend/src/components/HelpModal.tsx` (1066 lines): five tabs (Swaps,
  Algorithm, Fairness, Deep Dive, and Gimelim — gimelim only added if
  `gimelimEnabled`). Fully static except `FairnessTab`, which already
  fetches the viewing user's own real effort breakdown via
  `getEffortBreakdown` (`api/scoring.ts`) — this is the pattern the new
  live widgets should follow.
- `frontend/src/components/AlgorithmModeHelpModal.tsx`: separate static
  modal explaining draft vs. publish mode, opened from
  `AlgorithmInlinePanel.tsx`. No role gating. Its content will be merged
  into the Algorithm tab's duty-manager/admin section rather than kept as
  a second modal.
- `frontend/src/searchRegistry.ts` already has the permission model this
  project should reuse: `isAdmin`, `canApprove` (admin/commander/DM),
  `canPlan` (admin/duty_manager), `authenticated`, currently private
  functions used to filter `PageEntry`, `QuickActionEntry`, and
  `HelpTopicEntry` (`getHelpTopicEntries(gimelimEnabled)`, used by
  `HeaderSearch.tsx` to jump straight to a help tab). These are not
  exported today — `HelpModal.tsx` has no dependency on this file.
- Roles (`backend/app/db/models.py:29-30`, `frontend/src/api/auth.ts`):
  `Me.role: "soldier"|"commander"|"duty_manager"|"admin"`, plus computed
  booleans `is_commander`, `is_duty_manager` sent per-user (no scope list,
  no `permissions[]` array). Backend authorization is scope-aware
  (`backend/app/auth/authz.py`) but the frontend only ever gets the
  coarse booleans — matches how `searchRegistry.ts` already treats roles,
  so the new help gating stays consistent with existing precedent rather
  than inventing finer-grained scope checks the frontend can't verify
  anyway.
- `frontend/src/api/hierarchy.ts: fetchTree()` returns the hierarchy
  already scoped to what the caller may see, with `path_ids` per node —
  reusable directly for a live, read-only eligibility widget with no new
  endpoint.

### Content-audit findings (verified against backend code)

Verified accurate, no changes needed: all of AlgorithmTab's phase/ladder/
tiebreak/swap-pass claims (`solver.py`), fairness A/W math and
denominator-inflation fix (`effort_score.py`), subtree/`path_ids`
eligibility, potential (`potential.py`), reserve hierarchy-distance
preference (`reserve.py`), swap approval logic (`swaps.py`), and gimelim's
future-slot/demote-promote flow (`gimelim.py`).

Found stale/incomplete:
- **Gimelim reason visibility** (`GimelimTab`): claims "visible only to
  duty managers," but `backend/app/routes/gimelim.py` returns `reason`
  with no role check at all. Real gap, not just a doc error — see fix
  below.
- **Undocumented solver behavior**: `_auto_relax_node_quotas` (node-quota
  relaxation retry, `solver.py:225-287`), alternate decomposition modes
  (`_interleaved_solve`, `_decomposed_solve`), the 15s stall-based
  early-stop (`STALL_SECONDS`, `solver.py:36-52`), and the
  `gimalim.reserve_fate` setting (`"keep"` vs `"release"`) are real
  behavior with zero help-text mention.

## Capability model

Extract the three predicate functions already living (unexported) in
`searchRegistry.ts` into a new shared module,
`frontend/src/auth/permissions.ts`:

```ts
export interface PermissionUser {
  role: "soldier" | "commander" | "duty_manager" | "admin";
  is_commander: boolean;
  is_duty_manager: boolean;
}
export function isAdmin(user: PermissionUser | null): boolean;
export function canApprove(user: PermissionUser | null): boolean; // admin | commander | duty_manager
export function canPlan(user: PermissionUser | null): boolean;    // admin | duty_manager
export function authenticated(user: PermissionUser | null): boolean;
```

`searchRegistry.ts` imports these instead of defining its own copies
(`SearchUser` becomes an alias of `PermissionUser`, or is removed in favor
of it — implementer's call, keep whichever reads cleaner). `HelpModal.tsx`
imports the same functions — one permission model for both search
filtering and help gating, no drift between what search offers and what
help shows.

## Tab registry & visibility matrix

`HelpModal.tsx` changes from a hardcoded tab array to a registry:
```ts
interface HelpTab {
  id: string;
  label: string;
  visible: (user: PermissionUser | null, gimelimEnabled: boolean) => boolean;
  Component: React.ComponentType<{ user: PermissionUser | null }>;
}
```
`buildTabs()` filters by `visible`; a tab that returns `false` is dropped
from the tab bar entirely (not rendered-then-disabled) — this is the
"can't see help for a page you can't access" requirement.

| Tab | Gate | Role-tailoring within the tab |
|---|---|---|
| Swaps | `authenticated` | Soldier copy: request/accept. `canApprove` adds an approve-flow callout. |
| Fairness | `authenticated` | Same for everyone (it's inherently personal/comparative). |
| Algorithm | `authenticated` | Soldier: abbreviated "how you get assigned." `canPlan`: full run mechanics, includes what used to be `AlgorithmModeHelpModal`'s draft/publish explanation. |
| **Approvals** (new) | `canApprove` | What each approval type needs, who can approve, effect of rejecting, what happens if you don't act. |
| **Hierarchy/Eligibility** (new) | `authenticated` | Same for everyone; the live widget only shows nodes/data already visible to the caller via `fetchTree()`. |
| **Hakpaza** (new) | `canApprove` | Commander/DM/admin flow: when to use it, who gets bumped, side effects on reserve chain. |
| Gimelim | `authenticated` (existing `gimelimEnabled` gate stays) | Soldier: what happens if you're released. `canApprove`: full operational flow, corrected reason-visibility line. |
| **Import** (new) | `canPlan` | Upload/review/commit flow, what gets overwritten, how to undo (if possible) — matches `page-import` in `searchRegistry.ts`, which is already `canPlan`-gated. |
| Deep Dive | `authenticated` | Same for everyone — opt-in reading, already labeled as such. |

`getHelpTopicEntries()` in `searchRegistry.ts` gets four new entries
(`approvals`, `hierarchy`, `hakpaza`, `import`) with matching `canAccess`,
so header search stays in sync with the tab bar.

## Gimelim privacy fix (backend)

`backend/app/routes/gimelim.py` (and any other route serving
`DutyDismissal.reason`, e.g. assignment detail routes — implementer greps
for all serializers touching this field): redact `reason` to `null` in
the response unless the requester is `admin`, a duty manager whose scope
covers the affected soldier, a commander whose subtree covers the
affected soldier, or the soldier themself. Reuses existing scope-check
helpers in `backend/app/auth/authz.py` (`is_duty_manager`,
`is_commander` + subtree check) rather than adding new ones.

## Interactive widgets

- **Eligibility checker** (new, in the Hierarchy/Eligibility tab):
  fetches `fetchTree()` (already scoped) and the shift-template list with
  `eligible_node_ids`. Two dropdowns — pick a node, pick a duty type —
  compute `eligible_node_ids ∩ path_ids ≠ ∅` client-side and show a live
  pass/fail. Purely derived from GETs already used elsewhere in the app;
  no new endpoint, no writes.
- **Fairness**: keep `FairnessTab`'s existing live personal breakdown.
  Add a "what if I get one more duty of type X" control that recomputes
  `effort_score` client-side from the real `A`/`W` already fetched — pure
  arithmetic, no request.
- **Swap flow**: convert the static `FlowStep`/`Arrow` diagram into
  clickable steps — clicking a step expands an inline panel with that
  step's side effects and rationale; the rest of the flow stays visible
  for context. No live data involved, this is a process explainer.
- **Algorithm phases / relaxation ladder**: this describes solver
  internals, not something safe or meaningful to run live against real
  data from the client. Keep the existing worked numeric example, but
  render it as a slider/step-through (pick which step to inspect) instead
  of a static wall of boxes — interactivity without pretending to be a
  live solver call.

## Files touched

- `frontend/src/auth/permissions.ts` (new) — extracted predicates.
- `frontend/src/searchRegistry.ts` — import from `permissions.ts` instead
  of local defs; add 4 new `HelpTopicEntry` rows.
- `frontend/src/components/HelpModal.tsx` — registry refactor, role
  props threaded into tab components, corrected gimelim copy, new
  undocumented-behavior callouts in Algorithm/Deep Dive.
- `frontend/src/components/help/ApprovalsTab.tsx`,
  `HierarchyEligibilityTab.tsx`, `HakpazaTab.tsx`, `ImportTab.tsx` (new).
- `frontend/src/components/AlgorithmModeHelpModal.tsx` — content merged
  into Algorithm tab, component removed; `AlgorithmInlinePanel.tsx`
  updated to open the help modal's Algorithm tab instead.
- `backend/app/routes/gimelim.py` (+ any other route serializing
  `reason`) — scope-based redaction.

## Testing

- Frontend: `HelpModal.test.tsx` (new/extended) covering tab visibility
  per role (soldier sees no Approvals/Hakpaza/Import tab; duty_manager
  sees Import; commander sees Approvals/Hakpaza but not Import), and the
  eligibility widget's pure computation function as a unit test.
- Backend: a test asserting `reason` is `None` in the gimelim
  read/list response for a soldier outside the scope, and present for
  the soldier themself, their commander, and a duty manager in scope.
- Manual: open help as each of the four roles in the running dev stack,
  confirm tab bar matches the matrix above and the eligibility widget
  reflects real hierarchy data without any network write.
