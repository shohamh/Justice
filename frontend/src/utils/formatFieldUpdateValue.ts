import { formatDate } from "./formatDate";

export function formatFieldUpdateValue(
  fieldName: string,
  value: string | null,
  t: (key: string) => string
): string {
  if (!value) return "—";
  if (fieldName === "gender") return t(`soldier_profile.gender_${value}`);
  if (fieldName === "rank") {
    try {
      const parsed = JSON.parse(value) as { rank?: string; rank_track?: string };
      if (parsed.rank) {
        const trackLabel = parsed.rank_track === "officer_academic"
          ? " (קצינים אקדמאים)"
          : parsed.rank_track === "officer"
            ? " (קצינים)"
            : parsed.rank_track === "enlisted"
              ? " (חוגרים)"
              : "";
        return `${parsed.rank}${trackLabel}`;
      }
    } catch {
      // Legacy rank updates stored the rank as a plain string.
    }
  }
  if (fieldName === "military_driving_license") {
    try {
      const parsed = JSON.parse(value) as { has_license: boolean; expiry_date: string | null };
      if (!parsed.has_license) return "—";
      return parsed.expiry_date ? `✓ (${formatDate(parsed.expiry_date)})` : "✓";
    } catch {
      return value;
    }
  }
  return value;
}
