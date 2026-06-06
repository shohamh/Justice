/**
 * Shared date formatting utilities.
 * All display-facing dates use dd.mm.yyyy format.
 * ISO strings sent to the API are NOT changed here.
 */

export function formatDate(d: string | Date): string {
  const date = typeof d === "string" ? new Date(d) : d;
  const dd = String(date.getDate()).padStart(2, "0");
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const yyyy = date.getFullYear();
  return `${dd}.${mm}.${yyyy}`;
}

export function formatDateRange(start: string | Date, end: string | Date): string {
  if (typeof start === "string" && typeof end === "string" && start === end)
    return formatDate(start);
  return `${formatDate(start)} – ${formatDate(end)}`;
}
