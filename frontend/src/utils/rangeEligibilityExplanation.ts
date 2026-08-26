import type { TFunction } from "i18next";
import type { DutyEligibilityFact } from "../api/ineligibleSoldiers";
import type { RangeStatus } from "../api/rangeStatus";
import { RANGE_TYPE_LABELS } from "./rangeLabels";

export function formatDate(value: string): string {
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

  const lastQualificationClause = fact.last_qualification_date
    ? t("range_qualification.explanation.lastQualification", {
        rangeType: RANGE_TYPE_LABELS[fact.last_qualification_type ?? ""] ?? fact.last_qualification_type,
        date: formatDate(fact.last_qualification_date),
      })
    : t("range_qualification.explanation.neverQualified");

  return `${t("range_qualification.explanation.uncoveredDuty", {
    dutyType: fact.duty_type_name,
    rangeType: RANGE_TYPE_LABELS[fact.required_range_type] ?? fact.required_range_type,
    date: formatDate(fact.start_date),
  })}\n${lastQualificationClause}`;
}

/**
 * Duty-independent explanation of a soldier's range-qualification status
 * (RangeStatus), for surfaces like ProfilePage/UnifiedSoldierModal that show
 * "as of today" status rather than eligibility for a specific scheduled duty.
 * Unlike formatRangeEligibilityExplanation, this never references a duty.
 */
export function formatRangeStatus(status: RangeStatus, t: TFunction): string {
  const rangeTypeLabel = RANGE_TYPE_LABELS[status.required_range_type] ?? status.required_range_type;

  if (status.qualification_source === "current_qualification" && status.projected_valid_until) {
    return t("range_qualification.status.eligible", {
      rangeType: rangeTypeLabel,
      date: formatDate(status.projected_valid_until),
    });
  }

  if (
    status.qualification_source === "planned_range"
    && status.covered_by_range_date
    && status.projected_valid_until
  ) {
    return t("range_qualification.explanation.plannedRangeCoverage", {
      rangeType: RANGE_TYPE_LABELS[status.covering_range_type ?? status.required_range_type]
        ?? status.covering_range_type
        ?? status.required_range_type,
      rangeDate: formatDate(status.covered_by_range_date),
      projectedValidUntil: formatDate(status.projected_valid_until),
    });
  }

  if (status.qualification_source === "enforcement_disabled") {
    return t("range_qualification.status.enforcementDisabled", { rangeType: rangeTypeLabel });
  }

  const lastQualificationClause = status.last_qualification_date
    ? t("range_qualification.explanation.lastQualification", {
        rangeType: RANGE_TYPE_LABELS[status.last_qualification_type ?? ""] ?? status.last_qualification_type,
        date: formatDate(status.last_qualification_date),
      })
    : t("range_qualification.explanation.neverQualified");

  return `${t("range_qualification.status.ineligible", { rangeType: rangeTypeLabel })} ${lastQualificationClause}`;
}
