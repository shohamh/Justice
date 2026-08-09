import type { TFunction } from "i18next";
import type { DutyEligibilityFact } from "../api/ineligibleSoldiers";
import { RANGE_TYPE_LABELS } from "./rangeLabels";

function formatDate(value: string): string {
  const [year, month, day] = value.split("-");
  return `${day}.${month}.${year}`;
}

export function formatRangeEligibilityExplanation(fact: DutyEligibilityFact, t: TFunction): string {
  if (
    fact.qualification_source === "planned_range"
    && fact.covered_by_range_date
    && fact.projected_valid_until
  ) {
    return t("range_qualification.explanation.plannedRangeCoverage", {
      rangeType: RANGE_TYPE_LABELS[fact.covering_range_type ?? fact.required_range_type ?? ""]
        ?? fact.covering_range_type
        ?? fact.required_range_type,
      rangeDate: formatDate(fact.covered_by_range_date),
      projectedValidUntil: formatDate(fact.projected_valid_until),
    });
  }

  if (fact.qualification_source === "not_required") {
    return t("range_qualification.explanation.noWeaponDuty");
  }

  if (!fact.required_range_type) {
    return t("range_qualification.explanation.noCurrentQualification");
  }

  return t("range_qualification.explanation.uncoveredDuty", {
    dutyType: fact.duty_type_name,
    rangeType: RANGE_TYPE_LABELS[fact.required_range_type] ?? fact.required_range_type,
    date: formatDate(fact.start_date),
  });
}
