# Bug Fixes Design — 2026-06-05

## Scope

Seven independent fixes across the algorithm, frontend UI, seed data, and translations.

---

## 1. Algorithm score preference (alpha term missing)

**Problem:** `SolverSettings.alpha` exists but `build_model` never uses it. The objective only minimises density; soldiers are not preferentially chosen by low score, so high- and low-score soldiers get duties assigned arbitrarily within the K variance bound.

**Fix:** In `backend/app/algorithm/model.py`, compute a constant pre-assignment normalised score per soldier and add an `alpha`-weighted penalty to the objective:

```
pre_norm_si = int(s.cumulative_score * 1000 / s.active_days)  # constant, computed outside CP model
```

Append `alpha_int * pre_norm_si * x[(di, si)]` to a new `score_terms` list and subtract it from the `Maximize` objective:

```python
objective = -(density_terms) - (reserve_dist_terms) - (score_terms)
model.Maximize(objective)
```

Lower pre-score soldiers are preferred because subtracting a smaller value maximises the objective more. `alpha_int = int(settings.alpha * 1000)`.

---

## 2. Density as hard constraint (configurable)

**Problem:** Density is a soft piecewise penalty. With defaults T=7, W=14 a soldier can get duties on consecutive days without penalty. The user wants density to be a hard limit.

**Fix:**

1. Remove the piecewise penalty block (`e1/e2/e3`, `density_terms`, `beta`) from `model.py`.
2. Replace with a hard constraint per W-day window per soldier:
   ```python
   model.Add(existing_fixed + sum(var_for_window) <= T)
   ```
3. Remove `beta` from `SolverSettings` (unused after change) and add `min_gap_days` as an alias for T/W or keep T/W names.
4. Add two new system settings loaded in `run_algorithm_job`:
   - `algorithm.window_days` (W, default `14`)
   - `algorithm.max_duties_per_window` (T, default `7`)
5. The existing infeasibility relaxation chain already increments T on failure — no changes needed there.

**Admin guidance:** Setting T=1, W=7 enforces a strict 7-day minimum gap.

---

## 3. Seed script — richer swap variety

**Problem:** The seed only creates open/pending_approval/applied/rejected/cancelled swaps. Missing: trade offers (with `offered_assignment_ids`) and one-sided approval states.

**Fix:** Extend `swap_defs` in `backend/app/scripts/seed.py`:

- Add 2 more entries with `offered_assignment_ids` set (trade offers in `open` status).
- Add 1 entry with `requester_side_approved=True`, `covering_side_approved=False` (one-sided approval pending).
- Keep existing 10 entries; expand to ~13 total.
- Update the summary print line.

---

## 4. Cover-offer modal in ShiftDetailPanel

**Problem:** `ShiftDetailPanel` shows open swap requests with only an inline "cover for free" button (`claimSwap`). No option to offer a trade. The `CoverOfferModal` component only exists inside `SwapsPage.tsx`.

**Fix:**

1. Extract `CoverOfferModal` from `frontend/src/pages/SwapsPage.tsx` into `frontend/src/components/CoverOfferModal.tsx` (same props interface).
2. Update `SwapsPage.tsx` to import from the new location.
3. In `ShiftDetailPanel.tsx`:
   - Add state: `coverSwap: SwapRequest | null` and `userDuties: EffectiveDuty[]`.
   - On open of the modal (when a swap is selected), lazily fetch `listEffectiveDuties(user.id)` and `listDutyTypes()`.
   - Replace the inline "cover for free" + `claimSwap` button with a single "הצע/קבל החלפה" button that sets `coverSwap`.
   - Render `<CoverOfferModal>` when `coverSwap !== null`.
4. Add `useAuth` import to `ShiftDetailPanel`.

---

## 5. Translation: "לוח פתוח" → "מרקטפלייס"

**File:** `frontend/src/i18n/he.json` line 489.

```json
"tab_board": "מרקטפלייס"
```

---

## 6. Unit calendar — default node and tree-walk order

**Problem:** `UnitCalendarPage` defaults to `ns[0]` (first flat API node) and lists nodes in arbitrary order.

**Fix in `frontend/src/pages/UnitCalendarPage.tsx`:**

1. Import `useAuth` and read `user.hierarchy_node_id`.
2. After `fetchTree()`, sort nodes into DFS preorder:
   ```ts
   function treeOrder(nodes: NodeDTO[]): NodeDTO[] {
     const byParent = new Map<string | null, NodeDTO[]>();
     for (const n of nodes) {
       const key = n.parent_id ?? null;
       byParent.set(key, [...(byParent.get(key) ?? []), n]);
     }
     const result: NodeDTO[] = [];
     function walk(parentId: string | null) {
       for (const n of byParent.get(parentId) ?? []) {
         result.push(n);
         walk(n.id);
       }
     }
     walk(null);
     return result;
   }
   ```
3. Default `nodeId` to `user.hierarchy_node_id` if present in the tree; otherwise fall back to the first node in tree order.

---

## 7. Bell icon colour

**Problem:** `NotificationBell` button has `hover:bg-gray-100` but no `text-gray-500` class, making the icon darker than the surrounding header icons (CircleUser, Settings, HelpCircle all use `text-gray-500 hover:text-indigo-600`).

**Fix in `frontend/src/components/NotificationBell.tsx`:**

Replace:
```tsx
className="relative p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
```
With:
```tsx
className="relative text-gray-500 hover:text-indigo-600 p-1"
```

---

## Files changed

| File | Change |
|------|--------|
| `backend/app/algorithm/model.py` | Add alpha score term; replace soft density with hard constraint |
| `backend/app/services/algorithm_bridge.py` | Read T and W from system settings |
| `backend/app/algorithm/types.py` | Remove `beta`; add/verify T,W fields |
| `backend/app/scripts/seed.py` | Extend swap_defs |
| `frontend/src/components/CoverOfferModal.tsx` | New file (extracted from SwapsPage) |
| `frontend/src/pages/SwapsPage.tsx` | Import CoverOfferModal from components |
| `frontend/src/components/ShiftDetailPanel.tsx` | Add cover offer modal flow |
| `frontend/src/i18n/he.json` | tab_board translation |
| `frontend/src/pages/UnitCalendarPage.tsx` | Default node + tree-walk order |
| `frontend/src/components/NotificationBell.tsx` | Icon colour fix |
