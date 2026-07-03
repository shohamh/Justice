# Potential page improvements — design

## Context

The Potential page (`frontend/src/pages/planning/PotentialPage.tsx`) shows a flat
list of every hierarchy node with rolled-up subtree potential numbers, and lets
you expand a row to see the per-soldier detail behind that number. Four gaps:

1. Soldier names in the expanded detail table are plain text — no way to open
   their profile.
2. No rank shown for soldiers in that detail table.
3. The main table is a flat list of every node in the tree (all levels mixed
   together) with no indication of parent/child relationships, and the column
   names (כשירים / התאמות / פוטנציאל סופי) aren't self-explanatory.
4. No way to see how much a node contributes to its parent's total.

## 1. Soldier detail table: clickable names

Replace the plain-text name cell with the existing `SoldierLink` component
(`frontend/src/components/SoldierLink.tsx`), already used the same way in
`AlgorithmProposalTable.tsx`. It opens the existing `UnifiedSoldierModal` via
`SoldierModalContext` — no new modal code.

```tsx
cell: (s) => <SoldierLink id={s.soldier_id} name={s.full_name} />,
```

## 2. Soldier detail table: rank column

Add a `rank` column between name and "counted". Requires a small backend
addition:

- `SoldierPotentialDetail` (service dataclass, `backend/app/services/potential.py`)
  gets a `rank: str | None = None` field. `compute_potential` already computes
  `rank = _rank_as_of(s, reference_date)` per soldier — just pass it through
  instead of discarding it, for both the counted and not-counted branches.
- `SoldierDetailOut` (route, `backend/app/routes/potential.py`) and
  `SoldierPotentialDetail` (frontend, `frontend/src/api/potential.ts`) get the
  matching `rank: str | null` field.
- No permission gating needed — rank is not a private field (see
  `PRIVATE_FIELD_NAMES` in `authz.py`, which only lists gender/phone/email).

## 3. Main table: show hierarchy structure

`flattenTree` (in `PotentialPage.tsx`) changes from unordered depth-first push
to depth-first traversal that also records each node's `depth` (root = 0),
still visiting parents before their children so the natural (unsorted) row
order nests visually. Represent this as `{ node: NodeDTO; depth: number }[]`
instead of `NodeDTO[]`, and update `cols`/`nodes` typing accordingly (`results`
lookups keyed by `node.id` are unaffected).

The name cell renders:

- Right-padding proportional to depth (RTL: `paddingRight: depth * 16`) to
  visually nest child rows under their parent.
- A small neutral level badge (pill, one shared style — not per-level colors)
  showing the human label for `node.level`, sourced from the existing
  `useLevelTypes()` hook (`frontend/src/hooks/useLevelTypes.ts`) the same way
  `HierarchyTree.tsx` does it (`labelByKey.get(node.level) ?? node.level`).
- The node name itself, unchanged.

Sorting by other columns still works as today (react-table sorts the row
array you hand it); depth-first order is only the *default* (pre-sort) order.

## 4. Main table: clarify column meanings

Add `headerTooltip` (existing `ColDef` field, precedent in
`TransparencyPage.tsx`) to the three numeric columns — no renaming:

- **כשירים**: "מספר החיילים הכשירים לתורנות כלשהי ביחידה זו ובכל תתי-היחידות שלה, נכון לתאריך הייחוס."
- **התאמות**: "סכום ההתאמות הידניות הפעילות שהוגדרו ליחידה זו ולתתי-היחידות שלה."
- **פוטנציאל סופי**: "כשירים + התאמות — האומדן הסופי לכמות התורנויות שהיחידה יכולה לספק."

## 5. Main table: "% of parent" column

New column `pct_of_parent`, placed immediately after "פוטנציאל סופי":

- Value: `results[n.id].final_potential / results[n.parent_id].final_potential`,
  formatted as a percentage (e.g. `"18%"`), computed client-side from the
  already-fetched `results` map — no backend change.
- Root nodes (`parent_id === null`) show `"—"`.
- If the parent's result isn't loaded yet, or its `final_potential` is `0`,
  show `"—"` (avoid divide-by-zero/NaN).
- Sortable numerically (missing/root → treated as `-Infinity` for sort
  purposes, consistent with other columns' `-1`/`-Infinity` sentinel
  convention already used in this file).

## Out of scope

- No change to the true collapsible-tree UX (rows stay one-per-node, flat,
  with depth-based indentation only) — confirmed with the user.
- No "% of siblings" column — confirmed "share of parent's total" only.
- No percentage for the "כשירים" column — confirmed "final potential only".
- No per-level color coding on the level badge (kept to one neutral style,
  unlike `HierarchyTree.tsx`'s `LEVEL_COLORS`) — smaller surface, not a
  navigation UI, doesn't need color differentiation.

## Testing

- Backend: extend `backend/app/services/tests/test_potential.py` with an
  assertion that `SoldierPotentialDetail.rank` is populated correctly
  (including the next-rank-date rollover case already covered by
  `_rank_as_of`).
- Frontend: no new test file expected (this page has no existing test
  suite); rely on `npm run typecheck` and manual verification in the running
  app, consistent with how the previous exemption-details change on this page
  was verified.
