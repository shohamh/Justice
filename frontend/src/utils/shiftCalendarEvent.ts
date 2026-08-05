import { CalendarShift } from "../api/calendar";

export interface ShiftCalendarEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  allDay: boolean;
  backgroundColor: string;
  borderColor: string;
  classNames: string[];
  extendedProps: { shiftId: string; dutyTypeId: string; swapCount: number };
}

/**
 * Maps a shift to a FullCalendar event, deciding whether it renders as an
 * all-day banner or a timed block.
 *
 * A shift is rendered all-day when it uses the full-day default times
 * (00:00-23:59, which carry no real hour data) OR when it spans multiple
 * calendar days — a *timed* multi-day event gets split by FullCalendar's
 * timeGrid (week/3-day) views into a separate segment on every day it
 * touches, each re-rendering the full event content, so a single multi-day
 * duty looks like several duplicate entries. All-day rendering instead shows
 * one continuous banner across every day it spans.
 */
export function shiftToCalendarEvent(s: CalendarShift): ShiftCalendarEvent {
  const isFullDayDefault = s.start_time === "00:00" && s.end_time === "23:59";
  const spansMultipleDays = s.start_date !== s.end_date;
  const useAllDay = isFullDayDefault || spansMultipleDays;
  return {
    id: s.id,
    title: `${s.duty_type_name} — ${s.duty_location_name}`,
    start: useAllDay ? s.start_date : s.start_at,
    end: useAllDay ? s.end_date : s.end_at,
    allDay: useAllDay,
    backgroundColor: s.duty_type_color,
    borderColor: s.duty_type_color,
    classNames: s.reserve_count > 0 ? ["fc-event-has-reserves"] : [],
    extendedProps: { shiftId: s.id, dutyTypeId: s.duty_type_id, swapCount: s.swap_request_count ?? 0 },
  };
}
