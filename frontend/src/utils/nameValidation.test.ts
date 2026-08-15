import { describe, expect, it } from "vitest";
import { fullNameValid } from "./nameValidation";

describe("fullNameValid", () => {
  it("requires at least two words", () => {
    expect(fullNameValid("ישראל")).toBe(false);
    expect(fullNameValid("ישראל ישראלי")).toBe(true);
  });

  it("allows repeated whitespace between words", () => {
    expect(fullNameValid("ישראל   ישראלי")).toBe(true);
  });

  it("rejects names longer than 100 characters", () => {
    expect(fullNameValid(`ישראל ${"א".repeat(96)}`)).toBe(false);
  });
});
