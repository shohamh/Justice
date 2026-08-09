import type { TFunction } from "i18next";
import { describe, expect, it } from "vitest";
import type { DutyEligibilityFact } from "../api/ineligibleSoldiers";
import { formatRangeEligibilityExplanation } from "./rangeEligibilityExplanation";

const translations: Record<string, string> = {
  "range_qualification.explanation.noCurrentQualification": "אין מטווחים בתוקף",
  "range_qualification.explanation.noWeaponDuty": "טרם שובץ לתורנות שדורשת נשק",
  "range_qualification.explanation.uncoveredDuty": "משובץ לתורנות {{dutyType}} שדורשת לפחות מטווח מסוג {{rangeType}} בתאריך {{date}}",
  "range_qualification.explanation.plannedRangeCoverage": "מטווח מתוכנן מסוג {{rangeType}} בתאריך {{rangeDate}} מכסה את התורנות; הכשירות צפויה בתוקף עד {{projectedValidUntil}}",
};

const t = ((key: string, options?: Record<string, string>) =>
  Object.entries(options ?? {}).reduce(
    (value, [name, replacement]) => value.replace(`{{${name}}}`, replacement),
    translations[key] ?? key,
  )) as unknown as TFunction;

function fact(overrides: Partial<DutyEligibilityFact>): DutyEligibilityFact {
  return {
    eligible: false,
    required_range_type: null,
    qualification_source: null,
    covered_by_range_date: null,
    projected_valid_until: null,
    reason: "weapon_qualification",
    duty_type_name: "שמירה",
    start_date: "2026-08-21",
    ...overrides,
  };
}

describe("formatRangeEligibilityExplanation", () => {
  it("explains that no current qualification exists", () => {
    expect(formatRangeEligibilityExplanation(fact({}), t)).toBe("אין מטווחים בתוקף");
  });

  it("explains that no weapon-required duty is assigned", () => {
    expect(formatRangeEligibilityExplanation(fact({ eligible: true, qualification_source: "not_required" }), t)).toBe("טרם שובץ לתורנות שדורשת נשק");
  });

  it("explains an uncovered weapon duty with its required range and date", () => {
    expect(formatRangeEligibilityExplanation(fact({ required_range_type: "live" }), t)).toBe("משובץ לתורנות שמירה שדורשת לפחות מטווח מסוג מטווח חי בתאריך 21.08.2026");
  });

  it("explains planned-range coverage and projected validity instead of an uncovered duty", () => {
    expect(formatRangeEligibilityExplanation(fact({
      eligible: true,
      required_range_type: "laser",
      qualification_source: "planned_range",
      covered_by_range_date: "2026-08-20",
      projected_valid_until: "2027-02-20",
    }), t)).toBe("מטווח מתוכנן מסוג מטווח לייזר בתאריך 20.08.2026 מכסה את התורנות; הכשירות צפויה בתוקף עד 20.02.2027");
  });
});
