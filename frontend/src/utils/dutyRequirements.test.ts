import { describe, it, expect } from "vitest";
import { formatDutyRequirements } from "./dutyRequirements";
import type { DutyType } from "../api/dutyConfig";

function dutyType(requirements: NonNullable<DutyType["requirements"]>): DutyType {
  return { id: "d1", name: "duty", requirements } as DutyType;
}

describe("formatDutyRequirements", () => {
  it("annotates a rank with its per-rank service-type override", () => {
    const labels = formatDutyRequirements(
      dutyType({ allowed_ranks: ["סמר", "רסל"], rank_service_types: { סמר: ["קבע"] } }),
      null
    );
    expect(labels).toContain('סמר (קבע), רסל');
  });

  it("leaves ranks without an override unannotated", () => {
    const labels = formatDutyRequirements(dutyType({ allowed_ranks: ["רסל"] }), null);
    expect(labels).toContain("רסל");
  });
});
