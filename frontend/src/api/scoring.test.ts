import { describe, it, expect, vi } from "vitest";
import { api } from "./client";
import {
  listEligibilityGroups,
  getTransparency,
  getFairnessComponents,
  getBreakdown,
  getBurdenShareBreakdown,
  getBurdenShare,
} from "./scoring";

vi.mock("./client");

describe("listEligibilityGroups", () => {
  it("calls GET /scoring/eligibility-groups", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [{ duty_type_ids: ["t1"], duty_type_names: ["שמירה"], soldier_count: 5 }] });
    const result = await listEligibilityGroups();
    expect(api.get).toHaveBeenCalledWith("/scoring/eligibility-groups");
    expect(result).toEqual([{ duty_type_ids: ["t1"], duty_type_names: ["שמירה"], soldier_count: 5 }]);
  });
});

describe("getTransparency", () => {
  it("rejects a non-object transparency payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: null });
    await expect(getTransparency()).rejects.toThrow("Invalid transparency response");
  });

  it("normalizes a malformed rows payload to an empty list on an otherwise-valid object", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { rows: { detail: "unexpected response" }, can_see_exemption_aggregates: true },
    });
    await expect(getTransparency()).resolves.toEqual({ rows: [], can_see_exemption_aggregates: true });
  });

  it("keeps a legitimately empty rows array as empty, not an error", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { rows: [], can_see_exemption_aggregates: false } });
    await expect(getTransparency()).resolves.toEqual({ rows: [], can_see_exemption_aggregates: false });
  });
});

describe("getFairnessComponents", () => {
  it("rejects a non-object payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: "unexpected response" });
    await expect(getFairnessComponents()).rejects.toThrow("Invalid fairness components response");
  });

  it("normalizes a malformed components/exempt_from_all payload", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { components: { detail: "unexpected response" }, exempt_from_all: "unexpected response" },
    });
    await expect(getFairnessComponents()).resolves.toEqual({
      components: [],
      exempt_from_all: { count: 0, soldiers: [] },
    });
  });

  it("passes through a well-formed payload", async () => {
    const components = [{ duty_type_names: ["שמירה"], soldier_count: 2, burden_share: null, soldiers: [] }];
    vi.mocked(api.get).mockResolvedValue({
      data: { components, exempt_from_all: { count: 1, soldiers: [{ soldier_id: "s1", full_name: "א", burden_share: 0, eligible_type_count: 0 }] } },
    });
    await expect(getFairnessComponents()).resolves.toEqual({
      components,
      exempt_from_all: { count: 1, soldiers: [{ soldier_id: "s1", full_name: "א", burden_share: 0, eligible_type_count: 0 }] },
    });
  });
});

describe("getBreakdown", () => {
  it("rejects a non-object payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: null });
    await expect(getBreakdown("s1")).rejects.toThrow("Invalid score breakdown response");
  });

  it("normalizes malformed per_type/adjustments to empty arrays", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { per_type: { detail: "unexpected response" }, adjustments: "unexpected response" },
    });
    await expect(getBreakdown("s1")).resolves.toEqual({ per_type: [], adjustments: [] });
  });

  it("keeps a legitimately empty breakdown as empty, not an error", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { per_type: [], adjustments: [] } });
    await expect(getBreakdown("s1")).resolves.toEqual({ per_type: [], adjustments: [] });
  });
});

describe("getBurdenShareBreakdown", () => {
  it("rejects a non-object payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: null });
    await expect(getBurdenShareBreakdown("s1")).rejects.toThrow("Invalid burden-share breakdown response");
  });

  it("rejects a payload missing the required scalar fields", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { quarters: [] } });
    await expect(getBurdenShareBreakdown("s1")).rejects.toThrow("Invalid burden-share breakdown response");
  });

  it("normalizes a malformed quarters payload while keeping valid scalar fields", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { quarters: { detail: "unexpected response" }, burden_share: "0.5", A_i: "1", W_i: "2" },
    });
    await expect(getBurdenShareBreakdown("s1")).resolves.toEqual({
      quarters: [], burden_share: "0.5", A_i: "1", W_i: "2",
    });
  });
});

describe("getBurdenShare", () => {
  it("rejects a non-object payload", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: null });
    await expect(getBurdenShare("s1")).rejects.toThrow("Invalid burden share response");
  });

  it("rejects a payload missing has_group", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { burden_share: 0.1 } });
    await expect(getBurdenShare("s1")).rejects.toThrow("Invalid burden share response");
  });

  it("normalizes malformed duty_type_names/peer_scores to empty arrays", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        has_group: true,
        burden_share: 0.2,
        rank: 1,
        group_size: 5,
        duty_type_names: { detail: "unexpected response" },
        peer_scores: "unexpected response",
        mean: 0.2,
        stddev: 0.05,
        cv: 0.25,
        low_sample: false,
      },
    });
    const result = await getBurdenShare("s1");
    expect(result.duty_type_names).toEqual([]);
    expect(result.peer_scores).toEqual([]);
    expect(result.has_group).toBe(true);
  });
});
