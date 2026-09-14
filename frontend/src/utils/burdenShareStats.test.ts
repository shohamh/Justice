import { describe, expect, it } from "vitest";
import { computeBurdenShareStats, getBurdenShareColor } from "./burdenShareStats";

describe("computeBurdenShareStats", () => {
  it("returns null for empty array", () => {
    expect(computeBurdenShareStats([])).toBeNull();
  });

  it("returns null for single-element array", () => {
    expect(computeBurdenShareStats([0.5])).toBeNull();
  });

  it("returns correct stats for uniform array", () => {
    const result = computeBurdenShareStats([0.1, 0.1, 0.1]);
    expect(result).not.toBeNull();
    expect(result!.mean).toBeCloseTo(0.1);
    expect(result!.stddev).toBeCloseTo(0);
    expect(result!.cv).toBeCloseTo(0);
    expect(result!.min).toBeCloseTo(0.1);
    expect(result!.max).toBeCloseTo(0.1);
  });

  it("returns correct stats for varied array", () => {
    // [0.1, 0.3] → mean=0.2, variance=0.01, stddev=0.1, cv=0.5
    const result = computeBurdenShareStats([0.1, 0.3]);
    expect(result).not.toBeNull();
    expect(result!.mean).toBeCloseTo(0.2);
    expect(result!.stddev).toBeCloseTo(0.1);
    expect(result!.cv).toBeCloseTo(0.5);
    expect(result!.min).toBeCloseTo(0.1);
    expect(result!.max).toBeCloseTo(0.3);
  });

  it("returns cv=0 when mean is 0", () => {
    const result = computeBurdenShareStats([0, 0, 0]);
    expect(result).not.toBeNull();
    expect(result!.cv).toBe(0);
  });
});

describe("getBurdenShareColor", () => {
  it("returns empty string when stddev is 0", () => {
    expect(getBurdenShareColor(0.2, 0.2, 0)).toBe("");
  });

  it("returns empty string when the raw gap is below the meaningful-difference floor", () => {
    // mean=0.2, stddev=0.001 (a tightly-clustered subgroup): 0.201 is 1σ away,
    // but the raw gap (0.1 percentage points) is trivial and must stay uncolored.
    expect(getBurdenShareColor(0.201, 0.2, 0.001)).toBe("");
  });

  it("colors a value near the mean closer to green than one far from it", () => {
    // mean=0.2, stddev=0.1: 0.25 is 0.5σ away, 0.45 is 2.5σ away.
    const near = getBurdenShareColor(0.25, 0.2, 0.1);
    const far = getBurdenShareColor(0.45, 0.2, 0.1);
    expect(near).not.toBe("");
    expect(far).not.toBe("");
    // Green's the low end of the scale, red the high end — a value near the
    // mean should carry far more green and far less red than one at 2.5σ.
    const [, nr, ng] = near.match(/rgba\((\d+), (\d+), (\d+)/) ?? [];
    const [, fr, fg] = far.match(/rgba\((\d+), (\d+), (\d+)/) ?? [];
    expect(Number(ng)).toBeGreaterThan(Number(fg));
    expect(Number(fr)).toBeGreaterThan(Number(nr));
  });

  it("increases opacity as the deviation grows", () => {
    const near = getBurdenShareColor(0.25, 0.2, 0.1);
    const far = getBurdenShareColor(0.45, 0.2, 0.1);
    const nearAlpha = Number(near.match(/[\d.]+\)$/)?.[0].replace(")", ""));
    const farAlpha = Number(far.match(/[\d.]+\)$/)?.[0].replace(")", ""));
    expect(farAlpha).toBeGreaterThan(nearAlpha);
  });

  it("caps out at the fully-saturated red end for extreme deviations", () => {
    // mean=0.2, stddev=0.1: 0.5 is 3σ away (at or past BURDEN_SHARE_MAX_Z)
    expect(getBurdenShareColor(0.5, 0.2, 0.1)).toBe("rgba(239, 68, 68, 0.550)");
  });

  it("never escalates further past the max-z cap", () => {
    // mean=0.2, stddev=0.1: 0.9 is 7σ away, well past BURDEN_SHARE_MAX_Z
    expect(getBurdenShareColor(0.9, 0.2, 0.1)).toBe(getBurdenShareColor(0.5, 0.2, 0.1));
  });
});
