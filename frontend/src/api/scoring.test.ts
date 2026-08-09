import { describe, it, expect, vi } from "vitest";
import { api } from "./client";
import { listEligibilityGroups } from "./scoring";

vi.mock("./client");

describe("listEligibilityGroups", () => {
  it("calls GET /scoring/eligibility-groups", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [{ duty_type_ids: ["t1"], duty_type_names: ["שמירה"], soldier_count: 5 }] });
    const result = await listEligibilityGroups();
    expect(api.get).toHaveBeenCalledWith("/scoring/eligibility-groups");
    expect(result).toEqual([{ duty_type_ids: ["t1"], duty_type_names: ["שמירה"], soldier_count: 5 }]);
  });
});
