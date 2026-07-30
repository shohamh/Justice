import { describe, it, expect } from "vitest";
import { ENLISTED_RANKS, OFFICER_RANKS, isOfficerRank } from "./ranks";

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
