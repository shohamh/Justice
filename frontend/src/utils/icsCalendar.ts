import type { EffectiveDuty } from "../api/assignments";

function formatICSDate(dateStr: string): string {
  return dateStr.replace(/-/g, "");
}

function escapeICS(str: string): string {
  return str.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\n/g, "\\n");
}

export function downloadDutyICS(
  duty: EffectiveDuty,
  dutyTypeName: string,
  locationName: string,
): void {
  const uid = `duty-${duty.assignment_id}@callofduty`;
  const dtstart = formatICSDate(duty.start_date);
  const endDate = new Date(duty.end_date);
  endDate.setDate(endDate.getDate() + 1);
  const dtend = endDate.toISOString().slice(0, 10).replace(/-/g, "");
  const summary = escapeICS(`תורנות: ${dutyTypeName}`);
  const location = escapeICS(locationName);
  const now = new Date().toISOString().replace(/[-:.]/g, "").slice(0, 15) + "Z";

  const ics = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//CallOfDuty//HE",
    "CALSCALE:GREGORIAN",
    "BEGIN:VEVENT",
    `UID:${uid}`,
    `DTSTAMP:${now}`,
    `DTSTART;VALUE=DATE:${dtstart}`,
    `DTEND;VALUE=DATE:${dtend}`,
    `SUMMARY:${summary}`,
    `LOCATION:${location}`,
    "END:VEVENT",
    "END:VCALENDAR",
  ].join("\r\n");

  const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `תורנות-${duty.start_date}.ics`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
