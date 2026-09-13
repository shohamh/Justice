export interface BurdenShareStats {
  mean: number;
  stddev: number;
  cv: number;
  min: number;
  max: number;
}

export function computeBurdenShareStats(values: number[]): BurdenShareStats | null {
  if (values.length < 2) return null;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const variance = values.reduce((s, v) => s + (v - mean) ** 2, 0) / values.length;
  const stddev = Math.sqrt(variance);
  const cv = mean === 0 ? 0 : stddev / mean;
  return { mean, stddev, cv, min: Math.min(...values), max: Math.max(...values) };
}

const BURDEN_COLOR_LOW: [number, number, number] = [34, 197, 94]; // green-500
const BURDEN_COLOR_MID: [number, number, number] = [234, 179, 8]; // yellow-500
const BURDEN_COLOR_HIGH: [number, number, number] = [239, 68, 68]; // red-500

/** Minimum absolute burden-share gap (a fraction, e.g. 0.005 = 0.5 percentage
 * points) before a deviation counts as meaningful at all. Without this floor, a
 * tightly-clustered subgroup (e.g. filtering down to just officers) can have a
 * stddev so small that a trivial real-world gap — 0.05 percentage points —
 * reads as several standard deviations and gets painted as an extreme outlier,
 * even though nobody would call that gap significant. */
const BURDEN_SHARE_MIN_GAP = 0.005;

/** How many standard deviations out the color scale finishes ramping to fully
 * saturated red — matches how far real burden-share outliers actually sit in
 * this app's typically right-skewed distributions. */
const BURDEN_SHARE_MAX_Z = 3;

/**
 * CSS background color for a burden-share cell, based on how far it sits from
 * the group mean — a continuous green→yellow→red gradient by z-score (no hard
 * cliff at a fixed threshold) that only starts escalating once the raw gap
 * clears BURDEN_SHARE_MIN_GAP, so a tiny absolute difference in a tight group
 * never gets flagged as an outlier just because it's statistically unusual
 * for that group. Empty string when there's no meaningful spread to compare against.
 */
export function getBurdenShareColor(value: number, mean: number, stddev: number): string {
  const gap = Math.abs(value - mean);
  if (stddev === 0 || gap < BURDEN_SHARE_MIN_GAP) return "";
  const z = gap / stddev;
  const t = Math.max(0, Math.min(1, z / BURDEN_SHARE_MAX_Z));
  const stops: [number, number, number][] = [BURDEN_COLOR_LOW, BURDEN_COLOR_MID, BURDEN_COLOR_HIGH];
  const scaled = t * (stops.length - 1);
  const idx = Math.min(stops.length - 2, Math.floor(scaled));
  const localT = scaled - idx;
  const [r1, g1, b1] = stops[idx];
  const [r2, g2, b2] = stops[idx + 1];
  const r = Math.round(r1 + (r2 - r1) * localT);
  const g = Math.round(g1 + (g2 - g1) * localT);
  const b = Math.round(b1 + (b2 - b1) * localT);
  const alpha = 0.15 + 0.4 * t;
  return `rgba(${r}, ${g}, ${b}, ${alpha.toFixed(3)})`;
}
