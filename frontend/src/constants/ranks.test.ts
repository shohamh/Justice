import { describe, it, expect } from "vitest";
import { isOfficerRank, isRankTrackCompatible, deriveBahad1Graduate, deriveIsCareer } from "./ranks";

describe("rank constants", () => {
  it("classifies סגמ (סג\"ם) as an officer rank, not enlisted", () => {
    expect(isOfficerRank("סגמ")).toBe(true);
  });

  it("classifies קמא as an officer rank, not enlisted", () => {
    expect(isOfficerRank("קמא")).toBe(true);
  });

  it("classifies רסל (רס\"ל) as enlisted, not officer", () => {
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

  it("allows סמ\"ר (samal rishon) on either track", () => {
    expect(isRankTrackCompatible("סמר", true)).toBe(true);
    expect(isRankTrackCompatible("סמר", false)).toBe(true);
  });
});

describe("קא\"ם rank", () => {
  it("classifies קאם as an officer rank positioned below רסן", () => {
    expect(isOfficerRank("קאם")).toBe(true);
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

describe("deriveIsCareer", () => {
  it("is false before mandatory end date", () => {
    expect(deriveIsCareer("טוראי", "2027-01-01", "", "2026-07-19")).toBe(false);
  });

  it("is true after mandatory end date with no discharge date, for a non-חובה-only rank", () => {
    expect(deriveIsCareer("רסן", "2025-01-01", "", "2026-07-19")).toBe(true);
  });

  it("is false if discharged before mandatory end date", () => {
    expect(deriveIsCareer("רסן", "2027-01-01", "2026-06-01", "2026-07-19")).toBe(false);
  });

  it("is never true for a חובה-only rank regardless of dates", () => {
    expect(deriveIsCareer("טוראי", "2020-01-01", "", "2026-07-19")).toBe(false);
  });
});
