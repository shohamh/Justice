import { CalendarShift } from "../api/calendar";
import { formatDate, lastDutyDay } from "./formatDate";

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
 * True when a shift covers more than one calendar day.
 *
 * `end_date` is the backend's EXCLUSIVE boundary (the first day NOT
 * touched — see formatDate.ts and calendar_shifts.py's `_shift_instants`),
 * so even an ordinary single-day shift already has `end_date = start_date +
 * 1 day`. Comparing `start_date`/`end_date` directly would treat every
 * shift as multi-day; compare against the *inclusive* last day instead.
 */
export function shiftSpansMultipleDays(s: CalendarShift): boolean {
  return lastDutyDay(s.end_date) !== s.start_date;
}

const HEBREW_DAY_SHORT = ["א׳", "ב׳", "ג׳", "ד׳", "ה׳", "ו׳", "ש׳"];

/** Short Hebrew day-of-week label (א׳-ש׳) for a yyyy-mm-dd date, Sunday-first. */
function hebrewDayShort(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return HEBREW_DAY_SHORT[new Date(y, m - 1, d).getDay()];
}

/**
 * "א׳ dd.mm.yyyy HH:MM" labels for a multi-day shift's true start and end
 * moments, for the Outlook-style edge labels shown on its all-day banner.
 * `end_date` is the backend's exclusive boundary (see formatDate.ts) —
 * `end_time` pairs with the actual inclusive last day, not that boundary.
 */
export function shiftEdgeLabels(s: CalendarShift): { start: string; end: string } {
  const endDay = lastDutyDay(s.end_date);
  return {
    start: `${hebrewDayShort(s.start_date)} ${formatDate(s.start_date)} ${s.start_time}`,
    end: `${hebrewDayShort(endDay)} ${formatDate(endDay)} ${s.end_time}`,
  };
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
  const useAllDay = isFullDayDefault || shiftSpansMultipleDays(s);
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
