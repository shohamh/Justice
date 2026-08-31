import { describe, expect, it, vi } from "vitest";
import { api } from "./client";
import { getSoldierDutyHistory } from "./dutyHistory";

vi.mock("./client");

describe("getSoldierDutyHistory", () => {
  it("rejects a malformed response", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { detail: "unexpected" } });

    await expect(getSoldierDutyHistory("soldier-1")).rejects.toThrow(
      "Invalid duty history response",
    );
  });

  it("passes through a well-formed timeline", async () => {
    const events = [
      {
        id: "event-1",
        event_type: "assignment" as const,
        date: "2026-08-30",
        end_date: null,
        title: "Assigned",
        description: null,
        status: null,
        metadata: {},
        created_at: "2026-08-30T00:00:00Z",
      },
    ];
    vi.mocked(api.get).mockResolvedValue({ data: events });

    await expect(getSoldierDutyHistory("soldier-1")).resolves.toEqual(events);
  });
});
