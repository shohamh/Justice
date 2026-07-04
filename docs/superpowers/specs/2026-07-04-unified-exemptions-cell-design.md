# Unified exemptions cell (Transparency + Potential pages)

## Goal

The פטורים (exemptions) column renders differently today in the Transparency
page and the Potential planning page. Unify them into one shared component
used by both, combining the best of each: Transparency's "until DD/MM/YYYY"
summary text, and Potential's clickable exemption-type chips — plus a richer,
soldier-specific detail modal on click (dates, reason, granted-by) instead of
the current type-only modal.

## Current state (why they differ)

- **Transparency** (`frontend/src/pages/TransparencyPage.tsx:548-553`): the
  cell renders a single backend-formatted string, `TransparencyRow.exemptions_display`
  (built in `backend/app/services/scoring.py`'s `_exemption_label`), e.g.
  `"פטור רפואי (גלובלי, עד 01/05/2026)"`. Plain text, not clickable, no modal.
- **Potential** (`frontend/src/pages/planning/PotentialPage.tsx:273-336`): the
  `reason` column renders `SoldierPotentialDetail.partial_exemption_names`
  as clickable blue-underline buttons that open `ExemptionTypeViewModal`
  (the exemption *type's* general config — flags, mapped duty types — not
  this soldier's specific exemption instance). `exemption_names` (full/global
  exemptions) render as plain joined text, not clickable.
- Neither endpoint returns per-exemption instance data (id, dates, reason)
  to these two table views today — both reduce to strings/name-arrays before
  the data reaches the frontend, even though the backend services building
  those strings have full `SoldierExemption` records (with `start_date`/
  `end_date`) in hand at the point of formatting.

## Permission model — two layers, matching what already exists today

The codebase already has **two separate, non-equivalent** permission checks
around exemption data, and this design must not blur them together:

1. **Table-level visibility** (whether the chip shows real data at all vs.
   a redacted placeholder) — a coarse, page-specific check that already
   exists and is unchanged by this design:
   - Transparency: per-soldier hierarchy `in_scope` check in
     `scoring.py` (`backend/app/services/scoring.py:538-544`) — computed
     independently per row, so one table can show real data for some
     soldiers and "חסוי" for others.
   - Potential: a single per-request `can_view_exemptions` flag computed
     once for the requested node (`backend/app/routes/potential.py`'s
     `_can_view_exemptions`), applied uniformly to every soldier in that
     response.
2. **Detail-level visibility** (whether `reason` is shown once a chip is
   clicked) — a stricter, independent check already used by the existing
   single-soldier exemptions endpoint (`backend/app/routes/exemptions.py:60-70`):
   `Action.EXEMPTION_READ` authorization, then `can_see_private()` gating
   `reason` specifically. `granted_by` is shown whenever the base
   `EXEMPTION_READ` check passes, matching existing behavior — it is not
   further gated by `can_see_private()`.

`is_medical`/`is_commander_exemption` flags carry no additional redaction
today (confirmed — they're display-only badges), so this design introduces
none either.

**Why these must stay separate:** if the two were merged, either the modal
would leak `reason` to viewers who only pass the coarse table-level check
(privacy regression), or the table would over-hide entries that should be
visible under its own existing (looser) rule. Keeping them separate also
avoids leaking the *count* of hidden exemptions — see below.

## Data model — new structured field on both endpoints (table-level only)

Both endpoints get a new **additive** field carrying per-exemption summary
data for the table cell — no `reason`, no `granted_by`. Existing fields
(`exemptions_display`, `exemption_names`, `partial_exemption_names`) are
left untouched — Transparency's CSV export (`exportValue`) keeps reading
`exemptions_display` unchanged.

```python
class ExemptionSummaryItem(BaseModel):
    id: uuid.UUID
    exemption_type_name: str
    is_global: bool          # true = full/global exemption, false = partial
    start_date: date
    end_date: date | None
```

- `TransparencyRow.exemptions: list[ExemptionSummaryItem]` — built from the
  same `_active_exemptions_by_soldier()` data `scoring.py` already computes
  for `exemptions_display`, just not reduced to a string. **When the
  existing per-row `in_scope` check fails, this array is empty** (not a
  count-preserving list of redacted placeholders) — the frontend falls back
  to the existing `exemptions_visible: false` flag already on
  `TransparencyRow` to render the "חסוי" placeholder, exactly matching
  today's behavior of revealing nothing, not even a count.
- `SoldierPotentialDetail.exemptions: list[ExemptionSummaryItem]` — same
  shape, built from `active_exemptions` already computed in
  `backend/app/services/potential.py`, tagged `is_global` per item. **When
  the existing per-request `can_view_exemptions` check fails, this array is
  empty** and the frontend falls back to the existing
  `t("potential.reason_exempted_restricted")` placeholder (triggered today
  by `exemption_names`/`partial_exemption_names` being `null` — this design
  doesn't change that signal, `exemptions` simply mirrors it).

## New endpoint for detail-level data (the modal)

`GET /soldiers/{soldier_id}/exemptions/{exemption_id}` — a new, narrow
endpoint that independently re-authorizes on every call (defense in depth:
the frontend only offers a click target when the table-level check passed,
but the server never trusts that alone, since exemption IDs could otherwise
be guessed/replayed):

```python
class ExemptionDetailOut(BaseModel):
    id: uuid.UUID
    exemption_type_name: str
    is_global: bool
    start_date: date
    end_date: date | None
    reason: str | None       # None if viewer fails can_see_private()
    granted_by_name: str | None   # shown whenever EXEMPTION_READ passes
```

Authorization: `authorize(session, user, Action.EXEMPTION_READ, target_node=...)`
(same as `list_exemptions` today; raises 403 if it fails), then
`can_see_private(session, user, soldier)` gates `reason` — identical logic
to the existing single-soldier endpoint, just scoped to one exemption
instance instead of the soldier's full list.

## Frontend: shared `ExemptionsCell` component

New component: `frontend/src/components/ExemptionsCell.tsx`.

```tsx
interface ExemptionsCellProps {
  exemptions: ExemptionSummaryItem[];
  visible: boolean;   // Transparency: row's exemptions_visible; Potential: !!exemption_names (i.e. not redacted)
  soldierId: string;
}
```

- When `visible` is `false`: render the existing placeholder text for that
  page ("חסוי" for Transparency, `t("potential.reason_exempted_restricted")`
  for Potential) — no chips, nothing clickable, exactly today's behavior.
- When `visible` is `true` and the array is empty: render "—".
- Otherwise, each item renders as a small clickable chip/button:
  `{exemption_type_name}` alone when `end_date` is `null`, or
  `{exemption_type_name} (עד DD/MM/YYYY)` when it exists — Transparency's
  existing date phrasing, now applied consistently in both tables.
- Both global and partial exemptions render identically and are both
  clickable (no separate visual treatment beyond the date suffix already
  implied above).
- Clicking a chip opens the shared exemption-instance modal (below),
  passing `soldierId` and the clicked item's `id`. Modal open/close state
  is owned internally by `ExemptionsCell` — neither page needs to manage
  it.

## Frontend: shared `ExemptionInstanceModal` component

New component: `frontend/src/components/ExemptionInstanceModal.tsx`. This is
the click target for `ExemptionsCell` specifically — it does **not** replace
`ExemptionTypeViewModal`, which keeps its existing separate use elsewhere
(e.g. the exemption-types admin config screen). Read-only (no grant/revoke
controls — out of scope for this change).

On open, it fetches `GET /soldiers/{soldierId}/exemptions/{exemptionId}`
(the new endpoint above) rather than reusing table-row data, so detail-level
authorization is always freshly checked server-side. Renders:

- Exemption type name + category badge (global/partial)
- Start date, end date (or "ללא הגבלה" when `end_date` is `null`)
- `reason`, if present in the response (omitted/blank if the viewer fails
  `can_see_private()` — no placeholder text implying a hidden reason exists,
  since that itself would leak information; the field is simply absent)
- `granted_by_name`, if present

If the fetch returns 403 (the viewer's access changed between page-load and
click, or something bypassed the table-level gate), show a plain "אין הרשאה
לצפות בפרטים" message in the modal body instead of crashing.

This mirrors `ExemptionsPanel`'s existing per-exemption card content,
presented as a modal instead of an inline panel, without the grant/revoke
actions.

## Wiring the two pages

- **TransparencyPage**: the `exemptions` column's `cell` renders
  `<ExemptionsCell exemptions={r.exemptions} visible={r.exemptions_visible} soldierId={r.soldier_id} />`
  instead of the plain string. `exportValue` is unchanged
  (`r.exemptions_display`).
- **PotentialPage**: the `reason` column, in both the `counted` (partial
  exemption) and `reason === "exempted"` (full exemption) branches, renders
  `<ExemptionsCell exemptions={s.exemptions} visible={s.exemption_names !== null} soldierId={s.soldier_id} />`
  instead of today's manual button-mapping / plain-text branching and the
  `openExemptionModal`/`viewingExemption` state + `ExemptionTypeViewModal`
  wiring, all of which are removed from this page (the reason-label
  fallback path for non-exemption reasons, e.g. "on_break", is unchanged).

## Testing

- Backend: unit tests for the new `exemptions` field on both endpoints —
  dates present/absent, the array is empty (not count-preserving) when the
  table-level check fails, partial vs. global tagging is correct. Separate
  tests for the new detail endpoint: 403 when `EXEMPTION_READ` fails,
  `reason` present/absent based on `can_see_private()`, `granted_by_name`
  shown whenever the base check passes regardless of `can_see_private()`.
- Frontend: a component test for `ExemptionsCell` (renders chips, the
  `visible=false` placeholder, empty state, click opens the modal and
  fetches detail) plus a test for the modal's 403 handling, plus updates to
  existing `TransparencyPage`/`PotentialPage` tests that reference the old
  rendering/modal behavior.

## Out of scope

- Grant/revoke actions from the new modal (view-only).
- Linking the new modal to the exemption type's mapped duty types (that
  remains exclusive to `ExemptionTypeViewModal`'s existing usage).
- Any change to `exemptions_display`, `exemption_names`,
  `partial_exemption_names`, or the CSV export path.
- Color-coding or badges per exemption category beyond the existing
  "(עד DATE)" suffix.
