import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { fetchFullTree, fetchFullTreeForExport, fetchMyCommandScope, fetchTree } from "./hierarchy";

vi.mock("./client");

describe("hierarchy tree APIs", () => {
  it.each([
    ["fetchTree", () => fetchTree()],
    ["fetchFullTree", () => fetchFullTree()],
  ])("returns an empty list when %s receives a non-array payload", async (_name, call) => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected response" } });

    await expect(call()).resolves.toEqual([]);
  });

  it("rejects malformed full-tree export data but accepts a valid empty tree", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ data: { detail: "unexpected response" } });
    await expect(fetchFullTreeForExport()).rejects.toThrow("Invalid hierarchy tree response");

    vi.mocked(api.get).mockResolvedValueOnce({ data: [] });
    await expect(fetchFullTreeForExport()).resolves.toEqual([]);
  });

  it("reads the compact current-user command scope and exposes only summary fields", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        commanded_nodes: [
          { id: "commanded", level: "team", name: "Owned", commander_id: "hidden" },
        ],
        assigned_node: { id: "assigned", level: "unit", name: "Assigned", duty_managers: [] },
      },
    });

    await expect(fetchMyCommandScope()).resolves.toEqual({
      commanded_nodes: [{ id: "commanded", level: "team", name: "Owned" }],
      assigned_node: { id: "assigned", level: "unit", name: "Assigned" },
    });
    expect(api.get).toHaveBeenCalledWith("/hierarchy/my-command-scope");
  });
});
