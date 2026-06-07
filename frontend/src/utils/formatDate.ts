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
