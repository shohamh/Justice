# ניקוד Badge in Duty History

**Date:** 2026-06-09  
**Status:** Approved

## Overview

Show a ניקוד (score) badge on every duty-related event card in the Duty History panel. The badge shows the score contribution of that duty at a glance; expanding the card reveals the full formula breakdown.

## Scope

Affected event types: `assignment`, `cancellation`, `call_up`, `dismissal`.  
Not affected: `exemption_request`, `personal_constraint`.

## Data Model

Two new keys are added to the `metadata` dict of each duty-related `TimelineEvent`:

| Key | Type | Example |
|-----|------|---------|
| `score_total` | string (Decimal) | `"10.4"` |
| `score_formula` | string | `"3 × 4.0 × 0.2 + 2 × 4.0 × 1.3"` |

Formula notation: `{days} × {score_per_day} × {multiplier}` per segment, segments joined with ` + `.

### Multiplier rules (per day)

| Situation | Multiplier |
|-----------|-----------|
| Regular assignment day | 1.0 |
| Reserve standby day | `scoring.reserve_standby_multiplier` (default 0.2) |
| Reserve called-up day | `scoring.reserve_called_up_multiplier` (default 1.3) |
| Dismissed day | `scoring.dismissed_multiplier` (default 0.0) |

### Score per event type

- **`assignment` (regular, no dismissals):** `N × SPD × 1.0`
- **`assignment` (regular, with dismissal days):** standby days and dismissed days are separate segments
- **`assignment` (reserve, standby only):** `N × SPD × 0.2`
- **`assignment` (reserve, with call-up):** standby and called-up days are separate segments
- **`call_up`:** only the called-up sub-period — `N × SPD × 1.3`
- **`dismissal`:** only that dismissal's sub-period — `N × SPD × 0.0`
- **`cancellation`:** `score_total = "0"`, `score_formula` omitted

## Backend Changes

**File:** `backend/app/services/duty_history.py`

Add a private helper `_score_parts` that takes an assignment, its dismissals, `score_per_day`, and the three multipliers. It iterates each day from `start_date` to `end_date`, classifies it into a bucket (regular / standby / called-up / dismissed), groups consecutive same-bucket days, and returns `(score_total: str, score_formula: str)`.

In `get_duty_history`:
1. Load multipliers once at the top using `_get_multiplier_setting` (imported from `scoring.py`).
2. For each assignment, look up `score_per_day` from the `DutyType` (already fetched).
3. Call `_score_parts` and inject results into the `metadata` dict of:
   - The `assignment` event (full span)
   - The `call_up` event (only called-up sub-period)
   - Each `dismissal` event (only that dismissal's sub-period)
   - The `cancellation` event (`score_total = "0"`, no formula key)

No new endpoints. No changes to `TimelineEventOut` schema (metadata is already `dict`).

## Frontend Changes

**File:** `frontend/src/components/DutyHistoryPanel.tsx`

### Collapsed card

Add a small neutral pill badge in the top-right cluster, next to the existing status badge:

```
[published]  [10.4 ניקוד]
```

- Rendered only when `metadata.score_total` is present.
- Style: `bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300` (neutral, informational).

### Expanded card

Below the description/notes area, show a single formula line:

```
ניקוד: 3 × 4.0 × 0.2 + 2 × 4.0 × 1.3 = 10.4
```

- When `score_formula` is absent (cancellation): show `ניקוד: 0`
- Style: small (`text-xs`), muted (`text-gray-500`)

No new components, no new API calls. `EventCard` reads `metadata.score_total` and `metadata.score_formula` directly.

## Error Handling

- If `score_per_day` is missing or zero for a duty type, `score_total = "0"` and formula is omitted gracefully.
- If multiplier settings are missing, defaults (0.2 / 1.3 / 0.0) apply — same as the main scoring service.

## Out of Scope

- DutyDayOverrides (replacement days): the badge shows score based on the soldier's own assignment span. Overrides are a rare edge case and are already accounted for in the soldier's cumulative score on the transparency page.
- Score adjustments (ScoreAdjustment): these are not tied to individual assignments and are not shown here.
