import type { DutyType } from "../api/dutyConfig";
import { RANGE_TYPE_LABELS } from "./rangeLabels";

export function formatDutyRequirements(
  dutyType: DutyType | undefined,
  requiredRangeType: string | null
): string[] {
  const requirements = dutyType?.requirements;
  const labels: string[] = [];

  if (requiredRangeType) labels.push(RANGE_TYPE_LABELS[requiredRangeType] ?? requiredRangeType);
  else if (requirements?.requires_mitvahim) labels.push("מטווחים");
  if (requirements?.requires_alal) labels.push('אל"ל');
  if (requirements?.requires_bahad1) labels.push('בה"ד 1');
  if (requirements?.requires_military_driving_license) labels.push('נדרש רשנ"צ');

  const genders = requirements?.allowed_genders ?? [];
  if (genders.length === 1) labels.push(genders[0] === "male" ? "גברים" : "נשים");

  const serviceTypes = requirements?.allowed_service_types ?? [];
  if (serviceTypes.length === 1) labels.push(serviceTypes[0]);

  if (requirements?.officers_allowed === false) labels.push("חוגרים");
  else if (requirements?.enlisted_allowed === false) labels.push("קצינים");

  const ranks = requirements?.allowed_ranks ?? [];
  if (ranks.length > 0) labels.push(ranks.join(", "));

  return labels;
}
