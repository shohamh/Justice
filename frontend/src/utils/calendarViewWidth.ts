const DAY_COLUMN_MIN_PX = 420;
const TIME_AXIS_GUTTER_PX = 60;

export const CALENDAR_VIEW_DAY_COUNTS: Record<string, number> = {
  timeGridWeek: 7,
  timeGridThreeDay: 3,
};

export function calendarViewMinWidth(viewType: string): number | undefined {
  const dayCount = CALENDAR_VIEW_DAY_COUNTS[viewType];
  if (!dayCount) return undefined;
  return dayCount * DAY_COLUMN_MIN_PX + TIME_AXIS_GUTTER_PX;
}
