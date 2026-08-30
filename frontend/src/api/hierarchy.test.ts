import { afterEach, describe, expect, it, vi } from "vitest";

const mockGet = vi.fn();

vi.mock("./client", () => ({
  api: {
    get: (...args: unknown[]) => mockGet(...args),
  },
}));

describe("hierarchy api", () => {
  afterEach(() => {
    mockGet.mockReset();
  });

  it("normalizes an enveloped full-tree response to the node list", async () => {
    const nodes = [{ id: "node-1", name: "Unit", parent_id: null }];
    mockGet.mockResolvedValueOnce({ data: { nodes } });
    const { fetchFullTree } = await import("./hierarchy");

    await expect(fetchFullTree()).resolves.toEqual(nodes);
  });

  it("returns an empty list for a non-list full-tree response", async () => {
    mockGet.mockResolvedValueOnce({ data: { detail: "unexpected response" } });
    const { fetchFullTree } = await import("./hierarchy");

    await expect(fetchFullTree()).resolves.toEqual([]);
  });
});
