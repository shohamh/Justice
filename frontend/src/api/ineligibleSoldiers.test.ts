import { afterEach, describe, expect, it, vi } from "vitest";
import he from "../i18n/he.json";
import { queryKeys } from "../queryKeys";

const mockGet = vi.fn();

vi.mock("./client", () => ({
  api: {
    get: (...args: unknown[]) => mockGet(...args),
  },
}));

const response = {
  count: 1,
  nodes: [
    { id: "node-1", name: "Alpha", level: "company", parent_id: null, path_ids: ["node-1"] },
  ],
  soldiers: [
    {
      soldier_id: "soldier-1",
      soldier_name: "Test Soldier",
      personal_number: "1234567",
      hierarchy_node_id: "node-1",
      hierarchy_node_name: "Alpha",
      hierarchy_path_ids: ["node-1"],
      valid_qualifications: [{ range_type: "laser", valid_until: "2026-09-01" }],
      has_upcoming_weapon_duty: true,
      has_upcoming_matching_range: false,
      upcoming_weapon_duties: [{
        assignment_id: "assignment-1",
        duty_type_id: "duty-type-1",
        duty_type_name: "Guard",
        start_date: "2026-09-10",
        end_date: "2026-09-10",
        required_range_type: "laser",
      }],
      upcoming_matching_ranges: [],
    },
  ],
} as const;

describe("ineligible soldiers api", () => {
  afterEach(() => {
    mockGet.mockReset();
  });

  it("gets the scoped list with the exact audience query parameter", async () => {
    mockGet.mockResolvedValueOnce({ data: response });
    const { getIneligibleSoldiers } = await import("./ineligibleSoldiers");

    await expect(getIneligibleSoldiers("commander")).resolves.toEqual(response);
    expect(mockGet).toHaveBeenCalledWith("/ranges/ineligible-soldiers", {
      params: { audience: "commander" },
    });
  });

  it("gets the dashboard count from the endpoint without query parameters", async () => {
    mockGet.mockResolvedValueOnce({ data: { count: 3 } });
    const { getIneligibleSoldierCount } = await import("./ineligibleSoldiers");

    await expect(getIneligibleSoldierCount()).resolves.toEqual({ count: 3 });
    expect(mockGet).toHaveBeenCalledWith("/ranges/ineligible-soldiers/count");
  });

  it("registers stable query keys for both audiences and the count", () => {
    expect(queryKeys.ineligibleSoldiers("planning")).toEqual(["ranges", "ineligibleSoldiers", "planning"]);
    expect(queryKeys.ineligibleSoldiers("commander")).toEqual(["ranges", "ineligibleSoldiers", "commander"]);
    expect(queryKeys.ineligibleSoldierCount()).toEqual(["ranges", "ineligibleSoldiers", "count"]);
  });

  it("rejects a malformed ineligible soldiers response", async () => {
    mockGet.mockResolvedValueOnce({ data: "not-an-object" });
    const { getIneligibleSoldiers } = await import("./ineligibleSoldiers");

    await expect(getIneligibleSoldiers("commander")).rejects.toThrow(
      "Invalid ineligible soldiers response",
    );
  });

  it("drops a non-object node/soldier row and normalizes malformed nested arrays to []", async () => {
    mockGet.mockResolvedValueOnce({
      data: {
        count: 1,
        nodes: [42, { id: "node-1", name: "Alpha", level: "company", parent_id: null, path_ids: "not-an-array" }],
        soldiers: [
          "not-an-object",
          {
            ...response.soldiers[0],
            hierarchy_path_ids: null,
            valid_qualifications: "not-an-array",
            upcoming_weapon_duties: undefined,
            upcoming_matching_ranges: 42,
          },
        ],
      },
    });
    const { getIneligibleSoldiers } = await import("./ineligibleSoldiers");

    const result = await getIneligibleSoldiers("commander");

    expect(result.nodes).toEqual([
      { id: "node-1", name: "Alpha", level: "company", parent_id: null, path_ids: [] },
    ]);
    expect(result.soldiers).toHaveLength(1);
    expect(result.soldiers[0].hierarchy_path_ids).toEqual([]);
    expect(result.soldiers[0].valid_qualifications).toEqual([]);
    expect(result.soldiers[0].upcoming_weapon_duties).toEqual([]);
    expect(result.soldiers[0].upcoming_matching_ranges).toEqual([]);
  });

  it("provides the ranges qualification view Hebrew copy", () => {
    const keys = [
      "title", "tabs.schedule", "tabs.qualification", "columns.soldier", "columns.hierarchy",
      "columns.qualification", "columns.upcomingDuty", "columns.upcomingRange", "loading",
      "empty", "error", "qualificationExpiry", "warning.normal", "warning.urgent",
      "dashboard.title", "dashboard.description", "dashboard.empty",
    ];
    for (const key of keys) {
      const value = key.split(".").reduce<unknown>((current, part) => (
        current && typeof current === "object" ? (current as Record<string, unknown>)[part] : undefined
      ), he.range_qualification);
      expect(value, `missing translation range_qualification.${key}`).toEqual(expect.any(String));
    }
  });
});
