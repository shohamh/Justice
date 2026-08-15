import { describe, expect, it } from "vitest";
import { personalConstraintComplete } from "./constraintValidation";

describe("personalConstraintComplete", () => {
  it("requires dates and a non-empty reason", () => {
    expect(personalConstraintComplete("2026-01-01", "2026-01-02", "סיבה")).toBe(true);
    expect(personalConstraintComplete("2026-01-01", "2026-01-02", "   ")).toBe(false);
    expect(personalConstraintComplete("", "2026-01-02", "סיבה")).toBe(false);
  });
});
