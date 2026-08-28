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

/** Tailwind bg class based on distance from mean in stddev units. Empty string when stddev === 0. */
export function getBurdenShareColor(value: number, mean: number, stddev: number): string {
  if (stddev === 0) return "";
  const dev = Math.abs(value - mean) / stddev;
  if (dev <= 1) return "bg-green-100 dark:bg-green-950";
  if (dev <= 2) return "bg-yellow-100 dark:bg-yellow-950";
  return "bg-red-100 dark:bg-red-950";
}
