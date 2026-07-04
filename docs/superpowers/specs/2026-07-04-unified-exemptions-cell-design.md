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

## Data model — new structured field on both endpoints

Both endpoints get a new **additive** field carrying per-exemption instance
data. Existing fields (`exemptions_display`, `exemption_names`,
`partial_exemption_names`) are left untouched — Transparency's CSV export
(`exportValue`) keeps reading `exemptions_display` unchanged, so nothing
about export behavior changes.

```python
class ExemptionSummaryItem(BaseModel):
    id: uuid.UUID
    exemption_type_id: uuid.UUID
    exemption_type_name: str
    is_global: bool          # true = full/global exemption, false = partial
    start_date: date
    end_date: date | None
    reason: str | None
    redacted: bool           # true when the viewer lacks permission to see details
```

- `TransparencyRow.exemptions: list[ExemptionSummaryItem]` — built from the
  same `_active_exemptions_by_soldier()` data `scoring.py` already computes
  for `exemptions_display`, just not reduced to a string. Where today's code
  redacts an entry to "חסוי" for unauthorized viewers, the new array instead
  includes an item with `redacted=True` (name/dates blanked) so the frontend
  renders a non-clickable placeholder chip in the same slot, rather than
  exposing a bare "חסוי" string with no structure.
- `SoldierPotentialDetail.exemptions: list[ExemptionSummaryItem]` — same
  shape, built from `active_exemptions` already computed in
  `backend/app/services/potential.py`, tagged `is_global` per item (the
  distinction that today splits into `exemption_names` vs
  `partial_exemption_names`).

## Frontend: shared `ExemptionsCell` component

New component: `frontend/src/components/ExemptionsCell.tsx`.

```tsx
interface ExemptionsCellProps {
  exemptions: ExemptionSummaryItem[];
}
```

- Each non-redacted item renders as a small clickable chip/button:
  `{exemption_type_name}` alone when `end_date` is `null`, or
  `{exemption_type_name} (עד DD/MM/YYYY)` when it exists — Transparency's
  existing date phrasing, now applied consistently in both tables.
- Redacted items (`redacted: true`) render as plain, non-clickable "חסוי"
  text in the same slot — preserving today's confidentiality behavior
  exactly.
- Both global and partial exemptions render identically and are both
  clickable (no separate visual treatment beyond the date suffix already
  implied above).
- Empty array renders "—", matching both pages' current empty state.
- Clicking a non-redacted chip opens the shared exemption-instance modal
  (below). Modal open/close state is owned internally by `ExemptionsCell`
  — neither page needs to manage it.

## Frontend: shared `ExemptionInstanceModal` component

New component: `frontend/src/components/ExemptionInstanceModal.tsx`. This is
the click target for `ExemptionsCell` specifically — it does **not** replace
`ExemptionTypeViewModal`, which keeps its existing separate use elsewhere
(e.g. the exemption-types admin config screen). Read-only (no grant/revoke
controls — out of scope for this change):

- Exemption type name + category badge (global/partial)
- Start date, end date (or "ללא הגבלה" when `end_date` is `null`)
- Reason, if present
- Granted-by, resolved to a soldier name (mirrors the resolution
  `ExemptionsPanel` already does for its per-exemption cards)

This mirrors `ExemptionsPanel`'s existing per-exemption card content,
presented as a modal instead of an inline panel, without the grant/revoke
actions.

## Wiring the two pages

- **TransparencyPage**: the `exemptions` column's `cell` renders
  `<ExemptionsCell exemptions={r.exemptions} />` instead of the plain
  string. `exportValue` is unchanged (`r.exemptions_display`).
- **PotentialPage**: the `reason` column, in both the `counted` (partial
  exemption) and `reason === "exempted"` (full exemption) branches, renders
  `<ExemptionsCell exemptions={s.exemptions} />` instead of today's manual
  button-mapping / plain-text branching and the `openExemptionModal`/
  `viewingExemption` state + `ExemptionTypeViewModal` wiring, all of which
  are removed from this page (the reason-label fallback path for
  non-exemption reasons, e.g. "on_break", is unchanged).

## Testing

- Backend: unit tests for the new `exemptions` field on both endpoints —
  dates present/absent, redaction still hides instance details, partial vs.
  global tagging is correct.
- Frontend: a component test for `ExemptionsCell` (renders chips, redacted
  placeholder, empty state, click opens the modal) plus updates to existing
  `TransparencyPage`/`PotentialPage` tests that reference the old
  rendering/modal behavior.

## Out of scope

- Grant/revoke actions from the new modal (view-only).
- Linking the new modal to the exemption type's mapped duty types (that
  remains exclusive to `ExemptionTypeViewModal`'s existing usage).
- Any change to `exemptions_display`, `exemption_names`,
  `partial_exemption_names`, or the CSV export path.
- Color-coding or badges per exemption category beyond the existing
  "(עד DATE)" suffix.
