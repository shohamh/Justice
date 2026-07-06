import { formatFieldUpdateValue } from "./formatFieldUpdateValue";

const t = (key: string) => key;

test("formats a military_driving_license JSON payload with a license and expiry", () => {
  const value = JSON.stringify({ has_license: true, expiry_date: "2027-01-01" });
  expect(formatFieldUpdateValue("military_driving_license", value, t)).toContain("✓");
});

test("formats a military_driving_license payload with no license as a dash", () => {
  const value = JSON.stringify({ has_license: false, expiry_date: null });
  expect(formatFieldUpdateValue("military_driving_license", value, t)).toBe("—");
});

test("returns the raw string unchanged for non-JSON fields", () => {
  expect(formatFieldUpdateValue("phone", "050-1234567", t)).toBe("050-1234567");
});

test("falls back to null-dash for empty values", () => {
  expect(formatFieldUpdateValue("phone", null, t)).toBe("—");
});
