import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { getBurdenShareGap, getPotential, listModifiers } from "./potential";

vi.mock("./client");

describe("getPotential", () => {
  it("rejects a malformed potential response", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: "not-an-object" });

    await expect(getPotential("node-1")).rejects.toThrow("Invalid potential response");
  });

  it("normalizes malformed modifiers/soldiers fields to empty arrays", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        node_id: "node-1",
        as_of: "2026-08-30",
        raw_eligible_count: 1,
        total_soldiers: 2,
        modifiers: "not-an-array",
        final_potential: 1,
        soldiers: null,
        partial_exemption_count: 0,
      },
    });

    const result = await getPotential("node-1");

    expect(result.modifiers).toEqual([]);
    expect(result.soldiers).toEqual([]);
  });
});

describe("listModifiers", () => {
  it("returns an empty list when the payload is not an array", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected" } });

    await expect(listModifiers("node-1")).resolves.toEqual([]);
  });
});

describe("getBurdenShareGap", () => {
  it("returns an empty list when the response object's nodes field is malformed", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { nodes: "not-an-array" } });

    await expect(getBurdenShareGap()).resolves.toEqual([]);
  });

  it("returns the nodes array when the payload is valid", async () => {
    const nodes = [{ node_id: "node-1", node_name: "Alpha", final_potential: 1, total_burden_share: 1, sibling_potential_share: null, sibling_burden_share: null, sibling_gap: null, global_potential_share: null, global_burden_share: null, global_gap: null }];
    vi.mocked(api.get).mockResolvedValue({ data: { nodes } });

    await expect(getBurdenShareGap()).resolves.toEqual(nodes);
  });
});
