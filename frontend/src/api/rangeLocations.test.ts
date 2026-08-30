import { describe, it, expect, vi } from "vitest";

const mockGet = vi.fn();
vi.mock("./client", () => ({
  api: {
    get: (...args: unknown[]) => mockGet(...args),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("rangeLocations api", () => {
  it("listRangeLocations returns the array on a valid response", async () => {
    mockGet.mockResolvedValue({ data: [{ id: "loc-1", name: "מטווח דרום", active: true }] });
    const { listRangeLocations } = await import("./rangeLocations");
    const result = await listRangeLocations();
    expect(result).toEqual([{ id: "loc-1", name: "מטווח דרום", active: true }]);
  });

  it("listRangeLocations normalizes a malformed (non-array) response to an empty list", async () => {
    mockGet.mockResolvedValue({ data: { not: "an array" } });
    const { listRangeLocations } = await import("./rangeLocations");
    const result = await listRangeLocations();
    expect(result).toEqual([]);
  });
});
