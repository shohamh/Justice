import { describe, expect, test } from "vitest";
import { isValidIsraeliPhone } from "./phoneValidation";

describe("isValidIsraeliPhone", () => {
  test.each([
    "0501234567",       // mobile, no separators
    "050-1234567",      // mobile, dash
    "050 1234567",      // mobile, space
    "+972501234567",    // mobile, country code
    "+972-50-1234567",  // mobile, country code with separators
    "972501234567",     // mobile, country code no plus
    "021234567",        // landline (Tel Aviv area code)
    "02-1234567",       // landline, dash
    "081234567",        // landline (area code 08)
  ])("accepts valid Israeli number %s", (phone) => {
    expect(isValidIsraeliPhone(phone)).toBe(true);
  });

  test.each([
    "",
    "123",
    "05012345",         // too short
    "050123456789",     // too long
    "0601234567",       // invalid prefix (06 doesn't exist)
    "abcdefghij",
    "+1-555-123-4567",  // US number, not Israeli
  ])("rejects invalid number %s", (phone) => {
    expect(isValidIsraeliPhone(phone)).toBe(false);
  });
});
