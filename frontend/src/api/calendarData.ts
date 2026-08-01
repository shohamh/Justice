import type { CalendarShiftsResponse } from "./calendar";
import type { RangeEvent } from "./ranges";

export async function loadCalendarData(
  loadCalendar: () => Promise<CalendarShiftsResponse>,
  loadRanges: () => Promise<RangeEvent[]>,
  rangesEnabled: boolean,
): Promise<{ calendar: CalendarShiftsResponse; ranges: RangeEvent[] }> {
  const calendar = await loadCalendar();
  if (!rangesEnabled) return { calendar, ranges: [] };
  try {
    return { calendar, ranges: await loadRanges() };
  } catch {
    return { calendar, ranges: [] };
  }
}
