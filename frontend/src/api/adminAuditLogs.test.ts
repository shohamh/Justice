import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listAdminAuditLogs } from "./adminAuditLogs";

vi.mock("./client");

const filters = { limit: 50, offset: 0 };

describe("listAdminAuditLogs", () => {
  it("rejects a malformed page response", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: "not-an-object" });

    await expect(listAdminAuditLogs(filters)).rejects.toThrow("Invalid admin audit log response");
  });

  it("normalizes malformed items and facets fields to empty arrays", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: { items: "not-an-array", total: 0, facets: "not-an-object" },
    });

    const result = await listAdminAuditLogs(filters);

    expect(result.items).toEqual([]);
    expect(result.facets).toEqual({ actions: [], entity_types: [], actors: [] });
  });

  it("normalizes malformed nested facet arrays to empty arrays", async () => {
    vi.mocked(api.get).mockResolvedValue({
      data: {
        items: [],
        total: 0,
        facets: { actions: "not-an-array", entity_types: null, actors: 42 },
      },
    });

    const result = await listAdminAuditLogs(filters);

    expect(result.facets).toEqual({ actions: [], entity_types: [], actors: [] });
  });
});
