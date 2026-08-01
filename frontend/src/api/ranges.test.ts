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

  it("autoAssignRange calls POST /ranges/event-1/auto-assign", async () => {
    const created = [{ id: "a1", is_draft: true }];
    mockPost.mockResolvedValue({ data: { created, shortfall: 1 } });
    const { autoAssignRange } = await import("./ranges");
    const result = await autoAssignRange("event-1");
    expect(mockPost).toHaveBeenCalledWith("/ranges/event-1/auto-assign");
    expect(result).toEqual({ created, shortfall: 1 });
  });

  it("confirmDraftAssignment calls POST /ranges/event-1/assignments/a1/confirm", async () => {
    const assignment = { id: "a1", is_draft: false };
    mockPost.mockResolvedValue({ data: assignment });
    const { confirmDraftAssignment } = await import("./ranges");
    const result = await confirmDraftAssignment("event-1", "a1");
    expect(mockPost).toHaveBeenCalledWith("/ranges/event-1/assignments/a1/confirm");
    expect(result).toEqual(assignment);
  });

  it("confirmAllDrafts calls POST /ranges/event-1/assignments/confirm-all", async () => {
    const assignments = [{ id: "a1", is_draft: false }, { id: "a2", is_draft: false }];
    mockPost.mockResolvedValue({ data: assignments });
    const { confirmAllDrafts } = await import("./ranges");
    const result = await confirmAllDrafts("event-1");
    expect(mockPost).toHaveBeenCalledWith("/ranges/event-1/assignments/confirm-all");
    expect(result).toEqual(assignments);
  });
});
