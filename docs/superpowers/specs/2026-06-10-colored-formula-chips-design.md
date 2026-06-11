# Spec: Colored Formula Chips + Hakpaza Scoring Fix

**Branch:** `feat/duty-type-operational-fields` (add-on to nikud badge feature)
**Date:** 2026-06-10

---

## Background

Feature 1 (already merged) added a score badge and plain-text formula to every duty-related event card in the Duty History panel. The formula looks like:

> ניקוד: 3 × 1.0 × 0.2 + 2 × 1.0 × 1.3 = 3.2

This spec adds:
1. A **hakpaza scoring bug fix** (Section 1)
2. A **`score_segments` JSON payload** (Section 2) that tags each formula segment with its type
3. **Colored segment chips** rendered below the formula (Section 3)

---

## Section 1 — Hakpaza Scoring Fix

### Problem

When a `ForcedCallup` is approved (`POST /hakpaza/{id}/approve`), the current code:
1. Creates a new `DutyAssignment` (regular, `is_reserve=False`) for the replacement soldier — scores at ×1.0
2. Also creates a `ScoreAdjustment` with `delta = spd * days * callup_multiplier`

This yields total effective multiplier = **1 + callup_multiplier** (e.g. ×3.0 when multiplier is 2.0), not the intended ×2.0.

### Fix

**`backend/app/db/models.py`** — add column to `DutyAssignment`:
```python
forced_call_up_multiplier: Mapped[Decimal | None] = mapped_column(
    Numeric(6, 2), nullable=True, default=None
)
```

**`backend/app/routes/hakpaza.py`** — in the `approve` endpoint:
- Set `new_assignment.forced_call_up_multiplier = h.callup_multiplier`
- Remove the `ScoreAdjustment` creation entirely

**`backend/app/services/scoring.py`** — in `effective_duty_days` (the per-day multiplier logic):
```python
# Before the is_reserve branch, add:
if a.forced_call_up_multiplier is not None:
    mult = a.forced_call_up_multiplier
elif a.is_reserve:
    ...  # existing reserve branch
else:
    ...  # existing non-reserve branch
```

**`backend/app/services/duty_history.py`** — in `_score_parts` → `_day_mult`:
- Before the `is_reserve` check, add the same `forced_call_up_multiplier` branch

**Alembic migration:**
- Add `forced_call_up_multiplier` column (nullable)
- For each `ForcedCallup` with `status='approved'`, find its `replacement_assignment_id`, set `forced_call_up_multiplier = h.callup_multiplier`
- Delete all `ScoreAdjustment` rows whose `reason` starts with `"הקפצה פיקודית"` (these are the ones the old code created; replace with the field)

**No new tests required for scoring** — existing scoring tests already cover the multiplier path once the field is in place. Add one integration test that verifies: after approving a hakpaza, the replacement assignment has `forced_call_up_multiplier` set and no `ScoreAdjustment` exists.

---

## Section 2 — `score_segments` Metadata Format

### Change to `_score_parts`

Currently returns `(score_total: str, formula: str)`. Change to return `(score_total: str, formula: str, segments_json: str)`.

The internal segment tuple changes from `(count, mult)` to `(count, mult, seg_type)`.

`seg_type` is determined per day in `_day_mult`:

| Priority | `seg_type` | condition |
|---|---|---|
| 1 | `forced_call_up` | `a.forced_call_up_multiplier is not None` (check first) |
| 2 | `dismissed` | day falls inside any dismissal range |
| 3 | `reserve_called_up` | `a.is_reserve` and day inside `called_up_from…called_up_to` |
| 4 | `reserve_standby` | `a.is_reserve` and day outside called_up window |
| 5 | `regular` | otherwise |

Consecutive days with the same `(mult, seg_type)` pair are grouped into one segment.

`segments_json` is the JSON encoding of:
```json
[
  {"days": 3, "spd": "1.0", "mult": "0.2", "type": "reserve_standby"},
  {"days": 2, "spd": "1.0", "mult": "1.3", "type": "reserve_called_up"}
]
```

All numeric values are strings in `_fmt()` notation.

### Metadata propagation

Every place that calls `_score_parts` in `get_duty_history` (assignment, call_up, dismissal events) must store the third return value as `"score_segments"` in the event's metadata dict.

Cancellation events do not call `_score_parts` and therefore do not get `score_segments`.

---

## Section 3 — Frontend Colored Chips

### Parsing

On the frontend, parse `e.metadata.score_segments` with `JSON.parse()` only when the string is present. Type it as:
```ts
interface ScoreSegment {
  days: number;
  spd: string;
  mult: string;
  type: "regular" | "reserve_standby" | "reserve_called_up" | "forced_call_up" | "dismissed";
}
```

### Rendering (inside the expanded card section)

Replace the current plain-text formula `<p>` with:

1. **Formula line** — keep identical text: `ניקוד: {formula} = {total}` (or just `{total}` when no formula)
2. **Chips row** — a `<div className="flex flex-wrap gap-1 mt-1">` with one chip per segment

Each chip: `<span>` showing **label + ×mult** in the segment's color.

Chip colors (Tailwind classes):

| type | chip classes |
|---|---|
| `regular` | `bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200` |
| `reserve_standby` | `bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200` |
| `reserve_called_up` | `bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200` |
| `forced_call_up` | `bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200` |
| `dismissed` | `bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200` |

Chip labels (Hebrew):

| type | label |
|---|---|
| `regular` | `רגיל` |
| `reserve_standby` | `רזרבה` |
| `reserve_called_up` | `הוקפץ מרזרבה` |
| `forced_call_up` | `הקפצה פיקודית` |
| `dismissed` | `שוחרר` |

Chip text: `{label} ×{mult}` — e.g. `רזרבה ×0.2`, `הקפצה פיקודית ×2.0`

Chips are only shown when `score_segments` is present and non-empty. When `score_segments` is absent (e.g. cancellation), keep the existing score display as-is.

### Constraints

- The formula text line is **not** removed — chips are additive
- Chips row is part of the expanded content (not visible when card is collapsed)
- No i18n required — labels are hardcoded Hebrew strings (same pattern as existing badge text)

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/db/models.py` | Add `forced_call_up_multiplier` to `DutyAssignment` |
| `backend/alembic/versions/<new>.py` | Migration: add column, backfill, remove old ScoreAdjustments |
| `backend/app/routes/hakpaza.py` | Set field instead of creating ScoreAdjustment |
| `backend/app/services/scoring.py` | Branch on `forced_call_up_multiplier` before reserve check |
| `backend/app/services/duty_history.py` | `_score_parts` returns 3 values; `_day_mult` tracks seg_type |
| `backend/tests/integration/test_hakpaza_approve.py` | New test: no ScoreAdjustment, field is set |
| `frontend/src/components/DutyHistoryPanel.tsx` | Parse `score_segments`, render chips |

---

## Out of Scope

- Changing the formula text format
- Adding i18n keys for chip labels
- Showing chips on collapsed cards
- Modifying any other page or component
