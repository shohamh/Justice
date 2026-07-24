import { describe, expect, it } from "vitest";
import { formatDutyRange, isDateRangeValid, lastDutyDay, toExclusiveEndDate } from "./formatDate";

describe("isDateRangeValid", () => {
  it("is valid when from is before to", () => {
    expect(isDateRangeValid("2026-01-01", "2026-01-31")).toBe(true);
  });

  it("is valid when from equals to", () => {
    expect(isDateRangeValid("2026-01-01", "2026-01-01")).toBe(true);
  });

  it("is invalid when from is after to", () => {
    expect(isDateRangeValid("2026-02-01", "2026-01-01")).toBe(false);
  });

  it("treats a missing from as valid (not yet chosen)", () => {
    expect(isDateRangeValid(undefined, "2026-01-01")).toBe(true);
    expect(isDateRangeValid("", "2026-01-01")).toBe(true);
  });

  it("treats a missing to as valid (not yet chosen)", () => {
    expect(isDateRangeValid("2026-01-01", undefined)).toBe(true);
    expect(isDateRangeValid("2026-01-01", "")).toBe(true);
  });
});

describe("lastDutyDay", () => {
  it("subtracts one day from an exclusive end_date", () => {
    expect(lastDutyDay("2026-06-02")).toBe("2026-06-01");
  });

  it("handles month boundaries", () => {
    expect(lastDutyDay("2026-07-01")).toBe("2026-06-30");
  });

  it("handles year boundaries", () => {
    expect(lastDutyDay("2026-01-01")).toBe("2025-12-31");
  });
});

describe("toExclusiveEndDate", () => {
  it("is the inverse of lastDutyDay", () => {
    expect(toExclusiveEndDate("2026-06-01")).toBe("2026-06-02");
    expect(toExclusiveEndDate("2026-06-30")).toBe("2026-07-01");
    expect(toExclusiveEndDate("2025-12-31")).toBe("2026-01-01");
  });
});

describe("formatDutyRange", () => {
  it("collapses to a single date for a one-day duty", () => {
    // Monday start_date="2026-06-01", exclusive end_date="2026-06-02" -> a Monday-only duty.
    expect(formatDutyRange("2026-06-01", "2026-06-02")).toBe("01.06.2026");
  });

  it("shows the actual last day touched for a multi-day duty", () => {
    // start Monday, exclusive end the following Monday -> last day touched is Sunday.
    expect(formatDutyRange("2026-06-01", "2026-06-08")).toBe("01.06.2026 – 07.06.2026");
  });
});
