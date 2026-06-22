/**
 * Shared date formatting utilities.
 * All display-facing dates use dd.mm.yyyy format.
 * ISO strings sent to the API are NOT changed here.
 */

export function formatDate(d: string | Date): string {
  if (typeof d === "string") {
    const [yyyy, mm, dd] = d.split("-");
    return `${dd}.${mm}.${yyyy}`;
  }
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yyyy = d.getFullYear();
  return `${dd}.${mm}.${yyyy}`;
}

export function formatDateRange(start: string | Date, end: string | Date): string {
  if (typeof start === "string" && typeof end === "string" && start === end)
    return formatDate(start);
  return `${formatDate(start)} – ${formatDate(end)}`;
}

/**
 * DutyShift/DutyAssignment `end_date` (and everything derived from them, e.g.
 * CalendarShift/TimelineEvent/EffectiveDuty) is stored EXCLUSIVE — the first
 * calendar day NOT touched, not the last day worked. Use these two helpers at
 * the UI boundary to translate to/from the inclusive "last day" a user expects
 * to see/pick. Do not use these on constraint/exemption/dismissal/call-up date
 * ranges — those are already inclusive on the backend.
 */
export function lastDutyDay(endDateExclusive: string): string {
  const [yyyy, mm, dd] = endDateExclusive.split("-").map(Number);
  const d = new Date(yyyy, mm - 1, dd - 1);
  const y2 = d.getFullYear();
  const m2 = String(d.getMonth() + 1).padStart(2, "0");
  const d2 = String(d.getDate()).padStart(2, "0");
  return `${y2}-${m2}-${d2}`;
}

export function toExclusiveEndDate(lastDutyDayInclusive: string): string {
  const [yyyy, mm, dd] = lastDutyDayInclusive.split("-").map(Number);
  const d = new Date(yyyy, mm - 1, dd + 1);
  const y2 = d.getFullYear();
  const m2 = String(d.getMonth() + 1).padStart(2, "0");
  const d2 = String(d.getDate()).padStart(2, "0");
  return `${y2}-${m2}-${d2}`;
}

/** Formats a duty/shift date range whose `end` is the backend's exclusive end_date. */
export function formatDutyRange(start: string, endExclusive: string): string {
  return formatDateRange(start, lastDutyDay(endExclusive));
}
