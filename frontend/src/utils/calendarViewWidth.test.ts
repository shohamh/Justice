import { describe, expect, it } from "vitest";
import { calendarViewMinWidth, CALENDAR_VIEW_DAY_COUNTS } from "./calendarViewWidth";

describe("calendarViewMinWidth", () => {
  it("returns undefined for month view (no min-width constraint)", () => {
    expect(calendarViewMinWidth("dayGridMonth")).toBeUndefined();
  });

  it("returns undefined for an unrecognized view type", () => {
    expect(calendarViewMinWidth("listWeek")).toBeUndefined();
  });

  it("computes 7 columns * 420px + 60px gutter for the week view", () => {
    expect(calendarViewMinWidth("timeGridWeek")).toBe(3000);
  });

  it("computes 3 columns * 420px + 60px gutter for the 3-day view", () => {
    expect(calendarViewMinWidth("timeGridThreeDay")).toBe(1320);
  });
});

describe("CALENDAR_VIEW_DAY_COUNTS", () => {
  it("has 7 days for the week view and 3 for the 3-day view", () => {
    expect(CALENDAR_VIEW_DAY_COUNTS.timeGridWeek).toBe(7);
    expect(CALENDAR_VIEW_DAY_COUNTS.timeGridThreeDay).toBe(3);
  });
});
