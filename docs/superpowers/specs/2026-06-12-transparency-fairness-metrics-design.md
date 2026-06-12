# Transparency Fairness Metrics — Design

## Goal

Add inequality/spread metrics to the Transparency page so commanders can see both a high-level unit fairness score and identify specific soldiers or sub-units carrying disproportionate load.

## Architecture

All statistics are computed **frontend-only** from `visibleRows` (the already-filtered `TransparencyRow[]`). The backend already returns `effort_score` per soldier; no new API endpoints or backend changes are needed. Stats recompute whenever the active filters change.

The core metric is **Coefficient of Variation (CV)** = `stddev(effort_scores) / mean(effort_scores)`, expressed as a percentage. Lower = fairer distribution.

---

## Section 1: Fairness Summary Card (Soldiers Tab)

A new summary card added to the existing cards row at the top of the Transparency page.

**Main number:** CV as a percentage (e.g. `42%`) with label `פיזור עומס`.

**Color indicator** (dot or card border):
- 🟢 Green: CV < 25% — healthy spread
- 🟡 Yellow: CV 25–50% — moderate inequality
- 🔴 Red: CV > 50% — high inequality

**Supporting stats** in smaller text below:
- `ממוצע: X%`
- `סטיית תקן: ±Y%`
- `טווח: min% – max%`

Responds to the active filters (node selector, officer/enlisted, חובה/קבע). If fewer than 2 soldiers are visible, show `—` instead of stats.

---

## Section 2: Effort Column Color Bands (Soldiers Tab Table)

Each row's `effort_score` cell gets a subtle background color based on deviation from the filtered mean:

| Deviation from mean | Color |
|---|---|
| Within ± 1σ | 🟢 Green |
| Between 1σ and 2σ (either direction) | 🟡 Yellow |
| Beyond 2σ | 🔴 Red |

Color applies only to the effort cell, not the whole row. The existing click-for-breakdown modal is unchanged.

**Helper:** `getEffortColor(value: number, mean: number, stddev: number): string` returns a Tailwind bg class.

---

## Section 3: Sub-units Tab Additions

### Per-sub-unit columns

Two new columns in the sub-units table:
1. **ממוצע עומס** — mean `effort_score` of soldiers in that node
2. **פיזור (CV)** — CV of effort scores within that node (internal spread)

Both computed during the existing `subRows` aggregation pass.

### Sub-unit-level fairness card

A CV card at the top of the sub-units tab (mirroring the soldier-level card) showing spread *across* sub-units:
- Main number: CV of the per-sub-unit average effort scores
- Same green/yellow/red thresholds
- Supporting stats: mean sub-unit avg, stddev of sub-unit avgs, min–max range

This gives two distinct views:
- **Soldiers tab card** → "Is load spread fairly across individuals?"
- **Sub-units tab card** → "Are my sub-units carrying equal load?"

---

## Data / Computation

All stats derived from `visibleRows: TransparencyRow[]` (soldiers tab) or from sub-unit aggregates (sub-units tab).

```ts
function computeStats(values: number[]) {
  if (values.length < 2) return null;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const variance = values.reduce((s, v) => s + (v - mean) ** 2, 0) / values.length;
  const stddev = Math.sqrt(variance);
  const cv = mean === 0 ? 0 : stddev / mean;
  const min = Math.min(...values);
  const max = Math.max(...values);
  return { mean, stddev, cv, min, max };
}
```

---

## Files Affected

| File | Change |
|---|---|
| `frontend/src/pages/TransparencyPage.tsx` | Add fairness cards, effort color bands, sub-unit columns |
| `frontend/src/i18n/he.json` | Add translation keys: `פיזור_עומס`, supporting stat labels |

No backend changes. No new API files.

---

## Out of Scope

- Historical trend of CV over time
- Alerting / notifications when CV crosses a threshold
- Per-soldier percentile rank display
