import { describe, expect, it } from "vitest";
import { computeEffortStats, getEffortColor } from "./effortStats";

describe("computeEffortStats", () => {
  it("returns null for empty array", () => {
    expect(computeEffortStats([])).toBeNull();
  });

  it("returns null for single-element array", () => {
    expect(computeEffortStats([0.5])).toBeNull();
  });

  it("returns correct stats for uniform array", () => {
    const result = computeEffortStats([0.1, 0.1, 0.1]);
    expect(result).not.toBeNull();
    expect(result!.mean).toBeCloseTo(0.1);
    expect(result!.stddev).toBeCloseTo(0);
    expect(result!.cv).toBeCloseTo(0);
    expect(result!.min).toBeCloseTo(0.1);
    expect(result!.max).toBeCloseTo(0.1);
  });

  it("returns correct stats for varied array", () => {
    // [0.1, 0.3] → mean=0.2, variance=0.01, stddev=0.1, cv=0.5
    const result = computeEffortStats([0.1, 0.3]);
    expect(result).not.toBeNull();
    expect(result!.mean).toBeCloseTo(0.2);
    expect(result!.stddev).toBeCloseTo(0.1);
    expect(result!.cv).toBeCloseTo(0.5);
    expect(result!.min).toBeCloseTo(0.1);
    expect(result!.max).toBeCloseTo(0.3);
  });

  it("returns cv=0 when mean is 0", () => {
    const result = computeEffortStats([0, 0, 0]);
    expect(result).not.toBeNull();
    expect(result!.cv).toBe(0);
  });
});

describe("getEffortColor", () => {
  it("returns green class when value is within 1 stddev of mean", () => {
    // mean=0.2, stddev=0.1: value 0.25 is 0.5σ away
    expect(getEffortColor(0.25, 0.2, 0.1)).toContain("green");
  });

  it("returns yellow class when value is between 1 and 2 stddev", () => {
    // mean=0.2, stddev=0.1: value 0.35 is 1.5σ away
    expect(getEffortColor(0.35, 0.2, 0.1)).toContain("yellow");
  });

  it("returns red class when value is beyond 2 stddev", () => {
    // mean=0.2, stddev=0.1: value 0.45 is 2.5σ away
    expect(getEffortColor(0.45, 0.2, 0.1)).toContain("red");
  });

  it("returns empty string when stddev is 0", () => {
    expect(getEffortColor(0.2, 0.2, 0)).toBe("");
  });
});
