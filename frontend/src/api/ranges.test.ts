import { describe, it, expect, vi } from "vitest";

const mockGet = vi.fn();
const mockPost = vi.fn();
vi.mock("./client", () => ({
  api: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

describe("ranges api", () => {
  it("getRanges calls GET /ranges with node_id", async () => {
    mockGet.mockResolvedValue({ data: [] });
    const { getRanges } = await import("./ranges");
    const result = await getRanges("node-1");
    expect(mockGet).toHaveBeenCalledWith(expect.stringContaining("node_id=node-1"));
    expect(result).toEqual([]);
  });

  it("createRangeEvent calls POST /ranges with body", async () => {
    const body = {
      hierarchy_node_id: "node-1",
      range_type: "laser" as const,
      date: "2026-09-01",
      location: "מטווח",
      required_count: 3,
      reserve_count: 1,
    };
    mockPost.mockResolvedValue({ data: { id: "event-1", ...body, status: "planned", assignments: [] } });
    const { createRangeEvent } = await import("./ranges");
    const result = await createRangeEvent(body);
    expect(mockPost).toHaveBeenCalledWith("/ranges", body);
    expect(result.id).toBe("event-1");
  });

  it("getRanges normalizes a malformed (non-array) response to an empty list", async () => {
    mockGet.mockResolvedValue({ data: { not: "an array" } });
    const { getRanges } = await import("./ranges");
    const result = await getRanges("node-1");
    expect(result).toEqual([]);
  });

  it("getMyRanges normalizes a malformed (non-array) response to an empty list", async () => {
    mockGet.mockResolvedValue({ data: null });
    const { getMyRanges } = await import("./ranges");
    const result = await getMyRanges("soldier-1");
    expect(result).toEqual([]);
  });

  it("getRangeEvent returns the event with a normalized assignments array", async () => {
    mockGet.mockResolvedValue({
      data: { id: "event-1", location: "מטווח", assignments: "not-an-array" },
    });
    const { getRangeEvent } = await import("./ranges");
    const result = await getRangeEvent("event-1");
    expect(result.id).toBe("event-1");
    expect(result.assignments).toEqual([]);
  });

  it("getRangeEvent throws a descriptive error for a malformed top-level response", async () => {
    mockGet.mockResolvedValue({ data: [] });
    const { getRangeEvent } = await import("./ranges");
    await expect(getRangeEvent("event-1")).rejects.toThrow("Invalid range response");
  });

  it("getRangeEvent throws a descriptive error when the required id field is missing", async () => {
    mockGet.mockResolvedValue({ data: { location: "מטווח" } });
    const { getRangeEvent } = await import("./ranges");
    await expect(getRangeEvent("event-1")).rejects.toThrow("Invalid range response");
  });

  it("getRangeCandidates normalizes malformed candidates/excluded fields individually", async () => {
    mockGet.mockResolvedValue({ data: { candidates: "bad", excluded: null } });
    const { getRangeCandidates } = await import("./ranges");
    const result = await getRangeCandidates("event-1");
    expect(result).toEqual({ candidates: [], excluded: [] });
  });

  it("getRangeCandidates defaults to empty arrays for a completely malformed top-level response", async () => {
    mockGet.mockResolvedValue({ data: "not-an-object" });
    const { getRangeCandidates } = await import("./ranges");
    const result = await getRangeCandidates("event-1");
    expect(result).toEqual({ candidates: [], excluded: [] });
  });

  it("getRangeExcusalRequests normalizes a malformed (non-array) response to an empty list", async () => {
    mockGet.mockResolvedValue({ data: { not: "an array" } });
    const { getRangeExcusalRequests } = await import("./ranges");
    const result = await getRangeExcusalRequests("event-1");
    expect(result).toEqual([]);
  });
});
