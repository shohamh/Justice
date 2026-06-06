# Plan D — Transparency & Fairness Accuracy
**Date:** 2026-06-06  
**Issues:** #6, #13, #14, #25

---

## Overview

Four issues where the transparency and fairness data shown to users is either incorrect or unclear. Fixes range from a profile-edit field to redesigning the "why did I get this duty?" explanation.

---

## 1. Active days — enrolled_at editable (#6)

**Root cause:** `active_days` is computed as `(today - soldier.enrolled_at).days`. `enrolled_at` defaults to `CURRENT_DATE` on system registration, so all soldiers registered around the same time show identical active days.

**Fix:** Make `enrolled_at` editable in the soldier profile so commanders/admins can set the correct date (i.e., when the soldier actually joined the unit, not when they registered in this app).

**Backend:**
- `PATCH /soldiers/{id}` already exists; ensure `enrolled_at` is in the allowed update fields (check `SoldierEditRequest` schema — add if missing).

**Frontend:**
- In the soldier edit modal (`UnifiedSoldierModal` or `SoldierEditModal`), add an `enrolled_at` date field labelled **"תאריך הצטרפות ליחידה"**.
- Visible to commanders and admins only (not the soldier themselves).
- Displayed as `dd.mm.yyyy` per Plan B standard.

**Note:** This is a data-fix mechanism, not an algorithm change. After updating `enrolled_at` values, active_days will diverge naturally.

---

## 2. Exemption effect on transparency percentage (#13)

**Current state:** The "% active" column in the Subunits view of `TransparencyPage` counts soldiers with no active exemption, but the exemption status may not be propagated to the hierarchy node active-count calculation.

**Design:**
- Backend: the `/scoring/transparency` endpoint's per-node aggregation must recompute `active_soldier_count` as: soldiers in this node where no full-coverage exemption is active as of today.
- "Full-coverage exemption" = an exemption whose `ExemptionType.is_global = true`, OR one that covers all active duty types.
- The `TransparencyRow` (per-soldier) already has exemption info implicitly (via `active_days` reduction). The per-node summary needs an explicit `active_count` and `exempted_count` field.
- Frontend: in the Subunits table, add an **"ממוצרים"** (exempted) count column, and show `active_count / total` as the percentage with a tooltip listing how many are exempted.

**Backend change:** Extend the subunits aggregation endpoint to return `exempted_count` alongside `active_count`.

---

## 3. Excel export sorted by hierarchy (#14)

**Current state:** `downloadSubUnitsExport` in the backend writes rows in query order, not tree order.

**Design:**
- The export function fetches the hierarchy tree and performs a DFS traversal to get the sorted node list.
- Rows in the Excel file follow this order: for each node in DFS order, write all soldiers belonging to that node sorted by name.
- Add a "Node" column as the first column showing the hierarchy path (e.g., "יחידה / ענף א / מדור 1").
- Same fix applies to both the soldiers tab and any per-node summary tabs.

**Backend change:** In `scoring.py` export handler, build node order from `hierarchy.py` tree fetch before writing rows.

---

## 4. "למה קיבלתי?" redesign (#25)

**Current state:** `ExplanationModal` shows raw data that is hard to interpret.

**Design — redesigned explanation:**

The modal shows three sections:

**Section 1 — Summary sentence (top, bold):**
> "קיבלת תורנות זו כי היה לך הניקוד הנמוך ביותר מבין 12 חיילים כשירים לתאריך זה."

**Section 2 — Your standing at assignment time:**
| שדה | ערך |
|-----|-----|
| ניקוד מצטבר | 14.5 |
| דירוג בין כשירים | 3 / 12 |
| תורנויות קודמות בתקופה | 1 |
| אילוצים פעילים | אין |

**Section 3 — Why others weren't chosen:**
A short list of reasons why the next candidates were ranked lower (e.g., "חייל ב' — ניקוד גבוה יותר (21.3)", "חייל ג' — אילוץ אישי מאושר בתאריך זה").

**Data source:** `AssignmentExplanation` model already exists in the DB and stores `ExplanationData`. The `ExplanationData` dataclass in `algorithm/types.py` needs to be verified to include ranked-candidates data; add if missing.

**Frontend:** `ExplanationModal.tsx` redesigned with the three sections above. RTL layout. Plain Hebrew throughout.

---

## Data / API changes

| Change | Type |
|--------|------|
| `PATCH /soldiers/{id}`: add `enrolled_at` to editable fields | Extend existing |
| Subunits aggregation endpoint: add `exempted_count` | Extend existing |
| Excel export: sort by DFS tree order | Bug fix |
| `ExplanationData` dataclass: ensure ranked candidates included | Extend existing |

---

## Testing

- Commander edits soldier's `enrolled_at` → `active_days` changes on next transparency load.
- Exempted soldier reduces `active_count` in their node's transparency row.
- Excel export rows follow tree order with hierarchy path column.
- "למה קיבלתי?" modal shows summary sentence, standing table, and rejected-candidates list.
