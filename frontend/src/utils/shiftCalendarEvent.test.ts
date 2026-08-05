import { describe, expect, it } from "vitest";
import { shiftToCalendarEvent } from "./shiftCalendarEvent";
import { CalendarShift } from "../api/calendar";

function shift(overrides: Partial<CalendarShift> = {}): CalendarShift {
  return {
    id: "s1", duty_type_id: "dt1", duty_type_name: "שמירה", duty_type_color: "#123456",
    duty_location_name: "שער ראשי", start_date: "2026-08-10", end_date: "2026-08-10",
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
    expect(event.end).toBe("2026-08-10");
  });

  it("renders a multi-day shift as all-day, spanning its full date range, even with real hours", () => {
    const event = shiftToCalendarEvent(shift({
      start_date: "2026-08-10", end_date: "2026-08-12",
      start_time: "08:00", end_time: "08:00",
      start_at: "2026-08-10T08:00:00Z", end_at: "2026-08-12T08:00:00Z",
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
