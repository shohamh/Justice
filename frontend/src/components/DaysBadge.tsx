export function daysBetween(start: string, end: string | null | undefined): number | null {
  if (!end) return null;
  const a = new Date(start);
  const b = new Date(end);
  return Math.round((b.getTime() - a.getTime()) / (1000 * 60 * 60 * 24)) + 1;
}

export function DaysBadge({ start, end }: { start: string; end: string | null | undefined }) {
  const days = daysBetween(start, end);
  if (days === null) return null;
  const cls =
    days > 90
      ? "text-red-600 dark:text-red-400"
      : days > 30
      ? "text-yellow-600 dark:text-yellow-400"
      : "text-gray-400 dark:text-gray-500";
  return <span className={`text-xs ${cls}`}>({days} ימים)</span>;
}
