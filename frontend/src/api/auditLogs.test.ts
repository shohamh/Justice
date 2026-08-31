import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { listAuditLogs } from "./auditLogs";

vi.mock("./client");

describe("listAuditLogs", () => {
  it("normalizes a malformed response to an empty list", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected" } });

    await expect(listAuditLogs("soldier_exemption", "ent-1")).resolves.toEqual([]);
  });

  it("passes through a well-formed list", async () => {
    const entries = [
      {
        id: "log-1",
        action: "grant",
        actor_id: null,
        actor_name: null,
        entity_type: "soldier_exemption",
        entity_id: "ent-1",
        before: null,
        after: null,
        context: null,
        created_at: "2026-08-30T00:00:00Z",
      },
    ];
    vi.mocked(api.get).mockResolvedValue({ data: entries });

    await expect(listAuditLogs("soldier_exemption", "ent-1")).resolves.toEqual(entries);
  });
});
