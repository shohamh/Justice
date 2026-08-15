import { describe, expect, it } from "vitest";
import type { DutyType } from "../api/dutyConfig";
import { formatDutyRequirements } from "./dutyRequirements";

function dutyType(requirements: DutyType["requirements"]): DutyType {
  return {
    id: "guard",
    name: "שמירה",
    score_per_day: "1",
    description: null,
    active: true,
    requirements,
    contact_name: null,
    contact_phone: null,
    start_time: null,
    end_time: null,
    instructions: null,
    is_external: false,
    required_range_type: null,
    eligible_node_ids: null,
  };
}

describe("formatDutyRequirements", () => {
  it("returns no labels when the duty has no active requirements", () => {
    expect(formatDutyRequirements(dutyType({}), null)).toEqual([]);
  });

  it("shows the specific required range", () => {
    expect(formatDutyRequirements(dutyType({}), "laser")).toEqual(["מטווח לייזר"]);
  });

  it("shows the military driving license requirement", () => {
    expect(
      formatDutyRequirements(dutyType({ requires_military_driving_license: true }), null)
    ).toEqual(['נדרש רשנ"צ']);
  });

  it("keeps combined requirements ordered without duplicating a generic range", () => {
    expect(
      formatDutyRequirements(
        dutyType({
          requires_mitvahim: true,
          requires_alal: true,
          requires_bahad1: true,
          requires_military_driving_license: true,
          allowed_genders: ["female"],
          allowed_service_types: ["קבע"],
          allowed_ranks: ["סרן"],
          enlisted_allowed: false,
        }),
        "laser"
      )
    ).toEqual(["מטווח לייזר", 'אל"ל', 'בה"ד 1', 'נדרש רשנ"צ', "נשים", "קבע", "קצינים", "סרן"]);
  });
});
