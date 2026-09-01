import type { TFunction } from "i18next";
import { describe, expect, it } from "vitest";
import type { DutyEligibilityFact } from "../api/ineligibleSoldiers";
import type { RangeStatus } from "../api/rangeStatus";
import { formatRangeEligibilityExplanation, formatRangeStatus } from "./rangeEligibilityExplanation";

const translations: Record<string, string> = {
  "range_qualification.explanation.noCurrentQualification": "אין מטווחים בתוקף",
  "range_qualification.explanation.noWeaponDuty": "טרם שובץ לתורנות שדורשת נשק",
  "range_qualification.explanation.uncoveredDuty": "משובץ לתורנות {{dutyType}} ב-{{date}} שדורשת {{rangeType}}",
  "range_qualification.explanation.plannedRangeCoverage": "מטווח מתוכנן מסוג {{rangeType}} בתאריך {{rangeDate}} מכסה את התורנות; הכשירות צפויה בתוקף עד {{projectedValidUntil}}",
  "range_qualification.explanation.neverQualified": "אין מטווחים בתוקף",
  "range_qualification.explanation.lastQualification": "מטווח אחרון - {{rangeType}} (בתוקף עד {{date}})",
  "range_qualification.status.eligible": "כשיר למטווח מסוג {{rangeType}}; בתוקף עד {{date}}",
  "range_qualification.status.ineligible": "אין כשירות מטווח מסוג {{rangeType}}",
  "range_qualification.status.enforcementDisabled": "אכיפת כשירות מטווח מסוג {{rangeType}} אינה פעילה כעת",
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
    covering_range_type: null,
    projected_valid_until: null,
    reason: "weapon_qualification",
    duty_type_name: "שמירה",
    start_date: "2026-08-21",
    last_qualification_type: null,
    last_qualification_date: null,
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
    expect(formatRangeEligibilityExplanation(fact({ required_range_type: "live" }), t)).toBe("משובץ לתורנות שמירה ב-21.08.2026 שדורשת מטווח חי\nאין מטווחים בתוקף");
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

  it("names the actual higher-tier planned range that covers the duty", () => {
    expect(formatRangeEligibilityExplanation(fact({
      eligible: true,
      required_range_type: "laser",
      qualification_source: "planned_range",
      covered_by_range_date: "2026-08-20",
      covering_range_type: "live",
      projected_valid_until: "2027-02-20",
    }), t)).toBe("מטווח מתוכנן מסוג מטווח חי בתאריך 20.08.2026 מכסה את התורנות; הכשירות צפויה בתוקף עד 20.02.2027");
  });

  it("appends the last qualification when uncovered and previously qualified", () => {
    const result = formatRangeEligibilityExplanation(
      fact({
        required_range_type: "laser",
        qualification_source: null,
        last_qualification_type: "laser",
        last_qualification_date: "2026-03-01",
      }),
      t,
    );
    expect(result).toBe("משובץ לתורנות שמירה ב-21.08.2026 שדורשת מטווח לייזר\nמטווח אחרון - מטווח לייזר (בתוקף עד 01.03.2026)");
  });

  it("notes never-qualified when uncovered and no last qualification exists", () => {
    const result = formatRangeEligibilityExplanation(
      fact({ required_range_type: "laser", qualification_source: null, last_qualification_type: null, last_qualification_date: null }),
      t,
    );
    expect(result).toBe("משובץ לתורנות שמירה ב-21.08.2026 שדורשת מטווח לייזר\nאין מטווחים בתוקף");
  });
});

function rangeStatus(overrides: Partial<RangeStatus>): RangeStatus {
  return {
    required_range_type: "laser",
    eligible: false,
    qualification_source: null,
    covered_by_range_date: null,
    covering_range_type: null,
    projected_valid_until: null,
    last_qualification_type: null,
    last_qualification_date: null,
    ...overrides,
  };
}

describe("formatRangeStatus", () => {
  it("renders an eligible status with the valid-until date and no undefined text", () => {
    const result = formatRangeStatus(
      rangeStatus({
        eligible: true,
        qualification_source: "current_qualification",
        projected_valid_until: "2027-02-20",
      }),
      t,
    );
    expect(result).toBe("כשיר למטווח מסוג מטווח לייזר; בתוקף עד 20.02.2027");
    expect(result).not.toContain("undefined");
    expect(result).not.toContain("אין כשירות מטווח");
  });

  it("renders planned-range coverage using the same phrasing as duty-based explanations", () => {
    const result = formatRangeStatus(
      rangeStatus({
        eligible: true,
        qualification_source: "planned_range",
        covered_by_range_date: "2026-08-20",
        projected_valid_until: "2027-02-20",
      }),
      t,
    );
    expect(result).toBe("מטווח מתוכנן מסוג מטווח לייזר בתאריך 20.08.2026 מכסה את התורנות; הכשירות צפויה בתוקף עד 20.02.2027");
    expect(result).not.toContain("undefined");
  });

  it("renders a neutral message when enforcement is disabled", () => {
    const result = formatRangeStatus(
      rangeStatus({ eligible: true, qualification_source: "enforcement_disabled" }),
      t,
    );
    expect(result).toBe("אכיפת כשירות מטווח מסוג מטווח לייזר אינה פעילה כעת");
    expect(result).not.toContain("undefined");
  });

  it("renders an ineligible status with the last-qualification clause and no duty reference", () => {
    const result = formatRangeStatus(
      rangeStatus({
        required_range_type: "live",
        eligible: false,
        qualification_source: null,
        last_qualification_type: "live",
        last_qualification_date: "2026-03-01",
      }),
      t,
    );
    expect(result).toBe("אין כשירות מטווח מסוג מטווח חי מטווח אחרון - מטווח חי (בתוקף עד 01.03.2026)");
    expect(result).not.toContain("undefined");
  });

  it("renders an ineligible status with never-qualified when there is no last qualification", () => {
    const result = formatRangeStatus(
      rangeStatus({ required_range_type: "alal", eligible: false, qualification_source: null }),
      t,
    );
    expect(result).toBe('אין כשירות מטווח מסוג אל"ל אין מטווחים בתוקף');
    expect(result).not.toContain("undefined");
  });
});
