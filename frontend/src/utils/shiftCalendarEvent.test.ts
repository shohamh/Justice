import { describe, expect, it } from "vitest";
import { shiftToCalendarEvent, shiftSpansMultipleDays, shiftEdgeLabels } from "./shiftCalendarEvent";
import { CalendarShift } from "../api/calendar";

// end_date is the backend's EXCLUSIVE boundary (the first day NOT touched —
// see formatDate.ts / calendar_shifts.py's _shift_instants), so a realistic
// single-day shift running only on 2026-08-10 has end_date="2026-08-11", not
// "2026-08-10". Every fixture below reflects that.
function shift(overrides: Partial<CalendarShift> = {}): CalendarShift {
  return {
    id: "s1", duty_type_id: "dt1", duty_type_name: "שמירה", duty_type_color: "#123456",
    duty_location_name: "שער ראשי", start_date: "2026-08-10", end_date: "2026-08-11",
    start_time: "08:00", end_time: "16:00",
    start_at: "2026-08-10T08:00:00Z", end_at: "2026-08-10T16:00:00Z",
    required_count: 1, assigned_count: 1, fill_status: "full", reserve_count: 0,
    assignees: [], swap_request_count: 0,
    ...overrides,
  };
}

describe("shiftToCalendarEvent", () => {
  it("renders a single-day timed shift as a timed event using its real hours", () => {
    const event = shiftToCalendarEvent(shift());
    expect(event.allDay).toBe(false);
    expect(event.start).toBe("2026-08-10T08:00:00Z");
    expect(event.end).toBe("2026-08-10T16:00:00Z");
  });

  it("renders a full-day-default shift as all-day even when it's a single day", () => {
    const event = shiftToCalendarEvent(shift({ start_time: "00:00", end_time: "23:59" }));
    expect(event.allDay).toBe(true);
    expect(event.start).toBe("2026-08-10");
    expect(event.end).toBe("2026-08-11");
  });

  it("renders a multi-day shift as all-day, spanning its full date range, even with real hours", () => {
    // A shift running Aug 10 08:00 through Aug 11 08:00 (two calendar days)
    // has end_date=Aug 12 (exclusive); end_at lands on the actual last day
    // touched (Aug 11), not the exclusive boundary itself.
    const event = shiftToCalendarEvent(shift({
      start_date: "2026-08-10", end_date: "2026-08-12",
      start_time: "08:00", end_time: "08:00",
      start_at: "2026-08-10T08:00:00Z", end_at: "2026-08-11T08:00:00Z",
    }));
    expect(event.allDay).toBe(true);
    expect(event.start).toBe("2026-08-10");
    expect(event.end).toBe("2026-08-12");
  });

  it("carries through the shift id, title, colors, and extended props", () => {
    const event = shiftToCalendarEvent(shift({ duty_type_color: "#abcdef" }));
    expect(event.id).toBe("s1");
    expect(event.title).toBe("שמירה — שער ראשי");
    expect(event.backgroundColor).toBe("#abcdef");
    expect(event.borderColor).toBe("#abcdef");
    expect(event.extendedProps).toEqual({ shiftId: "s1", dutyTypeId: "dt1", swapCount: 0 });
  });

  it("adds the reserve highlight class only when reserve_count is positive", () => {
    expect(shiftToCalendarEvent(shift({ reserve_count: 0 })).classNames).toEqual([]);
    expect(shiftToCalendarEvent(shift({ reserve_count: 2 })).classNames).toEqual(["fc-event-has-reserves"]);
  });
});

describe("shiftSpansMultipleDays", () => {
  it("is false for a realistic single-day shift (end_date one past start_date)", () => {
    expect(shiftSpansMultipleDays(shift({ start_date: "2026-08-10", end_date: "2026-08-11" }))).toBe(false);
  });

  it("is true when the exclusive end_date is more than one day past start_date", () => {
    expect(shiftSpansMultipleDays(shift({ start_date: "2026-08-10", end_date: "2026-08-12" }))).toBe(true);
  });

  it("would be wrongly true for a naive direct start_date/end_date comparison — regression guard", () => {
    // This is the exact bug this function exists to avoid: comparing the raw
    // (exclusive) end_date to start_date directly flags every ordinary
    // single-day shift as multi-day, since end_date is always start_date+1
    // at minimum. Guard against reintroducing that comparison.
    const singleDay = shift({ start_date: "2026-08-10", end_date: "2026-08-11" });
    expect(singleDay.start_date).not.toBe(singleDay.end_date);
    expect(shiftSpansMultipleDays(singleDay)).toBe(false);
  });
});

describe("shiftEdgeLabels", () => {
  it("formats the start label from start_date + start_time directly", () => {
    const labels = shiftEdgeLabels(shift({ start_date: "2026-08-10", start_time: "08:00" }));
    expect(labels.start).toBe("10.08.2026 08:00");
  });

  it("formats the end label from the exclusive end_date's inclusive last day + end_time", () => {
    // end_date=2026-08-12 is exclusive, so the actual last day is 2026-08-11.
    const labels = shiftEdgeLabels(shift({ end_date: "2026-08-12", end_time: "08:00" }));
    expect(labels.end).toBe("11.08.2026 08:00");
  });

  it("produces the same day for both edges on a single-day shift", () => {
    const labels = shiftEdgeLabels(shift({
      start_date: "2026-08-10", end_date: "2026-08-11", start_time: "08:00", end_time: "16:00",
    }));
    expect(labels.start).toBe("10.08.2026 08:00");
    expect(labels.end).toBe("10.08.2026 16:00");
  });
});
