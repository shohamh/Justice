import { describe, it, expect } from "vitest";
import { ENLISTED_RANKS, OFFICER_RANKS, isOfficerRank, isRankTrackCompatible, deriveBahad1Graduate } from "./ranks";

describe("rank constants", () => {
  it("classifies סגמ (סג\"ם) as an officer rank, not enlisted", () => {
    expect(OFFICER_RANKS).toContain("סגמ");
    expect(ENLISTED_RANKS).not.toContain("סגמ");
    expect(isOfficerRank("סגמ")).toBe(true);
  });

  it("classifies קמא as an officer rank, not enlisted", () => {
    expect(OFFICER_RANKS).toContain("קמא");
    expect(ENLISTED_RANKS).not.toContain("קמא");
  });

  it("classifies רסל (רס\"ל) as enlisted, not officer", () => {
    expect(ENLISTED_RANKS).toContain("רסל");
    expect(isOfficerRank("רסל")).toBe(false);
  });
});

describe("rank/track compatibility", () => {
  it("rejects a חובה-only rank on the קבע track", () => {
    expect(isRankTrackCompatible("טוראי", true)).toBe(false);
    expect(isRankTrackCompatible("טוראי", false)).toBe(true);
  });

  it("rejects a קבע-only rank on the חובה track", () => {
    expect(isRankTrackCompatible("רסל", false)).toBe(false);
    expect(isRankTrackCompatible("רסל", true)).toBe(true);
  });

  it("rejects a קבע-only officer rank (קא\"ב) on the חובה track", () => {
    expect(isRankTrackCompatible("קאב", false)).toBe(false);
    expect(isRankTrackCompatible("קאב", true)).toBe(true);
  });

  it("rejects a קבע-only officer rank (סרן) on the חובה track", () => {
    expect(isRankTrackCompatible("סרן", false)).toBe(false);
    expect(isRankTrackCompatible("סרן", true)).toBe(true);
  });

  it("allows the one deliberately unrestricted rank (סגן) on either track", () => {
    expect(isRankTrackCompatible("סגן", true)).toBe(true);
    expect(isRankTrackCompatible("סגן", false)).toBe(true);
  });
});

describe("קא\"ם rank", () => {
  it("classifies קאם as an officer rank positioned below רסן", () => {
    expect(OFFICER_RANKS).toContain("קאם");
    expect(OFFICER_RANKS.indexOf("קאם")).toBeLessThan(OFFICER_RANKS.indexOf("רסן"));
  });

  it("rejects קאם on the חובה track and accepts it on קבע", () => {
    expect(isRankTrackCompatible("קאם", false)).toBe(false);
    expect(isRankTrackCompatible("קאם", true)).toBe(true);
  });
});

describe("deriveBahad1Graduate", () => {
  it("is true for regular officer ranks", () => {
    expect(deriveBahad1Graduate("סרן")).toBe(true);
    expect(deriveBahad1Graduate("רסן")).toBe(true);
    expect(deriveBahad1Graduate("סגן")).toBe(true);
  });

  it("is false for קמא, קאב, קאם", () => {
    expect(deriveBahad1Graduate("קמא")).toBe(false);
    expect(deriveBahad1Graduate("קאב")).toBe(false);
    expect(deriveBahad1Graduate("קאם")).toBe(false);
  });

  it("is false for enlisted ranks", () => {
    expect(deriveBahad1Graduate("טוראי")).toBe(false);
  });
});
