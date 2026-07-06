import { formatDate } from "./formatDate";

export function formatFieldUpdateValue(
  fieldName: string,
  value: string | null,
  t: (key: string) => string
): string {
  if (!value) return "—";
  if (fieldName === "gender") return t(`soldier_profile.gender_${value}`);
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
