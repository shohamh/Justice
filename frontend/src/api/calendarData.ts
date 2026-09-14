import type { CalendarShiftsResponse } from "./calendar";
import type { RangeEvent } from "./ranges";

export async function loadCalendarData(
  loadCalendar: () => Promise<CalendarShiftsResponse>,
  loadRanges: () => Promise<RangeEvent[]>,
  rangesEnabled: boolean,
): Promise<{ calendar: CalendarShiftsResponse; ranges: RangeEvent[] }> {
  const calendarPromise = loadCalendar();
  if (!rangesEnabled) return { calendar: await calendarPromise, ranges: [] };
  const rangesPromise = loadRanges().catch(() => [] as RangeEvent[]);
  const [calendar, ranges] = await Promise.all([calendarPromise, rangesPromise]);
  return { calendar, ranges };
}
