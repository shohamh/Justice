# Swap approval card clarity — design

## Problem

The swap request cards (mobile screenshot: "incoming" swap card, seen by an
invited candidate) are unclear:

1. **Misleading empty-state text.** `DirectCommanderApproval` shows the same
   generic string ("לא נדרש אישור מפקד" — "commander approval not required")
   whenever an approval-kind list is empty, regardless of *why* it's empty.
   For the duty-manager row this happens because no `DutyManagerScope` covers
   the soldier's branch — a data/scoping fact, not a settings toggle — but the
   text reads as if duty-manager approval is globally turned off.
2. **No way to configure duty-manager approval requirement.** The backend
   already supports `swaps.require_duty_manager_approval` (defaults to `True`
   when unset — see `_require_duty_manager_approval` in
   `backend/app/services/swaps.py`), but there is no admin UI control for it.
   Confirmed absent from `frontend/src/pages/SystemSettingsPage.tsx` and not
   duplicated anywhere else in the frontend — only `swaps.require_manager_approval`
   (commander) is exposed today.
3. **Layout is hard to scan.** Requester vs. candidate status is buried below
   the reason text and action buttons, rendered as flat inline spans with no
   visual separation between "my side" and "the other side," and no per-line
   bullets.
4. **Reason text has no label.** `swap.reason` renders as bare text with no
   prefix, so a reader can't tell at a glance what the text is.

## Scope

Frontend-only, except for one new system setting definition (no backend
logic changes — the setting is already read/enforced, just not configurable
via UI).

Applies to every place a swap card shows requester + candidate(s) side by
side, in `frontend/src/pages/SwapsPage.tsx`:
- `renderMySwapCard` ("mine" tab)
- `renderIncomingCard` ("incoming" tab) — the card in the screenshot
- `PendingApprovalCard` ("pending" tab)

And the swaps tab of `frontend/src/pages/ApprovalsPage.tsx` (admin/manager
approval view).

## Changes

### 1. Add the missing setting

In `SystemSettingsPage.tsx`, add a new row next to the existing
`swaps.require_manager_approval` entry:

```
{ key: "swaps.require_duty_manager_approval", label: "דורש אישור אחראי תורנויות",
  description: "האם החלפות דורשות אישור אחראי תורנויות", type: "boolean", defaultValue: true }
```

No other file changes needed for this — `getSwapConfig()` /
`_require_duty_manager_approval` already read this key correctly.

### 2. Kind-aware empty-state text

`DirectCommanderApproval` (`frontend/src/components/DirectCommanderApproval.tsx`)
currently renders `t("swaps.no_managers_required")` for any empty
`approvals` list. Add an `approverKind: "commander" | "duty_manager"` prop
(threaded through from every call site, which already knows which group
it's rendering via `groupByKind`). When `approvals.length === 0`:
- `approverKind === "commander"` → keep existing "לא נדרש אישור מפקד" (this
  case is legitimate: an empty commander chain does mean no commander
  requirement exists for this soldier).
- `approverKind === "duty_manager"` → new string, `swaps.no_duty_manager_assigned`
  = **"אין אחראי תורנויות משויך למסגרת"** ("no duty manager assigned to the
  unit/scope"). This is shown regardless of whether the setting is on —
  because the setting being on just means "if a duty manager exists in the
  chain, they must approve," and here none exists to ask.

### 3. Reason label

Wrap the three bare `swap.reason` renders in `SwapsPage.tsx` (lines ~333,
392, 440) with the existing `swaps.reason` ("סיבה") label, e.g.:

```
{swap.reason && <p className="...">{t("swaps.reason")}: {swap.reason}</p>}
```

### 4. Two-column approval layout

Replace the current flat/inline approval status rendering with a shared
two-column block, used by all four call sites listed in Scope:

- **Position:** immediately under the duty header (type/location/date row),
  above the reason text and action buttons.
- **Columns:** right column = "my side" where the viewer is a participant
  (the invited candidate's own row in `renderIncomingCard`; the requester's
  own row in `renderMySwapCard`), or the requester where the viewer has no
  personal side (`PendingApprovalCard`, `ApprovalsPage` swap tab — labeled
  "מבקש"/"מועמד" rather than "שלי"). Left column = the other side. A vertical
  separator divides them. "My side" is always right, per RTL reading order.
- **Bulleted lines per column:** each applicable fact gets its own bullet —
  soldier-side confirmation (✓/✗/pending), commander approval row, and
  duty-manager approval row (each via `DirectCommanderApproval`, using the
  kind-aware text from #2).
- **Column-level status color:** each column gets ONE aggregate background
  tint + leading icon, computed from all bullets in that column:
  - **Green + ✓** only if every required approval in that column is done
    (soldier confirmed, and every present commander/duty-manager group is
    satisfied).
  - **Red + ✗** if anything in that column was explicitly rejected.
  - **Amber/orange + ellipsis (⋯) icon** otherwise (still pending).
  - A column with nothing required at all (e.g. no candidates yet) is
    neutral/gray, no color.
  - `PendingApprovalCard` and the `ApprovalsPage` swap tab can have more
    than one live candidate. There, render one requester column plus one
    column per candidate (not a fixed "my side"/"other side" pair), each
    separated by a vertical divider and independently colored using the
    same rules above.

## Out of scope

- No change to the actual approval/rejection business logic — this is
  purely a display + settings-visibility fix.
- No change to `_require_duty_manager_approval`'s default-when-unset
  behavior (already safely defaults to `True`).
- Multi-candidate layouts beyond 2 columns (requester + N candidates) keep
  their existing flex-wrap card-per-candidate structure — only the visual
  treatment (bullets, color, position) of each card/column changes.

## Testing

- `DirectCommanderApproval` unit test: empty duty_manager list renders the
  new string, empty commander list still renders the old one.
- `SwapsPage.test.tsx` / `ApprovalsPage.test.tsx`: update existing snapshots/
  assertions for the moved reason label and any changed empty-state copy.
- Manual check in dev: incoming-swap card for a soldier whose branch has no
  `DutyManagerScope` shows the new distinct text, not "not required."
