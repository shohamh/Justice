import { describe, expect, it } from "vitest";
import { personalNumberValid } from "./personalNumberValidation";

describe("personalNumberValid", () => {
  it("accepts 7 or 8 digits", () => {
    expect(personalNumberValid("1234567")).toBe(true);
    expect(personalNumberValid("12345678")).toBe(true);
  });

  it("rejects other lengths and non-digits", () => {
    expect(personalNumberValid("123456")).toBe(false);
    expect(personalNumberValid("123456789")).toBe(false);
    expect(personalNumberValid("1234567A")).toBe(false);
  });
});
